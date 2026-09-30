"""SceneModify survives refresh without ordinary-key subset normalization."""
import json
import os
from pathlib import Path
import sys

import pytest

from cbus_toolkit.project_documentation_neoclassic_modify import scene_modify_projection

ROOT = Path(__file__).parents[1]
RECEIPT = ROOT / "research/experiments/2026-09-30/project-documentor-neoclassic-scene-modify-static.json"


def project(commands, *, index=0, masks=None, groups=None, secondary=0):
    return scene_modify_projection(index, commands,
        masks=tuple(1 << slot for slot in range(8)) if masks is None else masks,
        groups=(255,) * 8 if groups is None else groups, secondary=secondary)


@pytest.mark.parametrize("commands", [(0, 0, 0, 0), (12, 0, 0, 0),
    (6, 0, 0, 0), (11, 7, 0, 7), (13, 15, 7, 15), (1, 2, 3, 4)])
def test_refresh_preserves_scene_modify_template_and_raw_stages(commands):
    result = project(commands)
    assert (result.macro_type, result.macro_label) == (25, "<Scene Modify>")
    assert result.commands == commands
    assert (result.scene_index, result.scene_ramp, result.scene_trigger) == (0, 0, None)


@pytest.mark.parametrize("override", [
    {"masks": (2, 2, 4, 8, 16, 32, 64, 128)},
    {"masks": (1, 3, 4, 8, 16, 32, 64, 128)},
    {"groups": (42, 255, 255, 255, 255, 255, 255, 255)},
    {"secondary": 1},
])
def test_noncanonical_block_history_is_refused(override):
    with pytest.raises(ValueError, match="unshared linear primary unused-group"):
        project((0, 11, 2, 14), **override)


def test_last_virtual_key_has_its_own_linear_block():
    assert project((12, 0, 0, 0), index=7).commands == (12, 0, 0, 0)
    with pytest.raises(ValueError, match="unshared linear primary unused-group"):
        project((12, 0, 0, 0), index=7, secondary=128)


@pytest.mark.parametrize("commands", [(14, 0, 0, 0), (16, 0, 0, 0), (0, 0, 0)])
def test_scene24_and_invalid_stage_vectors_are_refused(commands):
    with pytest.raises(ValueError, match="four raw nibble stages"):
        project(commands)


def test_scene_modify_receipt_closes_special_branch_and_keeps_filter_bypassed():
    receipt = json.loads(RECEIPT.read_text())
    assert all(receipt["checks"].values())
    assert all(receipt["inherited_scene_loader_checks"].values())
    assert receipt["original_executed"] is False
    assert receipt["original_generated_page_captured"] is False
    cases = receipt["source_table_transition_cases"]
    assert all(case["final_key_template_type"] == 25
               and case["consumer_commands_preserved"]
               and case["extension_scene_number"] == 1
               and case["extension_ramp_ordinal"] == 0 for case in cases)
    # Application255's normal subset allows only Unused. SceneModify still
    # stores the shutter alias20 on its extension and retains key template25.
    shutter = next(case for case in cases
                   if case["raw_commands"] == [12, 0, 0, 0] and case["application"] == 255)
    assert shutter["resolved_ramp_template_type"] == 20
    # Non-KEY global macros likewise survive on the internal ramp reference.
    sunset = next(case for case in cases
                  if case["raw_commands"] == [13, 15, 7, 15] and case["application"] == 56)
    assert sunset["resolved_ramp_template_type"] == 34


def test_scene_modify_receipt_reproduces_when_configured():
    source = os.environ.get("CBUS_TOOLKIT_EXE")
    if not source:
        pytest.skip("Set CBUS_TOOLKIT_EXE for the SceneModify source comparison")
    sys.path.insert(0, str(ROOT / "research"))
    from project_documentor_neoclassic_modify_static import inspect
    exe = Path(source)
    assert inspect(exe, Path(os.environ.get("CBUS_TOOLKIT_MAP", exe.with_suffix(".map")))) == json.loads(RECEIPT.read_text())
