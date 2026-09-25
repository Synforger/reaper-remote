"""Load and validate `config.json`.

The file is the single source of truth for every machine-specific value
(bind address, REAPER URL, audio device names, render directory, the REAPER
actions it triggers). The code only reads it; nothing here guesses a device
name or a path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.json"
CONFIG_ENV = "REAPER_REMOTE_CONFIG"

# The three output targets the UI offers. The keys are part of the HTTP
# contract (`POST /device`); the device names behind them come from config.
DEVICE_KEYS = ("headphones", "multi", "blackhole")


class ConfigError(ValueError):
    """Raised when config.json is missing a value or carries an unknown one."""


@dataclass(frozen=True)
class StreamConfig:
    input: str
    bitrate: str = "128k"
    ffmpeg: str = "ffmpeg"


@dataclass(frozen=True)
class MediaConfig:
    """Where mediamtx serves the stream (loopback; this app relays to it)."""

    webrtc: str = "http://127.0.0.1:8889"
    hls: str = "http://127.0.0.1:8888"
    path: str = "reaper"


@dataclass(frozen=True)
class DeviceConfig:
    names: dict[str, str]
    switch_audio_source: str = "SwitchAudioSource"


@dataclass(frozen=True)
class RenderConfig:
    action: str
    dir: Path
    timeout_s: float = 600.0


@dataclass(frozen=True)
class TimelineConfig:
    action: str


@dataclass(frozen=True)
class LoopConfig:
    action: str


@dataclass(frozen=True)
class ProjectsConfig:
    list_action: str
    select_action: str


@dataclass(frozen=True)
class Config:
    reaper_url: str
    stream: StreamConfig
    devices: DeviceConfig
    render: RenderConfig | None
    timeline: TimelineConfig | None = None
    loop: LoopConfig | None = None
    projects: ProjectsConfig | None = None
    media: MediaConfig = field(default_factory=MediaConfig)
    host: str = "127.0.0.1"
    port: int = 8090
    web_dir: Path = field(default=REPO_ROOT / "web")


def _take(section: dict, name: str, allowed: set[str], required: set[str]) -> dict:
    if not isinstance(section, dict):
        raise ConfigError(f"{name}: expected an object")
    unknown = set(section) - allowed
    if unknown:
        raise ConfigError(f"{name}: unknown key(s) {sorted(unknown)}")
    missing = required - set(section)
    if missing:
        raise ConfigError(f"{name}: missing key(s) {sorted(missing)}")
    return section


def parse(raw: dict) -> Config:
    top = _take(
        raw,
        "config",
        {
            "host",
            "port",
            "reaper_url",
            "stream",
            "devices",
            "render",
            "timeline",
            "loop",
            "projects",
            "media",
        },
        {"reaper_url", "stream", "devices"},
    )

    stream = _take(top["stream"], "stream", {"input", "bitrate", "ffmpeg"}, {"input"})

    devices = _take(
        top["devices"],
        "devices",
        {*DEVICE_KEYS, "switch_audio_source"},
        set(),
    )
    names = {k: v for k, v in devices.items() if k in DEVICE_KEYS}
    for key, value in names.items():
        if not isinstance(value, str) or not value:
            raise ConfigError(f"devices.{key}: expected a non-empty device name")

    render = None
    if top.get("render") is not None:
        r = _take(top["render"], "render", {"action", "dir", "timeout_s"}, {"action", "dir"})
        render = RenderConfig(
            action=str(r["action"]),
            dir=Path(os.path.expanduser(r["dir"])).resolve(),
            timeout_s=float(r.get("timeout_s", 600.0)),
        )

    timeline = None
    if top.get("timeline") is not None:
        t = _take(top["timeline"], "timeline", {"action"}, {"action"})
        timeline = TimelineConfig(action=str(t["action"]))

    loop = None
    if top.get("loop") is not None:
        lp = _take(top["loop"], "loop", {"action"}, {"action"})
        loop = LoopConfig(action=str(lp["action"]))

    projects = None
    if top.get("projects") is not None:
        keys = {"list_action", "select_action"}
        pj = _take(top["projects"], "projects", keys, keys)
        projects = ProjectsConfig(
            list_action=str(pj["list_action"]), select_action=str(pj["select_action"])
        )

    m = _take(top.get("media", {}), "media", {"webrtc", "hls", "path"}, set())
    media = MediaConfig(
        **{k: str(v).rstrip("/") if k != "path" else str(v).strip("/") for k, v in m.items()}
    )

    return Config(
        media=media,
        host=str(top.get("host", "127.0.0.1")),
        port=int(top.get("port", 8090)),
        reaper_url=str(top["reaper_url"]).rstrip("/"),
        stream=StreamConfig(**stream),
        devices=DeviceConfig(
            names=names,
            switch_audio_source=devices.get("switch_audio_source", "SwitchAudioSource"),
        ),
        render=render,
        timeline=timeline,
        loop=loop,
        projects=projects,
    )


def load(path: Path | None = None) -> Config:
    path = path or Path(os.environ.get(CONFIG_ENV, DEFAULT_CONFIG_PATH))
    if not path.is_file():
        raise ConfigError(f"{path} not found (copy config.example.json to config.json)")
    return parse(json.loads(path.read_text(encoding="utf-8")))
