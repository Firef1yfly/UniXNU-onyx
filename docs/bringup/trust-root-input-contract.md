# Trust, Data and root-input contract

This is a **read-only contract audit** for the eventual onyx payload. It does
not generate, copy, hash, or record any private trust bundle, Data seed,
platform seed, userdata image, or root-policy bundle. It does not change
`board.toml`, kernel configuration, firmware, or the device.

The audit follows the current UniXNU build code, the pinned
`ipados-17.7.11-21H461` profile, and the current onyx board description. A
successful host assembly is not a root or hardware result.

## Contract summary

| Input | Build option / output | Required in every payload? | Current onyx status | Hardware acceptance |
| --- | --- | --- | --- | --- |
| Static/original trust cache | `--trust-cache FILE` → `Payloads/kernel.macho.trustcache` and ADT `TrustCache` mapping | Optional to the generic payload writer; functionally required for a normal AMFI launch path unless a separately proven no-AMFI route is selected | Not supplied or pinned in current `board.toml`; the OS profile provides public accepted SHA-256 pins | Same-build file hash, module structure and ADT mapping; then observe trust-cache load and launchd/exec on the device |
| Owner trust-cache bundle | `--owner-trust-cache FILE` → same payload sidecar, board allow-list bypassed | Route-dependent; required when adding owner-signed modules or using an owner-trust route | Not present; must not be invented or copied from another device | Same bundle must pair with the kernel, addon and Data seed; observe AMFI acceptance and process launch |
| Data seed | `--data-ramdisk FILE` → `Payloads/scratch-data.img`, packed `PackedRAMDisk` or `RAMDisk` mapping | Optional only when the selected kernel does not require owner Data; required by `CONFIG_XNU_OWNER_DATA_MOUNT` and by persistent/owner-Data routes | Not present; no seed UUID or hash is recorded here | Same seed must match the compiled owner-data UUID and paired image; observe RamBlock publication, APFS Data mount and userland |
| First-install Data generation | `--init-data` / board runtime seed tool | Explicit first-install route only; never an automatic cache fallback | No route is configured in current onyx board | Must be treated as a new installation and paired with a kernel rebuilt for its resulting UUID |
| OS/SystemOS root windows | `build userdata` from IPSW `OS` and `Cryptex1,SystemOS` | Required for a UFS/SHNGROOT root route; `SystemOS` may be profile-optional, but onyx has no selected userdata route | Current board has no `[userdata]`; no userdata artifact is qualified | Read-only extracted windows, SHNGROOT manifest, GPT geometry and root-volume UUID must all match the same IPSW/profile |
| Root matching | profile `root.os_volume_uuid` / generated ADT `root-matching` | Required when DarwinBoot/XNU selects a specific APFS root volume | The public 21H461 profile records a root UUID, but current onyx board does not expose a completed root route or `payload.adt.root_match_volume_uuid` | Observe the selected IOMedia UUID and successful root mount; a UUID string alone is not proof |
| Verified-root policy bundle | `board.toml [payload].root_policies` → `Payloads/kernel.macho.vroot`, ADT `RootPolicies` mapping | Required only if the selected NativeUfs/VerifiedRoot route enforces signed policies | No path or bundle is configured; no policy bytes are present | Validate VROOTB01 structure, signed policy/key provenance, same userdata windows and kernel policy consumer; then observe authenticated root |
| Platform seed | `--unique-chip-id HEX` / `UNIXNU_UNIQUE_CHIP_ID` → ADT identity fields | Required by current onyx (`unique_chip_id = "required"`); not a trust/Data/root file | Deliberately absent from this audit and all repository artifacts | Supply locally, never log it; verify only that the same local value was used for the paired build and device |

“Optional” above means optional to the generic host writer. It does not mean
that the chosen kernel, AMFI policy, NativeUfs implementation, or root route
will boot without the input.

## Trust-cache input

The selected OS profile is `ipados-17.7.11-21H461` and records two public
trust-cache source components (`StaticTrustCache` and
`Cryptex1,SystemTrustCache`). It publishes accepted SHA-256 pins in the OS
profile and the board may narrow them further with
`[payload].trust_cache_sha256`. The current onyx board does neither. The public
profile's first 21H461 bundle pin is documented in the profile and in the
existing readiness record; this audit intentionally does not copy a trust
bundle or any owner/private value.

`payload.py` behavior is precise:

1. `--trust-cache` is optional. If present, the file must exist.
2. If the board supplies an allow-list, a normal `--trust-cache` file must have
   one of the listed SHA-256 values. `--owner-trust-cache` deliberately skips
   this board allow-list because it is an owner-signed route.
3. A supplied trust cache is copied to `kernel.macho.trustcache` and causes a
   16-byte `TrustCache` entry in ADT `/chosen/memory-map`.
4. DarwinBoot accepts one sidecar of one to 128 version-2 modules. Each module
   must fit its offset table, contain exactly its declared entries, use a hash
   type from 1 through 4, and have strictly ascending 20-byte hashes. These are
   loader structural checks, not proof that AMFI will accept every process.

For an eventual onyx build, the trust bundle must be selected from the target
21H461 IPSW/profile route, or be an explicitly documented owner bundle paired
with the kernel/addon route. Do not reuse a trust bundle from sheng, dada,
pagani, another IPSW build, or another device merely because its file format
looks valid.

### Offline checks

- Verify the input file exists and hash it locally without putting the value in
  a public manifest.
- Verify the OS/profile pin (normal route) or record the owner-bundle provenance
  privately (owner route).
- Parse the DarwinBoot module table and ascending hash rules.
- Verify the payload sidecar hash, FAT path and `payload.json` agree.
- Verify the ADT contains `TrustCache` exactly when the sidecar is present.
- Verify the kernel, trust bundle, optional addon and Data seed came from the
  same build record.

### Hardware checks

- DarwinBoot reports/loads the sidecar without a malformed-cache error.
- XNU trust-cache runtime initializes and the first required launchd/process
  exec is accepted.
- A no-trust control is useful only if the selected kernel explicitly proves a
  no-AMFI/no-trust route; it cannot be treated as a root-qualified image.

## Data seed input

The generic payload writer copies a supplied Data seed to
`Payloads/scratch-data.img`. The ADT mapping is `PackedRAMDisk` when
`[payload.adt].packed_data_ramdisk = true`, otherwise `RAMDisk`. A nonpersistent
seed also adds the `ephemeral-storage` chosen property. The current onyx board
has no Data configuration beyond the required platform-seed field, so no Data
route is currently selected.

The runtime preparation code adds stricter conditions:

- A kernel with `CONFIG_XNU_OWNER_DATA_MOUNT` refuses a payload without
  `--data-ramdisk`, even if persistent Data is intended.
- A missing seed is never silently regenerated. An existing installation must
  pass its preserved original seed; first installation must explicitly use
  `--init-data` and the configured seed builder.
- A seed's packed APFS extents must contain exactly one discoverable volume UUID
  for the runtime preparation path.
- If the seed UUID differs from the compiled
  `CONFIG_XNU_OWNER_DATA_VOLUME_UUID`, the kernel must be rebuilt for a new
  first-install seed; this is not fixed by changing the ADT alone.
- `--skip-setup` edits a copy and therefore must be recorded as a new seed,
  never silently substituted for the preserved original.

The Data seed is private installation state. This audit records no path,
actual UUID, hash, APFS bytes, owner metadata, or seed contents. A future
private build manifest may record a redacted input identifier or hash only in a
local ignored file, paired with the exact kernel and payload hashes.

### Offline checks

- Confirm the route (preserved seed versus explicit first install) before
  building.
- Verify file existence, format, packed extents and one-volume identity.
- Verify the seed's UUID against the compiled kernel configuration.
- Verify the Data sidecar, ADT mapping name and payload report agree.
- If a `skip_setup` copy is used, preserve the original and record the copy's
  private hash locally.

### Hardware checks

- DarwinBoot publishes the expected RAMDisk/PackedRAMDisk mapping.
- The Data block provider finds the seed and the expected APFS Data volume.
- XNU mounts `/private/var`; then observe launchd and setup behavior. A payload
  containing a seed but failing to publish/mount it is not Data-qualified.

## Root and userdata contract

The 21H461 profile identifies the OS as iPad7,1/J120 and describes `OS` plus
optional `Cryptex1,SystemOS` userdata windows. The generic userdata builder
creates a raw SHNGROOT image with a 4096-byte manifest, 1 MiB-aligned windows,
SHA-256 entries, and a manifest checksum. Window entries use block size 512 and
read-only flags. Optional data objects use version 2, 4096-byte blocks and
flags 3; these are kernel-read objects, not block devices.

The current onyx board has **no `[userdata]` section**. Therefore the following
are not yet a selected or buildable onyx root contract:

- target userdata GPT first/last LBA and logical-sector size;
- a source IPSW's exact OS/SystemOS disk members;
- SHNGROOT v1/v2 window order and offsets;
- root APFS volume UUID binding;
- NativeUfs/VerifiedRoot component and its root-policy bundle.

The public 21H461 profile contains an OS volume UUID for its own iPadOS image.
That value is not evidence that an onyx UFS driver can find or mount it, and it
must be rechecked against the exact userdata windows extracted from the same
IPSW. A root policy bundle, if later selected, must be generated/signed for
those exact windows and the exact policy consumer. A `VROOTB01` header is only
a structural contract: version 1, one to 16 policy records, total-size field
matching the file, and bounded size. It is not an authentication result.

### Root-route choices

1. **Bring-up/no-root route:** build only enough payload to test firmware,
   menu, DarwinBoot and XNU console. Do not claim root or userland. Trust/Data
   can be absent only if the selected kernel configuration permits it.
2. **Read-only SHNGROOT route:** add a board-owned UFS component and `[userdata]`
   OS/SystemOS windows, with the exact target GPT geometry and profile volume
   binding. This still needs the required trust/Data inputs for the selected
   XNU configuration.
3. **Verified-root route:** additionally select the VerifiedRoot policy
   component, generate policy objects from the same userdata image, place them
   as version-2 kernel-read objects or the board's documented policy input,
   and verify signatures/keys locally. No policy bytes are currently available
   for onyx.

No route may be inferred from the historical onyx payload. The existing
historical/synthetic payload has no qualified trust cache, Data seed, root
policy or onyx UFS contract and is explicitly prohibited for device use.

## Same-build consistency matrix

The following must all be tied to one private build record before any device
candidate is considered:

```text
OS profile/IPSW build + source revisions
  ├─ prelinked kernel.macho
  ├─ exact trust-cache route (normal or owner)
  ├─ exact Data seed route/seed (or explicit no-Data route)
  ├─ exact userdata OS/SystemOS windows and GPT geometry
  ├─ exact root UUID / VROOTB01 policy route, if selected
  ├─ generated ADT (mapping names reflect present sidecars)
  ├─ payload FAT + payload.json
  ├─ Mu-Silicium FD containing matching DarwinBoot/UniXNU stack
  ├─ firmware DTB used by bootimg
  └─ boot.img readback
```

A hash or size from a different OS build, device, kernel, UEFI FD, Data seed,
trust route, or userdata image cannot be carried forward as if it were the
same candidate. Android `fastboot boot` acceptance is not a trust/root result.

## Current decision and blockers

- **Current status:** audit-only; no private input was copied or generated.
- **Allowed now:** host-side contract checks, public profile/schema inspection,
  and documentation.
- **Not allowed to claim:** root readiness, AMFI readiness, Data readiness,
  userdata readiness, or hardware boot.
- **Before a full onyx payload:** choose and implement the onyx UFS/root route;
  add exact userdata geometry/windows; decide normal versus owner trust route;
  obtain a private preserved/new Data seed if the kernel requires owner Data;
  obtain the local platform seed; generate an ADT from real onyx memory/EFI
  evidence; and verify all same-build hashes.
- **Device gate:** only after offline readback passes and the fixed Mu/menu
  baseline is reproduced; then use `fastboot boot` only, with no partition
  flash, and record DarwinBoot, XNU, root and userland observations separately.
