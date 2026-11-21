# Current XNU and payload readiness audit

This is a read-only audit of the existing onyx kernel and payload outputs. It
did not build or modify the kernel, ADT, payload, board configuration, DTS,
porting record, firmware, or phone. The platform identity seed is private and
is deliberately not reproduced in this report or manifest.

## Decision

**The existing `payload.img` is synthetic bring-up output and is prohibited
from device use.** It is internally self-consistent as a FAT image, but its ADT
contains a fabricated 1 GiB `0x80000000..0xc0000000` memory range that does not
come from the current checked-in zero-memory DTS, a real EFI memory map, or a
qualified DarwinBoot allocation. The image is also missing trust cache, Data
seed, root policy/root binding, and an onyx UFS/root implementation. There is
no matching boot image under the current output directory.

This prohibition is independent of whether fastboot would accept a future
wrapper. `Sending OKAY`/`Booting OKAY` would not qualify the payload.

## Existing reusable output

The current kernel output is:

| file | bytes | SHA-256 |
|---|---:|---|
| `unixnu/out/onyx/ipados-17.7.11-21H461/onyx/kernel/kernel.macho` | 51,048,448 | `6954c1b2b61802fc4df17564d07a3ad090bca46d6cc23e1dcc20d9cc528b3f70` |

It is an ARM64 Mach-O executable. `kernel.json` records:

- native kernel SHA-256 `88345e346a6ada4344b09aa10ba28ab0444852ede450a0b7a3b9979ad48997f5`;
- original kernelcache SHA-256 `f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7`;
- prelink slide `-0x1000000`;
- 30 prelinked components plus one codeless component.

The list includes AppleMobileFileIntegrity, ApplePMGR, APFS, IOStorageFamily,
CoreTrust, AppleImage4, sandbox and the graphics/HID families selected by the
OS profile. The kernel contains `_arm_init`, but the inspected binary has no
`_native_ufs` or `_sheng_pmgr_run` symbol. The board defconfig explicitly keeps
`CONFIG_XNU_NATIVE_UFS` and `CONFIG_XNU_NATIVE_ADRENO` disabled. Therefore the
binary can remain a host-build reference, but it is not a qualified root-boot
kernel for onyx.

The current kernel is not the historical FAT kernel:

| generation | bytes | SHA-256 |
|---|---:|---|
| historical FAT kernel | 50,999,296 | `6cfb2c40100607e60e0a8156094f9d8044a3a4d3d5a591693a260d7ad477ce17` |
| current build kernel | 51,048,448 | `6954c1b2b61802fc4df17564d07a3ad090bca46d6cc23e1dcc20d9cc528b3f70` |

They must not be mixed with one another's ADT or described as the same build.

Current source provenance is also not clean: UniXNU is at
`7b730b231746667d8b7f54746c2c1ce45852611c` with local modifications to the
XNU progress patch and device-tree generator; the onyx repository is at
`542df208708b9be7341cc8e47e36dbb0938e35e0` with multiple tracked local
changes. Any final payload must record the exact source diff or a committed
revision, not only these base commits.

## Existing synthetic payload: exact readback

| file | bytes | SHA-256 |
|---|---:|---|
| `payload/payload.img` | 201,326,592 | `2b5efc601e617382243f93127ba1a4a14e48239fd77dc82abe61b8fdffebba2b` |
| embedded `kernel.macho` | 51,048,448 | `6954c1b2b61802fc4df17564d07a3ad090bca46d6cc23e1dcc20d9cc528b3f70` |
| embedded `kernel.macho.adt` | 11,456 | `1dd1ca867de5396fd06316572cc409b39d0fc70427ff198e8bce73b85ebf60cb` |
| embedded `unixnu.toml` | 330 | `4683ed5c3b8ffe010de194d383ee29e0a2e7576fa72f27d0d1f1835834b42d07` |

The payload manifest matches all three extracted hashes and states
`hardware_tested: false`, `trust_cache_sha256: null`,
`data_ramdisk_sha256: null`, `gpu_addon_sha256: null`, and
`panic_screen: false`. The current output tree contains no
`boot/boot.img` and no userdata output.

The payload is FAT32, 192 MiB, 512-byte sectors, 4 sectors per cluster, label
`ONYX`. Direct mtools readback finds only:

```text
EFI/UniXNU/unixnu.toml
EFI/UniXNU/Payloads/kernel.macho
EFI/UniXNU/Payloads/kernel.macho.adt
```

The config selects firmware-provided DarwinBoot and the XNU entry after a
three-second timeout. It has no trust cache, Data image, root-policy bundle,
GPU addon or payload DarwinBoot executable.

The ADT is structurally parseable and describes `iPad7,1`/`J120`, onyx/Tuna
compatible strings, CPU0 and GIC resources. Its `/chosen` records:

- `dram-base = 0x80000000`;
- `dram-size = 0x40000000` (1 GiB);
- a private platform seed (not reproduced here);
- chip/OS identity from the selected profile.

This memory was synthetic. The checked-in `dts/onyx-bringup.dts` intentionally
contains `reg = <0 0 0 0>` and `board.example = true`; current
generator code refuses zero memory. No current source configuration records
`0x80000000/0x40000000` as verified onyx/DarwinBoot memory. The runtime Android
FDT and `/proc/iomem` are not substitutes for a UEFI conventional-memory
allocation. Therefore this ADT must not be reused, patched in place, or sent to
the device.

## Host checks observed

Read-only checks performed during this audit, from the `unixnu/` checkout, were:

```text
PYTHONPATH=scripts python3 -m unittest unixnu.test_patch_chain unixnu.test_devicetree
  -> 5 tests OK
```

The test modules are `scripts/unixnu/test_patch_chain.py` and
`scripts/unixnu/test_devicetree.py`; the `PYTHONPATH=scripts` prefix and
`unixnu/` working directory are intentional. The extracted FAT kernel and ADT hashes match `payload.json`. These checks
validate patch ordering, generic ADT constraints and payload integrity only;
they do not qualify onyx memory, firmware allocation, kernel entry or root.

## Required real inputs and rebuilds

### Can be reused as a reference

1. The current prelinked kernel and its `kernel.json`, provided the final source
   diff is pinned and the kernel is rebuilt if root/platform components change.
2. The deterministic FAT layout and schema-1 generated config format.
3. The OS profile identity, original kernelcache pin, two allowed trust-cache
   bundle hashes, and root OS volume UUID from the pinned profile.
4. The existing firmware-loader convention: DarwinBoot belongs in the selected
   FD rather than the FAT. This still requires exact final-FD verification.

### Must be regenerated from same-build inputs

1. Hardware DTS and ADT from a single real, contiguous onyx DRAM range, with
   board reservations reconciled to the same-boot EFI map and Qualcomm RAM
   partition table.
2. DarwinBoot owned-memory size/excluded ranges/loader-inputs properties from
   the actual allocation policy. The current board has none, and the synthetic
   1 GiB ADT cannot choose them.
3. FAT payload with the selected kernel, new ADT, accepted trust-cache bundle,
   optional/required Data seed and root-policy sidecars from one recorded run.
4. Boot image from the fixed known-good firmware baseline and the verified FAT,
   followed by complete image readback. Do not rebuild or swap FD during this
   payload-only step.

### Still missing or unqualified

- **Memory:** structured UEFI descriptors and Qualcomm RAM partitions from the
  same firmware boot; one safe contiguous DarwinBoot allocation and exclusion
  policy. Android addresses and another device's window are not sufficient.
- **Platform identity:** a locally supplied nonzero seed. It must never enter a
  repository, report, command transcript, or public manifest.
- **Trust:** one actual bundle whose SHA-256 is one of the two hashes pinned by
  `ipados-17.7.11-21H461`. The existing payload has none.
- **Root/Data:** a reviewed root route, root volume binding, partition geometry,
  and—if the selected kernel enables owner Data—a preserved Data seed. The
  current board lacks userdata geometry and root-matching configuration.
- **Storage:** a reviewed SM8735/onyx UFS component and kernel archive. Native
  UFS is currently disabled, so a root image alone is unusable.
- **Root policies:** decide and record whether the selected VerifiedRoot route
  requires a `VROOTB01` policy bundle; no bundle or ADT mapping exists now.
- **Firmware loader:** final FD must contain matching UniXNU,
  UniXNURamDiskDxe, DiskIo/FAT and DarwinBoot modules. A host package build does
  not prove that the selected FD contains or dispatches them. The current
  `package/` output contains UniXNU application/driver binaries but no
  DarwinBoot artifact and is not an FD.
- **Menu/config handoff:** independently verify the already-prepared menu-only
  FAT on the fixed firmware baseline before allowing an XNU payload.

## Offline acceptance gate for a new payload

Before any phone test, require one manifest tying together:

1. exact UniXNU/device/SoC/firmware revisions and local-diff hashes;
2. kernel, ADT, trust cache, Data/root policy and FAT SHA-256 values;
3. ADT parsed back to the verified DRAM base/size, owned window, exclusions,
   loader-input records, root UUID, CPU/GIC and identity fields;
4. FAT directory readback proving every config reference exists and every
   optional ADT mapping has its corresponding file (and vice versa);
5. FD/FV readback proving the firmware loader stack is present;
6. boot-image boundary readback proving unchanged known-good shim/FD/DTB plus
   exactly the intended FAT change;
7. `board.example = false` only after all required real inputs are documented;
8. `hardware_tested = false` until a separate device observation is recorded.

A candidate fails closed if any source, hash, memory descriptor, optional
sidecar, root binding, or loader module is unresolved.

## Hardware acceptance order

After explicit user approval, use only `fastboot boot` and record observations
separately. The fixed historical image hash below is associated with the
reported visible Mu/no-OS result; it is **not** an exact hash binding for the
separate earlier Apple-logo UniXNU-menu observation.

1. fixed Mu-Silicium baseline reaches the reported visible Mu/no-OS stage;
2. a separately hash-bound image starts UniXNU and displays the unique
   menu-only FAT marker;
3. matching XNU payload shows DarwinBoot handoff evidence;
4. XNU reaches its first entry/console checkpoint;
5. storage adopts, root mounts, and only then launchd/userland stages are
   considered.

A black screen, `No Operating System Found`, or fastboot acceptance alone does
not advance these stages. No partition flash is part of this plan.
