"""Read the open project tabs and the outcome of switching between them.

REAPER's web interface can neither list project tabs nor switch them.
`reaper/reaper-remote-projects.lua` publishes the tabs to an ExtState as JSON,
and `reaper/reaper-remote-project-select.lua` switches to a named tab and
reports how it went. Each is run and read back in one request, after clearing
the ExtState, so a missing or misregistered script reads as empty, never as a
stale answer.
"""

from __future__ import annotations

import json

LIST_KEY = "projects"
SELECT_KEY = "project_select"
RESULT_KEY = "project_select_result"


class ProjectsError(ValueError):
    """Raised when a script's ExtState is missing or malformed."""


def extstate(reply: str, section: str, key: str) -> str:
    """The value of one `GET/EXTSTATE` line in a REAPER reply ("" when absent)."""
    for line in reply.split("\n"):
        tok = line.split("\t")
        if tok[0] == "EXTSTATE" and tok[1:3] == [section, key]:
            # REAPER encodes newlines, tabs and backslashes inside the value.
            value = tok[3] if len(tok) > 3 else ""
            return value.replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
    return ""


def parse_list(reply: str, section: str) -> list[dict]:
    state = extstate(reply, section, LIST_KEY)
    if not state:
        raise ProjectsError("the projects script left no result (is projects.list_action right?)")
    try:
        tabs = json.loads(state)["tabs"]
        return [
            {
                "index": int(t["index"]),
                "name": str(t["name"]),
                "dirty": bool(t["dirty"]),
                "active": bool(t["active"]),
            }
            for t in tabs
        ]
    except (ValueError, KeyError, TypeError) as e:
        raise ProjectsError(f"unreadable projects result: {state[:80]!r}") from e


def parse_select(reply: str, section: str) -> str | None:
    """None when the switch happened, else the reason it did not."""
    result = extstate(reply, section, RESULT_KEY)
    if result == "ok":
        return None
    if not result:
        raise ProjectsError(
            "the project-select script left no result (is projects.select_action right?)"
        )
    return result.removeprefix("error: ")
