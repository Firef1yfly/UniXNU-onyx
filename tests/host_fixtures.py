"""Resolve host-side checkouts and pinned artifacts these tests exercise.

Several modules need inputs that this repository does not own: the upstream
UniXNU checkout (``scripts/unixnu`` parsers, ``package/UniXNUPkg``) and the
artifacts of an earlier bring-up session (the stock boot image, the menu FAT and
the assembled menu-probe candidate).  Each location is asked for in the same
order:

1. the environment variable named at the call site,
2. the historical location the test used to hardcode.

A caller therefore keeps its assertions unchanged and only reports a skip when
neither exists, instead of failing on an absent sibling checkout.  Nothing here
relaxes a check: a resolved path goes through exactly the assertions that ran
when the path was a constant, and a resolved file with the wrong bytes still
fails.
"""
from __future__ import annotations

import os
from pathlib import Path

DEVICE = Path(__file__).resolve().parents[1]

#: Upstream checkout of UniXNU. ``board.toml`` records the same sibling
#: relationship as ``[package] unixnu = "../UniXNU"``.
UNIXNU_VARIABLE = "UNIXNU_HOME"
UNIXNU_MARKER = "scripts/unixnu/devicetree.py"


def _candidates(variable: str, candidates) -> list[Path]:
    override = os.environ.get(variable, "").strip()
    ordered = [Path(override).expanduser()] if override else []
    return ordered + [Path(candidate) for candidate in candidates]


def _reason(variable: str, paths, description: str) -> str:
    tried = ", ".join(str(path) for path in _candidates(variable, paths))
    return f"{description} not found; set {variable} (tried: {tried})"


def locate_checkout(variable: str, candidates, marker: str, description: str):
    """Return ``(path, None)`` for the first candidate holding marker, else ``(None, reason)``."""
    for path in _candidates(variable, candidates):
        if (path / marker).is_file():
            return path, None
    return None, _reason(variable, candidates, description)


def locate_file(variable: str, candidates, description: str):
    """Return ``(path, None)`` for the first candidate file that exists, else ``(None, reason)``."""
    for path in _candidates(variable, candidates):
        if path.is_file():
            return path, None
    return None, _reason(variable, candidates, description)


def upstream(marker: str = UNIXNU_MARKER):
    """Return ``(checkout, None)`` or ``(None, skip_reason)`` for the UniXNU tree."""
    return locate_checkout(
        UNIXNU_VARIABLE,
        (DEVICE.parent / "UniXNU", DEVICE.parent / "unixnu"),
        marker,
        f"UniXNU checkout with {marker}",
    )
