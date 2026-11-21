# Mu-first boot baseline and scope reset

The next construction must start from the exact local baseline that was reported to start Mu-Silicium UEFI:

```text
Mu commit: f77f9457b82f4a1dd33a305ab6ff12591347d416
FD: /home/firefly/UniXNU/Mu-Silicium/Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd
FD sha256: a7fbef72f78b7e5e4e14680cd6fe85429db866a0e16c5931208db4d53e69d20e
historical boot: /home/firefly/UniXNU/out/onyx/ios-17.7.11-21H461/example/boot/boot.img
boot sha256: f84337c7aa91436779844b6d86f8829d83461592e27edbbb7241378dba5985c2
```

The historical image is Android v4 with a 192 MiB FAT payload and the generic Tuna/zero-memory appended DTB. It is the only local artifact associated with the user's report that Mu-Silicium reaches UEFI/UniXNU integration. Current candidate images changed BootShim, DTB, APRIORI ordering, QR, and payload source simultaneously; they are not valid first-stage comparisons.

Scope reset:

1. Rebuild or reproduce Mu-Silicium UEFI alone from the pinned source/binaries and verify FD hash.
2. Use the historical boot image only as a byte/layout reference; do not assume its generic zero-memory DTB is safe for a new run.
3. Produce a Mu-only diagnostic image with no UniXNU changes if needed, then add UniXNU exactly as the user's tested repository does.
4. Only after Mu → UniXNU menu is stable, test config/FAT and then kernel/ADT.

The previously proposed `OnyxMapDxe`, QR, runtime-FDT replacement and ramdisk-first ordering are deferred until the Mu-first baseline is reproduced. No current black-screen candidate is considered a valid baseline.
