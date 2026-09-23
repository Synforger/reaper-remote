"""Live audio: one shared encoder per format, running only while someone listens.

- `OggBroadcast` runs one ffmpeg producing Ogg/Opus and fans its pages out to
  every connected listener. A listener that joins late first receives the
  stream's header pages (OpusHead / OpusTags), then pages from the current
  position — the same thing an Icecast server does.
- `HlsSession` runs one ffmpeg writing an HLS playlist of AAC segments into a
  temporary directory. Players poll the playlist while they play; when nobody
  has asked for it for `idle_s` seconds the encoder stops.

The UI uses HLS wherever the browser plays it natively (iOS Safari plays live
Ogg/Opus at the wrong speed) and Ogg everywhere else.
"""

from __future__ import annotations

import asyncio
import shutil
import struct
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path

from .config import Config

OGG_READ_BYTES = 4096
# Pages buffered per listener before it counts as stalled and is dropped.
LISTENER_QUEUE_PAGES = 256

HLS_PLAYLIST = "stream.m3u8"
HLS_SEGMENT_S = 2
HLS_LIST_SIZE = 5
HLS_IDLE_S = 20.0
HLS_FIRST_PLAYLIST_TIMEOUT_S = 15.0
HLS_POLL_S = 0.2


def capture_args(cfg: Config) -> list[str]:
    s = cfg.stream
    return [
        s.ffmpeg,
        "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "avfoundation", "-i", f":{s.input}",
        "-ac", "2",
    ]  # fmt: skip


def ogg_args(cfg: Config) -> list[str]:
    return [
        *capture_args(cfg),
        "-c:a", "libopus", "-b:a", cfg.stream.bitrate, "-application", "audio",
        "-f", "ogg", "-flush_packets", "1",
        "pipe:1",
    ]  # fmt: skip


def hls_args(cfg: Config, out_dir: Path) -> list[str]:
    return [
        *capture_args(cfg),
        "-c:a", "aac", "-b:a", cfg.stream.bitrate,
        "-f", "hls",
        "-hls_time", str(HLS_SEGMENT_S),
        "-hls_list_size", str(HLS_LIST_SIZE),
        "-hls_flags", "delete_segments+omit_endlist",
        "-hls_segment_filename", str(out_dir / "seg%05d.ts"),
        str(out_dir / HLS_PLAYLIST),
    ]  # fmt: skip


async def _kill(proc: asyncio.subprocess.Process | None) -> None:
    if proc is None:
        return
    if proc.returncode is None:
        proc.kill()
    await proc.wait()


# -- Ogg ------------------------------------------------------------------------


def split_pages(buf: bytearray) -> list[bytes]:
    """Remove every complete Ogg page from the front of `buf` and return them."""
    pages: list[bytes] = []
    while True:
        start = buf.find(b"OggS")
        if start < 0:
            # Keep a possible partial capture pattern at the tail.
            del buf[: max(0, len(buf) - 3)]
            return pages
        if start:
            del buf[:start]
        if len(buf) < 27:
            return pages
        nseg = buf[26]
        if len(buf) < 27 + nseg:
            return pages
        total = 27 + nseg + sum(buf[27 : 27 + nseg])
        if len(buf) < total:
            return pages
        pages.append(bytes(buf[:total]))
        del buf[:total]


def granule_position(page: bytes) -> int:
    return struct.unpack_from("<q", page, 6)[0]


class OggBroadcast:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.proc: asyncio.subprocess.Process | None = None
        self.reader: asyncio.Task | None = None
        self.header = b""
        self.header_done = False
        self.listeners: dict[asyncio.Queue, bool] = {}  # queue -> has received the header
        self.lock = asyncio.Lock()

    async def listen(self) -> AsyncIterator[bytes]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=LISTENER_QUEUE_PAGES)
        async with self.lock:
            if self.proc is None:
                await self._start()
            self.listeners[queue] = False
            if self.header_done:
                self._send_header(queue)
        try:
            while (page := await queue.get()) is not None:
                yield page
        finally:
            async with self.lock:
                self.listeners.pop(queue, None)
                if not self.listeners:
                    await self._stop()

    def _send_header(self, queue: asyncio.Queue) -> None:
        queue.put_nowait(self.header)
        self.listeners[queue] = True

    async def _start(self) -> None:
        self.header, self.header_done = b"", False
        self.proc = await asyncio.create_subprocess_exec(
            *ogg_args(self.cfg),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL,
        )
        self.reader = asyncio.create_task(self._read(self.proc))

    async def _stop(self) -> None:
        proc, reader = self.proc, self.reader
        self.proc = self.reader = None
        await _kill(proc)
        if reader is not None:
            reader.cancel()

    async def _read(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        buf = bytearray()
        while chunk := await proc.stdout.read(OGG_READ_BYTES):
            buf += chunk
            for page in split_pages(buf):
                self._dispatch(page)
        # The encoder died: end every listener's stream so players reconnect.
        for queue in list(self.listeners):
            self._end(queue)

    def _dispatch(self, page: bytes) -> None:
        if not self.header_done:
            # Header pages (OpusHead, OpusTags) carry granule position 0.
            if granule_position(page) == 0:
                self.header += page
                return
            self.header_done = True
            for queue, got in list(self.listeners.items()):
                if not got:
                    self._send_header(queue)
        for queue, got in list(self.listeners.items()):
            if not got:
                continue
            try:
                queue.put_nowait(page)
            except asyncio.QueueFull:
                self._end(queue)

    def _end(self, queue: asyncio.Queue) -> None:
        # Detach first so no further page is queued behind the end marker.
        self.listeners.pop(queue, None)
        # Make room for the end marker even when the queue is full.
        while queue.full():
            queue.get_nowait()
        queue.put_nowait(None)


# -- HLS ------------------------------------------------------------------------


class HlsSession:
    def __init__(self, cfg: Config, idle_s: float | None = None) -> None:
        self.cfg = cfg
        self.idle_s = HLS_IDLE_S if idle_s is None else idle_s
        self.proc: asyncio.subprocess.Process | None = None
        self.dir: Path | None = None
        self.last_request = 0.0
        self.watchdog: asyncio.Task | None = None
        self.lock = asyncio.Lock()

    async def playlist(self) -> Path | None:
        """Start the encoder if needed and return the playlist once it exists."""
        self.last_request = time.monotonic()
        async with self.lock:
            if self.proc is None or self.proc.returncode is not None:
                await self._start()
            assert self.dir is not None
            path = self.dir / HLS_PLAYLIST
        deadline = time.monotonic() + HLS_FIRST_PLAYLIST_TIMEOUT_S
        while not path.is_file():
            if time.monotonic() > deadline or self.proc is None:
                return None
            await asyncio.sleep(HLS_POLL_S)
        return path

    def segment(self, name: str) -> Path | None:
        if self.dir is None or "/" in name or not name.endswith(".ts"):
            return None
        path = self.dir / name
        return path if path.is_file() else None

    async def _start(self) -> None:
        await self._stop()
        self.dir = Path(tempfile.mkdtemp(prefix="reaper-remote-hls-"))
        self.proc = await asyncio.create_subprocess_exec(
            *hls_args(self.cfg, self.dir),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL,
        )
        if self.watchdog is None or self.watchdog.done():
            self.watchdog = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(min(1.0, self.idle_s / 4))
            if time.monotonic() - self.last_request > self.idle_s:
                async with self.lock:
                    await self._stop()
                return

    async def _stop(self) -> None:
        proc, out_dir = self.proc, self.dir
        self.proc = self.dir = None
        await _kill(proc)
        if out_dir is not None:
            shutil.rmtree(out_dir, ignore_errors=True)

    async def close(self) -> None:
        if self.watchdog is not None:
            self.watchdog.cancel()
        await self._stop()
