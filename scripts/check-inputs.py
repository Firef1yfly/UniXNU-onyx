#!/usr/bin/env python3
"""Read-only, offline input lint. Success is NOT a build or hardware boot test.

DTS inspection intentionally supports only a simple literal, single-range memory
node. Includes, macros, overlays and other encodings require separate verification.
The optional-to-store inputs.toml is required to pass this lint. Its [device]
name/firmware_version and [memory] source/sha256 describe original board evidence,
not generated artifacts. These declarations are not authenticated.
"""
import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlparse

NOTICE = ('Host input lint only; no build, firmware authenticity, memory-map safety '
          'or real-device boot validation is performed.')


def audit(device, unixnu):
    device, unixnu = Path(device).resolve(), Path(unixnu).resolve()
    checks = []

    def add(identifier, status, message):
        checks.append(dict(id=identifier, status=status, message=message))

    def load(path):
        try:
            with path.open('rb') as stream:
                result = tomllib.load(stream)
            add('toml:' + str(path), 'ok', 'TOML parsed: ' + str(path))
            return result
        except (OSError, ValueError) as exc:
            add('toml:' + str(path), 'error', str(exc))
            return {}

    board = load(device / 'board.toml')
    identity = board.get('board', {})
    add('board.example', 'ok' if identity.get('example') is False else 'error',
        'board.example must explicitly be false after inputs are completed')
    profile = identity.get('os_profile', '')
    safe_profile = bool(profile) and Path(profile).name == profile and profile not in ('.', '..')
    os_root = unixnu / 'profiles/os' / profile if safe_profile else None
    add('os.profile', 'ok' if os_root and (os_root / 'profile.toml').is_file() else 'error',
        'Selected OS profile must exist: ' + str(profile))
    kernel = board.get('kernel', {})
    defconfigs = {kernel.get('defconfig', '')}
    defconfigs.update(board.get('package', {}).get('defconfig', {}).values())
    for name in sorted(defconfigs):
        safe = bool(name) and Path(name).name == name and name not in ('.', '..')
        add('defconfig:' + name, 'ok' if safe and (device / 'configs' / name).is_file() else 'error',
            'Device defconfig must exist: ' + name)
    record = load(device / 'porting.toml').get('device', {})
    for key in ('name', 'soc', 'os_profile'):
        add('record.' + key, 'ok' if identity.get(key) and record.get(key) == identity[key] else 'error',
            'porting.toml device.' + key + ' must match board.toml')

    sources = load(device / 'feeds.toml').get('source', [])
    # No resolution, download, git checkout or implicit local overrides are performed.
    candidates = [s for s in sources if s.get('kind') == 'soc' and s.get('name') == identity.get('soc_source')]
    soc_root = None
    if len(candidates) != 1:
        add('soc.source', 'error', 'Expected exactly one selected SoC feed')
    else:
        source = candidates[0]
        local = source.get('local')
        uri = urlparse(source.get('git', ''))
        if local:
            soc_root = Path(local).expanduser()
            if not soc_root.is_absolute():
                soc_root = device / soc_root
        elif uri.scheme == 'file' and uri.netloc in ('', 'localhost'):
            soc_root = Path(unquote(uri.path))
        else:
            add('soc.source', 'pending', 'Remote/unsupported SoC feed cannot be verified offline')
        if soc_root is not None:
            add('soc.directory', 'ok' if soc_root.is_dir() else 'error', 'SoC directory: ' + str(soc_root))
            if (soc_root / 'soc.toml').is_file():
                load(soc_root / 'soc.toml')
            else:
                add('soc.manifest', 'error', 'Missing SoC soc.toml: ' + str(soc_root))
            for folder in ('configs', 'dts'):
                add('soc.' + folder, 'ok' if (soc_root / folder).is_dir() else 'error',
                    'Required SoC directory: ' + str(soc_root / folder))

    roots = {'device': device, 'os': os_root, 'soc': soc_root,
             'arch': unixnu / 'profiles/arch/arm64'}
    for fragment in kernel.get('config_fragments', []):
        prefix, sep, relative = fragment.partition(':')
        root = roots.get(prefix) if sep else device
        path = root / (relative if sep else fragment) if root is not None else None
        add('fragment:' + fragment, 'ok' if path and path.is_file() else 'error',
            'Configuration fragment must exist: ' + fragment)

    seed = board.get('payload', {}).get('adt', {}).get('unique_chip_id')
    if seed in (None, 'required'):
        add('identity.seed', 'ok', 'No fixed identity seed; runtime seed remains a build input')
    else:
        add('identity.seed', 'error', 'Fixed identity seed in board.toml (including example seeds) must be removed')

    spec = board.get('device_tree', {}).get('source', '')
    prefix, sep, relative = spec.partition(':')
    root = roots.get(prefix) if sep else device
    path = root / (relative if sep else spec) if root is not None and spec else None
    try:
        text = path.read_text(encoding='utf-8') if path else ''
    except (OSError, UnicodeError) as exc:
        add('dts.source', 'error', str(exc))
        text = ''
    # Strip comments; do not interpret preprocessor directives or nested memory bodies.
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    memory = re.findall(r'\bmemory(?:@[\w,]+)?\s*\{([^{}]*)\}', text, re.S)
    regs = re.findall(r'\breg\s*=\s*<([^>]+)>\s*;', memory[0]) if len(memory) == 1 else []
    literals = regs[0].split() if len(regs) == 1 else []
    directives = bool(re.search(r'^\s*#\s*(?:include|define|if|ifdef|ifndef|else|elif|endif|undef|pragma)\b|/include/|/plugin/|/delete-node/|&\w+\s*\{', text, re.M))
    if not directives and len(literals) == 4 and all(re.fullmatch(r'0[xX][0-9a-fA-F]+|[0-9]+', v) for v in literals):
        cells = [int(v, 16) if v.lower().startswith('0x') else int(v, 10) for v in literals]
        if any(v > 0xffffffff for v in cells) or (cells[2] << 32 | cells[3]) == 0:
            add('dts.memory', 'error', 'Literal memory range has zero size or invalid cells')
        else:
            add('dts.memory', 'ok', 'Nonzero literal memory range found; geometry/reservations UNVERIFIED')
    else:
        add('dts.memory', 'pending', 'Cannot confirm memory from DTS text; inspect compiled DTB and board evidence')
    evidence = load(device / 'inputs.toml')
    evidence_device, evidence_memory = evidence.get('device', {}), evidence.get('memory', {})
    digest = evidence_memory.get('sha256', '')
    valid = (bool(identity.get('name')) and evidence_device.get('name') == identity.get('name')
             and isinstance(evidence_memory.get('source'), str) and bool(evidence_memory['source'].strip())
             and isinstance(evidence_device.get('firmware_version'), str) and bool(evidence_device['firmware_version'].strip())
             and isinstance(digest, str) and bool(re.fullmatch(r'[0-9a-fA-F]{64}', digest))
             and len(set(digest.lower())) > 1)
    add('board.provenance', 'ok' if valid else 'error',
        'inputs.toml requires [device] name/firmware_version and [memory] source/sha256 of original evidence; declarations are not authenticated')
    return {'schema_version': 1, 'complete': all(c['status'] == 'ok' for c in checks),
            'hardware_tested': False, 'notice': NOTICE, 'checks': checks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--unixnu', type=Path, help='UniXNU checkout (default: sibling unixnu)')
    parser.add_argument('--json', action='store_true', help='Emit a single JSON result')
    args = parser.parse_args(argv)
    try:
        result = audit(args.device, args.unixnu or args.device.resolve().parent / 'unixnu')
    except (TypeError, AttributeError, KeyError) as exc:
        result = {'schema_version': 1, 'complete': False, 'hardware_tested': False, 'notice': NOTICE,
                  'checks': [{'id': 'schema', 'status': 'error', 'message': 'Unsupported configuration shape: ' + str(exc)}]}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result['notice'])
        for check in result['checks']:
            print(f"[{check['status'].upper()}] {check['id']}: {check['message']}")
        print('Host inputs complete (NOT boot verified).' if result['complete'] else 'Inputs incomplete; do not treat this repository as boot-ready.')
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
