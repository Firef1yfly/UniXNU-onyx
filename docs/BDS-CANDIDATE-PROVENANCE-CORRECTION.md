# Candidate artifact provenance correction

Important: `/tmp/onyx-bds-candidate-image/boot.img` (hash `e63db8864ef0d51027da07c6a7fd0d48a1cd7b54b0aaadc1683a93e65ad5a2cd`) was assembled with the earlier mixed diagnostic FD `7910f75c3cbbcd3db12d90a6208a6a6edb6e65e920898656900aa8235d6775ea`. It is **not** the isolated Mu-first BDS build.

The isolated Mu-first FD is:

```text
066d1a9427dab62e72c88094a3e9f4aae9478fa6ad76b4370e61eb82cbab6e58
```

A matching isolated boot image has not yet been assembled because the host command runner currently returns `UNKNOWN: unknown error, write` for shell commands. Do not use the older e63 image to judge the isolated BDS fix.
