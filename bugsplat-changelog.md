## 2026-05-03
- Hardened the public bot surface after a cybersecurity review. User-supplied raw URLs are now limited to YouTube, local/private/non-YouTube URLs are rejected before `yt-dlp`, username-based admin overrides are ignored, `/purgequeue` is admin-only, playback controls require the same voice channel unless the user is an admin, and downloaded-file deletion validates paths before removing anything.
- Raised vulnerable dependency minimums to `aiohttp>=3.13.4,<4.0` for the 2026 aiohttp DoS advisories and `python-dotenv>=1.2.2,<2.0` for the `.env` symlink rewrite advisory.
- Fixed stale now-playing messages retaining active playback control reactions after a newer now-playing message was sent. Old now-playing messages now lose only the bot's playback controls, while `/reboot` and other confirmation prompts keep their own `👍`/`👎` reactions isolated.
- Fixed the systemd example so Python logging on stderr is appended to `output.log`; this makes now-playing edit/send, reaction cleanup, and queue-jump diagnostics visible in the documented service setup.

## 2026-05-02
- Fixed Discord voice reconnect loops where the bot joined and immediately left with websocket close code 4006. The project now requires `discord.py[voice]==2.7.1`, pins the `davey` voice dependency, and blocks startup on known-broken `discord.py<2.6.0` installs.

## 2025-08-12
- Play commands now check for a connected voice client before starting playback. If the bot isn't in a channel, it joins the caller's channel or asks them to join one, preventing stray ffmpeg processes.

- Fixed slash command error handler so it replies properly; no more 404 'Unknown interaction' when something breaks.
