"""HTTP surface: REAPER proxy, live audio stream, output device, render, and the UI.

Every path is relative to wherever the app is mounted, so the same process
works at `/` locally and at `/ext/reaper/` behind `tailscale serve --set-path`.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import DEVICE_KEYS, Config
from .stream import HLS_PLAYLIST, HlsSession, OggBroadcast

log = logging.getLogger("reaper_remote")

PROXY_PREFIX = "/reaper/_/"
PROXY_TIMEOUT_S = 5.0
RENDER_POLL_S = 0.5
EXTSTATE_SECTION = "reaper_remote"


class DeviceRequest(BaseModel):
    device: str


async def _run(*args: str) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as e:
        raise HTTPException(500, f"{args[0]} not found") from e
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode().strip(), err.decode().strip()


def create_app(cfg: Config, reaper_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """Build the app. `reaper_transport` replaces the network path to REAPER (tests only)."""
    client = httpx.AsyncClient(
        base_url=cfg.reaper_url, timeout=PROXY_TIMEOUT_S, transport=reaper_transport
    )

    ogg = OggBroadcast(cfg)
    hls = HlsSession(cfg)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await hls.close()
        await client.aclose()

    app = FastAPI(
        title="reaper-remote", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )

    @app.exception_handler(HTTPException)
    async def log_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        # The access log shows only the status; keep the reason next to it.
        log.warning(
            "%s %s -> %s: %s", request.method, request.url.path, exc.status_code, exc.detail
        )
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    render_lock = asyncio.Lock()

    async def reaper(commands: str, timeout: float = PROXY_TIMEOUT_S) -> str:
        try:
            r = await client.get(f"/_/{commands}", timeout=timeout)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"REAPER web interface unreachable: {e}") from e
        if r.status_code != 200:
            raise HTTPException(502, f"REAPER web interface answered {r.status_code}")
        return r.text

    # -- REAPER web API, passed through byte-for-byte ------------------------
    @app.get(PROXY_PREFIX + "{commands:path}")
    async def proxy(request: Request) -> Response:
        # Use the raw path so `;`, `%2F` and friends reach REAPER exactly as sent.
        raw = request.scope["raw_path"].decode("latin-1")
        commands = raw[raw.index(PROXY_PREFIX) + len(PROXY_PREFIX) :]
        # Front proxies (tailscale serve among them) may percent-encode the
        # `;` separator, and REAPER only splits on a literal `;`.
        commands = commands.replace("%3B", ";").replace("%3b", ";")
        body = await reaper(commands)
        return Response(body, media_type="text/plain", headers={"Cache-Control": "no-store"})

    # -- live audio -----------------------------------------------------------
    @app.get("/stream.ogg")
    async def stream_ogg() -> StreamingResponse:
        # One shared encoder for every listener; it stops with the last one.
        if shutil.which(cfg.stream.ffmpeg) is None:
            raise HTTPException(500, f"ffmpeg not found: {cfg.stream.ffmpeg}")
        return StreamingResponse(
            ogg.listen(), media_type="audio/ogg", headers={"Cache-Control": "no-store"}
        )

    @app.get("/hls/" + HLS_PLAYLIST)
    async def hls_playlist() -> FileResponse:
        if shutil.which(cfg.stream.ffmpeg) is None:
            raise HTTPException(500, f"ffmpeg not found: {cfg.stream.ffmpeg}")
        path = await hls.playlist()
        if path is None:
            raise HTTPException(503, "the HLS encoder did not produce a playlist")
        return FileResponse(
            path,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/hls/{name}")
    async def hls_segment(name: str) -> FileResponse:
        path = hls.segment(name)
        if path is None:
            raise HTTPException(404)
        return FileResponse(path, media_type="video/mp2t")

    # -- system output device -------------------------------------------------
    async def switch_tool(*args: str) -> str:
        tool = cfg.devices.switch_audio_source
        code, out, err = await _run(tool, *args)
        if code != 0:
            raise HTTPException(500, f"{tool} failed: {err}")
        return out

    async def current_device() -> dict:
        out = await switch_tool("-c", "-t", "output")
        present = set((await switch_tool("-a", "-t", "output")).splitlines())
        key = next((k for k, v in cfg.devices.names.items() if v == out), None)
        return {
            "current": key,
            "name": out,
            "options": list(cfg.devices.names),
            # A device can come and go (e.g. a headphone jack), so report what exists now.
            "available": [k for k, v in cfg.devices.names.items() if v in present],
        }

    @app.get("/device")
    async def get_device() -> dict:
        return await current_device()

    @app.post("/device")
    async def set_device(req: DeviceRequest) -> dict:
        if req.device not in DEVICE_KEYS:
            raise HTTPException(400, f"device must be one of {list(DEVICE_KEYS)}")
        name = cfg.devices.names.get(req.device)
        if name is None:
            raise HTTPException(404, f"devices.{req.device} is not configured")
        if req.device not in (await current_device())["available"]:
            raise HTTPException(409, f"{name} is not connected")
        await switch_tool("-t", "output", "-s", name)
        return await current_device()

    # -- render ---------------------------------------------------------------
    @app.get("/render")
    async def render_enabled() -> dict:
        return {"enabled": cfg.render is not None}

    @app.post("/render")
    async def render() -> JSONResponse:
        rc = cfg.render
        if rc is None:
            raise HTTPException(404, "render is not configured")
        if render_lock.locked():
            raise HTTPException(409, "a render is already running")
        async with render_lock:
            rc.dir.mkdir(parents=True, exist_ok=True)
            before = {p.name for p in rc.dir.iterdir()}
            started = time.time()
            # The ReaScript reads its output directory from this ExtState.
            await reaper(
                f"SET/EXTSTATE/{EXTSTATE_SECTION}/render_dir/{quote(str(rc.dir), safe='')}"
                f";{rc.action}",
                # REAPER may hold the reply until the render finishes.
                timeout=rc.timeout_s,
            )
            path = await _wait_for_render(rc.dir, before, started, rc.timeout_s)
        return JSONResponse({"name": path.name, "url": f"renders/{quote(path.name)}"})

    @app.get("/renders/{name}")
    async def rendered(name: str) -> FileResponse:
        rc = cfg.render
        if rc is None:
            raise HTTPException(404)
        path = (rc.dir / name).resolve()
        if path.parent != rc.dir.resolve() or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    # -- UI (mounted last so the routes above win) ----------------------------
    app.mount("/", StaticFiles(directory=cfg.web_dir, html=True), name="web")
    return app


async def _wait_for_render(dir: Path, before: set[str], started: float, timeout: float) -> Path:
    """Wait for a new file in `dir` and return it once its size stops changing."""
    deadline = started + timeout
    last: tuple[Path, int] | None = None
    while time.time() < deadline:
        fresh = [
            p
            for p in dir.iterdir()
            if p.is_file() and p.name not in before and not p.name.startswith(".")
        ]
        if fresh:
            newest = max(fresh, key=lambda p: p.stat().st_mtime)
            size = newest.stat().st_size
            if last is not None and last[0] == newest and last[1] == size and size > 0:
                return newest
            last = (newest, size)
        await asyncio.sleep(RENDER_POLL_S)
    raise HTTPException(504, f"no rendered file appeared in {timeout:.0f}s")
