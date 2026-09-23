"""`reaper-remote publish`: capture the input device and publish it to mediamtx.

mediamtx starts this command on demand (`runOnDemand`) when the first listener
arrives and stops it with SIGINT when the last one has gone, so the device is
captured only while someone listens and exactly once however many listen.
The audio is encoded to Opus without any other processing.
"""

from __future__ import annotations

import logging
import os
import queue
import signal
import subprocess
import sys
import threading

from .capture import CHANNELS, SAMPLE_FORMAT, OpenStream, open_coreaudio
from .config import Config

log = logging.getLogger("reaper_remote")

# Opus only runs at these rates; any other device rate would make ffmpeg
# resample, which the "never alter the audio" rule forbids.
OPUS_RATES = (48000, 24000, 16000, 12000, 8000)
QUEUE_BLOCKS = 128  # ~2.7 s at 48 kHz before the encoder counts as stalled
STOP_TIMEOUT_S = 5.0


def publish_args(cfg: Config, rate: int, url: str) -> list[str]:
    return [
        cfg.stream.ffmpeg,
        "-hide_banner", "-loglevel", "error",
        "-f", SAMPLE_FORMAT, "-ar", str(rate), "-ac", str(CHANNELS), "-i", "pipe:0",
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
