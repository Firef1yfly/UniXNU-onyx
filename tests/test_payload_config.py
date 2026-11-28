#!/usr/bin/env python3
"""The payload checker must reject configs the firmware silently ignores."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEVICE = HERE.parent
sys.path.insert(0, str(HERE))
from host_fixtures import upstream  # noqa: E402  (sibling helper, not a test module)

SPEC = importlib.util.spec_from_file_location("payload_check", DEVICE / "scripts/check-payload-config.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
# The checker is diffed against the upstream firmware parser, which lives in the
# UniXNU checkout (UNIXNU_HOME, else a sibling ../UniXNU).
UPSTREAM, UPSTREAM_SKIP = upstream("package/UniXNUPkg/Library/UniXNULib/Config.c")
CONFIG_C = None if UPSTREAM is None else UPSTREAM / "package/UniXNUPkg/Library/UniXNULib/Config.c"


@unittest.skipIf(CONFIG_C is None, UPSTREAM_SKIP)
class PayloadConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "unixnu.toml"

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")
        return CHECK.check(self.path, CONFIG_C)

    def test_tools_is_an_entry_action_not_a_ui_key(self):
        problems = self.write('version = 1\n[ui]\ntools = true\n')
        self.assertTrue(any("'tools' is not read" in p for p in problems), problems)

    def test_valid_menu_payload_passes(self):
        problems = self.write(
            'version = 1\n[boot]\ntimeout = 10\n[ui]\ntitle = "x"\n'
            '[[entry]]\nid = "tools"\ntype = "action"\naction = "tools"\n')
        self.assertEqual(problems, [])

    def test_unsupported_action_is_reported(self):
        problems = self.write('version = 1\n[[entry]]\nid = "s"\ntype = "efi"\naction = "shell"\n')
        self.assertTrue(any("not handled" in p for p in problems), problems)

    def test_unknown_section_is_reported(self):
        problems = self.write('version = 1\n[payload]\ntools = true\n')
        self.assertTrue(any("unknown table [payload]" in p for p in problems), problems)

    def test_unknown_entry_key_is_reported(self):
        problems = self.write('version = 1\n[[entry]]\nid = "a"\ntype = "action"\naction = "reset"\nkernel = "x"\n')
        self.assertTrue(any("unknown key 'kernel'" in p for p in problems), problems)

    def test_surface_is_derived_from_the_parser(self):
        keys, actions, _lists = CHECK.parsed_surface(CONFIG_C)
        self.assertIn("timeout", keys["boot"])
        self.assertIn("title", keys["ui"])
        self.assertNotIn("tools", keys["ui"])
        self.assertEqual(actions, {"reset", "shutdown", "exit", "tools"})


if __name__ == "__main__":
    unittest.main()
