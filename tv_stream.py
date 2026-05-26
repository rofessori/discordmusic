"""
Live TV streaming module for the Discord music bot.

Activation:
    TV_ENABLED=true          in .env
    TV_STREAM_URL=<m3u8_url> in .env  (optional if always passed via /tv start <url>)

Auth:
    The &o= URL parameter carries the auth token — no cookies or Authorization header needed.
    The headers below must match the browser's fingerprint exactly (copied from the working
    curl command). Every header ends with CRLF; the block ends with a final CRLF as FFmpeg
    requires.

URL refresh:
    The &o= token is stable for a browser session. When it expires, use /tv update <url>
    to swap in a fresh URL without restarting the bot.
"""
import shlex

# Exact headers from the working curl command. Each line ends with \r\n; the block also
# ends with \r\n so FFmpeg does not warn "No trailing CRLF found in HTTP header."
TV_STREAM_HEADERS = (
    "User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0\r\n"
    "Accept: */*\r\n"
    "Accept-Language: en-US,en;q=0.5\r\n"
    "Origin: https://www.tvkaista.org\r\n"
    "Connection: keep-alive\r\n"
    "Referer: https://www.tvkaista.org/\r\n"
    "Sec-Fetch-Dest: empty\r\n"
    "Sec-Fetch-Mode: cors\r\n"
    "Sec-Fetch-Site: cross-site\r\n"
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
