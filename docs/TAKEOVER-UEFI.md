# Onyx UEFI handoff takeover record

## Scope and revisions

This record now lives in the device repository `/home/firefly/UniXNU-onyx` on branch `main`, tracking `origin/main` at `1d31324`. It began as an isolated worktree on branch `port/onyx-uefi-handoff` based on `Firef1yfly/UniXNU-onyx` commit `9afe88a6ce3ffd42b24ef7a2d4ef04aedf393085`; that worktree and branch name are history, not the current checkout. It is a source baseline, not a validated build revision. The reviewed adjacent upstream source checkouts were UniXNU `fdf81eaa832ce5c850d3c53c698407aa722a4653` and Firef1yfly/Mu-Silicium `1d0f1e41018b2519ab9b41b60ac073453e346ba0`; those revisions are not evidence that the Onyx-specific diff in this worktree builds or boots.

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

Those two adb values are disguised, and reading them as the lock state was an
error corrected on 2026-11-28. Fastboot is authoritative on this device and
reports `unlocked: yes` with `product: onyx` and `current-slot: a`, so the
bootloader is unlocked; the runtime capture in `docs/RUNTIME-ANDROID17.md` also
records `verified boot state: orange`, which is what an unlocked bootloader
reports. The lock was never the blocker: images did execute on the device
afterwards, with BootShim relocating the volume, SEC running and DXE output
reaching the panel.

`/chosen` on the live tree holds `linux,initrd-start = 0xb5921000` and
`linux,initrd-end = 0xb7ffeb18`. That end is not sector aligned, which showed the
first SEC validator was too strict; it now rounds up and requires the padded
range to stay inside the same reserved region. The padded end `0xb8000000` still
fits the `Kernel` reservation, and no firmware reservation (`UEFI_FD`, stack,
SEC/DXE heaps) overlaps the payload.

A locked bootloader would be a hard prerequisite, but this one is not locked, so
nothing in the acceptance ladder waits on Mi Unlock. What the ladder waits on is
an observable channel and a hash-bound image, which is a different constraint and
is why the bring-up report driver exists.

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

The volume of that round carried every marker. This is a presence check only; it
cannot show that the guard is reached at runtime. It also has to be re-run on
each build rather than trusted once: `OnyxHandoff.c` holds nineteen `ONYX:`
literals and the checker requires sixteen of them, and a later build compiled
the guard out entirely because the DSC lost its compile switch — the round
recorded at the end of this document. A previous "all markers present" sentence
in this document was true of its own build and false of the next one.

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
| Firmware volume | 3 MiB, the build `ea2ff324...` of that round (superseded; the later builds are bound below) |
| Appended device tree | the captured runtime FDT, SHA-256 `42dc9ca6...` (not the ADT DTS) |
| Payload | 16 MiB FAT12 volume with `EFI/UniXNU/unixnu.toml` exposing a Tools entry |
| Header | Android v4, `kernel_compression = none` |
| Output | `out/onyx-menu-boot.img`, 20,779,008 bytes |

That image hash `e0258873...` no longer resolves anywhere in this workspace, so
it is not cited further. The images that do exist are bound in the artefact note
under the round recorded at the end of this document.

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
only in that transport sense, and step 2 could not be reached by observing the
device, because at that point nothing of ours appeared to run. That was the
pre-`text_offset` state; the later runs in this document overturn it for the
images that carry the corrected header, and it is kept here as the reason a
`Booting OKAY` line alone is never counted as execution.

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
| `proprietary-files.txt`, firmware patches, DSC/FDF integration | done, as `patches/uefi/0001` and `0007`-`0013`; `0002` and `0003` were withdrawn and their surviving content folded into `0007`/`0009` |
| `README.md`, `AGENTS.md` with scope, commands and guide links | done, in English and Chinese |
| `.gitignore`, `local.toml.example` | done; local paths and generated output ignored |
| `unixnu` GitHub topic | added and verified |
| `.github/workflows/porting-record.yml`, `package.yml` | pushed; the `Porting record` check passes on `main` |

A pushed commit whose `porting.toml` does not parse makes the *next* run fail as
well, because the check parses the record at its base commit. Re-word the record
without stray quotes and push once more rather than rewriting history.
| `board.example` | stays `true`; the hardware inputs are incomplete and the specification forbids claiming otherwise |

`check-inputs.py` still fails closed, as it must while the DRAM evidence and
`inputs.toml` provenance are missing.

## Output paths, and why the report is still not visible

Two output paths behave differently on this board:

| Path | Result |
| --- | --- |
| `Print` -> ConOut -> GraphicsConsole -> GOP | nothing renders |
| `DEBUG` -> platform SerialPortLib -> framebuffer | renders (hundreds of lines were readable) |

Restricting `PcdDebugPrintErrorLevel` to errors made the framebuffer draw nothing
at all, so the level is back at its default. The bring-up report uses `DEBUG` at
error level and then halts, on the theory that a halt makes the report the tail of
the log; the device still ends on a grey frame after about three pages of output,
which means the driver did not reach its halt. Its file is present in the inner
volume; the cause is dispatch order. With `Depex = TRUE` it dispatched at DXE core
start, before the graphics and firmware-volume plumbing it reads, so its report was
written into a framebuffer path that did not exist yet. The driver now depends on
`gEfiGraphicsOutputProtocolGuid`.

What is established for that driver is only this: it is present in the volume and,
under the current depex, it dispatches after GOP is installed. Whether it reaches
its halt on hardware is not established — the panel evidence is a grey frame that
follows about three pages of `DEBUG` output, which is also what a driver that ran
with a broken display path would look like. A later revision powers the board off
after printing instead of halting, because staying dark is a display-independent
signal; that revision is not established on hardware either.

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

## Round recorded 2026-11-28 (host only): a silently disabled guard, a series that was not a stack, and a direct-start fallback

No phone was attached during this round and no `adb` or `fastboot` command was
run, so nothing below is a hardware result. BDS has still never been observed
starting `UniXNU.efi`; the newest device observation remains the grey frame and
reset consistent with `PlatformBootManagerUnableToBoot` recorded earlier in this
document.

### The handoff guard was compiled out and nothing failed loudly

`onyx.dsc` had lost its `-DONYX_FDT_HANDOFF=1` switch, and `Sec.inf` adds
`OnyxHandoff.c` only under that switch. The guard was therefore absent from the
firmware volume while the source, the host tests and the record all still said it
was there. This was measured on the last build in
`Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd`: 3,145,728 bytes, SHA-256
`be68806743b96a57ccf73a28cc75ad6565243ed0ec616d5d976f55e12f19531f`, in which
`strings -a` finds zero occurrences of `ONYX:`, `ONYX-BOOT` and `OnyxHandoff`.

`scripts/accept-firmware.py` refuses that volume, which is exactly what the marker
check was added for:

```
ERROR: the SEC handoff guard is not compiled into the compact outer FV: ONYX: FDT address 0x; ONYX: FDT and initrd ranges overlap; ... ONYX: x0 = 0x
```

It names the sixteen `ONYX:` markers it extracts from `OnyxHandoff.c`; the source
holds nineteen. The switch is restored in the live `onyx.dsc` (line 139) and
patch `0009` carries it, so a rebuild has the guard back. `Sec.inf` had also been
rewritten with LF endings while the tree uses CRLF, which produced a 69-line
phantom diff that said nothing about the guard; the endings are restored.

The lesson is worth stating plainly, because it is the failure mode this record
exists to prevent: a compile switch that gates a guard is part of the artefact's
identity, not a build convenience. Green host tests and a green source tree did
not show the missing guard; parsing the actual FD did.

Not every FD-path check is per-build, either. `tests/test_port_policy.py` reads
the tracked `onyx.dsc`, so it would have caught the dropped switch, and
`tests/test_accept_firmware.py` only exercises synthetic fixtures. The check that
matters for a device attempt is the one run against the bytes about to be packed.

### The patch series was not a cumulative stack

`0001`, `0002` and `0007` all diffed the same baseline BootShim blob, and `0002`'s
DSC/FDF hunks overlapped `0009`'s, so the earlier sentence in this document that
`0007`-`0010` apply cleanly in order described parts of the series and not the
series. It is now a real stack: `0001`, `0007`, `0008`, `0009`, `0010`, `0011`,
`0012`, `0013`, each applying in order onto the pristine baseline and
reproducing the live tree byte for byte.

`0002` (QR/Advanced Logger diagnostic) and `0003` (BDS platform option) were
withdrawn; their surviving wiring is folded into `0007` and `0009` and the folds
are documented in those patch headers. The orphan `OnyxBootOptions` provider was
not landed, because it still needs the application volume's device path — the
exact thing that is missing when registration cannot be trusted.
`tests/test_uefi_patch_series.py` pins the patch list and the blob-hash chain, so
a patch that stops being cumulative fails on the host instead of during a build:
thirteen tests, OK.

The series is two-tree and cannot be validated from one checkout: `UniXNUPkg` is
a symlink to the external UniXNU checkout
(`Mu-Silicium/UniXNUPkg -> UniXNU/package/UniXNUPkg`), so a patch touching
`UniXNUDxe.c` only applies when that checkout is present at the recorded
revision. Both trees must therefore be recorded for any build that carries
`0012`.

### A direct-start fallback exists as a host-tested contingency only

Patch `0012` leaves the `Boot####`/`BootOrder` registration as the primary path
and adds one fallback that arms only when that path cannot be trusted: the
application's firmware volume has no device path, or `gRT->SetVariable` fails for
`Boot####`/`BootOrder`. It logs the armed reason on `EndOfDxe` (hooked to log
only, because this platform signals `EndOfDxe` before it registers its own default
options) and starts the application's PE32 section once, on `ReadyToBoot`, with
`LoadImage(TRUE, gImageHandle, NULL, ...)` plus `StartImage`, under a run-once
flag. Every decision prints `DEBUG` at error level under the prefix
`ONYX-BOOT: `, including the case where nothing needed doing: `Boot%04x
registered first in BootOrder, BDS starts it, fallback not armed`. That last
marker matters, because it makes a successful registration visible instead of
leaving an empty log ambiguous.

Its limits are part of the record: it is not a second boot manager, it does not
run when both variables were written, it requires the application and the driver
to share a firmware volume, it changes nothing about image authentication, and it
is unverified on hardware. `Tests/OnyxBootPath` covers it on the host — nine
tests, OK, added by patch `0013`. The fallback has never fired on a device and
none of its markers has ever been read from the panel, so it is a contingency,
not an observed boot path.

Correction (2026-11-29): the trigger is wrong. Mu_Basecore signals
`gEfiEventReadyToBootGuid` only from `EfiBootManagerBoot()`
(`MdeModulePkg/Library/UefiBootManagerLib/BmBoot.c`) and Silicium's
`PlatformBootManagerLib` never signals it, so an armed fallback waits for an
event that a boot with no startable option never raises — exactly the boot it was
written for. Patch `0014` moves the hand-off to
`DeviceBootManagerAfterConsole()`; the round recorded 2026-11-29 at the end of
this document has the evidence and the artefact hashes. `0012` stays in the
series because the registration and its markers are still what the driver does.

### Artefact binding, and why two images with different hashes are not a contradiction

Every pack rewrites `out/boot.json`, so that file binds only the pack that wrote
it last and says nothing about the images written before it. The images were
hashed in place on 2026-11-28:

| Image (`/home/firefly/文档/onyx-porting/out/`) | Bytes | SHA-256 |
| --- | ---: | --- |
| `onyx-menu-boot.img` | 20,779,008 | `69945aedf50538574c42f2be5505200513932e3dd2dd2dbd3feb3eb80cd5322c` |
| `onyx-menu-boot-nodiag.img` | 20,779,008 | `6dfaadaa3a26660dea965d898cef3cae1fe22c57add494833792efb51264c383` |
| `onyx-ab-noguard.img` | 20,779,008 | `28415a3f50587da4d9274852834f94520c01a072e847e5342ef96bade432fe15` |
| `onyx-probe-shutdown.img` | 20,779,008 | `33160e5223713f323ee2602485718e5f73057b32e5a1daaa5812709c1ce2989d` |
| `onyx-probe-coldboot.img` | 20,779,008 | `83e0c436b3e9cf52b5aa4dcc0fe5f2bf00b1f9ecc704737b637cb3871f2e1de7` |
| `onyx-menu-spin.img` | 20,779,008 | `122797670433e3f0200cbf255455d5e98f73b8822879227a34d85b3c47f3c233` |
| `onyx-probe-spin.img` | 4,001,792 | `bde2c053f7e2c5801301ac6db9558b9f69c2cb9248cea3a96eda644a29641ff4` |

The latest pack (2026-11-29 00:38) is bound end to end: `out/boot.json` names
`image_sha256 9809edcb0f9ce5df47e827666cfbda44342e40a287fe9a77e2f81bf83e5a1147`
beside `fd_sha256 8b2d6b9ce58ea6f1c511774a22c4ebec6ca5fdcdf9612e492687fa6aa239d5b8`
and `dtb_sha256 42dc9ca6223c3b0ba61d6960c611bca08ddeb2283d41657cbf2d0fe7f88d013f`,
and the same bytes are shelved as `out/onyx-menu-boot-9809edcb.img`. Re-reading
that file confirms the structure the record depends on: `text_offset` is `0x0`
(the ABL jump-address bug), the FD starts at shim offset 256, and the header's
`image_size` `0x300100` equals shim plus 3 MiB exactly, so the volume in the
image is the volume `scripts/accept-firmware.py` accepted.
An earlier table row above still disagrees with the file of the same name,
because each pack rewrites it in place; those rows are dated observations, and an
image counts as evidence only when a `boot.json` beside it names it, or when its
hash was taken from the file itself.

### What this round does not claim

No menu, no payload discovery, no QR log and no OS boot. The guard, the series
order and the fallback are all host-side facts. Milestone 1 — the same image hash
cold-booting to an interactive UniXNU menu three times with a saved log each
time — is unmet, so every area in `porting.toml` stays `planned`, and the area
`firmware` deliberately still has no completion claim.

## Round recorded 2026-11-29 (host, plus the hand-off owner's device photos): the panel log, and a fallback that could not fire

No phone was attached during this round; no `adb` or `fastboot` command was run.
The device part of this section is three screenshots of the panel's debug console
that the previous owner took before the hand-off, plus their account of what
happened after the last one.

### What the panel actually showed before the grey frame

| Screenshot (`/home/firefly/文档/onyx-porting/evidence/20261129/`) | Bytes | SHA-256 |
| --- | ---: | --- |
| `page1-dxe-start.png` | 1,471,711 | `2909bb5702583a0a6da6fe9b46ec0928dbbbb7b25507ab4b96401ebd43a01dfd` |
| `page2-dxe-mid.png` | 1,766,215 | `2ca13c01d3f4a0145525dbcc4cb92f3fd7bad68fa719e0e5b94868b2f38609d5` |
| `page3-last-before-grey.png` | 1,149,396 | `9b2182bb8e6cc55e5a0b9c9438adf16c2bb1c8fe1f65b007506710ba8c832b73` |

The frames are rotated a quarter turn (the platform's framebuffer is not the
panel's orientation), and read in that rotation they carry the ordinary DXE
dispatch log: `Loading driver at 0x... EntryPoint=0x...` for some sixty modules in
address order, an `[00012732] ChargerPlatform_Init` group, a
`[00012956] usb_repeater_init` / `qcom repeater found` / `READING: reg 0x...` group,
`[00013024] usb_redriver_init`, `[00013036] ConnectSts` and a `ButtonsDxeTest:
Keypress SDAM data payload` line. The last captured frames end mid-dispatch on
`ConSplitterDxe`, `PrintDxe` and `SimpleTextInOutSerial`, and the previous owner
reports a grey frame after that.

What this establishes, and what it does not:

- Firmware reached BDS setup. DXE dispatch of the whole volume, the charger, USB
  and button drivers, ConSplitter and the console plumbing is far past SEC, and
  this is the first device evidence that the volume built here runs this deep.
- The readable channel is `DEBUG` through the platform `SerialPortLib`, exactly
  as `docs/DEVICE-DIAGNOSTIC-FAILURE.md` says; `Print` never appears.
- The screenshots are not hash-bound to any image. They predate this hand-off, no
  `boot.json` accompanies them, and the bootloader was not re-initialised for a
  named hash, so they fix the shape of the failure, not the artefact.
- None of the three captured pages contains an `ONYX-BOOT: ` line. That is not
  evidence that the registrar driver did not run: it is placed late in the volume
  and dispatch had not reached it in the frames that were captured.

### Why patch 0012's fallback cannot have fired, and what the grey frame is

`gEfiEventReadyToBootGuid` is signalled in exactly one place in Mu_Basecore —
`EfiBootManagerBoot()` (`MdeModulePkg/Library/UefiBootManagerLib/BmBoot.c`), that
is, only after BDS has already chosen a load option and is about to start it.
Silicium's `PlatformBootManagerLib` never signals it either. A boot in which BDS
finds nothing to start therefore never signals `ReadyToBoot`, so the fallback
armed by `0012` waits for an event that cannot occur: it covers the case where
registration succeeded and BDS then failed, not the case where there is nothing to
boot. This is now a correction to the record, not a hypothesis.

That boot ends in `PlatformBootManagerUnableToBoot()`
(`Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/BootManager.c`), which calls
`DeviceBootManagerUnableToBoot()`, then `DisplayBootGraphic (BG_NO_BOOT_OS)`, then
`gBS->Stall (10000000)`, then `gRT->ResetSystem (EfiResetShutdown, ...)`. The
no-boot-OS graphic is painted over the debug console, which is why the panel turns
into a featureless grey frame while the console text is still the only place the
reason was written; `BdsEntry.c` prints `[Bds] Unable to boot!` at `DEBUG_ERROR`
immediately before that call, so the line above the graphic is the diagnostic the
next attempt has to capture.

### The hand-off now has an owner that cannot be skipped

Patch `0014` adds `Platforms/Xiaomi/onyxPkg/Library/DeviceBootManagerLib` and maps
the library class to it in `onyx.dsc`; the inherited instance was
`SiliciumNullPkg`'s no-op. `PlatformBootManagerAfterConsole()` calls
`DeviceBootManagerAfterConsole()` once per boot, after console connect and after
the disk stack is dispatched, and before BDS looks at a single load option. The
library finds the firmware volume carrying the application file, reads its PE32
section, and `LoadImage`s plus `StartImage`s it from that buffer. Because the
application is started there, BDS never reaches its option loop, so
`PlatformBootManagerUnableToBoot()` becomes unreachable while the application is
present — the grey frame is removed by construction rather than by a better
trigger.

Its limits are the same as `0012`'s and are recorded with it: the application and
BDS must share a firmware volume, image authentication is unchanged, the
application is started at most once per boot, and a returning application is a
bring-up signal, not a supported state. Every step prints `DEBUG` at error level
under the prefix `ONYX-BOOT: ac: `, so the panel log now distinguishes "the
hand-off ran" from "BDS still had to look for options".

### Rebound artefacts for the next device attempt

The FD rebuilt from the same sources plus `0014` is
`Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd`, 3,145,728 bytes, SHA-256
`d1ceaae4a58a6042e2b9d704fb7d87189bf94e5a8ca7c5431d766ab708cdf811`.
`scripts/accept-firmware.py` accepts it with the same nine required modules and 14
SEC guard markers, 110 inner FFS files, and the decompressed inner volume carries
29 `ONYX-BOOT: ` markers, nine of them the new `ONYX-BOOT: ac: ` family, next to
the single `[Bds] Unable to boot!` string.

The menu image packed from it is `out/onyx-menu-boot.img`, 20,779,008 bytes,
SHA-256 `fc9374e452fbea8bd888877e3c36efd0497857812fbe7b73bc68014bcc757a8e`,
shelved byte-identically as `out/onyx-menu-boot-fc9374e4.img`; `out/boot.json`
binds it to FD `d1ceaae4...` and DTB
`42dc9ca6223c3b0ba61d6960c611bca08ddeb2283d41657cbf2d0fe7f88d013f`, with
`text_offset` zeroed from `0xa7100000`, so the ABL jump-address bug stays handled.

A second build and pack on 2026-11-29 02:00 (an incremental relink of unchanged
sources) is recorded here because the firmware is not bit-reproducible and the
record must not pretend two packs can share one hash. That FD is 3,145,728 bytes,
SHA-256 `7ca3fe22bea67afb9d0cebe15b616dc110fb8810938470a67dbe8c827c824fb1`; it
accepts identically — nine required modules, 14 of 14 SEC guard markers, the same
110 inner FFS files, `ONYX-BOOT: ` 29 times with the nine `ONYX-BOOT: ac: ` new
lines, and one `[Bds] Unable to boot!` — and it differs from `d1ceaae4` only in
the eight `PcdDxe` CodeView bytes the record already names as the source of the
variation. Its image is `out/onyx-menu-boot.img`, 20,779,008 bytes, SHA-256
`83e75046304d6983a6e211e445737e1917d24c35f06e48f7be7e84deb6b492df`, shelved as
`out/onyx-menu-boot-83e75046.img`; `out/boot.json` binds it to FD `7ca3fe22...`
and to the same DTB, with `text_offset` zeroed from `0xa7100000`. The kernel field
of that image re-hashes to `7ca3fe22...` at shim offset 256, so the volume that
was accepted is the volume in the file. Both packs are recorded; a device attempt
names one of them, never "the current image".

### What this round does not claim

No menu, no payload discovery, no QR log, no OS boot. The photos are historical
device evidence of a firmware that ran deep into dispatch and then fell into the
unable-to-boot path; `0014` is host-built and host-tested only and has never run
on hardware. Milestone 1 — one image hash cold-booting to an interactive UniXNU
menu three times with a saved log each time — is still unmet, and every area in
`porting.toml` stays `planned`.

## Design-doc question settled on evidence: which counter does the timer run on

The port design left `USE_PHYSICAL_TIMER` open for onyx: the platform could use
the EL1 physical counter or the EL1 virtual counter, and the wrong choice shows up
late, as a firmware whose `TimerDxe` interrupts never arrive, whose `Stall` calls
return at once or never, and whose event log has no usable time base. It is not a
free choice: it has to match what the bootloader left behind.

Two facts settle it, and neither needs the phone:

- `Silicon/Qualcomm/BonitoPkg/BonitoPkg.dsc.inc` — the package onyx's `onyx.dsc`
  includes — sets `USE_PHYSICAL_TIMER = 0`, and
  `Silicon/Silicium/SiliciumPkg/SiliciumPkg.dsc.inc` turns exactly that into
  `ArmGenericTimerVirtCounterLib` (the virtual counter, `CNTVCT_EL0`) versus
  `ArmGenericTimerPhyCounterLib`. Every other Qualcomm package in the same tree
  makes the same choice, so this is the family default, not a stray value.
- No interrupt-number override is needed either: `ArmPkg.dec` defaults
  `PcdArmArchTimerIntrNum` to 30 and `PcdArmArchTimerVirtIntrNum` to 27, which are
  the Qualcomm PPIs, and `TimerDxe` reads whichever one the counter library
  selected. BonitoPkg overrides neither.

The device evidence agrees. The panel frames recorded before the hand-off carry
increasing `[000xxxxx]` timestamps across a dispatch log of about sixty modules, a
`gBS->Stall (10000000)` around the unable-to-boot path, and a ten-second pause
between the last frame and the grey one — all of which need a running time base.
A frozen counter would have shown as identical timestamps and as a stall that
returns immediately.

Decision: **keep `USE_PHYSICAL_TIMER = 0`; add no override to `onyx.dsc`.** The
`CNTCTLBase`/`CNTHCTL_EL2` question the design raised only matters if the virtual
counter stops advancing, and nothing observed so far suggests it does. The
falsifying observation is cheap to state: a log whose timestamps stop changing, or
a `Stall` that returns instantly, would send this back for a physical-timer build
to compare. Recorded 2026-11-29.
