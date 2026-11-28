# Onyx UEFI handoff takeover record

## Scope and revisions

This work is an isolated device-repository worktree on branch `port/onyx-uefi-handoff`, based on `Firef1yfly/UniXNU-onyx` commit `9afe88a6ce3ffd42b24ef7a2d4ef04aedf393085`. It is a source baseline, not a validated build revision. The reviewed adjacent upstream source checkouts were UniXNU `fdf81eaa832ce5c850d3c53c698407aa722a4653` and Firef1yfly/Mu-Silicium `1d0f1e41018b2519ab9b41b60ac073453e346ba0`; those revisions are not evidence that the Onyx-specific diff in this worktree builds or boots.

The source changes in this branch have not been committed. Do not cite the base commit alone as containing or validating these changes. Keep firmware, memory, configuration, packaging, display, input and kernel status at `planned` until each required input and test is independently qualified.

## Device-gate policy

- Keep `board.example = true` while the selected device inputs are incomplete.
- Keep the Onyx DTS memory node as the zero-size placeholder. Do not replace it with a guessed range or a candidate inferred from another SM8735 phone.
- Keep the local identity seed as `required`; it is supplied only as a local build input.
- The firmware boot DTB is not qualified. Do not substitute the minimal ADT DTS or another stock DTB as a firmware DTB.
- The offline `scripts/check-inputs.py` result is expected to fail closed until provenance, memory and source inputs are complete. Do not bypass it to get a green check.

## Menu-only payload configuration

The payload config now enables the `Tools` entry so the Advanced Logger QR exporter can be opened after the menu is usable. The package source path points to the adjacent UniXNU checkout (`../UniXNU`). Neither setting supplies a kernel, firmware DTB, or identity seed, and neither is evidence that the menu or exporter works on device.

QR logging is only usable after UniXNU's menu has appeared and accepts input, with the logger data and display path functioning. It cannot diagnose a black screen or a halt before menu interaction. Such failures need an earlier observable channel, such as UART or a separately qualified USB/ADB handoff.

## Firmware-volume acceptance

Run the byte-level offline acceptance check after a firmware FD has been built:

```sh
python3 scripts/accept-firmware.py \
  --fd ../Mu-Silicium/Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
  --unixnu ../UniXNU \
  --uefi ../Mu-Silicium \
  --json docs/firmware-acceptance.json
```

The checker reads the FD itself, requires exactly 3 MiB, validates the compact outer FV and its guided LZMA-compressed nested FV, then checks FFS module GUIDs against `FILE_GUID` values in the UniXNU and Mu_Basecore INF sources. The required set is UniXNU, UniXNUDxe, DarwinBoot, UniXNURamDiskDxe, DiskIoDxe, PartitionDxe, FAT, English Unicode collation and AdvancedLogDxe. The JSON manifest binds the actual FD and source INFs by SHA-256 and reports source checkout revisions/dirty state. It checks structural/module presence only; it does not qualify build reproducibility, driver dispatch, memory safety, cryptographic authenticity, a boot image, or device behavior. Do not write a passing synthetic-fixture result as an FD acceptance result.

## Runtime evidence captured 2026-11-28

A read-only `adb` capture on the rooted device recorded fingerprint
`Redmi/onyx/onyx:17/CP2A.260605.016/OS4.0.4.0.XOLCNXM:user/release-keys`, slot
`_a`, and `ro.boot.flash.locked=1` with `verifiedbootstate=green`.

`/chosen` on the live tree holds `linux,initrd-start = 0xb5921000` and
`linux,initrd-end = 0xb7ffeb18`. That end is not sector aligned, which showed the
first SEC validator was too strict; it now rounds up and requires the padded
range to stay inside the same reserved region. The padded end `0xb8000000` still
fits the `Kernel` reservation, and no firmware reservation (`UEFI_FD`, stack,
SEC/DXE heaps) overlaps the payload.

The locked bootloader is a hard prerequisite, not a verification result. A
locked state refuses `fastboot boot` of an unsigned image, so the acceptance
ladder cannot start until Mi Unlock is completed with the stock archive in hand.

## Board-map cross-check

`Tests/OnyxHandoff/test_onyx_board_map.py` parses the descriptors from
`Platforms/Xiaomi/onyxPkg/Library/MemoryMapLib/MemoryMapLib.c` and feeds the
captured initrd range through the real validator, so a map edit that moves a
region fails the test instead of quietly invalidating the handoff assumptions.

That cross-check changed the implementation. `Kernel` is system memory typed
`EfiReservedMemoryType`, but `XBL_DT` — where the bootloader places the device
tree — is a memory-reserved resource descriptor, not system memory. Requiring
`EFI_RESOURCE_SYSTEM_MEMORY` excluded exactly the region that must be accepted.
The validator now discriminates on the reservation (a reserved descriptor never
becomes a free page) and keeps the name allowlist to exclude display, modem PIL
and AOP carve-outs.

With the live map and the captured range the validator accepts a tree in
`XBL_DT`, rounds `0xb7ffeb18` up to `0xb7ffec00` and confirms it stays inside the
`Kernel` reservation ending at `0xb8000000`. It rejects a tree anywhere in the
firmware footprint, rejects the initrd when the `Kernel` reservation is removed,
and rejects a payload that runs past `0xb8000000`.

## Payload configuration must match the parser, not the documentation

The first draft of the menu payload used `[ui] tools = true`. `UniXNULib/Config.c`
never reads that key: `tools` is an *entry action* (`Config.c:1151`), and `[ui]`
parses only `title`, `scale`, `logo`, `layout`, `portrait_below`, `console` and
`theme`. Unknown keys are ignored silently, so that payload would have produced a
menu with no Tools entry, no error, and no way to reach the QR exporter — the
exact diagnostic channel milestone 1 depends on.

`scripts/check-payload-config.py` now extracts the tables, keys and actions from
`Config.c` itself and rejects anything the firmware does not consume, so a later
edit cannot reintroduce the mistake. The shipped image was verified by extracting
the ramdisk from the boot image and reading the config out of the FAT volume:
`3,993,129` kernel bytes equals the 224-byte shim, the 3 MiB firmware volume and
the 847,177-byte device tree exactly.

## The guard must be visible in the volume, not only in source

`Sec.inf` is placed in `FVMAIN_COMPACT`, the *outer* volume, beside the
compressed inner `FVMAIN`. A search of the inner volume therefore reports the
handoff guard as absent even when it compiled correctly — an easy way to draw the
wrong conclusion. The acceptance script now extracts the `ONYX:` diagnostic
markers from `OnyxHandoff.c` and requires each to appear in the compact volume
bytes, so a guard that is compiled out, optimised away or linked into the wrong
volume fails acceptance instead of shipping silently.

The current volume carries all 13 markers. This is a presence check only; it
cannot show that the guard is reached at runtime.

## Build determinism

Two consecutive builds of identical sources produce FVs that differ in exactly
eight bytes, all inside the CodeView `RSDS` record of `PcdDxe`
(`80CF7257-87AB-47F9-A3FE-D50B76D89541`) at module offset `0x74bc`. Everything
else, including all other module bodies, matches byte for byte.

`/Brepro` is present on every link line (verified in the build log) and does not
remove that signature, so the debug-directory GUID is generated independently of
the reproducible-build hash. Do not describe the firmware as bit-reproducible.
The verification ladder therefore binds each tested image by the SHA-256 of the
image that was actually packed.

## Milestone-1 image packaging

`make-menu-image.py` calls UniXNU's own `scripts/unixnu/bootimg.build` with an
explicit board mapping rather than the CLI, because `board.example = true` keeps
the CLI gate closed and this image is a bring-up probe. The packer still
re-verifies its own output.

| Input | Value |
| --- | --- |
| Firmware volume | `ea2ff324...`, 3 MiB |
| Appended device tree | the captured runtime FDT, SHA-256 `42dc9ca6...` (not the ADT DTS) |
| Payload | 16 MiB FAT12 volume with `EFI/UniXNU/unixnu.toml` exposing a Tools entry |
| Header | Android v4, `kernel_compression = none` |
| Output | `out/onyx-menu-boot.img`, 20,779,008 bytes, SHA-256 `e0258873...` |

The packer reported `shim_bytes = 224`, `ramdisk_bytes = 16777216` and
`kernel_address = 0x0` (v4 has no load addresses).

## Device attempts 2026-11-28

### What was observed

| Run | image | result |
| --- | --- | --- |
| 1 | menu, `46758031...` | `Booting OKAY`; device back in fastboot, screen dark |
| 2 | menu with the reordered guard, `49a06104...` | `Booting OKAY`; back in fastboot, watched 60 s |
| 3 | stock `boot_a` dumped from the device | `Booting OKAY`; Android came up |
| 4 | spin probe (valid header, then `b _Start`) | first `Load Error`, then `Booting OKAY` after a clean `reboot-bootloader`; back in fastboot |

Screen state is not a usable signal on this hardware: even a stock boot shows no
Redmi logo and only lights up at the second stage, which was confirmed on the
device during this work.

### The transfer acknowledgement does not mean the payload ran

The spin probe carries a valid ARM64 header and then branches to itself forever.
An unconditional self-branch cannot return, so if the bootloader had transferred
control the device would have hung and needed a power cycle. It instead
reappeared as `18d1:d00d` (fastboot) within about a second, reproducibly, across
two trials started from a clean `fastboot reboot-bootloader`.

So `Booting OKAY` acknowledges the download, not execution. Verification ladder
step 1 as written in the design ("bootloader accepts the header") is satisfied
only in that transport sense, and step 2 cannot be reached by observing the
device, because nothing of ours appears to run.

The same file also produced both `Booting OKAY` and
`Booting FAILED (remote: 'Failed to load/authenticate boot image: Load Error')`
depending on the state the previous failed attempt left the bootloader in, so a
single `OKAY` is not evidence of anything. Every device result must name the
exact image hash and whether the bootloader was freshly re-initialised.

The stock control is weaker than it looks: "booted Android" is also what a plain
reboot produces, so it does not prove that `fastboot boot` runs a transferred
image on this board.

### Root cause found: the ABL adds text_offset to the jump address

The stock image and every UniXNU image differ in the arm64 header fields:

| Field | stock `boot_a` | UniXNU image |
| --- | --- | --- |
| `text_offset` (offset 8) | `0x0` | `0xa7100000` (the firmware base) |
| `image_size` (offset 16) | whole kernel field | shim plus firmware volume |
| `magic` (offset 56) | `ARM\x64` | `ARM\x64` |

Signing is not the obstacle: a copy of the stock image with one byte flipped —
breaking its signature — still booted Android, and the USB trace showed the
successful pattern `18d1:d00d` → disconnected → `18d1:4e11`. Our images never
produced the disconnect, so the ABL never left its own loop.

The decisive experiment was the spin probe with only `text_offset` patched to
zero: the device `Booting OKAY`, lost USB at about eight seconds and stayed
disconnected for the rest of the observation. A shim that branches to itself
cannot surrender the CPU, so the shim was running. The ABL computes the jump
address as the load address plus `text_offset`; writing the firmware base there
sends it past the end of RAM.

This also explains the community history of "accepted by fastboot, black screen,
no ADB": the image never executed. `BootShim.S` keeps the firmware base in that
word because the packer checks it there, and onyx's ABL is the first board in
this tree observed to honour the field.

Working around it: `make-menu-image.py` zeroes `text_offset` in the packed image
after the packer has verified its own output, and records the original value plus
the new SHA-256 in `boot.json`. `BootShim` still copies to `FD_BASE` from its
instruction stream, so the firmware lands where its memory map expects it; only
the bootloader-visible field changes.

### Consequences for the port

- Any onyx image built by the stock packer without this adjustment will appear to
  work (`Booting OKAY`) and do nothing. This is a device-specific constraint the
  design document did not know about.
- The correct long-term fix is a BootShim or packer option that separates "where
  the firmware goes" from "what the header advertises", rather than a post-build
  patch.

### Consequence

The milestone cannot be advanced by repeating `fastboot boot`. Either the ABL
refuses unsigned images on this board, or it jumps and faults before the first
instruction is retired; both look identical from the host because there is no
observable channel before DXE. Resolving it needs an early log path (UART) or an
execution path other than `fastboot boot`, and the design's "never `fastboot
flash`" rule means that choice belongs to the user.

### BootShim change made in this round

Overlap between the loaded image and the firmware destination is now resolved by
copying backwards when the destination sits above the source, instead of jumping
to the dead loop. The dead loop now only guards arithmetic overflow. This removes
a failure mode where a bootloader that loaded the image near `FD_BASE` would have
parked the CPU permanently.

## Hardware status and safety

No successful UEFI/menu boot is claimed. A prior `fastboot boot` attempt was black-screen/unobserved and was recovered by rebooting Android; it did not demonstrate UEFI success. No `fastboot flash` or partition write is part of this work. Any future device attempts remain `fastboot boot` only, after log capture and recovery readiness.

The first milestone is not complete until the same SHA-256-bound image cold-boots to an interactive UniXNU menu three consecutive times and a log is saved for each run. Report firmware screen, menu interaction, payload discovery, storage, display, input and GPU results separately. A host unit test or FV parser pass is not a hardware result.

## Current offline verification record

- `python3 -m unittest tests.test_accept_firmware -v`: synthetic nested-FV fixtures only; covers valid structure/module set, missing module, wrong FD size, corrupt compression and JSON manifest hashing.
- `python3 -m unittest tests.test_port_policy -v`: checks the example/zero-DRAM policy, Tools setting, sibling source path and absence of guessed firmware-DTB/identity values.
- `python3 -m unittest discover -s tests -v`: run after the takeover changes; record its actual exit status. Test fixtures are not Onyx hardware evidence.
- `python3 scripts/check-inputs.py --unixnu ../UniXNU --json`: expected to fail until the documented inputs and provenance are supplied.
- No hardware operation is recorded by this takeover work.

## Firmware build and FD acceptance recorded in this takeover

A DEBUG CLANGPDB build of the isolated Mu-Silicium worktree at
`1d0f1e41018b2519ab9b41b60ac073453e346ba0` plus the local diff produced the 3 MiB
volume `Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd`, SHA-256
`ea2ff3248bd6b44d6a85144af1b95b0bbd5a928d5f6f4a645f475642c4a4922a`.

`scripts/accept-firmware.py` reported 109 inner FFS files and all nine required
module GUIDs (UniXNU, UniXNUDxe, DarwinBoot, UniXNURamDiskDxe, DiskIoDxe,
PartitionDxe, Fat, EnglishDxe, AdvancedLogDxe), an 8-byte nested-wrapper prefix
and 0x805008 decoded bytes. This is host structure evidence for one build; it
does not prove dispatch order, memory safety, or device boot.

Build inputs were independent of any pre-existing local tree: Mu_Basecore
`64f478939955e45faa632c160ae2a75a5ff7ef7f`, Common/Mu
`566cf5c8c2c8adf8e1a337ced1d147bc6246856f`, Binaries
`9f4dbfd7d61acdae69fd5bb48720ce7e53711e25`, Silicium-ACPI
`8c4cdc43abf23cffdeb588621126253bb2c559da`, openssl
`67b5686b4419b4cb8caa502711c41815f5279751`, LLVM/LLD 22.1.8, and
`SOURCE_DATE_EPOCH` pinned to the Mu commit time.
