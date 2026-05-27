# friendly-streamprober + TV Module Prober Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python daemon (`friendly-streamprober`) that continually probes tvkaista.org stream URLs and exposes them over a local HTTP API, then wire the discordmusic bot's TV module to consume those URLs via a new `/tv channel <name>` command.

**Architecture:** The prober constructs tvkaista URLs from the known public opengraph pattern (`https://live-fi.tvkaista.net/{channel}/live.m3u8?src=opengraph&timestamp=YYYY-MM-DD-HH-MM`), probes them via HTTP HEAD every N seconds, and caches results. An aiohttp server on localhost exposes a JSON REST API. The Discord bot gains `TV_PROBER_URL` config and a `/tv channel` command; on stream reconnect, if the prober is configured it fetches a fresh URL automatically.

**Tech Stack:** Python 3.11+, aiohttp (prober HTTP server and outbound probing), python-dotenv, pytest + pytest-asyncio. No new deps for discordmusic — aiohttp is already in its requirements.txt.

---

## File Map

### New repo: `~/friendly-streamprober/`

| File | Responsibility |
|---|---|
| `streamprober/__init__.py` | Package marker |
| `streamprober/fetcher.py` | `build_stream_url(channel)` + `probe_channel(session, channel)` |
| `streamprober/server.py` | `ProberServer` class — aiohttp app + background probe loop |
| `fetch.py` | CLI entry point: one-shot URL fetch, bare URL or `--json` |
| `serve.py` | Daemon entry point: load .env, start `ProberServer`, run forever |
| `tests/__init__.py` | Package marker |
| `tests/test_fetcher.py` | Unit tests for fetcher |
| `tests/test_server.py` | Integration tests for HTTP API |
| `requirements.txt` | aiohttp, python-dotenv, pytest, pytest-asyncio |
| `.env.example` | Template with no secrets |
| `.gitignore` | Excludes `.env`, venv, cache |
| `README.md` | Install, configure, run, API reference, bot integration |
| `pytest.ini` | `asyncio_mode = auto` |

### Modified: `~/discordmusic/`

| File | Change |
|---|---|
| `tv_stream.py` | Add `fetch_prober_url(channel, prober_base_url)` |
| `main.py` | Add `TV_PROBER_URL` env var; add `client.tv_prober_channel` state; add `/tv channel` command; update `_tv_restart` to fetch fresh URL from prober; update `tv_stop_cmd` to clear prober channel |
| `docs/COMMANDS.md` | Add `/tv channel` to TV section; add `TV_PROBER_URL` note |
| `.env` | Add commented `TV_PROBER_URL` example |

---

## Task 1: friendly-streamprober — Project scaffold

**Files:**
- Create: `~/friendly-streamprober/streamprober/__init__.py`
- Create: `~/friendly-streamprober/tests/__init__.py`
- Create: `~/friendly-streamprober/requirements.txt`
- Create: `~/friendly-streamprober/pytest.ini`
- Create: `~/friendly-streamprober/.gitignore`
- Create: `~/friendly-streamprober/.env.example`

- [ ] **Step 1: Create repo directory and package skeleton**

```bash
mkdir -p ~/friendly-streamprober/streamprober
mkdir -p ~/friendly-streamprober/tests
touch ~/friendly-streamprober/streamprober/__init__.py
touch ~/friendly-streamprober/tests/__init__.py
```

- [ ] **Step 2: Write `requirements.txt`**

```
# ~/friendly-streamprober/requirements.txt
aiohttp>=3.9.0,<4.0
python-dotenv>=1.0.0,<2.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 3: Write `pytest.ini`**

```ini
# ~/friendly-streamprober/pytest.ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 4: Write `.gitignore`**

```
# ~/friendly-streamprober/.gitignore
.env
__pycache__/
*.pyc
*.pyo
.venv/
venv/
*.egg-info/
dist/
.pytest_cache/
.mypy_cache/
```

- [ ] **Step 5: Write `.env.example`**

```
# ~/friendly-streamprober/.env.example

# Local HTTP server settings
PROBER_HOST=127.0.0.1
PROBER_PORT=8765

# How often (seconds) to re-probe each channel
PROBE_INTERVAL=30

# Comma-separated list of tvkaista.org channel slugs to monitor
PROBER_CHANNELS=mtv3,nelonen,sub,tv5,jim,yle-teema-fem,kutonen,liv,ava
```

- [ ] **Step 6: Install dependencies in a venv**

```bash
cd ~/friendly-streamprober
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Expected: packages install without errors.

- [ ] **Step 7: Commit**

```bash
cd ~/friendly-streamprober
git init
git add .
git commit -m "chore: initial project scaffold"
```

---

## Task 2: friendly-streamprober — fetcher.py

**Files:**
- Create: `~/friendly-streamprober/streamprober/fetcher.py`

- [ ] **Step 1: Write `streamprober/fetcher.py`**

```python
# ~/friendly-streamprober/streamprober/fetcher.py
from datetime import datetime, timezone

_BASE = "https://live-fi.tvkaista.net"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "*/*",
    "Origin": "https://www.tvkaista.org",
    "Referer": "https://www.tvkaista.org/",
}


def build_stream_url(channel: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M")
    return f"{_BASE}/{channel}/live.m3u8?src=opengraph&timestamp={ts}"


async def probe_channel(session, channel: str) -> dict:
    """HEAD-probe a channel and return a result dict.

    Always returns a dict — never raises. Callers check result["ok"].
    """
    import aiohttp
    url = build_stream_url(channel)
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        async with session.head(url, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                return {"ok": True, "url": url, "channel": channel, "fetched_at": fetched_at}
            return {"ok": False, "url": url, "channel": channel, "fetched_at": fetched_at, "status": resp.status}
    except Exception as exc:
        return {"ok": False, "url": url, "channel": channel, "fetched_at": fetched_at, "error": str(exc)}
```

- [ ] **Step 2: Quick sanity smoke-test (no network needed yet — just import)**

```bash
cd ~/friendly-streamprober
source .venv/bin/activate
python -c "from streamprober.fetcher import build_stream_url; print(build_stream_url('mtv3'))"
```

Expected output: a URL like `https://live-fi.tvkaista.net/mtv3/live.m3u8?src=opengraph&timestamp=2026-05-27-...`

- [ ] **Step 3: Commit**

```bash
cd ~/friendly-streamprober
git add streamprober/fetcher.py
git commit -m "feat: fetcher — URL builder and channel probe"
```

---

## Task 3: friendly-streamprober — tests/test_fetcher.py

**Files:**
- Create: `~/friendly-streamprober/tests/test_fetcher.py`

- [ ] **Step 1: Write the tests**

```python
# ~/friendly-streamprober/tests/test_fetcher.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from streamprober.fetcher import build_stream_url, probe_channel


def test_build_stream_url_format():
    url = build_stream_url("mtv3")
    assert url.startswith("https://live-fi.tvkaista.net/mtv3/live.m3u8?src=opengraph&timestamp=")
    suffix = url.split("timestamp=")[1]
    parts = suffix.split("-")
    assert len(parts) == 5, f"expected YYYY-MM-DD-HH-MM, got {suffix!r}"
    assert len(parts[0]) == 4  # year


def test_build_stream_url_encodes_channel():
    url = build_stream_url("yle-teema-fem")
    assert "/yle-teema-fem/live.m3u8" in url


@pytest.mark.asyncio
async def test_probe_channel_success():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_session = MagicMock()
    mock_session.head.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.head.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await probe_channel(mock_session, "mtv3")

    assert result["ok"] is True
    assert result["channel"] == "mtv3"
    assert "live-fi.tvkaista.net/mtv3/live.m3u8" in result["url"]
    assert "fetched_at" in result
    assert "error" not in result


@pytest.mark.asyncio
async def test_probe_channel_404():
    mock_resp = AsyncMock()
    mock_resp.status = 404
    mock_session = MagicMock()
    mock_session.head.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.head.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await probe_channel(mock_session, "yle-tv2")

    assert result["ok"] is False
    assert result["channel"] == "yle-tv2"
    assert result["status"] == 404


@pytest.mark.asyncio
async def test_probe_channel_network_error():
    mock_session = MagicMock()
    mock_session.head.return_value.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
    mock_session.head.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await probe_channel(mock_session, "mtv3")

    assert result["ok"] is False
    assert "connection refused" in result["error"]
```

- [ ] **Step 2: Run tests and verify they pass**

```bash
cd ~/friendly-streamprober
source .venv/bin/activate
pytest tests/test_fetcher.py -v
```

Expected:
```
PASSED tests/test_fetcher.py::test_build_stream_url_format
PASSED tests/test_fetcher.py::test_build_stream_url_encodes_channel
PASSED tests/test_fetcher.py::test_probe_channel_success
PASSED tests/test_fetcher.py::test_probe_channel_404
PASSED tests/test_fetcher.py::test_probe_channel_network_error
5 passed
```

- [ ] **Step 3: Commit**

```bash
cd ~/friendly-streamprober
git add tests/test_fetcher.py
git commit -m "test: fetcher unit tests"
```

---

## Task 4: friendly-streamprober — server.py

**Files:**
- Create: `~/friendly-streamprober/streamprober/server.py`

- [ ] **Step 1: Write `streamprober/server.py`**

```python
# ~/friendly-streamprober/streamprober/server.py
import asyncio
import logging
import time

import aiohttp
from aiohttp import web

from .fetcher import probe_channel

logger = logging.getLogger(__name__)


class ProberServer:
    def __init__(self, channels: list[str], interval: int, host: str, port: int):
        self._channels = channels
        self._interval = interval
        self._host = host
        self._port = port
        self._cache: dict[str, dict] = {}
        self._started_at: float = 0.0

    def build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/stream/{channel}", self._handle_stream)
        app.router.add_get("/channels", self._handle_channels)
        app.router.add_get("/health", self._handle_health)
        return app

    async def start(self) -> None:
        self._started_at = time.monotonic()
        app = self.build_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self._host, self._port)
        await site.start()
        asyncio.create_task(self._probe_loop())
        logger.info(
            "ProberServer started on http://%s:%s/ — probing %d channel(s) every %ds",
            self._host, self._port, len(self._channels), self._interval,
        )

    async def _probe_loop(self) -> None:
        async with aiohttp.ClientSession() as session:
            while True:
                for channel in self._channels:
                    result = await probe_channel(session, channel)
                    self._cache[channel] = result
                    status = "up" if result["ok"] else "down"
                    logger.debug("probe %s -> %s", channel, status)
                await asyncio.sleep(self._interval)

    async def _handle_stream(self, request: web.Request) -> web.Response:
        channel = request.match_info["channel"]
        if channel not in self._channels:
            return web.Response(status=404, text=f"unknown channel: {channel!r}")
        result = self._cache.get(channel)
        if result is None:
            return web.Response(status=503, text="probe not yet complete, try again shortly")
        if not result["ok"]:
            return web.Response(status=502, content_type="application/json",
                                text=__import__("json").dumps(result))
        return web.json_response(result)

    async def _handle_channels(self, request: web.Request) -> web.Response:
        return web.json_response(list(self._cache.values()))

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "ok": True,
            "uptime_seconds": int(time.monotonic() - self._started_at),
            "channels": self._channels,
            "probe_interval": self._interval,
        })
```

- [ ] **Step 2: Verify import works**

```bash
cd ~/friendly-streamprober
source .venv/bin/activate
python -c "from streamprober.server import ProberServer; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
cd ~/friendly-streamprober
git add streamprober/server.py
git commit -m "feat: ProberServer — aiohttp API and background probe loop"
```

---

## Task 5: friendly-streamprober — tests/test_server.py

**Files:**
- Create: `~/friendly-streamprober/tests/test_server.py`

- [ ] **Step 1: Write the tests**

```python
# ~/friendly-streamprober/tests/test_server.py
import pytest
from aiohttp.test_utils import TestClient
from streamprober.server import ProberServer


@pytest.fixture
async def prober_client(aiohttp_client):
    server = ProberServer(channels=["mtv3", "nelonen"], interval=9999, host="127.0.0.1", port=0)
    app = server.build_app()
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_health_ok(prober_client):
    resp = await prober_client.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True
    assert "uptime_seconds" in data
    assert "mtv3" in data["channels"]


@pytest.mark.asyncio
async def test_stream_unknown_channel(prober_client):
    resp = await prober_client.get("/stream/does-not-exist")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_stream_not_probed_yet(prober_client):
    resp = await prober_client.get("/stream/mtv3")
    assert resp.status == 503


@pytest.mark.asyncio
async def test_stream_cached_ok(prober_client):
    server = prober_client.app._state.get("_server_instance")
    # Manually inject a successful cache entry
    prober_client.server.app._router  # just to access the underlying server
    # Access the ProberServer instance via the fixture closure
    # We need to inject cache directly — build a fresh server and inject
    s = ProberServer(channels=["mtv3"], interval=9999, host="127.0.0.1", port=0)
    s._cache["mtv3"] = {"ok": True, "url": "https://live-fi.tvkaista.net/mtv3/live.m3u8?src=opengraph&timestamp=2026-01-01-00-00", "channel": "mtv3", "fetched_at": "2026-01-01T00:00:00+00:00"}
    app = s.build_app()
    from aiohttp.test_utils import TestClient, TestServer
    import aiohttp
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/stream/mtv3")
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert "live-fi.tvkaista.net/mtv3" in data["url"]


@pytest.mark.asyncio
async def test_channels_empty_before_probe(prober_client):
    resp = await prober_client.get("/channels")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, list)
    assert len(data) == 0  # cache is empty before first probe
```

- [ ] **Step 2: Run tests**

```bash
cd ~/friendly-streamprober
source .venv/bin/activate
pytest tests/test_server.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 3: Commit**

```bash
cd ~/friendly-streamprober
git add tests/test_server.py
git commit -m "test: ProberServer HTTP API tests"
```

---

## Task 6: friendly-streamprober — fetch.py (CLI tool)

**Files:**
- Create: `~/friendly-streamprober/fetch.py`

- [ ] **Step 1: Write `fetch.py`**

```python
#!/usr/bin/env python3
# ~/friendly-streamprober/fetch.py
"""One-shot CLI: fetch the current stream URL for a tvkaista channel.

Usage:
  python fetch.py mtv3            # prints bare URL
  python fetch.py mtv3 --json     # prints JSON result
"""
import argparse
import asyncio
import json
import sys

from dotenv import load_dotenv

load_dotenv()

import aiohttp
from streamprober.fetcher import probe_channel


def main():
    parser = argparse.ArgumentParser(
        description="Fetch a live tvkaista.org stream URL.",
        epilog="Example: python fetch.py mtv3 | ffplay -",
    )
    parser.add_argument("channel", help="Channel slug (e.g. mtv3, nelonen, sub, tv5, jim)")
    parser.add_argument("--json", dest="json_output", action="store_true",
                        help="Print full JSON result instead of bare URL")
    args = parser.parse_args()

    async def run():
        async with aiohttp.ClientSession() as session:
            return await probe_channel(session, args.channel)

    result = asyncio.run(run())
    if not result["ok"]:
        err = result.get("error") or f"HTTP {result.get('status', '?')}"
        print(f"error: channel '{args.channel}' not available: {err}", file=sys.stderr)
        sys.exit(1)
    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(result["url"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test the CLI**

```bash
cd ~/friendly-streamprober
source .venv/bin/activate
python fetch.py mtv3
```

Expected: a URL like `https://live-fi.tvkaista.net/mtv3/live.m3u8?src=opengraph&timestamp=...`

```bash
python fetch.py mtv3 --json
```

Expected: JSON with `"ok": true`, `"url"`, `"channel"`, `"fetched_at"`.

```bash
python fetch.py yle-tv2
```

Expected: prints error to stderr, exits non-zero (yle-tv2 returns 404).

- [ ] **Step 3: Commit**

```bash
cd ~/friendly-streamprober
git add fetch.py
git commit -m "feat: fetch.py — one-shot CLI URL fetcher"
```

---

## Task 7: friendly-streamprober — serve.py (daemon entry point)

**Files:**
- Create: `~/friendly-streamprober/serve.py`

- [ ] **Step 1: Write `serve.py`**

```python
#!/usr/bin/env python3
# ~/friendly-streamprober/serve.py
"""Start the stream prober daemon.

Reads configuration from .env. Runs until killed.
"""
import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from streamprober.server import ProberServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("streamprober")


def _channels() -> list[str]:
    raw = os.getenv("PROBER_CHANNELS", "mtv3,nelonen,sub,tv5,jim,yle-teema-fem,kutonen,liv,ava")
    return [c.strip() for c in raw.split(",") if c.strip()]


async def main():
    host = os.getenv("PROBER_HOST", "127.0.0.1")
    port = int(os.getenv("PROBER_PORT", "8765"))
    interval = int(os.getenv("PROBE_INTERVAL", "30"))
    channels = _channels()

    logger.info("Starting friendly-streamprober for channels: %s", ", ".join(channels))

    server = ProberServer(channels=channels, interval=interval, host=host, port=port)
    await server.start()

    logger.info("API listening at http://%s:%d/", host, port)
    logger.info("Endpoints: /health  /channels  /stream/{channel}")

    await asyncio.Event().wait()  # run until Ctrl+C / SIGTERM


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
```

- [ ] **Step 2: Test that the daemon starts**

```bash
cd ~/friendly-streamprober
source .venv/bin/activate
cp .env.example .env
python serve.py &
sleep 2
curl -s http://127.0.0.1:8765/health | python -m json.tool
```

Expected JSON: `{"ok": true, "uptime_seconds": ..., "channels": [...], "probe_interval": 30}`

```bash
curl -s http://127.0.0.1:8765/stream/mtv3 | python -m json.tool
```

Expected: within 30 seconds of startup you'll see `{"ok": true, "url": "...", ...}`. Before first probe: `503` with text "probe not yet complete".

```bash
# Kill background server
kill %1
```

- [ ] **Step 3: Commit**

```bash
cd ~/friendly-streamprober
git add serve.py
git commit -m "feat: serve.py — daemon entry point"
```

---

## Task 8: friendly-streamprober — README.md

**Files:**
- Create: `~/friendly-streamprober/README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# friendly-streamprober

Lightweight daemon that continuously probes live TV stream URLs from tvkaista.org and serves them over a local HTTP API. Designed to run alongside the [discordmusic bot](https://github.com/yourusername/discordmusic) so the bot always has a fresh, working stream URL without manual token refreshes.

## What it does

Fetches stream URLs using the tvkaista.org public opengraph pattern:

```
https://live-fi.tvkaista.net/{channel}/live.m3u8?src=opengraph&timestamp=YYYY-MM-DD-HH-MM
```

No login or auth token needed. Probes each channel via HTTP HEAD every N seconds and caches the result. Available channels: `mtv3`, `nelonen`, `sub`, `tv5`, `jim`, `yle-teema-fem`, `kutonen`, `liv`, `ava`.

## Installation

```bash
git clone <this-repo> ~/friendly-streamprober
cd ~/friendly-streamprober
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env if needed (defaults work out of the box)
```

## Configuration

Copy `.env.example` to `.env`. Available variables:

```
PROBER_HOST=127.0.0.1      # bind address (127.0.0.1 = local only)
PROBER_PORT=8765            # HTTP API port
PROBE_INTERVAL=30           # seconds between probes
PROBER_CHANNELS=mtv3,nelonen,sub,tv5,jim,yle-teema-fem,kutonen,liv,ava
```

## Running

```bash
# Daemon (runs until Ctrl+C)
python serve.py

# One-shot URL fetch (no daemon needed)
python fetch.py mtv3
python fetch.py mtv3 --json
```

## HTTP API

| Endpoint | Response |
|---|---|
| `GET /health` | `{"ok": true, "uptime_seconds": N, "channels": [...], "probe_interval": N}` |
| `GET /channels` | Array of all cached channel results |
| `GET /stream/{channel}` | `200` with result JSON if live; `502` if channel is down; `503` if not yet probed; `404` if channel not configured |

Example:
```bash
curl http://127.0.0.1:8765/stream/mtv3
# {"ok": true, "url": "https://live-fi.tvkaista.net/mtv3/live.m3u8?src=opengraph&timestamp=...", "channel": "mtv3", "fetched_at": "..."}
```

## Discord bot integration

Set in the discordmusic `.env`:

```
TV_PROBER_URL=http://127.0.0.1:8765
```

Then use `/tv channel mtv3` in Discord to start streaming. The bot queries the prober for the current URL automatically, including on reconnect.

## Running as a service (Linux)

```bash
# /etc/systemd/system/streamprober.service
[Unit]
Description=tvkaista stream prober
After=network.target

[Service]
User=youruser
WorkingDirectory=/home/youruser/friendly-streamprober
ExecStart=/home/youruser/friendly-streamprober/.venv/bin/python serve.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable streamprober
sudo systemctl start streamprober
```

## Tests

```bash
source .venv/bin/activate
pytest -v
```
```

- [ ] **Step 2: Commit**

```bash
cd ~/friendly-streamprober
git add README.md
git commit -m "docs: README with install, config, API reference, bot integration"
```

---

## Task 9: discordmusic — tv_stream.py: add fetch_prober_url()

**Files:**
- Modify: `~/discordmusic/tv_stream.py` (add after line 169, end of file)

- [ ] **Step 1: Append `fetch_prober_url` to `tv_stream.py`**

Add the following block at the end of `~/discordmusic/tv_stream.py`:

```python

async def fetch_prober_url(channel: str, prober_base_url: str) -> str:
    """Query the local friendly-streamprober daemon for a live stream URL.

    Raises RuntimeError with a user-friendly message on any failure.
    """
    from aiohttp import ClientSession, ClientTimeout
    url = f"{prober_base_url.rstrip('/')}/stream/{channel}"
    try:
        async with ClientSession() as session:
            async with session.get(url, timeout=ClientTimeout(total=5)) as resp:
                if resp.status == 404:
                    raise RuntimeError(
                        f"Channel {channel!r} is not in the prober's channel list. "
                        "Add it to PROBER_CHANNELS in the prober's .env."
                    )
                if resp.status == 503:
                    raise RuntimeError(
                        "Stream prober is still warming up. Wait a moment and retry."
                    )
                if resp.status == 502:
                    raise RuntimeError(
                        f"Channel {channel!r} is currently unreachable according to the prober."
                    )
                if resp.status != 200:
                    raise RuntimeError(f"Prober returned unexpected HTTP {resp.status}.")
                data = await resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Prober reports channel {channel!r} is down: {data}")
        stream_url = data.get("url")
        if not stream_url:
            raise RuntimeError(f"Prober response missing 'url' field: {data}")
        return stream_url
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not contact stream prober at {prober_base_url}: {exc}") from exc
```

- [ ] **Step 2: Verify import**

```bash
cd ~/discordmusic
source venv/bin/activate 2>/dev/null || true
python -c "from tv_stream import fetch_prober_url; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
cd ~/discordmusic
git add tv_stream.py
git commit -m "feat(tv): add fetch_prober_url for local streamprober integration"
```

---

## Task 10: discordmusic — main.py: TV_PROBER_URL, state, /tv channel, restart

**Files:**
- Modify: `~/discordmusic/main.py` (4 targeted edits)

### Edit A — Add `TV_PROBER_URL` env var (near line 497–501 where other TV env vars are read)

- [ ] **Step 1: Add TV_PROBER_URL**

Find the block:
```python
TV_STREAM_URL = get_env_value("TV_STREAM_URL", required=False)
TV_MAX_RESTARTS = env_int("TV_MAX_RESTARTS", 3, 1)
TV_RESTART_WINDOW_SECONDS = env_int("TV_RESTART_WINDOW_SECONDS", 60, 10)
TV_WEBHOOK_SECRET = get_env_value("TV_WEBHOOK_SECRET", required=False)
TV_WEBHOOK_PORT = env_int("TV_WEBHOOK_PORT", 8766, 1024)
```

Add one line after `TV_WEBHOOK_PORT`:
```python
TV_PROBER_URL = get_env_value("TV_PROBER_URL", required=False)
```

### Edit B — Add `tv_prober_channel` to client state (near line 1671)

- [ ] **Step 2: Add tv_prober_channel to client init**

Find the block:
```python
        self.tv_mode_active = False
        self.tv_stream_url = None
        self.tv_notify_channel = None
        self.tv_restart_count = 0
```

Add one line after `self.tv_restart_count = 0`:
```python
        self.tv_prober_channel = None
```

### Edit C — Update `_tv_restart` to fetch fresh URL from prober (near line 2484)

- [ ] **Step 3: Update `_tv_restart`**

Find:
```python
    logger.info(f"Restarting TV stream (attempt {client.tv_restart_count}/{TV_MAX_RESTARTS})")
    await _start_tv_stream(channel, client.tv_stream_url)
```

Replace with:
```python
    logger.info(f"Restarting TV stream (attempt {client.tv_restart_count}/{TV_MAX_RESTARTS})")
    url = client.tv_stream_url
    if TV_PROBER_URL and client.tv_prober_channel:
        try:
            url = await _tv_module.fetch_prober_url(client.tv_prober_channel, TV_PROBER_URL)
            client.tv_stream_url = url
            logger.info(f"TV restart: fetched fresh URL from prober for {client.tv_prober_channel!r}")
        except RuntimeError as exc:
            logger.warning(f"TV restart: prober fetch failed ({exc}), reusing cached URL")
    await _start_tv_stream(channel, url)
```

### Edit D — Add `/tv channel` command and update `tv_stop_cmd` (near line 10063)

- [ ] **Step 4: Update tv_stop_cmd to clear prober channel**

Find inside `tv_stop_cmd`:
```python
        client.tv_mode_active = False
        client.tv_stream_url = None
        client.tv_notify_channel = None
```

Add one line:
```python
        client.tv_mode_active = False
        client.tv_stream_url = None
        client.tv_notify_channel = None
        client.tv_prober_channel = None
```

- [ ] **Step 5: Add `/tv channel` command**

Find (near the end of the `if _tv_module is not None:` block, just before `client.tree.add_command(tv_group)`):
```python
    client.tree.add_command(tv_group)
```

Insert before it:

```python
    @app_commands.describe(channel="Channel slug: mtv3, nelonen, sub, tv5, jim, yle-teema-fem, kutonen, liv, ava")
    @tv_group.command(name="channel", description="Start a tvkaista.org channel via the local stream prober.")
    async def tv_channel_cmd(ctx, channel: str):
        record_command(ctx)
        if not is_user_admin(ctx.user):
            await ctx.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        if not TV_PROBER_URL:
            await ctx.response.send_message(
                "No stream prober configured. Set `TV_PROBER_URL` in `.env` (e.g. `http://127.0.0.1:8765`).",
                ephemeral=True,
            )
            return
        if not ctx.user.voice or not ctx.user.voice.channel:
            await ctx.response.send_message("You must be in a voice channel to start the TV stream.", ephemeral=True)
            return
        if client.currently_playing and not client.tv_mode_active:
            await ctx.response.send_message(
                "Music is currently playing. Use `/stop` to clear playback first.", ephemeral=True
            )
            return
        await ctx.response.defer()
        try:
            stream_url = await _tv_module.fetch_prober_url(channel, TV_PROBER_URL)
        except RuntimeError as exc:
            await ctx.followup.send(f"Stream prober error: {exc}", ephemeral=True)
            return
        target_channel = ctx.user.voice.channel
        voice = active_voice_client(ctx.guild)
        try:
            if voice and voice.is_connected():
                if getattr(voice, "channel", None) != target_channel:
                    await voice.move_to(target_channel)
                    apply_channel_volume_default(target_channel, "tv channel move")
            else:
                voice = await target_channel.connect()
                client.current_voice_channel = voice
                apply_channel_volume_default(target_channel, "tv channel join")
        except Exception as exc:
            logger.error(f"TV channel: voice join error: {exc}")
            await ctx.followup.send("Could not join the voice channel.", ephemeral=True)
            return
        if client.tv_mode_active and voice.is_playing():
            client.tv_mode_active = False
            voice.stop()
            await asyncio.sleep(0.1)
        client.tv_restart_count = 0
        client.tv_restart_window_start = None
        client.tv_prober_channel = channel
        await _start_tv_stream(ctx.channel, stream_url)
        await ctx.followup.send(f"TV channel **{channel}** started in **{target_channel.name}**.")

```

- [ ] **Step 6: Verify Python syntax**

```bash
cd ~/discordmusic
python -m py_compile main.py && echo "syntax ok"
```

Expected: `syntax ok`

- [ ] **Step 7: Commit**

```bash
cd ~/discordmusic
git add main.py
git commit -m "feat(tv): TV_PROBER_URL env var, /tv channel command, auto-refresh URL on restart"
```

---

## Task 11: discordmusic — Update .env example and docs

**Files:**
- Modify: `~/discordmusic/.env`
- Modify: `~/discordmusic/docs/COMMANDS.md`

- [ ] **Step 1: Add TV_PROBER_URL comment to `.env`**

Find the TV section in `.env`:
```
# TV_WEBHOOK_SECRET=pick-a-strong-random-string
# TV_WEBHOOK_PORT=8766
# TV_MAX_RESTARTS=3
# TV_RESTART_WINDOW_SECONDS=60
```

Add after it:
```
# TV_PROBER_URL=http://127.0.0.1:8765
```

- [ ] **Step 2: Update `docs/COMMANDS.md` TV section**

Find the `## tv` section in `docs/COMMANDS.md`:
```markdown
## tv

requires `TV_ENABLED=true` in `.env`. admin-only.

| command | purpose |
| --- | --- |
| `/tv start [url]` | start a live stream in your voice channel. supports HLS (`.m3u8`), generic HTTP audio/video streams, RTMP, and YouTube livestreams. defaults to `TV_STREAM_URL` in `.env` if no url is given. |
| `/tv stop` | stop the live stream and disconnect from voice. |
| `/tv update <url>` | swap in a new stream URL while the stream is live — no reconnect needed. useful for refreshing an expired tvkaista auth token. |
```

Replace it with:
```markdown
## tv

requires `TV_ENABLED=true` in `.env`. admin-only. the tv module is an optional extra — it is not required for normal music playback.

| command | purpose |
| --- | --- |
| `/tv start [url]` | start a live stream in your voice channel. supports HLS (`.m3u8`), generic HTTP audio/video streams, RTMP, and YouTube livestreams. defaults to `TV_STREAM_URL` in `.env` if no url is given. |
| `/tv channel <name>` | start a tvkaista.org channel by slug (e.g. `mtv3`, `nelonen`, `sub`, `tv5`, `jim`, `yle-teema-fem`, `kutonen`, `liv`, `ava`) using the local stream prober. requires `TV_PROBER_URL` in `.env`. the bot fetches a fresh URL automatically on reconnect. |
| `/tv stop` | stop the live stream and disconnect from voice. |
| `/tv update <url>` | swap in a new stream URL while the stream is live — no reconnect needed. useful for refreshing an expired tvkaista auth token. |

**stream prober integration:** `/tv channel` requires the `friendly-streamprober` daemon running locally. set `TV_PROBER_URL=http://127.0.0.1:8765` in `.env`. the prober continuously probes tvkaista.org channels and serves current URLs at `GET /stream/{channel}`. when the stream drops, the bot requests a fresh URL from the prober before reconnecting instead of reusing a potentially stale URL.
```

- [ ] **Step 3: Commit**

```bash
cd ~/discordmusic
git add .env docs/COMMANDS.md
git commit -m "docs(tv): add TV_PROBER_URL to .env example and /tv channel to COMMANDS.md"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] friendly-streamprober daemon — Task 7
- [x] HTTP API (GET /stream, /channels, /health) — Task 4
- [x] CLI fetch tool with --json flag — Task 6
- [x] .env for all config, no secrets in code — Tasks 1, 5, 8
- [x] README with example .env — Task 8
- [x] .gitignore — Task 1
- [x] discordmusic: /tv channel command — Task 10
- [x] discordmusic: auto-refresh URL on reconnect — Task 10
- [x] discordmusic: docs updated — Task 11
- [x] Tests for fetcher and server — Tasks 3, 5

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:** `probe_channel` returns `dict` consistently; `fetch_prober_url` returns `str` consistently. `ProberServer.build_app()` → `web.Application` matches usage in `start()` and tests. `TV_PROBER_URL` referenced in edits A, C, D consistently.
