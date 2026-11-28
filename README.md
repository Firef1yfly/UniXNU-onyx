# UniXNU — Redmi Turbo 4 Pro (onyx)

English | [简体中文](README.zh-CN.md)

**Experimental reconstruction. No successful UEFI boot is claimed yet** — firmware
has been observed running deep into DXE dispatch on the device and then falling
into the platform's unable-to-boot path (a grey frame), but no boot option, menu
or OS has ever been reached. Nothing has been flashed; every device test used
`fastboot boot` only.

## Current scope

- Target: Redmi Turbo 4 Pro, codename `onyx`, SM8735, running OS `4.0.4.0.XOLCNXM`
  (fingerprint `Redmi/onyx/onyx:17/CP2A.260605.016/OS4.0.4.0.XOLCNXM:user/release-keys`).
- Provisional OS profile: upstream `ipados-17.7.11-21H461`.
- `board.example = true` deliberately keeps unfinished inputs from being treated as
  production configuration.
- The selected generic components are not proof of storage, display, touch, GPU,
  network or power support.
- The minimal DTS retains zero-size DRAM on purpose; no memory range is inferred
  from another SM8735 phone.
- Firmware status is `planned` in [porting.toml](porting.toml); all areas remain
  unverified on hardware.

## Where the firmware stands

A DEBUG CLANGPDB Mu-Silicium build succeeds and the resulting 3 MiB volume passes
an offline, byte-level acceptance check. On the device the volume dispatches the
whole DXE driver set — three screens of `DEBUG` text through the platform
`SerialPortLib` are on record — and then stops with a grey frame, which the
platform BDS paints when it gives up on its boot options
(`PlatformBootManagerUnableToBoot`). The hand-off to the UniXNU application is now
owned by `PlatformBootManagerAfterConsole()` through the platform's
`DeviceBootManagerLib`, so BDS cannot reach that path while the application is
present. None of this has reached a menu yet. Read
[the takeover record](docs/TAKEOVER-UEFI.md) before changing anything here.

### The onyx boot loader adds `text_offset` to the jump address

This is the most important board fact discovered so far, and it invalidates every
earlier "accepted by fastboot, black screen" observation:

| Field | stock `boot_a` | stock packer output |
| --- | --- | --- |
| `text_offset` (offset 8) | `0x0` | `0xa7100000` (firmware base) |

The ABL computes `jump = load address + text_offset`. Writing the firmware base in
that field sends the CPU past the end of RAM, so the image reports `Booting OKAY`,
never executes, and the board falls back to fastboot. A self-branching probe shim
hung the device only after that field was zeroed, which confirms the mechanism.

Any packaging step must zero `text_offset` in the packed image after the packer
verifies its own output, and record the original value in `boot.json`.
[scripts/make-menu-image.py](scripts/make-menu-image.py) does this:

```sh
python3 scripts/make-menu-image.py --fd <SILICIUM_UEFI.fd> --dtb <device.dtb> \
  --ramdisk <payload.img> --output out/onyx-menu-boot.img
```

Signing is not the obstacle: a stock image with one byte flipped still boots.

## Verifying a firmware volume

The acceptance check parses the FD bytes — outer compact FV, guided LZMA inner FV,
then FFS module GUIDs read from the UniXNU and Mu_Basecore sources. It also requires
the SEC handoff guard's diagnostic markers to appear in the compact volume, because
`Sec.inf` lives there and not in the decompressed inner volume.

```sh
python3 scripts/accept-firmware.py \
  --fd ../Mu-Silicium/Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
  --unixnu ../UniXNU --uefi ../Mu-Silicium --json docs/firmware-acceptance.json
```

Required modules: UniXNU, UniXNUDxe, DarwinBoot, UniXNURamDiskDxe, DiskIoDxe,
PartitionDxe, FAT, English Unicode collation, AdvancedLogDxe. The check is
structural only; it does not prove dispatch, memory safety or boot.

## Checks

```sh
python3 -m unittest discover -s tests -p 'test_*.py'      # 203 tests; upstream-tree ones skip
UNIXNU_UEFI=../Mu-Silicium python3 scripts/check-firmware-inputs.py
python3 scripts/check-payload-config.py ../menu-payload/EFI/UniXNU/unixnu.toml --unixnu ../UniXNU --require-tools
python3 scripts/check-inputs.py --unixnu ../UniXNU       # expected to fail closed
python3 ../UniXNU/scripts/porting-record.py check --device . --base origin/main
```

`scripts/check-firmware-inputs.py` is the board's `[firmware] preflight`, so the
official firmware step runs it too. It compares every file the series touches with
the blob that series records for it — which catches a tree that is one patch old, a
hand edit and a missing file — and refuses a Mu-Silicium `onyx.toml` whose
`uefi_fd` base/size, compression or header version drifted, a `board.toml`
compression setting that disagrees with the firmware's, and an `onyx.dsc`/`onyx.fdf`
that lost the PE alignment, the `FdtLib` mapping, the `-DONYX_FDT_HANDOFF=1` switch
or one of the eight required modules. Without `UNIXNU_UEFI` it skips and says so,
because `unixnu package --check` runs it on machines with no firmware checkout.

The record check is run by CI on every push, and it compares the push range against
`origin/main`: a change that touches an owned path without updating that area's
findings fails. `tests/test_porting_record.py` runs the same command, so that
failure happens locally first.

`check-inputs.py` failing is correct while the example gate, DRAM evidence and
`inputs.toml` provenance are missing; do not weaken it to get a green result.

`check-payload-config.py` exists because a payload that looks right can be
silently ignored: `[ui] tools = true` is not read by `Config.c` (Tools is an entry
action), and unknown keys produce no error — the menu then has no way to reach the
QR log exporter.

## Firmware patches

The Mu-Silicium side is carried as a series in [patches/uefi](patches/uefi):

| Patch | Contents |
| --- | --- |
| `0001` | BootShim: keep the runtime FDT and describe shim plus volume |
| `0007` | BootShim: header describes shim plus FD, runtime `x0` preserved, relocation published with `dc cvac`/`dsb`/`ic iallu`/`isb`, overlap resolved by a backwards copy |
| `0008` | SEC: fail-closed FDT/initrd handoff guard, ownership decided before any dereference |
| `0009` | DSC/FDF: UniXNU stack, Advanced Logger, `FdtLib`, PE alignment `0x1000`, `/Brepro` |
| `0010` | host tests for BootShim and the handoff guard |
| `0011` | bring-up report driver: prints the DXE checkpoints through `DEBUG` and stops the board |
| `0012` | UniXNUDxe: direct-start fallback when BDS has no option to start (kept for its registration and markers; `0014` is what actually fires) |
| `0013` | host tests for that boot path |
| `0014` | `DeviceBootManagerLib`: the hand-off happens in `DeviceBootManagerAfterConsole()`, before BDS reads a load option, so `PlatformBootManagerUnableToBoot()` is unreachable while the application is present |

`0002` and `0003` were withdrawn: their content now lives in `0007`, `0008` and
`0009`. The remaining series applies cleanly, in order, to a fresh
`Firef1yfly/Mu-Silicium` checkout and reconstructs the exact tree that built the
accepted volume — `scripts/check-firmware-inputs.py` checks that by blob, and
`tests/test_uefi_patch_series.py` pins which checkout each patch belongs to (`0012`
targets the UniXNU tree, which `git apply` reaches only with `--directory=package`).

## Bring-up order

1. Keep the device on `fastboot boot` only; never `fastboot flash`.
2. Run one attempt through [scripts/device-ladder.py](scripts/device-ladder.py):
   `boot --image … --confirm-sha256 … --cold-restart` refuses an image that is not
   the hash you named or whose `text_offset` is not zero, writes a record, and
   derives its verdict from the polled device-presence sequence. A single
   `Booting OKAY` is never a pass.
3. Bind the panel to that record with `device-ladder.py attach --photo … --note …`,
   so the frames that show the menu are attached to the image hash that produced
   them instead of to a memory of the run.
4. Reach an interactive UniXNU menu and export one Advanced Logger QR log.
5. Only then qualify the firmware device tree, the payload volume size and the
   kernel path.

The first milestone is complete when the same image hash cold-boots to an
interactive menu three consecutive times with a log saved for each run.

Common references: [porting](https://unixnu.com/porting/), [UEFI firmware](https://unixnu.com/porting/uefi-firmware),
[device repository](https://unixnu.com/porting/device-repository), [bring-up](https://unixnu.com/porting/bring-up).
