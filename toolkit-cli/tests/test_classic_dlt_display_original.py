"""Independent original display evidence and opt-in fresh instruction replay."""
import json
import os
from pathlib import Path

import pytest

from cbus_toolkit.dlt_display import ClassicDltDisplay, MODES
from test_dlt_display import fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/classic-dlt-display-original.json'
REPORT = json.loads(FIXTURE.read_text())
VENDOR = os.environ.get('CBUS_DLT_VENDOR_ROOT')
EXECUTABLE = os.environ.get('CBUS_TOOLKIT_EXE') or (
    str(Path(VENDOR) / 'toolkit/app/CBusToolkit.exe') if VENDOR else None)
SPECIFICATIONS = os.environ.get('CBUS_UNITSPEC_DIR')


def test_retained_source_locations_layout_and_boundaries():
    controls = json.loads((FIXTURE.parent / 'classic-dlt-controls-original.json').read_text())
    assert REPORT['format'] == 'cbus-classic-dlt-display-original-v1'
    assert REPORT['source'] == controls['source']
    assert REPORT['passed'] is True
    assert REPORT['original_full_form_executed'] is False
    assert REPORT['physical_hardware_verified'] is False
    assert len(REPORT['observations']) == 15
    assert [row['case_count'] for row in REPORT['conversion_checks']] == [10, 256]
    assert REPORT['parameters'] == {
        'IndicatorMode': {'address': 0x35, 'bit': 0, 'width': 2, 'default': 1},
        'InvertDisplay': {'address': 0x35, 'bit': 4, 'width': 1, 'default': 0},
        'HideClock': {'address': 0x35, 'bit': 5, 'width': 1, 'default': 0},
    }
    assert REPORT['rules']['indicator_load'] == {'0': 'off', '1': 'normal', '2': 'on', '3': 'on'}
    assert REPORT['rules']['indicator_save'] == {'off': 0, 'normal': 1, 'on': 2}
    assert {row['property'] for row in REPORT['checkbox_bindings']} == {'InvertDisplay', 'ShowClock'}
    for span in (*REPORT['methods'].values(), *REPORT['fragments'].values()):
        assert int(span['start'], 16) < int(span['stop'], 16)
        assert len(span['sha256']) == 64


@pytest.mark.parametrize('observation', REPORT['observations'], ids=[
    f"{row['control']}-{row['operation']}-{row['input']}" for row in REPORT['observations']])
def test_original_display_observations_match_portable_control(observation):
    spec = fixture()
    editor = ClassicDltDisplay(spec, 'KEYBL5')
    values = spec.defaults()
    control, parameter = {
        'indicator': ('indicator_mode', 'IndicatorMode'),
        'invert': ('invert_display', 'InvertDisplay'),
        'clock': ('show_clock', 'HideClock'),
    }[observation['control']]
    assert observation['other_attributes_preserved'] is True
    assert observation['original_instruction_count'] > 0
    if observation['operation'] == 'load':
        values[parameter] = str(int(observation['input']))
        expected = (MODES[observation['output']] if control == 'indicator_mode'
                    else observation['output'])
        assert editor.show(values)['controls'][control] == expected
    else:
        selected = (MODES[observation['input']] if control == 'indicator_mode'
                    else observation['input'])
        plan = editor.plan(values, settings={control: selected})
        effective = {**plan.expected, **plan.changes}
        assert effective[parameter] == (int(observation['output']),)
        assert all(effective[name] == previous for name, previous in plan.expected.items()
                   if name != parameter)


def test_unpinned_executable_and_map_refused_before_emulation(tmp_path):
    from research.classic_dlt_display_original import ClassicDisplayProbe
    source = tmp_path / 'untrusted.bin'
    source.write_bytes(b'not a vendor executable or map')
    with pytest.raises(ValueError, match='pinned Toolkit'):
        ClassicDisplayProbe(source, source)


def test_unpinned_specification_refused_before_parsing_or_emulation(tmp_path):
    from research.classic_dlt_display_original import ClassicDisplayProbe
    source = tmp_path / 'I_DLT.xml'
    source.write_bytes(b'not the pinned unit specification')
    probe = ClassicDisplayProbe.__new__(ClassicDisplayProbe)
    with pytest.raises(ValueError, match='pinned DLT profile facts'):
        probe.static_facts(source)


@pytest.mark.skipif(not (EXECUTABLE and SPECIFICATIONS),
                    reason='requires pinned original Toolkit EXE/MAP and decoded I_DLT.xml')
def test_fresh_original_instructions_match_retained_evidence():
    from research.classic_dlt_display_original import inspect
    executable = Path(EXECUTABLE)
    symbols = Path(os.environ.get('CBUS_TOOLKIT_MAP', executable.with_suffix('.map')))
    assert inspect(executable, symbols, Path(SPECIFICATIONS) / 'I_DLT.xml') == REPORT
