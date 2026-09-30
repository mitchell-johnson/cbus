#!/usr/bin/env python3
"""Owned native acceptance for classic 1.2.67 -> Neo 2.5.00 Toolkit conversion.

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


SOURCES = ('KEY1', 'KEY2', 'KEY4', 'KEYIR1', 'KEYIR4')
NEO_TARGETS = ('KEYB2', 'KEYB4', 'KEYB6', 'KEYH1', 'KEYH2', 'KEYH3', 'KEYH4',
               'KEYM2', 'KEYM4', 'KEYM8', 'KEYA1', 'KEYA3', 'KEYA6', 'KEYA8', 'KEYAV2', 'KEYAV4')
PAIRS = tuple((source, target) for source in SOURCES for target in NEO_TARGETS) + tuple(
    (source, target) for source in SOURCES[:3] for target in ('KEYC1', 'KEYC2', 'KEYC4')) + tuple(
    (source, target) for source in SOURCES[3:] for target in ('KEYCIR1', 'KEYCIR4'))
TARGETS = tuple(dict.fromkeys(target for _, target in PAIRS))
CATALOGS = {
    'KEY1': '5031N', 'KEY2': '5032N', 'KEY4': '5034N', 'KEYIR1': '5031NIR', 'KEYIR4': '5034NIR',
    'KEYB2': '5082NL', 'KEYB4': '5084NL', 'KEYB6': '5086NL',
    'KEYH1': 'R5041NL', 'KEYH2': 'R5042NL', 'KEYH3': 'R5043NL', 'KEYH4': 'R5044NL',
    'KEYM2': '5052NL', 'KEYM4': '5054NL', 'KEYM8': '5058NL',
    'KEYA1': 'R5061NL', 'KEYA3': 'R5063NL', 'KEYA6': 'R5066NL', 'KEYA8': 'R5068NL',
    'KEYAV2': 'R5062VNL', 'KEYAV4': 'R5064VNL',
    'KEYC1': '5031NL', 'KEYC2': '5032NL', 'KEYC4': '5034NL',
    'KEYCIR1': '5031NIRL', 'KEYCIR4': '5034NIRL',
}
SOURCE_FIRMWARE, TARGET_FIRMWARE = '1.2.67', '2.5.00'
SEED = {
    'GroupAddress': '0 127 254 255 42 99 231 17',
    'IndicatorFunction': '0 1 2 3',
    'IndicatorBlockAssignment': '3 2 1 0',
    'BlockAllocation': '1 3 5 15',
    'JPCommand': '0 1 2 15', 'SRCommand': '3 4 5 6',
    'LPCommand': '7 8 9 10', 'LRCommand': '11 12 13 14',
    'LightLevelStore1': '0 127 254 255', 'LightLevelStore2': '255 254 127 0',
    'TimerHighByte': '0 1 2 255', 'TimerLowByte': '255 254 1 0', 'TimerExpiryCommand': '0 1 2 15',
    'Application': '56 255', 'AreaGroupAddress': '254', 'IndicatorBrightness': '173',
    'LearnMode': '1', 'LearnAnyApp': '1', 'LearnedFlag': '0', 'PatchEnable': '85 170',
    'UnitName': 'KEYSRC',
}
# Original CoreKey's IntToHex(2) formatting is uppercase and padded; original
# KeyToNeo indicator remapping deliberately retains one trailing space.
GROUP_PLAN = '0x00 0x7F 0xFE 0xFF 0xFF 0xFF 0xFF 0xFF 0x2A'
GROUP_RAW = '0x0 0x7f 0xfe 0xff 0xff 0xff 0xff 0xff 0x2a'
INDICATOR_PLAN = '0 2 2 1 '
INDICATOR_PREFIX = ('0x0', '0x2', '0x2', '0x1')
# These literals pin copied numeric prefixes independently of plan_writes.
COPIED_PREFIXES = {
    'IndicatorBlockAssignment': '0x3 0x2 0x1 0x0', 'BlockAllocation': '0x1 0x3 0x5 0xf',
    'JPCommand': '0x0 0x1 0x2 0xf', 'SRCommand': '0x3 0x4 0x5 0x6',
    'LPCommand': '0x7 0x8 0x9 0xa', 'LRCommand': '0xb 0xc 0xd 0xe',
    'LightLevelStore1': '0x0 0x7f 0xfe 0xff', 'LightLevelStore2': '0xff 0xfe 0x7f 0x0',
    'TimerHighByte': '0x0 0x1 0x2 0xff', 'TimerLowByte': '0xff 0xfe 0x1 0x0',
    'TimerExpiryCommand': '0x0 0x1 0x2 0xf', 'Application': '0x38 0xff',
    'AreaGroupAddress': '0xfe', 'IndicatorBrightness': '0xad', 'LearnMode': '1', 'LearnAnyApp': '1',
}
RETAIN_DEFAULT = (
    'LearnedFlag', 'PatchEnable', 'ControlAppGroupAddress', 'SceneKeySelector', 'SceneTable', 'SceneTablePointer',
    'TimerDuration', 'EnableNightlight', 'EnableNightlightControl', 'DisableTimerFlash', 'FirstKeyThrowAway',
    'IndicatorPressedLevel', 'IDBacklightIllumination', 'PrimaryColour', 'EnableNightlightOnPCx',
    'EnableNightlightOnPA6', 'DisableIR', 'DisableIRNEC', 'IRBank', 'SecondApplicationBlocks',
    'KeyDisableGroup', 'KeyDisableGroupInvert', 'HardwareConfiguration', 'CorridorOfficeGroupBlock',
    'CorridorGroupBlock', 'CorridorLinkEnable', 'JoinPrimaryApplication', 'DualJoinPrimaryApplication',
    'CorridorMasterGroup', 'JoinSecondaryApplication', 'DualJoinSecondaryApplication', 'SerialNo',
)


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
            raise AssertionError('Toolkit key acceptance must not use native conversion or open a network')
        return self.client.command(text, *args, **kwargs)

    def command_document(self, *_args, **_kwargs):
        raise AssertionError('Key conversion acceptance does not need document writes')


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
    database.create_unit(network, address, f'KEY FIXTURE {address}', unit_type, firmware,
                         catalog_number=CATALOGS[unit_type])
    if seed:
        with programmer.load(network, '/db' + unit) as session:
            for name, value in SEED.items():
                session.set(name, value)
            if unit_type.startswith('KEYIR'):
                session.set('InfraRedBank', '2')
            session.save_to_source()
    return unit


def run(*, vendor, java, spec_dir):
    inputs = Inputs(spec_dir, vendor)
    for unit_type in CATALOGS:
        inputs.spec(unit_type)
    refusals = []
    for source_type, target_type in (('KEYBC2', 'BCN2B'), ('DINAUX4', 'BCI4A'),
                                     ('KEYC1', 'KEY1'), ('KEY1', 'KEY1')):
        try:
            ToolkitTweakerConversion(NoIO(), source_type, None, target_type, None)
        except TweakerRefused:
            refusals.append(f'{source_type}>{target_type}')
        else:
            raise AssertionError('Out-of-profile pair was admitted')
    wrong_firmware = ToolkitTweakerConversion(NoIO(), 'KEY1', inputs.spec('KEY1'), 'KEYB2', inputs.spec('KEYB2'))
    try:
        wrong_firmware.apply('//KEYCHECK/254/p/10', 50, target_firmware='2.4.99', target_catalog=CATALOGS['KEYB2'])
    except (TweakerRefused, TweakerConversionError, ValueError):
        pass
    else:
        raise AssertionError('Out-of-profile target firmware was admitted')
    service = LocalCGate(vendor, java=java)
    (service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
    root = Path(__file__).resolve().parents[1]
    code_inputs = ('research/keytweaker_native.py', 'tests/test_keytweaker_native.py',
                   'src/cbus_toolkit/toolkit_conversion_tweakers.py',
                   'src/cbus_toolkit/toolkit_conversion_key_to_neo.py')
    report = {'format': 'cbus-toolkit-keytweaker-native-v1', 'cases': [],
              'code_sha256': {name: sha256((root / name).read_bytes()).hexdigest() for name in code_inputs},
              'source_firmware': SOURCE_FIRMWARE, 'target_firmware': TARGET_FIRMWARE,
              'refused_pairs_before_io': refusals, 'target_firmware_refused_before_io': True,
              'native_convertunit_used': False, 'hardware_contacted': False,
              'original_toolkit_gui_executed': False, 'inputs': inputs.hashes}
    with service:
        with CGateClient('127.0.0.1', service.port, timeout=60) as raw_client:
            client = TrackingClient(raw_client)
            projects, database, programmer = NativeProjects(client), NativeDatabase(client), Programmer(client)
            project = 'K' + uuid4().hex[:7].upper()
            network = f'//{project}/254'
            projects.operation('new', project)
            projects.operation('use', project)
            client.command('DBCREATENET 254 KeyAcceptance Cni 127.0.0.1:29999')
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
            unsupported = _make(database, programmer, network, 'KEY1', 16, firmware='1.2.66')
            converter = ToolkitTweakerConversion(client, 'KEY1', inputs.spec('KEY1'), 'KEYB2', inputs.spec('KEYB2'))
            mark = len(client.commands)
            try:
                converter.apply(unsupported, 200, target_firmware=TARGET_FIRMWARE, target_catalog=CATALOGS['KEYB2'])
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
                _expect(_document(client, source) == source_document, 'Read-only planning changed source')
                converter = ToolkitTweakerConversion(client, source_type, source_spec, target_type, target_spec)
                result = converter.apply(source, 50 + index, target_firmware=TARGET_FIRMWARE,
                                         target_catalog=CATALOGS[target_type], tag_name=f'KEY TARGET {index}')
                _expect(result['failed_writes'] == {}, f'{source_type}->{target_type}: PP SET failed')
                target = f'{network}/p/{50 + index}'
                after, document = _values(programmer, network, target), _document(client, target)
                baseline = defaults[target_type]
                expected_fields = {'GroupAddress': GROUP_RAW,
                                   'IndicatorFunction': ' '.join((*INDICATOR_PREFIX, *baseline['IndicatorFunction'].split()[4:]))}
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
    report['passed'] = report['summary'] == {'directions': 93, 'passed': 93} and service.report['cleanup_complete']
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
