# Firef1yfly Mu-Silicium onyx package audit

The linked directory is useful and is the strongest source for the board's tested firmware integration. Local active source files were compared with `origin/main` commit `664c841260773a369f758d7a27baa3494a59827f`; hashes are identical for:

- `Platforms/Xiaomi/onyxPkg/onyx.dsc`
- `Platforms/Xiaomi/onyxPkg/onyx.fdf`
- `Resources/Configs/onyx.toml`
- `BootShim/BootShim.S`
- `Silicon/Silicium/SiliciumPkg/Sec/Sec.c`

The local HEAD `f77f9457b82f4a1dd33a305ab6ff12591347d416` adds backup files, while the active source content remains the public main content. The package provides concrete onyx integration:

- FD base `0xA7100000`, size `0x300000`, Android boot header v4, no kernel compression, appended DTB;
- UniXNURamDiskDxe, UniXNUDxe, UniXNU application, DarwinBoot, DiskIo, Partition, UnicodeCollation and FAT in the DSC/FDF;
- Qualcomm/Silicium RamManagerDxe;
- onyx vendor binaries and patched drivers;
- onyx framebuffer model values and memory-map library.

This explains how the maintainer could reach `EFI/UniXNU` with a FAT payload. It does **not** by itself solve current payload qualification:

1. Active BootShim forces the appended static DTB and writes only a fixed `FD_SIZE` image-size field; our candidate temporary patch differs.
2. Active DSC uses `/FILEALIGN:0x200`; the temporary current build required `/FILEALIGN:0x1000` to pass GenFv PE rebasing.
3. Active DSC/FDF has no `AdvancedLogDxe`, AdvancedLogger producer, or QR Tools integration; UniXNU's QR plugin needs those dependencies and `[payload] tools = true`.
4. The package's static MemoryMapLib is not the runtime EFI map; the temporary `OnyxMapDxe` is still needed to export EFI descriptors/RAM partitions.

Therefore this link is useful as the **baseline tested firmware integration**, but future boot tests must record any deviation from this exact source combination and build hashes. Do not mix its old static DTB or old BootShim with the current runtime FDT without a deliberate experiment.
