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
from dataclasses import dataclass
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
