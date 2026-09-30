"""Canonical NeoProClassic SceneModify consumer state from pinned source.

The loader's final refresh assigns the resolved raw macro to the extension's
ramp-template reference under its lock. It preserves key template 25 and the
raw stages. The Classic body and usage consumers do not read that reference or
the final indicator block number; neither is inferred here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SceneModifyProjection:
    commands: tuple[int, ...]
    macro_type: int = 25
    macro_label: str = "<Scene Modify>"
    scene_index: int = 0
    scene_ramp: int = 0
    scene_trigger: None = None


def scene_modify_projection(index: int, commands: tuple[int, ...], *,
                            masks: tuple[int, ...], groups: tuple[int, ...],
                            secondary: int) -> SceneModifyProjection:
    """Project a selector-1/JP-not-14 key on the canonical eight-block graph.

    The caller owns exact KEYC/CIR profile and SceneKeySelector admission.
    An unshared, linear primary unused block makes the initial template event's
    remove/add transitions preserve the consumed block data. Retained GUI
    history and noncanonical relocation remain outside this contract.
    """
    if (type(index) is not int or not 0 <= index < 8 or len(masks) != 8
            or len(groups) != 8 or type(secondary) is not int or not 0 <= secondary <= 255
            or any(type(value) is not int or not 0 <= value <= 255
                   for value in (*masks, *groups))):
        raise ValueError("NeoProClassic Scene Modify requires an explicit eight-block graph")
    if (len(commands) != 4 or any(type(value) is not int or not 0 <= value <= 15
                                  for value in commands) or commands[0] == 14):
        raise ValueError("NeoProClassic Scene Modify requires four raw nibble stages and JP != 14")
    bit = 1 << index
    if (masks[index] != bit or groups[index] != 255 or secondary & bit
            or any(mask & bit for other, mask in enumerate(masks) if other != index)):
        raise ValueError("NeoProClassic scene key requires an unshared linear primary unused-group block")
    return SceneModifyProjection(tuple(commands))
