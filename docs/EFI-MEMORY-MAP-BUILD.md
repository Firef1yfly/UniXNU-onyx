# Round 28/32 EFI-map diagnostic build and device result

The tested temporary Mu-Silicium checkout remains available at `/tmp/onyx-uefi-shim`, with OnyxMapDxe integrated into its onyx DSC/FDF. FD SHA-256: `e31f5dbd540411db1ce92af941693fc0ad2710b53ca7ca799d2d08f8b639b5e6`.

A diagnostic image was assembled using that FD, the current runtime FDT and a historical 192 MiB payload. It was sent with `fastboot boot`; transfer and boot both returned `OKAY`, but the phone black-screened. No serial/QR `ONYXMAP` output was captured. The user recovered Android manually. KernelSU then reported `ro.boot.bootreason=shutdown,userrequested` and `sys.boot_completed=1`; pstore had no firmware/kernel console output. Full details: [EFI map diagnostic result](EFI-MAP-DIAGNOSTIC-RESULT.md).

This historical-payload/current-FDT combination cannot localize the black screen to EFI map, UniXNU menu, DarwinBoot, XNU or root. Do not repeat it without a serial/QR capture path. No partition was flashed.
