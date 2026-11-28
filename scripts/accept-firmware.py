#!/usr/bin/env python3
"""Inspect an onyx UEFI FD and verify its nested module contents.

This is an offline artifact-format check, not a firmware build or device test.
The FD is parsed from its FV bytes; build listings are never consulted.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import lzma
import re
import struct
import subprocess
import sys
import uuid
from pathlib import Path

FD_BYTES = 0x300000
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024
NESTED_FFS_GUID = "9E21FD93-9C72-4C15-8C4B-E77F1DB2D792"
LZMA_GUID = "EE4E5898-3914-4259-9D6E-DC7BD79403CF"

# SEC lives in the compact outer volume beside the compressed inner one, so a
# guard that only exists in source is invisible there. Take the diagnostic
# markers from the SEC source itself and require them in the outer volume.
SEC_SOURCE = Path("Silicon/Silicium/SiliciumPkg/Sec/OnyxHandoff.c")
SEC_MARKER_RE = re.compile(r'"(ONYX: [^"\\]+)')

# Source inputs come from the pinned UniXNU and Mu-Silicium trees. GUID values
# are extracted from each INF so the report also records the INF content hash.
MODULE_INFS = {
    "UniXNU": ("unixnu", "package/UniXNUPkg/Application/UniXNU/UniXNU.inf"),
    "UniXNUDxe": ("unixnu", "package/UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf"),
    "DarwinBoot": ("unixnu", "drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.inf"),
    "UniXNURamDiskDxe": ("unixnu", "package/UniXNUPkg/Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.inf"),
    "DiskIoDxe": ("uefi", "Mu_Basecore/MdeModulePkg/Universal/Disk/DiskIoDxe/DiskIoDxe.inf"),
    "PartitionDxe": ("uefi", "Mu_Basecore/MdeModulePkg/Universal/Disk/PartitionDxe/PartitionDxe.inf"),
    "Fat": ("uefi", "Mu_Basecore/FatPkg/EnhancedFatDxe/Fat.inf"),
    "EnglishDxe": ("uefi", "Mu_Basecore/MdeModulePkg/Universal/Disk/UnicodeCollation/EnglishDxe/EnglishDxe.inf"),
    "AdvancedLogDxe": ("unixnu", "package/UniXNUPkg/Driver/AdvancedLogDxe/AdvancedLogDxe.inf"),
}
INF_GUID_RE = re.compile(r"^\s*FILE_GUID\s*=\s*([0-9a-fA-F-]{36})\s*(?:#.*)?$", re.MULTILINE)

# Reuse the strict FV/FFS/section bounds and checksum parser already maintained
# by this device repository's historical Mu FV inspector. Do not use its
# historical hash or hard-coded module set for current acceptance.
INSPECTOR_PATH = Path(__file__).resolve().with_name("inspect-mu-fv.py")
_SPEC = importlib.util.spec_from_file_location("onyx_inspect_mu_fv", INSPECTOR_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"cannot load FV parser: {INSPECTOR_PATH}")
_FV = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FV)


def _source_identity(path: Path) -> dict:
    """Return a revision and dirty marker without claiming dirty sources match the FD."""
    try:
        head = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            check=True, capture_output=True, text=True,
        ).stdout
        return {"head": head, "dirty": bool(status.strip()), "status_lines": len(status.splitlines())}
    except (OSError, subprocess.CalledProcessError):
        return {"head": None, "dirty": None, "status_lines": None}


def _inf_guid(path: Path) -> tuple[str, str]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError(f"missing module INF: {path}") from error
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as error:
        raise ValueError(f"module INF is not UTF-8: {path}") from error
    matches = INF_GUID_RE.findall(text)
    if len(matches) != 1:
        raise ValueError(f"expected one FILE_GUID in {path}, found {len(matches)}")
    try:
        value = str(uuid.UUID(matches[0])).upper()
    except ValueError as error:
        raise ValueError(f"invalid FILE_GUID in {path}: {matches[0]}") from error
    return value, hashlib.sha256(raw).hexdigest()


def _sec_markers(uefi: Path) -> list[str]:
    source = uefi / SEC_SOURCE
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return []
    markers = []
    for found in SEC_MARKER_RE.findall(text):
        marker = found.split("%")[0].strip()
        if len(marker) > 12:
            markers.append(marker)
    return sorted(set(markers))


def _decompress_lzma(payload: bytes) -> bytes:
    if len(payload) < 13:
        raise ValueError("nested FV LZMA stream is truncated")
    # LZMA-alone carries an uncompressed-size header. Bound both the advertised
    # value and actual decoder output before accepting any nested FV bytes.
    advertised = int.from_bytes(payload[5:13], "little")
    if advertised not in (0xFFFFFFFFFFFFFFFF,) and (advertised == 0 or advertised > MAX_DECOMPRESSED_BYTES):
        raise ValueError("nested FV LZMA output size is invalid or exceeds the limit")
    try:
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE, memlimit=128 * 1024 * 1024)
        decoded = decoder.decompress(payload, max_length=MAX_DECOMPRESSED_BYTES + 1)
    except (lzma.LZMAError, EOFError) as error:
        raise ValueError(f"nested FV LZMA stream is corrupt: {error}") from error
    if len(decoded) > MAX_DECOMPRESSED_BYTES:
        raise ValueError("nested FV LZMA output exceeds the safety limit")
    if not decoder.eof or decoder.unused_data:
        raise ValueError("nested FV LZMA stream is incomplete or has trailing bytes")
    if advertised not in (0xFFFFFFFFFFFFFFFF,) and len(decoded) != advertised:
        raise ValueError("nested FV LZMA output length disagrees with its header")
    return decoded


def _expected_module_guids(unixnu: Path, uefi: Path) -> tuple[dict, dict]:
    expected, sources = {}, {}
    roots = {"unixnu": unixnu, "uefi": uefi}
    for name, (root_key, relative) in MODULE_INFS.items():
        path = roots[root_key] / relative
        guid, digest = _inf_guid(path)
        expected[name] = guid
        sources[name] = {"inf": str(path), "inf_sha256": digest, "guid": guid}
    if len(set(expected.values())) != len(expected):
        raise ValueError("required module INFs do not have unique FILE_GUID values")
    return expected, sources


def inspect_fd(fd: Path, unixnu: Path, uefi: Path) -> dict:
    fd, unixnu, uefi = Path(fd).resolve(strict=True), Path(unixnu).resolve(strict=True), Path(uefi).resolve(strict=True)
    data = fd.read_bytes()
    if len(data) != FD_BYTES:
        raise ValueError(f"firmware FD must be exactly 0x{FD_BYTES:x} bytes; got 0x{len(data):x}")

    try:
        outer = _FV.parse_fv(data, 0, expected_length=FD_BYTES, label="outer FVMAIN_COMPACT")
    except (ValueError, IndexError, struct.error) as error:
        raise ValueError(f"invalid outer FVMAIN_COMPACT: {error}") from error
    wrappers = [item for item in outer["ffs"] if item["guid"] == NESTED_FFS_GUID]
    if len(wrappers) != 1:
        raise ValueError(f"expected one nested-FV wrapper FFS, found {len(wrappers)}")
    wrapper = wrappers[0]
    try:
        wrapper_sections = _FV.sections(data, wrapper)
    except (ValueError, IndexError, struct.error) as error:
        raise ValueError(f"invalid nested-FV wrapper sections: {error}") from error
    guided = [item for item in wrapper_sections if item["type"] == 0x02]
    if len(guided) != 1:
        raise ValueError(f"expected one GUID-defined LZMA section, found {len(guided)}")
    section = guided[0]
    section_end = section["offset"] + section["size"]
    if section["offset"] + 24 > section_end:
        raise ValueError("nested-FV GUID-defined section header is truncated")
    section_guid = str(uuid.UUID(bytes_le=data[section["data"]:section["data"] + 16])).upper()
    data_offset, attributes = int.from_bytes(data[section["data"] + 16:section["data"] + 18], "little"), int.from_bytes(data[section["data"] + 18:section["data"] + 20], "little")
    if section_guid != LZMA_GUID or data_offset < 24 or data_offset > section["size"]:
        raise ValueError("nested-FV GUID-defined section has wrong GUID or invalid data offset")
    if not (attributes & 1):
        raise ValueError("nested-FV LZMA section does not require processing")
    compressed = data[section["offset"] + data_offset:section_end]
    decoded = _decompress_lzma(compressed)

    # Mu's FV-guided-section output carries a short wrapper prefix ahead of the
    # real inner FV. Its bytes encode the FV length, so locate the FV header
    # structurally instead of trusting a fixed constant that changes with size.
    signature = decoded.find(b"_FVH")
    if signature < 40:
        raise ValueError("decoded nested-FV wrapper does not contain an FV header")
    start = signature - 40
    if start > 16:
        raise ValueError("decoded nested-FV wrapper prefix is unrecognized")
    inner_data = decoded[start:]
    try:
        inner = _FV.parse_fv(inner_data, 0, label="inner FVMAIN")
    except (ValueError, IndexError, struct.error) as error:
        raise ValueError(f"invalid decompressed inner FVMAIN: {error}") from error
    if inner["length"] != len(inner_data):
        raise ValueError("decompressed inner FV has extra or missing bytes")

    markers = _sec_markers(uefi)
    missing = [marker for marker in markers if marker.encode() not in data]
    if missing:
        raise ValueError(
            "the SEC handoff guard is not compiled into the compact outer FV: "
            + "; ".join(missing))

    expected, sources = _expected_module_guids(unixnu, uefi)
    actual = {}
    for name, guid in expected.items():
        found = [item for item in inner["ffs"] if item["guid"] == guid]
        if len(found) != 1:
            raise ValueError(f"required module {name} ({guid}) must occur exactly once in inner FV; found {len(found)}")
        item = found[0]
        actual[name] = {"guid": guid, "count": 1, "offset": item["offset"], "size": item["size"], "type": item["type"], "inf": sources[name]["inf"], "inf_sha256": sources[name]["inf_sha256"]}

    return {
        "schema_version": 1,
        "artifact": str(fd),
        "fd_bytes": len(data),
        "fd_sha256": hashlib.sha256(data).hexdigest(),
        "hardware_tested": False,
        "source_revisions": {"unixnu": _source_identity(unixnu), "uefi": _source_identity(uefi)},
        "outer_fv": {"guid": outer["guid"], "length": outer["length"], "ffs_count": len(outer["ffs"])},
        "nested_fv": {"wrapper_ffs_guid": NESTED_FFS_GUID, "compression_guid": section_guid, "compressed_bytes": len(compressed), "decoded_bytes": len(decoded), "wrapper_prefix_bytes": start, "inner_fv_length": inner["length"], "inner_ffs_count": len(inner["ffs"])},
        "modules": actual,
        "sec_guard_markers": {"checked": len(markers), "missing": len(missing)},
        "notice": "Host-side FD structure/module check only; no firmware build, authenticity, device boot, or log export is proven.",
    }


def main(argv=None) -> int:
    device = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fd", type=Path, required=True, help="built firmware FD binary")
    parser.add_argument("--unixnu", type=Path, default=device.parent / "UniXNU", help="pinned UniXNU source checkout")
    parser.add_argument("--uefi", type=Path, default=device.parent / "Mu-Silicium", help="pinned Mu-Silicium checkout, including Mu_Basecore")
    parser.add_argument("--json", nargs="?", const="-", metavar="PATH", help="write acceptance manifest (default: stdout)")
    args = parser.parse_args(argv)
    try:
        report = inspect_fd(args.fd, args.unixnu, args.uefi)
    except (OSError, ValueError, RuntimeError, struct.error) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json == "-":
        print(output, end="")
    elif args.json:
        Path(args.json).write_text(output, encoding="utf-8")
    else:
        print(f"FD SHA-256: {report['fd_sha256']}")
        print(f"FD size: {report['fd_bytes']} bytes")
        print(f"Validated required modules from inner FV: {', '.join(report['modules'])}")
        print(report["notice"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
