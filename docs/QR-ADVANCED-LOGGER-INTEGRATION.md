# QR Advanced Logger integration — round 39

UniXNU already ships the QR menu plugin `package/UniXNUPkg/Driver/AdvancedLogDxe/AdvancedLogDxe.inf` (OneSend frames, Tools menu). It consumes `gAdvancedLoggerProtocolGuid` from `AdvLoggerPkg` and needs `AdvancedLoggerAccessLib`, `QrEncoderLib` (already present in `Common/Mu/MsGraphicsPkg`) and the UniXNU menu plugin protocol.

A temporary onyx firmware build now integrates it. Changes live only in `/tmp/onyx-uefi-shim` and are captured as `patches/uefi/0002-onyx-qr-advanced-logger-diagnostic.patch`:

- `onyx.dsc`: adds `AdvancedLogDxe`, per-phase AdvancedLogger libraries (`DXE_CORE`, `DXE_DRIVER`, `UEFI_DRIVER`, `DXE_RUNTIME_DRIVER`, `UEFI_APPLICATION`), `QrEncoderLib`, `AdvancedLoggerHdwPortLibNull`, `AssertLib`, and `PcdUniXNUDeviceModel = "onyx"`.
- `SiliconPkg.dsc.inc`: maps `AdvancedLoggerAccessLib`, `QrEncoderLib`, `PcdAdvancedLoggerPages = 1024` (4 MiB reserved log buffer). The log buffer is allocated by the DxeCore AdvancedLogger constructor using `AllocateReservedPages`, so no fixed physical address is guessed.
- `onyx.fdf`: places `AdvancedLogDxe` and `OnyxMapDxe` into `FvMain`.
- `BootShim`: preserves bootloader x0 (candidate patch 0001), so the firmware receives the runtime FDT with the actual `fastboot boot` initrd addresses rather than the stale appended runtime FDT's Android initrd addresses.

Build result: success.

```text
FD: 3145728 bytes
sha256: 3e05e4c7e4b5022d43307a6f609d427dde1d5cb2ca166a27ad3aef3d9df9ba03
AdvancedLogDxe.efi: 49152 bytes
OnyxMapDxe.efi: 24576 bytes
FVMAIN.inf contains FFS 8D4E7F50-3A2C-4C9A-9E1B-50C4C8472D41AdvancedLogDxe
```

Still missing for a usable QR capture:

1. A payload whose generated menu contains `Tools` (`[payload] tools = true`), with a valid kernel/ADT or a menu-only payload.
2. Device test with a second camera running OneSend; QR cannot be captured from the same phone.
3. Verification that `AdvancedLogDxe` actually receives a non-empty log (`Advanced Logger: no log` would mean the DCE production path is inactive).

Do not reuse the earlier black-screen image. The likely additional defect found this round: the appended runtime FDT's `/chosen/linux,initrd-start/end` describe the current Android boot, not the `fastboot boot` payload. Using that appended DTB without preserving bootloader x0 would make `UniXNURamDiskDxe` read the wrong physical range; the temporary build uses the candidate BootShim x0 patch to avoid this.

Reproduce from the temporary tree:

```sh
git -C /tmp/onyx-uefi-shim apply UniXNU-onyx/patches/uefi/0001-*.patch
git -C /tmp/onyx-uefi-shim apply UniXNU-onyx/patches/uefi/0002-*.patch
./unixnu build firmware -D /tmp/onyx-package-map \
  --uefi /tmp/onyx-uefi-shim \
  --edk2 /home/firefly/UniXNU/Mu-Silicium/Mu_Basecore --skip-preflight -j 2
```
