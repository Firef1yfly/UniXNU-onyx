# Menu-only FAT probe

This artifact is an **offline diagnostic input** for a UniXNU application that
has already been started by UEFI. It is not a firmware image and is not an OS
payload. The FAT contains only:

```text
EFI/
  UniXNU/
    unixnu.toml
```

The generated configuration has:

- `version = 1`;
- `timeout = -1`;
- `fallback_timeout = 86400` (24 hours);
- explicit `[kits] autoload = false`;
- unique default `probe`, whose marker title is `MENU_ONLY_PROBE` and action is
  `tools`;
- `restart` and `shutdown` actions;
- no `path`, `initrd`, `dtb`, driver, kit entry, kext, ACPI, block slice, kernel,
  DarwinBoot, root filesystem, or device-tree file.

The marker title is an ASCII-only value that can be found in a menu photograph
or in a later FAT readback. It is deliberately not an entry payload.

## Why timeout is negative

The source implementation in
`/home/firefly/UniXNU/package/UniXNUPkg/Library/UniXNULib/Menu.c` treats
`timeout = 0` as `RemainingMs == 0`, then immediately returns the default entry
(lines 152–155). It is therefore an **auto-start setting**, not “disable
automatic startup”. The generator rejects zero, and
`tests/test_menu_probe.py` keeps zero as a negative test case.

For `timeout = -1`, UniXNU waits for a key when a physical input device is
present. When no physical input device exists, `Menu.c` substitutes
`fallback_timeout` (lines 114–125); the probe uses 86400 seconds rather than
claiming an infinite wait. This behavior is also documented in
`/home/firefly/UniXNU/docs/reference/boot-configuration.md` (lines 287–295).

## Default action behavior

`tools` is an action, so `Boot.c` does not attempt to load a kernel or an EFI
image. `MenuRunTools` returns when the UI is not graphics or when no usable
menu-plugin protocol is installed (`Menu.c`, lines 291–310). Main then returns
to its menu loop (`Main.c`, lines 149–168). Thus the probe cannot select XNU,
Linux, EFI, DarwinBoot, or a file-backed payload. If no input is present, the
24-hour fallback selects `tools`; with no plugin, it returns and the menu is
shown again. This is intentionally non-destructive: it does not reset,
shutdown, or start an OS.

A GOP or text `ConOut` is still required for visible output. `Ui.c` chooses GOP
first and text-console fallback second (lines 647–699). Without either, the
application can remain in its headless/log-only loop and no visible menu can
be claimed.

## FAT geometry and Mu compatibility

Mu `EnhancedFatDxe/Init.c:392-395` rejects FAT32 volumes whose computed
`MaxCluster` is below `FAT_MAX_FAT16_CLUSTER` (`0xFFF5`, 65525). A forced
16 MiB FAT32 image has only 32232 clusters at one sector per cluster and is
therefore rejected by this tool, even though mtools can create and read it.
The old `menu-only.img` remains untouched as negative evidence.

The valid artifact uses 64 MiB, 512-byte sectors, and one sector per cluster:

```text
FAT32; total clusters 129022; MaxCluster >= 65525
```

The generator parses the BPB before and after writing, applies the Mu minimum
cluster rule, and reports sector/cluster geometry. It supports other power-of-
two sectors-per-cluster values, but the default is the 64 MiB / 1-sector
geometry above.

## Build and verification

From the workspace root:

```sh
python3 UniXNU-onyx/scripts/make-menu-probe.py \
  --output UniXNU-onyx/out/onyx-bringup/menu-fat/menu-only-fat32-64m.img \
  --size-mib 64 --sectors-per-cluster 1 --timeout -1
python3 UniXNU-onyx/scripts/make-menu-probe.py --verify \
  --output UniXNU-onyx/out/onyx-bringup/menu-fat/menu-only-fat32-64m.img
python3 -m unittest UniXNU-onyx.tests.test_menu_probe -v
```

The valid generated artifact in this workspace is:

```text
size: 64 MiB (67108864 bytes)
geometry: FAT32, 512-byte sectors, 1 sector/cluster, 129022 clusters
sha256: 6cd92831a9b2a48d5e9e73bf509443546e70ad7d27296b1558c29230857999d8
menu text bytes: 394
```

The previous 16 MiB artifact is retained unchanged for the negative check:

```text
menu-only.img sha256: 6e9cc29c2d9c6d00078aa707b769552e2410e21e18122bd12f9f494689fd8ed3
verification: rejected (`FAT32 has 32232 clusters; Mu requires at least 65525`)
```

The host tests cover:

1. `timeout = 0` is rejected and modeled as immediate default selection;
2. `timeout = -1` waits with input and uses the long fallback without input;
3. the TOML parses as version 1, explicitly disables kit autoload, and resolves
   the default uniquely to the marker `tools` action;
4. the valid FAT file round-trips byte-for-byte through `mcopy`/`mtype`;
5. BPB geometry is checked against Mu's FAT32 minimum;
6. forced 16 MiB FAT32 geometry is rejected;
7. malformed TOML, wrong version, non-action/payload entries, missing marker,
   unsupported actions/keys, duplicate IDs/marker, and overwrite of an existing
   output are rejected.

## Limits

This does **not** prove that a particular Mu FD reaches or starts UniXNU, that
BDS registered the application, that GOP/ConOut works on hardware, or that the
FAT is discovered by a ramdisk Block I/O path. It does not modify or rebuild
Mu-Silicium, the original UniXNU checkout, any shared board configuration, or
an existing Mu baseline. No device operation is part of this artifact or its
host tests.
