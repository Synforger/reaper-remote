"""CoreAudio capture of the input device.

ffmpeg's avfoundation input drops most of a loopback device's samples while
REAPER plays (measured: 1.3 s of audio in 8.6 s of wall time), so the device is
read through CoreAudio itself (PortAudio, via sounddevice) and raw PCM is fed
to the encoder's stdin. The samples are passed on untouched: no gain, no
limiting, no resampling — the device's own rate is used.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger("reaper_remote")

CHANNELS = 2
SAMPLE_FORMAT = "f32le"  # ffmpeg's name for what the capture delivers
BLOCK_FRAMES = 1024


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
