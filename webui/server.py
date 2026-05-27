"""
FastAPI server for the music bot web UI.

Auth: Bearer token — either a per-user session token (from /webui Discord command)
or the WEBUI_SECRET_KEY admin bypass.  Per-user sessions are IP-bound after first
request and expire after INACTIVITY_TTL seconds.

Admin endpoints are gated on ctx.is_admin; non-admin requests get 403.
"""

import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import time
from collections import deque
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory log buffer — installed on the root logger by configure()
# ---------------------------------------------------------------------------

class _MemLogHandler(logging.Handler):
    def __init__(self, maxlen: int = 400):
        super().__init__()
        self._buf: deque = deque(maxlen=maxlen)
        self.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord):
        try:
            self._buf.append({
                "ts":    record.created,
                "level": record.levelname,
                "name":  record.name,
                "msg":   self.format(record),
            })
        except Exception:
            pass

    def records(self, min_level: str = "DEBUG", source: str = "") -> list:
        lvl = getattr(logging, min_level.upper(), logging.DEBUG)
        result = [r for r in self._buf if logging.getLevelName(r["level"]) >= lvl]
        if source:
            src = source.lower()
            result = [r for r in result if src in (r.get("name") or "").lower()]
        return result


_log_handler = _MemLogHandler()

# ---------------------------------------------------------------------------
# Module-level state — set once by configure()
# ---------------------------------------------------------------------------

_playlists_dir: str = ""
_bot_state = None        # webui.BotState
_secret_key: str = ""
_sessions = None         # webui.sessions.SessionStore
_base_dir: str = ""      # project root (parent of playlists/)
_guesser = None          # quote_guesser.QuoteGuesser or None

# ---------------------------------------------------------------------------
# Lazy FastAPI app
# ---------------------------------------------------------------------------

try:
    from fastapi import FastAPI, HTTPException, Depends, Header, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    import aiohttp

    app = FastAPI(title="DISCORDMUSIC", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    _STATIC_DIR = os.path.join(os.path.dirname(__file__), "frontend")

    # -----------------------------------------------------------------------
    # Session context
    # -----------------------------------------------------------------------

    class _SessionContext:
        __slots__ = ("discord_user_id", "discord_username", "is_admin", "token")

        def __init__(self, discord_user_id: int, is_admin: bool,
                     token: str = "", discord_username: str = ""):
            self.discord_user_id = discord_user_id
            self.discord_username = discord_username
            self.is_admin = is_admin
            self.token = token

    # -----------------------------------------------------------------------
    # Auth
    # -----------------------------------------------------------------------

    def _get_client_ip(request: Request) -> str:
        if request.client and request.client.host:
            return request.client.host
        return "unknown"

    async def _require_session(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> _SessionContext:
        token: str = ""
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()

        if not token:
            raise HTTPException(status_code=401, detail="Authorization required")

        if _sessions is not None:
            session = _sessions.get(token)
            if session is not None:
                ip = _get_client_ip(request)
                if session.bound_ip is None:
                    session.bound_ip = ip
                elif session.bound_ip != ip:
                    raise HTTPException(status_code=403, detail="ip_mismatch")
                _sessions.touch(session)
                return _SessionContext(
                    discord_user_id=session.discord_user_id,
                    discord_username=getattr(session, "discord_username", ""),
                    is_admin=session.is_admin,
                    token=token,
                )
            if token in _sessions._sessions:
                raise HTTPException(status_code=401, detail="inactive")

        if _secret_key and hmac.compare_digest(token, _secret_key):
            return _SessionContext(discord_user_id=0, is_admin=True, token=token,
                                   discord_username="admin")

        raise HTTPException(status_code=401, detail="Authorization required")

    _auth = Depends(_require_session)

    def _require_admin(ctx: _SessionContext = _auth) -> _SessionContext:
        if not ctx.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")
        return ctx

    _admin_auth = Depends(_require_admin)

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

    def _playlist_summary(pl: dict, *, ctx: "_SessionContext | None" = None) -> dict:
        s = {
            "id":             pl.get("id"),
            "name":           pl.get("name"),
            "visibility":     pl.get("visibility"),
            "type":           pl.get("type", "playlist"),
            "track_count":    len(pl.get("tracks", [])),
            "owner":          pl.get("owner_discord_name"),
            "owner_id":       pl.get("owner_user_id"),
            "locked":         bool(pl.get("locked")),
            "cache_mode":     pl.get("cache_mode", "streaming"),
            "admin_disabled": bool(pl.get("admin_disabled")),
            "manager_user_ids": list(pl.get("manager_user_ids", [])),
        }
        if ctx is not None:
            s["can_edit"] = _can_edit(pl, ctx)
        return s

    def _sanitize_track(t: dict) -> dict:
        vid = str(t.get("id") or "")
        url = str(t.get("webpage_url") or "")
        if vid and not url.startswith("http"):
            url = _canonical_youtube_url(vid)
        return {
            "id":             vid,
            "title":          str(t.get("title") or url or "Unknown"),
            "webpage_url":    url,
            "needs_refresh":  bool(t.get("needs_refresh")),
            "admin_disabled": bool(t.get("admin_disabled")),
        }

    # -----------------------------------------------------------------------
    # Permission helpers
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
        if pl.get("admin_disabled"):
            return False
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
    # Favorites helpers
    # -----------------------------------------------------------------------

    def _find_favorites_path(user_id: int) -> tuple[str, dict | None]:
        """Return (path, playlist) for the user's favorites, or (path, None) if not found."""
        folder = f"favorites-{user_id}"
        path = os.path.join(_playlists_dir, folder, "metadata.json")
        if os.path.isfile(path):
            try:
                return path, _load_playlist(path)
            except Exception:
                pass
        return path, None

    def _create_favorites(user_id: int, username: str) -> tuple[str, dict]:
        folder = f"favorites-{user_id}"
        path = os.path.join(_playlists_dir, folder, "metadata.json")
        now = time.time()
        pl = {
            "id":                 f"fav-{user_id}",
            "name":               f"{username} favorites",
            "type":               "favorites",
            "generated_at":       now,
            "updated_at":         now,
            "locked":             True,
            "visibility":         "private",
            "owner_user_id":      user_id,
            "owner_discord_name": username,
            "manager_user_ids":   [],
            "tracks":             [],
            "folder":             folder,
            "cache_mode":         "favorites",
            "predownloaded":      False,
            "deleted":            False,
        }
        _save_playlist_atomic(path, pl)
        return path, pl

    # -----------------------------------------------------------------------
    # oEmbed title lookup
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
    # Routes — session & player
    # -----------------------------------------------------------------------

    @app.get("/api/ping")
    async def ping(ctx: _SessionContext = _auth):
        logger.debug(f"[ping] user={ctx.discord_user_id} admin={ctx.is_admin}")
        return {"ok": True}

    @app.get("/api/me")
    async def get_me(ctx: _SessionContext = _auth):
        logger.debug(f"[me] user={ctx.discord_user_id} ({ctx.discord_username}) admin={ctx.is_admin}")
        return {
            "user_id":  ctx.discord_user_id,
            "username": ctx.discord_username,
            "is_admin": ctx.is_admin,
        }

    @app.get("/api/now-playing")
    async def get_now_playing(ctx: _SessionContext = _auth):
        if _bot_state is None:
            logger.debug("[now-playing] bot_state is None")
            return None
        track = _bot_state.current_track_info
        if not track:
            logger.debug(f"[now-playing] user={ctx.discord_user_id} idle paused={_bot_state.is_paused}")
            return {"playing": False, "paused": _bot_state.is_paused}
        vid = str(track.get("id") or "")
        logger.debug(
            f"[now-playing] user={ctx.discord_user_id} "
            f"vid={vid} title='{track.get('title', '')[:60]}' "
            f"paused={_bot_state.is_paused}"
        )
        return {
            "playing":   True,
            "paused":    _bot_state.is_paused,
            "id":        vid,
            "title":     str(track.get("title") or "Unknown"),
            "url":       str(track.get("webpage_url") or (_canonical_youtube_url(vid) if vid else "")),
            "thumbnail": f"https://img.youtube.com/vi/{vid}/mqdefault.jpg" if vid else None,
        }

    @app.post("/api/player/skip")
    async def player_skip(ctx: _SessionContext = _auth):
        if _bot_state is None:
            raise HTTPException(status_code=503, detail="Bot state unavailable")
        ok = _bot_state.skip()
        logger.info(f"[player/skip] user={ctx.discord_user_id} ({ctx.discord_username}) result={ok}")
        return {"ok": ok, "msg": "Skipped" if ok else "Nothing to skip"}

    @app.post("/api/player/pause")
    async def player_pause(ctx: _SessionContext = _auth):
        if _bot_state is None:
            raise HTTPException(status_code=503, detail="Bot state unavailable")
        if _bot_state.is_paused:
            ok = _bot_state.resume()
            logger.info(f"[player/pause] user={ctx.discord_user_id} action=resume result={ok}")
            return {"ok": ok, "paused": False}
        ok = _bot_state.pause()
        logger.info(f"[player/pause] user={ctx.discord_user_id} action=pause result={ok}")
        return {"ok": ok, "paused": True}

    @app.post("/api/player/star")
    async def player_star(ctx: _SessionContext = _auth):
        logger.debug(f"[player/star] user={ctx.discord_user_id} ({ctx.discord_username})")
        if _bot_state is None:
            raise HTTPException(status_code=503, detail="Bot state unavailable")
        track = _bot_state.current_track_info
        if not track:
            raise HTTPException(status_code=404, detail="Nothing is playing")
        if not ctx.discord_user_id:
            raise HTTPException(status_code=403, detail="Cannot star without a Discord user session")

        vid = str(track.get("id") or "")
        title = str(track.get("title") or "Unknown")
        url = str(track.get("webpage_url") or (_canonical_youtube_url(vid) if vid else ""))

        path, pl = _find_favorites_path(ctx.discord_user_id)
        if pl is None:
            path, pl = _create_favorites(ctx.discord_user_id,
                                          ctx.discord_username or f"user-{ctx.discord_user_id}")

        # Check if already starred
        for t in pl.get("tracks", []):
            if str(t.get("id") or "") == vid and vid:
                return {"ok": True, "added": False, "title": title}

        pl.setdefault("tracks", []).append({
            "id":            vid,
            "title":         title,
            "webpage_url":   url,
            "needs_refresh": False,
            "added_at":      time.time(),
            "cache_key":     None,
            "cache_path":    None,
            "cache_mode":    "streaming",
            "ext":           None,
        })
        pl["updated_at"] = time.time()
        _save_playlist_atomic(path, pl)
        return {"ok": True, "added": True, "title": title}

    # -----------------------------------------------------------------------
    # Routes — queue
    # -----------------------------------------------------------------------

    @app.get("/api/queue")
    async def get_queue(ctx: _SessionContext = _auth):
        if _bot_state is None:
            logger.debug("[queue] bot_state is None")
            return []
        q = _bot_state.queue or []
        logger.debug(f"[queue] user={ctx.discord_user_id} queue_len={len(q)}")
        return [
            {
                "id":    str(t.get("id") or ""),
                "title": str(t.get("title") or t.get("webpage_url") or "Unknown"),
                "url":   str(t.get("webpage_url") or ""),
            }
            for t in q
        ]

    @app.post("/api/queue/add")
    async def queue_add(request: Request, ctx: _SessionContext = _auth):
        body = await request.json()
        url = str(body.get("url") or "").strip()
        logger.debug(f"[queue/add] user={ctx.discord_user_id} url='{url[:80]}'")
        if not url:
            raise HTTPException(status_code=422, detail="url is required")
        if not _is_youtube_url(url):
            raise HTTPException(status_code=422, detail="Only YouTube URLs are accepted")
        video_id = _extract_video_id(url)
        if not video_id:
            raise HTTPException(status_code=422, detail="Could not extract a YouTube video ID")
        canonical = _canonical_youtube_url(video_id)
        title = await _fetch_youtube_title(canonical) or f"youtu.be/{video_id}"
        if _bot_state is None:
            raise HTTPException(status_code=503, detail="Bot state unavailable")
        _bot_state.add_to_queue({
            "id":            video_id,
            "title":         title,
            "webpage_url":   canonical,
            "needs_refresh": False,
            "added_via":     "webui",
        })
        logger.info(
            f"[queue/add] user={ctx.discord_user_id} ({ctx.discord_username}) "
            f"queued vid={video_id} title='{title[:60]}'"
        )
        return {"ok": True, "title": title, "id": video_id}

    # -----------------------------------------------------------------------
    # Routes — playlists
    # -----------------------------------------------------------------------

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
                result.append(_playlist_summary(pl, ctx=ctx))
            except Exception:
                continue
        result.sort(key=lambda p: str(p.get("name") or "").lower())
        logger.debug(f"[playlists] user={ctx.discord_user_id} visible={len(result)}")
        return result

    @app.get("/api/playlists/{playlist_id}")
    async def get_playlist(playlist_id: str, ctx: _SessionContext = _auth):
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None or not _can_view(pl, ctx):
            raise HTTPException(status_code=404, detail="Playlist not found")
        return {
            **_playlist_summary(pl, ctx=ctx),
            "tracks": [_sanitize_track(t) for t in pl.get("tracks", [])],
        }

    @app.post("/api/playlists")
    async def create_playlist(request: Request, ctx: _SessionContext = _auth):
        if not ctx.discord_user_id:
            raise HTTPException(status_code=403, detail="Cannot create playlist without a Discord user session")
        body = await request.json()
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name is required")
        if len(name) > 80:
            raise HTTPException(status_code=422, detail="name is too long (max 80 characters)")
        visibility = str(body.get("visibility") or "private").lower()
        if visibility not in ("public", "private"):
            visibility = "private"

        # Generate a safe ID and folder name
        playlist_id = secrets.token_urlsafe(8)
        safe_name = re.sub(r"[^\w\- ]", "", name).strip().replace(" ", "-").lower()[:40]
        folder = f"{safe_name}-{playlist_id}"
        path = os.path.join(_playlists_dir, folder, "metadata.json")

        now = time.time()
        pl = {
            "id":                 playlist_id,
            "name":               name,
            "type":               "playlist",
            "generated_at":       now,
            "updated_at":         now,
            "locked":             False,
            "visibility":         visibility,
            "owner_user_id":      ctx.discord_user_id,
            "owner_discord_name": ctx.discord_username or f"user-{ctx.discord_user_id}",
            "manager_user_ids":   [],
            "tracks":             [],
            "folder":             folder,
            "cache_mode":         "follow_global",
            "predownloaded":      False,
            "deleted":            False,
        }
        _save_playlist_atomic(path, pl)
        logger.info(
            f"[playlists/create] user={ctx.discord_user_id} ({ctx.discord_username}) "
            f"name='{name}' visibility={visibility} id={playlist_id}"
        )
        return _playlist_summary(pl, ctx=ctx)

    @app.patch("/api/playlists/{playlist_id}")
    async def patch_playlist(playlist_id: str, request: Request, ctx: _SessionContext = _auth):
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
    async def remove_track(playlist_id: str, index: int, ctx: _SessionContext = _auth):
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
    async def add_track(playlist_id: str, request: Request, ctx: _SessionContext = _auth):
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
            raise HTTPException(status_code=422, detail="Could not extract a YouTube video ID")
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

    # -----------------------------------------------------------------------
    # Routes — playlist managers (owner or admin only)
    # -----------------------------------------------------------------------

    @app.get("/api/playlists/{playlist_id}/managers")
    async def get_managers(playlist_id: str, ctx: _SessionContext = _auth):
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None or not _can_view(pl, ctx):
            raise HTTPException(status_code=404, detail="Playlist not found")
        uid = ctx.discord_user_id
        is_owner = ctx.is_admin or (uid and uid == pl.get("owner_user_id"))
        if not is_owner:
            raise HTTPException(status_code=403, detail="Only the owner can manage moderators")
        return {"manager_user_ids": list(pl.get("manager_user_ids", []))}

    @app.post("/api/playlists/{playlist_id}/managers")
    async def add_manager(playlist_id: str, request: Request, ctx: _SessionContext = _auth):
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None or not _can_view(pl, ctx):
            raise HTTPException(status_code=404, detail="Playlist not found")
        uid = ctx.discord_user_id
        is_owner = ctx.is_admin or (uid and uid == pl.get("owner_user_id"))
        if not is_owner:
            raise HTTPException(status_code=403, detail="Only the owner can add moderators")
        body = await request.json()
        new_uid = body.get("user_id")
        if not new_uid:
            raise HTTPException(status_code=422, detail="user_id is required")
        try:
            new_uid = int(new_uid)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="user_id must be an integer")
        if new_uid == pl.get("owner_user_id"):
            raise HTTPException(status_code=422, detail="Owner is already the owner")
        managers = pl.setdefault("manager_user_ids", [])
        if str(new_uid) not in [str(x) for x in managers]:
            managers.append(new_uid)
            pl["updated_at"] = time.time()
            _save_playlist_atomic(path, pl)
            logger.info(
                f"[playlists/managers/add] user={ctx.discord_user_id} ({ctx.discord_username}) "
                f"added manager {new_uid} to playlist {playlist_id}"
            )
        return {"ok": True, "manager_user_ids": list(pl.get("manager_user_ids", []))}

    @app.delete("/api/playlists/{playlist_id}/managers/{manager_user_id}")
    async def remove_manager(playlist_id: str, manager_user_id: int, ctx: _SessionContext = _auth):
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None or not _can_view(pl, ctx):
            raise HTTPException(status_code=404, detail="Playlist not found")
        uid = ctx.discord_user_id
        is_owner = ctx.is_admin or (uid and uid == pl.get("owner_user_id"))
        if not is_owner:
            raise HTTPException(status_code=403, detail="Only the owner can remove moderators")
        managers = pl.get("manager_user_ids", [])
        new_managers = [x for x in managers if str(x) != str(manager_user_id)]
        pl["manager_user_ids"] = new_managers
        pl["updated_at"] = time.time()
        _save_playlist_atomic(path, pl)
        logger.info(
            f"[playlists/managers/remove] user={ctx.discord_user_id} ({ctx.discord_username}) "
            f"removed manager {manager_user_id} from playlist {playlist_id}"
        )
        return {"ok": True, "manager_user_ids": list(pl.get("manager_user_ids", []))}

    # -----------------------------------------------------------------------
    # Routes — admin: all playlists view + disable/enable playlists/tracks
    # -----------------------------------------------------------------------

    @app.get("/api/admin/playlists")
    async def admin_list_playlists(ctx: _SessionContext = _admin_auth):
        """Admin view of all playlists including disabled ones."""
        result = []
        for path in _playlist_metadata_files():
            try:
                pl = _load_playlist(path)
                if pl.get("deleted"):
                    continue
                result.append(_playlist_summary(pl, ctx=ctx))
            except Exception:
                continue
        result.sort(key=lambda p: str(p.get("name") or "").lower())
        logger.debug(f"[admin/playlists] admin={ctx.discord_user_id} total={len(result)}")
        return result

    @app.get("/api/admin/playlists/{playlist_id}")
    async def admin_get_playlist(playlist_id: str, ctx: _SessionContext = _admin_auth):
        """Admin view of a single playlist including all track details."""
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        return {
            **_playlist_summary(pl, ctx=ctx),
            "tracks": [_sanitize_track(t) for t in pl.get("tracks", [])],
        }

    @app.patch("/api/admin/playlists/{playlist_id}")
    async def admin_patch_playlist(playlist_id: str, request: Request, ctx: _SessionContext = _admin_auth):
        """Admin can disable/enable an entire playlist."""
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        body = await request.json()
        changed = False
        if "admin_disabled" in body:
            pl["admin_disabled"] = bool(body["admin_disabled"])
            changed = True
            logger.info(
                f"[admin/playlists/patch] admin={ctx.discord_user_id} ({ctx.discord_username}) "
                f"playlist={playlist_id} admin_disabled={pl['admin_disabled']}"
            )
        if changed:
            pl["updated_at"] = time.time()
            _save_playlist_atomic(path, pl)
        return {"ok": True, "admin_disabled": bool(pl.get("admin_disabled"))}

    @app.patch("/api/admin/playlists/{playlist_id}/tracks/{index}")
    async def admin_patch_track(playlist_id: str, index: int, request: Request,
                                 ctx: _SessionContext = _admin_auth):
        """Admin can disable/enable a specific track."""
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        tracks = pl.get("tracks", [])
        if index < 0 or index >= len(tracks):
            raise HTTPException(status_code=404, detail="Track index out of range")
        body = await request.json()
        if "admin_disabled" in body:
            tracks[index]["admin_disabled"] = bool(body["admin_disabled"])
            pl["updated_at"] = time.time()
            _save_playlist_atomic(path, pl)
            logger.info(
                f"[admin/playlists/tracks/patch] admin={ctx.discord_user_id} ({ctx.discord_username}) "
                f"playlist={playlist_id} index={index} admin_disabled={tracks[index]['admin_disabled']}"
            )
        return {"ok": True, "admin_disabled": bool(tracks[index].get("admin_disabled"))}

    @app.delete("/api/admin/playlists/{playlist_id}/tracks/{index}")
    async def admin_remove_track(playlist_id: str, index: int, ctx: _SessionContext = _admin_auth):
        """Admin can remove any track from any playlist."""
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        tracks = pl.get("tracks", [])
        if index < 0 or index >= len(tracks):
            raise HTTPException(status_code=404, detail="Track index out of range")
        removed = tracks.pop(index)
        pl["tracks"] = tracks
        pl["updated_at"] = time.time()
        _save_playlist_atomic(path, pl)
        logger.info(
            f"[admin/playlists/tracks/remove] admin={ctx.discord_user_id} ({ctx.discord_username}) "
            f"playlist={playlist_id} removed index={index} title='{removed.get('title', '')[:60]}'"
        )
        return {"ok": True, "track_count": len(tracks)}

    # -----------------------------------------------------------------------
    # Routes — favorites
    # -----------------------------------------------------------------------

    @app.get("/api/favorites")
    async def get_favorites(ctx: _SessionContext = _auth):
        if not ctx.discord_user_id:
            return {"tracks": [], "exists": False}
        path, pl = _find_favorites_path(ctx.discord_user_id)
        if pl is None:
            return {"tracks": [], "exists": False}
        return {
            "exists":      True,
            "track_count": len(pl.get("tracks", [])),
            "tracks":      [_sanitize_track(t) for t in pl.get("tracks", [])],
        }

    @app.delete("/api/favorites/{index}")
    async def remove_favorite(index: int, ctx: _SessionContext = _auth):
        if not ctx.discord_user_id:
            raise HTTPException(status_code=403, detail="No Discord user session")
        path, pl = _find_favorites_path(ctx.discord_user_id)
        if pl is None:
            raise HTTPException(status_code=404, detail="No favorites playlist")
        tracks = pl.get("tracks", [])
        if index < 0 or index >= len(tracks):
            raise HTTPException(status_code=404, detail="Index out of range")
        tracks.pop(index)
        pl["tracks"] = tracks
        pl["updated_at"] = time.time()
        _save_playlist_atomic(path, pl)
        return {"ok": True}

    @app.post("/api/favorites/add-to-playlist/{playlist_id}")
    async def favorites_add_to_playlist(
        playlist_id: str, request: Request, ctx: _SessionContext = _auth
    ):
        """Copy selected favorites tracks into a playlist."""
        body = await request.json()
        indices = body.get("indices", [])
        if not isinstance(indices, list):
            raise HTTPException(status_code=422, detail="indices must be a list")

        _, fav = _find_favorites_path(ctx.discord_user_id)
        if fav is None:
            raise HTTPException(status_code=404, detail="No favorites playlist")
        fav_tracks = fav.get("tracks", [])

        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None or not _can_view(pl, ctx):
            raise HTTPException(status_code=404, detail="Playlist not found")
        if not _can_edit(pl, ctx):
            raise HTTPException(status_code=403, detail="No edit permission")

        dest_tracks = pl.setdefault("tracks", [])
        existing_ids = {str(t.get("id") or "") for t in dest_tracks}
        added = 0
        for i in indices:
            if not isinstance(i, int) or i < 0 or i >= len(fav_tracks):
                continue
            t = fav_tracks[i]
            vid = str(t.get("id") or "")
            if vid in existing_ids:
                continue
            dest_tracks.append({**t, "added_at": time.time()})
            existing_ids.add(vid)
            added += 1
        pl["updated_at"] = time.time()
        _save_playlist_atomic(path, pl)
        return {"ok": True, "added": added}

    # -----------------------------------------------------------------------
    # Routes — Spotify import (requires SPOTIFY_ENABLED + dependencies)
    # -----------------------------------------------------------------------

    @app.post("/api/spotify/search")
    async def spotify_search(request: Request, ctx: _SessionContext = _auth):
        """
        Fetch a Spotify playlist and search YouTube Music for each track.
        Returns up to 50 tracks with confidence scores.
        Requires SPOTIFY_ENABLED=true and spotify dependencies installed.
        """
        try:
            import spotify_import as _sp
        except ImportError:
            raise HTTPException(status_code=503,
                detail="Spotify module not available. Set SPOTIFY_ENABLED=true and install dependencies.")

        if _sp.check_dependencies():
            raise HTTPException(status_code=503,
                detail="Spotify dependencies not installed. Run: pip install spotipy ytmusicapi rapidfuzz")

        body = await request.json()
        url = str(body.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=422, detail="url is required")

        try:
            spotify_tracks = await _sp.fetch_spotify_tracks(url)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Spotify fetch failed: {exc}")

        # Search YouTube for up to 30 tracks concurrently (limited batch)
        batch = spotify_tracks[:30]
        results = []

        async def _search_one(st):
            matches = await _sp.search_youtube_for_track(st)
            best = matches[0] if matches else None
            return {
                "spotify_name":   st.name,
                "spotify_artist": st.artist,
                "duration_ms":    st.duration_ms,
                "match":          {
                    "id":         best.video_id if best else None,
                    "title":      best.title if best else None,
                    "url":        _canonical_youtube_url(best.video_id) if best else None,
                    "confidence": round(best.confidence, 3) if best else 0,
                } if best else None,
            }

        tasks = [_search_one(st) for st in batch]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return {"tracks": results, "total": len(spotify_tracks), "returned": len(results)}

    # -----------------------------------------------------------------------
    # Routes — admin: status, logs
    # -----------------------------------------------------------------------

    @app.get("/api/status")
    async def get_status(ctx: _SessionContext = _admin_auth):
        bs = _bot_state
        queue_len = len(bs.queue) if bs else 0
        track = bs.current_track_info if bs else None

        # Count playlists / tracks
        pl_count, tr_count = 0, 0
        for path in _playlist_metadata_files():
            try:
                pl = _load_playlist(path)
                if not pl.get("deleted") and pl.get("type") != "favorites":
                    pl_count += 1
                    tr_count += len(pl.get("tracks", []))
            except Exception:
                pass

        disk = bs.disk_usage(_base_dir) if bs else {}

        return {
            "uptime_seconds":   round(bs.uptime_seconds, 1) if bs else None,
            "memory_mb":        round(bs.process_memory_mb, 1) if bs and bs.process_memory_mb else None,
            "queue_length":     queue_len,
            "is_playing":       bs.is_playing if bs else False,
            "is_paused":        bs.is_paused if bs else False,
            "current_track":    track.get("title") if track else None,
            "playlist_count":   pl_count,
            "total_tracks":     tr_count,
            "disk":             disk,
        }

    @app.get("/api/logs")
    async def get_logs(level: str = "INFO", source: str = "",
                       ctx: _SessionContext = _admin_auth):
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level.upper() not in valid:
            level = "INFO"
        records = _log_handler.records(min_level=level.upper(), source=source.strip())
        logger.debug(
            f"[logs] admin={ctx.discord_user_id} level={level} "
            f"source='{source}' returned={len(records)}"
        )
        return {"records": records}

    # -----------------------------------------------------------------------
    # Routes — admin: audit log, user permissions, config, cache
    # -----------------------------------------------------------------------

    @app.get("/api/admin/config")
    async def admin_config(ctx: _SessionContext = _admin_auth):
        """Read-only snapshot of key runtime settings."""
        bs = _bot_state
        logger.debug(f"[admin/config] admin={ctx.discord_user_id}")
        if bs is None:
            return {}
        snap = bs.get_config_snapshot()
        snap["guesser_enabled"] = _guesser is not None
        snap["playlists_dir"] = _playlists_dir
        return snap

    @app.get("/api/admin/audit")
    async def admin_audit(limit: int = 100, ctx: _SessionContext = _admin_auth):
        """Return the last *limit* entries from runtime-audit.json."""
        logger.debug(f"[admin/audit] admin={ctx.discord_user_id} limit={limit}")
        audit_path = os.path.join(_base_dir, "runtime-audit.json")
        if not os.path.isfile(audit_path):
            return {"events": [], "total": 0}
        try:
            with open(audit_path) as f:
                events = json.load(f)
            if not isinstance(events, list):
                return {"events": [], "total": 0}
            limit = max(1, min(500, limit))
            return {"events": events[-limit:], "total": len(events)}
        except Exception as exc:
            logger.error(f"[admin/audit] failed to read audit log: {exc}")
            raise HTTPException(status_code=500, detail="Failed to read audit log")

    @app.get("/api/admin/users")
    async def admin_users(ctx: _SessionContext = _admin_auth):
        """Return current user permission/restriction data."""
        logger.debug(f"[admin/users] admin={ctx.discord_user_id}")
        perms_path = os.path.join(_base_dir, "user-permissions.json")
        if not os.path.isfile(perms_path):
            return {"users": [], "note": "No user-permissions.json found."}
        try:
            with open(perms_path) as f:
                data = json.load(f)
            users_list = []
            if isinstance(data, dict):
                # Each key is a user_id string
                for uid, entry in data.items():
                    if not isinstance(entry, dict):
                        continue
                    users_list.append({
                        "user_id":  uid,
                        "username": entry.get("discord_name") or entry.get("username") or f"user-{uid}",
                        "groups":   list(entry.get("groups", [])),
                        "updated_at": entry.get("updated_at"),
                    })
            users_list.sort(key=lambda u: str(u.get("username") or "").lower())
            return {"users": users_list}
        except Exception as exc:
            logger.error(f"[admin/users] failed to read permissions: {exc}")
            raise HTTPException(status_code=500, detail="Failed to read user permissions")

    @app.post("/api/admin/cache/clear")
    async def admin_cache_clear(ctx: _SessionContext = _admin_auth):
        """Remove old/zero-byte files from the cache directory."""
        cache_dir = os.path.join(_base_dir, "cache")
        logger.info(f"[admin/cache/clear] admin={ctx.discord_user_id} ({ctx.discord_username}) cache_dir={cache_dir}")
        if not os.path.isdir(cache_dir):
            return {"ok": True, "removed": 0, "note": "Cache directory not found."}
        removed = 0
        errors = 0
        for fname in os.listdir(cache_dir):
            fpath = os.path.join(cache_dir, fname)
            try:
                # Only remove empty / zero-byte files (safe cleanup)
                if os.path.isfile(fpath) and os.path.getsize(fpath) == 0:
                    os.unlink(fpath)
                    removed += 1
                    logger.debug(f"[cache/clear] removed zero-byte file: {fname}")
            except OSError as exc:
                logger.warning(f"[cache/clear] could not remove {fname}: {exc}")
                errors += 1
        logger.info(f"[admin/cache/clear] removed={removed} errors={errors}")
        return {"ok": True, "removed": removed, "errors": errors}

    # -----------------------------------------------------------------------
    # Routes — quote guesser
    # -----------------------------------------------------------------------

    def _require_guesser():
        if _guesser is None:
            raise HTTPException(
                status_code=503,
                detail="Quote guesser not enabled. Set QUOTE_GUESSER_ENABLED=true in .env.",
            )

    @app.get("/api/guesser/today")
    async def guesser_today(ctx: _SessionContext = _auth):
        """Return today's challenge (quote text + choices) and the caller's state."""
        _require_guesser()
        if not ctx.discord_user_id:
            raise HTTPException(status_code=403, detail="Need a Discord user session to play")
        logger.debug(f"[guesser/today] user={ctx.discord_user_id} ({ctx.discord_username})")
        challenge = _guesser.get_today_challenge(ctx.discord_user_id)
        if challenge is None:
            raise HTTPException(
                status_code=503,
                detail="No attributed quotes available. Run /backup_teekkari_quotes first.",
            )
        return challenge

    @app.post("/api/guesser/guess")
    async def guesser_guess(request: Request, ctx: _SessionContext = _auth):
        """Submit a guess for today's challenge."""
        _require_guesser()
        if not ctx.discord_user_id:
            raise HTTPException(status_code=403, detail="Need a Discord user session to play")
        body = await request.json()
        choice = str(body.get("choice") or "").strip()
        if not choice:
            raise HTTPException(status_code=422, detail="choice is required")
        logger.debug(
            f"[guesser/guess] user={ctx.discord_user_id} ({ctx.discord_username}) "
            f"choice='{choice[:60]}'"
        )
        result = _guesser.submit_guess(ctx.discord_user_id, ctx.discord_username or f"user-{ctx.discord_user_id}", choice)
        if "error" in result:
            raise HTTPException(status_code=409, detail=result["error"])
        return result

    @app.get("/api/guesser/leaderboard")
    async def guesser_leaderboard(ctx: _SessionContext = _auth):
        """Return the all-time leaderboard."""
        _require_guesser()
        logger.debug(f"[guesser/leaderboard] user={ctx.discord_user_id}")
        return {"entries": _guesser.get_leaderboard(limit=15)}

    # -----------------------------------------------------------------------
    # Serve frontend (must be last)
    # -----------------------------------------------------------------------

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        index = os.path.join(_STATIC_DIR, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        return JSONResponse(status_code=503,
            content={"detail": "Frontend not found. See webui/frontend/index.html"})

except ImportError:
    pass


# ---------------------------------------------------------------------------
# Configure — called once at startup
# ---------------------------------------------------------------------------

def configure(*, playlists_dir: str, bot_state, secret_key: str, sessions,
              guesser=None):
    global _playlists_dir, _bot_state, _secret_key, _sessions, _base_dir, _guesser
    _playlists_dir = playlists_dir
    _bot_state     = bot_state
    _secret_key    = secret_key
    _sessions      = sessions
    _base_dir      = os.path.dirname(playlists_dir)
    _guesser       = guesser

    # Install memory log handler on root logger (idempotent)
    root = logging.getLogger()
    if _log_handler not in root.handlers:
        # Ensure handler captures DEBUG records regardless of root level
        _log_handler.setLevel(logging.DEBUG)
        root.addHandler(_log_handler)
    logger.info(
        f"[webui] configured: playlists_dir={playlists_dir} "
        f"guesser={'yes' if guesser else 'no'}"
    )
