# commands

clean reference for the bot's slash commands and now-playing reaction controls.

## music playback

| command | purpose |
| --- | --- |
| `/join` | join the voice channel you are currently in. |
| `/play <youtube url, search, or playlist:name>` | play a youtube result or playlist immediately, or add it to the queue if something is already playing. raw non-youtube urls are rejected. |
| `/play:last` | restore the last auto-saved voice session after auto-leave. in Discord slash options this is entered as `/play` with `last`, `play:last`, or `/play:last` as the value. |
| `/playtop <query>` | add a track to the front of the queue so it plays next. if nothing is playing, it starts immediately. |
| `/enqueue <query or playlist:name>` | add a track or playlist to the end of the queue. |
| `/q <query or playlist:name>` | alias for `/enqueue`. |
| `/queue [links]` | show the upcoming songs in the queue. set `links:true` to include youtube urls when links are enabled. |
| `/queuelist [links]` | alias for `/queue`. |
| `/queuefirst <position or playlist:name>` | move an existing queued song or playlist to the front of the queue. |
| `/qfirst <position or playlist:name>` | alias for `/queuefirst`. |
| `/skip` | vote to skip the current track and continue to the next queued track. admins bypass the vote. |
| `/stop` | vote to stop playback, clear the queue, and disconnect from voice. admins bypass the vote. |
| `/pause` | pause the current playing audio. requires the same voice channel unless the user is an admin. |
| `/resume` | resume paused audio. requires the same voice channel unless the user is an admin. |
| `/volume <1-100>` | vote to set playback volume from 1 to 100 percent. admins bypass the vote. |
| `/now` | show the currently playing song. |
| `/nytsoi` | finnish alias for `/now`. |
| `/getqueue` | list all songs requested in the current session and show whether they are playing, queued, played, or removed. |

## now-playing reactions

| reaction | purpose |
| --- | --- |
| `◀️` | vote to replay the previous track when one is available. admins bypass the vote. |
| `⏸️` | pause or resume playback. requires the same voice channel unless the user is an admin. |
| `▶️` | vote to skip to the next track. admins bypass the vote. |
| `📜` | toggle the current queue above the now-playing message. requires the same voice channel unless the user is an admin. |

## queue management

| command | purpose |
| --- | --- |
| `/clear_queue` | clear the current song queue. requires the same voice channel unless the user is an admin; admins are prompted to optionally delete downloaded files. |
| `/purgequeue` | delete downloaded song files from disk while keeping the queue intact. admin only; the currently playing file is not deleted. |
| `/restorequeue` | restore a recently cleared queue or a queue saved during reboot. admin only, time-limited. |

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
| `/playlist add <playlist> current` | add the currently playing song to a playlist you can edit. |
| `/playlist add <playlist> queue <position>` | add a queued song by queue number to a playlist you can edit. |
| `/playlist add <playlist> url <url>` | add a youtube url directly to a playlist you can edit. |
| `/playlist fill current <playlist>` | add queued songs that are not already in the playlist. |
| `/playlist addmod <playlist> <user>` | add a manager to a playlist you own. |
| `/playlist remove <playlist> [flags]` | remove a whole playlist after confirmation. it can be rescued for 600 seconds. admins can use `-now`; `-now -force` skips confirmation. |
| `/playlist delete <playlist> [flags]` | alias for `/playlist remove`. |
| `/playlist rename <playlist> <new_name> [flags]` | rename a playlist you own or manage. admins can rename any playlist after confirmation unless `-force` is supplied. |
| `/playlist removesong <playlist> <position> [flags]` | remove a song from a playlist you can edit. admins editing someone else's playlist are asked to confirm unless `-force` is supplied. |
| `/playlist move <playlist> <from> <to> [flags]` | reorder songs inside a playlist you can edit. admins editing someone else's playlist are asked to confirm unless `-force` is supplied. |
| `/playlist lock <playlist> <locked>` | lock or unlock manager edits. owner/admin only. |
| `/playlist cachemode <playlist> <mode>` | set one playlist's cache behavior. admin only. modes: `follow_global`, `streaming`, `bounded`, `keep_cached`. |
| `/playlist cacheglobal <mode> [force]` | set the persistent global playlist cache behavior. admin only. modes: `streaming`, `bounded`, `keep_cached`; `force:true` makes playlists ignore their own mode. |
| `/playlist predownload <playlist>` | admin-only hook for permanent playlist downloads into `cache/plst-<cache-key>.<ext>`. disabled by default. |

## admin

| command | purpose |
| --- | --- |
| `/cachestatus` | show cache directory, size, file count, global playlist cache mode, and force-global state. admin only. |
| `/purgecache` | delete validated media files from `cache/`, keeping the current playing file if present, and report scanned/removed/skipped/metadata-cleaned counts. admin only. |
| `/togglelog [toggle\|debug\|normal\|off]` | toggle verbose debug logging. `debug` also enables editable `/play` download debug messages. admin only. |
| `/toggledownload` | switch between download-and-play mode and stream-only mode. admin only. |
| `/disablelinks` | toggle whether queue-style displays are allowed to show youtube links. admin only. |
| `/volume_session <1-100>` | hard-set this bot session's volume until disconnect. admin only. |
| `/volume_default <1-100>` | save the current voice channel's default volume in `channel-volume-config.json`. admin only. |
| `/autoleave <enabled> [delay_seconds]` | when enabled, save the current song and queue and leave if the bot is alone in voice for the configured delay. admin only. |
| `/setdeletetime <seconds>` | set how long downloaded song files wait after playback before delayed cleanup deletes them. admin only. |
| `/reboot` | save the queue, ask for confirmation, disconnect, and exit the bot process. admin only. |
| `/status [view]` | show runtime diagnostics, the full suggestion session, or the last five commands. admin only. |

status views:

- `latest`: runtime status plus the latest music suggestion.
- `session`: music suggestion history for the current bot session.
- `commands`: the last five slash commands used this session.

## quotes

| command | purpose |
| --- | --- |
| `/backup_teekkari_quotes` | scan the configured quotes channel and back up all messages. |
| `/random_quote` | return a random saved quote. |

## help

| command | purpose |
| --- | --- |
| `/help` | show the in-discord command summary. react `📖` to expand it. |
| `/help command:<command>` | show a manpage-style help page for any root command, for example `/help command:nytsoi`, `/help command:play`, or `/help command:purgecache`. |
| `/help command:playlist <subcommand>` | show playlist subcommand help without setting a topic, for example `/help command:playlist new`. |
| `/help topic:playlists` | show the playlist quick-start help page. |
| `/help topic:playlist command:<subcommand>` | show a manpage-style playlist subcommand help page. available pages: `new`, `list`, `show`, `play`, `edit`, `add`, `fill`, `addmod`, `remove`, `delete`, `rename`, `removesong`, `move`, `lock`, `cachemode`, `cacheglobal`, `rescue`, `predownload`. |

Every slash command has a command-specific help page. Use command names without the leading slash.
