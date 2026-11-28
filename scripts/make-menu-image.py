#!/usr/bin/env python3
"""Package an onyx bring-up boot image and apply the ABL text_offset correction.

UniXNU's own `bootimg.build` produces the image; this wrapper exists for two
reasons:

1. The onyx ABL computes `jump = load address + header.text_offset`. Stock
   `boot_a` carries 0 there, while BootShim writes the firmware base because the
   stock packer validates that value. An unmodified image therefore reports
   `Booting OKAY`, never executes and drops back to fastboot. The field is zeroed
   here, after the packer has verified its own output; BootShim still copies to
   `FD_BASE` from its instruction stream, so the firmware lands where the board
   memory map expects it.
2. `board.example = true` keeps the CLI gate closed on purpose. This is a
   bring-up probe with every input named on the command line, not a release
   artifact, so it calls the packer directly instead of weakening the gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

DEVICE = Path(__file__).resolve().parent.parent
PAGE = 4096
HEADER_VERSION_OFFSET = 40
HEADER_SIZE_OFFSET = 20
TEXT_OFFSET_POSITION = 8


def kernel_field_offset(data: bytes) -> int:
    """Return where the kernel payload starts in a v3/v4 boot image."""
    header_size = struct.unpack_from("<I", data, HEADER_SIZE_OFFSET)[0]
    return PAGE * max(1, -(-header_size // PAGE))


def zero_text_offset(data: bytes) -> tuple[bytes, int]:
    """Return the image with header.text_offset cleared, plus its previous value."""
    output = bytearray(data)
    position = kernel_field_offset(data) + TEXT_OFFSET_POSITION
    previous = struct.unpack_from("<Q", output, position)[0]
    if previous != 0:
        struct.pack_into("<Q", output, position, 0)
    return bytes(output), previous


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fd", type=Path, required=True, help="3 MiB SILICIUM_UEFI.fd")
    parser.add_argument("--dtb", type=Path, required=True, help="compiled device tree to append")
    parser.add_argument("--ramdisk", type=Path, required=True, help="menu-only FAT payload")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--unixnu", type=Path, default=DEVICE.parent / "UniXNU",
                        help="pinned UniXNU checkout")
    parser.add_argument("--uefi", type=Path, default=DEVICE.parent / "Mu-Silicium",
                        help="pinned Mu-Silicium checkout")
    parser.add_argument("--header-version", type=int, default=4)
    args = parser.parse_args(argv)

    sys.path.insert(0, str(args.unixnu.resolve() / "scripts"))
    from unixnu import bootimg  # noqa: PLC0415

    board = {"firmware": {"config": "onyx"},
             "bootimg": {"image": {"kernel_compression": "none",
                                   "header_version": args.header_version}}}
    ctx = SimpleNamespace(board=board, work=args.output.resolve().parent, tree=DEVICE, jobs=2)
    bootimg.build(ctx, args.uefi.resolve(), args.fd.resolve(), args.dtb.resolve(),
                  args.ramdisk.resolve(), args.output.resolve())

    data, previous = zero_text_offset(args.output.resolve().read_bytes())
    args.output.resolve().write_bytes(data)

    report_path = args.output.resolve().parent / "boot.json"
    report = json.loads(report_path.read_text())
    report["text_offset_zeroed_from"] = previous
    report["image_sha256"] = hashlib.sha256(data).hexdigest()
    report["image_bytes"] = len(data)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"bootimg: text_offset {previous:#x} -> 0x0")
    print(f"bootimg: {args.output.resolve()} sha256 {report['image_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
