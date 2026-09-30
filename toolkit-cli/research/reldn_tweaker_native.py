#!/usr/bin/env python3
"""Owned native C-Gate acceptance for Toolkit RELDN client-side conversion.

The expected relay fields below are literal independent vectors, not values
computed by the implementation under test. No CONVERTUNIT command is used.
Only a fresh temporary C-Gate process, synthetic project and closed loopback
network are created. The receipt omits vendor specifications and private paths.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4
import xml.etree.ElementTree as ET

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.conversion_mapping import catalog_default, load_catalog
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer, xml_text
from cbus_toolkit.toolkit_conversion_tweakers import (
    ToolkitTweakerConversion, TweakerRefused, plan_writes,
)
from cbus_toolkit.unitspec import UnitSpecStore
from research.local_cgate import LocalCGate


CATALOGS = {
    'RELDN8': 'L5508RVF', 'RELDN12': 'L5512RVF', 'RELDN4': 'L5504RVF16',
    'RELDN8B': 'L5508RVFP', 'RELSM8': 'L5108RELVP',
}
PAIRS = tuple(('RELDN8', target) for target in ('RELDN12', 'RELDN4', 'RELDN8B', 'RELSM8')) + tuple(
    (source, 'RELDN8') for source in ('RELDN12', 'RELDN4', 'RELDN8B', 'RELSM8'))
LOGIC = tuple(f'LogicGA{number}Associations' for number in range(13, 17))
FIELDS = ('GroupAddress', *LOGIC)
# Position-distinct values include group 0, 254 and 255 and all four logic rows.
SOURCE = {
    'GroupAddress': '255 0 1 127 254 17 18 255 32 64 128 250 0 254 255 73',
    LOGIC[0]: '1 0 1 1 0 1 0 1 1 0 1 0',
    LOGIC[1]: '0 1 0 0 1 0 1 0 0 1 0 1',
    LOGIC[2]: '1 1 1 1 1 1 1 1 1 1 1 1',
    LOGIC[3]: '0 0 0 0 0 0 0 0 0 0 0 0',
}
EXPECTED_FORWARD = {
    'GroupAddress': '0 1 127 254 255 32 64 128 255 255 255 255 0 254 255 73',
    LOGIC[0]: '0 1 1 0 1 1 0 1 0 0 0 0',
    LOGIC[1]: '1 0 0 1 0 0 1 0 0 0 0 0',
    LOGIC[2]: '1 1 1 1 1 1 1 1 0 0 0 0',
    LOGIC[3]: '0 0 0 0 0 0 0 0 0 0 0 0',
}
EXPECTED_REVERSE = {
    'GroupAddress': '255 255 0 1 127 255 255 254 17 18 255 255 0 254 255 73',
    LOGIC[0]: '0 1 0 1 1 0 0 0 1 0 1 0',
    LOGIC[1]: '0 0 1 0 0 0 0 1 0 1 0 0',
    LOGIC[2]: '0 1 1 1 1 0 0 1 1 1 1 0',
    LOGIC[3]: '0 0 0 0 0 0 0 0 0 0 0 0',
}


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _raw(decimal):
    """Literal numeric vector rendered in observed native PP storage syntax."""
    return ' '.join(hex(int(token)) for token in decimal.split())


class TrackingClient:
    def __init__(self, client):
        self.client, self.commands = client, []

    def command(self, text, *args, **kwargs):
        self.commands.append(text)
        if 'CONVERTUNIT' in text.upper() or text.upper().startswith(('NET OPEN', 'NETWORK OPEN')):
            raise AssertionError('Toolkit relay acceptance must not use native conversion or open a network')
        return self.client.command(text, *args, **kwargs)

    def command_document(self, *args, **kwargs):
        raise AssertionError('RELDN acceptance does not need document writes')


class NoIO:
    def command(self, *_args, **_kwargs):
        raise AssertionError('refusal must occur before C-Gate I/O')

    command_document = command


class Inputs:
    def __init__(self, spec_dir, vendor):
        self.store = UnitSpecStore(spec_dir)
        catalog_path = Path(vendor) / 'unitspec/cbusunits.xml'
        self.catalog = load_catalog(catalog_path)
        self.hashes = {'cbusunits.xml': sha256(catalog_path.read_bytes()).hexdigest()}
        self.spec_dir = Path(spec_dir)

    def revision(self, unit_type):
        return catalog_default(self.catalog, unit_type, CATALOGS[unit_type])

    def spec(self, unit_type):
        spec = self.store.load(self.revision(unit_type)['spec_filename'])
        for name in spec.sources:
            self.hashes[name] = sha256((self.spec_dir / name).read_bytes()).hexdigest()
        return spec


def _values(programmer, network, unit):
    with programmer.load(network, '/db' + unit) as session:
        return session.values()


def _document(client, unit):
    root = ET.fromstring(xml_text(client.command('DBGETXML ' + unit)))
    return {
        'scalars': {child.tag: child.text or '' for child in root if len(child) == 0 and child.tag != 'PP'},
        'pp': {child.get('Name'): child.get('Value') for child in root if child.tag == 'PP'},
    }


def _expect(condition, message):
    if not condition:
        raise AssertionError(message)


def run(*, vendor, java, spec_dir):
    """Return a sanitized receipt after cleanup; assertions fail on any mismatch."""
    inputs = Inputs(spec_dir, vendor)
    for unit_type in CATALOGS:
        inputs.spec(unit_type)
    # Self conversion is not registered; even constructing it must be read free.
    refusals = []
    for unit_type in CATALOGS:
        try:
            ToolkitTweakerConversion(NoIO(), unit_type, inputs.spec(unit_type), unit_type, inputs.spec(unit_type))
        except TweakerRefused:
            refusals.append(unit_type)
        else:
            raise AssertionError('Unregistered self conversion was admitted: ' + unit_type)
    service = LocalCGate(vendor, java=java)
    (service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
    root = Path(__file__).resolve().parents[1]
    code_inputs = ('research/reldn_tweaker_native.py', 'tests/test_reldn_tweaker_native.py',
                   'src/cbus_toolkit/toolkit_conversion_tweakers.py',
                   'src/cbus_toolkit/toolkit_conversion_reldn.py')
    report = {'format': 'cbus-toolkit-reldn-tweaker-native-v1', 'cases': [],
              'code_sha256': {name: sha256((root / name).read_bytes()).hexdigest() for name in code_inputs},
              'self_conversion_refused_before_io': refusals, 'native_convertunit_used': False,
              'hardware_contacted': False, 'original_toolkit_gui_executed': False,
              'inputs': inputs.hashes}
    with service:
        with CGateClient('127.0.0.1', service.port, timeout=60) as raw_client:
            client = TrackingClient(raw_client)
            projects, database, programmer = NativeProjects(client), NativeDatabase(client), Programmer(client)
            project = 'R' + uuid4().hex[:7].upper()
            network = f'//{project}/254'
            projects.operation('new', project)
            projects.operation('use', project)
            client.command('DBCREATENET 254 RelayAcceptance Cni 127.0.0.1:29999')
            client.command('NET LOAD DB')
            snapshots = []
            for index, (source_type, target_type) in enumerate(PAIRS):
                source, target = f'{network}/p/{20 + index}', f'{network}/p/{100 + index}'
                source_spec, target_spec = inputs.spec(source_type), inputs.spec(target_type)
                source_revision, target_revision = inputs.revision(source_type), inputs.revision(target_type)
                database.create_unit(network, 20 + index, f'RELAY SOURCE {index}', source_type,
                                     source_revision['firmware'], catalog_number=CATALOGS[source_type])
                with programmer.load(network, '/db' + source) as session:
                    for name, decimal in SOURCE.items():
                        # Native accepts a long SET by truncating to spec length.
                        # Preserve the observed short RELDN4 source for the safety check.
                        session.set(name, decimal)
                    for name, value in {'Application': '56 255', 'AreaGroupAddress': '254',
                                        'UnitName': 'RELAY', 'SerialNo': '1 2 3 4',
                                        'PowerUpDelay': '3 70 90 10 255 59 60 61 0 254 255 7'}.items():
                        session.set(name, value)
                    session.save_to_source()
                before = _values(programmer, network, source)
                source_document = _document(client, source)
                for name, literal in SOURCE.items():
                    count = source_spec.parameters[name].array_size
                    seeded_raw = _raw(' '.join(literal.split()[:count]))
                    _expect(before[name] == seeded_raw and source_document['pp'][name] == seeded_raw,
                            f'{source_type} source seed mismatch: {name}')
                row = {'source_type': source_type, 'target_type': target_type,
                       'source_logic_lengths': [len(before[name].split()) for name in LOGIC],
                       'source_pp_sha256': _hash(source_document['pp'])}
                if source_type == 'RELDN4':
                    # Native has only four source logic elements. The recovered
                    # method dereferences indices 4..7, so this direction is
                    # intentionally refused rather than inventing padding.
                    mark = len(client.commands)
                    try:
                        ToolkitTweakerConversion(NoIO(), source_type, source_spec, target_type, target_spec)
                    except TweakerRefused as error:
                        row['refusal_reason'] = error.reason
                    else:
                        raise AssertionError('Short original source unexpectedly admitted')
                    _expect(len(client.commands) == mark, 'Constructor refusal performed C-Gate I/O')
                    _expect(row['source_logic_lengths'] == [4, 4, 4, 4], 'RELDN4 source boundary changed')
                    _expect(_document(client, source) == source_document, 'Refused source changed')
                    try:
                        client.command('DBGET ' + target + '/UnitType')
                    except CGateError:
                        pass
                    else:
                        raise AssertionError('Refused target was created')
                    row.update(status='refused_short_original_source', refusal_before_io=True,
                               source_preserved=True, source_logic_raw={name: before[name] for name in LOGIC})
                    report['cases'].append(row)
                    snapshots.append((source, before, source_document))
                    continue
                converter = ToolkitTweakerConversion(client, source_type, source_spec, target_type, target_spec)
                plan = plan_writes(source_type, target_type, before, set(target_spec.parameters))
                expected = EXPECTED_FORWARD if source_type == 'RELDN8' else EXPECTED_REVERSE
                planned = {name: value for name, value, _ in plan.writes}
                for name, literal in expected.items():
                    _expect(planned[name] == literal, f'{source_type}->{target_type} literal plan mismatch: {name}')
                _expect(_document(client, source) == source_document, 'Read-only planning changed source')
                result = converter.apply(source, 100 + index, target_firmware=target_revision['firmware'],
                                         target_catalog=CATALOGS[target_type], tag_name=f'RELAY TARGET {index}')
                _expect(result['failed_writes'] == {}, f'{source_type}->{target_type} PP SET failed')
                after, target_document = _values(programmer, network, target), _document(client, target)
                expected_raw = {}
                for name, literal in expected.items():
                    count = target_spec.parameters[name].array_size
                    expected_raw[name] = _raw(' '.join(literal.split()[:count]))
                    _expect(after[name] == expected_raw[name], f'{source_type}->{target_type} PP readback mismatch: {name}')
                    _expect(target_document['pp'][name] == expected_raw[name],
                            f'{source_type}->{target_type} raw database PP mismatch: {name}')
                for name in ('Application', 'AreaGroupAddress', 'UnitName'):
                    _expect(after[name] == before[name], f'Copied nondefault {name} changed')
                count = target_spec.parameters['PowerUpDelay'].array_size
                _expect(after['PowerUpDelay'].split() == before['PowerUpDelay'].split()[:count],
                        'Copied nondefault PowerUpDelay changed')
                _expect(after['SerialNo'] != before['SerialNo'], 'Immutable serial was incorrectly copied')
                _expect(target_document['scalars']['UnitType'] == target_type, 'Target database identity changed')
                _expect(target_document['scalars']['TagName'] == f'RELAY TARGET {index}', 'Explicit target tag changed')
                _expect(_values(programmer, network, source) == before, 'Source PP changed')
                _expect(_document(client, source) == source_document, 'Source metadata changed')
                _expect(plan_writes(source_type, target_type, before, set(target_spec.parameters)) == plan,
                        'Read-only repeated planning changed the result')
                _expect(client.command('NOOP').code == 200, 'Native NOOP failed')
                _expect(_document(client, target) == target_document, 'NOOP changed target')
                row.update(status='converted', plan_writes=len(plan.writes), raw_expected=expected_raw,
                           raw_pp_sha256=_hash(target_document['pp']), source_preserved=True,
                           repeated_plan_unchanged=True, noop_unchanged=True,
                           verified_parameters=result['verified_parameters'], failed_writes={})
                report['cases'].append(row)
                snapshots.extend(((source, before, source_document), (target, after, target_document)))
            projects.operation('save', project)
            projects.operation('close', project)
            projects.operation('load', project)
            projects.operation('use', project)
            client.command('NET LOAD DB')
            for unit, pp, document in snapshots:
                _expect(_values(programmer, network, unit) == pp, 'PP changed after project reload')
                reloaded = _document(client, unit)
                _expect(reloaded['pp'] == document['pp'], 'Raw database PP changed after project reload')
                # Native reload materializes two previously omitted scalar defaults.
                expected_scalars = {'DeviceName': 'NEWUNIT', 'GroupNumber': '', **document['scalars']}
                _expect(reloaded['scalars'] == expected_scalars, 'Unit metadata changed after project reload')
            report['reload_materialized_scalar_defaults'] = {'DeviceName': 'NEWUNIT', 'GroupNumber': ''}
            report['reload_verified_units'] = len(snapshots)
            projects.operation('close', project)
            projects.operation('delete', project)
            report['native_commands'] = len(client.commands)
    report['backend'] = {key: service.report[key] for key in
                         ('vendor_jar_sha256', 'java_sha256', 'listener_ownership_verified',
                          'projects_adopted', 'cleanup_complete', 'process_exit_confirmed', 'work_removed')}
    report['summary'] = {'directions': len(report['cases']),
                         'converted': sum(row['status'] == 'converted' for row in report['cases']),
                         'refused_short_original_source': sum(row['status'] == 'refused_short_original_source'
                                                             for row in report['cases'])}
    report['requested_directions_complete'] = False
    report['blocked_directions'] = [{'source_type': 'RELDN4', 'target_type': 'RELDN8',
                                     'reason': 'Native source has four logic elements; original tweaker reads eight'}]
    report['passed'] = report['summary'] == {'directions': 8, 'converted': 7,
                                           'refused_short_original_source': 1} and service.report['cleanup_complete']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', type=Path, default=os.environ.get('CBUS_LOCAL_CGATE_VENDOR'))
    parser.add_argument('--java', type=Path, default=os.environ.get('CBUS_CGATE_JAVA'))
    parser.add_argument('--unitspec', type=Path, default=os.environ.get('CBUS_UNITSPEC_DIR'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if any(value is None for value in (args.vendor, args.java, args.unitspec)):
        parser.error('Supply vendor, java and unitspec paths explicitly or via CBUS environment variables')
    report = run(vendor=args.vendor, java=args.java, spec_dir=args.unitspec)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['summary'], sort_keys=True))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
