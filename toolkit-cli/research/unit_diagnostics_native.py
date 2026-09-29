"""Native C-Gate capture of the Toolkit Diagnostics dialog sequence (P8.05).

Owned loopback C-Gate 3.4.0.2001 talks to the synthetic PCI fixture in
``unit_diagnostics_fixture``. The scenario runs ``cbus-toolkit cgate network
diagnose`` twice: with all four fixture units present, then after unit 17 is
detached from the simulated bus. Direct probes pin the native replies for a
database-only unit (99) and the detached unit. The committed JSON keeps
command/reply text with generated OIDs and ephemeral ports removed.

    CBUS_LOCAL_CGATE_VENDOR=... CBUS_CGATE_JAVA=... \\
    PYTHONPATH=src:. python research/unit_diagnostics_native.py --output research/fixtures/native-unit-diagnostics.json
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbus_toolkit.cgate import CGateClient, CGateError  # noqa: E402
from cbus_toolkit.cli import main  # noqa: E402
import unit_diagnostics_fixture as fixture  # noqa: E402

PROJECT = 'DIAGNOSE'
NETWORK = f'//{PROJECT}/254'
PROBES = ('GET {path} NetVoltage', 'DO {path} Psync', 'GET {path} BurdenActive')


def _sanitize(value, port):
    if isinstance(value, str):
        value = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '00000000-0000-4000-8000-000000000000', value)
        value = re.sub(r'cbus_cli_[0-9a-f]{16}', '<session>', value)
        return value.replace(f'127.0.0.1:{port}', '127.0.0.1:0')
    if isinstance(value, list):
        return [_sanitize(item, port) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item, port) for key, item in value.items()}
    return value


def run(host, port, sim_host='127.0.0.1', bind='127.0.0.1'):
    """Run the two-pass scenario; return the unsanitized report."""
    report = {'scope': 'Owned native C-Gate + synthetic PCI; no physical electrical claim',
              'project': PROJECT, 'setup': [], 'passes': [], 'probes': [], 'cleanup_errors': []}
    sim = fixture.diagnostics_simulator()
    with sim.running(bind, 0) as (_, sim_port), CGateClient(host, port, timeout=60) as client:
        report['simulator_port'] = sim_port

        def command(text, bucket):
            try:
                lines = list(client.command(text).lines)
            except CGateError as error:
                lines = list(error.response.lines)
            bucket.append({'command': text, 'lines': lines})
            return lines

        def diagnose(label):
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                status = main(['cgate', '--host', host, '--port', str(port), '--timeout', '60',
                               'network', 'diagnose', NETWORK])
            report['passes'].append({'label': label, 'exit_status': status,
                                     'result': json.loads(output.getvalue()) if output.getvalue() else None,
                                     'errors': errors.getvalue()})

        created = False
        try:
            setup = report['setup']
            command('PROJECT NEW ' + PROJECT, setup); created = True
            command('PROJECT USE ' + PROJECT, setup)
            command(f'DBCREATENET 254 Diag Cni {sim_host}:{sim_port}', setup)
            for address, unit_type, firmware in fixture.DATABASE_UNITS:
                command(f'DBADDSAFE {NETWORK} Unit {address} U{address}', setup)
                for name, value in (('UnitType', unit_type), ('FirmwareVersion', firmware),
                                    ('UnitName', f'U{address}')):
                    command(f'DBSETSAFE {NETWORK}/p/{address}/{name} {value}', setup)
            command('PROJECT SAVE ' + PROJECT, setup)
            command('NET LOAD DB ' + PROJECT, setup)
            command('NET OPEN ' + NETWORK, setup)
            deadline = time.monotonic() + 30
            while not any('state=ok' in line for line in command(f'GET {NETWORK} state', [])):
                if time.monotonic() > deadline:
                    raise RuntimeError('Diagnostics fixture network did not become ready')
                time.sleep(0.1)
            diagnose('all-present')
            for address in (16, 99):
                for probe in PROBES:
                    command(probe.format(path=f'{NETWORK}/p/{address}'), report['probes'])
            sim.detach_unit(17)
            diagnose('unit-17-detached')
            for probe in PROBES + ('GET {path} NetVoltage',):
                command(probe.format(path=f'{NETWORK}/p/17'), report['probes'])
        finally:
            if created:
                for text in ('NET CLOSE ' + NETWORK, 'PROJECT CLOSE ' + PROJECT, 'PROJECT DELETE ' + PROJECT):
                    try:
                        lines = command(text, [])
                        if not lines or not lines[-1].startswith('200'):
                            report['cleanup_errors'].append({'command': text, 'lines': lines})
                    except Exception as error:  # pragma: no cover - evidence only
                        report['cleanup_errors'].append({'command': text, 'error': type(error).__name__})
            report['wire_rejections'] = [row for row in sim.wire_log if row.get('reason')]
    return report


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
    port = report.pop('simulator_port')
    report = _sanitize(report, port)
    report['native'] = {'cgate_jar_sha256': local['vendor_jar_sha256'], 'java_version': local['java_version'],
                        'cleanup_complete': local['cleanup_complete']}
    report['fixture_sha256'] = hashlib.sha256(
        Path(__file__).with_name('unit_diagnostics_fixture.py').read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')
    print(json.dumps({'passes': [(p['label'], p['exit_status']) for p in report['passes']],
                      'cleanup_errors': report['cleanup_errors']}))


if __name__ == '__main__':
    main_cli()
