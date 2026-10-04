"""Source-derived full thermostat owner histories on two owned backends.

Family PP rosters are synthetic and omit the other family's dependencies.
Expected values are literal source transcriptions, never planner/model output.
Database acceptance does not establish original window scheduling or hardware.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.file_transfer import prepare_upload, upload
from test_cgate_barcode_database_interop import FaultGate, graph, parse_wire, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)
import test_thermostat_damper_controls_backends as damper
from test_thermostat_plant_types import PP_NAMES
from test_thermostat_settings import _spec

outputs, refs = damper.outputs, damper.refs
BACKENDS = damper.BACKENDS
PROJECT, UNIT, BACKUP = damper.PROJECT, damper.UNIT, damper.BACKUP
PROGRAM_FIELDS = frozenset(('TimeUnits', 'SendInterval', 'EvapProgramEnabled',
    'NonEvapProgramEnabled', 'ScheduleControlledZones', 'RemoteScheduleEnable',
    'RemoteScheduleOnGroup', 'RemoteScheduleOffGroup', 'RemoteScheduleOverrideGroup'))
INPUT_MODULES = ('thermostat_quick_zone_controls', 'thermostat_zone_defaults',
    'thermostat_plant_types', 'thermostat_posted_changes', 'thermostat_damper_controls',
    'thermostat_output_groups', 'thermostat_remote_references', 'thermostat_settings',
    'thermostat_templates_cli', 'thermostat_templates', 'thermostat_post_load',
    'thermostat_temperature', 'thermostat_settings_guard', 'native', 'programming',
    'cgate', 'unitspec')


def family(kind):
    return 'basic' if kind.startswith('PC_TSB') else 'programmable'


def pp_names(kind):
    names = set(PP_NAMES) | {'GuardEnable'}
    return names - (PROGRAM_FIELDS if family(kind) == 'basic' else {'TimerEnable'})


def prepare_specs(folder):
    for kind in ('THERMOSTATA', 'THERMOSTATB', 'PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5'):
        alias = 'PC_TSB' if kind == 'THERMOSTATB' else 'PC_TSA' if kind == 'THERMOSTATA' else kind
        names = pp_names(alias)
        assert not (names & PROGRAM_FIELDS) if family(alias) == 'basic' else 'TimerEnable' not in names
        (folder / (kind + '.xml')).write_text(_spec(kind, names), encoding='utf-8')


def source_seed(kind):
    # Source Celsius min15/max32, Guard0 and settled on/off1/2/cycle12.
    # Delay and temperature byte multiples survive the separate one-save codec.
    result = dict.fromkeys(pp_names(kind), 0)
    result.update({name: 255 for name in outputs.OUTPUT_FIELDS})
    result.update(ApplicationNumber=56, Application=49, UnrelatedParameter=173,
        ZoneGroup=1, InstallationCode=0, InternalPlantType=3, InternalPlantModes=31,
        VentPlantType=2, InstalledZones=30, ControlledZones=30, InternalPlantZones=30,
        HeatingPlantInstalledZones=30, CoolingPlantInstalledZones=30,
        VentingPlantInstalledZones=30, HeatingPlantType=3, CoolingPlantType=3,
        HeatCoolPlantType=3, VentingPlantType=3, UIAllocatedZones=2, MeasuredZones=1,
        MinimumSetTemperature=15, MaximumSetTemperature=32, PlantMinimumOnTime=1,
        PlantMinimumOffTime=2, PlantCycleTime=12, RemoteSetbackControlSource=2,
        RemoteSetbackOnGroup=30, RemoteSetbackOffGroup=31, ZoneTemperatureDisplay=4,
        HeatingPlantFanSpeeds=1, CoolingPlantFanSpeeds=1,
        HeatingPlantFanDefaultSpeed=1, CoolingPlantFanDefaultSpeed=1)
    if family(kind) == 'programmable':
        result.update(EvapProgramEnabled=1, NonEvapProgramEnabled=1, RemoteScheduleEnable=1,
            RemoteScheduleOnGroup=32, RemoteScheduleOffGroup=33, RemoteScheduleOverrideGroup=34)
    else:
        result['TimerEnable'] = 1
    return result


def click(zone, checked):
    return {'op': 'quick-zone-click', 'zone': zone, 'checked': checked}


def make_case(name, kind, *, seed=None, history=None, changed=None, creates=(), ledger=(), edits=None,
              final_state=None, intermediates=(), groups=None, tags=None, preconnect=False,
              schedule_enabled=True):
    values = source_seed(kind) | (seed or {})
    return {'id': name, 'input': {'unit_type': kind, 'seed': values,
        'groups': groups or {56: [40, 41, 42, 43, 70, 255], 172: [1], 203: [30, 31, 32, 33, 34, 255]},
        'group_tags': tags or {56: {40: 'Damper one', 41: 'Damper two', 42: 'Damper three',
            43: 'Damper four', 70: 'Opaque retained output'}, 172: {1: 'Zone'}}},
        'history': history or [{'op': 'quick-zone-view'}], 'changed': changed or {},
        'final_creations': [{'address': address, 'name': tag} for address, tag in creates],
        'graph_ledger': list(ledger), 'operations': [
            (row['action'], 56, row['address'], row['name']) for row in ledger],
        'final_state': final_state or {}, 'intermediates': list(intermediates),
        'preconnect': preconnect, 'edits': edits or {},
        'schedule_enabled': schedule_enabled}


POSITIVES = []
for kind in ('PC_TSB', 'PC_TSB5'):
    suffix = kind.lower()
    # Source master setup changes display4 to0 before the first quick refresh.
    # Quick edits change live masks; the Basic save tail uses OperationZone1.
    POSITIVES.append(make_case('basic-master-live-display-and-tail-' + suffix, kind,
        history=[click(2, True)], edits={'ControlledZones': 30},
        changed={'ZoneTemperatureDisplay': 0, 'UIAllocatedZones': 1,
            'InstalledZones': 1, 'ControlledZones': 1, 'InternalPlantZones': 1,
            'HeatingPlantInstalledZones': 1, 'CoolingPlantInstalledZones': 1,
            'VentingPlantInstalledZones': 1}, final_state={'used_zones': 4, 'loaded_master': True,
            'masks': {'ui': 6, 'measured': 5, 'internal': 30, 'controlled': 30, 'cbus': 30}}))
    POSITIVES.append(make_case('basic-retained-disabled-flags-' + suffix, kind,
        seed={'UIAllocatedZones': 0, 'MeasuredZones': 0}, history=[click(2, True)],
        changed={'ZoneTemperatureDisplay': 0, 'InstalledZones': 1, 'ControlledZones': 1,
            'InternalPlantZones': 1, 'HeatingPlantInstalledZones': 1,
            'CoolingPlantInstalledZones': 1, 'VentingPlantInstalledZones': 1},
        final_state={'loaded_master': True, 'masks': {'ui': 4, 'measured': 4, 'cbus': 30}},
        intermediates=({'position': 1, 'masks': {'ui': 4, 'measured': 4}},)))
    POSITIVES.append(make_case('basic-slave-live-display-four-' + suffix, kind,
        seed={'ControlledZones': 0}, history=[click(2, True)],
        changed={'UIAllocatedZones': 16, 'MeasuredZones': 16,
            'InternalPlantType': 0, 'InternalPlantZones': 0},
        final_state={'loaded_master': False, 'masks': {'controlled': 4, 'internal': 30, 'cbus': 30}}))

for kind in ('PC_TSA', 'PC_TSA5'):
    suffix = kind.lower()
    POSITIVES.append(make_case('programmable-include-exclude-live-' + suffix, kind,
        seed={'DamperZone1Output': 40, 'DamperZone2Output': 41,
              'DamperZone3Output': 42, 'DamperZone4Output': 43},
        history=[click(2, True), click(2, False)],
        changed={'InternalPlantZones': 26, 'InstalledZones': 26, 'ControlledZones': 26,
            'HeatingPlantInstalledZones': 26, 'CoolingPlantInstalledZones': 26,
            'VentingPlantInstalledZones': 26, 'DamperZone2Output': 255},
        final_state={'used_zones': 0, 'loaded_master': True,
            'masks': {'ui': 2, 'measured': 1, 'schedule': 0, 'internal': 26, 'cbus': 26}},
        intermediates=({'position': 1, 'used_zones': 4,
            'masks': {'ui': 6, 'measured': 5, 'schedule': 4, 'cbus': 30}},)))
    for allocate in (False, True):
        rows = [70, 255] if allocate else [3, 5, 41, 70, 255]
        tags = {56: {70: 'Opaque retained output'}, 172: {1: 'Zone'}}
        if not allocate:
            tags[56].update({3: '[CG01] G (heat fan)', 5: '[CG01] W (heat)',
                            41: '[CG01] Damper Zone 2'})
        ledger = []
        if allocate:
            # Plant.GetGroup assigns its generated name before AddObject/save;
            # the separate damper path creates generic Group0, then renames it.
            ledger += [{'action': 'create', 'address': 5, 'name': '[CG01] W (heat)'},
                {'action': 'create', 'address': 3, 'name': '[CG01] G (heat fan)'},
                {'action': 'create', 'address': 0, 'name': 'Group 0'},
                {'action': 'rename', 'address': 0, 'previous_name': 'Group 0',
                 'name': '[CG01] Damper Zone 2'}]
        ledger.append({'action': 'rename', 'address': 70, 'previous_name': 'Opaque retained output',
                       'name': 'Shared retained output', 'output_edit': True})
        creates = [(5, '[CG01] W (heat)'), (3, '[CG01] G (heat fan)'),
                   (0, '[CG01] Damper Zone 2')] if allocate else []
        # IncludeZone writes Controlled before checking the live role types.
        # Its ZoneAfter callback sees the still-empty H/C/V masks and clears
        # those types synchronously; modes and program flags follow that state.
        # BeforeSave preserves the disabled schedule's stored default addresses.
        changed = {'InternalPlantType': 1, 'HeatingPlantStages': 1,
            'HeatStage1Output': 70, 'HeatFanLowOutput': 3,
            'InternalRelay3GroupNumber': 3, 'InternalRelay5GroupNumber': 5,
            'HeatingPlantFanEnable': 1, 'HeatingPlantFanSpeeds': 0,
            'CoolingPlantFanSpeeds': 0, 'UIAllocatedZones': 4, 'InternalPlantZones': 4,
            'MeasuredZones': 4, 'ScheduleControlledZones': 4, 'InstalledZones': 4,
            'ControlledZones': 4, 'InternalPlantModes': 1, 'VentPlantType': 0,
            'EvapProgramEnabled': 0, 'NonEvapProgramEnabled': 0, 'RemoteScheduleEnable': 0,
            'DamperZone2Output': 0 if allocate else 41}
        POSITIVES.append(make_case('ordered-plant-one-' + ('allocate-' if allocate else 'reuse-') + suffix,
            kind, seed={'InternalPlantModes': 19, 'VentPlantType': 1, 'ControlledZones': 1,
                'UIAllocatedZones': 0, 'InternalPlantZones': 0, 'MeasuredZones': 0,
                'ScheduleControlledZones': 0, 'InstalledZones': 0, 'HeatingPlantType': 0,
                'CoolingPlantType': 0, 'HeatCoolPlantType': 0, 'VentingPlantType': 0,
                'HeatingPlantInstalledZones': 0, 'CoolingPlantInstalledZones': 0,
                'VentingPlantInstalledZones': 0, 'ZoneTemperatureDisplay': 0},
            history=[{'op': 'select-plant-type', 'value': 1},
                {'op': 'dispatch-plant-type-change', 'posted_by': 1}, click(2, True),
                {'op': 'select-output-group', 'parameter': 'HeatStage1Output', 'address': 70},
                {'op': 'edit-output-group', 'parameter': 'HeatStage1Output', 'outcome': 'accept',
                 'name': 'Shared retained output'}], changed=changed, creates=creates, ledger=ledger,
            final_state={'plant_type': 1, 'modes': 1, 'used_zones': 4, 'loaded_master': True,
                'masks': {'ui': 4, 'internal': 4, 'measured': 4, 'schedule': 4,
                          'cbus': 4, 'controlled': 5, 'heating': 0, 'cooling': 0, 'venting': 0}},
            intermediates=({'position': 1, 'plant_type': 1, 'used_zones': 0,
                           'masks': {'cbus': 0, 'controlled': 1}},
                          {'position': 2, 'plant_type': 1, 'modes': 19, 'used_zones': 0,
                           'masks': {'cbus': 0, 'heating': 0, 'venting': 0}},
                          {'position': 3, 'modes': 1, 'used_zones': 4,
                           'masks': {'controlled': 5, 'cbus': 4,
                                     'heating': 0, 'cooling': 0, 'venting': 0}}),
            groups={56: rows, 172: [1], 203: [30, 31, 32, 33, 34, 255]}, tags=tags,
            schedule_enabled=False))
assert len(POSITIVES) == 12
assert {case['input']['unit_type'] for case in POSITIVES} == {'PC_TSA','PC_TSA5','PC_TSB','PC_TSB5'}

REFUSALS = [
    ('changed-loaded-role', {'edits': {'ControlledZones': 0}}, 'changed scalar ControlledZones'),
    ('pending-source-message', {'history': [{'op': 'select-plant-type', 'value': 1}]}, 'pending'),
    ('consumed-source-message', {'history': [{'op': 'select-plant-type', 'value': 0},
        {'op': 'dispatch-plant-type-change', 'posted_by': 1},
        {'op': 'dispatch-plant-type-change', 'posted_by': 1}]}, 'consumed'),
    ('invalid-display-before-master-setup', {'input_seed': {'ZoneTemperatureDisplay': 255}}, 'ZoneTemperatureDisplay'),
]


def input_pins():
    result = {}
    for name in INPUT_MODULES:
        spec = importlib.util.find_spec('cbus_toolkit.' + name)
        assert spec and spec.origin
        path = Path(spec.origin)
        assert path.name == name + '.py' and path.parent.name == 'cbus_toolkit'
        content = path.read_bytes()
        result['cbus_toolkit.' + name] = {'sha256': hashlib.sha256(content).hexdigest(),
            'bytes': len(content), 'origin': str(path)}
    return result


def seed(owner, work, trap, case, evidence):
    fixture = outputs.seed(owner, work, trap, case['input'])
    root = outputs.parse(fixture.read_text())
    unit = root.find("Project/Network[Address='11']/Unit[Address='20']")
    names = pp_names(case['input']['unit_type'])
    for row in list(unit.findall('PP')):
        unit.remove(row)
    for name in sorted(names):
        ET.SubElement(unit, 'PP', Name=name, Value=str(case['input']['seed'][name]))
    # Archive import admits numeric Level values. Introduce opaque retained
    # metadata through the separately accepted field setter after restore.
    setup = []
    for level in root.iter('Level'):
        if level.findtext('Address') == '7':
            level.set('Value', '7')
            setup.append({'oid': level.findtext('OID'), 'address': 7,
                          'archive_value': '7', 'retained_value': 'oops'})
    assert setup and len({row['oid'] for row in setup}) == len(setup)
    evidence['fixture_numeric_to_opaque_setup'] = setup
    fixture = work / 'thermostat-full-owner-synthetic.xml'
    fixture.write_bytes(ET.tostring(root))
    assert upload(prepare_upload('Projects/archived/' + fixture.name, fixture), owner)['upload_completed']
    for command in ('PROJECT CLOSE ' + PROJECT, 'PROJECT DELETE ' + PROJECT,
                    'PROJECT RESTORE ' + PROJECT + ' ' + fixture.name,
                    'PROJECT USE ' + PROJECT, 'PROJECT SAVE ' + PROJECT):
        assert owner.command(command).code == 200
    for row in setup:
        before = owner.command('DBGET !' + row['oid'] + '/Value')
        row.update(before_code=before.code, before_lines=list(before.lines))
        assert before.code == 342 and list(before.lines) == [
            '342 !' + row['oid'] + '/Value=7']
        command = 'DBSETSAFE !' + row['oid'] + '/Value oops'
        row['command'] = command
        reply = owner.command(command)
        row.update(response_code=reply.code, response_lines=list(reply.lines))
        assert reply.code == 200
        after = owner.command('DBGET !' + row['oid'] + '/Value')
        row.update(after_code=after.code, after_lines=list(after.lines))
        assert after.code == 342 and list(after.lines) == [
            '342 !' + row['oid'] + '/Value=oops']
    assert owner.command('PROJECT SAVE ' + PROJECT).code == 200
    evidence['fixture_opaque_project_saved'] = True
    return fixture, setup


@contextmanager
def journey(backend, variable, tmp_path, case):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'backend')
    specs = tmp_path / 'synthetic-specs'; specs.mkdir()
    prepare_specs(specs)
    evidence = {'format': 'cbus-thermostat-full-owner-backend-v1', 'backend': backend,
        'case': case['id'], 'input': deepcopy(case['input']),
        'source_derived_expected_changes': deepcopy(case['changed']),
        'original_execution': False, 'physical_acceptance': False,
        'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'specification_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in specs.iterdir()},
        'test_module_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'calls': [], 'wires': [], 'processes': []}
    pins = input_pins()
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(backend, binary, work, extra_args=(
                '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec', specs)) as (endpoint, process):
            evidence['processes'].append(process)
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                fixture, setup = seed(owner, work, trap, case, evidence)
                current_test = os.environ.get('PYTEST_CURRENT_TEST')
                assert current_test and current_test.endswith(' (call)')
                nodeid = current_test.rsplit(' (', 1)[0]
                assert 'test_thermostat_quick_zone_controls_backends.py::' in nodeid
                evidence.update(fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                    before_xml=refs.document(owner), before_parameters=refs.parameters(owner),
                    fixture_numeric_to_opaque_setup=setup,
                    pytest_current_test=current_test, actual_nodeid=nodeid,
                    implementation_inputs=pins, source_pp_scope='complete synthetic family roster',
                    expected_pp_names=sorted(pp_names(case['input']['unit_type'])))
                assert set(evidence['before_parameters']) == pp_names(case['input']['unit_type'])
                retained = {row.findtext('OID'): row.get('Value') for row in outputs.parse(
                    evidence['before_xml']).iter('Level') if row.findtext('Address') == '7'}
                assert retained == {row['oid']: 'oops' for row in setup}
                yield owner, relay, evidence, specs, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'] = relay.evidence()
        evidence['implementation_inputs_after'] = input_pins()
        associated_evidence(tmp_path / 'thermostat-quick-zone-controls-evidence.json', evidence)
        assert evidence['implementation_inputs_after'] == pins


def invoke(relay, evidence, specs, case, *, action='apply', expected=0, complete=True):
    start = len(relay.rows)
    argv = [sys.executable, '-m', 'cbus_toolkit', 'thermostat', 'settings', action, UNIT,
        '--host', relay.endpoint[0], '--port', str(relay.endpoint[1]), '--timeout', '3',
        '--exclusive-project', '--spec-dir', str(specs), '--temperature-preference', 'celsius']
    for event in case['history']:
        argv += ['--output-operation', json.dumps(event, ensure_ascii=False)]
    for name, value in case.get('edits', {}).items():
        argv += ['--set', name + '=' + str(value)]
    if action == 'apply':
        argv += ['--backup-project', BACKUP]
    call = {'argv': argv, 'action': action, 'accepted_terminal': False,
        'call_id': evidence['actual_nodeid'] + ':' + str(len(evidence['calls']) + 1) + ':' + action,
        'owning_nodeid': evidence['actual_nodeid'],
        'wire_artifact': 'fault_wires' if isinstance(relay, FaultGate) else 'wires'}
    evidence['calls'].append(call)
    try:
        process = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired as error:
        def text(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else value
        call.update(timeout_expired=True, stdout=text(error.stdout), stderr=text(error.stderr))
        if len(relay.rows) > start:
            partial = relay.rows[start]; partial['done'].wait(5)
            call.update(parse_wire(partial, complete=False), wire_index=start)
        raise
    call.update(exit=process.returncode, stdout=process.stdout, stderr=process.stderr)
    result = json.loads(process.stdout or process.stderr)
    call['result'] = result
    assert len(relay.rows) == start + 1 and relay.rows[start]['done'].wait(5)
    call.update(parse_wire(relay.rows[start], complete=complete), wire_index=start)
    assert process.returncode == expected, call
    call['accepted_terminal'] = complete
    assert not any(c.startswith(('NET OPEN ', 'PP PROGRAM ')) for c in call['commands'])
    assert all('/db' + UNIT in c for c in call['commands'] if c.startswith('PP LOAD '))
    return result, call


def assert_state(state, expected):
    for key, value in expected.items():
        if key == 'position':
            continue
        if key == 'masks':
            assert {name: state['masks'][name] for name in value} == value
        else:
            assert state[key] == value, (key, state, expected)


def assert_projection(plan, case, before):
    assert {row['name']: row['after'] for row in plan['changed_parameters']} == case['changed']
    assert plan['planned_level_creations'] == []
    model = plan['output_projection']['quick_zone_controls']
    assert model['profile'] == 'fresh-source-owner-settled-explicit-quick-zone-controls-v1'
    assert model['full_toolkit_parity'] is False
    assert model['original_form_executed'] is False
    assert model['physical_device_programmed'] is False
    assert model['native_control_scheduling_reproduced'] is False
    assert model['detached_continuation_admitted'] is False
    assert model['posted_changes']['pending_positions'] == []
    assert not any(model['state']['guards'].values())
    assert_state(model['state'], case['final_state'])
    indexed = {row['position']: row for row in model['operations']}
    assert list(indexed) == list(range(1, len(case['history']) + 1))
    for row in case['intermediates']:
        assert_state(indexed[row['position']]['after'], row)
    assert [row['operation'] for row in model['operations']] == case['history']
    assert model['save_projection']['retained_master'] == case['final_state'].get('loaded_master', True)
    mutation = bool(case['changed'] or case['operations'])
    assert plan['apply_would_mutate'] is mutation
    assert plan['pp_save_count'] == int(bool(case['changed']))
    assert plan['target_project_save_count'] == int(mutation)
    assert plan['backup_source_save_count'] == int(mutation)
    assert [(row['action'], row['application'], row['address'], row['name'])
            for row in plan['graph_operations']] == list(case['operations'])
    # Every joined remote role binds its existing application+OID. Source
    # validation keeps setback/schedule identities distinct; no Levels move.
    document = outputs.parse(before)
    roles = {'setback_on': 30, 'setback_off': 31}
    if family(case['input']['unit_type']) == 'programmable':
        enabled = case['schedule_enabled']
        roles.update(schedule_on=32 if enabled else 255, schedule_off=33 if enabled else 255,
                     schedule_override=34 if enabled else 255)
    assert plan['remote_references']['resolved_roles'] == {
        role: {'application': 203, 'address': address,
               'identity': outputs.group_at(document, 203, address).findtext('OID'),
               'unused': address == 255} for role, address in roles.items()}
    if family(case['input']['unit_type']) == 'programmable':
        saved = model['save_projection']['expected']
        assert {name: saved[name] for name in ('RemoteScheduleEnable', 'RemoteScheduleOnGroup',
            'RemoteScheduleOffGroup', 'RemoteScheduleOverrideGroup')} == {
            'RemoteScheduleEnable': int(case['schedule_enabled']), 'RemoteScheduleOnGroup': 32,
            'RemoteScheduleOffGroup': 33, 'RemoteScheduleOverrideGroup': 34}
    return model


def assert_after(owner, evidence, case):
    actual, after = refs.parameters(owner), refs.document(owner)
    refs.assert_values(evidence['before_parameters'], actual, case['changed'])
    damper.preserve(evidence['before_xml'], after, case)
    assert set(actual) == set(evidence['before_parameters'])
    return actual, after


def assert_graph_wire(call, before, case):
    # Native source owner names created Plant groups before saving them, while
    # explicit Edit uses TagStringToCgateString's quoted name representation.
    commands = call['commands']
    identities = {int(row.findtext('Address')): row.findtext('OID') for row in refs.groups(
        outputs.parse(before).find("Project/Network[Address='11']/Application[Address='56']"))}
    expected = []
    for row in case['graph_ledger']:
        address, name = row['address'], row['name']
        if row['action'] == 'create':
            command = refs.expected_creates({'creates': [(56, address, name)]})[0]
            index = commands.index(command)
            assert call['statuses'][index] == 301
            terminal = call['terminals'][index]
            assert terminal.startswith('OID=')
            oid = terminal[4:]
            assert str(uuid.UUID(oid)) == oid and oid not in identities.values()
            identities[address] = oid
            assert commands[index + 1] == 'DBGET !' + oid + '/OID'
            assert call['statuses'][index + 1] == 342
            assert call['terminals'][index + 1] == '!' + oid + '/OID=' + oid
        else:
            oid = identities[address]
            # This fixture's explicit Edit label is an ASCII literal with no
            # quote/backslash/control characters or repeated spaces.
            wire_name = '"' + name + '"' if row.get('output_edit') else name
            verb = 'DBSET !' if row.get('output_edit') else 'DBSETSAFE !'
            command = verb + oid + '/TagName ' + wire_name
            index = commands.index(command)
            assert commands[index - 2:index] == ['DBGET !' + oid + '/OID', 'DBGET !' + oid + '/TagName']
            assert call['statuses'][index - 2:index] == [342, 342]
            assert call['terminals'][index - 2:index] == ['!' + oid + '/OID=' + oid,
                '!' + oid + '/TagName=' + row['previous_name']]
            assert call['statuses'][index] == 200
        expected.append(command)
    assert [c for c in commands if c.startswith(('DBADD', 'DBSET', 'DBDELETE'))] == expected


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
@pytest.mark.parametrize('case', POSITIVES, ids=lambda row: row['id'])
def test_public_full_owner_history(backend, variable, case, tmp_path):
    with journey(backend, variable, tmp_path, case) as (owner, relay, evidence, specs, _):
        preview, peek = invoke(relay, evidence, specs, case, action='preview')
        assert_projection(preview, case, evidence['before_xml'])
        damper.assert_no_mutation(peek)
        assert refs.document(owner) == evidence['before_xml']
        assert refs.parameters(owner) == evidence['before_parameters']
        result, call = invoke(relay, evidence, specs, case)
        assert result['complete'] and result['persistence_verified']
        assert result['plan'] == {key: value for key, value in preview.items() if key != 'scope'}
        assert_graph_wire(call, evidence['before_xml'], case)
        commands = call['commands']
        assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands) == 1
        assert commands.count('PROJECT SAVE ' + PROJECT) == 2
        assert commands.count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == 1
        assert commands.count('PROJECT CLOSE ' + PROJECT) == 1
        assert commands.count('PROJECT LOAD ' + PROJECT) == 1
        assert result['pp_save_count'] == result['target_project_save_count'] == 1
        first = next(i for i, c in enumerate(commands) if c.startswith(('DBADD', 'DBSET', 'PP SET ', 'PP SAVE')))
        assert commands.index('PROJECT SAVE ' + PROJECT) < commands.index(
            'PROJECT COPY ' + PROJECT + ' ' + BACKUP) < first
        backup = refs.document(owner, '//' + BACKUP)
        assert graph(backup) == damper.copied_project_graph(evidence['before_xml'])
        actual, after = assert_after(owner, evidence, case)
        for verb in ('CLOSE', 'LOAD', 'USE'):
            assert owner.command('PROJECT ' + verb + ' ' + PROJECT).code == 200
        fresh, reopened = assert_after(owner, evidence, case)
        assert fresh == actual and graph(reopened) == graph(after)
        evidence.update(preview=preview, result=result, after_xml=after, after_parameters=actual,
            reopened_xml=reopened, reopened_parameters=fresh, backup_xml=backup,
            backup_preapply_graph_verified=True, full_pp_and_graph_preserved=True,
            independent_reopen=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
@pytest.mark.parametrize('name,overrides,error', REFUSALS, ids=[row[0] for row in REFUSALS])
def test_public_full_owner_refuses_before_backup(backend, variable, name, overrides, error, tmp_path):
    case = deepcopy(POSITIVES[6])
    case['id'] = name
    case.update({k: v for k, v in overrides.items() if k != 'input_seed'})
    case['input']['seed'].update(overrides.get('input_seed', {}))
    with journey(backend, variable, tmp_path, case) as (owner, relay, evidence, specs, _):
        result, call = invoke(relay, evidence, specs, case, expected=1)
        assert error in result['error']
        damper.assert_no_mutation(call)
        assert refs.document(owner) == evidence['before_xml']
        assert refs.parameters(owner) == evidence['before_parameters']
        assert not result['thermostat_template_evidence']['outcome_uncertain']
        evidence.update(result=result, refusal_before_backup=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
@pytest.mark.parametrize('phase', ['PP SAVE_TO_SOURCE', 'PROJECT SAVE'])
def test_public_full_owner_lost_successful_save_never_replays(backend, variable, phase, tmp_path):
    case = deepcopy(next(row for row in POSITIVES if row['id'] == 'ordered-plant-one-allocate-pc_tsa5'))
    case['id'] = 'lost-' + phase.lower().replace(' ', '-')
    with journey(backend, variable, tmp_path, case) as (owner, _, evidence, specs, endpoint):
        occurrence = 2 if phase == 'PROJECT SAVE' else 1
        with FaultGate(endpoint, phase, 'drop', occurrence=occurrence) as fault:
            result, call = invoke(fault, evidence, specs, case, expected=1, complete=False)
        evidence['fault_wires'] = fault.evidence()
        assert fault.matches == occurrence
        state = result['thermostat_template_evidence']
        assert not state['complete'] and state['outcome_uncertain']
        assert state['automatic_retries'] == 0 and state['rollback_performed'] is False
        assert state['pp_save_attempted'] and not state['target_save_confirmed']
        assert state['pp_save_confirmed'] is (phase == 'PROJECT SAVE')
        assert state['target_save_attempted'] is (phase == 'PROJECT SAVE')
        commands = call['commands']
        assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands) == 1
        assert commands.count('PROJECT SAVE ' + PROJECT) == occurrence
        assert commands.count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == 1
        assert not any(c.startswith(('DBDELETE', 'PROJECT CLOSE ', 'PROJECT LOAD ')) for c in commands)
        assert commands[-1].startswith(phase) and call['statuses'][-1] is None
        lost = [row for row in evidence['fault_wires'] if 'lost_backend_terminal_hex' in row]
        assert len(lost) == 1
        terminal = bytes.fromhex(lost[0]['lost_backend_terminal_hex'])
        assert re.fullmatch(rb'\[[^]]+\] 200 OK\r\n', terminal)
        assert terminal in bytes.fromhex(lost[0]['backend_response_hex'])
        assert terminal not in bytes.fromhex(lost[0]['response_hex'])
        assert_graph_wire(call, evidence['before_xml'], case)
        actual, after = assert_after(owner, evidence, case)
        evidence.update(result=result, after_xml=after, after_parameters=actual,
            replay_count=0, saved_response_lost=True, full_pp_and_graph_preserved=True,
            independent_reopen=False)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
def test_public_full_owner_opaque_level_stale_refuses(backend, variable, tmp_path):
    case = deepcopy(next(row for row in POSITIVES if row['id'] == 'ordered-plant-one-reuse-pc_tsa5'))
    case['id'] = 'stale-opaque-value'
    with journey(backend, variable, tmp_path, case) as (owner, _, evidence, specs, endpoint):
        original = outputs.parse(evidence['before_xml'])
        group = outputs.group_at(original, 56, 70)
        level = next(row for row in group.findall('Level') if row.findtext('Address') == '7')
        oid = level.findtext('OID')
        assert level.get('Value') == 'oops'
        def mutate():
            assert owner.command('DBSETSAFE !' + oid + '/Value externally changed opaque value').code == 200
        with FaultGate(endpoint, 'PROJECT USE', 'change', occurrence=4, callback=mutate) as fault:
            result, call = invoke(fault, evidence, specs, case, expected=1)
        assert fault.matches >= 4 and any(row.get('controlled_change_completed') for row in fault.rows)
        assert 'changed since planning' in result['error']
        damper.assert_no_mutation(call)
        level.set('Value', 'externally changed opaque value')
        actual, after = refs.parameters(owner), refs.document(owner)
        assert actual == evidence['before_parameters']
        assert graph(ET.tostring(original, encoding='unicode')) == graph(after)
        evidence.update(result=result, fault_wires=fault.evidence(), after_xml=after,
            after_parameters=actual, refusal_before_backup=True,
            controlled_change={'oid': oid, 'field': 'Value', 'before': 'oops',
                               'after': 'externally changed opaque value'})


@pytest.mark.parametrize('name,history,preference,error', [
    ('missing-celsius', [{'op': 'quick-zone-view'}], None, 'celsius'),
    ('wrong-preference', [{'op': 'quick-zone-view'}], 'fahrenheit', 'celsius'),
    ('invalid-plant-choice', [{'op': 'select-plant-type', 'value': 12}], 'celsius', 'Plant selection'),
    ('nonboolean-checkbox', [{'op': 'quick-zone-click', 'zone': 2, 'checked': 1}], 'celsius', 'Boolean'),
], ids=['missing-celsius','wrong-preference','invalid-plant-choice','nonboolean-checkbox'])
def test_public_full_owner_schema_refuses_before_connection(name, history, preference, error, tmp_path):
    specs = tmp_path / 'synthetic-specs'; specs.mkdir()
    prepare_specs(specs)
    with no_contact_trap() as endpoint:
        host, port = endpoint.rsplit(':', 1)
        argv = [sys.executable, '-m', 'cbus_toolkit', 'thermostat', 'settings', 'apply', UNIT,
            '--host', host, '--port', port, '--exclusive-project', '--spec-dir', str(specs),
            '--backup-project', BACKUP]
        if preference is not None:
            argv += ['--temperature-preference', preference]
        for event in history:
            argv += ['--output-operation', json.dumps(event)]
        process = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        result = json.loads(process.stdout or process.stderr)
        assert process.returncode == 1 and error in result['error'], result
    (tmp_path / 'thermostat-quick-zone-schema-evidence.json').write_text(json.dumps({
        'case': name, 'argv': argv, 'exit': process.returncode, 'result': result,
        'zero_tcp_contacts': True, 'original_execution': False,
        'physical_acceptance': False}, sort_keys=True), encoding='utf-8')
