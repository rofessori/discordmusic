"""
Web UI module for the Discord music bot.

Provides a browser-based interface for managing playlists, queue, favorites,
and admin tools. Runs as a FastAPI server on the same asyncio event loop.

Activation:
    Set WEBUI_ENABLED=true in .env, then restart.
    Everything else is automatic:
      - WEBUI_SECRET_KEY auto-generated and written to .env if not set.
      - Missing packages (uvicorn, fastapi, aiohttp) auto-installed.
      - cloudflared auto-downloaded to bin/ if not found in PATH.
      - Cloudflare tunnel started automatically and URL persisted to
        cloudflare_tunnel_url.json — survives bot restarts.
      - Port conflicts resolved automatically: same-bot processes are
        assimilated (killed and replaced); foreign processes cause a
        fallback to the next available port.

Environment variables:
    WEBUI_ENABLED           – set to true/1/yes to activate
    WEBUI_PORT              – port to bind (default: 8765)
    WEBUI_BIND_HOST         – host to bind (default: 127.0.0.1)
    WEBUI_SECRET_KEY        – admin bearer token (auto-generated if unset)
    WEBUI_PUBLIC_URL        – override the public URL (skips cloudflared)
    WEBUI_CLOUDFLARED_AUTO  – set to false to disable cloudflared (default: true when WEBUI_ENABLED)
"""

import asyncio
import json
import logging
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WEBUI_PORT             = int(os.getenv("WEBUI_PORT", "8765"))
WEBUI_BIND_HOST        = os.getenv("WEBUI_BIND_HOST", "127.0.0.1")
WEBUI_SECRET_KEY       = os.getenv("WEBUI_SECRET_KEY", "")
WEBUI_PUBLIC_URL       = os.getenv("WEBUI_PUBLIC_URL", "")
# Defaults to True when WEBUI_ENABLED — user can set WEBUI_CLOUDFLARED_AUTO=false to opt out
WEBUI_CLOUDFLARED_AUTO = os.getenv("WEBUI_CLOUDFLARED_AUTO", "true").lower() not in ("0", "false", "no")

# Project root (parent of this webui/ package)
_MODULE_DIR  = os.path.dirname(__file__)
_PROJECT_DIR = os.path.normpath(os.path.join(_MODULE_DIR, ".."))

# Paths for persistent state
_TUNNEL_URL_FILE   = os.path.join(_PROJECT_DIR, "cloudflare_tunnel_url.json")
_CLOUDFLARED_BIN   = os.path.join(_PROJECT_DIR, "bin", "cloudflared")
_CF_URL_RE         = re.compile(r'https://\S+\.trycloudflare\.com')

# Load persisted tunnel URL at module import time so /webui works immediately
# on restart before the new tunnel is ready.
cloudflared_tunnel_url: str | None = None


def _load_persisted_tunnel_url() -> str | None:
    try:
        with open(_TUNNEL_URL_FILE) as f:
            data = json.load(f)
        url = data.get("url", "")
        if url and "trycloudflare.com" in url:
            return url
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def _save_tunnel_url(url: str) -> None:
    try:
        with open(_TUNNEL_URL_FILE, "w") as f:
            json.dump({"url": url, "saved_at": time.time()}, f)
    except Exception as exc:
        logger.debug(f"[webui] Failed to persist tunnel URL: {exc}")


# Initialise from disk at module load (before tunnel is ready)
cloudflared_tunnel_url = _load_persisted_tunnel_url()
if cloudflared_tunnel_url:
    logger.debug(f"[webui] Loaded persisted tunnel URL: {cloudflared_tunnel_url}")

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

def check_dependencies() -> list:
    """Return list of missing package specs needed to run the web UI."""
    missing = []
    for pkg, spec in (
        ("uvicorn",  "uvicorn>=0.30.0,<1.0"),
        ("fastapi",  "fastapi>=0.111.0,<1.0"),
        ("aiohttp",  "aiohttp>=3.9.0,<4.0"),
    ):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(spec)
    return missing


def _auto_install_deps(missing: list) -> bool:
    """
    Run pip install for missing packages.
    Returns True if all packages installed successfully.
    """
    logger.info(f"[webui] Auto-installing missing packages: {missing}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet"] + missing,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            logger.info("[webui] Packages installed successfully")
            return True
        logger.warning(f"[webui] pip install failed:\n{result.stderr[:400]}")
        return False
    except Exception as exc:
        logger.warning(f"[webui] Auto-install failed: {exc}")
        return False

# ---------------------------------------------------------------------------
# Secret key auto-generation
# ---------------------------------------------------------------------------

def _ensure_secret_key() -> str:
    """
    Return WEBUI_SECRET_KEY. If not set, generate one and write it to .env.
    Updates the module-level WEBUI_SECRET_KEY so the server uses it.
    """
    global WEBUI_SECRET_KEY
    key = WEBUI_SECRET_KEY.strip()
    if key:
        return key

    key = secrets.token_urlsafe(32)
    WEBUI_SECRET_KEY = key
    logger.info("[webui] Auto-generated WEBUI_SECRET_KEY")

    env_path = os.path.join(_PROJECT_DIR, ".env")
    _write_env_value(env_path, "WEBUI_SECRET_KEY", key)
    return key


def _write_env_value(env_path: str, key: str, value: str) -> None:
    """Insert or replace a key=value line in .env."""
    try:
        if os.path.isfile(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
        else:
            lines = []

        new_line = f"{key}={value}\n"
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                lines[i] = new_line
                break
        else:
            lines.append(new_line)

        with open(env_path, "w") as f:
            f.writelines(lines)
        logger.debug(f"[webui] Wrote {key} to {env_path}")
    except Exception as exc:
        logger.warning(f"[webui] Could not write {key} to .env: {exc}")

# ---------------------------------------------------------------------------
# Port utilities
# ---------------------------------------------------------------------------

def _is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if we can bind the port right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _get_pid_on_port(port: int) -> int | None:
    """Return PID of the process listening on *port*, or None."""
    # Try psutil first (clean cross-platform)
    try:
        import psutil
        for conn in psutil.net_connections(kind="tcp"):
            if getattr(conn.laddr, "port", None) == port and conn.status == "LISTEN":
                return conn.pid
    except Exception:
        pass

    # macOS / Linux: lsof
    try:
        r = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=4,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().splitlines():
                line = line.strip()
                if line.isdigit():
                    return int(line)
    except Exception:
        pass

    # Linux: fuser
    try:
        r = subprocess.run(
            ["fuser", f"{port}/tcp"],
            capture_output=True, text=True, timeout=4,
        )
        if r.returncode == 0:
            parts = r.stdout.strip().split()
            if parts and parts[0].isdigit():
                return int(parts[0])
    except Exception:
        pass

    return None


def _is_discordmusic_process(pid: int) -> bool:
    """Heuristic: is this PID another instance of our bot?"""
    try:
        import psutil
        proc = psutil.Process(pid)
        cmdline = " ".join(proc.cmdline()).lower()
        return "main.py" in cmdline or "discordmusic" in cmdline
    except Exception:
        pass
    # Fallback: check /proc on Linux
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().replace(b"\x00", b" ").decode(errors="replace").lower()
        return "main.py" in cmdline or "discordmusic" in cmdline
    except Exception:
        pass
    return False


async def _kill_pid(pid: int) -> bool:
    """Send SIGTERM then SIGKILL to pid. Returns True if successfully killed."""
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            await asyncio.sleep(0.2)
            try:
                os.kill(pid, 0)  # 0 = existence check
            except ProcessLookupError:
                return True  # already gone
        # Still alive after 2s — force kill
        try:
            os.kill(pid, signal.SIGKILL)
            await asyncio.sleep(0.3)
        except ProcessLookupError:
            pass
        return True
    except (ProcessLookupError, PermissionError) as exc:
        logger.debug(f"[webui] kill PID {pid}: {exc}")
        return False


async def _assimilate_or_find_port(preferred_port: int) -> int:
    """
    Find a usable port starting from *preferred_port*.

    Strategy:
      1. Port is free → use it.
      2. Port is taken by another discordmusic process → kill it, take the port.
      3. Port is taken by something unrelated → try preferred+1 … preferred+4.
      4. Give up and return preferred_port anyway (uvicorn will log the error).
    """
    if _is_port_free(preferred_port):
        return preferred_port

    pid = _get_pid_on_port(preferred_port)
    if pid is not None:
        own_pid = os.getpid()
        if pid != own_pid and _is_discordmusic_process(pid):
            logger.info(
                f"[webui] Assimilating old bot instance on port {preferred_port} (PID {pid})"
            )
            killed = await _kill_pid(pid)
            if killed:
                await asyncio.sleep(0.5)
                if _is_port_free(preferred_port):
                    logger.info(f"[webui] Port {preferred_port} reclaimed after assimilation")
                    return preferred_port
        else:
            logger.info(
                f"[webui] Port {preferred_port} taken by unrelated process (PID {pid}), "
                "looking for an alternative"
            )
    else:
        logger.info(f"[webui] Port {preferred_port} appears busy, looking for an alternative")

    # Try next few ports
    for offset in range(1, 6):
        candidate = preferred_port + offset
        if _is_port_free(candidate):
            logger.info(f"[webui] Using fallback port {candidate}")
            return candidate

    logger.warning(
        f"[webui] Could not find a free port near {preferred_port}; "
        "proceeding anyway — uvicorn will report the exact error"
    )
    return preferred_port

# ---------------------------------------------------------------------------
# BotState
# ---------------------------------------------------------------------------

class BotState:
    """
    Live view of bot state exposed to the web server.
    Holds references (not snapshots) so values are always current.
    """
    def __init__(self, client_ref, queue_ref):
        self._client     = client_ref
        self._queue      = queue_ref
        self._start_time = time.time()

    @property
    def queue(self) -> list:
        return self._queue

    @property
    def current_track_info(self):
        return getattr(self._client, "current_track_info", None)

    @property
    def _voice_client(self):
        vcs = getattr(self._client, "voice_clients", [])
        return vcs[0] if vcs else None

    @property
    def is_playing(self) -> bool:
        vc = self._voice_client
        return bool(vc and vc.is_playing())

    @property
    def is_paused(self) -> bool:
        vc = self._voice_client
        return bool(vc and vc.is_paused())

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time

    @property
    def process_memory_mb(self) -> float | None:
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            if platform.system() == "Darwin":
                return usage.ru_maxrss / (1024 * 1024)
            return usage.ru_maxrss / 1024
        except Exception:
            return None

    @property
    def volume_percent(self) -> int:
        try:
            return int(round(float(getattr(self._client, "volume", 0.5)) * 100))
        except Exception:
            return 0

    @property
    def is_repeat(self) -> bool:
        return bool(getattr(self._client, "repeat", False))

    @property
    def queue_length(self) -> int:
        return len(self._queue)

    @property
    def session_count(self) -> int:
        store = getattr(self._client, "webui_session_store", None)
        if store is None:
            return 0
        try:
            return store.active_count()
        except Exception:
            return 0

    def get_config_snapshot(self) -> dict:
        return {
            "volume_percent":  self.volume_percent,
            "is_repeat":       self.is_repeat,
            "is_playing":      self.is_playing,
            "is_paused":       self.is_paused,
            "queue_length":    self.queue_length,
            "uptime_seconds":  round(self.uptime_seconds, 1),
            "session_count":   self.session_count,
        }

    def disk_usage(self, base_dir: str) -> dict:
        result = {}
        for name in ("cache", "playlists"):
            path = os.path.join(base_dir, name)
            total, count = 0, 0
            if os.path.isdir(path):
                for dp, _, files in os.walk(path):
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(dp, f))
                            count += 1
                        except OSError:
                            pass
            result[name] = {"bytes": total, "files": count}
        return result

    def skip(self) -> bool:
        vc = self._voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            return True
        return False

    def pause(self) -> bool:
        vc = self._voice_client
        if vc and vc.is_playing():
            vc.pause()
            return True
        return False

    def resume(self) -> bool:
        vc = self._voice_client
        if vc and vc.is_paused():
            vc.resume()
            return True
        return False

    def add_to_queue(self, track: dict):
        self._queue.append(track)

# ---------------------------------------------------------------------------
# cloudflared management
# ---------------------------------------------------------------------------

async def _ensure_cloudflared() -> str | None:
    """
    Locate the cloudflared binary.
    Checks PATH, then project bin/, then auto-downloads from GitHub.
    Returns the path to the binary, or None on failure.
    """
    # In PATH
    found = shutil.which("cloudflared")
    if found:
        return found

    # Project-local bin/
    local = _CLOUDFLARED_BIN
    if platform.system() == "Windows":
        local += ".exe"
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local

    # Auto-download
    logger.info("[webui] cloudflared not found — auto-downloading from GitHub")
    return await _download_cloudflared(local)


async def _download_cloudflared(dest_path: str) -> str | None:
    """Download the cloudflared binary for the current platform."""
    try:
        import aiohttp
    except ImportError:
        logger.warning("[webui] aiohttp not installed — cannot auto-download cloudflared")
        return None

    system  = platform.system().lower()
    machine = platform.machine().lower()

    os_map   = {"darwin": "darwin", "linux": "linux", "windows": "windows"}
    arch_map = {
        "x86_64": "amd64", "amd64": "amd64",
        "aarch64": "arm64", "arm64": "arm64",
    }
    os_name = os_map.get(system)
    arch    = arch_map.get(machine)
    if not os_name or not arch:
        logger.warning(
            f"[webui] cloudflared auto-download not supported for {system}/{machine}"
        )
        return None

    ext   = ".exe" if system == "windows" else ""
    fname = f"cloudflared-{os_name}-{arch}{ext}"
    url   = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{fname}"

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                url, timeout=aiohttp.ClientTimeout(total=90)
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"[webui] cloudflared download failed: HTTP {resp.status}"
                    )
                    return None
                data = await resp.read()
        with open(dest_path, "wb") as f:
            f.write(data)
        os.chmod(dest_path, 0o755)
        logger.info(f"[webui] cloudflared downloaded to {dest_path}")
        return dest_path
    except Exception as exc:
        logger.warning(f"[webui] cloudflared download failed: {exc}")
        return None


async def _run_cloudflared(port: int) -> None:
    """Launch cloudflared quick tunnel and persist the URL."""
    global cloudflared_tunnel_url

    cf_bin = await _ensure_cloudflared()
    if not cf_bin:
        logger.warning(
            "[webui] cloudflared not available and auto-download failed. "
            "Install cloudflared manually or set WEBUI_PUBLIC_URL."
        )
        return

    logger.info(f"[webui] Starting cloudflared quick tunnel on port {port}")
    try:
        proc = await asyncio.create_subprocess_exec(
            cf_bin, "tunnel", "--url", f"http://127.0.0.1:{port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:
        logger.warning(f"[webui] Failed to launch cloudflared: {exc}")
        return

    async def _drain(stream):
        global cloudflared_tunnel_url
        async for raw in stream:
            line = raw.decode(errors="replace").strip()
            if not cloudflared_tunnel_url or "trycloudflare.com" not in cloudflared_tunnel_url:
                m = _CF_URL_RE.search(line)
                if m:
                    new_url = m.group(0).rstrip("/")
                    cloudflared_tunnel_url = new_url
                    _save_tunnel_url(new_url)
                    logger.info(f"[webui] Cloudflare tunnel URL: {new_url}")

    asyncio.create_task(_drain(proc.stdout))
    asyncio.create_task(_drain(proc.stderr))

# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

async def start(*, playlists_dir: str, bot_state: "BotState", sessions,
                guesser=None):
    """
    Start the FastAPI server as a background asyncio task.
    Returns immediately; server runs concurrently with the bot.
    All setup steps are automatic — keys, packages, ports, cloudflared.
    """
    global WEBUI_SECRET_KEY

    # 1. Ensure dependencies are installed
    missing = check_dependencies()
    if missing:
        logger.info(
            f"[webui] Missing packages: {missing} — attempting auto-install"
        )
        if not _auto_install_deps(missing):
            logger.warning(
                "[webui] Auto-install failed. "
                f"Run manually: pip install {' '.join(missing)}"
            )
            return
        # Re-check after install
        still_missing = check_dependencies()
        if still_missing:
            logger.warning(
                f"[webui] Packages still missing after install: {still_missing}"
            )
            return

    # 2. Ensure secret key exists
    secret_key = _ensure_secret_key()

    # 3. Determine port (assimilate or fall back)
    port = await _assimilate_or_find_port(WEBUI_PORT)

    import uvicorn
    from webui.server import app, configure

    configure(
        playlists_dir=playlists_dir,
        bot_state=bot_state,
        secret_key=secret_key,
        sessions=sessions,
        guesser=guesser,
    )

    config = uvicorn.Config(
        app,
        host=WEBUI_BIND_HOST,
        port=port,
        log_level="warning",
        loop="asyncio",
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )

    class _EmbeddedServer(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            pass

    server = _EmbeddedServer(config)
    logger.info(f"[webui] Server starting on http://{WEBUI_BIND_HOST}:{port}")

    async def _serve():
        try:
            await server.serve()
        except OSError as exc:
            logger.warning(
                f"[webui] Server could not bind to port {port}: {exc} — "
                "the web UI will not be available this session"
            )
        except SystemExit:
            logger.warning(
                f"[webui] Server exited (port {port} may be in use) — "
                "the web UI will not be available this session"
            )
        except Exception as exc:
            logger.error(f"[webui] Server stopped unexpectedly: {exc}", exc_info=True)

    asyncio.create_task(_serve())

    # 4. Start cloudflared if no manual public URL
    if WEBUI_CLOUDFLARED_AUTO and not WEBUI_PUBLIC_URL:
        asyncio.create_task(_run_cloudflared(port))
    elif not WEBUI_PUBLIC_URL and not WEBUI_CLOUDFLARED_AUTO:
        logger.info(
            "[webui] WEBUI_CLOUDFLARED_AUTO=false and WEBUI_PUBLIC_URL not set. "
            "The /webui command will only work with a manually configured URL."
        )
