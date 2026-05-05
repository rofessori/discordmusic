# Recent Updates

Source: local git history on `playlist-new` since `2026-05-03`; separate push timestamps are not available in this checkout.

## 2026-05-05

- Added `/whatsnew`, backed by this file, so Discord users can see recent bot changes without reading git.
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
