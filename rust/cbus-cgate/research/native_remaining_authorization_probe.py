"""Capture remaining safe handler-entry roles on an owned C-Gate 3.4 child.

The C-Gate child binds loopback only and has no C-Bus endpoint. Targeted
objects live under an absent MISSING project. PORT discovery uses an explicit
loopback destination; PROBE connects only to loopback port 1. Local ACCESS
snapshot and database operations affect only the disposable child directory.
"""

import argparse
import hashlib
import json
from pathlib import Path

import native_admin_authorization_probe as base


COMMANDS = [
    'PORT CNISCAN 127.0.0.1 FAST',
    'PORT CNISCAN2 127.0.0.1 127.0.0.1 FAST',
    'PORT PROBE socket 127.0.0.1:1',
    'PORT REFRESH',
    'ACCESS LIST',
    'ACCESS DELETE 999',
    'ACCESS SAVE auth-role-probe',
    'DBADD //MISSING/254 Network',
    'DBADDSAFE //MISSING/254 Network',
    'DBCOPYSAFE //MISSING/254/56 //MISSING/254/56',
    'DBCREATENET 253 Local Cni 127.0.0.1:1',
    'DBGETJSON //MISSING/254',
    'DBGETJSON NAC_OBJECTS_LIST //MISSING/254',
    'DBGETJSON NAC_ROUTING_TABLE //MISSING/254',
    'DBGETJSON NAC_TAGMAP //MISSING/254',
    'DBRENAMENET 254 253',
    'DBRENAMENETSAFE 254 253',
    'CONVERTUNIT CHECK //MISSING/254/p/1',
    'CONVERTUNIT CONVERT //MISSING/254/p/1',
    'IDENTIFY OFF //MISSING/254/251/1',
    'IDENTIFY ON //MISSING/254/251/1',
    'IDENTIFY RAMP //MISSING/254/251/1 128 20',
    'IDENTIFY TERMINATERAMP //MISSING/254/251/1',
    'LIGHTING STOP //MISSING/254/56/1',
    'NET CREATE MISSING Cni 127.0.0.1:1',
    'NET PROJECT_IDENTIFY //MISSING/254',
    'NETWORK LOCATE //MISSING/254/208 UNIT 1 ON',
    'PROJECT ARCHIVE MISSING auth-role-probe.zip',
    'TOPOLOGY EXPLORE //MISSING/254',
    'TRIGGER INDICATORKILL //MISSING/254/202',
    'APPLICATIONS GET_CATALOG',
]


def capture(vendor: Path, java: Path, output: Path) -> dict:
    base.COMMANDS = COMMANDS
    base.capture(vendor, java, output)
    report = json.loads(output.read_text(encoding='utf-8'))
    report['format'] = 'native-cgate-remaining-authorization-v1'
    report['capture_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['capture_engine_sha256'] = hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest()
    report['method'] = (
        'One owned native Java 11 child and nine fresh role sockets; explicit '
        'loopback PORT targets; otherwise disposable local state or absent '
        'MISSING project objects; no C-Bus endpoint. A 420 below a non-420 '
        'response establishes only the exact invocation handler-entry floor. '
        'Generated credentials were redacted before retention.'
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
