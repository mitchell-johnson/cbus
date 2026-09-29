"""Native C-Gate generic-GET inventory for an open synthetic KEYGL5 (P6.05).

Owned loopback C-Gate 3.4.0.2001 opens one network whose CNI is the Python
PCI simulator. Unit 5 is the named SIMTEST KEYGL5 5.5.00 identity from
``synthetic_units`` with three explicit fixture additions: parameter 0x3E
(learn-enable byte, chosen 00), a writable 0xFF selector block, and IDENTIFY
attribute 0x3D carrying chosen key-function-indicator nibbles. These are the
only extra blocks native C-Gate requested for ``GET *`` and ``LABEL KFIGET``;
they are not device observations and model no label storage.

With the unit in ``State=ok`` the probe captures ``GET ?``, ``??``, ``*``,
named cache candidates, the lighting application/group inventories and
``LABEL KFIGET``, plus every simulator frame each command caused. The
committed JSON removes generated OIDs and the ephemeral simulator port.

    CBUS_LOCAL_CGATE_VENDOR=... CBUS_CGATE_JAVA=... \\
    PYTHONPATH=src:. python research/edlt_open_unit_native.py --output research/fixtures/edlt-open-unit-get-native.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbus_toolkit.cgate import CGateClient, CGateError  # noqa: E402
from cbus_toolkit.simulator import PCISimulator, synthetic_units  # noqa: E402

PROJECT = 'EDLTGET'
NETWORK = f'//{PROJECT}/254'
UNIT = f'{NETWORK}/p/5'
# Chosen KFI nibbles, packed as kv.m() decodes them (low nibble first).
KFI_BYTES = bytes.fromhex('10325476')
CANDIDATES = ('DynamicLabels', 'DynamicLabel', 'LabelCache', 'Labels', 'Label',
              'LabelText', 'Cache', 'KFI')
PROBES = (
    f'GET {UNIT} ?', f'GET {UNIT} ??', f'GET {UNIT} *', f'GET {UNIT} WidgetGroups',
    *(f'GET {UNIT} {name}' for name in CANDIDATES),
    'HELP GET', 'HELP LABEL',
    f'GET {NETWORK}/56 ??', f'GET {NETWORK}/56 *',
    f'GET {NETWORK}/56/27 ??', f'GET {NETWORK}/56/27 *',
    f'LABEL KFIGET {NETWORK}/56 5',
)


def edlt_simulator(**options):
    units = synthetic_units()
    unit = next(item for item in units if item.address == 5)
    unit.parameters[0x3E] = b'\x00'
    unit.parameters[0xFF] = b'\x00\x00'
    unit.write_tags[0xFF] = 0x00
    unit.attributes[0x3D] = b'\x80' + KFI_BYTES + bytes(7)
    return PCISimulator(units, profile='synthetic', response_delay=0.01, **options)


def _sanitize(value, port):
    if isinstance(value, str):
        value = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                       '00000000-0000-4000-8000-000000000000', value)
        return value.replace(f'127.0.0.1:{port}', '127.0.0.1:0')
    if isinstance(value, list):
        return [_sanitize(item, port) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item, port) for key, item in value.items()}
    return value


def _frames(rows):
    # ASCII PCI frames; per-request confirmation codes are dropped.
    result = []
    for row in rows:
        text = bytes.fromhex(row['hex']).decode('ascii', 'replace').strip().lstrip('\\')
        text = re.sub(r'[g-z]$', '', text) if row['direction'] == 'rx' else re.sub(r'^[g-z]\.', '', text)
        result.append({'direction': row['direction'], 'frame': text,
                       **({'rejected': row['reason']} if row.get('reason') else {})})
    return result


def run(host, port, sim_host='127.0.0.1', bind='127.0.0.1'):
    """Open the synthetic unit, run every probe; return the unsanitized report."""
    report = {'scope': 'Owned native C-Gate + synthetic PCI; no physical eDLT or rendered label',
              'project': PROJECT, 'setup': [], 'probes': [], 'cleanup_errors': []}
    sim = edlt_simulator()
    with sim.running(bind, 0) as (_, sim_port), CGateClient(host, port, timeout=60) as client:
        report['simulator_port'] = sim_port

        def command(text, bucket, wire=False):
            start = len(sim.wire_log)
            try:
                lines = list(client.command(text).lines)
            except CGateError as error:
                lines = list(error.response.lines)
            row = {'command': text, 'lines': lines}
            if wire:
                row['wire'] = _frames(sim.wire_log[start:])
            bucket.append(row)
            return lines

        created = False
        try:
            setup = report['setup']
            command('PROJECT NEW ' + PROJECT, setup); created = True
            command('PROJECT USE ' + PROJECT, setup)
            command(f'DBCREATENET 254 Edlt Cni {sim_host}:{sim_port}', setup)
            command(f'DBADDSAFE {NETWORK} Unit 5 U5', setup)
            for name, value in (('UnitType', 'KEYGL5'), ('FirmwareVersion', '5.5.00'), ('UnitName', 'U5')):
                command(f'DBSETSAFE {UNIT}/{name} {value}', setup)
            command('PROJECT SAVE ' + PROJECT, setup)
            command('NET LOAD DB ' + PROJECT, setup)
            command('NET OPEN ' + NETWORK, setup)
            deadline = time.monotonic() + 60
            # The network can report ok before its first sync creates unit 5.
            while not (any('state=ok' in line for line in command(f'GET {NETWORK} state', []))
                       and any('State=ok' in line for line in command(f'GET {UNIT} State', []))):
                if time.monotonic() > deadline:
                    raise RuntimeError('eDLT fixture unit did not open')
                time.sleep(0.2)
            for probe in PROBES:
                command(probe, report['probes'], wire=True)
        finally:
            if created:
                for text in ('NET CLOSE ' + NETWORK, 'PROJECT CLOSE ' + PROJECT, 'PROJECT DELETE ' + PROJECT):
                    try:
                        lines = command(text, [])
                        if not lines or not lines[-1].startswith('200'):
                            report['cleanup_errors'].append({'command': text, 'lines': lines})
                    except Exception as error:  # pragma: no cover - evidence only
                        report['cleanup_errors'].append({'command': text, 'error': type(error).__name__})
    return report


def sanitized(report):
    port = report.pop('simulator_port')
    return _sanitize(report, port)


def main_cli():
    from local_cgate import LocalCGate

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'], java=os.environ['CBUS_CGATE_JAVA'])
    (service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
    service.start()
    try:
        report = run('127.0.0.1', service.port)
    finally:
        local = service.close()
    report = sanitized(report)
    report['native'] = {'cgate_jar_sha256': local['vendor_jar_sha256'],
                        'java_version': local['java_version'].splitlines()[0],
                        'cleanup_complete': local['cleanup_complete']}
    report['probe_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')
    print(json.dumps({'probes': len(report['probes']), 'cleanup_errors': report['cleanup_errors']}))


if __name__ == '__main__':
    main_cli()
