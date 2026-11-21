From 7b730b2 (onyx BDS candidate)

This patch is dormant. It is not applied to the original Mu-Silicium tree,
and is not a claim that BDS registration is the cause of any prior black
screen or `No Operating System Found` result.

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
