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

### First confirmed execution

After zeroing `text_offset`, image `25c0d07a...` ran on the device: USB dropped
about four seconds after `Booting OKAY` and stayed gone for roughly a minute, the
screen showed several lines of firmware text, then a grey frame, and the board
returned to Android after the bootloader watchdog expired
(`ro.boot.bootreason=bootloader`, no pstore records).

That satisfies the "firmware output" rung of the ladder and, for the first time,
proves the whole transport works: the bootloader jumps into BootShim, BootShim
relocates the volume, and SEC starts.

Two things this exposed:

- The visible lines were SEC output only. DXE debug had been routed into the
  Advanced Logger RAM buffer by the DSC, whose only reader is the Tools QR
  exporter — which needs an interactive menu. A stall before the menu therefore
  produced no observable output at all. The DebugLib override is removed so DXE
  prints through the platform SerialPortLib to the framebuffer;
  `AdvancedLogDxe` stays in the volume and reports "no log" until it is switched
  back once the menu is reachable.
- The board resets through the bootloader rather than panicking, so a hang and a
  crash look the same from the host and both end in a stock boot.

### Reaching DXE, and why the screen was unreadable

Watching the framebuffer is not a usable channel before the menu: SEC writes to
the panel directly, and the graphics driver re-takes the display during DXE, so
that text is legible for only a couple of seconds. Lengthening the boot is not an
acceptable fix.

The first attempt drew that report through ConOut after GOP and text output were
installed. It cleared the panel and printed nothing legible, which is
indistinguishable from a hang, so the driver now writes pixels itself: the
background colour encodes the furthest checkpoint reached and one black bar per
checkpoint confirms the count. No font, no console binding and no added delay:

| Background | Meaning |
| --- | --- |
| unchanged grey | driver did not run, or GOP was unavailable |
| orange, 1 bar | driver ran and GOP is usable |
| green, 2 bars | and the SEC handoff HOB is present |
| cyan, 3 bars | and the memory map is readable, so the DXE core is fully live |

Nothing is added to the boot path; the report replaces the dead grey frame that
previously preceded the watchdog reset.

With that driver in the volume the board no longer resets on the boot loader
watchdog: it stayed off USB for over 100 seconds, where the previous build
returned to Android at about 65 seconds. Reaching the halt means the DXE core
dispatched, the graphics output and text output protocols were installed, and
ConOut accepted output.

### First DXE exception

With the corrected `text_offset` the firmware runs far enough to dispatch DXE
drivers and print through the console. The run ends in the default exception
handler:

```
ERT[ArmCpuDxe]CpuExceptionHandlerLib.c(438):((BOOLEAN)(0==1))
```

That line is the `ASSERT (FALSE)` at the end of `DxeCpuExceptionHandlerLib`'s
default handler, so an unhandled CPU exception occurred during `ArmCpuDxe`
dispatch and the register dump precedes it. The useful fields — exception type,
`ESR`, `ELR`, `FAR` — scrolled away under several hundred lines of DEBUG output.

For the next attempt the platform debug level is restricted to errors
(`PcdDebugPrintErrorLevel = 0x80000000`) so the exception header stays on screen.
That is a diagnostic setting only and must be restored before the port is
considered usable.

### Framebuffer geometry: the panel size is the wrong answer

The platform PCDs carried `1280x2772`, which is not this board. The live device
tree gives the panel geometry directly:

```
qcom,mdss-dsi-panel-width  = <0x5a0>   /* 1440 */
qcom,mdss-dsi-panel-height = <0xc80>   /* 3200 */
```

with the contiguous splash region at `0xfc800000` sized `0x02b00000`, matching
`Display_Reserved` in the board memory map. Setting the PCDs to those values made
DXE text render as scrambled glyphs, while `1280x2772` renders readable text, so
the panel geometry is not the geometry of the framebuffer the loader hands over.
`1280x2772` is restored and the mismatch is recorded rather than solved: the real
framebuffer mode still has to be measured.

### Image variants for the next device runs

| Image | Contents | Expectation |
| --- | --- | --- |
| `onyx-menu-boot.img` | includes `OnyxBringupReportDxe` | paints a checkpoint colour and halts, so the stage is readable |
| `onyx-menu-boot-nodiag.img` | same firmware without that driver | runs BDS to completion, so the menu or `No Operating System Found!` appears |

The report also mirrors `FindApplication`: it counts firmware volumes, how many
carry a device path, and how many hold `UniXNU.efi`, because `UniXNUDxe` cannot
register a boot option when either is missing — and an empty `BootOrder` looks
identical to a BDS that ignores a valid one.

Test the second one first once the panel geometry is correct: `Print` in
`PlatformBootManagerUnableToBoot` is not DEBUG-gated, so either outcome is
visible without any extra instrumentation.

### Consequences for the port

- Any onyx image built by the stock packer without the `text_offset` adjustment
  reports `Booting OKAY` and does nothing. The design document did not know about
  this constraint.
- The correct long-term fix is a BootShim or packer option that separates "where
  the firmware goes" from "what the header advertises", rather than a post-build
  patch; `scripts/make-menu-image.py` is the transitional implementation.
- The board resets through the bootloader rather than panicking, so a hang and a
  crash are indistinguishable from the host and both end in a stock boot. Any
  further progress depends on reading firmware output from the screen.

### BootShim change made in this round

Overlap between the loaded image and the firmware destination is now resolved by
copying backwards when the destination sits above the source, instead of jumping
to the dead loop. The dead loop now only guards arithmetic overflow. This removes
a failure mode where a bootloader that loaded the image near `FD_BASE` would have
parked the CPU permanently.

## Repository publication status

Checked against the device repository specification
(`docs/porting/device-repository.md` in UniXNU):

| Requirement | State |
| --- | --- |
| `board.toml` format 2, `porting.toml` format 1, matching identity | done; record checker passes (13 areas) |
| `feeds.toml`, `unixnu.lock`, `configs/`, `dts/`, `patches/xnu/series`, `package/` | present |
| `proprietary-files.txt`, firmware patches, DSC/FDF integration | done, as `patches/uefi/0001`-`0011` |
| `README.md`, `AGENTS.md` with scope, commands and guide links | done, in English and Chinese |
| `.gitignore`, `local.toml.example` | done; local paths and generated output ignored |
| `unixnu` GitHub topic | added and verified |
| `.github/workflows/porting-record.yml`, `package.yml` | written; not pushed yet because the current token lacks the `workflow` scope |
| `board.example` | stays `true`; the hardware inputs are incomplete and the specification forbids claiming otherwise |

`check-inputs.py` still fails closed, as it must while the DRAM evidence and
`inputs.toml` provenance are missing.

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
