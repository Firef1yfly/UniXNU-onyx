## Android 17 ramdisk baseline

The current Android 17 image archive contains a single vendor ramdisk component. It is LZ4-compressed Android vendor content, not UniXNU's Mu-Silicium FAT payload. The archive's vendor boot and DTB offsets are recorded in [CURRENT-ANDROID17.md](CURRENT-ANDROID17.md). This round only used `unpack_bootimg --format info` and bounded byte inspection; no decompression package was installed.

A UniXNU image still needs the payload path described by the Mu-Silicium handoff: runtime FDT `/chosen/linux,initrd-start` and `linux,initrd-end`, followed by `UniXNURamDiskDxe` publishing a Block I/O device and FAT discovering `EFI/UniXNU/unixnu.toml`. The existence of Android's compressed vendor ramdisk does not supply those properties or prove that Mu-Silicium can consume it.

Do not force the appended static DTB when the runtime x0 FDT is missing or lacks initrd properties. Record that as an explicit handoff failure until a reviewed firmware path converts/preserves the actual payload and owns its pages.
