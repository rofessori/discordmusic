# features

## name

discord music bot - youtube-backed voice playback and quote utilities for one discord guild.

## synopsis

the bot joins a discord voice channel, resolves youtube urls or search text with `yt-dlp`, and plays audio through `ffmpeg`. it keeps an in-memory song queue, tracks the current session history, can cache downloaded audio for playback, and includes quote backup/random quote commands for a configured quotes channel.

## playback technology

- `discord.py[voice]` provides slash commands, guild command sync, voice connection handling, and reaction events.
- `yt-dlp` resolves youtube urls or search terms, extracts metadata, checks duration/filesize, and downloads audio when download mode is enabled.
- `ffmpeg` feeds the selected audio source into discord voice playback.
- `yt-dlp-ejs` plus `deno` or `node` supports current youtube javascript challenge handling.
- `.env` values configure the bot token, guild id, quotes channel id, and optional admin identity.

## download-and-play mode

download mode is enabled by default. in this mode the bot downloads audio before playback and stores metadata in `downloads.json`.

download mode exists to make playback more stable after extraction succeeds: once the file is local, discord playback reads from disk instead of relying on a live youtube stream for the whole song. the bot also:

- reuses cached files when the same youtube video is requested again.
- removes cached files older than one hour on startup.
- schedules played files for deletion after playback.
- enforces duration and cache-size limits, with stricter behavior for non-admin users.
- asks admins to confirm unusually large downloads instead of downloading silently.

## stream-only mode

admins can use `/toggledownload` to switch between download-and-play and stream-only mode. stream-only mode skips the local file cache and asks `yt-dlp` for a direct stream url. this uses less disk space, but playback depends more directly on the remote stream staying healthy.

## queue and playback flow

the queue is an in-memory list of upcoming track dictionaries. `/play` starts playback immediately when nothing is playing, or queues the track when something is already playing. `/enqueue` and `/q` add to the end of the queue. `/playtop` inserts a new track at the front so it plays next. `/queuefirst` and `/qfirst` move an existing queued item to the front by its queue position. `/queue links:true` can show youtube urls with queued songs unless an admin has disabled queue links.

when a track ends or is skipped, the bot pops the next queued track and starts it. session history is also kept so `/getqueue` can show whether requested songs are playing, queued, played, or removed.

## now-playing controls

the now-playing message is the control surface for playback. it shows:

- a note emoji.
- a bold song title.
- an italic youtube url.
- reaction controls for previous, pause/resume, next, and queue display.

the bot tries to edit the latest now-playing message when no one has posted after it in the same channel. if another message exists after it, the bot sends a new now-playing message and removes playback-control reactions from the old one.

the `📜` reaction toggles the current queue above the now-playing block. the queue section uses bold numbered titles, optional italic urls, a divider, and then the current song. admins can use `/disablelinks` to hide urls from queue-style displays for the current bot session.

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
