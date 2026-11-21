# onyx GOP/ConOut fixed-baseline audit

This is a read-only audit of the fixed historical onyx firmware volume and its
source integration. It does not build, modify, or replace firmware, display
binaries, configuration, source, or device state.

## Scope of the historical result

The fixed image `boot.img` SHA-256
`f84337c7aa91436779844b6d86f8829d83461592e27edbbb7241378dba5985c2` is bound
only to the historical reported visible **Mu/no-OS** result. It is not an exact
hash binding for the separate earlier user report of an Apple-logo UniXNU menu.
The latter image/configuration remains unidentified here.

The FD associated with that image is:

| item | value |
|---|---|
| path | `/home/firefly/UniXNU/Mu-Silicium/Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd` |
| bytes | 3,145,728 (`0x300000`) |
| SHA-256 | `a7fbef72f78b7e5e4e14680cd6fe85429db866a0e16c5931208db4d53e69d20e` |

A 7-Zip UEFI read-only listing of this exact FD identifies these display and
console files in the main FV:

| FV file | bytes | SHA-256 of extracted file |
|---|---:|---|
| `SimpleFbDxe.efi` | 28,672 | `703492a16a489dafd34e9100e29ce99f37a09c5e8ec6b6cfe7f1f9d65520bdf0` |
| `GraphicsConsoleDxe.efi` | 40,960 | `3ba62140e8e17ef422cf03e896c5ab7bd5624a10a5f552bcd994486b3922911b` |
| `ConPlatformDxe.efi` | 32,768 | `9f002072b8d1a30f03197d3cf88c1d5fa4a6ec1d2b8ed1b40f08dfe9b36f9954` |
| `ConSplitterDxe.efi` | 45,056 | `0fa99d5e1150f1dcc16659d653cb82eab56d87454980e49028e2263f91fd2c57` |
| `SimpleTextInOutSerial.efi` | listed; hash not needed for GOP conclusion | — |
| `ClockDxe.efi` | 376,832 | `342791d7176d5a538b9ee733bc42e90a7d9ac8f183c5b5b94c3c3be1a08e1356` |
| `FeatureEnablerDxe.efi` | 32,768 | `1b3cb967e2362bc22873c85428be67a3913d52bd4348cfb93a7e490a54be19ca` |
| `BootGraphicsResourceTableDxe.efi` | 24,576 | `188baa4d47b2afbd2b487792b3d5012c0e858e79657c89b0274fde11c63dd992` |

The FD listing did not expose a separately named `DisplayReEnablerDxe.efi` or
`DisplayDxe.efi` file. That is consistent with the onyx build selecting the
SimpleFb path; it is not proof that every vendor display-power service was
absent from all compressed or unnamed firmware content.

## Static GOP chain

The onyx DSC sets `USE_CUSTOM_DISPLAY_DRIVER = 0` in
`/home/firefly/UniXNU/Mu-Silicium/Platforms/Xiaomi/onyxPkg/onyx.dsc`. Its
conditional platform DXE list therefore selects
`SiliciumPkg/Drivers/SimpleFbDxe/SimpleFbDxe.inf`, not the onyx vendor
`Binaries/onyx/QcomPkg/Drivers/DisplayDxe/DisplayDxe.efi`.
The same include lists `GraphicsConsoleDxe`, `ConPlatformDxe`, and
`ConSplitterDxe`; `QcomPkg.dsc.inc` adds the generic display re-enabler source
as a platform component, but the historical FD listing is the authoritative
artifact list for this fixed build.

The static chain is:

```text
onyx vendor DXE / existing display state
  -> SimpleFbDxe (registers EFI_GRAPHICS_OUTPUT_PROTOCOL)
  -> GraphicsConsoleDxe (GOP-backed text output)
  -> ConPlatformDxe + ConSplitterDxe (ConOut aggregation)
  -> UniXNU UI / DarwinBoot video handoff
```

`SimpleFbDxe` has an unconditional DEPEX (`TRUE`) and installs GOP with a
simple device path. It does not initialize a panel or clocks itself. It looks
up the memory-map region named `Display Reserved`, then `Display_Reserved`;
without that named region it returns `EFI_NOT_FOUND`. It allocates one GOP mode,
uses `FrameBufferBltLib`, and installs the protocol.

The source and INF identify the SimpleFb module GUID as
`DCFD1E6D-788D-4FFC-8E1B-CA2F75651A92`. The console module GUIDs are:

- GraphicsConsoleDxe: `CCCB0C28-4B24-11D5-9A5A-0090273FC14D`
- ConPlatformDxe: `51CCF399-4FDF-4E55-A45B-E123F84D456A`
- ConSplitterDxe: `408EDCEC-CF6D-477C-A5A8-B4844E3DE281`

These GUIDs and extracted FV names establish static contents, not dispatch,
protocol installation success, or visible pixels.

## Onyx framebuffer parameters

`onyx.dsc` fixes these PCD values:

| PCD | value | source |
|---|---:|---|
| `PcdFrameBufferWidth` | 1280 | onyx DSC |
| `PcdFrameBufferHeight` | 2772 | onyx DSC |
| `PcdFrameBufferColorDepth` | 32 | onyx DSC |
| `PcdSystemMemoryBase` | `0x80000000` | onyx DSC |
| `PcdFrameBufferDelay` | 10,000 microseconds | Silicium common DSC |

From the SimpleFb implementation, the resulting **configured** GOP mode is:

- `HorizontalResolution = 1280`;
- `VerticalResolution = 2772`;
- `PixelsPerScanLine = 1280`;
- framebuffer size `1280 * 2772 * 4 = 14,192,640` bytes;
- `PixelBlueGreenRedReserved8BitPerColor` (the 32-bit BGRx UEFI format);
- framebuffer base = the address returned by `MemoryMapHelperLib` for
  `Display_Reserved`.

Thus the source-configured stride is 1280 pixels (5120 bytes per row). This is
not a measurement of the vendor GOP's actual stride or the panel's scanout
stride. SimpleFb does not query a live GOP mode or discover a runtime stride.

The onyx `MemoryMapLib.c` entry is:

```text
Display_Reserved: 0xFC800000 + 0x02B00000
Display_Demura:   0xB81C0000 + 0x02C80000
```

The Android 17 read-only runtime capture independently records
`splash_region = 0xFC800000 + 0x02B00000`. This supports the address/size as a
stock splash reservation, but does not prove that Mu's memory map, SimpleFb,
GOP, pixel format, stride, or panel clocks successfully use it during a
fastboot boot. The runtime capture explicitly remains non-UEFI evidence.

## ConOut and UI implications

The historical FD contains the static GOP and console modules needed by the
usual EDK2 chain, and the onyx DSC/FDF contain the corresponding INF entries.
If SimpleFb successfully finds its named region and creates GOP, the generic
GraphicsConsole and ConSplitter path can expose a ConOut to UniXNU. However,
none of the following is observed in the fixed artifact:

1. DXE dispatch order and successful entry of SimpleFb;
2. `EFI_GRAPHICS_OUTPUT_PROTOCOL` installation on a live handle;
3. `EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL`/ConOut connection;
4. actual framebuffer base, stride, or pixel format returned at runtime;
5. panel power/clock state or physical scanout;
6. UniXNU UI drawing or whether its Apple-logo/menu report came from this exact
   image.

A black screen therefore cannot be localized from this audit to the panel,
ClockDxe, vendor display service, SimpleFb, GOP, ConOut, UniXNU, or a later
stage. The historical fixed result is only Mu/no-OS evidence.

## Reuse policy

Do not copy another board's `DisplayDxe`, `ClockDxe`, framebuffer address,
stride, resolution, Demura carveout, or display reservation into onyx. Similar
Qualcomm/Xiaomi addresses do not establish panel, TZ, clock, IOVA, or vendor
binary compatibility. In particular:

- do not switch onyx to `USE_CUSTOM_DISPLAY_DRIVER = 1` merely to imitate
  another board;
- do not replace the onyx SimpleFb path with peridot, nuwa, garnet, or any
  other board's prebuilt DisplayDxe;
- retain onyx's own `1280x2772x32` and `0xFC800000/0x02B00000` as static
  candidates only, until live GOP/ConOut evidence exists;
- use the exact onyx vendor ClockDxe/FeatureEnablerDxe already associated with
  the fixed FD, not a binary from another board.

The next diagnostic should inspect a newly authorized, hash-bound image with
serial/USB debug or an external camera while making no display parameter
change. It must distinguish: no DXE video, GOP absent, ConOut absent, UniXNU
not started, and UI not drawn. A fastboot acceptance line or a black screen is
not sufficient evidence for any of those stages.
