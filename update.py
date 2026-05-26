#!/usr/bin/env python3
"""
update.py — Day-2 updater and health-check for the Discord music bot.

Run this any time you want to:
  - Update Python dependencies (pip install -r requirements.txt)
  - Check that required .env keys are set
  - Review and update optional module settings (webui, TV, spotify)

Usage:
    python3 update.py          # interactive update + health check
    python3 update.py --check  # read-only health check, no prompts for changes

Stdlib-only. Works before the venv exists.
"""

import os
import re
import subprocess
import sys
import shutil
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(SCRIPT_DIR, ".env")
VENV_DIR = os.path.join(SCRIPT_DIR, "venv")
REQUIREMENTS = os.path.join(SCRIPT_DIR, "requirements.txt")

CHECK_ONLY = "--check" in sys.argv

# Keys whose values must not be written back to .env by this tool.
# They are written once during initial setup and should be managed manually
# (or via a secrets manager) thereafter.
_SENSITIVE_KEYS = {"TV_WEBHOOK_SECRET", "WEBUI_SECRET_KEY", "SPOTIFY_CLIENT_SECRET"}

# ── ANSI colours ──────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
DIM    = "\033[2m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def _sanitize(msg: str) -> str:
    text = str(msg)
    text = re.sub(
        r'(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASS|API_KEY|KEY|WEBHOOK)[A-Z0-9_]*)\s*=\s*(\S+)',
        r'\1=<redacted>',
        text,
    )
    return text

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET}  {msg}")
def err(msg):  print(f"  {RED}✗{RESET}  {msg}")
def info(msg): print(f"  {CYAN}·{RESET}  {_sanitize(msg)}")

def section(title):
    print(f"\n{BOLD}{title}{RESET}")
    print("─" * 50)


# ── .env helpers ──────────────────────────────────────────────────────────────

def read_env() -> dict:
    """Read .env into a dict. Ignores comments and blank lines."""
    env = {}
    if not os.path.isfile(ENV_FILE):
        return env
    with open(ENV_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def write_env(env: dict):
    """Write env dict back to .env, preserving comments and ordering."""
    backup = ENV_FILE + f".bak.{int(time.time())}"
    if os.path.isfile(ENV_FILE):
        shutil.copy2(ENV_FILE, backup)
        info(f"Backup written to {os.path.basename(backup)}")

    lines = []
    if os.path.isfile(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            lines = f.readlines()

    written = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        if "=" in stripped:
            k = stripped.partition("=")[0].strip()
            if k in env and k not in _SENSITIVE_KEYS:
                out.append(f'{k}={env[k]}\n')
                written.add(k)
            else:
                out.append(line)

    for k, v in env.items():
        if k not in written and k not in _SENSITIVE_KEYS:
            out.append(f'{k}={v}\n')

    with open(ENV_FILE, "w") as f:
        f.writelines(out)


def env_flag_true(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def prompt(question: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        answer = input(f"  {question}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return answer or default


def confirm(question: str) -> bool:
    try:
        answer = input(f"  {question} [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return answer in ("y", "yes")


# ── Phase 1: venv + pip ───────────────────────────────────────────────────────

def phase_venv():
    section("1. Python environment")

    python = sys.executable
    pip_path = os.path.join(VENV_DIR, "bin", "pip")
    venv_exists = os.path.isdir(VENV_DIR)

    if not venv_exists:
        warn("No venv/ directory found.")
        if not CHECK_ONLY and confirm("Create a virtual environment now?"):
            subprocess.check_call([python, "-m", "venv", VENV_DIR])
            ok("venv created.")
            venv_exists = True
        else:
            info("Skipping venv creation.")
    else:
        ok(f"venv exists at {VENV_DIR}")

    if not venv_exists:
        return

    if not os.path.isfile(REQUIREMENTS):
        warn("requirements.txt not found — skipping pip install.")
        return

    if CHECK_ONLY:
        info("Skipping pip update (--check mode).")
        return

    if confirm("Run pip install -r requirements.txt (install/upgrade all deps)?"):
        result = subprocess.run(
            [pip_path, "install", "-r", REQUIREMENTS],
            capture_output=False,
        )
        if result.returncode == 0:
            ok("Dependencies installed/updated.")
        else:
            err("pip install failed. Check the output above.")


# ── Phase 2: .env health ──────────────────────────────────────────────────────

def phase_env_health(env: dict) -> list:
    """
    Check required and optional env keys. Returns list of (key, status) tuples
    for the summary. Status: 'ok', 'warn', 'err'.
    """
    section("2. Environment health")
    results = []

    required = [
        ("bot_token",  "Discord bot token"),
        ("my_guild",   "Guild (server) ID"),
    ]
    for key, label in required:
        if env.get(key, "").strip():
            ok(f"{key} is set ({label})")
            results.append((key, "ok"))
        else:
            err(f"{key} is NOT set — {label} is required")
            results.append((key, "err"))

    optional_core = [
        ("admin_user_id", "Admin user ID"),
        ("quotes_id",     "Quotes channel ID"),
    ]
    for key, label in optional_core:
        if env.get(key, "").strip():
            ok(f"{key} is set ({label})")
            results.append((key, "ok"))
        else:
            info(f"{key} not set ({label} — optional)")
            results.append((key, "ok"))

    webui_enabled = env_flag_true(env.get("WEBUI_ENABLED", ""))
    tv_enabled    = env_flag_true(env.get("TV_ENABLED", ""))
    spotify_enabled = env_flag_true(env.get("SPOTIFY_ENABLED", ""))

    if webui_enabled:
        for key, label in [
            ("WEBUI_SECRET_KEY", "WebUI admin secret key"),
            ("WEBUI_PUBLIC_URL", "WebUI public URL (needed for /webui command)"),
        ]:
            if env.get(key, "").strip():
                ok(f"{key} is set ({label})")
                results.append((key, "ok"))
            else:
                warn(f"{key} is not set — {label}")
                results.append((key, "warn"))

    if tv_enabled:
        tv_url = env.get("TV_STREAM_URL", "").strip()
        tv_secret = env.get("TV_WEBHOOK_SECRET", "").strip()
        if tv_url:
            ok(f"TV_STREAM_URL is set")
            results.append(("TV_STREAM_URL", "ok"))
        else:
            info("TV_STREAM_URL not set (can pass url to /tv start instead)")
            results.append(("TV_STREAM_URL", "ok"))
        if tv_secret:
            ok("TV_WEBHOOK_SECRET is set (webhook server will start)")
            results.append(("TV_WEBHOOK_SECRET", "ok"))

    if spotify_enabled:
        for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
            if env.get(key, "").strip():
                ok(f"{key} is set")
                results.append((key, "ok"))
            else:
                err(f"{key} is NOT set — required when SPOTIFY_ENABLED=true")
                results.append((key, "err"))

    return results


# ── Phase 3: WebUI config ─────────────────────────────────────────────────────

def phase_webui(env: dict) -> dict:
    if not env_flag_true(env.get("WEBUI_ENABLED", "")):
        return env

    section("3. Web UI configuration")

    host = env.get("WEBUI_BIND_HOST", "127.0.0.1")
    port = env.get("WEBUI_PORT", "8765")
    public_url = env.get("WEBUI_PUBLIC_URL", "")

    info(f"Current bind: {host}:{port}")
    info(f"Current WEBUI_PUBLIC_URL: {public_url or '(not set)'}")

    if CHECK_ONLY:
        return env

    if confirm("Update WEBUI_BIND_HOST?"):
        new_host = prompt("New bind host (127.0.0.1 = local only, 0.0.0.0 = all interfaces)", host)
        env["WEBUI_BIND_HOST"] = new_host

    if confirm("Update WEBUI_PUBLIC_URL?"):
        new_url = prompt("New public URL (e.g. https://music.yoursite.com)", public_url)
        env["WEBUI_PUBLIC_URL"] = new_url.rstrip("/")

    return env


# ── Phase 4: TV config ────────────────────────────────────────────────────────

def phase_tv(env: dict) -> dict:
    if not env_flag_true(env.get("TV_ENABLED", "")):
        return env

    section("4. TV stream configuration")

    stream_url = env.get("TV_STREAM_URL", "")
    webhook_secret = env.get("TV_WEBHOOK_SECRET", "")

    info(f"Current TV_STREAM_URL: {stream_url[:60] + '…' if len(stream_url) > 60 else stream_url or '(not set)'}")
    info(f"Current TV_WEBHOOK_SECRET: {'(set)' if webhook_secret else '(not set)'}")

    if CHECK_ONLY:
        return env

    if confirm("Update TV_STREAM_URL?"):
        new_url = prompt("New stream URL", stream_url)
        env["TV_STREAM_URL"] = new_url

    if confirm("Update TV_WEBHOOK_SECRET?"):
        warn("TV_WEBHOOK_SECRET is a sensitive key and is not written by this tool.")
        info("Edit .env directly, or re-run setup_assistant.py to set it securely.")

    return env


# ── Phase 5: Summary ──────────────────────────────────────────────────────────

def phase_summary(health_results: list):
    section("Health summary")

    errors = [k for k, s in health_results if s == "err"]
    warnings = [k for k, s in health_results if s == "warn"]

    if not errors and not warnings:
        ok("All checks passed.")
    else:
        if errors:
            err(f"Missing required keys: {', '.join(errors)}")
        if warnings:
            warn(f"Optional keys not set: {', '.join(warnings)}")

    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print(f"\n{BOLD}Discord Music Bot — Updater{RESET}")
    if CHECK_ONLY:
        print(f"{DIM}Running in read-only health-check mode (--check){RESET}")

    env = read_env()
    if not env:
        warn(".env file not found or empty. Some checks will fail.")

    phase_venv()

    health = phase_env_health(env)

    env = phase_webui(env)
    env = phase_tv(env)

    if not CHECK_ONLY:
        changed = {k: v for k, v in env.items() if read_env().get(k) != v}
        if changed:
            print()
            info(f"Changes to write: {', '.join(changed.keys())}")
            if confirm("Write changes to .env?"):
                write_env(env)
                ok(".env updated.")
            else:
                info("No changes written.")

    phase_summary(health)


if __name__ == "__main__":
    main()
