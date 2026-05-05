# commands

clean reference for the bot's slash commands and now-playing reaction controls.

## music playback

| command | purpose |
| --- | --- |
| `/join` | join the voice channel you are currently in. |
| `/play <youtube url, youtube playlist url, search, playlist:name, or -favorites username>` | play a youtube result, saved playlist, or public favorites immediately, or add it to the queue if something is already playing. raw non-youtube urls are rejected. |
| `/play:last` | restore the last auto-saved voice session after auto-leave. in Discord slash options this is entered as `/play` with `last`, `play:last`, or `/play:last` as the value. |
| `/playtop <query or youtube playlist url>` | add a track or youtube playlist block to the front of the queue so it plays next. if nothing is playing, it starts immediately. |
| `/enqueue <query, youtube playlist url, or playlist:name>` | add a track or playlist to the end of the queue. |
| `/q <query, youtube playlist url, or playlist:name>` | alias for `/enqueue`. |
| `/queue [links]` | show the upcoming songs in the queue. set `links:true` to include youtube urls when links are enabled. |
| `/queuelist [links]` | alias for `/queue`. |
| `/queuefirst <position, youtube playlist url, or playlist:name>` | move an existing queued song or playlist to the front of the queue. |
| `/qfirst <position, youtube playlist url, or playlist:name>` | alias for `/queuefirst`. |
| `/skip` | vote to skip the current track and continue to the next queued track. admins bypass the vote. |
| `/stop` | vote to stop playback, clear the queue, and disconnect from voice. admins bypass the vote. |
| `/pause` | pause the current playing audio. requires the same voice channel unless the user is an admin. |
| `/resume` | resume paused audio. requires the same voice channel unless the user is an admin. |
| `/volume <1-50>` | vote to set playback volume from 1 to 50 percent. admins bypass the vote, but the normal command keeps the ear-safety cap. |
| `/now` | show the currently playing song. |
| `/nytsoi` | finnish alias for `/now`. |
| `/getqueue` | list all songs requested in the current session and show whether they are playing, queued, played, or removed. |
| `/whatsnew` | show the recent bot update summary from `RECENT_UPDATES.md`. |

## now-playing reactions

| reaction | purpose |
| --- | --- |
| `⭐` | add the current song to your favorites. the now-playing message is edited with a short notice naming the user. |
| `◀️` | vote to replay the previous track when one is available. admins bypass the vote. |
| `⏸️` | pause or resume playback. requires the same voice channel unless the user is an admin. |
| `▶️` | vote to skip to the next track. admins bypass the vote. |
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

Favorites are special per-user playlists under `playlists/favorites-<user-id>/metadata.json`. Favorites privacy is not strong secrecy: admins can bypass private favorites with a warning prompt, and filesystem access can read metadata.

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
| `/playlist add <playlist> url <url>` | add a youtube video or playlist url directly to a playlist you can edit. |
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

Users in `noplaylistcreate` cannot use playlist creation/import commands.

## admin

| command | purpose |
| --- | --- |
| `/cachestatus` | show cache directory, size, file count, global playlist cache mode, and force-global state. admin only. |
| `/purgecache` | delete validated media files from `cache/`, keeping the current playing file if present, and report scanned/removed/skipped/metadata-cleaned counts. admin only. |
| `/togglelog [toggle\|debug\|admin\|all\|normal\|off]` | toggle verbose debug logging. `debug` enables editable `/play` download debug messages; `admin`/`all` turn on the larger user-space operation event trail. admin only. |
| `/toggledownload` | switch between download-and-play mode and stream-only mode. admin only. |
| `/disablelinks` | toggle whether queue-style displays are allowed to show youtube links. admin only. |
| `/volume_session <1-50>` | hard-set this bot session's volume until disconnect within the safety cap. admin only. |
| `/volume_default <1-50>` | save the current voice channel's safe default volume in `channel-volume-config.json`. admin only. |
| `/volume_force <1-100> [save_default]` | intentionally bypass the 50 percent safety cap for the current session; `save_default:true` stores a forced default for the current voice channel. admin only. |
| `/autoleave <enabled> [delay_seconds]` | when enabled, save the current song and queue and leave if the bot is alone in voice for the configured delay. admin only. |
| `/setdeletetime <seconds>` | set how long downloaded song files wait after playback before delayed cleanup deletes them. admin only. |
| `/reboot` | save the queue, ask for confirmation, disconnect, and exit the bot process. admin only. |
| `/status [view]` | show runtime diagnostics, the full suggestion session, or the last five commands. admin only. |
| `/usergroup add <user> <group>` | add a runtime restriction group to a user. admin only. |
| `/usergroup remove <user> <group>` | remove a runtime restriction group from a user. admin only. |
| `/usergroup list <user>` | list a user's runtime restriction groups. admin only. |

restriction groups live in `user-permissions.json`: `nodownload` makes that user's requests stream-only and prevents favorite cache entries for that user, `novolumechange` blocks `/volume`, `noplaylistcreate` blocks playlist creation/import, `noqueueskip` blocks `/playtop` queue jumps and `/queuefirst`/`/qfirst`, `noskip` blocks `/skip` and skip votes, and `norepeat` blocks repeat reactions.

## user permissions

| command | purpose |
| --- | --- |
| `/permissions` | show `normal user` when you have no restriction groups, or list assigned groups. |

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
