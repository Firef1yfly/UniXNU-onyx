# onyx reconstruction status

This checkout is an evidence-first reconstruction of UniXNU for the Redmi Turbo 4 Pro (`onyx`). It is **not** a bootable-port claim.

## Source hierarchy

1. **Board hardware source (primary):** Xiaomi MiCode `kernel_devicetree`, branch `onyx-v-oss`, commit `2e51db4a1ea216ef69122485bf53161743da55b7`.
   - Overlay: `qcom/onyx-sm8735-overlay.dts`
   - Board DTSI: `qcom/onyx-sm8735.dtsi`
   - URL: https://github.com/MiCode/kernel_devicetree/tree/2e51db4a1ea216ef69122485bf53161743da55b7
2. **Kernel implementation source:** Xiaomi `Xiaomi_Kernel_OpenSource`, branch `onyx-v-oss`, commit `58e48d87fdc02f1e2978547f75ea524962217cc5`.
   - URL: https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/58e48d87fdc02f1e2978547f75ea524962217cc5
3. **Local firmware source:** `/home/firefly/UniXNU/Mu-Silicium`, commit `f77f9457b82f4a1dd33a305ab6ff12591347d416`.
   - This is source/configuration evidence only. Its onyx DTS still has a zero DRAM range, so it is not used as a RAM inventory.
4. **UniXNU SM8735 feed:** the incomplete absolute home-directory dependency has been replaced by the tracked local `soc/` development profile. Core bindings compile and parse; full platform support and a public source pin are still pending.
5. **Current stock-image baseline:** [Android 17 archive inspection](CURRENT-ANDROID17.md), identified by the user as matching the running device. Earlier loose images are user-identified Android 16 and remain [historical evidence](STOCK-IMAGES.md) only. Both sets retain zero-size static DRAM placeholders; runtime geometry remains unknown.

## Current gates

- The only available OS profile selected here is the upstream `ipados-17.7.11-21H461`; an `ios-17.7.11-21H461` profile does not exist in UniXNU.
- `board.example = true` remains deliberate until hardware inputs and the complete source graph are supplied.
- DRAM base/size, reservations, UFS geometry, panel/GOP details, platform seed and device boot results are unresolved.
- `scripts/check-inputs.py` is the fail-closed host-side gate. A passing check means only that declared inputs are structurally complete; it never proves that the phone boots.
- No adb/fastboot device was connected during this audit, and no flashing or boot operation was performed.

## Required next evidence

1. Obtain the runtime onyx DT or bootloader memory map and record its hash, selected SKU/board ID, actual DRAM ranges and reserved-memory map. Static stock trees have already been acquired and are insufficient for DRAM.
2. Publish or locally validate a complete `UniXNU-sm8735-common` source with `soc.toml`, DTSI, config and patch ownership.
3. Match UEFI memory reservations, display handoff and boot-header inputs against the same board evidence.
4. Add only components whose SM8735/onyx interface and firmware inputs are identified; then resolve `status`, compile the ADT, and build on a host.
5. Perform device bring-up only after the host build gates pass, recording firmware/image/source revisions separately from source inspection.
