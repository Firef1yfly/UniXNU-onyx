#!/usr/bin/env python3
"""Strictly inspect the historical onyx Mu-Silicium firmware volume.

The input is the FD *bytes*, not a GenFv listing.  The compressed nested FV is
decoded with the explicitly supplied EDK2 LzmaCompress executable and is also
checked with Python's strict LZMA decoder so trailing/corrupt input is not
silently accepted.  No firmware source is built or modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import struct
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

FD_BYTES = 0x300000
FV_HEADER_LENGTH = 0x48
FFS_HEADER_LENGTH = 24
LZMA_GUID = "EE4E5898-3914-4259-9D6E-DC7BD79403CF"
NESTED_FFS_GUID = "9E21FD93-9C72-4C15-8C4B-E77F1DB2D792"
INNER_SHA256 = "f8f28a02a0969e4f132d33160c3e7f37694e23c276b224685247dcfd5e6b944b"
# This 8-byte prefix is emitted by the historical guided-section builder before
# the inner FV.  It is deliberately checked rather than discarded blindly.
INNER_PREFIX = bytes.fromhex("04 00 00 19 04 e0 7b 17")
KEY_GUIDS = {
    "DiskIoDxe": "6B38F7B4-AD98-40E9-9093-ACA2B5A253C4",
    "PartitionDxe": "1FA1F39E-FEFF-4AAE-BD7B-38A070A3B609",
    "Fat": "961578FE-B6B7-44C3-AF35-6BC705CD2B1F",
    "EnglishDxe": "CD3BAFB6-50FB-4FE8-8E4E-AB74D2C1A600",
    "ConPlatformDxe": "51CCF399-4FDF-4E55-A45B-E123F84D456A",
    "ConSplitterDxe": "408EDCEC-CF6D-477C-A5A8-B4844E3DE281",
    "GraphicsConsoleDxe": "CCCB0C28-4B24-11D5-9A5A-0090273FC14D",
    "SimpleFbDxe": "DCFD1E6D-788D-4FFC-8E1B-CA2F75651A92",
    "UniXNURamDiskDxe": "75CA63AD-FBAE-4A06-92A0-F937C671251D",
    "UniXNUDxe": "29B950CF-586D-49EA-9D71-F88645CCDAF6",
    "UniXNU": "9B665204-A133-47A2-9396-9E2B370A4E25",
    "DarwinBoot": "1B64AF87-8415-4B57-9B16-680D70913B9F",
}


def align(value, alignment):
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("alignment must be a positive power of two")
    return (value + alignment - 1) & ~(alignment - 1)


def guid(data):
    try:
        return str(uuid.UUID(bytes_le=bytes(data))).upper()
    except (ValueError, AttributeError):
        raise ValueError("invalid GUID bytes")


def checksum16(header):
    if len(header) & 1:
        raise ValueError("odd FV header length")
    return sum(struct.unpack_from("<%dH" % (len(header) // 2), header)) & 0xFFFF


def parse_block_map(data, offset, header_length, fv_length):
    pos = offset + 0x38
    total = 0
    entries = []
    while True:
        if pos + 8 > offset + header_length:
            raise ValueError("FV block map is truncated")
        length, count = struct.unpack_from("<II", data, pos)
        pos += 8
        if length == 0 and count == 0:
            break
        if length == 0 or count == 0:
            raise ValueError("FV block map has a half-empty entry")
        if count > (fv_length - total) // length:
            raise ValueError("FV block map overflows FvLength")
        total += length * count
        entries.append({"length": length, "count": count})
    if pos > offset + header_length or total != fv_length:
        raise ValueError("FV block map does not describe FvLength")
    return entries


def parse_ffs(data, offset, end):
    if offset < 0 or end > len(data) or offset + FFS_HEADER_LENGTH > end:
        raise ValueError("FFS header is outside FV bounds")
    header = bytearray(data[offset:offset + FFS_HEADER_LENGTH])
    if header == b"\xff" * FFS_HEADER_LENGTH:
        return None
    file_guid = guid(header[:16])
    size = int.from_bytes(header[20:23], "little")
    file_type = header[18]
    attributes = header[19]
    state = header[23]
    if size < FFS_HEADER_LENGTH or offset + size > end:
        raise ValueError("FFS size is outside FV bounds")
    if state != 0xF8:
        raise ValueError("FFS has unexpected state 0x%02x" % state)
    # EDK2 VerifyHeaderChecksum sums the full header, then subtracts State and
    # the File checksum; the Header checksum itself stays included.
    if (sum(header) - state - header[17]) & 0xFF:
        raise ValueError(f"FFS header checksum mismatch at 0x{offset:x}")
    if not (attributes & 0x40) and header[17] != 0xAA:
        raise ValueError("FFS fixed checksum marker is missing")
    return {
        "guid": file_guid,
        "offset": offset,
        "size": size,
        "type": file_type,
        "attributes": attributes,
        "state": state,
        "data_offset": offset + FFS_HEADER_LENGTH,
    }


def parse_fv(data, offset=0, expected_length=None, label="FV"):
    if offset < 0 or offset + FV_HEADER_LENGTH > len(data):
        raise ValueError(f"{label} header is truncated")
    if data[offset + 0x28:offset + 0x2C] != b"_FVH":
        raise ValueError(f"{label} signature is missing")
    fv_length = struct.unpack_from("<Q", data, offset + 0x20)[0]
    header_length = struct.unpack_from("<H", data, offset + 0x30)[0]
    revision = data[offset + 0x37]
    if fv_length < header_length or offset + fv_length > len(data):
        raise ValueError(f"{label} FvLength is outside the input")
    if expected_length is not None and fv_length != expected_length:
        raise ValueError(f"{label} FvLength is 0x{fv_length:x}, expected 0x{expected_length:x}")
    if header_length < 0x38 or header_length > fv_length or header_length & 7:
        raise ValueError(f"{label} has invalid header length")
    if revision not in (2, 3):
        raise ValueError(f"{label} has unsupported revision {revision}")
    header = data[offset:offset + header_length]
    if checksum16(header):
        raise ValueError(f"{label} header checksum mismatch")
    blocks = parse_block_map(data, offset, header_length, fv_length)
    ffs = []
    pos = offset + align(header_length, 8)
    end = offset + fv_length
    while pos < end:
        if data[pos: min(pos + FFS_HEADER_LENGTH, end)] == b"\xff" * min(FFS_HEADER_LENGTH, end - pos):
            if any(byte != 0xFF for byte in data[pos:end]):
                raise ValueError(f"{label} has non-padding bytes after FFS files")
            pos = end
            break
        file_info = parse_ffs(data, pos, end)
        if file_info is None:
            raise ValueError(f"{label} has a truncated FFS header")
        ffs.append(file_info)
        next_pos = align(pos + file_info["size"], 8)
        if next_pos <= pos or next_pos > end:
            raise ValueError(f"{label} FFS alignment overflows FV")
        pos = next_pos
    return {
        "offset": offset,
        "length": fv_length,
        "header_length": header_length,
        "revision": revision,
        "guid": guid(data[offset + 0x10:offset + 0x20]),
        "block_map": blocks,
        "ffs": ffs,
    }


def sections(data, file_info):
    pos = file_info["data_offset"]
    end = file_info["offset"] + file_info["size"]
    result = []
    while pos < end:
        if data[pos: min(pos + 4, end)] == b"\xff" * min(4, end - pos):
            if any(byte != 0xFF for byte in data[pos:end]):
                raise ValueError("non-padding bytes follow FFS sections")
            break
        if pos + 4 > end:
            raise ValueError("FFS section header is truncated")
        size = int.from_bytes(data[pos:pos + 3], "little")
        kind = data[pos + 3]
        if size < 4 or pos + size > end:
            raise ValueError("FFS section is outside file bounds")
        result.append({"offset": pos, "size": size, "type": kind, "data": pos + 4})
        pos = align(pos + size, 4)
    return result


def decode_lzma(payload, executable):
    if len(payload) < 13:
        raise ValueError("LZMA payload is truncated")
    declared = int.from_bytes(payload[5:13], "little")
    if declared == 0 or declared > 64 * 1024 * 1024:
        raise ValueError("LZMA declared output is invalid or too large")
    with tempfile.TemporaryDirectory(prefix="inspect-mu-fv-") as directory:
        directory = Path(directory)
        source = directory / "input.lzma"
        output = directory / "output.bin"
        source.write_bytes(payload)
        subprocess.run([str(executable), "-d", "-q", "-o", str(output), str(source)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        decoded = output.read_bytes()
    if len(decoded) != declared:
        raise ValueError("LZMA output length does not match its 8-byte header")
    try:
        strict = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        python_decoded = strict.decompress(payload)
        if not strict.eof or strict.unused_data:
            raise ValueError("LZMA stream has trailing or incomplete data")
    except lzma.LZMAError as error:
        raise ValueError(f"LZMA stream is corrupt: {error}") from error
    if python_decoded != decoded:
        raise ValueError("LzmaCompress and strict host decoder disagree")
    return decoded


def inspect_bytes(data, executable, *, require_historical=True):
    if require_historical and len(data) != FD_BYTES:
        raise ValueError("historical FD must be exactly 0x300000 bytes")
    outer = parse_fv(data, 0, expected_length=FD_BYTES if require_historical else None, label="outer FV")
    nested = [item for item in outer["ffs"] if item["guid"] == NESTED_FFS_GUID]
    if len(nested) != 1:
        raise ValueError(f"expected exactly one nested FV FFS, found {len(nested)}")
    nested = nested[0]
    nested_sections = sections(data, nested)
    guided = [item for item in nested_sections if item["type"] == 0x02]
    if len(guided) != 1:
        raise ValueError(f"expected exactly one GUID-defined section, found {len(guided)}")
    section = guided[0]
    if section["offset"] + 24 > nested["offset"] + nested["size"]:
        raise ValueError("GUID-defined section header is truncated")
    section_guid = guid(data[section["data"]:section["data"] + 16])
    data_offset, attributes = struct.unpack_from("<HH", data, section["data"] + 16)
    if section_guid != LZMA_GUID or data_offset < 24 or data_offset > section["size"]:
        raise ValueError("GUID-defined section has wrong GUID or data offset")
    compressed = data[section["offset"] + data_offset:section["offset"] + section["size"]]
    decoded = decode_lzma(compressed, executable)
    if decoded[:8] != INNER_PREFIX:
        raise ValueError("decoded LZMA wrapper prefix is unexpected")
    inner_data = decoded[8:]
    inner = parse_fv(inner_data, 0, expected_length=0x7BE000 if require_historical else None, label="inner FV")
    if len(decoded) != 8 + inner["length"]:
        raise ValueError("decoded bytes extend beyond the inner FV")
    inner_hash = hashlib.sha256(inner_data).hexdigest()
    if require_historical and inner_hash != INNER_SHA256:
        raise ValueError("inner FV SHA-256 does not match historical evidence")
    occurrences = {}
    for name, wanted in KEY_GUIDS.items():
        found = [item for item in inner["ffs"] if item["guid"] == wanted]
        if len(found) != 1:
            raise ValueError(f"key GUID {name} must occur exactly once, found {len(found)}")
        occurrences[name] = found[0]
    return {
        "fd_bytes": len(data), "outer_fv": outer, "nested_ffs": nested,
        "guid_defined": {"offset": section["offset"], "size": section["size"],
                          "guid": section_guid, "data_offset": data_offset,
                          "attributes": attributes, "compressed_bytes": len(compressed)},
        "decoded_wrapper_prefix": decoded[:8].hex(),
        "inner_fv": {"offset": 0x7BE000 if require_historical else 0,
                     "length": inner["length"], "sha256": inner_hash,
                     "ffs_count": len(inner["ffs"]), "header_length": inner["header_length"],
                     "guid": inner["guid"]},
        "key_guids": {name: {"guid": info["guid"], "offset": info["offset"],
                              "size": info["size"], "type": info["type"]}
                      for name, info in occurrences.items()},
    }


def inspect(path, executable, *, require_historical=True):
    return inspect_bytes(Path(path).read_bytes(), Path(executable), require_historical=require_historical)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fd", type=Path)
    parser.add_argument("--lzma-compress", required=True, type=Path,
                        help="EDK2 BaseTools LzmaCompress executable")
    args = parser.parse_args(argv)
    try:
        executable = args.lzma_compress.resolve(strict=True)
        report = inspect(args.fd, executable)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
