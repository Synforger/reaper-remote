from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from reaper_remote.app import ffmpeg_args
from reaper_remote.config import parse

# -- proxy ------------------------------------------------------------------


def test_proxy_passes_commands_through_verbatim(client, reaper) -> None:
    r = client.get("/reaper/_/TRANSPORT;SET/EXTSTATE/a/b/c%2Fd;TRACK/0-3")
    assert r.status_code == 200
    assert r.text.startswith("TRANSPORT\t0")
    assert reaper.requests == ["/_/TRANSPORT;SET/EXTSTATE/a/b/c%2Fd;TRACK/0-3"]
    assert r.headers["cache-control"] == "no-store"


def test_proxy_reports_reaper_errors_as_502(client, reaper) -> None:
    reaper.status = 500
    r = client.get("/reaper/_/TRANSPORT")
    assert r.status_code == 502


# -- UI ---------------------------------------------------------------------


def test_ui_is_served_at_root(client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert '<script type="module" src="app.js">' in r.text
    assert client.head("/").status_code == 200
    assert client.get("/lib.js").status_code == 200


def test_ui_only_uses_relative_urls() -> None:
    # Mounted under /ext/<id>/, an absolute path would escape to the host app.
    web = Path(__file__).resolve().parents[2] / "web"
    for f in web.iterdir():
        text = f.read_text(encoding="utf-8")
        for needle in ('src="/', 'href="/', 'fetch("/', "fetch('/", "fetch(`/", 'request("/'):
            assert needle not in text, f"{f.name} contains {needle!r}"


# -- device -----------------------------------------------------------------


def test_device_reports_current_key(client) -> None:
    r = client.get("/device")
    assert r.json() == {
        "current": "headphones",
        "name": "Headphones Out",
        "options": ["headphones", "multi", "blackhole"],
    }


def test_device_switch_changes_system_output(client, tools) -> None:
    r = client.post("/device", json={"device": "multi"})
    assert r.status_code == 200
    assert r.json()["current"] == "multi"
    assert tools["state"].read_text() == "Multi-Output"


def test_device_rejects_unknown_key(client) -> None:
    assert client.post("/device", json={"device": "speakers"}).status_code == 400


def test_device_unconfigured_key_is_404(make_client, raw_config) -> None:
    del raw_config["devices"]["multi"]
    with make_client(raw_config) as c:
        assert c.post("/device", json={"device": "multi"}).status_code == 404


def test_device_tool_failure_is_surfaced(client) -> None:
    r = client.post("/device", json={"device": "blackhole"})
    assert r.status_code == 500
    assert "no such device" in r.json()["detail"]


# -- stream -----------------------------------------------------------------


def test_ffmpeg_captures_configured_input_as_ogg_opus(raw_config) -> None:
    args = ffmpeg_args(parse(raw_config))
    assert args[args.index("-i") + 1] == ":Capture Device"
    assert args[args.index("-c:a") + 1] == "libopus"
    assert args[args.index("-f", args.index("-c:a")) + 1] == "ogg"
    assert args[-1] == "pipe:1"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_stream_starts_encoder_on_connect_and_kills_it_on_disconnect(client, tools) -> None:
    assert not tools["pidfile"].exists()  # nothing encodes before a listener arrives
    with client.stream("GET", "/stream.ogg") as r:
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/ogg"
        # Hold on to the iterator: a discarded one is closed at once, which
        # closes the response and would hang up on the server.
        chunks = r.iter_bytes()
        assert next(chunks).startswith(b"OggS-fake-header")
        pid = int(tools["pidfile"].read_text())
        assert b"chunk" in next(chunks)  # still streaming while connected
        assert _alive(pid)
    deadline = time.time() + 5
    while _alive(pid) and time.time() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)


# -- render -----------------------------------------------------------------


def test_render_reports_enabled(client) -> None:
    assert client.get("/render").json() == {"enabled": True}


def test_render_disabled_without_config(make_client, raw_config) -> None:
    del raw_config["render"]
    with make_client(raw_config) as c:
        assert c.get("/render").json() == {"enabled": False}
        assert c.post("/render").status_code == 404


def test_render_triggers_action_and_serves_the_new_file(client, reaper, tools) -> None:
    render_dir: Path = tools["render_dir"]
    render_dir.mkdir()
    (render_dir / "older.wav").write_bytes(b"old")

    def fake_render(raw: str) -> None:
        if "_RS1234" not in raw:
            return

        def write() -> None:
            time.sleep(0.2)
            (render_dir / "reaper-remote-20260923.wav").write_bytes(b"RIFF" + b"\0" * 64)

        threading.Thread(target=write).start()

    reaper.on_request = fake_render
    r = client.post("/render")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "name": "reaper-remote-20260923.wav",
        "url": "renders/reaper-remote-20260923.wav",
    }
    sent = reaper.requests[-1]
    assert sent.startswith("/_/SET/EXTSTATE/reaper_remote/render_dir/")
    assert "%2F" in sent and sent.endswith(";_RS1234")

    got = client.get("/renders/reaper-remote-20260923.wav")
    assert got.status_code == 200
    assert got.content.startswith(b"RIFF")


def test_render_times_out_when_nothing_appears(client) -> None:
    r = client.post("/render")
    assert r.status_code == 504


def test_renders_cannot_escape_the_render_dir(client, tools) -> None:
    tools["render_dir"].mkdir()
    secret = tools["render_dir"].parent / "secret.txt"
    secret.write_text("nope")
    assert client.get("/renders/..%2Fsecret.txt").status_code == 404
    assert client.get("/renders/%2E%2E/secret.txt").status_code == 404


def test_hidden_attribute_wins_over_layout_rules() -> None:
    # `.row { display: flex }` alone would keep hidden sections (render, output) on screen.
    css = (Path(__file__).resolve().parents[2] / "web" / "style.css").read_text(encoding="utf-8")
    assert "[hidden] { display: none !important; }" in css


def test_missing_switch_tool_is_a_clean_500(make_client, raw_config, tmp_path) -> None:
    raw_config["devices"]["switch_audio_source"] = str(tmp_path / "does-not-exist")
    with make_client(raw_config) as c:
        for r in (c.get("/device"), c.post("/device", json={"device": "multi"})):
            assert r.status_code == 500
            assert r.json()["detail"].endswith("does-not-exist not found")
