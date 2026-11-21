# Historical onyx payload audit

This report is an offline audit of the exact ramdisk embedded in the historical
Android v4 image associated with the user's earlier visible Mu-Silicium result
and subsequent `No Operating System Found` screen. The user separately reported
an older repository version that showed the Apple-logo UniXNU menu, but no
current evidence binds that menu observation to this exact image hash. It does
**not** add a new hardware observation. Inputs were read only;
no Mu-Silicium checkout, source configuration, board file, firmware image, or
phone was modified.

## Inputs and image boundaries

| item | bytes | SHA-256 | read source |
|---|---:|---|---|
| historical `boot.img` | 205,361,152 | `f84337c7aa91436779844b6d86f8829d83461592e27edbbb7241378dba5985c2` | `/home/firefly/UniXNU/out/onyx/ios-17.7.11-21H461/example/boot/boot.img` |
| Android kernel field | 4,025,169 | `a9a3e200f0bfe9e2acb0f06cdb66dbc9e10ae2168cb65df4891fc5eee211477c` | kernel field, offset `0x1000` |
| embedded BootShim | 128 | `7d40b171cb39a311d522bada00df2d857046fd1ef109462494d1f5c50a606594` | kernel field offset `0x1000` |
| embedded UEFI FD | 3,145,728 | `a7fbef72f78b7e5e4e14680cd6fe85429db866a0e16c5931208db4d53e69d20e` | kernel field offset `0x1080` |
| appended DTB | 879,313 | `6379d64c8472c7c4c2d9d225803bebe33b8bd2c14cb73c6b329a8a5458dd6f23` | kernel field offset `0x301080` |
| embedded FAT ramdisk | 201,326,592 | `be6aeabf340f9e06e3bb31adb40787af1f96cfda774a7892e7901361418cc521` | Android ramdisk field offset `0x3d8000` |

The historical kernel field is uncompressed and consists of `128-byte
BootShim + 0x300000-byte FD + 879313-byte appended DTB`. Its ARM64 header
records text offset `0` and image size `0x300080`; the v4 signature area is one
4096-byte all-zero page. The embedded ramdisk is byte-identical to
`/tmp/prior-onyx-analysis/ramdisk`.

The standalone FD at
`/home/firefly/UniXNU/Mu-Silicium/Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd`
has the same SHA-256 as the FD bytes in the historical image. That fact does
not establish that the current checkout built the complete historical image.
The historical BootShim was reconstructed byte-for-byte from the `f77f9457`
source shape after applying its observed behavior, but the unrecorded working
tree that produced the original image remains unknown.

Offline checker and byte-exact temporary repack:

```text
TMPDIR="$PWD" python3 UniXNU-onyx/scripts/inspect-mu-baseline.py \
  /home/firefly/UniXNU/out/onyx/ios-17.7.11-21H461/example/boot/boot.img \
  --mkbootimg /home/firefly/UniXNU/Mu-Silicium/Resources/Scripts/mkbootimg.py
byte_exact_temporary_repack: true
```

This verifies packaging and boundaries only; it is not a source or hardware
reproducibility claim.

## FAT geometry and directory

The ramdisk is FAT32 with 512-byte sectors, 4 sectors per cluster, 32 reserved
sectors, two FATs, 393,216 total sectors, 765 sectors per FAT, root cluster 2,
volume serial `0x53484e47`, and label `ONYX`. `mdir` read the following
complete directory tree (dot entries omitted):

```text
EFI/
EFI/UniXNU/
EFI/UniXNU/unixnu.toml                         330 bytes
EFI/UniXNU/Payloads/
EFI/UniXNU/Payloads/kernel.macho          50,999,296 bytes
EFI/UniXNU/Payloads/kernel.macho.adt          12,988 bytes
```

No `DarwinBoot.efi`, trust cache, GPU addon, root-policy (`.vroot`), or
`scratch-data.img`/Data seed exists in this FAT. The mtools volume listing
reports 149,501,952 free bytes. The complete root/EFI/UniXNU/ Payloads
listings and mtools reads were made directly from the ramdisk rather than
inferred from an older report.

The exact config bytes are:

```toml
version = 1
[boot]
timeout = 3
default = "xnu"
[kits]
autoload = false
[[entry]]
id = "xnu"
title = "UniXNU"
type = "xnu"
path = "Payloads/kernel.macho"
args = "-v serial=3"
[[entry]]
id = "reset"
title = "Restart"
type = "action"
action = "reset"
[[entry]]
id = "shutdown"
title = "Power off"
type = "action"
action = "shutdown"
```

`unixnu.toml`: 330 bytes, SHA-256
`4683ed5c3b8ffe010de194d383ee29e0a2e7576fa72f27d0d1f1835834b42d07`.
The mtools-read referenced payload hashes are:

| referenced file | bytes | SHA-256 |
|---|---:|---|
| `Payloads/kernel.macho` | 50,999,296 | `6cfb2c40100607e60e0a8156094f9d8044a3a4d3d5a591693a260d7ad477ce17` |
| `Payloads/kernel.macho.adt` | 12,988 | `51f551b44526c5a5ed75f9e0f10e29f7c323c9cfd2907fac930709e3b226f828` |

The kernel is a Mach-O 64-bit ARM64 executable (`MH_MAGIC_64`, cputype
`CPU_TYPE_ARM64`, filetype `MH_EXECUTE`, 25 load commands). The ADT sidecar is
Apple-flat device-tree data. It contains `J120AP`, `qcom,tuna`, `iPad7,1`,
`J120`, eight `cpu0`–`cpu7` nodes, `psci`, `arm-io`, `chosen`, and
`memory-map`/`manifest-properties` nodes. Its `/chosen` includes
`dram-base` and `dram-size` values that are both zero in this historical file.
That is a property of the payload and must not be presented as a real EFI
memory map or current ADT-ready RAM range.

The historical directory contains no DarwinBoot driver file because this config
uses `loader = "firmware"` in the generated-payload convention: the firmware
is expected to provide DarwinBoot. `unixnu.toml` directly selects an XNU entry
with `type = "xnu"` and a path relative to the same volume.

## Current-source semantics

The current `Config.c` parser and `Menu.c` implementation give the following
limited conclusions:

* `version = 1` is the required schema version. The `[boot]` table reads
  `timeout`, `default`, `fallback_timeout`, and `connect_all`; `[kits]` controls
  kit loading. `[[entry]]` with `type = "xnu"` requires `path`; action entries
  support `reset`, `shutdown`, `exit`, and `tools` (see
  `unixnu/package/UniXNUPkg/Library/UniXNULib/Config.c:1383-1391` and
  `:1135-1163`).
* `default = "xnu"` selects the sole boot entry. `timeout = 3` is a countdown
  in seconds, not proof that the default entry was eventually launched.
  `Menu.c` uses the default when the timer expires (`:152-155` for the special
  zero case and `:186-194` for a positive countdown). With no input device,
  current code reports the default boots when the timer ends and uses the
  fallback policy where applicable (`:110-125`).
* `[kits] autoload = false` means the config does not request kit autoloading;
  it does not remove the firmware-provided DarwinBoot driver.
* `DarwinBoot.c` opens the selected volume, reads the configured kernel, then
  derives and reads `kernel.macho.adt`, and optionally looks for
  `.trustcache`, `.gpuaddon`, and `.vroot` sidecars
  (`unixnu/drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c:867-953`).
  For this exact FAT, kernel and ADT are present; all optional sidecars listed
  above are absent. The ADT does not advertise a packed RAM disk or trust cache
  in the inspected historical payload, and no Data seed is present.
* The source path and files therefore establish a coherent **attempted**
  DarwinBoot/XNU payload. They do not establish that the firmware started the
  application, that FAT was discovered through the Mu FDT/HOB ramdisk handoff,
  that the configuration was loaded, that GOP/ConOut was visible, that the
  kernel entered, or that root mounted.

## What the user observation does and does not prove

The user reported seeing the Apple-chip-logo UniXNU menu with an earlier
repository image. The historical payload is consistent with that image having
an external/firmware-provided DarwinBoot and an XNU entry, but the payload
alone cannot bind the report to a particular config-read event. In particular,
there is no serial/application trace in this artifact proving that this exact
`unixnu.toml` was loaded.

The following stages remain unobserved for this artifact and are intentionally
not inferred:

1. ABL accepted and entered BootShim/SEC (Android `Sending/Booting OKAY` is not
   this evidence).
2. Mu-Silicium DXE produced GOP/ConOut and started UniXNU.
3. UniXNU found the FAT volume and loaded the exact TOML rather than using its
   built-in fallback.
4. The default XNU entry was launched after the three-second timer.
5. DarwinBoot successfully parsed/loaded the Mach-O and ADT.
6. XNU entered, and root/storage mounted.

The historical artifact is consequently a useful fixed payload/layout
reference, not proof of any unobserved stage. It must not be mixed with a new
FD, new BootShim, new DTB, or a different RAM/payload image while claiming a
reproduction.
