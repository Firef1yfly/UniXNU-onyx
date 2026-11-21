# EFI memory-map investigation — round 19

The current Mu-Silicium source already contains Qualcomm RAM and EFI map logic:

- `Silicon/Qualcomm/QcomPkg/Library/RamManagerLib/RamManager.c` obtains `EFI_RAMPARTITION_PROTOCOL` and converts vendor `Base`/`AvailableLength` entries into usable ranges.
- `Silicon/Silicium/SiliciumPkg/Drivers/RamManagerDxe/RamManager.c` obtains `GetMemoryMap()`, sorts descriptors and maps gaps as conventional memory.
- The generic Mu_Basecore Shell `memmap` command (`ShellPkg/Library/UefiShellDebug1CommandsLib/MemMap.c:359-385`) can print a live EFI memory map, but the onyx FDF does not currently include the shell package/driver. No existing onyx source path exports the map through the UniXNU menu or payload.

The safe next diagnostic design is therefore a temporary firmware-only memory-map exporter, or a temporary ShellPkg inclusion, that emits descriptors and RAM-partition entries over the existing serial/QR log path **before** UniXNU/DarwinBoot changes ownership. It must not be replaced by Linux `/proc/iomem` or Android FDT ranges. No source was changed this round and no firmware was rebuilt.

## Prepared temporary exporter (round 22)

The device repository now contains an unintegrated diagnostic module under `package/OnyxMapDxe/`:

- `OnyxMapDxe.c` calls `GetMemoryMap()` and prints each descriptor's type/base/page count/attributes.
- It locates `EFI_RAMPARTITION_PROTOCOL`, prints the partition count and every `Base/AvailableLength` pair.
- It performs no protocol installation, HOB writes, memory mapping or Conventional Memory changes.
- `OnyxMapDxe.inf` declares only the required MdePkg/Qualcomm protocol dependencies and a `TRUE` DEPEX.

The exporter source has been hardened before integration: bounded EFI-map retries, descriptor stride/byte limits, range overflow checks, partition count cap, UINT32 count preservation, and explicit acknowledgement that temporary pool allocations perturb the observed map. It still does not implement the final handoff reservation contract.

## Round 24 build result

The host quota recovered after the failed duplicate copy. Existing `/tmp/onyx-uefi-shim` was reused, `OnyxMapDxe` was added to its temporary onyx DSC/FDF, and the firmware build succeeded. FD SHA-256: `e31f5dbd540411db1ce92af941693fc0ad2710b53ca7ca799d2d08f8b639b5e6`. `OnyxMapDxe.efi` is present in EDK2 outputs. Full result: [EFI map build report](EFI-MEMORY-MAP-BUILD.md).

The FD has not been packed or booted. The next step is to place a complete payload and test this exact diagnostic combination only with `fastboot boot`, capturing serial/QR `ONYXMAP` lines; do not flash it.



