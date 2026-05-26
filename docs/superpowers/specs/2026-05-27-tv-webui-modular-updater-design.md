# TV/WebUI Modular Refactor + Updater Script — Design Spec

**Date:** 2026-05-27

---

## 1. Problem Statement

Four independent improvements are needed:

1. **TV stream accepts only HLS with tvkaista-specific headers.** Any other URL type (generic HTTP stream, RTMP, YouTube live) gets the same headers injected, which breaks them.
2. **No day-2 updater script.** `setup_assistant.py` covers first-run only. Re-running pip, checking for missing env vars, reconfiguring webui/TV settings requires manual work.
3. **WebUI has no setup tutorial.** The FEATURES.md section covers capabilities but not step-by-step activation/hosting.
4. **COMMANDS.md is missing the `/tv` command group.**

---

## 2. Scope

| Component | Change |
|-----------|--------|
| `tv_stream.py` | Full refactor: stream-type detection, yt-dlp YouTube extraction, per-type FFmpeg options |
| `main.py` | ~5-line change in `_start_tv_stream` to resolve URL before playback |
| `update.py` | New interactive updater script (stdlib-only) |
| `docs/WEBUI_SETUP.md` | New step-by-step hosting tutorial |
| `docs/COMMANDS.md` | Add `/tv` commands section |
| `docs/FEATURES.md` | Update TV section with new stream types |

**Out of scope:** changes to the playlist/queue/favorites systems, webui frontend changes, setup_assistant.py changes.

---

## 3. tv_stream.py — Architecture

### 3.1 Stream Type Detection

```
detect_stream_type(url) → str
```

| URL pattern | Detected type | Notes |
|-------------|---------------|-------|
| `*tvkaista*` | `hls_tvkaista` | Inject full curl-fingerprint headers |
| `rtmp://` | `rtmp` | No reconnect flags; FFmpeg handles RTMP natively |
| `youtube.com/*` or `youtu.be/*` | `youtube` | Must be resolved via yt-dlp before playback |
| `*.m3u8*` | `hls_generic` | Reconnect flags only, no custom headers |
| everything else | `http` | Reconnect flags, no custom headers |

### 3.2 FFmpeg Options

`build_ffmpeg_before_options(url: str) -> str`

- `hls_tvkaista` → `-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -headers <tvkaista headers>`
- `hls_generic`, `http`, `youtube` (post-resolution) → `-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5`
- `rtmp` → `""` (empty — reconnect flags are not valid for RTMP)

The resolved URL (not the original YouTube URL) is passed to this function.

### 3.3 yt-dlp URL Resolution

`resolve_stream_url(url: str) -> str` (async)

- Non-YouTube URLs: returned as-is.
- YouTube URLs: runs `yt_dlp.YoutubeDL` in a thread executor (non-blocking), extracting `format: bestaudio/best`.
  - Returns `info["url"]` or `info["manifest_url"]` — whichever is a valid URL.
  - On error: raises `RuntimeError` with a short message so `_start_tv_stream` can surface it to the user.
- YouTube stream URLs expire. On each restart the original URL is stored in `client.tv_stream_url` and re-resolved by `_tv_restart`.

### 3.4 main.py change (only section that changes)

```python
async def _start_tv_stream(channel, url):
    if _tv_module is None:
        return
    voice = active_voice_client(channel.guild)
    if not voice:
        return
    try:
        resolved_url = await _tv_module.resolve_stream_url(url)
    except Exception as exc:
        ...error handling → notify channel...
        return
    before_opts = _tv_module.build_ffmpeg_before_options(resolved_url)
    player = discord.FFmpegPCMAudio(resolved_url, before_options=before_opts)
    ...rest unchanged...
```

`client.tv_stream_url` always stores the **original** URL so YouTube live streams can be re-extracted on reconnect.

### 3.5 check_dependencies update

Add yt-dlp import check (it's already required so this is just a sanity gate, not a new dep).

---

## 4. update.py — Architecture

Standalone stdlib-only script. Works before the venv exists.

### Phases

1. **Venv phase** — check if `venv/` exists; offer to create it. Run `pip install -r requirements.txt` (or upgrade).
2. **Env health phase** — read `.env`, check:
   - Required: `bot_token`, `my_guild`
   - Optional core: `admin_user_id`, `quotes_id`
   - Per module: `WEBUI_SECRET_KEY` if `WEBUI_ENABLED=true`, `TV_STREAM_URL` or `TV_WEBHOOK_SECRET` if `TV_ENABLED=true`, Spotify creds if `SPOTIFY_ENABLED=true`
3. **WebUI config phase** (if `WEBUI_ENABLED=true`) — show current `WEBUI_BIND_HOST`, `WEBUI_PORT`. Ask if user wants to change bind host for LAN/public access. Offer to write the change.
4. **TV config phase** (if `TV_ENABLED=true`) — show current stream URL and webhook config. Offer to update `TV_STREAM_URL` or `TV_WEBHOOK_SECRET`.
5. **Health summary** — print status for all checks. Green ✓ / Yellow ⚠ / Red ✗.

### Design constraints

- Never writes `.env` without explicit user confirmation.
- Backs up `.env` before any write (same as setup_assistant.py).
- F1/:save / F2/:quit controls inherited from setup_assistant.py pattern.
- Can be re-run as a health check with no side effects (read-only mode if user declines all writes).

---

## 5. docs/WEBUI_SETUP.md — Contents

1. Prerequisites (uvicorn, fastapi — uncomment lines in requirements.txt)
2. Enable: set `WEBUI_ENABLED=true` in `.env`
3. Generate a secret key: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
4. Set `WEBUI_SECRET_KEY=<value>` in `.env`
5. Install deps: `venv/bin/pip install uvicorn fastapi`
6. Restart the bot
7. Open `http://localhost:8765` — enter the secret key
8. **Cloudflare Tunnel (quick public):** `cloudflared tunnel --url http://127.0.0.1:8765` — works instantly, no config
9. **Homelab reverse proxy:** set `WEBUI_BIND_HOST=0.0.0.0` (or your internal IP), point ingress at that host:port
10. Security notes: the token lives in sessionStorage (cleared on tab close), bearer auth with constant-time comparison, no secrets in committed code

---

## 6. Docs updates

### COMMANDS.md

Add `/tv` section:

| command | purpose |
|---------|---------|
| `/tv start [url]` | Start a live stream in your voice channel. Supports HLS (.m3u8), HTTP audio/video streams, RTMP, and YouTube livestreams. Defaults to `TV_STREAM_URL` in `.env`. Admin only. |
| `/tv stop` | Stop the live stream and disconnect. Admin only. |
| `/tv update <url>` | Swap in a new stream URL while the stream is live — no reconnect needed. Admin only. |

### FEATURES.md

Update the `## live TV / stream` section (to be added — it's currently not present in FEATURES.md) with:
- Supported stream types: HLS, generic HTTP audio, RTMP, YouTube livestreams
- URL is passed directly; for YouTube live URLs, the bot resolves the real stream URL via yt-dlp automatically
- Watchdog reconnect (up to `TV_MAX_RESTARTS` in `TV_RESTART_WINDOW_SECONDS`)
- `/tv update <url>` for live URL swap without stopping
- Optional webhook server (`TV_WEBHOOK_SECRET`, `TV_WEBHOOK_PORT`) for Chrome extension auto-push

---

## 7. Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| tv_stream.py refactor | Low — isolated module | All changes inside tv_stream.py; main.py change is 5 lines in one function |
| yt-dlp extraction | Medium — yt-dlp already in requirements; adds async executor call | Timeout + error handling → fallback error message to Discord channel |
| update.py | None — new file, no existing code touched | |
| Docs updates | None | |
| WEBUI_SETUP.md | None — new file | |

---

## 8. File Manifest

| File | Action |
|------|--------|
| `tv_stream.py` | Rewrite |
| `main.py` | Edit `_start_tv_stream` (~5 lines) |
| `update.py` | Create |
| `docs/WEBUI_SETUP.md` | Create |
| `docs/COMMANDS.md` | Edit (add /tv section) |
| `docs/FEATURES.md` | Edit (add TV stream section) |
