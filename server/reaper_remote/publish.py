"""`reaper-remote publish`: capture the input device and publish it to mediamtx.

mediamtx starts this command on demand (`runOnDemand`) when the first listener
arrives and stops it with SIGINT when the last one has gone, so the device is
captured only while someone listens and exactly once however many listen.
The audio is encoded to Opus without any other processing.

The PCM reaches ffmpeg as a WAV stream read one block (20 ms) at a time. Read as
raw f32le, ffmpeg takes 32768 bytes (85 ms) per packet, encodes four Opus
frames at once and sends them together, which the listener hears as jitter.
"""

from __future__ import annotations

import logging
import os
import queue
import signal
import struct
import subprocess
import sys
import threading

from .capture import CHANNELS, SAMPLE_BYTES, OpenStream, block_frames, open_coreaudio
from .config import Config

log = logging.getLogger("reaper_remote")

# Opus only runs at these rates; any other device rate would make ffmpeg
# resample, which the "never alter the audio" rule forbids.
OPUS_RATES = (48000, 24000, 16000, 12000, 8000)
QUEUE_BLOCKS = 128  # ~2.7 s at 48 kHz before the encoder counts as stalled
STOP_TIMEOUT_S = 5.0


WAVE_FORMAT_IEEE_FLOAT = 3
UNKNOWN_LENGTH = 0xFFFFFFFF


def wav_header(rate: int) -> bytes:
    """A WAV header for an endless stream of the capture's float samples."""
    align = CHANNELS * SAMPLE_BYTES
    fmt = struct.pack(
        "<HHIIHH", WAVE_FORMAT_IEEE_FLOAT, CHANNELS, rate, rate * align, align, SAMPLE_BYTES * 8
    )
    return (
        b"RIFF" + struct.pack("<I", UNKNOWN_LENGTH) + b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", UNKNOWN_LENGTH)
    )  # fmt: skip


def publish_args(cfg: Config, rate: int, url: str) -> list[str]:
    packet_bytes = block_frames(rate) * CHANNELS * SAMPLE_BYTES
    return [
        cfg.stream.ffmpeg,
        "-hide_banner", "-loglevel", "error",
        "-f", "wav", "-ignore_length", "1", "-max_size", str(packet_bytes), "-i", "pipe:0",
        "-c:a", "libopus", "-b:a", cfg.stream.bitrate, "-application", "audio",
        "-f", "rtsp", "-rtsp_transport", "tcp",
        url,
    ]  # fmt: skip


def default_url() -> str:
    """The RTSP URL mediamtx expects its on-demand publisher to use."""
    port, path = os.environ.get("RTSP_PORT"), os.environ.get("MTX_PATH")
    if not port or not path:
        raise SystemExit("publish: no URL given and RTSP_PORT / MTX_PATH are not set")
    return f"rtsp://127.0.0.1:{port}/{path}"


def publish(cfg: Config, url: str, open_stream: OpenStream = open_coreaudio) -> int:
    blocks: queue.Queue[bytes] = queue.Queue(maxsize=QUEUE_BLOCKS)
    stop = threading.Event()

    def on_block(pcm: bytes) -> None:
        try:
            blocks.put_nowait(pcm)
        except queue.Full:
            log.warning("publish: the encoder fell behind; dropped one block")

    stream, rate = open_stream(cfg.stream.input, on_block)
    if rate not in OPUS_RATES:
        stream.close()
        raise SystemExit(
            f"publish: {cfg.stream.input} runs at {rate} Hz; Opus needs one of {OPUS_RATES}. "
            "Set the device to 48 kHz in Audio MIDI Setup (resampling would alter the audio)."
        )

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    proc = subprocess.Popen(publish_args(cfg, rate, url), stdin=subprocess.PIPE)
    assert proc.stdin is not None
    proc.stdin.write(wav_header(rate))
    stream.start()
    try:
        while not stop.is_set() and proc.poll() is None:
            try:
                pcm = blocks.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                proc.stdin.write(pcm)
                proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                break
    finally:
        stream.stop()
        stream.close()
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        try:
            proc.wait(timeout=STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    # Stopped on request: a clean exit whatever ffmpeg reported.
    return 0 if stop.is_set() else (proc.returncode or 0)


def main(cfg: Config, argv: list[str]) -> None:
    sys.exit(publish(cfg, argv[0] if argv else default_url()))
