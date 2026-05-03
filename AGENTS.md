# Repository Guidelines

## Project Structure & Module Organization
Core runtime logic lives in `main.py`, which wires Discord intents, audio queueing, and yt-dlp downloads. Quote persistence is isolated in `quotes.py`, producing `quotes.txt` at runtime. Runtime artifacts such as `downloads.json`, `queue_backup.json`, and `queue_backup.tmp` live at the repo root; keep them out of commits unless they are fixtures. Environment secrets belong in `.env`; if `.env` already exists, do not add or recreate an `.env.example` template unless the user explicitly asks for one. Deployment helpers live in `start.sh.example`, `stop.sh.example`, and `bot.service.example` for systemd setups.

## Build, Test, and Development Commands
Use a virtualenv to keep yt-dlp, discord.py, and PyNaCl pinned:
```bash
python3 -m venv venv && source venv/bin/activate
pip install --upgrade -r requirements.txt
python main.py           # launches the bot with slash commands synced
```
`ffmpeg` must be on `PATH` (`brew install ffmpeg` or `apt install ffmpeg`). Tail `output.log` while iterating: `touch output.log && tail -f output.log`. If voice joins then immediately leaves with websocket close code `4006`, refresh the venv from `requirements.txt`; older `discord.py` voice handshakes are known-broken, and startup diagnostics should block `discord.py<2.6.0`.

## Coding Style & Naming Conventions
Follow PEP8: four-space indentation, snake_case for functions/variables, CapWords classes (e.g., `Client`, `YTDLSource`). Keep command handlers cohesive by grouping related helpers nearby and annotate async functions with type hints when possible. Prefer `logging` over prints, reuse the module-level `logger`, and clean up temporary files within the existing download-tracking helpers. When adding commands, register them on `client.tree` and keep user-facing strings concise and lowercase to match the current style.

## Testing Guidelines
There is no automated suite yet; validate behavior manually on a staging guild. Smoke-test playback by running `python main.py`, issuing `/join`, `/play <url>`, `/queue`, and `/stop`, and watching for regressions in `output.log`. For deterministic modules (e.g., future queue utilities or quote formatting), place tests in `tests/test_<feature>.py` and run them with `pytest`. Target at least covering new helper functions and error paths, and refresh the README with any new commands.

## Commit & Pull Request Guidelines
Recent commits are short, imperative sentences (e.g., `Handle missing voice client before playback`). Follow that style, group related edits in one commit, and mention relevant issue numbers in the body. PRs should describe user-facing changes, list bot commands touched, outline manual test steps, and attach screenshots/log excerpts when altering slash-command UX. Include notes about migration needs (new env vars, files) so deployers can react before merging.

## Security & Configuration Tips
Never commit `.env`, tokens, or `quotes.txt` contents—use `.gitignore`. Rotate discord tokens after sharing test bots and revoke invite links when done. When enabling download mode, ensure disk clean-up logic stays intact and document any new directories or cache knobs in this guide.

## 2026-05-03 Queue Jump & Now Playing Notes
Focused current-state analysis before the change:
- `main.py` keeps the upcoming music list in the global `queue`; `/play`, `/playtop`, and `/enqueue` append or insert fetched track dictionaries, and `/queue` prints that list with 1-based numbering.
- Playback startup was duplicated in `/play`, `/playtop`, and `play_next_channel()`: each block built a player, updated `client.current_track_info`, sent a plain `Now playing:` message, stored it in `client.current_track_message`, and added the three control reactions.
- `on_reaction_add()` only treats reactions on `client.current_track_message` as music controls. Admin confirmation prompts for `/reboot`, large downloads, and queue clearing use separate message ids with `👍`/`👎`, so they should remain isolated from playback controls.
- The old implementation never removed playback controls from stale now-playing messages when a new announcement was sent.

Implementation plan used:
- Add shared helpers for now-playing formatting, edit-vs-send decisions, and playback-control reaction cleanup.
- Format announcements as `🎵 Now playing: **title**` plus the italicized YouTube URL on the next line.
- Edit the previous now-playing message only when it is in the same channel and no newer message exists; otherwise send a new message and remove only `◀️`, `⏸️`, and `▶️` from the old playback message.
- Add `/queuefirst <position>` and `/qfirst <position>` as 1-based queue reordering commands that move an existing queued song to the front without interrupting the current track.
- Update `/help` and `README.md` so users can discover the new commands.

Completed work log:
- Centralized now-playing publishing in `publish_now_playing()`, with `format_now_playing()`, `has_newer_message()`, `remove_control_reactions()`, and `add_control_reactions()` supporting it.
- Replaced duplicated announcement/reaction code in `/play`, `/playtop`, and `play_next_channel()` with the shared publisher.
- Added `queue_first()` plus the `/queuefirst` and `/qfirst` slash commands, including empty queue, invalid position, and already-first responses.
- Left confirmation reactions isolated: only the stored `client.current_track_message` receives playback-control handling or stale playback-control cleanup.
- Added `INFO` logs for now-playing message edits, new now-playing sends, playback-control reaction additions/removals, and `/queuefirst`/`/qfirst` validation decisions so these actions are visible in `output.log` when stdout/stderr are redirected there. The systemd example now appends stderr to `output.log` too, matching Python logging's default stream.

Queue reaction idea recorded before implementation:
- Add a `📜` reaction to the current now-playing message. Toggling it should edit that message so the current queue appears at the top with styled titles and italic URLs, followed by a clean divider and the existing styled now-playing block.
- The queue view should remember its open/closed state while the bot keeps editing the same now-playing message, but reset when a new now-playing message is sent.
- Keep cleanup scoped to now-playing controls only: stale now-playing messages lose `◀️`, `⏸️`, `▶️`, and `📜`; `/reboot` confirmation `👍`/`👎` reactions remain separate.

Queue reaction completed work:
- Added `📜` to the now-playing control reactions and wired it to toggle a queue section inside the existing now-playing message.
- The queue section renders at the top with bold numbered titles, italic YouTube URLs, a clean divider, and then the styled `🎵 Now playing:` block.
- The queue-open state is preserved when the same now-playing message is edited for the next song, and reset when a fresh now-playing message is sent.
- Reaction cleanup and logging now cover the `📜` control while leaving `/reboot` and other confirmation reactions keyed to their own messages.
