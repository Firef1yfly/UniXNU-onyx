#!/usr/bin/env python3
"""Assemble a single-variable onyx menu-probe Android v4 image offline.

The source is the pinned historical image.  Only its ramdisk is replaced.  The
source must be byte-for-byte the historical f84337c7 image; output is refused
if it already exists.  This is a host packaging/readback check, never a device
boot or firmware build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO

PAGE = 4096
SOURCE_SHA256 = "f84337c7aa91436779844b6d86f8829d83461592e27edbbb7241378dba5985c2"
RAMDISK_SHA256 = "6cd92831a9b2a48d5e9e73bf509443546e70ad7d27296b1558c29230857999d8"
HEADER_VERSION = 4
HISTORICAL_KERNEL_BYTES = 4025169
HISTORICAL_RAMDISK_BYTES = 201326592
FD_OFFSET_IN_KERNEL = 128
FD_BYTES = 0x300000
CHUNK = 1024 * 1024


def align(size: int) -> int:
    return (size + PAGE - 1) // PAGE * PAGE


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_range(stream: BinaryIO, size: int, *, require_zero: bool = False) -> tuple[str, bool]:
    """Hash exactly size bytes without retaining the range in memory."""
    digest = hashlib.sha256()
    all_zero = True
    remaining = size
    while remaining:
        chunk = stream.read(min(CHUNK, remaining))
        if not chunk:
            raise ValueError(f"short read: wanted {size}, got {size - remaining}")
        digest.update(chunk)
        if any(chunk):
            all_zero = False
        remaining -= len(chunk)
    if require_zero and not all_zero:
        raise ValueError("nonzero Android field padding")
    return digest.hexdigest(), all_zero


def read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise ValueError(f"short read: wanted {size}, got {len(data)}")
    return data


def _scan_image(path: Path) -> dict:
    """Parse and hash an Android v4 image while retaining only small metadata."""
    path = Path(path)
    with path.open("rb") as stream:
        header = read_exact(stream, PAGE)
        if header[:8] != b"ANDROID!":
            raise ValueError("Android boot magic missing")
        kernel_bytes = int.from_bytes(header[8:12], "little")
        ramdisk_bytes = int.from_bytes(header[12:16], "little")
        os_version = int.from_bytes(header[16:20], "little")
        header_size = int.from_bytes(header[20:24], "little")
        version = int.from_bytes(header[40:44], "little")
        signature_bytes = int.from_bytes(header[1580:1584], "little")
        if version != HEADER_VERSION or header_size != 1584 or signature_bytes != PAGE:
            raise ValueError("not the expected Android v4 header geometry")
        if int.from_bytes(header[24:40], "little") != 0:
            raise ValueError("v4 reserved header fields are not zero")
        if any(header[44:1580]) or any(header[1584:]):
            raise ValueError("historical cmdline/header padding is not zero")

        kernel_offset = PAGE
        kernel_sha256, _ = _hash_range(stream, kernel_bytes)
        kernel_pad = align(kernel_bytes) - kernel_bytes
        _hash_range(stream, kernel_pad, require_zero=True)
        ramdisk_offset = PAGE + align(kernel_bytes)
        ramdisk_sha256, _ = _hash_range(stream, ramdisk_bytes)
        ramdisk_pad = align(ramdisk_bytes) - ramdisk_bytes
        _hash_range(stream, ramdisk_pad, require_zero=True)
        signature_offset = ramdisk_offset + align(ramdisk_bytes)
        signature_sha256, signature_zero = _hash_range(stream, PAGE, require_zero=True)
        if stream.read(1):
            raise ValueError("unexpected bytes after v4 signature")

    return {
        "path": str(path), "header": header,
        "kernel_offset": kernel_offset, "ramdisk_offset": ramdisk_offset,
        "signature_offset": signature_offset, "kernel_bytes": kernel_bytes,
        "ramdisk_bytes": ramdisk_bytes, "os_version": os_version,
        "header_size": header_size, "version": version,
        "kernel_sha256": kernel_sha256, "ramdisk_sha256": ramdisk_sha256,
        "signature_sha256": signature_sha256, "signature_zero": signature_zero,
        "image_bytes": signature_offset + PAGE,
    }


def split_image(path: Path, *, load_data: bool = True) -> dict:
    """Parse an image for compatibility; use load_data=False for large images.

    Existing callers can request the historical byte fields.  The assembler
    deliberately uses the streaming scanner instead and never loads a kernel or
    ramdisk into one Python object.
    """
    report = _scan_image(path)
    if not load_data:
        return report
    with Path(path).open("rb") as stream:
        stream.seek(report["kernel_offset"])
        report["kernel"] = read_exact(stream, report["kernel_bytes"])
        stream.seek(report["ramdisk_offset"])
        report["ramdisk"] = read_exact(stream, report["ramdisk_bytes"])
        stream.seek(report["signature_offset"])
        report["signature"] = read_exact(stream, PAGE)
    return report


def _read_range(path: Path, offset: int, size: int) -> bytes:
    with Path(path).open("rb") as stream:
        stream.seek(offset)
        return read_exact(stream, size)


def _copy_range(source: Path, offset: int, size: int, destination: Path) -> None:
    with Path(source).open("rb") as src, Path(destination).open("xb") as dst:
        src.seek(offset)
        remaining = size
        while remaining:
            chunk = src.read(min(CHUNK, remaining))
            if not chunk:
                raise ValueError(f"short read while extracting {size} bytes")
            dst.write(chunk)
            remaining -= len(chunk)


def _hash_segment(path: Path, offset: int, size: int) -> str:
    with Path(path).open("rb") as stream:
        stream.seek(offset)
        digest, _ = _hash_range(stream, size)
    return digest


def _same_owned_file(path: Path, identity: tuple[int, int] | None) -> bool:
    if identity is None:
        return False
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity


def _unlink_owned(path: Path, identity: tuple[int, int] | None) -> None:
    """Remove only a regular file whose inode we created, never a replacement."""
    if _same_owned_file(path, identity):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _preflight_paths(output: Path, report_path: Path | None) -> None:
    if _lexists(output):
        raise ValueError(f"refusing existing output: {output}")
    if report_path is not None:
        if output == report_path:
            raise ValueError("output and report must be different paths")
        if _lexists(report_path):
            raise ValueError(f"refusing existing report: {report_path}")


def _copy_file_exclusive(source: Path, output: Path) -> tuple[int, int]:
    """Copy a candidate to its final path and clean up only our inode on error."""
    identity = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with Path(output).open("xb") as dst, Path(source).open("rb") as src:
            info = os.fstat(dst.fileno())
            identity = (info.st_dev, info.st_ino)
            for chunk in iter(lambda: src.read(CHUNK), b""):
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
    except BaseException:
        _unlink_owned(output, identity)
        raise
    assert identity is not None
    return identity


def _write_report(path: Path, report: dict) -> tuple[int, int]:
    """Write a report exclusively, removing a partial report only if ours."""
    identity = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(report, indent=2) + "\n").encode("utf-8")
        with Path(path).open("xb") as stream:
            info = os.fstat(stream.fileno())
            identity = (info.st_dev, info.st_ino)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        _unlink_owned(path, identity)
        raise
    assert identity is not None
    return identity


def assert_historical_source(path: Path, *, load_data: bool = True) -> dict:
    digest = sha256_file(path)
    if digest != SOURCE_SHA256:
        raise ValueError(f"source SHA-256 {digest} does not match pinned historical {SOURCE_SHA256}")
    report = split_image(path, load_data=load_data)
    if report["kernel_bytes"] != HISTORICAL_KERNEL_BYTES or report["ramdisk_bytes"] != HISTORICAL_RAMDISK_BYTES:
        raise ValueError("historical source has unexpected kernel or ramdisk size")
    if load_data:
        kernel = report["kernel"]
        if kernel[56:60] != b"ARM\x64":
            raise ValueError("historical kernel does not contain the expected ARM64 shim header")
        if int.from_bytes(kernel[8:16], "little") != 0 or int.from_bytes(kernel[16:24], "little") != FD_OFFSET_IN_KERNEL + FD_BYTES:
            raise ValueError("historical shim image header is not the tested zero-text-offset form")
        dtb = kernel[FD_OFFSET_IN_KERNEL + FD_BYTES:]
        if len(dtb) < 40 or int.from_bytes(dtb[:4], "big") != 0xD00DFEED or int.from_bytes(dtb[4:8], "big") != len(dtb):
            raise ValueError("historical appended DTB is not a complete FDT")
    else:
        kernel_head = _read_range(path, PAGE, 60)
        if kernel_head[56:60] != b"ARM\x64":
            raise ValueError("historical kernel does not contain the expected ARM64 shim header")
        if int.from_bytes(kernel_head[8:16], "little") != 0 or int.from_bytes(kernel_head[16:24], "little") != FD_OFFSET_IN_KERNEL + FD_BYTES:
            raise ValueError("historical shim image header is not the tested zero-text-offset form")
        dtb_offset = PAGE + FD_OFFSET_IN_KERNEL + FD_BYTES
        dtb_header = _read_range(path, dtb_offset, 8)
        if int.from_bytes(dtb_header[:4], "big") != 0xD00DFEED or int.from_bytes(dtb_header[4:8], "big") != report["kernel_bytes"] - FD_OFFSET_IN_KERNEL - FD_BYTES:
            raise ValueError("historical appended DTB is not a complete FDT")
    return report


def fat_listing(image: Path) -> tuple[list[str], bytes]:
    """Read the FAT with mtools and return normalized entries and TOML bytes."""
    def run(*args: str) -> bytes:
        command = ["mdir", "-b", "-i", str(image), *args]
        return subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    root = run("::").decode("utf-8", "strict").splitlines()
    efi = run("::/EFI").decode("utf-8", "strict").splitlines()
    nested = run("::/EFI/UniXNU").decode("utf-8", "strict").splitlines()
    entries = [line.strip() for line in root + efi + nested if line.strip()]
    command = ["mtype", "-t", "-i", str(image), "::/EFI/UniXNU/unixnu.toml"]
    text = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    if b"kernel.macho" in text or b"DarwinBoot" in text or b"Payloads" in text or b"[[driver]]" in text:
        raise ValueError("menu FAT contains an XNU/driver payload reference")
    return entries, text


def assert_menu_fat(path: Path) -> dict:
    digest = sha256_file(path)
    if digest != RAMDISK_SHA256:
        raise ValueError(f"menu FAT SHA-256 {digest} does not match pinned {RAMDISK_SHA256}")
    entries, config = fat_listing(path)
    expected = ["::/EFI/", "::/EFI/UniXNU/", "::/EFI/UniXNU/unixnu.toml"]
    if entries != expected:
        raise ValueError(f"menu FAT entries differ: {entries!r}")
    if b"MENU_ONLY_PROBE" not in config or b'type = "action"' not in config or b'action = "tools"' not in config:
        raise ValueError("menu marker/action is absent")
    if b"timeout = 0" in config or b'[[entry]]\nid = "xnu"' in config:
        raise ValueError("menu FAT contains auto-start or XNU entry")
    return {"sha256": digest, "bytes": Path(path).stat().st_size,
            "entries": entries, "config_bytes": len(config), "config_sha256": hashlib.sha256(config).hexdigest()}


def _validate_candidate(source: Path, source_report: dict, ramdisk: Path, fat_report: dict,
                        candidate: Path, candidate_report: dict) -> tuple[list[int], dict]:
    if candidate_report["kernel_bytes"] != source_report["kernel_bytes"]:
        raise ValueError("kernel size changed while replacing ramdisk")
    if candidate_report["kernel_sha256"] != source_report["kernel_sha256"]:
        raise ValueError("kernel field changed while replacing ramdisk")
    if candidate_report["ramdisk_bytes"] != fat_report["bytes"] or candidate_report["ramdisk_sha256"] != fat_report["sha256"]:
        raise ValueError("candidate ramdisk does not byte-match input FAT")
    if not candidate_report["signature_zero"]:
        raise ValueError("candidate v4 signature is not zero")
    source_header = source_report["header"]
    candidate_header = candidate_report["header"]
    header_differences = [i for i, (left, right) in enumerate(zip(source_header, candidate_header)) if left != right]
    if header_differences != [15]:
        raise ValueError(f"unexpected Android header changes: {header_differences}")
    segments = {}
    source_kernel_offset = source_report["kernel_offset"]
    for name, offset, size in (("shim", 0, FD_OFFSET_IN_KERNEL),
                               ("fd", FD_OFFSET_IN_KERNEL, FD_BYTES),
                               ("dtb", FD_OFFSET_IN_KERNEL + FD_BYTES,
                                source_report["kernel_bytes"] - FD_OFFSET_IN_KERNEL - FD_BYTES)):
        left_offset = source_kernel_offset + offset
        right_offset = candidate_report["kernel_offset"] + offset
        left_hash = _hash_segment(source, left_offset, size)
        right_hash = _hash_segment(candidate, right_offset, size)
        same = left_hash == right_hash
        segments[name] = {"bytes": size, "source_sha256": left_hash,
                           "candidate_sha256": right_hash, "unchanged": same}
        if not same:
            raise ValueError(f"{name} changed")
    return header_differences, segments


def assemble(source: Path, ramdisk: Path, output: Path, mkbootimg: Path,
             report_path: Path | None = None) -> dict:
    source = Path(source).resolve(strict=True)
    ramdisk = Path(ramdisk).resolve(strict=True)
    output = Path(output).resolve()
    mkbootimg = Path(mkbootimg).resolve(strict=True)
    report_path = Path(report_path).resolve() if report_path is not None else None
    _preflight_paths(output, report_path)

    output_identity = None
    try:
        source_report = assert_historical_source(source, load_data=False)
        fat_report = assert_menu_fat(ramdisk)
        with tempfile.TemporaryDirectory(prefix="onyx-menu-probe-") as scratch_name:
            scratch = Path(scratch_name)
            kernel = scratch / "kernel"
            _copy_range(source, source_report["kernel_offset"], source_report["kernel_bytes"], kernel)
            candidate = scratch / "candidate.img"
            command = [sys.executable, str(mkbootimg), "--header_version", "4", "--pagesize", str(PAGE),
                       "--kernel", str(kernel), "--ramdisk", str(ramdisk), "--output", str(candidate)]
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # The final path, not merely mkbootimg's temporary path, is scanned below.
            output_identity = _copy_file_exclusive(candidate, output)

        if not _same_owned_file(output, output_identity):
            raise ValueError("final output path was replaced before readback")
        candidate_report = _scan_image(output)
        header_differences, segments = _validate_candidate(
            source, source_report, ramdisk, fat_report, output, candidate_report)
        if not _same_owned_file(output, output_identity):
            raise ValueError("final output path was replaced during readback")
        output_digest = sha256_file(output)
        if not _same_owned_file(output, output_identity):
            raise ValueError("final output path was replaced during hashing")
        report = {
            "source": {"path": str(source), "sha256": SOURCE_SHA256, "bytes": source_report["image_bytes"]},
            "ramdisk": fat_report,
            "candidate": {"path": str(output), "sha256": output_digest, "bytes": output.stat().st_size,
                          "header_version": HEADER_VERSION, "kernel_bytes": candidate_report["kernel_bytes"],
                          "ramdisk_bytes": candidate_report["ramdisk_bytes"], "signature_zero": True},
            "header": {"version_unchanged": source_report["version"] == candidate_report["version"],
                       "size": PAGE, "changed_offsets": header_differences,
                       "ramdisk_size_field_only": True},
            "kernel": {"bytes_unchanged": True, "source_sha256": source_report["kernel_sha256"],
                       "candidate_sha256": candidate_report["kernel_sha256"]},
            "segments": segments,
            "difference": "only Android v4 ramdisk-size field, ramdisk bytes, field padding/placement, and image length/hash changed",
            "hardware_tested": False}
        if report_path is not None:
            if not _same_owned_file(output, output_identity):
                raise ValueError("final output path was replaced before report write")
            _write_report(report_path, report)
        return report
    except BaseException:
        _unlink_owned(output, output_identity)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--ramdisk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mkbootimg", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = assemble(args.source, args.ramdisk, args.output, args.mkbootimg, args.report)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
