#!/usr/bin/env python3
"""Fail closed before an EDK II build whose source tree is not the reviewed one.

Runs as `[firmware] preflight` in board.toml, so `unixnu build firmware` (and
`unixnu package --check`) calls it with `UNIXNU_UEFI` naming the Mu-Silicium
checkout and `UNIXNU_DEVICE` naming this repository.

Two kinds of mistake are cheap to make and expensive to discover late: the
firmware source tree does not carry `patches/uefi/` yet, and the two compression
settings drift apart. The first produces a volume that builds, passes a size
check and then fails on the phone for a reason that is one patch old; the second
produces an image whose payload the firmware will not read. Both are checked
here, before the build, with the exact command that fixes them.

Nothing here proves anything about a device. A green run says the source tree
matches the reviewed series and the configuration agrees with itself.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_SKIPPED = 0

BOARD_FIRMWARE = ('Platforms/Xiaomi/onyxPkg/onyx.dsc', 'Platforms/Xiaomi/onyxPkg/onyx.fdf')

# Patch target that is not the Mu-Silicium checkout: 0012 rewrites the driver in
# the UniXNU source tree, which is mounted, not edited, by the firmware build.
FOREIGN_TARGET = {
    '0012-onyx-unixnudxe-direct-start-fallback.patch': 'U',
}
FOREIGN_TARGET_PATHS = ('UniXNUPkg/',)

# onyx traps this port already paid for; the FDF/DSC must keep carrying them.
REQUIRED_FDF_LINES = ('UniXNUPkg/Application/UniXNU/UniXNU.inf',
                      'UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf',
                      'DarwinBootPkg/Driver/DarwinBoot.inf',
                      'UniXNUPkg/Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.inf',
                      'MdeModulePkg/Universal/Disk/DiskIoDxe/DiskIoDxe.inf',
                      'MdeModulePkg/Universal/Disk/PartitionDxe/PartitionDxe.inf',
                      'FatPkg/EnhancedFatDxe/Fat.inf',
                      'UniXNUPkg/Driver/AdvancedLogDxe/AdvancedLogDxe.inf')

REQUIRED_DSC_TEXT = ('/FILEALIGN:0x1000',
                     'FdtLib|MdePkg/Library/BaseFdtLib/BaseFdtLib.inf',
                     '-DONYX_FDT_HANDOFF=1')


class Report:
    def __init__(self):
        self.failures: list[str] = []
        self.skips: list[str] = []
        self.fixed: list[str] = []

    def fail(self, message, hint=None):
        self.failures.append(message if not hint else f'{message}\n    fix: {hint}')

    def skip(self, message):
        self.skips.append(message)

    def print(self, stream=None):
        stream = sys.stdout if stream is None else stream
        for line in self.fixed:
            print(f'ok   {line}', file=stream)
        for line in self.skips:
            print(f'skip {line}', file=stream)
        for line in self.failures:
            print(f'FAIL {line}', file=stream)
        return EXIT_FAILED if self.failures else EXIT_OK


def patch_number(name: str) -> str:
    match = re.match(r'^(\d{4})-', name)
    return match.group(1) if match else ''


def series(device: Path) -> list[Path]:
    return sorted((device / 'patches' / 'uefi').glob('*.patch'))


INDEX_LINE = re.compile(r'^index ([0-9a-f]+)\.\.([0-9a-f]+)', re.M)
DIFF_BLOCK = re.compile(r'diff --git a/(\S+) b/(\S+)\n(.*?)(?=\ndiff --git |\Z)', re.S)


def series_endpoints(device: Path) -> dict[str, tuple[str, str]]:
    """Where the reviewed series leaves each file.

    A patch records the blob it produces, and the last patch touching a path
    records the final content, so the endpoint is exact without replaying the
    series. Replaying it would need a writable checkout and would still be
    confused by a later patch that rewrites the same hunk.
    """
    endpoints: dict[str, tuple[str, str]] = {}
    for patch in series(device):
        for block in DIFF_BLOCK.finditer(patch.read_text(encoding='utf-8')):
            path = block.group(2)
            match = INDEX_LINE.search(block.group(3))
            if match:
                endpoints[path] = (patch.name, match.group(2))
    return endpoints


def blob_of(uefi: Path, path: str) -> str | None:
    result = subprocess.run(['git', '-C', str(uefi), 'hash-object', path],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def check_series(device: Path, uefi: Path, report: Report) -> None:
    patches = series(device)
    if not patches:
        report.fail(f'no patches under {device / "patches" / "uefi"}')
        return
    endpoints = series_endpoints(device)
    local = {path: item for path, item in endpoints.items()
             if not path.startswith(FOREIGN_TARGET_PATHS)}
    drifted = []
    for path, (patch, expected) in sorted(local.items()):
        actual = blob_of(uefi, path)
        if actual is None or not actual.startswith(expected):
            drifted.append((path, patch, expected, actual))
    if drifted:
        names = sorted({item[1] for item in drifted})
        report.fail(
            f'{len(drifted)} file(s) in {uefi} are not at the endpoint of the reviewed series '
            f'({", ".join(names)}): '
            + ', '.join(f'{path} (want {want[:10]}, has {(has or "missing")[:10]})'
                        for path, _, want, has in drifted[:5]),
            f'apply the series in order to a checkout at the recorded pin: '
            f'git -C {uefi} apply {" ".join(str(patch) for patch in patches if patch.name not in FOREIGN_TARGET)}')
        return
    report.fixed.append(f'{len(local)} Mu-Silicium files match the endpoint of all {len(patches)} '
                        f'reviewed patches')


def load_toml(path: Path, report: Report, label: str):
    try:
        return tomllib.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        report.fail(f'{label} is missing: {path}')
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        report.fail(f'{label} is not readable TOML ({error}): {path}')
    return None


def check_mu_config(uefi: Path, report: Report) -> None:
    path = uefi / 'Resources' / 'Configs' / 'onyx.toml'
    config = load_toml(path, report, 'the Mu-Silicium board configuration')
    if config is None:
        return
    fd = config.get('uefi_fd', {})
    base, size = fd.get('base'), fd.get('size')
    if base != 0xA7100000:
        report.fail(f'{path.name}: uefi_fd.base is {base!r}, not 0xA7100000')
    if size != 0x300000:
        report.fail(f'{path.name}: uefi_fd.size is {size!r}, not 0x300000 (3 MiB, the size '
                    'scripts/accept-firmware.py requires)')
    if not config.get('boot_shim', {}).get('requires_kernel_header'):
        report.fail(f'{path.name}: [boot_shim] requires_kernel_header must be true, otherwise '
                    'BootShim writes only the volume size into the ARM64 header')
    compression = config.get('boot_image_kernel', {}).get('kernel_compression')
    if compression != 'none':
        report.fail(f'{path.name}: [boot_image_kernel] kernel_compression is {compression!r}, '
                    'not "none"; onyx appends the volume uncompressed')
    if config.get('boot_image', {}).get('header_version') != 4:
        report.fail(f'{path.name}: [boot_image] header_version is '
                    f'{config.get("boot_image", {}).get("header_version")!r}, not 4')
    if not report.failures:
        report.fixed.append(f'{path.name}: 3 MiB at 0xA7100000, uncompressed, v4 header, shim header on')


def check_compression_agreement(device: Path, uefi: Path, report: Report) -> None:
    """The packer reads board.toml, the firmware reads Mu's config. They must agree."""
    board = load_toml(device / 'board.toml', report, 'board.toml')
    mu = load_toml(uefi / 'Resources' / 'Configs' / 'onyx.toml', report, 'the Mu-Silicium config')
    if board is None or mu is None:
        return
    ours = board.get('bootimg', {}).get('image', {}).get('kernel_compression')
    theirs = mu.get('boot_image_kernel', {}).get('kernel_compression')
    if ours != theirs:
        report.fail(f'compression disagreement: board.toml [bootimg.image] says {ours!r} while '
                    f'the Mu-Silicium config says {theirs!r}; UniXNU reads the first and the '
                    'firmware expects the second',
                    'make both "none" -- onyx appends the firmware volume uncompressed')
        return
    if ours != 'none':
        report.fail(f'both configurations say kernel_compression={ours!r}; onyx must use "none"')
        return
    report.fixed.append('board.toml and the Mu-Silicium config agree on kernel_compression=none')


def check_platform_files(uefi: Path, report: Report) -> None:
    platform = uefi / 'Platforms' / 'Xiaomi' / 'onyxPkg'
    for relative in BOARD_FIRMWARE:
        if not (uefi / relative).is_file():
            report.fail(f'{uefi / relative} is missing; the board names it in [firmware] dsc/fdf')
    fdf, dsc = (uefi / BOARD_FIRMWARE[1]), (uefi / BOARD_FIRMWARE[0])
    if fdf.is_file():
        text = fdf.read_text(encoding='utf-8', errors='replace')
        absent = [line for line in REQUIRED_FDF_LINES if line not in text]
        if absent:
            report.fail('onyx.fdf no longer carries: ' + ', '.join(absent),
                        'restore the module lines; a missing one surfaces as "No Operating '
                        'System Found" on the device, not as a build error')
        else:
            report.fixed.append(f'onyx.fdf carries all {len(REQUIRED_FDF_LINES)} required modules')
    if dsc.is_file():
        text = dsc.read_text(encoding='utf-8', errors='replace')
        absent = [item for item in REQUIRED_DSC_TEXT if item not in text]
        if absent:
            report.fail('onyx.dsc no longer carries: ' + ', '.join(absent),
                        '/FILEALIGN:0x1000 is the onyx PE alignment GenFv requires for DiskIoDxe; '
                        'the two library mappings are the UniXNU integration')
        else:
            report.fixed.append(f'onyx.dsc carries the PE alignment and {len(REQUIRED_DSC_TEXT) - 1} '
                                'library mappings')
    mount = uefi / 'UniXNUPkg'
    if not (mount / 'Driver' / 'UniXNUDxe' / 'UniXNUDxe.inf').is_file():
        report.fail(f'{mount} is not mounted on the UniXNU source tree',
                    'ln -s <unixnu-checkout>/package/UniXNUPkg ' f'{mount}')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description='Fail closed before an EDK II build whose source tree is not the reviewed one.')
    parser.add_argument('--device', type=Path, help='device repository (default: UNIXNU_DEVICE)')
    parser.add_argument('--uefi', type=Path, help='Mu-Silicium checkout (default: UNIXNU_UEFI)')
    parser.add_argument('--require-uefi', action='store_true',
                        help='fail instead of skipping when no firmware checkout is named')
    args = parser.parse_args(argv)

    device = (args.device or os.environ.get('UNIXNU_DEVICE') or Path(__file__).resolve().parents[1])
    device = Path(device).expanduser()
    named = args.uefi or os.environ.get('UNIXNU_UEFI')
    report = Report()

    if not (device / 'board.toml').is_file():
        print(f'FAIL no board.toml under {device}', file=sys.stderr)
        return EXIT_FAILED

    if not named:
        message = ('no firmware checkout named (UNIXNU_UEFI or --uefi); the firmware-source checks '
                   'did not run')
        if args.require_uefi:
            print(f'FAIL {message}', file=sys.stderr)
            return EXIT_FAILED
        report.skip(message)
        return report.print()

    uefi = Path(named).expanduser()
    if not (uefi / 'Platforms' / 'Xiaomi' / 'onyxPkg').is_dir():
        print(f'FAIL {uefi} is not a Mu-Silicium checkout with Platforms/Xiaomi/onyxPkg',
              file=sys.stderr)
        return EXIT_FAILED

    check_platform_files(uefi, report)
    check_series(device, uefi, report)
    check_mu_config(uefi, report)
    check_compression_agreement(device, uefi, report)
    return report.print()


if __name__ == '__main__':
    sys.exit(main())
