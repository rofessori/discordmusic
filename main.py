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
import math
import importlib.util
from dataclasses import dataclass, field
from typing import Optional

# Setup logging (default to INFO level; can be toggled to DEBUG via /togglelog)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SAFE_MEDIA_EXTENSIONS = {
    ".aac", ".flac", ".m4a", ".mka", ".mkv", ".mp3", ".mp4", ".ogg",
    ".opus", ".wav", ".webm",
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)
downloads_file = os.path.join(BASE_DIR, "downloads.json")
LAST_SESSION_QUEUE_FILE = os.path.join(BASE_DIR, "last_session_queue.tmp.json")
PLAYLISTS_DIR = os.path.join(BASE_DIR, "playlists")
PLAYLIST_BLACKBOX_FILE = os.path.join(BASE_DIR, "playlists-blackbox.json")
QUEUE_BLACKBOX_FILE = os.path.join(BASE_DIR, "queue-blackbox.json")
RUNTIME_AUDIT_FILE = os.path.join(BASE_DIR, "runtime-audit.json")
PLAYLIST_CACHE_POLICY_FILE = os.path.join(BASE_DIR, "playlist-cache-policy.json")
CHANNEL_VOLUME_CONFIG_FILE = os.path.join(BASE_DIR, "channel-volume-config.json")
USER_PERMISSIONS_FILE = os.path.join(BASE_DIR, "user-permissions.json")
RECENT_UPDATES_FILE = os.path.join(BASE_DIR, "RECENT_UPDATES.md")
youtube_base_url = 'https://www.youtube.com/'
youtube_base_url_2 = 'https://youtu.be/'
youtube_watch_url = youtube_base_url + 'watch?v='
PLAYLIST_PAGE_SIZE = 6
PLAYLIST_TRACK_PAGE_SIZE = 8
PLAYLIST_PAGE_REACTIONS = ("◀️", "▶️")
PLAYLIST_DELETE_GRACE_SECONDS = 600
PLAYLIST_NAME_MAX_LENGTH = 80
PLAYLIST_CREATION_TIMEOUT_SECONDS = 300
PLAYLIST_CREATION_FINISH_WORDS = {"done", "finish", "valmis", "loppu", "stop"}
PLAYLIST_CREATION_CANCEL_WORDS = {"cancel", "peru", "abort"}
PLAYLIST_QUEUE_IMPORT_MODES = {"current", "currentqueue", "jono"}
PLAYLIST_CACHE_MODES = {"follow_global", "streaming", "bounded", "keep_cached"}
GLOBAL_PLAYLIST_CACHE_MODES = {"streaming", "bounded", "keep_cached"}
DEFAULT_PLAYLIST_CACHE_MODE = "bounded"
PLAYLIST_CACHE_BOUNDED_TRACK_LIMIT = 15
PLAYLIST_CACHE_BOUNDED_BYTES = 3 * 1024 * 1024 * 1024
CACHE_HARD_LIMIT_BYTES = 20 * 1024 * 1024 * 1024
FAVORITES_CACHE_DEFAULT_MAX_BYTES = 6 * 1024 * 1024 * 1024
FAVORITES_CACHE_MAX_BYTES = 6 * 1024 * 1024 * 1024
FAVORITES_CACHE_DEFAULT_TRACKS_PER_USER = 30
FAVORITES_MAX_TRACKS_PER_USER = 100
DEFAULT_VOLUME_LEVEL = 20
MIN_VOLUME_LEVEL = 1
MAX_VOLUME_LEVEL = 100
SAFE_VOLUME_MAX_LEVEL = 50
MAX_PLAY_REPEAT_COUNT = 20
MIN_PLAYBACK_SPEED = 0.1
MAX_PLAYBACK_SPEED = 2.0
DEFAULT_NOWPLAYING_COOLDOWN_SECONDS = 30
NOWPLAYING_COOLDOWN_MIN_SECONDS = 5
NOWPLAYING_COOLDOWN_MAX_SECONDS = 300
DEFAULT_BOT_PRESENCE = "/play (yt-link)"
UNKNOWN_BOT_PRESENCE = "???"
BOT_PRESENCE_MAX_LENGTH = 120
LAST_SESSION_RECOVERY_MAX_AGE_SECONDS = 1800
VOICE_VOTE_TIMEOUT_SECONDS = 45
REPEAT_TOGGLE_RECENT_SECONDS = 300
REPEAT_TOGGLE_VOTE_THRESHOLD = 2
HELP_EXPAND_REACTION = "📖"
DEBUG_COLLAPSE_REACTION = "🧹"
HELP_PAGE_REACTIONS = ("◀️", "▶️")
CONFIG_REACTIONS = ("🎧", "📥", "🔍", "🧭", "🔗", "🚪", "⭐", "🌐", "📦", "🏃", "⏱️", "📊", "🗳️")
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}

def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in TRUTHY_ENV_VALUES

def env_int(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        parsed = int(value.strip())
    except ValueError:
        raise RuntimeError(f"{name} must be a number.") from None
    if parsed < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}.")
    return parsed

PLAYLIST_PREDOWNLOAD_ENABLED = (
    env_flag("PLAYLIST_PREDOWNLOAD_ENABLED")
)
YTDLP_NO_CHECK_CERTIFICATE = env_flag("YTDLP_NO_CHECK_CERTIFICATE", False)
ALLOW_ADMIN_ROLE_NAME = env_flag("ALLOW_ADMIN_ROLE_NAME", False)
MAX_PLAYLIST_TRACKS = env_int("MAX_PLAYLIST_TRACKS", 100)
MAX_URLS_PER_MESSAGE = env_int("MAX_URLS_PER_MESSAGE", 10)
YOUTUBE_PLAYLIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,128}$")
YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,32}$")

def display_path(path: str) -> str:
    try:
        return os.path.relpath(path, BASE_DIR)
    except ValueError:
        return path

def path_from_metadata(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    path = str(path)
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)

def metadata_path_for_cache_file(file_path: str) -> str:
    return display_path(file_path).replace(os.sep, "/")

def is_valid_cache_key(cache_key: Optional[str]) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{16,256}", str(cache_key or "")))

def is_safe_cache_path(file_path: str, expected_cache_key: Optional[str] = None) -> bool:
    """Only trust media files that resolve inside the root cache directory."""
    if not file_path:
        return False
    try:
        resolved = path_from_metadata(file_path)
        if not resolved:
            return False
        if os.path.islink(resolved):
            return False
        real_base = os.path.realpath(CACHE_DIR)
        real_path = os.path.realpath(resolved)
        if os.path.commonpath([real_base, real_path]) != real_base:
            return False
        if not os.path.isfile(real_path):
            return False
        filename = os.path.basename(real_path)
        stem, ext = os.path.splitext(filename)
        if ext.lower() not in SAFE_MEDIA_EXTENSIONS:
            return False
        if expected_cache_key:
            if not is_valid_cache_key(expected_cache_key):
                return False
            allowed_stems = {expected_cache_key, f"plst-{expected_cache_key}"}
            if stem not in allowed_stems:
                return False
        return True
    except (OSError, ValueError):
        return False

def is_safe_download_path(file_path: str, video_id: Optional[str] = None) -> bool:
    """Compatibility wrapper for normal downloaded-cache deletion checks."""
    expected_cache_key = canonical_cache_key_from_video_id(video_id) if video_id else None
    return is_safe_cache_path(file_path, expected_cache_key)

def remove_download_file(file_path: str, *, video_id: Optional[str] = None, reason: str = "") -> bool:
    """Remove a tracked media file only after path validation."""
    if not file_path:
        return False
    if not is_safe_download_path(file_path, video_id):
        logger.warning(
            f"Skipped unsafe download deletion path for {video_id or 'unknown'} "
            f"during {reason or 'cleanup'}: {file_path}"
        )
        append_runtime_audit_event("media-delete-skipped", details={
            "video_id": video_id,
            "reason": reason or "cleanup",
            "path": file_path,
            "safe": False,
        })
        return False
    try:
        os.remove(file_path)
        logger.info(f"Removed downloaded media file during {reason or 'cleanup'}: {file_path}")
        append_runtime_audit_event("media-file-deleted", details={
            "video_id": video_id,
            "reason": reason or "cleanup",
            "path": file_path,
        })
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

SENSITIVE_AUDIT_KEY_PARTS = ("token", "secret", "password", "cookie", "authorization")

def sanitize_audit_value(key: str, value):
    key_lower = str(key or "").lower()
    if any(part in key_lower for part in SENSITIVE_AUDIT_KEY_PARTS):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(item_key)[:80]: sanitize_audit_value(str(item_key), item_value)
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_audit_value(key, item) for item in list(value)[:50]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(value)
    if key_lower.endswith("path") or key_lower in {"file", "file_path", "cache_file", "cache_path"}:
        candidate = path_from_metadata(text)
        try:
            real_base = os.path.realpath(BASE_DIR)
            real_path = os.path.realpath(candidate)
            if os.path.commonpath([real_base, real_path]) == real_base:
                return display_path(real_path).replace(os.sep, "/")
        except Exception:
            pass
    bot_token = globals().get("BOT_TOKEN")
    cookiefile = globals().get("YTDLP_COOKIEFILE")
    text = text.replace(bot_token, "<bot-token>") if bot_token else text
    text = text.replace(cookiefile, "<yt-dlp-cookiefile>") if cookiefile else text
    return truncate_text(text, 500) if "truncate_text" in globals() else text[:500]

def sanitize_audit_details(details: Optional[dict]) -> dict:
    if not isinstance(details, dict):
        return {}
    return {str(key)[:80]: sanitize_audit_value(str(key), value) for key, value in details.items()}

def append_runtime_audit_event(action: str, *, actor=None, details: Optional[dict] = None):
    entry = {
        "timestamp": time.time(),
        "action": str(action or "unknown"),
        "boot_id": getattr(globals().get("client"), "boot_id", None),
        "actor_user_id": user_id_value(actor) if actor else None,
        "actor_discord_name": user_display(actor) if actor else None,
        "details": sanitize_audit_details(details),
    }
    try:
        events = []
        if os.path.isfile(RUNTIME_AUDIT_FILE):
            with open(RUNTIME_AUDIT_FILE, "r") as f:
                loaded = json.load(f)
            if not isinstance(loaded, list):
                logger.error("Runtime audit file is not a JSON list; preserving it without appending.")
                return
            events = loaded
        events.append(entry)
        write_json_atomic(RUNTIME_AUDIT_FILE, events)
        logger.info(f"Runtime audit: {entry['action']} details={entry['details']}")
    except Exception as exc:
        logger.error(f"Failed to append runtime audit event: {exc}")

def canonical_youtube_url(video_id: str) -> str:
    return youtube_watch_url + str(video_id or "").strip()

def base64url_cache_key(value: str) -> str:
    return base64.urlsafe_b64encode(str(value).encode("utf-8")).decode("ascii").rstrip("=")

def canonical_cache_key_from_video_id(video_id: Optional[str]) -> Optional[str]:
    if not video_id:
        return None
    return base64url_cache_key(canonical_youtube_url(video_id))

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
    'outtmpl': os.path.join(CACHE_DIR, '%(id)s.%(ext)s'),
    'restrictfilenames': True,
    'noplaylist': True,
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
if YTDLP_NO_CHECK_CERTIFICATE:
    ytdl_options['nocheckcertificate'] = True
YTDLP_JS_RUNTIMES = {}
deno_path = shutil.which("deno")
if deno_path:
    YTDLP_JS_RUNTIMES['deno'] = {'path': deno_path}
node_path = shutil.which("node")
if node_path:
    YTDLP_JS_RUNTIMES['node'] = {'path': node_path}
if YTDLP_JS_RUNTIMES:
    ytdl_options['js_runtimes'] = YTDLP_JS_RUNTIMES
YTDLP_COOKIEFILE = os.getenv("YTDLP_COOKIEFILE") or os.getenv("ytdlp_cookiefile")
if YTDLP_COOKIEFILE:
    if not os.path.isabs(YTDLP_COOKIEFILE):
        YTDLP_COOKIEFILE = os.path.join(BASE_DIR, YTDLP_COOKIEFILE)
    ytdl_options['cookiefile'] = YTDLP_COOKIEFILE
ytdl = yt_dlp.YoutubeDL(ytdl_options)

# Setup ffmpeg options for Discord audio
FFMPEG_RECONNECT_OPTIONS = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'

def normalize_playback_speed(value) -> tuple:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return None, f"Playback speed must be a number from {MIN_PLAYBACK_SPEED:g} to {MAX_PLAYBACK_SPEED:g}."
    if speed < MIN_PLAYBACK_SPEED or speed > MAX_PLAYBACK_SPEED:
        return None, f"Playback speed must be between {MIN_PLAYBACK_SPEED:g} and {MAX_PLAYBACK_SPEED:g}."
    return round(speed, 3), None

def atempo_filter_for_speed(speed: float) -> str:
    speed = float(speed or 1.0)
    factors = []
    while speed < 0.5:
        factors.append(0.5)
        speed /= 0.5
    while speed > 2.0:
        factors.append(2.0)
        speed /= 2.0
    factors.append(speed)
    return ",".join(f"atempo={factor:.6g}" for factor in factors)

def ffmpeg_audio_options_for_speed(speed: Optional[float] = None, *, reconnect: bool = False) -> dict:
    speed = float(speed or 1.0)
    options = "-vn"
    if abs(speed - 1.0) > 0.001:
        options += f" -filter:a {atempo_filter_for_speed(speed)}"
    result = {"options": options}
    if reconnect:
        result["before_options"] = FFMPEG_RECONNECT_OPTIONS
    return result

ffmpeg_options = ffmpeg_audio_options_for_speed(1.0, reconnect=True)

def playback_speed_for_track(track: Optional[dict] = None) -> float:
    raw_speed = (track or {}).get("playback_speed") if track else None
    speed, _ = normalize_playback_speed(raw_speed if raw_speed is not None else getattr(client, "playback_speed", 1.0))
    return speed or 1.0

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
FAVORITE_REACTION = "⭐"
QUEUE_REACTION = "📜"
REPEAT_REACTION = "🔂"
CONTROL_REACTIONS = (FAVORITE_REACTION, "◀️", "⏸️", "▶️", REPEAT_REACTION, QUEUE_REACTION)
DISCORD_MESSAGE_SAFE_LIMIT = 1900
MAX_QUEUE_LENGTH = 50
MIN_FREE_DOWNLOAD_MB = 512
DOWNLOAD_DELETE_DELAY_MIN_SECONDS = 0
DOWNLOAD_DELETE_DELAY_MAX_SECONDS = 86400
AUTO_LEAVE_DEFAULT_DELAY_SECONDS = 10
AUTO_LEAVE_MIN_DELAY_SECONDS = 5
AUTO_LEAVE_MAX_DELAY_SECONDS = 3600

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

USER_RESTRICTION_GROUPS = {
    "nodownload",
    "novolumechange",
    "noplaylistcreate",
    "noqueueskip",
    "noskip",
    "norepeat",
    "playspeed",
}
NOWPLAYING_COOLDOWN_CHOICES = (5, 10, 20, 30, 60, 120, 300)

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{27,}$")
MIN_DISCORD_PY_VERSION = (2, 6, 0)
MIN_YTDLP_VERSION = (2026, 3, 17)

def coerce_duration_seconds(value, label: str, *, default: int, minimum: int, maximum: int) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        raise RuntimeError(f"{label} must be a whole number of seconds.") from None
    if seconds < minimum or seconds > maximum:
        raise RuntimeError(f"{label} must be between {minimum} and {maximum} seconds.")
    return seconds

DEFAULT_DOWNLOAD_DELETE_DELAY_SECONDS = coerce_duration_seconds(
    get_env_value("DOWNLOAD_DELETE_DELAY_SECONDS", "download_delete_delay_seconds", default="600", required=False),
    "DOWNLOAD_DELETE_DELAY_SECONDS",
    default=600,
    minimum=DOWNLOAD_DELETE_DELAY_MIN_SECONDS,
    maximum=DOWNLOAD_DELETE_DELAY_MAX_SECONDS,
)

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

def youtube_url_parts(query: str) -> tuple:
    try:
        parsed = urllib.parse.urlparse(str(query or "").strip())
    except Exception:
        return None, {}
    host = (parsed.hostname or parsed.netloc or "").lower().rstrip(".")
    if not is_youtube_host(host):
        return parsed, {}
    return parsed, urllib.parse.parse_qs(parsed.query)

def parse_youtube_playlist_id(query: str) -> Optional[str]:
    """Return a YouTube playlist id from a URL's list= parameter."""
    parsed, qs = youtube_url_parts(query)
    if not parsed or not qs:
        return None
    playlist_id = str((qs.get("list") or [""])[0]).strip()
    if playlist_id and YOUTUBE_PLAYLIST_ID_PATTERN.fullmatch(playlist_id):
        return playlist_id
    return None

def parse_youtube_playlist_index(query: str) -> Optional[int]:
    parsed, qs = youtube_url_parts(query)
    if not parsed or not qs:
        return None
    try:
        index = int(str((qs.get("index") or [""])[0]).strip())
    except ValueError:
        return None
    return index if index > 0 else None

def is_youtube_playlist_url(query: str) -> bool:
    return bool(parse_youtube_playlist_id(query))

def normalize_youtube_query(query: str):
    """Normalize YouTube URLs for caching; leave search text for yt-dlp's ytsearch1."""
    query = validate_media_query(query)
    video_id = parse_youtube_video_id(query)
    if video_id:
        return youtube_watch_url + video_id, video_id
    return query, None

def cache_key_for_youtube_url(url: str) -> Optional[str]:
    video_id = parse_youtube_video_id(url)
    if not video_id:
        return None
    return canonical_cache_key_from_video_id(video_id)

def cache_key_for_track(track: dict) -> Optional[str]:
    cache_key = str(track.get("cache_key") or "").strip()
    if is_valid_cache_key(cache_key):
        return cache_key
    if cache_key:
        logger.warning(
            f"Ignoring invalid cache key for {track.get('title', 'Unknown title')}: {cache_key[:80]}"
        )
    video_id = str(track.get("id") or "").strip()
    if video_id:
        return canonical_cache_key_from_video_id(video_id)
    return cache_key_for_youtube_url(str(track.get("webpage_url") or ""))

def cache_filename(cache_key: str, ext: str, *, playlist: bool = False) -> str:
    clean_ext = str(ext or "").lstrip(".").lower()
    prefix = "plst-" if playlist else ""
    return f"{prefix}{cache_key}.{clean_ext}"

def cache_path_for_key(cache_key: str, ext: str, *, playlist: bool = False) -> str:
    return os.path.join(CACHE_DIR, cache_filename(cache_key, ext, playlist=playlist))

def human_bytes(num_bytes: Optional[float]) -> str:
    try:
        value = float(num_bytes or 0)
    except (TypeError, ValueError):
        value = 0.0
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if abs(value) < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0

def cache_file_size(file_path: str) -> int:
    try:
        if is_safe_cache_path(file_path):
            return os.path.getsize(path_from_metadata(file_path))
    except OSError:
        pass
    return 0

def cache_total_bytes() -> int:
    total = 0
    if not os.path.isdir(CACHE_DIR):
        return 0
    for filename in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, filename)
        if is_safe_cache_path(path):
            try:
                total += os.path.getsize(path)
            except OSError:
                continue
    return total

def cache_has_room(projected_bytes: int = 0) -> bool:
    return cache_total_bytes() + max(0, projected_bytes or 0) <= CACHE_HARD_LIMIT_BYTES

def find_legacy_cache_file(video_id: Optional[str], *, prefer_playlist: bool = True) -> tuple:
    if not video_id or not os.path.isdir(CACHE_DIR):
        return None, False
    try:
        filenames = os.listdir(CACHE_DIR)
    except OSError as exc:
        logger.warning(f"Could not inspect cache directory for legacy file: {exc}")
        return None, False
    stems = [f"plst-{video_id}", video_id] if prefer_playlist else [video_id, f"plst-{video_id}"]
    for stem in stems:
        for filename in filenames:
            file_stem, ext = os.path.splitext(filename)
            if file_stem != stem or ext.lower() not in SAFE_MEDIA_EXTENSIONS:
                continue
            path = os.path.join(CACHE_DIR, filename)
            if is_safe_cache_path(path):
                return path, stem.startswith("plst-")
    return None, False

def adopt_legacy_cache_file(video_id: Optional[str], cache_key: Optional[str], *, prefer_playlist: bool = True) -> Optional[str]:
    legacy_path, playlist = find_legacy_cache_file(video_id, prefer_playlist=prefer_playlist)
    if not legacy_path or not cache_key:
        return None
    ext = os.path.splitext(legacy_path)[1].lstrip(".").lower()
    target_path = cache_path_for_key(cache_key, ext, playlist=playlist)
    if os.path.realpath(legacy_path) == os.path.realpath(target_path):
        return legacy_path
    if os.path.exists(target_path):
        logger.info(
            f"Legacy cache file exists for {video_id}, but canonical cache file already exists: "
            f"legacy={metadata_path_for_cache_file(legacy_path)} canonical={metadata_path_for_cache_file(target_path)}"
        )
        return target_path if is_safe_cache_path(target_path, cache_key) else None
    try:
        os.replace(legacy_path, target_path)
    except OSError as exc:
        logger.warning(
            f"Could not adopt legacy cache file for {video_id}: "
            f"{metadata_path_for_cache_file(legacy_path)} -> {metadata_path_for_cache_file(target_path)}: {exc}"
        )
        return None
    logger.info(
        f"Adopted legacy cache file for {video_id}: "
        f"{metadata_path_for_cache_file(legacy_path)} -> {metadata_path_for_cache_file(target_path)}"
    )
    append_runtime_audit_event("cache-legacy-adopted", details={
        "video_id": video_id,
        "from_path": metadata_path_for_cache_file(legacy_path),
        "to_path": metadata_path_for_cache_file(target_path),
    })
    return target_path if is_safe_cache_path(target_path, cache_key) else None

def find_existing_cache_file(cache_key: Optional[str], *, prefer_playlist: bool = True, video_id: Optional[str] = None) -> Optional[str]:
    if not cache_key or not os.path.isdir(CACHE_DIR):
        return None
    if not is_valid_cache_key(cache_key):
        logger.warning(f"Cache lookup skipped invalid cache key: {str(cache_key)[:80]}")
        return None
    try:
        filenames = os.listdir(CACHE_DIR)
    except OSError as exc:
        logger.warning(f"Could not inspect cache directory: {exc}")
        return None
    prefixes = [f"plst-{cache_key}.", f"{cache_key}."] if prefer_playlist else [f"{cache_key}.", f"plst-{cache_key}."]
    for prefix in prefixes:
        for filename in filenames:
            if not filename.startswith(prefix):
                continue
            path = os.path.join(CACHE_DIR, filename)
            if is_safe_cache_path(path, cache_key):
                logger.debug(f"Cache hit for key={cache_key}: {metadata_path_for_cache_file(path)}")
                return path
    adopted = adopt_legacy_cache_file(video_id, cache_key, prefer_playlist=prefer_playlist)
    if adopted:
        return adopted
    logger.debug(f"Cache miss for key={cache_key} video_id={video_id or '-'}")
    return None

def apply_cache_fields(track: dict, file_path: Optional[str], *, cache_mode: str):
    cache_key = cache_key_for_track(track)
    if cache_key:
        track["cache_key"] = cache_key
    track["cache_mode"] = cache_mode
    if file_path and is_safe_cache_path(file_path, cache_key):
        ext = os.path.splitext(path_from_metadata(file_path))[1].lstrip(".").lower()
        track["file"] = path_from_metadata(file_path)
        track["cache_path"] = metadata_path_for_cache_file(path_from_metadata(file_path))
        track["ext"] = ext
    else:
        track.pop("file", None)
        track["cache_path"] = None
        track["ext"] = None
    return track

def cached_file_for_track(track: dict, *, prefer_playlist: bool = True) -> Optional[str]:
    cache_key = cache_key_for_track(track)
    video_id = str(track.get("id") or "").strip() or None
    cache_path = track.get("cache_path")
    if cache_path and is_safe_cache_path(cache_path, cache_key):
        return path_from_metadata(cache_path)
    return find_existing_cache_file(cache_key, prefer_playlist=prefer_playlist, video_id=video_id)

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

@dataclass
class PlaylistCreationSession:
    user_id: int
    guild_id: int
    channel_id: int
    step: str
    name: str = ""
    tracks: list = None
    playlist_id: str = ""
    append_to_existing: bool = False
    started_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self):
        if self.tracks is None:
            self.tracks = []

@dataclass
class VoiceVote:
    key: tuple
    action: str
    title: str
    voice_channel_id: int
    text_channel_id: int
    value: Optional[int] = None
    track_id: str = ""
    message_id: int = 0
    message: object = None
    votes: set = field(default_factory=set)
    no_votes: set = field(default_factory=set)
    created_at: float = 0.0
    expires_at: float = 0.0
    task: object = None

@dataclass
class PurgeCacheResult:
    scanned: int = 0
    removed: int = 0
    removed_bytes: int = 0
    kept_current: int = 0
    skipped_unsafe: int = 0
    failed: int = 0
    metadata_removed: int = 0

@dataclass
class DebugPlaybackMessage:
    message: object
    normal_content: str
    stage: str = "starting"
    title: str = ""
    video_id: str = ""
    cache_state: str = ""
    format_id: str = ""
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: Optional[float] = None
    status: str = "active"
    error: str = ""
    last_edit_at: float = 0.0
    events: list = field(default_factory=list)

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
            "ADMIN_USERNAME is configured but ignored for security. Use ADMIN_USER_ID or ADMIN_ROLE_ID."
        )
    if ALLOW_ADMIN_ROLE_NAME:
        report.warnings.append(
            "ALLOW_ADMIN_ROLE_NAME is enabled. Use ADMIN_USER_ID or ADMIN_ROLE_ID for production admin access."
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
        os.makedirs(CACHE_DIR, exist_ok=True)
        test_path = os.path.join(CACHE_DIR, f".write-test-{os.getpid()}")
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
        cache_mb = cache_total_bytes() // (1024 * 1024)
        limit_mb = CACHE_HARD_LIMIT_BYTES // (1024 * 1024)
        if cache_total_bytes() > CACHE_HARD_LIMIT_BYTES:
            report.warnings.append(
                f"Cache directory is over the hard cap ({cache_mb} MB / {limit_mb} MB); new downloads will stream."
            )
        else:
            report.notes.append(f"Cache storage available ({cache_mb} MB / {limit_mb} MB used).")
    except OSError as exc:
        report.errors.append(f"Cannot write media cache at {CACHE_DIR}: {exc}")

    try:
        os.makedirs(PLAYLISTS_DIR, exist_ok=True)
        test_path = os.path.join(PLAYLISTS_DIR, f".write-test-{os.getpid()}")
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
        report.notes.append("Playlist storage available.")
    except OSError as exc:
        report.errors.append(f"Cannot write playlist storage at {PLAYLISTS_DIR}: {exc}")

    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        test_path = os.path.join(BASE_DIR, f".volume-write-test-{os.getpid()}")
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
        report.notes.append("Channel volume config storage available.")
    except OSError as exc:
        report.errors.append(f"Cannot write channel volume config in {BASE_DIR}: {exc}")

    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        test_path = os.path.join(BASE_DIR, f".user-permissions-write-test-{os.getpid()}")
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
        report.notes.append("User permissions config storage available.")
    except OSError as exc:
        report.errors.append(f"Cannot write user permissions config in {BASE_DIR}: {exc}")

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
    if isinstance(user, int):
        return bool(ADMIN_USER_ID and user == ADMIN_USER_ID)
    if isinstance(user, str) and user.isdigit():
        return bool(ADMIN_USER_ID and int(user) == ADMIN_USER_ID)
    # 1) role-based check
    for role in getattr(user, "roles", []):
        if ADMIN_ROLE_ID and getattr(role, "id", None) == ADMIN_ROLE_ID:
            return True
        if ALLOW_ADMIN_ROLE_NAME and ADMIN_ROLE_NAME and role.name == ADMIN_ROLE_NAME:
            return True
    # 2) optional user-based check (only if you set ADMIN_USER_ID)
    user_id = getattr(user, "id", None)
    if ADMIN_USER_ID and user_id == ADMIN_USER_ID:
        return True
    return False

def voice_client_is_connected(voice) -> bool:
    if voice is None:
        return False
    try:
        return bool(voice.is_connected())
    except Exception as exc:
        logger.warning(f"Voice client connection check failed: {exc}")
        return False


def same_guild(left, right) -> bool:
    if left is None or right is None:
        return False
    left_id = getattr(left, "id", None)
    right_id = getattr(right, "id", None)
    if left_id is not None and right_id is not None:
        return left_id == right_id
    return left == right


def active_voice_client(guild=None):
    """Return the live voice client and repair stale local tracking."""
    current = getattr(client, "current_voice_channel", None)
    guild_voice = getattr(guild, "voice_client", None) if guild is not None else None

    if voice_client_is_connected(guild_voice):
        if current is not guild_voice:
            logger.info("Synchronized tracked voice client from guild voice state.")
        client.current_voice_channel = guild_voice
        return guild_voice

    if voice_client_is_connected(current):
        current_guild = getattr(current, "guild", None)
        if guild is None or current_guild is None or same_guild(current_guild, guild):
            return current

    if current is not None:
        logger.warning("Cleared stale tracked voice client; no connected guild voice client was available.")
        client.current_voice_channel = None
    return None


def user_in_bot_voice_channel(user) -> bool:
    voice = active_voice_client(getattr(user, "guild", None))
    bot_channel = getattr(voice, "channel", None)
    user_channel = getattr(getattr(user, "voice", None), "channel", None)
    return bool(
        bot_channel
        and user_channel
        and getattr(bot_channel, "id", None) == getattr(user_channel, "id", None)
    )

def can_control_voice(user) -> bool:
    if is_user_admin(user):
        return True
    if active_voice_client(getattr(user, "guild", None)) is None:
        return True
    return user_in_bot_voice_channel(user)

def user_id_value(user) -> int:
    if isinstance(user, int):
        return user
    if isinstance(user, str) and user.isdigit():
        return int(user)
    return int(getattr(user, "id", 0) or 0)

def user_permissions_entry(user, *, create: bool = False) -> dict:
    uid = user_id_value(user)
    if not uid:
        return {}
    users = client.user_permissions_config.setdefault("users", {})
    key = str(uid)
    if create:
        return users.setdefault(key, {"groups": [], "favorite_cache_enabled": None})
    return users.get(key, {})

def user_groups(user) -> set:
    entry = user_permissions_entry(user)
    return {
        str(group).lower()
        for group in entry.get("groups", [])
        if str(group).lower() in USER_RESTRICTION_GROUPS
    }

def user_has_group(user, group: str) -> bool:
    return str(group).lower() in user_groups(user)

def can_use_play_speed(user) -> bool:
    return is_user_admin(user) or getattr(client, "playspeed_allow_all", False) or user_has_group(user, "playspeed")

def favorite_cache_allowed_for_user(user) -> bool:
    entry = user_permissions_entry(user)
    value = entry.get("favorite_cache_enabled")
    return False if value is False else True

def add_user_group(user, group: str, actor=None):
    group = str(group or "").lower()
    if group not in USER_RESTRICTION_GROUPS:
        raise ValueError("Unknown user group.")
    entry = user_permissions_entry(user, create=True)
    groups = set(entry.get("groups", []))
    groups.add(group)
    entry["groups"] = sorted(groups)
    entry["updated_at"] = time.time()
    entry["updated_by_user_id"] = user_id_value(actor) if actor else None
    entry["updated_by_discord_name"] = user_display(actor) if actor else None
    save_user_permissions_config()

def remove_user_group(user, group: str, actor=None):
    group = str(group or "").lower()
    if group not in USER_RESTRICTION_GROUPS:
        raise ValueError("Unknown user group.")
    entry = user_permissions_entry(user, create=True)
    groups = set(entry.get("groups", []))
    groups.discard(group)
    entry["groups"] = sorted(groups)
    entry["updated_at"] = time.time()
    entry["updated_by_user_id"] = user_id_value(actor) if actor else None
    entry["updated_by_discord_name"] = user_display(actor) if actor else None
    save_user_permissions_config()

async def require_not_restricted(ctx, group: str, action: str) -> bool:
    if not user_has_group(ctx.user, group):
        return True
    logger.warning(
        f"Denied /{command_name(ctx)} by {user_display(ctx.user)} "
        f"({user_id_value(ctx.user)}): user is in restriction group {group}."
    )
    await safe_interaction_send(ctx, f"You cannot {action} because your account is in `{group}`.", ephemeral=True)
    return False

def permissions_summary_for(user) -> str:
    groups = sorted(user_groups(user))
    if not groups:
        return "normal user"
    return ", ".join(f"`{group}`" for group in groups)

def bool_status(value: bool) -> str:
    return "enabled" if value else "disabled"

def playlist_cache_modes_order() -> list:
    return ["streaming", "bounded", "keep_cached"]

def set_verbose_logging(enabled: bool):
    client.log_verbose = bool(enabled)
    logger.setLevel(logging.DEBUG if client.log_verbose else logging.INFO)

def config_panel_message() -> str:
    policy = favorites_cache_policy()
    lines = [
        "**admin config**",
        "React with the matching emoji to change a setting. Only admins can use this panel.",
        "",
        f"🎧 download-and-play: `{bool_status(client.download_mode)}`",
        f"📥 Discord download logs: `{bool_status(client.download_debug_messages)}`",
        f"🔍 Python DEBUG logging: `{bool_status(client.log_verbose)}` (`{logging.getLevelName(logger.level)}`)",
        f"🧭 admin operation trail: `{bool_status(client.user_operation_debug_messages)}`",
        f"🔗 queue links: `{'disabled' if client.queue_links_disabled else 'enabled'}`",
        f"🚪 auto-leave: `{bool_status(client.auto_leave_enabled)}` (`{client.auto_leave_delay_seconds}s`)",
        f"⭐ favorites autocache: `{bool_status(bool(policy.get('enabled')))}`",
        f"🌐 force global playlist cache: `{bool_status(client.force_global_playlist_cache_mode)}`",
        f"📦 playlist cache default: `{client.playlist_cache_default_mode}`",
        f"🏃 playspeed for everyone: `{bool_status(client.playspeed_allow_all)}`",
        f"🏃 alone speed reset: `1x after {alone_speed_reset_delay_seconds()}s alone`",
        f"⏱️ nowplaying cooldown: `{client.nowplaying_cooldown_seconds}s`",
        f"📊 public `/status play`: `{bool_status(client.status_play_public)}`",
        f"🗳️ voice votes: `{bool_status(client.voice_votes_enabled)}`",
        "",
        "_Config changes are runtime changes unless that setting already has a persistent policy file._",
    ]
    return "\n".join(lines)

async def apply_config_reaction(emoji: str, actor=None) -> str:
    if emoji == "🎧":
        client.download_mode = not client.download_mode
        append_runtime_audit_event("config-toggle", actor=actor, details={"setting": "download_mode", "enabled": client.download_mode})
        return f"download-and-play is now `{bool_status(client.download_mode)}`."
    if emoji == "📥":
        client.download_debug_messages = not client.download_debug_messages
        append_runtime_audit_event("config-toggle", actor=actor, details={"setting": "download_debug_messages", "enabled": client.download_debug_messages})
        return f"Discord download logs are now `{bool_status(client.download_debug_messages)}`."
    if emoji == "🔍":
        set_verbose_logging(not client.log_verbose)
        append_runtime_audit_event("config-toggle", actor=actor, details={"setting": "log_verbose", "enabled": client.log_verbose})
        return f"Python DEBUG logging is now `{bool_status(client.log_verbose)}`."
    if emoji == "🧭":
        client.user_operation_debug_messages = not client.user_operation_debug_messages
        append_runtime_audit_event("config-toggle", actor=actor, details={"setting": "user_operation_debug_messages", "enabled": client.user_operation_debug_messages})
        return f"admin operation trail is now `{bool_status(client.user_operation_debug_messages)}`."
    if emoji == "🔗":
        client.queue_links_disabled = not client.queue_links_disabled
        append_runtime_audit_event("config-toggle", actor=actor, details={"setting": "queue_links_disabled", "enabled": client.queue_links_disabled})
        return f"queue links are now `{'disabled' if client.queue_links_disabled else 'enabled'}`."
    if emoji == "🚪":
        client.auto_leave_enabled = not client.auto_leave_enabled
        if not client.auto_leave_enabled:
            cancel_auto_leave_task("config panel")
        else:
            voice = active_voice_client()
            schedule_auto_leave_if_needed(getattr(voice, "channel", None))
        append_runtime_audit_event("config-toggle", actor=actor, details={"setting": "auto_leave_enabled", "enabled": client.auto_leave_enabled})
        return f"auto-leave is now `{bool_status(client.auto_leave_enabled)}`."
    if emoji == "⭐":
        policy = favorites_cache_policy()
        set_favorites_cache_policy(not bool(policy.get("enabled")))
        append_runtime_audit_event("config-toggle", actor=actor, details={"setting": "favorites_cache_enabled", "enabled": bool(favorites_cache_policy().get("enabled"))})
        return f"favorites autocache is now `{bool_status(bool(favorites_cache_policy().get('enabled')))}`."
    if emoji == "🌐":
        client.force_global_playlist_cache_mode = not client.force_global_playlist_cache_mode
        save_playlist_cache_policy()
        append_runtime_audit_event("config-toggle", actor=actor, details={"setting": "force_global_playlist_cache_mode", "enabled": client.force_global_playlist_cache_mode})
        return f"force global playlist cache is now `{bool_status(client.force_global_playlist_cache_mode)}`."
    if emoji == "📦":
        modes = playlist_cache_modes_order()
        current = client.playlist_cache_default_mode
        next_mode = modes[(modes.index(current) + 1) % len(modes)] if current in modes else DEFAULT_PLAYLIST_CACHE_MODE
        client.playlist_cache_default_mode = next_mode
        save_playlist_cache_policy()
        append_runtime_audit_event("config-toggle", actor=actor, details={"setting": "playlist_cache_default_mode", "mode": next_mode})
        return f"playlist cache default is now `{next_mode}`."
    if emoji == "🏃":
        client.playspeed_allow_all = not client.playspeed_allow_all
        save_runtime_permissions_config()
        append_runtime_audit_event("config-toggle", actor=actor, details={"setting": "playspeed_allow_all", "enabled": client.playspeed_allow_all})
        return f"playspeed for everyone is now `{bool_status(client.playspeed_allow_all)}`."
    if emoji == "⏱️":
        choices = list(NOWPLAYING_COOLDOWN_CHOICES)
        current = client.nowplaying_cooldown_seconds
        next_value = choices[(choices.index(current) + 1) % len(choices)] if current in choices else DEFAULT_NOWPLAYING_COOLDOWN_SECONDS
        client.nowplaying_cooldown_seconds = next_value
        save_runtime_permissions_config()
        append_runtime_audit_event("config-toggle", actor=actor, details={"setting": "nowplaying_cooldown_seconds", "seconds": next_value})
        return f"nowplaying cooldown is now `{next_value}s`."
    if emoji == "📊":
        client.status_play_public = not client.status_play_public
        save_runtime_permissions_config()
        append_runtime_audit_event("config-toggle", actor=actor, details={
            "setting": "status_play_public",
            "enabled": client.status_play_public,
        })
        return f"`/status play` public access is now `{bool_status(client.status_play_public)}`."
    if emoji == "🗳️":
        client.voice_votes_enabled = not client.voice_votes_enabled
        save_runtime_permissions_config()
        append_runtime_audit_event("config-toggle", actor=actor, details={
            "setting": "voice_votes_enabled",
            "enabled": client.voice_votes_enabled,
        })
        return f"voice votes are now `{bool_status(client.voice_votes_enabled)}`."
    return "unknown config reaction."

async def handle_config_reaction(reaction, user) -> bool:
    if reaction.message.id != getattr(client, "config_panel_message_id", None):
        return False
    emoji = str(reaction.emoji)
    if emoji not in CONFIG_REACTIONS:
        return True
    if not is_user_admin(user):
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except Exception as exc:
            logger.warning(f"Failed to remove denied config reaction: {exc}")
        return True
    try:
        result = await apply_config_reaction(emoji, actor=user)
        await reaction.message.edit(content=config_panel_message())
        await reaction.message.remove_reaction(reaction.emoji, user)
        logger.info(f"Config panel changed by {user_display(user)} ({user_id_value(user)}): {result}")
    except Exception as exc:
        logger.error(f"Config panel reaction failed: {exc}")
        try:
            await reaction.message.channel.send("Config update failed. Check output.log.")
        except Exception:
            pass
    return True

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

async def require_queue_room_for_count(ctx, track_count: int) -> bool:
    if is_user_admin(ctx.user) or len(queue) + track_count <= MAX_QUEUE_LENGTH:
        return True
    logger.warning(
        f"Denied /{command_name(ctx)} by {user_display(ctx.user)} "
        f"({getattr(ctx.user, 'id', 0)}): queue length limit {MAX_QUEUE_LENGTH} would be exceeded by {track_count} track(s)."
    )
    await safe_interaction_send(
        ctx,
        f"Queue limit reached ({MAX_QUEUE_LENGTH} songs). This playlist would add {track_count} song(s). Ask an admin to clear the queue.",
        ephemeral=True,
    )
    return False

def load_playlist_cache_policy() -> dict:
    policy = {
        "default_mode": DEFAULT_PLAYLIST_CACHE_MODE,
        "force_global": False,
    }
    if not os.path.isfile(PLAYLIST_CACHE_POLICY_FILE):
        return policy
    try:
        with open(PLAYLIST_CACHE_POLICY_FILE, "r") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            logger.error("Playlist cache policy file is not a JSON object; using defaults.")
            return policy
        mode = loaded.get("default_mode")
        if mode in GLOBAL_PLAYLIST_CACHE_MODES:
            policy["default_mode"] = mode
        policy["force_global"] = bool(loaded.get("force_global", False))
    except Exception as exc:
        logger.error(f"Failed to load playlist cache policy: {exc}")
    return policy

def load_channel_volume_config() -> dict:
    config = {"channels": {}}
    if not os.path.isfile(CHANNEL_VOLUME_CONFIG_FILE):
        return config
    try:
        with open(CHANNEL_VOLUME_CONFIG_FILE, "r") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            logger.error("Channel volume config is not a JSON object; using defaults.")
            return config
        channels = loaded.get("channels", {})
        if not isinstance(channels, dict):
            logger.error("Channel volume config channels value is invalid; using defaults.")
            return config
        for key, entry in channels.items():
            if not isinstance(entry, dict):
                continue
            level = entry.get("level")
            if isinstance(level, int) and MIN_VOLUME_LEVEL <= level <= MAX_VOLUME_LEVEL:
                config["channels"][str(key)] = {
                    "level": level,
                    "force": bool(entry.get("force", False)),
                    "updated_at": entry.get("updated_at", 0),
                    "updated_by_user_id": entry.get("updated_by_user_id"),
                    "updated_by_discord_name": entry.get("updated_by_discord_name"),
                }
    except Exception as exc:
        logger.error(f"Failed to load channel volume config: {exc}")
    return config

def load_user_permissions_config() -> dict:
    config = {
        "users": {},
        "runtime": {
            "playspeed_allow_all": False,
            "nowplaying_cooldown_seconds": DEFAULT_NOWPLAYING_COOLDOWN_SECONDS,
            "status_play_public": False,
            "voice_votes_enabled": True,
        },
        "favorites_cache": {
            "enabled": False,
            "max_bytes": FAVORITES_CACHE_DEFAULT_MAX_BYTES,
            "per_user_tracks": FAVORITES_CACHE_DEFAULT_TRACKS_PER_USER,
        },
    }
    if not os.path.isfile(USER_PERMISSIONS_FILE):
        return config
    try:
        with open(USER_PERMISSIONS_FILE, "r") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            logger.error("User permissions config is not a JSON object; using defaults.")
            return config
        users = loaded.get("users", {})
        if isinstance(users, dict):
            for raw_user_id, entry in users.items():
                user_id = str(raw_user_id)
                if not user_id.isdigit() or not isinstance(entry, dict):
                    continue
                groups = [
                    str(group).lower()
                    for group in entry.get("groups", [])
                    if str(group).lower() in USER_RESTRICTION_GROUPS
                ]
                config["users"][user_id] = {
                    "groups": sorted(set(groups)),
                    "favorite_cache_enabled": entry.get("favorite_cache_enabled"),
                    "updated_at": entry.get("updated_at", 0),
                    "updated_by_user_id": entry.get("updated_by_user_id"),
                    "updated_by_discord_name": entry.get("updated_by_discord_name"),
                }
        runtime = loaded.get("runtime", {})
        if isinstance(runtime, dict):
            config["runtime"]["playspeed_allow_all"] = bool(runtime.get("playspeed_allow_all", False))
            config["runtime"]["status_play_public"] = bool(runtime.get("status_play_public", False))
            config["runtime"]["voice_votes_enabled"] = bool(runtime.get("voice_votes_enabled", True))
            try:
                cooldown = int(runtime.get("nowplaying_cooldown_seconds", DEFAULT_NOWPLAYING_COOLDOWN_SECONDS))
            except (TypeError, ValueError):
                cooldown = DEFAULT_NOWPLAYING_COOLDOWN_SECONDS
            config["runtime"]["nowplaying_cooldown_seconds"] = max(
                NOWPLAYING_COOLDOWN_MIN_SECONDS,
                min(cooldown, NOWPLAYING_COOLDOWN_MAX_SECONDS),
            )
        cache = loaded.get("favorites_cache", {})
        if isinstance(cache, dict):
            config["favorites_cache"]["enabled"] = bool(cache.get("enabled", False))
            try:
                max_bytes = int(cache.get("max_bytes", FAVORITES_CACHE_DEFAULT_MAX_BYTES))
            except (TypeError, ValueError):
                max_bytes = FAVORITES_CACHE_DEFAULT_MAX_BYTES
            config["favorites_cache"]["max_bytes"] = max(
                0,
                min(max_bytes, FAVORITES_CACHE_MAX_BYTES),
            )
            try:
                per_user_tracks = int(cache.get("per_user_tracks", FAVORITES_CACHE_DEFAULT_TRACKS_PER_USER))
            except (TypeError, ValueError):
                per_user_tracks = FAVORITES_CACHE_DEFAULT_TRACKS_PER_USER
            config["favorites_cache"]["per_user_tracks"] = max(
                0,
                min(per_user_tracks, FAVORITES_MAX_TRACKS_PER_USER),
            )
    except Exception as exc:
        logger.error(f"Failed to load user permissions config: {exc}")
    return config

def save_playlist_cache_policy():
    write_json_atomic(PLAYLIST_CACHE_POLICY_FILE, {
        "default_mode": client.playlist_cache_default_mode,
        "force_global": client.force_global_playlist_cache_mode,
        "updated_at": time.time(),
    })

def save_channel_volume_config():
    write_json_atomic(CHANNEL_VOLUME_CONFIG_FILE, client.channel_volume_config)

def save_user_permissions_config():
    write_json_atomic(USER_PERMISSIONS_FILE, client.user_permissions_config)

def runtime_permissions_config() -> dict:
    runtime = client.user_permissions_config.setdefault("runtime", {})
    runtime.setdefault("playspeed_allow_all", False)
    runtime.setdefault("nowplaying_cooldown_seconds", DEFAULT_NOWPLAYING_COOLDOWN_SECONDS)
    runtime.setdefault("status_play_public", False)
    runtime.setdefault("voice_votes_enabled", True)
    return runtime

def save_runtime_permissions_config():
    runtime = runtime_permissions_config()
    runtime["playspeed_allow_all"] = bool(getattr(client, "playspeed_allow_all", False))
    runtime["nowplaying_cooldown_seconds"] = int(getattr(client, "nowplaying_cooldown_seconds", DEFAULT_NOWPLAYING_COOLDOWN_SECONDS))
    runtime["status_play_public"] = bool(getattr(client, "status_play_public", False))
    runtime["voice_votes_enabled"] = bool(getattr(client, "voice_votes_enabled", True))
    save_user_permissions_config()

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
    async def from_url(cls, url, *, loop=None, stream=False, speed: Optional[float] = None):
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
        ffmpeg_args = ffmpeg_audio_options_for_speed(speed or 1.0, reconnect=True)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_args), data=data, volume=client.volume), data.get('webpage_url', url)

class Client(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        # Voice and playback state
        self.current_voice_channel = None      # discord.VoiceClient when connected
        self.currently_playing = False
        self.volume = DEFAULT_VOLUME_LEVEL / 100.0
        self.session_volume_locked = False
        self.current_track_id = None
        self.current_track_info = None         # current track's info (dict)
        self.last_track_info = None            # last played track's info (dict)
        self.current_track_message = None      # discord.Message for the "Now Playing" announcement
        self.current_track_message_show_queue = False
        self.current_track_message_show_url = True
        # Admin-controllable flags
        self.download_mode = True              # True = download-and-play, False = stream-only
        self.log_verbose = False               # True = DEBUG logging on
        self.user_operation_debug_messages = False
        self.queue_links_disabled = False
        playlist_cache_policy = load_playlist_cache_policy()
        self.playlist_cache_default_mode = playlist_cache_policy["default_mode"]
        self.force_global_playlist_cache_mode = playlist_cache_policy["force_global"]
        self.channel_volume_config = load_channel_volume_config()
        self.user_permissions_config = load_user_permissions_config()
        runtime_config = self.user_permissions_config.get("runtime", {})
        self.playspeed_allow_all = bool(runtime_config.get("playspeed_allow_all", False))
        self.status_play_public = bool(runtime_config.get("status_play_public", False))
        self.voice_votes_enabled = bool(runtime_config.get("voice_votes_enabled", True))
        self.playback_speed = 1.0
        self.nowplaying_cooldown_seconds = int(
            runtime_config.get("nowplaying_cooldown_seconds", DEFAULT_NOWPLAYING_COOLDOWN_SECONDS)
        )
        self.nowplaying_last_used = {}
        self.boot_id = secrets.token_urlsafe(8)
        self.booted_at = time.time()
        self.download_delete_delay_seconds = DEFAULT_DOWNLOAD_DELETE_DELAY_SECONDS
        self.auto_leave_enabled = False
        self.auto_leave_delay_seconds = AUTO_LEAVE_DEFAULT_DELAY_SECONDS
        self.auto_leave_task = None
        self.alone_speed_reset_task = None
        self.auto_leave_disconnect_in_progress = False
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
        self.help_page = 0
        self.help_pages = None
        self.config_panel_message_id = None
        self.config_panel_user_id = None
        self.playlist_delete_tasks = {}
        self.playlist_cache_tasks = {}
        self.playlist_creation_sessions = {}
        self.playlist_creation_timeout_tasks = {}
        self.active_voice_votes = {}
        self.download_debug_messages = False
        self.debug_playback_messages = {}
        self.repeat_current_track = False
        self.repeat_track_id = None
        self.repeat_disable_history = []
        self.current_track_favorite_notice = ""
        self.current_track_started_at = None
        self.last_presence_text = None
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
    cache_mb = cache_total_bytes() / (1024 * 1024)
    cache_limit_mb = CACHE_HARD_LIMIT_BYTES // (1024 * 1024)
    favorites_cache = client.user_permissions_config.get("favorites_cache", {})
    fav_cache_mb = int(favorites_cache.get("max_bytes", FAVORITES_CACHE_DEFAULT_MAX_BYTES)) // (1024 * 1024)
    lines = [
        "**runtime**",
        f"- mode: `{mode}`",
        f"- queue length: `{len(queue)}`",
        f"- song history entries: `{len(client.song_history)}`",
        f"- currently playing: **{discord.utils.escape_markdown(str(current))}**",
        f"- bot status: `{discord.utils.escape_markdown(str(client.last_presence_text or DEFAULT_BOT_PRESENCE))}`",
        f"- boot id: `{client.boot_id}`",
        f"- volume: `{int(round(client.volume * 100))}%` (`{'session' if client.session_volume_locked else 'channel/default'}`)",
        f"- playback speed default: `{client.playback_speed:g}x` (`{'everyone' if client.playspeed_allow_all else 'admin/group'}`)",
        f"- alone speed reset: `1x after {alone_speed_reset_delay_seconds()}s alone`",
        f"- log level: `{logging.getLevelName(logger.level)}`",
        f"- download log messages: `{'enabled' if client.download_debug_messages else 'disabled'}`",
        f"- admin operation messages: `{'enabled' if client.user_operation_debug_messages else 'disabled'}`",
        f"- repeat current track: `{'enabled' if client.repeat_current_track else 'disabled'}`",
        f"- queue links: `{'disabled' if client.queue_links_disabled else 'enabled'}`",
        f"- public /status play: `{'enabled' if client.status_play_public else 'disabled'}`",
        f"- voice votes: `{'enabled' if client.voice_votes_enabled else 'disabled'}`",
        f"- song delete delay: `{client.download_delete_delay_seconds}s`",
        f"- auto leave: `{'enabled' if client.auto_leave_enabled else 'disabled'}` (`{client.auto_leave_delay_seconds}s`)",
        f"- nowplaying cooldown: `{client.nowplaying_cooldown_seconds}s`",
        f"- cache: `{cache_mb:.1f} MB / {cache_limit_mb} MB`",
        f"- playlist cache default: `{client.playlist_cache_default_mode}`",
        f"- force global playlist cache: `{client.force_global_playlist_cache_mode}`",
        f"- favorites cache: `{'enabled' if favorites_cache.get('enabled') else 'disabled'}` (`{fav_cache_mb} MB`, `{favorites_cache.get('per_user_tracks', FAVORITES_CACHE_DEFAULT_TRACKS_PER_USER)}` tracks/user)",
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

def format_seconds(value) -> str:
    try:
        seconds = int(float(value or 0))
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        return "unknown"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

def metadata_value(track: dict, *keys, default="unknown"):
    for key in keys:
        value = track.get(key)
        if value not in (None, "", 0):
            return value
    return default

def build_playback_status() -> str:
    track = client.current_track_info or {}
    voice = active_voice_client()
    voice_channel = getattr(voice, "channel", None)
    cached_file = cached_file_for_track(track) if track else None
    duration = track.get("duration") or 0
    elapsed = 0
    if client.current_track_started_at:
        elapsed = max(0, int(time.time() - client.current_track_started_at))
    lines = ["**playback status**"]
    if not track:
        lines.append("- state: `idle`")
        lines.append(f"- bot status: `{discord.utils.escape_markdown(str(client.last_presence_text or DEFAULT_BOT_PRESENCE))}`")
        lines.append(f"- queue length: `{len(queue)}`")
        lines.append(f"- cache use: `{human_bytes(cache_total_bytes())} / {human_bytes(CACHE_HARD_LIMIT_BYTES)}`")
        return "\n".join(lines)
    lines.extend([
        f"- state: `{'playing' if client.currently_playing else 'not playing'}`",
        f"- bot status: `{discord.utils.escape_markdown(str(client.last_presence_text or DEFAULT_BOT_PRESENCE))}`",
        f"- title: **{discord.utils.escape_markdown(str(track.get('title') or 'Unknown title'))}**",
        f"- song/artist status source: `{bot_presence_for_track(track)[1]}`",
        f"- video id: `{discord.utils.escape_markdown(str(track.get('id') or '-'))}`",
    ])
    if not client.queue_links_disabled and track.get("webpage_url"):
        lines.append(f"- url: {track.get('webpage_url')}")
    lines.extend([
        f"- voice channel: `{discord.utils.escape_markdown(str(getattr(voice_channel, 'name', 'none')))}`",
        f"- paused: `{bool(voice and voice.is_paused())}`",
        f"- queue length: `{len(queue)}`",
        f"- playlist context: `{discord.utils.escape_markdown(str(track.get('playlist_name') or 'none'))}`",
        f"- duration: `{format_seconds(duration)}`",
        f"- estimated position: `{format_seconds(elapsed)}`",
        f"- volume: `{int(round(client.volume * 100))}%`",
        f"- playback speed: `{playback_speed_for_track(track):g}x`",
        f"- repeat-one: `{bool(client.repeat_current_track and client.repeat_track_id == str(track.get('id') or ''))}`",
        f"- cache mode: `{discord.utils.escape_markdown(str(track.get('cache_mode') or 'streaming'))}`",
        f"- cached file: `{metadata_path_for_cache_file(cached_file) if cached_file else 'none'}`",
        f"- file extension: `{discord.utils.escape_markdown(str(track.get('ext') or 'unknown'))}`",
        f"- file size: `{human_bytes(track.get('filesize') or cache_file_size(cached_file) if cached_file else track.get('filesize'))}`",
        f"- yt-dlp format id: `{discord.utils.escape_markdown(str(metadata_value(track, 'format_id')))}`",
        f"- audio codec: `{discord.utils.escape_markdown(str(metadata_value(track, 'acodec')))}`",
        f"- container/format: `{discord.utils.escape_markdown(str(metadata_value(track, 'format', 'format_note')))}`",
        f"- audio bitrate: `{metadata_value(track, 'abr')} kbps`",
        f"- total bitrate: `{metadata_value(track, 'tbr')} kbps`",
        f"- sample rate: `{metadata_value(track, 'asr')} Hz`",
        f"- channels: `{metadata_value(track, 'audio_channels')}`",
        f"- dynamic range: `{discord.utils.escape_markdown(str(metadata_value(track, 'dynamic_range')))}`",
        f"- bpm: `{metadata_value(track, 'bpm')}`",
        f"- uploader/channel: `{discord.utils.escape_markdown(str(metadata_value(track, 'uploader', 'channel')))}`",
        f"- live stream: `{bool(track.get('is_live'))}`",
        f"- age limit: `{metadata_value(track, 'age_limit')}`",
        f"- cache use: `{human_bytes(cache_total_bytes())} / {human_bytes(CACHE_HARD_LIMIT_BYTES)}`",
    ])
    return "\n".join(lines)[:DISCORD_MESSAGE_SAFE_LIMIT]

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

def debug_playback_content(report: DebugPlaybackMessage, *, collapsed: bool = False) -> str:
    if collapsed:
        title = discord.utils.escape_markdown(report.title or "track")
        video_id = discord.utils.escape_markdown(report.video_id or "-")
        return f"**download log hidden**\n- track: **{title}** (`{video_id}`)"
    progress = download_progress_bar(report.downloaded_bytes, report.total_bytes)
    lines = [
        "**download log**",
        f"- stage: `{discord.utils.escape_markdown(report.stage)}`",
    ]
    if report.title or report.video_id:
        lines.append(
            f"- track: **{discord.utils.escape_markdown(report.title or 'unknown')}** "
            f"(`{discord.utils.escape_markdown(report.video_id or '-')}`)"
        )
    voice = active_voice_client()
    if voice and getattr(voice, "channel", None):
        channel_name = getattr(voice.channel, "name", "voice")
        lines.append(f"- voice: `{discord.utils.escape_markdown(str(channel_name))}`")
    if report.cache_state:
        lines.append(f"- cache: `{discord.utils.escape_markdown(report.cache_state)}`")
    if report.format_id:
        lines.append(f"- yt-dlp format: `{discord.utils.escape_markdown(report.format_id)}`")
    if report.total_bytes or report.downloaded_bytes:
        total = human_bytes(report.total_bytes) if report.total_bytes else "unknown"
        lines.append(f"- downloaded: `{human_bytes(report.downloaded_bytes)} / {total}`")
        if progress:
            lines.append(f"- progress: `{progress}`")
    if report.speed:
        lines.append(f"- speed: `{human_bytes(report.speed)}/s`")
    if report.events:
        lines.append("**events**")
        lines.extend(f"- {discord.utils.escape_markdown(event)}" for event in report.events[-8:])
    if report.error:
        lines.append(f"- internal error: `{discord.utils.escape_markdown(truncate_text(sanitize_debug_text(report.error), 140))}`")
        lines.append("- user error: `normal command error was sent separately`")
    if report.status in {"done", "error"}:
        if report.status == "done":
            lines.append("- ffmpeg: `audio-only (-vn), Discord PCM volume transformer`")
        lines.append(f"_react {DEBUG_COLLAPSE_REACTION} to hide debug details._")
    return "\n".join(lines)

def download_progress_bar(downloaded: int, total: int, *, width: int = 24) -> Optional[str]:
    if not total or total <= 0:
        return None
    ratio = max(0.0, min(1.0, float(downloaded or 0) / float(total)))
    filled = int(round(ratio * width))
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {ratio * 100:.0f}%"

async def append_debug_playback_event(report: Optional[DebugPlaybackMessage], event: str, *, stage: Optional[str] = None, force: bool = False):
    if not report:
        return
    clean = truncate_text(sanitize_debug_text(event), 160)
    report.events.append(f"{format_timestamp(time.time())} {clean}")
    if stage:
        report.stage = stage
    await edit_debug_playback_message(report, force=force)

def sanitize_debug_text(value: str) -> str:
    text = str(value or "")
    replacements = [
        (CACHE_DIR, "cache"),
        (BASE_DIR, "<repo>"),
        (YTDLP_COOKIEFILE, "<yt-dlp-cookiefile>"),
        (BOT_TOKEN, "<bot-token>"),
    ]
    for absolute, label in replacements:
        if absolute:
            text = text.replace(absolute, label)
    return text

async def edit_debug_playback_message(report: DebugPlaybackMessage, *, force: bool = False):
    if not report or not report.message:
        return
    now = time.time()
    if not force and now - report.last_edit_at < 1.0:
        return
    report.last_edit_at = now
    try:
        await report.message.edit(content=debug_playback_content(report))
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
        logger.warning(f"Could not edit debug playback message: {exc}")

def schedule_debug_playback_update(report: Optional[DebugPlaybackMessage], loop, *, force: bool = False):
    if not report or not loop:
        return
    try:
        asyncio.run_coroutine_threadsafe(edit_debug_playback_message(report, force=force), loop)
    except RuntimeError as exc:
        logger.debug(f"Could not schedule debug playback update: {exc}")

async def create_debug_playback_message(ctx, command: str, *, force: bool = False) -> Optional[DebugPlaybackMessage]:
    if not (force or client.download_debug_messages):
        return None
    normal = f"**download log hidden**\n- command: `/{command}`"
    try:
        message = await ctx.followup.send(
            f"**download log**\n- command: `/{command}`\n- stage: `starting`",
            wait=True,
        )
        report = DebugPlaybackMessage(message=message, normal_content=normal, stage="starting")
        client.debug_playback_messages[message.id] = report
        await append_debug_playback_event(report, "command accepted; preparing playback", force=True)
        return report
    except Exception as exc:
        logger.warning(f"Could not create debug playback message: {exc}")
        return None

async def finish_debug_playback_message(report: Optional[DebugPlaybackMessage], *, status: str = "done", error: str = ""):
    if not report:
        return
    report.status = status
    if error:
        report.error = error
        report.stage = "error"
    elif report.stage not in {"cache-hit", "streaming", "queued", "playing"}:
        report.stage = status
    await edit_debug_playback_message(report, force=True)
    if status in {"done", "error"}:
        try:
            await report.message.add_reaction(DEBUG_COLLAPSE_REACTION)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning(f"Could not add debug collapse reaction: {exc}")

async def handle_debug_playback_reaction(reaction, user) -> bool:
    report = client.debug_playback_messages.get(reaction.message.id)
    if not report:
        return False
    if str(reaction.emoji) != DEBUG_COLLAPSE_REACTION:
        return True
    try:
        await reaction.message.edit(content=debug_playback_content(report, collapsed=True))
        await reaction.message.clear_reactions()
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
        logger.warning(f"Could not collapse debug playback message: {exc}")
    return True

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

def parse_play_repeat_request(query: str, repeat: Optional[int]) -> tuple:
    text = str(query or "").strip()
    explicit = repeat is not None
    requested = repeat
    match = re.search(r"(?:^|\s)-repeat(?:\s+(\d+))?\s*$", text, flags=re.IGNORECASE)
    if match:
        explicit = True
        requested = int(match.group(1) or 2)
        text = text[:match.start()].strip()
    if not explicit:
        return text, 1, False, False
    try:
        requested = int(requested)
    except (TypeError, ValueError):
        requested = 1
    requested = max(1, requested)
    return text, min(requested, MAX_PLAY_REPEAT_COUNT), requested > MAX_PLAY_REPEAT_COUNT, True

def parse_play_speed_request(query: str, speed: Optional[float]) -> tuple:
    text = str(query or "").strip()
    explicit = speed is not None
    requested = speed
    match = re.search(r"(?:^|\s)--?speed(?::|=|\s+)([0-9]+(?:\.[0-9]+)?)\s*$", text, flags=re.IGNORECASE)
    if match:
        explicit = True
        requested = match.group(1)
        text = text[:match.start()].strip()
    if not explicit:
        return text, 1.0, False, None
    parsed, error = normalize_playback_speed(requested)
    return text, parsed, True, error

def normal_speed_message() -> str:
    return "Speed `1` is normal time. Multiplying time by one changes nothing. Bold choice."

def clone_track_for_repeat(track: dict, *, repeat_loop: bool = False) -> dict:
    clone = dict(track)
    if repeat_loop:
        clone["repeat_loop"] = True
    else:
        clone.pop("repeat_loop", None)
    return clone

def queue_repeat_copies(track: dict, repeat_count: int, *, already_started: bool = False) -> int:
    copies = max(0, int(repeat_count or 1) - (1 if already_started else 0))
    for _ in range(copies):
        repeated = clone_track_for_repeat(track)
        queue.append(repeated)
        client.song_history.append(repeated)
    if copies:
        logger.info(
            f"Queued {copies} repeat copy/copies for {track.get('title')} ({track.get('id')})."
        )
    return copies

async def announce_repeat_request(ctx, repeat_count: int, repeat_loop: bool, *, started: bool):
    if repeat_loop:
        await ctx.followup.send(
            f"Repeat count above {MAX_PLAY_REPEAT_COUNT} requested; this track will loop until repeat is turned off."
        )
    elif repeat_count > 1:
        action = "started and repeat copies were queued" if started else "queued"
        await ctx.followup.send(f"Repeat {action}: this track will play `{repeat_count}` time(s).")

async def maybe_send_speed_notice(ctx, speed: float, explicit: bool):
    if not explicit:
        return
    if abs(float(speed or 1.0) - 1.0) <= 0.001:
        await ctx.followup.send(normal_speed_message())

def track_requested_by_user(track: dict, user) -> bool:
    return user_id_value(track.get("requested_by_user_id")) == user_id_value(user)

def format_recent_user_commands(user, limit: int = 5) -> list:
    uid = user_id_value(user)
    commands = [record for record in client.recent_commands if user_id_value(record.user_id) == uid]
    return [
        f"`/{record.command}` at `{format_timestamp(record.timestamp)}`"
        for record in commands[-limit:]
    ]

def format_recent_user_suggestions(user, limit: int = 5) -> list:
    uid = user_id_value(user)
    suggestions = [record for record in client.suggestion_history if user_id_value(record.user_id) == uid]
    lines = []
    for record in suggestions[-limit:]:
        title = discord.utils.escape_markdown(record.title or record.raw_value or "unresolved")
        lines.append(f"**{title}** (`/{record.command}`, `{format_timestamp(record.timestamp)}`)")
    return lines

def user_stats_message(user) -> str:
    uid = user_id_value(user)
    playlists = load_playlists()
    normal_playlists = [p for p in playlists if not is_favorites_playlist(p)]
    owned = [p for p in normal_playlists if playlist_owner_id(p) == uid]
    managed = [p for p in normal_playlists if uid in playlist_manager_ids(p) and playlist_owner_id(p) != uid]
    favorites = favorites_playlist_for_user(user, create=False)
    favorite_tracks = favorites.get("tracks", []) if favorites else []
    favorite_visibility = favorites.get("visibility", "private") if favorites else "private"
    queued_count = sum(1 for track in queue if track_requested_by_user(track, user))
    history_count = sum(1 for track in client.song_history if track_requested_by_user(track, user))
    cache_allowed = favorite_cache_allowed_for_user(user) and not user_has_group(user, "nodownload")
    owned_names = ", ".join(discord.utils.escape_markdown(p.get("name", "unnamed")) for p in owned[:5]) or "none"
    managed_names = ", ".join(discord.utils.escape_markdown(p.get("name", "unnamed")) for p in managed[:5]) or "none"
    recent_commands = format_recent_user_commands(user)
    recent_suggestions = format_recent_user_suggestions(user)
    lines = [
        f"**user stats: {discord.utils.escape_markdown(user_display(user))}**",
        f"- user id: `{uid}`",
        f"- permissions: {permissions_summary_for(user)}",
        f"- playspeed access: `{'yes' if can_use_play_speed(user) else 'no'}`",
        f"- voice vote mode: `{'direct controls' if not client.voice_votes_enabled else 'vote prompts enabled'}`",
        f"- favorites: `{len(favorite_tracks)}` saved, `{favorite_visibility}` visibility, cache `{'eligible' if cache_allowed else 'disabled'}`",
        f"- playlists owned: `{len(owned)}` ({owned_names})",
        f"- playlists managed: `{len(managed)}` ({managed_names})",
        f"- session requests: `{history_count}` total, `{queued_count}` still queued",
        "",
        "**recent commands**",
    ]
    lines.extend(f"- {item}" for item in recent_commands) if recent_commands else lines.append("- none in retained command memory")
    lines.append("")
    lines.append("**recent music requests**")
    lines.extend(f"- {item}" for item in recent_suggestions) if recent_suggestions else lines.append("- none in retained suggestion memory")
    return "\n".join(lines)[:1900]

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
        if client.queue_links_disabled:
            lines.append(f"- url:\n```text\n{record.url}\n```")
        else:
            lines.append(f"- url: {record.url}")
    return "\n".join(lines)

def format_command_record(record: CommandRecord) -> str:
    user_name = discord.utils.escape_markdown(record.user_name)
    return f"- `{format_timestamp(record.timestamp)}` /{record.command} by **{user_name}** (`{record.user_id}`)"

def build_status_message(view: str = "latest") -> str:
    view = (view or "latest").lower()
    if view in {"play", "playback", "musicstream", "stream"}:
        return build_playback_status()
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

def voice_channel_human_members(channel) -> list:
    return [
        member for member in getattr(channel, "members", [])
        if not getattr(member, "bot", False)
    ]

def bot_is_alone_in_voice(channel) -> bool:
    if channel is None:
        return False
    return len(voice_channel_human_members(channel)) == 0

def voice_channel_id(channel) -> int:
    return int(getattr(channel, "id", 0) or 0)

def channel_volume_key(channel) -> Optional[str]:
    channel_id = voice_channel_id(channel)
    if not channel_id:
        return None
    guild = getattr(channel, "guild", None)
    guild_id = int(getattr(guild, "id", 0) or 0)
    return f"{guild_id}:{channel_id}"

def validate_volume_level(level: int, *, allow_unsafe: bool = False) -> Optional[str]:
    if level < MIN_VOLUME_LEVEL or level > MAX_VOLUME_LEVEL:
        return f"Volume must be between {MIN_VOLUME_LEVEL} and {MAX_VOLUME_LEVEL}."
    if not allow_unsafe and level > SAFE_VOLUME_MAX_LEVEL:
        return f"Volume is capped at {SAFE_VOLUME_MAX_LEVEL}% for ear safety. Admins can use `/volume_force` to go louder."
    return None

def channel_volume_entry(channel) -> dict:
    key = channel_volume_key(channel)
    if not key:
        return {}
    return client.channel_volume_config.get("channels", {}).get(key, {})

def configured_volume_level_for_channel(channel) -> int:
    entry = channel_volume_entry(channel)
    if not entry:
        return DEFAULT_VOLUME_LEVEL
    level = entry.get("level")
    if isinstance(level, int) and MIN_VOLUME_LEVEL <= level <= MAX_VOLUME_LEVEL:
        if level > SAFE_VOLUME_MAX_LEVEL and not entry.get("force"):
            logger.warning(
                f"Clamping unsafe channel volume default {level}% for {channel_volume_key(channel)} "
                f"to {SAFE_VOLUME_MAX_LEVEL}%."
            )
            return SAFE_VOLUME_MAX_LEVEL
        return level
    return DEFAULT_VOLUME_LEVEL

def set_client_volume_level(level: int, *, allow_unsafe: bool = False):
    if not allow_unsafe and level > SAFE_VOLUME_MAX_LEVEL:
        logger.warning(f"Clamping requested volume {level}% to safe limit {SAFE_VOLUME_MAX_LEVEL}%.")
        level = SAFE_VOLUME_MAX_LEVEL
    client.volume = level / 100.0
    voice = active_voice_client()
    if voice and getattr(voice, "source", None):
        try:
            voice.source.volume = client.volume
        except Exception as exc:
            logger.error(f"Volume adjust error: {exc}")

def apply_channel_volume_default(channel, reason: str = ""):
    if client.session_volume_locked:
        return
    level = configured_volume_level_for_channel(channel)
    set_client_volume_level(level, allow_unsafe=bool(channel_volume_entry(channel).get("force")))
    logger.info(
        f"Applied voice channel volume default {level}%"
        f"{f' during {reason}' if reason else ''}."
    )

def reset_session_volume(reason: str = ""):
    client.session_volume_locked = False
    set_client_volume_level(DEFAULT_VOLUME_LEVEL)
    logger.info(f"Reset session volume to {DEFAULT_VOLUME_LEVEL}%{f' after {reason}' if reason else ''}.")

def playback_speed_is_normal(speed: Optional[float]) -> bool:
    try:
        return abs(float(speed or 1.0) - 1.0) <= 0.001
    except (TypeError, ValueError):
        return True

def playback_speed_reset_needed() -> bool:
    if not playback_speed_is_normal(getattr(client, "playback_speed", 1.0)):
        return True
    track = client.current_track_info or {}
    if "playback_speed" in track and not playback_speed_is_normal(track.get("playback_speed")):
        return True
    return False

def alone_speed_reset_delay_seconds() -> int:
    return int(getattr(client, "auto_leave_delay_seconds", AUTO_LEAVE_DEFAULT_DELAY_SECONDS) or AUTO_LEAVE_DEFAULT_DELAY_SECONDS)

async def reset_playback_speed_after_alone(voice_channel, *, reason: str) -> bool:
    if not playback_speed_reset_needed():
        return False
    old_default = playback_speed_for_track(None)
    old_current = playback_speed_for_track(client.current_track_info) if client.current_track_info else old_default
    client.playback_speed = 1.0
    if client.current_track_info and "playback_speed" in client.current_track_info:
        client.current_track_info["playback_speed"] = 1.0
    details = {
        "reason": reason,
        "voice_channel_id": getattr(voice_channel, "id", None),
        "voice_channel_name": getattr(voice_channel, "name", None),
        "old_default_speed": old_default,
        "old_current_speed": old_current,
        "new_speed": 1.0,
        "delay_seconds": alone_speed_reset_delay_seconds(),
        "currently_playing": bool(client.currently_playing),
    }
    append_runtime_audit_event("playback-speed-alone-reset", details=details)
    logger.info(
        "Playback speed reset to 1x after bot was alone: "
        f"channel={getattr(voice_channel, 'name', voice_channel)} "
        f"old_default={old_default:g}x old_current={old_current:g}x reason={reason}."
    )
    notify_channel = getattr(client.current_track_message, "channel", None)
    if client.user_operation_debug_messages and notify_channel:
        try:
            await notify_channel.send(
                "**admin operation**\n"
                f"- playback speed reset: `{old_current:g}x` -> `1x`\n"
                f"- reason: bot was alone for `{alone_speed_reset_delay_seconds()}s`\n"
                "- note: already-running audio changes on the next track or replay."
            )
        except Exception as exc:
            logger.warning(f"Failed to send alone speed-reset operation message: {exc}")
    return True

def find_voice_channel_by_name(guild, name: str):
    lookup = str(name or "").strip().lower()
    if not guild or not lookup:
        return None
    voice_channels = getattr(guild, "voice_channels", [])
    for channel in voice_channels:
        if str(getattr(channel, "name", "")).lower() == lookup:
            return channel
    matches = [
        channel for channel in voice_channels
        if lookup in str(getattr(channel, "name", "")).lower()
    ]
    if len(matches) == 1:
        return matches[0]
    return None

async def connect_or_move_to_voice_channel(ctx, voice_channel, *, reason: str):
    if voice_channel is None:
        await safe_interaction_send(ctx, "Voice channel not found.", ephemeral=True)
        return False
    voice = active_voice_client(ctx.guild)
    try:
        if voice and voice.is_connected():
            if getattr(voice, "channel", None) == voice_channel:
                client.current_voice_channel = voice
                await safe_interaction_send(ctx, f"Already in voice channel **{discord.utils.escape_markdown(voice_channel.name)}**.", ephemeral=True)
                return True
            await voice.move_to(voice_channel)
            client.current_voice_channel = voice
            logger.info(f"Moved bot to voice channel {voice_channel.name} for {reason}.")
        else:
            client.current_voice_channel = await voice_channel.connect()
            if not client.currently_playing:
                client.song_history = []
            logger.info(f"Connected bot to voice channel {voice_channel.name} for {reason}.")
        apply_channel_volume_default(voice_channel, reason)
        cancel_auto_leave_task(reason)
        cancel_alone_speed_reset_task(reason)
        await safe_interaction_send(ctx, f"Joined voice channel **{discord.utils.escape_markdown(voice_channel.name)}**.", ephemeral=True)
        return True
    except Exception as exc:
        logger.error(f"Admin voice join failed for {getattr(voice_channel, 'name', voice_channel)}: {exc}")
        await safe_interaction_send(ctx, "Unable to join that voice channel. Check output.log.", ephemeral=True)
        return False

def voice_vote_quorum(channel) -> int:
    human_count = len(voice_channel_human_members(channel))
    if human_count <= 0:
        return 1
    return max(1, math.ceil(human_count * 0.5))

def voice_vote_key(channel, action: str, value: Optional[int] = None) -> tuple:
    return (voice_channel_id(channel), action, value)

def active_voice_vote_for_message(message_id: int):
    for vote in client.active_voice_votes.values():
        if vote.message_id == message_id:
            return vote
    return None

def voice_vote_prompt_content(vote: VoiceVote, *, status: str = "open") -> str:
    channel = getattr(active_voice_client(), "channel", None)
    quorum = voice_vote_quorum(channel) if channel and voice_channel_id(channel) == vote.voice_channel_id else 1
    status_line = {
        "open": "React 👍 to approve or 👎 to reject.",
        "passed": "Vote passed.",
        "rejected": "Vote rejected.",
        "expired": "Vote expired.",
        "cancelled": "Vote cancelled.",
    }.get(status, status)
    return (
        f"**vote: {vote.title}**\n"
        f"{status_line}\n"
        f"yes: `{len(vote.votes)}/{quorum}`  no: `{len(vote.no_votes)}/{quorum}`"
    )

async def expire_voice_vote(vote: VoiceVote):
    await asyncio.sleep(max(0, vote.expires_at - time.time()))
    current = client.active_voice_votes.get(vote.key)
    if current is not vote:
        return
    client.active_voice_votes.pop(vote.key, None)
    if vote.message:
        try:
            await vote.message.edit(content=voice_vote_prompt_content(vote, status="expired"))
            await vote.message.clear_reactions()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            logger.warning(f"Failed to expire voice vote message: {exc}")

async def finish_voice_vote(vote: VoiceVote, status: str):
    client.active_voice_votes.pop(vote.key, None)
    if vote.task:
        vote.task.cancel()
    if vote.message:
        try:
            await vote.message.edit(content=voice_vote_prompt_content(vote, status=status))
            await vote.message.clear_reactions()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            logger.warning(f"Failed to finish voice vote message: {exc}")

async def perform_skip_action() -> str:
    voice = active_voice_client()
    if voice and voice.is_connected() and (voice.is_playing() or voice.is_paused()):
        voice.stop()
        logger.info("Track skipped.")
        return "Skipped the current track."
    logger.info("Skip requested, but nothing is playing.")
    return "No track is currently playing."

async def perform_previous_action() -> str:
    if not client.last_track_info:
        return "No previous track to play."
    queue.insert(0, client.last_track_info)
    voice = active_voice_client()
    if voice and voice.is_connected() and (voice.is_playing() or voice.is_paused()):
        voice.stop()
    logger.info("Previous track requested.")
    return "Queued the previous track to replay next."

async def perform_stop_action() -> str:
    voice = active_voice_client()
    if voice:
        cancel_auto_leave_task("stop command")
        cancel_alone_speed_reset_task("stop command")
        try:
            if voice.is_playing() or voice.is_paused():
                voice.stop()
        except Exception as exc:
            logger.error(f"Error stopping voice client: {exc}")
        logger.info("Stopping playback, clearing queue, and disconnecting.")
        queue.clear()
        await voice.disconnect()
        client.current_voice_channel = None
        await clear_playback_tracking("stop command")
        reset_session_volume("voice disconnect")
        await update_bot_presence_idle(reason="stop command")
        return "Vittuun täältä keilahallista"
    logger.info("Stop requested while bot was not in a voice channel.")
    return "Not currently in a voice channel."

async def perform_volume_action(level: int) -> str:
    set_client_volume_level(level)
    logger.info(f"Volume set to {level}%.")
    return f"Volume set to {level}%."

def current_repeat_track_id() -> Optional[str]:
    track = client.current_track_info or {}
    track_id = str(track.get("id") or "").strip()
    return track_id or None

def prune_repeat_disable_history():
    cutoff = time.time() - REPEAT_TOGGLE_RECENT_SECONDS
    client.repeat_disable_history = [
        item for item in client.repeat_disable_history
        if item.get("timestamp", 0) >= cutoff
    ]

def recent_repeat_disable_users(track_id: str, *, excluding_user_id: Optional[int] = None) -> set:
    prune_repeat_disable_history()
    users = set()
    for item in client.repeat_disable_history:
        if item.get("track_id") != track_id:
            continue
        user_id = int(item.get("user_id") or 0)
        if excluding_user_id and user_id == excluding_user_id:
            continue
        if user_id:
            users.add(user_id)
    return users

async def refresh_current_track_message():
    message = client.current_track_message
    track = client.current_track_info
    if not message or not track:
        return
    try:
        await message.edit(content=format_now_playing(
            track,
            show_queue=client.current_track_message_show_queue,
            show_url=client.current_track_message_show_url,
        ))
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
        logger.warning(f"Failed to refresh now-playing message: {exc}")

async def set_repeat_current_track(enabled: bool, user=None, *, record_disable: bool = True) -> str:
    track_id = current_repeat_track_id()
    if not track_id:
        return "No track is currently playing."
    title = discord.utils.escape_markdown(str((client.current_track_info or {}).get("title") or "current track"))
    if enabled:
        client.repeat_current_track = True
        client.repeat_track_id = track_id
        logger.info(f"Repeat enabled for {track_id} by {user_display(user) if user else 'system'}.")
        await refresh_current_track_message()
        return f"Repeat enabled for **{title}**."
    if record_disable and user:
        client.repeat_disable_history.append({
            "track_id": track_id,
            "user_id": user_id_value(user),
            "timestamp": time.time(),
        })
        prune_repeat_disable_history()
    client.repeat_current_track = False
    client.repeat_track_id = None
    logger.info(f"Repeat disabled for {track_id} by {user_display(user) if user else 'system'}.")
    await refresh_current_track_message()
    return f"Repeat disabled for **{title}**."

async def perform_repeat_off_action() -> str:
    return await set_repeat_current_track(False, record_disable=False)

async def perform_voice_control_action(action: str, value: Optional[int] = None) -> str:
    if action == "skip":
        return await perform_skip_action()
    if action == "previous":
        return await perform_previous_action()
    if action == "stop":
        return await perform_stop_action()
    if action == "volume" and value is not None:
        return await perform_volume_action(value)
    if action == "repeat_off":
        return await perform_repeat_off_action()
    return "Unknown vote action."

async def handle_repeat_reaction(user, text_channel) -> str:
    track_id = current_repeat_track_id()
    if not track_id:
        return "No track is currently playing."
    if user_has_group(user, "norepeat"):
        logger.warning(f"Denied repeat reaction by {user_display(user)} ({user_id_value(user)}): norepeat.")
        return "You cannot use repeat because your account is in `norepeat`."
    if not client.repeat_current_track or client.repeat_track_id != track_id:
        return await set_repeat_current_track(True, user)
    if is_user_admin(user):
        return await set_repeat_current_track(False, user)
    recent_other_users = recent_repeat_disable_users(track_id, excluding_user_id=user_id_value(user))
    if len(recent_other_users) >= REPEAT_TOGGLE_VOTE_THRESHOLD:
        await request_voice_vote(user, text_channel, "repeat_off", "turn off repeat")
        return "Repeat-off vote started."
    return await set_repeat_current_track(False, user)

def sync_repeat_for_started_track(track: dict):
    track_id = str(track.get("id") or "").strip()
    if track.get("repeat_loop") and track_id:
        client.repeat_current_track = True
        client.repeat_track_id = track_id
        logger.info(f"Repeat loop enabled from queued repeat request for {track_id}.")
        return
    if client.repeat_current_track and client.repeat_track_id and client.repeat_track_id != track_id:
        logger.info(f"Repeat cleared because playback moved from {client.repeat_track_id} to {track_id}.")
        client.repeat_current_track = False
        client.repeat_track_id = None

async def apply_voice_vote(vote: VoiceVote):
    voice = active_voice_client(getattr(getattr(vote, "message", None), "guild", None))
    channel = getattr(voice, "channel", None)
    if not voice or not voice.is_connected() or voice_channel_id(channel) != vote.voice_channel_id:
        await finish_voice_vote(vote, "cancelled")
        if vote.message:
            await vote.message.channel.send("Vote cancelled because the bot is no longer in that voice channel.")
        return
    if vote.action in {"skip", "previous", "repeat_off"} and vote.track_id and vote.track_id != client.current_track_id:
        await finish_voice_vote(vote, "cancelled")
        if vote.message:
            await vote.message.channel.send("Vote cancelled because the current track changed.")
        return
    result = await perform_voice_control_action(vote.action, vote.value)
    append_runtime_audit_event("voice-vote-passed", details={
        "action": vote.action,
        "value": vote.value,
        "yes": len(vote.votes),
        "no": len(vote.no_votes),
        "track_id": vote.track_id,
    })
    await finish_voice_vote(vote, "passed")
    if vote.message:
        await vote.message.channel.send(result)

async def maybe_apply_voice_vote(vote: VoiceVote):
    voice = active_voice_client(getattr(getattr(vote, "message", None), "guild", None))
    channel = getattr(voice, "channel", None)
    quorum = voice_vote_quorum(channel)
    if len(vote.votes) >= quorum:
        await apply_voice_vote(vote)
        return True
    if len(vote.no_votes) >= quorum:
        await finish_voice_vote(vote, "rejected")
        return True
    if vote.message:
        try:
            await vote.message.edit(content=voice_vote_prompt_content(vote))
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            logger.warning(f"Failed to update voice vote message: {exc}")
    return False

async def request_voice_vote(user, text_channel, action: str, title: str, *, value: Optional[int] = None, ctx=None) -> bool:
    if action == "skip" and user_has_group(user, "noskip"):
        message = "You cannot skip because your account is in `noskip`."
        logger.warning(f"Denied skip request by {user_display(user)} ({user_id_value(user)}): noskip.")
        if ctx:
            await safe_interaction_send(ctx, message, ephemeral=True)
        else:
            await text_channel.send(message)
        return False
    if action == "volume" and user_has_group(user, "novolumechange"):
        message = "You cannot change volume because your account is in `novolumechange`."
        logger.warning(f"Denied volume request by {user_display(user)} ({user_id_value(user)}): novolumechange.")
        if ctx:
            await safe_interaction_send(ctx, message, ephemeral=True)
        else:
            await text_channel.send(message)
        return False
    guild = getattr(user, "guild", None) or getattr(text_channel, "guild", None)
    voice = active_voice_client(guild)
    voice_channel = getattr(voice, "channel", None)
    if voice is None or not voice.is_connected() or voice_channel is None:
        if ctx:
            await safe_interaction_send(ctx, "Not currently in a voice channel.")
        else:
            await text_channel.send("Not currently in a voice channel.")
        return False
    if not is_user_admin(user) and not user_in_bot_voice_channel(user):
        message = f"You must be in the bot's voice channel to {title.lower()}."
        if ctx:
            await safe_interaction_send(ctx, message, ephemeral=True)
        else:
            await text_channel.send(message)
        return False
    if action in {"skip", "previous", "repeat_off"} and not (voice.is_playing() or voice.is_paused()):
        if ctx:
            await safe_interaction_send(ctx, "No track is currently playing.")
        else:
            await text_channel.send("No track is currently playing.")
        return False
    direct_reason = "admin" if is_user_admin(user) else None
    if not direct_reason and not getattr(client, "voice_votes_enabled", True):
        direct_reason = "voice_votes_disabled"
    if direct_reason:
        result = await perform_voice_control_action(action, value)
        append_runtime_audit_event("voice-control-direct", actor=user, details={
            "action": action,
            "value": value,
            "reason": direct_reason,
            "track_id": client.current_track_id,
        })
        if ctx:
            await safe_interaction_send(ctx, result)
        else:
            await text_channel.send(result)
        return True

    key = voice_vote_key(voice_channel, action, value)
    user_id = user_id_value(user)
    vote = client.active_voice_votes.get(key)
    now = time.time()
    if vote and vote.expires_at > now:
        vote.votes.add(user_id)
        vote.no_votes.discard(user_id)
        if ctx:
            await safe_interaction_send(ctx, f"Your vote was counted for **{title}**.", ephemeral=True)
        await maybe_apply_voice_vote(vote)
        return True

    vote = VoiceVote(
        key=key,
        action=action,
        title=title,
        value=value,
        voice_channel_id=voice_channel_id(voice_channel),
        text_channel_id=getattr(text_channel, "id", 0),
        track_id=client.current_track_id if action in {"skip", "previous", "repeat_off"} else "",
        votes={user_id},
        created_at=now,
        expires_at=now + VOICE_VOTE_TIMEOUT_SECONDS,
    )
    if len(vote.votes) >= voice_vote_quorum(voice_channel):
        result = await perform_voice_control_action(action, value)
        append_runtime_audit_event("voice-vote-immediate", actor=user, details={
            "action": action,
            "value": value,
            "track_id": client.current_track_id,
            "quorum": voice_vote_quorum(voice_channel),
        })
        if ctx:
            await safe_interaction_send(ctx, f"Vote passed immediately. {result}")
        else:
            await text_channel.send(f"Vote passed immediately. {result}")
        return True

    if ctx:
        if ctx.response.is_done():
            vote.message = await ctx.followup.send(voice_vote_prompt_content(vote), wait=True)
        else:
            await ctx.response.send_message(voice_vote_prompt_content(vote))
            vote.message = await ctx.original_response()
    else:
        vote.message = await text_channel.send(voice_vote_prompt_content(vote))
    vote.message_id = vote.message.id
    client.active_voice_votes[key] = vote
    vote.task = asyncio.create_task(expire_voice_vote(vote))
    try:
        await vote.message.add_reaction("👍")
        await vote.message.add_reaction("👎")
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warning(f"Failed to add voice vote reactions: {exc}")
    logger.info(f"Started voice vote {action} value={value} quorum={voice_vote_quorum(voice_channel)}.")
    return True

async def handle_voice_vote_reaction(reaction, user) -> bool:
    vote = active_voice_vote_for_message(reaction.message.id)
    if not vote:
        return False
    emoji = str(reaction.emoji)
    if emoji not in {"👍", "👎"}:
        return True
    if vote.action == "skip" and user_has_group(user, "noskip"):
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except Exception as exc:
            logger.warning(f"Failed to remove denied skip vote reaction: {exc}")
        return True
    if vote.action == "volume" and user_has_group(user, "novolumechange"):
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except Exception as exc:
            logger.warning(f"Failed to remove denied volume vote reaction: {exc}")
        return True
    if vote.action == "repeat_off" and user_has_group(user, "norepeat"):
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except Exception as exc:
            logger.warning(f"Failed to remove denied repeat vote reaction: {exc}")
        return True
    if is_user_admin(user):
        if emoji == "👍":
            append_runtime_audit_event("voice-vote-admin-bypass", actor=user, details={
                "action": vote.action,
                "value": vote.value,
                "track_id": vote.track_id,
            })
            vote.votes.add(user_id_value(user))
            await apply_voice_vote(vote)
        else:
            client.active_voice_votes.pop(vote.key, None)
            await finish_voice_vote(vote, "rejected")
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except Exception as exc:
            logger.warning(f"Failed to remove admin vote reaction: {exc}")
        return True
    if not user_in_bot_voice_channel(user):
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except Exception as exc:
            logger.warning(f"Failed to remove denied vote reaction: {exc}")
        return True
    user_id = user_id_value(user)
    if emoji == "👍":
        vote.votes.add(user_id)
        vote.no_votes.discard(user_id)
    else:
        vote.no_votes.add(user_id)
        vote.votes.discard(user_id)
    try:
        await reaction.message.remove_reaction(reaction.emoji, user)
    except Exception as exc:
        logger.warning(f"Failed to remove voice vote reaction: {exc}")
    await maybe_apply_voice_vote(vote)
    return True

def cancel_auto_leave_task(reason: str = ""):
    task = getattr(client, "auto_leave_task", None)
    if task and not task.done():
        task.cancel()
        logger.info(f"Cancelled auto-leave task{f' ({reason})' if reason else ''}.")
    client.auto_leave_task = None

def cancel_alone_speed_reset_task(reason: str = ""):
    task = getattr(client, "alone_speed_reset_task", None)
    if task and not task.done():
        task.cancel()
        logger.info(f"Cancelled alone speed-reset task{f' ({reason})' if reason else ''}.")
    client.alone_speed_reset_task = None

def current_playback_recovery_tracks() -> list:
    tracks = []
    if client.current_track_info:
        tracks.append(dict(client.current_track_info))
    tracks.extend(dict(track) for track in queue)
    return tracks

def queue_blackbox_track_entry(track: dict) -> dict:
    return {
        "id": str(track.get("id") or ""),
        "title": str(track.get("title") or "Unknown title"),
        "webpage_url": str(track.get("webpage_url") or ""),
        "requested_by_user_id": track.get("requested_by_user_id"),
        "playlist_id": track.get("playlist_id"),
        "playlist_name": track.get("playlist_name"),
    }

def append_queue_blackbox_event(action: str, *, tracks: Optional[list] = None, actor=None, details: Optional[dict] = None):
    entry = {
        "timestamp": time.time(),
        "action": action,
        "boot_id": getattr(client, "boot_id", None),
        "actor_user_id": user_id_value(actor) if actor else None,
        "actor_discord_name": user_display(actor) if actor else None,
        "current_track": queue_blackbox_track_entry(client.current_track_info) if client.current_track_info else None,
        "queue_count": len(queue),
        "tracks": [queue_blackbox_track_entry(track) for track in (tracks or [])],
        "details": details or {},
    }
    try:
        events = []
        if os.path.isfile(QUEUE_BLACKBOX_FILE):
            with open(QUEUE_BLACKBOX_FILE, "r") as f:
                loaded = json.load(f)
            if not isinstance(loaded, list):
                logger.error("Queue blackbox file is not a JSON list; preserving it without appending.")
                return
            events = loaded
        events.append(entry)
        write_json_atomic(QUEUE_BLACKBOX_FILE, events)
    except Exception as exc:
        logger.error(f"Failed to append queue blackbox event: {exc}")

def save_last_session_recovery(voice_channel=None) -> int:
    tracks = current_playback_recovery_tracks()
    if not tracks:
        return 0
    text_channel = None
    if client.current_track_message:
        text_channel = getattr(client.current_track_message, "channel", None)
    payload = {
        "timestamp": time.time(),
        "reason": "auto_leave",
        "boot_id": getattr(client, "boot_id", None),
        "voice_channel_id": getattr(voice_channel, "id", None),
        "voice_channel_name": getattr(voice_channel, "name", None),
        "text_channel_id": getattr(text_channel, "id", None),
        "tracks": tracks,
    }
    write_json_atomic(LAST_SESSION_QUEUE_FILE, payload)
    append_queue_blackbox_event("last-session-saved", tracks=tracks, details={
        "reason": "auto_leave",
        "voice_channel_id": payload["voice_channel_id"],
        "text_channel_id": payload["text_channel_id"],
    })
    logger.info(f"Saved last session recovery with {len(tracks)} track(s) to {LAST_SESSION_QUEUE_FILE}.")
    return len(tracks)

def validate_last_session_recovery_payload(payload: dict) -> Optional[str]:
    if payload.get("reason") != "auto_leave":
        return "saved session is legacy or was not created by auto-leave"
    try:
        timestamp = float(payload.get("timestamp") or 0)
    except (TypeError, ValueError):
        timestamp = 0
    if timestamp <= 0:
        return "saved session has no valid timestamp"
    age = time.time() - timestamp
    if age > LAST_SESSION_RECOVERY_MAX_AGE_SECONDS:
        return f"saved session is too old ({int(age)}s > {LAST_SESSION_RECOVERY_MAX_AGE_SECONDS}s)"
    tracks = payload.get("tracks", [])
    if not isinstance(tracks, list) or not tracks:
        return "saved session has no tracks"
    return None

def load_last_session_recovery() -> tuple:
    if not os.path.isfile(LAST_SESSION_QUEUE_FILE):
        return None, "no saved last session file"
    try:
        with open(LAST_SESSION_QUEUE_FILE, "r") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            append_queue_blackbox_event("last-session-rejected", details={
                "reason": "saved session file is not a JSON object",
            })
            remove_last_session_recovery()
            return None, "saved session file is not a JSON object"
        tracks = payload.get("tracks", [])
        if not isinstance(tracks, list) or not tracks:
            append_queue_blackbox_event("last-session-rejected", details={
                "reason": "saved session has no tracks",
            })
            remove_last_session_recovery()
            return None, "saved session has no tracks"
        reason = validate_last_session_recovery_payload(payload)
        if reason:
            append_queue_blackbox_event("last-session-rejected", tracks=tracks if isinstance(tracks, list) else [], details={"reason": reason})
            remove_last_session_recovery()
            return None, reason
        payload["tracks"] = tracks
        return payload, None
    except Exception as exc:
        logger.error(f"Failed to load last session recovery file: {exc}")
        return None, str(exc)

def remove_last_session_recovery():
    try:
        if os.path.isfile(LAST_SESSION_QUEUE_FILE):
            os.remove(LAST_SESSION_QUEUE_FILE)
            logger.info("Removed last session recovery file after successful restore.")
    except Exception as exc:
        logger.warning(f"Failed to remove last session recovery file: {exc}")

def is_play_last_query(value: str) -> bool:
    return str(value or "").strip().lower() in {"last", "play:last", "/play:last"}

async def play_saved_track_now(voice, channel, track: dict):
    if not track.get("webpage_url") and track.get("id"):
        track["webpage_url"] = youtube_watch_url + str(track.get("id"))
    requester = track.get("requested_by_user_id")
    await resolve_track_for_playback(track, requested_by=requester)
    cached_file = None if user_has_group(requester, "nodownload") else cached_file_for_track(track)
    speed = playback_speed_for_track(track)
    track["playback_speed"] = speed
    if cached_file:
        track["file"] = cached_file
        append_runtime_audit_event("playback-source-cache", actor=requester, details={
            "video_id": track.get("id"),
            "title": track.get("title"),
            "cache_path": metadata_path_for_cache_file(cached_file),
            "speed": speed,
        })
        source = discord.FFmpegPCMAudio(cached_file, **ffmpeg_audio_options_for_speed(speed))
        player = discord.PCMVolumeTransformer(source, volume=client.volume)
    else:
        append_runtime_audit_event("playback-source-stream", actor=requester, details={
            "video_id": track.get("id"),
            "title": track.get("title"),
            "reason": "nodownload" if user_has_group(requester, "nodownload") else "cache_unavailable",
            "speed": speed,
        })
        player, _ = await YTDLSource.from_url(track['webpage_url'], stream=True, speed=speed)
    voice.play(player, after=lambda e, vid=track.get('id'): after_played_track(e, vid, channel))
    client.current_track_id = track.get('id')
    client.currently_playing = True
    client.last_track_info = client.current_track_info
    client.current_track_info = track
    client.current_track_started_at = time.time()
    sync_repeat_for_started_track(track)
    if track not in client.song_history:
        client.song_history.append(track)
    await publish_now_playing(channel, track)

async def restore_last_session(ctx) -> bool:
    payload, reason = load_last_session_recovery()
    if not payload:
        append_runtime_audit_event("last-session-restore-rejected", actor=ctx.user, details={
            "reason": reason,
        })
        await ctx.followup.send(f"No valid saved last session is available. ({reason})")
        return False
    if client.currently_playing:
        await ctx.followup.send("Something is already playing. Stop playback before using `/play:last`.")
        return False
    if not ctx.user.voice or not ctx.user.voice.channel:
        await ctx.followup.send("You need to join a voice channel first.")
        return False
    tracks = [track for track in payload.get("tracks", []) if track.get("webpage_url") or track.get("id")]
    if not tracks:
        await ctx.followup.send("The saved last session has no playable tracks.")
        return False
    voice = active_voice_client(ctx.guild)
    if voice is None or not voice.is_connected():
        try:
            voice = await ctx.user.voice.channel.connect()
            client.current_voice_channel = voice
            apply_channel_volume_default(ctx.user.voice.channel, "play last join")
            cancel_auto_leave_task("play last joined voice")
            cancel_alone_speed_reset_task("play last joined voice")
            client.song_history = []
            await ctx.followup.send(f"Joined voice channel {ctx.user.voice.channel.name}")
        except Exception as exc:
            logger.error(f"Voice connection failed during /play last: {exc}")
            await ctx.followup.send("Couldn't join voice channel.")
            return False
    else:
        client.current_voice_channel = voice
        if not await require_voice_control(ctx, "restore last session"):
            return False
    first_track = dict(tracks[0])
    queue[:] = [dict(track) for track in tracks[1:]]
    try:
        await play_saved_track_now(voice, ctx.channel, first_track)
    except Exception as exc:
        logger.error(f"Failed to restore last session playback: {exc}")
        await ctx.followup.send("Failed to restore the saved last session.")
        return False
    remove_last_session_recovery()
    append_queue_blackbox_event("last-session-restored", tracks=tracks, actor=ctx.user, details={
        "saved_boot_id": payload.get("boot_id"),
        "saved_at": payload.get("timestamp"),
    })
    append_runtime_audit_event("last-session-restored", actor=ctx.user, details={
        "track_count": len(tracks),
        "saved_boot_id": payload.get("boot_id"),
        "saved_at": payload.get("timestamp"),
    })
    await ctx.followup.send(f"Restored last session with {len(tracks)} track(s).")
    logger.info(f"Restored last session through /play:last with {len(tracks)} track(s).")
    return True

async def perform_auto_leave_if_still_alone(voice_channel):
    try:
        await asyncio.sleep(client.auto_leave_delay_seconds)
        if not client.auto_leave_enabled:
            return
        if asyncio.current_task() is not client.auto_leave_task:
            return
        voice = active_voice_client(getattr(voice_channel, "guild", None))
        if voice is None or not voice.is_connected() or getattr(voice, "channel", None) != voice_channel:
            return
        if not bot_is_alone_in_voice(voice_channel):
            return
        notify_channel = getattr(client.current_track_message, "channel", None)
        await reset_playback_speed_after_alone(voice_channel, reason="auto-leave")
        saved_count = save_last_session_recovery(voice_channel)
        if not saved_count:
            logger.info("Auto-leave found no current song or queue to save.")
        client.auto_leave_disconnect_in_progress = True
        try:
            if voice.is_playing() or voice.is_paused():
                voice.stop()
            queue.clear()
            await clear_playback_tracking("auto-leave")
            await voice.disconnect()
            reset_session_volume("auto-leave")
            await update_bot_presence_idle(reason="auto-leave", channel=notify_channel)
            if notify_channel and saved_count:
                try:
                    await notify_channel.send(
                        f"Left voice because nobody was listening. Saved {saved_count} song(s); start again with `/play:last`."
                    )
                except Exception as exc:
                    logger.warning(f"Failed to send auto-leave recovery message: {exc}")
            logger.info(f"Auto-left voice channel {getattr(voice_channel, 'name', voice_channel)} after being alone.")
        finally:
            client.auto_leave_disconnect_in_progress = False
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.error(f"Auto-leave task failed: {exc}")
    finally:
        if asyncio.current_task() is client.auto_leave_task:
            client.auto_leave_task = None

async def perform_alone_speed_reset_if_still_alone(voice_channel):
    try:
        await asyncio.sleep(alone_speed_reset_delay_seconds())
        if asyncio.current_task() is not client.alone_speed_reset_task:
            return
        voice = active_voice_client(getattr(voice_channel, "guild", None))
        if voice is None or not voice.is_connected() or getattr(voice, "channel", None) != voice_channel:
            return
        if not bot_is_alone_in_voice(voice_channel):
            return
        await reset_playback_speed_after_alone(voice_channel, reason="alone-timer")
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.error(f"Alone speed-reset task failed: {exc}")
    finally:
        if asyncio.current_task() is client.alone_speed_reset_task:
            client.alone_speed_reset_task = None

def schedule_alone_speed_reset_if_needed(channel):
    if channel is None:
        return
    if not bot_is_alone_in_voice(channel):
        cancel_alone_speed_reset_task("user present")
        return
    if not playback_speed_reset_needed():
        cancel_alone_speed_reset_task("speed already normal")
        return
    task = getattr(client, "alone_speed_reset_task", None)
    if task and not task.done():
        return
    client.alone_speed_reset_task = asyncio.create_task(perform_alone_speed_reset_if_still_alone(channel))
    logger.info(f"Scheduled playback speed reset to 1x in {alone_speed_reset_delay_seconds()}s for channel {getattr(channel, 'name', channel)}.")

def schedule_auto_leave_if_needed(channel):
    if not client.auto_leave_enabled or channel is None:
        return
    if not bot_is_alone_in_voice(channel):
        cancel_auto_leave_task("user present")
        return
    task = getattr(client, "auto_leave_task", None)
    if task and not task.done():
        return
    client.auto_leave_task = asyncio.create_task(perform_auto_leave_if_still_alone(channel))
    logger.info(f"Scheduled auto-leave in {client.auto_leave_delay_seconds}s for channel {getattr(channel, 'name', channel)}.")

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
        "cache_mode": "follow_global",
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
            playlist.setdefault("type", "playlist")
            playlist.setdefault("folder", os.path.basename(root))
            playlist.setdefault("cache_mode", "follow_global")
            for track in playlist.get("tracks", []):
                normalize_playlist_track_cache_fields(track)
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
    playlists = [
        playlist for playlist in load_playlists()
        if not is_favorites_playlist(playlist) and can_view_playlist(user, playlist)
    ]
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
        if is_favorites_playlist(playlist):
            continue
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
    item = {
        "title": str(track.get("title") or "Unknown title"),
        "id": str(track.get("id") or ""),
        "webpage_url": track.get("webpage_url") or youtube_watch_url + str(track.get("id") or ""),
        "added_by_user_id": user_id_value(user),
        "added_by_discord_name": user_display(user),
        "added_at": time.time(),
    }
    if track.get("needs_refresh"):
        item["needs_refresh"] = True
    normalize_playlist_track_cache_fields(item, source_track=track)
    return item

def normalize_playlist_track_cache_fields(track: dict, *, source_track: Optional[dict] = None) -> dict:
    source_track = source_track or track
    if not track.get("webpage_url") and track.get("id"):
        track["webpage_url"] = canonical_youtube_url(track.get("id"))
    cache_key = cache_key_for_track(track) or cache_key_for_track(source_track)
    if cache_key:
        track["cache_key"] = cache_key
    cache_path = source_track.get("cache_path") or track.get("cache_path")
    file_path = source_track.get("file") or path_from_metadata(cache_path)
    if file_path and is_safe_cache_path(file_path, cache_key):
        ext = os.path.splitext(path_from_metadata(file_path))[1].lstrip(".").lower()
        track["cache_path"] = metadata_path_for_cache_file(path_from_metadata(file_path))
        track["ext"] = ext
        if os.path.basename(path_from_metadata(file_path)).startswith("plst-"):
            track["cache_mode"] = "playlist"
        else:
            track["cache_mode"] = "shortterm"
    else:
        if cache_path:
            logger.warning(
                f"Ignoring unsafe or missing playlist cache path for "
                f"{track.get('title', 'Unknown title')}: {cache_path}"
            )
        track["cache_path"] = None
        track.setdefault("cache_mode", "streaming")
    track.setdefault("ext", None)
    return track

def playlist_track_identity(track: dict) -> Optional[str]:
    video_id = str(track.get("id") or "").strip()
    if video_id:
        return f"id:{video_id}"
    url = str(track.get("webpage_url") or "").strip()
    if not url:
        return None
    parsed_id = parse_youtube_video_id(url)
    if parsed_id:
        return f"id:{parsed_id}"
    return f"url:{url.lower()}"

def playlist_existing_track_identities(playlist: dict) -> set:
    identities = set()
    for track in playlist.get("tracks", []):
        identity = playlist_track_identity(track)
        if identity:
            identities.add(identity)
    return identities

def playlist_name_error(name: str, user=None) -> Optional[str]:
    safe_name = normalize_playlist_name(name)
    if not safe_name:
        return "I need a playlist name. Try `/playlist new` for guided setup."
    if len(safe_name) > PLAYLIST_NAME_MAX_LENGTH:
        return f"Playlist names must be {PLAYLIST_NAME_MAX_LENGTH} characters or shorter."
    if resolve_playlist_reference(safe_name, user, require_visible=False):
        return "A playlist with that name already exists. Choose another name or remove the old playlist first."
    return None

def extract_youtube_urls(text: str) -> list:
    urls = []
    for match in re.findall(r"https?://[^\s<>()]+", str(text or "")):
        candidate = match.rstrip(".,);]>")
        try:
            validate_media_query(candidate)
        except ValueError:
            continue
        if (parse_youtube_video_id(candidate) or parse_youtube_playlist_id(candidate)) and candidate not in urls:
            urls.append(candidate)
    return urls

def playlist_session_key(user, channel) -> tuple:
    guild = getattr(channel, "guild", None)
    guild_id = getattr(guild, "id", 0) or 0
    return (guild_id, getattr(channel, "id", 0), user_id_value(user))

def expire_playlist_creation_sessions():
    now = time.time()
    expired = [
        key for key, session in client.playlist_creation_sessions.items()
        if now - session.updated_at > PLAYLIST_CREATION_TIMEOUT_SECONDS
    ]
    for key in expired:
        client.playlist_creation_sessions.pop(key, None)
        task = client.playlist_creation_timeout_tasks.pop(key, None)
        if task:
            task.cancel()

def queue_tracks_for_playlist_import(user) -> list:
    tracks = []
    for track in queue:
        if track.get("webpage_url") or track.get("id"):
            tracks.append(playlist_track_from_track(track, user))
    return tracks

def queue_tracks_missing_from_playlist(playlist: dict, user) -> tuple:
    existing = playlist_existing_track_identities(playlist)
    additions = []
    skipped_duplicates = 0
    skipped_missing = 0
    for track in queue:
        if not (track.get("webpage_url") or track.get("id")):
            skipped_missing += 1
            continue
        candidate = playlist_track_from_track(track, user)
        identity = playlist_track_identity(candidate)
        if not identity:
            skipped_missing += 1
            continue
        if identity in existing:
            skipped_duplicates += 1
            continue
        existing.add(identity)
        additions.append(candidate)
    return additions, skipped_duplicates, skipped_missing

def save_new_playlist(name: str, owner, tracks: Optional[list] = None, visibility: str = "private") -> dict:
    playlist = make_playlist_metadata(name, owner, visibility)
    playlist["tracks"] = tracks or []
    save_playlist(playlist)
    append_playlist_blackbox_event("created", playlist, owner)
    logger.info(f"Playlist created: {playlist['name']} ({playlist['id']}) by {user_display(owner)}")
    return playlist

def playlist_created_message(playlist: dict) -> str:
    name = discord.utils.escape_markdown(str(playlist.get("name", "playlist")))
    count = len(playlist.get("tracks", []))
    return (
        f"Created playlist **{name}** with {count} track(s). "
        f"Play it with `/playlist play {playlist.get('name')}`."
    )

def favorite_playlist_folder(user_id: int) -> str:
    return f"favorites-{int(user_id)}"

def make_favorites_metadata(user, visibility: str = "private") -> dict:
    uid = user_id_value(user)
    now = time.time()
    return {
        "id": f"fav-{uid}",
        "name": f"{user_display(user)} favorites",
        "type": "favorites",
        "generated_at": now,
        "updated_at": now,
        "locked": True,
        "visibility": visibility,
        "owner_user_id": uid,
        "owner_discord_name": user_display(user),
        "manager_user_ids": [],
        "tracks": [],
        "folder": favorite_playlist_folder(uid),
        "cache_mode": "favorites",
        "predownloaded": False,
        "deleted": False,
    }

def is_favorites_playlist(playlist: dict) -> bool:
    return playlist.get("type") == "favorites" or str(playlist.get("id", "")).startswith("fav-")

def favorites_playlist_for_user(user, *, create: bool = False) -> Optional[dict]:
    uid = user_id_value(user)
    if not uid:
        return None
    for playlist in load_playlists(include_deleted=False):
        if is_favorites_playlist(playlist) and playlist_owner_id(playlist) == uid:
            if user_display(user) and playlist.get("owner_discord_name") != user_display(user):
                playlist["owner_discord_name"] = user_display(user)
                playlist["name"] = f"{user_display(user)} favorites"
                save_playlist(playlist)
            return playlist
    if not create:
        return None
    playlist = make_favorites_metadata(user)
    save_playlist(playlist)
    append_playlist_blackbox_event("favorites-created", playlist, user)
    logger.info(f"Favorites playlist created for {user_display(user)} ({uid}).")
    return playlist

def favorites_track_limit() -> int:
    return FAVORITES_MAX_TRACKS_PER_USER

def favorites_cache_policy() -> dict:
    return client.user_permissions_config.setdefault("favorites_cache", {
        "enabled": False,
        "max_bytes": FAVORITES_CACHE_DEFAULT_MAX_BYTES,
        "per_user_tracks": FAVORITES_CACHE_DEFAULT_TRACKS_PER_USER,
    })

def set_favorites_cache_policy(enabled: bool, *, max_gb: Optional[float] = None, per_user_tracks: Optional[int] = None):
    policy = favorites_cache_policy()
    policy["enabled"] = bool(enabled)
    if max_gb is not None:
        max_bytes = int(float(max_gb) * 1024 * 1024 * 1024)
        policy["max_bytes"] = max(0, min(max_bytes, FAVORITES_CACHE_MAX_BYTES))
    else:
        policy.setdefault("max_bytes", FAVORITES_CACHE_DEFAULT_MAX_BYTES)
    if per_user_tracks is not None:
        policy["per_user_tracks"] = max(0, min(int(per_user_tracks), FAVORITES_MAX_TRACKS_PER_USER))
    else:
        policy.setdefault("per_user_tracks", FAVORITES_CACHE_DEFAULT_TRACKS_PER_USER)
    save_user_permissions_config()

def favorite_cache_bytes() -> int:
    total = 0
    seen = set()
    for playlist in load_playlists():
        if not is_favorites_playlist(playlist):
            continue
        for track in playlist.get("tracks", []):
            cache_key = cache_key_for_track(track)
            file_path = path_from_metadata(track.get("cache_path"))
            if not file_path or file_path in seen:
                continue
            if is_safe_cache_path(file_path, cache_key) and os.path.basename(file_path).startswith("plst-"):
                try:
                    total += os.path.getsize(file_path)
                    seen.add(file_path)
                except OSError:
                    continue
    return total

async def prepare_favorites_cache_round_robin() -> dict:
    policy = favorites_cache_policy()
    if not policy.get("enabled"):
        return {"enabled": False, "downloaded": 0, "reused": 0, "bytes": 0, "capped": False}
    max_bytes = min(int(policy.get("max_bytes", FAVORITES_CACHE_DEFAULT_MAX_BYTES)), FAVORITES_CACHE_MAX_BYTES)
    per_user_tracks = max(0, min(int(policy.get("per_user_tracks", FAVORITES_CACHE_DEFAULT_TRACKS_PER_USER)), FAVORITES_MAX_TRACKS_PER_USER))
    favorites = [
        playlist for playlist in load_playlists()
        if is_favorites_playlist(playlist)
        and favorite_cache_allowed_for_user(playlist_owner_id(playlist))
        and not user_has_group(playlist_owner_id(playlist), "nodownload")
    ]
    favorites.sort(key=lambda item: (item.get("generated_at", 0), playlist_owner_id(item)))
    current_bytes = favorite_cache_bytes()
    result = {"enabled": True, "downloaded": 0, "reused": 0, "bytes": current_bytes, "capped": False}
    changed = set()
    for index in range(per_user_tracks):
        for playlist in favorites:
            tracks = playlist.get("tracks", [])
            if index >= len(tracks):
                continue
            if current_bytes >= max_bytes:
                result["capped"] = True
                continue
            track = tracks[index]
            normalize_playlist_track_cache_fields(track)
            cache_key = cache_key_for_track(track)
            existing = find_existing_cache_file(cache_key, prefer_playlist=True, video_id=str(track.get("id") or "").strip() or None)
            if existing and os.path.basename(existing).startswith("plst-"):
                apply_cache_fields(track, existing, cache_mode="playlist")
                result["reused"] += 1
                changed.add(playlist.get("id"))
                continue
            try:
                did_download, size = await cache_playlist_track(
                    track,
                    playlist_cache=True,
                    projected_limit=max(0, max_bytes - current_bytes),
                )
            except Exception as exc:
                logger.warning(f"Favorites cache download failed for {track.get('id')}: {exc}")
                continue
            if did_download:
                if current_bytes + size > max_bytes:
                    file_path = track.get("file")
                    cache_key = cache_key_for_track(track)
                    if file_path and is_safe_cache_path(file_path, cache_key):
                        try:
                            os.remove(file_path)
                        except OSError as exc:
                            logger.warning(f"Failed to remove over-limit favorites cache file {file_path}: {exc}")
                    apply_cache_fields(track, None, cache_mode="streaming")
                    result["capped"] = True
                    continue
                current_bytes += size
                result["downloaded"] += 1
                result["bytes"] = current_bytes
                changed.add(playlist.get("id"))
            elif size == 0 and current_bytes >= max_bytes:
                result["capped"] = True
    for playlist in favorites:
        if playlist.get("id") in changed:
            playlist["predownloaded"] = True
            playlist["predownloaded_at"] = time.time()
            save_playlist(playlist)
    return result

def favorite_added_notice(user, *, duplicate: bool = False) -> str:
    name = discord.utils.escape_markdown(user_display(user))
    if duplicate:
        return f"{FAVORITE_REACTION} {name} already had this in their favorites."
    return f"{FAVORITE_REACTION} {name} added this to their favorites."

def favorite_removed_notice(user) -> str:
    name = discord.utils.escape_markdown(user_display(user))
    return f"{FAVORITE_REACTION} {name} removed this from their favorites."

async def add_current_track_to_favorites(user) -> tuple:
    track = client.current_track_info
    if not track:
        return False, "No song is currently playing."
    playlist = favorites_playlist_for_user(user, create=True)
    if not playlist:
        return False, "Could not create your favorites playlist."
    identities = playlist_existing_track_identities(playlist)
    candidate = playlist_track_from_track(track, user)
    identity = playlist_track_identity(candidate)
    if identity and identity in identities:
        original_count = len(playlist.get("tracks", []))
        playlist["tracks"] = [
            saved for saved in playlist.get("tracks", [])
            if playlist_track_identity(saved) != identity
        ]
        playlist["updated_at"] = time.time()
        playlist["owner_discord_name"] = user_display(user)
        playlist["name"] = f"{user_display(user)} favorites"
        save_playlist(playlist)
        append_playlist_blackbox_event("favorite-removed", playlist, user)
        logger.info(
            f"Favorite removed: user={user_display(user)} ({user_id_value(user)}) "
            f"title={candidate.get('title')} id={candidate.get('id')} "
            f"count={original_count}->{len(playlist.get('tracks', []))}"
        )
        return True, favorite_removed_notice(user)
    if len(playlist.get("tracks", [])) >= favorites_track_limit():
        return False, f"Favorites can store up to {favorites_track_limit()} song(s). Remove one before adding more."
    playlist.setdefault("tracks", []).append(candidate)
    playlist["updated_at"] = time.time()
    playlist["owner_discord_name"] = user_display(user)
    playlist["name"] = f"{user_display(user)} favorites"
    save_playlist(playlist)
    append_playlist_blackbox_event("favorite-added", playlist, user)
    logger.info(
        f"Favorite added: user={user_display(user)} ({user_id_value(user)}) "
        f"title={candidate.get('title')} id={candidate.get('id')}"
    )
    return True, favorite_added_notice(user)

def favorites_list_message(playlist: dict, *, viewer=None) -> str:
    owner = discord.utils.escape_markdown(str(playlist.get("owner_discord_name", "unknown")))
    lines = [
        f"**{owner}'s favorites**",
        f"- visibility: `{playlist.get('visibility', 'private')}`",
        f"- tracks: `{len(playlist.get('tracks', []))}/{favorites_track_limit()}`",
    ]
    tracks = playlist.get("tracks", [])
    if not tracks:
        lines.append("_no favorites saved yet._")
        return "\n".join(lines)
    lines.append("")
    for index, track in enumerate(tracks, start=1):
        title = discord.utils.escape_markdown(str(track.get("title") or "Unknown title"))
        video_id = discord.utils.escape_markdown(str(track.get("id") or ""))
        entry = f"{index}. **{title}** (`{video_id}`)"
        candidate = "\n".join(lines + [entry, f"_and {len(tracks) - index} more favorite(s) omitted._"])
        if len(candidate) > DISCORD_MESSAGE_SAFE_LIMIT:
            lines.append(f"_and {len(tracks) - index + 1} more favorite(s) omitted._")
            break
        lines.append(entry)
    return "\n".join(lines)

def favorites_status_message(user) -> str:
    playlist = favorites_playlist_for_user(user, create=True)
    policy = favorites_cache_policy()
    groups = permissions_summary_for(user)
    cache_allowed = favorite_cache_allowed_for_user(user) and not user_has_group(user, "nodownload")
    return "\n".join([
        "**favorites status**",
        f"- visibility: `{playlist.get('visibility', 'private')}`",
        f"- tracks: `{len(playlist.get('tracks', []))}/{favorites_track_limit()}`",
        f"- cache eligible: `{'yes' if cache_allowed else 'no'}`",
        f"- global favorites cache: `{'enabled' if policy.get('enabled') else 'disabled'}`",
        f"- favorites cache cap: `{human_bytes(policy.get('max_bytes', FAVORITES_CACHE_DEFAULT_MAX_BYTES))}`",
        f"- cache tracks per user: `{policy.get('per_user_tracks', FAVORITES_CACHE_DEFAULT_TRACKS_PER_USER)}`",
        f"- permissions: {groups}",
    ])

def playlist_track_identity(track: dict) -> Optional[str]:
    video_id = str(track.get("id") or "").strip()
    if video_id:
        return f"id:{video_id}"
    url = str(track.get("webpage_url") or "").strip()
    if not url:
        return None
    parsed_id = parse_youtube_video_id(url)
    if parsed_id:
        return f"id:{parsed_id}"
    return f"url:{url.lower()}"

def playlist_existing_track_identities(playlist: dict) -> set:
    identities = set()
    for track in playlist.get("tracks", []):
        identity = playlist_track_identity(track)
        if identity:
            identities.add(identity)
    return identities

def playlist_name_error(name: str, user=None) -> Optional[str]:
    safe_name = normalize_playlist_name(name)
    if not safe_name:
        return "I need a playlist name. Try `/playlist new` for guided setup."
    if len(safe_name) > PLAYLIST_NAME_MAX_LENGTH:
        return f"Playlist names must be {PLAYLIST_NAME_MAX_LENGTH} characters or shorter."
    if resolve_playlist_reference(safe_name, user, require_visible=False):
        return "A playlist with that name already exists. Choose another name or remove the old playlist first."
    return None

def extract_youtube_urls(text: str) -> list:
    urls = []
    for match in re.findall(r"https?://[^\s<>()]+", str(text or "")):
        candidate = match.rstrip(".,);]>")
        try:
            validate_media_query(candidate)
        except ValueError:
            continue
        if (parse_youtube_video_id(candidate) or parse_youtube_playlist_id(candidate)) and candidate not in urls:
            urls.append(candidate)
    return urls

def playlist_session_key(user, channel) -> tuple:
    guild = getattr(channel, "guild", None)
    guild_id = getattr(guild, "id", 0) or 0
    return (guild_id, getattr(channel, "id", 0), user_id_value(user))

def expire_playlist_creation_sessions():
    now = time.time()
    expired = [
        key for key, session in client.playlist_creation_sessions.items()
        if now - session.updated_at > PLAYLIST_CREATION_TIMEOUT_SECONDS
    ]
    for key in expired:
        client.playlist_creation_sessions.pop(key, None)
        task = client.playlist_creation_timeout_tasks.pop(key, None)
        if task:
            task.cancel()

def queue_tracks_for_playlist_import(user) -> list:
    tracks = []
    for track in queue:
        if track.get("webpage_url") or track.get("id"):
            tracks.append(playlist_track_from_track(track, user))
    return tracks

def queue_tracks_missing_from_playlist(playlist: dict, user) -> tuple:
    existing = playlist_existing_track_identities(playlist)
    additions = []
    skipped_duplicates = 0
    skipped_missing = 0
    for track in queue:
        if not (track.get("webpage_url") or track.get("id")):
            skipped_missing += 1
            continue
        candidate = playlist_track_from_track(track, user)
        identity = playlist_track_identity(candidate)
        if not identity:
            skipped_missing += 1
            continue
        if identity in existing:
            skipped_duplicates += 1
            continue
        existing.add(identity)
        additions.append(candidate)
    return additions, skipped_duplicates, skipped_missing

def save_new_playlist(name: str, owner, tracks: Optional[list] = None, visibility: str = "private") -> dict:
    playlist = make_playlist_metadata(name, owner, visibility)
    playlist["tracks"] = tracks or []
    save_playlist(playlist)
    append_playlist_blackbox_event("created", playlist, owner)
    logger.info(f"Playlist created: {playlist['name']} ({playlist['id']}) by {user_display(owner)}")
    return playlist

def playlist_created_message(playlist: dict) -> str:
    name = discord.utils.escape_markdown(str(playlist.get("name", "playlist")))
    count = len(playlist.get("tracks", []))
    return (
        f"Created playlist **{name}** with {count} track(s). "
        f"Play it with `/playlist play {playlist.get('name')}`."
    )

def playlist_to_queue_tracks(playlist: dict, *, block_id: Optional[str] = None) -> list:
    tracks = playlist.get("tracks", [])
    block_id = block_id or generate_playlist_id()
    total = len(tracks)
    queue_tracks = []
    for index, track in enumerate(tracks, start=1):
        normalize_playlist_track_cache_fields(track)
        queue_track = {
            "id": str(track.get("id") or ""),
            "title": str(track.get("title") or "Unknown title"),
            "webpage_url": track.get("webpage_url") or youtube_watch_url + str(track.get("id") or ""),
            "cache_key": track.get("cache_key"),
            "cache_mode": track.get("cache_mode", "streaming"),
            "cache_path": track.get("cache_path"),
            "ext": track.get("ext"),
            "needs_refresh": bool(track.get("needs_refresh")),
            "playlist_id": playlist.get("id"),
            "playlist_name": playlist.get("name"),
            "playlist_block_id": block_id,
            "playlist_index": index,
            "playlist_total": total,
        }
        cached_file = cached_file_for_track(queue_track)
        if cached_file:
            queue_track["file"] = cached_file
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
        f"- {playlist_cache_status_line(playlist)}",
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
    expected_cache_key = canonical_cache_key_from_video_id(video_id) if video_id else None
    return is_safe_cache_path(file_path, expected_cache_key)

def track_display_parts(track: dict) -> tuple:
    title = discord.utils.escape_markdown(str(track.get('title') or 'Unknown title'))
    url = track.get('webpage_url') or youtube_watch_url + str(track.get('id') or '')
    url = discord.utils.escape_markdown(str(url))
    return title, url

def first_metadata_text(track: dict, *keys) -> str:
    for key in keys:
        value = track.get(key)
        if isinstance(value, (list, tuple)):
            parts = [str(item).strip() for item in value if str(item or "").strip()]
            if parts:
                return ", ".join(parts[:3])
            continue
        text = str(value or "").strip()
        if text and text.lower() not in {"unknown", "unknown title", "none", "null"}:
            return text
    return ""

def clean_presence_text(value: str) -> str:
    text = truncate_text(sanitize_debug_text(value), BOT_PRESENCE_MAX_LENGTH)
    return text.strip() or UNKNOWN_BOT_PRESENCE

def parse_song_artist_from_title(title: str) -> tuple:
    text = str(title or "").strip()
    if " - " not in text:
        return "", ""
    artist, song = [part.strip() for part in text.split(" - ", 1)]
    if not artist or not song:
        return "", ""
    return song, artist

def bot_presence_for_track(track: Optional[dict]) -> tuple:
    if track is None:
        return DEFAULT_BOT_PRESENCE, "idle"
    try:
        song = first_metadata_text(track, "track", "alt_title")
        artist = first_metadata_text(track, "artist", "artists", "creator", "uploader", "channel")
        if song and artist:
            return clean_presence_text(f"{song} - {artist}"), "metadata"

        title = first_metadata_text(track, "title", "fulltitle")
        parsed_song, parsed_artist = parse_song_artist_from_title(title)
        if parsed_song and parsed_artist:
            return clean_presence_text(f"{parsed_song} - {parsed_artist}"), "title-parse"
        if title and artist:
            return clean_presence_text(f"{title} - {artist}"), "metadata-title"
        if title:
            return clean_presence_text(f"PLAYING ({title})"), "title-fallback"

        return UNKNOWN_BOT_PRESENCE, "unknown"
    except Exception as exc:
        logger.error(f"Failed to format bot presence for track: {exc}")
        return DEFAULT_BOT_PRESENCE, "format-error"

async def send_presence_operation_notice(channel, message: str):
    if not client.user_operation_debug_messages or channel is None:
        return
    try:
        await channel.send(message)
    except Exception as exc:
        logger.warning(f"Failed to send bot presence operation notice: {exc}")

async def update_bot_presence(track: Optional[dict] = None, *, reason: str = "", channel=None):
    presence_text, source = bot_presence_for_track(track if client.currently_playing else None)
    fallback_title = track.get("title", "-") if isinstance(track, dict) else "-"
    if source == "title-fallback":
        logger.info(
            "Bot presence used title fallback formatting: "
            f"reason={reason} track={fallback_title}"
        )
    elif source in {"unknown", "format-error"}:
        logger.warning(
            "Bot presence used fallback formatting: "
            f"source={source} reason={reason} track={fallback_title}"
        )
    if presence_text == client.last_presence_text:
        logger.debug(f"Bot presence unchanged ({presence_text}) during {reason or 'unknown reason'}.")
        return
    try:
        await client.change_presence(activity=discord.Game(name=presence_text))
        client.last_presence_text = presence_text
        logger.info(f"Bot presence updated: {presence_text} (source={source}, reason={reason or 'unspecified'}).")
    except Exception as exc:
        logger.error(f"Failed to update bot presence to {presence_text!r}: {exc}")
        append_runtime_audit_event("bot-presence-error", details={
            "requested_presence": presence_text,
            "source": source,
            "reason": reason,
            "error": str(exc),
            "track_id": track.get("id") if isinstance(track, dict) else None,
            "title": track.get("title") if isinstance(track, dict) else None,
        })
        try:
            await client.change_presence(activity=discord.Game(name=DEFAULT_BOT_PRESENCE))
            client.last_presence_text = DEFAULT_BOT_PRESENCE
            logger.info(f"Bot presence fell back to {DEFAULT_BOT_PRESENCE} after update error.")
        except Exception as fallback_exc:
            logger.error(f"Failed to apply fallback bot presence: {fallback_exc}")
        await send_presence_operation_notice(
            channel or getattr(getattr(client, "current_track_message", None), "channel", None),
            "**admin operation**\n"
            "- bot status update failed\n"
            f"- fallback: `{DEFAULT_BOT_PRESENCE}`\n"
            f"- reason: `{discord.utils.escape_markdown(truncate_text(str(exc), 180))}`",
        )

async def update_bot_presence_idle(*, reason: str = "", channel=None):
    await update_bot_presence(None, reason=reason, channel=channel)

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

def format_now_playing(track: dict, *, show_queue: bool = False, show_url: bool = True) -> str:
    title, url = track_display_parts(track)
    now_playing = f"🎵 Now playing: **{title}**"
    if show_url:
        now_playing += f"\n*{url}*"
    if track.get("playlist_name"):
        playlist_name = discord.utils.escape_markdown(str(track.get("playlist_name")))
        now_playing += f"\n_from playlist: **{playlist_name}**_"
    speed = playback_speed_for_track(track)
    if abs(speed - 1.0) > 0.001:
        now_playing += f"\n_speed: **{speed:g}x**_"
    if client.repeat_current_track and client.repeat_track_id == str(track.get("id") or ""):
        now_playing += "\n_repeat: **on**_"
    if client.current_track_favorite_notice:
        now_playing += f"\n{client.current_track_favorite_notice}"
    if not show_queue:
        return now_playing
    divider = "━━━━━━━━━━━━"
    fixed_content = f"\n\n{divider}\n\n{now_playing}"
    queue_chars = DISCORD_MESSAGE_SAFE_LIMIT - len(fixed_content)
    return f"{format_queue_section(max_chars=queue_chars, show_links=show_url)}{fixed_content}"

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

async def clear_playback_tracking(reason: str, *, remove_controls: bool = True):
    old_message = client.current_track_message
    client.currently_playing = False
    client.current_track_id = None
    client.current_track_info = None
    client.current_track_started_at = None
    client.current_track_message = None
    client.current_track_message_show_queue = False
    client.current_track_message_show_url = True
    client.current_track_favorite_notice = ""
    client.repeat_current_track = False
    client.repeat_track_id = None
    if remove_controls:
        await remove_control_reactions(old_message)
    logger.info(f"Cleared playback tracking state: {reason}.")

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
    client.current_track_favorite_notice = ""
    client.current_track_message_show_url = True
    same_channel = old_message and getattr(getattr(old_message, "channel", None), "id", None) == channel.id
    newer_message_exists = await has_newer_message(channel, old_message) if same_channel else None
    can_edit = same_channel and not newer_message_exists

    if can_edit:
        try:
            content = format_now_playing(track, show_queue=client.current_track_message_show_queue, show_url=True)
            await old_message.edit(content=content)
            await add_control_reactions(old_message)
            if acknowledge:
                await acknowledge("Now playing message updated.", ephemeral=True)
            client.current_track_message = old_message
            logger.info(
                f"Edited now-playing message {old_message.id} in channel {channel.id} "
                f"for {track.get('title', 'Unknown title')} ({track.get('id', '')})."
            )
            await update_bot_presence(track, reason="now-playing edit", channel=channel)
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
    client.current_track_message_show_url = True
    content = format_now_playing(track, show_queue=False, show_url=True)
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
    await update_bot_presence(track, reason="now-playing send", channel=channel)
    return new_message

def nowplaying_cooldown_key(ctx) -> tuple:
    guild_id = getattr(getattr(ctx, "guild", None), "id", 0) or 0
    channel_id = getattr(getattr(ctx, "channel", None), "id", 0) or 0
    return (guild_id, channel_id)

async def require_nowplaying_cooldown(ctx) -> bool:
    if is_user_admin(ctx.user):
        return True
    key = nowplaying_cooldown_key(ctx)
    now = time.time()
    last_used = client.nowplaying_last_used.get(key, 0)
    remaining = int(math.ceil(client.nowplaying_cooldown_seconds - (now - last_used)))
    if remaining > 0:
        await ctx.response.send_message(
            f"`/nowplaying` is on cooldown for `{remaining}s` in this channel.",
            ephemeral=True,
        )
        return False
    client.nowplaying_last_used[key] = now
    return True

async def send_nowplaying_controls(ctx):
    if not client.currently_playing or not client.current_track_info:
        await ctx.response.send_message("No song is currently playing.", ephemeral=True)
        return
    if not await require_voice_control(ctx, "show now-playing controls"):
        return
    if not await require_nowplaying_cooldown(ctx):
        return
    old_message = client.current_track_message
    content = format_now_playing(client.current_track_info, show_queue=False, show_url=False)
    await ctx.response.send_message(content)
    message = await ctx.original_response()
    client.current_track_message = message
    client.current_track_message_show_queue = False
    client.current_track_message_show_url = False
    await add_control_reactions(message)
    if old_message and old_message.id != message.id:
        await remove_control_reactions(old_message)
    logger.info(
        f"Sent user-requested nowplaying controls {message.id} in channel {getattr(ctx.channel, 'id', 0)} "
        f"for {client.current_track_info.get('title', 'Unknown title')}."
    )

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
                show_url=client.current_track_message_show_url,
            )
        )
        state = "shown" if client.current_track_message_show_queue else "hidden"
        logger.info(f"Queue section {state} on now-playing message {message.id}.")
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
        logger.warning(f"Failed to toggle queue section on now-playing message {message.id}: {exc}")

async def handle_favorite_reaction(user, message):
    _, notice = await add_current_track_to_favorites(user)
    if not client.current_track_info:
        try:
            await message.channel.send(notice)
        except (discord.Forbidden, discord.HTTPException):
            pass
        return
    client.current_track_favorite_notice = notice
    try:
        await message.edit(
            content=format_now_playing(
                client.current_track_info,
                show_queue=client.current_track_message_show_queue,
                show_url=client.current_track_message_show_url,
            )
        )
        logger.info(f"Updated now-playing favorite notice on message {message.id}: {notice}")
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
        logger.warning(f"Failed to edit now-playing favorite notice on message {message.id}: {exc}")

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
        "",
        "**playback**",
        "`/play` - play YouTube, search, saved playlists, or favorites.",
        "`/playtop` - put a request next.",
        "`/enqueue` / `/q` - add to the queue.",
        "`/queue` - show upcoming songs.",
        "",
        "**controls**",
        "`/nowplaying` - repost controls without the video URL.",
        "`/skip` `/pause` `/resume` `/stop` `/volume` - voice controls.",
        f"Reactions: {FAVORITE_REACTION} favorite, {QUEUE_REACTION} queue, {REPEAT_REACTION} repeat.",
        "",
        "**more**",
        "`/favorites` - play and manage starred songs.",
        "`/playlist` - create, play, and edit saved playlists.",
        "`/whatsnew` - recent bot updates.",
        "`/help topic:all` - literally every command.",
        f"React {HELP_EXPAND_REACTION} for common commands.",
    ])

def expanded_help_message() -> str:
    return expanded_help_pages()[0]

def expanded_help_pages() -> list:
    pages = [
        "\n".join([
            "**help - playback**",
            "",
            "`/join` - join your voice channel.",
            "`/play` - play now or queue YouTube, search, `playlist:name`, or favorites.",
            "`/playtop` - place a request next.",
            "`/enqueue` / `/q` - append to the queue.",
            "`/queue` / `/queuelist` - show upcoming songs.",
            "`/queuefirst` / `/qfirst` - move a queued item or playlist block next.",
            "",
            "**now playing**",
            "`/nowplaying` - repost controls without the URL.",
            "`/now` / `/nytsoi` - compact current-song view.",
            "`/getqueue` - session request history.",
            f"`/volume` - set volume up to {SAFE_VOLUME_MAX_LEVEL}% for normal users.",
            "`/skip` `/pause` `/resume` `/stop` - voice controls.",
            f"Reactions: {FAVORITE_REACTION} favorite, ◀️ previous, ⏸️ pause/resume, ▶️ skip, {REPEAT_REACTION} repeat, {QUEUE_REACTION} queue.",
        ]),
        "\n".join([
            "**help - playlists and favorites**",
            "",
            "`/playlist list` - browse saved playlists.",
            "`/playlist new` - guided creation.",
            "`/playlist new <name> current` - import the upcoming queue.",
            "`/playlist show` / `/playlist edit` - inspect playlist details.",
            "`/playlist play` - play or queue a saved playlist.",
            "`/playlist add` - add current, queued, or URL media.",
            "`/playlist fill current` - bulk-add queued songs not already present.",
            "`/playlist remove` / `/playlist delete` - delete with rescue window.",
            "`/playlist rescue` - restore a recently deleted playlist.",
            "`/playlist removesong` / `/playlist move` / `/playlist rename` / `/playlist lock` - edit tools.",
            "`/playlist cachemode` / `/playlist cacheglobal` - admin cache policy.",
            "`/favorites play` / `/favorites list` - use starred songs.",
            "`/favorites privacy` / `/favorites status` - manage favorites visibility.",
        ]),
        "\n".join([
            "**help - admin and utilities**",
            "",
            "`/config show` - reaction-toggle runtime settings.",
            "`/status` / `/status play` - runtime and playback diagnostics.",
            "`/userstats` - admin diagnostics for one user.",
            "`/usergroup` / `/permissions` - restriction groups.",
            "`/cachequeue` / `/cachestatus` / `/purgecache` / `/purgequeue` - cache tools.",
            "`/clear_queue` / `/restorequeue` - queue cleanup and recovery.",
            "`/autoleave` / `/setdeletetime` - leave and cleanup timers.",
            "`/volume_session` / `/volume_default` / `/volume_force` - admin volume controls.",
            "`/togglelog` / `/toggledownload` / `/disablelinks` / `/reboot` - runtime controls.",
            "`/playspeed` / `/playspeedaccess` / `/nowplayingcooldown` - hidden/admin tuning.",
            "`/backup_teekkari_quotes` / `/random_quote` - quote tools.",
            "`/whatsnew` - recent bot changes.",
            "",
            "Use `/help topic:all` for every slash command.",
            "Use `/help command:play` or `/help command:playlist new` for details.",
        ]),
    ]
    return [trim_discord_message(page) for page in pages]

def command_description(command) -> str:
    return str(getattr(command, "description", "") or "no description").strip()

def all_command_entries() -> list:
    entries = []
    for command in client.tree.get_commands():
        children = list(getattr(command, "commands", []) or [])
        entries.append(f"`/{command.name}` - {command_description(command)}")
        for child in children:
            entries.append(f"`/{command.name} {child.name}` - {command_description(child)}")
    return entries

def paginate_help_entries(title: str, intro: str, entries: list) -> list:
    pages = []
    header = [f"**{title}**", intro, ""]
    current = list(header)
    for entry in entries:
        candidate = "\n".join([*current, entry])
        if len(candidate) > DISCORD_MESSAGE_SAFE_LIMIT - 120 and len(current) > len(header):
            pages.append("\n".join(current))
            current = list(header)
        current.append(entry)
    if len(current) > len(header):
        pages.append("\n".join(current))
    return [trim_discord_message(page) for page in pages] or ["**all commands**\nNo commands are registered."]

def all_help_pages() -> list:
    return paginate_help_entries(
        "all commands",
        "Every registered slash command and subcommand. Use `/help command:<name>` for details.",
        all_command_entries(),
    )

def trim_discord_message(content: str) -> str:
    if len(content) <= DISCORD_MESSAGE_SAFE_LIMIT:
        return content
    suffix = "\n\n_This help page was shortened to fit Discord._"
    return content[:DISCORD_MESSAGE_SAFE_LIMIT - len(suffix)].rstrip() + suffix

def help_message_content(*, expanded: bool, page: int = 0) -> str:
    if not expanded:
        return compact_help_message()
    pages = client.help_pages or expanded_help_pages()
    page = max(0, min(page, len(pages) - 1))
    footer = f"\n\n_page {page + 1}/{len(pages)} - react {HELP_EXPAND_REACTION} to close, ◀️/▶️ to change page_"
    content = pages[page] + footer
    return trim_discord_message(content)

async def send_help_pages(ctx, pages: list):
    client.help_pages = pages
    client.help_expanded = True
    client.help_page = 0
    await ctx.response.send_message(help_message_content(expanded=True, page=0))
    message = await ctx.original_response()
    client.help_message_id = message.id
    for emoji in (HELP_EXPAND_REACTION, *HELP_PAGE_REACTIONS):
        try:
            await message.add_reaction(emoji)
        except Exception as exc:
            logger.warning(f"Failed to add help reaction {emoji}: {exc}")
    return message

async def handle_help_reaction(reaction, user) -> bool:
    if not client.help_message_id or reaction.message.id != client.help_message_id:
        return False
    emoji = str(reaction.emoji)
    if emoji not in {HELP_EXPAND_REACTION, *HELP_PAGE_REACTIONS}:
        return True
    pages = client.help_pages or expanded_help_pages()
    if emoji == HELP_EXPAND_REACTION:
        client.help_expanded = not client.help_expanded
        client.help_page = 0
        client.help_pages = expanded_help_pages() if client.help_expanded else None
    elif client.help_expanded and emoji == "◀️":
        client.help_page = max(0, getattr(client, "help_page", 0) - 1)
    elif client.help_expanded and emoji == "▶️":
        client.help_page = min(len(pages) - 1, getattr(client, "help_page", 0) + 1)
    else:
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except Exception as exc:
            logger.warning(f"Failed to remove inactive help reaction: {exc}")
        return True
    try:
        await reaction.message.edit(content=help_message_content(
            expanded=client.help_expanded,
            page=getattr(client, "help_page", 0),
        ))
        if client.help_expanded:
            for page_emoji in HELP_PAGE_REACTIONS:
                await reaction.message.add_reaction(page_emoji)
        await reaction.message.remove_reaction(reaction.emoji, user)
        state = "expanded" if client.help_expanded else "compacted"
        logger.info(f"{state.title()} help message {reaction.message.id} page={getattr(client, 'help_page', 0)}.")
    except Exception as exc:
        logger.warning(f"Failed to update help message: {exc}")
    return True

def playlist_general_help_message() -> str:
    return "\n".join([
        "**playlist help**",
        "Playlists are saved lists of YouTube tracks you can play later.",
        "",
        "**quick start**",
        "/playlist new - guided creation",
        "/playlist new Roadtrip current - save the upcoming queue, then optionally add more URLs",
        "/playlist list - browse playlists",
        "/playlist show Roadtrip - view songs",
        "/playlist play Roadtrip - play or queue it",
        "/playlist add Roadtrip url https://youtube.com/watch?v=... - add a link",
        "/playlist add Roadtrip url https://youtube.com/playlist?list=... - import a YouTube playlist link",
        "/playlist fill current Roadtrip - add queued songs not already in it",
        "",
        "Detailed help: `/help topic:playlist command:new`, `/help topic:playlist command:add`, `/help topic:playlist command:fill`.",
        "Playlist cache policy is admin-controlled with `/playlist cacheglobal` and `/playlist cachemode`.",
    ])

def playlist_help_pages() -> dict:
    return {
        "new": {
            "purpose": "create a new playlist",
            "synopsis": ["/playlist new", "/playlist new <name> private", "/playlist new <name> public", "/playlist new <name> current", "/playlist new <name> currentqueue", "/playlist new <name> jono"],
            "description": "Starts a guided playlist creation flow, creates an empty playlist, or imports the current upcoming queue.",
            "arguments": ["<name> - playlist name.", "private/public - playlist visibility.", "current/currentqueue - import the upcoming queue.", "jono - Finnish alias for currentqueue."],
            "examples": ["/playlist new", "/playlist new Roadtrip current", "/playlist new Suomi jono"],
            "notes": ["Guided creation accepts YouTube video or playlist URLs, `done` to finish, and `cancel` to stop.", "Queue import creates the playlist immediately, then accepts more YouTube URLs until `done`.", "The compact help does not advertise `jono`, but this page documents it."],
            "errors": ["Queue is empty - add songs to the queue first.", "Duplicate name - choose another name or remove the old playlist."],
        },
        "list": {
            "purpose": "browse playlists you can see",
            "synopsis": ["/playlist list"],
            "description": "Shows your playlists first, then visible public playlists, with reaction pages.",
            "arguments": ["none"],
            "examples": ["/playlist list"],
            "notes": ["React ◀️ or ▶️ to move pages."],
            "errors": ["No playlists - create one with `/playlist new`."],
        },
        "show": {
            "purpose": "show playlist details",
            "synopsis": ["/playlist show <playlist>"],
            "description": "Shows owner, managers, visibility, lock state, and songs.",
            "arguments": ["<playlist> - name, id, or playlist:name."],
            "examples": ["/playlist show Roadtrip"],
            "notes": ["Use `/playlist edit` when you specifically need edit/admin confirmation behavior."],
            "errors": ["Playlist not found - run `/playlist list`."],
        },
        "play": {
            "purpose": "play or queue a playlist",
            "synopsis": ["/playlist play <playlist>"],
            "description": "Starts the playlist if nothing is playing, otherwise queues it.",
            "arguments": ["<playlist> - name, id, or playlist:name."],
            "examples": ["/playlist play Roadtrip"],
            "notes": ["You can also use `/play playlist:name`."],
            "errors": ["Empty playlist - add songs first.", "Need voice channel - join a voice channel first."],
        },
        "edit": {
            "purpose": "show editable playlist details",
            "synopsis": ["/playlist edit <playlist> [flags]"],
            "description": "Shows playlist details for users who can edit the playlist.",
            "arguments": ["<playlist> - name, id, or playlist:name.", "-force - admin bypass for foreign playlist confirmation."],
            "examples": ["/playlist edit Roadtrip", "/playlist edit Roadtrip -force"],
            "notes": ["Admins editing someone else's playlist are asked to confirm unless `-force` is used."],
            "errors": ["No edit permission - ask the owner to add you as manager."],
        },
        "add": {
            "purpose": "add a song to a playlist",
            "synopsis": ["/playlist add <playlist> current", "/playlist add <playlist> queue <position>", "/playlist add <playlist> url <youtube-url>"],
            "description": "Adds the current song, a queued song, a YouTube video URL, or a YouTube playlist URL to a playlist you can edit.",
            "arguments": ["<playlist> - playlist to edit.", "current - currently playing song.", "queue - song from upcoming queue.", "url - YouTube video or playlist URL.", "<position> - queue position when source is queue."],
            "examples": ["/playlist add Roadtrip current", "/playlist add Roadtrip queue 2", "/playlist add Roadtrip url https://youtube.com/watch?v=...", "/playlist add Roadtrip url https://youtube.com/playlist?list=..."],
            "notes": ["Raw non-YouTube URLs are rejected.", f"YouTube playlist imports are capped at {MAX_PLAYLIST_TRACKS} track(s)."],
            "errors": ["No current song - start playback first.", "Bad queue position - run `/queue`.", "Invalid URL - send a YouTube link."],
        },
        "addmod": {
            "purpose": "add a playlist manager",
            "synopsis": ["/playlist addmod <playlist> <user>"],
            "description": "Lets a playlist owner or admin add another user as manager.",
            "arguments": ["<playlist> - playlist to manage.", "<user> - Discord member."],
            "examples": ["/playlist addmod Roadtrip @friend"],
            "notes": ["Managers can edit unless the playlist is locked."],
            "errors": ["Only owner/admin can add managers."],
        },
        "fill": {
            "purpose": "fill a playlist from the current queue",
            "synopsis": ["/playlist fill current <playlist>"],
            "description": "Adds songs from the upcoming queue that are not already in the target playlist.",
            "arguments": ["current - use the current upcoming queue.", "<playlist> - playlist to edit."],
            "examples": ["/playlist fill current Roadtrip"],
            "notes": ["The currently playing song is not included; this uses the upcoming queue.", "Duplicates are skipped by YouTube video id or URL."],
            "errors": ["Queue is empty - add songs to the queue first.", "No edit permission - ask the owner to add you as manager."],
        },
        "remove": {
            "purpose": "remove a playlist with rescue window",
            "synopsis": ["/playlist remove <playlist> [flags]"],
            "description": "Soft-deletes a playlist for 600 seconds before permanent deletion.",
            "arguments": ["<playlist> - playlist to remove.", "-now - admin-only immediate delete.", "-force - admin confirmation bypass with -now."],
            "examples": ["/playlist remove Roadtrip", "/playlist remove Roadtrip -now -force"],
            "notes": ["Use `/playlist rescue` soon after deleting if you made a mistake."],
            "errors": ["Only owner/admin can remove playlists."],
        },
        "delete": {
            "purpose": "alias for playlist remove",
            "synopsis": ["/playlist delete <playlist> [flags]"],
            "description": "Same behavior as `/playlist remove`.",
            "arguments": ["same as remove"],
            "examples": ["/playlist delete Roadtrip"],
            "notes": ["Kept as a friendlier alias."],
            "errors": ["See `/help topic:playlist command:remove`."],
        },
        "rename": {
            "purpose": "rename a playlist",
            "synopsis": ["/playlist rename <playlist> <new_name> [flags]"],
            "description": "Renames a playlist without changing its id or folder.",
            "arguments": ["<playlist> - current playlist.", "<new_name> - new name.", "-force - admin foreign playlist confirmation bypass."],
            "examples": ["/playlist rename Roadtrip Summer Drive"],
            "notes": ["Names must be unique and short."],
            "errors": ["Duplicate name - choose another name."],
        },
        "removesong": {
            "purpose": "remove one song from a playlist",
            "synopsis": ["/playlist removesong <playlist> <position> [flags]"],
            "description": "Removes a song by playlist position.",
            "arguments": ["<position> - 1-based playlist song number."],
            "examples": ["/playlist removesong Roadtrip 3"],
            "notes": ["Use `/playlist show` to see positions."],
            "errors": ["Position missing - run `/playlist show` first."],
        },
        "move": {
            "purpose": "reorder songs in a playlist",
            "synopsis": ["/playlist move <playlist> <from_position> <to_position> [flags]"],
            "description": "Moves a song to another position inside the playlist.",
            "arguments": ["<from_position> and <to_position> are 1-based."],
            "examples": ["/playlist move Roadtrip 5 1"],
            "notes": ["Use `/playlist show` to see positions."],
            "errors": ["Positions must exist in the playlist."],
        },
        "lock": {
            "purpose": "lock or unlock manager edits",
            "synopsis": ["/playlist lock <playlist> <locked>"],
            "description": "Blocks or allows manager edits. Owners and admins can still manage the playlist.",
            "arguments": ["<locked> - true or false."],
            "examples": ["/playlist lock Roadtrip true"],
            "notes": ["Useful before sharing a public playlist."],
            "errors": ["Only owner/admin can lock playlists."],
        },
        "cachemode": {
            "purpose": "set one playlist's cache behavior",
            "synopsis": ["/playlist cachemode <playlist> <follow_global|streaming|bounded|keep_cached>"],
            "description": "Sets the cache mode stored in that playlist's metadata.",
            "arguments": ["<playlist> - playlist to configure.", "<mode> - follow_global, streaming, bounded, or keep_cached."],
            "examples": ["/playlist cachemode Roadtrip bounded", "/playlist cachemode Roadtrip keep_cached"],
            "notes": ["Admin only.", "Bounded caches up to 15 tracks or 3 GB per playlist play operation.", "Cache files live in cache/, not the playlist folder."],
            "errors": ["Playlist not found.", "Admin permission required."],
        },
        "cacheglobal": {
            "purpose": "set the global playlist cache behavior",
            "synopsis": ["/playlist cacheglobal <streaming|bounded|keep_cached> [force]"],
            "description": "Sets the persistent default for playlists whose mode is follow_global.",
            "arguments": ["<mode> - streaming, bounded, or keep_cached.", "<force> - true makes all playlists ignore their own mode."],
            "examples": ["/playlist cacheglobal bounded false", "/playlist cacheglobal streaming true"],
            "notes": ["Admin only.", "The default at startup is bounded.", "The cache hard cap is 20 GB."],
            "errors": ["Admin permission required."],
        },
        "rescue": {
            "purpose": "restore a recently removed playlist",
            "synopsis": ["/playlist rescue", "/playlist rescue <playlist>"],
            "description": "Lists or restores playlists still inside the 600 second delete grace window.",
            "arguments": ["<playlist> - deleted playlist name or id."],
            "examples": ["/playlist rescue", "/playlist rescue Roadtrip"],
            "notes": ["Hidden from compact help but documented here."],
            "errors": ["Deleted playlist not found - the grace window may have expired."],
        },
        "predownload": {
            "purpose": "permanently predownload playlist files",
            "synopsis": ["/playlist predownload <playlist>"],
            "description": "Admin-only permanent playlist download hook, disabled unless configured.",
            "arguments": ["<playlist> - playlist to predownload."],
            "examples": ["/playlist predownload Roadtrip"],
            "notes": ["Requires `PLAYLIST_PREDOWNLOAD_ENABLED=true`."],
            "errors": ["Disabled on this bot - enable the feature flag first."],
        },
    }

def format_playlist_manpage(command: str) -> Optional[str]:
    page = playlist_help_pages().get(str(command or "").lower())
    if not page:
        return None
    lines = [
        f"**NAME**\n  playlist {command} - {page['purpose']}",
        "**SYNOPSIS**",
        *[f"  {item}" for item in page["synopsis"]],
        "**DESCRIPTION**",
        f"  {page['description']}",
        "**ARGUMENTS**",
        *[f"  {item}" for item in page["arguments"]],
        "**EXAMPLES**",
        *[f"  {item}" for item in page["examples"]],
        "**NOTES**",
        *[f"  {item}" for item in page["notes"]],
        "**COMMON ERRORS**",
        *[f"  {item}" for item in page["errors"]],
    ]
    return "\n".join(lines)

def command_help_pages() -> dict:
    return {
        "join": {
            "purpose": "connect the bot to your voice channel",
            "synopsis": ["/join"],
            "description": "Joins the voice channel you are currently in and resets the session song history for the new listening session.",
            "arguments": ["none"],
            "examples": ["/join"],
            "notes": ["You must already be in a voice channel.", "Playback commands can also connect the bot automatically."],
            "errors": ["Not in voice - join a voice channel first.", "Discord voice connection failed - check output.log."],
        },
        "play": {
            "purpose": "play or queue YouTube audio",
            "synopsis": ["/play <youtube url or search> [repeat] [speed] [show_download_log]", "/play <search> -repeat <count>", "/play <search> --speed:<number>", "/play <youtube playlist url>", "/play playlist:<name>", "/play -favorites <username>", "/play last"],
            "description": "Resolves YouTube URLs, YouTube playlist URLs, favorites, or search text with yt-dlp. If nothing is playing, a single track or the selected playlist/favorites entry starts immediately; otherwise the result is queued. Playlist names can start or queue saved playlists.",
            "arguments": ["<query> - YouTube video URL, YouTube playlist URL, YouTube search text, playlist:name, -favorites username, or last/play:last.", f"repeat - optional repeat count for single-track requests; values above {MAX_PLAY_REPEAT_COUNT} turn into repeat-one loop.", f"speed - optional playback speed from {MIN_PLAYBACK_SPEED:g} to {MAX_PLAYBACK_SPEED:g}; requires admin, playspeed group, or allow-all.", "show_download_log - true shows an editable sanitized download progress log for this request."],
            "examples": ["/play viidestoista yö", "/play viidestoista yö -repeat 3", "/play viidestoista yö --speed:1.25", "/play https://youtube.com/watch?v=... repeat:4 speed:1.1 show_download_log:true", "/play https://youtube.com/playlist?list=...", "/play playlist:Roadtrip", "/play -favorites jantso", "/play last"],
            "notes": ["Raw non-YouTube URLs are rejected.", f"YouTube playlist URLs are capped at {MAX_PLAYLIST_TRACKS} track(s) and respect the queue length limit for non-admins.", "A watch URL with both `v=` and `list=` starts from that video when possible, then queues the rest of the playlist block.", "Repeat and speed are only for single-track YouTube/search requests; playlists, favorites, and last-session restore are rejected when either is requested.", "Favorites are private by default; public favorites can be played by others, and admins get a confirmation warning before overriding private favorites.", "Users in `nodownload` always stream and do not create normal downloads.", "Users in `norepeat` cannot use repeat requests.", "The `playspeed` group grants speed controls when allow-all is off.", "Download mode caches individual tracks when they reach playback; stream-only mode skips local caching.", "`show_download_log:true` shows the editable progress log once; `/togglelog download` enables it globally while keeping normal INFO logging."],
            "errors": ["Need voice channel - join voice first.", "Extraction failed - check yt-dlp, deno/node, and output.log.", "Large download - admin confirmation may be required."],
        },
        "playtop": {
            "purpose": "play a song next",
            "synopsis": ["/playtop <query>"],
            "description": "Adds a resolved YouTube track or YouTube playlist block to the front of the queue. If nothing is currently playing, it starts immediately.",
            "arguments": ["<query> - YouTube URL, YouTube playlist URL, or search text."],
            "examples": ["/playtop panzermensch", "/playtop https://youtube.com/playlist?list=..."],
            "notes": ["This does not interrupt the current track when something is already playing.", "Users in `noqueueskip` cannot use this to jump songs ahead while playback is active."],
            "errors": ["Queue limit reached for non-admins.", "Extraction failed - check output.log.", "Restricted by noqueueskip."],
        },
        "enqueue": {
            "purpose": "add a song or playlist to the end of the queue",
            "synopsis": ["/enqueue <query>", "/enqueue playlist:<name>"],
            "description": "Resolves a YouTube query, YouTube playlist URL, or visible playlist and appends it to the upcoming queue.",
            "arguments": ["<query> - YouTube URL, YouTube playlist URL, search text, playlist:name, or exact playlist name."],
            "examples": ["/enqueue and one panzermensch", "/enqueue https://youtube.com/playlist?list=...", "/enqueue playlist:Roadtrip"],
            "notes": ["Alias: /q.", "If a playlist is actively playing, normal song requests are placed after that playlist block."],
            "errors": ["Queue limit reached.", "Large download requires /play confirmation."],
        },
        "q": {
            "purpose": "alias for enqueue",
            "synopsis": ["/q <query>"],
            "description": "Short alias for `/enqueue` with the same behavior.",
            "arguments": ["<query> - YouTube URL, YouTube playlist URL, search text, playlist:name, or exact playlist name."],
            "examples": ["/q viidestoista yö"],
            "notes": ["Use `/help command:enqueue` for the full behavior."],
            "errors": ["Same as `/enqueue`."],
        },
        "queue": {
            "purpose": "show the upcoming queue",
            "synopsis": ["/queue", "/queue links:true"],
            "description": "Displays upcoming tracks with 1-based positions. Those positions are used by commands like `/queuefirst` and `/playlist add ... queue`.",
            "arguments": ["links - true shows YouTube links unless an admin disabled queue links."],
            "examples": ["/queue", "/queue links:true"],
            "notes": ["Alias: /queuelist.", "The currently playing song is not part of the upcoming queue."],
            "errors": ["Queue is empty - add songs with /play, /enqueue, or /q."],
        },
        "queuelist": {
            "purpose": "alias for queue",
            "synopsis": ["/queuelist", "/queuelist links:true"],
            "description": "Alias for `/queue`.",
            "arguments": ["links - true shows YouTube links unless links are disabled."],
            "examples": ["/queuelist links:true"],
            "notes": ["Use `/help command:queue` for the full behavior."],
            "errors": ["Same as `/queue`."],
        },
        "queuefirst": {
            "purpose": "move a queued song or playlist to play next",
            "synopsis": ["/queuefirst <position>", "/queuefirst playlist:<name>", "/queuefirst <youtube playlist url>"],
            "description": "Moves an upcoming queue item to position 1, or moves/adds a saved or YouTube playlist block to the front of the queue.",
            "arguments": ["<position> - 1-based queue position.", "<playlist> - visible playlist name, id, playlist:name, or YouTube playlist URL."],
            "examples": ["/queuefirst 3", "/queuefirst playlist:Roadtrip", "/queuefirst https://youtube.com/playlist?list=..."],
            "notes": ["Does not interrupt the currently playing track.", "Users in `noqueueskip` cannot reorder the queue."],
            "errors": ["Queue is empty.", "Position is outside the queue.", "Playlist is empty or not visible.", "Restricted by noqueueskip."],
        },
        "qfirst": {
            "purpose": "alias for queuefirst",
            "synopsis": ["/qfirst <position or playlist>"],
            "description": "Short alias for `/queuefirst`.",
            "arguments": ["<target> - queue position, visible playlist, or YouTube playlist URL."],
            "examples": ["/qfirst 2"],
            "notes": ["Use `/help command:queuefirst` for the full behavior."],
            "errors": ["Same as `/queuefirst`."],
        },
        "skip": {
            "purpose": "skip the current track",
            "synopsis": ["/skip"],
            "description": "Requests that the current track stop so the next queued track can start. Non-admins start or join a reaction vote; admins bypass the vote.",
            "arguments": ["none"],
            "examples": ["/skip"],
            "notes": ["Quorum is 50% of current human voice-channel members, rounded up.", "The now-playing ▶️ reaction uses the same vote logic.", "Users in `noskip` cannot start skip votes or vote to skip."],
            "errors": ["No track is playing.", "You must be in the bot's voice channel.", "Restricted by noskip."],
        },
        "pause": {
            "purpose": "pause playback",
            "synopsis": ["/pause"],
            "description": "Pauses the current audio without clearing the queue or disconnecting.",
            "arguments": ["none"],
            "examples": ["/pause"],
            "notes": ["The now-playing ⏸️ reaction can also pause or resume."],
            "errors": ["No audio is playing.", "Already paused.", "You must be in the bot's voice channel."],
        },
        "resume": {
            "purpose": "resume paused playback",
            "synopsis": ["/resume"],
            "description": "Resumes audio that was paused with /pause or the now-playing pause reaction.",
            "arguments": ["none"],
            "examples": ["/resume"],
            "notes": ["Does nothing if audio is already playing."],
            "errors": ["No audio is paused.", "You must be in the bot's voice channel."],
        },
        "stop": {
            "purpose": "stop playback and leave voice",
            "synopsis": ["/stop"],
            "description": "Stops playback, clears the upcoming queue, disconnects from voice, and resets session-only volume. Non-admins vote; admins bypass.",
            "arguments": ["none"],
            "examples": ["/stop"],
            "notes": ["Use `/autoleave` if you want automatic leave when nobody is listening."],
            "errors": ["Bot is not in voice.", "You must be in the bot's voice channel."],
        },
        "volume": {
            "purpose": "vote to change playback volume",
            "synopsis": [f"/volume <1-{SAFE_VOLUME_MAX_LEVEL}>"],
            "description": "Sets the current playback volume after a non-admin vote. Admins bypass the vote, but the normal command still keeps the ear-safety ceiling.",
            "arguments": [f"<level> - volume percentage from 1 to {SAFE_VOLUME_MAX_LEVEL}."],
            "examples": ["/volume 20", "/volume 35"],
            "notes": ["The startup default is 20%.", f"Normal volume commands are capped at {SAFE_VOLUME_MAX_LEVEL}% for ear safety.", "Admins can use `/volume_force` when a louder override is intentionally needed.", "Users in `novolumechange` cannot use this command."],
            "errors": [f"Level outside 1-{SAFE_VOLUME_MAX_LEVEL}.", "Bot is not in voice.", "You must be in the bot's voice channel.", "Restricted by novolumechange."],
        },
        "now": {
            "purpose": "show the current song",
            "synopsis": ["/now"],
            "description": "Shows the currently playing track title and YouTube video id.",
            "arguments": ["none"],
            "examples": ["/now"],
            "notes": ["Alias: /nytsoi.", "This intentionally stays compact and does not show the full URL."],
            "errors": ["No song is currently playing."],
        },
        "nytsoi": {
            "purpose": "Finnish alias for now",
            "synopsis": ["/nytsoi"],
            "description": "Shows the currently playing track title and YouTube video id, same as `/now`.",
            "arguments": ["none"],
            "examples": ["/nytsoi"],
            "notes": ["Use `/help command:now` for the non-alias page."],
            "errors": ["No song is currently playing."],
        },
        "nowplaying": {
            "purpose": "repost now-playing controls without the video URL",
            "synopsis": ["/nowplaying"],
            "description": "Posts a fresh now-playing control message for the current track without showing the YouTube URL. The new message receives the normal playback reactions and old controls are removed.",
            "arguments": ["none"],
            "examples": ["/nowplaying"],
            "notes": ["Requires the same voice channel unless the user is an admin.", "Non-admins share a per-channel cooldown configured by admins."],
            "errors": ["No song is currently playing.", "Cooldown active.", "You must be in the bot's voice channel."],
        },
        "getqueue": {
            "purpose": "show session song history",
            "synopsis": ["/getqueue"],
            "description": "Lists songs requested since the bot joined voice and marks each as playing, queued, played, or removed.",
            "arguments": ["none"],
            "examples": ["/getqueue"],
            "notes": ["This is session memory, not persistent storage."],
            "errors": ["No songs have been requested this session."],
        },
        "whatsnew": {
            "purpose": "show recent bot updates",
            "synopsis": ["/whatsnew"],
            "description": "Shows the latest user-facing update summary from RECENT_UPDATES.md.",
            "arguments": ["none"],
            "examples": ["/whatsnew"],
            "notes": ["The update file is generated from recent local git history and maintainer notes.", "If the file grows too long for one Discord message, the command shows the first part with a truncation note."],
            "errors": ["RECENT_UPDATES.md is missing or unreadable."],
        },
        "favorites": {
            "purpose": "play and manage per-user favorites",
            "synopsis": ["/favorites play [user]", "/favorites list [user]", "/favorites privacy <public|private>", "/favorites status", "/favorites cacheuser <user> <enabled>", "/favorites cacheglobal <enabled> [max_gb] [per_user_tracks]"],
            "description": "Favorites are special per-user saved playlists. The now-playing star reaction toggles the current song in the reacting user's favorites.",
            "arguments": ["user - optional Discord user for public favorites.", "privacy - public lets others play your favorites, private blocks normal users.", "cacheuser/cacheglobal - admin cache controls."],
            "examples": ["/favorites play", "/favorites play @friend", "/favorites privacy public", "/favorites cacheglobal true 6 30"],
            "notes": ["Favorites are private by default.", "Favorites privacy is a social bot setting, not strong secrecy: admins can override with confirmation and anyone with filesystem access can read metadata.", "Favorites media cache uses cache/ only and is capped globally at 6 GiB.", "Each user can store up to 100 favorites; the default cache pass considers 30 per user."],
            "errors": ["Favorites are private.", "No favorites are saved.", "Admin permission required for cache commands."],
        },
        "permissions": {
            "purpose": "show your restriction groups",
            "synopsis": ["/permissions"],
            "description": "Shows `normal user` when no restriction groups are assigned, otherwise lists assigned groups.",
            "arguments": ["none"],
            "examples": ["/permissions"],
            "notes": ["Groups are stored in user-permissions.json runtime config.", "Known groups: nodownload, novolumechange, noplaylistcreate, noqueueskip, noskip, norepeat, playspeed."],
            "errors": ["none"],
        },
        "usergroup": {
            "purpose": "admin manage user restriction groups",
            "synopsis": ["/usergroup add <user> <group>", "/usergroup remove <user> <group>", "/usergroup list <user>"],
            "description": "Adds, removes, or lists user restriction groups used by playback, queue, playlist, repeat, and download paths.",
            "arguments": ["user - Discord member.", "group - nodownload, novolumechange, noplaylistcreate, noqueueskip, noskip, norepeat, or playspeed."],
            "examples": ["/usergroup add @user nodownload", "/usergroup remove @user noskip", "/usergroup list @user"],
            "notes": ["Admin only.", "`nodownload` forces that user's requests to stream and prevents favorite cache entries for that user.", "The config is runtime state and should not be committed."],
            "errors": ["Admin permission required.", "Unknown group."],
        },
        "config": {
            "purpose": "admin reaction-toggle runtime settings",
            "synopsis": ["/config show"],
            "description": "Posts a runtime configuration panel. Each setting has an emoji reaction; admin reactions flip or cycle the setting and edit the same message.",
            "arguments": ["none"],
            "examples": ["/config show"],
            "notes": ["Admin only.", "The panel covers download mode, Discord download logs, Python DEBUG logging, admin operation trail, queue links, auto-leave, favorites autocache, playlist cache policy, playspeed allow-all, and nowplaying cooldown.", "Most toggles are runtime state unless that setting already writes to a policy file."],
            "errors": ["Admin permission required.", "Discord may block reaction cleanup if the bot lacks reaction permissions."],
        },
        "userstats": {
            "purpose": "admin inspect one user's bot state",
            "synopsis": ["/userstats <user>"],
            "description": "Shows one user's restriction groups, favorites count/visibility/cache eligibility, owned and managed playlists, queued/session request counts, recent commands, and recent music requests.",
            "arguments": ["user - Discord member to inspect."],
            "examples": ["/userstats @user"],
            "notes": ["Admin only.", "Recent command memory is intentionally small and resets on bot restart."],
            "errors": ["Admin permission required."],
        },
        "playspeed": {
            "purpose": "set playback speed for future audio sources",
            "synopsis": ["/playspeed <speed>"],
            "description": "Sets the session playback speed used when the bot builds the next FFmpeg audio source.",
            "arguments": [f"speed - number from {MIN_PLAYBACK_SPEED:g} to {MAX_PLAYBACK_SPEED:g}; 1 is normal time."],
            "examples": ["/playspeed 1.25", "/playspeed 0.75"],
            "notes": ["Hidden operational command.", "Usable by admins, users in the `playspeed` group, or everyone when admins enable playspeed allow-all.", "Already-running audio keeps its current FFmpeg source until the next track or replay.", "If the bot is alone for the configured alone delay, playback speed resets back to normal `1x`."],
            "errors": ["Permission denied.", "Speed outside allowed range."],
        },
        "playspeedaccess": {
            "purpose": "admin allow or restrict playspeed for everyone",
            "synopsis": ["/playspeedaccess <enabled>"],
            "description": "Toggles whether all users may use `/playspeed` and `/play speed` without the `playspeed` group.",
            "arguments": ["enabled - true or false."],
            "examples": ["/playspeedaccess true", "/playspeedaccess false"],
            "notes": ["Admin only.", "The setting is stored in ignored runtime user-permissions config."],
            "errors": ["Admin permission required."],
        },
        "nowplayingcooldown": {
            "purpose": "admin configure nowplaying spam guard",
            "synopsis": ["/nowplayingcooldown <seconds>"],
            "description": "Sets the per-channel non-admin cooldown for `/nowplaying`.",
            "arguments": [f"seconds - value from {NOWPLAYING_COOLDOWN_MIN_SECONDS} to {NOWPLAYING_COOLDOWN_MAX_SECONDS}."],
            "examples": ["/nowplayingcooldown 30"],
            "notes": ["Admin only.", "Admins bypass the cooldown."],
            "errors": ["Admin permission required.", "Seconds outside allowed range."],
        },
        "clear_queue": {
            "purpose": "clear the upcoming queue",
            "synopsis": ["/clear_queue"],
            "description": "Clears the current upcoming queue and keeps a short in-memory backup for `/restorequeue`. Admins are asked whether to delete downloaded files too.",
            "arguments": ["none"],
            "examples": ["/clear_queue"],
            "notes": ["Does not stop the currently playing song.", "Non-admins cannot delete files from disk."],
            "errors": ["Queue is already empty.", "You must be in the bot's voice channel."],
        },
        "restorequeue": {
            "purpose": "restore a recently cleared or reboot-saved queue",
            "synopsis": ["/restorequeue"],
            "description": "Restores a queue from the short in-memory clear backup or from a reboot backup file if it is still fresh.",
            "arguments": ["none"],
            "examples": ["/restorequeue"],
            "notes": ["Admin only.", "The restore window is 10 minutes.", "The current queue must be empty."],
            "errors": ["No backup available.", "Backup is too old.", "Queue is not empty."],
        },
        "cachestatus": {
            "purpose": "inspect media cache usage",
            "synopsis": ["/cachestatus"],
            "description": "Shows cache directory, safe media file count, size against hard cap, and playlist cache policy.",
            "arguments": ["none"],
            "examples": ["/cachestatus"],
            "notes": ["Admin only.", "Only validated media files are counted."],
            "errors": ["Admin permission required."],
        },
        "cachequeue": {
            "purpose": "download the current session queue into cache",
            "synopsis": ["/cachequeue [include_current]"],
            "description": "Admin-only command that walks the current song plus upcoming queue and downloads safe eligible tracks into root cache/ using the normal cache key/path helpers.",
            "arguments": ["include_current - true also considers the currently playing track."],
            "examples": ["/cachequeue", "/cachequeue false"],
            "notes": ["Admin only.", "Tracks requested by users in `nodownload` are skipped.", "The command writes queue-blackbox audit events and respects the hard cache cap."],
            "errors": ["Admin permission required.", "Cache hard limit reached.", "Some downloads failed - check output.log."],
        },
        "purgecache": {
            "purpose": "delete validated cache files",
            "synopsis": ["/purgecache"],
            "description": "Deletes safe media files from cache while keeping the current playing file. Reports scanned, removed, skipped, failed, bytes freed, and stale metadata cleanup counts.",
            "arguments": ["none"],
            "examples": ["/purgecache"],
            "notes": ["Admin only.", "Unsafe paths and non-media files are skipped.", "Detailed audit lines are written to output.log."],
            "errors": ["Admin permission required.", "Some files may fail to delete due to OS permissions."],
        },
        "purgequeue": {
            "purpose": "delete tracked downloaded files without changing the queue",
            "synopsis": ["/purgequeue"],
            "description": "Removes tracked downloaded files from disk but leaves queued song entries intact. The current playing file is skipped.",
            "arguments": ["none"],
            "examples": ["/purgequeue"],
            "notes": ["Admin only.", "Deletion uses the safe media-file validation helper."],
            "errors": ["Admin permission required."],
        },
        "setdeletetime": {
            "purpose": "set delayed download cleanup time",
            "synopsis": ["/setdeletetime <seconds>"],
            "description": "Controls how long played downloaded songs wait before delayed cleanup removes their cache file.",
            "arguments": ["<seconds> - value between the configured minimum and maximum."],
            "examples": ["/setdeletetime 600", "/setdeletetime 0"],
            "notes": ["Admin only.", "Already scheduled deletion tasks keep their original timer."],
            "errors": ["Seconds outside allowed range.", "Admin permission required."],
        },
        "autoleave": {
            "purpose": "leave voice when nobody is listening",
            "synopsis": ["/autoleave <enabled> [delay_seconds]"],
            "description": "When enabled, the bot waits while alone in voice, saves the current song and queue, disconnects, and lets users restore with `/play last`.",
            "arguments": ["enabled - true or false.", "delay_seconds - optional delay before leaving."],
            "examples": ["/autoleave true 10", "/autoleave false"],
            "notes": ["Admin only.", "The bot cancels the pending leave when a human rejoins voice.", "The same alone delay resets playback speed back to `1x` even when auto-leave is disabled."],
            "errors": ["Delay outside allowed range.", "Admin permission required."],
        },
        "volume_session": {
            "purpose": "admin session volume hard-set",
            "synopsis": [f"/volume_session <1-{SAFE_VOLUME_MAX_LEVEL}>"],
            "description": "Sets the bot's current session volume immediately and keeps it until the bot disconnects, within the normal safety ceiling.",
            "arguments": [f"<level> - volume percentage from 1 to {SAFE_VOLUME_MAX_LEVEL}."],
            "examples": ["/volume_session 20"],
            "notes": ["Admin only.", "This overrides channel defaults for the current connection only.", "Use `/volume_force` for intentional louder overrides."],
            "errors": ["Bot is not connected to voice.", f"Level outside 1-{SAFE_VOLUME_MAX_LEVEL}.", "Admin permission required."],
        },
        "volume_default": {
            "purpose": "save a persistent channel volume default",
            "synopsis": [f"/volume_default <1-{SAFE_VOLUME_MAX_LEVEL}>"],
            "description": "Stores the default volume for the current voice channel in channel-volume-config.json, within the normal safety ceiling.",
            "arguments": [f"<level> - volume percentage from 1 to {SAFE_VOLUME_MAX_LEVEL}."],
            "examples": ["/volume_default 20"],
            "notes": ["Admin only.", "Applied when the bot joins that voice channel unless a session hard-set is active.", "Use `/volume_force save_default:true` for an intentional louder forced default."],
            "errors": ["No voice channel context.", f"Level outside 1-{SAFE_VOLUME_MAX_LEVEL}.", "Config write failed."],
        },
        "volume_force": {
            "purpose": "admin intentional loud-volume override",
            "synopsis": ["/volume_force <1-100> [save_default]"],
            "description": "Sets the bot's current session volume above the normal 50% safety ceiling when an admin intentionally needs that override.",
            "arguments": ["<level> - forced volume percentage from 1 to 100.", "save_default - optional true/false; true saves the level as a forced default for the current voice channel."],
            "examples": ["/volume_force 65", "/volume_force 65 true"],
            "notes": ["Admin only.", "This bypasses the normal ear-safety ceiling by design.", "Forced saved defaults are marked in channel-volume-config.json and are applied when the bot joins that voice channel."],
            "errors": ["Bot is not connected to voice.", "Level outside 1-100.", "Admin permission required.", "Config write failed."],
        },
        "togglelog": {
            "purpose": "toggle server debug logging",
            "synopsis": ["/togglelog", "/togglelog download", "/togglelog debug", "/togglelog admin", "/togglelog all", "/togglelog normal"],
            "description": "Controls Python log verbosity and the editable Discord `/play` download log independently.",
            "arguments": ["mode - toggle, download, debug, admin, all, normal, or off."],
            "examples": ["/togglelog download", "/togglelog debug", "/togglelog normal"],
            "notes": ["Admin only.", "`download` keeps normal INFO logging but enables the sanitized `/play` download progress message.", "`debug` enables DEBUG logging plus the download log.", "`admin` and `all` keep the larger user-space operation trail, including automatic alone speed-reset notices and bot status update errors.", "Download log messages can be collapsed with the cleanup reaction."],
            "errors": ["Admin permission required."],
        },
        "toggledownload": {
            "purpose": "switch download mode",
            "synopsis": ["/toggledownload"],
            "description": "Switches between download-and-play mode and stream-only mode.",
            "arguments": ["none"],
            "examples": ["/toggledownload"],
            "notes": ["Admin only.", "Download mode is more stable after extraction succeeds; stream-only uses less disk."],
            "errors": ["Admin permission required."],
        },
        "disablelinks": {
            "purpose": "toggle queue link display",
            "synopsis": ["/disablelinks"],
            "description": "Turns YouTube link display on or off in queue-style views, including `/queue links:true` and the now-playing queue section.",
            "arguments": ["none"],
            "examples": ["/disablelinks"],
            "notes": ["Admin only.", "The command toggles the current session setting."],
            "errors": ["Admin permission required."],
        },
        "reboot": {
            "purpose": "save queue and restart the bot process",
            "synopsis": ["/reboot"],
            "description": "Asks for reaction confirmation, writes current queue/current track to queue_backup.json, disconnects, and exits the process.",
            "arguments": ["none"],
            "examples": ["/reboot"],
            "notes": ["Admin only.", "Use `/restorequeue` after the process starts again."],
            "errors": ["Confirmation timed out.", "Backup write failed - check output.log."],
        },
        "backup_teekkari_quotes": {
            "purpose": "back up configured quote channel",
            "synopsis": ["/backup_teekkari_quotes"],
            "description": "Scans the configured quotes channel and rewrites quotes.txt through quotes.py.",
            "arguments": ["none"],
            "examples": ["/backup_teekkari_quotes"],
            "notes": ["Requires QUOTES_ID to point at an accessible channel.", "QUOTES_ID=0 disables quote backup."],
            "errors": ["Quotes channel disabled or inaccessible."],
        },
        "random_quote": {
            "purpose": "show a random saved quote",
            "synopsis": ["/random_quote"],
            "description": "Returns one random quote from quotes.txt using the quote persistence helper.",
            "arguments": ["none"],
            "examples": ["/random_quote"],
            "notes": ["Run `/backup_teekkari_quotes` first if the quote file is empty."],
            "errors": ["Quote storage empty or unavailable."],
        },
        "help": {
            "purpose": "show command help",
            "synopsis": ["/help", "/help topic:all", "/help command:<command>", "/help topic:playlist command:<subcommand>"],
            "description": "Shows compact help, paged all-command help, a command-specific manpage, or playlist topic help.",
            "arguments": ["topic - optional topic such as all or playlist.", "command - command, all, or playlist subcommand name."],
            "examples": ["/help", "/help topic:all", "/help command:nytsoi", "/help topic:playlist command:new"],
            "notes": ["Use command names without the leading slash.", "Playlist subcommands can be addressed as `playlist new` or with topic:playlist.", "The all-command view is paged with reaction controls."],
            "errors": ["Unknown command - check spelling or run `/help`."],
        },
        "status": {
            "purpose": "show runtime status and session audit",
            "synopsis": ["/status", "/status play", "/status session", "/status commands"],
            "description": "Shows runtime mode, queue/cache state, warning summary, detailed current playback diagnostics, session suggestions, or recent commands.",
            "arguments": ["view - latest, play, session, or commands."],
            "examples": ["/status", "/status play", "/status session"],
            "notes": ["Admin only except `/status play` when public access is enabled in `/config show`.", "Session audit lives in memory and resets when the bot restarts.", "Playback diagnostics show any known bitrate, BPM, codec, duration, cache, speed, bot status, and voice state fields; unavailable metadata is shown as unknown."],
            "errors": ["Admin permission required."],
        },
    }

def command_aliases() -> dict:
    return {
        "play:last": "play",
        "/play:last": "play",
        "playlist:list": "playlist list",
        "playlist:new": "playlist new",
        "playlist:edit": "playlist edit",
        "playlist:show": "playlist show",
        "playlist:play": "playlist play",
        "playlist:add": "playlist add",
        "playlist:fill": "playlist fill",
        "playlist:addmod": "playlist addmod",
        "playlist:remove": "playlist remove",
        "playlist:delete": "playlist delete",
        "playlist:rescue": "playlist rescue",
        "playlist:removesong": "playlist removesong",
        "playlist:move": "playlist move",
        "playlist:rename": "playlist rename",
        "playlist:lock": "playlist lock",
        "playlist:cachemode": "playlist cachemode",
        "playlist:cacheglobal": "playlist cacheglobal",
        "playlist:predownload": "playlist predownload",
        "favorites:play": "favorites",
        "favorites:list": "favorites",
        "favorites:privacy": "favorites",
        "favorites:status": "favorites",
        "favorites:cacheuser": "favorites",
        "favorites:cacheglobal": "favorites",
        "usergroup:add": "usergroup",
        "usergroup:remove": "usergroup",
        "usergroup:list": "usergroup",
        "config:show": "config",
        "config show": "config",
    }

def normalize_help_command(command: str) -> str:
    key = str(command or "").strip().lower()
    key = key.lstrip("/")
    key = re.sub(r"\s+", " ", key)
    key = command_aliases().get(key, key)
    if key.startswith("playlist ") and len(key.split(" ", 1)) == 2:
        return key
    return key.replace(" ", "_")

def format_command_manpage(command: str) -> Optional[str]:
    key = normalize_help_command(command)
    if key.startswith("playlist "):
        _, subcommand = key.split(" ", 1)
        return format_playlist_manpage(subcommand)
    page = command_help_pages().get(key)
    if not page:
        return None
    lines = [
        f"**NAME**\n  {key} - {page['purpose']}",
        "**SYNOPSIS**",
        *[f"  {item}" for item in page["synopsis"]],
        "**DESCRIPTION**",
        f"  {page['description']}",
        "**ARGUMENTS**",
        *[f"  {item}" for item in page["arguments"]],
        "**EXAMPLES**",
        *[f"  {item}" for item in page["examples"]],
        "**NOTES**",
        *[f"  {item}" for item in page["notes"]],
        "**COMMON ERRORS**",
        *[f"  {item}" for item in page["errors"]],
    ]
    return "\n".join(lines)

def help_message_for(topic: Optional[str] = None, command: Optional[str] = None) -> Optional[str]:
    topic_key = str(topic or "").strip().lower()
    command_key = str(command or "").strip().lower()
    if topic_key in {"all", "commands"} or command_key in {"all", "commands"}:
        return "__HELP_ALL__"
    if command_key and not topic_key:
        if normalize_help_command(command_key) in {"playlist", "playlists"}:
            return playlist_general_help_message()
        return format_command_manpage(command_key) or f"No help page for `{command}`. Try `/help` for the command list."
    if not topic_key:
        return None
    if topic_key in {"playlist", "playlists"}:
        if command_key:
            return format_playlist_manpage(command_key) or f"No playlist help page for `{command}`. Try `/help topic:playlists`."
        return playlist_general_help_message()
    return None

def recent_updates_message() -> str:
    try:
        with open(RECENT_UPDATES_FILE, "r") as f:
            content = f.read().strip()
    except Exception as exc:
        logger.warning(f"Could not read recent updates file: {exc}")
        return "**recent updates**\nRECENT_UPDATES.md is not available. Check the bot logs."

    if not content:
        return "**recent updates**\nNo recent updates have been written yet."
    if len(content) <= DISCORD_MESSAGE_SAFE_LIMIT:
        return content

    notice = "\n\n_Showing the first part. See RECENT_UPDATES.md for the full list._"
    allowed = DISCORD_MESSAGE_SAFE_LIMIT - len(notice)
    lines = []
    for line in content.splitlines():
        candidate = "\n".join(lines + [line]).rstrip()
        if len(candidate) > allowed:
            break
        lines.append(line)
    if not lines:
        return content[:allowed].rstrip() + notice
    return "\n".join(lines).rstrip() + notice

def enough_disk_for_download() -> bool:
    try:
        usage = shutil.disk_usage(BASE_DIR)
        return usage.free >= MIN_FREE_DOWNLOAD_MB * 1024 * 1024
    except Exception as exc:
        logger.warning(f"Disk usage check failed before download: {exc}")
        return True

def estimate_total_downloaded_bytes() -> int:
    total = 0
    for vid, info in downloaded.items():
        fp = info.get('filepath')
        if fp and is_safe_download_path(fp, vid):
            try:
                total += os.path.getsize(path_from_metadata(fp))
            except Exception:
                continue
    return total

async def download_youtube_to_cache(
    video_url: str,
    cache_key: str,
    *,
    playlist: bool = False,
    debug_report: Optional[DebugPlaybackMessage] = None,
) -> tuple:
    prefix = "plst-" if playlist else ""
    temp_token = secrets.token_hex(4)
    cache_bytes_before = cache_total_bytes()
    options = dict(ytdl_options)
    options["outtmpl"] = os.path.join(CACHE_DIR, f".download-{prefix}{cache_key}-{temp_token}.%(ext)s")
    loop = asyncio.get_event_loop()
    if debug_report:
        debug_report.stage = "downloading"
        debug_report.cache_state = "miss"
        await append_debug_playback_event(debug_report, "download started", force=True)
        await edit_debug_playback_message(debug_report, force=True)

        def debug_progress_hook(status):
            if not isinstance(status, dict):
                return
            debug_report.stage = str(status.get("status") or "downloading")
            debug_report.downloaded_bytes = int(status.get("downloaded_bytes") or 0)
            debug_report.total_bytes = int(status.get("total_bytes") or status.get("total_bytes_estimate") or 0)
            debug_report.speed = status.get("speed")
            info = status.get("info_dict") or {}
            if info.get("format_id"):
                debug_report.format_id = str(info.get("format_id"))
            schedule_debug_playback_update(debug_report, loop)

        options["progress_hooks"] = [debug_progress_hook]
    downloader = yt_dlp.YoutubeDL(options)
    data = await loop.run_in_executor(None, lambda: downloader.extract_info(video_url, download=True))
    if data is None:
        raise Exception("Failed to download track info")
    if 'entries' in data:
        data = next((entry for entry in data['entries'] if entry), None)
    if data is None:
        raise Exception("No playable result found during download")
    temp_path = downloader.prepare_filename(data)
    if debug_report:
        debug_report.format_id = str(data.get("format_id") or debug_report.format_id or "")
        debug_report.stage = "downloaded"
        await append_debug_playback_event(debug_report, "download completed; moving into cache", force=True)
        await edit_debug_playback_message(debug_report, force=True)
    ext = os.path.splitext(temp_path)[1].lstrip(".").lower()
    target_path = cache_path_for_key(cache_key, ext, playlist=playlist)
    if not is_safe_cache_path(temp_path):
        raise Exception("Downloaded file path failed safety validation.")
    if cache_bytes_before + os.path.getsize(temp_path) > CACHE_HARD_LIMIT_BYTES:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise Exception("Cache hard limit reached; download refused.")
    os.replace(temp_path, target_path)
    if not is_safe_cache_path(target_path, cache_key):
        raise Exception("Final cache file failed safety validation.")
    return target_path, ext, data

def youtube_playlist_watch_url(playlist_id: str, video_id: Optional[str] = None) -> str:
    if video_id:
        return f"{youtube_watch_url}{video_id}&list={urllib.parse.quote(playlist_id)}"
    return f"{youtube_base_url}playlist?list={urllib.parse.quote(playlist_id)}"

def track_metadata_from_ytdlp(data: dict, *, filesize: Optional[int] = None) -> dict:
    metadata = {}
    for key in (
        "duration", "format_id", "format", "format_note", "acodec", "abr", "tbr",
        "asr", "audio_channels", "dynamic_range", "bpm", "uploader", "channel",
        "creator", "artist", "artists", "track", "alt_title", "fulltitle",
        "is_live", "age_limit",
    ):
        value = data.get(key)
        if value not in (None, ""):
            metadata[key] = value
    if filesize:
        metadata["filesize"] = filesize
    elif data.get("filesize") or data.get("filesize_approx"):
        metadata["filesize"] = data.get("filesize") or data.get("filesize_approx")
    return metadata

def is_search_query(query: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(query or "").strip())
    except Exception:
        return True
    return not parsed.netloc and not parsed.scheme

def playback_error_message(error, user=None) -> str:
    text = sanitize_debug_text(str(error or ""))
    lower = text.lower()
    admin_suffix = ""
    if is_user_admin(user) and not YTDLP_JS_RUNTIMES:
        admin_suffix = " Admin note: install `deno` or `node` on PATH so yt-dlp can use YouTube's current JavaScript player."
    if "this video is not available" in lower or "private video" in lower or "video unavailable" in lower:
        return "YouTube says that selected video is unavailable. Try a more specific search or a direct working YouTube link." + admin_suffix
    if "no playable result" in lower or "no data found" in lower:
        return "No playable YouTube result was found for that request. Try a more specific title or a direct YouTube link." + admin_suffix
    if "only youtube urls" in lower or "private network" in lower or "local" in lower:
        return "Only YouTube URLs or search terms are supported."
    if "cache hard limit" in lower or "disk" in lower or "free on disk" in lower:
        return f"Playback was refused because of a cache or disk limit: {discord.utils.escape_markdown(truncate_text(text, 220))}"
    if "javascript runtime" in lower or "js runtime" in lower:
        return "YouTube extraction needs a supported JavaScript runtime. Ask an admin to install `deno` or `node` on PATH."
    return "Failed to add or play that track. Check the bot logs for details." + admin_suffix

async def fetch_search_fallback_metadata(query: str, original_error):
    """Try a few search results when yt-dlp's first selected result is unavailable."""
    options = dict(ytdl_options)
    options["default_search"] = "ytsearch5"
    options["ignoreerrors"] = True
    options["extract_flat"] = "in_playlist"
    loop = asyncio.get_event_loop()
    extractor = yt_dlp.YoutubeDL(options)
    search_data = await loop.run_in_executor(None, lambda: extractor.extract_info(f"ytsearch5:{query}", download=False))
    entries = [entry for entry in (search_data or {}).get("entries", []) if entry]
    last_error = original_error
    for entry in entries[:5]:
        video_id = playlist_entry_video_id(entry)
        if not video_id:
            continue
        try:
            return await loop.run_in_executor(None, lambda vid=video_id: ytdl.extract_info(canonical_youtube_url(vid), download=False))
        except Exception as exc:
            last_error = exc
            logger.info(f"Skipping unavailable fallback search result {video_id} for {query!r}: {exc}")
    raise last_error

def playlist_entry_video_id(entry: dict) -> Optional[str]:
    if not isinstance(entry, dict):
        return None
    for key in ("id", "url", "webpage_url"):
        value = str(entry.get(key) or "").strip()
        if not value:
            continue
        if key == "id" and YOUTUBE_VIDEO_ID_PATTERN.fullmatch(value):
            return value
        parsed = parse_youtube_video_id(value)
        if parsed:
            return parsed
        if YOUTUBE_VIDEO_ID_PATTERN.fullmatch(value):
            return value
    return None

def playlist_entry_to_track(entry: dict, *, playlist_id: str, playlist_name: str, block_id: str, index: int, total: int) -> Optional[dict]:
    video_id = playlist_entry_video_id(entry)
    if not video_id:
        return None
    title = str(entry.get("title") or "Unknown title")
    if title.lower() in {"[deleted video]", "[private video]"}:
        return None
    return {
        "id": video_id,
        "title": title,
        "webpage_url": canonical_youtube_url(video_id),
        "cache_key": canonical_cache_key_from_video_id(video_id),
        "cache_mode": "streaming",
        "cache_path": None,
        "ext": None,
        "playlist_id": f"youtube:{playlist_id}",
        "playlist_name": playlist_name,
        "playlist_block_id": block_id,
        "playlist_index": index,
        "playlist_total": total,
        "youtube_playlist_id": playlist_id,
        "youtube_playlist_url": youtube_playlist_watch_url(playlist_id, video_id),
        # Playlist extraction is metadata-only. Resolve each track through the
        # normal fetch path when it reaches playback so duration/cache rules
        # are still applied before ffmpeg sees it.
        "needs_refresh": True,
    }

def rotate_playlist_entries_for_selected(entries: list, selected_video_id: Optional[str]) -> list:
    if not selected_video_id:
        return entries
    for index, entry in enumerate(entries):
        if playlist_entry_video_id(entry) == selected_video_id:
            return entries[index:]
    return entries

async def fetch_youtube_playlist_tracks(query: str, requested_by=None, debug_report: Optional[DebugPlaybackMessage] = None) -> Optional[list]:
    """Extract a YouTube playlist URL into queue-ready track dictionaries."""
    query = validate_media_query(query)
    playlist_id = parse_youtube_playlist_id(query)
    if not playlist_id:
        return None

    selected_video_id = parse_youtube_video_id(query)
    selected_index = parse_youtube_playlist_index(query)
    options = dict(ytdl_options)
    options["noplaylist"] = False
    options["extract_flat"] = "in_playlist"
    options["ignoreerrors"] = True
    if selected_index:
        options["playliststart"] = selected_index
        options["playlistend"] = selected_index + MAX_PLAYLIST_TRACKS - 1
    else:
        options["playlistend"] = MAX_PLAYLIST_TRACKS

    if debug_report:
        debug_report.stage = "playlist"
        debug_report.cache_state = "metadata"
        await append_debug_playback_event(debug_report, "reading YouTube playlist metadata", force=True)
        await edit_debug_playback_message(debug_report, force=True)

    loop = asyncio.get_event_loop()
    extractor = yt_dlp.YoutubeDL(options)
    data = await loop.run_in_executor(None, lambda: extractor.extract_info(query, download=False))
    entries = [entry for entry in (data or {}).get("entries", []) if entry]
    if not entries:
        raise Exception("No playable entries were found in that YouTube playlist.")

    entries = rotate_playlist_entries_for_selected(entries, selected_video_id)
    if selected_video_id and not any(playlist_entry_video_id(entry) == selected_video_id for entry in entries):
        entries.insert(0, {
            "id": selected_video_id,
            "title": "Selected YouTube video",
            "webpage_url": canonical_youtube_url(selected_video_id),
        })

    entries = entries[:MAX_PLAYLIST_TRACKS]
    playlist_name = str((data or {}).get("title") or f"YouTube playlist {playlist_id}")
    block_id = generate_playlist_id()
    tracks = []
    for entry in entries:
        track = playlist_entry_to_track(
            entry,
            playlist_id=playlist_id,
            playlist_name=playlist_name,
            block_id=block_id,
            index=len(tracks) + 1,
            total=len(entries),
        )
        if track:
            tracks.append(track)

    total = len(tracks)
    for index, track in enumerate(tracks, start=1):
        track["playlist_index"] = index
        track["playlist_total"] = total

    if not tracks:
        raise Exception("No playable entries were found in that YouTube playlist.")
    logger.info(
        f"Resolved YouTube playlist {playlist_id} into {len(tracks)} track(s) "
        f"for {user_display(requested_by) if requested_by else 'unknown user'}."
    )
    await append_debug_playback_event(debug_report, f"playlist metadata resolved: {len(tracks)} track(s)", stage="playlist-ready", force=True)
    return tracks

async def fetch_media_tracks(query: str, requested_by=None, debug_report: Optional[DebugPlaybackMessage] = None) -> list:
    playlist_tracks = await fetch_youtube_playlist_tracks(query, requested_by=requested_by, debug_report=debug_report)
    tracks = playlist_tracks if playlist_tracks else [await fetch_track(query, requested_by=requested_by, debug_report=debug_report)]
    requester_id = user_id_value(requested_by)
    if requester_id:
        for track in tracks:
            track["requested_by_user_id"] = requester_id
            track["requested_by_discord_name"] = user_display(requested_by)
    return tracks

def preserve_playlist_context(original: dict, resolved: dict) -> dict:
    context_keys = (
        "playlist_id", "playlist_name", "playlist_block_id", "playlist_index",
        "playlist_total", "youtube_playlist_id", "youtube_playlist_url",
        "requested_by_user_id", "requested_by_discord_name",
    )
    for key in context_keys:
        if key in original:
            resolved[key] = original[key]
    resolved.pop("needs_refresh", None)
    original.clear()
    original.update(resolved)
    return original

async def resolve_track_for_playback(track: dict, requested_by=None, debug_report: Optional[DebugPlaybackMessage] = None) -> dict:
    if not track.get("needs_refresh"):
        return track
    requester = requested_by or track.get("requested_by_user_id")
    resolved = await fetch_track(track.get("webpage_url") or canonical_youtube_url(track.get("id")), requested_by=requester, debug_report=debug_report)
    if resolved.get("needs_confirm"):
        raise Exception("Track needs admin confirmation before playback.")
    return preserve_playlist_context(track, resolved)

async def fetch_track(query: str, requested_by=None, debug_report: Optional[DebugPlaybackMessage] = None):
    """
    Fetches YouTube track info for the given query (URL or search term).
    If download_mode is True, downloads the audio (unless cached) and returns track info with file path.
    If download_mode is False, returns track info for streaming (no file path).
    Applies size and duration restrictions based on user permissions.
    """
    # Determine the full YouTube URL and video ID for URL inputs. Search text is
    # passed directly to yt-dlp so it can use its own maintained search extractor.
    video_url, video_id = normalize_youtube_query(query)
    force_stream_only = user_has_group(requested_by, "nodownload")
    if force_stream_only:
        logger.info(f"Download/cache disabled for {user_display(requested_by)} ({user_id_value(requested_by)}): nodownload.")

    cache_key = canonical_cache_key_from_video_id(video_id) if video_id else None
    if debug_report:
        debug_report.stage = "normalizing"
        await append_debug_playback_event(debug_report, "normalizing media query", force=True)
        await edit_debug_playback_message(debug_report, force=True)

    # If we have a video_id and it's cached (and in download mode), use the cached file.
    if video_id and client.download_mode and not force_stream_only:
        existing_cache = find_existing_cache_file(cache_key, prefer_playlist=True, video_id=video_id)
        info = downloaded.get(video_id, {})
        if existing_cache and info.get('title'):
            title = info.get('title', 'Unknown title')
            if debug_report:
                debug_report.title = title
                debug_report.video_id = video_id
                debug_report.cache_state = "hit"
                debug_report.stage = "cache-hit"
                await append_debug_playback_event(debug_report, "cache hit from metadata", force=True)
                await edit_debug_playback_message(debug_report, force=True)
            page_url = youtube_watch_url + video_id
            cache_mode = "playlist" if os.path.basename(existing_cache).startswith("plst-") else "shortterm"
            append_runtime_audit_event("cache-hit", actor=requested_by, details={
                "video_id": video_id,
                "title": title,
                "cache_mode": cache_mode,
                "cache_path": metadata_path_for_cache_file(existing_cache),
                "source": "downloads_metadata",
            })
            if cache_mode != "playlist":
                downloaded[video_id] = {
                    'title': title,
                    'filepath': existing_cache,
                    'timestamp': time.time(),
                    'cache_key': cache_key,
                    'cache_path': metadata_path_for_cache_file(existing_cache),
                    'ext': os.path.splitext(existing_cache)[1].lstrip(".").lower(),
                }
                save_downloads_metadata("cache reuse")
            return {
                'id': video_id,
                'title': title,
                'webpage_url': page_url,
                'file': existing_cache,
                'cache_key': cache_key,
                'cache_path': metadata_path_for_cache_file(existing_cache),
                'cache_mode': cache_mode,
                'ext': os.path.splitext(existing_cache)[1].lstrip(".").lower(),
            }

    if video_id and video_id in downloaded and client.download_mode and not force_stream_only:
        info = downloaded[video_id]
        file_path = info.get('filepath')
        title = info.get('title', 'Unknown title')
        page_url = youtube_watch_url + video_id
        if file_path and is_safe_download_path(file_path, video_id):
            logger.debug(f"Using cached file for {video_id}: {title}")
            append_runtime_audit_event("cache-hit", actor=requested_by, details={
                "video_id": video_id,
                "title": title,
                "cache_mode": "shortterm",
                "cache_path": metadata_path_for_cache_file(path_from_metadata(file_path)),
                "source": "downloads_metadata_fallback",
            })
            return {'id': video_id, 'title': title, 'webpage_url': page_url, 'file': file_path}
        else:
            # Cached metadata exists but file is missing; remove from cache
            downloaded.pop(video_id, None)
            logger.info(f"Cache entry for {video_id} removed (file not found)")

    # Not cached or not using cache: fetch metadata (and download if needed)
    try:
        logger.debug(f"Fetching track info for query: {query}")
        if debug_report:
            debug_report.stage = "resolving"
            debug_report.cache_state = "checking"
            await append_debug_playback_event(debug_report, "asking yt-dlp for metadata", force=True)
            await edit_debug_playback_message(debug_report, force=True)
        loop = asyncio.get_event_loop()
        # Always extract metadata without downloading first (to get info like duration and size)
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(video_url, download=False))
        except Exception as exc:
            if not video_id and is_search_query(query):
                logger.info(f"Primary search result failed for {query!r}; trying fallback search results: {exc}")
                data = await fetch_search_fallback_metadata(query, exc)
            else:
                raise
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
        if debug_report:
            debug_report.title = title
            debug_report.video_id = video_id
            debug_report.format_id = str(data.get("format_id") or "")
            await append_debug_playback_event(debug_report, "metadata resolved", force=True)
            await edit_debug_playback_message(debug_report, force=True)
        page_url = canonical_youtube_url(video_id)
        cache_key = canonical_cache_key_from_video_id(video_id)
        duration = data.get('duration', 0) or 0  # duration in seconds
        filesize = data.get('filesize') or data.get('filesize_approx') or 0
        if filesize == 0:
            # Estimate filesize if not provided (approximate)
            abr = data.get('abr')  # average bitrate in kbps
            if abr and duration:
                filesize = int((abr * 1000 / 8) * duration)  # bytes
        metadata = track_metadata_from_ytdlp(data, filesize=filesize)

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

        existing_cache = find_existing_cache_file(cache_key, prefer_playlist=True, video_id=video_id)
        if existing_cache and client.download_mode and not force_stream_only:
            cache_mode = "playlist" if os.path.basename(existing_cache).startswith("plst-") else "shortterm"
            if debug_report:
                debug_report.cache_state = f"hit:{cache_mode}"
                debug_report.stage = "cache-hit"
                await append_debug_playback_event(debug_report, f"cache hit: {cache_mode}", force=True)
                await edit_debug_playback_message(debug_report, force=True)
            if cache_mode != "playlist":
                downloaded[video_id] = {
                    'title': title,
                    'filepath': existing_cache,
                    'timestamp': time.time(),
                    'cache_key': cache_key,
                    'cache_path': metadata_path_for_cache_file(existing_cache),
                    'ext': os.path.splitext(existing_cache)[1].lstrip(".").lower(),
                }
                save_downloads_metadata("cache reuse")
            logger.info(f"Using cached file for {video_id}: {title}")
            append_runtime_audit_event("cache-hit", actor=requested_by, details={
                "video_id": video_id,
                "title": title,
                "cache_mode": cache_mode,
                "cache_path": metadata_path_for_cache_file(existing_cache),
                "source": "cache_scan",
            })
            return {
                'id': video_id,
                'title': title,
                'webpage_url': page_url,
                'file': existing_cache,
                'cache_key': cache_key,
                'cache_path': metadata_path_for_cache_file(existing_cache),
                'cache_mode': cache_mode,
                'ext': os.path.splitext(existing_cache)[1].lstrip(".").lower(),
                **metadata,
            }

        total_bytes = estimate_total_downloaded_bytes()

        # If in download mode, enforce file size and total disk usage limits
        if client.download_mode and not force_stream_only:
            if not enough_disk_for_download():
                raise Exception(f"Less than {MIN_FREE_DOWNLOAD_MB}MB free on disk; download refused.")
            if not cache_has_room(filesize or 0):
                logger.warning("Cache hard limit reached; streaming without downloading.")
                append_runtime_audit_event("cache-hard-cap-stream", actor=requested_by, details={
                    "video_id": video_id,
                    "title": title,
                    "filesize": filesize,
                    "cache_bytes": cache_total_bytes(),
                })
                return {'id': video_id, 'title': title, 'webpage_url': page_url, 'cache_key': cache_key, 'cache_mode': 'streaming', 'cache_path': None, **metadata}
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
                    'needs_confirm': True, **metadata
                }

        # At this point, the track is within allowed limits
        if not client.download_mode or force_stream_only:
            # Stream-only mode: do not download, just return info (no 'file' key)
            logger.info(f"Using stream-only mode for '{title}' ({video_id}).")
            append_runtime_audit_event("stream-only-playback", actor=requested_by, details={
                "video_id": video_id,
                "title": title,
                "reason": "nodownload" if force_stream_only else "download_mode_disabled",
            })
            if debug_report:
                debug_report.cache_state = "nodownload" if force_stream_only else "stream-only"
                debug_report.stage = "streaming"
                detail = "nodownload restriction; skipping cache/download" if force_stream_only else "stream-only mode; skipping download"
                await append_debug_playback_event(debug_report, detail, force=True)
                await edit_debug_playback_message(debug_report, force=True)
            return {'id': video_id, 'title': title, 'webpage_url': page_url, 'cache_key': cache_key, 'cache_mode': 'streaming', 'cache_path': None, **metadata}

        # Download mode: download the audio file using yt_dlp
        logger.info(f"Downloading track '{title}' ({video_id})...")
        await append_debug_playback_event(debug_report, "cache miss; downloading audio", stage="downloading", force=True)
        file_path, ext, _ = await download_youtube_to_cache(video_url, cache_key, playlist=False, debug_report=debug_report)
        # Cache the downloaded file info
        downloaded[video_id] = {
            'title': title,
            'filepath': file_path,
            'timestamp': time.time(),
            'cache_key': cache_key,
            'cache_path': metadata_path_for_cache_file(file_path),
            'ext': ext,
        }
        save_downloads_metadata("track download")
        logger.info(f"Downloaded '{title}' ({video_id}) to {file_path}")
        append_runtime_audit_event("cache-download-complete", actor=requested_by, details={
            "video_id": video_id,
            "title": title,
            "cache_path": metadata_path_for_cache_file(file_path),
            "bytes": cache_file_size(file_path),
        })
        if debug_report:
            debug_report.cache_state = "downloaded"
            debug_report.stage = "cached"
            await append_debug_playback_event(debug_report, "cached audio ready for playback", force=True)
            await edit_debug_playback_message(debug_report, force=True)
        return {
            'id': video_id,
            'title': title,
            'webpage_url': page_url,
            'file': file_path,
            'cache_key': cache_key,
            'cache_path': metadata_path_for_cache_file(file_path),
            'cache_mode': 'shortterm',
            'ext': ext,
            **metadata,
        }
    except Exception as e:
        if debug_report:
            debug_report.error = str(e)
            await finish_debug_playback_message(debug_report, status="error", error=str(e))
        logger.error(f"yt_dlp error for {query}: {e}")
        raise

async def ensure_voice_for_playback(ctx):
    voice = active_voice_client(ctx.guild)
    if voice is None or not voice.is_connected():
        if ctx.user.voice and ctx.user.voice.channel:
            try:
                voice = await ctx.user.voice.channel.connect()
                client.current_voice_channel = voice
                apply_channel_volume_default(ctx.user.voice.channel, "playback join")
                cancel_auto_leave_task("playback joined voice")
                cancel_alone_speed_reset_task("playback joined voice")
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
    await resolve_track_for_playback(track, requested_by=track.get("requested_by_user_id"))
    cached_file = None if user_has_group(track.get("requested_by_user_id"), "nodownload") else cached_file_for_track(track)
    speed = playback_speed_for_track(track)
    track["playback_speed"] = speed
    if cached_file:
        track["file"] = cached_file
        append_runtime_audit_event("playback-source-cache", actor=track.get("requested_by_user_id"), details={
            "video_id": track.get("id"),
            "title": track.get("title"),
            "cache_path": metadata_path_for_cache_file(cached_file),
            "speed": speed,
        })
        source = discord.FFmpegPCMAudio(cached_file, **ffmpeg_audio_options_for_speed(speed))
        return discord.PCMVolumeTransformer(source, volume=client.volume)
    append_runtime_audit_event("playback-source-stream", actor=track.get("requested_by_user_id"), details={
        "video_id": track.get("id"),
        "title": track.get("title"),
        "reason": "nodownload" if user_has_group(track.get("requested_by_user_id"), "nodownload") else "cache_unavailable",
        "speed": speed,
    })
    player, _ = await YTDLSource.from_url(track['webpage_url'], stream=True, speed=speed)
    return player

async def start_track_now(ctx, voice, track: dict, *, debug_report: Optional[DebugPlaybackMessage] = None):
    await resolve_track_for_playback(track, requested_by=ctx.user, debug_report=debug_report)
    await append_debug_playback_event(debug_report, "building ffmpeg audio source", stage="ffmpeg", force=True)
    player = await build_audio_player(track)
    voice.play(player, after=lambda e, vid=track['id']: after_played_track(e, vid, ctx.channel))
    client.current_track_id = track['id']
    client.currently_playing = True
    client.last_track_info = client.current_track_info
    client.current_track_info = track
    client.current_track_started_at = time.time()
    sync_repeat_for_started_track(track)
    client.song_history.append(track)
    await publish_now_playing(
        ctx.channel,
        track,
        send_message=ctx.followup.send,
        acknowledge=ctx.followup.send,
    )
    await append_debug_playback_event(debug_report, "playback started", stage="playing", force=True)
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

def active_playlist_prompt_human_count() -> int:
    voice = active_voice_client()
    voice_channel = getattr(voice, "channel", None)
    return len(voice_channel_human_members(voice_channel)) if voice_channel else 0

async def move_queued_track_next(ctx, track: dict, *, reason: str):
    title = discord.utils.escape_markdown(str(track.get("title") or "Unknown title"))
    try:
        queue.remove(track)
    except ValueError:
        pass
    queue.insert(0, track)
    append_runtime_audit_event("playlist-placement-direct", actor=ctx.user, details={
        "reason": reason,
        "track_id": track.get("id"),
        "title": track.get("title"),
        "queue_length": len(queue),
    })
    await ctx.followup.send(f"Added to queue next: **{title}** ({track.get('id', '')})")
    logger.info(f"Moved track next after active playlist without prompt ({reason}): {track.get('title')} ({track.get('id')})")

async def enqueue_track_with_playlist_prompt(ctx, track: dict, command_name: str):
    block_id = active_playlist_block_id()
    if block_id:
        insert_after_active_playlist(track)
        client.song_history.append(track)
        logger.info(f"Track queued after active playlist via /{command_name}: {track.get('title')} ({track.get('id')})")
        if is_user_admin(ctx.user):
            await move_queued_track_next(ctx, track, reason="admin")
            return
        if user_has_group(ctx.user, "noqueueskip"):
            title = discord.utils.escape_markdown(str(track.get('title') or 'Unknown title'))
            await ctx.followup.send(
                f"Added **{title}** after the active playlist. Queue-jump prompts are disabled for your account.",
                ephemeral=True,
            )
            return
        human_count = active_playlist_prompt_human_count()
        if not getattr(client, "voice_votes_enabled", True):
            await move_queued_track_next(ctx, track, reason="voice_votes_disabled")
            return
        if human_count < 3:
            title = discord.utils.escape_markdown(str(track.get('title') or 'Unknown title'))
            await ctx.followup.send(
                f"Added **{title}** after the active playlist. Queue-jump prompt skipped because fewer than 3 people are in voice."
            )
            append_runtime_audit_event("playlist-placement-no-prompt", actor=ctx.user, details={
                "reason": "human_count_below_3",
                "human_count": human_count,
                "track_id": track.get("id"),
                "title": track.get("title"),
            })
            return
        await prompt_move_track_next(ctx, track, (client.current_track_info or {}).get("playlist_name", "playlist"))
    else:
        queue.append(track)
        client.song_history.append(track)
        title = discord.utils.escape_markdown(str(track.get('title') or 'Unknown title'))
        await ctx.followup.send(f"Added to queue: {title} ({track.get('id', '')})")
        logger.info(f"Track enqueued: {track.get('title')} ({track.get('id')})")

def youtube_playlist_queue_message(tracks: list, *, action: str) -> str:
    playlist_name = discord.utils.escape_markdown(str(tracks[0].get("playlist_name") or "YouTube playlist"))
    return f"{action} YouTube playlist **{playlist_name}** ({len(tracks)} song(s))."

async def enqueue_youtube_playlist_tracks(ctx, tracks: list, command_name: str, *, front: bool = False):
    if not tracks:
        await ctx.followup.send("That YouTube playlist has no playable tracks.")
        return
    if not await require_queue_room_for_count(ctx, len(tracks)):
        return
    if front:
        queue[0:0] = tracks
        action = "Moved to play next:"
    else:
        queue.extend(tracks)
        action = "Queued"
    client.song_history.extend(tracks)
    await ctx.followup.send(youtube_playlist_queue_message(tracks, action=action))
    logger.info(
        f"YouTube playlist queued via /{command_name}: "
        f"{tracks[0].get('playlist_name')} ({tracks[0].get('youtube_playlist_id')}) "
        f"tracks={len(tracks)} front={front}"
    )

async def play_youtube_playlist_tracks(ctx, voice, tracks: list, command_name: str, *, debug_report: Optional[DebugPlaybackMessage] = None):
    if not tracks:
        await ctx.followup.send("That YouTube playlist has no playable tracks.")
        return
    queued_count = max(0, len(tracks) - 1)
    if not await require_queue_room_for_count(ctx, queued_count):
        return
    first, rest = tracks[0], tracks[1:]
    await start_track_now(ctx, voice, first, debug_report=debug_report)
    queue.extend(rest)
    client.song_history.extend(rest)
    if rest:
        await ctx.followup.send(youtube_playlist_queue_message(tracks, action="Loaded"))
    logger.info(
        f"YouTube playlist started via /{command_name}: "
        f"{first.get('playlist_name')} ({first.get('youtube_playlist_id')}) "
        f"playing={first.get('id')} queued={len(rest)}"
    )

def effective_playlist_cache_mode(playlist: dict) -> str:
    if client.force_global_playlist_cache_mode:
        return client.playlist_cache_default_mode
    mode = playlist.get("cache_mode") or "follow_global"
    if mode == "follow_global":
        return client.playlist_cache_default_mode
    if mode not in PLAYLIST_CACHE_MODES:
        return client.playlist_cache_default_mode
    return mode

def playlist_cache_status_line(playlist: dict) -> str:
    configured = playlist.get("cache_mode", "follow_global")
    effective = effective_playlist_cache_mode(playlist)
    forced = " forced-global" if client.force_global_playlist_cache_mode else ""
    return f"cache mode: `{configured}` -> `{effective}`{forced}"

async def cache_playlist_track(track: dict, *, playlist_cache: bool, projected_limit: Optional[int] = None) -> tuple:
    cache_key = cache_key_for_track(track)
    video_id = str(track.get("id") or "").strip()
    if not cache_key or not video_id:
        return False, 0
    existing = find_existing_cache_file(cache_key, prefer_playlist=True, video_id=video_id)
    if existing:
        apply_cache_fields(track, existing, cache_mode="playlist" if os.path.basename(existing).startswith("plst-") else "shortterm")
        return False, 0
    url = track.get("webpage_url") or canonical_youtube_url(video_id)
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
    if data is None:
        return False, 0
    if 'entries' in data:
        data = next((entry for entry in data['entries'] if entry), None)
    if data is None:
        return False, 0
    filesize = data.get('filesize') or data.get('filesize_approx') or 0
    if projected_limit is not None and filesize and filesize > projected_limit:
        return False, 0
    if not enough_disk_for_download() or not cache_has_room(filesize or 0):
        logger.warning("Playlist cache download skipped because disk/cache limit was reached.")
        return False, 0
    file_path, ext, _ = await download_youtube_to_cache(url, cache_key, playlist=playlist_cache)
    apply_cache_fields(track, file_path, cache_mode="playlist" if playlist_cache else "shortterm")
    track["ext"] = ext
    return True, cache_file_size(file_path)

def playlist_cache_result_summary(result: dict) -> str:
    prepared = result.get("prepared", 0)
    downloaded = result.get("downloaded", 0)
    reused = result.get("reused", 0)
    failed = result.get("failed", 0)
    parts = [f"{prepared} prepared", f"{downloaded} downloaded", f"{reused} reused"]
    if failed:
        parts.append(f"{failed} failed")
    return ", ".join(parts)

def playlist_cache_warm_message(playlist: dict, result: dict) -> Optional[str]:
    if result.get("mode") == "streaming" or result.get("skipped"):
        return None
    if not (result.get("prepared") or result.get("downloaded") or result.get("reused") or result.get("failed")):
        return None
    name = discord.utils.escape_markdown(str(playlist.get("name") or "playlist"))
    summary = playlist_cache_result_summary(result)
    if result.get("capped"):
        return (
            f"Playlist cache warmup for **{name}** reached the bounded limit "
            f"({summary}). Remaining tracks will stream when needed."
        )
    return f"Playlist cache warmup for **{name}** complete ({summary})."

async def cache_playlist_tracks_for_playback(playlist: dict, tracks: list, *, actor=None) -> dict:
    mode = effective_playlist_cache_mode(playlist)
    result = {
        "playlist_id": playlist.get("id"),
        "playlist_name": playlist.get("name"),
        "mode": mode,
        "total": len(tracks),
        "considered": 0,
        "prepared": 0,
        "downloaded": 0,
        "reused": 0,
        "failed": 0,
        "bytes": 0,
        "capped": False,
        "skipped": False,
    }
    if mode == "streaming":
        result["skipped"] = True
        result["reason"] = "streaming"
        return result
    downloaded_bytes = 0
    track_limit = PLAYLIST_CACHE_BOUNDED_TRACK_LIMIT if mode == "bounded" else len(tracks)
    byte_limit = PLAYLIST_CACHE_BOUNDED_BYTES if mode == "bounded" else CACHE_HARD_LIMIT_BYTES
    changed = False
    playlist_tracks = playlist.get("tracks", [])

    for index, queue_track in enumerate(tracks):
        if mode == "bounded" and (result["considered"] >= track_limit or downloaded_bytes >= byte_limit):
            result["capped"] = index < len(tracks)
            break
        result["considered"] += 1
        cache_key = cache_key_for_track(queue_track)
        if not cache_key:
            continue
        existing = find_existing_cache_file(cache_key, prefer_playlist=True, video_id=str(queue_track.get("id") or "").strip() or None)
        if existing:
            apply_cache_fields(queue_track, existing, cache_mode="playlist" if os.path.basename(existing).startswith("plst-") else "shortterm")
            if index < len(playlist_tracks):
                apply_cache_fields(playlist_tracks[index], existing, cache_mode=queue_track.get("cache_mode", "shortterm"))
            result["reused"] += 1
            result["prepared"] += 1
            changed = True
            continue
        try:
            did_download, size = await cache_playlist_track(
                queue_track,
                playlist_cache=True,
                projected_limit=max(0, byte_limit - downloaded_bytes),
            )
        except Exception as exc:
            result["failed"] += 1
            logger.warning(f"Playlist cache download failed for {queue_track.get('id')}: {exc}")
            continue
        if did_download:
            if downloaded_bytes + size > byte_limit:
                file_path = queue_track.get("file")
                if file_path and is_safe_cache_path(file_path, cache_key):
                    try:
                        os.remove(file_path)
                    except OSError as exc:
                        logger.warning(f"Failed to remove over-limit playlist cache file {file_path}: {exc}")
                apply_cache_fields(queue_track, None, cache_mode="streaming")
                result["capped"] = True
                break
            result["downloaded"] += 1
            result["prepared"] += 1
            downloaded_bytes += size
            result["bytes"] += size
            if index < len(playlist_tracks):
                apply_cache_fields(playlist_tracks[index], queue_track.get("file"), cache_mode="playlist")
            changed = True
    if changed:
        playlist["predownloaded"] = True
        playlist["predownloaded_at"] = time.time()
        save_playlist(playlist)
    return result

async def prepare_playlist_cache_for_playback(ctx, playlist: dict, tracks: list):
    result = await cache_playlist_tracks_for_playback(playlist, tracks, actor=getattr(ctx, "user", None))
    if result.get("capped"):
        await ctx.followup.send(
            "Playlist cache limit reached: cached up to 15 tracks or 3 GB. Remaining tracks will stream when needed."
        )
    elif result.get("prepared"):
        await ctx.followup.send(f"Using playlist cache for {result.get('prepared')} track(s).")

def playlist_cache_task_key(playlist: dict, channel) -> str:
    return f"{playlist.get('id') or 'playlist'}:{getattr(channel, 'id', 'no-channel')}"

def schedule_playlist_cache_warmup(ctx, playlist: dict, tracks: list, command_name: str) -> bool:
    if not tracks or is_favorites_playlist(playlist) or user_has_group(ctx.user, "nodownload"):
        return False
    if effective_playlist_cache_mode(playlist) == "streaming":
        return False
    channel = getattr(ctx, "channel", None)
    key = playlist_cache_task_key(playlist, channel)
    existing_task = client.playlist_cache_tasks.get(key)
    if existing_task and not existing_task.done():
        append_runtime_audit_event("playlist-cache-warm-already-running", actor=ctx.user, details={
            "playlist_id": playlist.get("id"),
            "playlist_name": playlist.get("name"),
            "command": command_name,
            "tracks": len(tracks),
        })
        return False

    actor = ctx.user

    async def runner():
        try:
            append_runtime_audit_event("playlist-cache-warm-started", actor=actor, details={
                "playlist_id": playlist.get("id"),
                "playlist_name": playlist.get("name"),
                "command": command_name,
                "tracks": len(tracks),
                "mode": effective_playlist_cache_mode(playlist),
            })
            try:
                result = await cache_playlist_tracks_for_playback(playlist, tracks, actor=actor)
                append_runtime_audit_event("playlist-cache-warm-finished", actor=actor, details=result)
            except Exception as exc:
                append_runtime_audit_event("playlist-cache-warm-failed", actor=actor, details={
                    "playlist_id": playlist.get("id"),
                    "playlist_name": playlist.get("name"),
                    "command": command_name,
                    "error": str(exc),
                })
                logger.warning(f"Playlist cache warmup failed for {playlist.get('name')} ({playlist.get('id')}): {exc}")
                return
            message = playlist_cache_warm_message(playlist, result)
            if message and channel:
                try:
                    await channel.send(message)
                except Exception as exc:
                    append_runtime_audit_event("playlist-cache-warm-notify-failed", actor=actor, details={
                        "playlist_id": playlist.get("id"),
                        "playlist_name": playlist.get("name"),
                        "command": command_name,
                        "error": str(exc),
                    })
                    logger.warning(f"Playlist cache warmup notification failed for {playlist.get('name')} ({playlist.get('id')}): {exc}")
        finally:
            if client.playlist_cache_tasks.get(key) is task:
                client.playlist_cache_tasks.pop(key, None)

    task = asyncio.create_task(runner())
    client.playlist_cache_tasks[key] = task
    return True

async def play_playlist_now(ctx, playlist: dict, command_name: str):
    tracks = playlist_to_queue_tracks(playlist)
    for track in tracks:
        track["requested_by_user_id"] = user_id_value(ctx.user)
        track["requested_by_discord_name"] = user_display(ctx.user)
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
        warmup_started = schedule_playlist_cache_warmup(ctx, playlist, tracks, command_name)
        suffix = "\nPlaylist cache warmup is running in the background." if warmup_started else ""
        await ctx.followup.send(
            f"Queued playlist **{discord.utils.escape_markdown(playlist['name'])}** ({len(tracks)} song(s)).{suffix}"
        )
        logger.info(f"Queued playlist via /{command_name}: {playlist['name']} ({playlist['id']})")
        return
    first, rest = tracks[0], tracks[1:]
    queue.extend(rest)
    for track in rest:
        client.song_history.append(track)
    await start_track_now(ctx, voice, first)
    schedule_playlist_cache_warmup(ctx, playlist, tracks, command_name)
    logger.info(f"Started playlist via /{command_name}: {playlist['name']} ({playlist['id']})")

def favorites_visible_to_requester(requester, playlist: dict) -> bool:
    return (
        playlist_owner_id(playlist) == user_id_value(requester)
        or is_playlist_public(playlist)
    )

async def confirm_favorites_admin_override(ctx, playlist: dict, action: str = "play") -> bool:
    if favorites_visible_to_requester(ctx.user, playlist):
        return True
    if not is_user_admin(ctx.user):
        return False
    owner = discord.utils.escape_markdown(str(playlist.get("owner_discord_name", "unknown")))
    return await confirm_with_reactions(
        ctx,
        f"**admin privacy override**: **{owner}** has private favorites. Confirm {action} anyway?",
    )

async def play_favorites_playlist(ctx, playlist: dict, command_name: str):
    if not await confirm_favorites_admin_override(ctx, playlist, "playing favorites"):
        await safe_interaction_send(ctx, "Those favorites are private.", ephemeral=True)
        return
    if favorites_cache_policy().get("enabled") and not user_has_group(ctx.user, "nodownload"):
        result = await prepare_favorites_cache_round_robin()
        if result.get("enabled") and (result.get("downloaded") or result.get("reused") or result.get("capped")):
            suffix = " Favorite cache cap reached; later favorites will stream." if result.get("capped") else ""
            await ctx.followup.send(
                f"Favorites cache prepared: {result.get('downloaded', 0)} downloaded, "
                f"{result.get('reused', 0)} already cached.{suffix}"
            )
    await play_playlist_now(ctx, playlist, command_name)

def member_matches_text(member, text: str) -> bool:
    lookup = str(text or "").strip().lower()
    if not lookup:
        return False
    if lookup in {str(getattr(member, "id", "")), f"<@{getattr(member, 'id', '')}>", f"<@!{getattr(member, 'id', '')}>"}:
        return True
    names = {
        str(getattr(member, "display_name", "")).lower(),
        str(getattr(member, "name", "")).lower(),
        str(member).lower(),
    }
    return lookup in names

def resolve_member_text(ctx, text: str):
    text = str(text or "").strip()
    if not text:
        return ctx.user
    guild = getattr(ctx, "guild", None)
    members = getattr(guild, "members", []) if guild else []
    for member in members:
        if member_matches_text(member, text):
            return member
    return None

def parse_play_favorites_alias(query: str) -> Optional[str]:
    text = str(query or "").strip()
    if not text.lower().startswith("-favorites"):
        return None
    return text[len("-favorites"):].strip()

async def play_favorites_alias(ctx, user_text: str) -> bool:
    target_user = resolve_member_text(ctx, user_text)
    if not target_user:
        await ctx.followup.send("I could not find that user for favorites playback.", ephemeral=True)
        return True
    playlist = favorites_playlist_for_user(target_user, create=False)
    if not playlist or not playlist.get("tracks"):
        await ctx.followup.send("That user has no saved favorites yet.", ephemeral=True)
        return True
    await play_favorites_playlist(ctx, playlist, "play -favorites")
    return True

async def enqueue_playlist(ctx, playlist: dict, command_name: str):
    tracks = playlist_to_queue_tracks(playlist)
    for track in tracks:
        track["requested_by_user_id"] = user_id_value(ctx.user)
        track["requested_by_discord_name"] = user_display(ctx.user)
    if not tracks:
        await ctx.followup.send("That playlist is empty.")
        return
    if not is_user_admin(ctx.user) and len(queue) + len(tracks) > MAX_QUEUE_LENGTH:
        await ctx.followup.send(f"Queue limit reached ({MAX_QUEUE_LENGTH} songs). Ask an admin to clear the queue.", ephemeral=True)
        return
    for track in tracks:
        queue.append(track)
        client.song_history.append(track)
    warmup_started = schedule_playlist_cache_warmup(ctx, playlist, tracks, command_name)
    suffix = "\nPlaylist cache warmup is running in the background." if warmup_started else ""
    await ctx.followup.send(f"Queued playlist **{discord.utils.escape_markdown(playlist['name'])}** ({len(tracks)} song(s)).{suffix}")
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
    for track in tracks:
        track["requested_by_user_id"] = user_id_value(ctx.user)
        track["requested_by_discord_name"] = user_display(ctx.user)
    if not tracks:
        await ctx.response.send_message("That playlist is empty.")
        return
    if not is_user_admin(ctx.user) and len(queue) + len(tracks) > MAX_QUEUE_LENGTH:
        await ctx.response.send_message(f"Queue limit reached ({MAX_QUEUE_LENGTH} songs). Ask an admin to clear the queue.", ephemeral=True)
        return
    if not ctx.response.is_done():
        await ctx.response.defer()
    queue[0:0] = tracks
    client.song_history.extend(tracks)
    warmup_started = schedule_playlist_cache_warmup(ctx, playlist, tracks, "queuefirst")
    suffix = "\nPlaylist cache warmup is running in the background." if warmup_started else ""
    await ctx.followup.send(
        f"Moved playlist **{discord.utils.escape_markdown(playlist['name'])}** to play next ({len(tracks)} song(s)).{suffix}"
    )
    logger.info(f"Playlist queued at front: {playlist['name']} ({playlist['id']})")

async def predownload_playlist_files(playlist: dict) -> int:
    downloaded_count = 0
    for track in playlist.get("tracks", []):
        normalize_playlist_track_cache_fields(track)
        video_id = str(track.get("id") or "")
        if not video_id:
            continue
        cached_file = cached_file_for_track(track)
        if cached_file and os.path.basename(cached_file).startswith("plst-"):
            apply_cache_fields(track, cached_file, cache_mode="playlist")
            continue
        url = track.get("webpage_url") or youtube_watch_url + video_id
        cache_key = cache_key_for_track(track)
        if not cache_key:
            continue
        if not cache_has_room():
            logger.warning("Playlist predownload stopped because cache hard limit was reached.")
            break
        file_path, ext, _ = await download_youtube_to_cache(url, cache_key, playlist=True)
        apply_cache_fields(track, file_path, cache_mode="playlist")
        track["ext"] = ext
        track["permanent_downloaded_at"] = time.time()
        downloaded_count += 1
    playlist["predownloaded"] = True
    playlist["predownloaded_at"] = time.time()
    playlist["cache_mode"] = "keep_cached"
    save_playlist(playlist)
    return downloaded_count

def current_session_cache_targets(*, include_current: bool = True) -> list:
    tracks = []
    if include_current and client.current_track_info:
        tracks.append(client.current_track_info)
    tracks.extend(queue)
    return [
        track for track in tracks
        if isinstance(track, dict) and (track.get("webpage_url") or track.get("id"))
    ]

async def cache_current_session_tracks(*, include_current: bool = True) -> dict:
    result = {
        "total": 0,
        "downloaded": 0,
        "reused": 0,
        "skipped": 0,
        "restricted": 0,
        "failed": 0,
        "bytes": 0,
    }
    tracks = current_session_cache_targets(include_current=include_current)
    result["total"] = len(tracks)
    for track in tracks:
        requester = track.get("requested_by_user_id")
        if user_has_group(requester, "nodownload"):
            result["restricted"] += 1
            logger.info(f"Session cache skipped nodownload track: {track.get('title')} ({track.get('id')})")
            continue
        cache_key = cache_key_for_track(track)
        video_id = str(track.get("id") or "").strip()
        if not cache_key or not video_id:
            result["skipped"] += 1
            continue
        existing = cached_file_for_track(track) or find_existing_cache_file(cache_key, prefer_playlist=True, video_id=video_id)
        if existing:
            apply_cache_fields(track, existing, cache_mode="playlist" if os.path.basename(existing).startswith("plst-") else "shortterm")
            result["reused"] += 1
            continue
        try:
            did_download, size = await cache_playlist_track(track, playlist_cache=False)
        except Exception as exc:
            result["failed"] += 1
            logger.warning(f"Session cache download failed for {track.get('title')} ({video_id}): {exc}")
            continue
        if did_download:
            result["downloaded"] += 1
            result["bytes"] += size
        else:
            if cached_file_for_track(track):
                result["reused"] += 1
            else:
                result["skipped"] += 1
    return result

async def playlist_creation_timeout(key: tuple, channel, marker: float):
    await asyncio.sleep(PLAYLIST_CREATION_TIMEOUT_SECONDS)
    session = client.playlist_creation_sessions.get(key)
    if not session:
        client.playlist_creation_timeout_tasks.pop(key, None)
        return
    if session.updated_at != marker:
        return
    client.playlist_creation_sessions.pop(key, None)
    client.playlist_creation_timeout_tasks.pop(key, None)
    try:
        if session.append_to_existing:
            await channel.send(
                f"Playlist add-more timed out. **{discord.utils.escape_markdown(session.name)}** remains saved."
            )
        else:
            await channel.send("Playlist creation timed out. Nothing was saved. Start again with `/playlist new`.")
    except Exception as exc:
        logger.warning(f"Failed to send playlist creation timeout message: {exc}")

def refresh_playlist_creation_timeout(key: tuple, channel, session: PlaylistCreationSession):
    task = client.playlist_creation_timeout_tasks.pop(key, None)
    if task:
        task.cancel()
    client.playlist_creation_timeout_tasks[key] = asyncio.create_task(
        playlist_creation_timeout(key, channel, session.updated_at)
    )

def finish_playlist_creation_session(key: tuple):
    client.playlist_creation_sessions.pop(key, None)
    task = client.playlist_creation_timeout_tasks.pop(key, None)
    if task:
        task.cancel()

async def start_playlist_creation_flow(ctx):
    expire_playlist_creation_sessions()
    key = playlist_session_key(ctx.user, ctx.channel)
    if key in client.playlist_creation_sessions:
        await ctx.response.send_message(
            "You already have a playlist creation flow open here. Send `cancel` to stop it or `done` to finish.",
            ephemeral=True,
        )
        return
    now = time.time()
    session = PlaylistCreationSession(
        user_id=user_id_value(ctx.user),
        guild_id=key[0],
        channel_id=key[1],
        step="name",
        started_at=now,
        updated_at=now,
    )
    client.playlist_creation_sessions[key] = session
    refresh_playlist_creation_timeout(key, ctx.channel, session)
    await ctx.response.send_message("What should the playlist be called?")

async def create_playlist_from_queue(ctx, name: str, visibility: str = "private"):
    expire_playlist_creation_sessions()
    safe_name = normalize_playlist_name(name)
    error = playlist_name_error(safe_name, ctx.user)
    if error:
        await safe_interaction_send(ctx, error, ephemeral=True)
        return
    tracks = queue_tracks_for_playlist_import(ctx.user)
    if not tracks:
        await safe_interaction_send(
            ctx,
            "The queue is empty, so no playlist was created. Add songs to the queue first, then try `/playlist new Roadtrip current`.",
            ephemeral=True,
        )
        return
    try:
        playlist = save_new_playlist(safe_name, ctx.user, tracks, visibility)
    except Exception as exc:
        logger.error(f"Failed to create playlist from queue: {exc}")
        await safe_interaction_send(ctx, "Could not save the playlist. Check output.log.", ephemeral=True)
        return
    skipped = len(queue) - len(tracks)
    suffix = f" Skipped {skipped} queue item(s) without YouTube metadata." if skipped else ""
    key = playlist_session_key(ctx.user, ctx.channel)
    if key in client.playlist_creation_sessions:
        finish_playlist_creation_session(key)
    now = time.time()
    session = PlaylistCreationSession(
        user_id=user_id_value(ctx.user),
        guild_id=key[0],
        channel_id=key[1],
        step="urls",
        name=playlist["name"],
        tracks=list(playlist.get("tracks", [])),
        playlist_id=playlist["id"],
        append_to_existing=True,
        started_at=now,
        updated_at=now,
    )
    client.playlist_creation_sessions[key] = session
    refresh_playlist_creation_timeout(key, ctx.channel, session)
    await safe_interaction_send(
        ctx,
        playlist_created_message(playlist)
        + suffix
        + " Send more YouTube URLs to add them, or type `done` to finish.",
    )

async def add_urls_to_playlist_session(session: PlaylistCreationSession, user, urls: list) -> tuple:
    added = []
    failed = []
    limit_hit = False
    for url in urls:
        if len(session.tracks) + len(added) >= MAX_PLAYLIST_TRACKS:
            limit_hit = True
            break
        try:
            tracks = await fetch_media_tracks(url, requested_by=user)
            for track in tracks:
                if len(session.tracks) + len(added) >= MAX_PLAYLIST_TRACKS:
                    limit_hit = True
                    break
                if track.get("needs_confirm"):
                    failed.append(url)
                    continue
                added.append(playlist_track_from_track(track, user))
        except Exception as exc:
            logger.warning(f"Failed to add URL to playlist creation session: {url}: {exc}")
            failed.append(url)
    session.tracks.extend(added)
    return added, failed, limit_hit

async def handle_playlist_creation_message(msg) -> bool:
    if getattr(msg.author, "bot", False):
        return False
    expire_playlist_creation_sessions()
    key = playlist_session_key(msg.author, msg.channel)
    session = client.playlist_creation_sessions.get(key)
    if not session:
        return False
    if user_has_group(msg.author, "noplaylistcreate"):
        finish_playlist_creation_session(key)
        await msg.channel.send("Playlist creation cancelled because your account is in `noplaylistcreate`.")
        return True
    content = str(msg.content or "").strip()
    lowered = content.lower()
    session.updated_at = time.time()
    refresh_playlist_creation_timeout(key, msg.channel, session)

    if lowered in PLAYLIST_CREATION_CANCEL_WORDS:
        finish_playlist_creation_session(key)
        if session.append_to_existing:
            await msg.channel.send(
                f"Stopped adding songs. **{discord.utils.escape_markdown(session.name)}** remains saved."
            )
        else:
            await msg.channel.send("Playlist creation cancelled. Nothing was saved.")
        return True

    if session.step == "name":
        error = playlist_name_error(content, msg.author)
        if error:
            await msg.channel.send(f"{error} Send another name, or `cancel` to stop.")
            return True
        session.name = normalize_playlist_name(content)
        session.step = "urls"
        await msg.channel.send(
            f"Great. Send me YouTube URLs for **{discord.utils.escape_markdown(session.name)}**. "
            "You can send one or many links. Type `done` when finished or `cancel` to stop."
        )
        return True

    if session.step == "urls":
        if lowered in PLAYLIST_CREATION_FINISH_WORDS:
            if session.append_to_existing:
                finish_playlist_creation_session(key)
                await msg.channel.send(
                    f"Finished playlist **{discord.utils.escape_markdown(session.name)}** "
                    f"with {len(session.tracks)} track(s)."
                )
                return True
            if not session.tracks:
                await msg.channel.send("Add at least one YouTube URL first, or type `cancel` to stop.")
                return True
            try:
                playlist = save_new_playlist(session.name, msg.author, session.tracks)
            except Exception as exc:
                logger.error(f"Failed to save guided playlist: {exc}")
                await msg.channel.send("Could not save the playlist. Check output.log.")
                return True
            finish_playlist_creation_session(key)
            await msg.channel.send(playlist_created_message(playlist))
            return True
        urls = extract_youtube_urls(content)
        if not urls:
            await msg.channel.send(
                "That does not look like a YouTube URL. Send a YouTube link, `done` to finish, or `cancel` to stop."
            )
            return True
        if len(urls) > MAX_URLS_PER_MESSAGE:
            await msg.channel.send(
                f"You can send up to {MAX_URLS_PER_MESSAGE} YouTube link(s) at a time. "
                "Send fewer links, `done` to finish, or `cancel` to stop."
            )
            return True
        if len(session.tracks) >= MAX_PLAYLIST_TRACKS:
            finish_wording = "finish" if session.append_to_existing else "save it"
            await msg.channel.send(
                f"This playlist can hold up to {MAX_PLAYLIST_TRACKS} track(s). "
                f"Type `done` to {finish_wording} or `cancel` to stop."
            )
            return True
        added, failed, limit_hit = await add_urls_to_playlist_session(session, msg.author, urls)
        if session.append_to_existing and added:
            playlist = resolve_playlist_reference(session.playlist_id, msg.author, require_visible=False)
            if not playlist:
                await msg.channel.send("Could not find the saved playlist. Check output.log.")
                logger.error(f"Append playlist session lost playlist id {session.playlist_id}.")
                return True
            playlist["tracks"] = list(session.tracks)
            try:
                save_playlist(playlist)
            except Exception as exc:
                logger.error(f"Failed to save playlist add-more session: {exc}")
                await msg.channel.send("Could not save the playlist update. Check output.log.")
                return True
        parts = []
        if added:
            parts.append(f"Added {len(added)} track(s).")
        if failed:
            parts.append(f"Could not add {len(failed)} link(s).")
        if limit_hit or len(session.tracks) >= MAX_PLAYLIST_TRACKS:
            parts.append(
                f"This playlist can hold up to {MAX_PLAYLIST_TRACKS} track(s). "
                "Type `done` to finish or `cancel` to stop."
            )
        else:
            parts.append("Add another YouTube URL, or type `done`.")
        await msg.channel.send(" ".join(parts))
        return True
    return False

def after_played_track(error, video_id, channel):
    """Callback that runs after a track finishes playing or is stopped."""
    if error:
        logger.error(f"Error in playback: {error}")
    # Mark this track as played in history
    if video_id:
        client.played_tracks.add(video_id)
    # Schedule deletion of the file after the configured delay (if it exists in cache)
    if video_id in downloaded:
        delete_delay = client.download_delete_delay_seconds
        async def remove_file():
            await asyncio.sleep(delete_delay)
            # If the deletion task was canceled due to reuse, skip actual deletion
            if video_id not in client.deletion_tasks:
                return
            info = downloaded.get(video_id)
            if info:
                file_path = info.get('filepath')
                removed = remove_download_file(file_path, video_id=video_id, reason="delayed playback cleanup")
                downloaded.pop(video_id, None)
                save_downloads_metadata("delayed playback cleanup")
                append_runtime_audit_event("delayed-playback-cleanup", details={
                    "video_id": video_id,
                    "removed": removed,
                    "delay_seconds": delete_delay,
                    "path": file_path,
                })
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
        append_runtime_audit_event("delayed-playback-cleanup-scheduled", details={
            "video_id": video_id,
            "delay_seconds": delete_delay,
        })
        logger.info(f"Scheduled downloaded song cleanup for {video_id} in {delete_delay}s.")

    if client.auto_leave_disconnect_in_progress:
        logger.info("Playback callback suppressed because auto-leave is disconnecting.")
        return

    if (
        client.repeat_current_track
        and video_id
        and client.repeat_track_id == video_id
        and client.current_track_info
    ):
        replay_track = dict(client.current_track_info)
        queue.insert(0, replay_track)
        logger.info(f"Repeat-one queued current track again: {replay_track.get('title')} ({video_id})")

    # Proceed to the next track in queue
    asyncio.run_coroutine_threadsafe(play_next_channel(channel), client.loop)

async def play_next_channel(channel):
    """Plays the next track in the queue, if any."""
    if len(queue) > 0:
        track = queue.pop(0)
        try:
            await resolve_track_for_playback(track, requested_by=track.get("requested_by_user_id"))
            cached_file = None if user_has_group(track.get("requested_by_user_id"), "nodownload") else cached_file_for_track(track)
            speed = playback_speed_for_track(track)
            track["playback_speed"] = speed
            if cached_file:
                track["file"] = cached_file
                source = discord.FFmpegPCMAudio(cached_file, **ffmpeg_audio_options_for_speed(speed))
                player = discord.PCMVolumeTransformer(source, volume=client.volume)
            else:
                player, _ = await YTDLSource.from_url(track['webpage_url'], stream=True, speed=speed)
            guild = channel.guild
            client.current_track_id = track['id']
            # Start playback and provide callback
            voice = active_voice_client(guild)
            if voice is None:
                raise RuntimeError("No active voice client for queued playback.")
            voice.play(player, after=lambda e, vid=track['id']: after_played_track(e, vid, channel))
            client.currently_playing = True
            # Update current and last track info
            client.last_track_info = client.current_track_info
            client.current_track_info = track
            client.current_track_started_at = time.time()
            sync_repeat_for_started_track(track)
            await publish_now_playing(channel, track)
            logger.info(f"Started playing: {track['title']} ({track['id']})")
            # Add track to session history if not already recorded
            if track not in client.song_history:
                client.song_history.append(track)
        except Exception as e:
            logger.error(f"Failed to play next track: {e}")
            await channel.send("Failed to play the next track.")
            await clear_playback_tracking("play-next error")
            await update_bot_presence_idle(reason="play-next error", channel=channel)
    else:
        # Queue is empty
        logger.info("No more songs to play. Queue is now clear.")
        await clear_playback_tracking("queue empty")
        await update_bot_presence_idle(reason="queue empty", channel=channel)
        await channel.send("No more songs in queue.")

@client.event
async def on_ready():
    await update_bot_presence_idle(reason="startup")
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
        if not client.auto_leave_disconnect_in_progress:
            cancel_auto_leave_task("bot disconnected")
        cancel_alone_speed_reset_task("bot disconnected")
        client.current_voice_channel = None
        await clear_playback_tracking("bot disconnected")
        client.auto_leave_disconnect_in_progress = False
        reset_session_volume("bot disconnected")
        await update_bot_presence_idle(reason="bot disconnected")
        return
    if bot_id and member.id == bot_id and after.channel is not None:
        voice = active_voice_client(getattr(after.channel, "guild", None))
        if voice:
            apply_channel_volume_default(after.channel, "bot voice state update")
            logger.info(f"Synchronized bot voice channel to {getattr(after.channel, 'name', after.channel)} from voice state update.")
    else:
        voice = active_voice_client(getattr(getattr(after, "channel", None), "guild", None))
    voice_channel = getattr(voice, "channel", None)
    if voice and voice.is_connected() and voice_channel:
        if bot_is_alone_in_voice(voice_channel):
            schedule_auto_leave_if_needed(voice_channel)
            schedule_alone_speed_reset_if_needed(voice_channel)
        else:
            cancel_auto_leave_task("voice channel occupied")
            cancel_alone_speed_reset_task("voice channel occupied")

@client.event
async def on_message(msg):
    """On receiving a message in monitored channel, save quotes."""
    if await handle_playlist_creation_message(msg):
        return
    if QUOTES_ID and msg.channel == client.get_channel(QUOTES_ID):
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
    if await handle_debug_playback_reaction(reaction, user):
        return
    if await handle_config_reaction(reaction, user):
        return
    if await handle_help_reaction(reaction, user):
        return
    if await handle_voice_vote_reaction(reaction, user):
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
        if emoji == FAVORITE_REACTION:
            await handle_favorite_reaction(user, reaction.message)
        elif emoji == QUEUE_REACTION:
            await toggle_now_playing_queue(reaction.message)
        elif emoji == "▶️":
            # Skip to next track
            await request_voice_vote(user, reaction.message.channel, "skip", "skip the current track")
        elif emoji == REPEAT_REACTION:
            result = await handle_repeat_reaction(user, reaction.message.channel)
            if result != "Repeat-off vote started.":
                await reaction.message.channel.send(result)
        elif emoji == "⏸️":
            # Pause or resume
            voice = active_voice_client(getattr(reaction.message, "guild", None))
            if voice:
                if voice.is_playing():
                    voice.pause()
                    logger.info("Audio paused via reaction.")
                elif voice.is_paused():
                    voice.resume()
                    logger.info("Audio resumed via reaction.")
        elif emoji == "◀️":
            await request_voice_vote(user, reaction.message.channel, "previous", "replay the previous track")
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
favorites_group = app_commands.Group(name="favorites", description="play and manage per-user favorites")
usergroup_group = app_commands.Group(name="usergroup", description="admin user restriction groups")
config_group = app_commands.Group(name="config", description="admin runtime configuration panel")

@client.tree.command()
async def join(ctx):
    """Joins the voice channel that the user is currently in."""
    record_command(ctx)
    if ctx.user.voice:
        voice = active_voice_client(ctx.guild)
        target_channel = ctx.user.voice.channel
        try:
            if voice and voice.is_connected():
                if getattr(voice, "channel", None) == target_channel:
                    await ctx.response.send_message(f"Already in voice channel {target_channel.name}")
                    return
                if not is_user_admin(ctx.user):
                    await ctx.response.send_message("The bot is already in another voice channel.", ephemeral=True)
                    return
                await voice.move_to(target_channel)
                client.current_voice_channel = voice
            else:
                client.current_voice_channel = await target_channel.connect()
            apply_channel_volume_default(target_channel, "join command")
            cancel_auto_leave_task("joined voice")
            cancel_alone_speed_reset_task("joined voice")
            # Reset session history when joining a new voice channel
            client.song_history = []
            await ctx.response.send_message(f"Joined voice channel {target_channel.name}")
        except Exception as e:
            logger.error(f"Join error: {e}")
            await ctx.response.send_message(f"Unable to join voice channel {target_channel.name}")
    else:
        await ctx.response.send_message("You must be in a voice channel to use this command")

@app_commands.describe(
    channel_name="Voice channel name, exact or unique partial match",
    user="Join the voice channel this user is currently in",
)
@client.tree.command(name="adminjoin")
async def admin_join(ctx, channel_name: Optional[str] = None, user: Optional[discord.Member] = None):
    """Admin-only hidden utility to move/connect the bot by channel name or user's voice."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    target_channel = None
    if user:
        target_channel = getattr(getattr(user, "voice", None), "channel", None)
        if target_channel is None:
            await ctx.response.send_message("That user is not in a voice channel.", ephemeral=True)
            return
    elif channel_name:
        target_channel = find_voice_channel_by_name(ctx.guild, channel_name)
        if target_channel is None:
            await ctx.response.send_message("No exact or unique matching voice channel found.", ephemeral=True)
            return
    else:
        target_channel = getattr(getattr(ctx.user, "voice", None), "channel", None)
        if target_channel is None:
            await ctx.response.send_message("Provide `channel_name`, `user`, or join a voice channel yourself.", ephemeral=True)
            return
    await connect_or_move_to_voice_channel(ctx, target_channel, reason="adminjoin")

@config_group.command(name="show", description="Show an admin runtime config panel.")
async def config_show(ctx):
    """Shows reaction-toggleable runtime configuration."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    await ctx.response.send_message(config_panel_message())
    message = await ctx.original_response()
    client.config_panel_message_id = message.id
    client.config_panel_user_id = user_id_value(ctx.user)
    for emoji in CONFIG_REACTIONS:
        try:
            await message.add_reaction(emoji)
        except Exception as exc:
            logger.warning(f"Failed to add config reaction {emoji}: {exc}")
    logger.info(f"Config panel opened by {user_display(ctx.user)} ({user_id_value(ctx.user)}).")

@app_commands.describe(user="User to inspect")
@client.tree.command(name="userstats")
async def userstats(ctx, user: discord.Member):
    """Shows admin-only user stats across favorites, groups, playlists, and command memory."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    await ctx.response.send_message(user_stats_message(user), ephemeral=True)

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
                append_runtime_audit_event("clear-queue", actor=ctx.user, details={
                    "queue_count": len(client.queue_backup or []),
                    "delete_files": False,
                    "reason": "confirmation_timeout",
                })
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
                append_runtime_audit_event("clear-queue", actor=ctx.user, details={
                    "queue_count": len(client.queue_backup or []),
                    "delete_files": True,
                    "deleted_files": count,
                })
                logger.info(f"Queue cleared by admin (deleted {count} files from disk).")
            else:
                await ctx.followup.send("Queue cleared. Downloaded files retained.")
                append_runtime_audit_event("clear-queue", actor=ctx.user, details={
                    "queue_count": len(client.queue_backup or []),
                    "delete_files": False,
                    "reason": "admin_cancelled",
                })
                logger.info("Queue cleared by admin (files retained).")
    else:
        # Non-admin: just clear the queue, do not touch files
        await ctx.response.send_message("Queue cleared (downloaded files retained).")
        append_runtime_audit_event("clear-queue", actor=ctx.user, details={
            "queue_count": len(client.queue_backup or []),
            "delete_files": False,
            "reason": "non_admin",
        })
        logger.info("Queue cleared by user (no file deletion permitted).")

@client.tree.command()
async def skip(ctx):
    """Skips the currently playing track."""
    record_command(ctx)
    await request_voice_vote(ctx.user, ctx.channel, "skip", "skip the current track", ctx=ctx)

@app_commands.describe(
    url="YouTube URL, YouTube playlist URL, search term, or playlist:name",
    show_download_log="Show an editable download progress log for this play request",
    repeat=f"Repeat a single-track request; values above {MAX_PLAY_REPEAT_COUNT} enable repeat-one loop",
    speed=f"Playback speed from {MIN_PLAYBACK_SPEED:g} to {MAX_PLAYBACK_SPEED:g}; requires admin, playspeed group, or allow-all",
)
@client.tree.command()
async def play(
    ctx,
    url: str,
    show_download_log: Optional[bool] = False,
    repeat: Optional[int] = None,
    speed: Optional[float] = None,
):
    """Plays a YouTube video's audio, a YouTube playlist, or a search result."""
    record_command(ctx)
    await ctx.response.defer()
    url, repeat_count, repeat_loop, repeat_explicit = parse_play_repeat_request(url, repeat)
    url, playback_speed, speed_explicit, speed_error = parse_play_speed_request(url, speed)
    url, suffix_repeat_count, suffix_repeat_loop, suffix_repeat_explicit = parse_play_repeat_request(url, None)
    if suffix_repeat_explicit:
        repeat_count = suffix_repeat_count
        repeat_loop = suffix_repeat_loop
        repeat_explicit = True
    if repeat_explicit and not url:
        await ctx.followup.send("Provide a search term or YouTube link before `-repeat`.", ephemeral=True)
        return
    if speed_explicit and not url:
        await ctx.followup.send("Provide a search term or YouTube link before `--speed`.", ephemeral=True)
        return
    if speed_error:
        await ctx.followup.send(speed_error, ephemeral=True)
        return
    if speed_explicit and not can_use_play_speed(ctx.user):
        await ctx.followup.send("You do not have permission to use playback speed controls.", ephemeral=True)
        return
    if repeat_explicit and user_has_group(ctx.user, "norepeat"):
        await ctx.followup.send("You cannot use repeat because your account is in `norepeat`.", ephemeral=True)
        return
    if is_play_last_query(url):
        if repeat_explicit or speed_explicit:
            await ctx.followup.send("Repeat and speed are only supported for single-track YouTube/search play requests.", ephemeral=True)
            return
        await restore_last_session(ctx)
        return
    favorites_alias_user = parse_play_favorites_alias(url)
    if favorites_alias_user is not None:
        if repeat_explicit or speed_explicit:
            await ctx.followup.send("Repeat and speed are only supported for single-track YouTube/search play requests.", ephemeral=True)
            return
        await play_favorites_alias(ctx, favorites_alias_user)
        return
    playlist = resolve_playlist_reference(url, ctx.user)
    if playlist:
        if repeat_explicit or speed_explicit:
            await ctx.followup.send("Repeat and speed are only supported for single-track YouTube/search play requests.", ephemeral=True)
            return
        await play_playlist_now(ctx, playlist, "play")
        return
    if not client.currently_playing:
        repeat_queue_count = 0 if repeat_loop else max(0, repeat_count - 1)
        if repeat_queue_count and not await require_queue_room_for_count(ctx, repeat_queue_count):
            return
        debug_report = await create_debug_playback_message(ctx, "play", force=bool(show_download_log))
        await append_debug_playback_event(debug_report, "checking voice connection", stage="voice-check", force=True)
        # Ensure we're connected to a voice channel before creating the player
        voice = active_voice_client(ctx.guild)
        if voice is None or not voice.is_connected():
            if ctx.user.voice and ctx.user.voice.channel:
                try:
                    voice = await ctx.user.voice.channel.connect()
                    client.current_voice_channel = voice
                    apply_channel_volume_default(ctx.user.voice.channel, "play join")
                    cancel_auto_leave_task("play joined voice")
                    cancel_alone_speed_reset_task("play joined voice")
                    client.song_history = []  # reset history for new session
                    await append_debug_playback_event(
                        debug_report,
                        f"joined voice channel {ctx.user.voice.channel.name}",
                        stage="voice-ready",
                        force=True,
                    )
                    if not debug_report:
                        await ctx.followup.send(f"Joined voice channel {ctx.user.voice.channel.name}")
                except Exception as e:
                    logger.error(f"Voice connection failed: {e}")
                    await finish_debug_playback_message(debug_report, status="error", error=str(e))
                    await ctx.followup.send("Couldn't join voice channel.")
                    return
            else:
                await finish_debug_playback_message(debug_report, status="error", error="user is not in a voice channel")
                await ctx.followup.send("You need to join a voice channel first.")
                return
        else:
            client.current_voice_channel = voice
            if not await require_voice_control(ctx, "start playback"):
                await finish_debug_playback_message(debug_report, status="error", error="voice control denied")
                return
            await append_debug_playback_event(debug_report, "using existing voice connection", stage="voice-ready", force=True)
        try:
            suggestion = record_suggestion(ctx, "play", url)
            tracks = await fetch_media_tracks(url, requested_by=ctx.user, debug_report=debug_report)
            track = tracks[0]
            update_suggestion(suggestion, track)
            if track.get("youtube_playlist_id"):
                if repeat_explicit or speed_explicit:
                    await finish_debug_playback_message(debug_report, status="error", error="repeat or speed requested for playlist URL")
                    await ctx.followup.send("Repeat and speed are only supported for single-track YouTube/search play requests.", ephemeral=True)
                    return
                await play_youtube_playlist_tracks(ctx, voice, tracks, "play", debug_report=debug_report)
                if debug_report:
                    debug_report.stage = "playing"
                    await finish_debug_playback_message(debug_report)
                return
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
                    await finish_debug_playback_message(debug_report, status="error", error="large download confirmation timed out")
                    await ctx.followup.send("Confirmation timed out. Cancelling the play request.")
                    return
                if str(reaction.emoji) == "👍":
                    # Admin confirmed download: fetch again with download (this time no 'needs_confirm')
                    track = await fetch_track(track['webpage_url'], requested_by=ctx.user, debug_report=debug_report)
                    update_suggestion(suggestion, track)
                else:
                    await finish_debug_playback_message(debug_report, status="error", error="large download cancelled by user")
                    await ctx.followup.send("Download canceled.")
                    return
            if speed_explicit:
                track["playback_speed"] = playback_speed
            if repeat_loop:
                track["repeat_loop"] = True
            await append_debug_playback_event(debug_report, "building ffmpeg audio source", stage="ffmpeg", force=True)
            player = await build_audio_player(track)
            voice.play(player, after=lambda e, vid=track['id']: after_played_track(e, vid, ctx.channel))
            client.current_track_id = track['id']
            client.currently_playing = True
            client.last_track_info = client.current_track_info
            client.current_track_info = track
            client.current_track_started_at = time.time()
            sync_repeat_for_started_track(track)
            client.song_history.append(track)
            await publish_now_playing(
                ctx.channel,
                track,
                send_message=ctx.followup.send,
                acknowledge=ctx.followup.send,
            )
            if repeat_explicit:
                queue_repeat_copies(track, repeat_count, already_started=True)
                await announce_repeat_request(ctx, repeat_count, repeat_loop, started=True)
            await maybe_send_speed_notice(ctx, playback_speed, speed_explicit)
            await append_debug_playback_event(debug_report, "playback started", stage="playing", force=True)
            logger.info(f"Playing now: {track['title']} ({track['id']})")
            if debug_report:
                debug_report.stage = "playing"
                await finish_debug_playback_message(debug_report)
        except Exception as e:
            logger.error(f"/play error: {e}")
            await finish_debug_playback_message(debug_report, status="error", error=str(e))
            await ctx.followup.send(playback_error_message(e, ctx.user), ephemeral=True)
    else:
        # If something is already playing, add the requested song to the queue
        repeat_queue_count = 1 if repeat_loop else repeat_count
        if not await require_queue_room_for_count(ctx, repeat_queue_count):
            return
        debug_report = await create_debug_playback_message(ctx, "play", force=bool(show_download_log))
        try:
            suggestion = record_suggestion(ctx, "play", url)
            tracks = await fetch_media_tracks(url, requested_by=ctx.user, debug_report=debug_report)
            track = tracks[0]
            update_suggestion(suggestion, track)
            if track.get("youtube_playlist_id"):
                if repeat_explicit or speed_explicit:
                    await finish_debug_playback_message(debug_report, status="error", error="repeat or speed requested for playlist URL")
                    await ctx.followup.send("Repeat and speed are only supported for single-track YouTube/search play requests.", ephemeral=True)
                    return
                await enqueue_youtube_playlist_tracks(ctx, tracks, "play")
                if debug_report:
                    debug_report.stage = "queued"
                    await finish_debug_playback_message(debug_report)
                return
            if track.get('needs_confirm'):
                # Cannot queue a large download without confirmation; instruct admin to use /play
                filesize_mb = track.get('filesize', 0) / (1024 * 1024)
                await finish_debug_playback_message(debug_report, status="error", error="large download requires /play confirmation")
                await ctx.followup.send(f"Track **{track['title']}** (~{filesize_mb:.1f} MB) is too large to queue without confirmation. Please use /play to confirm.")
                return
            if speed_explicit:
                track["playback_speed"] = playback_speed
            if repeat_explicit:
                if repeat_loop:
                    repeated = clone_track_for_repeat(track, repeat_loop=True)
                    queue.append(repeated)
                    client.song_history.append(repeated)
                    logger.info(f"Queued repeat-loop track: {track.get('title')} ({track.get('id')})")
                else:
                    queue_repeat_copies(track, repeat_count)
                await announce_repeat_request(ctx, repeat_count, repeat_loop, started=False)
                if not repeat_loop and repeat_count <= 1:
                    title = discord.utils.escape_markdown(str(track.get('title') or 'Unknown title'))
                    await ctx.followup.send(f"Added to queue: {title} ({track.get('id', '')})")
                await maybe_send_speed_notice(ctx, playback_speed, speed_explicit)
                if debug_report:
                    debug_report.stage = "queued"
                    await finish_debug_playback_message(debug_report)
                return
            await enqueue_track_with_playlist_prompt(ctx, track, "play")
            await maybe_send_speed_notice(ctx, playback_speed, speed_explicit)
            if debug_report:
                debug_report.stage = "queued"
                await finish_debug_playback_message(debug_report)
        except Exception as e:
            logger.error(f"/play queue error: {e}")
            await finish_debug_playback_message(debug_report, status="error", error=str(e))
            await ctx.followup.send(playback_error_message(e, ctx.user), ephemeral=True)

@app_commands.describe(query="YouTube URL, YouTube playlist URL, or search term")
@client.tree.command()
async def playtop(ctx, *, query: str):
    """Adds a song to the top of the queue (plays next)."""
    record_command(ctx)
    if client.currently_playing and not await require_not_restricted(ctx, "noqueueskip", "add songs to the front of the queue"):
        return
    await ctx.response.defer()
    if not client.currently_playing:
        # Nothing playing, so this will play immediately (similar to /play when queue empty)
        voice = active_voice_client(ctx.guild)
        if voice is None or not voice.is_connected():
            if ctx.user.voice and ctx.user.voice.channel:
                try:
                    voice = await ctx.user.voice.channel.connect()
                    client.current_voice_channel = voice
                    apply_channel_volume_default(ctx.user.voice.channel, "playtop join")
                    cancel_auto_leave_task("playtop joined voice")
                    cancel_alone_speed_reset_task("playtop joined voice")
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
            tracks = await fetch_media_tracks(query, requested_by=ctx.user)
            track = tracks[0]
            update_suggestion(suggestion, track)
            if track.get("youtube_playlist_id"):
                await play_youtube_playlist_tracks(ctx, voice, tracks, "playtop")
                return
            if track.get('needs_confirm'):
                filesize_mb = track.get('filesize', 0) / (1024 * 1024)
                await ctx.followup.send(f"Track **{track['title']}** (~{filesize_mb:.1f} MB) is too large to play without confirmation. Use /play for this track.")
                return
            player = await build_audio_player(track)
            voice.play(player, after=lambda e, vid=track['id']: after_played_track(e, vid, ctx.channel))
            client.current_track_id = track['id']
            client.currently_playing = True
            client.last_track_info = client.current_track_info
            client.current_track_info = track
            client.current_track_started_at = time.time()
            sync_repeat_for_started_track(track)
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
            await ctx.followup.send(playback_error_message(e, ctx.user), ephemeral=True)
    else:
        # If currently playing, queue this track to be next
        if not await require_queue_room(ctx):
            return
        try:
            suggestion = record_suggestion(ctx, "playtop", query)
            tracks = await fetch_media_tracks(query, requested_by=ctx.user)
            track = tracks[0]
            update_suggestion(suggestion, track)
            if track.get("youtube_playlist_id"):
                await enqueue_youtube_playlist_tracks(ctx, tracks, "playtop", front=True)
                return
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
            await ctx.followup.send(playback_error_message(e, ctx.user), ephemeral=True)

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
        tracks = await fetch_media_tracks(query, requested_by=ctx.user)
        track = tracks[0]
        update_suggestion(suggestion, track)
        if track.get("youtube_playlist_id"):
            await enqueue_youtube_playlist_tracks(ctx, tracks, command_name)
            return
        if track.get('needs_confirm'):
            filesize_mb = track.get('filesize', 0) / (1024 * 1024)
            await ctx.followup.send(f"Track **{track['title']}** (~{filesize_mb:.1f} MB) requires confirmation to download. Use /play instead.")
            return
        await enqueue_track_with_playlist_prompt(ctx, track, command_name)
    except Exception as e:
        logger.error(f"/{command_name} error: {e}")
        await ctx.followup.send(playback_error_message(e, ctx.user), ephemeral=True)

@app_commands.describe(query="YouTube URL, YouTube playlist URL, search term, or playlist:name")
@client.tree.command(name="enqueue")
async def enqueue_cmd(ctx, *, query: str):
    """Enqueues a song to the queue (alias: /q)."""
    await enqueue_track(ctx, query, "enqueue")

@app_commands.describe(query="YouTube URL, YouTube playlist URL, search term, or playlist:name")
@client.tree.command(name="q")
async def q_cmd(ctx, *, query: str):
    """Alias of /enqueue."""
    await enqueue_track(ctx, query, "q")

async def queue_first(ctx, target: str, command_name: str):
    """Move a queued track to the front so it plays next."""
    record_command(ctx)
    if not await require_not_restricted(ctx, "noqueueskip", "reorder the queue"):
        return
    if not await require_voice_control(ctx, "reorder the queue"):
        return
    playlist = resolve_playlist_reference(target, ctx.user)
    if playlist:
        await add_playlist_to_queue_front(ctx, playlist)
        return
    if is_youtube_playlist_url(target):
        await ctx.response.defer()
        try:
            tracks = await fetch_youtube_playlist_tracks(target, requested_by=ctx.user)
            await enqueue_youtube_playlist_tracks(ctx, tracks or [], command_name, front=True)
        except Exception as exc:
            logger.error(f"/{command_name} YouTube playlist error: {exc}")
            await ctx.followup.send("Failed to read that YouTube playlist.", ephemeral=True)
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

@app_commands.describe(target="1-based queue position, playlist name, or YouTube playlist URL to move so it plays next")
@client.tree.command(name="queuefirst")
async def queuefirst_cmd(ctx, target: str):
    """Moves a queued song to the front of the queue."""
    await queue_first(ctx, target, "queuefirst")

@app_commands.describe(target="1-based queue position, playlist name, or YouTube playlist URL to move so it plays next")
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

@app_commands.describe(user="User whose public favorites should play; omit for your own")
@favorites_group.command(name="play", description="Play your favorites, or another user's public favorites.")
async def favorites_play(ctx, user: Optional[discord.Member] = None):
    record_command(ctx)
    await ctx.response.defer()
    target_user = user or ctx.user
    playlist = favorites_playlist_for_user(target_user, create=user_id_value(target_user) == user_id_value(ctx.user))
    if not playlist or not playlist.get("tracks"):
        await ctx.followup.send("No favorites are saved yet.", ephemeral=True)
        return
    await play_favorites_playlist(ctx, playlist, "favorites play")

@app_commands.describe(visibility="public lets other users play your favorites; private hides them from normal users")
@app_commands.choices(visibility=[
    app_commands.Choice(name="private", value="private"),
    app_commands.Choice(name="public", value="public"),
])
@favorites_group.command(name="privacy", description="Set your favorites visibility.")
async def favorites_privacy(ctx, visibility: str):
    record_command(ctx)
    playlist = favorites_playlist_for_user(ctx.user, create=True)
    playlist["visibility"] = visibility
    playlist["updated_at"] = time.time()
    save_playlist(playlist)
    await ctx.response.send_message(
        f"Favorites visibility set to `{visibility}`. This is a social bot setting, not strong secrecy.",
        ephemeral=True,
    )
    logger.info(f"Favorites privacy set to {visibility} by {user_display(ctx.user)} ({user_id_value(ctx.user)}).")

@app_commands.describe(user="User whose public favorites should be listed; omit for your own")
@favorites_group.command(name="list", description="List your favorites, or another user's public favorites.")
async def favorites_list(ctx, user: Optional[discord.Member] = None):
    record_command(ctx)
    target_user = user or ctx.user
    playlist = favorites_playlist_for_user(target_user, create=user_id_value(target_user) == user_id_value(ctx.user))
    if not playlist:
        await ctx.response.send_message("No favorites are saved yet.", ephemeral=True)
        return
    if user_id_value(target_user) != user_id_value(ctx.user) and not is_playlist_public(playlist):
        await ctx.response.send_message("Those favorites are private.", ephemeral=True)
        return
    await ctx.response.send_message(favorites_list_message(playlist), ephemeral=True)

@favorites_group.command(name="status", description="Show your favorites visibility, count, cache, and groups.")
async def favorites_status(ctx):
    record_command(ctx)
    await ctx.response.send_message(favorites_status_message(ctx.user), ephemeral=True)

@app_commands.describe(user="User whose favorite cache eligibility should change", enabled="Whether favorites cache may cache this user's favorites")
@favorites_group.command(name="cacheuser", description="Admin-only favorite cache allow/deny for one user.")
async def favorites_cacheuser(ctx, user: discord.Member, enabled: bool):
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    entry = user_permissions_entry(user, create=True)
    entry["favorite_cache_enabled"] = bool(enabled)
    entry["updated_at"] = time.time()
    entry["updated_by_user_id"] = user_id_value(ctx.user)
    entry["updated_by_discord_name"] = user_display(ctx.user)
    save_user_permissions_config()
    append_runtime_audit_event("favorites-cache-user", actor=ctx.user, details={
        "target_user_id": user_id_value(user),
        "target_discord_name": user_display(user),
        "enabled": bool(enabled),
    })
    state = "allowed" if enabled else "blocked"
    await ctx.response.send_message(f"Favorites cache is now **{state}** for **{discord.utils.escape_markdown(user_display(user))}**.", ephemeral=True)
    logger.info(f"Favorites cache eligibility for {user_display(user)} ({user_id_value(user)}) set to {enabled}.")

@app_commands.describe(
    enabled="Enable or disable global favorites autocache",
    max_gb="Global favorites cache cap in GiB; max 6",
    per_user_tracks="How many favorites per user may be cached; max 100",
)
@favorites_group.command(name="cacheglobal", description="Admin-only global favorites autocache policy.")
async def favorites_cacheglobal(ctx, enabled: bool, max_gb: Optional[float] = None, per_user_tracks: Optional[int] = None):
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    if max_gb is not None and max_gb < 0:
        await ctx.response.send_message("max_gb must be zero or higher.", ephemeral=True)
        return
    if per_user_tracks is not None and per_user_tracks < 0:
        await ctx.response.send_message("per_user_tracks must be zero or higher.", ephemeral=True)
        return
    set_favorites_cache_policy(enabled, max_gb=max_gb, per_user_tracks=per_user_tracks)
    policy = favorites_cache_policy()
    append_runtime_audit_event("favorites-cache-global", actor=ctx.user, details=policy)
    await ctx.response.send_message(
        "Favorites cache policy updated: "
        f"`{'enabled' if policy.get('enabled') else 'disabled'}`, "
        f"cap `{human_bytes(policy.get('max_bytes'))}`, "
        f"`{policy.get('per_user_tracks')}` track(s)/user.",
        ephemeral=True,
    )
    logger.info(f"Favorites cache global policy updated by {user_display(ctx.user)}: {policy}")

@client.tree.command(name="permissions")
async def permissions_cmd(ctx):
    """Shows the caller's user restriction groups."""
    record_command(ctx)
    await ctx.response.send_message(f"Your permissions: {permissions_summary_for(ctx.user)}.", ephemeral=True)

@app_commands.describe(user="User to inspect")
@usergroup_group.command(name="list", description="Admin-only list of a user's restriction groups.")
async def usergroup_list(ctx, user: discord.Member):
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    await ctx.response.send_message(
        f"Groups for **{discord.utils.escape_markdown(user_display(user))}**: {permissions_summary_for(user)}.",
        ephemeral=True,
    )

@app_commands.describe(user="User to restrict", group="Restriction group to add")
@app_commands.choices(group=[
    app_commands.Choice(name="nodownload", value="nodownload"),
    app_commands.Choice(name="novolumechange", value="novolumechange"),
    app_commands.Choice(name="noplaylistcreate", value="noplaylistcreate"),
    app_commands.Choice(name="noqueueskip", value="noqueueskip"),
    app_commands.Choice(name="noskip", value="noskip"),
    app_commands.Choice(name="norepeat", value="norepeat"),
    app_commands.Choice(name="playspeed", value="playspeed"),
])
@usergroup_group.command(name="add", description="Admin-only add a user restriction group.")
async def usergroup_add(ctx, user: discord.Member, group: str):
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    add_user_group(user, group, ctx.user)
    await ctx.response.send_message(
        f"Added `{group}` to **{discord.utils.escape_markdown(user_display(user))}**.",
        ephemeral=True,
    )
    logger.info(f"User group added: {group} -> {user_display(user)} ({user_id_value(user)}) by {user_display(ctx.user)}.")

@app_commands.describe(user="User to update", group="Restriction group to remove")
@app_commands.choices(group=[
    app_commands.Choice(name="nodownload", value="nodownload"),
    app_commands.Choice(name="novolumechange", value="novolumechange"),
    app_commands.Choice(name="noplaylistcreate", value="noplaylistcreate"),
    app_commands.Choice(name="noqueueskip", value="noqueueskip"),
    app_commands.Choice(name="noskip", value="noskip"),
    app_commands.Choice(name="norepeat", value="norepeat"),
    app_commands.Choice(name="playspeed", value="playspeed"),
])
@usergroup_group.command(name="remove", description="Admin-only remove a user restriction group.")
async def usergroup_remove(ctx, user: discord.Member, group: str):
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    remove_user_group(user, group, ctx.user)
    await ctx.response.send_message(
        f"Removed `{group}` from **{discord.utils.escape_markdown(user_display(user))}**.",
        ephemeral=True,
    )
    logger.info(f"User group removed: {group} -> {user_display(user)} ({user_id_value(user)}) by {user_display(ctx.user)}.")

@playlist_group.command(name="list", description="Browse your playlists and visible public playlists.")
async def playlist_list(ctx):
    record_command(ctx)
    pages = playlist_list_pages_for(ctx.user)
    await send_paged_playlist_message(ctx, pages)

@app_commands.describe(name="Playlist name", visibility="private, public, current, currentqueue, or jono")
@app_commands.choices(visibility=[
    app_commands.Choice(name="private", value="private"),
    app_commands.Choice(name="public", value="public"),
    app_commands.Choice(name="current", value="current"),
    app_commands.Choice(name="currentqueue", value="currentqueue"),
    app_commands.Choice(name="jono", value="jono"),
])
@playlist_group.command(name="new", description="Create a playlist.")
async def playlist_new(ctx, name: Optional[str] = None, visibility: Optional[str] = None):
    record_command(ctx)
    if not await require_not_restricted(ctx, "noplaylistcreate", "create playlists"):
        return
    mode = str(visibility or "private").lower()
    if name is None:
        await start_playlist_creation_flow(ctx)
        return
    if mode in PLAYLIST_QUEUE_IMPORT_MODES:
        await create_playlist_from_queue(ctx, name)
        return
    safe_name = normalize_playlist_name(name)
    error = playlist_name_error(safe_name, ctx.user)
    if error:
        await ctx.response.send_message(error, ephemeral=True)
        return
    if mode not in {"private", "public"}:
        await ctx.response.send_message(
            "Use `private`, `public`, `current`, `currentqueue`, or `jono`. See `/help topic:playlist command:new`.",
            ephemeral=True,
        )
        return
    try:
        playlist = save_new_playlist(safe_name, ctx.user, [], mode)
    except Exception as exc:
        logger.error(f"Failed to create playlist: {exc}")
        await ctx.response.send_message("Could not save the playlist. Check output.log.", ephemeral=True)
        return
    await ctx.response.send_message(
        f"Created {playlist['visibility']} playlist **{discord.utils.escape_markdown(playlist['name'])}** (`{playlist['id']}`). "
        f"It is empty. Add songs with `/playlist add {playlist['name']} url <youtube-url>`."
    )

async def show_playlist_details(ctx, name: str, flags: Optional[str] = None, *, require_edit: bool = False):
    record_command(ctx)
    parsed_flags = parse_playlist_flags(flags)
    playlist = resolve_playlist_reference(name, ctx.user)
    if not playlist:
        await ctx.response.send_message(
            "Playlist not found or not visible to you. Try `/playlist list` or `/help topic:playlist command:list`.",
            ephemeral=True,
        )
        return
    if require_edit and not can_edit_playlist(ctx.user, playlist):
        await ctx.response.send_message("You can view this playlist, but you cannot edit it.", ephemeral=True)
        return
    if require_edit:
        if not await confirm_admin_foreign_playlist(ctx, playlist, "playlist edit", parsed_flags):
            await safe_interaction_send(ctx, "Playlist edit cancelled.", ephemeral=True)
            return
    await send_paged_playlist_message(ctx, playlist_detail_pages(playlist))

@app_commands.describe(name="Playlist name, id, or playlist:name", flags="Optional flag: -force")
@playlist_group.command(name="edit", description="Show editable playlist details.")
async def playlist_edit(ctx, name: str, flags: Optional[str] = None):
    await show_playlist_details(ctx, name, flags, require_edit=True)

@app_commands.describe(playlist="Playlist name, id, or playlist:name")
@playlist_group.command(name="show", description="Show playlist details.")
async def playlist_show(ctx, playlist: str):
    await show_playlist_details(ctx, playlist)

@app_commands.describe(playlist="Playlist name, id, or playlist:name")
@playlist_group.command(name="play", description="Play or queue a saved playlist.")
async def playlist_play(ctx, playlist: str):
    record_command(ctx)
    await ctx.response.defer()
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.followup.send("Playlist not found or not visible to you. Try `/playlist list`.", ephemeral=True)
        return
    await play_playlist_now(ctx, target, "playlist play")

@app_commands.describe(
    playlist="Playlist name, id, or playlist:name",
    source="Add the current song, a queued song, or a YouTube URL",
    queue_position="Queue position when source is queue",
    url="YouTube URL when source is url",
)
@app_commands.choices(source=[
    app_commands.Choice(name="current", value="current"),
    app_commands.Choice(name="queue", value="queue"),
    app_commands.Choice(name="url", value="url"),
])
@playlist_group.command(name="add", description="Add current, queued, or URL song to a playlist.")
async def playlist_add(ctx, playlist: str, source: str, queue_position: Optional[int] = None, url: Optional[str] = None):
    record_command(ctx)
    await ctx.response.defer(ephemeral=True)
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.followup.send("Playlist not found or not visible to you. Try `/playlist list`.", ephemeral=True)
        return
    if not can_edit_playlist(ctx.user, target):
        await ctx.followup.send("You do not have permission to edit that playlist.", ephemeral=True)
        return
    tracks_to_add = []
    if source == "current":
        track = client.current_track_info
        if not track:
            await ctx.followup.send("No song is currently playing.", ephemeral=True)
            return
        tracks_to_add = [track]
    elif source == "queue":
        if queue_position is None or queue_position < 1 or queue_position > len(queue):
            await ctx.followup.send("Provide a valid queue position. See `/help topic:playlist command:add`.", ephemeral=True)
            return
        track = queue[queue_position - 1]
        tracks_to_add = [track]
    elif source == "url":
        if not url:
            await ctx.followup.send("Send a YouTube URL with `source:url`. See `/help topic:playlist command:add`.", ephemeral=True)
            return
        urls = extract_youtube_urls(url)
        if not urls:
            await ctx.followup.send("That does not look like a YouTube URL.", ephemeral=True)
            return
        url = urls[0]
        try:
            tracks_to_add = await fetch_media_tracks(url, requested_by=ctx.user)
        except Exception as exc:
            logger.warning(f"Failed to add playlist URL {url}: {exc}")
            await ctx.followup.send("Could not read that YouTube URL. Try another link.", ephemeral=True)
            return
        if any(track.get("needs_confirm") for track in tracks_to_add):
            await ctx.followup.send("That track needs admin confirmation before download, so it was not added.", ephemeral=True)
            return
    else:
        await ctx.followup.send("Use source `current`, `queue`, or `url`.", ephemeral=True)
        return
    remaining_slots = max(0, MAX_PLAYLIST_TRACKS - len(target.get("tracks", [])))
    if not remaining_slots:
        await ctx.followup.send(f"That playlist already has the maximum {MAX_PLAYLIST_TRACKS} track(s).", ephemeral=True)
        return
    tracks_to_add = tracks_to_add[:remaining_slots]
    target.setdefault("tracks", []).extend(playlist_track_from_track(track, ctx.user) for track in tracks_to_add)
    try:
        save_playlist(target)
    except Exception as exc:
        logger.error(f"Failed to save playlist after add: {exc}")
        await ctx.followup.send("Could not save the playlist. Check output.log.", ephemeral=True)
        return
    first_title = discord.utils.escape_markdown(str(tracks_to_add[0].get("title") or "Unknown title"))
    added_label = f"**{first_title}**" if len(tracks_to_add) == 1 else f"{len(tracks_to_add)} track(s), starting with **{first_title}**"
    await ctx.followup.send(
        f"Added {added_label} to **{discord.utils.escape_markdown(target['name'])}**. "
        "Track metadata is saved locally and will stream unless cached later.",
        ephemeral=True,
    )
    logger.info(f"Added {len(tracks_to_add)} track(s) to playlist {target['name']} ({target['id']}) via source {source}.")

@app_commands.describe(
    source="Source to fill from",
    playlist="Playlist name, id, or playlist:name",
)
@app_commands.choices(source=[
    app_commands.Choice(name="current", value="current"),
])
@playlist_group.command(name="fill", description="Add queued songs missing from a playlist.")
async def playlist_fill(ctx, source: str, playlist: str):
    record_command(ctx)
    await ctx.response.defer(ephemeral=True)
    if source != "current":
        await ctx.followup.send("Use `/playlist fill current <playlist>`.", ephemeral=True)
        return
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.followup.send("Playlist not found or not visible to you. Try `/playlist list`.", ephemeral=True)
        return
    if not can_edit_playlist(ctx.user, target):
        await ctx.followup.send("You do not have permission to edit that playlist.", ephemeral=True)
        return
    if not queue:
        await ctx.followup.send("The queue is empty. Add songs to the queue first, then try `/playlist fill current <playlist>`.", ephemeral=True)
        return
    additions, skipped_duplicates, skipped_missing = queue_tracks_missing_from_playlist(target, ctx.user)
    if not additions:
        details = []
        if skipped_duplicates:
            details.append(f"{skipped_duplicates} already in the playlist")
        if skipped_missing:
            details.append(f"{skipped_missing} missing YouTube metadata")
        reason = f" ({', '.join(details)})" if details else ""
        await ctx.followup.send(f"No new queued songs were added{reason}.", ephemeral=True)
        return
    target.setdefault("tracks", []).extend(additions)
    try:
        save_playlist(target)
    except Exception as exc:
        logger.error(f"Failed to save playlist after fill: {exc}")
        await ctx.followup.send("Could not save the playlist. Check output.log.", ephemeral=True)
        return
    details = []
    if skipped_duplicates:
        details.append(f"skipped {skipped_duplicates} duplicate(s)")
    if skipped_missing:
        details.append(f"skipped {skipped_missing} queue item(s) without YouTube metadata")
    suffix = f" ({'; '.join(details)})." if details else "."
    await ctx.followup.send(
        f"Added {len(additions)} queued song(s) to **{discord.utils.escape_markdown(target['name'])}**{suffix} "
        "These tracks are saved in playlist metadata and will stream unless cached later.",
        ephemeral=True,
    )
    logger.info(
        f"Filled playlist from current queue: {target['name']} ({target['id']}) "
        f"added={len(additions)} duplicates={skipped_duplicates} missing={skipped_missing}"
    )

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

async def remove_playlist_command(ctx, playlist: str, flags: Optional[str] = None):
    record_command(ctx)
    parsed_flags = parse_playlist_flags(flags)
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.response.send_message(
            "Playlist not found or not visible to you. Try `/playlist list` or `/help topic:playlist command:remove`.",
            ephemeral=True,
        )
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

@app_commands.describe(playlist="Playlist name, id, or playlist:name", flags="Optional flags: -now -force")
@playlist_group.command(name="remove", description="Delete a playlist with a rescue window.")
async def playlist_remove(ctx, playlist: str, flags: Optional[str] = None):
    await remove_playlist_command(ctx, playlist, flags)

@app_commands.describe(playlist="Playlist name, id, or playlist:name", flags="Optional flags: -now -force")
@playlist_group.command(name="delete", description="Alias for removing a playlist.")
async def playlist_delete(ctx, playlist: str, flags: Optional[str] = None):
    await remove_playlist_command(ctx, playlist, flags)

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

@app_commands.describe(playlist="Playlist name, id, or playlist:name", new_name="New playlist name", flags="Optional flag: -force")
@playlist_group.command(name="rename", description="Rename a playlist.")
async def playlist_rename(ctx, playlist: str, new_name: str, flags: Optional[str] = None):
    record_command(ctx)
    parsed_flags = parse_playlist_flags(flags)
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.response.send_message("Playlist not found or not visible to you. Try `/playlist list`.", ephemeral=True)
        return
    if not can_manage_playlist(ctx.user, target):
        await ctx.response.send_message("Only the owner or an admin can rename playlists.", ephemeral=True)
        return
    error = playlist_name_error(new_name, ctx.user)
    if error:
        await ctx.response.send_message(error, ephemeral=True)
        return
    if not await confirm_admin_foreign_playlist(ctx, target, "playlist rename", parsed_flags):
        await safe_interaction_send(ctx, "Playlist rename cancelled.", ephemeral=True)
        return
    old_name = target.get("name", "playlist")
    target["name"] = normalize_playlist_name(new_name)
    try:
        save_playlist(target)
    except Exception as exc:
        logger.error(f"Failed to rename playlist {target.get('id')}: {exc}")
        await safe_interaction_send(ctx, "Could not save the rename. Check output.log.", ephemeral=True)
        return
    await safe_interaction_send(
        ctx,
        f"Renamed **{discord.utils.escape_markdown(str(old_name))}** to **{discord.utils.escape_markdown(target['name'])}**.",
    )
    logger.info(f"Playlist renamed: {old_name} -> {target['name']} ({target.get('id')})")

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

@app_commands.describe(playlist="Playlist name, id, or playlist:name", mode="follow_global, streaming, bounded, or keep_cached")
@app_commands.choices(mode=[
    app_commands.Choice(name="follow_global", value="follow_global"),
    app_commands.Choice(name="streaming", value="streaming"),
    app_commands.Choice(name="bounded", value="bounded"),
    app_commands.Choice(name="keep_cached", value="keep_cached"),
])
@playlist_group.command(name="cachemode", description="Set a playlist's cache behavior.")
async def playlist_cachemode(ctx, playlist: str, mode: str):
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    target = resolve_playlist_reference(playlist, ctx.user)
    if not target:
        await ctx.response.send_message("Playlist not found.", ephemeral=True)
        return
    if mode not in PLAYLIST_CACHE_MODES:
        await ctx.response.send_message("Use follow_global, streaming, bounded, or keep_cached.", ephemeral=True)
        return
    target["cache_mode"] = mode
    save_playlist(target)
    append_runtime_audit_event("playlist-cache-mode", actor=ctx.user, details={
        "playlist_id": target.get("id"),
        "playlist_name": target.get("name"),
        "mode": mode,
    })
    await ctx.response.send_message(
        f"Playlist **{discord.utils.escape_markdown(target['name'])}** cache mode set to `{mode}`. "
        f"Effective mode is `{effective_playlist_cache_mode(target)}`.",
        ephemeral=True,
    )
    logger.info(f"Playlist cache mode changed: {target['name']} ({target['id']}) -> {mode}")

@app_commands.describe(mode="streaming, bounded, or keep_cached", force="Force all playlists to use this global mode")
@app_commands.choices(mode=[
    app_commands.Choice(name="streaming", value="streaming"),
    app_commands.Choice(name="bounded", value="bounded"),
    app_commands.Choice(name="keep_cached", value="keep_cached"),
])
@playlist_group.command(name="cacheglobal", description="Set the global playlist cache behavior.")
async def playlist_cacheglobal(ctx, mode: str, force: Optional[bool] = None):
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    if mode not in GLOBAL_PLAYLIST_CACHE_MODES:
        await ctx.response.send_message("Use streaming, bounded, or keep_cached.", ephemeral=True)
        return
    old_mode = client.playlist_cache_default_mode
    old_force = client.force_global_playlist_cache_mode
    client.playlist_cache_default_mode = mode
    if force is not None:
        client.force_global_playlist_cache_mode = bool(force)
    try:
        save_playlist_cache_policy()
    except Exception as exc:
        client.playlist_cache_default_mode = old_mode
        client.force_global_playlist_cache_mode = old_force
        logger.error(f"Failed to save playlist cache policy: {exc}")
        await ctx.response.send_message("Could not save playlist cache policy. Check output.log.", ephemeral=True)
        return
    await ctx.response.send_message(
        f"Global playlist cache mode changed `{old_mode}` -> `{mode}`. "
        f"Force global: `{old_force}` -> `{client.force_global_playlist_cache_mode}`.",
        ephemeral=True,
    )
    append_runtime_audit_event("playlist-cache-global", actor=ctx.user, details={
        "old_mode": old_mode,
        "new_mode": mode,
        "old_force": old_force,
        "new_force": client.force_global_playlist_cache_mode,
    })
    logger.info(
        f"Global playlist cache mode changed by {user_display(ctx.user)}: "
        f"{old_mode}/{old_force} -> {mode}/{client.force_global_playlist_cache_mode}"
    )

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

@app_commands.describe(include_current="Also cache the currently playing track")
@client.tree.command(name="cachequeue")
async def cachequeue(ctx, include_current: Optional[bool] = True):
    """Admin-only cache download for the current song plus upcoming queue."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    await ctx.response.defer(ephemeral=True)
    targets = current_session_cache_targets(include_current=bool(include_current))
    if not targets:
        await ctx.followup.send("No current session tracks are available to cache.", ephemeral=True)
        return
    append_queue_blackbox_event("cachequeue-started", tracks=[dict(track) for track in targets], actor=ctx.user, details={
        "include_current": bool(include_current),
    })
    append_runtime_audit_event("cachequeue-started", actor=ctx.user, details={
        "include_current": bool(include_current),
        "track_count": len(targets),
    })
    result = await cache_current_session_tracks(include_current=bool(include_current))
    append_queue_blackbox_event("cachequeue-finished", tracks=[dict(track) for track in targets], actor=ctx.user, details=result)
    append_runtime_audit_event("cachequeue-finished", actor=ctx.user, details=result)
    await ctx.followup.send(
        "\n".join([
            "**cachequeue complete**",
            f"- tracks considered: `{result['total']}`",
            f"- downloaded: `{result['downloaded']}` (`{human_bytes(result['bytes'])}`)",
            f"- reused existing cache: `{result['reused']}`",
            f"- skipped: `{result['skipped']}`",
            f"- skipped by `nodownload`: `{result['restricted']}`",
            f"- failed: `{result['failed']}`",
            f"- cache use: `{human_bytes(cache_total_bytes())} / {human_bytes(CACHE_HARD_LIMIT_BYTES)}`",
        ]),
        ephemeral=True,
    )
    logger.info(f"/cachequeue completed by {user_display(ctx.user)} ({user_id_value(ctx.user)}): {result}")

def purge_cache_files(*, keep_current: bool = True, actor=None) -> PurgeCacheResult:
    result = PurgeCacheResult()
    current_file = None
    if keep_current and client.current_track_info:
        current_file = cached_file_for_track(client.current_track_info)
        current_file = os.path.realpath(current_file) if current_file else None
    if not os.path.isdir(CACHE_DIR):
        logger.info(f"Cache purge skipped because cache directory does not exist: {CACHE_DIR}")
        return result
    logger.info(
        f"Cache purge started by admin: dir={CACHE_DIR} keep_current={keep_current} "
        f"current_file={metadata_path_for_cache_file(current_file) if current_file else '-'}"
    )
    for filename in os.listdir(CACHE_DIR):
        file_path = os.path.join(CACHE_DIR, filename)
        result.scanned += 1
        if not is_safe_cache_path(file_path):
            result.skipped_unsafe += 1
            logger.info(f"Cache purge skipped unsafe/non-media file: {metadata_path_for_cache_file(file_path)}")
            continue
        if current_file and os.path.realpath(file_path) == current_file:
            result.kept_current += 1
            logger.info(f"Cache purge kept current playing file: {metadata_path_for_cache_file(file_path)}")
            continue
        size = cache_file_size(file_path)
        try:
            os.remove(file_path)
            result.removed += 1
            result.removed_bytes += size
            logger.info(f"Cache purge removed file: {metadata_path_for_cache_file(file_path)} size={human_bytes(size)}")
        except OSError as exc:
            result.failed += 1
            logger.warning(f"Failed to purge cache file {file_path}: {exc}")
    for vid, info in list(downloaded.items()):
        file_path = info.get("filepath")
        if not file_path or not is_safe_cache_path(file_path):
            downloaded.pop(vid, None)
            result.metadata_removed += 1
            logger.info(f"Cache purge removed stale metadata entry for {vid}: invalid path {file_path or '-'}")
            continue
        if not os.path.isfile(path_from_metadata(file_path)):
            downloaded.pop(vid, None)
            result.metadata_removed += 1
            logger.info(f"Cache purge removed stale metadata entry for {vid}: missing file {file_path}")
    save_downloads_metadata("cache purge")
    logger.info(
        "Cache purge completed: "
        f"scanned={result.scanned} removed={result.removed} removed_bytes={human_bytes(result.removed_bytes)} "
        f"kept_current={result.kept_current} skipped_unsafe={result.skipped_unsafe} "
        f"failed={result.failed} metadata_removed={result.metadata_removed}"
    )
    append_runtime_audit_event("purgecache", actor=actor, details={
        "keep_current": keep_current,
        "scanned": result.scanned,
        "removed": result.removed,
        "removed_bytes": result.removed_bytes,
        "kept_current": result.kept_current,
        "skipped_unsafe": result.skipped_unsafe,
        "failed": result.failed,
        "metadata_removed": result.metadata_removed,
    })
    return result

@client.tree.command()
async def cachestatus(ctx):
    """Shows media cache status (admin only)."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    cache_bytes = cache_total_bytes()
    limit_bytes = CACHE_HARD_LIMIT_BYTES
    files = 0
    if os.path.isdir(CACHE_DIR):
        files = sum(1 for name in os.listdir(CACHE_DIR) if is_safe_cache_path(os.path.join(CACHE_DIR, name)))
    await ctx.response.send_message(
        "\n".join([
            "**cache status**",
            f"- directory: `{metadata_path_for_cache_file(CACHE_DIR)}`",
            f"- files: `{files}`",
            f"- size: `{cache_bytes / (1024 * 1024):.1f} MB / {limit_bytes // (1024 * 1024)} MB`",
            f"- playlist default: `{client.playlist_cache_default_mode}`",
            f"- force global playlist cache: `{client.force_global_playlist_cache_mode}`",
        ]),
        ephemeral=True,
    )

@client.tree.command()
async def purgecache(ctx):
    """Purges validated media files from cache (admin only)."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    before_bytes = cache_total_bytes()
    result = purge_cache_files(keep_current=True, actor=ctx.user)
    after_bytes = cache_total_bytes()
    await ctx.response.send_message(
        "\n".join([
            f"Purged {result.removed} cache file(s), freeing {human_bytes(result.removed_bytes)}.",
            f"Scanned {result.scanned}; kept current {result.kept_current}; skipped {result.skipped_unsafe}; failed {result.failed}.",
            f"Metadata entries cleaned: {result.metadata_removed}. Cache is now {human_bytes(after_bytes)} (was {human_bytes(before_bytes)}).",
        ]),
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
    append_runtime_audit_event("purgequeue", actor=ctx.user, details={
        "deleted_files": count,
        "kept_current": bool(current_id),
    })

@app_commands.describe(seconds="Seconds to wait after playback before deleting downloaded song files")
@client.tree.command()
async def setdeletetime(ctx, seconds: int):
    """Sets delayed cleanup time for downloaded song files (admin only)."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        logger.warning(
            f"Denied /setdeletetime by {user_display(ctx.user)} "
            f"({getattr(ctx.user, 'id', 0)}): admin required."
        )
        return
    if seconds < DOWNLOAD_DELETE_DELAY_MIN_SECONDS or seconds > DOWNLOAD_DELETE_DELAY_MAX_SECONDS:
        await ctx.response.send_message(
            f"Delete time must be between {DOWNLOAD_DELETE_DELAY_MIN_SECONDS} and {DOWNLOAD_DELETE_DELAY_MAX_SECONDS} seconds.",
            ephemeral=True,
        )
        return
    old_seconds = client.download_delete_delay_seconds
    client.download_delete_delay_seconds = seconds
    await ctx.response.send_message(
        f"Downloaded songs will now be deleted {seconds} second(s) after playback ends. "
        "Already scheduled deletions keep their previous timer.",
        ephemeral=True,
    )
    append_runtime_audit_event("delete-delay-changed", actor=ctx.user, details={
        "old_seconds": old_seconds,
        "new_seconds": seconds,
    })
    logger.info(
        f"Download delete delay changed by {user_display(ctx.user)} "
        f"({getattr(ctx.user, 'id', 0)}): {old_seconds}s -> {seconds}s"
    )

@app_commands.describe(
    enabled="Turn auto-leave on or off",
    delay_seconds="Seconds the bot must be alone before leaving (default 10)",
)
@client.tree.command()
async def autoleave(ctx, enabled: bool, delay_seconds: Optional[int] = None):
    """Toggles leaving voice when the bot is alone (admin only)."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        logger.warning(
            f"Denied /autoleave by {user_display(ctx.user)} "
            f"({getattr(ctx.user, 'id', 0)}): admin required."
        )
        return
    if delay_seconds is None:
        delay_seconds = client.auto_leave_delay_seconds or AUTO_LEAVE_DEFAULT_DELAY_SECONDS
    if delay_seconds < AUTO_LEAVE_MIN_DELAY_SECONDS or delay_seconds > AUTO_LEAVE_MAX_DELAY_SECONDS:
        await ctx.response.send_message(
            f"Auto-leave delay must be between {AUTO_LEAVE_MIN_DELAY_SECONDS} and {AUTO_LEAVE_MAX_DELAY_SECONDS} seconds.",
            ephemeral=True,
        )
        return
    client.auto_leave_enabled = enabled
    client.auto_leave_delay_seconds = delay_seconds
    if not enabled:
        cancel_auto_leave_task("auto-leave disabled")
        await ctx.response.send_message("Auto-leave is disabled.", ephemeral=True)
        append_runtime_audit_event("autoleave-changed", actor=ctx.user, details={
            "enabled": False,
            "delay_seconds": delay_seconds,
        })
        logger.info(f"Auto-leave disabled by {user_display(ctx.user)} ({getattr(ctx.user, 'id', 0)}).")
        return
    voice = active_voice_client(ctx.guild)
    if voice and voice.is_connected():
        client.current_voice_channel = voice
        schedule_auto_leave_if_needed(getattr(voice, "channel", None))
        schedule_alone_speed_reset_if_needed(getattr(voice, "channel", None))
    await ctx.response.send_message(
        f"Auto-leave is enabled. If the bot is alone for {delay_seconds} second(s), it will save the current song and queue, then disconnect. Restore with `/play last`.",
        ephemeral=True,
    )
    append_runtime_audit_event("autoleave-changed", actor=ctx.user, details={
        "enabled": True,
        "delay_seconds": delay_seconds,
    })
    logger.info(
        f"Auto-leave enabled by {user_display(ctx.user)} "
        f"({getattr(ctx.user, 'id', 0)}) with delay={delay_seconds}s."
    )

@app_commands.describe(level=f"Volume percent from 1 to {SAFE_VOLUME_MAX_LEVEL}")
@client.tree.command()
async def volume(ctx, level: int):
    """Sets the audio playback volume within the normal safety cap."""
    record_command(ctx)
    if not await require_not_restricted(ctx, "novolumechange", "change volume"):
        return
    error = validate_volume_level(level)
    if error:
        await ctx.response.send_message(error, ephemeral=True)
        return
    await request_voice_vote(ctx.user, ctx.channel, "volume", f"set volume to {level}%", value=level, ctx=ctx)

@app_commands.describe(level=f"Volume percent from 1 to {SAFE_VOLUME_MAX_LEVEL}")
@client.tree.command(name="volume_session")
async def volume_session(ctx, level: int):
    """Admin-only volume override until the bot disconnects."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    error = validate_volume_level(level)
    if error:
        await ctx.response.send_message(error, ephemeral=True)
        return
    voice = active_voice_client(ctx.guild)
    if not voice or not voice.is_connected():
        await ctx.response.send_message("Connect the bot to voice before setting a session volume.", ephemeral=True)
        return
    client.session_volume_locked = True
    set_client_volume_level(level)
    await ctx.response.send_message(f"Session volume hard-set to {level}% until the bot disconnects.")
    logger.info(f"Session volume hard-set to {level}% by {user_display(ctx.user)}.")

@app_commands.describe(
    level="Forced volume percent from 1 to 100",
    save_default="Also save this as the current voice channel default",
)
@client.tree.command(name="volume_force")
async def volume_force(ctx, level: int, save_default: Optional[bool] = False):
    """Admin-only forced volume override that can exceed the normal safety cap."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    error = validate_volume_level(level, allow_unsafe=True)
    if error:
        await ctx.response.send_message(error, ephemeral=True)
        return
    voice = active_voice_client(ctx.guild)
    voice_channel = getattr(voice, "channel", None) or getattr(getattr(ctx.user, "voice", None), "channel", None)
    if not voice or not voice.is_connected():
        await ctx.response.send_message("Connect the bot to voice before forcing volume.", ephemeral=True)
        return
    client.session_volume_locked = True
    set_client_volume_level(level, allow_unsafe=True)
    saved = False
    if save_default:
        key = channel_volume_key(voice_channel)
        if not key:
            await ctx.response.send_message("Forced session volume set, but no voice channel default could be saved.", ephemeral=True)
            return
        client.channel_volume_config.setdefault("channels", {})[key] = {
            "level": level,
            "force": True,
            "updated_at": time.time(),
            "updated_by_user_id": user_id_value(ctx.user),
            "updated_by_discord_name": user_display(ctx.user),
        }
        try:
            save_channel_volume_config()
            saved = True
        except Exception as exc:
            logger.error(f"Failed to save forced channel volume default: {exc}")
            await ctx.response.send_message("Forced session volume set, but saving the default failed. Check output.log.", ephemeral=True)
            return
    suffix = " and saved as a forced channel default" if saved else ""
    await ctx.response.send_message(f"Forced volume set to {level}%{suffix}.")
    logger.info(f"Forced volume set to {level}% by {user_display(ctx.user)} save_default={bool(save_default)}.")

@app_commands.describe(level=f"Volume percent from 1 to {SAFE_VOLUME_MAX_LEVEL}")
@client.tree.command(name="volume_default")
async def volume_default(ctx, level: int):
    """Admin-only persistent volume default for the current voice channel."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    error = validate_volume_level(level)
    if error:
        await ctx.response.send_message(error, ephemeral=True)
        return
    voice = active_voice_client(ctx.guild)
    voice_channel = getattr(voice, "channel", None) or getattr(getattr(ctx.user, "voice", None), "channel", None)
    key = channel_volume_key(voice_channel)
    if not key:
        await ctx.response.send_message("Join a voice channel or connect the bot before setting a channel default.", ephemeral=True)
        return
    client.channel_volume_config.setdefault("channels", {})[key] = {
        "level": level,
        "force": False,
        "updated_at": time.time(),
        "updated_by_user_id": user_id_value(ctx.user),
        "updated_by_discord_name": user_display(ctx.user),
    }
    try:
        save_channel_volume_config()
    except Exception as exc:
        logger.error(f"Failed to save channel volume default: {exc}")
        await ctx.response.send_message("Could not save the channel volume default. Check output.log.", ephemeral=True)
        return
    if voice and getattr(voice, "channel", None) == voice_channel and not client.session_volume_locked:
        set_client_volume_level(level)
    channel_name = discord.utils.escape_markdown(str(getattr(voice_channel, "name", "this channel")))
    await ctx.response.send_message(f"Default volume for **{channel_name}** is now {level}%.")
    logger.info(f"Persistent volume default for {key} set to {level}% by {user_display(ctx.user)}.")

@client.tree.command()
async def pause(ctx):
    """Pauses the current audio."""
    record_command(ctx)
    if not await require_voice_control(ctx, "pause playback"):
        return
    voice = active_voice_client(ctx.guild)
    if voice is None:
        logger.info("Pause command issued, but bot is not in a voice channel.")
        await ctx.response.send_message("Not currently in a voice channel")
    elif not client.currently_playing:
        await ctx.response.send_message("No audio is playing to pause")
    elif voice.is_paused():
        logger.info("Pause command issued, but audio is already paused.")
        await ctx.response.send_message("Audio is already paused")
    else:
        voice.pause()
        logger.info("Audio paused via /pause command.")
        await ctx.response.send_message("Audio paused")

@client.tree.command()
async def resume(ctx):
    """Resumes the current audio if paused."""
    record_command(ctx)
    if not await require_voice_control(ctx, "resume playback"):
        return
    voice = active_voice_client(ctx.guild)
    if voice is None:
        logger.info("Resume command issued, but bot is not in a voice channel.")
        await ctx.response.send_message("Not currently in a voice channel")
    elif not client.currently_playing:
        await ctx.response.send_message("No audio is playing to resume")
    elif voice.is_paused():
        voice.resume()
        logger.info("Audio playback resumed via /resume command.")
        await ctx.response.send_message("Resuming audio")
    else:
        logger.info("Resume command issued, but audio was not paused.")
        await ctx.response.send_message("Audio is not paused")

@client.tree.command()
async def stop(ctx):
    """Stops playback and disconnects the bot from the voice channel."""
    record_command(ctx)
    await request_voice_vote(ctx.user, ctx.channel, "stop", "stop playback")

@app_commands.describe(mode="download enables /play download logs without DEBUG logging; debug enables both")
@app_commands.choices(mode=[
    app_commands.Choice(name="toggle", value="toggle"),
    app_commands.Choice(name="download", value="download"),
    app_commands.Choice(name="debug", value="debug"),
    app_commands.Choice(name="admin", value="admin"),
    app_commands.Choice(name="all", value="all"),
    app_commands.Choice(name="normal", value="normal"),
    app_commands.Choice(name="off", value="off"),
])
@client.tree.command()
async def togglelog(ctx, mode: Optional[str] = "toggle"):
    """Toggles verbose (DEBUG level) logging and optional download debug UI (admin only)."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    mode = str(mode or "toggle").lower()
    if mode == "download":
        client.log_verbose = False
        client.download_debug_messages = True
        client.user_operation_debug_messages = False
    elif mode in {"debug", "admin", "all"}:
        client.log_verbose = True
        client.download_debug_messages = True
        client.user_operation_debug_messages = mode in {"admin", "all"}
    elif mode in {"normal", "off"}:
        client.log_verbose = False
        client.download_debug_messages = False
        client.user_operation_debug_messages = False
    else:
        client.log_verbose = not client.log_verbose
        client.download_debug_messages = client.log_verbose
        client.user_operation_debug_messages = False
    if client.log_verbose:
        logger.setLevel(logging.DEBUG)
        if client.user_operation_debug_messages:
            msg = "Verbose logging enabled. Admin user-space operation messages enabled for `/play` and automatic alone speed resets."
        else:
            msg = (
                "Verbose logging enabled."
                + (" Download log messages enabled for `/play`." if client.download_debug_messages else "")
            )
    else:
        logger.setLevel(logging.INFO)
        if client.download_debug_messages:
            msg = "Normal logging enabled. Download log messages enabled for `/play`."
        else:
            msg = "Verbose logging disabled. Download log messages disabled. Admin operation messages disabled."
    await ctx.response.send_message(msg)
    append_runtime_audit_event("logging-mode-changed", actor=ctx.user, details={
        "mode": mode,
        "log_verbose": client.log_verbose,
        "download_debug_messages": client.download_debug_messages,
        "user_operation_debug_messages": client.user_operation_debug_messages,
    })
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
    append_runtime_audit_event("download-mode-changed", actor=ctx.user, details={
        "download_mode": client.download_mode,
        "mode": mode,
    })
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
                content=format_now_playing(
                    client.current_track_info,
                    show_queue=True,
                    show_url=client.current_track_message_show_url,
                )
            )
            logger.info("Refreshed open now-playing queue section after queue link toggle.")
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            logger.warning(f"Failed to refresh now-playing queue section after link toggle: {exc}")
    await ctx.response.send_message(f"Queue links are now **{state}**.")
    append_runtime_audit_event("queue-links-changed", actor=ctx.user, details={
        "queue_links_disabled": client.queue_links_disabled,
        "state": state,
    })
    logger.info(f"Queue links toggled by admin: now {state}")

@app_commands.describe(speed=f"Playback speed from {MIN_PLAYBACK_SPEED:g} to {MAX_PLAYBACK_SPEED:g}")
@client.tree.command(name="playspeed")
async def playspeed_cmd(ctx, speed: float):
    """Hidden speed control for admins, the playspeed group, or everyone when enabled."""
    record_command(ctx)
    if not can_use_play_speed(ctx.user):
        await ctx.response.send_message("You do not have permission to use playspeed.", ephemeral=True)
        return
    parsed, error = normalize_playback_speed(speed)
    if error:
        await ctx.response.send_message(error, ephemeral=True)
        return
    if client.current_track_info and "playback_speed" not in client.current_track_info:
        client.current_track_info["playback_speed"] = playback_speed_for_track(client.current_track_info)
    client.playback_speed = parsed
    voice = active_voice_client(ctx.guild)
    schedule_alone_speed_reset_if_needed(getattr(voice, "channel", None))
    append_runtime_audit_event("playback-speed-changed", actor=ctx.user, details={
        "speed": parsed,
        "voice_channel_id": getattr(getattr(voice, "channel", None), "id", None),
        "voice_channel_name": getattr(getattr(voice, "channel", None), "name", None),
    })
    if abs(parsed - 1.0) <= 0.001:
        await ctx.response.send_message(normal_speed_message())
    else:
        await ctx.response.send_message(
            f"Playback speed set to `{parsed:g}x` for future audio sources. Current audio changes on the next track or replay."
        )
    logger.info(f"Playback speed set to {parsed:g}x by {user_display(ctx.user)} ({user_id_value(ctx.user)}).")

@app_commands.describe(enabled="Allow all users to use /playspeed and /play speed")
@client.tree.command(name="playspeedaccess")
async def playspeed_access(ctx, enabled: bool):
    """Hidden admin command to allow or restrict playspeed use."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    client.playspeed_allow_all = enabled
    save_runtime_permissions_config()
    await ctx.response.send_message(f"Playspeed access for everyone is now **{bool_status(enabled)}**.", ephemeral=True)
    logger.info(f"Playspeed allow-all set to {enabled} by {user_display(ctx.user)} ({user_id_value(ctx.user)}).")

@app_commands.describe(seconds=f"Cooldown from {NOWPLAYING_COOLDOWN_MIN_SECONDS} to {NOWPLAYING_COOLDOWN_MAX_SECONDS} seconds")
@client.tree.command(name="nowplayingcooldown")
async def nowplaying_cooldown(ctx, seconds: int):
    """Hidden admin command to set /nowplaying cooldown."""
    record_command(ctx)
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    if seconds < NOWPLAYING_COOLDOWN_MIN_SECONDS or seconds > NOWPLAYING_COOLDOWN_MAX_SECONDS:
        await ctx.response.send_message(
            f"Cooldown must be between {NOWPLAYING_COOLDOWN_MIN_SECONDS} and {NOWPLAYING_COOLDOWN_MAX_SECONDS} seconds.",
            ephemeral=True,
        )
        return
    client.nowplaying_cooldown_seconds = int(seconds)
    save_runtime_permissions_config()
    await ctx.response.send_message(f"`/nowplaying` cooldown set to `{seconds}s`.", ephemeral=True)
    logger.info(f"Nowplaying cooldown set to {seconds}s by {user_display(ctx.user)} ({user_id_value(ctx.user)}).")

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

@client.tree.command(name="nowplaying")
async def nowplaying_cmd(ctx):
    """Posts now-playing controls without exposing the video URL."""
    record_command(ctx)
    await send_nowplaying_controls(ctx)

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
            voice = active_voice_client(ctx.guild)
            if voice:
                await voice.disconnect()
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

@client.tree.command(name="whatsnew")
async def whatsnew(ctx):
    """Shows recent bot updates."""
    record_command(ctx)
    await ctx.response.send_message(recent_updates_message())

@app_commands.describe(topic="Help topic, for example all or playlists", command="Command name, for example nytsoi, play, playlist new, or all")
@app_commands.choices(topic=[
    app_commands.Choice(name="all", value="all"),
    app_commands.Choice(name="playlists", value="playlists"),
    app_commands.Choice(name="playlist", value="playlist"),
])
@client.tree.command()
async def help(ctx, topic: Optional[str] = None, command: Optional[str] = None):
    """Displays the list of available commands and their usage."""
    record_command(ctx)
    topic_message = help_message_for(topic, command)
    if topic_message == "__HELP_ALL__":
        await send_help_pages(ctx, all_help_pages())
        return
    if topic_message:
        await ctx.response.send_message(topic_message)
        return
    if topic:
        await ctx.response.send_message("Unknown help topic. Try `/help topic:playlists`.", ephemeral=True)
        return
    await ctx.response.send_message(compact_help_message())
    message = await ctx.original_response()
    client.help_message_id = message.id
    client.help_expanded = False
    client.help_page = 0
    client.help_pages = None
    try:
        await message.add_reaction(HELP_EXPAND_REACTION)
    except Exception as exc:
        logger.warning(f"Failed to add help expand reaction: {exc}")

@app_commands.describe(view="latest, play, session, or commands")
@app_commands.choices(view=[
    app_commands.Choice(name="latest", value="latest"),
    app_commands.Choice(name="play", value="play"),
    app_commands.Choice(name="session", value="session"),
    app_commands.Choice(name="commands", value="commands"),
])
@client.tree.command()
async def status(ctx, view: str = "latest"):
    """Displays runtime diagnostics."""
    record_command(ctx)
    view = (view or "latest").lower()
    public_play = view in {"play", "playback", "musicstream", "stream"} and client.status_play_public
    if not is_user_admin(ctx.user) and not public_play:
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    await ctx.response.send_message(build_status_message(view), ephemeral=not public_play)

client.tree.add_command(playlist_group)
client.tree.add_command(favorites_group)
client.tree.add_command(usergroup_group)
client.tree.add_command(config_group)

@client.tree.error
async def on_app_command_error(ctx, error):
    # Global error handler for app commands
    command = getattr(getattr(ctx, "command", None), "name", "unknown")
    logger.exception(f"Error in /{command}: {error}")
    await safe_interaction_send(ctx, "💥  Oops, something went wrong. Please check the bot logs for details.")

if __name__ == "__main__":
    client.run(BOT_TOKEN)
