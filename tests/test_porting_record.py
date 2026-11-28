#!/usr/bin/env python3
"""The record check the shared workflow runs, before the push instead of after it.

`.github/workflows/porting-record.yml` calls `UniXNU/UniXNU`'s checker with the
push range, and that check is easy to pass locally by accident: without `--base`
it validates the record's structure and stops, so a commit that changes an owned
path without updating that area's findings looks green here and fails on the
remote. Running it with `--base origin/main` is what the workflow does.

The checker itself lives in the UniXNU checkout, which this repository does not
carry, so the test skips (with a reason) when no checkout is present - the same
rule the other host tests use for upstream sources.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from host_fixtures import upstream  # noqa: E402  (sibling helper, not a test module)

DEVICE = Path(__file__).resolve().parents[1]
UPSTREAM, UPSTREAM_SKIP = upstream("scripts/porting-record.py")


def checker() -> Path | None:
    if UPSTREAM is None:
        return None
    path = UPSTREAM / "scripts/porting-record.py"
    return path if path.is_file() else None


def base_revision() -> str | None:
    """origin/main, which is the range base the workflow uses."""
    result = subprocess.run(["git", "-C", str(DEVICE), "rev-parse", "--verify", "origin/main"],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


class RecordTests(unittest.TestCase):
    def test_structure_and_owned_areas_match_the_push_range(self):
        path, base = checker(), base_revision()
        if path is None:
            self.skipTest(UPSTREAM_SKIP)
        if base is None:
            self.skipTest("no origin/main in this clone; the push range is unknown")
        result = subprocess.run([sys.executable, str(path), "check", "--device", str(DEVICE),
                                 "--base", base], capture_output=True, text=True)
        self.assertEqual(
            result.returncode, 0,
            "the shared record check rejects this working tree against origin/main; the same "
            "check runs on push:\n" + result.stdout + result.stderr)
        self.assertIn("structured areas checked", result.stdout)

    def test_the_record_parses_without_the_checker(self):
        """A broken porting.toml fails here even with no upstream checkout."""
        import tomllib
        record = tomllib.loads((DEVICE / "porting.toml").read_text(encoding="utf-8"))
        self.assertEqual(record["device"]["name"], "onyx")
        self.assertTrue(record["area"])
        for area in record["area"]:
            self.assertTrue(area.get("paths"), f'{area["id"]}: no owned paths')
            for item in area.get("evidence", []):
                reference = item["reference"]
                if reference.startswith("https://"):
                    continue
                self.assertTrue((DEVICE / reference).is_file(),
                                f'{area["id"]}: evidence file missing: {reference}')


if __name__ == "__main__":
    unittest.main()
