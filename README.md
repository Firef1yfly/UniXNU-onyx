# UniXNU — Redmi Turbo 4 Pro (onyx)

**Experimental reconstruction; no successful device boot is claimed.** The original configuration remains in `origin/main`; development takes place on `rebuild/onyx-evidence-first`. Nothing has been pushed or flashed.

## Current scope

- Target: Redmi Turbo 4 Pro, codename `onyx`, SM8735.
- Provisional OS profile: upstream `ipados-17.7.11-21H461`, not a custom `ios-*` profile.
- `board.example = true` deliberately prevents treating unfinished inputs as production configuration.
- The selected generic components are not proof of storage, display, touch, GPU, network or power support.
- Active stock-image baseline: the user-reported Android 17 archive; see [current-image inspection](docs/CURRENT-ANDROID17.md). Earlier loose Android 16 images are historical only.
- A minimal local [SM8735 profile](soc/README.md) now describes confirmed core resources. It is not a complete shared platform implementation.
- The selected minimal DTS retains zero-size DRAM until runtime evidence is available; neither kernel nor firmware is build-qualified.
- Binding tests require `dtc` and the local main-checkout ADT zero-DRAM rejection fix documented in the current-image inspection.
- [UEFI handoff audit](docs/UEFI-HANDOFF.md) identifies BootShim header/x0 issues and unresolved SEC buffer ownership. A tested source patch is a candidate only, not applied to the original firmware.
- Use the offline [runtime-memory evidence guide](docs/RUNTIME-MEMORY.md) to distinguish static image trees from actual runtime captures; no RAM range is inferred automatically.
- The [C handoff planner](package/HandoffPlan/README.md) is host-tested and cross-compiles, but has no firmware integration, physical memory access or allocation side effects.

See [reconstruction status](docs/ONYX-REBUILD.md) for source pins, missing inputs and the next measurements. [porting.toml](porting.toml) tracks subsystem status; all areas remain planned.

## UEFI build result

A reproducible DEBUG Mu-Silicium UEFI build now succeeds in an isolated tree based on Firef1yfly/Mu-Silicium commit `f77f9457b82f4a1dd33a305ab6ff12591347d416`, with the onyx PE file alignment changed to `0x1000` so GenFv accepts DiskIoDxe. The build includes UniXNU, UniXNURamDiskDxe, UniXNUDxe, DarwinBoot, DiskIo, Partition, UnicodeCollation and FAT.

```sh
PATH="$HOME/.local/bin:$PATH" CLANGPDB_AARCH64_PREFIX=aarch64-linux-gnu- \
  build -p Platforms/Xiaomi/onyxPkg/onyx.dsc -a AARCH64 -b DEBUG \
  -t CLANGPDB -n 2 -D FD_BASE=0xa7100000 -D FD_SIZE=0x300000 \
  -D FD_BLOCKS=0x300 -D DEVICE_MODEL=onyx -D ENABLE_SECUREBOOT=0
```

The verified 3 MiB firmware volume is `artifacts/SILICIUM_UEFI-onyx-DEBUG.fd`, SHA-256 `afa660579c245ca8d5bc8e474ed45428b99233341e552cbb52045536bf111eb5`. A separate candidate image combines the 112-byte handoff-fixed BootShim with that FD; it is host-built only and has SHA-256 `ecd4b4f060b257d8f3b4433584ccdf3de10624634a394ae16f840a833afe68fe`.

The BootShim fix writes the shim-plus-FD image size and preserves runtime `x0` rather than replacing it with a static appended DTB. It is source/host validated, not yet device validated. The connected Android 17 device supplied a live FDT hash `2c4ed066c378da1c56bca564c0bb221f7652d3367f5d27f57f2e4cc4f7364b18` with initrd `0xb5921000..0xb7ffeb04`; this does not prove custom UEFI allocator ownership or successful boot.

The first physical test was performed with `fastboot boot` only, never `fastboot flash`. A menu-only 64 MiB FAT payload was packed into Android v4 image `menu-boot.img` (SHA-256 `2129bc06f2073c389a5838315e5a8855bb382322718f8c343119f8887b7cbccf`). Fastboot accepted and reported `Booting OKAY`, but the phone remained black and did not expose ADB; after `fastboot reboot`, Android recovered on slot `_b` with `sys.boot_completed=1` and `ro.boot.bootreason=bootloader`. No pstore output was available. This is a failed/unobserved UEFI-menu test, not evidence of bootability. Do not repeat the test without serial/USB handoff logging.
The local Mu repository has commit `48d309fa9c5c360d57d2ce4dc2fce1cdb82b6d23` containing the BootShim/alignment fixes and copied UniXNU/DarwinBoot sources. The requested GitHub remote is configured, but publishing was not possible because this environment has no GitHub credentials (`git push` failed while reading the HTTPS username). No flash command or partition write was performed.


```sh
python3 -m unittest discover -s tests -v
python3 scripts/check-inputs.py --unixnu ../unixnu
python3 scripts/check-inputs.py --unixnu ../unixnu --json
python3 ../unixnu/scripts/porting-record.py check --device .
```

The input check is **expected to fail** until the missing sources and board evidence are supplied. It performs no network request, build, adb/fastboot command or device write. A passing lint result is not a successful build or a safe/bootable image. The independent porting-record check validates record structure only.

The checker uses a private, local `inputs.toml` evidence index, not an upstream board schema extension:

```toml
[device]
name = "onyx"
firmware_version = "<version of the captured stock firmware>"
[memory]
source = "<path or URL identifying original onyx board evidence>"
sha256 = "<SHA-256 of that original evidence>"
```

Do not fill this with guessed values or hashes of an unrelated board. The checker validates declaration format, not authenticity or complete memory-map safety. Keep identity seeds and private captures out of Git.

## Bring-up order

1. Verify official onyx DTS against the selected SKU and stock/live DT; establish RAM and reservation evidence.
2. Implement and validate the complete SM8735 shared profile and its source pins.
3. Review the existing onyx Mu-Silicium integration and handoff against the same hardware inputs.
4. Resolve sources, compile ADT, build kernel/package/firmware/payload, and validate image format.
5. Only then test firmware, loader, kernel and root separately on the device with recovery available.

Common references: [porting](https://unixnu.com/porting/), [SoC support](https://unixnu.com/porting/soc-support), [device repository](https://unixnu.com/porting/device-repository), [bring-up](https://unixnu.com/porting/bring-up).
