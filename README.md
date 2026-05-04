# discord music bot x)

a discord music bot for playing audio from any youtube video in your server’s voice channel. to use it, you need a bot token and invite url—see the [discord developer quick-start bullshittery on their devsite](https://discord.com/developers/docs/quick-start/getting-started).

also has commands for handling, saving, and displaying quotes from a specific channel.
also supports local saved playlists with owners, managers, public/private visibility, and playlist playback.
downloaded media is stored under `cache/`; playlist folders under `playlists/` contain metadata only.

## docs

- [Features](docs/FEATURES.md) - man-page style overview of the bot, playback tech, queue behavior, and restore flow.
- [Commands](docs/COMMANDS.md) - clean command reference with every slash command and now-playing reaction.

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
  - `/play <youtube url|query|playlist:name>`
  - `/play:last`
  - `/playtop <query>`
  - `/enqueue <query|playlist:name>` (alias: `/q`)
  - `/queue [links]` (alias: `/queuelist`)
  - `/queuefirst <position|playlist:name>` (alias: `/qfirst`)
  - react `📜` on now-playing to toggle the queue above the current song
  - `/skip` (non-admins vote)
  - `/pause` / `/resume`
  - `/stop` (non-admins vote)
  - `/volume <1–100>` (non-admins vote)
  - `/now` (alias `/nytsoi`)
  - `/getqueue`

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
  - `/playlist add <playlist> <current|queue|url> [queue_position] [url]`
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
  - `/help topic:playlists` and `/help topic:playlist command:new`

- **admin-only**:
  - `/cachestatus`
  - `/purgecache`
  - `/purgequeue`
  - `/playlist predownload <playlist>` (disabled unless `PLAYLIST_PREDOWNLOAD_ENABLED=true`)
  - `/autoleave <enabled> [delay_seconds]`
  - `/setdeletetime <seconds>`
  - `/volume_session <1–100>`
  - `/volume_default <1–100>`
  - `/togglelog [toggle|debug|normal|off]`
  - `/toggledownload`
  - `/disablelinks`
  - `/reboot`
  - `/status [view]`

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

- **dependabot alerts for aiohttp or python-dotenv**:
  run `pip install --upgrade -r requirements.txt`. the requirements require `aiohttp>=3.13.4,<4.0` for the 2026 aiohttp DoS fixes and `python-dotenv>=1.2.2,<2.0` for the `.env` symlink rewrite fix.

- **non-youtube urls rejected**:
  public users can provide youtube links or normal search text. raw non-youtube URLs, local URLs, and private-network URLs are rejected before `yt-dlp` runs to reduce SSRF and local-network probing risk.

- **runtime media cache**:
  downloaded audio lives in `cache/`, not the repository root. normal `/play` downloads use `cache/<base64url-canonical-youtube-url>.<ext>`. playlist long-term cache files use `cache/plst-<base64url-canonical-youtube-url>.<ext>`. raw youtube titles and user input are not used in cache filenames.
  exact legacy files named `cache/<youtube-id>.<ext>` or `cache/plst-<youtube-id>.<ext>` are adopted to the canonical cache name when that video is requested.

- **playlist storage**:
  playlists are metadata-first. each playlist folder contains `metadata.json`; audio files do not live under `playlists/`. track entries include youtube metadata plus cache fields such as `cache_key`, `cache_mode`, `cache_path`, and `ext` so playback can stream or reuse a safe file in `cache/`.

- **playlist cache limits**:
  playlist caching defaults to bounded mode: at most 15 tracks or 3 GB are cached per playlist play operation, and remaining tracks stream when needed. admins can change the persistent global mode with `/playlist cacheglobal`, override a playlist with `/playlist cachemode`, inspect cache with `/cachestatus`, and purge safe cache files with `/purgecache`. the hard cache cap is 20 GB; when it is reached, new downloads fall back to streaming.

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
