# Host verification

## Round 18 runtime ADT gate

The complete privileged runtime FDT was passed directly to `scripts/make-adt.py` with the runtime-derived platform seed. The converter rejected it before writing an ADT:

```text
ADT handoff requires one contiguous DRAM range
```

This confirms the current UniXNU ADT contract cannot consume Android's fragmented/reservation-oriented `memory/reg` directly. No bank was cropped, merged or invented. The correct next input is a verified UEFI usable-memory map plus early FDT/initrd ownership; a synthetic 1 GiB range remains host-test-only.



The corrected full 59-patch chain applies and the temporary XNU build now completes. Kernel SHA-256: `6954c1b2b61802fc4df17564d07a3ad090bca46d6cc23e1dcc20d9cc528b3f70`. Package build also completes and produces UniXNU EFI modules.

A first payload attempt correctly rejects zero DRAM. A separate host-only pipeline test used an invented 1 GiB RAM range and produced a 192 MiB payload (`2b5efc601e617382243f93127ba1a4a14e48239fd77dc82abe61b8fdffebba2b`); it is explicitly not for the device. See [kernel/payload host report](KERNEL-PAYLOAD-HOST.md).



The earlier temporary build that omitted the architecture and OS series was stopped; it is not a valid port build. All four architecture, SoC, OS and device series are restored in the temporary configuration. The actual ordered 59-patch chain now applies to XNU `d8b80295118ef25ac3a784134bcf95cd8e88109f`: the only removed hunk from the common boot-progress patch was diagnostic instrumentation that required an unselected Sheng-specific PMGR patch. Both prelink patches remain selected. Regression tests reproduce the old failure and verify the corrected full chain.

The existing local DriverKit/TrustCache manifests let the upstream preparation script restore 26 public headers with Git blob hash verification. No GitHub token was needed.

| Upstream host check | Result |
| --- | --- |
| `check-xnu-granules.py` | BCM2837: 4096 bytes, TG0=0/TG1=2; VMAPPLE control: 16384 bytes, TG0=2/TG1=1 |
| `check-native-4k-policy.py` | All five RAM boundary cases pass in each of the native 4K, Apple 4K and Apple 16K profiles |
| `check-code-signing-granules.py` | Eight extracted-gate cases pass after supplying Darwin `EBADEXEC=85` to the generated host probe only; Linux libc lacks this constant. No kernel logic changed. |

These checks verify compiler-visible granules and selected source policies. They do not prove on-device MMU setup, full signature validation, RAM ownership, or boot success. The 4 KiB XNU page granule is independent of the firmware's PE file/section alignment issue below.


## Boot preparation gate

The requested test boot image was **not generated** because the official packager correctly refuses this unfinished repository:

```text
scripts/package.sh --check --os ipados-17.7.11-21H461 --uefi /home/firefly/UniXNU/Mu-Silicium
... is an EXAMPLE device repository (example = true in board.toml)
exit 1
```

The independent input gate also remains failed closed: `board.example` is intentionally true, `inputs.toml` provenance is absent, and static DRAM is unresolved. The provisional DTS does compile to `/tmp/onyx-bringup.dtb` (2144 bytes, SHA-256 `53c6dee14db92effc6a638a801027b08bdf3496486d5b630ebe38c4ed732b2e5`), but it contains zero placeholder DRAM and is not suitable for a boot image.

No flags bypassed the example guard, no fake memory/identity seed was inserted, and no image was flashed. A real test boot requires runtime memory evidence, a platform seed, completed firmware/SEC handoff ownership, and a successful package/firmware/payload chain first.

## Round 15 kernel build attempt

A temporary board copy removed the stale Android/iPad diagnostic `zzz-boot-progress.patch` from its selected patch series; the production UniXNU tree was not changed. The retry then failed in `prepare-xnu-source.py` because anonymous GitHub API requests for omitted DriverKit/TrustCache headers returned HTTP 403 rate-limit exceeded. A partial temporary header cache exists, but it is not complete or authenticated and was not used to claim a kernel build.

No XNU kernel, prelinked kernel or payload was produced. The device remains recovered in Android; no new fastboot command was run.



The connected phone is still visible only in adb mode; `fastboot devices` is empty. The diagnostic image metadata is valid Android header v4 but has no kernel/payload and must not be started as a system image.

A temporary kernel build was attempted with the existing cached IPSW kernelcache and local XnuPrelink source. It reached XNU patch application but failed at `patches/xnu/zzz-boot-progress.patch` against `bsd/kern/bsd_init.c:773`; no kernel artifact was produced. This is an OS-profile/source revision mismatch, not a device boot result. No phone operation occurred.



The temporary Mu-Silicium build now succeeds after changing only temporary `onyx.dsc` PE file alignment from 0x200 to 0x1000. FD: 3145728 bytes, SHA-256 `57a10bba078e8251ab05df795510ed8d0c4e7c86b4fcf34af2f60cb65b7dfc1e`.

A diagnostic Android v4 boot image was assembled with the complete private runtime FDT and the patched BootShim:

- path: `/tmp/onyx-package-check/out/boot/boot.img`
- bytes: 4001792
- SHA-256: `7a1e4e21017060dc3d7ddcc5b4b3df3fc08f3536088a57f6678d32a358f64ddb`
- ramdisk: 0 bytes
- no XNU kernel, no FAT payload, no UniXNU menu
- hardware-tested: false

This is a diagnostic artifact only, not a bootable UniXNU/iOS image. No phone operation occurred. Full details: [diagnostic boot report](DIAGNOSTIC-BOOT.md).



A temporary copy of Mu-Silicium was created at `/tmp/onyx-uefi-shim`; the candidate BootShim patch was applied there only. UniXNU built BaseTools and started the EDK2 onyx build with:

```text
./unixnu build firmware -D /tmp/onyx-package-check \
  --uefi /tmp/onyx-uefi-shim \
  --edk2 /home/firefly/UniXNU/Mu-Silicium/Mu_Basecore \
  --skip-preflight -j 2
```

The build failed during `GenFv` before producing a new FD:

```text
PE image Section-Alignment and File-Alignment do not match: ...DiskIoDxe.ffs
GenFv: ERROR 3000: Could not rebase ...DiskIoDxe.ffs
```

No production checkout changed and no FD/boot image was installed. This is a real firmware-toolchain/integration failure, separate from the earlier BootShim header failure. The next fix must align the DiskIoDxe build output or disable/rebuild that duplicate FV module in the temporary firmware source; it must not be worked around by using the stale 7-Nov FD. The current Mu source and original device remain unchanged.



- Device suite: 54 tests passed, including bounded Android-image extraction tests.
- Porting record: 13 structured areas checked, exit 0.
- UniXNU status: resolved with the tracked local SoC profile and explicit XnuPrelink source.
- Android 17 archive SHA-256 remains `cfb7b8f2c0a026ceecab61a781f6ce0e4b4d010ab09676b13cf30ec0650d50f3`.
- `git diff --check`: exit 0.

This remains host-only progress. The board is still `example=true`; no runtime DRAM, EFI map, FDT/initrd ownership or real-device boot evidence exists.
