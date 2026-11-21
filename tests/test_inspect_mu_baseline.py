import hashlib
import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect-mu-baseline.py"
SPEC = importlib.util.spec_from_file_location("inspect_mu_baseline", SCRIPT)
mu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mu)


def fixture():
    header = bytearray(mu.PAGE)
    header[:8] = b"ANDROID!"
    struct.pack_into("<4I", header, 8, *mu.GEOMETRY)
    struct.pack_into("<I", header, 40, 4)
    struct.pack_into("<I", header, 1580, mu.PAGE)
    shim = bytearray(mu.SHIM_SIZE)
    shim[56:60] = b"ARM\x64"
    struct.pack_into("<Q", shim, 16, mu.SHIM_SIZE + mu.FD_SIZE)
    tree = struct.pack(">II32x", 0xd00dfeed, 40)
    kernel = shim + bytes(mu.FD_SIZE) + tree
    return header + kernel + bytes(-len(kernel) % mu.PAGE) + bytes(mu.PAGE) + bytes(mu.PAGE)


class InspectMuBaseline(unittest.TestCase):
    def inspect(self, transform=None):
        with patch.object(mu, "FD_SIZE", 128), patch.object(mu, "GEOMETRY", (296, 4096, 0, 1584)):
            original = fixture()
            with patch.object(mu, "PIN", hashlib.sha256(original).hexdigest()):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "image"
                    path.write_bytes(transform(original) if transform else original)
                    return mu.inspect(path)

    def test_offsets(self):
        report = self.inspect()
        self.assertEqual(report["compression"], "none")
        self.assertEqual(report["shim"]["offset"], 4096)
        self.assertEqual(report["fd"]["offset"], 4096 + 128)
        self.assertEqual(report["dtb"]["offset"], 4096 + 256)
        self.assertEqual(report["ramdisk"]["offset"], 8192)
        self.assertEqual(report["v4_signature"]["offset"], 12288)

    def test_tampered_payload(self):
        def mutate(data):
            data[8192] ^= 1
            return data

        with self.assertRaisesRegex(ValueError, "pinned historical SHA-256"):
            self.inspect(mutate)

    def test_tail_rejected(self):
        with self.assertRaisesRegex(ValueError, "no trailing data"):
            self.inspect(lambda data: data + b"x")

    def test_short_ramdisk(self):
        with self.assertRaisesRegex(ValueError, "short ramdisk"):
            self.inspect(lambda data: data[:8200])

    def test_nonhistorical_arm64_header(self):
        def mutate(data):
            struct.pack_into("<Q", data, 4096 + 8, 0xa7100000)
            return data

        with self.assertRaisesRegex(ValueError, "historical ARM64 header"):
            self.inspect(mutate)


if __name__ == "__main__":
    unittest.main()
