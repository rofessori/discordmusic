"""
Live TV streaming module for the Discord music bot.

Activation:
    TV_ENABLED=true          in .env
    TV_STREAM_URL=<m3u8_url> in .env  (optional if always passed via /tv start <url>)

Auth:
    The &o= URL parameter carries the auth token — no cookies or Authorization header needed.
    The three headers below are required to match the browser's fingerprint.

Network note:
    The stream hostname (e.g. hirtto.tvkaista.net) may only resolve on your local network.
    The bot host must be on the same network as the browser that generated the &o= token.
"""
import shlex

# Headers required by the stream server; must be CRLF-separated for FFmpeg.
TV_STREAM_HEADERS = (
    "User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0\r\n"
    "Referer: https://www.tvkaista.org/\r\n"
    "Origin: https://www.tvkaista.org"
)

TV_DEFAULT_MAX_RESTARTS = 3
TV_DEFAULT_RESTART_WINDOW_SECONDS = 60


def check_dependencies() -> list:
    return []  # no additional packages required


def build_ffmpeg_before_options() -> str:
    """Return the before_options string for discord.FFmpegPCMAudio for the TV stream.

    Uses shlex.quote so the CRLF-separated headers survive shlex.split() as a single token.
    """
    return (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        f" -headers {shlex.quote(TV_STREAM_HEADERS)}"
    )
