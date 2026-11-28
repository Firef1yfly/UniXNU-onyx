#!/usr/bin/env python3
"""Check a menu-only payload against the keys UniXNULib/Config.c actually parses.

UniXNU ignores unknown keys silently, so a plausible-looking `[ui] tools = true`
produces a menu with no Tools entry and no error. This check extracts the read
patterns from the C parser and fails when the payload uses a section, key or
action the firmware never consumes.
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

GET = re.compile(r'TomlGet\w*\s*\(\s*(?P<table>Boot|Ui|Kits|Root)\s*,\s*"(?P<key>[a-z_0-9]+)"')
ACTION = re.compile(r'AsciiStrCmp \(Action, "(?P<name>[a-z_]+)"\)')
TABLE_FOR = {"Root": None, "Boot": "boot", "Ui": "ui", "Kits": "kits"}
ENTRY_KEYS = ("id", "title", "type", "path", "args", "dtb", "initrd", "action", "chosen", "variable")
ENTRY_TABLES = ("chosen", "variable")
ROOT_LISTS = ("entry", "driver", "kit", "dt_patch", "block_slice")
ROOT_TABLES = ("boot", "ui", "kits", "acpi")


def parsed_surface(config_c: Path) -> tuple[dict, set, set]:
    """Return the per-section key sets and the supported actions from the parser."""
    keys: dict[str, set] = {"root": set(), "boot": set(), "ui": set(), "kits": set()}
    actions: set = set()
    lists: set = set()
    text = config_c.read_text(encoding="utf-8", errors="replace")
    for match in GET.finditer(text):
        section = TABLE_FOR[match["table"]]
        keys["root" if section is None else section].add(match["key"])
    for match in ACTION.finditer(text):
        actions.add(match["name"])
    # Root-level tables/lists are fetched with the same helper.
    for name in ROOT_LISTS:
        if re.search(rf'TomlGet \(\s*Root\s*,\s*"{name}"', text):
            lists.add(name)
    return keys, actions, lists


def check(payload: Path, config_c: Path) -> list[str]:
    keys, actions, lists = parsed_surface(config_c)
    try:
        document = tomllib.loads(payload.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        return [f"cannot read payload: {error}"]

    problems: list[str] = []
    if document.get("version") != 1:
        problems.append("version must be 1")

    for section, values in document.items():
        if not isinstance(values, dict):
            # Scalar root keys such as `version` are read directly.
            if section not in keys["root"]:
                problems.append(f"unknown root key '{section}'")
            continue
        if section in lists:
            continue
        if section not in ROOT_TABLES:
            problems.append(f"unknown table [{section}]")
            continue
        if not isinstance(values, dict):
            problems.append(f"[{section}] must be a table")
            continue
        for key in values:
            if key not in keys[section]:
                problems.append(f"[{section}] key '{key}' is not read by Config.c")

    for index, entry in enumerate(document.get("entry", [])):
        if not isinstance(entry, dict):
            problems.append(f"entry {index} must be a table")
            continue
        for key in entry:
            if key not in ENTRY_KEYS:
                problems.append(f"entry {index}: unknown key '{key}'")
                continue
            if key in ENTRY_TABLES:
                continue
        action = entry.get("action")
        if action is not None and action not in actions:
            problems.append(f"entry {index}: action '{action}' is not handled by Config.c")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path, help="unixnu.toml to check")
    parser.add_argument("--unixnu", type=Path, required=True, help="UniXNU checkout")
    parser.add_argument("--require-tools", action="store_true", help="fail unless a Tools entry exists")
    args = parser.parse_args(argv)
    config_c = args.unixnu / "package/UniXNUPkg/Library/UniXNULib/Config.c"
    if not config_c.is_file():
        print(f"ERROR: parser source not found: {config_c}", file=sys.stderr)
        return 1
    problems = check(args.payload, config_c)
    if args.require_tools:
        try:
            entries = tomllib.loads(args.payload.read_text(encoding="utf-8")).get("entry", [])
        except (OSError, tomllib.TOMLDecodeError):
            entries = []
        if not any(e.get("action") == "tools" for e in entries if isinstance(e, dict)):
            problems.append("no entry uses action = 'tools'; the QR log exporter is unreachable")
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"{args.payload}: keys and actions match {config_c.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
