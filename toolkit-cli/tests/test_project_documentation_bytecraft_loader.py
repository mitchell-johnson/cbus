"""Explicit old DIMPR12 packed scenes and conservative admission boundaries."""
import json
import os
from pathlib import Path
import sys

import pytest

from cbus_toolkit.project_documentation import Unit
from cbus_toolkit.project_documentation_bytecraft_loader import decode_bytecraft_scenes

FIXTURE = Path(__file__).parents[1] / 'research/fixtures/project-documentor-bytecraft-loader-static.json'


def unit(*, firmware='1.9.02', kind='DIMPR12', records=None, **changes):
    pp = {f'PresetRec{index:02d}': ' '.join(map(str, (records or {}).get(index, [0] * 32)))
          for index in range(33)}
    pp.update(changes)
    return Unit(1, 'Dimmer', kind, kind, '', firmware, '',
                {name: value for name, value in pp.items() if value is not None}, {})


def test_count_order_and_empty_explicit_records():
    scenes = decode_bytecraft_scenes(unit())
    assert tuple(scene.index for scene in scenes) == tuple(range(33))
    assert all(scene.unused and scene.on_unused and scene.off_unused for scene in scenes)
    assert all(not scene.advanced and scene.recall_group == scene.selector_address == 0 for scene in scenes)
    assert scenes[0].on_levels == (0,) * 12 and scenes[-1].off_levels == (0,) * 12


def test_packed_high_mask_channels_ramps_and_independent_levels():
    # Ramp bits share each mask's high byte but lie above the 12 channel bits.
    record = [1, 255, 255, 23, 0xAB, 0x81, *range(11, 23), 0x5D, 2, *range(31, 43)]
    scene = decode_bytecraft_scenes(unit(records={32: record}))[32]
    assert scene.advanced and (scene.recall_group, scene.selector_address, scene.link_group) == (255, 255, 23)
    assert scene.on == (True, False, False, False, False, False, False, True, True, True, False, True)
    assert scene.off == (False, True, False, False, False, False, False, False, True, False, True, True)
    assert scene.ramp_on == 10 and scene.ramp_off == 5
    assert scene.on_levels == tuple(range(11, 23)) and scene.off_levels == tuple(range(31, 43))


def test_all_12_mask_bits_normalize_before_low_byte_boolean_setters():
    records = {}
    for index in range(12):
        record = [0] * 32
        mask = 1 << index
        record[4], record[5] = mask >> 8, mask & 255
        record[18], record[19] = mask >> 8, mask & 255
        records[index] = record
    for index, scene in enumerate(decode_bytecraft_scenes(unit(records=records))[:12]):
        assert scene.on == scene.off == tuple(channel == index for channel in range(12))
        assert not scene.unused


@pytest.mark.parametrize('mode,advanced', [(0, False), (1, True), (2, False), (128, False), (255, False)])
def test_mode_is_exactly_one_not_general_nonzero(mode, advanced):
    record = [mode] + [0] * 31
    assert decode_bytecraft_scenes(unit(records={0: record}))[0].advanced is advanced


def test_levels_and_ramp_bits_alone_do_not_make_scene_used():
    record = [1, 8, 7, 6, 0xF0, 0, *([255] * 12), 0xE0, 0, *([255] * 12)]
    scene = decode_bytecraft_scenes(unit(records={1: record}))[1]
    assert scene.unused and scene.on_unused and scene.off_unused
    assert (scene.ramp_on, scene.ramp_off) == (15, 14)
    # A single off inclusion makes a basic-mode record used too.
    record[0], record[19] = 0, 1
    scene = decode_bytecraft_scenes(unit(records={1: record}))[1]
    assert not scene.unused and scene.on_unused and not scene.off_unused


@pytest.mark.parametrize('firmware', ['0', '1.9.01', '1.9.02'])
def test_old_registration_admitted(firmware):
    assert len(decode_bytecraft_scenes(unit(firmware=firmware))) == 33


@pytest.mark.parametrize('firmware', ['', '1.9.03', '9', '1.9.x', None, '2147483648'])
def test_l1_missing_and_malformed_firmware_refused(firmware):
    with pytest.raises(ValueError, match='old DIMPR12'):
        decode_bytecraft_scenes(unit(firmware=firmware))


@pytest.mark.parametrize('kind', ['DIMPR12A', 'DIMPR12L1', 'dimpr12'])
def test_other_registration_refused(kind):
    with pytest.raises(ValueError, match='old DIMPR12'):
        decode_bytecraft_scenes(unit(kind=kind))


@pytest.mark.parametrize('value', [None, '', '0 ' * 31, '0 ' * 31 + '-1',
    '0 ' * 31 + '256', '0 ' * 31 + 'broken', '0 ' * 32 + '256'])
def test_missing_partial_or_malformed_records_do_not_synthesize_defaults(value):
    with pytest.raises(ValueError, match='PresetRec32'):
        decode_bytecraft_scenes(unit(PresetRec32=value))


def test_extra_valid_values_ignored_and_other_pp_not_consumed():
    assert decode_bytecraft_scenes(unit(PresetRec00='0 ' * 32 + '99', Application='broken',
        GroupAddress='broken', LogicAttributes='broken')) == decode_bytecraft_scenes(unit())


def test_static_receipt_records_correction_and_unperformed_acceptance():
    receipt = json.loads(FIXTURE.read_text())
    assert all(receipt['checks'].values())
    assert len(receipt['assessment_spans_reproduced']) == 13
    assert receipt['scene_count'] == 33 and receipt['native_packed_array_default'] == 0
    assert 'SETG DL' in receipt['assessment_correction']
    assert receipt['original_loader_execution'] == 'not_executed'
    assert receipt['prior_scene_history'] == 'not_modeled'


def test_static_receipt_reproduces_when_configured():
    source = os.environ.get('CBUS_TOOLKIT_EXE')
    specification = os.environ.get('CBUS_BYTECRAFT_SPEC')
    if not source or not specification:
        pytest.skip('Set CBUS_TOOLKIT_EXE and CBUS_BYTECRAFT_SPEC for pinned static comparison')
    sys.path.insert(0, str(FIXTURE.parents[1]))
    from project_documentor_bytecraft_loader_static import inspect
    exe = Path(source)
    result = inspect(exe, Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map'))), Path(specification))
    assert json.loads(json.dumps(result)) == json.loads(FIXTURE.read_text())
