# UniXNU — Redmi Turbo 4 Pro (onyx)

**Experimental reconstruction. No successful UEFI boot is claimed yet** — the boot
loader accepts the image but the firmware has not been observed running. Nothing
has been flashed; every device test used `fastboot boot` only.

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
an offline, byte-level acceptance check. The boot loader accepts the image, but no
firmware output has been observed yet. Read
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
python3 -m unittest tests.test_accept_firmware tests.test_port_policy tests.test_payload_config
python3 scripts/check-payload-config.py ../menu-payload/EFI/UniXNU/unixnu.toml --unixnu ../UniXNU --require-tools
python3 scripts/check-inputs.py --unixnu ../UniXNU       # expected to fail closed
python3 ../UniXNU/scripts/porting-record.py check --device .
```

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
| `0001`, `0002` | historical runtime-FDT and Advanced Logger work |
| `0003` | historical BDS platform option |
| `0007` | BootShim: header describes shim plus FD, runtime `x0` preserved, relocation published with `dc cvac`/`dsb`/`ic iallu`/`isb`, overlap resolved by a backwards copy |
| `0008` | SEC: fail-closed FDT/initrd handoff guard, ownership decided before any dereference |
| `0009` | DSC/FDF: UniXNU stack, Advanced Logger, `FdtLib`, PE alignment `0x1000`, `/Brepro` |
| `0010` | host tests for BootShim and the handoff guard |

`0007`–`0010` apply cleanly, in order, to a fresh `Firef1yfly/Mu-Silicium` checkout.

## Bring-up order

1. Keep the device on `fastboot boot` only; never `fastboot flash`.
2. Boot the menu-only image and confirm the firmware runs at all (the USB link must
   drop; staying on `18d1:d00d` means the ABL never jumped).
3. Reach an interactive UniXNU menu and export one Advanced Logger QR log.
4. Only then qualify the firmware device tree, the payload volume size and the
   kernel path.

The first milestone is complete when the same image hash cold-boots to an
interactive menu three consecutive times with a log saved for each run.

Common references: [porting](https://unixnu.com/porting/), [UEFI firmware](https://unixnu.com/porting/uefi-firmware),
[device repository](https://unixnu.com/porting/device-repository), [bring-up](https://unixnu.com/porting/bring-up).
