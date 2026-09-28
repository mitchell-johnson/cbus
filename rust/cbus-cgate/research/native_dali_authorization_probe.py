"""Capture DALI handler and mode-selector roles on an owned native child.

Invocations derive from the pinned native help capture. Every CDG target is in
an absent MISSING project; no C-Bus endpoint or broker is configured. The
optional ``poll`` selector is captured separately where the native help lists
mode=(auto). Responses establish entry order only, not device permission.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

import native_admin_authorization_probe as base


ROOT = Path(__file__).resolve().parents[3]
HELP = ROOT / 'rust/testdata/fixtures/native_cgate_dali_help.json'
CDG = '//MISSING/254/p/1'


def argument(name: str) -> str:
    if name in {'cdg', 'cdg-object-id', 'db-cdg'}:
        return CDG
    if name in {'project-name'}:
        return 'TEST'
    if name in {'network-address', 'network-path', 'project-address'}:
        return '//MISSING/254'
    if name in {'session-name'}:
        return 'auth-dali'
    if name in {'dc-device-name'}:
        return 'missing-spec'
    if name in {'model-path'}:
        return 'Missing.Value'
    if name in {'model-json'}:
        return '{}'
    if name in {'line', 'dali-line'}:
        return 'A'
    if name in {'object-id', 'dali-OID', 'session-OID'}:
        return CDG
    return '1'


def commands() -> list[str]:
    paths = json.loads(HELP.read_text(encoding='utf-8'))['paths']
    selected = []
    for path, lines in paths.items():
        if not path.startswith('DALI ') or path in {
            'DALI CATALOG LIST', 'DALI SESSION LIST',
        }:
            continue
        first = lines[0]
        # Optional bracketed examples are omitted, preserving required
        # arguments only. Some native help text has incorrect verb spelling;
        # use the inventoried command path as the authority for the verb.
        required = re.sub(r'\[[^]]*\]', '', first)
        args = [argument(name) for name in re.findall(r'<([^>]+)>', required)]
        invocation = ' '.join([path, *args])
        selected.append(invocation)
        if '[mode=(auto)]' in first:
            selected.append(' '.join([path, 'poll', *args]))
    return selected


COMMANDS = commands()


def capture(vendor: Path, java: Path, output: Path) -> dict:
    base.COMMANDS = COMMANDS
    base.capture(vendor, java, output)
    report = json.loads(output.read_text(encoding='utf-8'))
    report['format'] = 'native-cgate-dali-authorization-v1'
    report['capture_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['capture_engine_sha256'] = hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest()
    report['help_fixture_sha256'] = hashlib.sha256(HELP.read_bytes()).hexdigest()
    report['method'] = (
        'One owned native Java 11 child; nine fresh logged-in role sockets; '
        'required arguments derived from the retained native DALI help capture; '
        'absent MISSING CDG targets; no C-Bus endpoint. Both default and poll '
        'modes are retained where advertised. A 420 below a non-420 response '
        'establishes only handler entry for that invocation. Generated '
        'credentials were redacted before retaining this report.'
    )
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-dir', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = capture(args.vendor_dir.resolve(), args.java.resolve(), args.output.resolve())
    print(json.dumps({
        'output': str(args.output),
        'cleanup': report['oracle']['cleanup_complete'],
        'cases': len(COMMANDS),
        'roles': len(report['roles']),
    }))
