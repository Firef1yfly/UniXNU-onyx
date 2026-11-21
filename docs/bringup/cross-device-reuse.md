# Cross-device reuse audit

This note classifies values by provenance. It does not make another device's
memory map, display firmware, or RAM window valid for onyx.

## Directly confirmed on onyx

The following values are present in the onyx Mu-Silicium sources and, where
noted, independently present in the captured onyx Android 17 runtime FDT:

| Item | Value | Onyx evidence | Decision |
| --- | --- | --- | --- |
| System memory base | `0x80000000` | `onyx.dsc`; runtime FDT has low DDR ranges above it | retain |
| UEFI FD | `0xA7100000 + 0x00300000` | `onyx.dsc`, `onyx.toml`, `MemoryMapLib.c`, historical boot image | retain |
| FD reserved | `0xA7400000 + 0x00200000` | onyx `MemoryMapLib.c` | retain |
| UEFI stack | `0xA760D000 + 0x00040000` | onyx DSC and memory map | retain |
| SEC heap | `0xA764D000 + 0x0008C000` | onyx memory map | retain |
| scheduler heap | `0xA76D9000 + 0x00400000` | onyx memory map | retain |
| FV region | `0xA7AD9000 + 0x00400000` | onyx memory map | retain |
| splash reservation | `0xFC800000 + 0x02B00000` | onyx runtime FDT and `/proc/iomem` | retain as reservation, not a proven GOP framebuffer |
| CPU affinity | `0, 0x100, ..., 0x700` | onyx runtime FDT | reusable SoC fact |
| GICD / GICR | `0x17100000/0x10000`, `0x17180000/0x200000` | onyx runtime FDT | reusable SoC fact |
| timer | 19.2 MHz, virtual INTID 27 | onyx runtime FDT | reusable SoC fact |
| UFS / PHY | `0x1D84000`, `0x1D80000`; SPI 265; stream `0x60` | onyx runtime FDT | reusable SoC fact, driver still unqualified |

Peridot, annibale, nuwa, marble and garnet repeat much of the UEFI window. That
is useful corroboration, but none of these values is accepted merely because it
appears on another board.

## Same-SoC result

The public luming SM8735 record reports the same CPU, GIC, timer, UFS, SMMU,
UART and GPU register facts. More importantly, its largest Android System RAM
run is also:

```text
0x8c0000000..0xaffffefff
```

The private onyx Android 17 `/proc/iomem` independently contains that exact
run, so the equality is real SM8735/on-device corroboration rather than a value
borrowed from luming.

It is not yet a valid DarwinBoot window. On onyx the same snapshot reserves the
upper part beginning at `0xaeec08000`. A conservative candidate before that
reservation is:

```text
base:             0x8c0000000
raw end:          0xaeec08000
raw size:         0x22ec08000
2 MiB floor end:  0xaeec00000
2 MiB floor size: 0x22ec00000
```

This candidate is recorded for comparison only. It is not written into the DTS
or ADT because Android `/proc/iomem` does not prove that the active Mu firmware
reports the same pages as `EfiConventionalMemory`, and DarwinBoot still needs a
real `GetMemoryMap` result and Qualcomm RAM partition evidence.

## Values that must remain onyx-specific

Do not copy any of the following from peridot, annibale, nuwa, marble, garnet,
sheng, luming, dada or pagani:

- `DXE_Heap`, `Display_Demura`, `Display_Reserved`, TZ and kernel carveouts;
- framebuffer base, stride, pixel format, resolution or panel/clock policy;
- `DisplayDxe.efi`, `ClockDxe.efi`, `CPRDxe.efi`, or a complete `MemoryMapLib`;
- Android initrd placement, a UEFI free-memory descriptor, or DarwinBoot owned
  memory size;
- an embedded-payload packaging route when testing the standard initrd route.

Onyx `MemoryMapLib.c` differs materially from peridot after the shared FV
window. The existing onyx `0xBAE40000 + 0x1D1C0000` DXE heap and
`0xB81C0000`/`0xFC800000` display reservations are kept. The runtime splash
reservation supports the latter reservation but does not prove GOP base,
stride, pixel format, panel state, or that `SimpleFbDxe` can scan it out.

## Mu-only observation

The independent `/home/firefly/mu-only-onyx` tree retained the onyx memory map,
SimpleFb policy and vendor binaries, while removing the UniXNU/DarwinBoot
modules. Its 3 MiB FD has SHA-256
`7ae85c31fd7f67b23574c0303fa49e50e6d129b0d2c51ebce5ee48e2258831c8`.
The reported temporary `fastboot boot` test was black and the device recovered
to Android. With no serial or structured firmware log, this does not locate the
failure at display, DXE, GOP, or any earlier stage. It is not a replacement for
the historical image associated with a visible Mu result.

## Implementation decision

No foreign board constant is copied into onyx. The immediate reusable changes
are already present in the local SM8735 DTS: CPU, PSCI, GIC and timer. UFS,
SMMU, UART and GPU register facts may be added only from the onyx runtime FDT
and only when their corresponding components are selected. The high DDR run
remains a candidate until the same firmware path exports an EFI map and the
Qualcomm RAM partition table.
