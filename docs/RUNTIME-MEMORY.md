# Runtime memory evidence checklist

No current-device connection was available in the host discovery check. This document is a collection plan, **not evidence of a completed capture**. The existing image DTBs are static, even after offline overlay application. Do not relabel them runtime or change `inputs.toml` to claim that.

## What to obtain from the running stock system

Use a device/permission state already available to you. Do not unlock, flash a recovery, root, reboot or change partitions merely to run these commands. Read-only capture may still contain identifiers; store it under ignored `private-inputs/` and do not publish it wholesale.

If a normally authorized adb connection is available, the following are read-only examples; **they have not been executed against a phone in this session**:

```sh
adb shell getprop ro.product.device
adb shell getprop ro.build.fingerprint
adb shell getprop ro.build.version.release
adb shell getprop ro.build.version.sdk
adb shell getprop ro.boot.hardware.sku
# Local output path: create a new private evidence directory first.
adb exec-out cat /sys/firmware/fdt > private-inputs/runtime-capture/runtime.dtb
```

The FDT path can be absent or permission-denied. If so, stop and record the actual failure; do not call the empty host output file a DTB and do not assume adb root is available. `/proc/iomem` can be restricted/redacted and is only supporting evidence, not a substitute for a complete unredacted FDT or EFI map. Board source and marketing RAM capacity are not runtime observations.

The offline checker rejects truncated/zero/malformed ranges and reports board identity ambiguity:

```sh
python3 scripts/inspect-memory.py \
  --dtb private-inputs/runtime-capture/runtime.dtb --unixnu ../unixnu --json
```

The analyzer writes no files by itself and performs no network/device operation. `memory_complete=true` means **structural** completeness only, not provenance, a ready ADT, or safe memory. Multiple banks are reported, never silently merged or cropped. Disabled banks and static/dynamic reservations are reported separately. A generic Tuna model alone does not confirm onyx, so capture the device properties as an independent cross-check. `runtime_source_verified`, `hardware_tested` and `safe_to_boot` remain false.

## Why the runtime FDT alone is insufficient

- Android's live map is not automatically the same as the custom UEFI's map.
- Runtime DRAM can consist of several banks; the current ADT expects a single explicitly justified contiguous handoff range.
- Reserved memory, secure/firmware ownership, splash, allocator ranges and initrd/FDT retention must agree with UEFI descriptors.
- A nonzero memory property cannot establish that every page is available to XNU.

Follow the [UEFI handoff audit](UEFI-HANDOFF.md): obtain firmware x0/FDT/initrd addresses, RAM-partition output and EFI descriptors before changing board DRAM. Keep `board.example=true` until these gaps and the full build chain are resolved.
