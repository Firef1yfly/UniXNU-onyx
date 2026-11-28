# The milestone-1 on-device ladder

`scripts/device-ladder.py` turns 阶段 2.6 of the port design into a command that
records evidence instead of printing an opinion. It exists because the same
`fastboot boot` file has produced `Booting OKAY` and
`Failed to load/authenticate boot image: Load Error` on this board depending on
what the previous attempt left behind, because the ABL adds the arm64 header's
`text_offset` to the jump address, and because the panel is dark until the second
stage — so neither the acknowledgement, the header, nor the screen can be read as
"the firmware ran".

Three rules follow, and the script enforces all of them:

1. **Bind the image hash.** `boot` refuses unless the file's SHA-256 equals
   `--confirm-sha256`, so a result can never be attributed to "whatever was in
   `out/` at the time".
2. **Refuse a stale header.** `boot` refuses an image whose ARM64 `text_offset`
   (offset 8, little endian) is not `0`, naming the value it found. A non-zero
   field is downloaded and never executed: the CPU is sent past the end of RAM.
3. **Never write to the device.** There is no `flash`, `erase`, `oem`, `format`,
   `write`, `wipe`, `set_active`, `sideload`, `update` or `partition` path in
   the script. `safety` prints the audited allowlist:

   ```
   fastboot devices            fastboot -s <serial> devices
   fastboot -s <serial> getvar <name>       name from GETVAR_NAMES only
   fastboot -s <serial> reboot-bootloader   only with --cold-restart
   fastboot -s <serial> boot <image>        only after the two checks above
   adb devices                 adb -s <serial> devices
   ```

   Forbidden argument substrings are also rejected positionally, so a future
   `fastboot` verb cannot be smuggled through the allowlist.

## Procedure

```sh
# 0. Read-only. What is attached, and in what state?
python3 scripts/device-ladder.py probe

# 1-2. One attempt, bound to one hash, from a fresh bootloader.
python3 scripts/device-ladder.py boot \
  --image /home/firefly/文档/onyx-porting/out/onyx-menu-boot.img \
  --confirm-sha256 83e75046304d6983a6e211e445737e1917d24c35f06e48f7be7e84deb6b492df \
  --cold-restart
```

`boot` writes `docs/bringup/ladder-<UTC>.json` (schema_version 1) and prints the
verdict plus what it proves and does not prove. The record binds: the image path,
size, SHA-256 and parsed header; the `--confirm-sha256` the caller gave; the
safety allowlist actually in force; the pre- and post-bootloader state; the
`fastboot boot` command and its exit status; the polled timeline; and the
verdict with its interpretation.

`--cold-restart` first issues `reboot-bootloader` and waits for the bootloader to
come back, so the attempt is bound to a freshly re-initialised bootloader. Without
that flag the record says so, and a `load_error` can only be attributed to
"this bootloader state", not to the image.

`probe` is read-only and issues no `boot`. `safety` issues no device command at
all.

## Reading the verdict

Only one verdict is positive:

| verdict | meaning | rule |
| --- | --- | --- |
| `disconnected_after_boot` | download acknowledged, device left USB and stayed away for the whole window | the strongest host-side signal that the image was executed; still says nothing about which stage it reached |
| `accepted_and_returned_to_fastboot` | device never left USB | **not a pass.** This is the signature of an image that was downloaded and never executed |
| `disconnected_then_returned_to_fastboot` | left USB, came back inside the window | a reset, not progress |
| `load_error` | refused before execution (or exited non-zero) | the bootloader state, not necessarily the image, may be the cause; retry only after `--cold-restart` |
| `boot_command_timeout` | the transfer itself stalled | cold restart before the next attempt |
| `cold_restart_failed` | bootloader did not come back | not a usable test target this run |
| `no_device` | nothing attached | nothing was touched |

Two consequences worth stating plainly, because both were paid for in device
time:

- **A single `Booting OKAY` is never a pass.** The record stores
  `acknowledged_booting_okay` beside the verdict precisely so the two cannot be
  confused later.
- **The screen is not a signal.** A stock boot shows no logo until its second
  stage, so a dark or grey panel is consistent with progress, with a hang and
  with a watchdog reset. The verdict is derived from the polled device-presence
  sequence, not from pixels and not from the transfer string.

## The positive control

Before trusting a negative result from a real image, run a shim that branches to
itself forever with `text_offset` 0. It cannot return, so if the device stays off
USB the harness's `disconnected_after_boot` reading is demonstrated end to end.
That experiment is what showed the ABL was jumping to `load_address +
text_offset`: with the firmware base in that field the device came back to
fastboot in about a second, and with the field zeroed it did not come back at all.

## What milestone 1 still requires

The ladder is the evidence channel, not the milestone. Milestone 1 is met only
when **the same SHA-256** cold-boots to an interactive UniXNU menu three times
with a saved log each time (阶段 2.6 step 3-5: BDS starts `UniXNU.efi`, the menu
is visible and accepts input, and the payload volume is listed). Steps 3-5 are
read from the panel and the QR log export, because the host-side harness cannot
see them; their observations belong in the same record's `warnings`/`anomalies`
by hand, or in a follow-up note that names the same image hash.

The harness's own unit tests are mocked host-side evidence: `tests/test_device_ladder.py`
drives stub `fastboot`/`adb` binaries in a temporary directory and proves the
refusals, the verdict state machine and the record shape. It says nothing about
the phone, and neither does this document.
