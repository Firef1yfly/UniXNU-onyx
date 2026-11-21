# Round 45 UniXNU menu failure and ramdisk-first firmware fix

The exact historical same-FD complete image was fastboot-accepted and launched UEFI, but the user reports no UniXNU menu. Source audit found APRIORI ordering in the tested onyx package:

```text
DiskIoDxe / PartitionDxe / FAT are APRIORI entries before UniXNURamDiskDxe
```

Because `UniXNURamDiskDxe` publishes the BlockIo handle from the runtime FDT initrd, FAT discovery can run before that handle exists. `UniXNU::Run()` explicitly calls `UniXNUConnectAll()` because the ramdisk may dispatch later, but the tested historical image still had no logs to prove the path.

A temporary APRIORI fix now orders:

```text
OnyxMapDxe
AdvancedLogDxe
UniXNURamDiskDxe
DiskIoDxe
PartitionDxe / Unicode / FAT
```

The temporary firmware rebuild succeeds:

```text
FD sha256: 8687f0ae5a33b8fb0edd07627aa220b2b9abe6e41d01bf3588c159dfb8432fc1
```

This is a targeted diagnostic ordering experiment, not yet a production patch. The current QR logger/OnyxMapDxe integration remains present. The exact test requires a complete payload, QR camera/OneSend capture, and a matching runtime FDT/BootShim combination. No device boot was run after this rebuild.
