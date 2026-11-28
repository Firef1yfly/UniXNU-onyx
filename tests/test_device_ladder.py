#!/usr/bin/env python3
"""Host-side tests for scripts/device-ladder.py, with stub fastboot/adb binaries.

These tests are host-side evidence only. They drive the harness against a stub
`fastboot`/`adb` pair in a temporary directory so the refusal paths and the
observation state machine can be exercised on a machine with no phone attached.
Nothing here is a hardware result: the stubs decide what "the device" does, so a
green run says the harness classifies the observations it is given, not that any
verdict has ever happened on onyx.

PATH is narrowed to the stub directory for every invocation, so a real fastboot
or adb binary can never be reached from these tests.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEVICE = HERE.parent
SPEC = importlib.util.spec_from_file_location("device_ladder", DEVICE / "scripts/device-ladder.py")
LADDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LADDER)

FIXTURE = Path("/home/firefly/文档/onyx-porting/out/onyx-menu-boot.img")
SERIAL = "5d7b86fd"
PAGE = 4096

STUB_FASTBOOT = r"""#!/usr/bin/env bash
# Stub `fastboot` for tests/test_device_ladder.py. Records every argv it is
# given, then answers from the STUB_SCENARIO environment variable.
set -u
printf 'fastboot %s\n' "$*" >> "$STUB_LOG"
args=("$@")
sub=""
i=0
while [ $i -lt ${#args[@]} ]; do
  a="${args[$i]}"
  case "$a" in
    -s|--serial) i=$((i+2)); continue;;
    -*) i=$((i+1)); continue;;
    *) sub="$a"; break;;
  esac
done
serial="${STUB_SERIAL:-5d7b86fd}"
serials="${STUB_SERIALS:-$serial}"
count_file="$STUB_STATE/devices_count"
bump() { n=$(cat "$count_file" 2>/dev/null || echo 0); echo $((n+1)) > "$count_file"; }
case "$sub" in
  devices)
    bump
    post=0
    if [ -e "$STUB_STATE/booted" ]; then
      p=$(cat "$STUB_STATE/post_count" 2>/dev/null || echo 0)
      echo $((p+1)) > "$STUB_STATE/post_count"
      post=$((p+1))
    fi
    case "$STUB_SCENARIO" in
      no_device) exit 0;;
      cold_restart_never_returns) [ -e "$STUB_STATE/restarted" ] && exit 0;;
      boot_then_gone) [ "$post" -gt 0 ] && exit 0;;
      gap_then_return) [ -e "$STUB_STATE/booted" ] && [ "$post" -le 2 ] && exit 0;;
    esac
    for s in $serials; do printf '%s\tfastboot\n' "$s"; done
    exit 0;;
  getvar)
    printf '(bootloader) %s: %s\n' "${args[${#args[@]}-1]}" "${STUB_GETVAR_VALUE:-onyx}" >&2
    echo "Finished. Total time: 0.001s"
    exit 0;;
  reboot-bootloader)
    touch "$STUB_STATE/restarted"
    echo "Rebooting into bootloader                          OKAY [  0.004s]"
    exit 0;;
  boot)
    case "$STUB_SCENARIO" in
      boot_timeout) sleep 30;;
      load_error)
        echo "Sending 'boot.img' (20292 KB)                       OKAY [  0.600s]"
        printf "FAILED (remote: 'Failed to load/authenticate boot image: Load Error')\n" >&2
        exit 1;;
    esac
    echo "Sending 'boot.img' (20292 KB)                       OKAY [  0.600s]"
    echo "Booting                                            OKAY [  0.900s]"
    touch "$STUB_STATE/booted"
    exit 0;;
  *)
    echo "stub fastboot: unsupported subcommand '$sub'" >&2
    exit 64;;
esac
"""

STUB_ADB = r"""#!/usr/bin/env bash
set -u
printf 'adb %s\n' "$*" >> "$STUB_LOG"
echo "List of devices attached"
exit 0
"""


def boot_image(*, text_offset=0x0, header_version=4, magic=b"ANDROID!",
               arm64_magic=b"ARM\x64", kernel_size=0x4000, header_size=1584) -> bytes:
    """Build an Android boot image with a chosen ARM64 header.

    Note there is no free space at file offset 8 to park a decoy: that offset is
    the 32-bit `kernel_size`/`ramdisk_size` pair in v3/v4 and the whole point of
    the check is that `text_offset` is only meaningful inside the kernel field.
    """
    if header_version >= 3:
        header_bytes = PAGE * max(1, -(-header_size // PAGE))
    else:
        header_bytes = PAGE
    data = bytearray(header_bytes + kernel_size)
    data[0:8] = magic
    struct.pack_into("<I", data, LADDER.KERNEL_SIZE_OFFSET, kernel_size)
    if header_version >= 3:
        struct.pack_into("<I", data, LADDER.HEADER_SIZE_OFFSET, header_size)
    else:
        struct.pack_into("<I", data, LADDER.PAGE_SIZE_OFFSET, PAGE)
    struct.pack_into("<I", data, LADDER.HEADER_VERSION_OFFSET, header_version)
    struct.pack_into("<Q", data, header_bytes + LADDER.TEXT_OFFSET_POSITION, text_offset)
    struct.pack_into("<Q", data, header_bytes + LADDER.IMAGE_SIZE_POSITION, kernel_size)
    data[header_bytes + LADDER.ARM64_MAGIC_POSITION:
         header_bytes + LADDER.ARM64_MAGIC_POSITION + 4] = arm64_magic
    return bytes(data)


class LadderCase(unittest.TestCase):
    """Base class: a temp workspace with stub tools and a fake sysfs."""

    scenario = "default"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="device-ladder-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.state = self.tmp / "state"
        self.usb = self.tmp / "usb"
        self.records = self.tmp / "records"
        for directory in (self.bin, self.state, self.usb):
            directory.mkdir(parents=True)
        self.log = self.tmp / "fastboot.log"
        self.log.touch()
        self.write_stub("fastboot", STUB_FASTBOOT)
        self.write_stub("adb", STUB_ADB)
        self.image = self.tmp / "boot.img"
        self.image.write_bytes(boot_image())
        self.sha256 = LADDER.sha256_file(self.image)

    def write_stub(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    # -- invocation ---------------------------------------------------------
    def run_ladder(self, *arguments, env=None, scenario=None):
        """Run the harness with PATH narrowed to the stub directory only."""
        environment = {
            # The stub directory is first, so `fastboot`/`adb` always resolve to the
            # stubs; /usr/bin and /bin are only there so the stub scripts' own
            # shebang, `env`, `cat` and `touch` can run.
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "STUB_LOG": str(self.log),
            "STUB_STATE": str(self.state),
            "STUB_SCENARIO": scenario or self.scenario,
            "LADDER_USB_ROOT": str(self.usb),
            "HOME": str(self.tmp),
        }
        if env:
            environment.update(env)
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(environment)
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = LADDER.main(["device-ladder.py", *arguments])
        finally:
            os.environ.clear()
            os.environ.update(saved)
        return code, stdout.getvalue(), stderr.getvalue()

    def boot(self, *extra, image=None, scenario=None, confirm=None, env=None):
        return self.run_ladder(
            "boot",
            "--image", str(image or self.image),
            "--confirm-sha256", confirm if confirm is not None else self.sha256,
            "--record-dir", str(self.records),
            "--poll-interval", "0.05",
            "--observe-seconds", "0.6",
            "--min-absence-seconds", "0.2",
            "--cold-restart-timeout", "0.6",
            "--boot-timeout", "10",
            *extra,
            scenario=scenario,
            env=env,
        )

    # -- assertions ---------------------------------------------------------
    def fastboot_calls(self):
        return [line for line in self.log.read_text().splitlines() if line]

    def records_written(self):
        return sorted(self.records.glob("ladder-*.json")) if self.records.exists() else []

    def single_record(self):
        records = self.records_written()
        self.assertEqual(len(records), 1, f"expected one record, found {records}")
        return json.loads(records[0].read_text())

    def assert_refused(self, code, *, listing_allowed=False):
        """A refusal must leave no record and must never reach `fastboot boot`."""
        self.assertEqual(code, LADDER.EXIT_REFUSED)
        self.assertFalse(self.records_written(),
                         "a refusal must not leave a ladder record behind")
        self.assertEqual([call for call in self.fastboot_calls() if " boot " in call], [],
                         "a refusal must happen before any download")
        if listing_allowed:
            listing = [call for call in self.fastboot_calls()
                       if call.strip() not in ("fastboot devices", "adb devices")]
            self.assertEqual(listing, [],
                             "the only command a listing refusal may run is `fastboot devices`")
        else:
            self.assertEqual(self.fastboot_calls(), [],
                             "a refusal must happen before any device command")


class RefusalTests(LadderCase):
    def test_sha256_mismatch_is_refused_and_names_both_hashes(self):
        other = "0" * 64
        code, stdout, stderr = self.boot(confirm=other)
        self.assert_refused(code)
        self.assertIn(LADDER.EXIT_REFUSED, (code,))
        payload = json.loads(stdout)
        self.assertEqual(payload["code"], "sha256_mismatch")
        self.assertIn(self.sha256, payload["message"])
        self.assertIn(other, payload["message"])
        self.assertIn("REFUSED:", stderr)

    def test_confirm_sha256_must_be_a_full_digest(self):
        code, stdout, _ = self.boot(confirm="deadbeef")
        self.assert_refused(code)
        self.assertEqual(json.loads(stdout)["code"], "confirm_sha256_malformed")

    def test_non_zero_text_offset_is_refused_naming_the_value(self):
        self.image.write_bytes(boot_image(text_offset=0xA7100000))
        self.sha256 = LADDER.sha256_file(self.image)
        code, stdout, _ = self.boot()
        self.assert_refused(code)
        payload = json.loads(stdout)
        self.assertEqual(payload["code"], "text_offset_nonzero")
        self.assertIn("0xa7100000", payload["message"])
        self.assertIn("ABL", payload["message"])

    def test_text_offset_is_read_inside_the_kernel_field_not_at_file_offset_8(self):
        # v0-v2 images put the kernel field one page in; the reader must follow the
        # version-specific geometry rather than assume the header starts at offset 0.
        self.image.write_bytes(boot_image(header_version=0, text_offset=0x1234))
        self.sha256 = LADDER.sha256_file(self.image)
        code, stdout, _ = self.boot()
        self.assert_refused(code)
        self.assertEqual(json.loads(stdout)["code"], "text_offset_nonzero")

    def test_reader_reports_the_exact_field_position_it_read(self):
        inspection = LADDER.inspect_boot_image(self.image)
        header = inspection["header"]
        self.assertEqual(header["kernel_field_offset"], PAGE)
        self.assertEqual(header["text_offset"], 0)
        self.assertEqual(header["text_offset_position"], hex(PAGE + LADDER.TEXT_OFFSET_POSITION))

    def test_large_header_pushes_the_kernel_field_to_the_next_page(self):
        self.image.write_bytes(boot_image(header_size=5000))
        inspection = LADDER.inspect_boot_image(self.image)
        self.assertEqual(inspection["header"]["kernel_field_offset"], 2 * PAGE)

    def test_image_without_android_boot_magic_is_refused(self):
        self.image.write_bytes(boot_image(magic=b"NOTBOOT!"))
        self.sha256 = LADDER.sha256_file(self.image)
        code, stdout, _ = self.boot()
        self.assert_refused(code)
        self.assertEqual(json.loads(stdout)["code"], "image_not_android_boot")

    def test_kernel_field_without_arm64_magic_is_refused(self):
        self.image.write_bytes(boot_image(arm64_magic=b"\0\0\0\0"))
        self.sha256 = LADDER.sha256_file(self.image)
        code, stdout, _ = self.boot()
        self.assert_refused(code)
        self.assertEqual(json.loads(stdout)["code"], "kernel_field_not_arm64")

    def test_unknown_header_version_is_refused_instead_of_guessed(self):
        self.image.write_bytes(boot_image(header_version=7))
        self.sha256 = LADDER.sha256_file(self.image)
        code, stdout, _ = self.boot()
        self.assert_refused(code)
        self.assertEqual(json.loads(stdout)["code"], "unknown_header_version")

    def test_flash_argument_is_refused_outright(self):
        flashing = self.tmp / "flash-boot.img"
        flashing.write_bytes(boot_image())
        code, stdout, _ = self.boot(image=flashing, confirm=LADDER.sha256_file(flashing))
        self.assert_refused(code)
        payload = json.loads(stdout)
        self.assertEqual(payload["code"], "unsafe_argument")
        self.assertIn("flash", payload["message"])

    def test_missing_image_is_refused(self):
        code, stdout, _ = self.boot(image=self.tmp / "absent.img")
        self.assert_refused(code)
        self.assertEqual(json.loads(stdout)["code"], "image_missing")

    def test_two_devices_without_serial_is_refused(self):
        code, stdout, _ = self.boot(env={"STUB_SERIALS": f"{SERIAL} 0123abcd"})
        self.assert_refused(code, listing_allowed=True)
        payload = json.loads(stdout)
        self.assertEqual(payload["code"], "ambiguous_devices")
        self.assertIn("--serial", payload["message"])

    def test_serial_not_attached_is_refused(self):
        code, stdout, _ = self.boot("--serial", "ffffffff")
        self.assert_refused(code, listing_allowed=True)
        self.assertEqual(json.loads(stdout)["code"], "serial_not_present")


class VerdictTests(LadderCase):
    def test_no_device_is_a_verdict_not_a_boot(self):
        code, stdout, _ = self.boot(scenario="no_device")
        self.assertEqual(code, LADDER.EXIT_NOT_PROVEN)
        record = self.single_record()
        self.assertEqual(record["verdict"]["code"], "no_device")
        self.assertEqual([call for call in self.fastboot_calls() if " boot " in call], [])
        self.assertEqual(record["safety"]["device_commands_run"], ["fastboot devices"])

    def test_device_that_never_leaves_fastboot_is_not_a_pass(self):
        code, _, _ = self.boot(scenario="default")
        self.assertEqual(code, LADDER.EXIT_NOT_PROVEN)
        record = self.single_record()
        verdict = record["verdict"]
        self.assertEqual(verdict["code"], "accepted_and_returned_to_fastboot")
        self.assertFalse(verdict["positive"])
        self.assertTrue(verdict["acknowledged_booting_okay"])
        self.assertIn("only that fastboot accepted the download",
                      " ".join(verdict["proves"]))
        self.assertTrue(any("not freshly re-initialised" in warning
                            for warning in record["warnings"]))

    def test_disconnected_after_boot_is_the_positive_verdict(self):
        code, stdout, _ = self.boot(scenario="boot_then_gone")
        self.assertEqual(code, LADDER.EXIT_POSITIVE)
        record = self.single_record()
        verdict = record["verdict"]
        self.assertEqual(verdict["code"], "disconnected_after_boot")
        self.assertTrue(verdict["positive"])
        self.assertIn("does not prove", json.dumps(verdict).lower().replace("does_not_prove",
                                                                           "does not prove"))
        self.assertEqual(verdict["ended_in"], "absent_from_usb")

    def test_disconnect_then_return_is_recorded_as_its_own_verdict(self):
        code, _, _ = self.boot(scenario="gap_then_return")
        self.assertEqual(code, LADDER.EXIT_NOT_PROVEN)
        verdict = self.single_record()["verdict"]
        self.assertEqual(verdict["code"], "disconnected_then_returned_to_fastboot")
        self.assertFalse(verdict["positive"])

    def test_load_error_is_its_own_verdict(self):
        code, _, _ = self.boot(scenario="load_error")
        self.assertEqual(code, LADDER.EXIT_NOT_PROVEN)
        record = self.single_record()
        self.assertEqual(record["verdict"]["code"], "load_error")
        self.assertIn("Load Error", record["boot_command"]["stderr"])
        self.assertEqual(record["boot_command"]["exit_code"], 1)

    def test_download_timeout_is_not_interpreted_as_execution(self):
        code, _, _ = self.boot("--boot-timeout", "0.5", scenario="boot_timeout")
        self.assertEqual(code, LADDER.EXIT_NOT_PROVEN)
        record = self.single_record()
        self.assertEqual(record["verdict"]["code"], "boot_command_timeout")
        self.assertTrue(record["boot_command"]["timed_out"])

    def test_cold_restart_makes_the_run_fresh(self):
        code, _, _ = self.boot("--cold-restart", scenario="default")
        self.assertEqual(code, LADDER.EXIT_NOT_PROVEN)
        record = self.single_record()
        self.assertTrue(record["bootloader"]["fresh"])
        self.assertTrue(record["bootloader"]["performed"])
        self.assertFalse(record["warnings"])
        self.assertTrue(any("reboot-bootloader" in call for call in self.fastboot_calls()))

    def test_cold_restart_that_never_returns_stops_before_booting(self):
        code, _, _ = self.boot("--cold-restart", scenario="cold_restart_never_returns")
        self.assertEqual(code, LADDER.EXIT_NOT_PROVEN)
        record = self.single_record()
        self.assertEqual(record["verdict"]["code"], "cold_restart_failed")
        self.assertIsNone(record["boot_command"])
        self.assertEqual([call for call in self.fastboot_calls() if " boot " in call], [])

    def test_boot_command_is_exactly_fastboot_boot_image(self):
        self.boot(scenario="default")
        boot_calls = [call for call in self.fastboot_calls() if " boot " in call]
        self.assertEqual(len(boot_calls), 1)
        self.assertEqual(boot_calls[0],
                         f"fastboot -s {SERIAL} boot {self.image.resolve()}")

    def test_ending_in_android_is_flagged_not_counted_as_a_control(self):
        android = self.usb / "1-1"
        android.mkdir()
        (android / "idVendor").write_text("18d1\n")
        (android / "idProduct").write_text("4e11\n")
        self.boot(scenario="boot_then_gone")
        record = self.single_record()
        self.assertEqual(record["verdict"]["ended_in"], "android")
        self.assertTrue(any("plain reboot" in warning for warning in record["warnings"]))


class RecordTests(LadderCase):
    REQUIRED_KEYS = (
        "schema_version", "record_kind", "generated_at", "evidence_class", "host",
        "image", "confirmation", "safety", "bootloader", "pre_device_state",
        "post_device_state", "boot_command", "timeline", "verdict", "warnings",
    )
    VERDICT_KEYS = ("code", "summary", "proves", "does_not_prove", "evidence",
                    "anomalies", "positive", "ended_in")
    HEADER_KEYS = ("boot_magic", "header_version", "kernel_field_offset", "kernel_size",
                   "ramdisk_size", "text_offset", "text_offset_hex", "image_size",
                   "arm64_magic")

    def test_record_contains_every_required_key_and_binds_the_image(self):
        self.boot(scenario="boot_then_gone")
        record = self.single_record()
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, record)
        for key in self.VERDICT_KEYS:
            self.assertIn(key, record["verdict"])
        for key in self.HEADER_KEYS:
            self.assertIn(key, record["image"]["header"])
        self.assertEqual(record["image"]["sha256"], self.sha256)
        self.assertTrue(record["confirmation"]["matches"])
        self.assertEqual(record["record_kind"], "on_device_attempt")
        self.assertIn("mocked host-side evidence", record["evidence_class"])

    def test_timeline_is_ordered_and_fully_timestamped(self):
        self.boot(scenario="boot_then_gone")
        timeline = self.single_record()["timeline"]
        self.assertGreaterEqual(len(timeline), 2)
        elapsed = [entry["elapsed_s"] for entry in timeline]
        self.assertEqual(elapsed, sorted(elapsed))
        for entry in timeline:
            self.assertRegex(entry["utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
            self.assertIn("fastboot_present", entry)
            self.assertIn("usb", entry)
        phases = {entry["phase"] for entry in timeline}
        self.assertIn("post_boot", phases)

    def test_every_recorded_device_command_is_in_the_allowlist(self):
        self.boot("--cold-restart", scenario="default")
        record = self.single_record()
        self.assertTrue(record["safety"]["device_commands_run"])
        for call in record["safety"]["device_commands_run"]:
            argv = call.split()
            LADDER.assert_allowed_device_command(argv)  # raises Refusal if not allowlisted
        self.assertFalse(record["safety"]["partition_writes_possible"])

    def test_record_file_name_carries_the_utc_stamp(self):
        self.boot(scenario="default")
        name = self.records_written()[0].name
        self.assertRegex(name, r"^ladder-\d{8}T\d{6}Z\.json$")

    def test_refusal_leaves_no_record(self):
        self.boot(confirm="f" * 64)
        self.assertFalse(self.records.exists() and any(self.records.iterdir()))


class ProbeTests(LadderCase):
    def test_probe_reads_variables_and_never_boots(self):
        code, stdout, _ = self.run_ladder("probe", env={"STUB_GETVAR_VALUE": "onyx"})
        self.assertEqual(code, LADDER.EXIT_POSITIVE)
        report = json.loads(stdout)
        self.assertTrue(report["device_present"])
        self.assertEqual(report["fastboot"]["devices"][0]["serial"], SERIAL)
        self.assertEqual(report["getvar"], {name: "onyx" for name in LADDER.GETVAR_NAMES})
        self.assertEqual(report["writes_attempted"], 0)
        calls = self.fastboot_calls()
        self.assertFalse(any(" boot " in call or call.startswith("boot") for call in calls))
        for call in calls:
            LADDER.assert_allowed_device_command(call.split())
        self.assertTrue(all(("getvar" in call) or ("devices" in call) for call in calls))

    def test_probe_reports_absent_device_with_a_non_zero_exit(self):
        code, stdout, _ = self.run_ladder("probe", scenario="no_device")
        self.assertEqual(code, LADDER.EXIT_NOT_PROVEN)
        report = json.loads(stdout)
        self.assertFalse(report["device_present"])
        self.assertEqual(report["getvar"], {})
        self.assertEqual(report["getvar_note"], None)

    def test_probe_skips_getvars_when_two_devices_are_attached(self):
        code, stdout, _ = self.run_ladder("probe", env={"STUB_SERIALS": f"{SERIAL} 0123abcd"})
        self.assertEqual(code, LADDER.EXIT_POSITIVE)
        report = json.loads(stdout)
        self.assertIn("--serial", report["getvar_note"])
        self.assertEqual(report["getvar"], {})


class SafetyBoundaryTests(unittest.TestCase):
    def test_allowlist_templates_satisfy_the_boundary(self):
        LADDER.assert_safety_boundary()  # raises AssertionError on drift

    def test_forbidden_words_cover_every_partition_write_verb(self):
        for word in ("flash", "erase", "oem", "format", "write", "sideload"):
            self.assertIn(word, LADDER.FORBIDDEN_SUBSTRINGS)
        self.assertNotIn("flash", LADDER.FASTBOOT_SUBCOMMANDS)

    def test_forbidden_verbs_are_refused_even_with_a_serial(self):
        for verb in ("flash", "erase", "oem", "format", "set_active", "sideload"):
            with self.assertRaises(LADDER.Refusal) as caught:
                LADDER.assert_allowed_device_command(["fastboot", "-s", SERIAL, verb,
                                                      "boot_a", "img"])
            self.assertEqual(caught.exception.code, "unsafe_argument")

    def test_getvar_names_are_closed(self):
        with self.assertRaises(LADDER.Refusal) as caught:
            LADDER.assert_allowed_device_command(["fastboot", "getvar", "all"])
        self.assertEqual(caught.exception.code, "unsafe_getvar")

    def test_boot_takes_exactly_one_trailing_argument(self):
        with self.assertRaises(LADDER.Refusal) as caught:
            LADDER.assert_allowed_device_command(
                ["fastboot", "boot", "a.img", "b.img"])
        self.assertEqual(caught.exception.code, "unsafe_boot_argv")

    def test_there_is_exactly_one_process_entry_point(self):
        source = (DEVICE / "scripts/device-ladder.py").read_text()
        self.assertEqual(source.count("subprocess.run("), 1)
        for forbidden in ("subprocess.Popen", "subprocess.call", "os.system", "shell=True"):
            self.assertNotIn(forbidden, source)

    def test_the_record_directory_default_is_docs_bringup(self):
        self.assertEqual(LADDER.DEFAULT_RECORD_DIR, DEVICE / "docs" / "bringup")


class FixtureTests(unittest.TestCase):
    """Read-only parsing of the packed menu image; the file is never modified."""

    @unittest.skipUnless(FIXTURE.is_file(), f"packed fixture absent: {FIXTURE}")
    def test_packed_menu_image_parses_and_carries_a_zeroed_text_offset(self):
        # The digest is deliberately not pinned: this workspace repacks the image
        # between rounds, and a test that fails on a legitimate repack would push
        # someone to pin a stale hash instead of reading the file. The invariants
        # that matter are the ones the harness depends on.
        before = LADDER.sha256_file(FIXTURE)
        inspection = LADDER.inspect_boot_image(FIXTURE)
        after = LADDER.sha256_file(FIXTURE)
        if before != after:
            self.skipTest("the packed fixture changed while it was being read")
        header = inspection["header"]
        self.assertEqual(header["boot_magic"], "ANDROID!")
        self.assertEqual(header["boot_magic"], "ANDROID!")
        self.assertEqual(header["kernel_field_offset"], PAGE)
        self.assertEqual(header["text_offset"], 0,
                         "a packed image must carry text_offset 0 or the ABL jumps past RAM")
        self.assertEqual(header["arm64_magic"], "ARMd")
        self.assertIn(header["header_version"], (3, 4))
        self.assertEqual(inspection["size"], len(FIXTURE.read_bytes()))
        self.assertEqual(LADDER.sha256_file(FIXTURE), before,
                         "parsing must not modify the fixture")


class StateMachineTests(unittest.TestCase):
    """Direct checks on the classifier, for combinations the stubs do not cover."""

    def observation(self, elapsed, present, phase="post_boot", usb=None):
        return {"phase": phase, "utc": "2026-11-29T00:00:00.000000Z",
                "elapsed_s": elapsed, "fastboot_present": present,
                "fastboot_serials": [SERIAL] if present else [],
                "fastboot_exit_code": 0,
                "usb": usb or {"available": True, "devices": []}}

    def test_load_error_wins_even_if_the_device_also_vanishes(self):
        timeline = [self.observation(index * 0.1, False) for index in range(10)]
        boot = {"exit_code": 1, "timed_out": False,
                "stdout": "Sending 'boot.img' OKAY", "stderr": "FAILED (remote: 'Load Error')"}
        verdict = LADDER.classify_verdict(timeline=timeline, boot=boot,
                                          cold_restart={"requested": False},
                                          pre_present=True, min_absence_seconds=0.2)
        self.assertEqual(verdict["code"], "load_error")
        self.assertTrue(verdict["anomalies"])

    def test_booting_okay_and_load_error_together_is_flagged(self):
        boot = {"exit_code": 1, "timed_out": False, "stdout": "Booting OKAY",
                "stderr": "FAILED (remote: 'Load Error')"}
        verdict = LADDER.classify_verdict(timeline=[self.observation(0.1, True)], boot=boot,
                                          cold_restart={"requested": False},
                                          pre_present=True, min_absence_seconds=0.2)
        self.assertEqual(verdict["code"], "load_error")
        self.assertTrue(any("stale-bootloader" in note for note in verdict["anomalies"]))

    def test_absence_shorter_than_the_minimum_is_not_a_positive(self):
        timeline = [self.observation(0.0, False), self.observation(0.5, False),
                    self.observation(1.0, True)]
        verdict = LADDER.classify_verdict(timeline=timeline, boot={"exit_code": 0},
                                          cold_restart={"requested": False},
                                          pre_present=True, min_absence_seconds=10.0)
        self.assertEqual(verdict["code"], "disconnected_then_returned_to_fastboot")

    def test_verdict_interpretation_is_defined_for_every_verdict(self):
        for code in (LADDER.VERDICT_DISCONNECTED, LADDER.VERDICT_ACCEPTED_RETURNED,
                     LADDER.VERDICT_DISCONNECTED_RETURNED, LADDER.VERDICT_LOAD_ERROR,
                     LADDER.VERDICT_NO_DEVICE, LADDER.VERDICT_COLD_RESTART_FAILED,
                     LADDER.VERDICT_BOOT_TIMEOUT):
            entry = LADDER.VERDICT_INTERPRETATION[code]
            self.assertTrue(entry["proves"], f"{code} must state what it proves")
            self.assertTrue(entry["does_not_prove"],
                            f"{code} must state what it does not prove")
        self.assertNotIn("booted", " ".join(
            " ".join(entry["proves"]) for entry in LADDER.VERDICT_INTERPRETATION.values()
        ).lower().replace("bootloader", ""))


if __name__ == "__main__":
    unittest.main()
