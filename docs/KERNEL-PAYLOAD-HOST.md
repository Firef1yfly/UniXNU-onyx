# Round 17 kernel and payload host results

## 4 KiB reference

The official UniXNU checks were run against the assembled temporary tree:

- `check-xnu-granules.py`: BCM2837 4096-byte control passes (`TCR_EL1_BOOT=0x22a51a251a`, TG0=0/TG1=2); VMAPPLE 16 KiB control passes.
- `check-native-4k-policy.py`: five RAM boundaries pass for native 4K, Apple 4K and Apple 16K controls.
- `check-code-signing-granules.py`: eight extracted code-signing gate cases pass after the Linux-only generated-probe fallback defines Darwin `EBADEXEC=85`. This only changes the host probe, not XNU.

The 4 KiB kernel granule and EDK2 PE alignment are separate concerns: XNU page tables use 4 KiB, while the earlier DiskIoDxe fix uses PE FileAlignment 0x1000.

## Full kernel and package success

With the corrected `zzz-boot-progress.patch` (only the unselected Sheng PMGR diagnostic hunk removed), all 59 selected XNU patches apply. Local cached DriverKit/TrustCache manifests restore 26 headers with Git blob hash checks. The kernel build then completed:

```text
kernel.macho sha256 6954c1b2b61802fc4df17564d07a3ad090bca46d6cc23e1dcc20d9cc528b3f70
```

Package build completed and produced the onyx EFI modules under the temporary output tree, including `UniXNU.efi` and `UniXNURamDiskDxe.efi`.

## Payload pipeline test (synthetic only)

The first payload attempt correctly rejected the board's zero DRAM:

```text
ADT handoff requires nonempty DRAM within the 64-bit address space
```

For a **host-only pipeline test**, a temporary copy's `memory@0` was replaced with synthetic `<0 0x80000000 0 0x40000000>`, and a runtime-derived platform seed was supplied. Payload assembly then succeeded:

```text
payload.img: 192 MiB
sha256: 2b5efc601e617382243f93127ba1a4a14e48239fd77dc82abe61b8fdffebba2b
```

This payload is explicitly **not a device artifact**: the 1 GiB RAM range is invented test data, and the current Android runtime has fragmented ranges plus reservations. Do not pass this payload or its synthetic hardware DTB to fastboot. The official device DTS remains zero-protected.

No phone operation occurred during kernel/package/payload builds. Full host tests and porting record checks remain required before any future real-image assembly.
