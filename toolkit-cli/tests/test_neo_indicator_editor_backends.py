"""Public per-unit Neo indicator histories against two owned Rust backends.

All specifications, projects and endpoints are test-owned. Literal expectations
derive from the retained Toolkit source review; no original instructions,
native vendor service or physical C-Bus endpoint execute here.
"""
from contextlib import contextmanager
import hashlib
import json
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.file_transfer import prepare_upload, upload
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.neo_indicators import OPTION_LAYOUTS, STYLE_LAYOUTS
from cbus_toolkit.programming import Programmer, xml_text
from test_cgate_barcode_database_interop import FaultGate, cli, selected_binary
from test_cgate_din_save_interop import assert_preservation, saved_once
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)


BACKENDS = [('cgate-mock', 'CBUS_CGATE_MOCK_BIN'), ('cmqttd', 'CBUS_CMQTTD_BIN')]
NETWORK = '//NEOLED/11'
SOURCE = '/db//NEOLED/11/p/20'
CASES = {
    'neo': ('KEYM4', 'SYNTHETIC'),
    'reflection': ('KEYA3', 'SYNTHETIC'),
    'classic': ('KEYC4', 'SYNTHETIC'),
    'saturn': ('KEYB4', 'SYNTHETIC'),
    'decorator': ('KEYDV2', 'SYNTHETIC'),
    'avanti': ('KEYV2', 'SYNTHETIC'),
    'catalogue-red': ('KEYM4', '5041NMML'),
}
EXTRA_LAYOUTS = {
    'NightlightColour': ('bit', 0x34, 1, 1, 2, 0),
    'EnableNightlightControl': ('bit', 0x34, 1, 1, 7, 0),
    'SceneKeySelector': ('int', 0x60, 8, 1, 7, 0),
    'IndicatorBlockAssignment': ('int', 0x60, 8, 3, 0, 0),
    'PackedNeighbour': ('int', 0x60, 8, 1, 6, 0),
    'JPCommand': ('int', 0x68, 8, 4, 4, 1),
    'SRCommand': ('int', 0x68, 8, 4, 0, 1),
    'LPCommand': ('int', 0x69, 8, 4, 4, 1),
    'LRCommand': ('int', 0x69, 8, 4, 0, 1),
    'UnitAddress': ('int', 0x20, 1, 8, 0, 0),
    'UnrelatedParameter': ('int', 0xF0, 1, 8, 0, 0),
}
VALUES = {
    'IndicatorBrightness': '255', 'GroupAddress': '1 2 3 4 5 6 7 8 9',
    'IndicatorPressedLevel': '15', 'TimerDuration': '15', 'EnableNightlight': '0',
    'DisableTimerFlash': '0', 'IDBacklightIllumination': '0', 'FirstKeyThrowAway': '0',
    'EnableNightlightOnPCx': '0', 'EnableNightlightOnPA6': '0',
    'IndicatorFunction': '3 0 1 2 3 1 0 3', 'PrimaryColour': '0 1 0 1 0 1 0 1',
    'NightlightColour': '0', 'EnableNightlightControl': '1',
    'SceneKeySelector': '1 0 1 0 1 0 1 0',
    'IndicatorBlockAssignment': '7 6 5 4 3 2 1 0', 'PackedNeighbour': '0 1 0 1 0 1 0 1',
    'JPCommand': '1 2 3 4 5 6 7 8', 'SRCommand': '8 7 6 5 4 3 2 1',
    'LPCommand': '9 10 11 12 13 14 15 0', 'LRCommand': '0 15 14 13 12 11 10 9',
    'UnitAddress': '20', 'UnrelatedParameter': '177',
}


def write_spec(folder, unit_type):
    root = ET.Element('UnitSpecification')
    ET.SubElement(root, 'Type').text = unit_type
    parameters = ET.SubElement(root, 'Parameters')
    for name, (kind, address, count, bits, offset, skip) in {
            **OPTION_LAYOUTS, **STYLE_LAYOUTS, **EXTRA_LAYOUTS}.items():
        node = ET.SubElement(parameters, 'Param')
        fields = {'Name': name, 'Type': kind, 'Address': str(address), 'ArraySize': str(count),
                  'BitSize': str(bits), 'BitAddress': str(offset), 'ArraySkip': str(skip),
                  'DefaultValue': VALUES[name]}
        for key, value in fields.items():
            ET.SubElement(node, key).text = value
    path = folder / (unit_type + '.xml')
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
    return path


def seed(owner, work, trap, unit_type, catalogue):
    root = ET.Element('Installation')
    ET.SubElement(root, 'DBVersion').text = '2.3'
    project = ET.SubElement(root, 'Project')
    for name, value in (('OID', str(uuid.uuid4())), ('TagName', 'NEOLED'), ('Address', 'NEOLED')):
        ET.SubElement(project, name).text = value
    network = ET.SubElement(project, 'Network')
    for name, value in (('OID', str(uuid.uuid4())), ('Address', '11'), ('NetworkNumber', '11'),
                        ('TagName', 'Closed synthetic indicator network')):
        ET.SubElement(network, name).text = value
    interface = ET.SubElement(network, 'Interface')
    for name, value in (('OID', str(uuid.uuid4())), ('InterfaceType', 'cni'), ('InterfaceAddress', trap)):
        ET.SubElement(interface, name).text = value
    unit = ET.SubElement(network, 'Unit')
    for name, value in (('OID', str(uuid.uuid4())), ('Address', '20'), ('TagName', 'Selected Neo'),
                        ('UnitName', 'NEO20'), ('UnitType', unit_type), ('FirmwareVersion', '2.5.00'),
                        ('SerialNumber', '123456.7'), ('CatalogNumber', catalogue)):
        ET.SubElement(unit, name).text = value
    unit.append(ET.Comment('preserve selected unit comment'))
    for name, value in VALUES.items():
        ET.SubElement(unit, 'PP', Name=name, Value=value)
    sibling = ET.SubElement(network, 'Unit')
    for name, value in (('OID', str(uuid.uuid4())), ('Address', '21'), ('TagName', 'Sibling'),
                        ('UnitName', 'Sibling'), ('UnitType', 'KEY1'), ('FirmwareVersion', '1.2.67')):
        ET.SubElement(sibling, name).text = value
    ET.SubElement(sibling, 'PP', Name='OpaqueSetting', Value='retained & exact Ω')
    network.append(ET.Comment('preserve network comment'))
    ET.SubElement(network, '{urn:cbus:synthetic:neo}Unrelated', token='retain').text = 'unchanged Ω'
    path = work / 'neo-synthetic.xml'
    path.write_bytes(ET.tostring(root))
    for command in ('FILE MKDIR Projects', 'FILE MKDIR Projects/archived'):
        assert owner.command(command).code == 200
    assert upload(prepare_upload('Projects/archived/' + path.name, path), owner)['upload_completed']
    for command in ('PROJECT RESTORE NEOLED ' + path.name, 'PROJECT USE NEOLED', 'PROJECT SAVE NEOLED'):
        assert owner.command(command).code == 200


@contextmanager
def journey(backend, variable, case, tmp_path):
    unit_type, catalogue = CASES[case]
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'backend')
    specs = tmp_path / 'synthetic-specs'
    specs.mkdir()
    write_spec(specs, unit_type)
    write_spec(specs, 'KEYM8')  # A real distinct admitted type for freshness refusal.
    flag = '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec'
    evidence = {'format': 'cbus-neo-indicator-editor-owned-v1', 'backend': backend, 'case': case,
                'unit_type': unit_type, 'catalog_number': catalogue,
                'original_execution': False, 'physical_acceptance': False,
                'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'specification_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                         for path in specs.iterdir()},
                'calls': [], 'processes': [], 'wires': []}
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(
                backend, binary, work, extra_args=(flag, specs)) as (endpoint, process):
            evidence['processes'].append(process)
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                seed(owner, work, trap, unit_type, catalogue)
                yield owner, relay, evidence, specs, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'].extend(relay.evidence())
        associated_evidence(tmp_path / 'neo-indicator-editor-evidence.json', evidence)


def document(owner):
    return xml_text(NativeDatabase(owner).get('//NEOLED', xml=True))


def neo_cli(relay, evidence, specs, *options, dry_run=False, expected=0, complete=True,
            source=SOURCE, destination=None, empty_wire=False):
    arguments = ['unit', '--lock-address', NETWORK, '--source', source]
    if destination is not None:
        arguments.extend(('--destination', destination))
    if dry_run:
        arguments.append('--dry-run')
    arguments.extend(('neo-indicator-editor', '--spec-dir', specs,
                      '--spec', evidence['unit_type'] + '.xml', *options))
    if empty_wire:
        # The database-source guard runs after the greeting but before PP I/O.
        # The shared tagged-wire parser intentionally requires a command, so
        # retain this zero-command connection directly instead.
        before = len(relay.rows)
        argv = [sys.executable, '-m', 'cbus_toolkit', 'cgate', '--host', relay.endpoint[0],
                '--port', str(relay.endpoint[1]), '--timeout', '3', *map(str, arguments)]
        process = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        result = json.loads(process.stdout or process.stderr)
        call = {'argv': argv, 'exit': process.returncode, 'stdout': process.stdout,
                'stderr': process.stderr, 'result': result, 'commands': [], 'statuses': [],
                'terminals': [], 'documents': [], 'reply_lines': [], 'wire_index': before}
        evidence['calls'].append(call)
        assert process.returncode == expected, call
        assert len(relay.rows) == before + 1
        assert relay.rows[before]['done'].wait(5)
        assert relay.rows[before]['request_hex'] == ''
    else:
        result, call = cli(relay, evidence['calls'], *arguments, expected=expected, complete=complete)
    assert not any(command.startswith(('NET OPEN ', 'PROJECT SAVE ', 'PP PROGRAM '))
                   for command in call['commands']), call
    return result, call


def json_file(tmp_path, name, value):
    path = tmp_path / (name + '.json')
    path.write_text(json.dumps(value))
    return path


def offline_plan(specs, tmp_path, evidence, current, operations):
    source = json_file(tmp_path, 'snapshot', {
        'format': 'cbus-cli-parameters-v1', 'unit_type': evidence['unit_type'],
        'firmware': '2.5.00', 'catalog_number': evidence['catalog_number'], 'parameters': current})
    controls = json_file(tmp_path, 'controls', operations)
    before = source.read_bytes(), controls.read_bytes()
    argv = [sys.executable, '-m', 'cbus_toolkit', 'keys', '--spec-dir', str(specs),
            'neo-indicator-editor-plan', evidence['unit_type'] + '.xml', str(source),
            '--controls', str(controls)]
    process = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stdout + process.stderr
    assert (source.read_bytes(), controls.read_bytes()) == before
    return json.loads(process.stdout), controls


def fresh_parameters(relay, evidence):
    result, call = cli(relay, evidence['calls'], 'unit', '--lock-address', NETWORK,
                       '--source', SOURCE, 'show')
    assert sum(command.startswith('PP LOAD ') for command in call['commands']) == 1
    no_write(call)
    return result


def packed_bytes(owner):
    with Programmer(owner).load(NETWORK, SOURCE) as session:
        rows = {}
        for start, count in ((0x32, 3), (0x60, 8), (0x68, 16)):
            raw = session.get_raw_data(start, count).lines[-1].split('RawData=', 1)[1]
            rows[f'{start:02x}'] = bytes.fromhex(raw).hex()
        return rows


def no_write(call):
    assert not any(command.startswith(('PP SET ', 'PP SAVE', 'PROJECT SAVE ', 'PP PROGRAM '))
                   for command in call['commands']), call


def history(case):
    if case == 'reflection':
        return [{'led': 2, 'style': 'status_on'}]
    if case == 'classic':
        return [{'led': 3, 'style': 'always_off'}]
    first_colour = 'green' if case == 'avanti' else 'red' if case == 'catalogue-red' else 'orange'
    second_colour = 'red' if case == 'avanti' else 'blue'
    # LED1 deliberately has SceneKeySelector1. This panel selects physical
    # LEDs directly; a monitored block or scene assignment cannot reorder it.
    operations = [
        {'led': 2, 'style': 'status_dual'}, {'led': 2, 'on_colour': second_colour},
        {'led': 1, 'on_colour': first_colour}, {'led': 1, 'style': 'always_off'},
        {'brightness_source': 'first_block'}, {'brightness_source': 'fixed'},
        {'fixed_brightness_percent': 50},
        {'key_press_brightness_enabled': False}, {'key_press_brightness_enabled': True},
        {'key_press_brightness_level': 9}, {'key_press_duration': 4},
        {'nightlight_enabled': True}, {'first_press_ignored': True}, {'timer_flash_enabled': False},
    ]
    if case in ('neo', 'catalogue-red'):
        operations.append({'id_backlight_enabled': True})
    if case in ('saturn', 'avanti'):
        operations.append({'nightlight_colour': 'red' if case == 'avanti' else 'blue'})
    return operations


def expected_changes(case):
    if case == 'reflection':
        return {'IndicatorFunction': '2 2 1 2 2 1 0 2', 'PrimaryColour': '1 1 1 1 1 1 1 1'}
    if case == 'classic':
        # The original Classic loader skips the hidden control; its fresh
        # model Boolean is false and the inherited save still owns that bit.
        return {'IndicatorFunction': '2 0 0 2 2 1 0 2', 'EnableNightlightControl': '0',
                'IndicatorPressedLevel': '0', 'TimerDuration': '0'}
    result = {'IndicatorFunction': '0 3 1 2 3 1 0 3', 'PrimaryColour': '1 0 0 1 0 1 0 1',
              'IndicatorBrightness': '127', 'IndicatorPressedLevel': '9', 'TimerDuration': '4',
              'FirstKeyThrowAway': '1', 'DisableTimerFlash': '1'}
    result['EnableNightlightOnPCx' if case in ('saturn', 'avanti') else 'EnableNightlightOnPA6'] = '1'
    if case in ('neo', 'catalogue-red'):
        result['IDBacklightIllumination'] = '1'
    if case in ('saturn', 'avanti'):
        result['NightlightColour'] = '1'
    return result


def expected_packed(case):
    return {'reflection': 'af6e9d6cab5a8968', 'classic': 'a74e856ca35a8168'}.get(
        case, '8f76956cb35a8178')


def expected_global_bytes(case):
    return {'reflection': 'ffff80', 'classic': 'ff0000', 'decorator': '7f94d2',
            'saturn': '7f94b6', 'avanti': '7f94b6'}.get(case, '7f94da')


def wrong_history(case):
    if case == 'reflection':
        return [{'led': 1, 'style': 'status_dual'}]
    if case == 'classic':
        return [{'led': 1, 'on_colour': 'blue'}]
    return [{'led': 1, 'style': 'always_off'},
            {'led': 1, 'on_colour': 'red' if case == 'avanti' else 'blue'}]


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('case', CASES)
def test_public_neo_indicator_editor_all_contexts(backend, variable, case, tmp_path):
    with journey(backend, variable, case, tmp_path) as context:
        owner, relay, evidence, specs, _ = context
        before = document(owner)
        current = fresh_parameters(relay, evidence)
        raw_before = packed_bytes(owner)
        assert raw_before['60'] == 'b74e956cb35a8178'
        assert raw_before['32'] == 'ffff80'
        operations = history(case)
        plan, controls = offline_plan(specs, tmp_path, evidence, current, operations)
        assert plan['format'] == 'cbus-neo-indicator-editor-plan-v1'
        assert plan['operations'] == operations
        expected = expected_changes(case)
        assert plan['changes'] == {name: list(map(int, values.split())) for name, values in expected.items()}
        preview, call = neo_cli(relay, evidence, specs, '--controls', controls, dry_run=True)
        for key, value in plan.items():
            assert preview[key] == value, (key, preview[key], value)
        assert preview['verified'] is True and preview['saved'] is False
        assert not any(command.startswith('PP SAVE') for command in call['commands'])
        assert document(owner) == before
        assert fresh_parameters(relay, evidence) == current
        assert packed_bytes(owner) == raw_before

        # Recompute the ordered callbacks rather than trusting a caller's
        # derived writes or accepting Boolean values as serialized integers.
        tampered = json.loads(json.dumps(plan))
        tampered['changes']['IndicatorFunction'][0] = 1
        malformed = json.loads(json.dumps(plan))
        malformed['expected']['IndicatorFunction'][0] = True
        for name, invalid in (('tampered-plan', tampered), ('boolean-plan', malformed)):
            refused, call = neo_cli(relay, evidence, specs, '--plan',
                                   json_file(tmp_path, name, invalid), expected=1)
            assert refused['error']
            no_write(call)
        refused, call = neo_cli(relay, evidence, specs, '--controls',
                               json_file(tmp_path, 'refused-controls', wrong_history(case)), expected=1)
        assert refused['error']
        no_write(call)
        if case == 'saturn':
            refused, call = neo_cli(relay, evidence, specs, '--controls', json_file(
                tmp_path, 'disabled-global-controls', [
                    {'key_press_brightness_enabled': False}, {'key_press_brightness_level': 9},
                ]), expected=1)
            assert refused['error']
            no_write(call)
        assert document(owner) == before

        reviewed = json_file(tmp_path, 'reviewed-plan', plan)
        if case == 'neo':
            # A saved plan binds the exact loaded identity, including catalogue
            # context which determines the displayed colour labels.
            database = NativeDatabase(owner)
            for property_name, value, original in (
                ('UnitType', 'KEYM8', 'KEYM4'),
                ('FirmwareVersion', '2.5.01', '2.5.00'),
                ('CatalogNumber', 'SYNTHETIC-CHANGED', 'SYNTHETIC'),
            ):
                field = '//NEOLED/11/p/20/' + property_name
                assert database.set(field, value).code == 200
                changed_identity = document(owner)
                refused, call = neo_cli(relay, evidence, specs, '--plan', reviewed, expected=1)
                assert refused['error']
                no_write(call)
                assert document(owner) == changed_identity
                assert database.set(field, original).code == 200
            assert document(owner) == before
            for flags in ({'source': '//NEOLED/11/p/20'},
                          {'destination': '/db//NEOLED/11/p/21'}):
                refused, call = neo_cli(relay, evidence, specs, '--controls', controls,
                                       expected=1, empty_wire=True, **flags)
                assert refused['error']
                assert not any(command.startswith('PP ') for command in call['commands'])
            assert document(owner) == before

        applied, call = neo_cli(relay, evidence, specs, '--plan', reviewed)
        assert applied['saved'] is True and applied['verified'] is True
        assert applied['operations'] == operations
        saved_once(call)
        after = document(owner)
        assert_preservation(before, after, expected)
        fresh = fresh_parameters(relay, evidence)
        assert fresh == applied['parameters']
        assert {name: fresh[name] for name in expected} == expected
        raw_after = packed_bytes(owner)
        assert raw_after['60'] == expected_packed(case)
        assert raw_after['32'] == expected_global_bytes(case)
        assert raw_after['68'] == raw_before['68']
        for name in ('SceneKeySelector', 'IndicatorBlockAssignment', 'PackedNeighbour',
                     'JPCommand', 'SRCommand', 'LPCommand', 'LRCommand'):
            assert fresh[name] == current[name]
        assert fresh['EnableNightlightControl'] == ('0' if case == 'classic' else '1')

        refused, call = neo_cli(relay, evidence, specs, '--plan', reviewed, expected=1)
        assert 'changed since' in refused['error']
        no_write(call)
        assert document(owner) == after
        for action in ('save', 'close', 'load'):
            result, call = cli(relay, evidence['calls'], 'project', action, 'NEOLED')
            assert result['status'] == 200
            assert call['commands'] == [f'PROJECT {action.upper()} NEOLED']
        assert owner.command('PROJECT USE NEOLED').code == 200
        assert document(owner) == after
        assert fresh_parameters(relay, evidence) == fresh
        assert packed_bytes(owner) == raw_after
        evidence['operations'] = operations
        evidence['expected_changes'] = expected
        evidence['packed_reads'] = {'before': raw_before, 'after': raw_after}
        evidence['snapshots'] = {'before': before, 'after': after}


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('case', ['reflection', 'saturn'])
def test_public_neo_indicator_editor_lost_successful_save_is_not_replayed(
        backend, variable, case, tmp_path):
    with journey(backend, variable, case, tmp_path) as context:
        owner, relay, evidence, specs, endpoint = context
        before = document(owner)
        operations = history(case)
        controls = json_file(tmp_path, 'controls', operations)
        with FaultGate(endpoint, 'PP SAVE_TO_SOURCE', 'drop') as fault:
            failure, call = neo_cli(fault, evidence, specs, '--controls', controls,
                                    expected=1, complete=False)
            assert failure['error'] and not failure.get('saved', False)
            assert len(fault.rows) == 1 and fault.matches == 1
            terminal = bytes.fromhex(fault.rows[0]['lost_backend_terminal_hex']).decode()
            assert '] 200 ' in terminal, terminal
            saves = [command for command in call['commands'] if command.startswith('PP SAVE')]
            assert len(saves) == 1 and saves[0].startswith('PP SAVE_TO_SOURCE ')
            assert call['commands'][-1] == saves[0]
            evidence['wires'].extend(fault.evidence())
        after = document(owner)
        expected = expected_changes(case)
        assert_preservation(before, after, expected)
        fresh = fresh_parameters(relay, evidence)
        assert {name: fresh[name] for name in expected} == expected
        raw_after = packed_bytes(owner)
        assert raw_after['60'] == expected_packed(case)
        assert raw_after['32'] == expected_global_bytes(case)
        assert document(owner) == after
        evidence['operations'] = operations
        evidence['expected_changes'] = expected
        evidence['snapshots'] = {'before': before, 'after_lost_successful_save': after}
