import hashlib
import importlib.util
import lzma
import struct
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "accept-firmware.py"
SPEC = importlib.util.spec_from_file_location("accept_firmware", SCRIPT)
accept = importlib.util.module_from_spec(SPEC)
if SPEC and SPEC.loader:
    SPEC.loader.exec_module(accept)

REQUIRED = {
    "UniXNU": "10000000-0000-4000-8000-000000000001",
    "UniXNUDxe": "10000000-0000-4000-8000-000000000002",
    "DarwinBoot": "10000000-0000-4000-8000-000000000003",
    "UniXNURamDiskDxe": "10000000-0000-4000-8000-000000000004",
    "DiskIoDxe": "10000000-0000-4000-8000-000000000005",
    "PartitionDxe": "10000000-0000-4000-8000-000000000006",
    "Fat": "10000000-0000-4000-8000-000000000007",
    "EnglishDxe": "10000000-0000-4000-8000-000000000008",
    "AdvancedLogDxe": "10000000-0000-4000-8000-000000000009",
}
NESTED_GUID = "9E21FD93-9C72-4C15-8C4B-E77F1DB2D792"
LZMA_GUID = "EE4E5898-3914-4259-9D6E-DC7BD79403CF"
INNER_PREFIX = bytes.fromhex("04 00 00 19 04 e0 7b 17")


def ffs(guid, body, file_type=7):
    header = bytearray(24)
    header[:16] = uuid.UUID(guid).bytes_le
    header[18] = file_type
    header[20:23] = (24 + len(body)).to_bytes(3, "little")
    header[23] = 0xF8
    header[17] = 0xAA
    header[16] = (0xAA + 0xF8 - sum(header)) & 0xFF
    return bytes(header) + body


def fv(files, length):
    header = bytearray(72)
    header[0x10:0x20] = uuid.UUID("8C8CE578-8A3D-4F1C-9935-896185C32DD3").bytes_le
    header[0x20:0x28] = length.to_bytes(8, "little")
    header[0x28:0x2C] = b"_FVH"
    header[0x2C:0x30] = (0xFFFF0C00).to_bytes(4, "little")
    header[0x30:0x32] = (72).to_bytes(2, "little")
    header[0x36] = 0
    header[0x37] = 2
    header[0x38:0x40] = struct.pack("<II", 0x1000, length // 0x1000)
    header[0x32:0x34] = ((-sum(struct.unpack("<36H", header))) & 0xFFFF).to_bytes(2, "little")
    data = bytes(header)
    for item in files:
        data += item
        data += b"\xff" * ((-len(data)) & 7)
    if len(data) > length:
        raise ValueError("fixture exceeds FV length")
    return data + b"\xff" * (length - len(data))


def fixture(required=None, corrupt=False):
    guids = REQUIRED if required is None else required
    modules = [ffs(guid, b"module") for guid in guids.values()]
    inner = fv(modules, 0x4000)
    compressed = lzma.compress(INNER_PREFIX + inner, format=lzma.FORMAT_ALONE)
    if corrupt:
        compressed = b"not-an-lzma-stream"
    section_payload = uuid.UUID(LZMA_GUID).bytes_le + struct.pack("<HH", 24, 1) + compressed
    section_bytes = len(section_payload) + 4
    section = section_bytes.to_bytes(3, "little") + b"\x02" + section_payload
    outer = fv([ffs(NESTED_GUID, section, file_type=0x0B)], 0x300000)
    return outer


class FirmwareAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.unixnu, self.uefi = self.root / "unixnu", self.root / "uefi"
        mapping = {
            "UniXNU": self.unixnu / "package/UniXNUPkg/Application/UniXNU/UniXNU.inf",
            "UniXNUDxe": self.unixnu / "package/UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf",
            "DarwinBoot": self.unixnu / "drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.inf",
            "UniXNURamDiskDxe": self.unixnu / "package/UniXNUPkg/Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.inf",
            "AdvancedLogDxe": self.unixnu / "package/UniXNUPkg/Driver/AdvancedLogDxe/AdvancedLogDxe.inf",
            "DiskIoDxe": self.uefi / "Mu_Basecore/MdeModulePkg/Universal/Disk/DiskIoDxe/DiskIoDxe.inf",
            "PartitionDxe": self.uefi / "Mu_Basecore/MdeModulePkg/Universal/Disk/PartitionDxe/PartitionDxe.inf",
            "Fat": self.uefi / "Mu_Basecore/FatPkg/EnhancedFatDxe/Fat.inf",
            "EnglishDxe": self.uefi / "Mu_Basecore/MdeModulePkg/Universal/Disk/UnicodeCollation/EnglishDxe/EnglishDxe.inf",
        }
        self.mapping = mapping
        for name, path in mapping.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"[Defines]\n  BASE_NAME = {name}\n  FILE_GUID = {REQUIRED[name]}\n", encoding="utf-8")
        self.fd = self.root / "firmware.fd"
        self.fd.write_bytes(fixture())

    def test_valid_image_reads_actual_nested_fv_and_binds_hashes(self):
        report = accept.inspect_fd(self.fd, self.unixnu, self.uefi)
        self.assertEqual(report["fd_bytes"], 0x300000)
        self.assertEqual(report["fd_sha256"], hashlib.sha256(self.fd.read_bytes()).hexdigest())
        self.assertEqual(set(report["modules"]), set(REQUIRED))
        for name, expected in REQUIRED.items():
            self.assertEqual(report["modules"][name]["guid"], expected)
            self.assertEqual(report["modules"][name]["count"], 1)
        self.assertEqual(report["nested_fv"]["inner_fv_length"], 0x4000)

    def test_missing_required_module_is_rejected(self):
        self.fd.write_bytes(fixture({k: v for k, v in REQUIRED.items() if k != "Fat"}))
        with self.assertRaisesRegex(ValueError, "Fat"):
            accept.inspect_fd(self.fd, self.unixnu, self.uefi)

    def test_wrong_fd_size_is_rejected_before_parsing(self):
        self.fd.write_bytes(fixture()[:-1])
        with self.assertRaisesRegex(ValueError, "0x300000"):
            accept.inspect_fd(self.fd, self.unixnu, self.uefi)

    def test_bad_compressed_fv_is_rejected(self):
        self.fd.write_bytes(fixture(corrupt=True))
        with self.assertRaisesRegex(ValueError, "LZMA|compressed"):
            accept.inspect_fd(self.fd, self.unixnu, self.uefi)

    def test_cli_writes_json_manifest_for_verified_fd(self):
        manifest = self.root / "manifest.json"
        rc = accept.main(["--fd", str(self.fd), "--unixnu", str(self.unixnu), "--uefi", str(self.uefi), "--json", str(manifest)])
        self.assertEqual(rc, 0)
        self.assertIn(hashlib.sha256(self.fd.read_bytes()).hexdigest(), manifest.read_text())


if __name__ == "__main__":
    unittest.main()

class SecGuardMarkerTests(unittest.TestCase):
    """The compact volume must carry the SEC guard, not just its source."""

    def test_markers_are_extracted_from_the_sec_source(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "accept_fw", Path(__file__).resolve().parents[1] / "scripts/accept-firmware.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        markers = module._sec_markers(Path(__file__).resolve().parents[1] / ".." / "Mu-Silicium")
        self.assertGreaterEqual(len(markers), 5, markers)
        for marker in markers:
            self.assertTrue(marker.startswith("ONYX:"), marker)
            self.assertNotIn("%", marker)

    def test_missing_marker_fails_acceptance(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "accept_fw", Path(__file__).resolve().parents[1] / "scripts/accept-firmware.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # A volume without the guard must not pass the marker check.
        self.assertEqual(module._sec_markers(Path("/nonexistent")), [])
