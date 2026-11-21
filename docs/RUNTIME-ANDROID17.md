# Runtime Android 17 evidence — KernelSU read-only capture

Capture date: 2026-11-14 (host timezone Asia/Shanghai). The device was connected over adb as serial `5d7b86fd`; commands used `adb shell su -c` and did not reboot, flash, mount or write to the phone. KernelSU reported `uid=0(root)` with context `u:r:ksu:s0`. Raw captures remain under ignored `private-inputs/runtime-android17-20261114/root-capture/` and are not publication artifacts.

## Identity

- `ro.product.device`: `onyx`
- `ro.build.fingerprint`: `Redmi/onyx/onyx:17/CP2A.260605.016/OS4.0.2.0.XOLCNXM:user/release-keys`
- Runtime DT model: `Qualcomm Technologies, Inc. Onyx based on SM8735`
- Compatible: `qcom,tuna-mtp`, `qcom,tuna`, `qcom,tunap-mtp`, `qcom,tunap`, `qcom,mtp`
- Runtime DT `qcom,msm-id`: `<681 0x10000>, <655 0x10000>`; `qcom,board-id`: `<8 0>`
- Bootconfig: `androidboot.hardware.sku="onyx"`, boot device `1d84000.ufshc`, slot `_b`, verified boot state `orange`, device unlocked.

The runtime identity now confirms that the user-supplied Android 17 images correspond to this onyx device at the build/fingerprint level. It does **not** make the static image DTBs runtime DTs.

## Runtime memory node

The privileged DT `memory/reg` is nonzero and contains multiple ranges. Decoded as 64-bit address/size tuples:

```text
0x081300000 + 0x00100000
0x081960000 + 0x000a0000
0x081a40000 + 0x001c0000
0x081cf5000 + 0x0000b000
0x081f00000 + 0x00300000
0x082460000 + 0x000040000
0x0d8600000 + 0x000000000   [zero-size entry; runtime node is not directly usable as a clean ADT range]
0x0e3720000 + 0x17ce0000
0x0fb800000 + 0x04000000
0x0ffe00000 + 0x00200000
0x0880000000 + 0x02f8fe000
0x08b0000000 + 0x007f00000
0x0980000000 + 0x180000000
0x08c0000000 + 0x0c0000000
0x08b8100000 + 0x01e00000
0x082800000 + 0x02200000
0x094e9c000 + 0x00064000
0x096f80000 + 0x00080000
0x099e00000 + 0x00500000
0x09e380000 + 0x08080000
0x0a7000000 + 0x11000000
0x0b81c0000 + 0x1fe40000
```

One entry is zero-size, and the tuples are fragmented/reservation-oriented rather than a single contiguous handoff range. Therefore this capture is valuable runtime evidence but **must not be copied directly into `dts/onyx-bringup.dts`**. It requires correlation with UEFI’s usable ranges and reserved-memory ownership.

The runtime node also reports `ddr_size = 0x0c` (vendor encoding; not interpreted as a byte count here), DDR device type `8`, manufacturer ID `0xff`. Linux reports `MemTotal: 11502936 kB`; that is not a physical DRAM map and is not used as DTS input.

## Runtime initrd handoff

The privileged `/chosen` properties are 64-bit big-endian values:

```text
linux,initrd-start = 0x00000000b5921000
linux,initrd-end   = 0x00000000b7ffeb04
```

Length is `0x20fdb04` bytes (about 32.999 MiB), and the range lies inside the runtime `/proc/iomem` System RAM interval `0xa7000000..0xb8000000`. `/proc/iomem` marks `0xb5921000..0xb7ffefff` reserved, which is strong supporting evidence that the Android runtime keeps this initrd range reserved. It is still not an EFI memory map and not proof that the current Mu-Silicium SEC path preserves it.

The runtime `/proc/cmdline` includes `debug_ext.initrd_size=39797` and Android vendor boot parameters. The current Android vendor ramdisk remains LZ4 Android content, not a proven UniXNU FAT payload.

The complete reserved-memory child-property capture is in `root-capture/reserved-values.txt` (62 nodes). It confirms a broad mix of fixed `no-map` firmware/secure/DSP/GPU/display regions and dynamic `shared-dma-pool` size-only regions such as `linux,cma`. This reinforces that `/proc/iomem` System RAM is not equivalent to free XNU RAM. In particular, `splash_region` is `0xfc800000/0x02b00000`, and many regions overlap the fragmented memory banks or are owned by firmware services.

## Complete runtime FDT capture

A correctly quoted read-only command, `adb exec-out "su -c 'cat /sys/firmware/fdt'"`, succeeded. The earlier permission errors were caused by remote shell quoting, not proof that KernelSU could not read the node. The complete runtime FDT is stored privately as `runtime-full.dtb`: 847177 bytes, SHA-256 `3b90da7e20c3bbde0e2663726e95ef66396260200aa2b2452fcb076d87794365`.

The existing analyzer reports onyx identity, 22 enabled memory tuples, 46 fixed reserved ranges, 11 size-only dynamic reservations, and a terminated (empty) FDT memreserve list. It deliberately exits 1 for the zero-size tuple and unresolved dynamic allocations. This is source evidence, not a UEFI map or proof of ADT readiness. Android's bootconfig reports `dtb_idx=0` and `dtbo_idx=0` for this boot; preserve those observations but do not assume future bootloaders use the same selection.

The missing EFI descriptor/RAM-partition output is now tracked in [EFI memory-map next steps](EFI-MEMORY-MAP-NEXT.md). Mu-Silicium has the RAM manager implementation but the onyx image does not expose a shell `memmap` command or structured exporter.



The new evidence justifies updating the development record and designing the handoff around preserving the runtime initrd range, but it does **not** justify setting `board.example=false`, selecting a single DRAM range, building a boot image, or flashing the phone. The existing fail-closed checks remain in place.
