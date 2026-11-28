#!/usr/bin/env python3
"""Host-side tests for scripts/check-firmware-inputs.py.

The script is the board's `[firmware] preflight` gate, so these tests build the
two trees it reads -- a device repository with a patch series and a Mu-Silicium
checkout -- in a temporary directory and check what it refuses.

Nothing here is a firmware or device result. A green run says the gate names the
right problem for a fixture that has that problem, not that any volume boots.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEVICE = HERE.parent
SPEC = importlib.util.spec_from_file_location("firmware_inputs",
                                              DEVICE / "scripts/check-firmware-inputs.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)

DSC = "Platforms/Xiaomi/onyxPkg/onyx.dsc"
FDF = "Platforms/Xiaomi/onyxPkg/onyx.fdf"
MU_CONFIG = "Resources/Configs/onyx.toml"
TARGET = "Silicon/Silicium/SiliciumPkg/Sec/Sec.c"


def mu_config(**overrides) -> str:
    values = {"base": "0xA7100000", "size": "0x300000", "compression": "none",
              "header_version": "4", "kernel_header": "true"}
    values.update(overrides)
    return (
        "[boot_shim]\n"
        f"requires_kernel_header = {values['kernel_header']}\n"
        "\n"
        "[uefi_fd]\n"
        f"base = {values['base']}\n"
        f"size = {values['size']}\n"
        "\n"
        "[boot_image_kernel]\n"
        f'kernel_compression = "{values["compression"]}"\n'
        "\n"
        "[boot_image]\n"
        f"header_version = {values['header_version']}\n"
    )


def board_toml(compression: str = "none") -> str:
    return (
        '[board]\nname = "onyx"\n\n'
        "[firmware]\n"
        'config = "onyx"\n'
        f'dsc = "{DSC}"\n'
        'fd = "Build/onyxPkg/{target}_CLANGPDB/FV/SILICIUM_UEFI.fd"\n'
        'preflight = ["scripts/check-firmware-inputs.py"]\n\n'
        "[bootimg.image]\n"
        f'kernel_compression = "{compression}"\n'
    )


def dsc_text() -> str:
    return ("[BuildOptions]\n"
            "  CLANGPDB:*_*_*_DLINK_FLAGS = /FILEALIGN:0x1000 /Brepro\n"
            "  *_CLANGPDB_AARCH64_CC_FLAGS = -DONYX_FDT_HANDOFF=1\n"
            "[LibraryClasses]\n"
            "  FdtLib|MdePkg/Library/BaseFdtLib/BaseFdtLib.inf\n")


def fdf_text() -> str:
    return "[FV.DXEFV]\n" + "\n".join(f"  INF {line}" for line in CHECK.REQUIRED_FDF_LINES) + "\n"


class Fixture:
    """A device repository plus a git-backed Mu-Silicium checkout."""

    def __init__(self, root: Path):
        self.root = root
        self.device = root / "device"
        self.uefi = root / "uefi"
        (self.device / "patches" / "uefi").mkdir(parents=True)
        (self.uefi / "Platforms/Xiaomi/onyxPkg").mkdir(parents=True)
        (self.uefi / "Resources/Configs").mkdir(parents=True)
        (self.uefi / "Silicon/Silicium/SiliciumPkg/Sec").mkdir(parents=True)
        (self.uefi / "UniXNUPkg/Driver/UniXNUDxe").mkdir(parents=True)
        (self.uefi / "UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf").write_text("")
        self.write_uefi(TARGET, "guarded sec\n")
        self.write_uefi(DSC, dsc_text())
        self.write_uefi(FDF, fdf_text())
        self.write_uefi(MU_CONFIG, mu_config())
        self.write_board(board_toml())
        self.git("init", "--quiet")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        self.write_patch_series()

    def git(self, *arguments):
        return subprocess.run(["git", "-C", str(self.uefi), *arguments], check=True,
                              capture_output=True, text=True)

    def write_uefi(self, relative, text):
        path = self.uefi / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_board(self, text):
        (self.device / "board.toml").write_text(text, encoding="utf-8")

    def write_patch_series(self):
        """One patch whose recorded endpoint is the current Sec.c blob."""
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", "base")
        blob = self.git("hash-object", TARGET).stdout.strip()
        (self.device / "patches/uefi/0001-fixture.patch").write_text(
            f"diff --git a/{TARGET} b/{TARGET}\n"
            f"index 0000000..{blob}\n"
            f"--- a/{TARGET}\n"
            f"+++ b/{TARGET}\n"
            "@@ -1 +1 @@\n-guarded sec\n+guarded sec\n",
            encoding="utf-8")
        return blob

    def run(self, *arguments, require=False):
        argv = ["--device", str(self.device), "--uefi", str(self.uefi), *arguments]
        if require:
            argv.append("--require-uefi")
        stdout, stderr = io.StringIO(), io.StringIO()
        saved = dict(os.environ)
        for name in ("UNIXNU_UEFI", "UNIXNU_DEVICE"):
            os.environ.pop(name, None)
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = CHECK.main(argv)
        finally:
            os.environ.clear()
            os.environ.update(saved)
        return code, stdout.getvalue(), stderr.getvalue()


class FirmwareInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = Fixture(Path(self.temp.name))

    def test_a_reviewed_tree_passes(self):
        code, stdout, _ = self.fixture.run()
        self.assertEqual(code, CHECK.EXIT_OK)
        self.assertIn("match the endpoint", stdout)

    def test_a_drifted_file_fails_and_names_both_blobs(self):
        self.fixture.write_uefi(TARGET, "something else\n")
        code, stdout, _ = self.fixture.run()
        self.assertEqual(code, CHECK.EXIT_FAILED)
        self.assertIn(TARGET, stdout)
        self.assertIn("want", stdout)

    def test_a_file_outside_the_series_fails_with_a_missing_blob(self):
        (self.fixture.uefi / "Platforms/Xiaomi/onyxPkg/onyx.fdf").unlink()
        code, stdout, _ = self.fixture.run()
        self.assertEqual(code, CHECK.EXIT_FAILED)
        self.assertIn(FDF, stdout)

    def test_compression_disagreement_names_both_sides(self):
        self.fixture.write_board(board_toml(compression="gzip"))
        code, stdout, _ = self.fixture.run()
        self.assertEqual(code, CHECK.EXIT_FAILED)
        self.assertIn("gzip", stdout)
        self.assertIn("none", stdout)

    def test_a_mu_config_with_the_wrong_size_fails(self):
        self.fixture.write_uefi(MU_CONFIG, mu_config(size="0x200000"))
        code, stdout, _ = self.fixture.run()
        self.assertEqual(code, CHECK.EXIT_FAILED)
        self.assertIn("3 MiB", stdout)

    def test_a_missing_guard_switch_fails(self):
        self.fixture.write_uefi(DSC, dsc_text().replace("-DONYX_FDT_HANDOFF=1\n", ""))
        code, stdout, _ = self.fixture.run()
        self.assertEqual(code, CHECK.EXIT_FAILED)
        self.assertIn("ONYX_FDT_HANDOFF", stdout)

    def test_an_fdf_that_lost_a_module_fails(self):
        lines = [line for line in CHECK.REQUIRED_FDF_LINES if "AdvancedLogDxe" not in line]
        self.fixture.write_uefi(FDF, "[FV.DXEFV]\n" + "\n".join(f"  INF {l}" for l in lines) + "\n")
        code, stdout, _ = self.fixture.run()
        self.assertEqual(code, CHECK.EXIT_FAILED)
        self.assertIn("AdvancedLogDxe", stdout)

    def test_no_checkout_skips_instead_of_failing(self):
        stdout = io.StringIO()
        saved = os.environ.pop("UNIXNU_UEFI", None)
        try:
            with contextlib.redirect_stdout(stdout):
                code = CHECK.main(["--device", str(self.fixture.device)])
        finally:
            if saved is not None:
                os.environ["UNIXNU_UEFI"] = saved
        self.assertEqual(code, CHECK.EXIT_SKIPPED)
        self.assertIn("did not run", stdout.getvalue())

    def test_no_checkout_is_a_failure_when_one_is_required(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        saved = os.environ.pop("UNIXNU_UEFI", None)
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = CHECK.main(["--device", str(self.fixture.device), "--require-uefi"])
        finally:
            if saved is not None:
                os.environ["UNIXNU_UEFI"] = saved
        self.assertEqual(code, CHECK.EXIT_FAILED)
        self.assertIn("UNIXNU_UEFI", stderr.getvalue())

    def test_a_directory_that_is_not_a_mu_checkout_fails(self):
        empty = Path(self.temp.name) / "not-mu"
        empty.mkdir()
        self.fixture.uefi = empty
        code, _, stderr = self.fixture.run()
        self.assertEqual(code, CHECK.EXIT_FAILED)
        self.assertIn("platforms/xiaomi/onyxPkg".lower(), stderr.lower())


class LiveBoardTests(unittest.TestCase):
    """The real board.toml must keep naming the preflight script."""

    def test_the_board_names_the_preflight(self):
        import tomllib
        board = tomllib.loads((DEVICE / "board.toml").read_text(encoding="utf-8"))
        self.assertIn("scripts/check-firmware-inputs.py", board["firmware"].get("preflight", []))

    def test_the_script_exists_and_is_executable_by_python(self):
        self.assertTrue((DEVICE / "scripts/check-firmware-inputs.py").is_file())
        self.assertTrue(CHECK.REQUIRED_FDF_LINES)
        self.assertEqual(json.dumps(CHECK.FOREIGN_TARGET_PATHS), '["UniXNUPkg/"]')


if __name__ == "__main__":
    unittest.main()
