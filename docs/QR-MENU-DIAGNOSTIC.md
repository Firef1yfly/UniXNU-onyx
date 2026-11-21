# QR menu-only diagnostic boot artifact

A menu-only payload was built with mtools; it contains no kernel, no ADT and no DRAM handoff:

```text
payload: /tmp/onyx-menu-payload.img
bytes: 67108864 (64 MiB)
sha256: 7ed3c6d3f3b5d0345118d2bf8eca22c0f7d08db798a74ebcf5356bdb29133f43
FAT volume: ONYX
EFI/UniXNU/unixnu.toml: Tools, Restart, Power off
```

The QR-enabled temporary FD and assembled Android v4 boot image are:

```text
FD sha256:   3e05e4c7e4b5022d43307a6f609d427dde1d5cb2ca166a27ad3aef3d9df9ba03
boot sha256: ad93ad4f484456439ff7d2dbaafb2ed62409167b85b2ed177a8df69fae6777b6
boot bytes:  70266880
ramdisk:     67108864
DTB sha256:  53c6dee14db92effc6a638a801027b08bdf3496486d5b630ebe38c4ed732b2e5  [host provisional DTB]
```

The host provisional DTB used for this menu-only image intentionally has zero DRAM and is not an iOS boot input. The image's only purpose is to test whether the QR Tools menu can be displayed by the firmware; it must not be treated as a kernel or root boot. The device was not connected during this check, so no `fastboot boot` was run.

Before a future test, prepare a second camera/OneSend scanner and capture QR frames. Do not repeat the image without a recovery plan, because previous mixed diagnostic images black-screened without logs.

## Image-internal verification

The unpacked kernel field is a raw ARM64 image:

```text
text_offset: 0xa7100000
image_size:  0x300070  (112-byte shim + 0x300000 firmware)
magic:       ARMd
shim sha256: 9346a527441b242c69414fd7e3d6fa17813f281d562fef13d9ba8373d39007a9
embedded FD sha256: 3e05e4c7e4b5022d43307a6f609d427dde1d5cb2ca166a27ad3aef3d9df9ba03
appended DTB sha256: 53c6dee14db92effc6a638a801027b08bdf3496486d5b630ebe38c4ed732b2e5
```

This confirms the candidate BootShim size fix is present (image_size includes the shim) and the QR-enabling firmware is the FD recorded above. The shim also comes from patch 0001, which preserves bootloader x0, so the firmware should use the bootloader-patched DTB carrying the actual `fastboot boot` initrd range instead of stale Android initrd addresses.

## Firmware volume contents

`FVMAIN.inf` lists 110 FFS files, including the required chain:

```text
8D4E7F50-3A2C-4C9A-9E1B-50C4C8472D41AdvancedLogDxe
4A0D0F2B-72C1-42F1-9B62-22EE8B33A3A1OnyxMapDxe
75CA63AD-FBAE-4A06-92A0-F937C671251DUniXNURamDiskDxe
29B950CF-586D-49EA-9D71-F88645CCDAF6UniXNU
1B64AF87-8415-4B57-9B16-680D70913B9FDarwinBoot
```

`AdvancedLogDxe` registers the `Advanced Logger` menu plugin as soon as its depex (`gAdvancedLoggerProtocolGuid`, installed by the DXE-core Advanced Logger constructor) is satisfied. The menu-only payload then exposes Tools; OnyxMapDxe's `ONYXMAP:` lines are captured into the 4 MiB Advanced Logger buffer.

## Device test checklist (pending phone connection)

1. Phone in fastboot: `fastboot devices -l` shows serial.
2. Second camera phone has OneSend receiver ready.
3. `fastboot boot /tmp/onyx-qr-image/boot.img` (never `flash`).
4. Expect UniXNU menu with `Tools`; select Tools → `Advanced Logger`.
5. Scan the rotating QR frames; wait for completion and save the log.
6. Verify the log contains `ONYXMAP: EFI begin` and `ONYXMAP: RAM begin` entries.
7. If the screen is inactive or the menu is absent, recover with a long power press and record the observation; do not retry blindly.
