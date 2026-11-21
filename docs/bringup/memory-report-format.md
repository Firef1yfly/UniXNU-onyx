# UEFI memory/RAM-partition report format

This document defines the **host-side input contract** for the future onyx
firmware exporter. It is intentionally separate from the current
`OnyxMapDxe`: that DXE only prints a diagnostic snapshot and does not yet emit
this report. A report accepted here is evidence of a UEFI snapshot, not an
ADT choice or a guarantee that DarwinBoot can allocate a window.

## Contract

The JSON root is:

```json
{
  "schema": "onyx-uefi-memory-report",
  "schema_version": 1,
  "device": "onyx",
  "capture": {
    "kind": "uefi_get_memory_map",
    "stage": "dxe_snapshot | bds_snapshot | pre_exit_boot_services",
    "exit_boot_services": false
  },
  "memory_map": { "...": "..." },
  "ram_partitions": { "...": "..." },
  "associations": { "...": "..." }
}
```

The parser rejects unknown root or nested keys. Numeric physical addresses,
lengths, page counts, attributes, protocol revisions, and hashes are strings
where required: addresses and lengths use explicit lowercase/uppercase
hexadecimal (`0x...`), and hashes are lowercase SHA-256. JSON floats, booleans,
negative integers, and decimal address strings are rejected. All ranges are
half-open `[base, base + length)` and must not overflow `2^64`.

`capture.kind` proves that the values came from UEFI
`GetMemoryMap()`, not Android `/proc/iomem`, a Linux DT `memory/reg` node, or a
luming/peridot candidate. `stage` identifies the pre-ExitBootServices point;
the report must not claim the ExitBootServices map/key. The parser also rejects
provenance strings containing Android, `/proc/iomem`, luming, or device serial
identifiers so a public report cannot accidentally publish those inputs.

## EFI memory map

Required fields:

```json
{
  "descriptor_version": 1,
  "descriptor_size": 40,
  "descriptor_count": 2,
  "map_bytes": 80,
  "descriptors": [
    {
      "type": 7,
      "physical_start": "0x80000000",
      "virtual_start": "0x0",
      "number_of_pages": "0x100",
      "attribute": "0x8"
    }
  ]
}
```

`descriptor_version` is `EFI_MEMORY_DESCRIPTOR_VERSION` (currently `1`).
`virtual_start + number_of_pages * 4096` is checked for the same 64-bit overflow as the physical range; `virtual_start = 0x0` is valid.

`descriptor_size` is a multiple of eight, at least the Mu Basecore AArch64
`sizeof(EFI_MEMORY_DESCRIPTOR) = 40` bytes, and bounded to 4096 bytes. (The
fields are `UINT32` type followed by four 64-bit fields; there is no implicit
48-byte padding in this ABI.) `map_bytes` must equal
`descriptor_count * descriptor_size`; the count is bounded to 65536. Each
entry has a UEFI memory type in `0..13`, strictly less than the
`EfiMaxMemoryType` enumerator (numeric value `14` in the pinned Mu Basecore),
page-aligned physical/virtual starts, a nonzero page count, a 64-bit-safe page
range, and only defined UEFI memory attribute bits. The accepted attribute
mask includes `EFI_MEMORY_ISA_MASK =
0x0FFFF00000000000` and `EFI_MEMORY_ISA_VALID = 0x4000000000000000`, in
addition to cache, access, persistence, reliability, SP, CPU crypto,
hot-plug, and runtime bits. ISA mask bits are accepted only when
`EFI_MEMORY_ISA_VALID` is also set; ISA bits without the valid bit are
rejected. Descriptors may be in any order in the JSON, but physical ranges
must not overlap.

The future exporter must capture the map size, map key, descriptor size and
version from the same `GetMemoryMap` call. The map key is deliberately not in
this v1 public report: it is only meaningful when immediately passed to
`ExitBootServices`, and a pre-exit diagnostic allocation invalidates it. Do not
call the report key proof of a DarwinBoot handoff.

## Qualcomm RAM partition protocol

Mu-Silicium's Qualcomm `EFIRamPartition` protocol has revision
`EFI_RAMPARTITION_PROTOCOL_REVISION = 0x10002` and returns
`RamPartitionEntry { UINT64 Base; UINT64 AvailableLength; }`. The report maps
that ABI to:

```json
{
  "protocol_revision": "0x10002",
  "count": 1,
  "entries": [
    { "base": "0x80000000", "available_length": "0x100000" }
  ]
}
```

The protocol revision must be exactly `0x10002` for this pinned Mu ABI. `count` and
`entries` must both be non-empty, with `1 <= count <= 4096` and equal list length.
A missing protocol, failed call, truncated count, revision mismatch, or second-call
mismatch is a failed capture, not an empty table. Entries must be non-empty,
64-bit-safe, and non-overlapping. These are vendor protocol ranges, not
automatically `EfiConventionalMemory`; the parser never converts them into ADT
memory or claims they are free for XNU.

## Associations

Associations bind the snapshot to the exact boot attempt without storing
private identifiers:

```json
{
  "fdt": {
    "sha256": "...64 lowercase hex...",
    "bytes": 847177,
    "source": "uefi_runtime_fdt"
  },
  "initrd": {
    "start": "0xb5921000",
    "end": "0xb7ffeb04",
    "source": "uefi_runtime_fdt_chosen"
  },
  "fd": {
    "base": "0xa7100000",
    "size": "0x300000",
    "sha256": "...64 lowercase hex...",
    "source": "mu_uefi_fd"
  }
}
```

The FDT source must be the Mu runtime FDT, and its byte size/hash are required.
The initrd is the runtime `/chosen` half-open range and must be non-empty; it
is not a replacement for the EFI map. The FD association records the **active
firmware build's** `PcdFdBaseAddress`/`PcdFdSize` values and hash. The parser
does not hard-code `0xa7100000/0x300000`: those are the current onyx values,
but the exact active PCD pair and the bytes hashed by the exporter are the
evidence. A separately pinned image/provenance checker may compare that pair
to the intended build; silently substituting another board's FD values is not
allowed. These fields establish provenance only: they do not validate a static
Android DTB, select a DRAM range, or establish ownership of buffers across
SEC/PrePi/DXE.

## Host command and fixture coverage

From the device checkout:

```sh
python3 scripts/parse-uefi-memory-report.py report.json \
  --output normalized.json
python3 -m unittest discover -s tests -p 'test_parse_uefi_memory_report.py' -v
```

The tests use only synthetic addresses and hashes. They cover valid
normalization; schema/device/capture rejection; Android/luming provenance
rejection; descriptor version/size/count/byte-length checks; type, alignment,
attribute, overflow and overlap checks; RAM partition range/count checks;
FDT/initrd/FD association source/hash/range checks; and CLI JSON round-trip.
No fixture value is an observed EFI map, an onyx ADT range, or a luming value.

## Exporter handoff checklist

A future DXE exporter must provide, in one bounded report:

1. `GetMemoryMap` status, required-size retry, descriptor version/size/count,
   map bytes, and every descriptor before any further allocation;
2. the RAM protocol revision, count, and every `Base/AvailableLength` entry;
3. runtime FDT byte count/hash and `/chosen` initrd start/end;
4. FD base/size/hash and the firmware build identity without private serials;
5. explicit `capture.stage` and `exit_boot_services: false`;
6. a checksum or transport framing outside JSON if the report is copied over a
   lossy UART/QR channel.

Until those fields are collected from the same temporary boot, do not replace
the zero placeholder in `dts/onyx-bringup.dts`, set `board.example = false`,
or reuse Android/luming memory candidates.
