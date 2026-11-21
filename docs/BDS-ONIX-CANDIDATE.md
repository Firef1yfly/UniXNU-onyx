# Round 64 Mu-first source deviation audit

After the BDS candidate black screen, a diff audit of `/tmp/onyx-uefi-shim` against the tested Mu source shows the temporary firmware still contains **five independent deviation groups**:

1. BootShim x0/image-size candidate patch;
2. OnyxMapDxe and AdvancedLogDxe integration;
3. board-local PlatformBootOptionsLib candidate;
4. ramdisk/QR APRIORI reorder;
5. AdvancedLogger PCD/library mappings and PE `/FILEALIGN:0x1000`.

The historical tested source used the unmodified `BootShim/BootShim.S`, `/FILEALIGN:0x200`, and original APRIORI/FDF. Therefore the current BDS candidate is not a one-variable reproduction of the user's previously working Mu → UniXNU path. Its black-screen result cannot prove the BDS library candidate wrong.

The current next experiment should restore the tested Mu source exactly, then apply **only** the OnyxBootOptions library candidate (no x0/QR/Map/APRIORI/PE-alignment changes) to isolate the `No Operating System Found` fix. This may require building in a fresh/reflink tree; do not modify the original Mu checkout. Device testing remains paused until that isolated image exists and a recovery/log plan is ready.
