#!/usr/bin/env python3
"""Build and verify a menu-only UniXNU FAT probe.

This image deliberately contains only ``EFI/UniXNU/unixnu.toml``.  It has no
kernel, ramdisk, driver, DarwinBoot image, or device-tree payload.  The probe
is useful only after the UniXNU UEFI application has already been started.

Important: UniXNU's Menu.c treats ``timeout = 0`` as an immediate boot of the
default entry.  Therefore this tool rejects zero for a menu-only image and
uses a negative timeout instead.  With no physical input, UniXNU still uses
``fallback_timeout``; that is a firmware menu policy, not an infinite wait.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

MARKER = "MENU_ONLY_PROBE"
MENU_PATH = "::/EFI/UniXNU/unixnu.toml"
DEFAULT_SIZE_MIB = 64
DEFAULT_SECTORS_PER_CLUSTER = 1
DEFAULT_FALLBACK_TIMEOUT = 86400
FAT32_MIN_CLUSTERS = 65525


def effective_timeout(timeout: int, has_input: bool, fallback_timeout: int) -> int:
    """Model Menu.c:114-120's timeout selection in milliseconds.

    A return value of zero means immediate default-entry selection.  A
    negative return value means wait for input; when no input exists the
    firmware substitutes fallback_timeout seconds.
    """
    if timeout < 0:
        return -1 if has_input else fallback_timeout * 1000
    return timeout * 1000


def inspect_bpb(image: Path) -> dict[str, int | str]:
    """Read the FAT BPB and apply Mu EnhancedFatDxe FAT32 invariants."""
    data = Path(image).read_bytes()
    if len(data) < 512 or data[510:512] != b"\x55\xaa":
        raise ValueError("invalid FAT boot signature")
    bps = int.from_bytes(data[11:13], "little")
    spc = data[13]
    reserved = int.from_bytes(data[14:16], "little")
    fats = data[16]
    total16 = int.from_bytes(data[19:21], "little")
    spf16 = int.from_bytes(data[22:24], "little")
    total = total16 or int.from_bytes(data[32:36], "little")
    spf = spf16 or int.from_bytes(data[36:40], "little")
    root_entries = int.from_bytes(data[17:19], "little")
    if bps != 512 or spc == 0 or (spc & (spc - 1)) != 0:
        raise ValueError("unsupported FAT sector or cluster geometry")
    if reserved == 0 or fats == 0 or total == 0 or spf == 0:
        raise ValueError("incomplete FAT BPB")
    root_dir_sectors = ((root_entries * 32) + bps - 1) // bps
    first_cluster_lba = reserved + fats * spf + root_dir_sectors
    clusters = (total - first_cluster_lba) // spc if total >= first_cluster_lba else 0
    fat32 = root_entries == 0 and spf16 == 0 and spc >= 1
    if fat32 and clusters < FAT32_MIN_CLUSTERS:
        raise ValueError(f"FAT32 has {clusters} clusters; Mu requires at least {FAT32_MIN_CLUSTERS}")
    return {
        "bytes_per_sector": bps,
        "sectors_per_cluster": spc,
        "reserved_sectors": reserved,
        "fats": fats,
        "total_sectors": total,
        "sectors_per_fat": spf,
        "first_cluster_lba": first_cluster_lba,
        "clusters": clusters,
        "fat_type": "FAT32" if fat32 else "FAT12/16",
    }


def menu_text(timeout: int = -1, fallback_timeout: int = DEFAULT_FALLBACK_TIMEOUT) -> str:
    """Return the intentionally payload-free TOML menu configuration."""
    return (
        "version = 1\n"
        "[boot]\n"
        f"timeout = {timeout}\n"
        f"fallback_timeout = {fallback_timeout}\n"
        'default = "probe"\n'
        "[ui]\n"
        'title = "UniXNU menu-only probe"\n'
        'console = "auto"\n'
        "[kits]\n"
        "autoload = false\n"
        "[[entry]]\n"
        'id = "probe"\n'
        f'title = "{MARKER}"\n'
        'type = "action"\n'
        'action = "tools"\n'
        "[[entry]]\n"
        'id = "restart"\n'
        'title = "Restart"\n'
        'type = "action"\n'
        'action = "reset"\n'
        "[[entry]]\n"
        'id = "shutdown"\n'
        'title = "Power off"\n'
        'type = "action"\n'
        'action = "shutdown"\n'
    )


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def validate_menu_text(text: str, *, require_menu_only: bool = True) -> dict[str, Any]:
    """Parse and validate a probe TOML document.

    The checks intentionally reject a configuration that could require any
    payload file.  ``timeout = 0`` is rejected because source-verified
    UniXNU menu semantics make it an immediate auto-start, not a disabled
    countdown.
    """
    if not isinstance(text, str) or not text:
        raise ValueError("configuration is empty")
    try:
        root = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, TypeError) as exc:
        raise ValueError(f"invalid TOML: {exc}") from exc
    if root.get("version") != 1:
        raise ValueError("version must be 1")
    unknown = set(root) - {"version", "boot", "ui", "kits", "entry"}
    if unknown:
        raise ValueError(f"unsupported top-level keys: {', '.join(sorted(unknown))}")
    boot = root.get("boot")
    kits = root.get("kits", {})
    if not isinstance(kits, dict) or kits.get("autoload") is not False or set(kits) != {"autoload"}:
        raise ValueError("[kits] must contain only autoload = false")
    if not isinstance(boot, dict):
        raise ValueError("[boot] is required")
    timeout = _int(boot.get("timeout"), "boot.timeout")
    fallback = _int(boot.get("fallback_timeout", DEFAULT_FALLBACK_TIMEOUT), "boot.fallback_timeout")
    if timeout == 0:
        raise ValueError("timeout=0 auto-starts the default entry; it is not menu-only")
    if fallback < 1:
        raise ValueError("fallback_timeout must be at least 1")
    if timeout >= 0:
        raise ValueError("menu-only probe requires a negative timeout")
    if "driver" in root or "dt_patch" in root or "block_slice" in root or "acpi" in root or "kit" in root:
        raise ValueError("probe must not declare drivers, patches, slices, ACPI, or kits")
    entries = root.get("entry")
    if not isinstance(entries, list) or not entries:
        raise ValueError("at least one action entry is required")
    found_markers = []
    allowed_actions = {"exit", "reset", "shutdown", "tools"}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"entry {index} is not a table")
        if entry.get("type") != "action":
            raise ValueError(f"entry {index} is not an action")
        if entry.get("action") not in allowed_actions:
            raise ValueError(f"entry {index} has an unsupported action")
        if entry.get("title") == MARKER:
            found_markers.append((index, entry))
        for forbidden in ("path", "initrd", "dtb", "kext", "variable", "chosen", "dt_patch"):
            if forbidden in entry:
                raise ValueError(f"entry {index} contains payload field {forbidden}")
    if len(found_markers) != 1:
        raise ValueError(f"expected one ASCII marker action, found {len(found_markers)}")
    marker_index, marker = found_markers[0]
    if marker.get("id") != "probe" or marker.get("action") != "tools":
        raise ValueError("marker must be id=probe with action=tools")
    default = boot.get("default")
    if default != "probe" or marker_index != next((i for i, item in enumerate(entries) if item.get("id") == default), -1):
        raise ValueError("default must resolve uniquely to the marker action")
    ids = [entry.get("id") for entry in entries]
    if any(not isinstance(item, str) for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("entry ids must be unique strings")
    return root


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise ValueError(f"missing mtools program: {name}")
    return found


def _run_mtools(name: str, image: Path, *args: str, capture: bool = False) -> subprocess.CompletedProcess[bytes]:
    command = [_tool(name), *args, "-i", str(image)]
    return subprocess.run(command, check=True, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.PIPE if capture else subprocess.DEVNULL)


def read_menu(image: Path) -> str:
    """Read the config through mtools and validate its exact UTF-8 text."""
    image = Path(image)
    if not image.is_file():
        raise ValueError(f"FAT image not found: {image}")
    inspect_bpb(image)
    try:
        result = _run_mtools("mtype", image, MENU_PATH, capture=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace").strip()
        raise ValueError(f"cannot read {MENU_PATH}: {detail}") from exc
    try:
        text = result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("menu file is not UTF-8") from exc
    validate_menu_text(text)
    return text


def build(image: Path, *, size_mib: int = DEFAULT_SIZE_MIB,
          sectors_per_cluster: int = DEFAULT_SECTORS_PER_CLUSTER,
          timeout: int = -1) -> Path:
    """Create a new FAT32 image and verify its config by reading it back."""
    image = Path(image).resolve()
    if image.exists():
        raise ValueError(f"refusing existing output: {image}")
    if not isinstance(size_mib, int) or size_mib < 16 or size_mib > 1024:
        raise ValueError("payload size must be 16..1024 MiB")
    if (not isinstance(sectors_per_cluster, int) or sectors_per_cluster < 1 or
            (sectors_per_cluster & (sectors_per_cluster - 1)) != 0):
        raise ValueError("sectors_per_cluster must be a positive power of two")
    text = menu_text(timeout=timeout)
    validate_menu_text(text)
    image.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        try:
            with image.open("xb") as stream:
                stream.truncate(size_mib * 1024 * 1024)
            created = True
        except FileExistsError as exc:
            # A concurrent creator won the exclusive-open race.  Never unlink
            # a file that this process did not create.
            raise ValueError(f"output appeared during creation: {image}") from exc
        _run_mtools("mformat", image, "-F", "-c", str(sectors_per_cluster), "-v", "MENUONLY")
        inspect_bpb(image)
        _run_mtools("mmd", image, "::/EFI")
        _run_mtools("mmd", image, "::/EFI/UniXNU")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".toml") as menu:
            menu.write(text)
            menu.flush()
            _run_mtools("mcopy", image, menu.name, MENU_PATH)
        readback = read_menu(image)
        if readback != text:
            raise ValueError("FAT config did not round-trip byte-for-byte")
    except Exception:
        if created:
            try:
                image.unlink()
            except FileNotFoundError:
                pass
        raise
    return image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--size-mib", type=int, default=DEFAULT_SIZE_MIB)
    parser.add_argument("--sectors-per-cluster", type=int, default=DEFAULT_SECTORS_PER_CLUSTER,
                        help="FAT32 sectors per cluster (default: 1)")
    parser.add_argument("--timeout", type=int, default=-1,
                        help="menu timeout; zero is rejected because it auto-starts")
    parser.add_argument("--verify", action="store_true", help="verify an existing image instead of creating one")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            text = read_menu(args.output)
            bpb = inspect_bpb(args.output)
            print(f"verified: {args.output} ({args.output.stat().st_size} bytes)")
        else:
            image = build(args.output, size_mib=args.size_mib,
                          sectors_per_cluster=args.sectors_per_cluster,
                          timeout=args.timeout)
            text = read_menu(image)
            bpb = inspect_bpb(image)
            print(f"payload: {image} ({image.stat().st_size} bytes)")
        print(f"geometry: {bpb['fat_type']} {bpb['bytes_per_sector']}B sectors, "
              f"{bpb['sectors_per_cluster']} sectors/cluster, {bpb['clusters']} clusters")
        print(f"menu-bytes: {len(text.encode('utf-8'))}")
        print(f"marker: {MARKER}")
        print("scope: config and action menu only; no kernel, ramdisk, driver, or DTB")
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
