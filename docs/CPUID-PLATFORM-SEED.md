# CPUID / platform seed audit — round 48

The Android runtime reports:

```text
androidboot.cpuid = 0x0000046c7b3a6387
androidboot.hardware.sku = onyx
androidboot.serialno = 5d7b86fd
androidboot.dtbo_idx = 0
androidboot.dtb_idx = 0
```

The `cpuid` value is a useful runtime observation and can be passed as the temporary UniXNU ADT platform seed (`--unique-chip-id 0x0000046c7b3a6387`) for host generation. It must not be committed to `board.toml` or treated as a public secret/firmware PCD. The current checked-in board deliberately keeps `unique_chip_id = "required"`; this is correct.

The Mu-Silicium onyx firmware sources do **not** consume this Android cpuid as a build-time PCD. The UEFI build config uses FD base/size, device model, framebuffer and vendor binaries. The platform seed is injected by UniXNU payload/ADT generation, not by the UEFI compilation step. Therefore the previous UEFI build was not missing a cpuid parameter; the missing real input is the ADT DRAM/EFI map and the seed must be supplied only at payload build time.

The QR/ramdisk-first menu diagnostic black-screened before a useful log, and the phone recovered to Android. Do not repeat until capture is available. Current device is online in Android after recovery.
