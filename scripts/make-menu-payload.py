#!/usr/bin/env python3
"""Build a menu-only UniXNU diagnostic FAT payload (no kernel, no firmware).

This payload exists solely to open the UniXNU Tools menu (Advanced Logger QR)
without inventing DRAM or kernel handoff inputs. It is not a bootable OS image.
"""
from __future__ import annotations
import argparse, shutil, subprocess, sys
from pathlib import Path

MENU = '''version = 1
[boot]
timeout = 60
default = "tools"
[kits]
autoload = false
[[entry]]
id = "tools"
title = "Tools"
type = "action"
action = "tools"
[[entry]]
id = "reset"
title = "Restart"
type = "action"
action = "reset"
[[entry]]
id = "shutdown"
title = "Power off"
type = "action"
action = "shutdown"
'''

def build(image: Path, mib: int, tools_available=None):
    for tool in ('mformat', 'mmd', 'mcopy'):
        if shutil.which(tool) is None:
            raise ValueError(f'missing mtools tool: {tool}')
    if mib < 16 or mib > 1024:
        raise ValueError('payload size must be 16..1024 MiB')
    image = image.resolve()
    if image.exists():
        raise ValueError(f'refusing existing payload: {image}')
    image.parent.mkdir(parents=True, exist_ok=True)
    with image.open('wb') as stream:
        stream.truncate(mib * 1024 * 1024)
    run = lambda *args: subprocess.run([*args, '-i', str(image)], check=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run('mformat', '-F', '-v', 'ONYX')
    run('mmd', '::/EFI')
    run('mmd', '::/EFI/UniXNU')
    menu = image.with_suffix('.unixnu.toml')
    menu.write_text(MENU, encoding='utf-8')
    try:
        run('mcopy', str(menu), '::/EFI/UniXNU/unixnu.toml')
    finally:
        menu.unlink()
    return image

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--size-mib', type=int, default=64)
    args = p.parse_args(argv)
    try:
        image = build(args.output, args.size_mib)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    print(f'payload: {image} ({image.stat().st_size} bytes)')
    print('scope: UniXNU Tools/Advanced Logger menu only; no kernel or DRAM handoff')
    return 0

if __name__ == '__main__':
    sys.exit(main())
