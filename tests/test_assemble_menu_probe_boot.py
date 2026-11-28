"""Offline checks for the single-variable menu-probe assembler.

Three groups of tests live here and they need different inputs:

* the pinned input tests re-derive the recorded bytes, so they need the real
  stock boot image, the real menu FAT and the real assembled candidate;
* the validation-order tests need a real pinned source but only a bogus ramdisk;
* the preflight and atomicity tests assert path/output policy and use tiny
  synthetic fixtures, so they always run.

The real artifacts are named by UNIXNU_HOME's siblings or by ONYX_BOOT_IMAGE,
ONYX_MENU_FAT and ONYX_MENU_PROBE_CANDIDATE; a host without them skips with a
reason instead of failing.
"""
import hashlib
import importlib.util
import os
import shutil
import struct
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
DEVICE = HERE.parent
sys.path.insert(0, str(HERE))
from host_fixtures import locate_file  # noqa: E402  (sibling helper, not a test module)

SCRIPT = DEVICE / "scripts/assemble-menu-probe-boot.py"
SPEC = importlib.util.spec_from_file_location("assemble_menu_probe_boot", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

# Pinned historical source: the UniXNU output path the record names, else the
# stock boot image this machine keeps at the top of the home directory.
SOURCE, SOURCE_SKIP = locate_file(
    "ONYX_BOOT_IMAGE",
    (Path("/home/firefly/UniXNU/out/onyx/ios-17.7.11-21H461/example/boot/boot.img"),
     Path("/home/firefly/onyx_boot.img")),
    "pinned historical stock boot image")
RAMDISK, RAMDISK_SKIP = locate_file(
    "ONYX_MENU_FAT",
    (DEVICE / "out/onyx-bringup/menu-fat/menu-only-fat32-64m.img",
     Path("/home/firefly/UniXNU/out/onyx-bringup/menu-fat/menu-only-fat32-64m.img")),
    "pinned menu FAT payload")
CANDIDATE, CANDIDATE_SKIP = locate_file(
    "ONYX_MENU_PROBE_CANDIDATE",
    (DEVICE / "out/onyx-bringup/config-discovery/menu-probe-boot.img",),
    "pinned menu-probe candidate image")


def tiny_v4(path: Path, *, kernel: bytes, ramdisk: bytes) -> dict:
    header = bytearray(probe.PAGE)
    header[:8] = b"ANDROID!"
    struct.pack_into("<4I", header, 8, len(kernel), len(ramdisk), 0, 1584)
    struct.pack_into("<I", header, 40, 4)
    struct.pack_into("<I", header, 1580, probe.PAGE)
    raw = bytes(header) + kernel + bytes(probe.align(len(kernel)) - len(kernel))
    raw += ramdisk + bytes(probe.align(len(ramdisk)) - len(ramdisk)) + bytes(probe.PAGE)
    path.write_bytes(raw)
    return probe._scan_image(path)


@contextmanager
def synthetic_inputs(directory: Path):
    """Yield tiny pinned-like inputs for the path-policy and atomicity tests.

    Nothing here is a device artifact: the three paths only have to exist, so the
    preflight, readback and cleanup rules can be asserted without the real
    multi-hundred-megabyte inputs.
    """
    directory = Path(directory)
    source = directory / "source.img"
    ramdisk = directory / "ramdisk.img"
    mkbootimg = directory / "mkbootimg-stub.py"
    # Keep a nonzero shim prefix, followed by the 32-byte FD and an 8-byte FDT.
    kernel = b"S" * 16 + b"F" * 32 + struct.pack(">II", 0xD00DFEED, 8)
    tiny_v4(source, kernel=kernel, ramdisk=b"S" * 2048)
    ramdisk.write_bytes(b"R" * 2048)
    mkbootimg.write_text("# patched subprocess stub\n", encoding="utf-8")
    try:
        yield source, ramdisk, mkbootimg
    finally:
        # TemporaryDirectory owns cleanup; no shared or pre-existing artifact
        # is touched by this fixture.
        pass


class MenuProbeBootTests(unittest.TestCase):
    def needs(self, path, reason):
        """Skip when a pinned host artifact is absent; the assertion cannot stand in for it."""
        if path is None:
            self.skipTest(reason)
        return path

    def test_pinned_inputs(self):
        if shutil.which("mdir") is None:
            self.skipTest("requires mtools mdir to read the menu FAT")
        source = probe.assert_historical_source(self.needs(SOURCE, SOURCE_SKIP))
        fat = probe.assert_menu_fat(self.needs(RAMDISK, RAMDISK_SKIP))
        self.assertEqual(source["image_bytes"], 205361152)
        self.assertEqual(source["kernel_bytes"], 4025169)
        self.assertEqual(source["ramdisk_bytes"], 201326592)
        self.assertEqual(fat["bytes"], 67108864)
        self.assertEqual(fat["config_bytes"], 394)
        self.assertEqual(fat["entries"], ["::/EFI/", "::/EFI/UniXNU/", "::/EFI/UniXNU/unixnu.toml"])

    def test_existing_candidate_hash_and_final_path_readback(self):
        candidate = self.needs(CANDIDATE, CANDIDATE_SKIP)
        self.assertTrue(candidate.is_file())
        self.assertEqual(probe.sha256_file(candidate),
                         "4a33c186869e9c82529891c8ca85913ef75577b439b94e8d5af455b37613616f")
        report = probe._scan_image(candidate)
        self.assertEqual(report["image_bytes"], 71143424)
        self.assertEqual(report["kernel_sha256"],
                         "a9a3e200f0bfe9e2acb0f06cdb66dbc9e10ae2168cb65df4891fc5eee211477c")
        self.assertEqual(report["ramdisk_sha256"], probe.RAMDISK_SHA256)
        self.assertTrue(report["signature_zero"])
        self.assertEqual(probe._hash_segment(candidate, probe.PAGE, probe.FD_OFFSET_IN_KERNEL),
                         "7d40b171cb39a311d522bada00df2d857046fd1ef109462494d1f5c50a606594")

    def test_refuse_existing_output(self):
        with tempfile.TemporaryDirectory(prefix="onyx-menu-probe-test-") as directory:
            directory = Path(directory)
            with synthetic_inputs(directory) as (source, ramdisk, mkbootimg):
                output = directory / "candidate.img"
                output.write_bytes(b"preserve me")
                with self.assertRaisesRegex(ValueError, "refusing existing output"):
                    probe.assemble(source, ramdisk, output, mkbootimg)
                self.assertEqual(output.read_bytes(), b"preserve me")

    def test_reject_nonhistorical_source(self):
        with tempfile.TemporaryDirectory(prefix="onyx-menu-probe-test-") as directory:
            directory = Path(directory)
            with synthetic_inputs(directory) as (_, ramdisk, mkbootimg):
                source = directory / "not-historical.img"
                source.write_bytes(b"not the pinned image")
                with self.assertRaisesRegex(ValueError, "does not match pinned historical"):
                    probe.assemble(source, ramdisk, directory / "candidate.img", mkbootimg)

    def test_reject_nonmenu_ramdisk(self):
        source = self.needs(SOURCE, SOURCE_SKIP)
        with tempfile.TemporaryDirectory(prefix="onyx-menu-probe-test-") as directory:
            directory = Path(directory)
            with synthetic_inputs(directory) as (_, _stub_source, mkbootimg):
                ramdisk = directory / "ramdisk.img"
                ramdisk.write_bytes(b"not the pinned menu FAT")
                with self.assertRaisesRegex(ValueError, "does not match pinned"):
                    probe.assemble(source, ramdisk, directory / "candidate.img", mkbootimg)

    def _atomic_assemble(self, directory: Path, *, report_failure=False, validation_failure=False):
        with synthetic_inputs(directory) as (source, ramdisk, mkbootimg):
            output = Path(directory) / "output.img"
            report_path = Path(directory) / "report.json"
            source_report = probe._scan_image(source)
            fat_report = {"sha256": probe.sha256_file(ramdisk), "bytes": ramdisk.stat().st_size,
                          "entries": [], "config_bytes": 0,
                          "config_sha256": hashlib.sha256(b"").hexdigest()}

            def fake_run(command, **kwargs):
                candidate = Path(command[command.index("--output") + 1])
                kernel = Path(command[command.index("--kernel") + 1]).read_bytes()
                tiny_v4(candidate, kernel=kernel, ramdisk=ramdisk.read_bytes())

            segments = {name: {"bytes": size, "source_sha256": hashlib.sha256(b"" * 0).hexdigest(),
                               "candidate_sha256": hashlib.sha256(b"" * 0).hexdigest(), "unchanged": True}
                        for name, size in (("shim", 16), ("fd", 32), ("dtb", 8))}
            with patch.object(probe, "FD_OFFSET_IN_KERNEL", 16), \
                 patch.object(probe, "FD_BYTES", 32), \
                 patch.object(probe, "assert_historical_source", return_value=source_report), \
                 patch.object(probe, "assert_menu_fat", return_value=fat_report), \
                 patch.object(probe.subprocess, "run", side_effect=fake_run), \
                 patch.object(probe, "_validate_candidate",
                              side_effect=ValueError("tampered final") if validation_failure else None,
                              return_value=None if validation_failure else ([15], segments)), \
                 patch.object(probe, "_write_report", side_effect=OSError("report full") if report_failure else None,
                              wraps=None if report_failure else probe._write_report):
                probe.assemble(source, ramdisk, output, mkbootimg, report_path)
            return output, report_path

    def test_report_collision_does_not_leave_output(self):
        with tempfile.TemporaryDirectory(prefix="onyx-menu-probe-test-") as directory:
            directory = Path(directory)
            with synthetic_inputs(directory) as (source, ramdisk, mkbootimg):
                output = directory / "candidate.img"
                report = directory / "report.json"
                report.write_text("preserve me", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "refusing existing report"):
                    probe.assemble(source, ramdisk, output, mkbootimg, report)
                self.assertFalse(output.exists())
                self.assertEqual(report.read_text(encoding="utf-8"), "preserve me")

    def test_output_and_report_same_path_rejected(self):
        with tempfile.TemporaryDirectory(prefix="onyx-menu-probe-test-") as directory:
            directory = Path(directory)
            with synthetic_inputs(directory) as (source, ramdisk, mkbootimg):
                path = directory / "same"
                with self.assertRaisesRegex(ValueError, "different paths"):
                    probe.assemble(source, ramdisk, path, mkbootimg, path)
                self.assertFalse(path.exists())

    def test_synthetic_report_failure_removes_only_our_output(self):
        with tempfile.TemporaryDirectory(prefix="onyx-menu-probe-test-") as directory:
            with self.assertRaisesRegex(OSError, "report full"):
                self._atomic_assemble(Path(directory), report_failure=True)
            self.assertFalse(Path(directory, "output.img").exists())
            self.assertFalse(Path(directory, "report.json").exists())

    def test_synthetic_final_readback_failure_removes_our_output(self):
        with tempfile.TemporaryDirectory(prefix="onyx-menu-probe-test-") as directory:
            with self.assertRaisesRegex(ValueError, "tampered final"):
                self._atomic_assemble(Path(directory), validation_failure=True)
            self.assertFalse(Path(directory, "output.img").exists())
            self.assertFalse(Path(directory, "report.json").exists())

    def test_synthetic_shim_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="onyx-menu-probe-test-") as directory:
            directory = Path(directory)
            source = directory / "source.img"
            candidate = directory / "candidate.img"
            ramdisk = b"R" * 2048
            source_kernel = b"S" * 16 + b"F" * 32 + struct.pack(">II", 0xD00DFEED, 8)
            candidate_kernel = b"T" * 16 + source_kernel[16:]
            source_report = tiny_v4(source, kernel=source_kernel, ramdisk=ramdisk)
            candidate_report = tiny_v4(candidate, kernel=candidate_kernel, ramdisk=ramdisk)
            candidate_report["kernel_sha256"] = source_report["kernel_sha256"]
            source_header = bytearray(source_report["header"])
            candidate_header = bytearray(candidate_report["header"])
            source_header[15], candidate_header[15] = 12, 4
            source_report["header"], candidate_report["header"] = bytes(source_header), bytes(candidate_header)
            fat_report = {"sha256": hashlib.sha256(ramdisk).hexdigest(), "bytes": len(ramdisk)}
            with patch.object(probe, "FD_OFFSET_IN_KERNEL", 16), patch.object(probe, "FD_BYTES", 32):
                with self.assertRaisesRegex(ValueError, "shim changed"):
                    probe._validate_candidate(source, source_report, Path(directory) / "ramdisk", fat_report,
                                              candidate, candidate_report)

        class FailingFile:
            def __init__(self, wrapped): self.wrapped = wrapped
            def __enter__(self): return self
            def __exit__(self, *args): return self.wrapped.__exit__(*args)
            def fileno(self): return self.wrapped.fileno()
            def write(self, data):
                self.wrapped.write(data[:1])
                raise OSError("quota")

        with tempfile.TemporaryDirectory(prefix="onyx-menu-probe-test-") as directory:
            directory = Path(directory)
            source, output = directory / "source", directory / "output"
            source.write_bytes(b"abc")
            original = Path.open

            def faulty_open(path, mode="r", *args, **kwargs):
                opened = original(path, mode, *args, **kwargs)
                return FailingFile(opened) if path == output and mode == "xb" else opened

            with patch.object(Path, "open", faulty_open):
                with self.assertRaisesRegex(OSError, "quota"):
                    probe._copy_file_exclusive(source, output)
            self.assertFalse(output.exists())

    def test_cleanup_does_not_delete_replacement_inode(self):
        with tempfile.TemporaryDirectory(prefix="onyx-menu-probe-test-") as directory:
            path = Path(directory) / "output"
            path.write_bytes(b"ours")
            info = os.lstat(path)
            identity = (info.st_dev, info.st_ino)
            path.unlink()
            path.write_bytes(b"replacement")
            probe._unlink_owned(path, identity)
            self.assertEqual(path.read_bytes(), b"replacement")

    def test_streaming_source_does_not_return_large_fields(self):
        report = probe.assert_historical_source(self.needs(SOURCE, SOURCE_SKIP), load_data=False)
        self.assertNotIn("kernel", report)
        self.assertNotIn("ramdisk", report)
        self.assertEqual(report["kernel_sha256"], "a9a3e200f0bfe9e2acb0f06cdb66dbc9e10ae2168cb65df4891fc5eee211477c")


if __name__ == "__main__":
    unittest.main()
