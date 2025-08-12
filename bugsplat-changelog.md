## 2025-08-12
- Play commands now check for a connected voice client before starting playback. If the bot isn't in a channel, it joins the caller's channel or asks them to join one, preventing stray ffmpeg processes.
- Fixed slash command error handler so it replies properly; no more 404 'Unknown interaction' when something breaks.
