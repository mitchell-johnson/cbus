"""Review regressions for complete typed Neo baselines and declared layouts."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from cbus_toolkit.cli import main
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.offline_workflows.neo_editor import NeoEditor, NeoProfile, NeoSnapshot
from cbus_toolkit.offline_workflows.neo_editor_input import evaluate
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


EXAMPLE = Path(__file__).resolve().parents[2] / "src/cbus_toolkit/offline_workflows/examples/neo-editor.json"


def supplied():
    return json.loads(EXAMPLE.read_text())


def with_opaque(value, placement):
    document = supplied()
    if placement == "top":
        opaque = value
    elif placement == "mapping":
        opaque = {"kept": "sentinel", "branch": {"value": value}}
    else:
        opaque = {"kept": "sentinel", "branch": [{"value": value}]}
    document["snapshot"]["values"]["ReviewOpaquePP"] = opaque
    document["operations"] = document["operations"][:3]
    document["operations"][2]["current"] = {"snapshot": deepcopy(document["snapshot"])}
    return document


def drift_current(document, value, placement):
    values = document["operations"][2]["current"]["snapshot"]["values"]
    if placement == "top":
        values["ReviewOpaquePP"] = value
    elif placement == "mapping":
        values["ReviewOpaquePP"]["branch"]["value"] = value
    else:
        values["ReviewOpaquePP"]["branch"][0]["value"] = value


@pytest.mark.parametrize("before,after", [(True, 1), (False, 0), (1, True), (0, False)])
@pytest.mark.parametrize("placement", ["top", "mapping", "array"])
def test_complete_current_rejects_boolean_integer_type_drift_and_retains_pending_state(before, after, placement):
    document = with_opaque(before, placement)
    drift_current(document, after, placement)
    original_json = json.dumps(document, sort_keys=True)
    result = evaluate(document, "plan")
    assert result["outcome"] == "refused" and not result["validation_passed"]
    assert result["operations_executed"] == 2 and result["errors"][0]["operation_index"] == 3
    assert "baseline" in result["errors"][0]["message"]
    state = result["final_state"]
    assert state["is_open"] and state["dirty"] and state["destination_action"] == "apply"
    assert state["local_apply_count"] == 0 and state["applied_revision"] == 0
    assert state["working"]["memory"]["bytes"]["104"] == 0xB0
    assert state["applied"]["memory"]["bytes"]["104"] == 0
    assert state["working"]["graph_hex"] == document["snapshot"]["graph_hex"]
    assert json.dumps(state["working"]["values"]["ReviewOpaquePP"], sort_keys=True) == (
        json.dumps(document["snapshot"]["values"]["ReviewOpaquePP"], sort_keys=True))
    assert state["pp_save_count"] == state["project_save_count"] == 0
    assert result["saved"] is False and result["io_performed"] is False
    assert json.dumps(document, sort_keys=True) == original_json


@pytest.mark.parametrize("value", [True, False, 1, 0])
def test_complete_current_equal_typed_control_still_accepts_one_local_proposal(value):
    result = evaluate(with_opaque(value, "array"), "plan")
    assert result["validation_passed"] and result["outcome"] == "prepared"
    state = result["final_state"]
    assert state["local_apply_count"] == 1 and not state["dirty"] and state["is_open"]
    assert state["applied"] == state["working"]
    assert result["saved"] is False and result["external_persistence_verified"] is False


@pytest.mark.parametrize("before,after", [(True, 1), (False, 0)])
def test_public_complete_current_type_drift_is_status_three(before, after, capsys, tmp_path):
    document = with_opaque(before, "array")
    drift_current(document, after, "array")
    raw = json.dumps(document).encode("utf-8")
    source = tmp_path.resolve() / "neo-typed-current.json"
    source.write_bytes(raw)
    status = main(["offline-workflows", "neo-editor", "plan", "--input", str(source), "--compact"])
    output = capsys.readouterr()
    assert status == 3 and not output.err
    envelope = json.loads(output.out)
    assert envelope["execution_enabled"] is False
    assert envelope["report"]["outcome"] == "refused"
    assert envelope["report"]["final_state"]["local_apply_count"] == 0
    assert envelope["report"]["final_state"]["destination_action"] == "apply"
    assert source.read_bytes() == raw


def snapshot(values):
    return NeoSnapshot(values, MemoryImage({104: 0, 255: 165}), b"<Project/>", ((56, 1), (56, 2)))


def test_snapshot_equality_preserves_type_order_and_unknown_memory_boundaries():
    original = snapshot({"opaque": {"flag": True, "items": [0, False, {"kept": None}]}})
    canonical_equal = snapshot({"opaque": {"items": (0, False, {"kept": None}), "flag": True}})
    assert original == canonical_equal
    assert original.__eq__({}) is NotImplemented
    with pytest.raises(TypeError):
        hash(original)
    for drifted in (
        snapshot({"opaque": {"flag": 1, "items": [0, False, {"kept": None}]}}),
        snapshot({"opaque": {"flag": True, "items": [False, False, {"kept": None}]}}),
        replace(original, memory=MemoryImage({104: 0})),
        replace(original, memory=MemoryImage({104: 0, 255: 0})),
        replace(original, graph_bytes=b"<Project/> "),
        replace(original, existing_groups=((56, 2), (56, 1))),
    ):
        assert original != drifted


def open_editor():
    document = supplied()
    row = document["spec"]
    parameters = {item["name"]: ParameterSpec(item["name"], item["type"], item["source"],
                                             item["fields"], tuple(item["tags"]))
                  for item in row["parameters"]}
    spec = UnitSpec(row["filename"], row["metadata"], tuple(row["sources"]), parameters)
    source = document["snapshot"]
    opening = NeoSnapshot(source["values"], MemoryImage({int(k): v for k, v in source["memory"]["bytes"].items()}),
                          bytes.fromhex(source["graph_hex"]), tuple(tuple(group) for group in source["existing_groups"]))
    return NeoEditor.open(spec, NeoProfile(**document["profile"]), opening)


def test_dirty_and_change_report_distinguish_typed_drift_and_added_null_fact():
    editor = open_editor()
    values = dict(editor.working.values)
    values["OpaqueExtraPP"] = {"text": "unchanged", "array": [1, {"flag": 1}]}
    values["NewOpaquePP"] = None
    dirty = replace(editor, working=replace(editor.working, values=values))
    assert dirty.dirty and not editor.dirty
    changes = dirty.as_dict()["changes_from_applied"]
    assert changes["OpaqueExtraPP"]["array"][1]["flag"] == 1
    assert type(changes["OpaqueExtraPP"]["array"][1]["flag"]) is int
    assert "NewOpaquePP" in changes and changes["NewOpaquePP"] is None
    assert editor.working.values["OpaqueExtraPP"]["array"][1]["flag"] is True


@pytest.mark.parametrize("case", ["alias", "invalid_layout", "invalid_value"])
def test_extra_declared_parameters_refuse_before_opening_or_any_edit(case):
    document = supplied()
    jp = deepcopy(next(row for row in document["spec"]["parameters"] if row["name"] == "JPCommand"))
    name = "AliasJP" if case == "alias" else "ExtraDeclaredPP"
    jp["name"] = jp["fields"]["Name"] = name
    if case == "invalid_layout":
        jp["fields"]["Address"] = "invalid address"
    document["spec"]["parameters"].append(jp)
    document["snapshot"]["values"][name] = (
        "invalid numeric value" if case == "invalid_value" else document["snapshot"]["values"]["JPCommand"])
    document["operations"] = document["operations"][:1]
    result = evaluate(document, "plan")
    assert result["outcome"] == "unsupported" and not result["validation_passed"]
    assert "declared parameters" in result["errors"][0]["message"]
    assert result["final_state"] is None and result["operations_executed"] == 0
    assert result["saved"] is False and result["io_performed"] is False


def test_undeclared_opaque_pp_is_preserved_through_apply_edit_cancel():
    document = supplied()
    opaque = {"top_true": True, "top_one": 1, "nested": [{"false": False, "zero": 0, "null": None}]}
    document["snapshot"]["values"]["UnmappedCallerPP"] = opaque
    result = evaluate(document, "plan")
    assert result["validation_passed"] and result["outcome"] == "cancelled"
    for phase in ("opening", "applied", "working"):
        retained = result["final_state"][phase]["values"]["UnmappedCallerPP"]
        assert json.dumps(retained, sort_keys=True) == json.dumps(opaque, sort_keys=True)
    assert result["final_state"]["local_apply_count"] == 1
    assert result["saved"] is False
