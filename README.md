# discord music bot x)

a discord music bot for playing audio from any youtube video in your server’s voice channel. to use it, you need a bot token and invite url—see the [discord developer quick-start bullshittery on their devsite](https://discord.com/developers/docs/quick-start/getting-started).

also has commands for handling, saving, and displaying quotes from a specific channel.
also supports YouTube playlist links, per-user favorites, plus local saved playlists with owners, managers, public/private visibility, and playlist playback.
downloaded media is stored under `cache/`; playlist folders under `playlists/` contain metadata only.

## docs

- [Features](docs/FEATURES.md) - man-page style overview of the bot, playback tech, queue behavior, and restore flow.
- [Commands](docs/COMMANDS.md) - clean command reference with every slash command and now-playing reaction.
- [Recent updates](RECENT_UPDATES.md) - user-facing summary shown by `/whatsnew`.

---

## requirements

- **python 3.8+**  
- **ffmpeg** installed (`sudo apt install ffmpeg`)  
- **deno** or **node 20+** on `PATH` for current yt-dlp YouTube challenge handling
- a discord bot token and guild/channel id (for quotes functionality)

---

## usage

```bash
cd discordmusic
python3 setup_assistant.py
```

the setup assistant guides you through the discord developer portal, writes `.env`,
creates the venv, can install `screen`, can start the bot in a screen session,
and can optionally install a systemd service on linux.

## setting up

the assistant is the easiest setup path. advanced users can still create `.env`
manually with these values:

```bash
# bot authentication
BOT_TOKEN=your_discord_bot_token
MY_GUILD=your_guild_id
QUOTES_ID=0  # optional quotes channel id, or 0 to disable quotes

# admin configuration
ADMIN_USER_ID=your_discord_user_id
ADMIN_ROLE_ID=optional_admin_role_id
# Production admin access should use ADMIN_USER_ID or ADMIN_ROLE_ID.
# Role-name admin is for development/compatibility only.
ADMIN_ROLE_NAME=Bottiadmin
ALLOW_ADMIN_ROLE_NAME=false

# optional runtime tuning
DOWNLOAD_DELETE_DELAY_SECONDS=600
YTDLP_NO_CHECK_CERTIFICATE=false
MAX_PLAYLIST_TRACKS=100
MAX_URLS_PER_MESSAGE=10
```

Keep `YTDLP_NO_CHECK_CERTIFICATE=false` in production so yt-dlp verifies TLS certificates. Set it to `true` only as a temporary debug override. Guided `/playlist new` accepts up to `MAX_URLS_PER_MESSAGE` YouTube links per message and stores up to `MAX_PLAYLIST_TRACKS` tracks per playlist creation session. The bot starts at 20% volume unless a voice-channel default has been saved by an admin.

---

## features

- **slash commands**:
  - `/join`
  - `/play <youtube url|youtube playlist url|query|playlist:name> [repeat] [speed] [show_download_log]`
  - `/play <query> -repeat <count>` (single tracks only; above 20 becomes repeat-one loop)
  - `/play <query> --speed:<0.1-2>` (single tracks only; requires admin, `playspeed`, or allow-all)
  - `/play -favorites username`
  - `/play:last`
  - `/playtop <query|youtube playlist url>`
  - `/enqueue <query|youtube playlist url|playlist:name>` (alias: `/q`)
  - `/queue [links]` (alias: `/queuelist`)
  - `/queuefirst <position|youtube playlist url|playlist:name>` (alias: `/qfirst`)
  - react `⭐` on now-playing to toggle the current song in your favorites
  - react `🔂` on now-playing to toggle repeat-one
  - react `📜` on now-playing to toggle the queue above the current song
  - `/skip` (non-admins vote unless voice votes are disabled)
  - `/pause` / `/resume`
  - `/stop` (non-admins vote unless voice votes are disabled)
  - `/volume <1–50>` (non-admins vote unless voice votes are disabled)
  - `/now` (alias `/nytsoi`)
  - `/nowplaying` (reposts controls without the video URL; cooldown protected)
  - `/getqueue`
  - `/whatsnew`

- **favorites**:
  - `/favorites play [user]`
  - `/favorites list [user]`
  - `/favorites privacy <public|private>`
  - `/favorites status`
  - `/play -favorites username` (alias for playing a user's public favorites)
  - `/permissions`

- **queue management**:
  - `/clear_queue`
  - `/restorequeue`

- **playlists**:
  - `/playlist list`
  - `/playlist new` guided creation flow
  - `/playlist new <name> current` (also accepts `currentqueue` and `jono`)
  - `/playlist new <name> [private|public]`
  - `/playlist edit <name>`
  - `/playlist show <name>`
  - `/playlist play <name>`
  - `/playlist add <playlist> <current|queue|url> [queue_position] [url]` (URL can be a YouTube video or playlist link)
  - `/playlist fill current <playlist>`
  - `/playlist addmod <playlist> <user>`
  - `/playlist remove <playlist> [flags]`
  - `/playlist delete <playlist> [flags]`
  - `/playlist rename <playlist> <new_name> [flags]`
  - `/playlist removesong <playlist> <position>`
  - `/playlist move <playlist> <from_position> <to_position>`
  - `/playlist lock <playlist> <locked>`
  - `/playlist cachemode <playlist> <follow_global|streaming|bounded|keep_cached>` (admin-only)
  - `/playlist cacheglobal <streaming|bounded|keep_cached> [force]` (admin-only)
  - `/help command:<command>`, `/help command:playlist new`, `/help topic:playlists`, and `/help topic:playlist command:new`
  - `/help` expanded view is paged with `◀️`/`▶️`

- **admin-only**:
  - `/favorites cacheglobal <enabled> [max_gb] [per_user_tracks]`
  - `/favorites cacheuser <user> <enabled>`
  - `/usergroup add <user> <nodownload|novolumechange|noplaylistcreate|noqueueskip|noskip|norepeat|playspeed>`
  - `/usergroup remove <user> <group>`
  - `/usergroup list <user>`
  - `/cachestatus`
  - `/cachequeue [include_current]`
  - `/purgecache`
  - `/purgequeue`
  - `/playlist predownload <playlist>` (disabled unless `PLAYLIST_PREDOWNLOAD_ENABLED=true`)
  - `/autoleave <enabled> [delay_seconds]`
  - `/setdeletetime <seconds>`
  - `/volume_session <1–50>`
  - `/volume_default <1–50>`
  - `/volume_force <1–100> [save_default]`
  - `/togglelog [toggle|download|debug|admin|all|normal|off]`
  - `/toggledownload`
  - `/disablelinks`
  - `/reboot`
  - `/status [view]` (`play` can be made public from `/config show`; other views are admin-only)
  - `/config show`
  - `/userstats <user>`
  - `/playspeed <0.1-2>` (hidden operational command; admin, `playspeed`, or allow-all)
  - `/playspeedaccess <enabled>` (admin-only)
  - `/nowplayingcooldown <seconds>` (admin-only)

- **quotes**:
  - `/backup_teekkari_quotes`
  - `/random_quote`

## troubleshooting

- **view logs**:  
  ```bash
  cd discordmusic
touch output.log
tail -f output.log
```

- **missing python module**:  
  ```bash
  source venv/bin/activate
  pip install <package>
  pip freeze > requirements.txt
  ```

- **youtube “confirm you're not a bot” error**:  
  update yt-dlp with `pip install --upgrade -r requirements.txt` and make sure `deno` or `node` is on `PATH`. if YouTube still blocks your server IP, export YouTube cookies to `cookies.txt` and set `YTDLP_COOKIEFILE=cookies.txt` in `.env`.

- **youtube unavailable search results**:
  if the first search result is unavailable, the bot tries a few fallback search results before failing. direct unavailable YouTube links still fail, but users get a specific availability message instead of a generic queue error. admins also see a reminder when no `deno` or `node` runtime is available.

- **dependabot alerts for aiohttp or python-dotenv**:
  run `pip install --upgrade -r requirements.txt`. the requirements require `aiohttp>=3.13.4,<4.0` for the 2026 aiohttp DoS fixes and `python-dotenv>=1.2.2,<2.0` for the `.env` symlink rewrite fix.

- **non-youtube urls rejected**:
  public users can provide youtube links or normal search text. raw non-youtube URLs, local URLs, and private-network URLs are rejected before `yt-dlp` runs to reduce SSRF and local-network probing risk.

- **runtime media cache**:
  downloaded audio lives in `cache/`, not the repository root. normal `/play` downloads use `cache/<base64url-canonical-youtube-url>.<ext>`. playlist long-term cache files use `cache/plst-<base64url-canonical-youtube-url>.<ext>`. raw youtube titles and user input are not used in cache filenames.
  exact legacy files named `cache/<youtube-id>.<ext>` or `cache/plst-<youtube-id>.<ext>` are adopted to the canonical cache name when that video is requested.
  admins can run `/cachequeue` to download the current song plus upcoming queue into `cache/` immediately. it reuses existing safe cache files, skips tracks from `nodownload` users, respects the hard cache cap, and writes queue audit entries to `queue-blackbox.json`.

- **runtime audit logging**:
  impactful runtime actions append sanitized entries to `runtime-audit.json` and write concise `output.log` lines. this covers config toggles, cache purge/cachequeue, queue clears that delete files, delayed cleanup, cache hits/downloads, stream fallbacks, and `/play last` restore decisions. runtime audit files are local operational state and should not be committed.

- **playback recovery and diagnostics**:
  `/play last` only restores recent auto-leave recovery files that were marked by the bot as auto-leave saves; stale or legacy recovery files are rejected, removed, and logged to `queue-blackbox.json`. `/status play` shows detailed current playback diagnostics such as codec, bitrate, BPM when known, duration/position, cache state, speed, repeat, queue, and voice state. admins can make only that playback status view public through `/config show`.

- **voice votes and active playlists**:
  skip, stop, volume, previous, and guarded repeat-off use voice votes for non-admins by default. admins always act directly. admins can toggle voice votes from `/config show`; when disabled, same-voice-channel non-admins act directly too, while restriction groups such as `noskip`, `novolumechange`, `norepeat`, and `noqueueskip` still block their actions. while an active playlist is playing, ordinary song requests only show the move-next prompt when votes are enabled and at least three human users are in voice; admins and disabled-vote sessions do not get that prompt.

- **playlist storage**:
  playlists are metadata-first. each playlist folder contains `metadata.json`; audio files do not live under `playlists/`. track entries include youtube metadata plus cache fields such as `cache_key`, `cache_mode`, `cache_path`, and `ext` so playback can stream or reuse a safe file in `cache/`.

- **favorites privacy and storage**:
  favorites are special per-user playlists stored under `playlists/favorites-<user-id>/metadata.json`. the now-playing star toggles the current song in or out of the reacting user's favorites and logs the change. favorites are private by default, can be made public with `/favorites privacy public`, and can be played by the owner with `/favorites play` or by others when public with `/favorites play user` or `/play -favorites username`. this privacy is a social bot setting, not strong secrecy: admins can override private favorites after a confirmation prompt, and anyone with filesystem access can read playlist metadata.

- **favorites cache and user restrictions**:
  favorites autocache is off by default. admins can enable it with `/favorites cacheglobal`; favorites cache files use `cache/plst-<cache-key>.<ext>`, never playlist folders, and the favorites cache policy is capped at 6 GiB globally. cache selection is round-robin across eligible users and considers 30 favorites per user by default, up to the supported maximum of 100 stored favorites per user. runtime user rules live in `user-permissions.json`: `nodownload` forces a user's requests to stream, `novolumechange` blocks `/volume`, `noplaylistcreate` blocks playlist creation/import, `noqueueskip` blocks queue jump/reorder commands, `noskip` blocks skip commands/votes, `norepeat` blocks repeat reactions plus `/play repeat`, and `playspeed` grants speed controls when allow-all is off.

- **playlist cache limits**:
  playlist caching defaults to bounded mode: playlist playback queues or starts immediately, then warms the cache in the background for at most the first 15 tracks or 3 GB; remaining tracks stream when needed. admins can change the persistent global mode with `/playlist cacheglobal`, override a playlist with `/playlist cachemode`, inspect cache with `/cachestatus`, and purge safe cache files with `/purgecache`. the hard cache cap is 20 GB; when it is reached, new downloads fall back to streaming.

- **startup warning: no deno or node executable found in path**:
  install Deno on the host and make sure the bot process can find it:
  ```bash
  curl -fsSL https://deno.land/install.sh | sh
  export PATH="$HOME/.deno/bin:$PATH"
  deno --version
  ```
  if the bot runs through systemd, add the same Deno bin directory to the service `PATH`, then reload and restart:
  ```bash
  sudo systemctl daemon-reload
  sudo systemctl restart YOUR_SERVICE_NAME
  ```
  after restart, `output.log` should include `YouTube JS runtime located at ...` instead of the warning.

- **permission errors/venv issues**:  
  ```bash
  rm -rf venv
  python3 -m venv venv
  source venv/bin/activate
  pip install --upgrade -r requirements.txt
  ```

- **voice joins then instantly leaves with websocket 4006**:  
  this is a known failure with older `discord.py` voice handshakes. update the venv with:
  ```bash
  source venv/bin/activate
  pip install --upgrade -r requirements.txt
  ```

- **ffmpeg not installed**:  
  ```bash
  sudo apt update && sudo apt install ffmpeg
  ```

- **systemd deployment**:  
  ensure your service’s `execstart` points to `venv/bin/python main.py` and uses `environmentfile` for `.env`.

---

## credit

original code by **@alwayslati**, maintained and extended by me.
