#!/usr/bin/env bash
# Assemble the isolated Mu-first BDS experiment. Never flashes or boots a device.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
UNIXNU=${UNIXNU:-"$ROOT/../unixnu"}
DEVICE=${DEVICE:-/tmp/onyx-package-map}
UEFI=${UEFI:-/tmp/onyx-uefi-shim}
FD="$UEFI/Build/onyxPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd"
DTB=${DTB:-/tmp/prior-onyx-analysis/dtb-3145856}
RAMDISK=${RAMDISK:-/tmp/prior-onyx-analysis/ramdisk}
OUT=${OUT:-/tmp/onyx-bds-isolated/boot.img}
EXPECTED_FD=066d1a9427dab62e72c88094a3e9f4aae9478fa6ad76b4370e61eb82cbab6e58
EXPECTED_DTB=6379d64c8472c7c4c2d9d225803bebe33b8bd2c14cb73c6b329a8a5458dd6f23
EXPECTED_RAM=be6aeabf340f604868c5093966729dc0b75b28233a70cd34266c0f01dd108

for p in "$UNIXNU/unixnu" "$DEVICE/board.toml" "$FD" "$DTB" "$RAMDISK"; do
  test -f "$p" || { echo "missing required Mu-first input: $p" >&2; exit 1; }
done
actual=$(sha256sum "$FD" | awk '{print $1}'); test "$actual" = "$EXPECTED_FD" || { echo "FD hash mismatch: $actual" >&2; exit 1; }
actual=$(sha256sum "$DTB" | awk '{print $1}'); test "$actual" = "$EXPECTED_DTB" || { echo "historical DTB hash mismatch: $actual" >&2; exit 1; }
actual=$(sha256sum "$RAMDISK" | awk '{print $1}'); test "$actual" = "$EXPECTED_RAM" || { echo "historical payload hash mismatch: $actual" >&2; exit 1; }
test ! -e "$OUT" || { echo "refusing to overwrite existing output: $OUT" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"
python3 "$UNIXNU/unixnu" bootimg -D "$DEVICE" --uefi "$UEFI" --fd "$FD" --dtb "$DTB" --ramdisk "$RAMDISK" --output "$OUT"
sha256sum "$OUT"
echo 'Mu-first BDS candidate assembled; no device operation performed.'
