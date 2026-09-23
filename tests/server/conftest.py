from __future__ import annotations

import socket
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn

from reaper_remote.app import create_app
from reaper_remote.config import parse


def write_tool(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class FakeReaper:
    """Stands in for REAPER's web interface: records requests, answers canned text."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.reply = "TRANSPORT\t0\t0.000000\t0\t0:00.000\t1.1.00\n"
        self.on_request = None
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        raw = request.url.raw_path.decode()
        self.requests.append(raw)
        if self.on_request:
            self.on_request(raw)
        return httpx.Response(self.status, text=self.reply)


class FakeMedia:
    """Stands in for mediamtx's WebRTC and HLS HTTP servers."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/reaper/whep":
            return httpx.Response(
                201,
                text="v=0 answer",
                headers={
                    "Content-Type": "application/sdp",
                    "Location": "/reaper/whep/3f2a-session",
                    "ETag": "*",
                    "Set-Cookie": "leak=1",
                },
            )
        if path.startswith("/reaper/whep/"):
            return httpx.Response(200)
        if path == "/reaper/index.m3u8":
            if request.url.params.get("cookieCheck") != "1":
                return httpx.Response(302, headers={"Location": "/reaper/index.m3u8?cookieCheck=1"})
            return httpx.Response(
                200,
                text="#EXTM3U\nstream.m3u8?session=abc\n",
                headers={"Content-Type": "application/vnd.apple.mpegurl"},
            )
        return httpx.Response(404)


class FakeDevice:
    """Stands in for the CoreAudio input: a thread delivering PCM blocks."""

    RATE = 48000
    BLOCK = b"\x01\x02\x03\x04" * 256

    def __init__(self) -> None:
        self.opened = 0
        self.running = 0
        self.missing = False

    def open(self, device: str, on_block):
        if self.missing:
            raise LookupError(f"no input device named {device!r} with 2 channels")
        self.opened += 1
        dev = self

        class Stream:
            def __init__(self) -> None:
                self.stop_event = threading.Event()

            def start(self) -> None:
                dev.running += 1

                def run() -> None:
                    while not self.stop_event.wait(0.02):
                        on_block(FakeDevice.BLOCK)

                threading.Thread(target=run, daemon=True).start()

            def stop(self) -> None:
                self.stop_event.set()
                dev.running -= 1

            def close(self) -> None:
                pass

        return Stream(), FakeDevice.RATE


@pytest.fixture
def device() -> FakeDevice:
    return FakeDevice()


@pytest.fixture
def media() -> FakeMedia:
    return FakeMedia()


@pytest.fixture
def reaper() -> FakeReaper:
    return FakeReaper()


@pytest.fixture
def tools(tmp_path: Path) -> dict[str, Path]:
    state = tmp_path / "current-output"
    state.write_text("Headphones Out")
    present = tmp_path / "present-outputs"
    present.write_text("Headphones Out\nMulti-Output\nBroken Device\nSpeakers\n")
    switch = write_tool(
        tmp_path / "SwitchAudioSource",
        f"""
state="{state}"
if [ "$1" = "-c" ]; then cat "$state"; exit 0; fi
if [ "$1" = "-a" ]; then cat "{present}"; exit 0; fi
if [ "$3" = "-s" ]; then
  case "$4" in
    "Broken Device") echo "no such device" >&2; exit 1 ;;
  esac
  printf '%s' "$4" > "$state"; exit 0
fi
exit 2
""",
    )
    pcmfile = tmp_path / "ffmpeg.stdin"
    argsfile = tmp_path / "ffmpeg.args"
    # Stands in for the publishing ffmpeg: records its arguments, then copies
    # 8 KiB of PCM from stdin and exits (as ffmpeg does when its input ends).
    ffmpeg = write_tool(
        tmp_path / "ffmpeg",
        f"""
printf '%s\\n' "$@" > "{argsfile}"
head -c 8192 > "{pcmfile}"
""",
    )
    return {
        "switch": switch,
        "state": state,
        "present": present,
        "ffmpeg": ffmpeg,
        "pcmfile": pcmfile,
        "argsfile": argsfile,
        "render_dir": tmp_path / "renders",
    }


@pytest.fixture
def raw_config(tools: dict[str, Path]) -> dict:
    return {
        "reaper_url": "http://reaper.test:8080",
        "stream": {"input": "Capture Device", "ffmpeg": str(tools["ffmpeg"])},
        "devices": {
            "headphones": "Headphones Out",
            "multi": "Multi-Output",
            "blackhole": "Broken Device",
            "switch_audio_source": str(tools["switch"]),
        },
        "render": {"action": "_RS1234", "dir": str(tools["render_dir"]), "timeout_s": 3},
    }


@contextmanager
def serve(raw: dict, reaper: FakeReaper, media: FakeMedia) -> Iterator[httpx.Client]:
    """Run the app under a real uvicorn server on a free loopback port.

    A real server (not TestClient) is used throughout: only it delivers the
    listener's disconnect to the app, which the stream endpoint depends on.
    """
    app = create_app(
        parse(raw),
        reaper_transport=httpx.MockTransport(reaper.handler),
        media_transport=httpx.MockTransport(media.handler),
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    assert server.started, "uvicorn did not start"
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as http:
            yield http
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture
def make_client(reaper: FakeReaper, media: FakeMedia):
    def make(raw: dict):
        return serve(raw, reaper, media)

    return make


@pytest.fixture
def client(make_client, raw_config) -> Iterator[httpx.Client]:
    with make_client(raw_config) as c:
        yield c
