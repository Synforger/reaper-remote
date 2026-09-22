from __future__ import annotations

import json
from pathlib import Path

import pytest

from reaper_remote.config import ConfigError, load, parse

REPO_ROOT = Path(__file__).resolve().parents[2]


def minimal() -> dict:
    return {
        "reaper_url": "http://127.0.0.1:8080/",
        "stream": {"input": "BlackHole 2ch"},
        "devices": {},
    }


def test_defaults_bind_to_loopback() -> None:
    cfg = parse(minimal())
    assert (cfg.host, cfg.port) == ("127.0.0.1", 8090)
    assert cfg.reaper_url == "http://127.0.0.1:8080"
    assert cfg.render is None
    assert cfg.devices.names == {}


def test_unknown_top_level_key_is_rejected() -> None:
    raw = minimal() | {"token": "x"}
    with pytest.raises(ConfigError, match="unknown key"):
        parse(raw)


def test_unknown_device_key_is_rejected() -> None:
    raw = minimal()
    raw["devices"] = {"speakers": "MacBook Speakers"}
    with pytest.raises(ConfigError, match="unknown key"):
        parse(raw)


def test_empty_device_name_is_rejected() -> None:
    raw = minimal()
    raw["devices"] = {"multi": ""}
    with pytest.raises(ConfigError, match="devices.multi"):
        parse(raw)


def test_missing_stream_input_is_rejected() -> None:
    raw = minimal()
    raw["stream"] = {}
    with pytest.raises(ConfigError, match="missing key"):
        parse(raw)


def test_render_dir_expands_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    raw = minimal() | {"render": {"action": "_RS1", "dir": "~/renders"}}
    cfg = parse(raw)
    assert cfg.render is not None
    assert cfg.render.dir == (tmp_path / "renders").resolve()


def test_missing_file_names_the_example(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config.example.json"):
        load(tmp_path / "config.json")


def test_shipped_example_parses() -> None:
    raw = json.loads((REPO_ROOT / "config.example.json").read_text(encoding="utf-8"))
    cfg = parse(raw)
    assert set(cfg.devices.names) == {"headphones", "multi", "blackhole"}
    assert cfg.render is not None
