# Round 58 BDS candidate offline verification

`/tmp/onyx-bds-candidate-image/boot.img` was unpacked and audited without a device. The image contains:

```text
Android v4
kernel bytes: 4025153 (raw BootShim + 3 MiB FD + appended DTB)
ramdisk bytes: 201326592
ramdisk sha256: be6aeabf340f604868c5093966729dc0b75b28233a70cd34266c0f01dd108 [historical FAT payload]
embedded DTB sha256: 6379d64c8472c7c4c2d9d225803bebe33b8bd2c14cb73c6b329a8a5458dd6f23
```

The FAT listing confirms `EFI/UniXNU/Payloads/kernel.macho` and `kernel.macho.adt`, plus the 330-byte menu config. The candidate FD hash is `7910f75c3cbbcd3db12d90a6208a6a6edb6e65e920898656900aa8235d6775ea`, while the overall boot image hash is `e63db8864ef0d51027da07c6a7fd0d48a1cd7b54b0aaadc1683a93e65ad5a2cd`.

This remains a Mu-first BDS experiment: historical DTB/payload plus the new active-Boot option FD. It has not been started on a device. The current device is not connected; no fastboot operation occurred in this round.
