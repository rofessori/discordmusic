"""
Live TV streaming module for the Discord music bot.

Activation:
    TV_ENABLED=true          in .env
    TV_STREAM_URL=<url>      in .env  (optional if always passed via /tv start <url>)

Supported stream types:
    hls_tvkaista  – tvkaista.org HLS streams (full browser-fingerprint headers injected)
    hls_generic   – any other .m3u8 URL (reconnect flags only)
    rtmp          – RTMP streams (no reconnect flags; FFmpeg handles natively)
    youtube       – YouTube live URLs resolved via yt-dlp before playback
    http          – generic HTTP audio/video streams (reconnect flags)

URL refresh:
    YouTube stream URLs expire. The original URL is always stored in
    client.tv_stream_url so it can be re-extracted on reconnect.
    For tvkaista, use /tv update <url> to swap in a fresh URL with a new token.
"""
import asyncio
import shlex
from typing import Optional

# Exact headers from the working curl command. Each line ends with \r\n; the block also
# ends with \r\n so FFmpeg does not warn "No trailing CRLF found in HTTP header."
_TVKAISTA_HEADERS = (
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

_YT_HOSTS = frozenset({
    "youtube.com", "www.youtube.com", "youtu.be",
    "m.youtube.com", "music.youtube.com",
})


def check_dependencies() -> list:
    missing = []
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        missing.append("yt-dlp")
    return missing


def detect_stream_type(url: str) -> str:
    """
    Classify a stream URL into one of five types used for FFmpeg option selection.

    Returns one of: 'hls_tvkaista', 'rtmp', 'youtube', 'hls_generic', 'http'
    """
    lower = url.lower()
    if "tvkaista" in lower:
        return "hls_tvkaista"
    if lower.startswith("rtmp://"):
        return "rtmp"
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        if host in _YT_HOSTS:
            return "youtube"
    except Exception:
        pass
    if ".m3u8" in lower:
        return "hls_generic"
    return "http"


async def resolve_stream_url(url: str) -> str:
    """
    Return the playable URL for a given input.

    Non-YouTube URLs are returned as-is.
    YouTube URLs are resolved via yt-dlp (run in a thread to avoid blocking the event loop).

    Raises RuntimeError if yt-dlp extraction fails, so the caller can surface the error
    to the Discord channel.
    """
    if detect_stream_type(url) != "youtube":
        return url

    def _extract():
        import yt_dlp
        opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            resolved = info.get("url") or info.get("manifest_url")
            if not resolved:
                raise RuntimeError("yt-dlp returned no stream URL for this YouTube link.")
            return resolved

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _extract)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"yt-dlp failed to resolve YouTube URL: {exc}") from exc


def build_ffmpeg_before_options(resolved_url: str) -> str:
    """
    Return the before_options string for discord.FFmpegPCMAudio.

    Takes the resolved (post-yt-dlp) URL — not the original YouTube URL.
    RTMP gets no reconnect flags; tvkaista gets full browser headers; all others
    get reconnect flags only.
    """
    stream_type = detect_stream_type(resolved_url)

    if stream_type == "rtmp":
        return ""

    reconnect = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

    if stream_type == "hls_tvkaista":
        return f"{reconnect} -headers {shlex.quote(_TVKAISTA_HEADERS)}"

    return reconnect


async def start_webhook_server(on_url_received, secret: str, port: int):
    """Start a tiny HTTP endpoint the Chrome extension can POST fresh URLs to.

    Expects JSON body: {"url": "<stream url>", "secret": "<TV_WEBHOOK_SECRET>"}
    Returns the aiohttp AppRunner so the caller can shut it down if needed.
    """
    from aiohttp import web

    async def handle_update(request):
        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="bad json")
        if body.get("secret") != secret:
            return web.Response(status=401, text="unauthorized")
        url = str(body.get("url", ""))
        if not url.startswith("https://") and not url.startswith("rtmp://"):
            return web.Response(status=400, text="url must be https or rtmp")
        await on_url_received(url)
        return web.Response(text="ok")

    async def handle_status(request):
        return web.Response(text="tv-webhook ok")

    app = web.Application()
    app.router.add_post("/tv/update", handle_update)
    app.router.add_get("/tv/status", handle_status)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner
