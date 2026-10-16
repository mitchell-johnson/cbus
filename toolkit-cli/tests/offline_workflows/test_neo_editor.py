"""Synthetic policy vectors, never original terminal or persistence acceptance."""
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from cbus_toolkit.extended_macros import ExtendedKeys, LAYOUTS
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.offline_workflows.neo_editor import (
    NeoEditor, NeoEditorError, NeoProfile, NeoSnapshot,
)
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


def synthetic_editor(*, value_overrides=None, spec_override=None, memory_override=None):
    defaults = {
        "JPCommand": [0, 3, 0, 0, 12, 0, 0, 7],
        "SRCommand": [0, 5, 0, 0, 6, 0, 0, 8],
        "LPCommand": [0, 7, 0, 0, 5, 0, 0, 9],
        "LRCommand": [0, 9, 0, 0, 4, 0, 0, 10],
        "BlockAllocation": [1, 2, 4, 8, 16, 32, 64, 128],
        "GroupAddress": [255] * 9, "Application": [56, 57],
        "SecondApplicationBlocks": [0], "TimerHighByte": [0, 3, 0, 0, 5, 0, 0, 7],
        "TimerLowByte": [0, 17, 0, 0, 19, 0, 0, 23],
        "TimerExpiryCommand": [15, 14, 15, 15, 12, 15, 15, 10],
        "LightLevelStore1": [255, 31, 255, 255, 33, 255, 255, 35],
        "LightLevelStore2": [255, 41, 255, 255, 43, 255, 255, 45],
        "SceneKeySelector": [0] * 8, "IndicatorBlockAssignment": [0, 7, 2, 3, 6, 5, 6, 4],
    }
    parameters = {}
    for name, (address, count, bits, bit, skip) in LAYOUTS.items():
        fields = {"Name": name, "Type": "int", "Address": str(address), "ArraySize": str(count),
                  "BitSize": str(bits), "BitAddress": str(bit), "ArraySkip": str(skip),
                  "DefaultValue": " ".join(map(str, defaults[name]))}
        parameters[name] = ParameterSpec(name, "int", "synthetic.xml", fields)
    spec = UnitSpec("KEYM4.xml", {"Type": "KEYM4"}, ("synthetic.xml",), parameters)
    if spec_override:
        spec = spec_override(spec)
    values = {name: " ".join(map(str, value)) for name, value in defaults.items()}
    values.update(value_overrides or {})
    memory = ExtendedKeys(spec).codec.encode_many({name: values[name] for name in LAYOUTS}).apply(
        MemoryImage.from_bytes(b"\xa5" * 256))
    cells = dict(memory.data)
    del cells[0]  # Unrelated invalid/unknown byte must stay unknown.
    memory = memory_override(MemoryImage(cells)) if memory_override else MemoryImage(cells)
    values["OpaqueExtraPP"] = {"text": "unchanged", "array": [1, {"flag": True}]}
    graph = (b'<Installation><Project OID="p1"><TagName>WFNEO</TagName><!--keep-->'
             b'<Network OID="n1"><Address>254</Address><Unit OID="u1" custom="keep"/>'
             b'<Unit OID="u2"/><Application OID="a1"><Address>56</Address>'
             b'<Group OID="g1"><Address>1</Address></Group><Group OID="g2">'
             b'<Address>2</Address></Group></Application></Network></Project></Installation>')
    snapshot = NeoSnapshot(values, memory, graph, ((56, 1), (56, 2)))
    profile = NeoProfile("/db//WFNEO/254/p/1", "KEYM4", "2.5.00", "5054NL", "", "closed", True)
    return NeoEditor.open(spec, profile, snapshot), spec, values


def edit_a(editor):
    return editor.edit_preset(key=1, preset="toggle", group=1, block=1, application="primary")


def edit_b(editor):
    return editor.edit_preset(key=1, preset="off", group=2, block=1, application="primary")


def apply_a(editor):
    state = edit_a(editor).request_apply()
    return state.confirm_database(current=state.applied)


def test_ec1_cancel_local_draft_returns_complete_opening_snapshot():
    editor, _, _ = synthetic_editor()
    draft = edit_a(editor)
    assert draft.dirty and editor.working == editor.opening
    cancelled = draft.cancel_editor()
    assert not cancelled.is_open and not cancelled.dirty
    assert cancelled.working == cancelled.applied == cancelled.opening
    assert cancelled.local_apply_count == 0


def test_ec2_apply_a_edit_b_cancel_preserves_a_not_baseline_or_b():
    editor, _, _ = synthetic_editor()
    applied = apply_a(editor)
    assert applied.is_open and not applied.dirty and applied.local_apply_count == 1
    dirty_b = edit_b(applied)
    assert dirty_b.dirty
    cancelled = dirty_b.cancel_editor()
    assert cancelled.working == applied.working
    assert cancelled.working != editor.opening and cancelled.working != dirty_b.working
    assert cancelled.working.memory.byte(0x68) == 0xB0
    assert cancelled.working.memory.byte(0x50) == 1
    assert dirty_b.working.memory.byte(0x68) == 0xF0
    assert dirty_b.working.memory.byte(0x50) == 2
    assert cancelled.applied_revision == 1 and cancelled.draft_revision == 2


def test_ec3_nested_cancel_retains_b_applied_a_and_can_accept_once():
    editor, _, _ = synthetic_editor()
    applied = apply_a(editor)
    b = edit_b(applied)
    nested = b.request_apply().cancel_destination()
    assert nested.is_open and nested.dirty and nested.working == b.working
    assert nested.applied == applied.applied and nested.destination_action is None
    accepted = nested.request_apply().confirm_database(current=nested.applied)
    assert accepted.local_apply_count == 2 and not accepted.dirty
    assert accepted.working.memory.byte(0x68) == 0xF0
    with pytest.raises(NeoEditorError, match="required"):
        accepted.confirm_database(current=accepted.applied)
    with pytest.raises(NeoEditorError, match="no unapplied"):
        accepted.request_apply()


def test_ok_closes_only_after_valid_local_acceptance():
    editor, _, _ = synthetic_editor()
    pending = edit_a(editor).request_ok()
    with pytest.raises(NeoEditorError, match="baseline"):
        pending.confirm_database(current=edit_b(editor).working)
    assert pending.is_open and pending.dirty and pending.destination_action == "ok"
    result = pending.confirm_database(current=editor.applied)
    assert not result.is_open and not result.dirty
    for method in (result.request_apply, result.request_ok, result.cancel_editor):
        with pytest.raises(NeoEditorError, match="closed"):
            method()
    with pytest.raises(NeoEditorError, match="closed"):
        result.edit_preset(key=1, preset="on")


@pytest.mark.parametrize("choice", [
    {"destination": "physical"}, {"destination": "both"}, {"entire_unit": True},
    {"dlt_labels": True}, {"changed_only": True}, {"changed_only": 0},
])
def test_unsupported_destinations_refuse_without_changing_pending_state(choice):
    editor, _, _ = synthetic_editor()
    pending = edit_a(editor).request_apply()
    before = pending.as_dict()
    with pytest.raises(NeoEditorError, match="Only local database"):
        pending.confirm_database(current=editor.applied, **choice)
    assert pending.as_dict() == before


@pytest.mark.parametrize("route", ["close", "escape", "ok", "apply"])
def test_uncaptured_cancel_aliases_refuse_and_record_only_explicit_cancel(route):
    editor, _, _ = synthetic_editor()
    with pytest.raises(NeoEditorError, match="original capture"):
        edit_a(editor).cancel_editor(route=route)
    assert edit_a(editor).cancel_editor().history[-1].details["requested_route"] == "cancel"


def test_pending_destination_blocks_edits_and_parent_cancel():
    editor, _, _ = synthetic_editor()
    pending = edit_a(editor).request_apply()
    for action in (lambda: pending.edit_preset(key=1, preset="off"), pending.cancel_editor,
                   pending.request_apply, pending.request_ok):
        with pytest.raises(NeoEditorError, match="already open"):
            action()


def test_literal_changes_preserve_all_other_values_graph_bytes_validity_and_guard_bits():
    editor, _, _ = synthetic_editor()
    a = edit_a(editor)
    assert a.working.graph_bytes == editor.opening.graph_bytes
    assert set(a.working.memory.data) == set(editor.opening.memory.data)
    assert {address for address, value in a.working.memory.data.items()
            if value != editor.opening.memory.data[address]} == {0x50, 0x68}
    assert {name for name in a.working.values
            if a.working.values[name] != editor.opening.values[name]} == {"JPCommand", "GroupAddress"}
    for address in (0x60, 0x62, 0x64, 0x67, 0x69, 0x6A, 0x70, 0x76, 0xFF):
        assert a.working.memory.byte(address) == editor.opening.memory.byte(address)


def test_validation_failure_then_correction_has_one_local_acceptance():
    editor, _, _ = synthetic_editor()
    with pytest.raises(NeoEditorError, match="already exist"):
        editor.edit_preset(key=1, preset="toggle", group=3, block=1)
    with pytest.raises(NeoEditorError, match="also assigned"):
        editor.edit_preset(key=1, preset="toggle", group=1, block=2)
    with pytest.raises(NeoEditorError, match="unsupported"):
        editor.edit_preset(key=1, preset="toggle", allow_shared_block=True)
    assert apply_a(editor).local_apply_count == 1 and editor.local_apply_count == 0


def test_trigger_application_refuses_even_stage_only_preset_or_custom():
    editor, _, _ = synthetic_editor(value_overrides={"Application": "202 57"})
    with pytest.raises(NeoEditorError, match="Lighting"):
        editor.edit_preset(key=1, preset="off")
    with pytest.raises(NeoEditorError, match="Lighting"):
        editor.edit_micro_functions(key=1, stages={"jp": 15})
    with pytest.raises(NeoEditorError, match="Trigger presets"):
        editor.edit_preset(key=1, preset="trigger1")


def test_custom_edit_reuses_only_named_stages_and_refuses_scene_key():
    editor, _, _ = synthetic_editor()
    custom = editor.edit_micro_functions(key=1, stages={"sr": "store1"})
    assert custom.working.memory.byte(0x68) == 1
    assert custom.working.values["JPCommand"] == editor.working.values["JPCommand"]
    scene, _, _ = synthetic_editor(value_overrides={"SceneKeySelector": "1 0 0 0 0 0 0 0"})
    with pytest.raises(NeoEditorError, match="scene keys"):
        scene.edit_micro_functions(key=1, stages={"jp": 15})


@pytest.mark.parametrize("change", [
    {"unit_type": "KEYM2"}, {"firmware": "2.5.01"}, {"catalogue": "5054N"},
    {"serial": "notblank"}, {"source": "//WFNEO/254/p/1"}, {"source": "/db//WFNEO/254/p/0"},
    {"network_state": "open"}, {"synthetic": False}, {"synthetic": 1},
])
def test_exact_profile_and_database_only_scope(change):
    editor, _, _ = synthetic_editor()
    with pytest.raises(NeoEditorError):
        replace(editor.profile, **change)


def test_missing_pp_raw_and_layout_mismatch_refuse_before_state_creation():
    editor, spec, _ = synthetic_editor()
    values = dict(editor.opening.values)
    del values["JPCommand"]
    with pytest.raises(NeoEditorError, match="omits"):
        NeoEditor.open(spec, editor.profile, replace(editor.opening, values=values))
    cells = dict(editor.opening.memory.data)
    cells[0x68] = 0xF0
    with pytest.raises(NeoEditorError, match="disagree"):
        NeoEditor.open(spec, editor.profile, replace(editor.opening, memory=MemoryImage(cells)))
    del cells[0x68]
    with pytest.raises(NeoEditorError, match="No known"):
        NeoEditor.open(spec, editor.profile, replace(editor.opening, memory=MemoryImage(cells)))
    parameters = dict(spec.parameters)
    row = parameters["JPCommand"]
    parameters["JPCommand"] = replace(row, fields={**row.fields, "Address": "103"})
    with pytest.raises(ValueError, match="layout"):
        NeoEditor.open(replace(spec, parameters=parameters), editor.profile, editor.opening)


@pytest.mark.parametrize("scope", ["values", "memory", "graph_bytes", "existing_groups"])
def test_stale_guard_compares_complete_snapshot(scope):
    editor, _, _ = synthetic_editor()
    pending = edit_a(editor).request_apply()
    if scope == "values":
        value = {**editor.applied.values, "OpaqueExtraPP": "drift"}
    elif scope == "memory":
        value = MemoryImage({**editor.applied.memory.data, 255: 0})
    elif scope == "graph_bytes":
        value = editor.applied.graph_bytes + b" "
    else:
        value = ((56, 2), (56, 1))
    stale = replace(editor.applied, **{scope: value})
    with pytest.raises(NeoEditorError, match="baseline"):
        pending.confirm_database(current=stale)


def test_immutable_inputs_exports_and_schema_defend_against_caller_mutation():
    editor, spec, input_values = synthetic_editor()
    input_values["OpaqueExtraPP"]["array"][1]["flag"] = False
    spec.parameters["JPCommand"].fields["Address"] = "99"
    assert editor.opening.values["OpaqueExtraPP"]["array"][1]["flag"] is True
    assert edit_a(editor).working.memory.byte(0x68) == 0xB0
    with pytest.raises(TypeError):
        editor.opening.values["JPCommand"] = "15"
    with pytest.raises(TypeError):
        editor.opening.values["OpaqueExtraPP"]["array"][1]["flag"] = False
    with pytest.raises(FrozenInstanceError):
        editor.is_open = False
    exported = editor.as_dict()
    exported["opening"]["values"]["OpaqueExtraPP"]["array"][1]["flag"] = False
    assert editor.opening.values["OpaqueExtraPP"]["array"][1]["flag"] is True


def test_reports_are_json_and_never_upgrade_local_policy_to_save_or_native_acceptance():
    editor, _, _ = synthetic_editor()
    receipt = apply_a(editor).as_dict()
    assert "PROPOSED" in receipt["policy"]
    assert receipt["original_terminal_semantics"] == "original terminal semantics unassessed"
    assert receipt["local_apply_count"] == 1
    assert receipt["pp_save_count"] == receipt["project_save_count"] == 0
    for key in ("saved", "io_performed", "external_persistence_verified", "native_acceptance",
                "physical_acceptance", "eager_graph_effects_observed"):
        assert receipt[key] is False
    assert "caller supplied" in receipt["opening"]["snapshot_provenance"]
    json.dumps(receipt)


def test_histories_perform_zero_file_socket_or_programming_io(monkeypatch):
    import builtins
    from pathlib import Path
    import socket

    editor, _, _ = synthetic_editor()
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Offline editor attempted I/O")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(Path, "read_bytes", forbidden)
        patch.setattr(Path, "write_bytes", forbidden)
        patch.setattr(Path, "read_text", forbidden)
        patch.setattr(Path, "write_text", forbidden)
        patch.setattr(ExtendedKeys, "apply", forbidden)
        a = apply_a(editor)
        b = edit_b(a).request_apply().cancel_destination()
        assert b.is_open and b.dirty
        assert b.cancel_editor().working == a.applied
        assert a.as_dict()["saved"] is False
    assert calls == []
