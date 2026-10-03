"""Static source proof and literal fixture consistency; no vendor instructions."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
RESEARCH=ROOT/'toolkit-cli/research'
ANNEX=RESEARCH/'fixtures/edlt-dual-key-control-source-annex.json'

def load_extractor():
    spec=importlib.util.spec_from_file_location('dual_key_static',RESEARCH/'edlt_dual_key_control_static.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_exact_static_proof_members_and_no_execution_claim():
    annex=json.loads(ANNEX.read_text())
    assert len(annex['original_inputs'])==24
    assert {row['logical_name'] for row in annex['original_inputs']} >= {'CBusLogicModel.dll','eDLT.dll','PPAttribute.cs','LevelControl.cs','TimerSelector.cs'}
    assert len(annex['managed_method_spans'])==187
    assert len(annex['static_checks'])==37
    assert len(annex['ordered_panel_bindings'])==33
    assert len(annex['decompiled_source_symbols'])==481
    assert annex['scope']['original_executed'] is False
    assert annex['scope']['framework_executed'] is False
    assert annex['scope']['physical_verified'] is False
    ids={r['id'] for r in annex['static_checks']}
    assert {'both-shutter-controls-have-six-248-setvalue-bounds','source-typo-target1-only',
        'timer-high-shift-not-mask','rcp-coupled-icon-off-before-on','macro-getter-effects-explicit',
        'mouse-down-int32-unchecked-sub-before-double'}<=ids
    assert all('string_literals' not in r for r in annex['managed_method_spans'])
    values=annex['source_choices']
    assert [r['value'] for r in values['lRampRate']]==list(range(16))
    assert [r['value'] for r in values['lShutterRelayKeyFunction']]==[0,1]
    assert [r['value'] for r in values['lDualKeyMacroFunctionsRCP']]==[255,25]
    assert [r['value'] for r in values['lDualKeyMacroFunctionsTimer']]==['35|34']
    assert [r['value'] for r in values['LKeyColours']]==list(range(9))


def test_literal_coverage_separate_from_runtime_output():
    fixture=json.loads((RESEARCH/'fixtures/edlt-dual-key-control-literal-vectors.json').read_text())
    assert len(fixture['property_cases'])==120
    assert len(fixture['control_cases'])==118
    assert fixture['original_executed'] is False
    assert {c['family'] for c in fixture['control_cases']}=={'timer','shutter','room-courtesy'}
    assert all(len(bytes.fromhex(c['expected_record_hex']))==32
        for c in fixture['property_cases']+fixture['control_cases'])


def test_provenance_hashes_saved_annex_and_literals():
    provenance=json.loads((RESEARCH/'fixtures/edlt-dual-key-control-provenance.json').read_text())
    for row in provenance['artifacts']:
        raw=(ROOT/row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==row['sha256']
        assert len(raw)==row['bytes']
    assert provenance['original_executed'] is False
    assert provenance['literal_authoring']['producer_imported'] is False


def test_source_annex_full_regeneration_from_configured_bytes():
    vendor=os.environ.get('CBUS_DUAL_KEY_STATIC_ROOT')
    if not vendor:
        pytest.skip('Requires explicit pinned original static-byte input directory; no vendor execution')
    regenerated=load_extractor().recover(ROOT,Path(vendor))
    raw=(json.dumps(regenerated,sort_keys=True,indent=2)+'\n').encode()
    assert raw==ANNEX.read_bytes()


def test_complete_macro_dependency_and_actual_override_metadata():
    from cbus_toolkit.edlt_dual_key_control_properties import MACRO_INPUTS
    annex=json.loads(ANNEX.read_text())
    assert [(r['macro'],tuple(r['inputs'])) for r in annex['macro_input_profiles']]==list(MACRO_INPUTS.items())
    assert len(annex['metadata_type_relationships'])==7
    for name in ('TimerData','ShutterRelayData','RCPData'):
        row=next(r for r in annex['metadata_type_relationships'] if r['type'].endswith('.'+name))
        assert row['base_type'].endswith('.AppGroupButtonFunctionsData')
    row=next(r for r in annex['managed_method_spans'] if r['symbol'].endswith('TimerData::SetForcedValues'))
    assert row['method_virtual'] is True and row['method_new_slot'] is False
