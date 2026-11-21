# Historical onyx images — user-identified Android 16

**Superseded as active baseline:** the user clarified that these loose files are Android 16, while the running phone is Android 17. Use [the current archive inspection](CURRENT-ANDROID17.md) for active comparisons. This historical record is retained for provenance and cross-version checks.

## Provenance and limits

The user identified three images in `/home/firefly/下载` as belonging to the target device. They were opened read-only; no original image was changed. Their authenticity, download source and exact device SKU have not been independently established. The version below is a string embedded in the image, not a confirmed running-device version.

| Image | Bytes | SHA-256 |
| --- | ---: | --- |
| boot.img | 100663296 | 34da585168b2e12f5253dc9b7fdfa4fa9be8da935f57c37e3ac58db8ceff36c6 |
| vendor_boot.img | 100663296 | d4d09cc510cd94a0fcb0dedeab6d179adbcb4bd2cd44f78722022c174a64d133 |
| dtbo.img | 18874368 | 0c560bb16f15d9bad9b8bd9ad74b9dfde5b5ec1d0f61ea8e0cec8dfe62ea5971 |

The ignored `private-inputs/stock-20261114/` directory contains bounded extracted trees, the extraction manifest and JSON hardware summaries. No raw image or extracted tree is intended for Git.

## Android image headers

- Boot: header v4; kernel size 36801024 bytes; ramdisk size 0; signature size field 0; OS-version field 0 (not an Android version claim).
- Vendor boot: header v4; page size 4096; header size 2128; vendor ramdisk size 33830252; DTB section size 966790; DTB load-address field `0x1f00000` (not DRAM base).
- Vendor cmdline includes `swinfo.fingerprint=onyx:15/OS3.0.306.0.WOLCNXM:user`.
- Vendor bootconfig includes `androidboot.hardware=qcom`, `androidboot.usbcontroller=a600000.dwc3` and protected-VM support. These are static configuration declarations.
- DTBO header: version 0; one entry; entry size 32; declared total size 440334 bytes within an 18874368-byte partition image.

## Extracted trees

| Output | Absolute offset in source image | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| vendor-base-0.dtb | 33837056 | 483475 | ac2702835b85de7033aed0cf85d9ebabf95964009620738a0a4b7b1b93641ecf |
| vendor-base-1.dtb | 34320531 | 483315 | 1dde55547a6fe71a889f88862cdb7aa3f4838909b55b0ed7662d5482e8d9f633 |
| overlay-0.dtbo | 64 | 440270 | 1dde1a93504098cdcaf69364483c0d7a0e3764ad9b963a32ba0b0194c600c45b |

Vendor DTB offset was computed as `align(header_size, page_size) + align(vendor_ramdisk_size, page_size)`. Each FDT was split by its big-endian FDT totalsize, with bounds/magic checks. The two sizes sum exactly to the vendor DTB section size. The overlay came from the DT table's entry offset and size, not a magic-byte search.

The base trees identify Tuna (`msm-id=655, revision=0x10000`) and Tuna 7 (`msm-id=681, revision=0x10000`). The overlay identifies `Qualcomm Technologies, Inc. Onyx based on SM8735`, accepts both IDs, and declares board ID `<8 0>` and Xiaomi board ID `<7 0>`. This matches the [pinned official MiCode overlay](https://github.com/MiCode/kernel_devicetree/blob/2e51db4a1ea216ef69122485bf53161743da55b7/qcom/onyx-sm8735-overlay.dts) at the identity level; this is not a byte-for-byte source-build comparison.

## Offline merge and observations

From `private-inputs/stock-20261114/`:

```sh
fdtoverlay -i vendor-base-0.dtb -o merged-0.dtb overlay-0.dtbo
fdtoverlay -i vendor-base-1.dtb -o merged-1.dtb overlay-0.dtbo
fdtget -t x merged-0.dtb /memory reg
fdtget -t s merged-0.dtb /soc/ufshc@1d84000 status
```

Both overlay applications exited 0. `/memory/reg` remains `<0 0 0 0>`, while the UFS node changes from `disabled` in the base to `ok` after merging. The merged root model remains the base model: overlay root identity properties are selection metadata and are not assumed to replace root properties during `fdtoverlay`.

| Subsystem | Static image observation; not runtime qualification |
| --- | --- |
| CPUs | Eight affinities `0x0, 0x100, ... 0x700`; compatible `qcom,kryo` (does not establish detailed microarchitecture) |
| PSCI | `arm,psci-1.0`, method `smc` |
| GIC | `arm,gic-v3`; distributor `0x17100000/0x10000`, redistributor `0x17180000/0x200000` |
| Timer | `arm,armv8-timer`, clock-frequency 19200000 Hz |
| UFS | HCI `0x1d84000/0x3000`; interrupt tuple `<0 265 4>`; enabled by overlay; no LUN/GPT/runtime read evidence |
| Touch | `novatek,NVT-ts-spi` under SPI `0xa90000`, chip select 0; interrupt GPIO specifier contains GPIO 78 |
| GPU | `qcom,adreno-gpu-gen8-6-0`; this does not establish compatibility with the A740 driver |
| Splash reservation | `0xfc800000/0x02b00000`; a reserved region, not proven active GOP geometry or pixel format |

## Consequence for the reconstruction

**Correction to the earlier audit's interpretation:** zero memory in the inherited DTS is not by itself proof of an invented or manually broken value. Both supplied stock base DTBs contain that same placeholder. It may be filled by the runtime boot chain, but these static images do not demonstrate that fixup or expose actual DRAM geometry. Zero remains unsuitable for the UniXNU ADT handoff.

Do not infer RAM size from image size, DTB load address, splash reservation or marketing RAM capacity. Obtain live DT/bootloader-adjusted memory information and the UEFI memory map before assigning a usable contiguous ADT range. Do not infer GPT or userdata layout from boot images. Keep the build input gate active.

No ADT/kernel/firmware/payload build or real-device boot is claimed by this inspection.
