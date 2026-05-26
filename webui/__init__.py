"""
Web UI module for the Discord music bot.

Provides a browser-based interface for managing playlists and viewing the queue.
Runs as a FastAPI server on the same asyncio event loop as the bot.

Activation:
    Set WEBUI_ENABLED=true in .env and restart the bot.

Required packages (uncomment in requirements.txt):
    uvicorn>=0.30.0,<1.0
    fastapi>=0.111.0,<1.0

Environment variables:
    WEBUI_ENABLED      – set to true/1/yes to activate
    WEBUI_PORT         – port to bind (default: 8765)
    WEBUI_BIND_HOST    – host to bind (default: 127.0.0.1)
                         set to 0.0.0.0 for LAN/homelab access
    WEBUI_SECRET_KEY   – bearer token for authentication (required)

Networking:
    The server binds to WEBUI_BIND_HOST:WEBUI_PORT.
    For public access, use Cloudflare Tunnel:
        cloudflared tunnel --url http://127.0.0.1:WEBUI_PORT
    For homelab reverse proxy: point your ingress at the bind host/port.
    Nothing in this code needs to change for either setup.
"""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

WEBUI_PORT = int(os.getenv("WEBUI_PORT", "8765"))
WEBUI_BIND_HOST = os.getenv("WEBUI_BIND_HOST", "127.0.0.1")
WEBUI_SECRET_KEY = os.getenv("WEBUI_SECRET_KEY", "")


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
        self._queue = queue_ref

    @property
    def queue(self) -> list:
        return self._queue

    @property
    def current_track_info(self):
        return getattr(self._client, "current_track_info", None)


async def start(*, playlists_dir: str, bot_state: BotState):
    """
    Start the web UI FastAPI server as a background asyncio task.
    Returns immediately; the server runs concurrently with the bot.
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
            "WEBUI_ENABLED=true but WEBUI_SECRET_KEY is not set in .env. "
            "The web UI will be accessible without authentication. "
            "Set a strong secret key before exposing this to a network."
        )

    import uvicorn
    from webui.server import app, configure

    configure(
        playlists_dir=playlists_dir,
        bot_state=bot_state,
        secret_key=WEBUI_SECRET_KEY,
    )

    config = uvicorn.Config(
        app,
        host=WEBUI_BIND_HOST,
        port=WEBUI_PORT,
        log_level="warning",
        loop="asyncio",
        access_log=False,
        # Trust proxy headers when behind a reverse proxy
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    server = uvicorn.Server(config)
    logger.info(f"Web UI starting on http://{WEBUI_BIND_HOST}:{WEBUI_PORT}")
    asyncio.create_task(server.serve())
