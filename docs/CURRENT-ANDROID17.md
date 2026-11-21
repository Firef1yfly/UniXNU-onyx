# Current-device image baseline: user-reported Android 17

## Provenance

The user clarified that `/home/firefly/下载/images.zip` contains the images matching the device's **currently running Android 17**, while the earlier loose images are **Android 16**. This supersedes the earlier loose-image set as the active comparison baseline. These version labels are user-provided, not independently measured with adb. The cmdline substring `onyx:15` in both sets is not used to override the user's version information.

Archive: 47331925 bytes, SHA-256 `cfb7b8f2c0a026ceecab61a781f6ce0e4b4d010ab09676b13cf30ec0650d50f3`.

The ZIP directory contains only `images/` and the three expected image members. Extraction used an explicit allowlist, fixed local output names and a 128 MiB/member size bound. Reading each member to EOF also performed ZIP CRC checks. No path from the ZIP was used for output path construction. The source ZIP and older loose images were not modified.

| Member | Bytes | SHA-256 |
| --- | ---: | --- |
| images/boot.img | 100663296 | 1e87310bc9b29f29a529e195fa093dde173e2136dd4f82c7ec006b65a2667257 |
| images/vendor_boot.img | 100663296 | db1c5fb9448c286637fee7f326d69253587de4c930d3c33ce9d397c4d6736544 |
| images/dtbo.img | 18874368 | 0a8831a39a504fb15645037446129b1683d86b0ddb9f1a2a218035f12d07becd |

Outputs and JSON manifests remain in ignored `private-inputs/current-android17/`, separate from the historical `private-inputs/stock-20261114/` directory. They have not been published or added to Git.

## Headers and extracted trees

Boot and vendor boot both use header v4; vendor page size is 4096. Vendor ramdisk size is 37688236 bytes; DTB section offset is 37695488, size 966906 bytes. The DTB load-address field is still `0x1f00000`, not a DRAM-base measurement. The current cmdline contains `swinfo.fingerprint=onyx:15/OS4.0.2.0.XOLCN:user`; the older cmdline contained `OS3.0.306.0.WOLCNXM`.

| Tree | Source offset | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| vendor-base-0.dtb | 37695488 | 483533 | 2485fe3878cc75a09f48c4f45ebedd46517e6292b16bb7a54b0c091330883227 |
| vendor-base-1.dtb | 38179021 | 483373 | bfd70e615a61358f451e233a2be7c20b358f898b62a4df8fce4be728a9e07d44 |
| overlay-0.dtbo | 64 | 440462 | da65f35561037fabfe28325814767ae815ee731c58ae76e08776b48ff43f6130 |

FDT splitting used exact header sizes/offsets and bounds checks, not signature scanning. Both current base DTBs and the overlay differ byte-for-byte from their historical counterparts. The single current overlay still identifies Onyx/SM8735 with msm IDs 681 and 655, board ID 8/0 and Xiaomi board ID 7/0. Both current offline merges using `fdtoverlay` succeeded (exit 0).

## Revalidated invariants

The following were asserted for **all eight** base/merged trees across both firmware sets; this is not a full device-tree diff or a guarantee that all peripheral/power configuration is unchanged:

- CPU affinities: `0, 0x100, ... 0x700`, compatible `qcom,kryo`.
- PSCI: `smc`.
- GIC physical ranges: distributor `0x17100000/0x10000`, redistributor `0x17180000/0x200000`, stride `0x40000`.
- Timer: 19200000 Hz, tuples `<1 13 0xff08>`, `<1 14 0xff08>`, `<1 11 0xff08>`, `<1 12 0xff08>`.
- Memory: `<0 0 0 0>` in every base and offline merge.
- UFS: base disabled; overlay enables it. HCI range `0x1d84000/0x3000` and interrupt tuple `<0 265 4>` unchanged in the merged comparison.
- Splash: merged reservation `0xfc800000/0x02b00000`.
- Current merged touch: Novatek SPI at `0xa90000`, chip-select 0, IRQ GPIO78.
- Current merged GPU compatible: `qcom,adreno-gpu-gen8-6-0`.

Thus the minimal CPU/GIC/timer/PSCI bindings in the local SoC source remain supported by the current image baseline. Do not infer DRAM or partition geometry, select a base DTB, or enable GPU/UFS drivers merely from these invariants. Runtime DT/UEFI map and firmware ownership remain required.

## Host integration (same round)

A local development profile now lives in `soc/`; `feeds.toml` no longer depends on the incomplete absolute home-directory SoC repository. `board.toml` selects `dts/onyx-bringup.dts`; the old huge vendor DTS and stale DTB are retained only as historical references. CPU0 is the sole enabled candidate; its status is policy, not a measured boot MPIDR.

Commands from the main UniXNU checkout:

```sh
./unixnu defconfig onyx_defconfig -D ../UniXNU-onyx
./unixnu status -D ../UniXNU-onyx \
  --local-module kit:XnuPrelink=../XnuPrelink-reference --json
```

Both succeeded after fetching XnuPrelink at its catalog pin `c645d76bb0ab8c506a76840ddf93a2276d419a0e`. Without this explicit component source, status failed on missing OS-profile patch files in the uninitialized submodule. This was a real dependency failure, not a board/DTS error. Other component submodules remain unfetched; status parsing does **not** prove their sources are present or the complete build graph is fetched. No lockfile or full build is claimed.

Tests:

- Device `python3 -m unittest discover -s tests -v`: **18 passed**, including warning-free DTB compilation, exact GIC address translation/stride, CPU policy, timer bindings, and actual ADT rejection of zero DRAM.
- Main `python3 -m unittest discover -s scripts/unixnu -p 'test_*.py' -v`: **20 passed**.
- Record checker: **13 structured areas checked**.
- Both Git diffs pass `git diff --check`.

The ADT converter previously accepted zero DRAM and a range extending beyond u64. A local two-line fix rejects these; three new regression tests verify failure and valid boundary preservation. Its changed file and new test are uncommitted in the main checkout. Device binding tests deliberately use one **synthetic** nonzero RAM range only in a temporary directory to test encoding; that fixture is never saved as an onyx hardware input.

No kernel, firmware, payload, boot image or real-device boot has been validated. The board remains `example=true`; DRAM remains zero by design.
