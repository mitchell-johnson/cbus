#!/usr/bin/env python3
"""Owned native acceptance for ten non-sensor InputUnit 1.2.67 -> 1.2.67 Toolkit conversion.

Only synthetic database units and an owned ephemeral loopback C-Gate process
are used. Expected group and indicator strings are independent literals. This
helper never issues C-Gate CONVERTUNIT, opens a network, or contacts hardware.
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
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer, xml_text
from cbus_toolkit.toolkit_conversion_tweakers import (
    ToolkitTweakerConversion, TweakerConversionError, TweakerRefused, plan_writes,
)
from cbus_toolkit.unitspec import UnitCatalog, UnitSpecStore
from research.local_cgate import LocalCGate


KEY_TYPES = ('KEY1', 'KEY2', 'KEY4')
COUPLER_TYPES = ('KEYBC2', 'KEYBC4', 'BCNC4A', 'BCNC4B')
SOURCES = KEY_TYPES + COUPLER_TYPES
TARGETS = SOURCES
PAIRS = tuple((source, target) for source in KEY_TYPES for target in KEY_TYPES if source != target) + (
    ('KEYBC2', 'KEYBC4'), ('KEYBC4', 'KEYBC2'), ('BCNC4A', 'BCNC4B'), ('BCNC4B', 'BCNC4A'))
CATALOGS = {
    'KEY1': '5031N', 'KEY2': '5032N', 'KEY4': '5034N',
    'KEYBC2': '5102BCLEDL', 'KEYBC4': '5104BCL',
    'BCNC4A': '5032NLPCP', 'BCNC4B': '5032NLPC',
}
SOURCE_FIRMWARE = TARGET_FIRMWARE = '1.2.67'
SEED = {
    'GroupAddress': '0 127 254 255 42 99 231 17',
    'IndicatorFunction': '0 1 2 3',
    'IndicatorBlockAssignment': '3 2 1 0',
    'BlockAllocation': '1 3 5 15',
    'JPCommand': '0 1 2 15', 'SRCommand': '3 4 5 6',
    'LPCommand': '7 8 9 10', 'LRCommand': '11 12 13 14',
    'LightLevelStore1': '0 127 254 255', 'LightLevelStore2': '255 254 127 0',
    'TimerHighByte': '0 1 2 255', 'TimerLowByte': '255 254 1 0', 'TimerExpiryCommand': '0 1 2 15',
    'Application': '56 255', 'AreaGroupAddress': '254', 'GAVBroadcastFlag': '90',
    'LightLevel': '0 1 2 3 4 5 6 7 128 129 130 131 252 253 254 255',
    'LearnMode': '1', 'LearnAnyApp': '1', 'LearnedFlag': '0', 'PatchEnable': '85 170',
    'UnitName': 'KEYSRC',
}
# Both agents are classic: neither GroupAddress nor IndicatorFunction is
# reformatted by an original conversion hook. These pin exact aligned strings.
GROUP_PLAN = GROUP_RAW = '0x0 0x7f 0xfe 0xff 0x2a 0x63 0xe7 0x11'
INDICATOR_PLAN = '0x0 0x1 0x2 0x3'
INDICATOR_PREFIX = ('0x0', '0x1', '0x2', '0x3')
# These literals pin copied numeric prefixes independently of plan_writes.
COPIED_PREFIXES = {
    'IndicatorBlockAssignment': '0x3 0x2 0x1 0x0', 'BlockAllocation': '0x1 0x3 0x5 0xf',
    'JPCommand': '0x0 0x1 0x2 0xf', 'SRCommand': '0x3 0x4 0x5 0x6',
    'LPCommand': '0x7 0x8 0x9 0xa', 'LRCommand': '0xb 0xc 0xd 0xe',
    'LightLevelStore1': '0x0 0x7f 0xfe 0xff', 'LightLevelStore2': '0xff 0xfe 0x7f 0x0',
    'TimerHighByte': '0x0 0x1 0x2 0xff', 'TimerLowByte': '0xff 0xfe 0x1 0x0',
    'TimerExpiryCommand': '0x0 0x1 0x2 0xf', 'Application': '0x38 0xff',
    'AreaGroupAddress': '0xfe', 'LearnMode': '1', 'LearnAnyApp': '1',
    'LightLevel': '0x0 0x1 0x2 0x3 0x4 0x5 0x6 0x7 0x80 0x81 0x82 0x83 0xfc 0xfd 0xfe 0xff',
}
# Distinct original causes: LearnedFlag is disabled by the fresh-model hook,
# GAVBroadcastFlag starts immutable, and PatchEnable is absent from classic35.
RETAIN_DEFAULT = ('LearnedFlag', 'GAVBroadcastFlag', 'PatchEnable')



def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _expect(condition, message):
    if not condition:
        raise AssertionError(message)


class TrackingClient:
    def __init__(self, client):
        self.client, self.commands = client, []

    def command(self, text, *args, **kwargs):
        self.commands.append(text)
        if 'CONVERTUNIT' in text.upper() or text.upper().startswith(('NET OPEN', 'NETWORK OPEN')):
            raise AssertionError('Toolkit InputUnit acceptance must not use native conversion or open a network')
        return self.client.command(text, *args, **kwargs)

    def command_document(self, *_args, **_kwargs):
        raise AssertionError('InputUnit conversion acceptance does not need document writes')


class NoIO:
    def command(self, *_args, **_kwargs):
        raise AssertionError('refusal must occur before C-Gate I/O')

    command_document = command


class Inputs:
    def __init__(self, spec_dir, vendor):
        self.spec_dir = Path(spec_dir)
        self.store = UnitSpecStore(spec_dir)
        catalog_path = Path(vendor) / 'unitspec/cbusunits.xml'
        self.catalog = UnitCatalog.load(catalog_path)
        self.hashes = {'cbusunits.xml': sha256(catalog_path.read_bytes()).hexdigest()}

    def spec(self, unit_type):
        firmware = SOURCE_FIRMWARE if unit_type in SOURCES else TARGET_FIRMWARE
        name = self.catalog.select_spec(unit_type=unit_type, firmware=firmware, catalog_number=CATALOGS[unit_type])
        spec = self.store.load(name)
        for filename in spec.sources:
            self.hashes[filename] = sha256((self.spec_dir / filename).read_bytes()).hexdigest()
        return spec


def _values(programmer, network, unit):
    with programmer.load(network, '/db' + unit) as session:
        return session.values()


def _document(client, unit):
    root = ET.fromstring(xml_text(client.command('DBGETXML ' + unit)))
    return {'scalars': {child.tag: child.text or '' for child in root if len(child) == 0 and child.tag != 'PP'},
            'pp': {child.get('Name'): child.get('Value') for child in root if child.tag == 'PP'}}


def _make(database, programmer, network, unit_type, address, *, seed=False, firmware=None):
    firmware = firmware or (SOURCE_FIRMWARE if unit_type in SOURCES else TARGET_FIRMWARE)
    unit = f'{network}/p/{address}'
    database.create_unit(network, address, f'INPUT FIXTURE {address}', unit_type, firmware,
                         catalog_number=CATALOGS[unit_type])
    if seed:
        with programmer.load(network, '/db' + unit) as session:
            available = set(session.values())
            for name, value in SEED.items():
                if name in available:
                    session.set(name, value)
            if unit_type in KEY_TYPES:
                session.set('IndicatorBrightness', '173')
            session.save_to_source()
    return unit


def run(*, vendor, java, spec_dir):
    inputs = Inputs(spec_dir, vendor)
    for unit_type in CATALOGS:
        inputs.spec(unit_type)
    refusals = []
    for source_type, target_type in (('SENPILL', 'SENPILL'), ('KEY1', 'KEY1'),
                                     ('KEY1', 'KEYBC2'), ('BCNC4A', 'KEY1')):
        try:
            ToolkitTweakerConversion(NoIO(), source_type, None, target_type, None)
        except TweakerRefused:
            refusals.append(f'{source_type}>{target_type}')
        else:
            raise AssertionError('Out-of-profile pair was admitted')
    wrong_firmware = ToolkitTweakerConversion(NoIO(), 'KEYBC2', inputs.spec('KEYBC2'), 'KEYBC4', inputs.spec('KEYBC4'))
    try:
        wrong_firmware.apply('//INCHECK/254/p/10', 50, target_firmware='1.2.66', target_catalog=CATALOGS['KEYBC4'])
    except (TweakerRefused, TweakerConversionError, ValueError):
        pass
    else:
        raise AssertionError('Out-of-profile target firmware was admitted')
    service = LocalCGate(vendor, java=java)
    (service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
    root = Path(__file__).resolve().parents[1]
    code_inputs = ('research/input_tweaker_native.py', 'tests/test_input_tweaker_native.py',
                   'src/cbus_toolkit/toolkit_conversion_tweakers.py',
                   'src/cbus_toolkit/toolkit_conversion_key_to_neo.py',
                   'src/cbus_toolkit/toolkit_conversion_input_unit.py')
    report = {'format': 'cbus-toolkit-input-tweaker-native-v1', 'cases': [],
              'code_sha256': {name: sha256((root / name).read_bytes()).hexdigest() for name in code_inputs},
              'source_firmware': SOURCE_FIRMWARE, 'target_firmware': TARGET_FIRMWARE,
              'refused_pairs_before_io': refusals, 'target_firmware_refused_before_io': True,
              'native_convertunit_used': False, 'hardware_contacted': False,
              'original_toolkit_gui_executed': False, 'inputs': inputs.hashes}
    with service:
        with CGateClient('127.0.0.1', service.port, timeout=60) as raw_client:
            client = TrackingClient(raw_client)
            projects, database, programmer = NativeProjects(client), NativeDatabase(client), Programmer(client)
            project = 'I' + uuid4().hex[:7].upper()
            network = f'//{project}/254'
            projects.operation('new', project)
            projects.operation('use', project)
            client.command('DBCREATENET 254 InputAcceptance Cni 127.0.0.1:29999')
            client.command('NET LOAD DB')
            sources, defaults, snapshots = {}, {}, []
            for index, unit_type in enumerate(SOURCES):
                unit = _make(database, programmer, network, unit_type, 10 + index, seed=True)
                pp, document = _values(programmer, network, unit), _document(client, unit)
                sources[unit_type] = (unit, pp, document)
                snapshots.append((unit, pp, document))
            for index, unit_type in enumerate(TARGETS):
                unit = _make(database, programmer, network, unit_type, 210 + index)
                defaults[unit_type] = _values(programmer, network, unit)
            # A source firmware outside the evidenced profile must not create a replacement.
            unsupported = _make(database, programmer, network, 'KEYBC2', 19, firmware='1.2.66')
            converter = ToolkitTweakerConversion(client, 'KEYBC2', inputs.spec('KEYBC2'), 'KEYBC4', inputs.spec('KEYBC4'))
            mark = len(client.commands)
            try:
                converter.apply(unsupported, 200, target_firmware=TARGET_FIRMWARE, target_catalog=CATALOGS['KEYBC4'])
            except (TweakerRefused, TweakerConversionError, ValueError):
                pass
            else:
                raise AssertionError('Out-of-profile source firmware was admitted')
            issued = client.commands[mark:]
            _expect(not any(command.startswith(('DBADD', 'DBSET', 'PP SET', 'PP SAVE')) for command in issued),
                    'Source firmware refusal performed a write')
            report['source_firmware_refused_before_target_creation'] = True
            for index, (source_type, target_type) in enumerate(PAIRS):
                source, before, source_document = sources[source_type]
                source_spec, target_spec = inputs.spec(source_type), inputs.spec(target_type)
                plan = plan_writes(source_type, target_type, before, set(target_spec.parameters),
                                   target_firmware=TARGET_FIRMWARE)
                planned = {name: value for name, value, _ in plan.writes}
                _expect(planned['GroupAddress'] == GROUP_PLAN, 'Original group literal plan differs')
                _expect(planned['IndicatorFunction'] == INDICATOR_PLAN, 'Original indicator literal plan differs')
                _expect(('IndicatorBrightness' in planned) == (target_type in KEY_TYPES),
                        'Target brightness property did not control the write')
                _expect('GAVBroadcastFlag' not in planned, 'Immutable GAV flag was incorrectly copied')
                _expect('PatchEnable' not in planned, 'PP-only PatchEnable was incorrectly copied')
                _expect(_document(client, source) == source_document, 'Read-only planning changed source')
                converter = ToolkitTweakerConversion(client, source_type, source_spec, target_type, target_spec)
                result = converter.apply(source, 50 + index, target_firmware=TARGET_FIRMWARE,
                                         target_catalog=CATALOGS[target_type], tag_name=f'INPUT TARGET {index}')
                _expect(result['failed_writes'] == {}, f'{source_type}->{target_type}: PP SET failed')
                target = f'{network}/p/{50 + index}'
                after, document = _values(programmer, network, target), _document(client, target)
                baseline = defaults[target_type]
                expected_fields = {'GroupAddress': GROUP_RAW,
                                   'IndicatorFunction': ' '.join((*INDICATOR_PREFIX, *baseline['IndicatorFunction'].split()[4:]))}
                if target_type in KEY_TYPES:
                    expected_fields['IndicatorBrightness'] = '0xad'
                for name, prefix in COPIED_PREFIXES.items():
                    tokens = prefix.split()
                    expected_fields[name] = ' '.join((*tokens, *baseline[name].split()[len(tokens):]))
                for name, expected in expected_fields.items():
                    _expect(after[name] == expected, f'{source_type}->{target_type}: native PP mismatch {name}')
                    _expect(document['pp'][name] == expected, f'{source_type}->{target_type}: raw PP mismatch {name}')
                for name in RETAIN_DEFAULT:
                    if name in baseline:
                        _expect(after[name] == baseline[name], f'{source_type}->{target_type}: target default changed {name}')
                _expect(after['UnitName'] == before['UnitName'], 'Copied unit name changed')
                _expect(before['PatchEnable'] == '0x55 0xaa', 'Synthetic PP-only PatchEnable was not seeded')
                if source_type in COUPLER_TYPES:
                    _expect(before['GAVBroadcastFlag'] == '0x5a', 'Synthetic immutable source GAV flag was not seeded')
                    _expect(after['GAVBroadcastFlag'] == '0xff', 'Immutable target GAV flag default changed')
                _expect(document['scalars']['UnitType'] == target_type, 'Target identity changed')
                _expect(_values(programmer, network, source) == before, 'Source PP changed')
                _expect(_document(client, source) == source_document, 'Source metadata changed')
                _expect(plan_writes(source_type, target_type, before, set(target_spec.parameters),
                                    target_firmware=TARGET_FIRMWARE) == plan, 'Repeated read-only plan changed')
                _expect(client.command('NOOP').code == 200, 'Native NOOP failed')
                _expect(_document(client, target) == document, 'NOOP changed target')
                report['cases'].append({'source_type': source_type, 'target_type': target_type,
                                        'source_catalog': CATALOGS[source_type], 'target_catalog': CATALOGS[target_type],
                                        'plan_writes': len(plan.writes), 'verified_parameters': result['verified_parameters'],
                                        'group_raw': after['GroupAddress'], 'indicator_raw': after['IndicatorFunction'],
                                        'indicator_brightness_raw': after.get('IndicatorBrightness'),
                                        'source_gav_flag_raw': before.get('GAVBroadcastFlag'),
                                        'target_gav_flag_raw': after.get('GAVBroadcastFlag'),
                                        'source_patch_enable_raw': before['PatchEnable'],
                                        'target_patch_enable_raw': after['PatchEnable'],
                                        'target_spec_filename': target_spec.filename,
                                        'target_spec_identity': target_spec.unit_type,
                                        'source_pp_sha256': _hash(source_document['pp']),
                                        'target_pp_sha256': _hash(document['pp']),
                                        'source_preserved': True, 'repeated_plan_unchanged': True,
                                        'noop_unchanged': True, 'failed_writes': {}, 'passed': True})
                snapshots.append((target, after, document))
            projects.operation('save', project)
            projects.operation('close', project)
            projects.operation('load', project)
            projects.operation('use', project)
            client.command('NET LOAD DB')
            for unit, pp, document in snapshots:
                _expect(_values(programmer, network, unit) == pp, 'PP changed after project reload')
                reloaded = _document(client, unit)
                _expect(reloaded['pp'] == document['pp'], 'Raw database PP changed after project reload')
                expected_scalars = {'DeviceName': 'NEWUNIT', 'GroupNumber': '', **document['scalars']}
                _expect(reloaded['scalars'] == expected_scalars, 'Unit metadata changed after project reload')
            report['reload_verified_units'] = len(snapshots)
            report['reload_materialized_scalar_defaults'] = {'DeviceName': 'NEWUNIT', 'GroupNumber': ''}
            projects.operation('close', project)
            projects.operation('delete', project)
            report['native_commands'] = len(client.commands)
    report['backend'] = {key: service.report[key] for key in
                         ('vendor_jar_sha256', 'java_sha256', 'listener_ownership_verified',
                          'projects_adopted', 'cleanup_complete', 'process_exit_confirmed', 'work_removed')}
    report['summary'] = {'directions': len(report['cases']), 'passed': sum(row['passed'] for row in report['cases'])}
    report['passed'] = report['summary'] == {'directions': 10, 'passed': 10} and service.report['cleanup_complete']
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
