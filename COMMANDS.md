# commands

clean reference for the bot's slash commands and now-playing reaction controls.

## music playback

| command | purpose |
| --- | --- |
| `/join` | join the voice channel you are currently in. |
| `/play <url or search>` | play a youtube url or search result immediately, or add it to the queue if something is already playing. |
| `/playtop <query>` | add a track to the front of the queue so it plays next. if nothing is playing, it starts immediately. |
| `/enqueue <query>` | add a track to the end of the queue. |
| `/q <query>` | alias for `/enqueue`. |
| `/queue` | show the upcoming songs in the queue. |
| `/queuelist` | alias for `/queue`. |
| `/queuefirst <position>` | move an existing queued song to the front of the queue by its 1-based position. |
| `/qfirst <position>` | alias for `/queuefirst`. |
| `/skip` | skip the current track and continue to the next queued track. |
| `/stop` | stop playback, clear the queue, and disconnect from voice. |
| `/pause` | pause the current playing audio. |
| `/resume` | resume paused audio. |
| `/volume <1-100>` | set playback volume from 1 to 100 percent. |
| `/now` | show the currently playing song. |
| `/nytsoi` | finnish alias for `/now`. |
| `/getqueue` | list all songs requested in the current session and show whether they are playing, queued, played, or removed. |

## now-playing reactions

| reaction | purpose |
| --- | --- |
| `◀️` | replay the previous track when one is available. |
| `⏸️` | pause or resume playback. |
| `▶️` | skip to the next track. |
| `📜` | toggle the current queue above the now-playing message. |

## queue management

| command | purpose |
| --- | --- |
| `/clear_queue` | clear the current song queue. admins are prompted to optionally delete downloaded files. |
| `/purgequeue` | delete downloaded song files from disk while keeping the queue intact. the currently playing file is not deleted. |
| `/restorequeue` | restore a recently cleared queue or a queue saved during reboot. admin only, time-limited. |

## admin

| command | purpose |
| --- | --- |
| `/togglelog` | toggle verbose debug logging. admin only. |
| `/toggledownload` | switch between download-and-play mode and stream-only mode. admin only. |
| `/reboot` | save the queue, ask for confirmation, disconnect, and exit the bot process. admin only. |
| `/status` | show runtime diagnostics such as playback mode, queue length, current track, log level, and startup warnings. admin only. |

## quotes

| command | purpose |
| --- | --- |
| `/backup_teekkari_quotes` | scan the configured quotes channel and back up all messages. |
| `/random_quote` | return a random saved quote. |

## help

| command | purpose |
| --- | --- |
| `/help` | show the in-discord command summary. |
