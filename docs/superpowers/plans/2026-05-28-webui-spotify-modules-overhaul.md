# WebUI + Spotify + Modules Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the WebUI always work automatically, add a no-API-key Spotify scraper, restructure modules, add admin unlimited quote guesser mode, and make everything resilient to restarts and port conflicts.

**Architecture:** All optional module files moved to `modules/` package. WebUI startup becomes self-healing: auto-generates secret key, auto-installs missing packages, auto-downloads cloudflared, persists tunnel URL across restarts, and assimilates port conflicts. Spotify import scrapes open.spotify.com first (no keys), falls back to spotipy API if credentials are set.

**Tech Stack:** Python asyncio, FastAPI+uvicorn, aiohttp (scraping + cloudflared download), yt-dlp, discord.py, React 18 (CDN, no build step), cloudflared quick tunnel.

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `modules/__init__.py` | Package marker |
| Move+modify | `modules/spotify_import.py` | Hybrid Spotify scraper (scrape first, API fallback) |
| Move+extend | `modules/quote_guesser.py` | Daily guesser + unlimited admin mode |
| Move | `modules/tv_stream.py` | TV streaming module (unchanged) |
| Move | `modules/update.py` | Bot update script (unchanged) |
| Overwrite | `webui/__init__.py` | Auto-setup, port resilience, cloudflared auto-download + URL persistence |
| Modify | `webui/server.py` | Add unlimited guesser API endpoints |
| Overwrite | `webui/frontend/index.html` | Admin ∞ button, Spotify default-on UI |
| Modify | `main.py` (lines 115–178, 7702–7756) | Update imports, PID file, defaults, /webui command fix |
| Modify | `setup_assistant.py` | Auto-configure webui+cloudflared+spotify after Discord setup |
| Update | `RECENT_UPDATES.md` | Document all changes |
| Create | `.gitignore` entries | `bin/cloudflared*`, `cloudflare_tunnel_url.json`, `discordmusic.pid` |

---

## Task 1: Create modules/ directory and move files

**Files:**
- Create: `modules/__init__.py`
- Create: `modules/tv_stream.py` (copy of root tv_stream.py)
- Create: `modules/update.py` (copy of root update.py)

- [ ] Create `modules/__init__.py` (empty)
- [ ] Copy `tv_stream.py` → `modules/tv_stream.py`
- [ ] Copy `update.py` → `modules/update.py`
- [ ] Add `.gitignore` entries for `bin/cloudflared*`, `cloudflare_tunnel_url.json`, `discordmusic.pid`

---

## Task 2: modules/spotify_import.py — hybrid scraper

**Files:**
- Create: `modules/spotify_import.py`

Core change: replace `_fetch_spotify_tracks_sync` with a two-phase approach:
1. `_scrape_open_spotify(playlist_id)` — parse `__NEXT_DATA__` JSON embedded in the Spotify web page
2. Fall back to `_fetch_via_spotipy(playlist_url)` if credentials are in env

New function `_extract_playlist_id(url)` handles both URL forms.
`fetch_spotify_tracks()` async wrapper tries scrape first, then API.

- [ ] Copy `spotify_import.py` to `modules/spotify_import.py`
- [ ] Add `_extract_playlist_id(url)` helper
- [ ] Add `_scrape_open_spotify(playlist_id)` using aiohttp + regex for `__NEXT_DATA__`
- [ ] Add `_parse_next_data_tracks(data)` that tries 3 known JSON paths
- [ ] Replace `fetch_spotify_tracks()` to call scraper first, spotipy second
- [ ] `SPOTIFY_CLIENT_ID`/`SECRET` now optional — only used as fallback

---

## Task 3: webui/__init__.py — full overhaul

**Files:**
- Overwrite: `webui/__init__.py`

Key additions:
- `_ensure_secret_key()` — auto-generate + write to .env if missing
- `_auto_install_deps(missing)` — subprocess pip install
- `_is_port_free(port)` — socket bind check
- `_get_pid_on_port(port)` — lsof/fuser/psutil
- `_assimilate_or_find_port(port)` — kill same-bot process OR try next 5 ports
- `_ensure_cloudflared()` — find in PATH or local bin/ or auto-download
- `_download_cloudflared(dest)` — aiohttp download from GitHub releases
- `_load_persisted_tunnel_url()` / `_save_tunnel_url(url)` — JSON file in project root
- `cloudflared_tunnel_url` initialized from persisted file at module load
- `WEBUI_CLOUDFLARED_AUTO` defaults to `True` (no env var needed)

- [ ] Write new `webui/__init__.py` with all helpers
- [ ] Replace error-only `SystemExit` handler with resilient `_serve()` that uses assimilated port

---

## Task 4: modules/quote_guesser.py — unlimited mode

**Files:**
- Create: `modules/quote_guesser.py`

New methods on `QuoteGuesser`:
- `get_unlimited_challenge(user_id, session_id)` — random quote, random seed, not daily-locked
- `submit_unlimited_guess(session_id, user_id, username, guess)` — in-memory only, no leaderboard effect

In `webui/server.py`:
- `POST /api/guesser/unlimited/start` (admin) → `{session_id, text, choices}`
- `POST /api/guesser/unlimited/guess` (admin) → `{correct, correct_author, done}`

- [ ] Copy `quote_guesser.py` → `modules/quote_guesser.py`
- [ ] Add `_unlimited_sessions: dict` to `QuoteGuesser.__init__`
- [ ] Add `get_unlimited_challenge()` method
- [ ] Add `submit_unlimited_guess()` method
- [ ] Add the two new routes to `webui/server.py`

---

## Task 5: main.py updates

**Files:**
- Modify: `main.py` (lines 115–178, 7360–7377, 7702–7756, top-level)

Changes:
- `SPOTIFY_ENABLED` default → `True`
- `WEBUI_ENABLED` default → `True`  
- Import `modules.spotify_import`, `modules.tv_stream`, `modules.quote_guesser`
- Add `_write_pid_file()` + `_check_and_kill_old_instance()` called at startup
- Update `/webui` command: if cloudflared URL not ready yet, poll from persisted file

- [ ] Update env_flag defaults for `SPOTIFY_ENABLED` and `WEBUI_ENABLED`
- [ ] Update module imports to `modules.*`
- [ ] Add PID file helpers + call at startup
- [ ] Fix `/webui` command to check persisted tunnel URL

---

## Task 6: webui/frontend/index.html — frontend updates

**Files:**
- Overwrite: `webui/frontend/index.html`

Changes:
- Spotify import section visible by default (not hidden behind a toggle)
- Admin `∞` button in top-right of topbar (only rendered when `is_admin=true`)
- Unlimited guesser modal: shows random quote challenge, "New Round" button, guess submission

---

## Task 7: setup_assistant.py — auto-configure

After Discord token + guild setup completes, auto-write to `.env`:
```
WEBUI_ENABLED=true
WEBUI_SECRET_KEY=<generated>
WEBUI_CLOUDFLARED_AUTO=true
SPOTIFY_ENABLED=true
```
Remove the mandatory Spotify API key prompt (make it optional, show at end).

---

## Task 8: Update RECENT_UPDATES.md

Document: modules/ restructure, hybrid Spotify scraper, WebUI auto-setup, cloudflared auto, unlimited guesser.
