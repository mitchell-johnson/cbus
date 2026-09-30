"""Synthetic source vectors; these do not execute the original validator."""

import json
from pathlib import Path

import pytest

from cbus_toolkit.edlt_template_save_predicates import (
    KeyGroup, ResolvedScene, check_scene_widget_variants,
    validate_serial_text, validate_unit,
)


@pytest.mark.parametrize("text,outcome,value", [
    ("", "accepted", None), ("abc", "accepted", None),
    ("0000", "accepted", 0), ("4095", "accepted", 4095),
    ("4096", "rejected", 4096), ("prefix4095", "accepted", 4095),
    ("+001", "unproven_parse", None), ("   1", "unproven_parse", None),
    ("-001", "unproven_parse", None), ("١٢٣٤", "unproven_parse", None),
    ("😀a", "accepted", None), ("😀ab", "unproven_parse", None),
    ("😀4095", "accepted", 4095),
])
def test_serial(text, outcome, value):
    result = validate_serial_text(text)
    assert (result.outcome, result.value) == (outcome, value)


def test_serial_tail_can_start_inside_surrogate_pair():
    result = validate_serial_text("😀abc")
    assert result.last_four == "\ude00abc"
    assert result.outcome == "unproven_parse"


def test_unit_source_vectors():
    source = Path(__file__).resolve().parents[1] / "research/edlt_template_unit_validation_source.json"
    for vector in json.loads(source.read_text())["cases"]:
        groups = [KeyGroup(**group) for group in vector["ordered_key_groups"]]
        scenes = [ResolvedScene(index + 1, *row) for index, row in enumerate(vector["scenes"])]
        result = validate_unit(vector["primary_application"], vector["corridor_link"], groups, scenes)
        expected = vector["expected"]
        assert result.valid == expected["valid"], vector["name"]
        assert len(result.errors) == expected["appended_error_count"]
        if "scene_warning_ids" in expected:
            assert result.warning_ids == tuple(expected["scene_warning_ids"])
        assert result.skipped_scene_indices == tuple(expected.get("skipped_scene_indices_zero_based", []))
        if "corridor_tag_name" in expected:
            assert f'"{expected["corridor_tag_name"]}"' in result.errors[0]


def test_exact_messages_and_clause_order():
    result = validate_unit(56, 42, [KeyGroup(56, 42, "Synthetic A")], [
        ResolvedScene(1, 1, 7, 9, -1), ResolvedScene(2, 1, 7, 9, -1),
        ResolvedScene(3, 1, 255, 255, -1),
    ])
    assert result.errors[0] == ('The selected Corridor Link Group "Synthetic A" is also being used in at least one key function. '
                                "To resolve this error, either change the Corridor Link Group or remove it's associated key functions.")
    assert result.errors[1] == (
        "The following problems were detected with the scene configurations: "
        "\n\nMultiple scenes have been assigned with identical Trigger Group and Action Selector combinations."
        "\n\nOne or more scenes have been populated with items but have not been assigned a Trigger Group and/or Action Selector."
        "\n\nOne or more scenes have been populated with items but have not been assigned a scene label."
        "\n\nMultiple scenes have been assigned identical scene labels."
    )


def test_short_circuit_does_not_read_unneeded_actions():
    class Scene:
        item_count = 0
        name_index = 255
        trigger = 255

        @property
        def action(self):
            raise AssertionError("action must not be read")

    assert validate_unit(56, 255, (), [Scene(), Scene()]).valid


@pytest.mark.parametrize("name,status_variant,outcome", [
    (None, 99, "skipped_null_name"), ("", 99, "expected_index_exception"),
    ("", 0, "checked"),
])
def test_widget_null_name_gate(name, status_variant, outcome):
    result = check_scene_widget_variants("text", "icon", 0, status_variant, ((name, True),), True)
    assert result.outcome == outcome
    if outcome == "checked":
        assert result.label_inconsistent and not result.status_inconsistent


def test_widget_missing_level_and_status_only_index():
    result = check_scene_widget_variants("text", "icon", 99, 99, (), False)
    assert result.label_inconsistent and result.status_inconsistent
    assert check_scene_widget_variants(None, "text", -1, 0, (("", False),), True).outcome == "expected_index_exception"
