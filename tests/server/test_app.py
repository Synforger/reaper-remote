from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from conftest import FakeDevice

from reaper_remote.config import parse
from reaper_remote.publish import default_url, publish, publish_args, wav_header

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


def test_publisher_encodes_the_capture_untouched(raw_config) -> None:
    args = publish_args(parse(raw_config), 48000, "rtsp://127.0.0.1:8554/reaper")
    i = args.index("-i")
    # WAV read one 20 ms block (960 frames x 2 ch x 4 bytes) per packet: raw f32le
    # would be read 85 ms at a time and leave as bursts of four Opus packets.
    assert args[i - 6 : i + 2] == [
        "-f", "wav", "-ignore_length", "1", "-max_size", "7680", "-i", "pipe:0",
    ]  # fmt: skip
    # The owner's rule: the sound is never altered. No filters, no gain,
    # no resampling or channel changes after the input.
    after = args[i + 2 :]
    for banned in ("-af", "-filter:a", "-filter_complex", "-ar", "-ac", "-vol"):
        assert banned not in after, f"{banned} would alter the audio"
    assert not any("volume" in a or "limit" in a or "loudnorm" in a for a in after)
    assert args[args.index("-c:a") + 1] == "libopus"
    assert args[-3:] == ["-rtsp_transport", "tcp", "rtsp://127.0.0.1:8554/reaper"]


def test_publisher_pipes_pcm_to_ffmpeg_and_releases_the_device(raw_config, tools, device):
    assert publish(parse(raw_config), "rtsp://x/reaper", open_stream=device.open) == 0
    sent = tools["pcmfile"].read_bytes()
    header = wav_header(48000)  # the device's own rate
    assert sent[: len(header)] == header
    body = sent[len(header) :]
    assert body == (FakeDevice.BLOCK * (8192 // len(FakeDevice.BLOCK) + 1))[: len(body)]
    assert device.running == 0


def test_wav_header_describes_the_capture_as_an_endless_float_stream() -> None:
    import struct

    h = wav_header(48000)
    assert (h[:4], h[8:16], h[36:40]) == (b"RIFF", b"WAVEfmt ", b"data")
    fmt, channels, rate, byte_rate, align, bits = struct.unpack("<HHIIHH", h[20:36])
    assert (fmt, channels, rate, byte_rate, align, bits) == (3, 2, 48000, 384000, 8, 32)
    assert struct.unpack("<I", h[40:44])[0] == 0xFFFFFFFF  # length unknown: read until EOF


def test_publisher_refuses_a_rate_opus_would_resample(raw_config, device, monkeypatch) -> None:
    monkeypatch.setattr(FakeDevice, "RATE", 44100)
    with pytest.raises(SystemExit, match="44100 Hz"):
        publish(parse(raw_config), "rtsp://x/reaper", open_stream=device.open)
    assert device.running == 0


def test_publisher_takes_its_url_from_mediamtx(monkeypatch) -> None:
    monkeypatch.setenv("RTSP_PORT", "8554")
    monkeypatch.setenv("MTX_PATH", "reaper")
    assert default_url() == "rtsp://127.0.0.1:8554/reaper"
    monkeypatch.delenv("MTX_PATH")
    with pytest.raises(SystemExit):
        default_url()


# -- mediamtx relay ------------------------------------------------------------


def test_whep_offer_is_relayed_and_the_session_url_made_relative(client, media) -> None:
    r = client.post("/whep", content="v=0 offer", headers={"Content-Type": "application/sdp"})
    assert r.status_code == 201
    assert r.text == "v=0 answer"
    assert r.headers["content-type"] == "application/sdp"
    assert r.headers["location"] == "whep/3f2a-session"
    assert "set-cookie" not in r.headers  # only the headers WHEP needs pass through
    sent = media.requests[-1]
    assert (sent.method, sent.url.host, sent.url.port) == ("POST", "127.0.0.1", 8889)
    assert sent.url.path == "/reaper/whep"
    assert sent.content == b"v=0 offer"
    assert sent.headers["content-type"] == "application/sdp"


def test_whep_session_delete_reaches_mediamtx(client, media) -> None:
    assert client.delete("/whep/3f2a-session").status_code == 200
    assert media.requests[-1].method == "DELETE"
    assert media.requests[-1].url.path == "/reaper/whep/3f2a-session"


def test_llhls_redirect_stays_under_the_relay(client, media) -> None:
    r = client.get("/llhls/index.m3u8", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "index.m3u8?cookieCheck=1"
    followed = client.get("/llhls/index.m3u8", follow_redirects=True)
    assert followed.status_code == 200
    assert "session=abc" in followed.text  # mediamtx's session rides in the query
    assert all("cookie" not in req.headers for req in media.requests)


def test_llhls_is_relayed_with_its_blocking_query(client, media) -> None:
    r = client.get(
        "/llhls/index.m3u8", params={"cookieCheck": "1", "_HLS_msn": "5", "_HLS_part": "1"}
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.apple.mpegurl"
    sent = media.requests[-1]
    assert (sent.url.port, sent.url.path) == (8888, "/reaper/index.m3u8")
    assert dict(sent.url.params) == {"cookieCheck": "1", "_HLS_msn": "5", "_HLS_part": "1"}


def test_mediamtx_down_is_a_502(client, media) -> None:
    media.down = True
    assert client.post("/whep", content="v=0").status_code == 502
    assert client.get("/llhls/index.m3u8").status_code == 502


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


def test_version_reports_a_ui_fingerprint_that_follows_the_files(tmp_path) -> None:
    import shutil

    from reaper_remote.app import ui_fingerprint

    web = tmp_path / "web"
    shutil.copytree(Path(__file__).resolve().parents[2] / "web", web)
    before = ui_fingerprint(web)
    assert before == ui_fingerprint(web)  # stable while nothing changes
    (web / "app.js").write_text((web / "app.js").read_text() + "\n// changed\n")
    assert ui_fingerprint(web) != before


def test_version_route_and_ui_files_are_never_served_stale(client) -> None:
    r = client.get("/version")
    assert r.status_code == 200
    assert len(r.json()["ui"]) == 16
    assert r.headers["cache-control"] == "no-store"
    for path in ("/", "/app.js", "/style.css"):
        assert client.get(path).headers["cache-control"] == "no-cache"


# -- timeline ---------------------------------------------------------------

TIMELINE_REPLY = (
    "EXTSTATE\treaper_remote\ttimeline\t9.000000|0.000000,2.000000,4.000000,6.000000,9.000000"
    "|4.000000,6.000000\n"
    "MARKER_LIST\n"
    "MARKER\tDrop\t1\t4.500000\t0x01ff8000\n"
    "MARKER_LIST_END\n"
    "REGION_LIST\n"
    "REGION\tIntro\\tA\t1\t0.000000\t4.000000\t0\n"
    "REGION\tHook\t2\t4.000000\t9.000000\n"
    "REGION_LIST_END\n"
)


def test_timeline_runs_the_script_and_reads_it_back_in_one_request(make_client, raw_config, reaper):
    raw_config["timeline"] = {"action": "_RS5678"}
    with make_client(raw_config) as c:
        reaper.reply = TIMELINE_REPLY
        r = c.get("/timeline")
        assert r.status_code == 200, r.text
        assert r.headers["cache-control"] == "no-store"
        assert r.json() == {
            "enabled": True,
            "end": 9.0,
            "edges": [0.0, 2.0, 4.0, 6.0, 9.0],
            "loop": {"start": 4.0, "end": 6.0},
            "markers": [{"id": 1, "name": "Drop", "pos": 4.5, "color": 0x01FF8000}],
            "regions": [
                {"id": 1, "name": "Intro\tA", "start": 0.0, "end": 4.0, "color": 0},
                {"id": 2, "name": "Hook", "start": 4.0, "end": 9.0, "color": 0},
            ],
        }
        # Cleared before the action runs, so a stale result can never be read.
        assert reaper.requests == [
            "/_/SET/EXTSTATE/reaper_remote/timeline/;_RS5678;"
            "GET/EXTSTATE/reaper_remote/timeline;MARKER;REGION"
        ]


def test_timeline_disabled_without_config(client, reaper) -> None:
    assert client.get("/timeline").json() == {"enabled": False}
    assert reaper.requests == []


@pytest.mark.parametrize(
    "state",
    ["", "garbage", "9.0||0,0", "9.0|0.0|0,0", "x|0.0,1.0|0,0", "9.0|0.0,1.0", "9.0|0.0,1.0|x"],
    ids=[
        "script-did-not-run",
        "no-separator",
        "no-edges",
        "one-edge",
        "bad-number",
        "no-loop",
        "bad-loop",
    ],
)
def test_timeline_without_a_usable_result_is_a_502(make_client, raw_config, reaper, state) -> None:
    raw_config["timeline"] = {"action": "_RS5678"}
    with make_client(raw_config) as c:
        reaper.reply = f"EXTSTATE\treaper_remote\ttimeline\t{state}\nMARKER_LIST\nMARKER_LIST_END\n"
        r = c.get("/timeline")
        assert r.status_code == 502
        assert r.json()["detail"]


def test_timeline_reports_no_loop_when_the_points_meet(make_client, raw_config, reaper) -> None:
    raw_config["timeline"] = {"action": "_RS5678"}
    with make_client(raw_config) as c:
        reaper.reply = "EXTSTATE\treaper_remote\ttimeline\t9.0|0.0,9.0|3.0,3.0\n"
        assert c.get("/timeline").json()["loop"] is None


# -- loop ---------------------------------------------------------------------


def test_loop_sets_the_range_through_the_script_and_turns_repeat_on(
    make_client, raw_config, reaper
):
    raw_config["loop"] = {"action": "_RS9abc"}
    with make_client(raw_config) as c:
        assert c.get("/loop").json() == {"enabled": True}
        r = c.post("/loop", json={"start": 55.652174, "end": 69.565217})
        assert r.status_code == 200, r.text
        assert r.json() == {"start": 55.652174, "end": 69.565217}
        assert reaper.requests == [
            "/_/SET/EXTSTATE/reaper_remote/loop/55.652174%2C69.565217;_RS9abc;SET/REPEAT/1"
        ]


def test_loop_disabled_without_config(client, reaper) -> None:
    assert client.get("/loop").json() == {"enabled": False}
    assert client.post("/loop", json={"start": 0, "end": 1}).status_code == 404
    assert reaper.requests == []


@pytest.mark.parametrize(
    "body", [{"start": 4, "end": 4}, {"start": 5, "end": 4}, {"start": -1, "end": 2}]
)
def test_loop_rejects_an_empty_or_reversed_range(make_client, raw_config, reaper, body) -> None:
    raw_config["loop"] = {"action": "_RS9abc"}
    with make_client(raw_config) as c:
        assert c.post("/loop", json=body).status_code == 400
    assert reaper.requests == []


# -- listening stats ------------------------------------------------------------


def test_listen_stats_are_logged_on_one_line(client, caplog) -> None:
    caplog.set_level("INFO", logger="reaper_remote")
    clean = {
        "mode": "webrtc",
        "seconds": 5.0,
        "received": 250,
        "lost": 0,
        "loss_pct": 0.0,
        "discarded": 0,
        "jitter_ms": 3.0,
        "concealed_pct": 0.0,
        "concealment_events": 0,
        "buffer_ms": 60.0,
        "rtt_ms": 41.0,
    }
    assert client.post("/listen-stats", json=clean).status_code == 204
    rec = next(r for r in caplog.records if r.getMessage().startswith("listen "))
    assert rec.levelname == "INFO"
    assert rec.getMessage().startswith("listen mode=webrtc seconds=5.0 received=250 lost=0 ")
    assert "buffer_ms=60.0 rtt_ms=41.0 from " in rec.getMessage()


@pytest.mark.parametrize("field", ["lost", "discarded", "concealment_events"])
def test_an_interval_with_missing_audio_is_logged_as_a_gap(client, caplog, field) -> None:
    caplog.set_level("INFO", logger="reaper_remote")
    body = {"mode": "webrtc", "seconds": 5.0, "received": 250, field: 1}
    assert client.post("/listen-stats", json=body).status_code == 204
    rec = next(r for r in caplog.records if r.getMessage().startswith("listen "))
    assert rec.levelname == "WARNING"
    assert rec.getMessage().startswith("listen GAP mode=webrtc ")


def test_listen_stats_log_a_fallback_with_its_reason(client, caplog) -> None:
    caplog.set_level("INFO", logger="reaper_remote")
    body = {"mode": "llhls", "event": "fallback", "reason": "WebRTC dropped"}
    assert client.post("/listen-stats", json=body).status_code == 204
    assert any(
        "listen GAP mode=llhls event=fallback reason='WebRTC dropped'" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "rtmp"},
        {"mode": "webrtc", "event": "anything"},
        {"mode": "llhls", "reason": "x" * 201},
    ],
    ids=["unknown-mode", "unknown-event", "long-reason"],
)
def test_listen_stats_reject_what_they_do_not_know(client, body) -> None:
    assert client.post("/listen-stats", json=body).status_code == 422
