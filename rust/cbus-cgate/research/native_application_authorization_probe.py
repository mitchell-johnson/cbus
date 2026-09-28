"""Capture remaining application entry roles on an owned C-Gate 3.4 child.

Every application target is under an absent MISSING project. The service has no
C-Bus endpoint; these invocations can establish handler-entry role floors but
cannot send on a physical network or establish successful device effects.
"""

import argparse
import hashlib
import json
from pathlib import Path

import native_admin_authorization_probe as base


COMMANDS = [
    'AIRCON SET_HUMIDITY_SETBACK_LIMIT //MISSING/254/172 1 1 20 0 0',
    'AIRCON SET_HUMIDITY_LOWER_GUARD_LIMIT //MISSING/254/172 1 1 20 0 0',
    'AIRCON SET_HUMIDITY_UPPER_GUARD_LIMIT //MISSING/254/172 1 1 80 0 0',
    'AIRCON SET_HVAC_LOWER_GUARD_LIMIT //MISSING/254/172 1 1 20 0 0',
    'AIRCON SET_HVAC_SETBACK_LIMIT //MISSING/254/172 1 1 20 0 0',
    'AIRCON SET_HVAC_UPPER_GUARD_LIMIT //MISSING/254/172 1 1 30 0 0',
    'AIRCON SET_WARD_OFF //MISSING/254/172 1',
    'AIRCON SET_WARD_ON //MISSING/254/172 1',
    'AIRCON SET_ZONE_HUMIDITY_MODE //MISSING/254/172 1 1 3 0',
    'AIRCON SET_ZONE_HVAC_MODE //MISSING/254/172 1 1 3 0 1',
    'CLOCK DATE //MISSING/254/223',
    'CLOCK REQUEST_REFRESH //MISSING/254/223',
    'ENABLE LABEL //MISSING/254/203 0 1 1 0 test',
    'ENABLE REMOVE //MISSING/254/203/1',
    'LIGHTING UNICODELABEL //MISSING/254/56 0 1 1 0 test',
    'LIGHTING TERMINATERAMP //MISSING/254/56/1',
    'SHORTMESSAGE SEND //MISSING/254/173 1 1 0 0 0 test',
    'TELEPHONY CLEAR_DIVERSION //MISSING/254/224',
    'TELEPHONY DIVERT //MISSING/254/224 12345',
    'TELEPHONY ISOLATE_SECONDARY_OUTLET //MISSING/254/224 1',
    'TELEPHONY RECALL_LAST_NUMBER_REQUEST //MISSING/254/224 out',
    'TELEPHONY REJECT_INCOMING_CALL //MISSING/254/224',
    'TRIGGER LABEL //MISSING/254/202 0 1 1 0 test',
    'TRIGGER UNICODELABEL //MISSING/254/202 0 1 1 0 test',
]


def capture(vendor: Path, java: Path, output: Path) -> dict:
    # The common capture engine owns one disposable child, generated per-role
    # credentials, all sockets and cleanup. Rewrite its source metadata to
    # bind this command list and its own engine, then keep only the redacted
    # serialized report that the engine wrote.
    base.COMMANDS = COMMANDS
    base.capture(vendor, java, output)
    report = json.loads(output.read_text(encoding='utf-8'))
    report['format'] = 'native-cgate-application-authorization-v1'
    report['capture_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['capture_engine_sha256'] = hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest()
    report['method'] = (
        'Owned native Java 11 child, nine fresh logged-in role sockets, absent '
        'MISSING project for every target, no C-Bus endpoint. A 420 at lower '
        'roles and non-420 at the floor proves only handler-entry order. '
        'Generated credentials were redacted before retaining this report.'
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
