# Round 25 complete-image preparation gate

The host has a real kernel and temporary diagnostic FD:

- kernel SHA-256 `6954c1b2b61802fc4df17564d07a3ad090bca46d6cc23e1dcc20d9cc528b3f70`
- EFI FD SHA-256 `e31f5dbd540411db1ce92af941693fc0ad2710b53ca7ca799d2d08f8b639b5e6`

The only existing 192 MiB payload was made with synthetic `<0 0x80000000 0 0x40000000>` DRAM and is not a device artifact. It is quarantined/never passed to fastboot. The direct real runtime FDT ADT command still rejects with `ADT handoff requires one contiguous DRAM range`, so no complete real payload or boot.img is assembled in this round.

The connected phone remains Android on `_b`; no fastboot command or partition write occurred. A complete boot image is blocked until EFI map/RAM partition output identifies a real safe contiguous handoff range and the initrd/FDT reservation is integrated.
