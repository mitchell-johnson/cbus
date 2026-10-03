"""Literal zero-key TNeoUnitAgent scene getter and serializer vectors."""
import pytest

from cbus_toolkit.native_sensor_scenes import loaded_scenes, scene_save_parameters


FIXED = [162, 182, 202, 222, 255, 255, 255, 255]
# Source audit vectors, independent of the implementation and device editor.
VECTORS = [
    ('duplicate-first-level', [20, 1, 20, 2, 255, 3, 30, 4] + [255] * 72,
     [0, 255, 255, 255, 255, 255, 255, 255],
     (((20, 1), (30, 4)),) + ((),) * 7,
     [20, 1, 30, 4] + [255] * 76, FIXED),
    ('duplicate-across-boundary', [20, 1, 20, 2, 20, 3, 30, 4] + [255] * 72,
     [0, 166, 255, 255, 255, 255, 255, 255],
     (((20, 1),), ((20, 3), (30, 4))) + ((),) * 6,
     [20, 1] + [255] * 18 + [20, 3, 30, 4] + [255] * 56, FIXED),
    ('compatible-hole', [10, 1, 255, 0, 20, 2] + [255] * 74,
     [0, 164, 166, 255, 255, 255, 255, 255],
     (((10, 1),), (), ((20, 2),)) + ((),) * 5,
     [10, 1] + [255] * 18 + [20, 2] + [255] * 58, FIXED),
    ('compact-hole', [10, 1, 255, 0, 11, 2, 12, 3, 13, 4, 14, 5] + [255] * 68,
     [0, 164, 166, 168, 170, 172, 255, 255],
     (((10, 1),), (), ((11, 2),), ((12, 3),), ((13, 4),), ((14, 5),), (), ()),
     [10, 1, 11, 2, 12, 3, 13, 4, 14, 5] + [255] * 70,
     [162, 255, 255, 255, 255, 255, 255, 255]),
    ('single-scene-eleven', [1, 100, 2, 101, 3, 102, 4, 103, 5, 104, 6, 105,
                            7, 106, 8, 107, 9, 108, 10, 109, 11, 110] + [255] * 58,
     [255] * 8,
     (((1, 100), (2, 101), (3, 102), (4, 103), (5, 104), (6, 105),
       (7, 106), (8, 107), (9, 108), (10, 109), (11, 110)),) + ((),) * 7,
     [1, 100, 2, 101, 3, 102, 4, 103, 5, 104, 6, 105,
      7, 106, 8, 107, 9, 108, 10, 109, 11, 110] + [255] * 58,
     [162, 255, 255, 255, 255, 255, 255, 255]),
    ('first-sentinel', [255, 0, 20, 99] + [255] * 76,
     [0, 164, 166, 168, 170, 172, 174, 176],
     ((),) * 8, [255] * 80, FIXED),
    ('odd-pointer-blocks-later-boundaries', [0, 255, 254, 0, 20, 123] + [255] * 74,
     [0, 165, 166, 168, 170, 172, 174, 176],
     (((0, 255), (254, 0), (20, 123)),) + ((),) * 7,
     [0, 255, 254, 0, 20, 123] + [255] * 74, FIXED),
]


@pytest.mark.parametrize('case,table,pointers,scenes,saved_table,saved_pointers', VECTORS,
                         ids=[row[0] for row in VECTORS])
def test_native_loaded_scene_save_vectors(case, table, pointers, scenes, saved_table, saved_pointers):
    assert loaded_scenes(table, pointers) == scenes
    current = {'PatchEnable': [0, 0], 'SceneTable': table, 'SceneTablePointer': pointers}
    assert scene_save_parameters(current) == {'SceneTable': saved_table, 'SceneTablePointer': saved_pointers}
    assert current == {'PatchEnable': [0, 0], 'SceneTable': table, 'SceneTablePointer': pointers}
    # Only the exact disabled sentinel suppresses writing. Getter facts survive.
    assert scene_save_parameters({**current, 'PatchEnable': [157, 64]}) == {}
    assert scene_save_parameters({**current, 'PatchEnable': [157, 65]}) == {
        'SceneTable': saved_table, 'SceneTablePointer': saved_pointers}


def test_full_eighty_byte_scene_retains_all_forty_commands():
    table = [value for group in range(40) for value in (group, 255 - group)]
    current = {'PatchEnable': [157, 0], 'SceneTable': table, 'SceneTablePointer': [255] * 8}
    assert tuple(len(scene) for scene in loaded_scenes(table, [255] * 8)) == (40, 0, 0, 0, 0, 0, 0, 0)
    assert scene_save_parameters(current) == {
        'SceneTable': table, 'SceneTablePointer': [162, 255, 255, 255, 255, 255, 255, 255]}


def test_compact_contiguous_five_scenes_and_last_scene_boundary():
    table = [10, 1, 11, 2, 12, 3, 13, 4, 14, 5] + [255] * 70
    pointers = [99, 164, 166, 168, 170, 255, 255, 255]
    assert scene_save_parameters({'PatchEnable': [0, 0], 'SceneTable': table, 'SceneTablePointer': pointers}) == {
        'SceneTable': table, 'SceneTablePointer': [162, 164, 166, 168, 170, 255, 255, 255]}
    table = [value for group in range(8) for value in (group, group + 20)] + [255] * 64
    pointers = [0, 164, 166, 168, 170, 172, 174, 176]
    assert loaded_scenes(table, pointers) == tuple(((group, group + 20),) for group in range(8))
    assert scene_save_parameters({'PatchEnable': [0, 0], 'SceneTable': table, 'SceneTablePointer': pointers}) == {
        'SceneTable': table, 'SceneTablePointer': [162, 164, 166, 168, 170, 172, 174, 176]}
