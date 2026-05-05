# features

## name

discord music bot - youtube-backed voice playback and quote utilities for one discord guild.

## synopsis

the bot joins a discord voice channel, resolves youtube urls, youtube playlist urls, favorites, or search text with `yt-dlp`, and plays audio through `ffmpeg`. it keeps an in-memory song queue, tracks the current session history, can cache downloaded audio for playback, supports local saved playlists and per-user favorites, and includes quote backup/random quote commands for a configured quotes channel.

## playback technology

- `discord.py[voice]` provides slash commands, guild command sync, voice connection handling, and reaction events.
- `yt-dlp` resolves youtube urls, youtube playlist urls, or search terms, extracts metadata, checks duration/filesize, and downloads audio when download mode is enabled. raw non-youtube urls are rejected before extraction.
- `ffmpeg` feeds the selected audio source into discord voice playback.
- `yt-dlp-ejs` plus `deno` or `node` supports current youtube javascript challenge handling.
- `.env` values configure the bot token, guild id, quotes channel id, and optional admin identity.

## download-and-play mode

download mode is enabled by default. in this mode the bot downloads audio before playback, stores media files under `cache/`, and stores metadata in `downloads.json`.

download mode exists to make playback more stable after extraction succeeds: once the file is local, discord playback reads from disk instead of relying on a live youtube stream for the whole song. the bot also:

- reuses cached files when the same youtube video is requested again.
- prefers playlist long-term cache files named `cache/plst-<cache-key>.<ext>` before normal cache files named `cache/<cache-key>.<ext>`.
- adopts exact legacy cache filenames such as `cache/<youtube-id>.<ext>` and `cache/plst-<youtube-id>.<ext>` into the canonical cache-key filename when that video is requested.
- removes cached files older than one hour on startup.
- schedules played files for deletion after playback. the default delay is 600 seconds and can be changed with `DOWNLOAD_DELETE_DELAY_SECONDS` or at runtime by admins with `/setdeletetime <seconds>`.
- enforces duration and cache-size limits, with stricter behavior for non-admin users.
- asks admins to confirm unusually large downloads instead of downloading silently.
- refuses downloads when free disk space is below the configured safety floor.
- deletes only validated media files from `cache/`.

cache keys are url-safe base64 of the canonical youtube watch URL. raw youtube titles and user-provided text are not used in downloaded filenames. the hard cache cap is 20 GB; when the cap is reached, new downloads are skipped and playback falls back to streaming.

users in the runtime `nodownload` group always stream. their requests skip normal cache lookup/download and their favorites are not eligible for favorites autocache.

`/purgecache` logs and reports the important purge counts: files scanned, removed, bytes freed, current file kept, unsafe or non-media entries skipped, failed deletions, and stale metadata removed.

## stream-only mode

admins can use `/toggledownload` to switch between download-and-play and stream-only mode. stream-only mode skips the local file cache and asks `yt-dlp` for a direct stream url. this uses less disk space, but playback depends more directly on the remote stream staying healthy.

admins can use `/togglelog debug` to enable verbose logs and editable `/play` download debug messages. `/togglelog admin` and `/togglelog all` enable the larger user-space operation trail: `/play` posts the sanitized progress message before voice connection work, then edits that same message through voice join, metadata extraction, cache lookup, download progress, and ffmpeg startup. those messages show sanitized track id, cache state, format id, downloaded amount, speed, and final ffmpeg playback path without exposing local absolute file paths. reacting with the cleanup emoji collapses the debug message back to a normal summary.

## queue and playback flow

the queue is an in-memory list of upcoming track dictionaries. `/play` starts playback immediately when nothing is playing, or queues the track when something is already playing. youtube playlist links are expanded into a single playlist block: pure playlist links start at the first extracted item, while watch links containing both `v=` and `list=` start from the selected video when possible and queue the remaining extracted items after it. `/enqueue` and `/q` add to the end of the queue. `/playtop` inserts a new track or youtube playlist block at the front so it plays next. `/queuefirst` and `/qfirst` move an existing queued item, saved playlist, or youtube playlist link to the front. `/queue links:true` can show youtube urls with queued songs unless an admin has disabled queue links.

when a track ends or is skipped, the bot pops the next queued track and starts it. session history is also kept so `/getqueue` can show whether requested songs are playing, queued, played, or removed. non-admin queueing is capped to limit public-server abuse. youtube playlist URL extraction is capped by `MAX_PLAYLIST_TRACKS`, and queued playlist entries are resolved through the normal safe track-fetch path when they reach playback.

`/skip`, `/stop`, and `/volume` are vote-based for non-admins in the bot's voice channel. quorum is 50% of the current human members in that voice channel, rounded up, and bots are excluded. admins bypass votes. the `🔂` now-playing reaction toggles repeat-one for the current track; repeat-off is instant for ordinary use, but after two other recent repeat-off toggles for the same song it uses the same voice quorum unless the user is an admin. the bot starts at 20% volume, admins can hard-set the current session with `/volume_session`, and admins can save a voice-channel default with `/volume_default` in `channel-volume-config.json`.

admins can enable `/autoleave` so that if the bot is alone in voice for the configured delay, it saves the current song plus upcoming queue to `last_session_queue.tmp.json`, disconnects, and reports that the session can be started again with `/play:last`. the saved session is restored by running `/play` with `last`, `play:last`, or `/play:last` as the value.

## playlists

playlists are stored locally under `playlists/<safe-name>-<playlistid>/metadata.json`. each playlist has an 8-character url-safe id, name, generated timestamp, lock state, visibility, owner discord id/name, manager user ids, cache mode, and ordered track entries. playlist folders are metadata-only; downloaded audio files never live under `playlists/`.

track entries include the youtube id, canonical youtube URL, cache key, cache mode, optional `cache_path`, media extension, and added-by metadata. if `cache_path` is missing or unsafe, playback ignores it and streams or downloads through the normal safe path.

users can create private or public playlists with `/playlist new`. without arguments it starts a guided flow: the bot asks for a playlist name, accepts one or more youtube video or playlist urls, supports `done`/`finish`/`valmis`/`loppu`/`stop`, and saves only when the user finishes. users can also import the upcoming queue directly with `/playlist new <name> current`; `currentqueue` and `jono` are aliases for that import mode. queue import creates the playlist immediately, then keeps a short add-more flow open for extra youtube urls.

users can browse playlists with `/playlist list`, inspect with `/playlist show`, inspect/edit with `/playlist edit`, play directly with `/playlist play`, add the current song, a queued song, a youtube video url, or a youtube playlist url with `/playlist add`, and bulk-fill a playlist from queued songs with `/playlist fill current <name>`. fill skips songs already in that playlist. owners can allow another user to manage the playlist with `/playlist addmod`. owners and admins can rename playlists with `/playlist rename` and lock playlists so managers cannot edit them.

playlist removal is soft by default. `/playlist remove <name>` asks for confirmation, marks the playlist deleted, and keeps it rescueable for 600 seconds. `/playlist rescue` lists deleted playlists that still exist on disk, and `/playlist rescue <name>` restores one for the owner or an admin. admins may remove immediately with `-now`; `-now -force` also skips the confirmation prompt. admins editing another user's playlist through edit/remove/move are reminded and asked to confirm unless they pass `-force`.

`playlists-blackbox.json` is an append-only audit record in the repository root. it stores playlist create/remove/rescue events with playlist name/id, owner, managers, and the playlist's youtube link list.

playlist references accept both `playlist:name` and exact playlist names. `/playlist play <name>` and `/play playlist:name` start or queue a playlist. `/enqueue playlist:name` and `/q playlist:name` queue it. `/queuefirst playlist:name` and `/qfirst playlist:name` move an existing playlist block to the front, or queue that playlist to play next.

while a playlist is actively playing, normal song requests are placed after the active playlist block and the requester gets a `👍`/`👎` prompt to move the song next instead.

playlist cache behavior is admin-controlled. the persistent global default is bounded caching, where a playlist play operation may cache up to 15 tracks or 3 GB and streams the rest. admins can use `/playlist cacheglobal` to change the global default, `/playlist cachemode` to override a playlist, `/cachestatus` to inspect cache use, and `/purgecache` to delete validated cache files. per-playlist modes are `follow_global`, `streaming`, `bounded`, and `keep_cached`.

the admin-only `/playlist predownload` command is disabled by default. enabling `PLAYLIST_PREDOWNLOAD_ENABLED=true` lets admins permanently download playlist audio into `cache/` with `plst-<cache-key>.<ext>` names without exposing that capability to normal users.

## favorites

favorites are special per-user playlists stored as metadata under `playlists/favorites-<user-id>/metadata.json`. they use the same track metadata shape as normal playlists, but they are managed through `/favorites` and the now-playing `⭐` reaction instead of the generic `/playlist` edit commands.

reacting `⭐` on the current now-playing message adds that song to the reacting user's favorites, deduped by youtube id or URL. the bot edits the now-playing message with a short notice such as `⭐ user added this to their favorites.` and resets that notice when the next now-playing song is published.

favorites are private by default. `/favorites privacy public` lets other users play or list them with `/favorites play user`, `/favorites list user`, or `/play -favorites username`. private favorites are denied to normal users. admins can play private favorites only after accepting a `👍`/`👎` warning prompt.

favorites privacy is not strong secrecy. it is a social bot visibility setting: admins can override it through the bot with confirmation, and anyone with filesystem access can read the metadata files.

favorites autocache is off by default and controlled by admins through `/favorites cacheglobal` and `/favorites cacheuser`. cached favorite media lives in root `cache/` as `plst-<cache-key>.<ext>` files, never in playlist folders. global favorites cache is capped at 6 GiB. the cache pass is balanced round-robin across eligible users so one user's favorites cannot consume the whole cap before other users are considered. by default it considers 30 tracks per user; the system supports up to 100 stored favorites per user.

`/favorites status` shows the caller's visibility, favorite count, cache eligibility, global favorites cache policy, and assigned restriction groups.

## now-playing controls

the now-playing message is the control surface for playback. it shows:

- a note emoji.
- a bold song title.
- an italic youtube url.
- reaction controls for favorite, previous, pause/resume, next, repeat-one, and queue display.

the bot tries to edit the latest now-playing message when no one has posted after it in the same channel. if another message exists after it, the bot sends a new now-playing message and removes playback-control reactions from the old one.

the `📜` reaction toggles the current queue above the now-playing block. the queue section uses bold numbered titles, optional italic urls, a divider, and then the current song. admins can use `/disablelinks` to hide urls from queue-style displays for the current bot session. users must be in the same voice channel as the bot to use playback-affecting commands or now-playing reactions, unless they are admins.

## runtime user restriction groups

admins can assign runtime restriction groups with `/usergroup add`, `/usergroup remove`, and `/usergroup list`. users can see their own status with `/permissions`; users without groups see `normal user`. group state is stored in `user-permissions.json`, which is runtime configuration and should not be committed.

the supported groups are:

- `nodownload`: user requests always stream and do not create normal downloads or favorite cache entries for that user.
- `novolumechange`: blocks `/volume`.
- `noplaylistcreate`: blocks guided playlist creation and queue-import playlist creation.
- `noqueueskip`: blocks `/playtop` while playback is active plus `/queuefirst` and `/qfirst`.
- `noskip`: blocks `/skip`, skip reactions, and skip vote participation.
- `norepeat`: blocks repeat reaction use.

playlist list/edit views use `◀️` and `▶️` reactions for pages. only the newest playlist view remains interactive. `/help` is compact by default and expands in place when users react with `📖`. every root slash command has a manpage-style page through `/help command:<command>`, for example `/help command:nytsoi`. playlist help is available with `/help topic:playlists`, `/help command:playlist new`, and `/help topic:playlist command:new` style selectors.

## security hardening

- media input is youtube-only for URLs; plain search text is still supported.
- local, private-network, and non-youtube URLs are rejected before `yt-dlp` runs.
- admin privileges come from `ADMIN_ROLE_NAME` or numeric `ADMIN_USER_ID`; username-based admin overrides are ignored.
- `/purgequeue` and `/purgecache` are admin-only and all downloaded-file deletion goes through path validation.
- dependency minimums include `aiohttp>=3.13.4,<4.0` for 2026 DoS fixes and `python-dotenv>=1.2.2,<2.0` for the `.env` symlink rewrite fix.

## status and session audit

the bot keeps a session-only audit of music suggestions and recent slash commands. suggestion logs include the user, command, raw requested value or queue position, and resolved track metadata when available. `/status` shows the latest suggestion by default, `/status view:session` shows the music suggestion history, and `/status view:commands` shows the last five slash commands. this audit lives in memory and resets when the bot restarts.

## restorequeue purpose

`/restorequeue` is a recovery command for admins. it exists for two cases:

- after `/clear_queue`, the bot keeps a short in-memory backup so an accidental clear can be reversed.
- before `/reboot`, the bot writes the current queue and current track to `queue_backup.json`, allowing the queue to be restored after the bot comes back.

restores are time-limited to avoid bringing back stale queues long after the listening session has moved on.

## quotes

the bot can watch a configured quotes channel, back up its messages to `quotes.txt`, and return a random saved quote. quote persistence is isolated in `quotes.py`.

## diagnostics and deployment

startup diagnostics check dependency versions, voice-stack requirements, write access, ffmpeg availability, youtube javascript runtime availability, disk space, and quote file access. deployment examples include a shell launcher and a systemd unit that append logs to `output.log`.

if startup reports `No deno or node executable found in PATH`, the bot can still start, but youtube extraction may miss formats. install Deno or Node on the host and make sure the same executable is visible to the process that launches `main.py`. for systemd deployments, that usually means adding the Deno or Node bin directory to the unit's `Environment=PATH=...` line before restarting the service.
