from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from conftest import FakeDevice

from reaper_remote.config import parse
from reaper_remote.publish import default_url, publish, publish_args

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
    assert args[i - 6 : i + 2] == ["-f", "f32le", "-ar", "48000", "-ac", "2", "-i", "pipe:0"]
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
    assert tools["pcmfile"].read_bytes() == FakeDevice.BLOCK * (8192 // len(FakeDevice.BLOCK))
    args = tools["argsfile"].read_text().split()
    assert args[args.index("-ar") + 1] == "48000"  # the device's own rate
    assert device.running == 0


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
