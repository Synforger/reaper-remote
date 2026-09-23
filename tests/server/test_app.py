from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from reaper_remote import stream
from reaper_remote.config import parse
from reaper_remote.stream import hls_args, ogg_args, split_pages

# -- proxy ------------------------------------------------------------------


def test_proxy_passes_commands_through_verbatim(client, reaper) -> None:
    r = client.get("/reaper/_/TRANSPORT;SET/EXTSTATE/a/b/c%2Fd;TRACK/0-3")
    assert r.status_code == 200
    assert r.text.startswith("TRANSPORT\t0")
    assert reaper.requests == ["/_/TRANSPORT;SET/EXTSTATE/a/b/c%2Fd;TRACK/0-3"]
    assert r.headers["cache-control"] == "no-store"


def test_proxy_turns_an_encoded_separator_back_into_a_semicolon(client, reaper) -> None:
    # tailscale serve forwards `;` as `%3B`; REAPER answers nothing to that.
    assert client.get("/reaper/_/TRANSPORT%3BTRACK").status_code == 200
    assert client.get("/reaper/_/NTRACK%3btrack").status_code == 200
    assert reaper.requests == ["/_/TRANSPORT;TRACK", "/_/NTRACK;track"]


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
        "available": ["headphones", "multi", "blackhole"],
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


def test_unplugged_device_is_reported_and_refused_with_409(client, tools) -> None:
    # A headphone jack output disappears when nothing is plugged in.
    tools["present"].write_text("Multi-Output\nBroken Device\n")
    assert client.get("/device").json()["available"] == ["multi", "blackhole"]
    r = client.post("/device", json={"device": "headphones"})
    assert r.status_code == 409
    assert r.json()["detail"] == "Headphones Out is not connected"
    assert tools["state"].read_text() == "Headphones Out"  # nothing was switched


def test_device_tool_failure_is_surfaced(client) -> None:
    r = client.post("/device", json={"device": "blackhole"})
    assert r.status_code == 500
    assert "no such device" in r.json()["detail"]


# -- stream -----------------------------------------------------------------


def test_encoders_capture_the_configured_input(raw_config, tmp_path) -> None:
    cfg = parse(raw_config)
    ogg = ogg_args(cfg)
    assert ogg[ogg.index("-i") + 1] == ":Capture Device"
    assert ogg[ogg.index("-c:a") + 1] == "libopus"
    assert ogg[-1] == "pipe:1"
    hls = hls_args(cfg, tmp_path)
    assert hls[hls.index("-c:a") + 1] == "aac"
    assert hls[hls.index("-f", hls.index("-c:a")) + 1] == "hls"
    assert hls[-1] == str(tmp_path / "stream.m3u8")
    # Apple's HLS authoring spec for live playlists: at least six segments (8.11)
    # and EXT-X-PROGRAM-DATE-TIME in every playlist (8.4).
    assert int(hls[hls.index("-hls_list_size") + 1]) >= 6
    assert "program_date_time" in hls[hls.index("-hls_flags") + 1]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _pids(tools) -> list[int]:
    return [int(x) for x in tools["pidfile"].read_text().split()]


def _wait_dead(pid: int) -> bool:
    deadline = time.time() + 5
    while _alive(pid) and time.time() < deadline:
        time.sleep(0.05)
    return not _alive(pid)


def test_ogg_listeners_share_one_encoder_and_each_gets_the_header(client, tools) -> None:
    header = (tools["pidfile"].parent / "ogg-header.bin").read_bytes()
    assert not tools["pidfile"].exists()  # nothing encodes before a listener arrives
    # Hold on to the iterators: a discarded one is closed at once, which
    # closes the response and hangs up on the server.
    with client.stream("GET", "/stream.ogg") as a:
        assert a.headers["content-type"] == "audio/ogg"
        chunks_a = a.iter_bytes()
        got_a = next(chunks_a)
        while len(got_a) < len(header) + 1:
            got_a += next(chunks_a)
        assert got_a.startswith(header)
        # A second listener (Safari opens two per play) joins mid-stream.
        with client.stream("GET", "/stream.ogg") as b:
            chunks_b = b.iter_bytes()
            got_b = next(chunks_b)
            while len(got_b) < len(header) + 1:
                got_b += next(chunks_b)
            assert got_b.startswith(header)
            assert b"audio-" in got_b[len(header) :] + next(chunks_b)
            assert len(_pids(tools)) == 1
        (pid,) = _pids(tools)
        assert b"audio-" in next(chunks_a)  # the first listener keeps streaming
        assert _alive(pid)
    assert _wait_dead(pid)  # the last listener leaving stops the encoder


def test_split_pages_resyncs_and_keeps_partial_pages() -> None:
    from conftest import ogg_page

    page = ogg_page(0, b"x" * 10)
    buf = bytearray(b"junk" + page + page[:5])
    assert split_pages(buf) == [page]
    assert bytes(buf) == page[:5]
    buf += page[5:]
    assert split_pages(buf) == [page]
    assert buf == bytearray()


def test_hls_playlist_starts_one_encoder_and_serves_segments(client, tools) -> None:
    r = client.get("/hls/stream.m3u8")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    assert "#EXTM3U" in r.text
    seg = next(line for line in r.text.splitlines() if line.endswith(".ts"))
    s = client.get(f"/hls/{seg}")
    assert s.status_code == 200
    assert s.content.startswith(b"segment-")
    assert client.get("/hls/stream.m3u8").status_code == 200
    assert len(_pids(tools)) == 1  # polling the playlist reuses the encoder
    assert client.get("/hls/..%2Fsecret.ts").status_code == 404
    assert client.get("/hls/nope.ts").status_code == 404


def test_hls_encoder_stops_when_nobody_polls(make_client, raw_config, tools, monkeypatch) -> None:
    monkeypatch.setattr(stream, "HLS_IDLE_S", 0.6)
    with make_client(raw_config) as c:
        assert c.get("/hls/stream.m3u8").status_code == 200
        (pid,) = _pids(tools)
        assert _wait_dead(pid)
        # The next poll starts a fresh encoder.
        assert c.get("/hls/stream.m3u8").status_code == 200
        assert len(_pids(tools)) == 2


def test_missing_ffmpeg_is_a_clean_500(make_client, raw_config, tmp_path) -> None:
    raw_config["stream"]["ffmpeg"] = str(tmp_path / "no-ffmpeg")
    with make_client(raw_config) as c:
        assert c.get("/stream.ogg").status_code == 500
        assert c.get("/hls/stream.m3u8").status_code == 500


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
