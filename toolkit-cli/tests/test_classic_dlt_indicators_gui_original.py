"""Independent original component event observations versus the public editor."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from cbus_toolkit.dlt_indicators import ClassicDltIndicators
from cbus_toolkit.dlt_labels import DltLabelError
from test_dlt_indicators import fixture


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/fixtures/classic-dlt-indicators-gui-original.json'
REPORT = json.loads(EVIDENCE.read_text())
VENDOR = os.environ.get('CBUS_DLT_VENDOR_ROOT')
EXECUTABLE = os.environ.get('CBUS_TOOLKIT_EXE') or (
    str(Path(VENDOR) / 'toolkit/app/CBusToolkit.exe') if VENDOR else None)
# These are independently named original PP bindings, not runtime constants.
FIELDS = {
    'page_fallback': 'EnablePageFallback', 'pressed_enabled': 'EnableIndicatorPressedLevel',
    'duration_seconds': 'TimerDuration', 'pressed_level': 'IndicatorPressedLevel',
    'nightlight_keys': 'EnableNightlightOnUserKeys', 'nightlight_toggle': 'EnableNightlightOnToggleKey',
    'first_key_throwaway': 'FirstKeyThrowAway',
}


def assert_snapshot(actual, original):
    assert {name: actual[name] for name in FIELDS} == original['controls']
    assert actual['duration_selected_seconds'] == original['duration_item_seconds']
    assert original['duration_item_seconds'] == original['duration_item_index'] + 2


def test_retained_source_contract_and_scope():
    assert REPORT['format'] == 'cbus-classic-dlt-indicators-gui-original-v1'
    assert REPORT['passed'] is True
    assert REPORT['original_full_form_executed'] is False
    assert REPORT['physical_hardware_verified'] is False
    assert REPORT['duration_items'] == list(range(2, 16))
    assert len(REPORT['observations']) == 32
    bindings = REPORT['gui_bindings']
    assert bindings['nightlight']['condition_uses_visibility_not_enabled'] == {
        'visible_field': 'control+0x59', 'enabled_field': 'control+0x5a'}
    assert bindings['pressed_brightness_slider']['minimum'] == 0
    assert bindings['pressed_brightness_slider']['maximum'] == 15
    assert bindings['pressed_brightness_slider']['use_raw_values'] is True
    assert bindings['controls']['0x300']['immediate'] is True
    assert bindings['checkbox_contract']['unchanged_state'] == 'No property write and no click callback'
    assert bindings['controls']['0x2e0']['expression'] == 'EnableNightLightOnKeys'
    assert bindings['controls']['0x2e8']['expression'] == 'EnableNightlightOnToggle'
    assert bindings['controls']['0x2e4']['expression'] == 'FirstKeyThrowaway'
    for source, key in (('classic_dlt_indicators_gui_original.py', 'script_sha256'),
                        ('classic_dlt_indicator_gui_bindings.py', 'bindings_script_sha256')):
        assert hashlib.sha256((ROOT / 'research' / source).read_bytes()).hexdigest() == REPORT[key]
    for span in (*REPORT['methods'].values(), *REPORT['fragments'].values(), *bindings['methods'].values()):
        assert int(span['start'], 16) < int(span['stop'], 16)
        assert len(span['sha256']) == 64


@pytest.mark.parametrize('row', REPORT['observations'], ids=[row['name'] for row in REPORT['observations']])
def test_public_editor_matches_independent_original_component_events(row):
    spec = fixture()
    editor = ClassicDltIndicators(spec, 'KEYBL5')
    values = spec.defaults()
    values.update({parameter: str(int(row['input'][name])) for name, parameter in FIELDS.items()})
    # Preserve unrelated neighbouring bits while original DLT save normalizes
    # the inherited nightlight flag; that agent-save evidence is separate.
    values.update(EnableNightlight='1', DisableTimerFlash='1', EnableNightlightControl='1')
    shown = editor.show(values)
    assert_snapshot(shown['controls'], row['initialized'])
    assert shown['enabled'] == row['initialized']['enabled']
    assert row['original_instruction_count'] > 0
    if not row['operations']:
        return
    if any(step['refused'] for step in row['transitions']):
        with pytest.raises(DltLabelError, match='disabled'):
            editor.plan(values, operations=row['operations'])
        return
    plan = editor.plan(values, operations=row['operations'])
    result = plan.as_dict()
    assert_snapshot(result['before'], row['initialized'])
    assert_snapshot(result['after'], row['output'])
    assert result['enabled_after'] == row['output']['enabled']
    assert len(result['steps']) == len(row['transitions'])
    for actual, original in zip(result['steps'], row['transitions']):
        assert_snapshot(actual['before'], original['before'])
        assert_snapshot(actual['after'], original['after'])
        assert actual['enabled_after'] == original['after']['enabled']
    effective = {**plan.expected, **plan.changes}
    assert {name: effective[parameter][0] for name, parameter in FIELDS.items()} == row['output']['controls']
    assert effective['EnableNightlight'] == (0,)
    assert effective['DisableTimerFlash'] == effective['EnableNightlightControl'] == (1,)


def test_distinct_original_event_orders_and_checkbox_noop_are_retained():
    cases = {row['name']: row for row in REPORT['observations']}
    assert cases['disable-pressed-then-page']['output']['controls']['duration_seconds'] == 15
    assert cases['disable-page-then-pressed']['output']['controls']['duration_seconds'] == 0
    assert cases['page-enable-from-zero']['output']['controls']['duration_seconds'] == 15
    assert cases['pressed-enable-from-zero']['output']['controls']['duration_seconds'] == 2
    for step in cases['unchanged-checkbox-no-callback']['transitions']:
        assert step['writes'] == []
        assert step['original_instruction_count'] == 0
    for name in ('nightlight-disable-keys-then-toggle', 'nightlight-disable-toggle-then-keys'):
        assert cases[name]['transitions'][0]['after']['controls']['first_key_throwaway'] is True
        assert cases[name]['transitions'][1]['after']['controls']['first_key_throwaway'] is False


def test_unpinned_executable_or_map_refused_before_emulation(tmp_path):
    from research.classic_dlt_indicators_gui_original import ClassicIndicatorsGuiProbe
    unknown = tmp_path / 'unknown.bin'
    unknown.write_bytes(b'not an original executable or map')
    with pytest.raises(ValueError, match='pinned Toolkit'):
        ClassicIndicatorsGuiProbe(unknown, unknown)


@pytest.mark.skipif(not EXECUTABLE, reason='requires pinned original Toolkit EXE/MAP and Unicorn JIT permission')
def test_fresh_original_component_replay_matches_retained_receipt():
    from research.classic_dlt_indicators_gui_original import inspect
    executable = Path(EXECUTABLE)
    mapping = Path(os.environ.get('CBUS_TOOLKIT_MAP', executable.with_suffix('.map')))
    assert inspect(executable, mapping) == REPORT
