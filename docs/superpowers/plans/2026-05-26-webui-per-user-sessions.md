# Web UI Per-User Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the shared `WEBUI_SECRET_KEY` login with per-user, Discord-issued session tokens that are scoped to each user's own playlists, bound to their IP address, and auto-expire after 2 minutes of inactivity.

**Architecture:** A `/webui` slash command creates a cryptographically random session token tied to the Discord user's ID and admin status, stores it in an in-memory `SessionStore` on the bot's `Client`, and sends an ephemeral (user-only) link. The FastAPI server validates that token on every request: it binds to the first requesting IP, checks inactivity, and scopes all playlist reads/writes to what that user owns or manages. `WEBUI_SECRET_KEY` remains as an admin bypass for direct access (no Discord required). The session sweeper runs as an asyncio background task every 30 seconds; it is lightweight and shares the bot's event loop.

**Tech Stack:** Python dataclasses, `secrets` module (already in main.py), FastAPI `Depends`, no new dependencies.

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `webui/sessions.py` | **CREATE** | `WebUISession` dataclass, `SessionStore` class |
| `main.py` | **MODIFY** | `WEBUI_PUBLIC_URL` env var, `client.webui_session_store`, `/webui` command, session sweeper |
| `webui/__init__.py` | **MODIFY** | Accept `sessions` param, pass to `configure()` |
| `webui/server.py` | **MODIFY** | New `_require_session` auth, scoped endpoints, `/api/ping` |
| `webui/frontend/index.html` | **MODIFY** | Token from URL param, strip from history, "get link from Discord" screen, session-expired screen |
| `docs/COMMANDS.md` | **MODIFY** | Document `/webui` command |
| `docs/FEATURES.md` | **MODIFY** | Document per-user session model in web UI section |

---

## Task 1: Create `webui/sessions.py`

**Files:**
- Create: `webui/sessions.py`

- [ ] **Step 1: Write the file**

```python
"""
webui/sessions.py — Per-user session management for the web UI.

Sessions are created by the /webui Discord command, stored in bot memory,
and validated by the FastAPI server on every request.

Lifecycle:
    1. /webui command creates a WebUISession and stores it in SessionStore.
    2. Bot sends the user an ephemeral Discord link containing ?s=<token>.
    3. First HTTP request from the frontend binds the session to that IP.
    4. Every authenticated request calls SessionStore.touch() to update last_active.
    5. Sessions expire after INACTIVITY_TTL seconds of no requests.
    6. SessionStore.sweep() removes dead entries; call it every 30s.
"""
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional


# 2-minute inactivity window. The frontend polls now-playing every 10s,
# so a closed tab expires in ~2m 10s in practice.
INACTIVITY_TTL: int = 120

# How long the link stays valid before the first request is made.
CREATION_TTL: int = 300

# 18 bytes → 24 URL-safe base64 characters. Short enough for a URL,
# 144 bits of entropy — far beyond brute-force range.
_TOKEN_BYTES: int = 18


@dataclass
class WebUISession:
    token: str
    discord_user_id: int       # 0 for legacy secret-key admin sessions
    discord_username: str
    is_admin: bool             # captured at creation time from is_user_admin()
    created_at: float
    last_active: float
    bound_ip: Optional[str] = None  # None until the first HTTP request arrives
    alive: bool = True


class SessionStore:
    """
    In-memory session store. Not thread-safe across OS threads, but safe
    within a single asyncio event loop (all accesses happen on the bot loop).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, WebUISession] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        discord_user_id: int,
        discord_username: str,
        is_admin: bool,
    ) -> WebUISession:
        """Mint a new session and return it. Token is cryptographically random."""
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        now = time.time()
        session = WebUISession(
            token=token,
            discord_user_id=discord_user_id,
            discord_username=discord_username,
            is_admin=is_admin,
            created_at=now,
            last_active=now,
        )
        self._sessions[token] = session
        return session

    def get(self, token: str) -> Optional[WebUISession]:
        """
        Look up and validate a token.

        Returns the session if it is alive and within its time bounds.
        Returns None if the token is unknown, dead, or expired.
        Does NOT update last_active — callers do that with touch() after
        the IP check passes.
        """
        if not token:
            return None
        session = self._sessions.get(token)
        if session is None or not session.alive:
            return None

        now = time.time()

        # Link was never opened and the creation window has passed
        if session.bound_ip is None and now - session.created_at > CREATION_TTL:
            session.alive = False
            return None

        # Session has been idle too long
        if session.bound_ip is not None and now - session.last_active > INACTIVITY_TTL:
            session.alive = False
            return None

        return session

    def touch(self, session: WebUISession) -> None:
        """Reset the inactivity timer for a session."""
        session.last_active = time.time()

    def revoke(self, token: str) -> None:
        """Immediately invalidate a session (e.g. on explicit logout)."""
        s = self._sessions.get(token)
        if s:
            s.alive = False

    def sweep(self) -> int:
        """
        Remove expired/dead sessions. Returns the number of entries removed.
        Call this on a background asyncio.sleep loop every 30 seconds.
        """
        now = time.time()
        dead = [
            token for token, s in self._sessions.items()
            if not s.alive
            or (s.bound_ip is None and now - s.created_at > CREATION_TTL)
            or (s.bound_ip is not None and now - s.last_active > INACTIVITY_TTL)
        ]
        for token in dead:
            del self._sessions[token]
        return len(dead)

    def active_count(self) -> int:
        """Number of sessions that are currently alive (for diagnostics)."""
        return sum(1 for s in self._sessions.values() if s.alive)
```

- [ ] **Step 2: Verify syntax**

```bash
cd /Users/louniol/discordmusic && python -c "from webui.sessions import SessionStore, WebUISession; s = SessionStore(); sess = s.create(123, 'test#0001', False); print(s.active_count(), s.get(sess.token) is not None)"
```

Expected output: `1 True`

- [ ] **Step 3: Commit**

```bash
git add webui/sessions.py
git commit -m "feat(webui): add per-user SessionStore"
```

---

## Task 2: Update `webui/__init__.py`

**Files:**
- Modify: `webui/__init__.py`

Add `WEBUI_PUBLIC_URL` env var and update `start()` to accept and pass the sessions store to `configure()`.

- [ ] **Step 1: Edit `webui/__init__.py`**

Replace the entire file with:

```python
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
```

- [ ] **Step 2: Verify syntax**

```bash
cd /Users/louniol/discordmusic && python -c "import webui; print(webui.WEBUI_PUBLIC_URL)"
```

Expected output: `` (empty string, or whatever's in .env)

- [ ] **Step 3: Commit**

```bash
git add webui/__init__.py
git commit -m "feat(webui): add WEBUI_PUBLIC_URL, pass sessions to configure()"
```

---

## Task 3: Add `webui_session_store` to `Client.__init__` in `main.py`

**Files:**
- Modify: `main.py` (around line 1640 — after `self.spotify_review_message_ids`)

- [ ] **Step 1: Add import at top of main.py**

Find the existing import block (around line 1-10) and add after any existing imports from the webui package. Since the import is conditional on `WEBUI_ENABLED`, we add a safe fallback. Find the spot where `_webui_module` is set (around line 117) and after the `if WEBUI_ENABLED:` block add:

```python
# Session store is always created; it's a no-op dict if WEBUI is disabled
from webui.sessions import SessionStore as _WebUISessionStore
_webui_session_store_class = _WebUISessionStore
```

Actually, to avoid import errors when webui isn't installed, do it conditionally. Find the block around line 117-131 in main.py:

```python
_webui_module = None
if WEBUI_ENABLED:
    try:
        import webui as _webui_module
        missing_webui = _webui_module.check_dependencies()
        if missing_webui:
            logger.warning(
                "WEBUI_ENABLED=true but required packages are missing. "
                f"Run: pip install {' '.join(missing_webui)}"
            )
            _webui_module = None
        else:
            logger.info("Web UI module loaded.")
    except ImportError as _e:
        logger.warning(f"WEBUI_ENABLED=true but webui module not found: {_e}")
```

Replace with:

```python
_webui_module = None
_WebUISessionStore = None
if WEBUI_ENABLED:
    try:
        import webui as _webui_module
        from webui.sessions import SessionStore as _WebUISessionStore
        missing_webui = _webui_module.check_dependencies()
        if missing_webui:
            logger.warning(
                "WEBUI_ENABLED=true but required packages are missing. "
                f"Run: pip install {' '.join(missing_webui)}"
            )
            _webui_module = None
        else:
            logger.info("Web UI module loaded.")
    except ImportError as _e:
        logger.warning(f"WEBUI_ENABLED=true but webui module not found: {_e}")
```

- [ ] **Step 2: Add `webui_session_store` to `Client.__init__`**

Find line ~1641 (after `self.spotify_review_message_ids = {}`). Add:

```python
        # Web UI per-user session store (populated at on_ready if WEBUI is enabled)
        self.webui_session_store = _WebUISessionStore() if _WebUISessionStore else None
```

- [ ] **Step 3: Verify syntax**

```bash
cd /Users/louniol/discordmusic && python -c "import ast, sys; ast.parse(open('main.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(webui): add webui_session_store to Client"
```

---

## Task 4: Update `on_ready` in `main.py` — pass sessions + add sweeper

**Files:**
- Modify: `main.py` (around line 6786-6788)

- [ ] **Step 1: Find and replace the webui startup block in `on_ready`**

Current code (lines ~6786-6788):
```python
    if _webui_module is not None:
        bot_state = _webui_module.BotState(client_ref=client, queue_ref=queue)
        await _webui_module.start(playlists_dir=PLAYLISTS_DIR, bot_state=bot_state)
```

Replace with:
```python
    if _webui_module is not None:
        bot_state = _webui_module.BotState(client_ref=client, queue_ref=queue)
        await _webui_module.start(
            playlists_dir=PLAYLISTS_DIR,
            bot_state=bot_state,
            sessions=client.webui_session_store,
        )

        # Sweep expired web UI sessions every 30 seconds.
        # Lightweight: O(n) dict scan on the bot's own event loop.
        async def _webui_session_sweeper():
            while True:
                await asyncio.sleep(30)
                if client.webui_session_store is not None:
                    n = client.webui_session_store.sweep()
                    if n > 0:
                        logger.debug(f"Web UI: swept {n} expired session(s)")

        asyncio.create_task(_webui_session_sweeper())
```

- [ ] **Step 2: Verify syntax**

```bash
cd /Users/louniol/discordmusic && python -c "import ast; ast.parse(open('main.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(webui): pass sessions to start(), add sweeper task"
```

---

## Task 5: Add `/webui` slash command to `main.py`

**Files:**
- Modify: `main.py`
- Also need `WEBUI_PUBLIC_URL` read near line 115 (env flags section)

- [ ] **Step 1: Add `WEBUI_PUBLIC_URL` to the env flags section (near line 115)**

Find:
```python
WEBUI_ENABLED = env_flag("WEBUI_ENABLED", False)
```

Add after it:
```python
WEBUI_PUBLIC_URL = os.getenv("WEBUI_PUBLIC_URL", "").rstrip("/")
```

- [ ] **Step 2: Add the `/webui` command**

Find the block where the Spotify commands are conditionally registered (search for `spotify_group` or `client.tree.add_command(spotify_group)`). Add the `/webui` command unconditionally near the other utility commands (it self-guards with an `if _webui_module is None` check). A good place is just before or after the `/help` command definition.

Search for `@client.tree.command()` with name `help` or a nearby command. Add this block:

```python
@app_commands.describe()
@client.tree.command(name="webui")
async def webui_command(ctx):
    """Get a private link to the playlist editor. Only visible to you."""
    record_command(ctx)

    if _webui_module is None:
        await ctx.response.send_message(
            "The web UI is not enabled. "
            "Set `WEBUI_ENABLED=true` in `.env` and install the optional packages.",
            ephemeral=True,
        )
        return

    if not WEBUI_PUBLIC_URL:
        await ctx.response.send_message(
            "The web UI is running but `WEBUI_PUBLIC_URL` is not configured. "
            "Set it in `.env` to the URL where the web UI is reachable, then restart.",
            ephemeral=True,
        )
        return

    if client.webui_session_store is None:
        await ctx.response.send_message(
            "Session store is not available. This is a startup error — check the bot logs.",
            ephemeral=True,
        )
        return

    session = client.webui_session_store.create(
        discord_user_id=ctx.user.id,
        discord_username=str(ctx.user),
        is_admin=is_user_admin(ctx.user),
    )

    link = f"{WEBUI_PUBLIC_URL}/?s={session.token}"

    await ctx.response.send_message(
        f"**🎵 Playlist Editor**\n"
        f"> {link}\n\n"
        f"This link is private to you. "
        f"It expires after **2 minutes** of inactivity.\n"
        f"Use `/webui` to get a fresh link anytime.",
        ephemeral=True,
    )
```

- [ ] **Step 3: Verify syntax**

```bash
cd /Users/louniol/discordmusic && python -c "import ast; ast.parse(open('main.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(webui): add /webui command that issues per-user session links"
```

---

## Task 6: Rewrite auth and scoping in `webui/server.py`

**Files:**
- Modify: `webui/server.py`

This is the largest change. The full new file replaces the old one:

- [ ] **Step 1: Write the new `webui/server.py`**

```python
"""
FastAPI server for the music bot web UI.

Auth model:
    Every request must present a Bearer token in the Authorization header.
    Tokens are one of:
      - A per-user session token created by the /webui Discord command.
        These are scoped: the user can only see/edit their own playlists.
      - The WEBUI_SECRET_KEY value (admin override).
        These see and can edit everything, like the original shared-key mode.

    Per-user sessions are bound to the IP of the first request that uses them.
    Requests from a different IP after binding return 403 ip_mismatch.
    Sessions expire after INACTIVITY_TTL seconds of no requests.

Playlist scoping:
    Regular users see: playlists they own, playlists they manage, public playlists.
    Regular users can edit: playlists they own or manage (unless locked — then owner only).
    Admin sessions see and can edit everything.
"""

import hmac
import json
import logging
import os
import re
import tempfile
import time
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state — set once by configure()
# ---------------------------------------------------------------------------

_playlists_dir: str = ""
_bot_state = None        # webui.BotState instance
_secret_key: str = ""
_sessions = None         # webui.sessions.SessionStore instance (or None)

# ---------------------------------------------------------------------------
# Lazy FastAPI app
# ---------------------------------------------------------------------------

try:
    from fastapi import FastAPI, HTTPException, Depends, Header, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    import aiohttp

    app = FastAPI(title="Music Bot", docs_url=None, redoc_url=None, openapi_url=None)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    _STATIC_DIR = os.path.join(os.path.dirname(__file__), "frontend")

    # -----------------------------------------------------------------------
    # Session context object (returned from the auth dependency)
    # -----------------------------------------------------------------------

    class _SessionContext:
        """
        Lightweight auth context passed to every endpoint.
        Carries the resolved Discord user ID and admin flag.
        """
        __slots__ = ("discord_user_id", "is_admin", "token")

        def __init__(self, discord_user_id: int, is_admin: bool, token: str = ""):
            self.discord_user_id = discord_user_id
            self.is_admin = is_admin
            self.token = token

    # -----------------------------------------------------------------------
    # Auth dependency
    # -----------------------------------------------------------------------

    def _get_client_ip(request: Request) -> str:
        """
        Return the real client IP.
        When behind a reverse proxy (Cloudflare Tunnel, nginx, etc.) uvicorn's
        proxy_headers=True causes FastAPI to surface the real IP via
        request.client.host already — no manual header parsing needed.
        """
        if request.client and request.client.host:
            return request.client.host
        return "unknown"

    async def _require_session(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> _SessionContext:
        """
        Validate the Bearer token and return a _SessionContext.

        Tries per-user session first, then falls back to the legacy
        WEBUI_SECRET_KEY for admin access.

        Error responses:
            401  – token missing, unknown, or session expired/inactive
            403  – valid session but request came from a different IP
        """
        token: str = ""
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()

        if not token:
            raise HTTPException(status_code=401, detail="Authorization required")

        # ---- Try per-user session ----
        if _sessions is not None:
            session = _sessions.get(token)
            if session is not None:
                client_ip = _get_client_ip(request)
                if session.bound_ip is None:
                    # Bind IP on first request
                    session.bound_ip = client_ip
                elif session.bound_ip != client_ip:
                    # Different IP — reject. This protects against token theft
                    # if someone intercepts the Discord ephemeral message.
                    raise HTTPException(status_code=403, detail="ip_mismatch")
                _sessions.touch(session)
                return _SessionContext(
                    discord_user_id=session.discord_user_id,
                    is_admin=session.is_admin,
                    token=token,
                )
            # Token string existed in our store but the session is now dead
            # (expired or revoked). Distinguish from "never seen" so the
            # frontend can show "session expired" vs "no token".
            if token in _sessions._sessions:
                raise HTTPException(status_code=401, detail="inactive")

        # ---- Legacy admin bypass via WEBUI_SECRET_KEY ----
        if _secret_key and hmac.compare_digest(token, _secret_key):
            return _SessionContext(discord_user_id=0, is_admin=True, token=token)

        raise HTTPException(status_code=401, detail="Authorization required")

    _auth = Depends(_require_session)

    # -----------------------------------------------------------------------
    # YouTube URL helpers
    # -----------------------------------------------------------------------

    _YT_DOMAINS = frozenset({
        "youtube.com", "www.youtube.com",
        "youtu.be", "m.youtube.com",
        "music.youtube.com",
    })
    _VIDEO_ID_RE = re.compile(
        r"(?:v=|youtu\.be/|/v/|/embed/|/shorts/)([A-Za-z0-9_-]{11})"
    )

    def _is_youtube_url(url: str) -> bool:
        try:
            return urlparse(url).netloc in _YT_DOMAINS
        except Exception:
            return False

    def _extract_video_id(url: str) -> Optional[str]:
        m = _VIDEO_ID_RE.search(url)
        return m.group(1) if m else None

    def _canonical_youtube_url(video_id: str) -> str:
        return f"https://www.youtube.com/watch?v={video_id}"

    # -----------------------------------------------------------------------
    # Playlist file helpers
    # -----------------------------------------------------------------------

    def _playlist_metadata_files():
        if not os.path.isdir(_playlists_dir):
            return
        for root, _, files in os.walk(_playlists_dir):
            if "metadata.json" in files:
                yield os.path.join(root, "metadata.json")

    def _load_playlist(path: str) -> dict:
        with open(path, "r") as f:
            data = json.load(f)
        data.setdefault("tracks", [])
        data.setdefault("visibility", "private")
        data.setdefault("locked", False)
        data.setdefault("type", "playlist")
        data.setdefault("manager_user_ids", [])
        return data

    def _save_playlist_atomic(path: str, data: dict):
        dir_ = os.path.dirname(path)
        os.makedirs(dir_, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=dir_)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _find_playlist_by_id(playlist_id: str):
        """Returns (path, playlist_dict) or (None, None). Validates id format."""
        if not re.match(r"^[A-Za-z0-9_=-]{4,32}$", str(playlist_id or "")):
            return None, None
        for path in _playlist_metadata_files():
            try:
                pl = _load_playlist(path)
                if pl.get("id") == playlist_id and not pl.get("deleted"):
                    return path, pl
            except Exception:
                continue
        return None, None

    def _playlist_summary(pl: dict) -> dict:
        return {
            "id":          pl.get("id"),
            "name":        pl.get("name"),
            "visibility":  pl.get("visibility"),
            "type":        pl.get("type", "playlist"),
            "track_count": len(pl.get("tracks", [])),
            "owner":       pl.get("owner_discord_name"),
            "owner_id":    pl.get("owner_user_id"),
            "locked":      bool(pl.get("locked")),
        }

    def _sanitize_track(t: dict) -> dict:
        """Return only the fields the frontend needs; strip absolute paths."""
        vid = str(t.get("id") or "")
        url = str(t.get("webpage_url") or "")
        if vid and not url.startswith("http"):
            url = _canonical_youtube_url(vid)
        return {
            "id":           vid,
            "title":        str(t.get("title") or url or "Unknown"),
            "webpage_url":  url,
            "needs_refresh": bool(t.get("needs_refresh")),
        }

    # -----------------------------------------------------------------------
    # Scoping helpers
    # -----------------------------------------------------------------------

    def _can_view(pl: dict, ctx: _SessionContext) -> bool:
        """Can the session's user see this playlist?"""
        if ctx.is_admin:
            return True
        if pl.get("visibility") == "public":
            return True
        uid = ctx.discord_user_id
        if uid and uid == pl.get("owner_user_id"):
            return True
        if uid and str(uid) in [str(x) for x in pl.get("manager_user_ids", [])]:
            return True
        return False

    def _can_edit(pl: dict, ctx: _SessionContext) -> bool:
        """Can the session's user modify this playlist's tracks?"""
        if ctx.is_admin:
            return True
        uid = ctx.discord_user_id
        if not uid:
            return False
        is_owner = (uid == pl.get("owner_user_id"))
        is_manager = str(uid) in [str(x) for x in pl.get("manager_user_ids", [])]
        if not (is_owner or is_manager):
            return False
        # Locked playlists: only owner (and admins, handled above) can edit
        if pl.get("locked") and not is_owner:
            return False
        return True

    # -----------------------------------------------------------------------
    # API routes
    # -----------------------------------------------------------------------

    @app.get("/api/ping")
    async def ping(ctx: _SessionContext = _auth):
        """Lightweight endpoint to keep the session alive. No-op response."""
        return {"ok": True}

    @app.get("/api/playlists")
    async def list_playlists(ctx: _SessionContext = _auth):
        """Return playlists visible to the requesting user."""
        result = []
        for path in _playlist_metadata_files():
            try:
                pl = _load_playlist(path)
                if pl.get("deleted"):
                    continue
                if pl.get("type") == "favorites":
                    continue
                if not _can_view(pl, ctx):
                    continue
                result.append(_playlist_summary(pl))
            except Exception:
                continue
        result.sort(key=lambda p: str(p.get("name") or "").lower())
        return result

    @app.get("/api/playlists/{playlist_id}")
    async def get_playlist(playlist_id: str, ctx: _SessionContext = _auth):
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None or not _can_view(pl, ctx):
            raise HTTPException(status_code=404, detail="Playlist not found")
        return {
            **_playlist_summary(pl),
            "can_edit": _can_edit(pl, ctx),
            "tracks":   [_sanitize_track(t) for t in pl.get("tracks", [])],
        }

    @app.patch("/api/playlists/{playlist_id}")
    async def patch_playlist(
        playlist_id: str, request: Request, ctx: _SessionContext = _auth
    ):
        body = await request.json()
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None or not _can_view(pl, ctx):
            raise HTTPException(status_code=404, detail="Playlist not found")
        if not _can_edit(pl, ctx):
            raise HTTPException(status_code=403, detail="You do not have permission to edit this playlist")

        if "tracks" in body:
            incoming = body["tracks"]
            if not isinstance(incoming, list):
                raise HTTPException(status_code=422, detail="tracks must be a list")
            valid = []
            for t in incoming:
                if not isinstance(t, dict):
                    continue
                vid = str(t.get("id") or "")
                url = str(t.get("webpage_url") or "")
                if not vid and not url:
                    continue
                valid.append({
                    "id":           vid,
                    "title":        str(t.get("title") or url or "Unknown")[:500],
                    "webpage_url":  url,
                    "needs_refresh": bool(t.get("needs_refresh", True)),
                    "cache_key":    None,
                    "cache_path":   None,
                    "cache_mode":   "streaming",
                    "ext":          None,
                })
            pl["tracks"] = valid
            pl["updated_at"] = time.time()
            _save_playlist_atomic(path, pl)

        return {"ok": True, "track_count": len(pl.get("tracks", []))}

    @app.delete("/api/playlists/{playlist_id}/tracks/{index}")
    async def remove_track(
        playlist_id: str, index: int, ctx: _SessionContext = _auth
    ):
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None or not _can_view(pl, ctx):
            raise HTTPException(status_code=404, detail="Playlist not found")
        if not _can_edit(pl, ctx):
            raise HTTPException(status_code=403, detail="You do not have permission to edit this playlist")

        tracks = pl.get("tracks", [])
        if index < 0 or index >= len(tracks):
            raise HTTPException(status_code=404, detail="Track index out of range")
        tracks.pop(index)
        pl["tracks"] = tracks
        pl["updated_at"] = time.time()
        _save_playlist_atomic(path, pl)
        return {"ok": True, "track_count": len(tracks)}

    @app.post("/api/playlists/{playlist_id}/tracks")
    async def add_track(
        playlist_id: str, request: Request, ctx: _SessionContext = _auth
    ):
        body = await request.json()
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None or not _can_view(pl, ctx):
            raise HTTPException(status_code=404, detail="Playlist not found")
        if not _can_edit(pl, ctx):
            raise HTTPException(status_code=403, detail="You do not have permission to edit this playlist")

        url = str(body.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=422, detail="url is required")
        if not _is_youtube_url(url):
            raise HTTPException(status_code=422, detail="Only YouTube URLs are accepted")

        video_id = _extract_video_id(url)
        if not video_id:
            raise HTTPException(status_code=422, detail="Could not extract a YouTube video ID from that URL")

        canonical = _canonical_youtube_url(video_id)
        title = await _fetch_youtube_title(canonical) or f"youtu.be/{video_id}"

        tracks = pl.setdefault("tracks", [])
        for t in tracks:
            if str(t.get("id") or "") == video_id:
                return JSONResponse(
                    status_code=200,
                    content={"ok": True, "duplicate": True, "title": title, "id": video_id},
                )

        tracks.append({
            "id":           video_id,
            "title":        title,
            "webpage_url":  canonical,
            "needs_refresh": False,
            "added_at":     time.time(),
            "cache_key":    None,
            "cache_path":   None,
            "cache_mode":   "streaming",
            "ext":          None,
        })
        pl["updated_at"] = time.time()
        _save_playlist_atomic(path, pl)
        return {"ok": True, "title": title, "id": video_id}

    @app.get("/api/queue")
    async def get_queue(ctx: _SessionContext = _auth):
        if _bot_state is None:
            return []
        return [
            {
                "id":    str(t.get("id") or ""),
                "title": str(t.get("title") or t.get("webpage_url") or "Unknown"),
                "url":   str(t.get("webpage_url") or ""),
            }
            for t in (_bot_state.queue or [])
        ]

    @app.get("/api/now-playing")
    async def get_now_playing(ctx: _SessionContext = _auth):
        if _bot_state is None:
            return None
        track = _bot_state.current_track_info
        if not track:
            return None
        return {
            "id":    str(track.get("id") or ""),
            "title": str(track.get("title") or "Unknown"),
            "url":   str(track.get("webpage_url") or ""),
        }

    # -----------------------------------------------------------------------
    # YouTube oEmbed title lookup
    # -----------------------------------------------------------------------

    async def _fetch_youtube_title(url: str) -> Optional[str]:
        oembed = f"https://www.youtube.com/oembed?url={url}&format=json"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            ) as session:
                async with session.get(oembed) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("title") or None
        except Exception as exc:
            logger.debug(f"oEmbed lookup failed for {url}: {exc}")
        return None

    # -----------------------------------------------------------------------
    # Serve frontend (must be last)
    # -----------------------------------------------------------------------

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        index = os.path.join(_STATIC_DIR, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={"detail": "Frontend not found. See webui/frontend/index.html"},
        )

except ImportError:
    pass


# ---------------------------------------------------------------------------
# Configure — called once at startup from webui/__init__.py start()
# ---------------------------------------------------------------------------

def configure(*, playlists_dir: str, bot_state, secret_key: str, sessions):
    global _playlists_dir, _bot_state, _secret_key, _sessions
    _playlists_dir = playlists_dir
    _bot_state     = bot_state
    _secret_key    = secret_key
    _sessions      = sessions
```

- [ ] **Step 2: Verify syntax**

```bash
cd /Users/louniol/discordmusic && python -c "import ast; ast.parse(open('webui/server.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Verify the configure signature matches the caller**

```bash
grep -n "configure(" /Users/louniol/discordmusic/webui/__init__.py
```

Expected: the call includes `sessions=sessions`.

- [ ] **Step 4: Commit**

```bash
git add webui/server.py
git commit -m "feat(webui): per-user session auth, playlist scoping, /api/ping"
```

---

## Task 7: Update `webui/frontend/index.html`

**Files:**
- Modify: `webui/frontend/index.html`

Key changes:
1. On page load, read `?s=TOKEN` from the URL and store in sessionStorage, then strip it from the URL bar using `history.replaceState`.
2. Replace the password-based `LoginScreen` with a `NoSessionScreen` that tells the user to run `/webui` in Discord — no input field.
3. Add a `SessionExpiredScreen` for when the API returns 401 (shown after a valid session expires).
4. Add an `IpMismatchScreen` for 403 `ip_mismatch`.
5. The `onAuthError` callback now inspects the API error reason and sets state accordingly.
6. Add `api.ping()` mapped to `GET /api/ping` (the now-playing poll every 10s already keeps the session alive; ping is available for explicit heartbeat use).
7. Update the `makeApi` error handling: on 401, throw `Error("AUTH:inactive")` if the response body has `detail: "inactive"`, otherwise `Error("AUTH")`. On 403 `ip_mismatch`, throw `Error("AUTH:ip_mismatch")`.

- [ ] **Step 1: Replace `webui/frontend/index.html`**

The file is large so the complete replacement is below. Every change from the current version is marked with a comment `// CHANGED:` for auditability.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Music Bot</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;1,9..40,400&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.3/Sortable.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:           #0b0b0e;
      --panel:        #111116;
      --surface:      #18181f;
      --raised:       #1e1e28;
      --border:       #252532;
      --border-h:     #38384e;
      --accent:       #7c5cfc;
      --accent-dim:   rgba(124, 92, 252, 0.12);
      --accent-glow:  rgba(124, 92, 252, 0.35);
      --text:         #e4e4f0;
      --text-dim:     #aaaac0;
      --muted:        #50506a;
      --success:      #4ade80;
      --danger:       #ff4d6d;
      --warn:         #fbbf24;
      --font-display: 'Syne', sans-serif;
      --font-body:    'DM Sans', sans-serif;
      --font-mono:    'JetBrains Mono', monospace;
      --radius:       8px;
      --radius-lg:    14px;
    }

    html, body, #root { height: 100%; }
    body { font-family: var(--font-body); background: var(--bg); color: var(--text); font-size: 14px; line-height: 1.5; }

    /* subtle noise grain */
    body::after {
      content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 9998;
      opacity: 0.025;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='300' height='300' filter='url(%23n)'/%3E%3C/svg%3E");
      background-repeat: repeat;
    }

    .layout { display: flex; flex-direction: column; height: 100%; }

    /* ---- Topbar ---- */
    .topbar {
      display: flex; align-items: center; gap: 14px;
      padding: 0 20px; height: 52px;
      background: var(--panel); border-bottom: 1px solid var(--border);
      flex-shrink: 0; position: relative;
    }
    .topbar::after {
      content: ''; position: absolute; bottom: -1px; left: 0; right: 0; height: 1px;
      background: linear-gradient(90deg, transparent 0%, var(--accent-glow) 40%, var(--accent-glow) 60%, transparent 100%);
    }
    .topbar-logo {
      font-family: var(--font-display); font-weight: 800; font-size: 14px;
      letter-spacing: 0.1em; color: var(--text);
      display: flex; align-items: center; gap: 9px; flex-shrink: 0; user-select: none;
    }
    .logo-mark {
      width: 28px; height: 28px; border-radius: 8px;
      background: var(--accent-dim); border: 1px solid rgba(124,92,252,0.3);
      display: flex; align-items: center; justify-content: center;
      font-size: 13px; color: var(--accent);
    }
    .topbar-now { flex: 1; display: flex; align-items: center; gap: 10px; min-width: 0; padding: 0 8px; }
    .eq-bars { display: flex; align-items: flex-end; gap: 2px; height: 14px; flex-shrink: 0; }
    .eq-bar { width: 3px; background: var(--accent); border-radius: 2px; }
    .eq-bar:nth-child(1) { animation: eq1 0.9s ease-in-out infinite; }
    .eq-bar:nth-child(2) { animation: eq2 0.65s ease-in-out infinite; }
    .eq-bar:nth-child(3) { animation: eq3 1.05s ease-in-out infinite; }
    .eq-bar:nth-child(4) { animation: eq1 0.75s ease-in-out infinite reverse; }
    @keyframes eq1 { 0%,100% { height: 3px; } 50% { height: 12px; } }
    @keyframes eq2 { 0%,100% { height: 7px; } 50% { height: 5px; } }
    @keyframes eq3 { 0%,100% { height: 10px; } 50% { height: 3px; } }
    .np-title { font-size: 13px; font-weight: 500; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .np-idle { font-size: 12px; color: var(--muted); font-style: italic; }
    .topbar-logout {
      padding: 5px 12px; background: transparent; border: 1px solid var(--border);
      border-radius: var(--radius); color: var(--muted); font-family: var(--font-body);
      font-size: 12px; cursor: pointer; transition: all .15s; flex-shrink: 0;
    }
    .topbar-logout:hover { border-color: var(--border-h); color: var(--text); background: var(--surface); }

    /* ---- Body ---- */
    .body { display: flex; flex: 1; overflow: hidden; }

    /* ---- Sidebar ---- */
    .sidebar {
      width: 228px; flex-shrink: 0;
      background: var(--panel); border-right: 1px solid var(--border);
      display: flex; flex-direction: column; overflow-y: auto;
      padding: 10px 8px 16px;
    }
    .sidebar-section {
      padding: 10px 10px 5px;
      font-family: var(--font-display); font-size: 9.5px; font-weight: 700;
      letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted);
    }
    .sidebar-divider { height: 1px; background: var(--border); margin: 10px 6px; }
    .sidebar-item {
      display: flex; align-items: center; padding: 8px 10px; gap: 9px; cursor: pointer;
      border-radius: var(--radius); transition: background .12s; position: relative; overflow: hidden;
    }
    .sidebar-item:hover { background: var(--surface); }
    .sidebar-item.active { background: var(--accent-dim); }
    .sidebar-item.active::before {
      content: ''; position: absolute; left: 0; top: 20%; bottom: 20%;
      width: 2px; background: var(--accent); border-radius: 0 2px 2px 0;
      box-shadow: 0 0 8px var(--accent-glow);
    }
    .sidebar-icon { font-size: 12px; flex-shrink: 0; width: 16px; text-align: center; color: var(--muted); transition: color .12s; }
    .sidebar-item.active .sidebar-icon, .sidebar-item:hover .sidebar-icon { color: var(--text); }
    .sidebar-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; font-weight: 400; color: var(--text-dim); transition: color .12s; }
    .sidebar-item.active .sidebar-name, .sidebar-item:hover .sidebar-name { color: var(--text); }
    .sidebar-count {
      font-family: var(--font-mono); font-size: 10px; color: var(--muted);
      background: var(--surface); border: 1px solid var(--border);
      padding: 1px 6px; border-radius: 4px; flex-shrink: 0;
    }
    .sidebar-item.active .sidebar-count { background: rgba(124,92,252,0.1); border-color: rgba(124,92,252,0.2); color: var(--accent); }
    .sidebar-empty { padding: 10px 12px; color: var(--muted); font-size: 12px; line-height: 1.7; }
    .sidebar-empty code { font-family: var(--font-mono); font-size: 10.5px; background: var(--surface); border: 1px solid var(--border); padding: 1px 5px; border-radius: 3px; color: var(--accent); }

    /* ---- Main ---- */
    .main { flex: 1; overflow: hidden; display: flex; flex-direction: column; }

    /* ---- Editor header ---- */
    .editor-header {
      display: flex; align-items: center; gap: 10px;
      padding: 13px 18px; border-bottom: 1px solid var(--border);
      flex-shrink: 0; background: var(--panel);
    }
    .editor-title { font-family: var(--font-display); font-size: 15px; font-weight: 700; flex: 1; letter-spacing: 0.01em; }
    .pill { font-family: var(--font-mono); font-size: 10px; padding: 3px 8px; border-radius: 20px; border: 1px solid var(--border); background: var(--surface); color: var(--muted); flex-shrink: 0; font-weight: 500; }
    .pill.pub { background: rgba(74,222,128,0.07); color: var(--success); border-color: rgba(74,222,128,0.18); }
    .pill.readonly { background: rgba(251,191,36,0.07); color: var(--warn); border-color: rgba(251,191,36,0.18); }

    /* ---- Buttons ---- */
    button { border: none; border-radius: var(--radius); cursor: pointer; font-family: var(--font-body); font-size: 13px; font-weight: 500; transition: all .15s; }
    button:disabled { opacity: .35; cursor: not-allowed; }
    .btn { padding: 7px 14px; background: var(--surface); color: var(--text-dim); border: 1px solid var(--border); }
    .btn:hover:not(:disabled) { background: var(--raised); color: var(--text); border-color: var(--border-h); }
    .btn-primary { background: var(--accent); color: #fff; border: 1px solid var(--accent); box-shadow: 0 2px 12px rgba(124,92,252,0.22); }
    .btn-primary:hover:not(:disabled) { background: #6b4ee8; box-shadow: 0 4px 20px rgba(124,92,252,0.4); }
    .btn-sm { padding: 5px 11px; font-size: 12px; }
    .btn-icon { padding: 4px 7px; background: transparent; color: var(--muted); font-size: 12px; border: 1px solid transparent; border-radius: 6px; }
    .btn-icon:hover:not(:disabled) { color: var(--danger); background: rgba(255,77,109,0.08); border-color: rgba(255,77,109,0.18); }

    /* ---- Track list ---- */
    .track-scroll { flex: 1; overflow-y: auto; padding: 6px 0; }
    .track-list { list-style: none; padding: 4px 10px; display: flex; flex-direction: column; gap: 1px; }
    .track-item { display: flex; align-items: center; gap: 10px; padding: 9px 10px; border-radius: var(--radius); border: 1px solid transparent; transition: background .1s, border-color .1s; }
    .track-item:hover { background: var(--surface); border-color: var(--border); }
    .track-item.sortable-ghost { opacity: .25; background: var(--surface); }
    .track-item.sortable-drag { background: var(--raised); border-color: var(--accent); box-shadow: 0 8px 28px rgba(0,0,0,.55), 0 0 0 1px var(--accent); }
    .drag-handle { cursor: grab; color: var(--border); flex-shrink: 0; user-select: none; display: flex; flex-direction: column; gap: 3px; padding: 3px; border-radius: 4px; transition: color .1s; }
    .drag-handle-row { display: flex; gap: 3px; }
    .drag-handle-dot { width: 2px; height: 2px; border-radius: 50%; background: currentColor; }
    .track-item:hover .drag-handle { color: var(--muted); }
    .drag-handle:active { cursor: grabbing; }
    .track-num { font-family: var(--font-mono); color: var(--muted); font-size: 11px; width: 26px; text-align: right; flex-shrink: 0; }
    .track-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; font-weight: 500; }
    .track-id { font-family: var(--font-mono); font-size: 10px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex-shrink: 0; max-width: 130px; }
    .track-pending { font-family: var(--font-mono); font-size: 10px; color: var(--warn); background: rgba(251,191,36,0.08); border: 1px solid rgba(251,191,36,0.2); padding: 1px 6px; border-radius: 4px; flex-shrink: 0; }

    /* ---- Empty / splash / info screens ---- */
    .empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; gap: 10px; color: var(--muted); text-align: center; padding: 40px; }
    .empty-icon { font-size: 26px; opacity: 0.35; }
    .empty-text { font-size: 13px; }

    /* ---- Add bar ---- */
    .add-bar { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--border); flex-shrink: 0; background: var(--panel); }
    .add-input { flex: 1; padding: 8px 13px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); color: var(--text); font-family: var(--font-body); font-size: 13px; outline: none; transition: border-color .15s, box-shadow .15s; }
    .add-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-dim); }
    .add-input::placeholder { color: var(--muted); }

    /* ---- Unsaved bar ---- */
    .unsaved-bar { display: flex; align-items: center; gap: 10px; padding: 9px 16px; background: rgba(251,191,36,0.05); border-top: 1px solid rgba(251,191,36,0.18); flex-shrink: 0; }
    .unsaved-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--warn); box-shadow: 0 0 6px var(--warn); animation: pulse-warn 1.8s ease-in-out infinite; flex-shrink: 0; }
    @keyframes pulse-warn { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
    .unsaved-text { flex: 1; color: var(--warn); font-size: 12px; font-weight: 500; }

    /* ---- Queue ---- */
    .queue-item { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--radius); border: 1px solid transparent; transition: background .1s; }
    .queue-item:hover { background: var(--surface); border-color: var(--border); }
    .queue-num { font-family: var(--font-mono); font-size: 11px; color: var(--muted); width: 24px; text-align: right; flex-shrink: 0; }
    .queue-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
    .queue-id { font-family: var(--font-mono); font-size: 10px; color: var(--muted); flex-shrink: 0; max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    /* ---- Toast ---- */
    .toast-stack { position: fixed; bottom: 20px; right: 20px; display: flex; flex-direction: column; gap: 8px; z-index: 9997; pointer-events: none; }
    .toast { padding: 10px 14px; border-radius: var(--radius); font-size: 13px; font-weight: 500; color: var(--text); pointer-events: auto; animation: toast-in .22s cubic-bezier(0.34,1.5,0.64,1); max-width: 320px; display: flex; align-items: center; gap: 9px; }
    .toast.ok  { background: rgba(74,222,128,.1);  border: 1px solid rgba(74,222,128,.22); }
    .toast.err { background: rgba(255,77,109,.1);  border: 1px solid rgba(255,77,109,.22); }
    .toast.info { background: var(--raised); border: 1px solid var(--border); }
    .toast-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
    .toast.ok  .toast-dot { background: var(--success); }
    .toast.err .toast-dot { background: var(--danger); }
    .toast.info .toast-dot { background: var(--muted); }
    @keyframes toast-in { from { transform: translateX(16px) scale(0.95); opacity: 0; } to { transform: none; opacity: 1; } }

    /* ---- Full-page screens (no-session, expired, ip-mismatch) ---- */
    .gate-wrap {
      display: flex; align-items: center; justify-content: center; height: 100%;
      background: radial-gradient(ellipse 60% 40% at 50% -5%, rgba(124,92,252,0.1) 0%, transparent 70%), var(--bg);
    }
    .gate-card {
      background: var(--panel); border: 1px solid var(--border);
      border-radius: var(--radius-lg); padding: 44px 36px; width: 380px;
      display: flex; flex-direction: column; gap: 20px;
      position: relative; overflow: hidden; text-align: center;
    }
    .gate-card::before {
      content: ''; position: absolute; top: 0; left: 10%; right: 10%; height: 1px;
      background: linear-gradient(90deg, transparent, var(--accent), transparent);
    }
    .gate-icon {
      width: 52px; height: 52px; border-radius: 14px;
      background: var(--accent-dim); border: 1px solid rgba(124,92,252,0.25);
      display: flex; align-items: center; justify-content: center;
      font-size: 22px; color: var(--accent);
      box-shadow: 0 0 24px rgba(124,92,252,0.12);
      margin: 0 auto;
    }
    .gate-icon.warn { background: rgba(251,191,36,0.08); border-color: rgba(251,191,36,0.2); color: var(--warn); box-shadow: 0 0 24px rgba(251,191,36,0.08); }
    .gate-icon.danger { background: rgba(255,77,109,0.08); border-color: rgba(255,77,109,0.2); color: var(--danger); box-shadow: 0 0 24px rgba(255,77,109,0.08); }
    .gate-title { font-family: var(--font-display); font-size: 20px; font-weight: 800; letter-spacing: 0.02em; }
    .gate-body { font-size: 13px; color: var(--muted); line-height: 1.7; }
    .gate-body code { font-family: var(--font-mono); font-size: 11.5px; background: var(--surface); border: 1px solid var(--border); padding: 2px 6px; border-radius: 4px; color: var(--accent); }
    .gate-hint { font-size: 11px; color: var(--muted); opacity: 0.6; }

    /* ---- Spinner ---- */
    .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .7s linear infinite; vertical-align: middle; }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* ---- Splash ---- */
    .splash { flex: 1; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: var(--muted); text-align: center; padding: 40px; }
    .splash-arrow { font-size: 16px; opacity: 0.3; animation: nudge 2s ease-in-out infinite; }
    @keyframes nudge { 0%,100% { transform: translateX(0); } 50% { transform: translateX(-8px); } }
    .splash-text { font-size: 13px; }

    /* ---- Scrollbar ---- */
    ::-webkit-scrollbar { width: 5px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--muted); }
  </style>
</head>
<body>
  <div id="root"></div>

  <script type="text/babel">
    const { useState, useEffect, useRef, useCallback } = React;

    // -----------------------------------------------------------------------
    // Read the ?s=TOKEN param from the URL on page load.
    // Store in sessionStorage and strip from the address bar so the token
    // is not visible in browser history or the URL bar after the first load.
    // -----------------------------------------------------------------------
    (function extractUrlToken() {
      const params = new URLSearchParams(window.location.search);
      const t = params.get("s");
      if (t) {
        sessionStorage.setItem("mbtoken", t);
        // Replace the URL in history without the token param
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    })();

    // -----------------------------------------------------------------------
    // API client
    // -----------------------------------------------------------------------
    function makeApi(token) {
      const h = token
        ? { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" }
        : { "Content-Type": "application/json" };

      const req = async (method, path, body) => {
        const r = await fetch(path, {
          method,
          headers: h,
          body: body ? JSON.stringify(body) : undefined,
        });

        // Auth errors — distinguish inactive sessions from general auth failures
        if (r.status === 401) {
          let reason = "auth";
          try { const d = await r.json(); reason = d.detail || reason; } catch {}
          throw new Error(reason === "inactive" ? "AUTH:inactive" : "AUTH");
        }
        if (r.status === 403) {
          let reason = "forbidden";
          try { const d = await r.json(); reason = d.detail || reason; } catch {}
          throw new Error(reason === "ip_mismatch" ? "AUTH:ip_mismatch" : "FORBIDDEN");
        }

        if (!r.ok) {
          let msg = `HTTP ${r.status}`;
          try { const d = await r.json(); msg = d.detail || msg; } catch {}
          throw new Error(msg);
        }
        if (r.status === 204) return null;
        return r.json();
      };

      return {
        playlists:     () => req("GET",    "/api/playlists"),
        playlist:      id => req("GET",    `/api/playlists/${id}`),
        patchPlaylist: (id, body) => req("PATCH",  `/api/playlists/${id}`, body),
        removeTrack:   (id, idx)  => req("DELETE", `/api/playlists/${id}/tracks/${idx}`),
        addTrack:      (id, url)  => req("POST",   `/api/playlists/${id}/tracks`, { url }),
        queue:         () => req("GET",    "/api/queue"),
        nowPlaying:    () => req("GET",    "/api/now-playing"),
        ping:          () => req("GET",    "/api/ping"),
      };
    }

    // -----------------------------------------------------------------------
    // Toasts
    // -----------------------------------------------------------------------
    function useToasts() {
      const [toasts, setToasts] = useState([]);
      const add = useCallback((msg, type = "info") => {
        const id = Date.now();
        setToasts(t => [...t, { id, msg, type }]);
        setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3500);
      }, []);
      return [toasts, add];
    }

    // -----------------------------------------------------------------------
    // SortableJS drag-and-drop
    // -----------------------------------------------------------------------
    function useSort(listRef, items, onReorder) {
      const sortRef = useRef(null);
      useEffect(() => {
        if (!listRef.current) return;
        if (sortRef.current) sortRef.current.destroy();
        sortRef.current = Sortable.create(listRef.current, {
          animation: 150,
          handle: ".drag-handle",
          ghostClass: "sortable-ghost",
          dragClass: "sortable-drag",
          onEnd(evt) {
            if (evt.oldIndex === evt.newIndex) return;
            const next = [...items];
            const [moved] = next.splice(evt.oldIndex, 1);
            next.splice(evt.newIndex, 0, moved);
            onReorder(next);
          },
        });
        return () => { if (sortRef.current) { sortRef.current.destroy(); sortRef.current = null; } };
      }, [items, onReorder]);
    }

    // -----------------------------------------------------------------------
    // Gate screens — shown when there is no valid session
    // -----------------------------------------------------------------------

    // Shown when the page loads with no token at all
    function NoSessionScreen() {
      return (
        <div className="gate-wrap">
          <div className="gate-card">
            <div className="gate-icon">♪</div>
            <div className="gate-title">Music Bot</div>
            <div className="gate-body">
              Use <code>/webui</code> in Discord to get your private link.
              <br /><br />
              The bot will send you a link visible only to you.
              Open it to access your playlists.
            </div>
            <div className="gate-hint">Links expire after 2 minutes of inactivity.</div>
          </div>
        </div>
      );
    }

    // Shown when the API returns 401 inactive (session timed out)
    function SessionExpiredScreen({ onReset }) {
      return (
        <div className="gate-wrap">
          <div className="gate-card">
            <div className="gate-icon warn">⏱</div>
            <div className="gate-title">Session Expired</div>
            <div className="gate-body">
              Your session timed out after 2 minutes of inactivity.
              <br /><br />
              Use <code>/webui</code> in Discord to get a fresh link.
            </div>
            <button className="btn btn-sm" onClick={onReset} style={{alignSelf:"center"}}>
              Try again with a new link
            </button>
          </div>
        </div>
      );
    }

    // Shown when the API returns 403 ip_mismatch
    function IpMismatchScreen() {
      return (
        <div className="gate-wrap">
          <div className="gate-card">
            <div className="gate-icon danger">⚠</div>
            <div className="gate-title">Network Mismatch</div>
            <div className="gate-body">
              This link was opened from a different IP address than the one it was issued for.
              <br /><br />
              Use <code>/webui</code> in Discord from your current network to get a new link.
            </div>
          </div>
        </div>
      );
    }

    // -----------------------------------------------------------------------
    // Drag handle (dot grid)
    // -----------------------------------------------------------------------
    function DragHandle() {
      return (
        <span className="drag-handle" title="Drag to reorder">
          {[0,1,2].map(i => (
            <span key={i} className="drag-handle-row">
              <span className="drag-handle-dot" />
              <span className="drag-handle-dot" />
            </span>
          ))}
        </span>
      );
    }

    // -----------------------------------------------------------------------
    // Track item
    // -----------------------------------------------------------------------
    function TrackItem({ track, index, onRemove, canEdit }) {
      const id = track.id ? `youtu.be/${track.id}` : track.webpage_url;
      return (
        <li className="track-item">
          {canEdit && <DragHandle />}
          <span className="track-num">{index + 1}</span>
          <span className="track-title" title={track.title}>{track.title}</span>
          {track.needs_refresh && <span className="track-pending" title="Will resolve on first play">pending</span>}
          <span className="track-id" title={track.webpage_url}>{id}</span>
          {canEdit && (
            <button className="btn-icon" onClick={() => onRemove(index)} title="Remove">✕</button>
          )}
        </li>
      );
    }

    // -----------------------------------------------------------------------
    // Add track bar
    // -----------------------------------------------------------------------
    function AddTrackBar({ playlistId, api, onAdded, toast }) {
      const [val, setVal] = useState("");
      const [loading, setLoading] = useState(false);
      const submit = async e => {
        e.preventDefault();
        const url = val.trim();
        if (!url) return;
        if (!url.includes("youtube.com") && !url.includes("youtu.be")) {
          toast("Only YouTube URLs are supported.", "err");
          return;
        }
        setLoading(true);
        try {
          const res = await api.addTrack(playlistId, url);
          setVal("");
          if (res.duplicate) {
            toast(`Already in playlist: ${res.title}`, "info");
          } else {
            toast(`Added: ${res.title}`, "ok");
            onAdded();
          }
        } catch (ex) {
          toast(`Failed to add: ${ex.message}`, "err");
        } finally { setLoading(false); }
      };
      return (
        <form className="add-bar" onSubmit={submit}>
          <input
            className="add-input"
            type="text"
            placeholder="Paste a YouTube URL to add a track…"
            value={val}
            onChange={e => setVal(e.target.value)}
          />
          <button className="btn btn-primary btn-sm" disabled={loading || !val.trim()}>
            {loading ? <span className="spinner" /> : "Add"}
          </button>
        </form>
      );
    }

    // -----------------------------------------------------------------------
    // Playlist editor
    // -----------------------------------------------------------------------
    function PlaylistEditor({ playlistId, api, toast }) {
      const [pl, setPl]       = useState(null);
      const [tracks, setTracks] = useState([]);
      const [dirty, setDirty] = useState(false);
      const [saving, setSaving] = useState(false);
      const [loading, setLoading] = useState(true);
      const listRef = useRef(null);

      const load = useCallback(async () => {
        setLoading(true);
        try {
          const data = await api.playlist(playlistId);
          setPl(data);
          setTracks(data.tracks || []);
          setDirty(false);
        } catch (ex) {
          toast(`Failed to load playlist: ${ex.message}`, "err");
        } finally { setLoading(false); }
      }, [playlistId]);

      useEffect(() => { load(); }, [load]);

      const reorder = useCallback(next => { setTracks(next); setDirty(true); }, []);
      useSort(listRef, tracks, reorder);

      const removeTrack = idx => { setTracks(t => t.filter((_, i) => i !== idx)); setDirty(true); };

      const save = async () => {
        setSaving(true);
        try {
          await api.patchPlaylist(playlistId, { tracks });
          setDirty(false);
          toast("Playlist saved.", "ok");
        } catch (ex) {
          toast(`Save failed: ${ex.message}`, "err");
        } finally { setSaving(false); }
      };

      const discard = () => { setTracks(pl?.tracks || []); setDirty(false); };

      if (loading) return <div className="empty"><span className="spinner" /></div>;
      if (!pl) return <div className="empty"><div className="empty-text">Playlist not found.</div></div>;

      // The server sends can_edit = true/false based on the session's permissions
      const canEdit = pl.can_edit !== false;

      return (
        <>
          <div className="editor-header">
            <div className="editor-title">{pl.name}</div>
            <span className={`pill${pl.visibility === "public" ? " pub" : ""}`}>{pl.visibility}</span>
            {!canEdit && <span className="pill readonly">read-only</span>}
            <span className="pill">{tracks.length} {tracks.length === 1 ? "track" : "tracks"}</span>
          </div>

          <div className="track-scroll">
            {tracks.length === 0
              ? <div className="empty">
                  <div className="empty-icon">♪</div>
                  <div className="empty-text">No tracks yet.{canEdit ? " Add one below." : ""}</div>
                </div>
              : <ul ref={canEdit ? listRef : null} className="track-list">
                  {tracks.map((t, i) => (
                    <TrackItem
                      key={t.id || `idx-${i}`}
                      track={t}
                      index={i}
                      onRemove={removeTrack}
                      canEdit={canEdit}
                    />
                  ))}
                </ul>
            }
          </div>

          {canEdit && dirty && (
            <div className="unsaved-bar">
              <span className="unsaved-dot" />
              <span className="unsaved-text">Unsaved changes</span>
              <button className="btn btn-sm" onClick={discard}>Discard</button>
              <button className="btn btn-primary btn-sm" disabled={saving} onClick={save}>
                {saving ? <><span className="spinner" /> Saving…</> : "Save"}
              </button>
            </div>
          )}

          {canEdit && (
            <AddTrackBar playlistId={playlistId} api={api} onAdded={load} toast={toast} />
          )}
        </>
      );
    }

    // -----------------------------------------------------------------------
    // Queue panel
    // -----------------------------------------------------------------------
    function QueuePanel({ api, toast }) {
      const [queue, setQueue] = useState(null);
      const [loading, setLoading] = useState(true);

      const load = async () => {
        setLoading(true);
        try { setQueue(await api.queue()); }
        catch (ex) { toast(`Failed to load queue: ${ex.message}`, "err"); }
        finally { setLoading(false); }
      };

      useEffect(() => { load(); }, []);

      return (
        <>
          <div className="editor-header">
            <div className="editor-title">Queue</div>
            <span className="pill">{queue ? `${queue.length} ${queue.length === 1 ? "track" : "tracks"}` : "…"}</span>
            <button className="btn btn-sm" onClick={load}>↻ Refresh</button>
          </div>
          <div className="track-scroll">
            {loading
              ? <div className="empty"><span className="spinner" /></div>
              : !queue || queue.length === 0
                ? <div className="empty">
                    <div className="empty-icon">♫</div>
                    <div className="empty-text">Queue is empty.</div>
                  </div>
                : <ul className="track-list">
                    {queue.map((t, i) => (
                      <li key={t.id || i} className="queue-item">
                        <span className="queue-num">{i + 1}</span>
                        <span className="queue-title" title={t.title}>{t.title}</span>
                        <span className="queue-id">{t.id ? `youtu.be/${t.id}` : t.url}</span>
                      </li>
                    ))}
                  </ul>
            }
          </div>
        </>
      );
    }

    // -----------------------------------------------------------------------
    // EQ bars (now-playing indicator)
    // -----------------------------------------------------------------------
    function EqBars() {
      return (
        <div className="eq-bars">
          <div className="eq-bar" style={{height:'5px'}} />
          <div className="eq-bar" style={{height:'11px'}} />
          <div className="eq-bar" style={{height:'7px'}} />
          <div className="eq-bar" style={{height:'13px'}} />
        </div>
      );
    }

    // -----------------------------------------------------------------------
    // Main app
    // -----------------------------------------------------------------------
    function App() {
      // authState: "ok" | "none" | "expired" | "ip_mismatch"
      const [authState, setAuthState] = useState(
        () => sessionStorage.getItem("mbtoken") ? "ok" : "none"
      );
      const [token, setToken] = useState(() => sessionStorage.getItem("mbtoken") || "");

      const [playlists, setPlaylists] = useState([]);
      const [selected, setSelected]   = useState(null);
      const [nowPlaying, setNowPlaying] = useState(null);
      const [toasts, addToast] = useToasts();

      const api = makeApi(token);

      // Called when any API request returns an auth error
      const onAuthError = useCallback((errMsg) => {
        sessionStorage.removeItem("mbtoken");
        setToken("");
        if (errMsg === "AUTH:inactive") {
          setAuthState("expired");
        } else if (errMsg === "AUTH:ip_mismatch") {
          setAuthState("ip_mismatch");
        } else {
          // Unknown or revoked token — go back to no-session screen
          setAuthState("none");
        }
      }, []);

      // Wrap every API method to intercept auth errors
      const safeApi = {};
      for (const [k, fn] of Object.entries(api)) {
        safeApi[k] = async (...args) => {
          try { return await fn(...args); }
          catch (ex) {
            if (ex.message.startsWith("AUTH")) { onAuthError(ex.message); throw ex; }
            throw ex;
          }
        };
      }

      // Load playlist sidebar
      const loadPlaylists = useCallback(async () => {
        if (authState !== "ok" || !token) return;
        try {
          const data = await safeApi.playlists();
          setPlaylists(data.filter(p => p.type !== "favorites"));
        } catch {}
      }, [token, authState]);

      useEffect(() => { loadPlaylists(); }, [loadPlaylists]);

      // Poll now-playing every 10s — this also acts as the session heartbeat
      // (each successful call updates last_active on the server).
      useEffect(() => {
        if (authState !== "ok" || !token) return;
        const poll = async () => { try { setNowPlaying(await safeApi.nowPlaying()); } catch {} };
        poll();
        const id = setInterval(poll, 10000);
        return () => clearInterval(id);
      }, [token, authState]);

      // Reset to no-session screen (used from SessionExpiredScreen button)
      const handleReset = () => {
        setAuthState("none");
        setToken("");
        setPlaylists([]);
        setSelected(null);
        setNowPlaying(null);
      };

      // ---- Render gate screens before the main layout ----
      if (authState === "none")        return <NoSessionScreen />;
      if (authState === "expired")     return <SessionExpiredScreen onReset={handleReset} />;
      if (authState === "ip_mismatch") return <IpMismatchScreen />;

      return (
        <div className="layout">

          <div className="topbar">
            <div className="topbar-logo">
              <div className="logo-mark">♪</div>
              MUSIC BOT
            </div>
            <div className="topbar-now">
              {nowPlaying
                ? <><EqBars /><span className="np-title">{nowPlaying.title}</span></>
                : <span className="np-idle">Nothing playing</span>
              }
            </div>
            <button className="topbar-logout" onClick={() => {
              sessionStorage.removeItem("mbtoken");
              setToken("");
              setAuthState("none");
            }}>
              Logout
            </button>
          </div>

          <div className="body">
            <div className="sidebar">
              <div className="sidebar-section">Playlists</div>
              {playlists.map(p => (
                <div
                  key={p.id}
                  className={`sidebar-item${selected === p.id ? " active" : ""}`}
                  onClick={() => setSelected(p.id)}
                >
                  <span className="sidebar-icon">{p.visibility === "public" ? "◉" : "◎"}</span>
                  <span className="sidebar-name" title={p.name}>{p.name}</span>
                  <span className="sidebar-count">{p.track_count}</span>
                </div>
              ))}
              {playlists.length === 0 && (
                <div className="sidebar-empty">
                  No playlists yet.<br />
                  Use <code>/playlist new</code> in Discord.
                </div>
              )}
              <div className="sidebar-divider" />
              <div className="sidebar-section">Bot</div>
              <div
                className={`sidebar-item${selected === "queue" ? " active" : ""}`}
                onClick={() => setSelected("queue")}
              >
                <span className="sidebar-icon">▷</span>
                <span className="sidebar-name">Queue</span>
              </div>
            </div>

            <div className="main">
              {selected === null && (
                <div className="splash">
                  <span className="splash-arrow">←</span>
                  <span className="splash-text">Select a playlist to edit it.</span>
                </div>
              )}
              {selected === "queue" && <QueuePanel api={safeApi} toast={addToast} />}
              {selected && selected !== "queue" && (
                <PlaylistEditor
                  key={selected}
                  playlistId={selected}
                  api={safeApi}
                  toast={addToast}
                />
              )}
            </div>
          </div>

          <div className="toast-stack">
            {toasts.map(t => (
              <div key={t.id} className={`toast ${t.type}`}>
                <span className="toast-dot" />
                {t.msg}
              </div>
            ))}
          </div>

        </div>
      );
    }

    ReactDOM.createRoot(document.getElementById("root")).render(<App />);
  </script>
</body>
</html>
```

- [ ] **Step 2: Verify the file was written correctly**

```bash
grep -c "extractUrlToken\|NoSessionScreen\|SessionExpiredScreen\|IpMismatchScreen\|AUTH:inactive\|AUTH:ip_mismatch" /Users/louniol/discordmusic/webui/frontend/index.html
```

Expected: `6` (one match per term)

- [ ] **Step 3: Commit**

```bash
git add webui/frontend/index.html
git commit -m "feat(webui): per-user session gate, URL token extraction, error screens"
```

---

## Task 8: Update docs

**Files:**
- Modify: `docs/COMMANDS.md`
- Modify: `docs/FEATURES.md`

- [ ] **Step 1: Add `/webui` to `docs/COMMANDS.md`**

Find the `## spotify` section and add a `## web ui` commands section before it:

```markdown
## web ui

requires `WEBUI_ENABLED=true` in `.env` and `WEBUI_PUBLIC_URL` set to where the web UI is reachable.

| command | purpose |
| --- | --- |
| `/webui` | get a private, ephemeral link to the playlist editor. the link is visible only to you in Discord. it expires after 2 minutes of inactivity. use `/webui` again to get a fresh link at any time. |
```

- [ ] **Step 2: Update the `## web ui` section in `docs/FEATURES.md`**

Find the existing `## web ui` section and replace it with:

```markdown
## web ui

activate by setting `WEBUI_ENABLED=true`, `WEBUI_SECRET_KEY=<strong-random-key>`, and `WEBUI_PUBLIC_URL=<your-url>` in `.env`, then install the optional dependencies (`uvicorn`, `fastapi`; uncomment the lines in `requirements.txt`). the server starts inside the bot's asyncio event loop — no separate process needed.

**per-user sessions:** each user runs `/webui` in Discord and receives an ephemeral link (visible only to them). the link contains a one-time session token issued by the bot. the first HTTP request from the browser binds the session to that IP address. any subsequent request from a different IP is rejected. sessions expire automatically after 2 minutes of inactivity — the browser tab's now-playing poll (every 10s) keeps the session alive as long as the tab is open. when a session expires, the browser shows a clear message telling the user to use `/webui` to get a new link.

**playlist scoping:** each session is limited to what that Discord user can access. a user sees their own playlists, playlists where they are a manager, and public playlists. they can only edit playlists they own or manage. locked playlists can only be edited by the owner. admin sessions (users who are admins in Discord) see and can edit everything.

**`WEBUI_SECRET_KEY` admin bypass:** the secret key still works as a direct bearer token for admin access without going through Discord. this is the fallback for bot operators who need to access the UI without the bot running. it should be a strong random value and never shared.

**binding and networking:**

- default: `127.0.0.1:8765` — local only. set `WEBUI_BIND_HOST=0.0.0.0` for LAN/homelab.
- for public access: `cloudflared tunnel --url http://127.0.0.1:8765` gives a public https url. set `WEBUI_PUBLIC_URL` to that url so `/webui` produces correct links.
- for homelab reverse proxy: set `WEBUI_BIND_HOST` to your internal ip, point your ingress at that host:port, and set `WEBUI_PUBLIC_URL` to the externally reachable url. the server passes `proxy_headers=True` so `X-Forwarded-For` is respected for IP locking.

**what it does:**

- browse playlists you can access in a sidebar.
- open any editable playlist, reorder tracks by dragging, remove tracks, add tracks by YouTube URL.
- read-only view for playlists you can see but not edit.
- read-only live queue view with manual refresh.
- now-playing in the top bar, polled every 10 seconds.
- session expiry and IP mismatch surface clear messages in the UI, not generic errors.

**what it does not do** (by design): create, delete, or rename playlists; edit favorites; reorder the live queue.
```

- [ ] **Step 3: Commit**

```bash
git add docs/COMMANDS.md docs/FEATURES.md
git commit -m "docs: document /webui command and per-user session model"
```

---

## Self-review checklist

**Spec coverage:**
- [x] `/webui` Discord command → ephemeral link → Task 5
- [x] Token in URL `?s=TOKEN` → stripped from address bar → Task 7
- [x] IP binding on first request → Task 6 `_require_session`
- [x] 2-minute inactivity expiry → `INACTIVITY_TTL=120` in sessions.py
- [x] Session sweeper every 30s → Task 4
- [x] Playlist scoping to user's own playlists → Task 6 `_can_view`, `_can_edit`
- [x] Read-only mode for viewable-but-not-editable playlists → Task 7 `canEdit`
- [x] "Session expired" screen → Task 7 `SessionExpiredScreen`
- [x] "IP mismatch" screen → Task 7 `IpMismatchScreen`
- [x] "Use /webui in Discord" screen when no token → Task 7 `NoSessionScreen`
- [x] Admin bypass via `WEBUI_SECRET_KEY` still works → Task 6 legacy key path
- [x] Docs updated → Task 8
- [x] `WEBUI_PUBLIC_URL` env var → Tasks 2 and 5

**No placeholders:** all tasks have complete code.

**Type consistency:** `_SessionContext.discord_user_id` (int) ↔ `pl.get("owner_user_id")` (int from `make_playlist_metadata`) ↔ `session.discord_user_id` (int, stored at creation in `/webui` command). Manager IDs compared as strings in both `_can_view` and `_can_edit` to handle storage format variation.
