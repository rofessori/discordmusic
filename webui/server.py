"""
FastAPI server for the music bot web UI.

All state is accessed through the BotState object injected via configure().
Playlist data is read/written from the same JSON files the bot uses.
"""

import json
import logging
import os
import re
import tempfile
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (set once by configure())
# ---------------------------------------------------------------------------

_playlists_dir: str = ""
_bot_state = None        # webui.BotState instance
_secret_key: str = ""

# ---------------------------------------------------------------------------
# Lazy FastAPI app (imported only when needed)
# ---------------------------------------------------------------------------

try:
    from fastapi import FastAPI, HTTPException, Depends, Header, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
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
    # Auth
    # -----------------------------------------------------------------------

    async def _require_auth(authorization: Optional[str] = Header(None)):
        if not _secret_key:
            return  # no key configured — warn was already logged at startup
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Authorization required")
        token = authorization.split(" ", 1)[1].strip()
        # Constant-time comparison to resist timing attacks
        import hmac
        if not hmac.compare_digest(token, _secret_key):
            raise HTTPException(status_code=403, detail="Invalid token")

    _auth = Depends(_require_auth)

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
        """Returns (path, playlist_dict) or (None, None)."""
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
            "locked":      bool(pl.get("locked")),
        }

    def _sanitize_track(t: dict) -> dict:
        """Return only the fields the frontend needs; strip absolute paths."""
        vid = str(t.get("id") or "")
        url = str(t.get("webpage_url") or "")
        if vid and not url.startswith("http"):
            url = _canonical_youtube_url(vid)
        return {
            "id":          vid,
            "title":       str(t.get("title") or url or "Unknown"),
            "webpage_url": url,
            "needs_refresh": bool(t.get("needs_refresh")),
        }

    # -----------------------------------------------------------------------
    # API routes
    # -----------------------------------------------------------------------

    @app.get("/api/playlists", dependencies=[_auth])
    async def list_playlists():
        result = []
        for path in _playlist_metadata_files():
            try:
                pl = _load_playlist(path)
                if pl.get("deleted"):
                    continue
                result.append(_playlist_summary(pl))
            except Exception:
                continue
        result.sort(key=lambda p: str(p.get("name") or "").lower())
        return result

    @app.get("/api/playlists/{playlist_id}", dependencies=[_auth])
    async def get_playlist(playlist_id: str):
        _, pl = _find_playlist_by_id(playlist_id)
        if pl is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        return {
            **_playlist_summary(pl),
            "tracks": [_sanitize_track(t) for t in pl.get("tracks", [])],
        }

    @app.patch("/api/playlists/{playlist_id}", dependencies=[_auth])
    async def patch_playlist(playlist_id: str, request: Request):
        body = await request.json()
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None:
            raise HTTPException(status_code=404, detail="Playlist not found")

        if "tracks" in body:
            incoming = body["tracks"]
            if not isinstance(incoming, list):
                raise HTTPException(status_code=422, detail="tracks must be a list")
            # Validate each track entry
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

    @app.delete("/api/playlists/{playlist_id}/tracks/{index}", dependencies=[_auth])
    async def remove_track(playlist_id: str, index: int):
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None:
            raise HTTPException(status_code=404, detail="Playlist not found")
        tracks = pl.get("tracks", [])
        if index < 0 or index >= len(tracks):
            raise HTTPException(status_code=404, detail="Track index out of range")
        tracks.pop(index)
        pl["tracks"] = tracks
        pl["updated_at"] = time.time()
        _save_playlist_atomic(path, pl)
        return {"ok": True, "track_count": len(tracks)}

    @app.post("/api/playlists/{playlist_id}/tracks", dependencies=[_auth])
    async def add_track(playlist_id: str, request: Request):
        body = await request.json()
        path, pl = _find_playlist_by_id(playlist_id)
        if pl is None:
            raise HTTPException(status_code=404, detail="Playlist not found")

        url = str(body.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=422, detail="url is required")

        if not _is_youtube_url(url):
            raise HTTPException(status_code=422, detail="Only YouTube URLs are accepted")

        video_id = _extract_video_id(url)
        if not video_id:
            raise HTTPException(status_code=422, detail="Could not extract a YouTube video ID from that URL")

        canonical = _canonical_youtube_url(video_id)

        # Try to get the title via YouTube oEmbed (no API key needed)
        title = await _fetch_youtube_title(canonical)
        if not title:
            title = f"youtu.be/{video_id}"

        tracks = pl.setdefault("tracks", [])
        # Check for duplicate
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

    @app.get("/api/queue", dependencies=[_auth])
    async def get_queue():
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

    @app.get("/api/now-playing", dependencies=[_auth])
    async def get_now_playing():
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
    # Serve frontend (must be last — catches all non-API paths)
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
    # FastAPI/uvicorn not installed — app object will not exist.
    # The check in webui/__init__.py catches this before starting.
    pass


# ---------------------------------------------------------------------------
# Configure function called once at startup
# ---------------------------------------------------------------------------

def configure(*, playlists_dir: str, bot_state, secret_key: str):
    global _playlists_dir, _bot_state, _secret_key
    _playlists_dir = playlists_dir
    _bot_state = bot_state
    _secret_key = secret_key
