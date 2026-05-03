import quotes

import discord
from discord import app_commands
import os
import asyncio
import yt_dlp
from dotenv import load_dotenv
import urllib.parse, re
import ipaddress
import base64
import secrets
import tempfile
import time
import json
import logging
import shutil
import sys
import importlib.util
from dataclasses import dataclass
from typing import Optional

# Setup logging (default to INFO level; can be toggled to DEBUG via /togglelog)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SAFE_MEDIA_EXTENSIONS = {
    ".aac", ".flac", ".m4a", ".mka", ".mkv", ".mp3", ".mp4", ".ogg",
    ".opus", ".wav", ".webm",
}

# Ensure songs directory exists and load downloaded songs metadata
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
songs_dir = BASE_DIR
os.makedirs(songs_dir, exist_ok=True)
downloads_file = os.path.join(songs_dir, "downloads.json")
PLAYLISTS_DIR = os.path.join(BASE_DIR, "playlists")
PLAYLIST_BLACKBOX_FILE = os.path.join(BASE_DIR, "playlists-blackbox.json")
PLAYLIST_PAGE_SIZE = 6
PLAYLIST_TRACK_PAGE_SIZE = 8
PLAYLIST_PAGE_REACTIONS = ("◀️", "▶️")
PLAYLIST_DELETE_GRACE_SECONDS = 600
HELP_EXPAND_REACTION = "📖"
PLAYLIST_PREDOWNLOAD_ENABLED = (
    os.getenv("PLAYLIST_PREDOWNLOAD_ENABLED", "").strip().lower()
    in {"1", "true", "yes", "on"}
)

def is_safe_download_path(file_path: str, video_id: Optional[str] = None) -> bool:
    """Only allow deletion of yt-dlp media files created in this checkout."""
    if not file_path:
        return False
    try:
        real_base = os.path.realpath(songs_dir)
        real_path = os.path.realpath(file_path)
        if os.path.commonpath([real_base, real_path]) != real_base:
            return False
        if not os.path.isfile(real_path):
            return False
        filename = os.path.basename(real_path)
        stem, ext = os.path.splitext(filename)
        if ext.lower() not in SAFE_MEDIA_EXTENSIONS:
            return False
        if not filename.startswith("youtube-"):
            return False
        if video_id and f"-{video_id}-" not in f"-{stem}-":
            return False
        return True
    except (OSError, ValueError):
        return False

def remove_download_file(file_path: str, *, video_id: Optional[str] = None, reason: str = "") -> bool:
    """Remove a tracked media file only after path validation."""
    if not file_path:
        return False
    if not is_safe_download_path(file_path, video_id):
        logger.warning(
            f"Skipped unsafe download deletion path for {video_id or 'unknown'} "
            f"during {reason or 'cleanup'}: {file_path}"
        )
        return False
    try:
        os.remove(file_path)
        logger.info(f"Removed downloaded media file during {reason or 'cleanup'}: {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error removing downloaded media file {file_path}: {e}")
        return False

def save_downloads_metadata(context: str):
    try:
        with open(downloads_file, 'w') as f:
            json.dump(downloaded, f)
    except Exception as e:
        logger.error(f"Failed to save downloads metadata after {context}: {e}")

def write_json_atomic(path: str, payload: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

downloaded = {}
if os.path.isfile(downloads_file):
    try:
        with open(downloads_file, 'r') as f:
            downloaded = json.load(f)
    except Exception as e:
        logger.error(f"Could not load downloads file: {e}")
        downloaded = {}

# Remove tracks older than 1 hour (3600 seconds) from disk on startup
current_time = time.time()
expired_ids = []
for vid, info in list(downloaded.items()):
    if current_time - info.get('timestamp', 0) > 3600:
        file_path = info.get('filepath')
        remove_download_file(file_path, video_id=vid, reason="startup expiry")
        expired_ids.append(vid)
for vid in expired_ids:
    downloaded.pop(vid, None)
# Save updated downloads info after cleanup
save_downloads_metadata("startup cleanup")
CLEANED_DOWNLOADS = len(expired_ids)

# Setup YouTube-DL (yt_dlp) options
ytdl_options = {
    'format': 'bestaudio[protocol^=http]/bestaudio/best[protocol^=http]/best',
    'outtmpl': os.path.join(songs_dir, '%(extractor)s-%(id)s-%(title)s.%(ext)s'),
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'check_formats': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': False,
    'default_search': 'ytsearch1',
    'source_address': '0.0.0.0',  # bind to IPv4
    'ignoreerrors': False,
    'verbose': False,
    'logger': logger
}
YTDLP_JS_RUNTIMES = {'deno': {}}
node_path = shutil.which("node")
if node_path:
    YTDLP_JS_RUNTIMES['node'] = {'path': node_path}
ytdl_options['js_runtimes'] = YTDLP_JS_RUNTIMES
YTDLP_COOKIEFILE = os.getenv("YTDLP_COOKIEFILE") or os.getenv("ytdlp_cookiefile")
if YTDLP_COOKIEFILE:
    if not os.path.isabs(YTDLP_COOKIEFILE):
        YTDLP_COOKIEFILE = os.path.join(BASE_DIR, YTDLP_COOKIEFILE)
    ytdl_options['cookiefile'] = YTDLP_COOKIEFILE
ytdl = yt_dlp.YoutubeDL(ytdl_options)

# Setup ffmpeg options for Discord audio
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

def get_env_value(*names, default=None, required=True):
    """Return the first populated environment variable from the provided names."""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    if default is not None:
        return default
    if required:
        raise RuntimeError(f"Missing required environment variable. Provide one of: {', '.join(names)}")
    return None

def coerce_int(value, label):
    """Convert environment values that should be integers and raise a helpful error."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise RuntimeError(f"{label} must be a numeric Discord snowflake.") from None

# Initialize constants and global state
queue = []  # list of track dicts for upcoming songs
youtube_base_url = 'https://www.youtube.com/'
youtube_base_url_2 = 'https://youtu.be/'
youtube_watch_url = youtube_base_url + 'watch?v='
QUEUE_REACTION = "📜"
CONTROL_REACTIONS = ("◀️", "⏸️", "▶️", QUEUE_REACTION)
DISCORD_MESSAGE_SAFE_LIMIT = 1900
MAX_QUEUE_LENGTH = 50
MIN_FREE_DOWNLOAD_MB = 512

BOT_TOKEN = get_env_value("BOT_TOKEN", "bot_token")
MY_GUILD_ID = coerce_int(get_env_value("MY_GUILD", "my_guild"), "MY_GUILD")
MY_GUILD = discord.Object(id=MY_GUILD_ID)
QUOTES_ID = coerce_int(get_env_value("QUOTES_ID", "quotes_id", default="0", required=False), "QUOTES_ID")

# Admin configuration (role and specific user allowed commands like reboot etc. + extra info privileges ;))
ADMIN_ROLE_ID   = get_env_value("ADMIN_ROLE_ID", "admin_role_id", required=False)
ADMIN_ROLE_ID   = coerce_int(ADMIN_ROLE_ID, "ADMIN_ROLE_ID") if ADMIN_ROLE_ID else None
ADMIN_ROLE_NAME = get_env_value("ADMIN_ROLE_NAME", "admin_role_name", default="Bottiadmin", required=False)
ADMIN_USER_ID   = get_env_value("ADMIN_USER_ID", "admin_user_id", required=False)
ADMIN_USER_ID   = coerce_int(ADMIN_USER_ID, "ADMIN_USER_ID") if ADMIN_USER_ID else None
ADMIN_USERNAME  = get_env_value("ADMIN_USERNAME", "admin_username", required=False)

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{27,}$")
MIN_DISCORD_PY_VERSION = (2, 6, 0)
MIN_YTDLP_VERSION = (2026, 3, 17)

def parse_youtube_video_id(query: str):
    """Return a YouTube video id from common URL shapes, or None for search text."""
    try:
        parsed = urllib.parse.urlparse(query)
    except Exception:
        return None
    netloc = parsed.netloc.lower()
    host = (parsed.hostname or netloc).lower().rstrip(".")
    if host == "youtu.be":
        return parsed.path.lstrip("/") or None
    if host != "youtube.com" and not host.endswith(".youtube.com"):
        return None
    qs = urllib.parse.parse_qs(parsed.query)
    if qs.get("v"):
        return qs["v"][0]
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[0] in {"embed", "shorts", "watch"} and len(path_parts) > 1:
        return path_parts[-1]
    return None

def normalize_youtube_query(query: str):
    """Normalize YouTube URLs for caching; leave search text for yt-dlp's ytsearch1."""
    query = validate_media_query(query)
    video_id = parse_youtube_video_id(query)
    if video_id:
        return youtube_watch_url + video_id, video_id
    return query, None

def youtube_url_for_track(track: dict) -> str:
    return track.get('webpage_url') or youtube_watch_url + str(track.get('id') or '')

def is_youtube_host(hostname: str) -> bool:
    host = hostname.lower().rstrip(".")
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")

def is_private_or_local_host(hostname: str) -> bool:
    host = hostname.strip("[]").lower().rstrip(".")
    if host in {"localhost", "ip6-localhost", "ip6-loopback"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )

def validate_media_query(query: str) -> str:
    """Allow YouTube URLs and search text, but reject arbitrary user-controlled URLs."""
    query = str(query or "").strip()
    if not query:
        raise ValueError("Provide a YouTube URL or search term.")
    try:
        parsed = urllib.parse.urlparse(query)
    except Exception:
        return query

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname or ""
    if parsed.netloc or scheme in {"http", "https", "file", "ftp", "ftps"}:
        if scheme and scheme not in {"http", "https"}:
            raise ValueError("Only YouTube URLs or search terms are supported.")
        if not hostname:
            raise ValueError("Only YouTube URLs or search terms are supported.")
        if is_private_or_local_host(hostname):
            logger.warning(f"Rejected private/local media URL host from user input: {hostname}")
            raise ValueError("Local or private network URLs are not allowed.")
        if not is_youtube_host(hostname):
            logger.warning(f"Rejected non-YouTube media URL host from user input: {hostname}")
            raise ValueError("Only YouTube URLs or search terms are supported.")
    elif scheme and re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", query) and not re.match(r"^[^:]{1,30}:\s", query):
        logger.warning(f"Rejected non-HTTP media URL scheme from user input: {scheme}")
        raise ValueError("Only YouTube URLs or search terms are supported.")
    return query

def parse_version(version: str) -> tuple:
    """Parse a package version into numeric parts for simple minimum checks."""
    parts = [int(part) for part in re.findall(r"\d+", version)[:3]]
    return tuple(parts + [0] * (3 - len(parts)))

@dataclass
class StartupReport:
    errors: list
    warnings: list
    notes: list

    def format_lines(self):
        lines = []
        if self.errors:
            lines.append("Startup blockers:")
            lines.extend(f"  ✖ {msg}" for msg in self.errors)
        if self.warnings:
            lines.append("Startup warnings:")
            lines.extend(f"  ⚠ {msg}" for msg in self.warnings)
        if self.notes:
            lines.append("Startup notes:")
            lines.extend(f"  • {msg}" for msg in self.notes)
        return lines or ["Startup diagnostics: no issues detected."]

    def has_blockers(self):
        return bool(self.errors)

@dataclass
class SuggestionRecord:
    timestamp: float
    user_name: str
    user_id: int
    command: str
    raw_value: str
    title: str = ""
    video_id: str = ""
    url: str = ""

@dataclass
class CommandRecord:
    timestamp: float
    user_name: str
    user_id: int
    command: str

def run_startup_diagnostics() -> StartupReport:
    report = StartupReport(errors=[], warnings=[], notes=[])
    discord_version = getattr(discord, "__version__", "0")
    if parse_version(discord_version) < MIN_DISCORD_PY_VERSION:
        report.errors.append(
            "discord.py "
            f"{discord_version} has a known Discord voice websocket 4006 bug. "
            "Run `pip install --upgrade -r requirements.txt` in the venv."
        )
    else:
        report.notes.append(f"discord.py {discord_version} available.")

    ytdlp_version = getattr(getattr(yt_dlp, "version", None), "__version__", "0")
    if parse_version(ytdlp_version) < MIN_YTDLP_VERSION:
        report.errors.append(
            "yt-dlp "
            f"{ytdlp_version} is too old for reliable YouTube playback. "
            "Run `pip install --upgrade -r requirements.txt` in the venv."
        )
    else:
        report.notes.append(f"yt-dlp {ytdlp_version} available.")

    if importlib.util.find_spec("yt_dlp_ejs") is None:
        report.errors.append(
            "yt-dlp-ejs is missing. Run `pip install --upgrade -r requirements.txt` "
            "to install YouTube JavaScript challenge support."
        )
    else:
        report.notes.append("yt-dlp-ejs available.")

    js_runtime = shutil.which("deno") or shutil.which("node")
    if js_runtime:
        report.notes.append(f"YouTube JS runtime located at {js_runtime}.")
    else:
        report.warnings.append(
            "No deno or node executable found in PATH. YouTube extraction may miss formats."
        )

    if importlib.util.find_spec("davey") is None:
        report.errors.append(
            "davey is missing. Run `pip install --upgrade -r requirements.txt` "
            "to install the Discord voice encryption dependency."
        )

    if ADMIN_USERNAME:
        report.warnings.append(
            "ADMIN_USERNAME is configured but ignored for security. Use ADMIN_USER_ID, ADMIN_ROLE_ID, or ADMIN_ROLE_NAME."
        )

    env_file = os.path.join(BASE_DIR, ".env")
    if not os.path.isfile(env_file):
        report.warnings.append(".env not found. Defaults or environment overrides will be used.")
    else:
        report.notes.append(".env loaded successfully.")

    if not TOKEN_PATTERN.match(BOT_TOKEN):
        report.warnings.append("BOT_TOKEN format looks unusual. Verify it was copied after the last reset.")

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        report.warnings.append("ffmpeg executable not found in PATH. Audio playback will fail until it is installed.")
    else:
        report.notes.append(f"ffmpeg located at {ffmpeg_path}.")

    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        with open(downloads_file, "a"):
            pass
    except OSError as exc:
        report.errors.append(f"Cannot write downloads cache at {downloads_file}: {exc}")

    try:
        os.makedirs(PLAYLISTS_DIR, exist_ok=True)
        test_path = os.path.join(PLAYLISTS_DIR, f".write-test-{os.getpid()}")
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
        report.notes.append("Playlist storage available.")
    except OSError as exc:
        report.errors.append(f"Cannot write playlist storage at {PLAYLISTS_DIR}: {exc}")

    if QUOTES_ID == 0:
        report.notes.append("Quotes channel disabled with QUOTES_ID=0.")
    else:
        try:
            if hasattr(quotes, "_ensure_quotes_file"):
                quotes._ensure_quotes_file()
            if quotes.QUOTES_FILE.exists():
                if quotes.QUOTES_FILE.stat().st_size == 0:
                    report.warnings.append("quotes.txt is empty. Run /backup_teekkari_quotes to seed it.")
                else:
                    report.notes.append("quotes.txt available.")
        except Exception as exc:
            report.errors.append(f"Cannot access quotes.txt: {exc}")

    try:
        usage = shutil.disk_usage(BASE_DIR)
        free_mb = usage.free // (1024 * 1024)
        if free_mb < 200:
            report.warnings.append(f"Only {free_mb} MB free on disk; downloads may fail.")
        else:
            report.notes.append(f"Disk free: {free_mb} MB.")
    except Exception as exc:
        report.warnings.append(f"Disk usage check failed: {exc}")

    if CLEANED_DOWNLOADS:
        report.notes.append(f"Pruned {CLEANED_DOWNLOADS} expired download(s) on startup.")

    return report

def is_user_admin(user) -> bool:
    """Check if the given user has admin privileges (role or specific user)."""
    if user is None:
        return False
    # 1) role-based check
    for role in getattr(user, "roles", []):
        if ADMIN_ROLE_ID and getattr(role, "id", None) == ADMIN_ROLE_ID:
            return True
        if role.name == ADMIN_ROLE_NAME:
            return True
    # 2) optional user-based check (only if you set ADMIN_USER_ID)
    user_id = getattr(user, "id", None)
    if ADMIN_USER_ID and user_id == ADMIN_USER_ID:
        return True
    return False

def user_in_bot_voice_channel(user) -> bool:
    bot_channel = getattr(client.current_voice_channel, "channel", None)
    user_channel = getattr(getattr(user, "voice", None), "channel", None)
    return bool(
        bot_channel
        and user_channel
        and getattr(bot_channel, "id", None) == getattr(user_channel, "id", None)
    )

def can_control_voice(user) -> bool:
    if is_user_admin(user):
        return True
    if client.current_voice_channel is None:
        return True
    return user_in_bot_voice_channel(user)

def user_id_value(user) -> int:
    return int(getattr(user, "id", 0) or 0)

async def require_voice_control(ctx, action: str = "control playback") -> bool:
    if can_control_voice(ctx.user):
        return True
    logger.warning(
        f"Denied /{command_name(ctx)} by {user_display(ctx.user)} "
        f"({getattr(ctx.user, 'id', 0)}): user is not in the bot voice channel."
    )
    await safe_interaction_send(
        ctx,
        f"You must be in the bot's voice channel to {action}.",
        ephemeral=True,
    )
    return False

async def require_queue_room(ctx) -> bool:
    if is_user_admin(ctx.user) or len(queue) < MAX_QUEUE_LENGTH:
        return True
    logger.warning(
        f"Denied /{command_name(ctx)} by {user_display(ctx.user)} "
        f"({getattr(ctx.user, 'id', 0)}): queue length limit {MAX_QUEUE_LENGTH} reached."
    )
    await safe_interaction_send(
        ctx,
        f"Queue limit reached ({MAX_QUEUE_LENGTH} songs). Ask an admin to clear the queue.",
        ephemeral=True,
    )
    return False

class YTDLSource(discord.PCMVolumeTransformer):
    """
    Class for creating an audio source from YouTube using yt_dlp and ffmpeg.
    """
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        """Gets an audio source from a YouTube URL (or search query)."""
        url, _ = normalize_youtube_query(url)
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if data is None:
            return None, url
        if 'entries' in data:
            data = next((entry for entry in data['entries'] if entry), None)
        if data is None:
            return None, url
        # If stream=True, use the direct URL; otherwise use downloaded filename
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data, volume=client.volume), data.get('webpage_url', url)

class Client(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        # Voice and playback state
        self.current_voice_channel = None      # discord.VoiceClient when connected
        self.currently_playing = False
        self.volume = 0.5
        self.current_track_id = None
        self.current_track_info = None         # current track's info (dict)
        self.last_track_info = None            # last played track's info (dict)
        self.current_track_message = None      # discord.Message for the "Now Playing" announcement
        self.current_track_message_show_queue = False
        # Admin-controllable flags
        self.download_mode = True              # True = download-and-play, False = stream-only
        self.log_verbose = False               # True = DEBUG logging on
        self.queue_links_disabled = False
        # Queue and history tracking
        self.song_history = []                # list of all tracks requested in current session
        self.queue_backup = None              # backup of last cleared queue (for restore)
        self.backup_timestamp = None          # timestamp for queue backup
        self.suggestion_history = []
        self.recent_commands = []
        self.playlist_pager_message_id = None
        self.playlist_pager = None
        self.help_message_id = None
        self.help_expanded = False
        self.playlist_delete_tasks = {}
        # File deletion task tracking
        self.deletion_tasks = {}              # map video_id -> asyncio.Future
        # Played tracks tracking
        self.played_tracks = set()           # set of video IDs that have been played (for history status)

    async def setup_hook(self):
        # Sync application commands to the specified guild
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)

# Intents setup (enable message content for slash commands to work properly)
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
client = Client(intents=intents)
startup_report = run_startup_diagnostics()
client.startup_report = startup_report
for line in startup_report.format_lines():
    logger.info(line)
if startup_report.has_blockers():
    raise SystemExit("Startup aborted due to blocking configuration errors.")

def build_runtime_status():
    mode = "download" if client.download_mode else "stream"
    current = client.current_track_info.get('title', 'Unknown title') if client.current_track_info else "Idle"
    lines = [
        "**runtime**",
        f"- mode: `{mode}`",
        f"- queue length: `{len(queue)}`",
        f"- song history entries: `{len(client.song_history)}`",
        f"- currently playing: **{discord.utils.escape_markdown(str(current))}**",
        f"- log level: `{logging.getLevelName(logger.level)}`",
        f"- queue links: `{'disabled' if client.queue_links_disabled else 'enabled'}`",
    ]
    latest_suggestion = format_suggestion_record(client.suggestion_history[-1]) if client.suggestion_history else None
    lines.append("")
    lines.append("**latest suggestion**")
    lines.append(latest_suggestion or "- none this session")
    diag = getattr(client, "startup_report", None)
    if diag and diag.warnings:
        lines.append("")
        lines.append("**outstanding warnings**")
        lines.extend(f"- {warn}" for warn in diag.warnings)
    return "\n".join(lines)

async def safe_interaction_send(ctx, message: str, *, ephemeral: bool = False):
    """Send an interaction response without letting expired tokens mask root errors."""
    try:
        if ctx.response.is_done():
            return await ctx.followup.send(message, ephemeral=ephemeral)
        return await ctx.response.send_message(message, ephemeral=ephemeral)
    except (discord.NotFound, discord.HTTPException) as exc:
        command_name = getattr(getattr(ctx, "command", None), "name", "unknown")
        logger.warning(f"Could not respond to /{command_name}: {exc}")
        return None

def user_display(user) -> str:
    return str(getattr(user, "display_name", None) or getattr(user, "name", None) or user)

def command_name(ctx, fallback="unknown") -> str:
    return getattr(getattr(ctx, "command", None), "name", fallback)

def format_timestamp(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

def truncate_text(value, max_chars: int = 180) -> str:
    text = re.sub(r"[\r\n\t]+", " ", str(value))
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."

def record_command(ctx):
    record = CommandRecord(
        timestamp=time.time(),
        user_name=user_display(ctx.user),
        user_id=getattr(ctx.user, "id", 0),
        command=command_name(ctx),
    )
    client.recent_commands.append(record)
    client.recent_commands = client.recent_commands[-5:]
    logger.info(f"Command invoked: /{record.command} by {record.user_name} ({record.user_id})")
    return record

def record_suggestion(ctx, command: str, raw_value, track=None):
    raw_text = truncate_text(raw_value, 240)
    record = SuggestionRecord(
        timestamp=time.time(),
        user_name=user_display(ctx.user),
        user_id=getattr(ctx.user, "id", 0),
        command=command,
        raw_value=raw_text,
        title=truncate_text(track.get('title', ''), 180) if track else "",
        video_id=str(track.get('id', '')) if track else "",
        url=truncate_text(track.get('webpage_url', ''), 300) if track else "",
    )
    client.suggestion_history.append(record)
    logger.info(
        f"Music suggestion: user={record.user_name} ({record.user_id}) "
        f"command=/{record.command} raw={record.raw_value!r} "
        f"title={record.title or '-'} id={record.video_id or '-'}"
    )
    return record

def update_suggestion(record: SuggestionRecord, track):
    record.title = truncate_text(track.get('title', ''), 180)
    record.video_id = str(track.get('id', ''))
    record.url = truncate_text(track.get('webpage_url', ''), 300)
    logger.info(
        f"Music suggestion resolved: user={record.user_name} ({record.user_id}) "
        f"command=/{record.command} title={record.title or '-'} id={record.video_id or '-'}"
    )
    return record

def format_suggestion_record(record: SuggestionRecord, *, include_url=True) -> str:
    title = discord.utils.escape_markdown(record.title or "unresolved")
    raw_value = discord.utils.escape_markdown(record.raw_value)
    lines = [
        f"- time: `{format_timestamp(record.timestamp)}`",
        f"- user: **{discord.utils.escape_markdown(record.user_name)}** (`{record.user_id}`)",
        f"- command: `/{record.command}`",
    ]
    if record.title:
        video = f" (`{record.video_id}`)" if record.video_id else ""
        lines.append(f"- song: **{title}**{video}")
    else:
        lines.append(f"- suggestion: `{raw_value}`")
    if include_url and record.url:
        lines.append(f"- url: {record.url}")
    return "\n".join(lines)

def format_command_record(record: CommandRecord) -> str:
    user_name = discord.utils.escape_markdown(record.user_name)
    return f"- `{format_timestamp(record.timestamp)}` /{record.command} by **{user_name}** (`{record.user_id}`)"

def build_status_message(view: str = "latest") -> str:
    view = (view or "latest").lower()
    if view == "session":
        lines = ["**music suggestion session history**"]
        if not client.suggestion_history:
            lines.append("- none this session")
        else:
            for index, record in enumerate(client.suggestion_history, start=1):
                block = [f"\n**{index}. /{record.command}**", format_suggestion_record(record)]
                candidate = "\n".join(lines + block)
                if len(candidate) > DISCORD_MESSAGE_SAFE_LIMIT:
                    remaining = len(client.suggestion_history) - index + 1
                    lines.append(f"\n_and {remaining} additional suggestion(s) are omitted from this status message._")
                    break
                lines.extend(block)
        return "\n".join(lines)
    if view == "commands":
        lines = ["**recent commands**"]
        if not client.recent_commands:
            lines.append("- none this session")
        else:
            lines.extend(format_command_record(record) for record in client.recent_commands[-5:])
        return "\n".join(lines)
    return build_runtime_status()

def generate_playlist_id() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(6)).decode("ascii").rstrip("=")

def normalize_playlist_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip())

def playlist_lookup_key(name: str) -> str:
    value = normalize_playlist_name(name)
    if value.lower().startswith("playlist:"):
        value = value.split(":", 1)[1].strip()
    return value.lower()

def safe_playlist_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", normalize_playlist_name(name).lower()).strip("-")
    return slug[:48] or "playlist"

def playlist_folder_path(playlist: dict) -> str:
    folder = playlist.get("folder")
    if folder:
        return os.path.join(PLAYLISTS_DIR, folder)
    return os.path.join(PLAYLISTS_DIR, f"{safe_playlist_slug(playlist.get('name', 'playlist'))}-{playlist['id']}")

def playlist_metadata_path(playlist: dict) -> str:
    return os.path.join(playlist_folder_path(playlist), "metadata.json")

def make_playlist_metadata(name: str, owner, visibility: str = "private") -> dict:
    playlist_id = generate_playlist_id()
    owner_id = user_id_value(owner)
    owner_name = user_display(owner)
    now = time.time()
    safe_name = normalize_playlist_name(name)
    return {
        "id": playlist_id,
        "name": safe_name,
        "generated_at": now,
        "locked": False,
        "visibility": visibility,
        "owner_user_id": owner_id,
        "owner_discord_name": owner_name,
        "manager_user_ids": [],
        "tracks": [],
        "folder": f"{safe_playlist_slug(safe_name)}-{playlist_id}",
        "predownloaded": False,
        "deleted": False,
    }

def load_playlists(*, include_deleted: bool = False, purge_expired: bool = True) -> list:
    playlists = []
    if not os.path.isdir(PLAYLISTS_DIR):
        return playlists
    if purge_expired:
        purge_expired_deleted_playlists()
    for root, _, files in os.walk(PLAYLISTS_DIR):
        if "metadata.json" not in files:
            continue
        path = os.path.join(root, "metadata.json")
        try:
            with open(path, "r") as f:
                playlist = json.load(f)
            playlist.setdefault("tracks", [])
            playlist.setdefault("manager_user_ids", [])
            playlist.setdefault("visibility", "private")
            playlist.setdefault("locked", False)
            playlist.setdefault("folder", os.path.basename(root))
            if playlist.get("deleted") and not include_deleted:
                continue
            playlists.append(playlist)
        except Exception as exc:
            logger.error(f"Failed to load playlist metadata {path}: {exc}")
    return playlists

def save_playlist(playlist: dict):
    write_json_atomic(playlist_metadata_path(playlist), playlist)

def playlist_video_links(playlist: dict) -> list:
    links = []
    for track in playlist.get("tracks", []):
        link = track.get("webpage_url") or youtube_watch_url + str(track.get("id") or "")
        if link and link not in links:
            links.append(link)
    return links

def append_playlist_blackbox_event(action: str, playlist: dict, actor=None):
    event = {
        "timestamp": time.time(),
        "action": action,
        "playlist_id": playlist.get("id"),
        "playlist_name": playlist.get("name"),
        "owner_user_id": playlist.get("owner_user_id"),
        "owner_discord_name": playlist.get("owner_discord_name"),
        "manager_user_ids": playlist.get("manager_user_ids", []),
        "youtube_links": playlist_video_links(playlist),
        "actor_user_id": user_id_value(actor) if actor else None,
        "actor_discord_name": user_display(actor) if actor else None,
    }
    try:
        if os.path.isfile(PLAYLIST_BLACKBOX_FILE):
            with open(PLAYLIST_BLACKBOX_FILE, "r") as f:
                events = json.load(f)
            if not isinstance(events, list):
                logger.error("Playlist blackbox file is not a JSON list; preserving it without appending.")
                return
        else:
            events = []
        events.append(event)
        write_json_atomic(PLAYLIST_BLACKBOX_FILE, events)
    except Exception as exc:
        logger.error(f"Failed to append playlist blackbox event: {exc}")

def parse_playlist_flags(flags: Optional[str]) -> set:
    return {
        token.strip().lower()
        for token in str(flags or "").split()
        if token.strip().startswith("-")
    }

def direct_playlist_editor(user, playlist: dict) -> bool:
    uid = user_id_value(user)
    if uid == playlist_owner_id(playlist):
        return True
    return not playlist.get("locked") and uid in playlist_manager_ids(playlist)

def admin_editing_foreign_playlist(user, playlist: dict) -> bool:
    return is_user_admin(user) and not direct_playlist_editor(user, playlist)

async def confirm_with_reactions(ctx, message: str, *, force: bool = False) -> bool:
    if force:
        return True
    try:
        if ctx.response.is_done():
            prompt_msg = await ctx.followup.send(message, wait=True)
        else:
            await ctx.response.send_message(message)
            prompt_msg = await ctx.original_response()
        await prompt_msg.add_reaction("👍")
        await prompt_msg.add_reaction("👎")
    except Exception as exc:
        logger.warning(f"Could not send confirmation prompt: {exc}")
        return False

    def check(reaction, user):
        return user == ctx.user and str(reaction.emoji) in ["👍", "👎"] and reaction.message.id == prompt_msg.id

    try:
        reaction, _ = await client.wait_for('reaction_add', timeout=30.0, check=check)
    except asyncio.TimeoutError:
        await safe_interaction_send(ctx, "No confirmation received. Cancelled.", ephemeral=True)
        return False
    return str(reaction.emoji) == "👍"

async def confirm_admin_foreign_playlist(ctx, playlist: dict, action: str, flags: set) -> bool:
    if not admin_editing_foreign_playlist(ctx.user, playlist):
        return True
    if "-force" in flags:
        return True
    owner = discord.utils.escape_markdown(str(playlist.get("owner_discord_name", "unknown")))
    name = discord.utils.escape_markdown(str(playlist.get("name", "playlist")))
    return await confirm_with_reactions(
        ctx,
        f"**{name}** belongs to **{owner}**. Confirm admin {action}?",
    )

def deleted_playlists_for(user) -> list:
    purge_expired_deleted_playlists()
    playlists = []
    for playlist in load_playlists(include_deleted=True):
        if not playlist.get("deleted"):
            continue
        if is_user_admin(user) or user_id_value(user) == playlist_owner_id(playlist):
            playlists.append(playlist)
    return sorted(playlists, key=lambda item: item.get("delete_after", 0))

def safe_remove_playlist_folder(playlist: dict) -> bool:
    folder = playlist_folder_path(playlist)
    try:
        real_base = os.path.realpath(PLAYLISTS_DIR)
        real_folder = os.path.realpath(folder)
        if real_folder == real_base or os.path.commonpath([real_base, real_folder]) != real_base:
            logger.warning(f"Skipped unsafe playlist folder removal: {folder}")
            return False
        if os.path.isdir(real_folder):
            shutil.rmtree(real_folder)
        return True
    except Exception as exc:
        logger.error(f"Failed to remove playlist folder {folder}: {exc}")
        return False

def purge_expired_deleted_playlists():
    now = time.time()
    if not os.path.isdir(PLAYLISTS_DIR):
        return
    for playlist in load_playlists(include_deleted=True, purge_expired=False):
        if playlist.get("deleted") and playlist.get("delete_after", 0) <= now:
            if safe_remove_playlist_folder(playlist):
                logger.info(f"Purged expired deleted playlist: {playlist.get('name')} ({playlist.get('id')})")

async def schedule_playlist_purge(playlist_id: str, delete_after: float):
    await asyncio.sleep(max(0, delete_after - time.time()))
    playlist = resolve_playlist_reference(playlist_id, require_visible=False, include_deleted=True)
    if playlist and playlist.get("deleted") and playlist.get("delete_after", 0) <= time.time():
        safe_remove_playlist_folder(playlist)
    client.playlist_delete_tasks.pop(playlist_id, None)

def is_playlist_public(playlist: dict) -> bool:
    return playlist.get("visibility") == "public"

def playlist_owner_id(playlist: dict) -> int:
    return int(playlist.get("owner_user_id") or 0)

def playlist_manager_ids(playlist: dict) -> set:
    return {int(user_id) for user_id in playlist.get("manager_user_ids", []) if str(user_id).isdigit()}

def can_view_playlist(user, playlist: dict) -> bool:
    uid = user_id_value(user)
    return (
        is_playlist_public(playlist)
        or is_user_admin(user)
        or uid == playlist_owner_id(playlist)
        or uid in playlist_manager_ids(playlist)
    )

def can_edit_playlist(user, playlist: dict) -> bool:
    uid = user_id_value(user)
    if is_user_admin(user):
        return True
    if uid == playlist_owner_id(playlist):
        return True
    if playlist.get("locked"):
        return False
    return uid in playlist_manager_ids(playlist)

def can_manage_playlist(user, playlist: dict) -> bool:
    return is_user_admin(user) or user_id_value(user) == playlist_owner_id(playlist)

def visible_playlists_for(user) -> list:
    uid = user_id_value(user)
    playlists = [playlist for playlist in load_playlists() if can_view_playlist(user, playlist)]
    return sorted(
        playlists,
        key=lambda playlist: (
            0 if playlist_owner_id(playlist) == uid else 1,
            playlist.get("name", "").lower(),
        ),
    )

def resolve_playlist_reference(reference: str, user=None, *, require_visible: bool = True, include_deleted: bool = False):
    lookup = playlist_lookup_key(reference)
    if not lookup:
        return None
    candidates = []
    for playlist in load_playlists(include_deleted=include_deleted):
        names = {playlist.get("id", "").lower(), playlist.get("name", "").lower()}
        if lookup in names:
            if require_visible and user is not None and not can_view_playlist(user, playlist):
                continue
            candidates.append(playlist)
    if not candidates:
        return None
    uid = user_id_value(user)
    candidates.sort(
        key=lambda playlist: (
            0 if playlist_owner_id(playlist) == uid else 1,
            0 if uid in playlist_manager_ids(playlist) else 1,
            0 if is_playlist_public(playlist) else 1,
            playlist.get("name", "").lower(),
        )
    )
    return candidates[0]

def is_playlist_reference(value: str, user=None) -> bool:
    text = str(value or "").strip()
    return text.lower().startswith("playlist:") or resolve_playlist_reference(text, user) is not None

def playlist_track_from_track(track: dict, user) -> dict:
    return {
        "title": str(track.get("title") or "Unknown title"),
        "id": str(track.get("id") or ""),
        "webpage_url": track.get("webpage_url") or youtube_watch_url + str(track.get("id") or ""),
        "added_by_user_id": user_id_value(user),
        "added_by_discord_name": user_display(user),
        "added_at": time.time(),
    }

def playlist_to_queue_tracks(playlist: dict, *, block_id: Optional[str] = None) -> list:
    tracks = playlist.get("tracks", [])
    block_id = block_id or generate_playlist_id()
    total = len(tracks)
    queue_tracks = []
    for index, track in enumerate(tracks, start=1):
        queue_track = {
            "id": str(track.get("id") or ""),
            "title": str(track.get("title") or "Unknown title"),
            "webpage_url": track.get("webpage_url") or youtube_watch_url + str(track.get("id") or ""),
            "playlist_id": playlist.get("id"),
            "playlist_name": playlist.get("name"),
            "playlist_block_id": block_id,
            "playlist_index": index,
            "playlist_total": total,
        }
        permanent_file = track.get("permanent_file")
        if permanent_file and is_safe_playlist_file_path(permanent_file, playlist, queue_track["id"]):
            queue_track["file"] = permanent_file
        queue_tracks.append(queue_track)
    return queue_tracks

def active_playlist_block_id() -> Optional[str]:
    current = client.current_track_info or {}
    return current.get("playlist_block_id")

def playlist_block_end_index(block_id: str) -> int:
    last_index = -1
    for index, track in enumerate(queue):
        if track.get("playlist_block_id") == block_id:
            last_index = index
    return last_index

def insert_after_active_playlist(track: dict):
    block_id = active_playlist_block_id()
    if not block_id:
        queue.append(track)
        return
    last_index = playlist_block_end_index(block_id)
    if last_index < 0:
        queue.append(track)
    else:
        queue.insert(last_index + 1, track)

def format_playlist_title(playlist: dict) -> str:
    name = discord.utils.escape_markdown(playlist.get("name", "unnamed"))
    visibility = playlist.get("visibility", "private")
    locked = " locked" if playlist.get("locked") else ""
    return f"**{name}** (`{playlist.get('id')}`) - {visibility}{locked}"

def chunk_lines(title: str, lines: list, page_size: int) -> list:
    if not lines:
        lines = ["_nothing to show._"]
    pages = []
    for offset in range(0, len(lines), page_size):
        page = lines[offset:offset + page_size]
        pages.append(f"{title}\n" + "\n".join(page))
    return pages

def playlist_list_pages_for(user) -> list:
    playlists = visible_playlists_for(user)
    uid = user_id_value(user)
    lines = []
    for playlist in playlists:
        relation = "owner" if playlist_owner_id(playlist) == uid else (
            "manager" if uid in playlist_manager_ids(playlist) else "public"
        )
        count = len(playlist.get("tracks", []))
        lines.append(f"- {format_playlist_title(playlist)} - {count} song(s), {relation}")
    return chunk_lines("**playlists**", lines, PLAYLIST_PAGE_SIZE)

def playlist_detail_pages(playlist: dict) -> list:
    lines = [
        f"- owner: **{discord.utils.escape_markdown(str(playlist.get('owner_discord_name', 'unknown')))}** (`{playlist_owner_id(playlist)}`)",
        f"- managers: `{len(playlist_manager_ids(playlist))}`",
        f"- visibility: `{playlist.get('visibility', 'private')}`",
        f"- locked: `{bool(playlist.get('locked'))}`",
        "",
        "**songs**",
    ]
    tracks = playlist.get("tracks", [])
    if tracks:
        for index, track in enumerate(tracks, start=1):
            title = discord.utils.escape_markdown(str(track.get("title") or "Unknown title"))
            lines.append(f"{index}. **{title}** (`{track.get('id', '')}`)")
    else:
        lines.append("_playlist is empty._")
    return chunk_lines(f"**playlist edit: {discord.utils.escape_markdown(playlist.get('name', 'unnamed'))}**", lines, PLAYLIST_TRACK_PAGE_SIZE)

def page_with_footer(pages: list, page_index: int) -> str:
    if not pages:
        return "_nothing to show._"
    page_index = max(0, min(page_index, len(pages) - 1))
    footer = f"\n\n_page {page_index + 1}/{len(pages)} - react ◀️/▶️ to move pages._"
    return pages[page_index] + footer

def is_safe_playlist_file_path(file_path: str, playlist: dict, video_id: Optional[str] = None) -> bool:
    try:
        real_folder = os.path.realpath(playlist_folder_path(playlist))
        real_path = os.path.realpath(file_path)
        return (
            os.path.commonpath([real_folder, real_path]) == real_folder
            and is_safe_download_path(file_path, video_id)
        )
    except (OSError, ValueError):
        return False

def track_display_parts(track: dict) -> tuple:
    title = discord.utils.escape_markdown(str(track.get('title') or 'Unknown title'))
    url = track.get('webpage_url') or youtube_watch_url + str(track.get('id') or '')
    url = discord.utils.escape_markdown(str(url))
    return title, url

def format_queue_section(*, max_chars=None, show_links=True) -> str:
    lines = ["📜 **Queue**"]
    if not queue:
        lines.append("_Queue is empty._")
        return "\n".join(lines)

    for index, track in enumerate(queue, start=1):
        title, url = track_display_parts(track)
        entry = [f"**{index}. {title}**"]
        if track.get("playlist_name"):
            entry.append(f"_playlist: {discord.utils.escape_markdown(str(track.get('playlist_name')))}_")
        if show_links and not client.queue_links_disabled:
            entry.append(f"*{url}*")
        remaining = len(queue) - index
        footer = f"_and {remaining} more queued song(s)._" if remaining else None
        candidate_lines = lines + entry + ([footer] if footer else [])
        if max_chars and len("\n".join(candidate_lines)) > max_chars:
            hidden_count = len(queue) - index + 1
            lines.append(f"_and {hidden_count} more queued song(s)._")
            break
        lines.extend(entry)
    return "\n".join(lines)

def format_now_playing(track: dict, *, show_queue: bool = False) -> str:
    title, url = track_display_parts(track)
    now_playing = f"🎵 Now playing: **{title}**\n*{url}*"
    if track.get("playlist_name"):
        playlist_name = discord.utils.escape_markdown(str(track.get("playlist_name")))
        now_playing += f"\n_from playlist: **{playlist_name}**_"
    if not show_queue:
        return now_playing
    divider = "━━━━━━━━━━━━"
    fixed_content = f"\n\n{divider}\n\n{now_playing}"
    queue_chars = DISCORD_MESSAGE_SAFE_LIMIT - len(fixed_content)
    return f"{format_queue_section(max_chars=queue_chars)}{fixed_content}"

async def has_newer_message(channel, message) -> bool:
    try:
        async for _ in channel.history(limit=1, after=message):
            return True
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warning(f"Could not inspect channel history before now-playing edit: {exc}")
        return True
    return False

async def remove_control_reactions(message):
    if message is None:
        return
    for emoji in CONTROL_REACTIONS:
        try:
            await message.clear_reaction(emoji)
            logger.info(f"Removed stale now-playing control reaction {emoji} from message {message.id}.")
        except (discord.Forbidden, discord.HTTPException):
            try:
                await message.remove_reaction(emoji, client.user)
                logger.info(f"Removed bot's stale now-playing control reaction {emoji} from message {message.id}.")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
                logger.warning(f"Failed to remove stale control reaction {emoji}: {exc}")

async def add_control_reactions(message):
    existing = {
        str(reaction.emoji)
        for reaction in getattr(message, "reactions", [])
        if getattr(reaction, "me", False)
    }
    for emoji in CONTROL_REACTIONS:
        if emoji in existing:
            continue
        try:
            await message.add_reaction(emoji)
            logger.info(f"Added now-playing control reaction {emoji} to message {message.id}.")
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.error(f"Failed to add now-playing control reaction {emoji}: {exc}")

async def publish_now_playing(channel, track: dict, *, send_message=None, acknowledge=None):
    """Edit the active now-playing message when it is still the latest message."""
    old_message = client.current_track_message
    same_channel = old_message and getattr(getattr(old_message, "channel", None), "id", None) == channel.id
    newer_message_exists = await has_newer_message(channel, old_message) if same_channel else None
    can_edit = same_channel and not newer_message_exists

    if can_edit:
        try:
            content = format_now_playing(track, show_queue=client.current_track_message_show_queue)
            await old_message.edit(content=content)
            await add_control_reactions(old_message)
            if acknowledge:
                await acknowledge("Now playing message updated.", ephemeral=True)
            client.current_track_message = old_message
            logger.info(
                f"Edited now-playing message {old_message.id} in channel {channel.id} "
                f"for {track.get('title', 'Unknown title')} ({track.get('id', '')})."
            )
            return old_message
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            logger.warning(f"Could not edit now-playing message; sending a new one: {exc}")

    if old_message:
        if not same_channel:
            reason = "previous now-playing message is in a different channel"
        elif newer_message_exists:
            reason = "a newer channel message exists"
        else:
            reason = "the previous message could not be edited"
        logger.info(
            f"Sending a new now-playing message because {reason}; "
            f"old message={old_message.id}, channel={channel.id}."
        )

    client.current_track_message_show_queue = False
    content = format_now_playing(track, show_queue=False)
    if send_message:
        new_message = await send_message(content, wait=True)
    else:
        new_message = await channel.send(content)
    client.current_track_message = new_message
    await add_control_reactions(new_message)
    if old_message and old_message.id != new_message.id:
        await remove_control_reactions(old_message)
    logger.info(
        f"Sent now-playing message {new_message.id} in channel {channel.id} "
        f"for {track.get('title', 'Unknown title')} ({track.get('id', '')})."
    )
    return new_message

async def toggle_now_playing_queue(message):
    if not client.current_track_info:
        logger.info("Queue reaction ignored because no track is currently tracked.")
        return
    client.current_track_message_show_queue = not client.current_track_message_show_queue
    try:
        await message.edit(
            content=format_now_playing(
                client.current_track_info,
                show_queue=client.current_track_message_show_queue,
            )
        )
        state = "shown" if client.current_track_message_show_queue else "hidden"
        logger.info(f"Queue section {state} on now-playing message {message.id}.")
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
        logger.warning(f"Failed to toggle queue section on now-playing message {message.id}: {exc}")

async def send_paged_playlist_message(ctx, pages: list):
    if ctx.response.is_done():
        message = await ctx.followup.send(page_with_footer(pages, 0), wait=True)
    else:
        await ctx.response.send_message(page_with_footer(pages, 0))
        message = await ctx.original_response()
    client.playlist_pager_message_id = message.id
    client.playlist_pager = {
        "pages": pages,
        "page": 0,
        "user_id": user_id_value(ctx.user),
    }
    for emoji in PLAYLIST_PAGE_REACTIONS:
        try:
            await message.add_reaction(emoji)
        except Exception as exc:
            logger.warning(f"Failed to add playlist pager reaction {emoji}: {exc}")
    return message

async def handle_playlist_pager_reaction(reaction, user) -> bool:
    pager = client.playlist_pager
    if not pager or reaction.message.id != client.playlist_pager_message_id:
        return False
    if user_id_value(user) != pager.get("user_id"):
        return True
    emoji = str(reaction.emoji)
    if emoji not in PLAYLIST_PAGE_REACTIONS:
        return False
    pages = pager.get("pages") or []
    if not pages:
        return True
    if emoji == "◀️":
        pager["page"] = max(0, pager.get("page", 0) - 1)
    elif emoji == "▶️":
        pager["page"] = min(len(pages) - 1, pager.get("page", 0) + 1)
    try:
        await reaction.message.edit(content=page_with_footer(pages, pager["page"]))
        await reaction.message.remove_reaction(reaction.emoji, user)
    except Exception as exc:
        logger.warning(f"Failed to update playlist pager: {exc}")
    return True

def compact_help_message() -> str:
    return "\n".join([
        "**music bot help**",
        "/play <youtube url or search> - play or queue music",
        "/enqueue <query> (alias /q) - add to queue",
        "/queue - show queue",
        "/playlist list - browse playlists",
        "/playlist new <name> - create a playlist",
        "/help - react 📖 for full help",
    ])

def expanded_help_message() -> str:
    return "\n".join([
        "**music playback**",
        "/join - Join your voice channel.",
        "/play <YouTube URL, search, or playlist:name> - Play now or queue.",
        "/playtop <query> - Play a song next.",
        "/enqueue <query or playlist:name> (alias: /q) - Add to queue.",
        "/queue [links] (alias: /queuelist) - Show upcoming songs.",
        "/queuefirst <position or playlist:name> (alias: /qfirst) - Move a song or playlist to play next.",
        "/skip, /pause, /resume, /stop, /volume <1-100> - Playback controls.",
        "/now (alias: /nytsoi), /getqueue - Current/session info.",
        "",
        "**playlists**",
        "/playlist list - Browse your playlists and visible public playlists.",
        "/playlist new <name> [visibility] - Create a playlist.",
        "/playlist edit <name> - Show editable playlist details.",
        "/playlist add <playlist> <current|queue> [queue_position] - Add current or queued song.",
        "/playlist addmod <playlist> <user> - Add manager (owner only).",
        "/playlist remove <playlist> [flags] - Remove a playlist with 600s rescue.",
        "/playlist removesong <playlist> <position> - Remove a song.",
        "/playlist move <playlist> <from> <to> - Reorder songs.",
        "/playlist lock <playlist> <locked> - Lock or unlock edits.",
        "",
        "**admin / other**",
        "/clear_queue, /restorequeue, /purgequeue, /togglelog, /toggledownload, /disablelinks, /reboot, /status",
        "/backup_teekkari_quotes, /random_quote",
    ])

def enough_disk_for_download() -> bool:
    try:
        usage = shutil.disk_usage(BASE_DIR)
        return usage.free >= MIN_FREE_DOWNLOAD_MB * 1024 * 1024
    except Exception as exc:
        logger.warning(f"Disk usage check failed before download: {exc}")
        return True

async def fetch_track(query: str, requested_by=None):
    """
    Fetches YouTube track info for the given query (URL or search term).
    If download_mode is True, downloads the audio (unless cached) and returns track info with file path.
    If download_mode is False, returns track info for streaming (no file path).
    Applies size and duration restrictions based on user permissions.
    """
    # Determine the full YouTube URL and video ID for URL inputs. Search text is
    # passed directly to yt-dlp so it can use its own maintained search extractor.
    video_url, video_id = normalize_youtube_query(query)

    # If we have a video_id and it's cached (and in download mode), use the cached file
    if video_id and video_id in downloaded and client.download_mode:
        info = downloaded[video_id]
        file_path = info.get('filepath')
        title = info.get('title', 'Unknown title')
        page_url = youtube_watch_url + video_id
        if file_path and is_safe_download_path(file_path, video_id):
            logger.debug(f"Using cached file for {video_id}: {title}")
            return {'id': video_id, 'title': title, 'webpage_url': page_url, 'file': file_path}
        else:
            # Cached metadata exists but file is missing; remove from cache
            downloaded.pop(video_id, None)
            logger.info(f"Cache entry for {video_id} removed (file not found)")

    # Not cached or not using cache: fetch metadata (and download if needed)
    try:
        logger.debug(f"Fetching track info for query: {query}")
        loop = asyncio.get_event_loop()
        # Always extract metadata without downloading first (to get info like duration and size)
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(video_url, download=False))
        if data is None:
            raise Exception("No data found for query")
        if 'entries' in data:
            data = next((entry for entry in data['entries'] if entry), None)
        if data is None:
            raise Exception("No playable result found for query")
        video_id = data.get('id')
        title = data.get('title', 'Unknown title')
        page_url = data.get('webpage_url', video_url)
        if not video_id:
            raise Exception("Resolved track is missing a YouTube video id.")
        duration = data.get('duration', 0) or 0  # duration in seconds
        filesize = data.get('filesize') or data.get('filesize_approx') or 0
        if filesize == 0:
            # Estimate filesize if not provided (approximate)
            abr = data.get('abr')  # average bitrate in kbps
            if abr and duration:
                filesize = int((abr * 1000 / 8) * duration)  # bytes

        # Define limits (in seconds for length, bytes for sizes)
        MAX_LENGTH_NORMAL = 3 * 60 * 60       # 3 hours
        MAX_LENGTH_ADMIN  = 5 * 60 * 60       # 5 hours
        MAX_FILESIZE_BYTES = 250 * 1024 * 1024        # ~250 MB
        TOTAL_LIMIT_NORMAL = 10 * 1024 * 1024 * 1024 // 8   # ~1.25 GB
        TOTAL_LIMIT_ADMIN  = 15 * 1024 * 1024 * 1024 // 8   # ~1.875 GB

        # Enforce duration limits
        if duration and duration > MAX_LENGTH_NORMAL and not is_user_admin(requested_by):
            raise Exception("Track duration exceeds 3 hours (non-admin limit).")
        if duration and duration > MAX_LENGTH_ADMIN:
            raise Exception("Track duration exceeds 5 hours (admin limit).")

        # Calculate total downloaded bytes currently on disk
        def total_downloaded_bytes():
            total = 0
            for vid, info in downloaded.items():
                fp = info.get('filepath')
                if fp and is_safe_download_path(fp, vid):
                    try:
                        total += os.path.getsize(fp)
                    except Exception:
                        continue
            return total
        total_bytes = total_downloaded_bytes()

        # If in download mode, enforce file size and total disk usage limits
        if client.download_mode:
            if not enough_disk_for_download():
                raise Exception(f"Less than {MIN_FREE_DOWNLOAD_MB}MB free on disk; download refused.")
            new_total = total_bytes + (filesize or 0)
            if new_total > TOTAL_LIMIT_NORMAL and not is_user_admin(requested_by):
                raise Exception("Total download cache size limit exceeded (normal user).")
            if new_total > TOTAL_LIMIT_ADMIN:
                raise Exception("Total download cache size limit exceeded (admin limit).")

        # Check single file size limit
        if filesize and filesize > MAX_FILESIZE_BYTES:
            if not is_user_admin(requested_by):
                raise Exception("File size exceeds 250MB limit for non-admin.")
            else:
                # Admin user with a very large file: require confirmation before downloading
                return {
                    'id': video_id, 'title': title, 'webpage_url': page_url,
                    'needs_confirm': True, 'filesize': filesize, 'duration': duration
                }

        # At this point, the track is within allowed limits
        if not client.download_mode:
            # Stream-only mode: do not download, just return info (no 'file' key)
            logger.info(f"Using stream-only mode for '{title}' ({video_id}).")
            return {'id': video_id, 'title': title, 'webpage_url': page_url}

        # Download mode: download the audio file using yt_dlp
        logger.info(f"Downloading track '{title}' ({video_id})...")
        data_full = await loop.run_in_executor(None, lambda: ytdl.extract_info(video_url, download=True))
        if data_full is None:
            raise Exception("Failed to download track info")
        if 'entries' in data_full:
            data_full = data_full['entries'][0]
        file_path = ytdl.prepare_filename(data_full)
        if not is_safe_download_path(file_path, video_id):
            raise Exception("Downloaded file path failed safety validation.")
        # Cache the downloaded file info
        downloaded[video_id] = {'title': title, 'filepath': file_path, 'timestamp': time.time()}
        save_downloads_metadata("track download")
        logger.info(f"Downloaded '{title}' ({video_id}) to {file_path}")
        return {'id': video_id, 'title': title, 'webpage_url': page_url, 'file': file_path}
    except Exception as e:
        logger.error(f"yt_dlp error for {query}: {e}")
        raise

async def ensure_voice_for_playback(ctx):
    voice = client.current_voice_channel or ctx.guild.voice_client
    if voice is None or not voice.is_connected():
        if ctx.user.voice and ctx.user.voice.channel:
            try:
                voice = await ctx.user.voice.channel.connect()
                client.current_voice_channel = voice
                client.song_history = []
                await ctx.followup.send(f"Joined voice channel {ctx.user.voice.channel.name}")
            except Exception as e:
                logger.error(f"Voice connection failed: {e}")
                await ctx.followup.send("Couldn't join voice channel.")
                return None
        else:
            await ctx.followup.send("You need to join a voice channel first.")
            return None
    else:
        client.current_voice_channel = voice
        if not await require_voice_control(ctx, "start playback"):
            return None
    return voice

async def build_audio_player(track: dict):
    if track.get('file'):
        source = discord.FFmpegPCMAudio(track['file'], options='-vn')
        return discord.PCMVolumeTransformer(source, volume=client.volume)
    player, _ = await YTDLSource.from_url(track['webpage_url'], stream=True)
    return player

async def start_track_now(ctx, voice, track: dict):
    player = await build_audio_player(track)
    voice.play(player, after=lambda e, vid=track['id']: after_played_track(e, vid, ctx.channel))
    client.current_track_id = track['id']
    client.currently_playing = True
    client.last_track_info = client.current_track_info
    client.current_track_info = track
    client.song_history.append(track)
    await publish_now_playing(
        ctx.channel,
        track,
        send_message=ctx.followup.send,
        acknowledge=ctx.followup.send,
    )
    logger.info(f"Playing now: {track['title']} ({track['id']})")

async def prompt_move_track_next(ctx, track: dict, playlist_name: str):
    title = discord.utils.escape_markdown(str(track.get("title") or "Unknown title"))
    safe_playlist = discord.utils.escape_markdown(str(playlist_name or "playlist"))
    text = (
        f"A playlist (**{safe_playlist}**) is playing. **{title}** was added after the playlist. "
        "React 👍 to play it next or 👎 to keep it there."
    )
    try:
        if ctx.response.is_done():
            prompt_msg = await ctx.followup.send(text, wait=True)
        else:
            await ctx.response.send_message(text)
            prompt_msg = await ctx.original_response()
        await prompt_msg.add_reaction("👍")
        await prompt_msg.add_reaction("👎")
    except Exception as exc:
        logger.warning(f"Could not send playlist placement prompt: {exc}")
        return

    def check(reaction, user):
        return user == ctx.user and str(reaction.emoji) in ["👍", "👎"] and reaction.message.id == prompt_msg.id

    try:
        reaction, _ = await client.wait_for('reaction_add', timeout=20.0, check=check)
    except asyncio.TimeoutError:
        logger.info("Playlist placement prompt timed out; keeping song after playlist.")
        return

    if str(reaction.emoji) == "👍":
        try:
            queue.remove(track)
        except ValueError:
            return
        queue.insert(0, track)
        await ctx.followup.send(f"Moved **{title}** to play next.")
        logger.info(f"Moved queued song ahead of active playlist by request: {track.get('title')} ({track.get('id')})")
    else:
        await ctx.followup.send(f"Keeping **{title}** after the playlist.")

async def enqueue_track_with_playlist_prompt(ctx, track: dict, command_name: str):
    block_id = active_playlist_block_id()
    if block_id:
        insert_after_active_playlist(track)
        client.song_history.append(track)
        logger.info(f"Track queued after active playlist via /{command_name}: {track.get('title')} ({track.get('id')})")
        await prompt_move_track_next(ctx, track, (client.current_track_info or {}).get("playlist_name", "playlist"))
    else:
        queue.append(track)
        client.song_history.append(track)
        title = discord.utils.escape_markdown(str(track.get('title') or 'Unknown title'))
        await ctx.followup.send(f"Added to queue: {title} ({track.get('id', '')})")
        logger.info(f"Track enqueued: {track.get('title')} ({track.get('id')})")

async def play_playlist_now(ctx, playlist: dict, command_name: str):
    tracks = playlist_to_queue_tracks(playlist)
    if not tracks:
        await ctx.followup.send("That playlist is empty.")
        return
    if not is_user_admin(ctx.user):
        projected_queue = len(queue) + len(tracks) if client.currently_playing else len(queue) + max(0, len(tracks) - 1)
        if projected_queue > MAX_QUEUE_LENGTH:
            await ctx.followup.send(f"Queue limit reached ({MAX_QUEUE_LENGTH} songs). Ask an admin to clear the queue.", ephemeral=True)
            return
    voice = await ensure_voice_for_playback(ctx)
    if voice is None:
        return
    if client.currently_playing:
        for track in tracks:
            queue.append(track)
            client.song_history.append(track)
        await ctx.followup.send(f"Queued playlist **{discord.utils.escape_markdown(playlist['name'])}** ({len(tracks)} song(s)).")
        logger.info(f"Queued playlist via /{command_name}: {playlist['name']} ({playlist['id']})")
        return
    first, rest = tracks[0], tracks[1:]
    queue.extend(rest)
    for track in rest:
        client.song_history.append(track)
    await start_track_now(ctx, voice, first)
    logger.info(f"Started playlist via /{command_name}: {playlist['name']} ({playlist['id']})")

async def enqueue_playlist(ctx, playlist: dict, command_name: str):
    tracks = playlist_to_queue_tracks(playlist)
    if not tracks:
        await ctx.followup.send("That playlist is empty.")
        return
    if not is_user_admin(ctx.user) and len(queue) + len(tracks) > MAX_QUEUE_LENGTH:
        await ctx.followup.send(f"Queue limit reached ({MAX_QUEUE_LENGTH} songs). Ask an admin to clear the queue.", ephemeral=True)
        return
    for track in tracks:
        queue.append(track)
        client.song_history.append(track)
    await ctx.followup.send(f"Queued playlist **{discord.utils.escape_markdown(playlist['name'])}** ({len(tracks)} song(s)).")
    logger.info(f"Queued playlist via /{command_name}: {playlist['name']} ({playlist['id']})")

def move_existing_playlist_block_to_front(playlist_id: str) -> int:
    moving = [track for track in queue if track.get("playlist_id") == playlist_id]
    if not moving:
        return 0
    queue[:] = [track for track in queue if track.get("playlist_id") != playlist_id]
    queue[0:0] = moving
    return len(moving)

async def add_playlist_to_queue_front(ctx, playlist: dict):
    moved = move_existing_playlist_block_to_front(playlist.get("id"))
    if moved:
        await ctx.response.send_message(
            f"Moved queued playlist **{discord.utils.escape_markdown(playlist['name'])}** to play next ({moved} song(s))."
        )
        logger.info(f"Moved existing playlist block to front: {playlist['name']} ({playlist['id']})")
        return
    tracks = playlist_to_queue_tracks(playlist)
    if not tracks:
        await ctx.response.send_message("That playlist is empty.")
        return
    if not is_user_admin(ctx.user) and len(queue) + len(tracks) > MAX_QUEUE_LENGTH:
        await ctx.response.send_message(f"Queue limit reached ({MAX_QUEUE_LENGTH} songs). Ask an admin to clear the queue.", ephemeral=True)
        return
    queue[0:0] = tracks
    client.song_history.extend(tracks)
    await ctx.response.send_message(
        f"Moved playlist **{discord.utils.escape_markdown(playlist['name'])}** to play next ({len(tracks)} song(s))."
    )
    logger.info(f"Playlist queued at front: {playlist['name']} ({playlist['id']})")

async def predownload_playlist_files(playlist: dict) -> int:
    folder = playlist_folder_path(playlist)
    os.makedirs(folder, exist_ok=True)
    options = dict(ytdl_options)
    options['outtmpl'] = os.path.join(folder, '%(extractor)s-%(id)s-%(title)s.%(ext)s')
    downloaded_count = 0
    loop = asyncio.get_event_loop()
    permanent_ytdl = yt_dlp.YoutubeDL(options)
    for track in playlist.get("tracks", []):
        video_id = str(track.get("id") or "")
        if not video_id:
            continue
        if track.get("permanent_file") and is_safe_playlist_file_path(track["permanent_file"], playlist, video_id):
            continue
        url = track.get("webpage_url") or youtube_watch_url + video_id
        data = await loop.run_in_executor(None, lambda u=url: permanent_ytdl.extract_info(u, download=True))
        if data is None:
            continue
        if 'entries' in data:
            data = next((entry for entry in data['entries'] if entry), None)
        if data is None:
            continue
        file_path = permanent_ytdl.prepare_filename(data)
        if not is_safe_playlist_file_path(file_path, playlist, video_id):
            raise Exception(f"Downloaded playlist file failed safety validation for {video_id}.")
        track["permanent_file"] = file_path
        track["permanent_downloaded_at"] = time.time()
        downloaded_count += 1
    playlist["predownloaded"] = True
    playlist["predownloaded_at"] = time.time()
    save_playlist(playlist)
    return downloaded_count

def after_played_track(error, video_id, channel):
    """Callback that runs after a track finishes playing or is stopped."""
    if error:
        logger.error(f"Error in playback: {error}")
    # Mark this track as played in history
    if video_id:
        client.played_tracks.add(video_id)
    # Schedule deletion of the file after 10 minutes (if it exists in cache)
    if video_id in downloaded:
        async def remove_file():
            await asyncio.sleep(600)  # wait 600 seconds before deleting
            # If the deletion task was canceled due to reuse, skip actual deletion
            if video_id not in client.deletion_tasks:
                return
            info = downloaded.get(video_id)
            if info:
                file_path = info.get('filepath')
                remove_download_file(file_path, video_id=video_id, reason="delayed playback cleanup")
                downloaded.pop(video_id, None)
                save_downloads_metadata("delayed playback cleanup")
            # Remove this task from tracking
            client.deletion_tasks.pop(video_id, None)
        # If a deletion task is already scheduled for this video, cancel it
        if video_id in client.deletion_tasks:
            try:
                client.deletion_tasks[video_id].cancel()
            except Exception as e:
                logger.debug(f"Canceling previous deletion task for {video_id}: {e}")
        # Schedule the deletion task in the event loop
        task = asyncio.run_coroutine_threadsafe(remove_file(), client.loop)
        client.deletion_tasks[video_id] = task

    # Proceed to the next track in queue
    asyncio.run_coroutine_threadsafe(play_next_channel(channel), client.loop)

async def play_next_channel(channel):
    """Plays the next track in the queue, if any."""
    if len(queue) > 0:
        track = queue.pop(0)
        try:
            # If a local file exists for this track, play from file; otherwise stream from YouTube
            if track.get('file') and os.path.isfile(track['file']):
                source = discord.FFmpegPCMAudio(track['file'], options='-vn')
                player = discord.PCMVolumeTransformer(source, volume=client.volume)
            else:
                # No local file (or file missing) – stream audio directly
                player, _ = await YTDLSource.from_url(track['webpage_url'], stream=True)
            guild = channel.guild
            client.current_track_id = track['id']
            # Start playback and provide callback
            guild.voice_client.play(player, after=lambda e, vid=track['id']: after_played_track(e, vid, channel))
            client.currently_playing = True
            # Update current and last track info
            client.last_track_info = client.current_track_info
            client.current_track_info = track
            await publish_now_playing(channel, track)
            logger.info(f"Started playing: {track['title']} ({track['id']})")
            # Add track to session history if not already recorded
            if track not in client.song_history:
                client.song_history.append(track)
        except Exception as e:
            logger.error(f"Failed to play next track: {e}")
            await channel.send("Failed to play the next track.")
            client.currently_playing = False
    else:
        # Queue is empty
        client.currently_playing = False
        logger.info("No more songs to play. Queue is now clear.")
        await channel.send("No more songs in queue.")

@client.event
async def on_ready():
    await client.change_presence(activity=discord.Game(name="/help for commands"))
    logger.info(f"{client.user} on käynnistynyt.")
    logger.info(build_runtime_status())
    try:
        synced = await client.tree.sync(guild=MY_GUILD)
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Sync error: {e}")

@client.event
async def on_voice_state_update(member, before, after):
    # If the bot client leaves voice entirely, reset tracking state
    bot_id = getattr(client.user, "id", None)
    if bot_id and member.id == bot_id and after.channel is None:
        client.current_voice_channel = None
        client.currently_playing = False

@client.event
async def on_message(msg):
    """On receiving a message in monitored channel, save quotes."""
    if msg.channel == client.get_channel(QUOTES_ID):
        quotes.saveSingleQuote(msg.content)

@client.event
async def on_message_edit(msg_before, msg_after):
    """On editing a message in monitored channel, update quotes backup."""
    if msg_after.channel == client.get_channel(QUOTES_ID):
        channel = client.get_channel(QUOTES_ID)
        await save_all_channel_messages(channel)

@client.event
async def on_message_delete(msg):
    """On deleting a message in monitored channel, update quotes backup."""
    if msg.channel == client.get_channel(QUOTES_ID):
        channel = client.get_channel(QUOTES_ID)
        await save_all_channel_messages(channel)

@client.event
async def on_reaction_add(reaction, user):
    """Handles reaction-based controls for playback and confirmation prompts."""
    if user == client.user:
        return  # ignore the bot's own reactions
    if await handle_playlist_pager_reaction(reaction, user):
        return
    if client.help_message_id and reaction.message.id == client.help_message_id and str(reaction.emoji) == HELP_EXPAND_REACTION:
        try:
            client.help_expanded = True
            await reaction.message.edit(content=expanded_help_message())
            await reaction.message.remove_reaction(reaction.emoji, user)
            logger.info(f"Expanded help message {reaction.message.id}.")
        except Exception as exc:
            logger.warning(f"Failed to expand help message: {exc}")
        return
    # Music control reactions on the "Now Playing" message
    if client.current_track_message and reaction.message.id == client.current_track_message.id:
        if not can_control_voice(user):
            logger.warning(
                f"Denied now-playing reaction {reaction.emoji} by {user_display(user)} "
                f"({getattr(user, 'id', 0)}): user is not in the bot voice channel."
            )
            try:
                await reaction.message.remove_reaction(reaction.emoji, user)
            except Exception as e:
                logger.warning(f"Failed to remove denied user reaction: {e}")
            return
        emoji = str(reaction.emoji)
        if emoji == QUEUE_REACTION:
            await toggle_now_playing_queue(reaction.message)
        elif emoji == "▶️":
            # Skip to next track
            if client.current_voice_channel and (client.current_voice_channel.is_playing() or client.current_voice_channel.is_paused()):
                logger.info("Skipped track with emoji.")
                client.current_voice_channel.stop()
        elif emoji == "⏸️":
            # Pause or resume
            if client.current_voice_channel:
                if client.current_voice_channel.is_playing():
                    client.current_voice_channel.pause()
                    logger.info("Audio paused via reaction.")
                elif client.current_voice_channel.is_paused():
                    client.current_voice_channel.resume()
                    logger.info("Audio resumed via reaction.")
        elif emoji == "◀️":
            # Play previous track (replay last track)
            if client.last_track_info:
                queue.insert(0, client.last_track_info)
                if client.current_voice_channel and (client.current_voice_channel.is_playing() or client.current_voice_channel.is_paused()):
                    client.current_voice_channel.stop()
                logger.info("Previous track requested via reaction.")
            else:
                await reaction.message.channel.send("No previous track to play.")
        else:
            return
        # Remove the user's reaction to allow them to use it again
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except Exception as e:
            logger.warning(f"Failed to remove user reaction: {e}")

async def save_all_channel_messages(channel):
    if channel is None:
        logger.warning("Quotes backup requested but quotes channel is not available.")
        return 0
    messages = [message.content async for message in channel.history(limit=None)]
    quotes.saveQuotes(messages)
    return len(messages)

# Slash commands

playlist_group = app_commands.Group(name="playlist", description="create, browse, and edit saved playlists")

@client.tree.command()
async def join(ctx):
    """Joins the voice channel that the user is currently in."""
    record_command(ctx)
    if ctx.user.voice:
        try:
            client.current_voice_channel = await ctx.user.voice.channel.connect()
            # Reset session history when joining a new voice channel
            client.song_history = []
            await ctx.response.send_message(f"Joined voice channel {ctx.user.voice.channel.name}")
        except Exception as e:
            logger.error(f"Join error: {e}")
            await ctx.response.send_message(f"Unable to join voice channel {ctx.user.voice.channel.name}")
    else:
        await ctx.response.send_message("You must be in a voice channel to use this command")

@client.tree.command()
async def clear_queue(ctx):
    """Clears the current song queue, with option to delete downloaded files."""
    record_command(ctx)
    if not await require_voice_control(ctx, "clear the queue"):
        return
    if len(queue) == 0:
        await ctx.response.send_message("There is no queue to clear")
        logger.info("User tried to clear queue, there is no queue to clear.")
        return
    # Backup the current queue for potential restore
    client.queue_backup = list(queue)
    client.backup_timestamp = time.time()
    queue.clear()
    is_admin = is_user_admin(ctx.user)
    if is_admin:
        # Ask admin for confirmation to delete all downloaded files
        await ctx.response.send_message("Queue cleared. Delete all downloaded files from disk? React with 👍 to confirm or 👎 to cancel (10s timeout).")
        try:
            prompt_msg = await ctx.original_response()
        except Exception:
            prompt_msg = None
        if prompt_msg:
            try:
                await prompt_msg.add_reaction("👍")
                await prompt_msg.add_reaction("👎")
            except Exception as e:
                logger.error(f"Failed to add reactions for file deletion prompt: {e}")
            # Wait for admin reaction
            def check(reaction, user):
                return user == ctx.user and str(reaction.emoji) in ["👍", "👎"] and reaction.message.id == prompt_msg.id
            try:
                reaction, user = await client.wait_for('reaction_add', timeout=10.0, check=check)
            except asyncio.TimeoutError:
                # No response in time
                await ctx.followup.send("No reaction received. Keeping downloaded files.")
                logger.info("Queue cleared by admin (files retained due to no confirmation).")
                return
            if str(reaction.emoji) == "👍":
                # Admin confirmed file deletion
                count = 0
                current_id = client.current_track_id
                for vid, info in list(downloaded.items()):
                    if vid == current_id:
                        # Do not delete the file of the currently playing track, if any
                        continue
                    file_path = info.get('filepath')
                    if remove_download_file(file_path, video_id=vid, reason="admin clear_queue"):
                        count += 1
                    downloaded.pop(vid, None)
                save_downloads_metadata("admin clear_queue deletion")
                await ctx.followup.send(f"Queue cleared and {count} files deleted from disk.")
                logger.info(f"Queue cleared by admin (deleted {count} files from disk).")
            else:
                await ctx.followup.send("Queue cleared. Downloaded files retained.")
                logger.info("Queue cleared by admin (files retained).")
    else:
        # Non-admin: just clear the queue, do not touch files
        await ctx.response.send_message("Queue cleared (downloaded files retained).")
        logger.info("Queue cleared by user (no file deletion permitted).")

@client.tree.command()
async def skip(ctx):
    """Skips the currently playing track."""
    record_command(ctx)
    if not await require_voice_control(ctx, "skip tracks"):
        return
    if client.current_voice_channel and client.current_voice_channel.is_connected() and (client.current_voice_channel.is_playing() or client.current_voice_channel.is_paused()):
        client.current_voice_channel.stop()
        await ctx.response.send_message("Skipped the current track")
        logger.info("Track skipped by user")
    else:
        logger.info("User tried to skip, but nothing is playing.")
        await ctx.response.send_message("No track is currently playing")

@app_commands.describe(url="YouTube URL or search term")
@client.tree.command()
async def play(ctx, *, url: str):
    """Plays a YouTube video's audio by URL or search term."""
    record_command(ctx)
    await ctx.response.defer()
    playlist = resolve_playlist_reference(url, ctx.user)
    if playlist:
        await play_playlist_now(ctx, playlist, "play")
        return
    if not client.currently_playing:
        # Ensure we're connected to a voice channel before creating the player
        voice = client.current_voice_channel or ctx.guild.voice_client
        if voice is None or not voice.is_connected():
            if ctx.user.voice and ctx.user.voice.channel:
                try:
                    voice = await ctx.user.voice.channel.connect()
                    client.current_voice_channel = voice
                    client.song_history = []  # reset history for new session
                    await ctx.followup.send(f"Joined voice channel {ctx.user.voice.channel.name}")
                except Exception as e:
                    logger.error(f"Voice connection failed: {e}")
                    await ctx.followup.send("Couldn't join voice channel.")
                    return
            else:
                await ctx.followup.send("You need to join a voice channel first.")
                return
        else:
            client.current_voice_channel = voice
            if not await require_voice_control(ctx, "start playback"):
                return
        try:
            suggestion = record_suggestion(ctx, "play", url)
            track = await fetch_track(url, requested_by=ctx.user)
            update_suggestion(suggestion, track)
            # If admin needs to confirm a large download
            if track.get('needs_confirm'):
                filesize_mb = track.get('filesize', 0) / (1024 * 1024)
                # Prompt admin for confirmation to download the large file
                confirm_text = f"Track **{track['title']}** is large (~{filesize_mb:.1f} MB). React 👍 to confirm download, or 👎 to cancel."
                confirm_msg = await ctx.followup.send(confirm_text, wait=True)
                try:
                    await confirm_msg.add_reaction("👍")
                    await confirm_msg.add_reaction("👎")
                except Exception as e:
                    logger.error(f"Failed to add reactions for large file confirm: {e}")
                def check(reaction, user):
                    return user == ctx.user and str(reaction.emoji) in ["👍", "👎"] and reaction.message.id == confirm_msg.id
                try:
                    reaction, user = await client.wait_for('reaction_add', timeout=15.0, check=check)
                except asyncio.TimeoutError:
                    await ctx.followup.send("Confirmation timed out. Cancelling the play request.")
                    return
                if str(reaction.emoji) == "👍":
                    # Admin confirmed download: fetch again with download (this time no 'needs_confirm')
                    track = await fetch_track(track['webpage_url'], requested_by=ctx.user)
                    update_suggestion(suggestion, track)
                else:
                    await ctx.followup.send("Download canceled.")
                    return
            # Play the track (either from file or streaming)
            if track.get('file'):
                source = discord.FFmpegPCMAudio(track['file'], options='-vn')
                player = discord.PCMVolumeTransformer(source, volume=client.volume)
            else:
                player, _ = await YTDLSource.from_url(track['webpage_url'], stream=True)
            voice.play(player, after=lambda e, vid=track['id']: after_played_track(e, vid, ctx.channel))
            client.current_track_id = track['id']
            client.currently_playing = True
            client.last_track_info = client.current_track_info
            client.current_track_info = track
            client.song_history.append(track)
            await publish_now_playing(
                ctx.channel,
                track,
                send_message=ctx.followup.send,
                acknowledge=ctx.followup.send,
            )
            logger.info(f"Playing now: {track['title']} ({track['id']})")
        except Exception as e:
            logger.error(f"/play error: {e}")
            await ctx.followup.send("Failed to play the requested track.")
    else:
        # If something is already playing, add the requested song to the queue
        if not await require_queue_room(ctx):
            return
        try:
            suggestion = record_suggestion(ctx, "play", url)
            track = await fetch_track(url, requested_by=ctx.user)
            update_suggestion(suggestion, track)
            if track.get('needs_confirm'):
                # Cannot queue a large download without confirmation; instruct admin to use /play
                filesize_mb = track.get('filesize', 0) / (1024 * 1024)
                await ctx.followup.send(f"Track **{track['title']}** (~{filesize_mb:.1f} MB) is too large to queue without confirmation. Please use /play to confirm.")
                return
            await enqueue_track_with_playlist_prompt(ctx, track, "play")
        except Exception as e:
            logger.error(f"/play queue error: {e}")
            await ctx.followup.send("Failed to add track to queue.")

@app_commands.describe(query="YouTube URL or search term")
@client.tree.command()
async def playtop(ctx, *, query: str):
    """Adds a song to the top of the queue (plays next)."""
    record_command(ctx)
    await ctx.response.defer()
    if not client.currently_playing:
        # Nothing playing, so this will play immediately (similar to /play when queue empty)
        voice = client.current_voice_channel or ctx.guild.voice_client
        if voice is None or not voice.is_connected():
            if ctx.user.voice and ctx.user.voice.channel:
                try:
                    voice = await ctx.user.voice.channel.connect()
                    client.current_voice_channel = voice
                    client.song_history = []
                    await ctx.followup.send(f"Joined voice channel {ctx.user.voice.channel.name}")
                except Exception as e:
                    logger.error(f"Voice connection failed: {e}")
                    await ctx.followup.send("Couldn't join voice channel.")
                    return
            else:
                await ctx.followup.send("You need to join a voice channel first.")
                return
        else:
            client.current_voice_channel = voice
            if not await require_voice_control(ctx, "start playback"):
                return
        try:
            suggestion = record_suggestion(ctx, "playtop", query)
            track = await fetch_track(query, requested_by=ctx.user)
            update_suggestion(suggestion, track)
            if track.get('needs_confirm'):
                filesize_mb = track.get('filesize', 0) / (1024 * 1024)
                await ctx.followup.send(f"Track **{track['title']}** (~{filesize_mb:.1f} MB) is too large to play without confirmation. Use /play for this track.")
                return
            # Play the track immediately
            if track.get('file'):
                source = discord.FFmpegPCMAudio(track['file'], options='-vn')
                player = discord.PCMVolumeTransformer(source, volume=client.volume)
            else:
                player, _ = await YTDLSource.from_url(track['webpage_url'], stream=True)
            voice.play(player, after=lambda e, vid=track['id']: after_played_track(e, vid, ctx.channel))
            client.current_track_id = track['id']
            client.currently_playing = True
            client.last_track_info = client.current_track_info
            client.current_track_info = track
            client.song_history.append(track)
            await publish_now_playing(
                ctx.channel,
                track,
                send_message=ctx.followup.send,
                acknowledge=ctx.followup.send,
            )
            logger.info(f"Playing now: {track['title']} ({track['id']})")
        except Exception as e:
            logger.error(f"/playtop error: {e}")
            await ctx.followup.send("Failed to play the track.")
    else:
        # If currently playing, queue this track to be next
        if not await require_queue_room(ctx):
            return
        try:
            suggestion = record_suggestion(ctx, "playtop", query)
            track = await fetch_track(query, requested_by=ctx.user)
            update_suggestion(suggestion, track)
            if track.get('needs_confirm'):
                filesize_mb = track.get('filesize', 0) / (1024 * 1024)
                await ctx.followup.send(f"Track **{track['title']}** (~{filesize_mb:.1f} MB) is too large to queue without confirmation.")
                return
            queue.insert(0, track)
            client.song_history.append(track)
            await ctx.followup.send(f"Added to queue (next): {track['title']} ({track['id']})")
            logger.info(f"Track added to top of queue: {track['title']} ({track['id']})")
        except Exception as e:
            logger.error(f"/playtop queue error: {e}")
            await ctx.followup.send("Failed to add track to queue.")

async def enqueue_track(ctx, query: str, command_name: str = "enqueue"):
    record_command(ctx)
    await ctx.response.defer()
    if not await require_queue_room(ctx):
        return
    playlist = resolve_playlist_reference(query, ctx.user)
    if playlist:
        await enqueue_playlist(ctx, playlist, command_name)
        return
    try:
        suggestion = record_suggestion(ctx, command_name, query)
        track = await fetch_track(query, requested_by=ctx.user)
        update_suggestion(suggestion, track)
        if track.get('needs_confirm'):
            filesize_mb = track.get('filesize', 0) / (1024 * 1024)
            await ctx.followup.send(f"Track **{track['title']}** (~{filesize_mb:.1f} MB) requires confirmation to download. Use /play instead.")
            return
        await enqueue_track_with_playlist_prompt(ctx, track, command_name)
    except Exception as e:
        logger.error(f"/{command_name} error: {e}")
        await ctx.followup.send("Failed to enqueue track.")

@app_commands.describe(query="YouTube URL or search term")
@client.tree.command(name="enqueue")
async def enqueue_cmd(ctx, *, query: str):
    """Enqueues a song to the queue (alias: /q)."""
    await enqueue_track(ctx, query, "enqueue")

@app_commands.describe(query="YouTube URL or search term")
@client.tree.command(name="q")
async def q_cmd(ctx, *, query: str):
    """Alias of /enqueue."""
    await enqueue_track(ctx, query, "q")

async def queue_first(ctx, target: str, command_name: str):
    """Move a queued track to the front so it plays next."""
    record_command(ctx)
    if not await require_voice_control(ctx, "reorder the queue"):
        return
    playlist = resolve_playlist_reference(target, ctx.user)
    if playlist:
        await add_playlist_to_queue_front(ctx, playlist)
        return
    try:
        position = int(str(target).strip())
    except ValueError:
        await ctx.response.send_message("Use a queue position number or a playlist name.")
        logger.info(f"/{command_name} rejected target {target!r}; not a number or visible playlist.")
        return
    if position < 1:
        await ctx.response.send_message("Queue positions start at 1.")
        logger.info(f"/{command_name} rejected invalid queue position {position}.")
        return
    if not queue:
        await ctx.response.send_message("Queue is empty.")
        logger.info(f"/{command_name} requested while queue is empty.")
        return
    if position > len(queue):
        await ctx.response.send_message(f"Queue only has {len(queue)} song(s).")
        logger.info(f"/{command_name} rejected position {position}; queue length is {len(queue)}.")
        return
    if position == 1:
        track = queue[0]
        record_suggestion(ctx, command_name, f"position {position}", track)
        title = discord.utils.escape_markdown(str(track.get('title') or 'Unknown title'))
        await ctx.response.send_message(f"**{title}** is already first in queue.")
        logger.info(f"/{command_name} requested position 1; queue already starts with {track.get('title', 'Unknown title')} ({track.get('id', '')}).")
        return

    track = queue.pop(position - 1)
    queue.insert(0, track)
    record_suggestion(ctx, command_name, f"position {position}", track)
    title = discord.utils.escape_markdown(str(track.get('title') or 'Unknown title'))
    await ctx.response.send_message(f"Moved **{title}** to the front of the queue. It will play next.")
    logger.info(f"/{command_name} moved queue position {position} to the front: {track.get('title', 'Unknown title')} ({track.get('id', '')})")

@app_commands.describe(target="1-based queue position or playlist name to move so it plays next")
@client.tree.command(name="queuefirst")
async def queuefirst_cmd(ctx, target: str):
    """Moves a queued song to the front of the queue."""
    await queue_first(ctx, target, "queuefirst")

@app_commands.describe(target="1-based queue position or playlist name to move so it plays next")
@client.tree.command(name="qfirst")
async def qfirst_cmd(ctx, target: str):
    """Alias of /queuefirst."""
    await queue_first(ctx, target, "qfirst")

async def send_queue_list(ctx, *, links: bool = False):
    if len(queue) == 0:
        await ctx.response.send_message("Queue is empty.")
    else:
        lines = ["Upcoming songs:"]
        show_links = links and not client.queue_links_disabled
        for i, track in enumerate(queue, start=1):
            title, url = track_display_parts(track)
            vid = track.get('id', '')
            entry = [f"{i}. **{title}** ({vid})"]
            if track.get("playlist_name"):
                entry.append(f"_playlist: {discord.utils.escape_markdown(str(track.get('playlist_name')))}_")
            if show_links:
                entry.append(f"*{url}*")
            remaining = len(queue) - i
            footer = f"_and {remaining} more queued song(s) omitted._" if remaining else None
            candidate_lines = lines + entry + ([footer] if footer else [])
            if len("\n".join(candidate_lines)) > DISCORD_MESSAGE_SAFE_LIMIT:
                lines.append(f"_and {len(queue) - i + 1} more queued song(s) omitted._")
                break
            lines.extend(entry)
        if links and client.queue_links_disabled:
            lines.append("_Links are disabled by an admin._")
        output = "\n".join(lines)
        await ctx.response.send_message(output)

@app_commands.describe(links="Show YouTube links with queued songs when links are enabled")
@client.tree.command(name="queue")
async def queue_cmd(ctx, links: bool = False):
    """Displays the upcoming songs in the queue."""
    record_command(ctx)
    await send_queue_list(ctx, links=links)

@app_commands.describe(links="Show YouTube links with queued songs when links are enabled")
@client.tree.command()
async def queuelist(ctx, links: bool = False):
    """Alias of /queue."""
    record_command(ctx)
    await send_queue_list(ctx, links=links)

@playlist_group.command(name="list", description="Browse your playlists and visible public playlists.")
async def playlist_list(ctx):
    record_command(ctx)
    pages = playlist_list_pages_for(ctx.user)
    await send_paged_playlist_message(ctx, pages)

@app_commands.describe(name="Playlist name", visibility="private or public")
@app_commands.choices(visibility=[
    app_commands.Choice(name="private", value="private"),
    app_commands.Choice(name="public", value="public"),
])
@playlist_group.command(name="new", description="Create a playlist.")
async def playlist_new(ctx, name: str, visibility: str = "private"):
    record_command(ctx)
    safe_name = normalize_playlist_name(name)
    if not safe_name:
        await ctx.response.send_message("Playlist name cannot be empty.", ephemeral=True)
        return
    if resolve_playlist_reference(safe_name, ctx.user, require_visible=False):
        await ctx.response.send_message("A playlist with that name or id already exists.", ephemeral=True)
        return
    playlist = make_playlist_metadata(safe_name, ctx.user, visibility if visibility in {"private", "public"} else "private")
    save_playlist(playlist)
    append_playlist_blackbox_event("created", playlist, ctx.user)
    await ctx.response.send_message(
        f"Created {playlist['visibility']} playlist **{discord.utils.escape_markdown(playlist['name'])}** (`{playlist['id']}`)."
    )
    logger.info(f"Playlist created: {playlist['name']} ({playlist['id']}) by {user_display(ctx.user)}")

@app_commands.describe(name="Playlist name, id, or playlist:name", flags="Optional flag: -force")
@playlist_group.command(name="edit", description="Show editable playlist details.")
async def playlist_edit(ctx, name: str, flags: Optional[str] = None):
    record_command(ctx)
    parsed_flags = parse_playlist_flags(flags)
    playlist = resolve_playlist_reference(name, ctx.user)
    if not playlist:
        await ctx.response.send_message("Playlist not found or not visible to you.", ephemeral=True)
        return
    if not can_edit_playlist(ctx.user, playlist):
        await ctx.response.send_message("You can view this playlist, but you cannot edit it.", ephemeral=True)
        return
    if not await confirm_admin_foreign_playlist(ctx, playlist, "playlist edit", parsed_flags):
        await safe_interaction_send(ctx, "Playlist edit cancelled.", ephemeral=True)
        return
    await send_paged_playlist_message(ctx, playlist_detail_pages(playlist))

@app_commands.describe(
    playlist="Playlist name, id, or playlist:name",
    source="Add the current song or a song from the queue",
    queue_position="Queue position when source is queue",
)
@app_commands.choices(source=[
    app_commands.Choice(name="current", value="current"),
    app_commands.Choice(name="queue", value="queue"),
])
@playlist_group.command(name="add", description="Add current or queued song to a playlist.")
async def playlist_add(ctx, playlist: str, source: str, queue_position: Optional[int] = None):
    record_command(ctx)
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.response.send_message("Playlist not found or not visible to you.", ephemeral=True)
        return
    if not can_edit_playlist(ctx.user, target):
        await ctx.response.send_message("You do not have permission to edit that playlist.", ephemeral=True)
        return
    if source == "current":
        track = client.current_track_info
        if not track:
            await ctx.response.send_message("No song is currently playing.", ephemeral=True)
            return
    elif source == "queue":
        if queue_position is None or queue_position < 1 or queue_position > len(queue):
            await ctx.response.send_message("Provide a valid queue position.", ephemeral=True)
            return
        track = queue[queue_position - 1]
    else:
        await ctx.response.send_message("Use source `current` or `queue`.", ephemeral=True)
        return
    target.setdefault("tracks", []).append(playlist_track_from_track(track, ctx.user))
    save_playlist(target)
    title = discord.utils.escape_markdown(str(track.get("title") or "Unknown title"))
    await ctx.response.send_message(f"Added **{title}** to **{discord.utils.escape_markdown(target['name'])}**.")
    logger.info(f"Added track to playlist {target['name']} ({target['id']}): {track.get('title')} ({track.get('id')})")

@app_commands.describe(playlist="Playlist name, id, or playlist:name", user="Discord user to add as manager")
@playlist_group.command(name="addmod", description="Add a playlist manager.")
async def playlist_addmod(ctx, playlist: str, user: discord.Member):
    record_command(ctx)
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.response.send_message("Playlist not found or not visible to you.", ephemeral=True)
        return
    if not can_manage_playlist(ctx.user, target):
        await ctx.response.send_message("Only the owner or an admin can add playlist managers.", ephemeral=True)
        return
    manager_ids = playlist_manager_ids(target)
    manager_ids.add(user_id_value(user))
    target["manager_user_ids"] = sorted(manager_ids)
    save_playlist(target)
    await ctx.response.send_message(f"Added **{discord.utils.escape_markdown(user_display(user))}** as manager for **{discord.utils.escape_markdown(target['name'])}**.")
    logger.info(f"Playlist manager added for {target['name']} ({target['id']}): {user_display(user)} ({user_id_value(user)})")

@app_commands.describe(playlist="Playlist name, id, or playlist:name", flags="Optional flags: -now -force")
@playlist_group.command(name="remove", description="Delete a playlist with a rescue window.")
async def playlist_remove(ctx, playlist: str, flags: Optional[str] = None):
    record_command(ctx)
    parsed_flags = parse_playlist_flags(flags)
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.response.send_message("Playlist not found or not visible to you.", ephemeral=True)
        return
    if not can_manage_playlist(ctx.user, target):
        await ctx.response.send_message("Only the owner or an admin can remove playlists.", ephemeral=True)
        return
    remove_now = "-now" in parsed_flags
    if remove_now and not is_user_admin(ctx.user):
        await ctx.response.send_message("Only admins can use `-now`.", ephemeral=True)
        return
    skip_confirm = remove_now and "-force" in parsed_flags and is_user_admin(ctx.user)
    if not skip_confirm:
        if not await confirm_admin_foreign_playlist(ctx, target, "playlist removal", parsed_flags):
            await safe_interaction_send(ctx, "Playlist removal cancelled.", ephemeral=True)
            return
        if not await confirm_with_reactions(
            ctx,
            f"Are you sure you want to remove playlist **{discord.utils.escape_markdown(target['name'])}**?",
        ):
            await safe_interaction_send(ctx, "Playlist removal cancelled.", ephemeral=True)
            return
    if remove_now:
        if not safe_remove_playlist_folder(target):
            await safe_interaction_send(ctx, "Playlist removal failed. Check output.log.", ephemeral=True)
            return
        append_playlist_blackbox_event("removed-now", target, ctx.user)
        await safe_interaction_send(ctx, "Playlist removed permanently.")
        logger.info(f"Playlist removed immediately: {target.get('name')} ({target.get('id')})")
        return

    delete_after = time.time() + PLAYLIST_DELETE_GRACE_SECONDS
    target["deleted"] = True
    target["deleted_at"] = time.time()
    target["delete_after"] = delete_after
    target["deleted_by_user_id"] = user_id_value(ctx.user)
    target["deleted_by_discord_name"] = user_display(ctx.user)
    save_playlist(target)
    append_playlist_blackbox_event("removed", target, ctx.user)
    if target.get("id") in client.playlist_delete_tasks:
        client.playlist_delete_tasks[target["id"]].cancel()
    client.playlist_delete_tasks[target["id"]] = asyncio.create_task(schedule_playlist_purge(target["id"], delete_after))
    await safe_interaction_send(
        ctx,
        f"Playlist removed. It can be restored for 600 seconds with `/playlist rescue {target['name']}`.",
    )
    logger.info(f"Playlist soft-deleted: {target.get('name')} ({target.get('id')})")

@app_commands.describe(playlist="Deleted playlist name, id, or playlist:name to restore")
@playlist_group.command(name="rescue", description="Restore a playlist during its delete grace window.")
async def playlist_rescue(ctx, playlist: Optional[str] = None):
    record_command(ctx)
    if not playlist:
        deleted = deleted_playlists_for(ctx.user)
        if not deleted:
            await ctx.response.send_message("No deleted playlists are available to rescue.", ephemeral=True)
            return
        lines = ["**deleted playlists available for rescue**"]
        now = time.time()
        for item in deleted:
            remaining = max(0, int(item.get("delete_after", now) - now))
            lines.append(
                f"- **{discord.utils.escape_markdown(str(item.get('name', 'playlist')))}** "
                f"(`{item.get('id')}`) - {remaining}s remaining"
            )
        await ctx.response.send_message("\n".join(lines), ephemeral=True)
        return

    target = resolve_playlist_reference(playlist, ctx.user, include_deleted=True)
    if not target or not target.get("deleted"):
        await ctx.response.send_message("Deleted playlist not found.", ephemeral=True)
        return
    if not (is_user_admin(ctx.user) or user_id_value(ctx.user) == playlist_owner_id(target)):
        await ctx.response.send_message("Only the owner or an admin can rescue that playlist.", ephemeral=True)
        return
    target["deleted"] = False
    target.pop("deleted_at", None)
    target.pop("delete_after", None)
    target.pop("deleted_by_user_id", None)
    target.pop("deleted_by_discord_name", None)
    save_playlist(target)
    task = client.playlist_delete_tasks.pop(target.get("id"), None)
    if task:
        task.cancel()
    append_playlist_blackbox_event("rescued", target, ctx.user)
    await ctx.response.send_message(f"Restored playlist **{discord.utils.escape_markdown(target['name'])}**.")
    logger.info(f"Playlist rescued: {target.get('name')} ({target.get('id')})")

@app_commands.describe(playlist="Playlist name, id, or playlist:name", position="1-based song position to remove")
@playlist_group.command(name="removesong", description="Remove a song from a playlist.")
async def playlist_removesong(ctx, playlist: str, position: int, flags: Optional[str] = None):
    record_command(ctx)
    parsed_flags = parse_playlist_flags(flags)
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.response.send_message("Playlist not found or not visible to you.", ephemeral=True)
        return
    if not can_edit_playlist(ctx.user, target):
        await ctx.response.send_message("You do not have permission to edit that playlist.", ephemeral=True)
        return
    if not await confirm_admin_foreign_playlist(ctx, target, "song removal", parsed_flags):
        await safe_interaction_send(ctx, "Song removal cancelled.", ephemeral=True)
        return
    tracks = target.get("tracks", [])
    if position < 1 or position > len(tracks):
        await safe_interaction_send(ctx, "That song position does not exist.", ephemeral=True)
        return
    removed = tracks.pop(position - 1)
    save_playlist(target)
    await safe_interaction_send(
        ctx,
        f"Removed **{discord.utils.escape_markdown(str(removed.get('title') or 'Unknown title'))}** from **{discord.utils.escape_markdown(target['name'])}**.",
    )

@app_commands.describe(playlist="Playlist name, id, or playlist:name", from_position="Current position", to_position="New position", flags="Optional flag: -force")
@playlist_group.command(name="move", description="Move a song inside a playlist.")
async def playlist_move(ctx, playlist: str, from_position: int, to_position: int, flags: Optional[str] = None):
    record_command(ctx)
    parsed_flags = parse_playlist_flags(flags)
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.response.send_message("Playlist not found or not visible to you.", ephemeral=True)
        return
    if not can_edit_playlist(ctx.user, target):
        await ctx.response.send_message("You do not have permission to edit that playlist.", ephemeral=True)
        return
    if not await confirm_admin_foreign_playlist(ctx, target, "song move", parsed_flags):
        await safe_interaction_send(ctx, "Song move cancelled.", ephemeral=True)
        return
    tracks = target.get("tracks", [])
    if from_position < 1 or from_position > len(tracks) or to_position < 1 or to_position > len(tracks):
        await safe_interaction_send(ctx, "Song positions must exist in the playlist.", ephemeral=True)
        return
    track = tracks.pop(from_position - 1)
    tracks.insert(to_position - 1, track)
    save_playlist(target)
    await safe_interaction_send(ctx, f"Moved **{discord.utils.escape_markdown(str(track.get('title') or 'Unknown title'))}** to position {to_position}.")

@app_commands.describe(playlist="Playlist name, id, or playlist:name", locked="Whether managers are blocked from editing")
@playlist_group.command(name="lock", description="Lock or unlock a playlist.")
async def playlist_lock(ctx, playlist: str, locked: bool):
    record_command(ctx)
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.response.send_message("Playlist not found or not visible to you.", ephemeral=True)
        return
    if not can_manage_playlist(ctx.user, target):
        await ctx.response.send_message("Only the owner or an admin can lock playlists.", ephemeral=True)
        return
    target["locked"] = bool(locked)
    save_playlist(target)
    state = "locked" if locked else "unlocked"
    await ctx.response.send_message(f"Playlist **{discord.utils.escape_markdown(target['name'])}** is now {state}.")

@app_commands.describe(playlist="Playlist name, id, or playlist:name")
@playlist_group.command(name="predownload", description="Admin-only future permanent playlist download hook.")
async def playlist_predownload(ctx, playlist: str):
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    await ctx.response.defer(ephemeral=True)
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.followup.send("Playlist not found.", ephemeral=True)
        return
    if not PLAYLIST_PREDOWNLOAD_ENABLED:
        await ctx.followup.send("Permanent playlist predownload is disabled on this bot.", ephemeral=True)
        return
    try:
        count = await predownload_playlist_files(target)
    except Exception as exc:
        logger.error(f"Playlist predownload failed for {target.get('name')} ({target.get('id')}): {exc}")
        await ctx.followup.send("Playlist predownload failed. Check output.log.", ephemeral=True)
        return
    await ctx.followup.send(
        f"Predownloaded {count} new file(s) for **{discord.utils.escape_markdown(target['name'])}**.",
        ephemeral=True,
    )

@client.tree.command()
async def purgequeue(ctx):
    """Removes all downloaded song files from disk, but keeps the queue intact."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        logger.warning(
            f"Denied /purgequeue by {user_display(ctx.user)} "
            f"({getattr(ctx.user, 'id', 0)}): admin required."
        )
        return
    count = 0
    current_id = client.current_track_id
    for vid, info in list(downloaded.items()):
        if vid == current_id:
            continue  # skip current playing track's file
        file_path = info.get('filepath')
        if remove_download_file(file_path, video_id=vid, reason="purgequeue"):
            count += 1
        downloaded.pop(vid, None)
    save_downloads_metadata("purgequeue")
    await ctx.response.send_message(f"Purged {count} files from disk.")

@client.tree.command()
async def volume(ctx, level: int):
    """Sets the audio playback volume (1-100)."""
    record_command(ctx)
    if not await require_voice_control(ctx, "change volume"):
        return
    if level < 1 or level > 100:
        await ctx.response.send_message("Volume must be between 1 and 100.")
        return
    client.volume = level / 100.0
    # If currently playing, adjust the volume on the fly
    if client.current_voice_channel and client.current_voice_channel.source:
        try:
            client.current_voice_channel.source.volume = client.volume
        except Exception as e:
            logger.error(f"Volume adjust error: {e}")
    await ctx.response.send_message(f"Volume set to {level}%")

@client.tree.command()
async def pause(ctx):
    """Pauses the current audio."""
    record_command(ctx)
    if not await require_voice_control(ctx, "pause playback"):
        return
    if client.current_voice_channel is None:
        logger.info("Pause command issued, but bot is not in a voice channel.")
        await ctx.response.send_message("Not currently in a voice channel")
    elif not client.currently_playing:
        await ctx.response.send_message("No audio is playing to pause")
    elif client.current_voice_channel.is_paused():
        logger.info("Pause command issued, but audio is already paused.")
        await ctx.response.send_message("Audio is already paused")
    else:
        client.current_voice_channel.pause()
        logger.info("Audio paused via /pause command.")
        await ctx.response.send_message("Audio paused")

@client.tree.command()
async def resume(ctx):
    """Resumes the current audio if paused."""
    record_command(ctx)
    if not await require_voice_control(ctx, "resume playback"):
        return
    if client.current_voice_channel is None:
        logger.info("Resume command issued, but bot is not in a voice channel.")
        await ctx.response.send_message("Not currently in a voice channel")
    elif not client.currently_playing:
        await ctx.response.send_message("No audio is playing to resume")
    elif client.current_voice_channel.is_paused():
        client.current_voice_channel.resume()
        logger.info("Audio playback resumed via /resume command.")
        await ctx.response.send_message("Resuming audio")
    else:
        logger.info("Resume command issued, but audio was not paused.")
        await ctx.response.send_message("Audio is not paused")

@client.tree.command()
async def stop(ctx):
    """Stops playback and disconnects the bot from the voice channel."""
    record_command(ctx)
    if not await require_voice_control(ctx, "stop playback"):
        return
    if client.current_voice_channel:
        try:
            ctx.guild.voice_client.stop()
        except Exception as e:
            logger.error(f"Error stopping voice client: {e}")
        logger.info("Stop command received: stopping playback and clearing queue.")
        queue.clear()
        await client.current_voice_channel.disconnect()
        client.current_voice_channel = None
        client.currently_playing = False
        await ctx.response.send_message("Vittuun täältä keilahallista")
        logger.info("Disconnected from voice channel (stop command executed).")
    else:
        logger.info("Stop command received while bot was not in a voice channel.")
        await ctx.response.send_message("Not currently in a voice channel")

@client.tree.command()
async def togglelog(ctx):
    """Toggles verbose (DEBUG level) logging on or off (admin only)."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    client.log_verbose = not client.log_verbose
    if client.log_verbose:
        logger.setLevel(logging.DEBUG)
        msg = "Verbose logging enabled."
    else:
        logger.setLevel(logging.INFO)
        msg = "Verbose logging disabled."
    await ctx.response.send_message(msg)
    logger.info(f"Logging level toggled by admin: {msg}")

@client.tree.command()
async def toggledownload(ctx):
    """Toggles between download-and-play mode and stream-only mode (admin only)."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    client.download_mode = not client.download_mode
    mode = "download-and-play" if client.download_mode else "stream-only"
    await ctx.response.send_message(f"Playback mode set to **{mode}**.")
    logger.info(f"Download mode toggled by admin: now {mode} mode")

@client.tree.command()
async def disablelinks(ctx):
    """Toggles queue link display on or off (admin only)."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    client.queue_links_disabled = not client.queue_links_disabled
    state = "disabled" if client.queue_links_disabled else "enabled"
    if client.current_track_message and client.current_track_info and client.current_track_message_show_queue:
        try:
            await client.current_track_message.edit(
                content=format_now_playing(client.current_track_info, show_queue=True)
            )
            logger.info("Refreshed open now-playing queue section after queue link toggle.")
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            logger.warning(f"Failed to refresh now-playing queue section after link toggle: {exc}")
    await ctx.response.send_message(f"Queue links are now **{state}**.")
    logger.info(f"Queue links toggled by admin: now {state}")

@client.tree.command(name="now")
async def now_cmd(ctx):
    """Displays the currently playing song."""
    record_command(ctx)
    if not client.currently_playing or not client.current_track_info:
        await ctx.response.send_message("No song is currently playing.")
    else:
        track = client.current_track_info
        title = track.get('title', 'Unknown title')
        vid = track.get('id', '')
        await ctx.response.send_message(f"Currently playing: **{title}** ({vid})")

@client.tree.command(name="nytsoi")
async def nytsoi_cmd(ctx):
    """Finnish alias for /now (shows the current song)."""
    record_command(ctx)
    if not client.currently_playing or not client.current_track_info:
        await ctx.response.send_message("No song is currently playing.")
    else:
        track = client.current_track_info
        title = track.get('title', 'Unknown title')
        vid = track.get('id', '')
        await ctx.response.send_message(f"Currently playing: **{title}** ({vid})")

@client.tree.command()
async def getqueue(ctx):
    """Displays all songs requested since the bot joined the current voice channel."""
    record_command(ctx)
    if not client.song_history:
        await ctx.response.send_message("No songs have been requested this session.")
        return
    lines = ["Songs requested this session:"]
    for i, track in enumerate(client.song_history, start=1):
        title = track.get('title', 'Unknown title')
        vid = track.get('id', '')
        status = ""
        if client.current_track_info and vid == client.current_track_info.get('id'):
            status = "(playing now)"
        elif vid in client.played_tracks:
            status = "(played)"
        elif any(qt.get('id') == vid for qt in queue):
            status = "(queued)"
        else:
            status = "(removed)"
        lines.append(f"{i}. {title} ({vid}) {status}")
    await ctx.response.send_message("\n".join(lines))

@client.tree.command()
async def reboot(ctx):
    """Saves the current queue and reboots the bot (admin only, requires confirmation)."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    # Prompt for reboot confirmation
    await ctx.response.send_message("Confirm reboot? React with 👍 to confirm, or 👎 to cancel.")
    reboot_msg = await ctx.original_response()
    try:
        await reboot_msg.add_reaction("👍")
        await reboot_msg.add_reaction("👎")
    except Exception as e:
        logger.error(f"Failed to add reactions for reboot confirmation: {e}")
    def check(reaction, user):
        return user == ctx.user and str(reaction.emoji) in ["👍", "👎"] and reaction.message.id == reboot_msg.id
    try:
        reaction, user = await client.wait_for('reaction_add', timeout=15.0, check=check)
    except asyncio.TimeoutError:
        await ctx.followup.send("Reboot cancelled (no response).")
        return
    if str(reaction.emoji) == "👍":
        # Save queue and current track to backup file
        backup_data = {"queue": queue, "current_track": client.current_track_info}
        try:
            with open("queue_backup.json", "w") as f:
                json.dump(backup_data, f, default=str)
        except Exception as e:
            logger.error(f"Failed to save queue backup: {e}")
        await ctx.followup.send("Rebooting now...")
        logger.info("Rebooting bot by admin request...")
        # Disconnect from voice and close the bot
        try:
            if client.current_voice_channel:
                await client.current_voice_channel.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting voice client on reboot: {e}")
        await client.close()
        os._exit(0)
    else:
        await ctx.followup.send("Reboot cancelled.")
        logger.info("Reboot cancelled by admin.")

@client.tree.command()
async def restorequeue(ctx):
    """Restores the last cleared or saved queue (admin only, within 10 minutes)."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    restored = False
    # Check in-memory backup from clear_queue
    if client.queue_backup and client.backup_timestamp and time.time() - client.backup_timestamp <= 600:
        if queue:
            await ctx.response.send_message("Cannot restore: the queue is not empty.")
            return
        for track in client.queue_backup:
            queue.append(track)
            if track not in client.song_history:
                client.song_history.append(track)
        client.queue_backup = None
        client.backup_timestamp = None
        await ctx.response.send_message("Queue restored from recent clear.")
        logger.info("Queue restored by admin from in-memory backup.")
        restored = True
    # If not restored from memory, check if there's a backup file from reboot
    if not restored:
        if os.path.isfile("queue_backup.json"):
            try:
                timestamp = os.path.getmtime("queue_backup.json")
                with open("queue_backup.json", "r") as f:
                    backup_data = json.load(f)
                if time.time() - timestamp <= 600:
                    if queue:
                        await ctx.response.send_message("Cannot restore: the queue is not empty.")
                        return
                    saved_queue = backup_data.get("queue", [])
                    current_track = backup_data.get("current_track")
                    for track in saved_queue:
                        queue.append(track)
                        if track not in client.song_history:
                            client.song_history.append(track)
                    if current_track:
                        queue.insert(0, current_track)
                        if current_track not in client.song_history:
                            client.song_history.append(current_track)
                    await ctx.response.send_message("Queue restored from reboot backup.")
                    logger.info("Queue restored by admin from file backup.")
                else:
                    await ctx.response.send_message("Backup from reboot is older than 10 minutes and cannot be restored.")
                # Remove the backup file after attempting restore (to avoid stale restores later)
                os.remove("queue_backup.json")
            except Exception as e:
                logger.error(f"Failed to restore from backup file: {e}")
                await ctx.response.send_message("Failed to restore backup due to an error.")
        else:
            await ctx.response.send_message("No queue backup available to restore.")

# Backup quotes command
@client.tree.command()
async def backup_teekkari_quotes(ctx):
    """Backs up all quotes from the Teekkari quotes channel."""
    record_command(ctx)
    await ctx.response.defer(thinking=True)
    if QUOTES_ID == 0:
        await safe_interaction_send(ctx, "Quotes backup is disabled because QUOTES_ID=0.")
        return
    channel = client.get_channel(QUOTES_ID)
    if channel is None:
        await safe_interaction_send(ctx, "Quotes channel is not accessible. Check QUOTES_ID.")
        return
    count = await save_all_channel_messages(channel)
    await safe_interaction_send(ctx, f"Quotes backup completed ({count} messages scanned).")
    logger.info("Teekkari quotes backed up by command.")

# Random quote command
@client.tree.command()
async def random_quote(ctx):
    """Gets a random Teekkari quote."""
    record_command(ctx)
    message = quotes.getRandomQuote()
    await ctx.response.send_message(message)
    logger.info("User requested random teekkari quote.")

@client.tree.command()
async def help(ctx):
    """Displays the list of available commands and their usage."""
    record_command(ctx)
    await ctx.response.send_message(compact_help_message())
    message = await ctx.original_response()
    client.help_message_id = message.id
    client.help_expanded = False
    try:
        await message.add_reaction(HELP_EXPAND_REACTION)
    except Exception as exc:
        logger.warning(f"Failed to add help expand reaction: {exc}")

@app_commands.describe(view="latest, session, or commands")
@app_commands.choices(view=[
    app_commands.Choice(name="latest", value="latest"),
    app_commands.Choice(name="session", value="session"),
    app_commands.Choice(name="commands", value="commands"),
])
@client.tree.command()
async def status(ctx, view: str = "latest"):
    """Displays runtime diagnostics (admin only)."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    await ctx.response.send_message(build_status_message(view), ephemeral=True)

client.tree.add_command(playlist_group)

@client.tree.error
async def on_app_command_error(ctx, error):
    # Global error handler for app commands
    logger.exception(f"Error in /{ctx.command.name}: {error}")
    await safe_interaction_send(ctx, "💥  Oops, something went wrong. Please check the bot logs for details.")

if __name__ == "__main__":
    client.run(BOT_TOKEN)
