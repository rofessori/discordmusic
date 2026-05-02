#!/usr/bin/env python3
"""
Professional setup assistant for the Discord music bot.

- Explains how to locate the Discord snowflakes the bot requires.
- Validates user input, masking secrets and preserving previous answers.
- Writes a well-formatted .env (with backup) even if .env.example is missing.
"""
from __future__ import annotations

import getpass
import shutil
import sys
import textwrap
from pathlib import Path
import re

ROOT = Path(__file__).parent
ENV_PATH = ROOT / ".env"
ENV_TEMPLATE_PATH = ROOT / ".env.example"
ENV_BACKUP_PATH = ROOT / ".env.backup"

DEV_PORTAL_URL = "https://discord.com/developers/applications"
DEVMODE_GUIDE_URL = "https://support.discord.com/hc/en-us/articles/206346498"

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{27,}$")
SNOWFLAKE_PATTERN = re.compile(r"^\d{17,20}$")

FIELD_ORDER = [
    ("bot_token", True),
    ("my_guild", False),
    ("quotes_id", False),
    ("admin_role_name", False),
    ("admin_user_id", False),
    ("admin_username", False),
]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def prompt_input(prompt: str, default: str | None = None, secret: bool = False) -> str:
    suffix = f" [{default}]" if default and not secret else (" [unchanged]" if default and secret else "")
    while True:
        try:
            if secret:
                response = getpass.getpass(f"{prompt}{suffix}: ") or ""
            else:
                response = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            print("\nInput stream closed. Aborting setup.")
            sys.exit(1)
        if response:
            return response
        if default:
            return default
        return response


def validate_token(token: str) -> bool:
    return bool(TOKEN_PATTERN.match(token))


def validate_snowflake(value: str) -> bool:
    return bool(SNOWFLAKE_PATTERN.match(value))


def collect_values(defaults: dict[str, str]) -> dict[str, str]:
    print(
        textwrap.dedent(
            f"""
            Welcome to the Discord Music Bot Setup Assistant.

            1. Create or reuse your bot application inside the Developer Portal:
               {DEV_PORTAL_URL}
            2. Enable Discord Developer Mode (guide: {DEVMODE_GUIDE_URL}).
               Right-click your server → Copy Server ID (this is your guild ID).
               Right-click the quotes channel → Copy Channel ID.
            """
        ).strip()
    )
    if ENV_PATH.exists():
        print(f"\nDetected existing {ENV_PATH}. Press Enter to keep current values.\n")

    values: dict[str, str] = {}

    # Bot token (masked + validated)
    while True:
        token_default = defaults.get("bot_token") or defaults.get("BOT_TOKEN")
        token = prompt_input("Discord bot token", default=token_default, secret=True)
        if token and validate_token(token):
            values["bot_token"] = token
            break
        print("  Token format looks off. Copy it again from the Developer Portal (it contains two dots).")

    # Guild ID
    while True:
        guild_default = defaults.get("my_guild") or defaults.get("MY_GUILD")
        guild = prompt_input("Server (guild) ID", default=guild_default)
        if validate_snowflake(guild):
            values["my_guild"] = guild
            break
        print("  Guild ID must be a numeric Discord snowflake (17-20 digits).")

    # Quotes channel ID
    while True:
        quotes_default = defaults.get("quotes_id") or defaults.get("QUOTES_ID")
        quotes_id = prompt_input("Quotes channel ID", default=quotes_default)
        if validate_snowflake(quotes_id):
            values["quotes_id"] = quotes_id
            break
        print("  Channel ID must be a numeric Discord snowflake (17-20 digits).")

    # Optional admin role
    admin_role_default = defaults.get("admin_role_name") or defaults.get("ADMIN_ROLE_NAME") or "bottiadmin"
    values["admin_role_name"] = prompt_input("Admin role name (optional)", default=admin_role_default) or admin_role_default

    # Optional admin ID
    admin_id_default = defaults.get("admin_user_id") or defaults.get("ADMIN_USER_ID") or ""
    while True:
        admin_id = prompt_input("Specific admin user ID (optional)", default=admin_id_default)
        if not admin_id or validate_snowflake(admin_id):
            values["admin_user_id"] = admin_id
            break
        print("  If provided, the admin user ID must be numeric.")

    # Optional admin username
    admin_user_default = defaults.get("admin_username") or defaults.get("ADMIN_USERNAME") or ""
    values["admin_username"] = prompt_input("Specific admin username (optional)", default=admin_user_default)

    return values


def summarize(values: dict[str, str]) -> None:
    print("\nConfiguration summary:")
    for key, is_secret in FIELD_ORDER:
        value = values.get(key, "")
        display = "***masked***" if (is_secret and value) else (value or "(empty)")
        print(f"  {key}: {display}")


def render_env(template_lines: list[str], values: dict[str, str]) -> str:
    rendered: list[str] = []
    used = set()
    for line in template_lines:
        stripped = line.strip()
        if "=" in line and not stripped.startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in values:
                rendered.append(f"{key}={values[key]}")
                used.add(key)
                continue
        rendered.append(line)
    for key, _ in FIELD_ORDER:
        if key in values and key not in used:
            rendered.append(f"{key}={values[key]}")
    return "\n".join(rendered) + "\n"


def write_env(values: dict[str, str]) -> None:
    if ENV_PATH.exists():
        shutil.copy2(ENV_PATH, ENV_BACKUP_PATH)
        print(f"Existing environment backed up to {ENV_BACKUP_PATH}")

    template_lines = ENV_TEMPLATE_PATH.read_text().splitlines() if ENV_TEMPLATE_PATH.exists() else []
    body = render_env(template_lines, values) if template_lines else "\n".join(f"{k}={v}" for k, v in values.items()) + "\n"
    ENV_PATH.write_text(body)
    print(f"\nAll set! Updated {ENV_PATH.resolve()}")


def main() -> None:
    defaults = read_env(ENV_PATH)
    if not defaults:
        defaults = read_env(ENV_TEMPLATE_PATH)

    values = collect_values(defaults)
    summarize(values)

    while True:
        confirm = input("\nWrite these values to .env? [Y/n]: ").strip().lower()
        if confirm in ("", "y", "yes"):
            write_env(values)
            break
        if confirm in ("n", "no"):
            print("No changes were written. Re-run the assistant when you're ready.")
            break
        print("  Please answer 'y' or 'n'.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSetup cancelled by user.")
        sys.exit(1)
