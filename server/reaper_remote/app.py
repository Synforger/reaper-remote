"""HTTP surface: REAPER proxy, output device, render, timeline, loop, project
tabs, the UI, and a thin same-origin relay to mediamtx for live audio (WHEP and
LL-HLS).

Every path is relative to wherever the app is mounted, so the same process
works at `/` locally and at `/ext/reaper/` behind `tailscale serve --set-path`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.types import Scope

from . import projects as projects_reply
from . import timeline as timeline_reply
from .config import DEVICE_KEYS, Config

log = logging.getLogger("reaper_remote")

PROXY_PREFIX = "/reaper/_/"
PROXY_TIMEOUT_S = 5.0
# LL-HLS playlist requests block until the next part exists; allow for that.
MEDIA_TIMEOUT_S = 30.0
# Response headers worth passing back from mediamtx.
MEDIA_HEADERS = ("content-type", "cache-control", "etag", "accept-patch", "link")
RENDER_POLL_S = 0.5
EXTSTATE_SECTION = "reaper_remote"


class DeviceRequest(BaseModel):
    device: str


class LoopRequest(BaseModel):
    start: float
    end: float


class ProjectSelectRequest(BaseModel):
    index: int = Field(ge=0)
    name: str = Field(max_length=255)


class ListenStats(BaseModel):
    """One report from a listening page: an interval of WebRTC receive counters,
    or an event (a fall back to LL-HLS, a stall on it)."""

    mode: Literal["webrtc", "llhls"]
    event: Literal["fallback", "waiting"] | None = None
    reason: str | None = Field(default=None, max_length=200)
    seconds: float | None = None
    received: int | None = None
    lost: int | None = None
    loss_pct: float | None = None
    discarded: int | None = None
    jitter_ms: float | None = None
    concealed_pct: float | None = None
    concealment_events: int | None = None
    buffer_ms: float | None = None
    rtt_ms: float | None = None


def ui_fingerprint(web_dir: Path) -> str:
    """A short hash of the UI files, so an open page can tell the UI changed."""
    digest = hashlib.sha256()
    for path in sorted(p for p in web_dir.rglob("*") if p.is_file()):
        digest.update(path.relative_to(web_dir).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


class RevalidatedStaticFiles(StaticFiles):
    """Static files that browsers must revalidate, so a reload picks up a new UI."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


async def _run(*args: str) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as e:
        raise HTTPException(500, f"{args[0]} not found") from e
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode().strip(), err.decode().strip()


def create_app(
    cfg: Config,
    reaper_transport: httpx.AsyncBaseTransport | None = None,
    media_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build the app. The transports replace REAPER and mediamtx (tests only)."""
    client = httpx.AsyncClient(
        base_url=cfg.reaper_url, timeout=PROXY_TIMEOUT_S, transport=reaper_transport
    )
    media = httpx.AsyncClient(timeout=MEDIA_TIMEOUT_S, transport=media_transport)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await media.aclose()
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

    # -- live audio: relayed to mediamtx ----------------------------------------
    # mediamtx listens on loopback only; these routes put WHEP signalling and
    # LL-HLS under this app's own path, so a single mount (and a single origin)
    # serves the page and its audio. The media itself flows over WebRTC's own
    # UDP port, not through here.
    whep_url = f"{cfg.media.webrtc}/{cfg.media.path}/whep"
    hls_url = f"{cfg.media.hls}/{cfg.media.path}"

    async def relay(method: str, url: str, request: Request) -> httpx.Response:
        headers = {
            k: v for k, v in request.headers.items() if k.lower() in ("content-type", "if-match")
        }
        try:
            return await media.request(
                method,
                url,
                params=request.query_params,
                headers=headers,
                content=await request.body(),
            )
        except httpx.HTTPError as e:
            raise HTTPException(502, f"mediamtx unreachable: {e}") from e

    def passthrough(r: httpx.Response, extra: dict[str, str] | None = None) -> Response:
        headers = {k: v for k, v in r.headers.items() if k.lower() in MEDIA_HEADERS}
        headers.update(extra or {})
        return Response(r.content, status_code=r.status_code, headers=headers)

    @app.post("/whep")
    async def whep_offer(request: Request) -> Response:
        r = await relay("POST", whep_url, request)
        extra = {}
        if "location" in r.headers:
            # mediamtx answers `/<path>/whep/<session>`; hand back a URL relative
            # to this app so the page can PATCH / DELETE the session through us.
            session = r.headers["location"].split("?")[0].rsplit("/", 1)[-1]
            extra["Location"] = f"whep/{session}"
        return passthrough(r, extra)

    @app.api_route("/whep/{session}", methods=["PATCH", "DELETE"])
    async def whep_session(session: str, request: Request) -> Response:
        return passthrough(await relay(request.method, f"{whep_url}/{quote(session)}", request))

    @app.get("/llhls/{name:path}")
    async def llhls(name: str, request: Request) -> Response:
        r = await relay("GET", f"{hls_url}/{name}", request)
        extra = {}
        if "location" in r.headers:
            # mediamtx first redirects the playlist to `/<path>/index.m3u8?cookieCheck=1`.
            # No cookies are relayed, so it then carries the session in the query
            # string of every URL it hands out; only the redirect needs rewriting,
            # to stay under llhls/.
            prefix = f"/{cfg.media.path}/"
            location = r.headers["location"]
            extra["Location"] = location.removeprefix(prefix)
        return passthrough(r, extra)

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

    # -- timeline ---------------------------------------------------------------
    @app.get("/timeline")
    async def timeline() -> JSONResponse:
        tc = cfg.timeline
        if tc is None:
            return JSONResponse({"enabled": False}, headers={"Cache-Control": "no-store"})
        key = f"{EXTSTATE_SECTION}/{timeline_reply.EXTSTATE_KEY}"
        # Clear first, so a script that did not run reads as empty, not as the last result.
        reply = await reaper(f"SET/EXTSTATE/{key}/;{tc.action};GET/EXTSTATE/{key};MARKER;REGION")
        try:
            data = timeline_reply.parse(reply, EXTSTATE_SECTION)
        except timeline_reply.TimelineError as e:
            raise HTTPException(502, str(e)) from e
        return JSONResponse({"enabled": True, **data}, headers={"Cache-Control": "no-store"})

    # -- loop -------------------------------------------------------------------
    @app.get("/loop")
    async def loop_enabled() -> dict:
        return {"enabled": cfg.loop is not None}

    @app.post("/loop")
    async def set_loop(req: LoopRequest) -> dict:
        lc = cfg.loop
        if lc is None:
            raise HTTPException(404, "loop is not configured")
        if not (0 <= req.start < req.end):
            raise HTTPException(400, "loop needs 0 <= start < end")
        # The ReaScript reads the range from this ExtState; repeat goes on with it.
        value = quote(f"{req.start:.6f},{req.end:.6f}", safe="")
        await reaper(f"SET/EXTSTATE/{EXTSTATE_SECTION}/loop/{value};{lc.action};SET/REPEAT/1")
        return {"start": req.start, "end": req.end}

    # -- project tabs -------------------------------------------------------------
    async def list_projects(pc) -> list[dict]:
        key = f"{EXTSTATE_SECTION}/{projects_reply.LIST_KEY}"
        # Cleared first, so a script that did not run reads as empty.
        reply = await reaper(f"SET/EXTSTATE/{key}/;{pc.list_action};GET/EXTSTATE/{key}")
        try:
            return projects_reply.parse_list(reply, EXTSTATE_SECTION)
        except projects_reply.ProjectsError as e:
            raise HTTPException(502, str(e)) from e

    @app.get("/projects")
    async def projects() -> JSONResponse:
        pc = cfg.projects
        if pc is None:
            return JSONResponse({"enabled": False}, headers={"Cache-Control": "no-store"})
        tabs = await list_projects(pc)
        return JSONResponse({"enabled": True, "tabs": tabs}, headers={"Cache-Control": "no-store"})

    @app.post("/projects/select")
    async def select_project(req: ProjectSelectRequest) -> dict:
        pc = cfg.projects
        if pc is None:
            raise HTTPException(404, "projects is not configured")
        want = quote(f"{req.index}/{req.name}", safe="")
        result = f"{EXTSTATE_SECTION}/{projects_reply.RESULT_KEY}"
        reply = await reaper(
            f"SET/EXTSTATE/{EXTSTATE_SECTION}/{projects_reply.SELECT_KEY}/{want}"
            f";SET/EXTSTATE/{result}/;{pc.select_action};GET/EXTSTATE/{result}"
        )
        try:
            refused = projects_reply.parse_select(reply, EXTSTATE_SECTION)
        except projects_reply.ProjectsError as e:
            raise HTTPException(502, str(e)) from e
        if refused:
            # The tabs changed since the page listed them; it lists them again.
            raise HTTPException(409, refused)
        return {"tabs": await list_projects(pc)}

    # -- listening stats ----------------------------------------------------------
    @app.post("/listen-stats", status_code=204)
    async def listen_stats(req: ListenStats, request: Request) -> Response:
        # An interval in which audio went missing is a GAP, logged as a warning,
        # so dropouts can be found without knowing when they were heard.
        client = request.headers.get("x-forwarded-for") or (
            request.client.host if request.client else "?"
        )
        fields = req.model_dump(exclude_none=True, exclude={"mode", "event", "reason"})
        parts = [f"mode={req.mode}"]
        if req.event:
            parts.append(f"event={req.event}")
        parts += [f"{k}={v}" for k, v in fields.items()]
        if req.reason:
            parts.append(f"reason={req.reason!r}")
        gap = (
            any((v or 0) > 0 for v in (req.lost, req.discarded, req.concealment_events))
            or req.event is not None
        )
        if gap:
            log.warning("listen GAP %s from %s", " ".join(parts), client)
        else:
            log.info("listen %s from %s", " ".join(parts), client)
        return Response(status_code=204)

    # -- UI (mounted last so the routes above win) ----------------------------
    # Fixed at start-up: a restart with new UI files changes it, and open pages
    # that see the change reload themselves.
    ui = ui_fingerprint(cfg.web_dir)

    @app.get("/version")
    async def version() -> JSONResponse:
        return JSONResponse({"ui": ui}, headers={"Cache-Control": "no-store"})

    app.mount("/", RevalidatedStaticFiles(directory=cfg.web_dir, html=True), name="web")
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
