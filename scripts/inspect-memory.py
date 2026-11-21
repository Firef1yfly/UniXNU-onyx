#!/usr/bin/env python3
"""Offline, read-only structural inspection of an FDT memory map.

This tool never edits a board repository, contacts a device or network, or
proves that a DTB came from a running phone. A nonzero DRAM range still needs
source provenance and a matching UEFI memory map.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import struct
import sys
import types
from pathlib import Path


U64 = 1 << 64
MAX_FDT_BYTES = 16 * 1024 * 1024
MAX_MEMRESERVE_ENTRIES = 65536
MAX_OVERLAP_EXAMPLES = 128


def _load_fdt(unixnu):
    root = Path(unixnu).expanduser().resolve()
    scripts = root / "scripts"
    if not scripts.is_dir():
        raise ValueError(f"UniXNU scripts directory not found: {scripts}")
    module_path = scripts / "unixnu/devicetree.py"
    if not module_path.is_file():
        raise ValueError(f"UniXNU FDT parser not found: {module_path}")
    # A separate package namespace honors --unixnu across repeated library calls;
    # do not silently reuse a previously imported checkout from sys.modules.
    package_name = "_inspect_memory_unixnu_" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(module_path.parent)]
        sys.modules[package_name] = package
    try:
        module = importlib.import_module(package_name + ".devicetree")
    except Exception as exc:
        raise ValueError(f"cannot load UniXNU FDT parser: {exc}") from None
    return module.Error, module.cell_count, module.number, module.read_fdt, module.registers


def _status(node):
    return "enabled" if node.enabled() else "disabled"


def _range_record(address, size, status=None):
    end = address + size
    errors = []
    if size == 0:
        errors.append("zero_size")
    if end > U64:
        errors.append("overflow")
    record = {"address": address, "size": size, "end": end if end <= U64 else None}
    if status is not None:
        record["status"] = status
    if errors:
        record["errors"] = errors
    return record


def _memory_nodes(root):
    result = []
    for node in root.children:
        try:
            device_types = node.strings("device_type")
        except Exception:
            device_types = []
        if "memory" in device_types or node.name == "memory" or node.name.startswith("memory@"):
            result.append(node)
    return result


def _path(node):
    parts = []
    current = node
    while current is not None:
        if current.name:
            parts.append(current.name)
        current = current.parent
    return "/" + "/".join(reversed(parts))


def _decode_node_ranges(node, registers):
    return [_range_record(address, size) for address, size in registers(node)]


def _overlaps(ranges):
    valid = [(item["address"], item["end"], index) for index, item in enumerate(ranges)
             if "errors" not in item and item["size"] > 0]
    # Sort once and retain the earlier interval with the furthest endpoint.
    # One witness per conflicting interval suffices to reject overlap; cap the
    # diagnostic list without an O(n^2) expansion for maliciously dense banks.
    result = []
    furthest_end, furthest_index = -1, None
    for address, end, index in sorted(valid):
        if address < furthest_end and len(result) < MAX_OVERLAP_EXAMPLES:
            result.append({"first": min(index, furthest_index), "second": max(index, furthest_index)})
        if end > furthest_end:
            furthest_end, furthest_index = end, index
    return result


def _parse_memreserve(blob, header, errors):
    total = header[1]
    offset = header[4]
    pairs = []
    terminated = False
    # Never search structure/string blocks for an accidental zero terminator.
    blocks = [(header[2], header[2] + header[9]),
              (header[3], header[3] + header[8])]
    limit = min([total] + [start for start, end in blocks if start >= offset and end > start])
    inside_block = any(start <= offset < end for start, end in blocks)
    if offset < 40 or offset % 8 or inside_block or offset + 16 > limit:
        errors.append("FDT memreserve offset is outside the bounded reservation area")
        return pairs, terminated
    for _ in range(MAX_MEMRESERVE_ENTRIES):
        if offset + 16 > limit:
            errors.append("FDT memreserve table has no bounded terminator")
            return pairs, terminated
        address, size = struct.unpack_from(">QQ", blob, offset)
        offset += 16
        if address == 0 and size == 0:
            terminated = True
            break
        end = address + size
        item = {"address": address, "size": size, "end": end if end <= U64 else None}
        if size == 0:
            item["errors"] = ["zero_size"]
        elif end > U64:
            item["errors"] = ["overflow"]
        pairs.append(item)
    else:
        errors.append("FDT memreserve table exceeds entry limit")
    return pairs, terminated


def _identity(root):
    model = root.strings("model")
    compatible = root.strings("compatible")
    candidates = [value.lower() for value in model + compatible]
    confirmed = any(re.search(r"(?<![a-z0-9])onyx(?![a-z0-9])", value) for value in candidates)
    reason = ("model/compatible contains onyx"
              if confirmed else
              "generic or non-onyx model/compatible; qcom,tuna alone is insufficient")
    ids = {}
    for key in ("qcom,msm-id", "qcom,board-id", "xiaomi,miboard-id"):
        ids[key] = root.cells(key) if key in root.properties else []
    return {"model": model, "compatible": compatible, "qcom_ids": ids,
            "onyx_confirmed": confirmed, "reason": reason,
            "runtime_source_verified": False}


def inspect(path, unixnu):
    path = Path(path).expanduser()
    report = {
        "schema_version": 1,
        "input": {"path": str(path), "size": None, "sha256": None},
        "identity": {"model": [], "compatible": [], "qcom_ids": {
                         "qcom,msm-id": [], "qcom,board-id": [], "xiaomi,miboard-id": []},
                     "onyx_confirmed": False, "reason": "not inspected",
                     "runtime_source_verified": False},
        "memory": {"nodes": [], "enabled_ranges": [], "disabled_ranges": [],
                   "overlaps": [], "errors": [], "complete": False},
        "reserved_memory": {"node": None, "ranges": [], "dynamic_size_only": [],
                             "errors": []},
        "fdt_memreserve": {"pairs": [], "terminated": False, "errors": []},
        "memory_complete": False,
        "hardware_tested": False,
        "safe_to_boot": False,
        "notice": "Offline structural FDT inspection only; memory_complete is not ADT readiness. Nonzero memory still requires source provenance and UEFI-map comparison; runtime authenticity is not established.",
        "requirements": ["Prove the input source and selected device/SKU independently.",
                         "Compare every bank and reservation with the active UEFI memory map.",
                         "Do not crop banks or write DTS automatically; UniXNU ADT may impose stricter handoff constraints."],
        "errors": [],
    }
    try:
        if not path.is_file():
            raise ValueError(f"DTB is not a regular file: {path}")
        size = path.stat().st_size
        report["input"]["size"] = size
        if size > MAX_FDT_BYTES:
            raise ValueError("DTB exceeds offline inspection limit (16 MiB)")
        with path.open("rb") as stream:
            blob = stream.read(MAX_FDT_BYTES + 1)
        if len(blob) > MAX_FDT_BYTES:
            raise ValueError("DTB exceeds offline inspection limit (16 MiB)")
        report["input"]["size"] = len(blob)
        report["input"]["sha256"] = hashlib.sha256(blob).hexdigest()
        if len(blob) < 40:
            raise ValueError("FDT header is truncated")
        header = struct.unpack_from(">10I", blob, 0)
        if header[0] != 0xD00DFEED or header[1] > len(blob):
            raise ValueError("invalid FDT magic or totalsize")
        Error, cell_count, number, read_fdt, registers = _load_fdt(unixnu)
        root = read_fdt(blob)
        report["identity"] = _identity(root)

        memory_nodes = _memory_nodes(root)
        all_enabled = []
        all_disabled = []
        for node in memory_nodes:
            status = _status(node)
            record = {"path": _path(node), "status": status, "ranges": []}
            try:
                if "reg" not in node.properties:
                    raise ValueError("memory node has no reg")
                ranges = _decode_node_ranges(node, registers)
                if not ranges:
                    raise ValueError("memory node has empty reg")
            except Exception as exc:
                record["errors"] = [str(exc)]
                report["memory"]["errors"].append(f"{record['path']}: {exc}")
                ranges = []
            for item in ranges:
                item["status"] = status
                record["ranges"].append(item)
                (all_enabled if status == "enabled" else all_disabled).append(item)
            report["memory"]["nodes"].append(record)
        report["memory"]["enabled_ranges"] = all_enabled
        report["memory"]["disabled_ranges"] = all_disabled
        report["memory"]["overlaps"] = _overlaps(all_enabled)
        for item in all_enabled:
            for issue in item.get("errors", []):
                report["memory"]["errors"].append(issue)
        if report["memory"]["overlaps"]:
            report["memory"]["errors"].append("enabled memory ranges overlap")
        report["memory"]["complete"] = bool(all_enabled) and not report["memory"]["errors"]

        reserved = next((node for node in root.children if node.name == "reserved-memory"), None)
        if reserved is not None:
            report["reserved_memory"]["node"] = _path(reserved)
            for child in reserved.children:
                status = _status(child)
                flags = {"no_map": "no-map" in child.properties,
                         "reusable": "reusable" in child.properties}
                if "reg" in child.properties:
                    try:
                        decoded = _decode_node_ranges(child, registers)
                        if not decoded:
                            raise ValueError("reservation has empty reg")
                        for item in decoded:
                            item.update({"path": _path(child), "status": status, **flags})
                        report["reserved_memory"]["ranges"].extend(decoded)
                    except Exception as exc:
                        report["reserved_memory"]["errors"].append(f"{_path(child)}: {exc}")
                elif "size" in child.properties:
                    try:
                        size_cells = cell_count(reserved, "#size-cells", 1)
                        values = child.cells("size")
                        if size_cells == 0 or len(values) != size_cells:
                            raise ValueError("size-only reservation has invalid cell count")
                        size = number(values)
                        report["reserved_memory"]["dynamic_size_only"].append({
                            "path": _path(child), "status": status, "size": size,
                            "no_map": flags["no_map"], "reusable": flags["reusable"],
                            "unresolved": True})
                    except Exception as exc:
                        report["reserved_memory"]["errors"].append(f"{_path(child)}: {exc}")
        memreserve_pairs, terminated = _parse_memreserve(blob, header, report["fdt_memreserve"]["errors"])
        report["fdt_memreserve"]["pairs"] = memreserve_pairs
        report["fdt_memreserve"]["terminated"] = terminated
        report["memory_complete"] = (report["memory"]["complete"]
            and not report["reserved_memory"]["errors"]
            and not any(x["status"] == "enabled" for x in report["reserved_memory"]["dynamic_size_only"])
            and not any(x.get("errors") and x["status"] == "enabled" for x in report["reserved_memory"]["ranges"])
            and terminated and not report["fdt_memreserve"]["errors"]
            and not any(x.get("errors") for x in memreserve_pairs))
    except Exception as exc:
        report["errors"].append(str(exc))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dtb", required=True, type=Path)
    parser.add_argument("--unixnu", type=Path,
                        default=Path(__file__).resolve().parents[1].parent / "unixnu")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect(args.dtb, args.unixnu)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(report["notice"])
        print(f"DTB: {report['input']['path']} ({report['input']['size']} bytes)")
        print(f"Onyx identity structurally confirmed: {report['identity']['onyx_confirmed']}")
        print(f"Memory structurally complete: {report['memory_complete']}")
        for message in report["errors"] + report["memory"]["errors"] + report["reserved_memory"]["errors"] + report["fdt_memreserve"]["errors"]:
            print(f"ERROR: {message}")
        print("safe_to_boot: false; hardware_tested: false")
    return 0 if report["memory_complete"] and not report["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
