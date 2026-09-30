"""NeoProClassic ordinary-key bodies from synthetic saved PP snapshots."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import sys

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_neoclassic as classic
from cbus_toolkit import project_documentation_neo as neo
from cbus_toolkit.macros import STAGES
from test_project_documentation_neo import network, pp, unit as neo_unit

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/experiments/2026-09-30/project-documentor-neoclassic-static.json"


def unit(typ="KEYC1", firmware="1.8.01", **changes):
    values = pp()
    for name in (*neo.JOIN_PARAMETERS, "SceneTable", "SceneTablePointer", "ControlAppGroupAddress",
                 "IndicatorBlockAssignment", "KeyMask"):
        values.pop(name)
    values.update(changes)
    return neo_unit({key: value for key, value in values.items() if value is not None}, typ, firmware)


def body(u, net=None):
    out = doc._Writer()
    status = classic.document_neoclassic(out, network() if net is None else net, u)
    return out, status


@pytest.mark.parametrize("typ,physical,infrared", [
    ("KEYC1", 1, False), ("KEYC2", 2, False), ("KEYC4", 4, False),
    ("KEYCIR1", 0, True), ("KEYCIR4", 4, True),
])
def test_native_eight_key_counts_and_physical_virtual_infrared_labels(typ, physical, infrared):
    u = unit(typ)
    data = classic.neoclassic_data(u)
    assert len(data.keys) == len(data.blocks) == 8
    assert data.physical_key_count == physical
    assert all(key.scene_index == 0 and key.scene_trigger is None for key in data.keys)
    out, status = body(u)
    assert status == "recovered" and not out.unrecovered
    rows = [line for line in out.lines if line.startswith('<tr><td>')]
    assert len(rows) == 8
    for index, row in enumerate(rows):
        prefix = "" if index < physical else "IR Key " if infrared else "Virtual Key "
        assert row.startswith(f'<tr><td>{prefix}{index + 1}</td>')
    assert not any('Bistable' in line or line == 'Scenes<br />' for line in out.lines)


@pytest.mark.parametrize("firmware", ["1.8.01", "1.8.1", "2.5.00", "8.9.9", "9"])
def test_numeric_original_class_firmware_admission(firmware):
    assert classic.neoclassic_profile(unit(firmware=firmware)).is_pro


@pytest.mark.parametrize("firmware", ["", "1.8.00", "1.7.99", "9.0.1", "unknown", "1.x.01", "9" * 5000])
def test_documentor_selection_alone_cannot_establish_native_class(firmware):
    out, status = body(unit(firmware=firmware))
    assert status == "partial" and not any(line.startswith('<table') for line in out.lines)
    assert 'class/firmware' in out.unrecovered[0]['item']


def test_ordinary_body_does_not_consume_scene_join_mask_or_trigger_parameters():
    u = unit(PatchEnable=[1], SceneTable=[1, 200], SceneTablePointer=[0],
             IndicatorBlockAssignment=[255], ControlAppGroupAddress=[8], KeyMask=[0],
             **{name: [1] for name in neo.JOIN_PARAMETERS})
    out, status = body(u)
    assert status == "recovered"
    assert 'Scenes<br />' not in out.lines
    assert not any('Join Key' in line or 'Unconnected Key' in line for line in out.lines)


@pytest.mark.parametrize("selectors", [None, [0] * 7, [0] * 7 + [1], [0] * 7 + [2]])
def test_encoded_or_missing_scene_selectors_remain_partial_even_with_disabled_capability(selectors):
    out, status = body(unit(SceneKeySelector=selectors, PatchEnable=[0]))
    assert status == "partial" and not any(line.startswith('<table') for line in out.lines)
    assert out.unrecovered


@pytest.mark.parametrize("field", ["Application", "SecondApplicationBlocks", "DebounceTime", "GroupAddress",
    "BlockAllocation", "JPCommand", "TimerHighByte", "LightLevelStore1", "TimerExpiryCommand"])
def test_consumed_missing_fields_do_not_emit_partial_key_tables(field):
    out, status = body(unit(**{field: None}))
    assert status == "partial" and not any(line.startswith('<table') for line in out.lines)


def test_secondary_application_and_first_group_identity_match_shared_native_key_renderer():
    values = pp()
    values['SecondApplicationBlocks'] = [8]
    values['GroupAddress'][:4] = [1, 2, 1, 1]
    values['BlockAllocation'][0] = 12
    values['LightLevelStore1'][2:4] = [240, 128]
    for stage, value in zip(STAGES, (12, 6, 7, 0)):
        values[stage][0] = value
    u = neo_unit(values, 'KEYC4', '1.8.01')
    data = classic.neoclassic_data(u)
    expected = neo.neo_data(u, neo.NeoProfile(4, True, False))
    assert data.blocks == expected.blocks and data.keys == expected.keys
    assert neo.neo_body_lines(network(), data, include_scenes=False) == neo.neo_body_lines(network(), expected)
    out, status = body(u)
    assert status == 'recovered'
    text = '\n'.join(out.lines)
    assert '<a href="#254_56_1_64">Low</a> (25%)' in text
    assert '<a href="#254_202_1">Mode</a></td><td>50%</td>' in text
    assert '94%' not in text


def test_mixed_key_macro_prefers_linear_block_and_preserves_primary_stored_alias():
    u = unit(GroupAddress=[255] * 8, SecondApplicationBlocks=[2],
             BlockAllocation=[0, 3, 3] + [0] * 5, JPCommand=[0, 12, 12] + [0] * 5,
             LightLevelStore1=[255] + [0] * 7)
    data = classic.neoclassic_data(u)
    assert (data.keys[1].application, data.keys[1].macro_label) == (202, 'Trigger 1')
    assert (data.keys[2].application, data.keys[2].macro_label) == (56, 'Shutter Open')


def test_virtual_timer_loading_defaults_and_idle_expiry_are_preserved():
    u = unit('KEYCIR1', BlockAllocation=[0] * 7 + [128], JPCommand=[0] * 7 + [13],
             SRCommand=[0] * 7 + [7], LPCommand=[0] * 7 + [15], TimerLowByte=[0] * 8,
             TimerExpiryCommand=[0] * 8, GroupAddress=[255] * 7 + [1])
    data = classic.neoclassic_data(u)
    assert data.keys[7].macro_label == 'Timer'
    assert data.blocks[7].timer == 300 and data.blocks[7].expiry == 0
    out, status = body(u)
    assert status == 'recovered' and any('0h5m0s</td><td>Idle' in line for line in out.lines)


@pytest.mark.parametrize("typ", classic.NEOCLASSIC_TYPES)
def test_full_report_dispatch_keeps_dependency_gaps_separate_from_recovered_body(typ):
    u, net = unit(typ), network()
    net.units = [u]
    text, summary = doc.render(doc.ProjectModel('Synthetic', [net]), generated=datetime(2026, 9, 30))
    assert summary['units'][0]['documentor'] == 'TClassicKeyInputDocumentor'
    assert summary['units'][0]['status'] == 'recovered'
    assert 'Virtual Key 8' in text or 'IR Key 8' in text
    assert summary['unrecovered']  # This fixture deliberately omits dependency/status programming.


def test_body_receipt_binds_runtime_and_method_local_projection_boundaries():
    receipt = json.loads(RECEIPT.read_text())
    assert len(receipt['checks']) == 104 and all(receipt['checks'].values())
    assert len(receipt['profiles']) == 5
    assert receipt['model_sha256'] == hashlib.sha256(Path(classic.__file__).read_bytes()).hexdigest()
    assert receipt['checks']['unused_first_match_is_exactly_idle_vector']
    assert receipt['original_executed'] is False
    assert receipt['original_generated_page_comparison'] == 'not_obtained'


def test_body_source_receipt_reproduces_when_configured():
    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source:
        pytest.skip('Set CBUS_TOOLKIT_EXE for the pinned KEYC/CIR body source comparison')
    sys.path.insert(0, str(ROOT / 'research'))
    from project_documentor_neoclassic_static import inspect
    exe = Path(source)
    assert inspect(exe, Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map')))) == json.loads(RECEIPT.read_text())
