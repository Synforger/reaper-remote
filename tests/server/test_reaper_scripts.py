"""The ReaScripts reaper-remote triggers must finish within the call.

reaper-remote runs them from web requests, some every few seconds. A script
that defers counts as running until REAPER's next idle cycle; a call arriving
before that opens a modal "already running" dialog, and while it is open REAPER
answers no web request at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).resolve().parents[2] / "reaper").glob("*.lua"))


def _code(path: Path) -> str:
    # Lua line comments start with `--`; the rule is about code, not the prose.
    return "\n".join(
        line.split("--", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()
    )


def test_there_are_scripts_to_check() -> None:
    assert {p.name for p in SCRIPTS} >= {
        "reaper-remote-loop.lua",
        "reaper-remote-render.lua",
        "reaper-remote-timeline.lua",
    }


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_never_defers(script: Path) -> None:
    assert not re.search(r"\breaper\.defer\s*\(", _code(script)), (
        f"{script.name} defers; see this module's docstring"
    )
