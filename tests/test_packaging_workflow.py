"""Pins the two CI workflows to what the device repository specification requires.

Neither workflow can run on this host (they need a macOS runner and a fork with
the `UNIXNU_UNIQUE_CHIP_ID` secret), so these are text-level guards on the two
properties that are cheap to break by hand and expensive to discover late:

* the packaging action must check for every tool its uploaded artefacts need,
  because the template's whole point is to fail fast by tool name instead of
  forty minutes into a build; and
* the board-specific values (firmware checkout, device name in the artefact
  paths, the packaging entry point) must be this board's, not the template's.

The checks are structural. They do not prove a workflow would pass, and nothing
here is evidence about the device.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

DEVICE = Path(__file__).resolve().parents[1]
PACKAGE = DEVICE / ".github/workflows/package.yml"
RECORD = DEVICE / ".github/workflows/porting-record.yml"

# The template (UniXNU examples/device/.github/workflows/package.yml) checks
# these before building. The kernel and IPSW entries are part of the packaging
# stage even while this port has no kernel inputs: package.sh builds
# kernel.macho and the action uploads it.
REQUIRED_TOOLS = (
    "clang", "xcodebuild", "make", "git", "ninja", "cmake", "dtc", "fdtget",
    "fdtput", "aea", "compression_tool", "mformat", "mcopy", "ipsw",
    "lld-link", "llvm-lib", "llvm-rc", "llvm-nm", "llvm-objcopy",
)

# Artefacts the packaging action uploads; the device name appears in each path.
REQUIRED_ARTIFACTS = (
    "boot/boot.img",
    "payload/payload.img",
    "kernel/kernel.macho",
    "package.manifest.json",
)


class PackagingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = PACKAGE.read_text(encoding="utf-8")

    def test_every_required_tool_is_checked(self):
        checked = set(re.findall(r"\b([a-z][a-z0-9_-]+)\b", self._tool_loop()))
        missing = [tool for tool in REQUIRED_TOOLS if tool not in checked]
        self.assertEqual(missing, [], f"packaging action no longer checks {missing}")

    def _tool_loop(self) -> str:
        """The fail-fast block, from its comment to the `ok` assertion."""
        start = self.text.index("Fail fast, naming the tool")
        end = self.text.index('[ "$ok" = 1 ]', start)
        return self.text[start:end]

    def test_artifact_paths_name_this_board(self):
        for suffix in REQUIRED_ARTIFACTS:
            with self.subTest(artifact=suffix):
                self.assertIn(suffix, self.text)
                line = next(line for line in self.text.splitlines() if suffix in line)
                self.assertIn("out/onyx/", line, line.strip())

    def test_no_template_placeholders_remain(self):
        self.assertNotIn("REPLACE/", self.text)

    def test_board_firmware_checkout_and_entry_point(self):
        self.assertIn("repository: Firef1yfly/Mu-Silicium", self.text)
        self.assertRegex(self.text, r"run: scripts/package\.sh --os .+ --uefi \.\./Mu-Silicium")

    def test_platform_seed_comes_from_the_secret_and_is_validated(self):
        self.assertIn("secrets.UNIXNU_UNIQUE_CHIP_ID", self.text)
        # The seed is baked into the images, so an invalid one must abort the run.
        self.assertIn("[0-9a-fA-F]{8}", self.text)


class PortingRecordWorkflowTests(unittest.TestCase):
    def test_record_check_runs_on_push_and_pull_request(self):
        text = RECORD.read_text(encoding="utf-8")
        self.assertIn("porting-record", text)
        self.assertIn("pull_request", text)
        self.assertIn("push", text)


if __name__ == "__main__":
    unittest.main()
