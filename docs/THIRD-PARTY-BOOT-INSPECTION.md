# Third-party Pictures/boot.img inspection

The user-supplied `/home/firefly/图片/boot.img` was inspected read-only.

```text
sha256: f2ca723993fa20f68a79e45d268443ce2b062f34a73bcc470717b2b953b74a9b
bytes: 1658880
header: Android v4
kernel field: gzip-compressed BootShim + firmware
ramdisk: 5 bytes, text "dummy"
```

The gzip stream decompresses to 3,145,840 bytes: 112-byte BootShim + 3 MiB firmware + 483,524-byte appended DTB. The BootShim ARM64 header reports FD base `0xa7100000` and image size `0x300000` (old BootShim behavior). The embedded DTB SHA-256 is `8127ab68f824743874ef2d42c2cf094b6fbbbb1490cb9a8749ff909968c052de` and identifies generic Tuna:

```text
model = Qualcomm Technologies, Inc. Tuna SoC
compatible = qcom,tuna
msm-id = <655 0x10000>
board-id = <0 0>
memory/reg = <0 0 0 0>
```

Thus this image is useful as an **offline provenance/reference sample**: it demonstrates a tiny 1.65 MiB Android v4 UEFI-only boot image with dummy ramdisk and old generic Tuna DTB. It is not suitable for the current onyx runtime: it has zero DRAM, no UniXNU payload, no XNU kernel, old board identity, old BootShim semantics, and its embedded firmware hash is not equal to either current local FD (`a7fb...` old build or `e31f...` map-exporter build). It must not be run or flashed.
