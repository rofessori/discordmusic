"""
Web UI module for the Discord music bot.

Provides a browser-based interface for managing playlists and viewing the queue.
Runs as a FastAPI server on the same asyncio event loop as the bot.

Activation:
    Set WEBUI_ENABLED=true and WEBUI_SECRET_KEY=<strong-secret> in .env, then restart.

Required packages (uncomment in requirements.txt):
    uvicorn>=0.30.0,<1.0
    fastapi>=0.111.0,<1.0

Environment variables:
    WEBUI_ENABLED       – set to true/1/yes to activate
    WEBUI_PORT          – port to bind (default: 8765)
    WEBUI_BIND_HOST     – host to bind (default: 127.0.0.1)
                          set to 0.0.0.0 for LAN/homelab access
    WEBUI_SECRET_KEY    – admin bearer token; also used for the legacy login screen
    WEBUI_PUBLIC_URL    – the URL users will open in their browser, e.g.
                          https://music.yoursite.com or the cloudflared tunnel URL.
                          Required for /webui command to produce clickable links.

Networking:
    For public access, use Cloudflare Tunnel:
        cloudflared tunnel --url http://127.0.0.1:WEBUI_PORT
    For homelab: point your ingress at WEBUI_BIND_HOST:WEBUI_PORT.
    Behind a reverse proxy? Set WEBUI_BIND_HOST=0.0.0.0 and ensure your proxy
    forwards X-Forwarded-For so per-user IP locking uses the real client IP.
"""

import asyncio
import logging
import os

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
    Live read-only view of bot state passed to the web server.
    Holds references — not snapshots — so values are always current.
    """
    def __init__(self, client_ref, queue_ref):
        self._client = client_ref
        self._queue  = queue_ref

    @property
    def queue(self) -> list:
        return self._queue

    @property
    def current_track_info(self):
        return getattr(self._client, "current_track_info", None)


async def start(*, playlists_dir: str, bot_state: "BotState", sessions):
    """
    Start the web UI FastAPI server as a background asyncio task.
    Returns immediately; the server runs concurrently with the bot.

    Args:
        playlists_dir: Absolute path to the playlists/ directory.
        bot_state:     BotState instance wrapping the live bot client.
        sessions:      webui.sessions.SessionStore instance from the bot Client.
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
            "The web UI requires either WEBUI_SECRET_KEY (admin bypass) or "
            "per-user sessions via /webui. Set a strong key before network exposure."
        )

    if not WEBUI_PUBLIC_URL:
        logger.warning(
            "WEBUI_PUBLIC_URL is not set. The /webui Discord command will not be able "
            "to produce links. Set WEBUI_PUBLIC_URL to the URL where the web UI is "
            "reachable (e.g. https://music.yoursite.com or a cloudflared URL)."
        )

    import uvicorn
    from webui.server import app, configure

    configure(
        playlists_dir=playlists_dir,
        bot_state=bot_state,
        secret_key=WEBUI_SECRET_KEY,
        sessions=sessions,
    )

    config = uvicorn.Config(
        app,
        host=WEBUI_BIND_HOST,
        port=WEBUI_PORT,
        log_level="warning",
        loop="asyncio",
        access_log=False,
        # Trust X-Forwarded-For so IP locking uses the real client IP
        # when the server is behind a reverse proxy or Cloudflare Tunnel.
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    server = uvicorn.Server(config)
    logger.info(f"Web UI starting on http://{WEBUI_BIND_HOST}:{WEBUI_PORT}")
    asyncio.create_task(server.serve())
