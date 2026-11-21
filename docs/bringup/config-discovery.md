# FAT configuration-discovery boot image

This is an **offline, single-variable packaging experiment**. It does not build
or modify Mu-Silicium and has not been run on a device.

## Inputs

The source is exactly the historical Android v4 image:

```text
/home/firefly/UniXNU/out/onyx/ios-17.7.11-21H461/example/boot/boot.img
size: 205361152 bytes
sha256: f84337c7aa91436779844b6d86f8829d83461592e27edbbb7241378dba5985c2
```

The replacement ramdisk is exactly the separately verified menu-only FAT32:

```text
UniXNU-onyx/out/onyx-bringup/menu-fat/menu-only-fat32-64m.img
size: 67108864 bytes
sha256: 6cd92831a9b2a48d5e9e73bf509443546e70ad7d27296b1558c29230857999d8
```

The existing Mu-Silicium `Resources/Scripts/mkbootimg.py` is used read-only.
The tool extracts the historical kernel field into a temporary directory and
passes it unchanged to `mkbootimg.py`; it does not compile BootShim or the FD.
Both inputs must match the pinned hashes before assembly starts. Existing output
and report paths are refused, including symlinks and the case where output and
report resolve to the same path. Assembly writes a temporary candidate, then
exclusively creates the final output and reopens that final path—not merely the
temporary file—for complete header, kernel, ramdisk, signature and segment
readback. Kernel and ramdisk ranges are copied and hashed in bounded 1 MiB
chunks instead of being retained as whole Python byte strings. If final
verification or report writing fails, cleanup removes only a regular file whose
device/inode was created by this process; a pre-existing file or a path replaced
by a race is never unlinked.

## Output

```text
UniXNU-onyx/out/onyx-bringup/config-discovery/menu-probe-boot.img
size: 71143424 bytes
sha256: 4a33c186869e9c82529891c8ca85913ef75577b439b94e8d5af455b37613616f
```

Machine-readable evidence is in
`UniXNU-onyx/out/onyx-bringup/config-discovery/menu-probe-boot.json`.

## Byte-level readback

The generated image was unpacked independently after `mkbootimg.py` returned.
The readback proves:

| Segment | Bytes | Historical SHA-256 | Candidate SHA-256 | Result |
| --- | ---: | --- | --- | --- |
| full kernel field | 4025169 | `a9a3e200f0bfe9e2acb0f06cdb66dbc9e10ae2168cb65df4891fc5eee211477c` | same | unchanged |
| BootShim | 128 | `7d40b171cb39a311d522bada00df2d857046fd1ef109462494d1f5c50a606594` | same | unchanged |
| UEFI FD | 3145728 | `a7fbef72f78b7e5e4e14680cd6fe85429db866a0e16c5931208db4d53e69d20e` | same | unchanged |
| appended DTB | 879313 | `6379d64c8472c7c4c2d9d225803bebe33b8bd2c14cb73c6b329a8a5458dd6f23` | same | unchanged |
| ramdisk | 67108864 | `6cd92831a9b2a48d5e9e73bf509443546e70ad7d27296b1558c29230857999d8` | same | replacement input |

The Android boot header remains version 4 with a 4096-byte header page. Its
only changed byte is offset 15, inside the little-endian ramdisk-size field at
offsets 12–15 (`0x0c000000` becomes `0x04000000`). Kernel size, OS version,
header size, reserved fields, cmdline and header padding are unchanged. The
4096-byte v4 signature region is still all zero.

The resulting image is shorter because the old 192 MiB ramdisk is replaced by
64 MiB. Thus the intentionally changed material is limited to the ramdisk-size
header field, ramdisk bytes, subsequent placement/length, whole-image size and
whole-image hash.

## FAT/config readback

The ramdisk was read through mtools before assembly. Its complete visible file
inventory is:

```text
::/EFI/
::/EFI/UniXNU/
::/EFI/UniXNU/unixnu.toml
```

`unixnu.toml` is exactly 394 bytes, SHA-256
`697ba173063bf4306e10e2789dc995c8cbf26a8dee77f513c016005ea0088fe8`.
It contains the unique `MENU_ONLY_PROBE` marker and only action entries. The
assembly check rejects references to `kernel.macho`, `DarwinBoot`, `Payloads`
or `[[driver]]`, plus `timeout = 0` and an `xnu` entry. There is no XNU kernel,
DarwinBoot binary, root filesystem or file-backed OS payload in this FAT.

## Reproduction and tests

From the workspace root:

```sh
python3 UniXNU-onyx/scripts/assemble-menu-probe-boot.py \
  --source /home/firefly/UniXNU/out/onyx/ios-17.7.11-21H461/example/boot/boot.img \
  --ramdisk UniXNU-onyx/out/onyx-bringup/menu-fat/menu-only-fat32-64m.img \
  --output UniXNU-onyx/out/onyx-bringup/config-discovery/menu-probe-boot.img \
  --mkbootimg /home/firefly/UniXNU/Mu-Silicium/Resources/Scripts/mkbootimg.py \
  --report UniXNU-onyx/out/onyx-bringup/config-discovery/menu-probe-boot.json

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  UniXNU-onyx.tests.test_assemble_menu_probe_boot -v
```

Tests cover pinned input hashes, read-only final-path verification of the existing candidate's exact `4a33c186...` hash and size, unchanged kernel hash and all-zero signature, plus refusal without overwrite for an existing output/report, output/report path collision, a changed historical source and a changed ramdisk. Quota-bounded synthetic v4 fixtures exercise partial-copy cleanup, final-readback failure, report-write failure and inode-replacement races without creating additional 71 MiB candidates.

## Limits and device gate

This artifact is **not hardware-tested**. It does not prove that ABL accepts the
image, Mu-Silicium starts, BDS starts UniXNU, the firmware preserves the initrd
range, EnhancedFatDxe mounts the volume, or the marker appears on screen. It
must not be described as bootable merely because host readback passes, and it
must not be handed to the device until the historical menu baseline in task-5
has been reproduced and a separate device test is authorized. No `fastboot`
command, flash, Mu build or device operation is part of this task.
