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
        __slots__ = ("discord_user_id", "is_admin", "token")

        def __init__(self, discord_user_id: int, is_admin: bool, token: str = ""):
            self.discord_user_id = discord_user_id
            self.is_admin = is_admin
            self.token = token

    # -----------------------------------------------------------------------
    # Auth dependency
    # -----------------------------------------------------------------------

    def _get_client_ip(request: Request) -> str:
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
                    session.bound_ip = client_ip
                elif session.bound_ip != client_ip:
                    raise HTTPException(status_code=403, detail="ip_mismatch")
                _sessions.touch(session)
                return _SessionContext(
                    discord_user_id=session.discord_user_id,
                    is_admin=session.is_admin,
                    token=token,
                )
            # Token string existed in our store but the session is now dead.
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
            "id":            vid,
            "title":         str(t.get("title") or url or "Unknown"),
            "webpage_url":   url,
            "needs_refresh": bool(t.get("needs_refresh")),
        }

    # -----------------------------------------------------------------------
    # Scoping helpers
    # -----------------------------------------------------------------------

    def _can_view(pl: dict, ctx: _SessionContext) -> bool:
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
        if ctx.is_admin:
            return True
        uid = ctx.discord_user_id
        if not uid:
            return False
        is_owner = (uid == pl.get("owner_user_id"))
        is_manager = str(uid) in [str(x) for x in pl.get("manager_user_ids", [])]
        if not (is_owner or is_manager):
            return False
        if pl.get("locked") and not is_owner:
            return False
        return True

    # -----------------------------------------------------------------------
    # API routes
    # -----------------------------------------------------------------------

    @app.get("/api/ping")
    async def ping(ctx: _SessionContext = _auth):
        """Lightweight endpoint to keep the session alive."""
        return {"ok": True}

    @app.get("/api/playlists")
    async def list_playlists(ctx: _SessionContext = _auth):
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
                    "id":            vid,
                    "title":         str(t.get("title") or url or "Unknown")[:500],
                    "webpage_url":   url,
                    "needs_refresh": bool(t.get("needs_refresh", True)),
                    "cache_key":     None,
                    "cache_path":    None,
                    "cache_mode":    "streaming",
                    "ext":           None,
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
            "id":            video_id,
            "title":         title,
            "webpage_url":   canonical,
            "needs_refresh": False,
            "added_at":      time.time(),
            "cache_key":     None,
            "cache_path":    None,
            "cache_mode":    "streaming",
            "ext":           None,
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
