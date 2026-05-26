#!/usr/bin/env python3
"""
Discord music bot assistant.

Handles first-time setup, module configuration, dependency updates,
and health checks. Stdlib-only — works before the virtualenv exists.

Usage:
    python3 setup_assistant.py            # main menu
    python3 setup_assistant.py --setup    # jump straight to discord setup
    python3 setup_assistant.py --self-test
"""
from __future__ import annotations

import getpass
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import textwrap
import webbrowser
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
ENV_TEMPLATE_PATH = ROOT / ".env.example"
ENV_BACKUP_PATH = ROOT / ".env.backup"
STATE_PATH = ROOT / "setup.tmp"

DEV_PORTAL_URL = "https://discord.com/developers/applications"
DEVMODE_GUIDE_URL = "https://support.discord.com/hc/en-us/articles/206346498"
CLOUDFLARE_DL_URL = "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
SPOTIFY_DASHBOARD_URL = "https://developer.spotify.com/dashboard"

STATE_VERSION = 1
DEFAULT_ADMIN_ROLE_NAME = "Bottiadmin"
SERVICE_NAME = "discordmusicbot.service"

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{27,}$")
SNOWFLAKE_PATTERN = re.compile(r"^\d{17,20}$")
F1_VALUES = {"f1", ":save", "\\f1", "\x1bOP", "\x1b[11~"}
F2_VALUES = {"f2", ":quit", ":nosave", "\\f2", "\x1bOQ", "\x1b[12~"}

# Core Discord config fields written by first-time setup
ENV_FIELDS = [
    "BOT_TOKEN",
    "MY_GUILD",
    "QUOTES_ID",
    "ADMIN_USER_ID",
    "ADMIN_ROLE_NAME",
    "ALLOW_ADMIN_ROLE_NAME",
    "ADMIN_ROLE_ID",
    "ADMIN_USERNAME",
]
SECRET_FIELDS = {"BOT_TOKEN", "WEBUI_SECRET_KEY", "TV_WEBHOOK_SECRET", "SPOTIFY_CLIENT_SECRET"}


# ── Exceptions ─────────────────────────────────────────────────────────────────

class SetupExit(Exception):
    def __init__(self, save: bool):
        self.save = save
        super().__init__("setup exit")


# ── Terminal helpers ───────────────────────────────────────────────────────────

def supports_color() -> bool:
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def c(text: str, code: str) -> str:
    if not supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


# Colour shortcuts
def bold(t):    return c(t, "1")
def dim(t):     return c(t, "2")
def green(t):   return c(t, "32")
def red(t):     return c(t, "31")
def yellow(t):  return c(t, "33")
def cyan(t):    return c(t, "36")
def blue(t):    return c(t, "34")
def magenta(t): return c(t, "35")


def clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def draw_box(rows: list[str], *, width: int = 62, title: str = "") -> None:
    """Draw a Unicode box around a list of pre-formatted strings."""
    inner = width - 2
    if title:
        t = f" {title} "
        pad_l = (inner - len(t)) // 2
        pad_r = inner - len(t) - pad_l
        top = f"┌{'─' * pad_l}{t}{'─' * pad_r}┐"
    else:
        top = f"┌{'─' * inner}┐"
    print(top)
    for row in rows:
        # strip ANSI for width calculation
        raw = re.sub(r"\033\[[0-9;]*m", "", row)
        pad = max(0, inner - 2 - len(raw))
        print(f"│ {row}{' ' * pad} │")
    print(f"└{'─' * inner}┘")


def draw_rule(width: int = 62, ch: str = "─") -> None:
    print(dim(ch * width))


def command_text(command: list[str]) -> str:
    return " ".join(command)


# ── .env helpers ───────────────────────────────────────────────────────────────

def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_default(defaults: dict[str, str], key: str, fallback: str = "") -> str:
    return defaults.get(key) or defaults.get(key.lower()) or fallback


def update_env_keys(updates: dict[str, str]) -> None:
    """
    Write specific keys into .env, preserving all other lines and comments.
    Creates .env if it does not exist. Always backs up first.
    """
    current_lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    if ENV_PATH.exists():
        shutil.copy2(ENV_PATH, ENV_BACKUP_PATH)
        try:
            os.chmod(ENV_BACKUP_PATH, 0o600)
        except OSError:
            pass

    written: set[str] = set()
    new_lines: list[str] = []
    for line in current_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in written:
            new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n")
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass


def validate_token(value: str) -> bool:
    return bool(TOKEN_PATTERN.match(value.strip()))


def validate_snowflake(value: str) -> bool:
    return bool(SNOWFLAKE_PATTERN.match(value.strip()))


def validate_quotes_id(value: str) -> bool:
    return value.strip() == "0" or validate_snowflake(value)


def normalize_optional_snowflake(value: str) -> str:
    value = value.strip()
    if value.lower() in {"skip", "none", "no", "-"}:
        return ""
    return value


def mask_value(key: str, value: str) -> str:
    if not value:
        return dim("(not set)")
    if key in SECRET_FIELDS:
        return dim("***set***")
    return value


def status_indicator(value: str, *, required: bool = False) -> str:
    if value:
        return green("✓")
    if required:
        return red("✗")
    return yellow("–")


# ── State ──────────────────────────────────────────────────────────────────────

def load_state(path: Path = STATE_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if data.get("version") != STATE_VERSION:
        return None
    data.setdefault("mode", "")
    data.setdefault("values", {})
    data.setdefault("setup", {})
    return data


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    state = dict(state)
    state["version"] = STATE_VERSION
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".setup-", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(state, handle, indent=2)
            handle.write("\n")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def remove_state(path: Path = STATE_PATH) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


# ── env rendering (first-time setup output) ────────────────────────────────────

def render_env(values: dict[str, str]) -> str:
    lines = [
        "# Discord music bot environment",
        "# Keep this file private. It contains your Discord bot token.",
    ]
    for key in ENV_FIELDS:
        if key == "ADMIN_USERNAME":
            continue
        lines.append(f"{key}={values.get(key, '')}")
    return "\n".join(lines) + "\n"


def render_env_example() -> str:
    return textwrap.dedent(
        f"""
        # Discord music bot environment example
        # Copy to .env and replace the placeholder values.
        # Never commit your real bot token.
        BOT_TOKEN=replace_with_your_discord_bot_token
        MY_GUILD=000000000000000000
        # Set QUOTES_ID=0 to skip the optional quotes feature.
        QUOTES_ID=0
        # ADMIN_USER_ID gives one Discord user admin access.
        ADMIN_USER_ID=
        # Production admin access should use ADMIN_USER_ID or ADMIN_ROLE_ID.
        # Role-name admin is for development/compatibility only.
        ADMIN_ROLE_NAME={DEFAULT_ADMIN_ROLE_NAME}
        ALLOW_ADMIN_ROLE_NAME=false
        # Optional stable role-id alternative/add-on. Leave blank unless you copied the role id.
        ADMIN_ROLE_ID=
        """
    ).strip() + "\n"


def write_env(values: dict[str, str]) -> None:
    if ENV_PATH.exists():
        shutil.copy2(ENV_PATH, ENV_BACKUP_PATH)
        try:
            os.chmod(ENV_BACKUP_PATH, 0o600)
        except OSError:
            pass
    ENV_PATH.write_text(render_env(values))
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass


def write_env_example_if_needed(force: bool = False) -> bool:
    if ENV_TEMPLATE_PATH.exists() and not force:
        return False
    ENV_TEMPLATE_PATH.write_text(render_env_example())
    return True


# ── System detection helpers ───────────────────────────────────────────────────

def detect_package_manager() -> tuple[str, list[str]] | None:
    system = platform.system().lower()
    if system == "darwin":
        if shutil.which("brew"):
            return "macOS/Homebrew", ["brew", "install", "screen"]
        return None
    if system != "linux":
        return None
    os_release = ""
    release_path = Path("/etc/os-release")
    if release_path.exists():
        os_release = release_path.read_text(errors="ignore").lower()
    if shutil.which("apt") and any(n in os_release for n in ["debian", "ubuntu", "linuxmint", "pop"]):
        return "Debian/Ubuntu", ["sudo", "apt", "install", "-y", "screen"]
    if shutil.which("dnf") and any(n in os_release for n in ["fedora", "rhel", "centos", "rocky", "alma"]):
        return "Fedora/RHEL", ["sudo", "dnf", "install", "-y", "screen"]
    if shutil.which("pacman") and "arch" in os_release:
        return "Arch", ["sudo", "pacman", "-S", "--needed", "screen"]
    if shutil.which("apt"):
        return "apt", ["sudo", "apt", "install", "-y", "screen"]
    if shutil.which("dnf"):
        return "dnf", ["sudo", "dnf", "install", "-y", "screen"]
    if shutil.which("pacman"):
        return "pacman", ["sudo", "pacman", "-S", "--needed", "screen"]
    return None


def build_venv_commands() -> list[list[str]]:
    python = shutil.which("python3") or sys.executable
    return [
        [python, "-m", "venv", "venv"],
        [str(ROOT / "venv" / "bin" / "python"), "-m", "pip", "install", "-r", "requirements.txt"],
    ]


def build_screen_start_command() -> list[str]:
    python = str(ROOT / "venv" / "bin" / "python")
    return ["screen", "-S", "bot", "-dm", python, "main.py"]


def render_systemd_service(service_user: str, workdir: Path) -> str:
    python = workdir / "venv" / "bin" / "python"
    return textwrap.dedent(
        f"""
        [Unit]
        Description=discord musicbot startup script
        After=network.target

        [Service]
        Type=simple
        User={service_user}
        WorkingDirectory={workdir}
        Environment=PATH={Path.home()}/.deno/bin:/usr/local/bin:/usr/bin:/bin
        ExecStart={python} {workdir / "main.py"}
        Restart=on-failure
        RestartSec=5

        NoNewPrivileges=true
        PrivateTmp=true
        ProtectSystem=full
        ProtectHome=true
        ReadWritePaths={workdir}
        CapabilityBoundingSet=
        LockPersonality=true
        RestrictSUIDSGID=true

        StandardOutput=append:{workdir / "output.log"}
        StandardError=append:{workdir / "output.log"}

        [Install]
        WantedBy=multi-user.target
        """
    ).strip() + "\n"


def write_private_temp_service(content: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w", prefix="discordmusicbot-", suffix=".service", delete=False,
    )
    temp_path = Path(handle.name)
    try:
        handle.write(content)
        handle.close()
        os.chmod(temp_path, 0o600)
        return temp_path
    except Exception:
        handle.close()
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def build_systemd_install_commands(local_service: Path) -> list[list[str]]:
    destination = f"/etc/systemd/system/{SERVICE_NAME}"
    return [
        ["sudo", "cp", str(local_service), destination],
        ["sudo", "systemctl", "daemon-reload"],
        ["sudo", "systemctl", "enable", "--now", SERVICE_NAME],
    ]


# ── Main assistant class ───────────────────────────────────────────────────────

class SetupAssistant:
    def __init__(self) -> None:
        self.defaults = read_env(ENV_PATH) or read_env(ENV_TEMPLATE_PATH)
        self.state = load_state() or {"version": STATE_VERSION, "mode": "", "values": {}, "setup": {}}

    # ── state ──────────────────────────────────────────────────────────────────

    @property
    def values(self) -> dict[str, str]:
        return self.state.setdefault("values", {})

    def save(self) -> None:
        save_state(self.state)

    def set_value(self, key: str, value: str) -> None:
        self.values[key] = value
        self.save()

    # ── UI primitives ──────────────────────────────────────────────────────────

    def header(self, heading: str, sub: str = "") -> None:
        clear_screen()
        print()
        print(f"  {bold(cyan('discord music bot'))}  {dim('·')}  {bold('assistant')}")
        print(f"  {dim('─' * 56)}")
        print(f"  {bold(heading)}")
        if sub:
            print(f"  {dim(sub)}")
        print(f"  {dim('F1 / :save  ·  save & exit     F2 / :quit  ·  exit')}")
        print()

    def title(self, heading: str, detail: str = "") -> None:
        """Alias kept for backward compatibility with existing methods."""
        self.header(heading, detail)

    def handle_control(self, response: str) -> None:
        normalized = response.strip().lower()
        if normalized in F1_VALUES:
            self.save()
            raise SetupExit(save=True)
        if normalized in F2_VALUES:
            remove_state()
            raise SetupExit(save=False)

    def raw_input(self, prompt: str, *, secret: bool = False) -> str:
        try:
            if secret:
                return getpass.getpass(prompt)
            return input(prompt)
        except EOFError:
            self.save()
            raise SetupExit(save=True)

    def ask_text(
        self,
        key: str,
        prompt: str,
        *,
        default: str = "",
        secret: bool = False,
        allow_blank: bool = False,
        validator: Callable[[str], bool] | None = None,
        error: str = "Invalid value.",
        transform: Callable[[str], str] | None = None,
    ) -> str:
        existing = self.values.get(key) or env_default(self.defaults, key, default)
        suffix = ""
        if existing:
            suffix = " [unchanged]" if secret else f" [{existing}]"
        while True:
            response = self.raw_input(f"  {prompt}{suffix}: ", secret=secret).strip()
            self.handle_control(response)
            value = existing if not response and existing else response
            if transform:
                value = transform(value)
            if not value and allow_blank:
                self.set_value(key, "")
                return ""
            if value and (validator is None or validator(value)):
                self.set_value(key, value)
                return value
            print(f"  {red('✗')}  {error}")

    def ask_yes_no(self, prompt: str, *, default: bool = True) -> bool:
        suffix = "[Y/n]" if default else "[y/N]"
        while True:
            response = self.raw_input(f"  {prompt} {suffix}: ").strip()
            self.handle_control(response)
            if not response:
                return default
            if response.lower() in {"y", "yes"}:
                return True
            if response.lower() in {"n", "no"}:
                return False
            print(f"  {yellow('?')}  Please answer y or n.")

    def ask_choice(self, prompt: str, choices: list[str]) -> str:
        """Ask for a choice from a numbered list. Returns the chosen string."""
        while True:
            response = self.raw_input(f"  {prompt}: ").strip()
            self.handle_control(response)
            if response in choices:
                return response
            try:
                idx = int(response) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]
            except ValueError:
                pass
            print(f"  {yellow('?')}  Enter a number from the menu.")

    def wait_continue(self, prompt: str = "Press Enter to continue.") -> None:
        response = self.raw_input(f"  {prompt} ").strip()
        self.handle_control(response)

    def open_link(self, url: str) -> None:
        print(f"  {cyan(url)}")
        response = self.raw_input("  Press Enter to open in browser, or type anything to skip: ")
        self.handle_control(response)
        if response == "":
            opened = webbrowser.open(url)
            print(f"  {green('Opened in browser.') if opened else yellow('Could not open browser — copy the link above.')}")
            self.wait_continue()

    def run_command(self, command: list[str], *, cwd: Path = ROOT) -> bool:
        print(f"  {blue('$')} {command_text(command)}")
        try:
            subprocess.run(command, cwd=str(cwd), check=True)
            return True
        except FileNotFoundError:
            print(f"  {red('✗')}  Command not found: {command[0]}")
            return False
        except subprocess.CalledProcessError as exc:
            print(f"  {red('✗')}  Command failed with exit code {exc.returncode}.")
            return False

    def note(self, text: str) -> None:
        for line in textwrap.wrap(text, 74):
            print(f"  {dim(line)}")

    def info(self, text: str) -> None:
        print(f"  {cyan('·')}  {text}")

    def ok(self, text: str) -> None:
        print(f"  {green('✓')}  {text}")

    def warn(self, text: str) -> None:
        print(f"  {yellow('⚠')}  {text}")

    def err(self, text: str) -> None:
        print(f"  {red('✗')}  {text}")

    # ── Main menu ──────────────────────────────────────────────────────────────

    def main_menu(self) -> str:
        env = read_env(ENV_PATH)
        has_token = bool(env.get("BOT_TOKEN") or env.get("bot_token"))

        clear_screen()
        print()
        title_line = f"  {bold(cyan('discord music bot'))}  {dim('·')}  {bold('assistant')}"
        print(title_line)
        print(f"  {dim('─' * 56)}")
        print()

        rows = [
            dim("setup & configure"),
            f"  {bold('1')}  discord setup        {dim('token · guild · admin ids')}",
            f"  {bold('2')}  web ui               {dim('per-user sessions · cloudflare')}",
            f"  {bold('3')}  tv / live stream     {dim('hls · rtmp · youtube live')}",
            f"  {bold('4')}  spotify import       {dim('playlist sync')}",
            "",
            dim("tools"),
            f"  {bold('5')}  update dependencies  {dim('pip install -r requirements.txt')}",
            f"  {bold('6')}  health check         {dim('show status of all config')}",
            "",
            f"  {bold('0')}  exit",
        ]
        draw_box(rows, width=62)
        print()

        if not has_token:
            print(f"  {yellow('→')}  No .env found — start with option 1 to set up the bot.")
            print()

        return self.ask_choice("Choose", ["0", "1", "2", "3", "4", "5", "6"])

    def run(self) -> None:
        """Main entry point — shows the menu and routes to sections."""
        # Resume saved first-time setup if interrupted
        existing = load_state()
        if existing and existing.get("values"):
            self.header("resume setup", f"Found saved progress in {STATE_PATH}.")
            self.note("This file may contain your bot token and is stored with private permissions.")
            if self.ask_yes_no("Resume first-time setup from where you left off?", default=True):
                self.run_initial_setup(resume=True)
                return
            else:
                remove_state()
                self.state = {"version": STATE_VERSION, "mode": "", "values": {}, "setup": {}}

        while True:
            choice = self.main_menu()
            if choice == "0":
                return
            elif choice == "1":
                self.run_initial_setup()
            elif choice == "2":
                self.webui_section()
            elif choice == "3":
                self.tv_section()
            elif choice == "4":
                self.spotify_section()
            elif choice == "5":
                self.update_deps_section()
            elif choice == "6":
                self.health_section()

    # ── First-time Discord setup ───────────────────────────────────────────────

    def choose_mode(self) -> str:
        if self.state.get("mode"):
            return str(self.state["mode"])
        self.header("choose setup mode")
        print(f"  {bold('Guided')} — explains each Discord step in detail.")
        print(f"  {bold('Quick')}  — for users who already know where to find IDs.")
        print()
        quick = self.ask_yes_no("Use quick setup?", default=False)
        mode = "quick" if quick else "guided"
        self.state["mode"] = mode
        self.save()
        return mode

    def collect_admin_role(self) -> None:
        self.note(
            "Admin access should come from your user ID or a stable admin role ID. "
            "Role-name admin is an explicit development/compatibility fallback."
        )
        print()
        role_name = self.ask_text(
            "ADMIN_ROLE_NAME",
            "Admin role name",
            default=DEFAULT_ADMIN_ROLE_NAME,
            allow_blank=True,
            transform=lambda v: "" if v.lower() in {"skip", "none", "no", "-"} else v,
        )
        if not role_name:
            self.set_value("ADMIN_ROLE_NAME", DEFAULT_ADMIN_ROLE_NAME)

        if role_name and self.ask_yes_no(
            "Enable role-name admin fallback? (development/compatibility only)",
            default=False,
        ):
            self.set_value("ALLOW_ADMIN_ROLE_NAME", "true")
        else:
            self.set_value("ALLOW_ADMIN_ROLE_NAME", "false")

        existing_role_id = self.values.get("ADMIN_ROLE_ID") or env_default(self.defaults, "ADMIN_ROLE_ID", "")
        if self.ask_yes_no("Add or keep an admin role ID too?", default=bool(existing_role_id)):
            self.ask_text(
                "ADMIN_ROLE_ID",
                "Admin role ID (type skip to leave blank)",
                allow_blank=True,
                validator=validate_snowflake,
                error="Role ID must be a 17-20 digit Discord ID, or blank.",
                transform=normalize_optional_snowflake,
            )
        else:
            self.set_value("ADMIN_ROLE_ID", "")

    def guided_discord_steps(self) -> None:
        # Step 1
        self.header("step 1 — discord developer portal")
        self.note("Create a new Discord application, or open the one you want this bot to use.")
        print()
        self.open_link(DEV_PORTAL_URL)

        # Step 2
        self.header("step 2 — create bot and copy token")
        self.note(
            "In the Developer Portal, open your app. Go to Bot in the left sidebar. "
            "Under the bot username click Reset Token, copy it, and paste it here. "
            "The token is secret — this assistant writes it only to .env, never to .env.example."
        )
        print()
        self.ask_text(
            "BOT_TOKEN",
            "Paste Discord bot token",
            secret=True,
            validator=validate_token,
            error="Token format looks wrong — Discord bot tokens have two dots.",
        )

        # Step 3
        self.header("step 3 — your admin user ID")
        self.note(
            "In Discord, enable Developer Mode (Settings → Advanced → Developer Mode). "
            "Then right-click your username in a message or voice channel and choose Copy User ID."
        )
        print()
        self.info(f"Developer Mode guide: {DEVMODE_GUIDE_URL}")
        print()
        self.ask_text(
            "ADMIN_USER_ID",
            "Paste your Discord user ID",
            validator=validate_snowflake,
            error="User ID must be a 17-20 digit number.",
        )

        # Step 4
        self.header("step 4 — admin role")
        self.note(
            "Create a server role for bot admins (e.g. Bottiadmin). "
            "You can also add the role's ID for stable access. "
            "Server Settings → Roles → right-click the role → Copy Role ID."
        )
        print()
        self.collect_admin_role()

        # Step 5
        self.header("step 5 — optional username label")
        self.note(
            "This is just a local note for the setup recap. "
            "The bot does not use usernames for admin checks because usernames can change."
        )
        print()
        self.ask_text(
            "ADMIN_USERNAME",
            "Username note (optional — type skip to skip)",
            allow_blank=True,
            transform=lambda v: "" if v.lower() == "skip" else v,
        )

        # Step 6
        self.header("step 6 — optional quotes channel")
        self.note(
            "The quotes channel backs up messages from a designated channel. "
            "Right-click the channel and choose Copy Channel ID. "
            "Type skip if you do not want this feature."
        )
        print()
        quotes = self.ask_text(
            "QUOTES_ID",
            "Quotes channel ID (type skip to disable)",
            default=env_default(self.defaults, "QUOTES_ID", ""),
            allow_blank=True,
            validator=validate_quotes_id,
            error="Channel ID must be a 17-20 digit number, 0, or blank.",
            transform=normalize_optional_snowflake,
        )
        if not quotes:
            self.set_value("QUOTES_ID", "0")

        # Step 7
        self.header("step 7 — server ID")
        self.note(
            "Right-click your server icon in Discord's sidebar and choose Copy Server ID. "
            "The bot only works in this one server."
        )
        print()
        self.ask_text(
            "MY_GUILD",
            "Paste server ID",
            validator=validate_snowflake,
            error="Server ID must be a 17-20 digit number.",
        )

        self.invite_walkthrough()

    def quick_steps(self) -> None:
        self.header("quick setup", "Discord Developer Portal → App → Bot → Token")
        self.open_link(DEV_PORTAL_URL)
        self.ask_text(
            "BOT_TOKEN", "Bot token",
            secret=True, validator=validate_token,
            error="Token format looks wrong.",
        )
        self.ask_text(
            "ADMIN_USER_ID", "Your Discord user ID",
            validator=validate_snowflake,
            error="User ID must be a 17-20 digit number.",
        )
        quotes = self.ask_text(
            "QUOTES_ID", "Quotes channel ID (type skip to disable)",
            allow_blank=True, validator=validate_quotes_id,
            error="Channel ID must be a 17-20 digit number, 0, or blank.",
            transform=normalize_optional_snowflake,
        )
        if not quotes:
            self.set_value("QUOTES_ID", "0")
        self.ask_text(
            "MY_GUILD", "Server ID",
            validator=validate_snowflake,
            error="Server ID must be a 17-20 digit number.",
        )
        self.collect_admin_role()
        self.set_value("ADMIN_USERNAME", self.values.get("ADMIN_USERNAME", ""))

    def invite_walkthrough(self) -> None:
        self.header("invite the bot to your server")
        self.note(
            "In the Developer Portal, go to your app → OAuth2 → URL Generator. "
            "Select scope: bot. "
            "Minimum permissions: View Channels, Send Messages, Embed Links, "
            "Attach Files, Read Message History, Use External Emojis, Add Reactions, "
            "Connect, Speak. Copy the generated URL and open it in your browser."
        )
        print()
        self.open_link(DEV_PORTAL_URL)

    def recap(self) -> bool:
        self.header("configuration recap")
        print(f"  {'Key':<28}  Value")
        draw_rule(62)
        for key in ENV_FIELDS:
            val = mask_value(key, self.values.get(key, ""))
            print(f"  {key:<28}  {val}")
        print()
        self.note("ADMIN_USER_ID and ADMIN_ROLE_ID are used for production admin access.")
        self.note("ADMIN_ROLE_NAME only works when ALLOW_ADMIN_ROLE_NAME=true.")
        print()
        return self.ask_yes_no("Write these values to .env now?", default=True)

    def write_files(self) -> None:
        write_env(self.values)
        created_example = False
        if not ENV_TEMPLATE_PATH.exists():
            created_example = write_env_example_if_needed()
        else:
            if self.ask_yes_no(
                "Refresh .env.example placeholders? Real secrets will not be written there.",
                default=False,
            ):
                created_example = write_env_example_if_needed(force=True)
        self.header("environment written")
        self.ok(f"Wrote {ENV_PATH}")
        if ENV_BACKUP_PATH.exists():
            self.info(f"Previous .env backed up to {ENV_BACKUP_PATH}")
        if created_example:
            self.ok(f"Wrote placeholder template: {ENV_TEMPLATE_PATH}")
        print()
        self.wait_continue()

    def dependency_setup(self) -> None:
        self.header("install python dependencies")
        self.note("This will create a virtualenv and install all required packages.")
        print()
        self.info("Commands that will run:")
        print(f"    python3 -m venv venv")
        print(f"    venv/bin/python -m pip install -r requirements.txt")
        print()
        if not self.ask_yes_no("Run these now?", default=True):
            return
        for command in build_venv_commands():
            if not self.run_command(command):
                print()
                self.warn("Stopped. Fix the error above and run the assistant again.")
                self.save()
                return

    def screen_setup(self) -> None:
        self.header("run bot in screen")
        self.note("screen keeps the bot running after you close the terminal.")
        print()
        package = detect_package_manager()
        if shutil.which("screen"):
            self.ok("screen is already installed.")
        elif package:
            label, command = package
            self.info(f"Detected {label}.")
            if self.ask_yes_no(f"Install screen with `{command_text(command)}`?", default=True):
                self.run_command(command)
        else:
            self.warn("Could not detect a package manager. Install screen manually if you want this mode.")

        if not shutil.which("screen"):
            self.wait_continue()
            return

        print()
        self.info(f"Start command: {command_text(build_screen_start_command())}")
        self.info("Reconnect:     screen -r -D bot")
        self.info("Detach:        Ctrl-a, then d")
        print()
        if self.ask_yes_no("Start the bot in a detached screen session now?", default=True):
            self.run_command(build_screen_start_command())
            self.ok("Bot started. Use `screen -r -D bot` to view output.")
            self.wait_continue()

    def systemd_setup(self) -> None:
        self.header("optional autostart (systemd)")
        if platform.system().lower() != "linux" or not shutil.which("systemctl"):
            self.info("systemd setup is only available on Linux with systemctl.")
            self.wait_continue()
            return
        if not self.ask_yes_no("Install a systemd service for autostart?", default=False):
            return
        service_user = self.ask_text(
            "SETUP_SERVICE_USER",
            "Linux user that should run the bot",
            default=getpass.getuser(),
            allow_blank=False,
        )
        workdir_text = self.ask_text(
            "SETUP_SERVICE_PATH",
            "Project path for the service",
            default=str(ROOT),
            allow_blank=False,
        )
        workdir = Path(workdir_text).expanduser().resolve()
        service_content = render_systemd_service(service_user, workdir)
        print()
        self.info(f"User: {service_user}")
        self.info(f"WorkingDirectory: {workdir}")
        print()
        if self.ask_yes_no("Install and start the systemd service now?", default=False):
            temp_service = write_private_temp_service(service_content)
            try:
                commands = build_systemd_install_commands(temp_service)
                for command in commands:
                    if not self.run_command(command):
                        self.warn("Systemd setup stopped.")
                        return
                self.ok("Systemd service installed and started.")
                self.wait_continue()
            finally:
                try:
                    temp_service.unlink()
                except OSError:
                    pass

    def finish(self) -> None:
        remove_state()
        self.header("setup complete")
        draw_box([
            f"  {green('✓')}  environment:     {str(ENV_PATH)}",
            f"  {green('✓')}  run manually:    source venv/bin/activate && python main.py",
            f"  {cyan('·')}  screen reconnect: screen -r -D bot",
            f"  {cyan('·')}  screen detach:    Ctrl-a, then d",
            "",
            dim("  If slash commands do not appear, wait a minute and restart the bot once."),
        ], width=62)
        print()
        self.note("You can run this assistant again any time to configure modules or check health.")
        print()

    def run_initial_setup(self, resume: bool = False) -> None:
        if not resume:
            mode = self.choose_mode()
        else:
            mode = self.state.get("mode") or "guided"
        if mode == "quick":
            self.quick_steps()
        else:
            self.guided_discord_steps()
        if self.recap():
            self.write_files()
        else:
            self.note("No .env changes were written.")
            self.save()
            return
        self.dependency_setup()
        self.screen_setup()
        self.systemd_setup()
        self.finish()

    # ── Web UI section ─────────────────────────────────────────────────────────

    def webui_section(self) -> None:
        env = read_env(ENV_PATH)
        updates: dict[str, str] = {}

        self.header(
            "web ui configuration",
            "Playlist editor · per-user sessions · Cloudflare Tunnel support",
        )

        # ── Enable/disable ──
        current_enabled = env.get("WEBUI_ENABLED", "").lower() in {"true", "1", "yes"}
        print(f"  Current status: {'enabled' if current_enabled else 'disabled'}")
        print()
        enable = self.ask_yes_no("Enable the web UI?", default=current_enabled)
        updates["WEBUI_ENABLED"] = "true" if enable else "false"

        if not enable:
            update_env_keys(updates)
            self.ok("WEBUI_ENABLED=false written to .env.")
            self.wait_continue()
            return

        # ── Secret key ──
        self.header("web ui — admin secret key")
        self.note(
            "WEBUI_SECRET_KEY is an admin bypass token. "
            "It lets you access the UI without a Discord session — useful for emergencies. "
            "Keep it strong and private. It is never sent to Discord."
        )
        print()
        existing_key = env.get("WEBUI_SECRET_KEY", "")
        if existing_key:
            self.ok("WEBUI_SECRET_KEY is already set.")
            if self.ask_yes_no("Regenerate it with a new random value?", default=False):
                existing_key = ""
        if not existing_key:
            generated = secrets.token_urlsafe(32)
            print()
            self.info("Generated a cryptographically random key:")
            print(f"    {bold(generated)}")
            print()
            if self.ask_yes_no("Use this key?", default=True):
                updates["WEBUI_SECRET_KEY"] = generated
            else:
                custom = self.ask_text(
                    "_webui_key_tmp",
                    "Paste your own secret key (at least 20 characters)",
                    allow_blank=False,
                    validator=lambda v: len(v) >= 20,
                    error="Key must be at least 20 characters.",
                )
                updates["WEBUI_SECRET_KEY"] = custom
        else:
            updates["WEBUI_SECRET_KEY"] = existing_key

        # ── Public URL + Cloudflare ──
        self.header("web ui — public URL")
        self.note(
            "WEBUI_PUBLIC_URL is the address users open in their browser. "
            "The /webui Discord command uses this to build the session link. "
            "Without it the command will not work."
        )
        print()
        current_url = env.get("WEBUI_PUBLIC_URL", "")
        print(f"  Current WEBUI_PUBLIC_URL: {current_url or dim('(not set)')}")
        print()

        print(f"  {bold('How to expose the web UI:')}")
        print()
        print(f"  {cyan('Option A — Cloudflare Tunnel')} (free, no account needed for a temporary URL)")
        print()
        print(f"    1. Download cloudflared:")
        print(f"       {dim(CLOUDFLARE_DL_URL)}")
        port = env.get("WEBUI_PORT", "8765")
        print(f"    2. Run: {bold(f'cloudflared tunnel --url http://127.0.0.1:{port}')}")
        print(f"    3. Copy the {cyan('https://xxxx.trycloudflare.com')} URL it shows.")
        print(f"    4. Paste it below as WEBUI_PUBLIC_URL.")
        print(f"    5. Restart the bot. Run the tunnel every time you need external access.")
        print()
        print(f"  {cyan('Option B — Homelab reverse proxy')}")
        print()
        print(f"    Set WEBUI_BIND_HOST=0.0.0.0 and point your nginx/Caddy/Traefik")
        print(f"    at this machine's internal IP on port {port}.")
        print(f"    Set WEBUI_PUBLIC_URL to the externally reachable URL.")
        print()

        new_url = self.ask_text(
            "_webui_url_tmp",
            "WEBUI_PUBLIC_URL (leave blank to keep current)",
            default=current_url,
            allow_blank=True,
        )
        updates["WEBUI_PUBLIC_URL"] = (new_url or current_url).rstrip("/")

        # ── Bind host / port ──
        self.header("web ui — bind address")
        self.note(
            "WEBUI_BIND_HOST controls which network interface the server listens on. "
            "Use 127.0.0.1 to keep it local (required for Cloudflare Tunnel). "
            "Use 0.0.0.0 if you are connecting to it directly from another machine."
        )
        print()
        current_host = env.get("WEBUI_BIND_HOST", "127.0.0.1")
        current_port = env.get("WEBUI_PORT", "8765")
        print(f"  Current: {current_host}:{current_port}")
        print()

        new_host = self.ask_text(
            "_webui_host_tmp",
            "WEBUI_BIND_HOST",
            default=current_host,
            allow_blank=False,
            validator=lambda v: bool(v.strip()),
            error="Cannot be blank.",
        )
        new_port = self.ask_text(
            "_webui_port_tmp",
            "WEBUI_PORT",
            default=current_port,
            allow_blank=False,
            validator=lambda v: v.isdigit() and 1024 <= int(v) <= 65535,
            error="Port must be a number between 1024 and 65535.",
        )
        updates["WEBUI_BIND_HOST"] = new_host
        updates["WEBUI_PORT"] = new_port

        # ── Write ──
        update_env_keys(updates)
        self.header("web ui — saved")
        for key, val in updates.items():
            display = mask_value(key, val)
            self.ok(f"{key} = {display}")
        print()
        self.note("Restart the bot for changes to take effect.")
        self.note("Users get their private link by running /webui in Discord.")
        self.wait_continue()

    # ── TV / live stream section ───────────────────────────────────────────────

    def tv_section(self) -> None:
        env = read_env(ENV_PATH)
        updates: dict[str, str] = {}

        self.header(
            "tv / live stream configuration",
            "HLS · RTMP · YouTube live · generic HTTP streams",
        )

        current_enabled = env.get("TV_ENABLED", "").lower() in {"true", "1", "yes"}
        print(f"  Current status: {'enabled' if current_enabled else 'disabled'}")
        print()
        enable = self.ask_yes_no("Enable the TV / live stream module?", default=current_enabled)
        updates["TV_ENABLED"] = "true" if enable else "false"

        if not enable:
            update_env_keys(updates)
            self.ok("TV_ENABLED=false written to .env.")
            self.wait_continue()
            return

        # ── Default stream URL ──
        self.header("tv — default stream URL")
        self.note(
            "TV_STREAM_URL is the default stream the bot plays when you run /tv start "
            "without a URL argument. You can leave this blank and always pass a URL to /tv start."
        )
        print()
        print(f"  {bold('Supported URL types:')}")
        print(f"    {cyan('HLS')}          https://example.com/stream.m3u8")
        print(f"    {cyan('RTMP')}         rtmp://live.example.com/stream")
        print(f"    {cyan('YouTube live')} https://www.youtube.com/watch?v=ID")
        print(f"    {cyan('Generic HTTP')} https://stream.radio.example/live.aac")
        print()
        print(f"  {dim('tvkaista URLs are detected automatically and get the required headers.')}")
        print()

        current_url = env.get("TV_STREAM_URL", "")
        self.ask_text(
            "_tv_url_tmp",
            "TV_STREAM_URL (type skip to leave blank)",
            default=current_url,
            allow_blank=True,
            transform=lambda v: "" if v.lower() in {"skip", "none", "-"} else v,
        )
        updates["TV_STREAM_URL"] = self.values.pop("_tv_url_tmp", current_url)

        # ── Webhook ──
        self.header("tv — chrome extension webhook (optional)")
        self.note(
            "The webhook server lets the Chrome extension push a new stream URL "
            "to the bot automatically when the tvkaista auth token expires. "
            "Leave TV_WEBHOOK_SECRET blank to disable the webhook server entirely."
        )
        print()
        current_secret = env.get("TV_WEBHOOK_SECRET", "")
        if current_secret:
            self.ok("TV_WEBHOOK_SECRET is already set.")
            if self.ask_yes_no("Change it?", default=False):
                new_secret = self.ask_text(
                    "_tv_secret_tmp",
                    "New webhook secret (type skip to disable)",
                    allow_blank=True,
                    transform=lambda v: "" if v.lower() in {"skip", "none", "-"} else v,
                )
                current_secret = self.values.pop("_tv_secret_tmp", current_secret)
        else:
            self.info("Webhook server is not enabled.")
            if self.ask_yes_no("Set a webhook secret to enable it?", default=False):
                generated = secrets.token_urlsafe(24)
                self.info(f"Generated key: {bold(generated)}")
                if self.ask_yes_no("Use this key?", default=True):
                    current_secret = generated
                else:
                    current_secret = self.ask_text(
                        "_tv_secret_tmp",
                        "Paste webhook secret",
                        allow_blank=False,
                    )
                    current_secret = self.values.pop("_tv_secret_tmp", current_secret)
        updates["TV_WEBHOOK_SECRET"] = current_secret

        current_wport = env.get("TV_WEBHOOK_PORT", "8766")
        if current_secret:
            new_wport = self.ask_text(
                "_tv_wport_tmp",
                "TV_WEBHOOK_PORT",
                default=current_wport,
                allow_blank=False,
                validator=lambda v: v.isdigit() and 1024 <= int(v) <= 65535,
                error="Port must be a number between 1024 and 65535.",
            )
            updates["TV_WEBHOOK_PORT"] = self.values.pop("_tv_wport_tmp", current_wport)
        else:
            updates["TV_WEBHOOK_PORT"] = current_wport

        # ── Reconnect settings ──
        self.header("tv — reconnect / watchdog")
        self.note(
            "If the stream drops, the bot reconnects automatically. "
            "TV_MAX_RESTARTS is the maximum reconnect attempts within TV_RESTART_WINDOW_SECONDS. "
            "Defaults (3 attempts / 60 seconds) work well for most streams."
        )
        print()
        current_restarts = env.get("TV_MAX_RESTARTS", "3")
        current_window   = env.get("TV_RESTART_WINDOW_SECONDS", "60")

        new_restarts = self.ask_text(
            "_tv_restarts_tmp",
            f"TV_MAX_RESTARTS",
            default=current_restarts,
            validator=lambda v: v.isdigit() and int(v) >= 1,
            error="Must be a whole number >= 1.",
        )
        updates["TV_MAX_RESTARTS"] = self.values.pop("_tv_restarts_tmp", current_restarts)

        new_window = self.ask_text(
            "_tv_window_tmp",
            f"TV_RESTART_WINDOW_SECONDS",
            default=current_window,
            validator=lambda v: v.isdigit() and int(v) >= 10,
            error="Must be a number >= 10.",
        )
        updates["TV_RESTART_WINDOW_SECONDS"] = self.values.pop("_tv_window_tmp", current_window)

        # ── Write ──
        update_env_keys(updates)
        self.header("tv — saved")
        for key, val in updates.items():
            display = mask_value(key, val)
            self.ok(f"{key} = {display}")
        print()
        self.note("Restart the bot for changes to take effect.")
        self.note("Use /tv start [url] in Discord to begin streaming.")
        self.wait_continue()

    # ── Spotify section ────────────────────────────────────────────────────────

    def spotify_section(self) -> None:
        env = read_env(ENV_PATH)
        updates: dict[str, str] = {}

        self.header(
            "spotify import configuration",
            "Import Spotify playlists into bot playlists via track matching",
        )

        current_enabled = env.get("SPOTIFY_ENABLED", "").lower() in {"true", "1", "yes"}
        print(f"  Current status: {'enabled' if current_enabled else 'disabled'}")
        print()
        enable = self.ask_yes_no("Enable Spotify import?", default=current_enabled)
        updates["SPOTIFY_ENABLED"] = "true" if enable else "false"

        if not enable:
            update_env_keys(updates)
            self.ok("SPOTIFY_ENABLED=false written to .env.")
            self.wait_continue()
            return

        self.header("spotify — developer credentials")
        self.note(
            "The bot uses Spotify's Client Credentials flow — it never asks for a user login. "
            "You need a free Spotify Developer account and a registered application."
        )
        print()
        print(f"  {bold('How to get your Spotify credentials:')}")
        print()
        print(f"  1. Open the Spotify Developer Dashboard:")
        print(f"     {cyan(SPOTIFY_DASHBOARD_URL)}")
        print()
        print(f"  2. Log in with your Spotify account (free is fine).")
        print()
        print(f"  3. Click {bold('Create app')}. Fill in:")
        print(f"       App name:        Discord Music Bot (or anything you like)")
        print(f"       App description: anything")
        print(f"       Redirect URI:    http://localhost")
        print(f"     Accept the terms and click Save.")
        print()
        print(f"  4. In your new app, click {bold('Settings')}.")
        print(f"     Your {bold('Client ID')} is shown there.")
        print(f"     Click {bold('View client secret')} to reveal the Client Secret.")
        print()

        if self.ask_yes_no("Open the Spotify Dashboard now?", default=False):
            self.open_link(SPOTIFY_DASHBOARD_URL)

        current_id = env.get("SPOTIFY_CLIENT_ID", "")
        self.ask_text(
            "_spotify_id_tmp",
            "Paste SPOTIFY_CLIENT_ID",
            default=current_id,
            allow_blank=False,
            validator=lambda v: len(v) >= 10,
            error="Client ID looks too short — copy it directly from the Settings page.",
        )
        updates["SPOTIFY_CLIENT_ID"] = self.values.pop("_spotify_id_tmp", current_id)

        current_secret = env.get("SPOTIFY_CLIENT_SECRET", "")
        self.ask_text(
            "_spotify_secret_tmp",
            "Paste SPOTIFY_CLIENT_SECRET",
            secret=True,
            default=current_secret,
            allow_blank=False,
            validator=lambda v: len(v) >= 10,
            error="Client Secret looks too short — reveal it on the Settings page.",
        )
        updates["SPOTIFY_CLIENT_SECRET"] = self.values.pop("_spotify_secret_tmp", current_secret)

        # ── Write ──
        update_env_keys(updates)
        self.header("spotify — saved")
        for key, val in updates.items():
            display = mask_value(key, val)
            self.ok(f"{key} = {display}")
        print()
        self.note("Restart the bot for changes to take effect.")
        self.note("Use /spotify import <url> in Discord to import a playlist.")
        self.note(
            "The bot matches Spotify tracks to YouTube using confidence scoring. "
            "Tracks above 0.82 are auto-accepted; others go to manual review."
        )
        self.wait_continue()

    # ── Update deps section ────────────────────────────────────────────────────

    def update_deps_section(self) -> None:
        self.header("update dependencies", "pip install -r requirements.txt")
        pip = ROOT / "venv" / "bin" / "pip"
        req = ROOT / "requirements.txt"

        if not (ROOT / "venv").exists():
            self.warn("No venv/ directory found.")
            if self.ask_yes_no("Create one now?", default=True):
                python = shutil.which("python3") or sys.executable
                self.run_command([python, "-m", "venv", "venv"])
            else:
                self.wait_continue()
                return

        if not req.exists():
            self.err("requirements.txt not found.")
            self.wait_continue()
            return

        if not self.ask_yes_no("Run pip install -r requirements.txt?", default=True):
            return

        result = subprocess.run([str(pip), "install", "-r", str(req)])
        print()
        if result.returncode == 0:
            self.ok("Dependencies installed/updated.")
        else:
            self.err("pip install failed — check the output above.")
        self.wait_continue()

    # ── Health check section ───────────────────────────────────────────────────

    def health_section(self) -> None:
        env = read_env(ENV_PATH)
        self.header("health check", f"Reading {ENV_PATH}")

        def row(key: str, label: str, *, required: bool = False) -> None:
            val = env.get(key, "")
            indicator = status_indicator(val, required=required)
            display = mask_value(key, val)
            print(f"  {indicator}  {key:<30}  {display}")

        print(f"  {dim('─' * 58)}")
        print(f"  {bold('Core Discord')}")
        print(f"  {dim('─' * 58)}")
        row("BOT_TOKEN",    "Bot token",      required=True)
        row("MY_GUILD",     "Server ID",      required=True)
        row("ADMIN_USER_ID","Admin user ID")
        row("ADMIN_ROLE_ID","Admin role ID")
        row("ADMIN_ROLE_NAME", "Admin role name")
        row("QUOTES_ID",    "Quotes channel")

        print()
        print(f"  {dim('─' * 58)}")
        webui_on = env.get("WEBUI_ENABLED", "").lower() in {"true", "1", "yes"}
        print(f"  {bold('Web UI')}  {green('enabled') if webui_on else dim('disabled')}")
        print(f"  {dim('─' * 58)}")
        if webui_on:
            row("WEBUI_SECRET_KEY",  "Admin bypass key", required=True)
            row("WEBUI_PUBLIC_URL",  "Public URL (for /webui command)", required=True)
            row("WEBUI_BIND_HOST",   "Bind host")
            row("WEBUI_PORT",        "Port")
        else:
            self.note("Set WEBUI_ENABLED=true and run option 2 to configure.")

        print()
        print(f"  {dim('─' * 58)}")
        tv_on = env.get("TV_ENABLED", "").lower() in {"true", "1", "yes"}
        print(f"  {bold('TV / live stream')}  {green('enabled') if tv_on else dim('disabled')}")
        print(f"  {dim('─' * 58)}")
        if tv_on:
            row("TV_STREAM_URL",           "Default stream URL")
            row("TV_WEBHOOK_SECRET",       "Webhook secret")
            row("TV_WEBHOOK_PORT",         "Webhook port")
            row("TV_MAX_RESTARTS",         "Max reconnects")
            row("TV_RESTART_WINDOW_SECONDS", "Reconnect window (s)")
        else:
            self.note("Set TV_ENABLED=true and run option 3 to configure.")

        print()
        print(f"  {dim('─' * 58)}")
        spotify_on = env.get("SPOTIFY_ENABLED", "").lower() in {"true", "1", "yes"}
        print(f"  {bold('Spotify')}  {green('enabled') if spotify_on else dim('disabled')}")
        print(f"  {dim('─' * 58)}")
        if spotify_on:
            row("SPOTIFY_CLIENT_ID",     "Client ID",     required=True)
            row("SPOTIFY_CLIENT_SECRET", "Client Secret", required=True)
        else:
            self.note("Set SPOTIFY_ENABLED=true and run option 4 to configure.")

        print()
        print(f"  {dim('─' * 58)}")
        print(f"  {bold('Environment')}")
        print(f"  {dim('─' * 58)}")
        venv_ok = (ROOT / "venv" / "bin" / "python").exists()
        req_ok  = (ROOT / "requirements.txt").exists()
        print(f"  {status_indicator('yes' if venv_ok else '')}  {'venv exists':<30}  {green('yes') if venv_ok else red('no — run option 5')}")
        print(f"  {status_indicator('yes' if req_ok else '')}  {'requirements.txt':<30}  {green('yes') if req_ok else red('not found')}")
        print()

        self.wait_continue()


# ── Self-test ──────────────────────────────────────────────────────────────────

def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "setup.tmp"
        state = {"version": STATE_VERSION, "mode": "quick", "values": {"BOT_TOKEN": "x.y.z"}, "setup": {}}
        save_state(state, state_path)
        loaded = load_state(state_path)
        assert loaded is not None
        assert loaded["values"]["BOT_TOKEN"] == "x.y.z"
        mode = state_path.stat().st_mode & 0o777
        assert mode == 0o600
        remove_state(state_path)
        assert not state_path.exists()

        # update_env_keys
        env_path = Path(tmp) / ".env"
        env_path.write_text("BOT_TOKEN=tok\nMY_GUILD=123\n")
        import unittest.mock
        with unittest.mock.patch(f"{__name__}.ENV_PATH", env_path), \
             unittest.mock.patch(f"{__name__}.ENV_BACKUP_PATH", Path(tmp) / ".env.backup"):
            update_env_keys({"MY_GUILD": "456", "WEBUI_ENABLED": "true"})
        result = read_env(env_path)
        assert result["BOT_TOKEN"] == "tok"
        assert result["MY_GUILD"] == "456"
        assert result["WEBUI_ENABLED"] == "true"

    assert validate_snowflake("123456789012345678")
    assert not validate_snowflake("abc")
    assert validate_quotes_id("0")
    assert normalize_optional_snowflake("skip") == ""
    rendered = render_env({"BOT_TOKEN": "token", "MY_GUILD": "1", "ADMIN_USERNAME": "ignored"})
    assert "BOT_TOKEN=" in rendered
    assert "ADMIN_USERNAME" not in rendered
    rendered_lines = rendered.splitlines()
    assert rendered_lines.index("ADMIN_ROLE_NAME=") < rendered_lines.index("ALLOW_ADMIN_ROLE_NAME=")
    assert rendered_lines.index("ALLOW_ADMIN_ROLE_NAME=") < rendered_lines.index("ADMIN_ROLE_ID=")
    env_example = render_env_example()
    assert "replace_with_your_discord_bot_token" in env_example
    example_lines = env_example.splitlines()
    assert example_lines.index(f"ADMIN_ROLE_NAME={DEFAULT_ADMIN_ROLE_NAME}") < example_lines.index("ALLOW_ADMIN_ROLE_NAME=false")
    assert build_venv_commands()[0][-3:] == ["-m", "venv", "venv"]
    assert build_screen_start_command()[:4] == ["screen", "-S", "bot", "-dm"]
    service_text = render_systemd_service("botuser", Path("/srv/discordmusic"))
    assert "BOT_TOKEN" not in service_text
    assert "NoNewPrivileges=true" in service_text
    assert "ReadWritePaths=/srv/discordmusic" in service_text
    temp_service = write_private_temp_service(service_text)
    try:
        assert temp_service.stat().st_mode & 0o777 == 0o600
        commands = build_systemd_install_commands(temp_service)
        assert commands[0][2] == str(temp_service)
        assert SERVICE_NAME in commands[2]
    finally:
        temp_service.unlink()
    assert mask_value("BOT_TOKEN", "abc") == "***set***"
    assert mask_value("MY_GUILD", "") == dim("(not set)")
    print("setup assistant self-test passed")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    if "--self-test" in sys.argv:
        self_test()
        return

    assistant = SetupAssistant()
    try:
        if "--setup" in sys.argv:
            assistant.run_initial_setup()
        else:
            assistant.run()
    except SetupExit as exc:
        if exc.save:
            print(f"\n  Progress saved to {STATE_PATH}. Re-run the assistant to resume.")
        else:
            print("\n  Exited without saving progress.")
        sys.exit(0)
    except KeyboardInterrupt:
        assistant.save()
        print(f"\n  Interrupted. Progress saved to {STATE_PATH}.")
        sys.exit(1)


if __name__ == "__main__":
    main()
