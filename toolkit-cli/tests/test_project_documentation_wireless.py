"""Independent literal wireless report bodies and ordered graph consumers."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit.project_documentation_native import build_native_model
from cbus_toolkit.project_documentation_wireless import document_wireless, remote_key_display, wireless_key_html
from cbus_toolkit.project_documentation_wireless_facts import MACRO_TEMPLATES, MICRO_GROUPS, WIRELESS_TYPES
from cbus_toolkit.project_documentation_wireless_loader import (
    command_type, decorator_load, decorator_save, gateway_profile, gateway_remote_data,
    input_remote_maps, wireless_key_data, wireless_profile,
)
from cbus_toolkit.project_documentation_wireless_usage import (
    gateway_action_usage, gateway_group_usage, remote_action_usage, remote_group_usage,
    wireless_action_usage, wireless_group_usage,
)
from cbus_toolkit.toolkit_database_csv_registry import REGISTRATIONS

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / 'research/fixtures/project-documentor-wireless.json'


def fixture():
    value = json.loads(VECTOR.read_text())
    model = build_native_model(value['native_xml'].encode())
    network = model.by_address[254]
    return value, model, network, {unit.address: unit for unit in network.units}


def changed(unit, **values):
    parameters = dict(unit.parameters)
    for name, value in values.items():
        if value is None:
            parameters.pop(name, None)
        else:
            parameters[name] = ' '.join(map(str, value))
    return replace(unit, parameters=parameters)


@pytest.mark.parametrize('address', [1, 2, 3, 10, 11, 12, 13, 14, 15, 16])
def test_complete_native_snapshot_literal_body_and_preservation(address):
    vector, model, network, units = fixture()
    before = deepcopy(model)
    unit = units[address]
    out = doc._Writer()
    assert document_wireless(out, network, unit, model.networks) == 'recovered'
    prefix = [f'Unit Address: {address}<br />', f'Tagname: {unit.name}<br />',
              f'Part name: {unit.unit_name}<br />']
    if address < 10:
        prefix += ['Application: <a href="#254_56">Lighting</a><br />',
                   'Secondary Application: <a href="#254_57">Lighting Two</a><br />']
    prefix += [f"Serial Number: {next(f['display_serial'] for f in vector['units'] if f['address'] == address)}<br />", f'Firmware Version: {unit.firmware}<br />',
               'Notes: <br />', '<br />']
    assert out.lines == prefix + vector['body_lines'][str(address)]
    assert not out.unrecovered and model == before


def test_literal_key_rows_and_address_not_value_selector_binding():
    vector, _, network, units = fixture()
    data = wireless_key_data(units[1])
    assert [wireless_key_html(network, data, index) for index in range(16)] == vector['key_html']
    assert len(data.keys) == len(data.groups) == 16
    assert [key.kind for key in data.keys[:6]] == [20, 13, 24, 31, 33, 34]
    assert [(scene.trigger_group, scene.trigger_address) for scene in data.scenes] == [(7, 11), (7, 12)]
    assert wireless_action_usage(units[1], 202, 7, 11).html == vector['selector_usage']['input_11']
    assert wireless_action_usage(units[1], 202, 7, 12).html == vector['selector_usage']['input_12']
    assert wireless_action_usage(units[1], 202, 7, 99).html == ''
    assert gateway_action_usage(network, units[3], 202, 7, 11).html == vector['selector_usage']['gateway_11']
    assert gateway_action_usage(network, units[3], 202, 7, 99).html == ''


def test_ordered_group_usage_keeps_duplicate_blocks_and_cross_receiver_bindings():
    vector, _, network, units = fixture()
    for app, group, kind, expected in [(56, 8, 'input', 'input_56_8'), (57, 9, 'input', 'input_57_9'),
            (56, 8, 'output', 'output_56_8'), (56, 8, 'other', 'other_56_8')]:
        result = wireless_group_usage(units[1], app, group, kind)
        assert (result.status, result.html) == ('recovered', vector['group_usage'][expected])
    result = remote_group_usage(network, units[10], 56, 8, 'input')
    assert (result.status, result.html) == ('recovered', vector['group_usage']['remote_56_8'])
    for kind in ('input', 'output', 'other'):
        assert gateway_group_usage(units[3], 56, 8, kind).html == ''
    for kind in ('output', 'other'):
        assert remote_group_usage(network, units[10], 56, 8, kind).html == ''
    assert remote_action_usage(units[10], 202, 7, 11).html == ''


def test_all_unit_factory_wireless_profiles_and_exact_gap_refusals():
    _, _, _, units = fixture()
    selected = [row for row in REGISTRATIONS if row[0] in WIRELESS_TYPES]
    assert len(WIRELESS_TYPES) == 50 and len(selected) == 173
    for row in selected:
        for version in row[1:3]:
            assert len(wireless_profile(replace(units[1], unit_type=row[0], firmware=version))) == 4
    for typ, version in [('WRD2R1', '1.0.00'), ('WRD4F1', '2.4.00'), ('WRB2R1', '9.1'),
                         ('WRB2R1', ''), ('WRB2R1', 'broken')]:
        with pytest.raises(ValueError, match='class/agent firmware profile'):
            wireless_profile(replace(units[1], unit_type=typ, firmware=version))
    for version in ('1.1.1', '2.2.89.1', '2.5.0', ''):
        with pytest.raises(ValueError):
            gateway_profile(replace(units[3], firmware=version))


def test_global_macro_templates_first_match_fallbacks_and_shutter_aliases():
    _, _, _, units = fixture()
    inverse = {**{i: i for i in range(23)}, 23: 128, **{i: i + 168 for i in range(24, 31)}, 31: 255}
    first = {}
    for kind, _, candidates in MACRO_TEMPLATES:
        for candidate in candidates:
            first.setdefault(MICRO_GROUPS[candidate], kind)
    for commands, expected in first.items():
        unit = changed(units[1], Key1CommandLookup=[inverse[i] for i in commands], Key1Parameter1=[254] * 6,
                       BlockMemory1=[249] * 16, BlockMemory2=[2] * 16)
        assert wireless_key_data(unit).keys[0].kind == expected
    for memory, expected in [(249, 41), (252, 42), (255, 44), (42, 41)]:
        assert wireless_key_data(changed(units[1], Key1CommandLookup=[12, 0, 0, 0, 0, 0],
            BlockMemory1=[memory] * 16)).keys[0].kind == expected
    for memory, expected in [(2, 43), (5, 46), (42, 43)]:
        assert wireless_key_data(changed(units[1], Key1CommandLookup=[6, 0, 0, 0, 0, 0],
            BlockMemory2=[memory] * 16)).keys[0].kind == expected
    assert [command_type(i) for i in (32, 33, 127, 128, 192, 198, 199, 223, 224, 255)] == [0, 0, 0, 23, 24, 30, 0, 0, 31, 31]


def test_decorator_load_inverse_and_packed_nibble_remote_maps():
    _, _, network, units = fixture()
    base = units[1]
    for visible in (1, 2, 3, 4):
        assert [decorator_save(decorator_load(i, visible), visible) for i in range(16)] == list(range(16))
    unit = replace(base, unit_type='WRD2R1', firmware='2.4.00')
    extra = {f'Remote{i}Identity': [255] * 4 for i in range(2, 9)}
    # PP slot4 low nibble points to raw decorator key2; inverse gives key1.
    extra['Remote1KeyMap'] = [255, 255, 0xF2] + [255] * 5
    unit = changed(unit, **extra)
    network.units[0] = unit
    data = wireless_key_data(unit)
    assert [key.kind for key in data.keys[:4]] == [20, 24, 33, 22]
    mapping = input_remote_maps(network, unit)
    assert len(mapping) == 8 and mapping[0][0] is units[10] and mapping[0][1][0] == 1
    # Packed nibble15 -> KeyNumber16 is explicitly discarded by the loader.
    assert mapping[0][1][1:] == (None,) * 9


@pytest.mark.parametrize('field,value', [('BlockGroup', None), ('BlockGroup', [8] * 15),
    ('BlockGroupSecondary', [2] * 16), ('Key16CommandLookup', [0] * 5),
    ('Key1BlockMap', [2] * 16), ('SceneVectorOffset', [0] * 7), ('InstalledChannels', [17]),
    ('OutputMaximumLevel', [256, 0]), ('SceneVector', [255] * 99)])
def test_consumed_missing_and_invalid_fields_emit_no_partial_table(field, value):
    _, model, network, units = fixture()
    out = doc._Writer()
    assert document_wireless(out, network, changed(units[1], **{field: value}), model.networks) == 'partial'
    assert not any(line.startswith('<table') for line in out.lines)
    assert field in out.unrecovered[0]['item']


def test_scene_metadata_and_pair_boundary_fail_closed_without_creation():
    _, model, network, units = fixture()
    network.application(202).group(7).levels = [doc.Level(99, 'Wrong Address', 11)]
    out = doc._Writer()
    assert document_wireless(out, network, units[1], model.networks) == 'partial'
    assert 'Level Address 11' in out.unrecovered[0]['item']
    assert network.application(202).group(7).levels == [doc.Level(99, 'Wrong Address', 11)]
    vector = [255] * 99 + [8]
    with pytest.raises(ValueError, match='byte 99'):
        wireless_key_data(changed(units[1], SceneVectorOffset=[99] + [255] * 7, SceneVector=vector))


def test_remote_missing_identity_does_not_create_project_unit_and_known_absence_needs_no_map():
    _, model, network, units = fixture()
    receiver = changed(units[1], Remote1Identity=[3, 32, 0, 0])
    network.units[0] = receiver
    before = deepcopy(model)
    result = remote_group_usage(network, units[10], 56, 8, 'input')
    assert result.status == 'unrecovered' and 'original loader would create a Unit' in result.missing[0]
    assert model == before
    receiver = changed(receiver, Remote1Identity=[255] * 4, Remote1KeyMap=None)
    network.units[0] = receiver
    assert input_remote_maps(network, receiver)[0] == (None, (None,) * 10)


def test_gateway_native_number_route_prefix_mode_and_clock_prefix():
    _, model, network, units = fixture()
    base = changed(units[2], ForwardingRoute=[99, 3, 42, 4, 255, 255, 255])
    out = doc._Writer()
    assert document_wireless(out, network, base, model.networks) == 'recovered'
    assert 'Send Messages to Remote Network: <a href="#3">Route 1</a><br/>' in out.lines
    # The model carries separate native routing Number and report anchor Address.
    next(item for item in model.networks if item.network_number == 3).address = 101
    out = doc._Writer()
    assert document_wireless(out, network, base, model.networks) == 'recovered'
    assert 'Send Messages to Remote Network: <a href="#101">Route 1</a><br/>' in out.lines
    no_far = replace(base, address=77, parameters={})
    out = doc._Writer()
    assert document_wireless(out, network, no_far, model.networks) == 'recovered'
    assert out.lines[-1] == 'WARNING: Wireless Gateway has no far side Network.'
    model.networks[1].network_number = None
    out = doc._Writer()
    assert document_wireless(out, network, base, model.networks) == 'partial'
    assert 'NetworkNumber' in out.unrecovered[0]['item']
    _, model, network, units = fixture()
    out = doc._Writer()
    advanced = replace(units[3], fields={'Burden': '1', 'ClockGenEnable': '1'})
    assert document_wireless(out, network, advanced, model.networks) == 'recovered'
    assert not any('clock is enabled' in line or 'burden is enabled' in line for line in out.lines)
    ordinary = replace(changed(advanced, MapWirelessRemotes=[0]), parameters={
        **units[2].parameters, 'MapWirelessRemotes': '0'}, fields=advanced.fields)
    out = doc._Writer()
    assert document_wireless(out, network, ordinary, model.networks) == 'recovered'
    assert 'Unit clock is enabled<br />' in out.lines and 'Unit burden is enabled<br />' in out.lines


def test_gateway_unassigned_primary_and_missing_scene_are_undefined_not_guessed():
    _, model, network, units = fixture()
    for unit, message in [(changed(units[3], Application=[255, 57]), 'undefined'),
                          (changed(units[3], SceneVectorOffset=[255] * 8), 'missing compacted scene')]:
        out = doc._Writer()
        assert document_wireless(out, network, unit, model.networks) == 'partial'
        assert not any(line.startswith('<table') for line in out.lines)
        assert message in out.unrecovered[0]['item']


def test_scene_secondary_flag_valid_offset_compaction_and_cycle_unassigned_scene():
    _, _, network, units = fixture()
    # Offsets100 and255 are skipped; highbit selects the secondary application.
    unit = changed(units[1], SceneVectorOffset=[100, 128, 255, 200] + [255] * 4,
                   Key3CommandLookup=[198, 0, 0, 0, 0, 0])
    data = wireless_key_data(unit)
    assert [(scene.application, scene.commands, scene.trigger_address) for scene in data.scenes] == [
        (57, ((8, 255),), 11), (57, (), 12)]
    assert (data.keys[2].kind, data.keys[2].scene_key, data.keys[2].scene) == (32, True, None)
    assert wireless_key_html(network, data, 2) == '<td>3</td><td>Scene Cycle</td><td>&nbsp;</td>'
    assert wireless_action_usage(unit, 202, 7, 11).html == ''


def test_basic_gateway_all_applications_and_no_forwarding_literal_branches():
    _, model, network, units = fixture()
    unit = changed(units[2], ApplicationConnectEnabled=[0], ForwardingMode=[0],
                   ForwardingRoute=None, SynchroniseToWired=[0], StatusMonitorApplication=[255])
    out = doc._Writer()
    assert document_wireless(out, network, unit, model.networks) == 'recovered'
    assert out.lines[-6:] == ['Adjacent Network: <a href="#2">Adjacent</a><br/>',
        'Connect Applications: All Applications<br/>', 'Send Messages to Adjacent Network: No<br/>',
        'Send Messages to a Remote Network: No<br/>', 'Sync To Wired: No<br/>',
        'Status Monitor Application: <Unused><br/>']


def test_static_receipt_reproduces_without_original_execution():
    executable = os.environ.get('CBUS_TOOLKIT_EXE')
    mapping = os.environ.get('CBUS_TOOLKIT_MAP')
    if not executable or not mapping:
        pytest.skip('explicit private Toolkit EXE/MAP static inputs not configured')
    sys.path.insert(0, str(ROOT / 'research'))
    from project_documentor_wireless_static import inspect
    actual = inspect(Path(executable), Path(mapping))
    assert actual == json.loads((ROOT / 'research/fixtures/project-documentor-wireless-static.json').read_text())
    assert actual['original_instructions_executed'] == 0 and all(actual['checks'].values())


def test_static_receipt_pins_complete_registration_and_model_facts():
    receipt = json.loads((ROOT / 'research/fixtures/project-documentor-wireless-static.json').read_text())
    assert len(receipt['native_profiles']) == 188 and len(receipt['methods']) == 75
    assert len(receipt['checks']) == 21 and all(receipt['checks'].values())
    assert len(receipt['macro_templates']) == 48 and len(receipt['micro_groups']) == 47
    assert receipt['original_instructions_executed'] == 0
    assert receipt['original_generated_page_comparison'] == 'not_obtained'
