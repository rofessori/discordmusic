# commands

clean reference for the bot's slash commands and now-playing reaction controls.

## music playback

| command | purpose |
| --- | --- |
| `/join` | join the voice channel you are currently in. |
| `/play <youtube url, youtube playlist url, search, playlist:name, or -favorites username> [repeat] [speed] [show_download_log]` | play a youtube result, saved playlist, or public favorites immediately, or add it to the queue if something is already playing. `repeat` or a trailing `-repeat <count>` repeats single-track requests; values above 20 become repeat-one loop. `speed` or trailing `--speed:<number>` applies 0.1x-2x speed for allowed users. `show_download_log:true` shows an editable sanitized progress log for this request. raw non-youtube urls are rejected. |
| `/play:last` | restore the last auto-saved voice session after auto-leave. in Discord slash options this is entered as `/play` with `last`, `play:last`, or `/play:last` as the value. |
| `/playtop <query or youtube playlist url>` | add a track or youtube playlist block to the front of the queue so it plays next. if nothing is playing, it starts immediately. |
| `/enqueue <query, youtube playlist url, or playlist:name>` | add a track or playlist to the end of the queue. |
| `/q <query, youtube playlist url, or playlist:name>` | alias for `/enqueue`. |
| `/queue [links]` | show the upcoming songs in the queue. set `links:true` to include youtube urls when links are enabled. |
| `/queuelist [links]` | alias for `/queue`. |
| `/queuefirst <position, youtube playlist url, or playlist:name>` | move an existing queued song or playlist to the front of the queue. |
| `/qfirst <position, youtube playlist url, or playlist:name>` | alias for `/queuefirst`. |
| `/skip` | vote to skip the current track and continue to the next queued track. admins bypass the vote; if voice votes are disabled, same-channel users act directly. |
| `/stop` | vote to stop playback, clear the queue, and disconnect from voice. admins bypass the vote; if voice votes are disabled, same-channel users act directly. |
| `/pause` | pause the current playing audio. requires the same voice channel unless the user is an admin. |
| `/resume` | resume paused audio. requires the same voice channel unless the user is an admin. |
| `/volume <1-50>` | vote to set playback volume from 1 to 50 percent. admins bypass the vote, and disabled voice votes make same-channel users direct, but the normal command keeps the ear-safety cap. |
| `/now` | show the currently playing song. |
| `/nowplaying` | repost the now-playing controls without the video url. non-admin use has a per-channel cooldown. |
| `/nytsoi` | finnish alias for `/now`. |
| `/getqueue` | list all songs requested in the current session and show whether they are playing, queued, played, or removed. |
| `/whatsnew` | show the recent bot update summary from `RECENT_UPDATES.md`. |

## now-playing reactions

| reaction | purpose |
| --- | --- |
| `⭐` | toggle the current song in your favorites. the now-playing message is edited with a short add/remove notice naming the user. |
| `◀️` | vote to replay the previous track when one is available. admins bypass the vote; disabled voice votes make same-channel users direct. |
| `⏸️` | pause or resume playback. requires the same voice channel unless the user is an admin. |
| `▶️` | vote to skip to the next track. admins bypass the vote; disabled voice votes make same-channel users direct. |
| `🔂` | toggle repeat-one for the current track. admins bypass repeat-off votes; non-admin repeat-off only starts a vote after two other recent repeat-off toggles for that same song. |
| `📜` | toggle the current queue above the now-playing message. requires the same voice channel unless the user is an admin. |

## favorites

| command | purpose |
| --- | --- |
| `/favorites play [user]` | play your favorites, or another user's public favorites. admins can override private favorites only after a confirmation warning. |
| `/favorites list [user]` | list your favorites, or another user's public favorites. |
| `/favorites privacy <public\|private>` | set whether normal users can view/play your favorites. private is the default. |
| `/favorites status` | show your favorites visibility, count, cache eligibility, and restriction groups. |
| `/favorites cacheuser <user> <enabled>` | admin-only allow or deny favorites autocache for one user. |
| `/favorites cacheglobal <enabled> [max_gb] [per_user_tracks]` | admin-only global favorites autocache policy. max cap is 6 GiB; default per-user cache pass is 30 tracks and supported storage is 100 favorites/user. |
| `/play -favorites username` | alias for playing a user's public favorites. |

Favorites are special per-user playlists under `playlists/favorites-<user-id>/metadata.json`. The star reaction dedupes by YouTube identity when adding and removes the same saved entry when pressed again. Favorites privacy is not strong secrecy: admins can bypass private favorites with a warning prompt, and filesystem access can read metadata.

## queue management

| command | purpose |
| --- | --- |
| `/clear_queue` | clear the current song queue. requires the same voice channel unless the user is an admin; admins are prompted to optionally delete downloaded files. |
| `/purgequeue` | delete downloaded song files from disk while keeping the queue intact. admin only; the currently playing file is not deleted. |
| `/restorequeue` | restore a recently cleared queue or a queue saved during reboot. admin only, time-limited. |
| `/cachequeue [include_current]` | admin-only immediate cache pass for the currently playing track plus upcoming queue. skips `nodownload` users, respects cache caps, and writes audit entries to `queue-blackbox.json`. |

## playlists

| command | purpose |
| --- | --- |
| `/playlist list` | list your playlists first, then visible public playlists, with reaction pages. |
| `/playlist new` | start a guided playlist creation flow that asks for the name and youtube urls. |
| `/playlist new <name> [visibility]` | create an empty private or public playlist. |
| `/playlist new <name> current` | create a playlist from the upcoming queue immediately, then keep a short add-more URL flow open. |
| `/playlist new <name> currentqueue` | alias for `current`. |
| `/playlist new <name> jono` | finnish alias for `current`. |
| `/playlist show <name>` | show readable playlist details without requiring edit permission. |
| `/playlist play <name>` | start a playlist now, or queue it if something is already playing. |
| `/playlist edit <name> [flags]` | show editable playlist details and song pages. admins editing someone else's playlist are asked to confirm unless `-force` is supplied. |
| `/playlist add <playlist>` | add the currently playing song to a playlist you can edit. `source` is auto-detected: omit it when adding the current track, supply `url` and a youtube url to add a specific video or playlist, or supply `queue` and a position number to add a queued song. |
| `/playlist add <playlist> current` | explicit form: add the currently playing song. |
| `/playlist add <playlist> queue <position>` | explicit form: add a queued song by queue number. |
| `/playlist add <playlist> url <url>` | explicit form: add a youtube video or playlist url. |
| `/playlist fill current <playlist>` | add queued songs that are not already in the playlist. |
| `/playlist addmod <playlist> <user>` | add a manager to a playlist you own. |
| `/playlist remove <playlist> [flags]` | remove a whole playlist after confirmation. it can be rescued for 600 seconds. admins can use `-now`; `-now -force` skips confirmation. |
| `/playlist delete <playlist> [flags]` | alias for `/playlist remove`. |
| `/playlist rename <playlist> <new_name> [flags]` | rename a playlist you own or manage. admins can rename any playlist after confirmation unless `-force` is supplied. |
| `/playlist removesong <playlist> <position> [flags]` | remove a song from a playlist you can edit. admins editing someone else's playlist are asked to confirm unless `-force` is supplied. |
| `/playlist move <playlist> <from> <to> [flags]` | reorder songs inside a playlist you can edit. admins editing someone else's playlist are asked to confirm unless `-force` is supplied. |
| `/playlist lock <playlist> <locked>` | lock or unlock manager edits. owner/admin only. |
| `/playlist cachemode <playlist> <mode>` | set one playlist's cache behavior. admin only. modes: `follow_global`, `streaming`, `bounded`, `keep_cached`. bounded playback starts/queues first, then warms up to the first 15 tracks or 3 GB in the background. |
| `/playlist cacheglobal <mode> [force]` | set the persistent global playlist cache behavior. admin only. modes: `streaming`, `bounded`, `keep_cached`; `force:true` makes playlists ignore their own mode. |
| `/playlist predownload <playlist>` | admin-only hook for permanent playlist downloads into `cache/plst-<cache-key>.<ext>`. disabled by default. |

Users in `noplaylistcreate` cannot use playlist creation/import commands.

## admin

| command | purpose |
| --- | --- |
| `/cachestatus` | show cache directory, size, file count, global playlist cache mode, and force-global state. admin only. |
| `/cachequeue [include_current]` | download the current song plus upcoming queue into `cache/` immediately. skips tracks requested by `nodownload` users and writes `queue-blackbox.json` audit events. admin only. |
| `/purgecache` | delete validated media files from `cache/`, keeping the current playing file if present, and report scanned/removed/skipped/metadata-cleaned counts. admin only. |
| `/togglelog [toggle\|download\|debug\|admin\|all\|normal\|off]` | control logging and Discord download logs. `download` keeps normal INFO logging but enables editable `/play` progress messages; `debug` enables DEBUG logging too; `admin`/`all` turn on the larger user-space operation event trail, including automatic alone speed-reset notices and bot status update errors. admin only. |
| `/toggledownload` | switch between download-and-play mode and stream-only mode. admin only. |
| `/disablelinks` | toggle whether queue-style displays are allowed to show youtube links. admin only. |
| `/volume_session <1-50>` | hard-set this bot session's volume until disconnect within the safety cap. admin only. |
| `/volume_default <1-50>` | save the current voice channel's safe default volume in `channel-volume-config.json`. admin only. |
| `/volume_force <1-100> [save_default]` | intentionally bypass the 50 percent safety cap for the current session; `save_default:true` stores a forced default for the current voice channel. admin only. |
| `/autoleave <enabled> [delay_seconds]` | when enabled, save the current song and queue and leave if the bot is alone in voice for the configured delay. admin only. |
| `/setdeletetime <seconds>` | set how long downloaded song files wait after playback before delayed cleanup deletes them. admin only. |
| `/reboot` | save the queue, ask for confirmation, disconnect, and exit the bot process. admin only. |
| `/status [view]` | show runtime diagnostics, detailed playback status, the full suggestion session, or the last five commands. admin only except `/status play` when public access is enabled. |
| `/config show` | show a reaction-toggleable runtime config panel for download mode, Discord download logs, DEBUG logging, admin operation trail, queue links, auto-leave, favorites autocache, playlist cache policy, playspeed allow-all, `/nowplaying` cooldown, public `/status play`, and voice votes. admin only. |
| `/userstats <user>` | show one user's restriction groups, favorites summary, playlist ownership/management, queued/session requests, recent commands, and recent music requests. admin only. |
| `/playspeed <speed>` | hidden operational speed command. usable by admins, users in `playspeed`, or everyone when allow-all is enabled. applies to future audio sources; current audio changes on next track or replay. if the bot is alone for the configured alone delay, speed resets to normal `1x`. |
| `/playspeedaccess <enabled>` | allow or restrict speed controls for everyone. admin only. |
| `/nowplayingcooldown <seconds>` | configure the `/nowplaying` per-channel non-admin cooldown. admin only. |
| `/usergroup add <user> <group>` | add a runtime restriction group to a user. admin only. |
| `/usergroup remove <user> <group>` | remove a runtime restriction group from a user. admin only. |
| `/usergroup list <user>` | list a user's runtime restriction groups. admin only. |

restriction groups live in `user-permissions.json`: `nodownload` makes that user's requests stream-only and prevents favorite cache entries for that user, `novolumechange` blocks `/volume`, `noplaylistcreate` blocks playlist creation/import, `noqueueskip` blocks `/playtop` queue jumps and `/queuefirst`/`/qfirst`, `noskip` blocks `/skip` and skip votes, `norepeat` blocks repeat reactions plus `/play repeat`, and `playspeed` grants speed controls when allow-all is off. the global voice vote toggle lives in the same runtime config; when disabled, same-channel users act directly but restriction groups still win.

## user permissions

| command | purpose |
| --- | --- |
| `/permissions` | show `normal user` when you have no restriction groups, or list assigned groups. |

status views:

- `latest`: runtime status plus the latest music suggestion.
- `play`: detailed current playback status, including known codec, bitrate, BPM, duration, cache, speed, queue, voice, repeat, and bot status fields. admins can make this public through `/config show`.
- `session`: music suggestion history for the current bot session.
- `commands`: the last five slash commands used this session.

the bot's Discord presence is also playback-aware: idle shows `/play (yt-link)`, active playback prefers `song - artist` from YouTube metadata, then falls back to `PLAYING (video title)`, `???`, or the idle prompt on hard update errors.

## quotes

| command | purpose |
| --- | --- |
| `/backup_teekkari_quotes` | scan the configured quotes channel and back up all messages. |
| `/random_quote` | return a random saved quote. |

## spotify

requires `SPOTIFY_ENABLED=true` in `.env` and the optional spotify dependencies installed. users in `noplaylistcreate` cannot use these commands.

| command | purpose |
| --- | --- |
| `/spotify import <url> [name] [auto]` | import a spotify playlist into a new bot playlist. `url` is the spotify playlist url, uri, or bare id. `name` overrides the playlist name; if omitted the spotify playlist name is used. `auto:true` skips manual review and imports all tracks with confidence above the auto threshold. the bot posts a summary message with reaction controls to accept, skip uncertain matches, or step through each one manually. |
| `/spotify status` | show the status of your active spotify import if one is in progress, including how many tracks are pending, accepted, or skipped and how long until it expires. |

spotify imports match tracks to youtube using a confidence score built from title similarity (40%), artist similarity (30%), duration match (20%), and youtube result type (10%). tracks above 0.82 confidence are accepted automatically; tracks between 0.50 and 0.82 go to manual review; tracks below 0.30 are skipped. the import session expires after 10 minutes. during manual review, react `👍` to accept, `👎` to skip, `🔄` to try the next youtube result, or `⏭️` to skip the remaining uncertain tracks and finish.

## help

| command | purpose |
| --- | --- |
| `/help` | show the in-discord command summary. react `📖` to expand or compact it; expanded help is paged with `◀️` and `▶️` so it stays under Discord's message limit. |
| `/help topic:all` | show every registered slash command and subcommand in paged help. |
| `/help command:<command>` | show a manpage-style help page for any root command, for example `/help command:nytsoi`, `/help command:play`, or `/help command:purgecache`. |
| `/help command:playlist <subcommand>` | show playlist subcommand help without setting a topic, for example `/help command:playlist new`. |
| `/help topic:playlists` | show the playlist quick-start help page. |
| `/help topic:playlist command:<subcommand>` | show a manpage-style playlist subcommand help page. available pages: `new`, `list`, `show`, `play`, `edit`, `add`, `fill`, `addmod`, `remove`, `delete`, `rename`, `removesong`, `move`, `lock`, `cachemode`, `cacheglobal`, `rescue`, `predownload`. |

Every slash command has a command-specific help page. Use command names without the leading slash.
