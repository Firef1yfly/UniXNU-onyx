# Round 30 diagnostic boot preparation

A boot image was assembled using:

- temporary FD with `OnyxMapDxe`, SHA-256 `e31f5dbd540411db1ce92af941693fc0ad2710b53ca7ca799d2d08f8b639b5e6`;
- current runtime FDT, SHA-256 `3b90da7e20c3bbde0e2663726e95ef66396260200aa2b2452fcb076d87794365`;
- a historical 192 MiB FAT payload whose source checkout differs from the current kernel build.

Diagnostic image:

```text
/tmp/onyx-package-map/out/boot/boot.img
bytes: 205328384
sha256: 160385afda0ca2a60b1871fafc9091ca2f790231c42e84eb29d02e77ab775c91
header: Android v4
ramdisk: 201326592 bytes
```

This image is for EFI-map diagnostics only, not a fully provenance-matched UniXNU release image. It has not been started.

The phone is now in fastboot mode and read-only `getvar` checks succeed:

```text
product: onyx
current-slot: b
unlocked: yes
slot-count: 2
```

`fastboot devices -l` enumerates serial `5d7b86fd` on USB `2-10`. No `fastboot boot` command was run in this round. Before doing so, retain recovery and capture the `ONYXMAP:` output over the available serial/QR path; a boot without log capture would not provide the required EFI evidence.
