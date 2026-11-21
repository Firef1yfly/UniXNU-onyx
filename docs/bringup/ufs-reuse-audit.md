# SM8735 UFS and root reuse audit

This is a read-only reuse audit. It did not modify the kernel, DTS, board
configuration, component catalog, porting record, firmware, root image, or
phone. Raw private captures and device identifiers are not reproduced. The
machine-readable conclusions are in
`out/onyx-bringup/ufs-reuse-audit/manifest.json`.

## Decision

**Reuse the same-SoC register inventory and the generic transport interfaces;
do not copy a complete UFS driver or root policy unchanged.** Onyx and the
public luming SM8735 work agree on the controller/ICE/MCQ/PHY/SMMU layout.
Those are real SoC facts because every value below was independently read back
from the captured onyx runtime FDT. The public luming record is corroboration,
not the source of truth for onyx.

The current onyx port cannot mount a UFS root. `board.toml` selects no UFS,
Virtio block, VerifiedRoot, or RamBlock component; `onyx_defconfig` explicitly
leaves `CONFIG_XNU_NATIVE_UFS` unset; `[kernel].archives` contains no storage
archive plan; and the current built kernel has no native-UFS symbol. There is
also no onyx userdata geometry, root-window manifest, qualified root-volume
binding, or owner policy.

## Onyx facts that match public SM8735 work

The private onyx runtime FDT was read only for non-sensitive hardware
properties. Its SHA-256 is recorded in the manifest so the facts remain tied
to one capture without publishing the DTB itself.

| Resource | Onyx runtime fact | Public luming SM8735 record | Reuse decision |
|---|---|---|---|
| UFS HCI | `0x01d84000/0x3000` | same | direct SoC input |
| ICE | `0x01d88000/0x18000` | same | inventory only; policy unqualified |
| MCQ SQD | `0x01da5000/0x2000` | same | inventory only; first route may use legacy UTRL |
| MCQ VS | `0x01da4000/0x10` | same | inventory only |
| IRQ | GIC SPI 265, flags 4 | same | direct SoC input |
| SMMU | apps SMMU `0x15000000/0x100000`, stream `0x60`, flags 0 | same | stream fact reusable; takeover policy not reusable |
| PHY | `0x01d80000/0x2000`, `qcom,ufs-phy-qmp-v4-niobe` | same | direct SoC input; no PHY programming inferred |
| lanes | 2 per direction | same | direct SoC input |
| GCC | `qcom,tuna-gcc`, `0x00100000/0x1f4200` | same | GCC window reusable; branch operations still require review |
| provider match | `qcom,ufshc` | same public board shape | an SM8550-only compatible match must be adapted |

The onyx FDT register names are `ufs_mem`, `ice`, `mcq_sqd`, and `mcq_vs`.
This is enough to define a host-checked SM8735 resource table. It is not proof
that the controller is powered, HCE/HCS are adoptable, firmware left a safe
request list, the SMMU context is usable, or storage DMA works under XNU.

## What can be reused

### Generic component and ABI shape

The UniXNU catalog's `ShengUfs` component supplies useful interfaces:

- `NativeUfs`/`NativeUfsBlock` runtime class names and the block transport
  boundary;
- a default-off, read-only stage-0 survey before DMA;
- bounded SCSI capacity/GPT/known-block reads before root publication;
- UFS-window bounds checking and ordered SystemOS/OS publication;
- dependencies on `VirtioMmioBlock` and `VerifiedRoot` for the documented
  route;
- the source/API split and storage-kext binding technique required to call the
  prelinked IOStorageFamily class without registering a duplicate
  `IOBlockStorageDevice` metaclass.

Dada demonstrates the correct ownership model for a different SoC: fork the
transport into a board/SoC-qualified component, replace measured hardware and
root policy, retain only generic classes and tests, and bind to the exact OS
ABI. It does **not** make DadaUfs constants valid for onyx.

### Same-SoC candidate table

The public luming record gives a plausible Tuna GCC table (branch offsets,
GDSCs, reset and RCG registers). Because luming and onyx expose the same Tuna
GCC window and identical UFS topology, that table is the strongest candidate
starting point. It remains candidate-only until checked against pinned Tuna
clock source and a read-only onyx stage-0 snapshot. It must not be silently
introduced as measured onyx evidence.

## What must not be copied

1. **SM8550 clock/reset constants.** Catalog `ShengUfs` is explicitly scoped to
   SM8550/sheng and hardcodes its compatible, GCC branches and sheng policy.
   Identical HCI base and stream ID do not make its clock table correct.
2. **RPMh, GDSC, regulator and PHY programming.** Onyx confirms windows and
   compatible strings, not command-DB resource IDs, voltage votes, reset
   order, interconnect votes, lane calibration, or power sequencing.
3. **SMMU context-bank selection.** Stream `0x60` is confirmed. The available
   stream-map slot, context bank, translation/bypass state, address width,
   cacheability, and firmware ownership must be observed on onyx. A bank
   number from sheng or luming is not reusable.
4. **ICE/MCQ policy.** The registers exist, but the first read-only route may
   adopt the firmware legacy UTRL. Android's MCQ/ICE mode, key policy, queue
   count, and crypto configuration are not a Darwin/XNU handoff contract.
5. **Firmware binaries.** No luming, sheng, dada or other board UFS/Clock/PHY
   DXE or firmware image should be substituted for onyx inputs.
6. **GPT and root geometry.** Never copy luming's first/last LBA, logical block
   count, storage capacity, root windows, partition name assumptions, or Data
   layout. Onyx has no qualified geometry in the public device config.
7. **Root identity and policy.** The OS profile and other boards are references
   for the SHNGROOT recipe, not proof of an onyx root UUID, trust-cache bundle,
   signed VerifiedRoot policy, SystemOS/OS window offsets, Data seed, or
   persistence behavior.
8. **Driver ABI.** The exact IOStorageFamily revision, vtable shape, kernelcache
   bindings, slide, arm64/arm64e mode, and archive order must match the selected
   onyx OS build. Copying a built archive from another port risks duplicate
   classes or wrong imports.

## Minimal host-first component boundary

A future implementation should be an `OnyxUfs` or shared `Sm8735Ufs`
component derived from the generic ShengUfs interfaces, not a direct selection
of the SM8550 catalog binary. Before any XNU image is produced, host tests
should establish:

1. **Resource contract:** compatible is only accepted for reviewed Tuna/onyx
   forms; HCI/ICE/MCQ/PHY/SMMU ranges, IRQ 265, stream `0x60`, and two lanes
   match the onyx inventory exactly. A deliberate SM8550/SM8750 constant must
   make the test fail.
2. **Clock contract:** every GCC branch/GDSC/reset/RCG offset stays within its
   declared window, comes from the pinned Tuna clock source, and is separated
   from the read-only survey. No RPMh or voltage identifier is invented.
3. **No-write survey:** the first diagnostic path maps and reads only; it must
   not ring a doorbell, stop a queue, reset the controller, change SMMU state,
   or touch media.
4. **Adoption state machine:** synthetic register models cover unavailable
   power/clocks, outstanding firmware requests, missing/aligned request-list
   base, HCE/HCS state, SMMU refusal, timeout and cleanup. DMA begins only after
   all checks pass.
5. **DMA/UPIU contract:** command, UTRD, PRDT alignment and endian fields,
   controller address width, cache maintenance, transfer bounds, SCSI status,
   sense data and timeout paths pass synthetic/fuzz tests.
6. **Read-only storage ladder:** INQUIRY/TUR, READ CAPACITY, GPT header and entry
   CRC, LUN/block size, and known-block hashes are validated before parsing a
   root manifest. No media write or persistent diagnostic window exists in the
   initial component.
7. **Root-window contract:** manifest offsets/sizes are overflow-safe,
   non-overlapping, inside a separately measured onyx userdata partition and
   aligned to the actual logical block size. OS and SystemOS must be distinct.
8. **ABI/archive contract:** build the exact storage reference object and
   kext-bindings for the pinned 21H461 kernelcache; prove no duplicate
   IOStorageFamily class is linked; require the selected archive and config
   symbols in the final kernel.
9. **Integrity contract:** if VerifiedRoot is selected, reject missing,
   duplicate, wrong-size or unauthenticated policies and bind the signed volume
   identity. If it is not selected, the report must not claim verified root.
10. **Packaging gate:** payload/root geometry and policy files must be tied to
    one manifest and hashes; a root image alone cannot pass while native UFS is
    disabled.

## Later approval-gated device observations

Only after the host gates pass, a read-only staged device test should record:

1. stage-0 GCC/HCI/SMMU snapshot, with HCE/HCS, version, doorbells, request-list
   base, stream map and context-bank state; no DMA;
2. if the firmware handoff is demonstrably quiescent, one bounded NOP/TUR and
   READ CAPACITY operation, then restore/refuse cleanly on error;
3. bounded GPT reads with header/entry CRC and actual LUN/logical block size;
4. known block hashes compared with an independently captured onyx reference;
5. root manifest/window containment and read-only IOMedia publication;
6. APFS root UUID match and root mount; only then launchd;
7. Data writes/persistence as a separate, explicitly authorized stage—never
   inferred from read-only root success.

No such observation was performed in this audit. Fastboot acceptance, another
board's root mount, Android's working UFS, or a host model does not qualify any
of these stages.
