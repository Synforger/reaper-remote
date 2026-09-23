"""One CoreAudio capture of the input device, shared by every encoder.

ffmpeg's avfoundation input drops most of a loopback device's samples while
REAPER plays (measured: 1.3 s of audio in 8.6 s of wall time), so the server
reads the device through CoreAudio itself (PortAudio, via sounddevice) and
feeds raw PCM to each encoder's stdin. The samples are passed on untouched:
no gain, no limiting, no resampling — the device's own rate is used.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger("reaper_remote")

CHANNELS = 2
SAMPLE_FORMAT = "f32le"  # ffmpeg's name for what the capture delivers
BLOCK_FRAMES = 1024
# Blocks buffered per encoder (~2.7 s at 48 kHz) before one counts as stalled.
SINK_QUEUE_BLOCKS = 128


class InputStream(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


# Opens a stream on the named device. Returns the stream and its sample rate;
# the stream calls `on_block(pcm_bytes)` from its own thread.
OpenStream = Callable[[str, Callable[[bytes], None]], tuple[InputStream, int]]


def open_coreaudio(device: str, on_block: Callable[[bytes], None]) -> tuple[InputStream, int]:
    import sounddevice as sd  # imported here: PortAudio is only needed on the Mac

    index = next(
        (
            i
            for i, d in enumerate(sd.query_devices())
            if d["name"] == device and d["max_input_channels"] >= CHANNELS
        ),
        None,
    )
    if index is None:
        raise LookupError(f"no input device named {device!r} with {CHANNELS} channels")
    rate = int(sd.query_devices(index)["default_samplerate"])

    def callback(data, frames, time, status) -> None:
        if status:
            log.warning("capture: %s", status)
        on_block(bytes(data))

    stream = sd.RawInputStream(
        device=index,
        channels=CHANNELS,
        samplerate=rate,
        dtype="float32",
        blocksize=BLOCK_FRAMES,
        callback=callback,
    )
    return stream, rate


class Capture:
    """Runs the device stream while at least one sink is subscribed."""

    def __init__(self, device: str, open_stream: OpenStream = open_coreaudio) -> None:
        self.device = device
        self.open_stream = open_stream
        self.stream: InputStream | None = None
        self.rate = 0
        self.sinks: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self) -> asyncio.Queue:
        """Return a queue of PCM blocks; starts the device on the first subscriber."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=SINK_QUEUE_BLOCKS)
        if self.stream is None:
            self.loop = asyncio.get_running_loop()
            self.stream, self.rate = self.open_stream(self.device, self._on_block)
            self.stream.start()
        self.sinks.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.sinks.discard(queue)
        if not self.sinks and self.stream is not None:
            stream, self.stream = self.stream, None
            stream.stop()
            stream.close()

    def _on_block(self, pcm: bytes) -> None:
        # Called on the audio thread: hand the block to the event loop.
        loop = self.loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._fan_out, pcm)
            except RuntimeError:  # the loop closed between the check and the call
                pass

    def _fan_out(self, pcm: bytes) -> None:
        for queue in list(self.sinks):
            try:
                queue.put_nowait(pcm)
            except asyncio.QueueFull:
                log.warning("capture: an encoder fell behind; dropped one block")


async def feed(queue: asyncio.Queue, stdin: asyncio.StreamWriter) -> None:
    """Copy PCM blocks from a capture queue into an encoder's stdin until it closes."""
    try:
        while True:
            stdin.write(await queue.get())
            await stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
