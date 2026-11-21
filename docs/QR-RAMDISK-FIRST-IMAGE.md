# Ramdisk-first QR menu diagnostic image

The temporary Mu-Silicium firmware now has APRIORI order `OnyxMapDxe`, `AdvancedLogDxe`, `UniXNURamDiskDxe`, then DiskIo/Partition/FAT. Its FD SHA-256 is `8687f0ae5a33b8fb0edd07627aa220b2b9abe6e41d01bf3588c159dfb8432fc1`.

A new menu-only QR diagnostic image was assembled with the 64 MiB Tools payload and provisional zero-DRAM DTB:

```text
path: /tmp/onyx-qr-order-image/boot.img
bytes: 70266880
sha256: aefcc615e9697612e9934c40de6eeb9e840c3a8ae074a84047ff9d86268f2fae
header: Android v4
ramdisk: 67108864
fd: 8687f0ae5a33b8fb0edd07627aa220b2b9abe6e41d01bf3588c159dfb8432fc1
DTB: 53c6dee14db92effc6a638a801027b08bdf3496486d5b630ebe38c4ed732b2e5
```

This image is for testing menu/QR and ramdisk dispatch only. It contains no XNU kernel, no ADT and no real DRAM input; do not use it to validate iOS or root. Device was offline during assembly; no fastboot boot occurred.
