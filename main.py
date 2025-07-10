import quotes

import discord
from discord import app_commands
import os
import asyncio
import yt_dlp
from dotenv import load_dotenv
import urllib.parse, urllib.request, re
import time
import json
import logging

# Setup logging (default to INFO level; can be toggled to DEBUG via /togglelog)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure songs directory exists and load downloaded songs metadata
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
songs_dir = BASE_DIR
os.makedirs(songs_dir, exist_ok=True)
downloads_file = os.path.join(songs_dir, "downloads.json")
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
        if file_path and os.path.isfile(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Removed expired file: {file_path}")
            except Exception as e:
                logger.error(f"Error removing file {file_path}: {e}")
        expired_ids.append(vid)
for vid in expired_ids:
    downloaded.pop(vid, None)
# Save updated downloads info after cleanup
try:
    with open(downloads_file, 'w') as f:
        json.dump(downloaded, f)
except Exception as e:
    logger.error(f"Could not save downloads file: {e}")

# Setup YouTube-DL (yt_dlp) options
ytdl_options = {
    'format': 'bestaudio/best',
    'outtmpl': os.path.join(songs_dir, '%(extractor)s-%(id)s-%(title)s.%(ext)s'),
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # bind to IPv4
    'ignoreerrors': 'Do not stop on download errors.',
    'verbose': True,
    'logger': logger
}
ytdl = yt_dlp.YoutubeDL(ytdl_options)

# Setup ffmpeg options for Discord audio
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# Load bot and guild tokens from .env file
load_dotenv()

# Initialize constants and global state
queue = []  # list of track dicts for upcoming songs
voice_clients = {}
youtube_base_url = 'https://www.youtube.com/'
youtube_base_url_2 = 'https://youtu.be/'
youtube_results_url = youtube_base_url + 'results?'
youtube_watch_url = youtube_base_url + 'watch?v='

MY_GUILD = discord.Object(os.environ["MY_GUILD"])
QUOTES_ID = int(os.environ["QUOTES_ID"])

# Admin configuration (role and specific user allowed commands like reboot etc. + extra info privileges ;))
ADMIN_ROLE_NAME = os.getenv("ADMIN_ROLE_NAME", "Bottiadmin")
ADMIN_USER_ID   = os.getenv("ADMIN_USER_ID")
ADMIN_USER_ID   = int(ADMIN_USER_ID) if ADMIN_USER_ID else None
ADMIN_USERNAME  = os.getenv("ADMIN_USERNAME") 

def is_user_admin(user) -> bool:
    """Check if the given user has admin privileges (role or specific user)."""
    if user is None:
        return False
    # 1) role-based check
    for role in getattr(user, "roles", []):
        if role.name == ADMIN_ROLE_NAME:
            return True
    # 2) optional user-based check (only if you set ADMIN_USER_ID/USERNAME)
    if hasattr(user, "id") and hasattr(user, "name"):
        if user.id == ADMIN_USER_ID and user.name == ADMIN_USERNAME:
            return True
    if ADMIN_USER_ID and user.id == ADMIN_USER_ID:
        return True
    if ADMIN_USERNAME and user.name == ADMIN_USERNAME:
        return True
    return False

def is_user_admin(user) -> bool:
     """Check if the given user has admin privileges (role or specific user)."""
     if user is None:
         return False
     # 1) role-based check
     for role in getattr(user, "roles", []):
         if role.name == ADMIN_ROLE_NAME:
             return True
     # 2) optional user‐based check (only if you set ADMIN_USER_ID/USERNAME)
     if hasattr(user, "id") and hasattr(user, "name"):
         if user.id == ADMIN_USER_ID and user.name == ADMIN_USERNAME:
             return True
     if ADMIN_USER_ID and user.id == ADMIN_USER_ID:
         return True
     if ADMIN_USERNAME and user.name == ADMIN_USERNAME:
         return True
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
        # If the query is not already a YouTube link, perform a search
        if youtube_base_url not in url and youtube_base_url_2 not in url:
            query_string = urllib.parse.urlencode({'search_query': url})
            content = urllib.request.urlopen(youtube_results_url + query_string)
            search_results = re.findall(r'/watch\?v=(.{11})', content.read().decode())
            if not search_results:
                return None, url
            url = youtube_watch_url + search_results[0]
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if data is None:
            return None, url
        if 'entries' in data:
            data = data['entries'][0]
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
        # Admin-controllable flags
        self.download_mode = True              # True = download-and-play, False = stream-only
        self.log_verbose = False               # True = DEBUG logging on
        # Queue and history tracking
        self.song_history = []                # list of all tracks requested in current session
        self.queue_backup = None              # backup of last cleared queue (for restore)
        self.backup_timestamp = None          # timestamp for queue backup
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
client = Client(intents=intents)

async def fetch_track(query: str, requested_by=None):
    """
    Fetches YouTube track info for the given query (URL or search term).
    If download_mode is True, downloads the audio (unless cached) and returns track info with file path.
    If download_mode is False, returns track info for streaming (no file path).
    Applies size and duration restrictions based on user permissions.
    """
    # Determine the full YouTube URL and video ID for the query
    video_url = query
    video_id = None
    if youtube_base_url not in query and youtube_base_url_2 not in query:
        # The query is a search term; perform a YouTube search to get the first result
        try:
            query_string = urllib.parse.urlencode({'search_query': query})
            content = urllib.request.urlopen(youtube_results_url + query_string)
            search_results = re.findall(r'/watch\?v=(.{11})', content.read().decode())
            if not search_results:
                raise Exception("No results found")
            video_id = search_results[0]
            video_url = youtube_watch_url + video_id
        except Exception as e:
            logger.error(f"Error searching for '{query}': {e}")
            raise
    else:
        # The query is already a YouTube URL; extract the video ID
        try:
            parsed = urllib.parse.urlparse(query)
            if parsed.netloc.endswith("youtu.be"):
                video_id = parsed.path.lstrip('/')
            elif "youtube.com" in parsed.netloc:
                qs = urllib.parse.parse_qs(parsed.query)
                if 'v' in qs:
                    video_id = qs['v'][0]
                elif parsed.path.startswith("/embed/") or parsed.path.startswith("/shorts/") or parsed.path.startswith("/watch/"):
                    parts = parsed.path.split('/')
                    video_id = parts[-1] if parts[-1] else parts[-2]  # handle trailing slash
            if video_id:
                video_url = youtube_watch_url + video_id
        except Exception as e:
            logger.error(f"Could not parse video ID from URL {query}: {e}")
            video_id = None

    # If we have a video_id and it's cached (and in download mode), use the cached file
    if video_id and video_id in downloaded and client.download_mode:
        info = downloaded[video_id]
        file_path = info.get('filepath')
        title = info.get('title', 'Unknown title')
        page_url = youtube_watch_url + video_id
        if file_path and os.path.isfile(file_path):
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
            data = data['entries'][0]
        video_id = data.get('id')
        title = data.get('title', 'Unknown title')
        page_url = data.get('webpage_url', video_url)
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
                if fp and os.path.isfile(fp):
                    try:
                        total += os.path.getsize(fp)
                    except Exception:
                        continue
            return total
        total_bytes = total_downloaded_bytes()

        # If in download mode, enforce file size and total disk usage limits
        if client.download_mode:
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
        # Cache the downloaded file info
        downloaded[video_id] = {'title': title, 'filepath': file_path, 'timestamp': time.time()}
        try:
            with open(downloads_file, 'w') as f:
                json.dump(downloaded, f)
        except Exception as e:
            logger.error(f"Failed to update downloads file: {e}")
        logger.info(f"Downloaded '{title}' ({video_id}) to {file_path}")
        return {'id': video_id, 'title': title, 'webpage_url': page_url, 'file': file_path}
    except Exception as e:
        logger.error(f"yt_dlp error for {query}: {e}")
        raise

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
                if file_path and os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                        logger.info(f"Removed file {file_path} after 600s delay")
                    except Exception as e:
                        logger.error(f"Error removing file {file_path}: {e}")
                downloaded.pop(video_id, None)
                try:
                    with open(downloads_file, 'w') as f:
                        json.dump(downloaded, f)
                except Exception as e:
                    logger.error(f"Failed to update downloads file: {e}")
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
            # Announce now playing
            now_msg = await channel.send(f"Now playing: {track['title']} ({track['id']})")
            client.current_track_message = now_msg
            try:
                await now_msg.add_reaction("◀️")
                await now_msg.add_reaction("⏸️")
                await now_msg.add_reaction("▶️")
            except Exception as e:
                logger.error(f"Failed to add reactions: {e}")
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
    logger.info(f"{client.user} on käynnistynyt.")
    try:
        synced = await client.tree.sync(guild=MY_GUILD)
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Sync error: {e}")

@client.event
async def on_voice_state_update(member, before, after):
    # If the bot (IgorBot) is disconnected from voice, reset the current voice channel reference
    if member.bot and member.name == "IgorBot":
        if after.channel is None:
            client.current_voice_channel = None

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
    # Music control reactions on the "Now Playing" message
    if client.current_track_message and reaction.message.id == client.current_track_message.id:
        emoji = str(reaction.emoji)
        if emoji == "▶️":
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
        # Remove the user's reaction to allow them to use it again
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except Exception as e:
            logger.warning(f"Failed to remove user reaction: {e}")

async def save_all_channel_messages(channel):
    messages = [message.content async for message in channel.history(limit=None)]
    quotes.saveQuotes(messages)

# Slash commands

@client.tree.command()
async def join(ctx):
    """Joins the voice channel that the user is currently in."""
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
                    if file_path and os.path.isfile(file_path):
                        try:
                            os.remove(file_path)
                            count += 1
                        except Exception as e:
                            logger.error(f"Error deleting file {file_path}: {e}")
                    downloaded.pop(vid, None)
                try:
                    with open(downloads_file, 'w') as f:
                        json.dump(downloaded, f)
                except Exception as e:
                    logger.error(f"Failed to save downloads file after deletion: {e}")
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
    await ctx.response.defer()
    if not client.currently_playing:
        # If not already playing, join voice if not in a channel
        if client.current_voice_channel is None:
            client.current_voice_channel = await ctx.user.voice.channel.connect()
            client.song_history = []  # reset history for new session
            await ctx.followup.send(f"Joined voice channel {ctx.user.voice.channel.name}")
        try:
            track = await fetch_track(url, requested_by=ctx.user)
            # If admin needs to confirm a large download
            if track.get('needs_confirm'):
                filesize_mb = track.get('filesize', 0) / (1024 * 1024)
                # Prompt admin for confirmation to download the large file
                confirm_text = f"Track **{track['title']}** is large (~{filesize_mb:.1f} MB). React 👍 to confirm download, or 👎 to cancel."
                await ctx.followup.send(confirm_text)
                # Get the confirmation message to add reactions
                confirm_msg = await ctx.original_response()
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
                else:
                    await ctx.followup.send("Download canceled.")
                    return
            # Play the track (either from file or streaming)
            if track.get('file'):
                source = discord.FFmpegPCMAudio(track['file'], options='-vn')
                player = discord.PCMVolumeTransformer(source, volume=client.volume)
            else:
                player, _ = await YTDLSource.from_url(track['webpage_url'], stream=True)
            ctx.guild.voice_client.play(player, after=lambda e, vid=track['id']: after_played_track(e, vid, ctx.channel))
            client.current_track_id = track['id']
            client.currently_playing = True
            client.last_track_info = client.current_track_info
            client.current_track_info = track
            client.song_history.append(track)
            # Send now playing message with reactions
            now_msg = await ctx.followup.send(f"Now playing: {track['title']} ({track['id']})")
            client.current_track_message = now_msg
            try:
                await now_msg.add_reaction("◀️")
                await now_msg.add_reaction("⏸️")
                await now_msg.add_reaction("▶️")
            except Exception as e:
                logger.error(f"Failed to add reactions: {e}")
            logger.info(f"Playing now: {track['title']} ({track['id']})")
        except Exception as e:
            logger.error(f"/play error: {e}")
            await ctx.followup.send("Failed to play the requested track.")
    else:
        # If something is already playing, add the requested song to the queue
        try:
            track = await fetch_track(url, requested_by=ctx.user)
            if track.get('needs_confirm'):
                # Cannot queue a large download without confirmation; instruct admin to use /play
                filesize_mb = track.get('filesize', 0) / (1024 * 1024)
                await ctx.followup.send(f"Track **{track['title']}** (~{filesize_mb:.1f} MB) is too large to queue without confirmation. Please use /play to confirm.")
                return
            queue.append(track)
            client.song_history.append(track)
            await ctx.followup.send(f"Added to queue: {track['title']} ({track['id']})")
            logger.info(f"Track added to queue: {track['title']} ({track['id']})")
        except Exception as e:
            logger.error(f"/play queue error: {e}")
            await ctx.followup.send("Failed to add track to queue.")

@app_commands.describe(query="YouTube URL or search term")
@client.tree.command()
async def playtop(ctx, *, query: str):
    """Adds a song to the top of the queue (plays next)."""
    await ctx.response.defer()
    if not client.currently_playing:
        # Nothing playing, so this will play immediately (similar to /play when queue empty)
        if client.current_voice_channel is None:
            client.current_voice_channel = await ctx.user.voice.channel.connect()
            client.song_history = []
            await ctx.followup.send(f"Joined voice channel {ctx.user.voice.channel.name}")
        try:
            track = await fetch_track(query, requested_by=ctx.user)
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
            ctx.guild.voice_client.play(player, after=lambda e, vid=track['id']: after_played_track(e, vid, ctx.channel))
            client.current_track_id = track['id']
            client.currently_playing = True
            client.last_track_info = client.current_track_info
            client.current_track_info = track
            client.song_history.append(track)
            now_msg = await ctx.followup.send(f"Now playing: {track['title']} ({track['id']})")
            client.current_track_message = now_msg
            try:
                await now_msg.add_reaction("◀️")
                await now_msg.add_reaction("⏸️")
                await now_msg.add_reaction("▶️")
            except Exception as e:
                logger.error(f"Failed to add reactions: {e}")
            logger.info(f"Playing now: {track['title']} ({track['id']})")
        except Exception as e:
            logger.error(f"/playtop error: {e}")
            await ctx.followup.send("Failed to play the track.")
    else:
        # If currently playing, queue this track to be next
        try:
            track = await fetch_track(query, requested_by=ctx.user)
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

@app_commands.describe(query="YouTube URL or search term")
@client.tree.command(name="enqueue")
async def enqueue_cmd(ctx, *, query: str):
    """Enqueues a song to the queue (alias: /queue, /q)."""
    await ctx.response.defer()
    try:
        track = await fetch_track(query, requested_by=ctx.user)
        if track.get('needs_confirm'):
            filesize_mb = track.get('filesize', 0) / (1024 * 1024)
            await ctx.followup.send(f"Track **{track['title']}** (~{filesize_mb:.1f} MB) requires confirmation to download. Use /play instead.")
            return
        queue.append(track)
        client.song_history.append(track)
        await ctx.followup.send(f"Added to queue: {track['title']} ({track['id']})")
        logger.info(f"Track enqueued: {track['title']} ({track['id']})")
    except Exception as e:
        logger.error(f"/enqueue error: {e}")
        await ctx.followup.send("Failed to enqueue track.")

@app_commands.describe(query="YouTube URL or search term")
@client.tree.command(name="queue")
async def queue_cmd(ctx, *, query: str):
    """Alias of /enqueue."""
    await enqueue_cmd(ctx, query=query)

@app_commands.describe(query="YouTube URL or search term")
@client.tree.command(name="q")
async def q_cmd(ctx, *, query: str):
    """Alias of /enqueue."""
    await enqueue_cmd(ctx, query=query)

@client.tree.command()
async def queuelist(ctx):
    """Displays the upcoming songs in the queue."""
    if len(queue) == 0:
        await ctx.response.send_message("Queue is empty.")
    else:
        lines = ["Upcoming songs:"]
        for i, track in enumerate(queue, start=1):
            title = track.get('title', 'Unknown title')
            vid = track.get('id', '')
            lines.append(f"{i}. {title} ({vid})")
        output = "\n".join(lines)
        await ctx.response.send_message(output)

@client.tree.command()
async def purgequeue(ctx):
    """Removes all downloaded song files from disk, but keeps the queue intact."""
    count = 0
    current_id = client.current_track_id
    for vid, info in list(downloaded.items()):
        if vid == current_id:
            continue  # skip current playing track's file
        file_path = info.get('filepath')
        if file_path and os.path.isfile(file_path):
            try:
                os.remove(file_path)
                count += 1
                logger.debug(f"Deleted file {file_path}")
            except Exception as e:
                logger.error(f"Error deleting file {file_path}: {e}")
        downloaded.pop(vid, None)
    try:
        with open(downloads_file, 'w') as f:
            json.dump(downloaded, f)
    except Exception as e:
        logger.error(f"Failed to save downloads file after purge: {e}")
    await ctx.response.send_message(f"Purged {count} files from disk.")

@client.tree.command()
async def volume(ctx, level: int):
    """Sets the audio playback volume (1-100)."""
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
    if not is_user_admin(ctx.user):
        await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    client.download_mode = not client.download_mode
    mode = "download-and-play" if client.download_mode else "stream-only"
    await ctx.response.send_message(f"Playback mode set to **{mode}**.")
    logger.info(f"Download mode toggled by admin: now {mode} mode")

@client.tree.command(name="now")
async def now_cmd(ctx):
    """Displays the currently playing song."""
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
    channel = client.get_channel(QUOTES_ID)
    await save_all_channel_messages(channel)
    await ctx.response.send_message("Quotes backup completed.")
    logger.info("Teekkari quotes backed up by command.")

# Random quote command
@client.tree.command()
async def random_quote(ctx):
    """Gets a random Teekkari quote."""
    message = quotes.getRandomQuote()
    await ctx.response.send_message(message)
    logger.info("User requested random teekkari quote.")

@client.tree.command()
async def help(ctx):
    """Displays the list of available commands and their usage."""
    help_lines = [
        "**Music Playback Commands:**",
        "/join – Join your voice channel.",
        "/play <URL or search> – Play a song (or add to queue if something is already playing).",
        "/playtop <query> – Play a song next (skip ahead of the queue).",
        "/enqueue <query> – Add a song to the queue (aliases: /queue, /q).",
        "/queuelist – Show the upcoming songs in the queue.",
        "/skip – Skip the current track.",
        "/stop – Stop playback and disconnect the bot.",
        "/pause – Pause the current playing audio.",
        "/resume – Resume the paused audio.",
        "/now (alias: /nytsoi) – Show the currently playing song.",
        "/getqueue – List all songs requested this session and their status.",
        "",
        "**Queue Management Commands:**",
        "/clear_queue – Clear the song queue (admins will be prompted to delete files).",
        "/purgequeue – Delete all downloaded song files (except the currently playing one).",
        "/restorequeue – Restore the last cleared or saved queue (admin only, within 10 min).",
        "",
        "**Admin Commands:**",
        "/togglelog – Toggle verbose logging on/off.",
        "/toggledownload – Toggle between download mode and streaming mode.",
        "/reboot – Reboot the bot (asks for confirmation).",
        "",
        "**Fun/Other Commands:**",
        "/backup_teekkari_quotes – Backup all quotes from the Teekkari quotes channel.",
        "/random_quote – Get a random Teekkari quote."
    ]
    await ctx.response.send_message("\n".join(help_lines))

@client.tree.error
async def on_app_command_error(ctx, error):
    # Global error handler for app commands
    logger.exception(f"Error in /{ctx.command.name}: {error}")
    await ctx.respond("💥 Oops, something went wrong. Please check the bot logs for details.")

if __name__ == "__main__":
    client.run(os.environ["BOT_TOKEN"])
