# Active Android 17 partition extraction

The device is on slot `_b` (`ro.boot.slot_suffix=_b`). Using KernelSU root and `adb exec-out su -c dd`, the following active partitions were extracted read-only to the ignored private directory `private-inputs/runtime-android17-20261114/partitions/`:

| Partition | Bytes | SHA-256 | Notes |
| --- | ---: | --- | --- |
| `boot_b` | 100663296 | `1e87310bc9b29f29a529e195fa093dde173e2136dd4f82c7ec006b65a2667257` | Byte-identical to supplied Android 17 archive `boot.img` |
| `vendor_boot_b` | 100663296 | `db1c5fb9448c286637fee7f326d69253587de4c930d3c33ce9d397c4d6736544` | Byte-identical to supplied `vendor_boot.img` |
| `dtbo_b` | 25165824 | `15076632b3ba76bca23ef009ea6626c4c9e87cec319ddad72eb3b62db37f03bc` | Declared DTBO table is identical; partition has a larger padded tail than archive |
| `vbmeta_b` | 131072 | `77b34032a7c5ca1e236d4a1289b292993aa695e19b7bab0493075cef2ff1bbf0` | AVB magic `AVB0` |
| `init_boot_b` | 8388608 | `b8e8095c0dec6dd8466dfc387aa672f50afb717d1cfe9dfbc7a4d6256d238c17` | Android boot header v4, ramdisk 3062751 bytes, no kernel |

The active partition checks confirm that the supplied Android 17 archive is the currently booted build for the active boot/vendor_boot content. `dtbo.img` from the archive is a shorter packaged copy, but its declared table header and table bytes match the active partition; the difference is padding/tail capacity, not a different selected overlay.

No partition was written, and no AVB/slot state was changed. These are source/runtime evidence artifacts, not UniXNU boot images.
