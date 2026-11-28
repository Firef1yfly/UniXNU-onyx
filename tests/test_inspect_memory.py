"""Offline tests for inspect-memory.py; no device/network operations."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

DEVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from host_fixtures import upstream  # noqa: E402  (sibling helper, not a test module)

SPEC = importlib.util.spec_from_file_location("inspect_memory", DEVICE / "scripts/inspect-memory.py")
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)
# The FDT parser lives in the upstream checkout, which this repository does not
# carry; UNIXNU_HOME names it, and a bare clone skips instead of failing.
UNIXNU, UNIXNU_SKIP = upstream()


@unittest.skipUnless(shutil.which("dtc"), "requires dtc")
@unittest.skipIf(UNIXNU is None, UNIXNU_SKIP)
class InspectMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def compile(self, body, name="fixture.dtb"):
        source = self.root / (name + ".dts")
        output = self.root / name
        source.write_text("/dts-v1/;\n" + body, encoding="utf-8")
        result = subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-o", output, source],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return output

    def inspect(self, body):
        return TOOL.inspect(self.compile(body), UNIXNU)

    def base(self, memory, extra=""):
        return f"""
/memreserve/ 0x90000000 0x1000;
/ {{
  model = \"Generic Tuna SoC\";
  compatible = \"qcom,tuna\";
  #address-cells = <2>;
  #size-cells = <2>;
  memory@0 {{ device_type = \"memory\"; reg = <{memory}>; }};
  {extra if extra else 'reserved-memory { #address-cells = <2>; #size-cells = <2>; ranges; };'}
}};
"""

    def test_input_hash_and_size_are_reported(self):
        path = self.compile(self.base("0 0 0 0"))
        report = TOOL.inspect(path, UNIXNU)
        raw = path.read_bytes()
        self.assertEqual(report["input"], {"path": str(path), "size": len(raw),
                                           "sha256": hashlib.sha256(raw).hexdigest()})

    def test_generic_tuna_does_not_confirm_onyx(self):
        report = self.inspect(self.base("0 0 0 0") .replace('model = "Generic Tuna SoC"', 'model = "Qualcomm Technologies, Inc. Tuna SoC"'))
        self.assertFalse(report["identity"]["onyx_confirmed"])
        self.assertIn("qcom,tuna alone", report["identity"]["reason"])

    def test_onyx_identity_requires_model_or_compatible_marker(self):
        body = self.base("0 0 0 0").replace('model = "Generic Tuna SoC"', 'model = "Qualcomm Technologies, Inc. Onyx based on SM8735"')
        report = self.inspect(body)
        self.assertTrue(report["identity"]["onyx_confirmed"])

    def test_qcom_ids_are_reported(self):
        body = self.base("0 0 0 0").replace('compatible = "qcom,tuna";', 'compatible = "qcom,tuna";\n  qcom,msm-id = <681 0x10000>;\n  qcom,board-id = <8 0>;\n  xiaomi,miboard-id = <7 0>;')
        ids = self.inspect(body)["identity"]["qcom_ids"]
        self.assertEqual(ids["qcom,msm-id"], [681, 0x10000])
        self.assertEqual(ids["qcom,board-id"], [8, 0])
        self.assertEqual(ids["xiaomi,miboard-id"], [7, 0])

    def test_zero_memory_is_incomplete_and_exit_one(self):
        path = self.compile(self.base("0 0 0 0"))
        report = TOOL.inspect(path, UNIXNU)
        self.assertFalse(report["memory_complete"])
        self.assertIn("zero_size", report["memory"]["errors"])
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = TOOL.main(["--dtb", str(path), "--unixnu", str(UNIXNU), "--json"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stdout.getvalue())["safe_to_boot"])

    def test_multiple_nonoverlapping_banks_are_decoded(self):
        body = self.base("0 0x80000000 0 0x40000000")
        body = body.replace('memory@0 { device_type = "memory"; reg = <0 0x80000000 0 0x40000000>; };',
                            'memory@80000000 { device_type = "memory"; reg = <0 0x80000000 0 0x40000000 0 0xc0000000 0 0x40000000>; };')
        report = self.inspect(body)
        ranges = report["memory"]["enabled_ranges"]
        self.assertEqual([(x["address"], x["size"]) for x in ranges],
                         [(0x80000000, 0x40000000), (0xc0000000, 0x40000000)])
        self.assertTrue(report["memory"]["complete"])

    def test_disabled_memory_is_separate(self):
        body = self.base("0 0x80000000 0 0x1000").replace('memory@0 {', 'memory@0 { status = "disabled";')
        report = self.inspect(body)
        self.assertEqual(report["memory"]["enabled_ranges"], [])
        self.assertEqual(report["memory"]["disabled_ranges"][0]["status"], "disabled")
        self.assertFalse(report["memory_complete"])

    def test_overflow_is_reported(self):
        report = self.inspect(self.base("0xffffffff 0xfffff000 0 0x2000"))
        self.assertIn("overflow", report["memory"]["errors"])
        self.assertFalse(report["memory_complete"])

    def test_overlapping_banks_are_reported(self):
        body = self.base("0 0 0 0x2000").replace('memory@0 { device_type = "memory"; reg = <0 0 0 0x2000>; };',
            'memory@0 { device_type = "memory"; reg = <0 0 0 0x2000>; };\n  memory@1000 { device_type = "memory"; reg = <0 0x1000 0 0x2000>; };')
        report = self.inspect(body)
        self.assertEqual(report["memory"]["overlaps"], [{"first": 0, "second": 1}])
        self.assertIn("enabled memory ranges overlap", report["memory"]["errors"])

    def test_reserved_reg_flags_are_reported(self):
        extra = 'reserved-memory { #address-cells = <2>; #size-cells = <2>; ranges; splash@fc800000 { no-map; reg = <0 0xfc800000 0 0x1000>; }; foo@fd000000 { reusable; reg = <0 0xfd000000 0 0x2000>; }; };'
        report = self.inspect(self.base("0 0 0 0x1000", extra))
        ranges = report["reserved_memory"]["ranges"]
        self.assertEqual([(r["path"], r["no_map"], r["reusable"]) for r in ranges],
                         [("/reserved-memory/splash@fc800000", True, False), ("/reserved-memory/foo@fd000000", False, True)])

    def test_size_only_reservation_is_unresolved(self):
        extra = 'reserved-memory { #address-cells = <2>; #size-cells = <2>; ranges; dynamic { size = <0 0x2000>; }; };'
        report = self.inspect(self.base("0 0 0 0x1000", extra))
        self.assertEqual(len(report["reserved_memory"]["dynamic_size_only"]), 1)
        self.assertTrue(report["reserved_memory"]["dynamic_size_only"][0]["unresolved"])
        self.assertFalse(report["memory_complete"])

    def test_memreserve_pairs_are_bounded_and_terminated(self):
        report = self.inspect(self.base("0 0 0 0x1000"))
        self.assertEqual(report["fdt_memreserve"]["pairs"], [{"address": 0x90000000, "size": 0x1000, "end": 0x90001000}])
        self.assertTrue(report["fdt_memreserve"]["terminated"])
        self.assertTrue(report["memory_complete"])

    def test_malformed_input_returns_json_without_traceback(self):
        path = self.root / "bad.dtb"
        path.write_bytes(b"not an fdt")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = TOOL.main(["--dtb", str(path), "--unixnu", str(UNIXNU), "--json"])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", output.getvalue())
        report = json.loads(output.getvalue())
        self.assertFalse(report["safe_to_boot"])
        self.assertTrue(report["errors"])

    def test_missing_or_empty_memory_reg_fails_with_other_valid_bank(self):
        for property_text in ('', 'reg;'):
            with self.subTest(property_text=property_text):
                body = self.base("0 0 0 0x1000").replace('memory@0 {', f'memory@2000 {{ device_type = "memory"; {property_text} }}; memory@0 {{')
                report = self.inspect(body)
                self.assertFalse(report["memory_complete"])
                self.assertTrue(report["memory"]["errors"])

    def test_empty_reserved_reg_fails(self):
        extra = 'reserved-memory { #address-cells = <2>; #size-cells = <2>; ranges; empty { reg; }; };'
        report = self.inspect(self.base("0 0 0 0x1000", extra))
        self.assertFalse(report["memory_complete"])
        self.assertIn("empty reg", report["reserved_memory"]["errors"][0])

    def test_parent_single_cell_widths_are_honored(self):
        body = self.base("0 0x1000").replace('#address-cells = <2>;', '#address-cells = <1>;', 1).replace('#size-cells = <2>;', '#size-cells = <1>;', 1)
        report = self.inspect(body)
        self.assertEqual(report["memory"]["enabled_ranges"][0]["size"], 0x1000)
        self.assertTrue(report["memory_complete"])

    def test_memreserve_missing_terminator_is_bounded(self):
        path = self.compile(self.base("0 0 0 0x1000"))
        raw = bytearray(path.read_bytes())
        reserve_offset = struct.unpack_from(">I", raw, 16)[0]
        struct.pack_into(">QQ", raw, reserve_offset + 16, 0x1000, 0x1000)
        path.write_bytes(raw)
        report = TOOL.inspect(path, UNIXNU)
        self.assertFalse(report["fdt_memreserve"]["terminated"])
        self.assertFalse(report["memory_complete"])
        self.assertIn("no bounded terminator", report["fdt_memreserve"]["errors"][0])

    def test_invalid_unixnu_path_is_json_error(self):
        path = self.compile(self.base("0 0 0 0x1000"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = TOOL.main(["--dtb", str(path), "--unixnu", str(self.root / "absent"), "--json"])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", output.getvalue())
        self.assertIn("scripts directory not found", report["errors"][0])

    def test_complete_stays_offline_and_does_not_modify_input(self):
        path = self.compile(self.base("0 0 0 0x1000"))
        before = path.read_bytes()
        first = TOOL.inspect(path, UNIXNU)
        second = TOOL.inspect(path, UNIXNU)
        self.assertEqual(first, second)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(first["hardware_tested"])
        self.assertFalse(first["safe_to_boot"])
        self.assertFalse(first["identity"]["runtime_source_verified"])

    def test_current_android17_zero_case_if_extracted(self):
        path = DEVICE / "private-inputs/current-android17/vendor-base-0.dtb"
        if not path.is_file():
            self.skipTest("current Android 17 evidence not extracted")
        report = TOOL.inspect(path, UNIXNU)
        self.assertFalse(report["memory_complete"])
        self.assertEqual(report["memory"]["enabled_ranges"][0]["size"], 0)
        self.assertFalse(report["identity"]["onyx_confirmed"])


class UnixnuDefaultTests(unittest.TestCase):
    """The CLI default, so a plain run finds the checkout without --unixnu."""

    def test_unixnu_home_names_the_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            (checkout / "scripts/unixnu").mkdir(parents=True)
            (checkout / "scripts/unixnu/devicetree.py").write_text("", encoding="utf-8")
            with mock.patch.dict(os.environ, {"UNIXNU_HOME": str(checkout)}):
                self.assertEqual(TOOL.default_unixnu(), checkout)

    def test_fallback_is_the_sibling_recorded_in_board_toml(self):
        board = tomllib.loads((DEVICE / "board.toml").read_text(encoding="utf-8"))
        with mock.patch.dict(os.environ):
            os.environ.pop("UNIXNU_HOME", None)
            # With no checkout beside this clone a plain run still points at the
            # documented sibling, so its error names the path a user must create.
            self.assertEqual(TOOL.default_unixnu().resolve(),
                             (DEVICE / board["package"]["unixnu"]).resolve())


if __name__ == "__main__":
    unittest.main()
