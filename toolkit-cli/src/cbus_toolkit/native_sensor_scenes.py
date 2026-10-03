"""Native zero-key sensor scene load/save semantics, without scene editing.

These rules follow TNeoUnitAgent's getters and before-save serializers. Native
histories can contain duplicate groups, holes, padding levels and unordered
pointers; the standalone device scene editor's canonical decoder is unsuitable.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from .sensors import SensorError


def _bytes(values: Sequence[int], count: int, name: str) -> tuple[int, ...]:
    if len(values) != count or any(type(value) is not int or not 0 <= value <= 255 for value in values):
        raise SensorError(f"{name} requires exactly {count} bytes")
    return tuple(values)


def loaded_scenes(table: Sequence[int], pointers: Sequence[int]) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Load eight scenes, retaining the first group/level pair in each scene."""
    raw = _bytes(table, 80, 'SceneTable')
    positions = _bytes(pointers, 8, 'SceneTablePointer')
    scenes: list[list[tuple[int, int]]] = [[] for _ in range(8)]
    seen: list[set[int]] = [set() for _ in range(8)]
    if raw[0] != 255:
        scene = 0
        for offset in range(0, 80, 2):
            group, level = raw[offset:offset + 2]
            if group != 255 and group not in seen[scene]:
                seen[scene].add(group)
                scenes[scene].append((group, level))
            # Native tests the next pointer after every pair, including an
            # ignored duplicate or sentinel. Pointer zero never selects a start.
            if scene < 7 and positions[scene + 1] == 162 + offset + 2:
                scene += 1
    return tuple(tuple(commands) for commands in scenes)


def scene_save_parameters(expected: Mapping[str, Sequence[int]]) -> dict[str, list[int]]:
    """Return native enabled-scene output; Area and Patch are never writable."""
    patch = _bytes(expected['PatchEnable'], 2, 'PatchEnable')
    scenes = loaded_scenes(expected['SceneTable'], expected['SceneTablePointer'])
    if patch == (157, 64):
        return {}
    nonempty = [commands for commands in scenes if commands]
    compatible = len(nonempty) <= 4 and max((len(commands) for commands in scenes), default=0) <= 10
    table = [255] * 80
    cursor = 0
    for ordinal, commands in enumerate(nonempty):
        if compatible:
            cursor = ordinal * 20
        for group, level in commands:
            table[cursor:cursor + 2] = [group, level]
            cursor += 2
    pointers = [162, 255, 255, 255, 255, 255, 255, 255]
    if compatible:
        pointers[1:4] = [182, 202, 222]
    else:
        for index in range(1, 8):
            # This uses the original scene indices, unlike the table's packed
            # nonempty ordinal. A hole stops pointer serialization immediately.
            if not scenes[index]:
                break
            pointers[index] = pointers[index - 1] + 2 * len(scenes[index - 1])
    return {'SceneTable': table, 'SceneTablePointer': pointers}
