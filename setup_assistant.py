#!/usr/bin/env python3
"""
Friendly terminal setup assistant for the Discord music bot.

The assistant is intentionally stdlib-only so it can run before the virtualenv
exists. It collects Discord configuration, writes .env safely, can resume from
setup.tmp, and can optionally run the common local setup commands.
"""
from __future__ import annotations

import getpass
import json
import os
import platform
import re
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

STATE_VERSION = 1
DEFAULT_ADMIN_ROLE_NAME = "Bottiadmin"
SERVICE_NAME = "discordmusicbot.service"

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{27,}$")
SNOWFLAKE_PATTERN = re.compile(r"^\d{17,20}$")
F1_VALUES = {"f1", ":save", "\\f1", "\x1bOP", "\x1b[11~"}
F2_VALUES = {"f2", ":quit", ":nosave", "\\f2", "\x1bOQ", "\x1b[12~"}

ENV_FIELDS = [
    "BOT_TOKEN",
    "MY_GUILD",
    "QUOTES_ID",
    "ADMIN_USER_ID",
    "ADMIN_ROLE_NAME",
    "ADMIN_ROLE_ID",
    "ADMIN_USERNAME",
]
SECRET_FIELDS = {"BOT_TOKEN"}


class SetupExit(Exception):
    """Raised when the user uses a setup control action."""

    def __init__(self, save: bool):
        self.save = save
        super().__init__("setup exit")


def supports_color() -> bool:
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def color(text: str, code: str) -> str:
    if not supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def command_text(command: list[str]) -> str:
    return " ".join(command)


def clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


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
        return "(empty)"
    if key in SECRET_FIELDS:
        return "***masked***"
    return value


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
        # Admin role by name. This is the default and easiest role setup.
        ADMIN_ROLE_NAME={DEFAULT_ADMIN_ROLE_NAME}
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
    if shutil.which("apt") and any(name in os_release for name in ["debian", "ubuntu", "linuxmint", "pop"]):
        return "Debian/Ubuntu", ["sudo", "apt", "install", "-y", "screen"]
    if shutil.which("dnf") and any(name in os_release for name in ["fedora", "rhel", "centos", "rocky", "alma"]):
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

        StandardOutput=append:{workdir / "output.log"}
        StandardError=append:{workdir / "output.log"}

        [Install]
        WantedBy=multi-user.target
        """
    ).strip() + "\n"


def write_private_temp_service(content: str) -> Path:
    """Keep generated service previews out of the repo and private until sudo copies them."""
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        prefix="discordmusicbot-",
        suffix=".service",
        delete=False,
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


class SetupAssistant:
    def __init__(self) -> None:
        self.defaults = read_env(ENV_PATH) or read_env(ENV_TEMPLATE_PATH)
        self.state = load_state() or {"version": STATE_VERSION, "mode": "", "values": {}, "setup": {}}

    @property
    def values(self) -> dict[str, str]:
        return self.state.setdefault("values", {})

    def save(self) -> None:
        save_state(self.state)

    def set_value(self, key: str, value: str) -> None:
        self.values[key] = value
        self.save()

    def title(self, heading: str, detail: str = "") -> None:
        clear_screen()
        print(color("discord music bot setup", "1;36"))
        print(color("=" * 62, "36"))
        print(color(heading, "1"))
        if detail:
            print(textwrap.fill(detail, 78))
        print(color("-" * 62, "36"))
        print(color("F1/:save saves and exits | F2/:quit exits without setup.tmp", "2"))
        print()

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
            response = self.raw_input(f"{prompt}{suffix}: ", secret=secret).strip()
            self.handle_control(response)
            if not response and existing:
                value = existing
            else:
                value = response
            if transform:
                value = transform(value)
            if not value and allow_blank:
                self.set_value(key, "")
                return ""
            if value and (validator is None or validator(value)):
                self.set_value(key, value)
                return value
            print(color(f"  {error}", "31"))

    def ask_yes_no(self, prompt: str, *, default: bool = True) -> bool:
        suffix = "[Y/n]" if default else "[y/N]"
        while True:
            response = self.raw_input(f"{prompt} {suffix}: ").strip()
            self.handle_control(response)
            if not response:
                return default
            if response.lower() in {"y", "yes"}:
                return True
            if response.lower() in {"n", "no"}:
                return False
            print(color("  Please answer y or n.", "31"))

    def wait_continue(self, prompt: str = "Press Enter to continue.") -> None:
        response = self.raw_input(prompt + " ").strip()
        self.handle_control(response)

    def open_link_step(self, url: str) -> None:
        print(color(url, "4;36"))
        response = self.raw_input(
            "Press Enter to open this link in your default browser, or type anything to continue: "
        )
        self.handle_control(response)
        if response == "":
            opened = webbrowser.open(url)
            if opened:
                print(color("Opened in your browser.", "32"))
            else:
                print(color("Could not open the browser automatically. Copy the link above.", "33"))
            self.wait_continue()

    def choose_mode(self) -> str:
        if self.state.get("mode"):
            return str(self.state["mode"])
        self.title("choose setup mode")
        print("Guided setup explains each Discord step.")
        print("Quick setup is for advanced users who already know where to get ids.")
        quick = self.ask_yes_no("Do you want quick advanced setup?", default=False)
        mode = "quick" if quick else "guided"
        self.state["mode"] = mode
        self.save()
        return mode

    def collect_admin_role(self) -> None:
        print(
            textwrap.fill(
                "Admin access can come from your user id, an admin role name, or an optional "
                "admin role id. The role name is the default and easiest setup path.",
                78,
            )
        )
        role_name = self.ask_text(
            "ADMIN_ROLE_NAME",
            "Admin role name",
            default=DEFAULT_ADMIN_ROLE_NAME,
            allow_blank=True,
            transform=lambda value: "" if value.lower() in {"skip", "none", "no", "-"} else value,
        )
        if not role_name:
            self.set_value("ADMIN_ROLE_NAME", DEFAULT_ADMIN_ROLE_NAME)

        existing_role_id = self.values.get("ADMIN_ROLE_ID") or env_default(self.defaults, "ADMIN_ROLE_ID", "")
        if self.ask_yes_no(
            "Add or keep an admin role id too?",
            default=bool(existing_role_id),
        ):
            self.ask_text(
                "ADMIN_ROLE_ID",
                "Admin role id (optional, type skip to leave blank)",
                allow_blank=True,
                validator=validate_snowflake,
                error="Role id must be a 17-20 digit Discord id, or blank.",
                transform=normalize_optional_snowflake,
            )
        else:
            self.set_value("ADMIN_ROLE_ID", "")

    def guided_discord_steps(self) -> None:
        self.title("step 1 - discord developer portal")
        print("Create a new Discord application or open the application you want this bot to use.")
        self.open_link_step(DEV_PORTAL_URL)

        self.title("step 2 - create bot and copy token")
        print(
            textwrap.fill(
                "In the Developer Portal, open your app. From the left side, go to Bot. "
                "Under the bot username there is Token. Reset/copy the token and paste it here. "
                "The token is secret. This assistant writes it only to .env, not to .env.example.",
                78,
            )
        )
        print()
        print("You can also stop here and create .env yourself later.")
        self.ask_text(
            "BOT_TOKEN",
            "Paste Discord bot token",
            secret=True,
            validator=validate_token,
            error="Token format looks wrong. Discord bot tokens usually contain two dots.",
        )

        self.title("step 3 - your admin user id")
        print(
            textwrap.fill(
                "In Discord, enable Developer Mode if needed. Then click your own username "
                "from a message or while active in a voice channel, and choose Copy ID.",
                78,
            )
        )
        print(color(f"Developer Mode guide: {DEVMODE_GUIDE_URL}", "36"))
        self.ask_text(
            "ADMIN_USER_ID",
            "Paste your Discord user id",
            validator=validate_snowflake,
            error="User id must be a 17-20 digit Discord id.",
        )

        self.title("step 4 - admin role")
        print(
            textwrap.fill(
                "Create a server role for bot admins. The default name is Bottiadmin, "
                "but you can use another name. You can also add a role id if you want "
                "a stable id-based admin role check.",
                78,
            )
        )
        self.collect_admin_role()

        self.title("step 5 - optional username label")
        print(
            textwrap.fill(
                "You can enter your Discord username as a local note for the setup recap. "
                "The bot does not use usernames for admin access because usernames can change.",
                78,
            )
        )
        self.ask_text(
            "ADMIN_USERNAME",
            "Username note (optional, type skip to leave blank)",
            allow_blank=True,
            transform=lambda value: "" if value.lower() == "skip" else value,
        )

        self.title("step 6 - optional quotes channel")
        print(
            textwrap.fill(
                "The quotes channel is a fun extra feature. If you want it, right-click "
                "the channel and choose Copy ID. If you do not want quotes now, skip it.",
                78,
            )
        )
        quotes = self.ask_text(
            "QUOTES_ID",
            "Quotes channel id (optional, type skip to disable)",
            default=env_default(self.defaults, "QUOTES_ID", ""),
            allow_blank=True,
            validator=validate_quotes_id,
            error="Channel id must be a 17-20 digit Discord id, 0, or blank.",
            transform=normalize_optional_snowflake,
        )
        if not quotes:
            self.set_value("QUOTES_ID", "0")

        self.title("step 7 - server id")
        print("Right-click your server icon in Discord and choose Copy Server ID.")
        self.ask_text(
            "MY_GUILD",
            "Paste server id",
            validator=validate_snowflake,
            error="Server id must be a 17-20 digit Discord id.",
        )

        self.invite_walkthrough()

    def quick_steps(self) -> None:
        self.title("quick setup")
        print("Developer Portal:")
        self.open_link_step(DEV_PORTAL_URL)
        self.ask_text(
            "BOT_TOKEN",
            "Bot token",
            secret=True,
            validator=validate_token,
            error="Token format looks wrong.",
        )
        self.ask_text(
            "ADMIN_USER_ID",
            "Your Discord user id",
            validator=validate_snowflake,
            error="User id must be a 17-20 digit Discord id.",
        )
        quotes = self.ask_text(
            "QUOTES_ID",
            "Quotes channel id (optional, type skip to disable)",
            allow_blank=True,
            validator=validate_quotes_id,
            error="Channel id must be a 17-20 digit Discord id, 0, or blank.",
            transform=normalize_optional_snowflake,
        )
        if not quotes:
            self.set_value("QUOTES_ID", "0")
        self.ask_text(
            "MY_GUILD",
            "Server id",
            validator=validate_snowflake,
            error="Server id must be a 17-20 digit Discord id.",
        )
        self.collect_admin_role()
        self.set_value("ADMIN_USERNAME", self.values.get("ADMIN_USERNAME", ""))

    def invite_walkthrough(self) -> None:
        self.title("invite the bot")
        print(
            textwrap.fill(
                "Open your application in the Discord Developer Portal, go to OAuth2, "
                "then OAuth2 URL Generator. Select the bot scope. Administrator is easiest, "
                "but broad. For minimum permissions choose: View Channels, Send Messages, "
                "Embed Links, Attach Files, Read Message History, Use External Emojis, "
                "Add Reactions, Connect, and Speak. Copy the Generated URL, open it in "
                "your browser, and add the bot to your server.",
                78,
            )
        )
        print()
        self.open_link_step(DEV_PORTAL_URL)

    def recap(self) -> bool:
        self.title("configuration recap")
        print("The assistant collected:")
        for key in ENV_FIELDS:
            print(f"  {key}: {mask_value(key, self.values.get(key, ''))}")
        print()
        print("The bot will use ADMIN_USER_ID, ADMIN_ROLE_NAME, and optional ADMIN_ROLE_ID for admin access.")
        print("ADMIN_ROLE_NAME is the default role setup; the bot will still start if that role is missing.")
        return self.ask_yes_no("Write these values to .env now?", default=True)

    def write_files(self) -> None:
        write_env(self.values)
        created_example = False
        if not ENV_TEMPLATE_PATH.exists():
            created_example = write_env_example_if_needed()
        else:
            if self.ask_yes_no("Refresh .env.example placeholders? Real secrets will not be written there.", default=False):
                created_example = write_env_example_if_needed(force=True)
        self.title("environment written")
        print(f"Wrote {ENV_PATH}")
        if ENV_BACKUP_PATH.exists():
            print(f"Existing .env backup: {ENV_BACKUP_PATH}")
        if created_example:
            print(f"Wrote safe placeholder template: {ENV_TEMPLATE_PATH}")
        else:
            print(".env.example was left unchanged.")
        self.wait_continue()

    def run_command(self, command: list[str], *, cwd: Path = ROOT) -> bool:
        print(color(f"$ {command_text(command)}", "1;34"))
        try:
            subprocess.run(command, cwd=str(cwd), check=True)
            return True
        except FileNotFoundError:
            print(color(f"Command not found: {command[0]}", "31"))
            return False
        except subprocess.CalledProcessError as exc:
            print(color(f"Command failed with exit code {exc.returncode}.", "31"))
            return False

    def dependency_setup(self) -> None:
        self.title("install python dependencies")
        print("To prepare the bot, the assistant can run:")
        print("  python3 -m venv venv")
        print("  venv/bin/python -m pip install -r requirements.txt")
        print()
        print("After this, the bot runs with the pinned dependencies from requirements.txt.")
        self.wait_continue("Press Enter to continue to dependency setup.")
        if not self.ask_yes_no("Run the virtualenv and pip install commands?", default=True):
            return
        for command in build_venv_commands():
            if not self.run_command(command):
                print("Setup progress was saved. Fix the error and run this assistant again.")
                self.save()
                return

    def screen_setup(self) -> None:
        self.title("run bot in screen")
        print("screen keeps the bot running after you detach from the terminal.")
        package = detect_package_manager()
        if shutil.which("screen"):
            print("screen is already installed.")
        elif package:
            label, command = package
            print(f"Detected {label}.")
            if self.ask_yes_no(f"Install screen with `{command_text(command)}`?", default=True):
                self.run_command(command)
        else:
            print("I could not detect a package manager for screen. Install screen manually if you want this mode.")

        if not shutil.which("screen"):
            print("screen is not available, so the assistant will not start the bot in screen.")
            self.wait_continue()
            return

        print()
        print("The assistant can now start the bot with:")
        print(f"  {command_text(build_screen_start_command())}")
        print("After it starts:")
        print("  reconnect: screen -r -D bot")
        print("  detach while leaving it running: press Ctrl-a, then d")
        if self.ask_yes_no("Start the bot in a detached screen session now?", default=True):
            self.run_command(build_screen_start_command())
            print(color("Bot start command sent to screen.", "32"))
            print("Use `screen -r -D bot` to view it.")
            self.wait_continue()

    def systemd_setup(self) -> None:
        self.title("optional autostart")
        print("Autostart makes the bot start on boot and restart after failure.")
        if platform.system().lower() != "linux" or not shutil.which("systemctl"):
            print("systemd setup is only available on Linux systems with systemctl.")
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
        print("Service preview:")
        print(color("-" * 62, "36"))
        print(service_content.rstrip())
        print(color("-" * 62, "36"))
        print("The assistant will copy this through a private temporary file if you confirm.")
        if self.ask_yes_no("Install and start the systemd service now?", default=False):
            temp_service = write_private_temp_service(service_content)
            try:
                commands = build_systemd_install_commands(temp_service)
                print("The assistant will run:")
                for command in commands:
                    print(f"  {command_text(command)}")
                for command in commands:
                    if not self.run_command(command):
                        print("Systemd setup stopped. The temporary service file was removed.")
                        return
                print(color("Systemd service installed and started.", "32"))
                self.wait_continue()
            finally:
                try:
                    temp_service.unlink()
                except OSError:
                    pass

    def finish(self) -> None:
        remove_state()
        self.title("setup complete")
        print("Your setup recap:")
        print(f"  environment: {ENV_PATH}")
        print("  run manually: source venv/bin/activate && python main.py")
        print("  screen reconnect: screen -r -D bot")
        print("  screen detach: Ctrl-a, then d")
        print()
        print("If Discord commands do not appear immediately, wait a minute and restart the bot once.")

    def run(self) -> None:
        existing = load_state()
        if existing:
            self.title("resume setup")
            print(f"Found saved setup progress in {STATE_PATH}.")
            print(color("This file may contain your bot token and is stored with private permissions.", "33"))
            if not self.ask_yes_no("Resume from setup.tmp?", default=True):
                remove_state()
                self.state = {"version": STATE_VERSION, "mode": "", "values": {}, "setup": {}}
        mode = self.choose_mode()
        if mode == "quick":
            self.quick_steps()
        else:
            self.guided_discord_steps()
        if self.recap():
            self.write_files()
        else:
            print("No .env changes were written.")
            self.save()
            return
        self.dependency_setup()
        self.screen_setup()
        self.systemd_setup()
        self.finish()


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

    assert validate_snowflake("123456789012345678")
    assert not validate_snowflake("abc")
    assert validate_quotes_id("0")
    assert normalize_optional_snowflake("skip") == ""
    rendered = render_env({"BOT_TOKEN": "token", "MY_GUILD": "1", "ADMIN_USERNAME": "ignored"})
    assert "BOT_TOKEN=" in rendered
    assert "ADMIN_USERNAME" not in rendered
    assert rendered.find("ADMIN_ROLE_NAME") < rendered.find("ADMIN_ROLE_ID")
    assert "replace_with_your_discord_bot_token" in render_env_example()
    assert render_env_example().find("ADMIN_ROLE_NAME") < render_env_example().find("ADMIN_ROLE_ID")
    assert build_venv_commands()[0][-3:] == ["-m", "venv", "venv"]
    assert build_screen_start_command()[:4] == ["screen", "-S", "bot", "-dm"]
    service_text = render_systemd_service("botuser", Path("/srv/discordmusic"))
    assert "BOT_TOKEN" not in service_text
    assert "MY_GUILD" not in service_text
    assert "QUOTES_ID" not in service_text
    temp_service = write_private_temp_service(service_text)
    try:
        assert temp_service.stat().st_mode & 0o777 == 0o600
        commands = build_systemd_install_commands(temp_service)
        assert commands[0][2] == str(temp_service)
        assert SERVICE_NAME in commands[2]
    finally:
        temp_service.unlink()
    print("setup assistant self-test passed")


def main() -> None:
    if "--self-test" in sys.argv:
        self_test()
        return
    assistant = SetupAssistant()
    try:
        assistant.run()
    except SetupExit as exc:
        if exc.save:
            print(f"\nSetup saved to {STATE_PATH}. Re-run the assistant to resume.")
        else:
            print("\nSetup exited without saving progress.")
        sys.exit(0)
    except KeyboardInterrupt:
        assistant.save()
        print(f"\nSetup interrupted. Progress saved to {STATE_PATH}.")
        sys.exit(1)


if __name__ == "__main__":
    main()
