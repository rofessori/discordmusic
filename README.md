# discord music bot x)

a discord music bot for playing audio from any youtube video in your server’s voice channel. to use it, you need a bot token and invite url—see the [discord developer quick-start bullshittery on their devsite](https://discord.com/developers/docs/quick-start/getting-started).

also has commands for handling, saving, and displaying quotes from a specific channel.

---

## requirements

- **python 3.8+**  
- **ffmpeg** installed (`sudo apt install ffmpeg`)  
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

## configuration

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
admin_username=
```

---

## features

- **slash commands**:
  - `/join`
  - `/play <url|query>`
  - `/playtop <query>`
  - `/enqueue <query>` (aliases: `/queue`, `/q`)
  - `/queuelist`
  - `/skip`
  - `/pause` / `/resume`
  - `/stop`
  - `/volume <1–100>`
  - `/now` (alias `/nytsoi`)
  - `/getqueue`

- **queue management**:
  - `/clear_queue`
  - `/purgequeue`
  - `/restorequeue`

- **admin-only**:
  - `/togglelog`
  - `/toggledownload`
  - `/reboot`

- **quotes**:
  - `/backup_teekkari_quotes`
  - `/random_quote`

---

## how it works

1. **command handling**  
   uses `discord.py` with slash commands synced to your guild.

2. **youtube fetch & playback**  
   - non-url input triggers a quick web search via `urllib` + regex.
   - `yt-dlp` extracts metadata and either **streams** or **downloads & plays**.
   - audio piped into discord with `ffmpegpcmaudio` (with automatic reconnect).

3. **caching & cleanup**  
   - downloads saved as `<extractor>-<id>-<title>.<ext>`.
   - `downloads.json` tracks file paths and timestamps.
   - deletes files older than 1 hour at startup and schedules deletion 10 minutes after playback.

4. **queue & controls**  
   - maintains fifo `queue`.
   - “now playing” message adds ◀️⏸️▶️ reactions for skip/pause/resume.

5. **quotes system**  
   - `quotes.py` writes messages from your designated channel (`quotes_id`) into `quotes.txt`.
   - `/random_quote` returns a random line; `/backup_teekkari_quotes` rebuilds the file.

---

## tips & troubleshooting

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
  export youtube cookies and set `ytdl_options['cookiefile']='cookies.txt'` in `main.py`.

- **permission errors/venv issues**:  
  ```bash
  rm -rf venv
  python3 -m venv venv
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
