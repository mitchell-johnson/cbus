"""Source-literal prepared Boolean contracts on the complete fresh owner."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from cbus_toolkit.thermostat_output_groups import normalize_output_operations
from cbus_toolkit.thermostat_quick_zone_controls import prepare_quick_zone_save
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
from cbus_toolkit.thermostat_zone_controls import ZONE_BINDINGS, normalize_zone_operation
from cbus_toolkit.thermostat_zone_controls import PreparedZoneControls
from test_thermostat_quick_zone_controls import model, call


# Literal Prepare expressions and Boolean bit indices, transcribed before the
# implementation from the retained panel sites, not produced by its registry.
PROPERTIES = (
    ('UIAllocatedZones', 'ui', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4')),
    ('InternalPlantZones', 'internal', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4')),
    ('InternalPlantModes', 'modes', ('Heat', 'Cool', 'HeatCool', 'Vent')),
    ('MeasuredZones', 'measured', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4')),
    ('CoolingPlantInstalledZones', 'cooling', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4')),
    ('VentingPlantInstalledZones', 'venting', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4')),
    ('HeatingPlantInstalledZones', 'heating', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4')),
)
LITERALS = tuple((field + '.' + name, field, role, bit)
    for field, role, names in PROPERTIES
    for bit, name in enumerate(names, 1 if role == 'modes' else 0))
FULL_MASKS = {field: 31 for field in (
    'UIAllocatedZones', 'InternalPlantZones', 'MeasuredZones', 'ScheduleControlledZones',
    'HeatingPlantInstalledZones', 'CoolingPlantInstalledZones', 'VentingPlantInstalledZones',
    'InstalledZones', 'ControlledZones', 'InternalPlantModes')}


def full_model(kind='PC_TSA5', *, changes=None):
    return model(kind, changes=FULL_MASKS | {
        'HeatingPlantType': 3, 'CoolingPlantType': 3, 'HeatCoolPlantType': 3,
        'VentingPlantType': 3, 'VentPlantType': 2,
        'HeatingPlantFanSpeeds': 1, 'CoolingPlantFanSpeeds': 1,
        'HeatingPlantFanDefaultSpeed': 1, 'CoolingPlantFanDefaultSpeed': 1,
        'DamperZone1Output': 40, 'DamperZone2Output': 41,
        'DamperZone3Output': 42, 'DamperZone4Output': 43} | (changes or {}),
        groups=[(40, 'Damper one'), (41, 'Damper two'), (42, 'Damper three'), (43, 'Damper four')])


def bind(m, expression, checked):
    return call(m, 'zone-checkbox-binding', binding=expression, checked=checked)


def test_literal_roster_is_exact_and_has_no_unprepared_masks_or_standby():
    assert len(LITERALS) == 34
    assert set(ZONE_BINDINGS) == {row[0] for row in LITERALS}
    assert 'InternalPlantModes.Standby' not in ZONE_BINDINGS
    assert not any(name.startswith(('InstalledZones.', 'ControlledZones.', 'ScheduleControlledZones.'))
                   for name in ZONE_BINDINGS)


@pytest.mark.parametrize('expression,field,role,bit', LITERALS, ids=[row[0] for row in LITERALS])
def test_every_binding_runs_complete_owner_callback_and_literal_mask(expression, field, role, bit):
    m = full_model()
    before = dict(m.values)
    groups = deepcopy(m.output.resolver.live)
    before_save = prepare_quick_zone_save(m, m.issue_save())
    start = len(m._trace)
    result = bind(m, expression, False)
    assert m.values == before | {field: 31 & ~(1 << bit)}
    assert m._used == (0 if role == 'ui' else 31)
    assert m._loaded_master and m.output.master
    assert m.output.resolver.live == groups
    assert not m.output.resolver.operations
    assert not any(m._guards.values())
    events = m._trace[start:]
    assert events[0]['method'] == 'explicit-prepared-Boolean-binding'
    assert events[1] == {'method': 'Boolean.SetAsBoolean', 'position': 1,
        'role': role, 'zone': bit, 'value': False, 'changed': True}
    assert events[2]['method'] == 'Boolean.Begin/store/End'
    assert events[2]['locked_intermediate_changes'] == 2 and events[2]['outer_end'] == 1
    assert events[3]['method'] == 'TZones.Managed.Changed' and events[3]['role'] == role
    assert events[4]['method'] == 'owned-Boolean-control-read' and events[4]['model_write'] is False
    assert events[5]['method'] == 'owning-ObjectAttribute.Changed'
    assert any(row['method'] == 'Templates.HandleUnitZoneChange' for row in events) is (role != 'ui')
    assert any(row['method'] == 'Thermostat.HandleInstalledZonesChange' for row in events) is (role != 'ui')
    saved = prepare_quick_zone_save(m, m.issue_save())
    # BeforeSave clears fan speeds when the Vent mode bit is absent.
    fan_tail = {'HeatingPlantFanSpeeds': 0, 'CoolingPlantFanSpeeds': 0} if expression == 'InternalPlantModes.Vent' else {}
    assert saved == before_save | {field: 31 & ~(1 << bit)} | fan_tail
    assert result['after']['masks'][role] == 31 & ~(1 << bit)
    proof = m.as_dict()['prepared_zone_bindings']
    assert proof['binding_count'] == 34 and proof['same_synchronous_settings_owner']
    assert proof['native_enabled_visible_focus_admission_verified'] is False
    assert proof['native_mouse_or_click_dispatched'] is False
    assert proof['operations'][0]['before_checked'] is True
    assert proof['operations'][0]['after_checked'] is False


@pytest.mark.parametrize('expression,field,role,bit', LITERALS, ids=[row[0] for row in LITERALS])
def test_every_prepared_boolean_same_value_skips_begin_end_and_callbacks(expression, field, role, bit):
    m = full_model()
    before = dict(m.values)
    start = len(m._trace)
    bind(m, expression, True)
    assert m.values == before and m._used == 0
    assert [row['method'] for row in m._trace[start:]] == [
        'explicit-prepared-Boolean-binding', 'Boolean.SetAsBoolean']
    assert m._trace[-1]['changed'] is False


def test_empty_heating_zone_clears_type_then_modes_then_program_flag_without_raw_mask_shortcut():
    m = full_model(changes={'HeatingPlantInstalledZones': 4})
    before = dict(m.values)
    bind(m, 'HeatingPlantInstalledZones.Zone2', False)
    assert m.values == before | {'HeatingPlantInstalledZones': 0,
        'HeatingPlantType': 0, 'InternalPlantModes': 29, 'EvapProgramEnabled': 0}
    assert m.values['RemoteScheduleEnable'] == 1
    assert m._used == 31 and not any(m._guards.values())
    setters = [(row['field'], row['value']) for row in m._trace
               if row['position'] == 1 and row['method'] == 'Integer.SetAsInteger' and row['changed']]
    assert setters == [('HeatingPlantType', 0), ('EvapProgramEnabled', 0)]
    # Modes are five Boolean attributes, not a single Integer setter.
    events = [row for row in m._trace if row['position'] == 1]
    mode_writes = [row for row in events if row['method'] == 'Boolean.SetAsBoolean'
                   and row['role'] == 'modes' and row['changed']]
    assert [(row['zone'], row['value']) for row in mode_writes] == [(1, False)]
    heating = next(row for row in events if row['method'] == 'Integer.SetAsInteger'
                   and row['field'] == 'HeatingPlantType' and row['changed'])
    program = next(row for row in events if row['method'] == 'Integer.SetAsInteger'
                   and row['field'] == 'EvapProgramEnabled' and row['changed'])
    assert events.index(heating) < events.index(mode_writes[0]) < events.index(program)
    guards = [(row['name'], row['value']) for row in m._trace
              if row['position'] == 1 and row['method'] == 'guard']
    assert guards[0] == ('zone130', True)
    assert ('plant15c', True) in guards and ('unit1c0', True) in guards
    assert ('zone130', False) in guards


def test_basic_save_uses_retained_ui_sensor_and_operation_zone_not_detailed_masks():
    m = full_model('PC_TSB', changes={'UIAllocatedZones': 0, 'MeasuredZones': 0})
    bind(m, 'UIAllocatedZones.Zone2', True)
    bind(m, 'MeasuredZones.Zone2', True)
    assert m.values['UIAllocatedZones'] == m.values['MeasuredZones'] == 4
    saved = prepare_quick_zone_save(m, m.issue_save())
    assert saved['UIAllocatedZones'] == saved['MeasuredZones'] == 0
    assert saved['InstalledZones'] == saved['ControlledZones'] == saved['InternalPlantZones'] == 1
    assert m._loaded_master


def test_binding_history_composes_with_owned_queue_output_identity_and_damper_cache():
    m = full_model()
    original = m.output.resolver.live[(56, 70)]
    bind(m, 'UIAllocatedZones.Zone2', False)
    call(m, 'select-plant-type', value=3)
    bind(m, 'MeasuredZones.Zone2', False)
    with pytest.raises(ThermostatTemplateError, match='pending'):
        m.issue_save()
    call(m, 'dispatch-plant-type-change', posted_by=2)
    call(m, 'select-output-group', parameter='HeatStage1Output', address=70)
    bind(m, 'MeasuredZones.Zone2', True)
    saved = prepare_quick_zone_save(m, m.issue_save())
    assert m.output.references['HeatStage1'].identity == original.identity
    assert saved['HeatStage1Output'] == 70
    assert [row['position'] for row in m.zone_controls.as_dict()['operations']] == [1, 3, 6]
    assert not m.queue.as_dict()['pending_positions']
    assert m._unit_lock == m._manager_lock == 0 and not any(m._guards.values())


def test_prepared_binding_refuses_forged_owner_descriptor_and_stale_save():
    m = full_model()
    saved = m.issue_save()
    bind(m, 'UIAllocatedZones.Zone1', False)
    with pytest.raises(ThermostatTemplateError, match='original'):
        prepare_quick_zone_save(m, saved)
    m.zone_controls._bindings['UIAllocatedZones.Zone1'].owner = full_model()
    with pytest.raises(ThermostatTemplateError, match='originally issued'):
        bind(m, 'UIAllocatedZones.Zone1', True)


def test_same_owner_controller_replacement_cannot_erase_prior_history_or_issue_save():
    m = full_model()
    bind(m, 'UIAllocatedZones.Zone1', False)
    original = m.zone_controls
    assert len(original.as_dict()['operations']) == 1
    m.zone_controls = PreparedZoneControls(m)
    with pytest.raises(ThermostatTemplateError, match='originally issued'):
        m.issue_save()
    with pytest.raises(ThermostatTemplateError, match='originally issued'):
        bind(m, 'UIAllocatedZones.Zone1', True)
    m.zone_controls = original
    assert len(m.as_dict()['prepared_zone_bindings']['operations']) == 1


@pytest.mark.parametrize('row', [
    {'op': 'zone-checkbox-binding', 'binding': 'InternalPlantModes.Standby', 'checked': True},
    {'op': 'zone-checkbox-binding', 'binding': 'InstalledZones.Zone1', 'checked': True},
    {'op': 'zone-checkbox-binding', 'binding': 'UIAllocatedZones.Zone5', 'checked': True},
    {'op': 'zone-checkbox-binding', 'binding': 'UIAllocatedZones.Zone1', 'checked': 1},
    {'op': 'zone-checkbox-binding', 'binding': [], 'checked': True},
    {'op': 'zone-checkbox-binding', 'binding': 'UIAllocatedZones.Zone1', 'checked': True, 'value': 31},
    {'op': 'zone-checkbox-binding', 'binding': 'UIAllocatedZones.Zone1'},
])
def test_closed_normalizer_refuses_unprepared_or_forged_property_schema(row):
    with pytest.raises(ThermostatTemplateError):
        normalize_zone_operation(row)
    with pytest.raises(ThermostatTemplateError):
        normalize_output_operations([row])


def test_binding_normalizes_through_existing_settings_operation_owner():
    row = {'op': 'zone-checkbox-binding', 'binding': 'InternalPlantModes.HeatCool', 'checked': False}
    assert tuple(json.loads(encoded) for encoded in normalize_output_operations([row])) == (row,)
    assert normalize_zone_operation({'op': 'quick-zone-view'}) is None
