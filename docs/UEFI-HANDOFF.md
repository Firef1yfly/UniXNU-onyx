# UEFI handoff audit — local source, not a boot result

Reviewed Mu-Silicium at `f77f9457b82f4a1dd33a305ab6ff12591347d416` in `/home/firefly/UniXNU/Mu-Silicium`. The source checkout remains unchanged. Current device image baseline is the [Android 17 archive](CURRENT-ANDROID17.md).

## Confirmed host build failures and candidate fixes

### ARM64 BootShim header

The original `BootShim/BootShim.S` writes only `FD_SIZE` to the ARM64 image-size field. UniXNU `scripts/unixnu/bootimg.py:24-40` requires `len(shim) + FD_SIZE`.

A direct call to `compile_shim()` with the actual onyx source, FD base `0xa7100000`, size `0x300000`, and `requires_header=True` reproduced:

```text
CONFIRMED HOST FAILURE: the ARM64 image header does not describe the shim plus the firmware volume
```

The [candidate BootShim patch](../patches/uefi/0001-bootshim-preserve-runtime-fdt-and-size.patch) changes the field to `FD_SIZE + (_Payload - _Head)`. It also addresses the runtime FDT issue below. `git apply --check` passes against the original checkout. Applying it **only in a temporary copy** produced:

```text
header=True: shim_bytes=112, image_size=0x300070
sha256=9346a527441b242c69414fd7e3d6fa17813f281d562fef13d9ba8373d39007a9
header=False: shim_bytes=64
sha256=e6f4736c394763238d86f0e9b2d43aeeb2eb64436d102213941adc5ed7db2e6c
```

Both calls to the real `compile_shim()` passed. These hashes describe a small host-compiled shim, **not a usable firmware or boot image**. The regression test also checks compiled executable disassembly for absence of x0 modification.

### Compression configuration

Mu `Resources/Configs/onyx.toml:17-19` declares `kernel_compression="none"` under `[boot_image_kernel]`. The current UniXNU packer reads `[boot_image]` plus `[bootimg.image]` instead and otherwise defaults to gzip at `bootimg.py:101`.

The device now explicitly sets `[bootimg.image] kernel_compression="none"` to match this onyx firmware source. The board stays `example=true`; this is not permission to boot or evidence that ABL accepts this packing.

## Historical exact-combo device result

The historical local boot image whose FD matched the tested Mu-Silicium build was accepted by fastboot and launched UEFI, but the user reports that it did not enter the UniXNU interface. The phone later recovered to Android. This narrows the next source investigation to UniXNU application registration, ramdisk BlockIo/FAT dispatch ordering, and config discovery. See [historical combo test](HISTORICAL-COMBO-BOOT-TEST.md).



The maintainer reports that `Firef1yfly/Mu-Silicium` files have been tested on onyx to reach the UniXNU directory. Local source evidence and the detailed caveat are recorded in [tested Mu-Silicium provenance](TESTED-MUSILICIUM-PROVENANCE.md). This validates the general firmware/payload filesystem integration path, but not the exact candidate BootShim patch, current kernel/payload combination, or a complete iOS boot.



The existing shim at `BootShim.S:19-24` unconditionally replaces bootloader x0 with the appended static FDT. This behavior was introduced by local commit `17467319c119bc6c75ac1abe3fb695aaca92143e`. That commit's explanation asserts a fastboot/GKI initrd problem, but no corresponding device log has been verified in this reconstruction.

Replacing the runtime FDT discards whatever memory, chosen/initrd and other fixups the bootloader actually supplied. Appended trees from both provided stock versions contain zero DRAM; static appended data cannot be presumed to contain current initrd addresses either. The candidate patch restores preservation of x0 instead of silently selecting stale static data. Missing initrd must remain an explicit diagnostic failure, not be hidden by that substitution.

**Preserving the pointer does not preserve the content.** SEC `Silicon/Silicium/SiliciumPkg/Sec/Sec.c:123-130` initializes the static MMU/HOB map before storing the x0 pointer in a GUID HOB. No FDT/initrd range copy or explicit allocation/reservation is made there. The current RAM-disk driver reads the HOB, FDT and initrd later; it does not establish allocation ownership of these bytes. Actual addresses may lie outside the initial static mapping, overlap an allocator's free region, or be reused during RAM expansion. These remain unresolved, so the patch is a source/host-tested candidate, **not a complete handoff fix**.

Do not install this patch as an automatic build step yet. UniXNU `[firmware] patches` applies to the EDK2 checkout, not the Mu platform tree (`firmware.py:59-64`); listing this Mu patch there would target the wrong repository. The original firmware source has not been modified.

## RAM source: not only the static table

The platform's `MemoryMapLib` is an initial reservation/MMIO/DXE-heap table, not measured whole-device RAM. Qualcomm's `QcomPkg/Library/RamManagerLib/RamManager.c:56-78` locates `EFI_RAMPARTITION_PROTOCOL` and obtains runtime partition entries; lines 31-35 transfer `Base`/`AvailableLength` into usable ranges. The protocol provider is vendor code; its actual returned data has not been captured.

`SiliciumPkg/Drivers/RamManagerDxe/RamManager.c:197-217` obtains the EFI map and RAM ranges, sorts them, and maps unlisted gaps as conventional memory via `ParseMemoryRange()`/`HandleRamRange()`. Thus there is a runtime RAM-expansion path. It is wrong either to equate the static table with total RAM or to assume this expansion automatically excludes bootloader FDT/initrd buffers: their reservations still must be explicit and verified.

## Firmware volumes and dispatch ordering

The FD contains `FVMAIN_COMPACT`, which embeds a compressed `FvMain`. UniXNU/RAM-disk/DarwinBoot are in inner `FvMain` (`onyx.fdf:82-90`). DiskIo/Partition/Unicode/FAT are **not missing**: they appear both in inner `Include/DXE.inc:40-44` and again in the outer volume (`onyx.fdf:142-145`). SEC/PrePi expose both firmware volumes to DXE, so their placement alone does not prove that they fail to load. There is also no source evidence that they actually dispatched on this phone.

The inner APRIORI list includes DiskIo/Partition/FAT (`Include/APRIORI.inc:45-52`) but not `UniXNURamDiskDxe`, DarwinBoot or RamManager. A `TRUE` DEPEX or earlier textual FDF position does not force the RAM-disk driver to run before APRIORI. DXE APRIORI ordering is scoped to the same firmware volume; duplicated drivers in the outer FV are not ordered by the inner list. A future reviewed patch should remove the duplicate outer disk stack and explicitly order RAM-disk publication before filesystem discovery **after** early FDT/initrd ownership is fixed. Ordering alone cannot repair overwritten/unmapped source buffers.

The current Android 17 `vendor_boot.img` contains one 37,688,236-byte LZ4-compressed vendor ramdisk, followed immediately by its DTB section; see [Android 17 ramdisk evidence](ANDROID17-RAMDISK.md). This is Android vendor content, not proof of a Mu-Silicium FAT initrd or `linux,initrd-start/end` runtime handoff.

## Allocator-preservation follow-up

The host-tested [C handoff planner](../package/HandoffPlan/README.md) now checks ranges and generates page-aligned retention spans, but performs no physical reads, allocations, mappings or HOB writes. It is not selected by any INF. It cannot protect an earlier BootShim FD copy or assembly stack clear when called later from C.

The PrePi page allocator (`Mu_Basecore/EmbeddedPkg/Library/PrePiMemoryAllocationLib/MemoryAllocationLib.c:29-83`) only moves the PHIT free top, while pool allocation creates growing HOB records; `BuildMemoryAllocationHob` merely describes a range and does not exclude it from that allocator. Thus a real integration must select a disjoint verified PrePi arena before `HobConstructor`, or implement real exclusion-aware allocation. Publishing an allocation HOB after constructing an overlapping free arena does not solve this issue. The planner intentionally treats caller-specified arena/write footprints as forbidden instead of automatically cropping RAM.

The device payload setting is 192 MiB. No actual payload file has been built, so do not claim its final size is 192 or 193 MiB. The static DXE heap is `0xBAE40000..0xD8000000` (465.75 MiB), but arithmetic capacity is not proof that a contiguous allocation is free after decompression and drivers. Allocation, mapping, source-buffer retention and final EFI descriptors must be measured together rather than choosing an address from this table.

## Required next measurements and implementation

1. Obtain a current-device runtime FDT (not a DTB extracted from an image) and record capture provenance/hash plus Android build information separately.
2. Capture the UEFI x0 address, FDT total size, initrd range, actual EFI memory descriptors and RAM-partition results. Confirm all pages have a defined owner before the allocator/RAM expansion can reuse them.
3. Implement early FDT/initrd mapping and preservation using those constraints, including overflow/bounds checks. Do not guess physical addresses or call static reservation metadata proof of safety.
4. Diagnose the GKI/fastboot ramdisk path using current-device logs. A missing `/chosen/linux,initrd-*` must stop payload discovery rather than fabricate a successful path.
5. Only then rebuild the real firmware and payload; verify dispatch and actual handoff on the device. Neither the old firmware nor the candidate patch has a verified real-device boot result here.
