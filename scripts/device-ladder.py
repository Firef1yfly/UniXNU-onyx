#!/usr/bin/env python3
"""Capture hash-bound, cold-restart-labelled evidence from the onyx verification ladder.

Why this exists
---------------
`docs/TAKEOVER-UEFI.md` ("Device attempts 2026-11-28") records that one
`Booting OKAY` from `fastboot boot` proves nothing on this board. The same file
printed both `Booting OKAY` and
`Failed to load/authenticate boot image: Load Error` depending on what a
previous failed attempt had left in the bootloader. The ABL also computes the
jump address as load address plus the ARM64 header's `text_offset`, so an image
whose field still holds the firmware base is downloaded, acknowledged and never
executed. The panel is dark until the second stage, so screen state is not a
signal either.

The only on-device signals this project actually has are:

1. whether the bootloader was freshly re-initialised before the attempt, and
2. whether the device left USB after the download and stayed away.

This harness makes both explicit, binds them to the SHA-256 of the exact file
that was downloaded, and derives a verdict from an observation state machine
rather than from the transfer acknowledgement. The verdict record states what it
does and does not establish.

Safety boundary
---------------
The script can issue exactly these device commands. `assert_safety_boundary()`
checks the allowlist before anything runs, and `run_device_command()` — the only
place in this module that starts a process — re-checks every argv:

    fastboot [-s SERIAL] devices
    fastboot [-s SERIAL] getvar <name>            name in GETVAR_NAMES only
    fastboot [-s SERIAL] reboot-bootloader        only with --cold-restart
    fastboot [-s SERIAL] boot <image>             only in `boot`, after the checks
    adb [-s SERIAL] devices                       listing only

`flash`, `erase`, `oem`, `format`, `write`, `wipe`, `set_active`, `sideload` and
`update` are refused as a substring of any argument of any argv, so a partition
write cannot be expressed here — not even accidentally by a future edit that
does not go out of its way to remove the check.

`attach` issues no device command at all: it only appends hash-bound panel
photographs to a record that `boot` already wrote, one label per photograph, and
never rewrites that record's verdict, image hash or hash confirmation. The panel
is where the stages the host cannot see are recorded, so a frame that is not
typed, hashed and labelled is not evidence.

Evidence classes
----------------
A record this script writes from a real run is an on-device observation. The
unit tests for this module drive stub `fastboot`/`adb` binaries in a temporary
directory and are host-side evidence only; they can show the state machine and
the refusals behave, never that any verdict occurs on the phone.

Exit codes
----------
0  a positive verdict was recorded (`disconnected_after_boot`)
1  a verdict was recorded that is not positive, or no device was present
2  command-line usage error (argparse)
3  the run refused to touch the device, and said exactly why
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

DEVICE = Path(__file__).resolve().parent.parent
DEFAULT_RECORD_DIR = DEVICE / "docs" / "bringup"

EXIT_POSITIVE = 0
EXIT_NOT_PROVEN = 1
EXIT_USAGE = 2
EXIT_REFUSED = 3

# Android boot image geometry. The kernel field of a v3/v4 image starts at the
# next 4096-byte boundary after the declared header size; for v0-v2 it starts at
# the declared page size. Within the kernel field the ARM64 Linux Image header
# begins at offset 0, so `text_offset` sits at file offset kernel_field + 8.
PAGE = 4096
BOOT_MAGIC = b"ANDROID!"
HEADER_SIZE_OFFSET = 20          # v3/v4 header_size
PAGE_SIZE_OFFSET = 36            # v0/v1/v2 page_size
HEADER_VERSION_OFFSET = 40
TEXT_OFFSET_POSITION = 8
IMAGE_SIZE_POSITION = 16
ARM64_MAGIC_POSITION = 56
ARM64_MAGIC = b"ARM\x64"
KERNEL_SIZE_OFFSET = 8
RAMDISK_SIZE_OFFSET = 12

# Read-only `getvar` names only. Anything else is refused rather than forwarded,
# so the boundary stays auditable even if fastboot grows more verbs.
GETVAR_NAMES = (
    "product",
    "current-slot",
    "unlocked",
    "slot-unlocked",
    "version-bootloader",
    "version-baseband",
)

# Substrings that may never appear in any argument (image, path, serial, name).
# `flash` is refused outright by the task; the rest close the partition-write
# surface that would otherwise be reachable through fastboot verbs.
FORBIDDEN_SUBSTRINGS = (
    "flash",
    "erase",
    "oem",
    "format",
    "write",
    "wipe",
    "set_active",
    "set-active",
    "sideload",
    "update",
    "partition",
)

FASTBOOT_SUBCOMMANDS = ("devices", "getvar", "reboot-bootloader", "boot")
ADB_SUBCOMMANDS = ("devices",)
DEVICE_TOOLS = ("fastboot", "adb")

# The allowlist in the form a human audits it. `assert_safety_boundary()` walks
# these tokens through the same check each real argv goes through.
DEVICE_COMMAND_TEMPLATES = (
    ("fastboot", "devices"),
    ("fastboot", "-s", "<serial>", "devices"),
    ("fastboot", "-s", "<serial>", "getvar", "<getvar-name>"),
    ("fastboot", "-s", "<serial>", "reboot-bootloader"),
    ("fastboot", "-s", "<serial>", "boot", "<image>"),
    ("adb", "devices"),
    ("adb", "-s", "<serial>", "devices"),
)

# USB ids observed on this board (docs/TAKEOVER-UEFI.md): the bootloader
# enumerates as 18d1:d00d while fastboot is in control, and Android as
# 18d1:4e11. Corroboration only; presence decisions use `fastboot devices`.
FASTBOOT_USB_IDS = ("18d1:d00d",)
ANDROID_USB_IDS = ("18d1:4e11", "18d1:4ee7", "18d1:4e40")
USB_ROOT_ENV = "LADDER_USB_ROOT"

LOAD_ERROR_PATTERNS = (
    "failed to load",
    "load error",
    "failed (remote",
    "cannot load",
    "unknown error",
)

VERDICT_DISCONNECTED = "disconnected_after_boot"
VERDICT_ACCEPTED_RETURNED = "accepted_and_returned_to_fastboot"
VERDICT_DISCONNECTED_RETURNED = "disconnected_then_returned_to_fastboot"
VERDICT_LOAD_ERROR = "load_error"
VERDICT_NO_DEVICE = "no_device"
VERDICT_COLD_RESTART_FAILED = "cold_restart_failed"
VERDICT_BOOT_TIMEOUT = "boot_command_timeout"

POSITIVE_VERDICTS = (VERDICT_DISCONNECTED,)

# Every verdict states its own limits. Nothing here is allowed to say "booted".
VERDICT_INTERPRETATION = {
    VERDICT_DISCONNECTED: {
        "summary": (
            "The download was acknowledged, the device then left USB and stayed "
            "away for the whole observation window."
        ),
        "proves": [
            "the bootloader stopped servicing its own fastboot loop after the download, "
            "so control left it: something in the image is holding, faulting or resetting "
            "the CPU",
            "the transport works end to end for this exact image hash: download, header "
            "acceptance and the jump",
        ],
        "does_not_prove": [
            "which stage the firmware reached (SEC, DXE, BDS, menu); the dark panel is not "
            "a signal on this board",
            "that the firmware is healthy: a hang and a crash look identical from the host, "
            "and the bootloader watchdog resets the board in both cases",
            "that any payload or menu was reached",
        ],
    },
    VERDICT_ACCEPTED_RETURNED: {
        "summary": (
            "The device never left USB: the transfer was acknowledged but the bootloader "
            "stayed in its own loop for the whole observation window."
        ),
        "proves": [
            "only that fastboot accepted the download; nothing about the image executing",
        ],
        "does_not_prove": [
            "that the image was executed, or that its header was even honoured",
            "anything about the firmware: this is the signature that was observed for "
            "images whose text_offset sent the jump past the end of RAM",
        ],
    },
    VERDICT_DISCONNECTED_RETURNED: {
        "summary": (
            "The device left USB after the download and came back into fastboot within "
            "the window, i.e. it reset before the observation minimum elapsed."
        ),
        "proves": [
            "the device stopped answering fastboot and re-enumerated; the interruption is "
            "real and timed, not inferred from a printed string",
        ],
        "does_not_prove": [
            "that the image executed: a reset can come from the image faulting in its first "
            "instructions or from the bootloader aborting without printing a verdict",
            "how far the firmware got, if it ran at all",
        ],
    },
    VERDICT_LOAD_ERROR: {
        "summary": (
            "fastboot reported a load/authentication failure, or exited non-zero, so the "
            "image was refused before any question of execution arises."
        ),
        "proves": [
            "the bootloader rejected this transfer in this bootloader state; the image was "
            "not executed",
        ],
        "does_not_prove": [
            "that the image is bad: the same file has reported both `Booting OKAY` and "
            "`Load Error` depending on the state left by the previous attempt, which is why "
            "a cold restart is recorded beside every result",
        ],
    },
    VERDICT_NO_DEVICE: {
        "summary": "No fastboot device was present, so nothing was downloaded or booted.",
        "proves": ["nothing about any image"],
        "does_not_prove": [
            "anything about the image, the firmware or the port; no device was touched",
        ],
    },
    VERDICT_COLD_RESTART_FAILED: {
        "summary": (
            "A cold restart was requested but the bootloader did not come back into "
            "fastboot in time, so no boot was attempted."
        ),
        "proves": ["the device is not usable as a test target in this run"],
        "does_not_prove": ["anything about any image"],
    },
    VERDICT_BOOT_TIMEOUT: {
        "summary": (
            "`fastboot boot` itself did not return within the transfer timeout; the "
            "download stalled, so there is no attempt to interpret."
        ),
        "proves": ["the transfer did not complete within the limit"],
        "does_not_prove": [
            "whether the image would execute; the device may still hold a partial transfer "
            "and needs a cold restart before the next attempt",
        ],
    },
}


class Refusal(Exception):
    """The run stopped before touching the device, and can name why."""

    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict:
        return {"refused": True, "code": self.code, "message": self.message,
                "details": self.details}


class ToolMissing(Refusal):
    def __init__(self, tool: str):
        super().__init__(
            "tool_missing",
            f"`{tool}` is not on PATH; the harness will not guess a path for a device tool",
            tool=tool,
        )


# --------------------------------------------------------------------------
# Safety boundary
# --------------------------------------------------------------------------

def _device_subcommand(argv) -> tuple[int | None, str | None]:
    """Return (index, token) of the fastboot/adb subcommand in argv."""
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in ("-s", "--serial"):
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return index, token
    return None, None


def assert_allowed_device_command(argv) -> None:
    """Raise Refusal unless argv is one of the allowlisted read-only commands."""
    if not argv:
        raise Refusal("empty_command", "refusing to run an empty argv")
    tool = Path(argv[0]).name
    for token in argv:
        lowered = str(token).lower()
        for forbidden in FORBIDDEN_SUBSTRINGS:
            if forbidden in lowered:
                raise Refusal(
                    "unsafe_argument",
                    f"argument {token!r} contains {forbidden!r}; no flash, erase, oem or "
                    "partition-writing verb exists in this harness",
                    argument=str(token),
                    forbidden_word=forbidden,
                )
    if tool not in DEVICE_TOOLS:
        raise Refusal("unknown_tool", f"only {DEVICE_TOOLS} may be run, not {tool!r}", tool=tool)
    index, subcommand = _device_subcommand(argv)
    allowed = FASTBOOT_SUBCOMMANDS if tool == "fastboot" else ADB_SUBCOMMANDS
    if subcommand is None or subcommand not in allowed:
        raise Refusal(
            "unsafe_subcommand",
            f"`{tool} {subcommand}` is not in the allowlist {allowed}",
            tool=tool,
            subcommand=subcommand,
        )
    if tool == "fastboot" and subcommand == "getvar":
        name_index = index + 1
        name = argv[name_index] if name_index < len(argv) else None
        if name not in GETVAR_NAMES:
            raise Refusal(
                "unsafe_getvar",
                f"getvar name {name!r} is not one of {GETVAR_NAMES}",
                getvar=name,
            )
    if tool == "fastboot" and subcommand == "boot":
        extra = list(argv[index + 1:])
        if len(extra) != 1:
            raise Refusal(
                "unsafe_boot_argv",
                "`fastboot boot` takes exactly the image path here; "
                f"got {len(extra)} trailing arguments",
                arguments=extra,
            )
    if tool == "fastboot" and subcommand == "reboot-bootloader" and len(argv) != index + 1:
        raise Refusal(
            "unsafe_reboot_argv",
            "`fastboot reboot-bootloader` takes no arguments in this harness",
            arguments=list(argv[index + 1:]),
        )
    if tool == "fastboot" and subcommand == "devices" and len(argv) != index + 1:
        raise Refusal("unsafe_devices_argv", "`fastboot devices` takes no arguments in this harness")


PLACEHOLDERS = {
    "<serial>": "5d7b86fd",
    "<getvar-name>": GETVAR_NAMES[0],
    "<image>": "/tmp/example-boot.img",
}


def assert_safety_boundary() -> None:
    """Fail closed if the declared allowlist has drifted from the safety rules."""
    for template in DEVICE_COMMAND_TEMPLATES:
        argv = [PLACEHOLDERS.get(token, token) for token in template]
        try:
            assert_allowed_device_command(argv)
        except Refusal as refusal:  # pragma: no cover - only on a broken template
            raise AssertionError(
                f"allowlist template {template} violates the safety boundary: {refusal.message}"
            ) from refusal
    if not any("boot" in template for template in DEVICE_COMMAND_TEMPLATES):
        raise AssertionError("the `boot` template vanished from the allowlist")
    for token in ("flash", "erase", "oem", "format", "write", "wipe", "sideload"):
        if token not in FORBIDDEN_SUBSTRINGS:
            raise AssertionError(f"{token!r} disappeared from FORBIDDEN_SUBSTRINGS")
    if "flash" in FASTBOOT_SUBCOMMANDS or "flash" in ADB_SUBCOMMANDS:
        raise AssertionError("a flash verb reached the subcommand allowlist")


def safety_summary() -> dict:
    """The boundary in machine-readable form, for the owner to audit."""
    return {
        "device_command_templates": [
            " ".join(template) for template in DEVICE_COMMAND_TEMPLATES
        ],
        "fastboot_subcommands": list(FASTBOOT_SUBCOMMANDS),
        "adb_subcommands": list(ADB_SUBCOMMANDS),
        "getvar_names": list(GETVAR_NAMES),
        "forbidden_argument_substrings": list(FORBIDDEN_SUBSTRINGS),
        "partition_writes_possible": False,
        "single_process_choke_point": "run_device_command",
    }


# --------------------------------------------------------------------------
# Device commands: one choke point
# --------------------------------------------------------------------------

def run_device_command(argv, *, timeout, commands_log):
    """Run one allowlisted device command and record it in commands_log."""
    assert_allowed_device_command(argv)
    tool = Path(argv[0]).name
    resolved = argv[0] if os.path.isabs(argv[0]) else (sys_which(tool) or argv[0])
    if not os.path.exists(resolved):
        raise ToolMissing(tool)
    commands_log.append(" ".join(argv))
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as expired:
        return {
            "argv": " ".join(argv),
            "exit_code": None,
            "timed_out": True,
            "stdout": _as_text(expired.stdout),
            "stderr": _as_text(expired.stderr),
        }
    except FileNotFoundError as error:  # pragma: no cover - guarded above
        raise ToolMissing(tool) from error
    return {
        "argv": " ".join(argv),
        "exit_code": completed.returncode,
        "timed_out": False,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def sys_which(tool: str) -> str | None:
    """Resolve a device tool through PATH; the harness never guesses a location."""
    return shutil.which(tool)


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _fastboot_argv(serial, *rest):
    if serial:
        return ["fastboot", "-s", serial, *rest]
    return ["fastboot", *rest]


def parse_fastboot_devices(text: str) -> list[dict]:
    """Parse `fastboot devices` output into [{serial, state}]."""
    found = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1].startswith("fastboot"):
            found.append({"serial": fields[0], "state": fields[1]})
    return found


def parse_getvar_text(text: str) -> dict:
    """Parse `(bootloader) key: value` lines (fastboot writes them to stderr)."""
    values = {}
    for line in text.splitlines():
        match = re.match(r"^\(bootloader\)\s+([A-Za-z0-9:_-]+):\s*(.*)$", line.strip())
        if not match:
            match = re.match(r"^([A-Za-z0-9:_-]+):\s*(.*)$", line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def parse_adb_devices(text: str) -> list[dict]:
    found = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] in ("device", "offline", "unauthorized",
                                              "recovery", "sideload", "bootloader"):
            found.append({"serial": fields[0], "state": fields[1]})
    return found


def list_fastboot_devices(*, serial=None, commands_log, timeout=30):
    result = run_device_command(_fastboot_argv(serial, "devices"), timeout=timeout,
                                commands_log=commands_log)
    devices = parse_fastboot_devices(result["stdout"] + "\n" + result["stderr"])
    return result, devices


def list_adb_devices(*, serial=None, commands_log, timeout=30):
    if sys_which("adb") is None:
        return None, []
    result = run_device_command(["adb", *(("-s", serial) if serial else ()), "devices"],
                                timeout=timeout, commands_log=commands_log)
    return result, parse_adb_devices(result["stdout"])


def read_getvars(serial, *, commands_log, timeout=30):
    values = {}
    errors = {}
    for name in GETVAR_NAMES:
        result = run_device_command(_fastboot_argv(serial, "getvar", name),
                                    timeout=timeout, commands_log=commands_log)
        parsed = parse_getvar_text(result["stderr"] + "\n" + result["stdout"])
        if name in parsed:
            values[name] = parsed[name]
        elif result["timed_out"]:
            errors[name] = "timeout"
        else:
            errors[name] = f"unparsed (exit {result['exit_code']})"
    return values, errors


# --------------------------------------------------------------------------
# USB corroboration
# --------------------------------------------------------------------------

def usb_snapshot(root=None) -> dict:
    """List USB vid:pid pairs from sysfs; never touches the device."""
    base = Path(root or os.environ.get(USB_ROOT_ENV, "/sys/bus/usb/devices"))
    if not base.is_dir():
        return {"available": False, "root": str(base), "devices": []}
    pairs = []
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return {"available": False, "root": str(base), "devices": []}
    for entry in entries:
        try:
            vid = (entry / "idVendor").read_text().strip()
            pid = (entry / "idProduct").read_text().strip()
        except OSError:
            continue
        if vid and pid:
            pairs.append(f"{vid.lower()}:{pid.lower()}")
    unique = sorted(set(pairs))
    return {
        "available": True,
        "root": str(base),
        "devices": unique,
        "fastboot_class": [p for p in unique if p in FASTBOOT_USB_IDS],
        "android_class": [p for p in unique if p in ANDROID_USB_IDS],
    }


# --------------------------------------------------------------------------
# Image inspection
# --------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def kernel_field_offset(data: bytes) -> tuple[int, dict]:
    """Return where the kernel payload (and its ARM64 header) starts."""
    if len(data) < HEADER_VERSION_OFFSET + 4:
        raise Refusal("image_truncated",
                      f"image is {len(data)} bytes, too short to hold a boot image header")
    header_version = struct.unpack_from("<I", data, HEADER_VERSION_OFFSET)[0]
    if header_version in (3, 4):
        header_size = struct.unpack_from("<I", data, HEADER_SIZE_OFFSET)[0]
        if header_size == 0:
            raise Refusal("image_truncated", "v3/v4 header declares header_size 0")
        offset = PAGE * max(1, -(-header_size // PAGE))
        geometry = {"header_version": header_version, "header_size": header_size,
                    "header_alignment": PAGE}
    elif header_version in (0, 1, 2):
        page_size = struct.unpack_from("<I", data, PAGE_SIZE_OFFSET)[0]
        if page_size not in (2048, 4096, 8192, 16384):
            raise Refusal(
                "unknown_page_size",
                f"v{header_version} header declares page_size {page_size}; refusing to guess "
                "where the kernel field starts",
                page_size=page_size,
            )
        offset = page_size
        geometry = {"header_version": header_version, "page_size": page_size,
                    "header_alignment": page_size}
    else:
        raise Refusal(
            "unknown_header_version",
            f"header_version {header_version} is not one this harness can locate the ARM64 "
            "header in (0-4); refusing to guess",
            header_version=header_version,
        )
    return offset, geometry


def inspect_boot_image(path: Path) -> dict:
    """Read the boot image header and its ARM64 header; refuse anything ambiguous."""
    if not path.is_file():
        raise Refusal("image_missing", f"image {path} does not exist", path=str(path))
    data = path.read_bytes()
    if data[:8] != BOOT_MAGIC:
        raise Refusal(
            "image_not_android_boot",
            f"{path.name} starts with {data[:8]!r}, not {BOOT_MAGIC!r}; this harness only "
            "boots Android boot images",
            magic=data[:8].hex(),
        )
    offset, geometry = kernel_field_offset(data)
    if offset + ARM64_MAGIC_POSITION + 4 > len(data):
        raise Refusal(
            "image_truncated",
            f"{path.name} declares the kernel field at {offset:#x} but is only {len(data)} "
            "bytes long",
            kernel_field_offset=offset,
        )
    magic = data[offset + ARM64_MAGIC_POSITION:offset + ARM64_MAGIC_POSITION + 4]
    if magic != ARM64_MAGIC:
        raise Refusal(
            "kernel_field_not_arm64",
            f"the kernel field at {offset:#x} carries magic {magic!r}, not {ARM64_MAGIC!r}; "
            "without an ARM64 header there is no text_offset to verify, so the image is "
            "refused instead of booted blind",
            kernel_field_offset=offset,
            magic=magic.hex(),
        )
    text_offset = struct.unpack_from("<Q", data, offset + TEXT_OFFSET_POSITION)[0]
    image_size = struct.unpack_from("<Q", data, offset + IMAGE_SIZE_POSITION)[0]
    flags = struct.unpack_from("<Q", data, offset + 24)[0]
    code0, code1 = struct.unpack_from("<II", data, offset)
    kernel_size = struct.unpack_from("<I", data, KERNEL_SIZE_OFFSET)[0]
    ramdisk_size = struct.unpack_from("<I", data, RAMDISK_SIZE_OFFSET)[0]
    if offset + kernel_size > len(data):
        raise Refusal(
            "image_truncated",
            f"{path.name} declares kernel_size {kernel_size} from {offset:#x}, past the "
            f"{len(data)}-byte file",
            kernel_size=kernel_size,
        )
    header = {
        "boot_magic": data[:8].decode("ascii", "replace"),
        **geometry,
        "kernel_field_offset": offset,
        "kernel_field_offset_hex": hex(offset),
        "kernel_size": kernel_size,
        "ramdisk_size": ramdisk_size,
        "text_offset": text_offset,
        "text_offset_hex": hex(text_offset),
        "text_offset_position": hex(offset + TEXT_OFFSET_POSITION),
        "image_size": image_size,
        "image_size_hex": hex(image_size),
        "flags": flags,
        "code0": hex(code0),
        "code1": hex(code1),
        "arm64_magic": magic.decode("latin-1"),
    }
    return {"path": path, "size": len(data), "header": header, "data": data}


def check_text_offset(inspection: dict) -> None:
    """Refuse an image whose ARM64 text_offset is non-zero, naming the value."""
    header = inspection["header"]
    if header["text_offset"] != 0:
        raise Refusal(
            "text_offset_nonzero",
            f"{inspection['path'].name} carries text_offset {header['text_offset_hex']} at "
            f"file offset {header['text_offset_position']}; the onyx ABL adds it to the jump "
            "address, so this image would be downloaded, acknowledged and never executed. "
            "Repack with scripts/make-menu-image.py, which zeroes the field, instead of "
            "patching bytes by hand",
            text_offset=header["text_offset_hex"],
            text_offset_position=header["text_offset_position"],
        )


def check_confirm_sha256(actual: str, confirm: str) -> None:
    confirm_text = (confirm or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", confirm_text):
        raise Refusal(
            "confirm_sha256_malformed",
            f"--confirm-sha256 must be 64 hex characters, got {confirm!r}",
            confirm_sha256=confirm,
        )
    if confirm_text != actual:
        raise Refusal(
            "sha256_mismatch",
            f"image SHA-256 is {actual}, but --confirm-sha256 says {confirm_text}; "
            "refusing to download an image the caller did not name",
            actual_sha256=actual,
            confirm_sha256=confirm_text,
        )


def check_no_forbidden_argument(values) -> None:
    """Refuse any caller-supplied argument carrying a forbidden substring."""
    for value in values:
        if value is None:
            continue
        lowered = str(value).lower()
        for forbidden in FORBIDDEN_SUBSTRINGS:
            if forbidden in lowered:
                raise Refusal(
                    "unsafe_argument",
                    f"argument {value!r} contains {forbidden!r}; this harness refuses any "
                    "flash/erase/oem/partition-write spelling outright",
                    argument=str(value),
                    forbidden_word=forbidden,
                )


# --------------------------------------------------------------------------
# Observation timeline
# --------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def observe_once(*, serial, commands_log, phase, started) -> dict:
    result, devices = list_fastboot_devices(serial=serial, commands_log=commands_log)
    usb = usb_snapshot()
    return {
        "phase": phase,
        "utc": utc_now(),
        "elapsed_s": round(time.monotonic() - started, 3),
        "fastboot_present": bool(devices),
        "fastboot_serials": [device["serial"] for device in devices],
        "fastboot_exit_code": result["exit_code"],
        "usb": usb,
    }


def absence_intervals(observations) -> list[dict]:
    """Contiguous runs of observations where no fastboot device was visible."""
    intervals = []
    current = None
    for index, observation in enumerate(observations):
        if observation["fastboot_present"]:
            if current is not None:
                current["end_elapsed_s"] = observations[index - 1]["elapsed_s"]
                current["duration_s"] = round(
                    current["end_elapsed_s"] - current["start_elapsed_s"], 3)
                intervals.append(current)
                current = None
        elif current is None:
            current = {"start_elapsed_s": observation["elapsed_s"],
                       "start_utc": observation["utc"],
                       "end_elapsed_s": observation["elapsed_s"]}
    if current is not None:
        current["end_elapsed_s"] = observations[-1]["elapsed_s"]
        current["duration_s"] = round(current["end_elapsed_s"] - current["start_elapsed_s"], 3)
        intervals.append(current)
    return intervals


def ended_in(post_observations) -> str:
    if not post_observations:
        return "unknown"
    last = post_observations[-1]
    if last["fastboot_present"]:
        return "fastboot"
    usb = last.get("usb") or {}
    if usb.get("android_class"):
        return "android"
    if usb.get("available") and not usb.get("devices"):
        return "absent_from_usb"
    if usb.get("available") and usb.get("devices"):
        return "usb_unknown_class"
    return "unknown"


def classify_verdict(*, timeline, boot, cold_restart, pre_present, min_absence_seconds) -> dict:
    """Derive the verdict from the observation record, never from the OKAY string.

    Precedence is fixed and ordered from "nothing was attempted" to "the transfer
    was acknowledged but the device never left its own loop" so that a weaker
    observation can never mask a stronger one.
    """
    post = [observation for observation in timeline if observation["phase"] == "post_boot"]
    evidence = []
    anomalies = []
    boot_text = ""
    if boot:
        boot_text = f"{boot.get('stdout', '')}\n{boot.get('stderr', '')}".lower()

    if cold_restart.get("requested") and not cold_restart.get("succeeded"):
        code = VERDICT_COLD_RESTART_FAILED
    elif not pre_present:
        code = VERDICT_NO_DEVICE
    elif boot and boot.get("timed_out"):
        code = VERDICT_BOOT_TIMEOUT
    elif boot and (boot.get("exit_code") not in (0, None)
                   or any(pattern in boot_text for pattern in LOAD_ERROR_PATTERNS)):
        code = VERDICT_LOAD_ERROR
        if boot.get("exit_code") == 0:
            evidence.append("fastboot exited 0 but its output carries a load/authentication "
                            "failure string")
    else:
        intervals = absence_intervals(post)
        suffix = None
        if post and not post[-1]["fastboot_present"]:
            run_start = post[-1]
            for observation in reversed(post):
                if observation["fastboot_present"]:
                    break
                run_start = observation
            suffix = {
                "start_elapsed_s": run_start["elapsed_s"],
                "duration_s": round(post[-1]["elapsed_s"] - run_start["elapsed_s"], 3),
            }
        if suffix is not None and suffix["duration_s"] >= min_absence_seconds:
            code = VERDICT_DISCONNECTED
            evidence.append(
                f"the device was absent from fastboot for the last {suffix['duration_s']}s of "
                f"the window (>= {min_absence_seconds}s required), starting at "
                f"+{suffix['start_elapsed_s']}s"
            )
        elif any(interval["duration_s"] > 0 for interval in intervals):
            code = VERDICT_DISCONNECTED_RETURNED
            evidence.append(
                "the device disappeared from fastboot and re-enumerated: "
                + ", ".join(f"+{i['start_elapsed_s']}s for {i['duration_s']}s" for i in intervals)
            )
        else:
            code = VERDICT_ACCEPTED_RETURNED
            evidence.append("no observation in the window ever showed the device missing from "
                            "fastboot")

    correct_anchor = bool(re.search(r"booting\s+okay", boot_text))
    if code in (VERDICT_ACCEPTED_RETURNED, VERDICT_DISCONNECTED, VERDICT_DISCONNECTED_RETURNED):
        evidence.append(
            "fastboot printed `Booting OKAY`" if correct_anchor
            else "fastboot did not print `Booting OKAY`; the verdict does not depend on it"
        )
    if code == VERDICT_LOAD_ERROR:
        absences = absence_intervals(post)
        if any(interval["duration_s"] >= min_absence_seconds for interval in absences):
            anomalies.append(
                "fastboot reported a load failure yet the device also left USB for longer "
                "than the absence minimum; these two observations contradict each other and "
                "the run needs a cold restart before either is trusted"
            )
    if code == VERDICT_LOAD_ERROR and correct_anchor:
        anomalies.append(
            "the same transfer printed both `Booting OKAY` and a load failure; this is the "
            "known stale-bootloader-state confusion, so the result is only interpretable "
            "beside a cold restart"
        )
    if code == VERDICT_DISCONNECTED and boot and boot.get("exit_code") not in (0, None):
        anomalies.append("fastboot exited non-zero yet the device left USB")

    interpretation = VERDICT_INTERPRETATION[code]
    return {
        "code": code,
        "summary": interpretation["summary"],
        "proves": list(interpretation["proves"]),
        "does_not_prove": list(interpretation["does_not_prove"]),
        "evidence": evidence,
        "anomalies": anomalies,
        "positive": code in POSITIVE_VERDICTS,
        "acknowledged_booting_okay": correct_anchor,
        "ended_in": ended_in(post),
        "observation_window_s": round(post[-1]["elapsed_s"], 3) if post else 0.0,
        "min_absence_seconds": min_absence_seconds,
    }


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

def build_record(*, image_info, confirmation, safety, bootloader, pre_state, post_state,
                 timeline, boot, verdict, warnings, argv, options) -> dict:
    return {
        "schema_version": 1,
        "record_kind": "on_device_attempt",
        "generated_at": utc_now(),
        "evidence_class": (
            "on-device observation captured by scripts/device-ladder.py; the module's own "
            "unit tests are mocked host-side evidence and say nothing about the phone"
        ),
        "host": {
            "argv": list(argv),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "device_repo": str(DEVICE),
            "options": options,
        },
        "image": {
            "path": image_info["path"],
            "bytes": image_info["size"],
            "sha256": image_info["sha256"],
            "header": image_info["header"],
        },
        "confirmation": confirmation,
        "safety": safety,
        "bootloader": bootloader,
        "pre_device_state": pre_state,
        "post_device_state": post_state,
        "boot_command": boot,
        "timeline": timeline,
        "verdict": verdict,
        "warnings": warnings,
    }


def record_path(directory: Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = directory / f"ladder-{stamp}.json"
    suffix = 2
    while candidate.exists():
        candidate = directory / f"ladder-{stamp}-{suffix}.json"
        suffix += 1
    return candidate


def write_record(record: dict, directory: Path) -> Path:
    path = record_path(directory)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return path


# --------------------------------------------------------------------------
# Panel evidence
# --------------------------------------------------------------------------

# Only container magic that a camera or `adb exec-out screencap` produces. The
# point is to refuse "whatever file was in the wrong argument slot", not to
# validate image contents.
PANEL_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def panel_format(head: bytes) -> str | None:
    for signature, name in PANEL_SIGNATURES:
        if head.startswith(signature):
            return name
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def describe_panel_file(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise Refusal("panel_file_missing", f"no regular file at {path}", path=str(path))
    with path.open("rb") as handle:
        head = handle.read(16)
    kind = panel_format(head)
    if kind is None:
        raise Refusal(
            "panel_file_not_an_image",
            f"{path.name} is not a PNG/JPEG/GIF/WebP; panel evidence is a photograph of the "
            "screen, and an untyped file cannot be attributed to a frame",
            path=str(path),
        )
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": sha256_file(path), "format": kind}


def pair_notes(photos: list[Path], notes: list[str]) -> list[str]:
    """One label per photograph: either a single note for all, or one each."""
    if not photos:
        raise Refusal("no_panel_evidence", "attach needs at least one --photo")
    if len(notes) == 1:
        return list(notes) * len(photos)
    if len(notes) != len(photos):
        raise Refusal(
            "panel_note_count_mismatch",
            f"{len(photos)} --photo but {len(notes)} --note; give one note per photo or a "
            "single note that covers all of them",
            photos=len(photos),
            notes=len(notes),
        )
    return list(notes)


def recheck_image(record: dict) -> dict:
    """Re-hash the image a record was made against, if it is still on disk."""
    image = record.get("image") or {}
    path, expected = image.get("path"), image.get("sha256")
    if not path or not expected:
        return {"state": "unrecorded"}
    if not Path(path).is_file():
        return {"state": "image_gone", "path": path, "expected_sha256": expected}
    actual = sha256_file(Path(path))
    return {"state": "match" if actual == expected else "MISMATCH",
            "path": path, "expected_sha256": expected, "actual_sha256": actual}


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def run_probe(args) -> int:
    commands_log = []
    result, devices = list_fastboot_devices(commands_log=commands_log)
    device_present = bool(devices)
    selected = args.serial or (devices[0]["serial"] if len(devices) == 1 else None)
    getvars, getvar_errors, getvar_note = {}, {}, None
    if len(devices) > 1 and not args.serial:
        getvar_note = "multiple fastboot devices present; pass --serial to read their variables"
    elif selected:
        getvars, getvar_errors = read_getvars(selected, commands_log=commands_log)
    adb_result, adb_devices = (None, [])
    if not args.no_adb:
        adb_result, adb_devices = list_adb_devices(serial=args.serial, commands_log=commands_log)
    report = {
        "schema_version": 1,
        "record_kind": "read_only_probe",
        "generated_at": utc_now(),
        "fastboot": {
            "devices": devices,
            "raw": (result["stdout"] + result["stderr"]).strip(),
            "exit_code": result["exit_code"],
            "selected_serial": selected,
        },
        "getvar": getvars,
        "getvar_errors": getvar_errors,
        "getvar_note": getvar_note,
        "adb": {
            "available": adb_result is not None,
            "devices": adb_devices,
            "raw": ((adb_result["stdout"] + adb_result["stderr"]).strip()
                    if adb_result else None),
        },
        "usb": usb_snapshot(),
        "device_present": device_present,
        "writes_attempted": 0,
        "safety": {**safety_summary(), "device_commands_run": commands_log},
    }
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return EXIT_POSITIVE if device_present else EXIT_NOT_PROVEN


def run_attach(args) -> int:
    """Bind panel photographs to an existing record; never a device command."""
    path = args.record.expanduser()
    if not path.is_file():
        raise Refusal("record_missing", f"no ladder record at {path}", path=str(path))
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Refusal("record_unreadable", f"{path} is not a JSON record: {error}",
                      path=str(path)) from error
    if record.get("schema_version") != 1 or record.get("record_kind") != "on_device_attempt":
        raise Refusal(
            "record_kind_unsupported",
            "panel evidence attaches only to a schema_version 1 on_device_attempt record; "
            f"{path.name} says schema_version={record.get('schema_version')!r} "
            f"record_kind={record.get('record_kind')!r}",
            path=str(path),
        )

    photos = [Path(item).expanduser() for item in args.photo]
    notes = list(args.note)
    labels = pair_notes(photos, notes)
    described = [describe_panel_file(item) for item in photos]
    recheck = recheck_image(record)
    attached_at = utc_now()

    evidence = record.setdefault("panel_evidence", [])
    for item, label in zip(described, labels):
        evidence.append({
            "attached_at": attached_at,
            "note": label,
            "observer": args.observer,
            "image_sha256": (record.get("image") or {}).get("sha256"),
            "image_sha256_recheck": recheck["state"],
            **item,
        })
    record["panel_evidence_recheck"] = {"utc": attached_at, **recheck}

    notes_log = record.setdefault("panel_notes", [])
    for label in labels:
        if label not in notes_log:
            notes_log.append(label)

    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {
        "record": str(path),
        "record_kind": record["record_kind"],
        "image_sha256": (record.get("image") or {}).get("sha256"),
        "verdict": record.get("verdict"),
        "verdict_changed": False,
        "panel_evidence_count": len(evidence),
        "attached": [{"path": item["path"], "sha256": item["sha256"], "note": label}
                     for item, label in zip(described, labels)],
        "image_sha256_recheck": recheck,
    }
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    if recheck["state"] == "MISMATCH":
        print(
            "WARNING: the image file no longer hashes to the value the record was made "
            "against; the photographs are now bound to a record whose artefact moved.",
            file=sys.stderr,
        )
        return EXIT_NOT_PROVEN
    return EXIT_POSITIVE


def run_boot(args, argv=None) -> int:
    commands_log = []
    image_path = args.image.expanduser()
    check_no_forbidden_argument([str(args.image), args.serial])
    inspection = inspect_boot_image(image_path)
    check_text_offset(inspection)
    actual_sha256 = sha256_file(image_path)
    check_confirm_sha256(actual_sha256, args.confirm_sha256)
    image_info = {
        "path": str(image_path.resolve()),
        "size": inspection["size"],
        "sha256": actual_sha256,
        "header": inspection["header"],
    }
    confirmation = {
        "confirmed_sha256": args.confirm_sha256.strip().lower(),
        "actual_sha256": actual_sha256,
        "matches": True,
    }
    safety = safety_summary()

    started = time.monotonic()
    timeline = []
    warnings = []

    # Pre-flight probe: which device, and in what state.
    pre_result, pre_devices = list_fastboot_devices(commands_log=commands_log)
    pre_state = {
        "utc": utc_now(),
        "fastboot_devices": pre_devices,
        "fastboot_raw": (pre_result["stdout"] + pre_result["stderr"]).strip(),
        "fastboot_exit_code": pre_result["exit_code"],
        "usb": usb_snapshot(),
    }
    pre_present = bool(pre_devices)
    if not pre_present:
        verdict = classify_verdict(timeline=timeline, boot=None, cold_restart={"requested": False},
                                   pre_present=False, min_absence_seconds=args.min_absence_seconds)
        return _finish(args, argv=argv, image_info=image_info, confirmation=confirmation,
                       safety=safety,
                       bootloader={"requested": args.cold_restart, "performed": False,
                                   "fresh": False, "succeeded": False},
                       pre_state=pre_state, post_state=None, timeline=timeline, boot=None,
                       verdict=verdict, warnings=warnings, commands_log=commands_log)
    if args.serial:
        serials = [device["serial"] for device in pre_devices]
        if args.serial not in serials:
            raise Refusal(
                "serial_not_present",
                f"--serial {args.serial!r} is not among the attached fastboot devices {serials}",
                serials=serials,
            )
        serial = args.serial
    elif len(pre_devices) == 1:
        serial = pre_devices[0]["serial"]
    else:
        raise Refusal(
            "ambiguous_devices",
            "more than one fastboot device is attached "
            f"({[d['serial'] for d in pre_devices]}); pass --serial, because this harness will "
            "not guess which phone receives the image",
            serials=[device["serial"] for device in pre_devices],
        )

    bootloader = {"requested": args.cold_restart, "performed": False, "fresh": False,
                  "succeeded": False, "serial": serial}
    if args.cold_restart:
        restart = run_device_command(_fastboot_argv(serial, "reboot-bootloader"),
                                     timeout=args.boot_timeout, commands_log=commands_log)
        bootloader["performed"] = True
        bootloader["command"] = restart
        deadline = time.monotonic() + args.cold_restart_timeout
        reappeared = False
        while time.monotonic() < deadline:
            observation = observe_once(serial=serial, commands_log=commands_log,
                                       phase="cold_restart", started=started)
            timeline.append(observation)
            if observation["fastboot_present"]:
                reappeared = True
                break
            time.sleep(args.poll_interval)
        bootloader["succeeded"] = reappeared
        bootloader["fresh"] = bool(reappeared and restart["exit_code"] == 0)
        if not reappeared:
            bootloader["failure"] = (
                f"the bootloader did not reappear in fastboot within {args.cold_restart_timeout}s"
            )
            bootloader["failure_utc"] = utc_now()
    if not bootloader["fresh"]:
        warnings.append(
            "the bootloader was not freshly re-initialised in this run; the record's device "
            "timeline belongs to whatever state the previous attempt left, and the same image "
            "has been observed to report both `Booting OKAY` and `Load Error` across such "
            "states (docs/TAKEOVER-UEFI.md, `Device attempts 2026-11-28`)"
        )

    if args.cold_restart and not bootloader["succeeded"]:
        verdict = classify_verdict(timeline=timeline, boot=None, cold_restart=bootloader,
                                   pre_present=True, min_absence_seconds=args.min_absence_seconds)
        post_state = {"utc": utc_now(), "fastboot_devices": [], "usb": usb_snapshot()}
        return _finish(args, argv=argv, image_info=image_info, confirmation=confirmation,
                       safety=safety, bootloader=bootloader, pre_state=pre_state, post_state=post_state,
                       timeline=timeline, boot=None, verdict=verdict, warnings=warnings,
                       commands_log=commands_log)

    # The only boot in the module: image path already verified against the hash above.
    boot_argv = _fastboot_argv(serial, "boot", str(image_path.resolve()))
    check_no_forbidden_argument(boot_argv)
    boot = run_device_command(boot_argv, timeout=args.boot_timeout, commands_log=commands_log)
    boot["started_utc"] = utc_now()
    timeline.append(observe_once(serial=serial, commands_log=commands_log,
                                 phase="post_boot", started=started))
    deadline = time.monotonic() + args.observe_seconds
    while time.monotonic() < deadline:
        time.sleep(args.poll_interval)
        timeline.append(observe_once(serial=serial, commands_log=commands_log,
                                     phase="post_boot", started=started))
    post_observations = [observation for observation in timeline
                         if observation["phase"] == "post_boot"]
    post_state = {
        "utc": utc_now(),
        "fastboot_devices": ([{"serial": s} for s in post_observations[-1]["fastboot_serials"]]
                             if post_observations else []),
        "usb": post_observations[-1]["usb"] if post_observations else usb_snapshot(),
    }
    verdict = classify_verdict(timeline=timeline, boot=boot, cold_restart=bootloader,
                               pre_present=True, min_absence_seconds=args.min_absence_seconds)
    if verdict["ended_in"] == "android":
        warnings.append(
            "the device ended in Android; a plain reboot also ends there, so this is not "
            "evidence that `fastboot boot` ran the image (docs/TAKEOVER-UEFI.md)"
        )
    if verdict["code"] == VERDICT_DISCONNECTED and not bootloader["fresh"]:
        warnings.append(
            "the positive observation was taken without a cold restart; re-run with "
            "--cold-restart before treating it as comparable to earlier runs"
        )
    return _finish(args, argv=argv, image_info=image_info, confirmation=confirmation,
                   safety=safety, bootloader=bootloader, pre_state=pre_state, post_state=post_state,
                   timeline=timeline, boot=boot, verdict=verdict, warnings=warnings,
                   commands_log=commands_log)


def _finish(args, *, argv=None, image_info, confirmation, safety, bootloader, pre_state, post_state,
            timeline, boot, verdict, warnings, commands_log) -> int:
    safety = {**safety, "device_commands_run": commands_log}
    record = build_record(
        image_info=image_info,
        confirmation=confirmation,
        safety=safety,
        bootloader=bootloader,
        pre_state=pre_state,
        post_state=post_state,
        timeline=timeline,
        boot=boot,
        verdict=verdict,
        warnings=warnings,
        argv=list(argv or []),
        options={
            "cold_restart": args.cold_restart,
            "observe_seconds": args.observe_seconds,
            "poll_interval": args.poll_interval,
            "boot_timeout": args.boot_timeout,
            "cold_restart_timeout": args.cold_restart_timeout,
            "min_absence_seconds": args.min_absence_seconds,
        },
    )
    path = write_record(record, args.record_dir)
    summary = {
        "record": str(path),
        "record_dir": str(args.record_dir),
        "verdict": verdict["code"],
        "positive": verdict["positive"],
        "summary": verdict["summary"],
        "proves": verdict["proves"],
        "does_not_prove": verdict["does_not_prove"],
        "warnings": warnings,
        "image_sha256": image_info["sha256"],
        "bootloader_fresh": bootloader["fresh"],
        "device_commands": commands_log,
    }
    print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
    return EXIT_POSITIVE if verdict["positive"] else EXIT_NOT_PROVEN


def run_safety(args) -> int:
    print(json.dumps({**safety_summary(), "record_dir_default": str(DEFAULT_RECORD_DIR)},
                     indent=2, sort_keys=True))
    return EXIT_POSITIVE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="device-ladder.py",
        description="Hash-bound, cold-restart-labelled on-device evidence for the onyx "
                    "verification ladder. Never flashes, erases or writes a partition.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See docs/bringup/ladder.md for the procedure and the interpretation rules.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser(
        "probe",
        help="read-only device state as compact JSON; issues no writing command",
        description="Read `fastboot devices`, the allowlisted getvar values and `adb devices`, "
                    "then print one compact JSON object. Nothing is written to the device.",
    )
    probe.add_argument("--serial", help="target serial; required when more than one is attached")
    probe.add_argument("--no-adb", action="store_true", help="skip the `adb devices` listing")

    boot = subparsers.add_parser(
        "boot",
        help="boot one hash-confirmed image and record an observation-based verdict",
        description="Refuse unless the image's SHA-256 matches --confirm-sha256 and its ARM64 "
                    "text_offset is 0, then `fastboot boot` it and derive a verdict from the "
                    "polled observation sequence, not from the transfer acknowledgement.",
    )
    boot.add_argument("--image", type=Path, required=True, help="Android boot image to boot")
    boot.add_argument("--confirm-sha256", required=True,
                      help="the SHA-256 of the exact image the caller intends to download")
    boot.add_argument("--serial", help="target serial; required when more than one is attached")
    boot.add_argument("--cold-restart", action="store_true",
                      help="`fastboot reboot-bootloader` first and wait for the bootloader to "
                           "come back, so the result is bound to a fresh bootloader")
    boot.add_argument("--observe-seconds", type=float, default=120.0,
                      help="how long to poll after the download (default 120; the watchdog "
                           "reset has been seen at about 65s)")
    boot.add_argument("--poll-interval", type=float, default=1.0,
                      help="seconds between observations (default 1.0)")
    boot.add_argument("--boot-timeout", type=float, default=180.0,
                      help="timeout for the download command itself (default 180)")
    boot.add_argument("--cold-restart-timeout", type=float, default=60.0,
                      help="how long to wait for the bootloader to reappear (default 60)")
    boot.add_argument("--min-absence-seconds", type=float, default=10.0,
                      help="how long the device must stay off USB to count as `disconnected` "
                           "(default 10)")
    boot.add_argument("--record-dir", type=Path, default=DEFAULT_RECORD_DIR,
                      help="where ladder-<UTC>.json is written (default docs/bringup)")

    subparsers.add_parser(
        "safety",
        help="print the audited device-command allowlist and exit",
        description="Print exactly which device commands this harness can issue, for audit.",
    )

    attach = subparsers.add_parser(
        "attach",
        help="bind panel photographs to an existing record; issues no device command",
        description="Append hash-bound panel evidence (screenshots or photographs of the debug "
                    "console) to a ladder record, one label per photograph. The boot verdict is "
                    "never rewritten: this adds what the host cannot see, it does not score it.",
    )
    attach.add_argument("--record", type=Path, required=True,
                        help="the ladder-<UTC>.json written by `boot`")
    attach.add_argument("--photo", type=Path, action="append", required=True,
                        help="PNG/JPEG/GIF/WebP of the panel; repeat for each frame")
    attach.add_argument("--note", action="append", required=True,
                        help="what the frame shows; repeat once per photo, or once for all")
    attach.add_argument("--observer", default="", help="who captured the frame (free text)")
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    try:
        assert_safety_boundary()
    except AssertionError as error:  # fail closed before any device contact
        print(json.dumps({"refused": True, "code": "safety_boundary_broken",
                          "message": str(error)}))
        return EXIT_REFUSED
    parser = build_parser()
    args = parser.parse_args(argv[1:])
    try:
        if args.command == "probe":
            return run_probe(args)
        if args.command == "boot":
            return run_boot(args, argv)
        if args.command == "attach":
            return run_attach(args)
        return run_safety(args)
    except Refusal as refusal:
        print(json.dumps(refusal.as_dict(), sort_keys=True, ensure_ascii=False))
        print(f"REFUSED: {refusal.message}", file=sys.stderr)
        return EXIT_REFUSED
    except OSError as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}))
        return EXIT_NOT_PROVEN


if __name__ == "__main__":
    sys.exit(main())
