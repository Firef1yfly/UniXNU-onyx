#!/usr/bin/env python3
"""Inspect or byte-repack the pinned historical onyx Mu boot image, offline.

Repacking uses the original bytes and is only a packaging regression. It is
not a replacement firmware build, and does not qualify an image for booting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

PAGE = 4096
PIN = "f84337c7aa91436779844b6d86f8829d83461592e27edbbb7241378dba5985c2"
GEOMETRY = (4025169, 201326592, 0, 1584)
SHIM_SIZE = 128
FD_SIZE = 0x300000


def align(size):
    return (size + PAGE - 1) // PAGE * PAGE


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect(path):
    """Return evidence for this one unsigned, uncompressed historical layout."""
    path = Path(path)
    with path.open("rb") as image:
        header = image.read(PAGE)
        if len(header) != PAGE or header[:8] != b"ANDROID!":
            raise ValueError("not a complete Android header page")
        if struct.unpack_from("<4I", header, 8) != GEOMETRY:
            raise ValueError("unexpected historical Android image geometry")
        if struct.unpack_from("<I", header, 40)[0] != 4:
            raise ValueError("expected Android boot v4")
        if any(header[24:40] + header[44:1580] + header[1584:]):
            raise ValueError("unexpected reserved, cmdline or padding bytes")
        if struct.unpack_from("<I", header, 1580)[0] != PAGE:
            raise ValueError("unexpected v4 signature size")
        kernel_size, ramdisk_size, _, _ = GEOMETRY
        kernel_aligned = align(kernel_size)
        ramdisk_offset = PAGE + kernel_aligned
        signature_offset = ramdisk_offset + align(ramdisk_size)
        kernel = image.read(kernel_size)
        if len(kernel) != kernel_size:
            raise ValueError("short kernel field")
        padding = image.read(kernel_aligned - kernel_size)
        if len(padding) != kernel_aligned - kernel_size or any(padding):
            raise ValueError("invalid kernel padding")
        shim, fd, dtb = kernel[:SHIM_SIZE], kernel[SHIM_SIZE:SHIM_SIZE + FD_SIZE], kernel[SHIM_SIZE + FD_SIZE:]
        if shim[56:60] != b"ARM\x64" or struct.unpack_from("<QQ", shim, 8) != (0, SHIM_SIZE + FD_SIZE):
            raise ValueError("unexpected historical ARM64 header")
        if len(dtb) < 40 or struct.unpack_from(">II", dtb) != (0xd00dfeed, len(dtb)):
            raise ValueError("expected a complete appended FDT")
        image_digest = hashlib.sha256(header + kernel + padding)
        ramdisk_digest = hashlib.sha256()
        remaining = ramdisk_size
        while remaining:
            data = image.read(min(remaining, 1024 * 1024))
            if not data:
                raise ValueError("short ramdisk")
            image_digest.update(data)
            ramdisk_digest.update(data)
            remaining -= len(data)
        signature = image.read(PAGE)
        if signature != bytes(PAGE) or image.read(1):
            raise ValueError("expected all-zero v4 signature and no trailing data")
        image_digest.update(signature)
        if image_digest.hexdigest() != PIN:
            raise ValueError("whole image does not match the pinned historical SHA-256")
    return {
        "image_sha256": PIN, "image_bytes": signature_offset + PAGE,
        "android_header_version": 4, "compression": "none",
        "arm64_text_offset": 0, "arm64_image_size": SHIM_SIZE + FD_SIZE,
        "kernel": {"offset": PAGE, "bytes": kernel_size, "sha256": digest(kernel)},
        "shim": {"offset": PAGE, "bytes": SHIM_SIZE, "sha256": digest(shim)},
        "fd": {"offset": PAGE + SHIM_SIZE, "bytes": FD_SIZE, "sha256": digest(fd)},
        "dtb": {"offset": PAGE + SHIM_SIZE + FD_SIZE, "bytes": len(dtb), "sha256": digest(dtb)},
        "ramdisk": {"offset": ramdisk_offset, "bytes": ramdisk_size, "sha256": ramdisk_digest.hexdigest()},
        "v4_signature": {"offset": signature_offset, "bytes": PAGE, "all_zero": True},
    }


def repack(path, report, mkbootimg):
    """Rebuild in a scratch directory and require full equality by SHA-256."""
    with tempfile.TemporaryDirectory(prefix="onyx-mu-repack-") as scratch:
        scratch = Path(scratch)
        paths = {}
        with Path(path).open("rb") as image:
            for name in ("kernel", "ramdisk"):
                info = report[name]
                image.seek(info["offset"])
                paths[name] = scratch / name
                remaining = info["bytes"]
                part_digest = hashlib.sha256()
                with paths[name].open("xb") as part:
                    while remaining:
                        data = image.read(min(remaining, 1024 * 1024))
                        if not data:
                            raise ValueError(f"short {name} during second read")
                        part.write(data)
                        part_digest.update(data)
                        remaining -= len(data)
                if part_digest.hexdigest() != info["sha256"]:
                    raise ValueError(f"{name} changed since first read")
        output = scratch / "boot.img"
        subprocess.run([sys.executable, str(mkbootimg), "--header_version", "4",
                        "--kernel", str(paths["kernel"]), "--ramdisk", str(paths["ramdisk"]),
                        "-o", str(output)], check=True, stdout=subprocess.DEVNULL)
        if inspect(output) != report:
            raise ValueError("repacked report does not equal historical report")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--mkbootimg", type=Path, help="also prove a byte-identical temporary repack")
    args = parser.parse_args(argv)
    try:
        report = inspect(args.image)
        if args.mkbootimg is not None:
            repack(args.image, report, args.mkbootimg.resolve(strict=True))
            report["byte_exact_temporary_repack"] = True
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
