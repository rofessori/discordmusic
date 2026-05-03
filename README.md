# discord music bot x)

a discord music bot for playing audio from any youtube video in your server’s voice channel. to use it, you need a bot token and invite url—see the [discord developer quick-start bullshittery on their devsite](https://discord.com/developers/docs/quick-start/getting-started).

also has commands for handling, saving, and displaying quotes from a specific channel.

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
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # ← edit .env with your values
python main.py
```

## setting up

copy `.env.example` to `.env` and fill the following (replace with your real tokens and ids):

```bash
# bot authentication
bot_token=your_discord_bot_token
my_guild=your_guild_id
quotes_id=your_quotes_channel_id

# admin configuration (defaults)
admin_role_name=bottiadmin
# optional admin user override:
admin_user_id=
```

---

## features

- **slash commands**:
  - `/join`
  - `/play <youtube url|query>`
  - `/playtop <query>`
  - `/enqueue <query>` (alias: `/q`)
  - `/queue [links]` (alias: `/queuelist`)
  - `/queuefirst <position>` (alias: `/qfirst`)
  - react `📜` on now-playing to toggle the queue above the current song
  - `/skip`
  - `/pause` / `/resume`
  - `/stop`
  - `/volume <1–100>`
  - `/now` (alias `/nytsoi`)
  - `/getqueue`

- **queue management**:
  - `/clear_queue`
  - `/restorequeue`

- **admin-only**:
  - `/purgequeue`
  - `/togglelog`
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
