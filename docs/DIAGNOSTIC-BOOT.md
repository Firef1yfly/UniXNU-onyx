# Round 14 firmware and diagnostic boot result

## Temporary firmware build

A 3.9 GiB temporary Mu-Silicium copy was used at `/tmp/onyx-uefi-shim`; the original `/home/firefly/UniXNU/Mu-Silicium` checkout remains clean. The candidate BootShim patch was applied only to the temporary copy. To resolve the prior GenFv error, only the temporary `onyx.dsc` changed `CLANGPDB:*_*_*_DLINK_FLAGS` from `/FILEALIGN:0x200` to `/FILEALIGN:0x1000`, matching the platform's 4 KiB PE alignment. No production file was changed.

Build command:

```sh
./unixnu build firmware -D /tmp/onyx-package-check \
  --uefi /tmp/onyx-uefi-shim \
  --edk2 /home/firefly/UniXNU/Mu-Silicium/Mu_Basecore \
  --skip-preflight -j 2
```

Result: success. New FD:

```text
/tmp/onyx-uefi-shim/Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd
size: 3145728 (0x300000)
sha256: 57a10bba078e8251ab05df795510ed8d0c4e7c86b4fcf34af2f60cb65b7dfc1e
```

This build skipped the vendor preflight deliberately in the temporary copy; it is not a production firmware qualification.

## Diagnostic boot image

Command:

```sh
./unixnu bootimg -D /tmp/onyx-package-check \
  --uefi /tmp/onyx-uefi-shim \
  --fd /tmp/onyx-uefi-shim/Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
  --dtb private-inputs/runtime-android17-20261114/runtime-full.dtb \
  --output /tmp/onyx-package-check/out/boot/boot.img
```

Result:

```text
path: /tmp/onyx-package-check/out/boot/boot.img
size: 4001792 bytes
sha256: 7a1e4e21017060dc3d7ddcc5b4b3df3fc08f3536088a57f6678d32a358f64ddb
header: Android v4
ramdisk: 0 bytes
shim: 112 bytes
runtime_dtb_sha256: 3b90da7e20c3bbde0e2663726e95ef66396260200aa2b2452fcb076d87794365
hardware_tested: false
```

`unpack_bootimg --format info` round-trips the image as Android header v4 with a zero-byte ramdisk. The image has **no XNU kernel and no UniXNU FAT payload**, so it is not expected to boot iOS or reach a UniXNU menu. It is a BootShim/UEFI diagnostic artifact only.

## Real-device result

The user tested this image once with `fastboot boot`. The phone accepted it, showed a black screen and required a long power-button hold before Android recovered. After recovery `sys.boot_completed=1`, `ro.boot.bootreason=reboot`, and slot `_b` was unchanged. No pstore console output was available. See [device diagnostic failure](DEVICE-DIAGNOSTIC-FAILURE.md).

This confirms only that the diagnostic artifact did not produce a visible UEFI result. It is not a UniXNU boot failure at the kernel stage because the image had no XNU kernel or payload, and it is not evidence that flashing is safe. Do not repeat it.

- No phone partition was written.
- No reboot, unlock, slot change or AVB change was performed.
- The connected device remains Android 17 on slot `_b`.
- Do not run this image expecting a complete OS boot. If later testing is approved, use `fastboot boot` only with recovery available and capture the serial/USB result; do not use `fastboot flash`.
