# Repository Guidelines

## Project Structure & Module Organization
Core runtime logic lives in `main.py`, which wires Discord intents, audio queueing, and yt-dlp downloads. Quote persistence is isolated in `quotes.py`, producing `quotes.txt` at runtime. Runtime artifacts such as `downloads.json`, `queue_backup.json`, and `queue_backup.tmp` live at the repo root; keep them out of commits unless they are fixtures. Environment secrets belong in `.env` (copy from `.env.example`). Deployment helpers live in `start.sh.example`, `stop.sh.example`, and `bot.service.example` for systemd setups.

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
