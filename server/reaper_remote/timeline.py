"""Read the project layout the seek bar draws: measures, markers, regions, loop.

REAPER's web interface reports markers and regions but not where measures
start, where the project ends or where the loop is. `reaper/reaper-remote-timeline.lua` publishes
those to an ExtState; one request clears that ExtState, runs the script, and
reads it back together with the marker and region lists, so a missing or
misregistered script shows up as an empty value instead of a stale one.
"""

from __future__ import annotations

EXTSTATE_KEY = "timeline"


class TimelineError(ValueError):
    """Raised when the script's ExtState is missing or malformed."""


def _unescape(value: str) -> str:
    # REAPER encodes newlines, tabs and backslashes inside string fields.
    return value.replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")


def _color(token: str) -> int:
    try:
        return int(token, 0)
    except ValueError:
        return 0


def parse(reply: str, section: str) -> dict:
    """Turn the reply of `<clear>;<action>;GET/EXTSTATE/...;MARKER;REGION` into JSON."""
    state = ""
    markers: list[dict] = []
    regions: list[dict] = []
    for line in reply.split("\n"):
        tok = line.split("\t")
        if tok[0] == "EXTSTATE" and tok[1:3] == [section, EXTSTATE_KEY]:
            state = tok[3] if len(tok) > 3 else ""
        elif tok[0] == "MARKER" and len(tok) >= 4:
            markers.append(
                {
                    "id": int(tok[2]),
                    "name": _unescape(tok[1]),
                    "pos": float(tok[3]),
                    "color": _color(tok[4]) if len(tok) > 4 else 0,
                }
            )
        elif tok[0] == "REGION" and len(tok) >= 5:
            regions.append(
                {
                    "id": int(tok[2]),
                    "name": _unescape(tok[1]),
                    "start": float(tok[3]),
                    "end": float(tok[4]),
                    "color": _color(tok[5]) if len(tok) > 5 else 0,
                }
            )

    if not state:
        raise TimelineError("the timeline script left no result (is timeline.action right?)")
    try:
        end_s, edges_s, loop_s = state.split("|")
        end = float(end_s)
        edges = [float(s) for s in edges_s.split(",") if s]
        loop_start, loop_end = (float(s) for s in loop_s.split(","))
    except ValueError as e:
        raise TimelineError(f"unreadable timeline result: {state[:80]!r}") from e
    if len(edges) < 2:
        raise TimelineError("the timeline script reported no measures")
    # edges[i] and edges[i + 1] bound measure i + 1.
    loop = {"start": loop_start, "end": loop_end} if loop_end > loop_start else None
    return {"end": end, "edges": edges, "loop": loop, "markers": markers, "regions": regions}
