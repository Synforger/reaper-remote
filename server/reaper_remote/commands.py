"""The REAPER web commands the page uses, and which of them change REAPER.

Called by the relay in app.py; nothing here touches a file or the network. A
button that sends a new command needs its form added here: anything else is
not relayed.
"""

from __future__ import annotations

import re

METRONOME_ACTION = "40364"
# Play, pause, stop, go to start, metronome (main section action IDs).
BUTTON_ACTIONS = ("1007", "1008", "1016", "40042", METRONOME_ACTION)

READ_COMMANDS = frozenset({"TRANSPORT", "TRACK", f"GET/{METRONOME_ACTION}"})

_DECIMAL = r"[0-9]+(?:\.[0-9]+)?"
_CHANGE = re.compile(
    "|".join(
        (
            *BUTTON_ACTIONS,
            r"SET/REPEAT/[01]",
            # A position that rounds to zero can be written "-0.000000".
            rf"SET/POS/-?{_DECIMAL}",
            r"SET/TRACK/[0-9]+/(?:MUTE|SOLO)/-1",
            rf"SET/TRACK/[0-9]+/VOL/{_DECIMAL}",
        )
    )
)


def is_relayed(commands: str) -> bool:
    """Whether every `;`-separated command is one the page uses."""
    return all(c in READ_COMMANDS or _CHANGE.fullmatch(c) for c in commands.split(";"))


def is_change(commands: str) -> bool:
    """Whether any of the commands does more than read."""
    return any(c not in READ_COMMANDS for c in commands.split(";"))
