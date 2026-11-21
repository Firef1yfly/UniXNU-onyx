# Pinned Mu-Silicium baseline

This baseline is the historical Android v4 image associated with the user's
visible Mu-Silicium result. It is not the later black-screen BDS, QR, memory-map
or Mu-only candidate.

## Immutable inputs

| Part | Bytes | SHA-256 |
| --- | ---: | --- |
| `boot.img` | 205361152 | `f84337c7aa91436779844b6d86f8829d83461592e27edbbb7241378dba5985c2` |
| kernel field | 4025169 | `a9a3e200f0bfe9e2acb0f06cdb66dbc9e10ae2168cb65df4891fc5eee211477c` |
| BootShim | 128 | `7d40b171cb39a311d522bada00df2d857046fd1ef109462494d1f5c50a606594` |
| UEFI FD | 3145728 | `a7fbef72f78b7e5e4e14680cd6fe85429db866a0e16c5931208db4d53e69d20e` |
| appended DTB | 879313 | `6379d64c8472c7c4c2d9d225803bebe33b8bd2c14cb73c6b329a8a5458dd6f23` |
| FAT ramdisk | 201326592 | `be6aeabf340f9e06e3bb31adb40787af1f96cfda774a7892e7901361418cc521` |

The kernel field is uncompressed and equals BootShim + 3 MiB FD + appended
DTB. The ARM64 header records text offset zero and image size `0x300080`. The
Android v4 signature area is 4096 zero bytes.

`/home/firefly/UniXNU/Mu-Silicium/Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd`
still matches the embedded FD. The active source checkout has since moved to
commit `48d309fa`; its current BootShim and integrated packages must not be
called the source of this old image without reconstruction evidence.

The embedded 128-byte BootShim was reconstructed byte-for-byte by applying the
historical behavior to the `f77f9457` source shape:

- ARM64 text offset zero;
- ARM64 image size includes the 128-byte shim;
- preserve nonzero bootloader `x0`, otherwise fall back to the appended DTB.

This explains why neither the stock official shim nor the current active shim
is byte-identical. It does not prove which unrecorded working-tree state built
the historical image.

## Offline verification

Run:

```sh
TMPDIR="$PWD" python3 UniXNU-onyx/scripts/inspect-mu-baseline.py \
  /home/firefly/UniXNU/out/onyx/ios-17.7.11-21H461/example/boot/boot.img \
  --mkbootimg /home/firefly/UniXNU/Mu-Silicium/Resources/Scripts/mkbootimg.py
```

The checker validates every boundary, the ARM64 header, the complete FDT,
padding, the zero v4 signature and the pinned whole-image digest. It also
repackages the original kernel and ramdisk in a temporary directory and
requires the full historical report to remain identical. This proves Android
packaging reproducibility, not firmware source reproducibility or hardware
boot.

## Competing configurations

Project-Silicium main currently declares gzip for onyx. The Firef1yfly fork and
this historical image use no compression. They are separate experiments and
must never be mixed in one provenance claim.

The independent Mu-only FD
`7ae85c31fd7f67b23574c0303fa49e50e6d129b0d2c51ebce5ee48e2258831c8`
removed UniXNU/DarwinBoot and produced a black display in its reported
temporary boot. That observation does not supersede this baseline and does not
localize the failure. See `cross-device-reuse.md`.

## Next controlled change

Do not rebuild the firmware or alter BootShim, DTB, APRIORI, BDS, display or
memory map for the first comparison. First reproduce the historical image's
visible firmware/menu behavior. Only after that result is bound to an image
hash may the ramdisk be replaced by the separately verified diagnostic FAT.
