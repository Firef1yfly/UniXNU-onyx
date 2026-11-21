# Isolated Mu-first BDS candidate build — round 65

The temporary Mu tree was restored to the exact tested f77f active source, then only these candidate changes were applied:

1. Board-local `OnyxBootOptions` PlatformBootOptionsLib provider;
2. PE `/FILEALIGN:0x1000` required by this host's GenFv (not a BDS logic change).

No BootShim x0 patch, QR, OnyxMapDxe, AdvancedLogger, APRIORI reorder, or ramdisk-first changes are present in this isolated tree. The temporary build succeeds:

```text
FD: /tmp/onyx-uefi-shim/Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd
sha256: 066d1a9427dab62e72c88094a3e9f4aae9478fa6ad76b4370e61eb82cbab6e58
```

The only tracked source diff in the temporary Mu Git tree is `onyx.dsc` (two lines added/one PE alignment line changed) plus the untracked provider source/INF. The candidate has not been device-tested; no device was connected during this build. It is now the correct isolated experiment for `No Operating System Found`.
