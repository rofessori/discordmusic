## 2026-05-07
- Fixed false "bot is not in a voice channel" / "not currently in a voice channel" decisions caused by stale `client.current_voice_channel` state after admin voice placement, Discord voice moves, or reconnect-like state drift. Voice-sensitive commands now reconcile the tracked client with `guild.voice_client` before checking channel membership, votes, pause/resume, volume, playback recovery, and queued playback.
- Fixed a related stale now-playing edge case where old playback control reactions and `current_track_info` could survive after stop, queue end, auto-leave, or an unexpected voice disconnect. Finished playback now clears the tracked current song and removes now-playing controls from the old message.

## 2026-05-06
- Fixed `/help` reaction expansion failing with Discord's 2000-character content limit by paging expanded help and keeping each edit below the safe limit.
- Restyled compact and expanded `/help` into grouped sections and added paged `/help topic:all` for every registered slash command and subcommand.
- Added persistent `voice_votes_enabled` runtime config in `/config show`; admins always bypass votes, and disabled votes make same-channel users act directly while restriction groups still apply.
- Fixed active-playlist move-next prompting so admins never get the prompt, disabled-vote sessions move next directly, and fewer than three human voice users skip the prompt.
- Fixed long saved playlist playback so `/play playlist:...` queues or starts immediately and bounded playlist cache warming runs in the background instead of blocking on up to 15 downloads first.
- Added sanitized `runtime-audit.json` entries for impactful runtime actions, including config toggles, cache purge/cachequeue, queue file deletion, delayed cleanup, cache hits/downloads, stream fallback, and `/play last` decisions.
- Added automatic playback-speed normalization: when the bot is alone for the configured alone delay, speed resets to `1x`, logs to `output.log` and `runtime-audit.json`, and posts an admin operation notice when that larger logging mode is enabled.
- Added playback-aware Discord presence: idle shows `/play (yt-link)`, active playback prefers `song - artist` from YouTube metadata, and fallback or hard-error paths are logged.
- Improved yt-dlp failure handling: unavailable videos now produce a specific user message, admins get a missing `deno`/`node` hint, and search requests try bounded fallback results before failing.
- Added `/nowplaying`, which reposts the active now-playing controls without the YouTube URL and uses an admin-configurable per-channel cooldown to prevent spam.
- Added hidden playback speed controls: `/playspeed`, `/playspeedaccess`, the `playspeed` allow group, and `/play speed`/`--speed:<number>` for single-track requests from 0.1x to 2x.
- Fixed stale `/play last` recovery behavior by requiring recent auto-leave metadata before restoring `last_session_queue.tmp.json`; rejected legacy/stale recovery files are logged to `queue-blackbox.json` and removed.
- Added admin `/cachequeue [include_current]` to download/cache the current session's eligible current/upcoming tracks into root `cache/`, while skipping `nodownload` users and respecting the cache hard cap.
- Changed the now-playing `⭐` reaction into a favorites toggle. A second press removes the same song from that user's favorites, edits the now-playing notice, and logs the removal.
- Added `/status play` for detailed music stream diagnostics and a `/config show` toggle that can make only that playback status view public.

## 2026-05-05
- Added admin `/config show`, a reaction-toggleable runtime config panel that edits itself when admins flip download mode, download logs, DEBUG logging, operation trail, queue links, auto-leave, favorites autocache, playlist cache policy, playspeed allow-all, or nowplaying cooldown.
- Added admin `/userstats <user>` for cross-checking a user's restriction groups, favorites, playlists, queued/session requests, recent commands, and recent music requests.
- Added `/play` single-track repeat support through the `repeat` slash option or trailing `-repeat <count>`; counts above 20 become repeat-one loop instead of queuing more than 20 copies.
- Decoupled Discord download logs from Python DEBUG logging: `/togglelog download` now enables editable `/play` progress logs while keeping normal INFO logging, `/play show_download_log:true` enables the log for one request, and the message now shows a styled progress bar when download totals are available.
- Added root `RECENT_UPDATES.md` plus `/whatsnew`, summarizing recent git-history updates for Discord users.
- Fixed a documentation/help regression from the 50% ear-safety change: `/volume_force` was registered and referenced by volume guidance but missing from the command reference and detailed `/help command:` pages.
- Added hidden admin voice placement with `/adminjoin`, allowing admins to connect or move the bot by voice channel name or by the voice channel a selected user is in.
- Added a 50% ear-safety ceiling to normal volume paths (`/volume`, `/volume_session`, and `/volume_default`) plus an admin `/volume_force` override for intentional louder session volume or forced channel defaults.
- Fixed regressions from the favorites/user-restriction addition: favorites playback no longer uses the generic playlist cache path unless favorites autocache is enabled, `nodownload` users do not trigger favorites cache work or reuse cached restored tracks, and `noqueueskip` users no longer get the active-playlist move-next prompt.
- Added per-user favorites as special playlist metadata: the now-playing `⭐` reaction stores the current song in the reacting user's favorites and edits the now-playing message with a short favorite notice.
- Added `/favorites play/list/privacy/status/cacheuser/cacheglobal`, `/play -favorites username`, and `/permissions`, plus admin `/usergroup add/remove/list` runtime restriction groups.
- Added favorites privacy/cache guardrails: favorites are private by default but not strong secrecy, admin private-favorites playback requires confirmation, favorites cache uses root `cache/` only, global favorites cache is capped at 6 GiB, and user restrictions live in ignored `user-permissions.json`.
- Added YouTube playlist URL ingestion for playback and saved-playlist import flows. `/play`, `/playtop`, `/enqueue`, `/q`, `/queuefirst`, `/qfirst`, guided `/playlist new`, and `/playlist add ... url` now understand `list=` links; watch links with both `v=` and `list=` start from the selected video when possible and keep the rest as one playlist block.
- Expanded admin logging controls with `/togglelog admin` and `/togglelog all`, which make `/play` post a sanitized progress message before voice join and edit it through voice, metadata, cache, download, and ffmpeg events.
- Added the now-playing `🔂` repeat-one reaction with admin bypass and a repeat-off quorum guard after two other recent repeat-off toggles for the same song.

## 2026-05-03
- Added admin `/autoleave <enabled> [delay_seconds]` and `/play:last` recovery so the bot can leave after being alone, save the current song plus queue, and resume that saved session later.
- Improved help/status UX: compact `/help` now focuses on core playback commands, `📖` toggles expanded help open and closed, and `/status` wraps URLs in a code block when queue links are disabled.
- Added admin `/setdeletetime <seconds>` and `DOWNLOAD_DELETE_DELAY_SECONDS` so downloaded song cleanup delay is configurable instead of hardwired to 600 seconds.
- Added `/playlist fill current <playlist>` to bulk-add queued songs that are not already in the target playlist, with duplicate and missing-metadata skips reported to the user.
- Redesigned playlist creation UX: `/playlist new` now starts a guided name-and-youtube-url flow with cancel/finish words and timeout cleanup, `/playlist new <name> currentqueue` imports the upcoming queue, and `/playlist new <name> jono` is supported as the Finnish queue-import alias.
- Added playlist usability commands and help coverage: `/playlist show`, `/playlist play`, `/playlist delete`, `/playlist rename`, URL-based `/playlist add`, `/help topic:playlists`, and manpage-style `/help topic:playlist command:<subcommand>` pages for every playlist subcommand.
- Fixed CodeQL clear-text storage alert in `setup_assistant.py` by removing the repo-root systemd service preview file and copying generated service content through a private temporary file that is deleted after install.
- Fixed the setup assistant role flow so admin role name is the default path in both guided and quick setup, with admin role id kept as an optional add-on instead of being prompted first.
- Rebuilt `setup_assistant.py` into a resumable stdlib terminal setup wizard with safe secret handling, quick/guided modes, placeholder-only `.env.example` generation, optional dependency/screen/systemd automation, optional `QUOTES_ID=0`, and stable `ADMIN_ROLE_ID` support.
- Fixed playlist edge cases found during a projectwide bug/security/UX pass: `/playlist move` now replies correctly after admin confirmation prompts, immediate playlist deletion only reports success after the safe folder-removal check passes, malformed `playlists-blackbox.json` files are preserved instead of overwritten, expired delete tasks are cleaned up, and locked playlist managers no longer bypass foreign-admin confirmation logic.
- Changed playlist deletion to a confirmed soft-delete flow with `/playlist rescue`, admin `-force` confirmation bypass for foreign playlist edits, admin-only `-now` immediate removal, `/playlist removesong` for per-song removal, and root-level `playlists-blackbox.json` audit events for playlist create/remove/rescue history.
- Added the saved playlist system: local playlist metadata under `playlists/`, owner/manager permissions, public/private playlist visibility, playlist listing/edit paging, playlist playback through `/play`/`/enqueue`/`/q`, `/queuefirst` playlist support, active-playlist insertion prompts, compact expandable `/help`, and a disabled-by-default admin predownload hook.
- Hardened the public bot surface after a cybersecurity review. User-supplied raw URLs are now limited to YouTube, local/private/non-YouTube URLs are rejected before `yt-dlp`, username-based admin overrides are ignored, `/purgequeue` is admin-only, playback controls require the same voice channel unless the user is an admin, and downloaded-file deletion validates paths before removing anything.
- Raised vulnerable dependency minimums to `aiohttp>=3.13.4,<4.0` for the 2026 aiohttp DoS advisories and `python-dotenv>=1.2.2,<2.0` for the `.env` symlink rewrite advisory.
- Fixed stale now-playing messages retaining active playback control reactions after a newer now-playing message was sent. Old now-playing messages now lose only the bot's playback controls, while `/reboot` and other confirmation prompts keep their own `👍`/`👎` reactions isolated.
- Fixed the systemd example so Python logging on stderr is appended to `output.log`; this makes now-playing edit/send, reaction cleanup, and queue-jump diagnostics visible in the documented service setup.

## 2026-05-02
- Fixed Discord voice reconnect loops where the bot joined and immediately left with websocket close code 4006. The project now requires `discord.py[voice]==2.7.1`, pins the `davey` voice dependency, and blocks startup on known-broken `discord.py<2.6.0` installs.

## 2025-08-12
- Play commands now check for a connected voice client before starting playback. If the bot isn't in a channel, it joins the caller's channel or asks them to join one, preventing stray ffmpeg processes.

- Fixed slash command error handler so it replies properly; no more 404 'Unknown interaction' when something breaks.
