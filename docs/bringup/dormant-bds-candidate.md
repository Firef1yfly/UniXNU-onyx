From 7b730b2 (onyx BDS candidate)

This patch is dormant. It is not applied to the original Mu-Silicium tree,
and is not a claim that BDS registration is the cause of any prior black
screen or `No Operating System Found` result.

Series status (2026-11-28): the candidate is withdrawn from the patch series.
`patches/uefi/0003-onyx-bds-platform-option.patch` was removed because
`onyxPkg/OnyxBootOptions.c/.inf` and the `PlatformBootOptionsLib` binding never
landed in the Mu tree, and because the approach still needs the application
volume's device path - the exact thing that is missing when registration is
untrustworthy. The boot path is hardened elsewhere: patch 0012 makes
`UniXNUDxe` fall back to `LoadImage`/`StartImage` from the volume, and
`Tests/OnyxBootPath` covers it on the host. Landing this candidate now would
add a second boot-option provider without a test that shows the existing path
failing at a known stage.

The candidate replaces only the onyx DSC `PlatformBootOptionsLib` mapping and
adds the board-local provider source/INF. It does **not** add the provider as
a `[Components]` entry or an FDF/FFS, and it does not change BootShim, APRIORI,
FDF, display, memory, or QR code paths.

The provider follows Mu's actual `EFI_PLATFORM_BOOT_OPTION` ABI: it allocates
two entries, preserves Qualcomm's hidden Mass Storage option, adds an active
UniXNU application entry using the fixed PCD GUID, and publishes only after
both PCD pointers are available. NULL output pointers, allocation failure, and
partial PCD failure return zero options; partial failure frees the temporary
array. The host test compiles this C against a mock of the same ABI and covers
these paths.

To apply manually to an isolated Mu source tree, the patch's intended source
layout is:

```text
Platforms/Xiaomi/onyxPkg/onyx.dsc
Platforms/Xiaomi/onyxPkg/OnyxBootOptions.c
Platforms/Xiaomi/onyxPkg/OnyxBootOptions.inf
```

The real Mu tree must be reviewed and the resulting FD must be separately
hash-bound before any device test. Task-5 Mu/menu evidence is a prerequisite;
this candidate remains disabled until the existing registration path is shown
to fail with a controlled, stage-specific observation. A host test or FD build
does not establish BDS execution, `StartImage`, GOP/ConOut, or a root cause.
