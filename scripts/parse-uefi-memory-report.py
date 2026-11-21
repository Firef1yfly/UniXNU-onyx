#!/usr/bin/env python3
"""Strict host parser for an onyx UEFI memory/RAM-partition report.

This parser accepts only the versioned JSON contract documented in
``docs/bringup/memory-report-format.md``.  It does not parse Android
/proc/iomem, a Linux DT dump, or another board's candidate values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "onyx-uefi-memory-report"
SCHEMA_VERSION = 1
EFI_MEMORY_DESCRIPTOR_VERSION = 1
EFI_PAGE_SIZE = 4096
EFI_DESCRIPTOR_MIN_SIZE = 40
EFI_DESCRIPTOR_MAX_SIZE = 4096
MAX_DESCRIPTORS = 65536
MAX_PARTITIONS = 4096
U64_MAX = (1 << 64) - 1
# EFI_MEMORY_* flags defined by UEFI 2.10 (including architectural ISA flags).
EFI_MEMORY_ISA_MASK = 0x0FFFF00000000000
EFI_MEMORY_ISA_VALID = 0x4000000000000000
EFI_MEMORY_ATTRIBUTE_MASK = (
    0x1 | 0x2 | 0x4 | 0x8 | 0x10 | 0x1000 | 0x2000 | 0x4000 |
    0x8000 | 0x10000 | 0x20000 | 0x40000 | 0x80000 | 0x100000 |
    EFI_MEMORY_ISA_MASK | 0x4000000000000000 | 0x8000000000000000
)
EFI_MEMORY_TYPES = set(range(14))
HEX64 = re.compile(r"0x[0-9a-fA-F]+\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ReportError(ValueError):
    """A report failed the host-side contract."""


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportError(f"{where} must be an object")
    return value


def _keys(value: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ReportError(f"{where} has unsupported fields: {', '.join(unknown)}")


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ReportError(f"{where} must be a string")
    return value


def _u64(value: Any, where: str, *, nonzero: bool = False) -> int:
    """Read an explicitly hexadecimal JSON integer, never a float or bool."""
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ReportError(f"{where} must be a hexadecimal string such as 0x1000")
    result = int(value, 16)
    if result > U64_MAX or (nonzero and result == 0):
        raise ReportError(f"{where} is outside the 64-bit range")
    return result


def _count(value: Any, where: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum:
        raise ReportError(f"{where} must be an integer in 0..{maximum}")
    return value


def _sha(value: Any, where: str) -> str:
    result = _string(value, where)
    if not SHA256.fullmatch(result):
        raise ReportError(f"{where} must be a lowercase SHA-256")
    return result


def _range(base: Any, length: Any, where: str, *, page_aligned: bool = False) -> tuple[int, int]:
    start = _u64(base, f"{where}.base", nonzero=False)
    size = _u64(length, f"{where}.length", nonzero=True)
    if page_aligned and (start % EFI_PAGE_SIZE or size % EFI_PAGE_SIZE):
        raise ReportError(f"{where} base and length must be EFI-page aligned")
    end = start + size
    if end > (1 << 64):
        raise ReportError(f"{where} overflows the 64-bit address space")
    return start, end


def _normal_hex(value: int) -> str:
    return f"0x{value:x}"


def _check_no_sensitive_text(value: Any, where: str = "report") -> None:
    """Reject accidental Android/proprietary capture labels in this public report."""
    if isinstance(value, str):
        lowered = value.lower()
        for marker in ("/proc/iomem", "android", "luming", "serialno", "serial_number", "imei"):
            if marker in lowered:
                raise ReportError(f"{where} contains forbidden non-UEFI provenance marker {marker!r}")
    elif isinstance(value, dict):
        for key, child in value.items():
            _check_no_sensitive_text(key, f"{where} field")
            _check_no_sensitive_text(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_no_sensitive_text(child, f"{where}[{index}]")


def _parse_descriptor(item: Any, index: int, descriptor_size: int) -> dict[str, Any]:
    item = _object(item, f"memory_map.descriptors[{index}]")
    _keys(item, {"type", "physical_start", "virtual_start", "number_of_pages", "attribute", "end", "descriptor_size"},
          f"memory_map.descriptors[{index}]")
    typ = item.get("type")
    if isinstance(typ, bool) or not isinstance(typ, int) or typ not in EFI_MEMORY_TYPES:
        raise ReportError(f"memory_map.descriptors[{index}].type is not a UEFI memory type")
    physical = _u64(item.get("physical_start"), f"memory_map.descriptors[{index}].physical_start")
    virtual = _u64(item.get("virtual_start"), f"memory_map.descriptors[{index}].virtual_start")
    pages = _u64(item.get("number_of_pages"), f"memory_map.descriptors[{index}].number_of_pages", nonzero=True)
    attribute = _u64(item.get("attribute"), f"memory_map.descriptors[{index}].attribute")
    if physical % EFI_PAGE_SIZE or virtual % EFI_PAGE_SIZE:
        raise ReportError(f"memory_map.descriptors[{index}] addresses must be EFI-page aligned")
    if attribute & ~EFI_MEMORY_ATTRIBUTE_MASK:
        raise ReportError(f"memory_map.descriptors[{index}].attribute has unknown bits")
    if (attribute & EFI_MEMORY_ISA_MASK) and not (attribute & EFI_MEMORY_ISA_VALID):
        raise ReportError(f"memory_map.descriptors[{index}].attribute has ISA bits without EFI_MEMORY_ISA_VALID")
    length = pages * EFI_PAGE_SIZE
    if length > (1 << 64) or physical + length > (1 << 64) or virtual + length > (1 << 64):
        raise ReportError(f"memory_map.descriptors[{index}] physical or virtual range overflows the 64-bit address space")
    end = physical + length
    if item.get("end") is not None and _u64(item["end"], f"memory_map.descriptors[{index}].end") != end:
        raise ReportError(f"memory_map.descriptors[{index}].end does not match its range")
    if item.get("descriptor_size") is not None and item["descriptor_size"] != descriptor_size:
        raise ReportError(f"memory_map.descriptors[{index}].descriptor_size does not match the map")
    # A descriptor larger than the base ABI must be explicitly declared; this is
    # why descriptor_size participates in map_bytes below, rather than being ignored.
    return {"type": typ, "physical_start": _normal_hex(physical), "virtual_start": _normal_hex(virtual),
            "number_of_pages": _normal_hex(pages), "attribute": _normal_hex(attribute),
            "end": _normal_hex(end), "descriptor_size": descriptor_size}


def _parse_memory_map(value: Any) -> dict[str, Any]:
    value = _object(value, "memory_map")
    _keys(value, {"descriptor_version", "descriptor_size", "descriptor_count", "map_bytes", "descriptors"}, "memory_map")
    version = value.get("descriptor_version")
    if version != EFI_MEMORY_DESCRIPTOR_VERSION:
        raise ReportError("memory_map.descriptor_version must be EFI version 1")
    size = value.get("descriptor_size")
    if isinstance(size, bool) or not isinstance(size, int) or size < EFI_DESCRIPTOR_MIN_SIZE or size > EFI_DESCRIPTOR_MAX_SIZE or size % 8:
        raise ReportError("memory_map.descriptor_size must be a multiple of 8 between 40 and 4096")
    descriptors = value.get("descriptors")
    if not isinstance(descriptors, list) or not descriptors:
        raise ReportError("memory_map.descriptors must be a non-empty array")
    count = _count(value.get("descriptor_count"), "memory_map.descriptor_count", MAX_DESCRIPTORS)
    if count != len(descriptors):
        raise ReportError("memory_map.descriptor_count does not match descriptors")
    map_bytes = value.get("map_bytes")
    if isinstance(map_bytes, bool) or not isinstance(map_bytes, int) or map_bytes != count * size:
        raise ReportError("memory_map.map_bytes must equal descriptor_count * descriptor_size")
    parsed = [_parse_descriptor(item, i, size) for i, item in enumerate(descriptors)]
    ranges = sorted((int(item["physical_start"], 16), int(item["end"], 16), i) for i, item in enumerate(parsed))
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] < previous[1]:
            raise ReportError(f"memory_map.descriptors overlap ({previous[2]} and {current[2]})")
    return {"descriptor_version": version, "descriptor_size": size, "descriptor_count": count,
            "map_bytes": map_bytes, "descriptors": parsed}


def _parse_partitions(value: Any) -> dict[str, Any]:
    value = _object(value, "ram_partitions")
    _keys(value, {"protocol_revision", "count", "entries"}, "ram_partitions")
    revision = _u64(value.get("protocol_revision"), "ram_partitions.protocol_revision", nonzero=True)
    if revision != 0x10002:
        raise ReportError("ram_partitions.protocol_revision must be 0x10002")
    count = _count(value.get("count"), "ram_partitions.count", MAX_PARTITIONS)
    if count == 0:
        raise ReportError("ram_partitions.count must be between 1 and 4096")
    entries = value.get("entries")
    if not isinstance(entries, list) or count != len(entries) or not entries:
        raise ReportError("ram_partitions.entries must be a non-empty array matching count")
    parsed = []
    for index, item in enumerate(entries):
        item = _object(item, f"ram_partitions.entries[{index}]")
        _keys(item, {"base", "available_length", "end"}, f"ram_partitions.entries[{index}]")
        start, end = _range(item.get("base"), item.get("available_length"), f"ram_partitions.entries[{index}]")
        if item.get("end") is not None and _u64(item["end"], f"ram_partitions.entries[{index}].end") != end:
            raise ReportError(f"ram_partitions.entries[{index}].end does not match its range")
        parsed.append({"base": _normal_hex(start), "available_length": _normal_hex(end - start), "end": _normal_hex(end)})
    ranges = sorted((int(item["base"], 16), int(item["end"], 16), i) for i, item in enumerate(parsed))
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] < previous[1]:
            raise ReportError(f"ram_partitions.entries overlap ({previous[2]} and {current[2]})")
    return {"protocol_revision": _normal_hex(revision), "count": count, "entries": parsed}


def _parse_associations(value: Any) -> dict[str, Any]:
    value = _object(value, "associations")
    _keys(value, {"fdt", "initrd", "fd"}, "associations")
    fdt = _object(value.get("fdt"), "associations.fdt")
    _keys(fdt, {"sha256", "bytes", "source"}, "associations.fdt")
    if fdt.get("source") != "uefi_runtime_fdt":
        raise ReportError("associations.fdt.source must be uefi_runtime_fdt")
    fdt_bytes = fdt.get("bytes")
    if isinstance(fdt_bytes, bool) or not isinstance(fdt_bytes, int) or fdt_bytes <= 0:
        raise ReportError("associations.fdt.bytes must be a positive integer")
    parsed_fdt = {"sha256": _sha(fdt.get("sha256"), "associations.fdt.sha256"), "bytes": fdt_bytes, "source": fdt["source"]}
    initrd = _object(value.get("initrd"), "associations.initrd")
    _keys(initrd, {"start", "end", "source"}, "associations.initrd")
    if initrd.get("source") != "uefi_runtime_fdt_chosen":
        raise ReportError("associations.initrd.source must be uefi_runtime_fdt_chosen")
    start = _u64(initrd.get("start"), "associations.initrd.start")
    end = _u64(initrd.get("end"), "associations.initrd.end")
    if start >= end:
        raise ReportError("associations.initrd must be a non-empty half-open range")
    parsed_initrd = {"start": _normal_hex(start), "end": _normal_hex(end), "source": initrd["source"]}
    fd = _object(value.get("fd"), "associations.fd")
    _keys(fd, {"base", "size", "sha256", "source"}, "associations.fd")
    if fd.get("source") != "mu_uefi_fd":
        raise ReportError("associations.fd.source must be mu_uefi_fd")
    fd_start, fd_end = _range(fd.get("base"), fd.get("size"), "associations.fd")
    parsed_fd = {"base": _normal_hex(fd_start), "size": _normal_hex(fd_end - fd_start),
                 "sha256": _sha(fd.get("sha256"), "associations.fd.sha256"), "source": fd["source"]}
    return {"fdt": parsed_fdt, "initrd": parsed_initrd, "fd": parsed_fd}


def parse_report(report: Any) -> dict[str, Any]:
    report = _object(report, "report")
    _check_no_sensitive_text(report)
    _keys(report, {"schema", "schema_version", "device", "capture", "memory_map", "ram_partitions", "associations"}, "report")
    if report.get("schema") != SCHEMA or report.get("schema_version") != SCHEMA_VERSION:
        raise ReportError(f"report schema must be {SCHEMA} version {SCHEMA_VERSION}")
    if report.get("device") != "onyx":
        raise ReportError("report.device must be onyx; other boards are not accepted")
    capture = _object(report.get("capture"), "capture")
    _keys(capture, {"kind", "stage", "exit_boot_services"}, "capture")
    if capture.get("kind") != "uefi_get_memory_map":
        raise ReportError("capture.kind must be uefi_get_memory_map, not Android or Linux memory evidence")
    if capture.get("stage") not in {"dxe_snapshot", "bds_snapshot", "pre_exit_boot_services"}:
        raise ReportError("capture.stage must identify a pre-ExitBootServices UEFI snapshot")
    if capture.get("exit_boot_services") is not False:
        raise ReportError("capture.exit_boot_services must be false for this snapshot contract")
    memory_map = _parse_memory_map(report.get("memory_map"))
    partitions = _parse_partitions(report.get("ram_partitions"))
    associations = _parse_associations(report.get("associations"))
    return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "device": "onyx",
            "capture": capture, "memory_map": memory_map, "ram_partitions": partitions,
            "associations": associations}


def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot read JSON report: {exc}") from exc
    return parse_report(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, help="write normalized JSON")
    args = parser.parse_args(argv)
    try:
        normalized = load(args.input)
        text = json.dumps(normalized, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    except (OSError, ReportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
