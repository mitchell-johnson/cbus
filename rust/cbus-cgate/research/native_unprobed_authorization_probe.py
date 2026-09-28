"""Capture further C-Gate handler-entry ACCESS floors on an owned loopback child.

All object references are absent MISSING-project objects. FILE/TRANSFORM/RUN
names resolve only inside the disposable native child, and no C-Bus endpoint
is configured. This observes command entry gates, not later object policy or
successful physical delivery.
"""

import argparse
import hashlib
import json
from pathlib import Path

import native_admin_authorization_probe as base


COMMANDS = [
    'ACCESS ADD user synthetic-probe synthetic-password Monitor',
    'CALCULATOR TEST //MISSING/254',
    'DBNEW',
    'LOG EXTRACT 1 auth-unprobed.log',
    'NET CHECK_UNRAVEL //MISSING/254',
    'NET STATE_INTERVAL //MISSING/254 1',
    'NEW UNIT //MISSING/254/p/1',
    'OFF //MISSING/254/56/1',
    'OID',
    'ON //MISSING/254/56/1',
    'RAMP //MISSING/254/56/1 128 4',
    'REPORT //MISSING/254',
    'RUN auth-unprobed-missing.txt',
    'STOP 999',
    'TERMINATERAMP //MISSING/254/56/1',
    'TEST_SPAM LIST',
    'TEST_SPAM STOP 999',
    'TRANSFORM MIGRATE_SQL auth-unprobed-missing.db',
    'TRANSFORM PROJECT MISSING',
    'TRANSFORM SQL_TO_XML auth-unprobed-missing.db',
    'TRANSFORM SQL_TO_XML_CGATE2 auth-unprobed-missing.db',
    'TRANSFORM XML_TO_SQL MISSING',
]


def capture(vendor: Path, java: Path, output: Path) -> dict:
    base.COMMANDS = COMMANDS
    base.capture(vendor, java, output)
    report = json.loads(output.read_text(encoding='utf-8'))
    report['format'] = 'native-cgate-unprobed-authorization-v1'
    report['capture_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['capture_engine_sha256'] = hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest()
    report['method'] = (
        'One owned native Java 11 child and nine fresh role sockets; missing '
        'object targets, disposable local files only, and no C-Bus endpoint. '
        'A lower-role 420 and at-floor non-420 establish only the exact '
        'invocation handler-entry floor. Synthetic ACCESS credentials are '
        'disposable and carry no site meaning.'
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
