"""
Web UI module for the Discord music bot.

Provides a browser-based interface for managing playlists, queue, favorites,
and admin tools. Runs as a FastAPI server on the same asyncio event loop.

Activation:
    Set WEBUI_ENABLED=true and WEBUI_SECRET_KEY=<strong-secret> in .env, then restart.

Required packages:
    uvicorn>=0.30.0,<1.0
    fastapi>=0.111.0,<1.0

Environment variables:
    WEBUI_ENABLED       – set to true/1/yes to activate
    WEBUI_PORT          – port to bind (default: 8765)
    WEBUI_BIND_HOST     – host to bind (default: 127.0.0.1)
    WEBUI_SECRET_KEY    – admin bearer token
    WEBUI_PUBLIC_URL    – public URL for /webui command links

Networking:
    Cloudflare Tunnel:  cloudflared tunnel --url http://127.0.0.1:WEBUI_PORT
    Homelab:            point nginx/Caddy at WEBUI_BIND_HOST:WEBUI_PORT
"""

import asyncio
import logging
import os
import platform
import time

logger = logging.getLogger(__name__)

WEBUI_PORT       = int(os.getenv("WEBUI_PORT", "8765"))
WEBUI_BIND_HOST  = os.getenv("WEBUI_BIND_HOST", "127.0.0.1")
WEBUI_SECRET_KEY = os.getenv("WEBUI_SECRET_KEY", "")
WEBUI_PUBLIC_URL = os.getenv("WEBUI_PUBLIC_URL", "")


def check_dependencies() -> list:
    """Return list of missing package specs needed to run the web UI."""
    missing = []
    for pkg, spec in (
        ("uvicorn", "uvicorn>=0.30.0,<1.0"),
        ("fastapi", "fastapi>=0.111.0,<1.0"),
    ):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(spec)
    return missing


class BotState:
    """
    Live view of bot state exposed to the web server.
    Holds references (not snapshots) so values are always current.
    Also exposes control methods (skip, pause, resume) that are safe
    to call from the asyncio web-request context.
    """
    def __init__(self, client_ref, queue_ref):
        self._client = client_ref
        self._queue  = queue_ref
        self._start_time = time.time()

    # ── Read-only state ───────────────────────────────────────────────────────

    @property
    def queue(self) -> list:
        return self._queue

    @property
    def current_track_info(self):
        return getattr(self._client, "current_track_info", None)

    @property
    def _voice_client(self):
        vcs = getattr(self._client, "voice_clients", [])
        return vcs[0] if vcs else None

    @property
    def is_playing(self) -> bool:
        vc = self._voice_client
        return bool(vc and vc.is_playing())

    @property
    def is_paused(self) -> bool:
        vc = self._voice_client
        return bool(vc and vc.is_paused())

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time

    @property
    def process_memory_mb(self) -> float | None:
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            if platform.system() == "Darwin":
                return usage.ru_maxrss / (1024 * 1024)
            return usage.ru_maxrss / 1024
        except Exception:
            return None

    @property
    def volume_percent(self) -> int:
        try:
            return int(round(float(getattr(self._client, "volume", 0.5)) * 100))
        except Exception:
            return 0

    @property
    def is_repeat(self) -> bool:
        return bool(getattr(self._client, "repeat", False))

    @property
    def queue_length(self) -> int:
        return len(self._queue)

    @property
    def session_count(self) -> int:
        """Active WebUI sessions (requires a store reference; 0 if unavailable)."""
        store = getattr(self._client, "webui_session_store", None)
        if store is None:
            return 0
        try:
            return store.active_count()
        except Exception:
            return 0

    def get_config_snapshot(self) -> dict:
        """Read-only runtime settings for admin status display."""
        return {
            "volume_percent":  self.volume_percent,
            "is_repeat":       self.is_repeat,
            "is_playing":      self.is_playing,
            "is_paused":       self.is_paused,
            "queue_length":    self.queue_length,
            "uptime_seconds":  round(self.uptime_seconds, 1),
            "session_count":   self.session_count,
        }

    def disk_usage(self, base_dir: str) -> dict:
        result = {}
        for name in ("cache", "playlists"):
            path = os.path.join(base_dir, name)
            total, count = 0, 0
            if os.path.isdir(path):
                for dp, _, files in os.walk(path):
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(dp, f))
                            count += 1
                        except OSError:
                            pass
            result[name] = {"bytes": total, "files": count}
        return result

    # ── Playback control ──────────────────────────────────────────────────────

    def skip(self) -> bool:
        vc = self._voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            return True
        return False

    def pause(self) -> bool:
        vc = self._voice_client
        if vc and vc.is_playing():
            vc.pause()
            return True
        return False

    def resume(self) -> bool:
        vc = self._voice_client
        if vc and vc.is_paused():
            vc.resume()
            return True
        return False

    def add_to_queue(self, track: dict):
        self._queue.append(track)


async def start(*, playlists_dir: str, bot_state: "BotState", sessions,
                guesser=None):
    """
    Start the FastAPI server as a background asyncio task.
    Returns immediately; the server runs concurrently with the bot.

    guesser: optional QuoteGuesser instance (from quote_guesser.py)
    """
    missing = check_dependencies()
    if missing:
        logger.warning(
            "WEBUI_ENABLED=true but required packages are missing. "
            f"Run: pip install {' '.join(missing)}"
        )
        return

    if not WEBUI_SECRET_KEY:
        logger.warning(
            "WEBUI_ENABLED=true but WEBUI_SECRET_KEY is not set. "
            "Set a strong key before network exposure."
        )

    if not WEBUI_PUBLIC_URL:
        logger.warning(
            "WEBUI_PUBLIC_URL is not set. The /webui command cannot produce links."
        )

    import uvicorn
    from webui.server import app, configure

    configure(
        playlists_dir=playlists_dir,
        bot_state=bot_state,
        secret_key=WEBUI_SECRET_KEY,
        sessions=sessions,
        guesser=guesser,
    )

    config = uvicorn.Config(
        app,
        host=WEBUI_BIND_HOST,
        port=WEBUI_PORT,
        log_level="warning",
        loop="asyncio",
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )

    class _EmbeddedServer(uvicorn.Server):
        """Uvicorn that doesn't overwrite discord.py's signal handlers."""
        def install_signal_handlers(self) -> None:
            pass

    server = _EmbeddedServer(config)
    logger.info(f"Web UI starting on http://{WEBUI_BIND_HOST}:{WEBUI_PORT}")

    async def _serve():
        try:
            await server.serve()
        except Exception as exc:
            logger.error(f"Web UI server stopped unexpectedly: {exc}", exc_info=True)

    asyncio.create_task(_serve())
