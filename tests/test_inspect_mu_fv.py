import hashlib
import importlib.util
import struct
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect-mu-fv.py"
SPEC = importlib.util.spec_from_file_location("inspect_mu_fv", SCRIPT)
mu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mu)
LZMA = Path("/home/firefly/UniXNU/Mu-Silicium/Mu_Basecore/BaseTools/Source/C/bin/LzmaCompress")


def checksum_header(header, skip=(17, 23)):
    header[17] = header[23] = 0
    header[17] = (-sum(header)) & 0xFF
    # The sum includes the State byte, which must be restored after calculation.
    header[23] = 0xF8
    header[17] = (-sum(header)) & 0xFF
    return bytes(header)


def ffs(file_guid, file_type=7, body=b"x"):
    h = bytearray(24)
    h[:16] = uuid.UUID(file_guid).bytes_le
    h[18] = file_type
    h[19] = 0
    h[20:23] = (24 + len(body)).to_bytes(3, "little")
    h[23] = 0xF8
    # Ordinary EDK2 FFS files use File checksum 0xAA; Header checksum is
    # selected so that sum(header) is zero (VerifyHeaderChecksum then
    # subtracts State and File checksum).
    h[17] = 0xAA
    h[16] = (0xAA + 0xF8 - sum(h)) & 0xFF
    return bytes(h) + body


def fv(files, length):
    h = bytearray(72)
    h[0x10:0x20] = uuid.UUID("8C8CE578-8A3D-4F1C-9935-896185C32DD3").bytes_le
    h[0x20:0x28] = length.to_bytes(8, "little")
    h[0x28:0x2C] = b"_FVH"
    h[0x2C:0x30] = (0xFFFF0C00).to_bytes(4, "little")
    h[0x30:0x32] = (72).to_bytes(2, "little")
    h[0x32:0x34] = (0).to_bytes(2, "little")
    h[0x34:0x36] = (0).to_bytes(2, "little")
    h[0x36] = 0
    h[0x37] = 2
    h[0x38:0x40] = struct.pack("<II", 0x1000, length // 0x1000)
    h[0x40:0x48] = b"\0" * 8
    # FV header checksum is a 16-bit sum over all 16-bit words.
    h[0x32:0x34] = (0).to_bytes(2, "little")
    h[0x32:0x34] = ((-sum(struct.unpack("<36H", h))) & 0xFFFF).to_bytes(2, "little")
    out = bytes(h) + b"\xff" * 0
    for item in files:
        out += item
        out += b"\xff" * ((-len(out)) & 7)
    return out + b"\xff" * (length - len(out))


def fixture():
    files = [ffs(g) for g in mu.KEY_GUIDS.values()]
    inner = fv(files, 0x4000)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        raw = d / "inner"
        enc = d / "enc"
        raw.write_bytes(inner)
        subprocess.run([str(LZMA), "-e", "-q", "-o", str(enc), str(raw)], check=True)
        compressed = enc.read_bytes()
    nested_guid = uuid.UUID(mu.NESTED_FFS_GUID).bytes_le
    section_guid = uuid.UUID(mu.LZMA_GUID).bytes_le
    section_body = section_guid + struct.pack("<HH", 24, 1) + compressed
    section = len(section_body) + 4
    section_blob = section.to_bytes(3, "little") + bytes([2]) + section_body
    nested = ffs(mu.NESTED_FFS_GUID, file_type=0x0B, body=section_blob)
    outer = fv([nested], 0x20000)
    return outer


@unittest.skipUnless(LZMA.is_file(), "EDK2 LzmaCompress is unavailable")
class InspectMuFv(unittest.TestCase):
    def valid(self):
        return mu.inspect_bytes(fixture(), LZMA, require_historical=False)

    def test_synthetic_valid_and_key_count(self):
        report = self.valid()
        self.assertEqual(report["inner_fv"]["ffs_count"], 12)
        self.assertEqual(len(report["key_guids"]), 12)

    def test_truncated_outer(self):
        with self.assertRaisesRegex(ValueError, "outside|truncated"):
            mu.inspect_bytes(fixture()[:-1], LZMA, require_historical=False)

    def test_duplicate_key_guid(self):
        data = bytearray(fixture())
        # The fixture's compressed bytes are intentionally not edited in-place;
        # duplicate/missing coverage is exercised by changing the key map.
        original = dict(mu.KEY_GUIDS)
        try:
            mu.KEY_GUIDS["Duplicate"] = mu.KEY_GUIDS["DiskIoDxe"]
            with self.assertRaisesRegex(ValueError, "exactly once"):
                mu.inspect_bytes(bytes(data), LZMA, require_historical=False)
        finally:
            mu.KEY_GUIDS.clear(); mu.KEY_GUIDS.update(original)

    def test_wrong_guid_defined_guid(self):
        data = bytearray(fixture())
        # Locate the nested file and its GUID-defined section in the outer FV.
        pos = 72
        section_guid_offset = pos + 24 + 4
        data[section_guid_offset] ^= 1
        with self.assertRaisesRegex(ValueError, "wrong GUID"):
            mu.inspect_bytes(bytes(data), LZMA, require_historical=False)

    def test_bad_lzma_rejected(self):
        data = bytearray(fixture())
        # Corrupt the last compressed byte; decoder must reject instead of accepting a prefix.
        data[-1] ^= 1
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            mu.inspect_bytes(bytes(data), LZMA, require_historical=False)

    def test_historical_size_gate(self):
        with self.assertRaisesRegex(ValueError, "exactly 0x300000"):
            mu.inspect_bytes(fixture(), LZMA, require_historical=True)


if __name__ == "__main__":
    unittest.main()
