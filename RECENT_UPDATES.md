# Recent Updates

Source: local git history and maintainer notes.

## 2026-05-28

### WebUI — fully automatic, always works
- WebUI now sets itself up with zero manual configuration when `WEBUI_ENABLED=true`:
  - `WEBUI_SECRET_KEY` is auto-generated and written to `.env` on first start if not set.
  - Missing packages (`uvicorn`, `fastapi`, `aiohttp`) are auto-installed at startup.
  - `cloudflared` is auto-downloaded to `bin/` if not found in PATH.
  - A Cloudflare quick tunnel is started automatically and the URL is persisted to `cloudflare_tunnel_url.json`. On restart, the last-known URL is used immediately while the new tunnel warms up — `/webui` always works.
  - `WEBUI_ENABLED` and `SPOTIFY_ENABLED` both default to `true` — no `.env` changes needed.
- **Port resilience**: if the WebUI port is already in use by another bot instance, it is automatically terminated and the port is reclaimed (assimilation). If an unrelated process holds the port, the next available port is used instead. The bot never crashes due to a port conflict.
- **Bot singleton**: a `discordmusic.pid` file is written on startup. If an existing instance is detected, it is terminated before the new one starts.

### Spotify import — no API keys required
- `/spotify import <url>` now works without any credentials. The bot scrapes `open.spotify.com` to extract track data (no Spotify Developer account needed).
- If `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` are set in `.env`, the official API is used as a fallback if scraping fails. This is optional.
- Confidence algorithm unchanged: title 40%, artist 30%, duration 20%, result-type bonus 10%.

### Modules restructure
- `spotify_import.py`, `quote_guesser.py`, `tv_stream.py`, and `update.py` are now in the `modules/` package. Root copies remain for backwards compatibility during the transition. New imports use `modules.*`.

### Quote guesser — unlimited admin mode
- Admins see a small `∞` button in the top-right corner of the WebUI.
- Clicking it opens a modal with a random attributed quote challenge. Guesses do not affect the leaderboard — it's purely for fun / testing.
- The daily challenge is unchanged for regular users.

### setup_assistant
- Running the Discord setup wizard now automatically writes `WEBUI_ENABLED=true`, a generated `WEBUI_SECRET_KEY`, `WEBUI_CLOUDFLARED_AUTO=true`, and `SPOTIFY_ENABLED=true` to `.env`. No extra steps needed.
- The Web UI configuration section now explains the auto-setup features clearly.

## 2026-05-06

- Fixed `/help` reaction expansion by splitting expanded help into safe pages with `◀️`/`▶️`.
- Restyled `/help` into grouped, scan-friendly sections and added `/help topic:all` for every registered command.
- Added a `/config show` voice-vote toggle. Admins always bypass votes; when votes are disabled, same-channel users act directly while restriction groups still apply.
- Reduced active-playlist move-next prompts: admins and disabled-vote sessions act directly, and small voice sessions no longer get the prompt.
- Playlist playback now starts or queues immediately while bounded playlist cache warming runs in the background for up to the first 15 tracks or 3 GB.
- Added `runtime-audit.json` for sanitized high-impact runtime events such as config toggles, cache purge/cachequeue, queue file deletion, cache playback, and `/play last` decisions.
- Playback speed now resets to normal `1x` after the bot has been alone for the configured alone delay; the reset is logged and announced when admin operation messages are enabled.
- Bot status now changes with playback: idle shows `/play (yt-link)`, active tracks prefer `song - artist` from YouTube metadata, and fallback/error cases are logged.
- Added a `/config show` voice-vote toggle. Admins always bypass votes; when votes are disabled, same-channel users act directly while restriction groups still apply.
- Reduced active-playlist move-next prompts: admins and disabled-vote sessions act directly, and small voice sessions no longer get the prompt.
- Added `runtime-audit.json` for sanitized high-impact runtime events such as config toggles, cache purge/cachequeue, queue file deletion, cache playback, and `/play last` decisions.
- Improved YouTube failure handling so unavailable videos get a useful message and search requests try fallback results before failing.
- Added `/nowplaying` URL-free controls with cooldown, plus hidden playspeed controls and `/play speed`.
- Added admin `/cachequeue` to cache the current song plus upcoming queue immediately, with `nodownload` skips and queue-blackbox audit entries.
- Hardened `/play last` so it only restores recent auto-leave recovery files and rejects stale or legacy previous-session data.
- Made the now-playing star a true favorites toggle: pressing it again removes the song from that user's favorites and logs the change.
- Added `/status play` for detailed current playback diagnostics, with an admin `/config show` toggle to allow that view publicly.

## 2026-05-05

- Added `/whatsnew`, backed by this file, so Discord users can see recent bot changes without reading git.
- Added `/play show_download_log:true` and `/togglelog download` for styled download progress logs without forcing DEBUG logging.
- Added admin `/config show`, `/userstats <user>`, and single-track `/play repeat`.
- Added a 50% ear-safety ceiling for `/volume`, `/volume_session`, and `/volume_default`. Admins can intentionally go louder with `/volume_force`, and can save a forced channel default when needed.
- Added hidden admin voice placement with `/adminjoin`: admins can move/connect the bot by voice-channel name or by the channel where a selected user currently is.
- Added per-user favorites: star reaction, `/favorites`, and `/play -favorites username`.
- Added runtime restriction groups plus `/permissions` and admin `/usergroup`.
- Added repeat-one with admin bypass and repeat-off quorum protection.
- Added YouTube playlist URL support across playback, queue-front commands, guided playlist creation, and playlist URL import.
- Expanded `/togglelog` with `admin` and `all` modes for sanitized `/play` progress.
- Fixed post-favorites regressions around cache use, `nodownload`, and `noqueueskip`.

## 2026-05-04

- Added detailed `/help command:<command>` pages and playlist help through `/help topic:playlist command:<subcommand>`.
- Improved cache/download diagnostics, including `/purgecache` audit logging and safer cache reuse/adoption behavior.
- Landed the quality-of-life batch: auto-leave recovery with `/play last`, runtime cleanup timing, playlist fill/import improvements, setup assistant polish, systemd logging updates, and docs refreshes.
