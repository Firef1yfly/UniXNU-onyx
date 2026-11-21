"""Offline tests for the menu-only FAT probe; no firmware or device access."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

DEVICE = Path(__file__).resolve().parents[1]
SCRIPT = DEVICE / "scripts/make-menu-probe.py"
spec = importlib.util.spec_from_file_location("make_menu_probe", SCRIPT)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@unittest.skipUnless(all(shutil.which(tool) for tool in ("mformat", "mmd", "mcopy", "mtype")),
                     "requires mtools")
class MenuProbeTests(unittest.TestCase):
    def test_timeout_semantics(self):
        self.assertEqual(probe.effective_timeout(0, True, 86400), 0)
        self.assertEqual(probe.effective_timeout(-1, True, 86400), -1)
        self.assertEqual(probe.effective_timeout(-1, False, 86400), 86400000)
        with self.assertRaisesRegex(ValueError, "timeout=0"):
            probe.validate_menu_text(probe.menu_text(timeout=0))

    def test_config_is_payload_free_and_exactly_parseable(self):
        text = probe.menu_text()
        root = probe.validate_menu_text(text)
        self.assertEqual(root["boot"]["timeout"], -1)
        self.assertEqual(root["boot"]["fallback_timeout"], 86400)
        self.assertEqual(root["boot"]["default"], "probe")
        self.assertEqual(len(root["entry"]), 3)
        self.assertEqual(root["entry"][0]["action"], "tools")
        self.assertIn(probe.MARKER, text)
        self.assertNotIn("path =", text)
        self.assertNotIn("initrd =", text)
        self.assertEqual(text.encode("utf-8").decode("utf-8"), text)

    def test_fat_round_trip_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "menu-only.img"
            probe.build(image, size_mib=64)
            self.assertEqual(image.stat().st_size, 64 * 1024 * 1024)
            bpb = probe.inspect_bpb(image)
            self.assertEqual(bpb["fat_type"], "FAT32")
            self.assertEqual(bpb["bytes_per_sector"], 512)
            self.assertEqual(bpb["sectors_per_cluster"], 1)
            self.assertGreaterEqual(bpb["clusters"], probe.FAT32_MIN_CLUSTERS)
            text = probe.read_menu(image)
            self.assertEqual(text, probe.menu_text())
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),
                             "697ba173063bf4306e10e2789dc995c8cbf26a8dee77f513c016005ea0088fe8")
            listing = subprocess.run(
                ["mdir", "-i", str(image), "::/EFI/UniXNU"],
                check=True, capture_output=True, text=True,
            ).stdout
            self.assertIn("UNIXNU", listing)

    def test_rejects_16_mib_fat32_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "too-small.img"
            subprocess.run(["truncate", "-s", "16M", str(image)], check=True)
            subprocess.run(["mformat", "-F", "-c", "1", "-v", "TOOSMALL", "-i", str(image)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self.assertRaisesRegex(ValueError, "FAT32 has"):
                probe.inspect_bpb(image)
            with self.assertRaisesRegex(ValueError, "FAT32 has"):
                probe.read_menu(image)

    def test_rejects_corrupt_or_payload_config(self):
        invalid = [
            probe.menu_text(timeout=0),
            probe.menu_text().replace("version = 1", "version = 2", 1),
            probe.menu_text().replace('action = "tools"', 'action = "efi"', 1),
            probe.menu_text().replace('type = "action"', 'type = "xnu"', 1),
            probe.menu_text().replace('title = "MENU_ONLY_PROBE"', 'title = "missing"', 1),
            probe.menu_text() + '\n[[entry]]\ntype = "action"\naction = "exit"\npath = "Payloads/kernel.macho"\n',
        ]
        for text in invalid:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    probe.validate_menu_text(text)

    def test_existing_image_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "existing.img"
            image.write_bytes(b"sentinel")
            with self.assertRaisesRegex(ValueError, "existing output"):
                probe.build(image)
            self.assertEqual(image.read_bytes(), b"sentinel")


if __name__ == "__main__":
    unittest.main()
