# Recent Updates

Source: local git history and maintainer notes.

## 2026-05-06

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
