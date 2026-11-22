"""Which requests the server takes: the page's commands, sent by the page."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
PLAY = "/reaper/_/1007"
ELSEWHERE = {"Sec-Fetch-Site": "cross-site"}
NEIGHBOUR = {"Sec-Fetch-Site": "same-site"}


def ui_commands() -> list[str]:
    """Every command web/app.js can send, read from its source with sample values."""
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    actions = dict(re.findall(r"(\w+): (\d+)", re.search(r"const ACTION = \{(.+)\}", js)[1]))
    found = list(actions.values())
    for literal in re.findall(r"`(SET/[^`]+|TRANSPORT[^`]*)`", js):
        text = literal.replace("${ACTION.METRONOME}", actions["METRONOME"])
        samples = {
            "${repeat ? 0 : 1}": ["0", "1"],
            "${seconds.toFixed(6)}": ["0.000000", "163.500000", "-0.000000"],
            "${track.index}": ["0", "3", "128"],
            "${index}": ["0", "3", "128"],
            "${volume.toFixed(6)}": ["0.000000", "1.000000", "3.981072"],
        }
        variants = [text]
        for hole, values in samples.items():
            if hole in text:
                variants = [v.replace(hole, value) for v in variants for value in values]
        assert not any("${" in v for v in variants), f"no sample for {literal}"
        found += variants
    return found


def test_the_ui_command_list_covers_every_call_site() -> None:
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    args = re.findall(r"(?<!function )\b(?:send|reaper)\((.+)", js)
    for arg in args:
        known = ("String(", "`SET/", "`TRANSPORT", "commands")
        assert arg.startswith(known), f"a call this test cannot read: {arg}"
    families = ("1007", "1008", "1016", "40042", "40364", "TRANSPORT;", "SET/REPEAT/", "SET/POS/")
    for family in (*families, "/MUTE/", "/SOLO/", "/VOL/"):
        assert any(family in c for c in ui_commands()), f"{family} was not found in app.js"


@pytest.mark.parametrize("command", ui_commands())
def test_every_ui_command_is_relayed_as_sent(client, reaper, command: str) -> None:
    assert client.get(f"/reaper/_/{command}").status_code == 200
    assert reaper.requests == [f"/_/{command}"]


@pytest.mark.parametrize(
    "command",
    [
        "99999",
        "_RSunlisted",
        "NTRACK",
        "SET/EXTSTATE/a/b/c",
        "GET/EXTSTATE/a/b",
        "TRANSPORT;99999",
        "SET/REPEAT/2",
        "SET/POS/x",
        "SET/TRACK/1/PAN/0.5",
        "1007%2F1",
        "1007%0A",
        "TRANSPORT;",
        "",
    ],
)
def test_commands_outside_the_ui_set_are_refused(client, reaper, command: str) -> None:
    assert client.get(f"/reaper/_/{command}").status_code == 403
    assert reaper.requests == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/reaper/_/TRANSPORT"),
        ("GET", PLAY),
        ("GET", "/timeline"),
        ("GET", "/projects"),
        ("GET", "/device"),
        ("GET", "/renders/a.wav"),
        ("GET", "/llhls/index.m3u8"),
        ("POST", "/render"),
        ("POST", "/device"),
        ("POST", "/loop"),
        ("POST", "/projects/select"),
        ("POST", "/listen-stats"),
        ("POST", "/whep"),
        ("PATCH", "/whep/s"),
        ("DELETE", "/whep/s"),
    ],
)
@pytest.mark.parametrize("headers", [ELSEWHERE, NEIGHBOUR], ids=["cross-site", "same-site"])
def test_routes_take_requests_from_their_own_page(
    client, reaper, media, method: str, path: str, headers: dict[str, str]
) -> None:
    assert client.request(method, path, headers=headers).status_code == 403
    assert reaper.requests == []
    assert media.requests == []


@pytest.mark.parametrize(
    "origin", ["null", "https://example.com", "https://mac.example.ts.net:8443", "not a url"]
)
def test_an_origin_must_be_the_servers_own(client, reaper, origin: str) -> None:
    headers = {"Host": "mac.example.ts.net", "Origin": origin}
    assert client.get(PLAY, headers=headers).status_code == 403
    assert reaper.requests == []


@pytest.mark.parametrize(
    "host", ["example.com", "mac.ts.net.example.com", "100.64.0.1", "ts.net", "a@localhost", ""]
)
def test_only_the_servers_own_names_are_answered(client, reaper, host: str) -> None:
    for path in ("/", "/version", "/reaper/_/TRANSPORT"):
        assert client.get(path, headers={"Host": host}).status_code in (400, 403)
    assert reaper.requests == []


@pytest.mark.parametrize(
    "host",
    [
        "localhost:8090",
        "127.0.0.1:8090",
        "[::1]:8090",
        "mac.example.ts.net",
        "Mac.Example.TS.net.:443",
    ],
)
def test_the_usual_ways_to_reach_the_page_work(client, host: str) -> None:
    assert client.get(PLAY, headers={"Host": host}).status_code == 200
    assert client.get("/", headers={"Host": host}).status_code == 200


def test_a_configured_bind_name_is_answered(make_client, raw_config) -> None:
    # Only the name: the test server itself always binds loopback.
    raw_config["host"] = "studio.lan"
    with make_client(raw_config) as c:
        assert c.get("/version", headers={"Host": "studio.lan:8090"}).status_code == 200


def test_the_page_behind_tailscale_serve_can_post(client, media) -> None:
    headers = {"Host": "mac.example.ts.net", "Origin": "https://mac.example.ts.net"}
    assert client.post("/whep", content="v=0", headers=headers).status_code == 201


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://localhost:8090"},
        {"Referer": "http://localhost:8090/"},
    ],
    ids=["origin", "referer"],
)
def test_browsers_without_fetch_metadata_still_work(plain, headers: dict[str, str]) -> None:
    assert plain.get(PLAY, headers={"Host": "localhost:8090", **headers}).status_code == 200


def test_a_change_needs_to_say_it_comes_from_the_page(plain, client, reaper) -> None:
    assert plain.get(PLAY).status_code == 403
    assert plain.post("/render").status_code == 403
    assert plain.get(PLAY, headers={"Referer": "https://example.com/"}).status_code == 403
    assert client.get(PLAY, headers={"Sec-Fetch-Site": "none"}).status_code == 403
    assert reaper.requests == []


def test_reading_works_for_players_and_command_line_tools(plain) -> None:
    # Native media players and ffmpeg send no browser headers.
    for path in ("/reaper/_/TRANSPORT", "/version", "/llhls/index.m3u8?cookieCheck=1"):
        assert plain.get(path).status_code == 200


def test_the_page_itself_opens_from_a_link_or_a_frame(client) -> None:
    for path in ("/", "/app.js", "/style.css"):
        assert client.get(path, headers=ELSEWHERE).status_code == 200
    assert client.get("/version", headers={"Sec-Fetch-Site": "none"}).status_code == 200


def test_the_mediamtx_example_allows_no_other_origins() -> None:
    text = (ROOT / "mediamtx" / "mediamtx.example.yml").read_text(encoding="utf-8")
    for key in ("hlsAllowOrigins", "webrtcAllowOrigins"):
        assert re.search(rf"^{key}: \[\]$", text, re.MULTILINE), key


@pytest.fixture
def plain(client) -> httpx.Client:
    """The same server, without the headers a browser adds."""
    del client.headers["Sec-Fetch-Site"]
    with httpx.Client(base_url=client.base_url, timeout=10) as http:
        yield http
    client.headers["Sec-Fetch-Site"] = "same-origin"
