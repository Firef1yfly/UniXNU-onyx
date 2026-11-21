#!/usr/bin/env python3
"""Extract bounded Android boot DT evidence without modifying the source archive.

This is an offline evidence helper, not an image flasher or boot-image builder.
It extracts only boot.img, vendor_boot.img, and dtbo.img from a ZIP and writes
bounded DTB/DTBO members plus a JSON manifest. Existing output is refused.
"""
from __future__ import annotations
import argparse, hashlib, json, struct, sys
from pathlib import Path
from zipfile import ZipFile

MAX_MEMBER = 128 * 1024 * 1024
ANDROID = b"ANDROID!"
VENDOR = b"VNDRBOOT"
DT_MAGIC = 0xD00DFEED
DTBO_MAGIC = 0xD7B7AB1E

def digest(data): return hashlib.sha256(data).hexdigest()
def align(n, page): return (n + page - 1) // page * page

def read_member(z, name):
    info = z.getinfo(name)
    if info.file_size > MAX_MEMBER: raise ValueError(f"{name}: member exceeds 128 MiB")
    with z.open(info) as f: data = f.read(MAX_MEMBER + 1)
    if len(data) != info.file_size: raise ValueError(f"{name}: short ZIP member")
    if len(data) > MAX_MEMBER: raise ValueError(f"{name}: member exceeds 128 MiB")
    return data

def extract(archive, output):
    archive = Path(archive).expanduser().resolve(); output = Path(output).expanduser()
    if not archive.is_file(): raise ValueError(f"archive is not a regular file: {archive}")
    if output.exists(): raise ValueError(f"refusing existing output: {output}")
    with ZipFile(archive) as z:
        names = {f"images/{x}": x.rsplit('.', 1)[0] for x in ("boot.img", "vendor_boot.img", "dtbo.img")}
        images = {x: read_member(z, member) for member, x in names.items()}
    output.mkdir(parents=True)
    manifest = {"archive": {"path": str(archive), "bytes": archive.stat().st_size,
                             "sha256": digest(archive.read_bytes())}, "images": {}, "trees": []}
    for name, data in images.items():
        (output / name).write_bytes(data)
        manifest["images"][name] = {"bytes": len(data), "sha256": digest(data)}
    v = images["vendor_boot"]
    if v[:8] != VENDOR: raise ValueError("vendor_boot: bad magic")
    version, page = struct.unpack_from("<II", v, 8)
    if version != 4 or page == 0 or page & (page - 1): raise ValueError("vendor_boot: unsupported header")
    header_size, dtb_size, dtb_addr = struct.unpack_from("<IIQ", v, 2096)
    ramdisk_size = struct.unpack_from("<I", v, 24)[0]
    dtb_offset = align(header_size, page) + align(ramdisk_size, page)
    if dtb_offset + dtb_size > len(v): raise ValueError("vendor_boot: DTB exceeds image")
    pos, end, index = dtb_offset, dtb_offset + dtb_size, 0
    while pos < end:
        if pos + 8 > end: raise ValueError("vendor_boot: truncated DTB header")
        magic, size = struct.unpack_from(">II", v, pos)
        if magic != DT_MAGIC or size < 40 or pos + size > end: raise ValueError("vendor_boot: invalid DTB")
        name = f"vendor-base-{index}.dtb"; blob = v[pos:pos+size]; (output/name).write_bytes(blob)
        manifest["trees"].append({"file": name, "image": "vendor_boot.img", "offset": pos,
                                   "bytes": size, "sha256": digest(blob)})
        pos += size; index += 1
    d = images["dtbo"]
    if len(d) < 32: raise ValueError("dtbo: truncated header")
    magic, total, hs, es, count, offset, page_size, dtbo_version = struct.unpack_from(">8I", d)
    if magic != DTBO_MAGIC or total > len(d) or es < 32 or offset + count * es > total: raise ValueError("dtbo: invalid table")
    for index in range(count):
        base = offset + index * es
        size, blob_offset, ident, revision, *custom = struct.unpack_from(">8I", d, base)
        if blob_offset + size > total or size < 40 or struct.unpack_from(">I", d, blob_offset)[0] != DT_MAGIC: raise ValueError("dtbo: invalid entry")
        name = f"overlay-{index}.dtbo"; blob = d[blob_offset:blob_offset+size]; (output/name).write_bytes(blob)
        manifest["trees"].append({"file": name, "image": "dtbo.img", "offset": blob_offset,
                                   "bytes": size, "id": ident, "revision": revision, "custom": custom,
                                   "sha256": digest(blob)})
    manifest["vendor_boot"] = {"header_version": version, "page_size": page, "header_size": header_size,
        "vendor_ramdisk_size": ramdisk_size, "dtb_size": dtb_size, "dtb_offset": dtb_offset,
        "dtb_address": hex(dtb_addr)}
    manifest["dtbo"] = {"version": dtbo_version, "table_bytes": total, "entry_size": es, "count": count}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--archive", required=True, type=Path); p.add_argument("--output", required=True, type=Path); p.add_argument("--json", action="store_true"); args = p.parse_args(argv)
    try: result = extract(args.archive, args.output); code = 0
    except (OSError, ValueError, KeyError, struct.error) as exc: result = {"error": str(exc)}; code = 1
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else ("Extraction complete" if code == 0 else "ERROR: " + result["error"]))
    return code
if __name__ == "__main__": sys.exit(main())
