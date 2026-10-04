"""Independent adversarial histories for the explicitly offline workflow bound."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from cbus_toolkit.memory import MemoryCodec, MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


GRAPH = b'<Project OID="project-original"><!--opaque--><Network Address="254"/></Project>'


def _neo_fixture():
    # Literal public synthetic KEYM4 layout; these are independent baseline facts.
    rows = (
        ("JPCommand", 104, 8, 4, 4, 1, [0, 7, 0, 0, 0, 0, 0, 0]),
        ("SRCommand", 104, 8, 4, 0, 1, [0, 1, 0, 0, 0, 0, 0, 0]),
        ("LPCommand", 105, 8, 4, 4, 1, [0, 3, 0, 0, 0, 0, 0, 0]),
        ("LRCommand", 105, 8, 4, 0, 1, [0, 2, 0, 0, 0, 0, 0, 0]),
        ("BlockAllocation", 54, 8, 8, 0, 0, [1, 2, 4, 8, 16, 32, 64, 128]),
        ("GroupAddress", 80, 9, 8, 0, 0, [255, 4, 255, 255, 255, 255, 255, 255, 255]),
        ("Application", 33, 2, 8, 0, 0, [56, 57]),
        ("SecondApplicationBlocks", 69, 1, 8, 0, 0, [0]),
        ("TimerHighByte", 136, 8, 8, 0, 0, [0] * 8),
        ("TimerLowByte", 144, 8, 8, 0, 0, [0] * 8),
        ("TimerExpiryCommand", 72, 8, 4, 0, 0, [15] * 8),
        ("LightLevelStore1", 120, 8, 8, 0, 0, [255] * 8),
        ("LightLevelStore2", 128, 8, 8, 0, 0, [255] * 8),
        ("SceneKeySelector", 96, 8, 1, 7, 0, [0] * 8),
        ("IndicatorBlockAssignment", 96, 8, 3, 0, 0, list(range(8))),
    )
    parameters = {}
    for name, address, count, bits, bit, skip, values in rows:
        fields = {"Name": name, "Type": "int", "Address": str(address), "ArraySize": str(count),
                  "BitSize": str(bits), "BitAddress": str(bit), "ArraySkip": str(skip),
                  "DefaultValue": " ".join(map(str, values))}
        parameters[name] = ParameterSpec(name, "int", "independent-synthetic.xml", fields)
    spec = UnitSpec("KEYM4.xml", {"Type": "KEYM4", "MinVersion": "2.5.00", "MaxVersion": "2.5.00"},
                    ("independent-synthetic.xml",), parameters)
    values = spec.defaults()
    memory = MemoryCodec(spec).encode_many(values).apply(MemoryImage.from_bytes(b"\xa5" * 256))
    values["Opaque"] = {"rows": ["sentinel", {"reference": "original-OID"}]}
    from cbus_toolkit.offline_workflows.neo_editor import NeoEditor, NeoProfile, NeoSnapshot
    snapshot = NeoSnapshot(values, memory, GRAPH, ((56, 1), (56, 2), (56, 4)))
    profile = NeoProfile("/db//WFNEO/254/p/1", "KEYM4", "2.5.00", "5054NL", "", "closed", True)
    return NeoEditor.open(spec, profile, snapshot), spec, values


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def test_apply_a_edit_b_cancel_keeps_only_locally_accepted_a_with_literal_bytes():
    opening, _, _ = _neo_fixture()
    a = opening.edit_preset(key=1, preset="toggle", group=1, block=1, application="primary")
    assert a.working.memory.byte(0x68) == 0xB0
    assert a.working.memory.byte(0x50) == 1
    applied = a.request_apply().confirm_database(current=opening.applied)
    b = applied.edit_preset(key=1, preset="off", group=2, block=1, application="primary")
    assert b.working.memory.byte(0x68) == 0xF0
    assert b.working.memory.byte(0x50) == 2
    final = b.cancel_editor()
    assert final.applied == applied.working == final.working
    assert final.working != opening.working
    assert final.working != b.working
    assert final.opening == opening.opening
    assert final.working.graph_bytes == GRAPH
    assert final.working.memory.byte(0xFE) == 0xA5
    # Paired stage nibble, unrelated physical key and opaque PP stay exact.
    assert final.working.memory.read(0x6A, 2) == opening.working.memory.read(0x6A, 2)
    assert final.working.values["Opaque"] == opening.working.values["Opaque"]
    report = final.as_dict()
    assert report["local_apply_count"] == 1
    assert report["pp_save_count"] == report["project_save_count"] == 0
    assert report["saved"] is report["external_persistence_verified"] is False
    assert report["native_acceptance"] is report["physical_acceptance"] is False


def test_nested_destination_cancel_retains_dirty_b_then_explicit_ok_accepts_once():
    opening, _, _ = _neo_fixture()
    applied = opening.edit_preset(key=1, preset="toggle", group=1).request_apply().confirm_database(current=opening.applied)
    b = applied.edit_preset(key=1, preset="off", group=2)
    nested_cancel = b.request_apply().cancel_destination()
    assert nested_cancel.is_open and nested_cancel.dirty
    assert nested_cancel.working == b.working
    assert nested_cancel.applied == applied.applied
    final = nested_cancel.request_ok().confirm_database(current=applied.applied)
    assert not final.is_open and not final.dirty
    assert final.working.memory.byte(0x68) == 0xF0
    assert final.local_apply_count == 2
    from cbus_toolkit.offline_workflows.neo_editor import NeoEditorError
    with pytest.raises(NeoEditorError):
        final.confirm_database(current=final.applied)
    with pytest.raises(NeoEditorError):
        final.edit_preset(key=1, preset="toggle", group=1)


def test_neo_caller_spec_pp_and_report_mutation_cannot_modify_issued_state():
    opening, spec, caller_values = _neo_fixture()
    before = _json(opening.as_dict())
    caller_values["Opaque"]["rows"][1]["reference"] = "forged"
    caller_values["Opaque"]["rows"].append("added")
    spec.metadata["Type"] = "KEYB2"
    spec.parameters["JPCommand"].fields["Address"] = "5"
    report = opening.as_dict()
    report["working"]["values"]["Opaque"]["rows"][1]["reference"] = "another-forgery"
    report["working"]["memory"]["bytes"].clear()
    assert _json(opening.as_dict()) == before
    edited = opening.edit_preset(key=1, preset="toggle", group=1)
    assert edited.working.memory.byte(0x68) == 0xB0
    assert edited.working.graph_bytes == GRAPH


@pytest.mark.parametrize("choice", ["physical", "both", "unknown"])
def test_neo_unsupported_destination_and_stale_snapshot_do_not_accept(choice):
    opening, _, _ = _neo_fixture()
    pending = opening.edit_preset(key=1, preset="toggle", group=1).request_apply()
    before = _json(pending.as_dict())
    from cbus_toolkit.offline_workflows.neo_editor import NeoEditorError, NeoSnapshot
    with pytest.raises(NeoEditorError):
        pending.confirm_database(current=pending.applied, destination=choice)
    stale = NeoSnapshot(pending.applied.values, pending.applied.memory, GRAPH + b" ", pending.applied.existing_groups)
    with pytest.raises(NeoEditorError):
        pending.confirm_database(current=stale)
    assert _json(pending.as_dict()) == before


def _copy_fixture(*, owner=None, unsupported=False):
    from cbus_toolkit.offline_workflows import copy_paste as cp
    owner = owner or cp.Ownership("fake-endpoint-A", "fake-repository", "project-A")
    caller_bytes = bytearray(GRAPH)
    source = cp.CopySource(owner, "//project-A/254/56/1", "shared-numeric-selector-OID", cp.CopyKind.GROUP, caller_bytes)
    target = cp.CopyTarget(owner, "//project-A/254/56", "parent-OID", cp.CopyKind.APPLICATION)
    copied = cp.copy_intent(source) if unsupported else cp.copy_intent(source, profile=cp.draft_child_profile(cp.CopyKind.GROUP))
    request = cp.PasteRequest("2", "Explicit name", source.sha256, False, False)
    return cp, cp.select_target(copied, target), request, caller_bytes


def test_copy_requires_explicit_profile_and_exact_owner_despite_colliding_selectors():
    cp, intent, request, _ = _copy_fixture(unsupported=True)
    refused = cp.attempt_paste(intent, request)
    assert refused.refusal.code == "unsupported_profile"
    cp, intent, request, _ = _copy_fixture()
    foreign = cp.CopyTarget(cp.Ownership("fake-endpoint-B", "fake-repository", "project-B"),
                            intent.target.selector, intent.target.oid, intent.target.kind)
    refused = cp.attempt_paste(cp.select_target(intent, foreign), request)
    assert refused.refusal.code == "different_owner"
    assert refused.report()["commands"] == []
    assert refused.report()["saved"] is False


def test_copy_source_bytes_and_diagnostics_are_defensive_and_uncertainty_never_replays():
    cp, intent, request, caller_bytes = _copy_fixture()
    before = _json(intent.report())
    caller_bytes[:] = b"tampered graph"
    report = intent.report()
    report["source"]["owner"]["project"] = "forged"
    report["history"].clear()
    assert _json(intent.report()) == before
    assert intent.source.snapshot == GRAPH
    prepared = cp.attempt_paste(intent, request)
    assert prepared.phase is cp.CopyPhase.ACCEPTED
    uncertain = cp.mark_uncertain(prepared, "Caller reports an unresolved observation")
    with pytest.raises(cp.CopyPasteError):
        cp.attempt_paste(uncertain, request)
    with pytest.raises(cp.CopyPasteError):
        cp.cancel_intent(uncertain)
    assert cp.persistence_gate(uncertain, cp.CopyPhase.SAVED).code == "uncertain_outcome"
    assert uncertain.report()["execution_enabled"] is False
    assert uncertain.report()["native_compatibility"] is False


@pytest.mark.parametrize("address_conflict,name_conflict", [(None, False), (False, None), (True, False), (False, True)])
def test_copy_unknown_or_independent_collisions_refuse(address_conflict, name_conflict):
    cp, intent, request, _ = _copy_fixture()
    refusal = cp.attempt_paste(intent, replace(request, address_conflict=address_conflict, name_conflict=name_conflict))
    assert refusal.phase is cp.CopyPhase.REFUSED
    assert refusal.report()["external_mutation_attempted"] is False
    assert refusal.source.snapshot == GRAPH


def test_catalogue_group_then_copy_intent_does_not_claim_unit_creation_or_graph_commit():
    from cbus_toolkit.offline_workflows import catalogue_groups as cg
    catalogue = b'''<CBusUnits><Units><Unit><CatalogNumber>5054NL</CatalogNumber>
      <UnitTitle>Family=Wired;Category=Input;HideInCatalog=false</UnitTitle><IsAddressable>true</IsAddressable>
      <FirmwareRevisions><Revision><UnitType>KEYM4</UnitType><MinVersion>2.5.00</MinVersion>
      <MaxVersion>2.5.00</MaxVersion><IsDefault>true</IsDefault><UnitSpecName>KEYM4.xml</UnitSpecName>
      </Revision></FirmwareRevisions></Unit></Units></CBusUnits>'''
    index = cg.CatalogueIndex.from_bytes(catalogue)
    selection = index.select_default(index.units[0].unit_id, profile=cg.CATALOGUE_PROFILE)
    assert selection.firmware == "2.5.00"
    assert selection.as_dict()["creation_admitted"] is False
    assert selection.as_dict()["default_pp_admitted"] is False
    policy = cg.GroupPolicy(tuple(range(256)), 256, "reject-exact")
    draft = cg.GroupDraft().add(cg.GroupRow("one", 1, "One")).add(cg.GroupRow("two", 2, "Two"))
    edited = draft.edit("two", address=3, tag_name="Three")
    validated = cg.validate_group_draft(edited, existing_groups=(), policy=policy,
        target_identity="//project-A/254/56", baseline_sha256="a" * 64)
    assert validated.valid
    assert validated.as_dict()["replacement_graph_admitted"] is False
    assert [row.address for row in validated.rows] == [1, 3]
    cp, copy, request, _ = _copy_fixture()
    prepared = cp.attempt_paste(copy, request)
    assert prepared.report()["execution_enabled"] is False
    assert prepared.source.snapshot == GRAPH
    assert index.snapshot == catalogue
    assert draft.rows[1].address == 2
    assert edited.cancel().rows == ()
    assert _json(validated.as_dict()) == _json(cg.validate_group_draft(edited,
        existing_groups=(), policy=policy, target_identity="//project-A/254/56", baseline_sha256="a" * 64).as_dict())


def test_group_invalid_middle_and_last_rows_refuse_entire_draft_without_prefix():
    from cbus_toolkit.offline_workflows import catalogue_groups as cg
    draft = cg.GroupDraft((cg.GroupRow("valid-first", 1, "One"),
                           cg.GroupRow("invalid-middle", "01", "Two"),
                           cg.GroupRow("collision-last", 3, "Three")))
    result = cg.validate_group_draft(draft, existing_groups=(cg.GroupRow("baseline", 3, "Old"),),
        policy=cg.GroupPolicy(tuple(range(256)), 256, "reject-exact"),
        target_identity="//synthetic/254/56", baseline_sha256="a" * 64)
    assert not result.valid
    assert result.errors == (("invalid-middle", "invalid_address"), ("collision-last", "existing_address_collision"))
    report = result.as_dict()
    assert report["accepted_rows"] == []
    assert len(report["proposed_rows"]) == 3
    report["proposed_rows"][0]["tag_name"] = "tampered"
    assert draft.rows[0].tag_name == "One"
    payload = {"format": cg.GROUP_ROWS_FORMAT, "rows": [
        {"row_id": "valid-first", "address": 1, "tag_name": "One"},
        {"row_id": "boolean-last", "address": True, "tag_name": "Two"}]}
    with pytest.raises(cg.CatalogueGroupsError):
        cg.parse_group_rows(json.dumps(payload).encode())


def _session_select_and_confirm(ds, state, *, project, operation_id):
    state = ds.reduce_session(state, ds.SessionAction("select", project=project,
        object_identity="254/p/1-shared-OID", model_generation=1)).state
    state = ds.reduce_session(state, ds.SessionAction("schedule", operation_id=operation_id,
        operation_kind="project_use")).state
    dispatched = ds.reduce_session(state, ds.SessionAction("dispatch", operation_id=operation_id))
    callback = ds.Callback(dispatched.effects[0].token, ds.Outcome("completed", code=200))
    return ds.reduce_session(dispatched.state, ds.SessionAction("callback", callback=callback)).state


def test_session_stale_callback_and_dirty_neo_snapshot_never_rebind_on_reconnect():
    from cbus_toolkit.offline_workflows import discovery_session as ds
    neo, _, _ = _neo_fixture()
    neo = neo.edit_preset(key=1, preset="off", group=2)
    payload = _json(neo.as_dict()).encode()
    state = ds.new_session(ds.Context("flow", "shell", "fake-endpoint-A"))
    state = _session_select_and_confirm(ds, state, project="A", operation_id="use-A")
    state = ds.reduce_session(state, ds.SessionAction("schedule", operation_id="load-A", operation_kind="load")).state
    dispatched = ds.reduce_session(state, ds.SessionAction("dispatch", operation_id="load-A"))
    old_token = dispatched.effects[0].token
    state = ds.reduce_session(dispatched.state, ds.SessionAction("select", project="B",
        object_identity="254/p/1-shared-OID", model_generation=1)).state
    callback = ds.Callback(old_token, ds.Outcome("completed"))
    late = ds.reduce_session(state, ds.SessionAction("callback", callback=callback))
    assert late.effects == ()
    assert late.state.context.project == "B"
    assert late.state.project_confirmed is None
    assert not late.state.journal[-1].presented
    assert late.state.journal[-1].reason == "selection_generation_mismatch"
    assert late.state.operations[-1].token.context.project == "A"
    state = _session_select_and_confirm(ds, late.state, project="B", operation_id="use-B")
    state = ds.reduce_session(state, ds.SessionAction("schedule", operation_id="pending-B", operation_kind="group_refresh")).state
    editor = ds.EditorSnapshot(state.context, payload)
    state = ds.reduce_session(state, ds.SessionAction("dirty_editor", editor=editor)).state
    disconnected = ds.reduce_session(state, ds.SessionAction("disconnect"))
    assert disconnected.effects == ()
    assert disconnected.state.detached_editors == (editor,)
    assert disconnected.state.detached_editors[0].payload == payload
    assert disconnected.state.operations[-1].phase == "cancelled_before_dispatch"
    reconnected = ds.reduce_session(disconnected.state, ds.SessionAction("reconnect", endpoint="fake-endpoint-A")).state
    assert reconnected.context.connection_generation > state.context.connection_generation
    reconnected = ds.reduce_session(reconnected, ds.SessionAction("select", project="B",
        object_identity="254/p/1-shared-OID", model_generation=1)).state
    reconnected = ds.reduce_session(reconnected, ds.SessionAction("schedule", operation_id="new-load", operation_kind="load")).state
    with pytest.raises(ds.UnsupportedContract):
        ds.reduce_session(reconnected, ds.SessionAction("dispatch", operation_id="new-load"))
    closed = ds.reduce_session(reconnected, ds.SessionAction("close")).state
    repeated = ds.reduce_session(closed, ds.SessionAction("close")).state
    assert repeated == closed
    final = ds.reduce_session(closed, ds.SessionAction("callback", callback=callback)).state
    assert final.closed and not final.connected
    assert not final.journal[-1].presented
    assert final.detached_editors[0].payload == payload
    assert final.io_performed is final.hardware_executed is final.native_manual_executed is False


def test_discovery_cancel_pause_and_open_unknowns_keep_distinct_surface_histories():
    from cbus_toolkit.offline_workflows import discovery_session as ds
    context = ds.Context("flow", "form", "fake-endpoint-A")
    rows = (ds.RowSpec("first", "fake-endpoint-A"), ds.RowSpec("second", "fake-endpoint-B"),
            ds.RowSpec("third", "fake-endpoint-C"))
    scan = ds.new_discovery(context, ds.Surface.COM_SCAN, rows)
    active = ds.reduce_discovery(scan, ds.DiscoveryAction("dispatch", ("first",)))
    cancelled = ds.reduce_discovery(active.state, ds.DiscoveryAction("com_cancel")).state
    late = ds.reduce_discovery(cancelled, ds.DiscoveryAction("callback",
        callback=ds.Callback(active.effects[0].token, ds.Outcome("present"))))
    assert late.effects == ()
    assert late.state.rows[0].phase == "interrupted"
    assert late.state.rows[1].phase == "cancelled_before_dispatch"
    assert not late.state.journal[-1].presented
    assert late.state.journal[-1].reason == "cancelled_result"
    cni = ds.new_discovery(context, ds.Surface.CNI_SCAN, rows)
    active_cni = ds.reduce_discovery(cni, ds.DiscoveryAction("dispatch", ("first",)))
    paused = ds.reduce_discovery(active_cni.state, ds.DiscoveryAction("cni_pause")).state
    assert paused.active_at_pause == (active_cni.effects[0].token,)
    for wrong_action in ("resume", "com_cancel", "scan_cancel"):
        with pytest.raises(ds.UnsupportedContract):
            ds.reduce_discovery(paused, ds.DiscoveryAction(wrong_action))
    assert ds.cni_outcome(collection_complete=True, devices=0, hidden_ignored=0, malformed=0).kind == "no_reply_by_deadline"
    assert paused.absence_proven is False
    opening_rows = tuple(ds.RowSpec(row.row_id, row.endpoint, "P", "254/" + row.row_id) for row in rows)
    opening = ds.new_open_networks(context, opening_rows)
    first = ds.reduce_open_networks(opening, ds.DiscoveryAction("dispatch", ("first",)))
    accepted = ds.reduce_open_networks(first.state, ds.DiscoveryAction("callback",
        callback=ds.Callback(first.effects[0].token, ds.Outcome("accepted")))).state
    assert accepted.rows[0].phase == "accepted"
    with pytest.raises(ds.UnsupportedContract):
        ds.reduce_open_networks(accepted, ds.DiscoveryAction("callback",
            callback=ds.Callback(first.effects[0].token, ds.Outcome("independently_ready"))))
    second = ds.reduce_open_networks(accepted, ds.DiscoveryAction("dispatch", ("second",)))
    stopped = ds.reduce_open_networks(second.state, ds.DiscoveryAction("stop"))
    assert stopped.effects == ()
    assert stopped.state.rows[0].phase == "accepted"
    assert stopped.state.rows[1].phase == "unknown_after_dispatch"
    assert stopped.state.rows[2].phase == "cancelled_before_dispatch"
    with pytest.raises(ds.UnsupportedContract):
        ds.reduce_open_networks(stopped.state, ds.DiscoveryAction("retry", ("second",)))
    closed = ds.reduce_open_networks(stopped.state, ds.DiscoveryAction("close"))
    assert closed.effects == ()
    assert closed.state.rows[0].phase == "accepted"


def test_transfer_direction_advanced_and_quick_are_frozen_without_execution_links():
    from cbus_toolkit.offline_workflows import transfer_restore as tr
    routes = ["bridge-A", "bridge-B"]
    row = tr.TransferRow("one", "source-one", "a" * 64, "destination-one", "b" * 64,
        "c" * 64, source_address="1", serial="synthetic-serial", unit_type="KEYM4",
        firmware="2.5.00", route=routes, destination_state="present")
    routes.append("caller-tamper")
    history = [tr.AdvancedTransferEvent("choose-action", ("one",), "programming-only"),
               tr.AdvancedTransferEvent("clear-actions", ("one",)),
               tr.AdvancedTransferEvent("choose-action", ("one",), "add-and-transfer"),
               tr.AdvancedTransferEvent("accept")]
    advanced = tr.prepare_advanced_transfer([row], history)
    frozen = advanced.as_dict()
    assert frozen["intent_frozen"] is True
    assert frozen["execution_admitted"] is False
    assert frozen["bindings"]["rows"][0]["route"] == ["bridge-A", "bridge-B"]
    assert frozen["bindings"]["rows"][0]["staged_data_sha256"] == "c" * 64
    assert frozen["direction_binding"] is None
    history.clear()
    frozen["bindings"]["rows"][0]["route"].clear()
    assert advanced.as_dict()["bindings"]["rows"][0]["route"] == ["bridge-A", "bridge-B"]
    assert tr.AdvancedTransferPlan.from_dict(advanced.as_dict()).as_dict() == advanced.as_dict()
    forged = advanced.as_dict()
    forged["execution_admitted"] = True
    with pytest.raises(ValueError):
        tr.AdvancedTransferPlan.from_dict(forged)
    direction = tr.prepare_transfer_direction("rdbNetwork", decision="accept").as_dict()
    assert direction["direction"] is None
    assert direction["advanced_invocation_link_verified"] is False
    quick = tr.record_quick_transfer(("one", "two"), (
        tr.QuickTransferEvent("progress", "one", 50), tr.QuickTransferEvent("completed", "one", 100),
        tr.QuickTransferEvent("pause"), tr.QuickTransferEvent("resume"), tr.QuickTransferEvent("failed", "two"),
        tr.QuickTransferEvent("close")), attempt_id="attempt-1").as_dict()
    assert [row["status"] for row in quick["observations"]] == ["completed", "failed"]
    assert quick["queue_commands"] == []
    assert quick["advanced_invocation_link_verified"] is False
    with pytest.raises(ValueError):
        tr.prepare_advanced_transfer((row,), (tr.QuickTransferEvent("pause"),))
    with pytest.raises(ValueError):
        tr.record_quick_transfer(("one",), (tr.AdvancedTransferEvent("accept"),), attempt_id="attempt-2")


def _restore_fixture(tr):
    return (tr.RestoreProject("one", "archive/one.xml", "ONE", "a" * 64),
            tr.RestoreProject("two", "archive/two.xml", "TWO", "b" * 64),
            tr.RestoreProject("unused", "archive/unused.xml", "UNUSED", "c" * 64, selected=False))


def test_restore_explicit_names_results_and_recovery_never_imply_replace_execution():
    from cbus_toolkit.offline_workflows import transfer_restore as tr
    projects = _restore_fixture(tr)
    events = (tr.RestoreEvent("choose-policy", policy="rename"),
              tr.RestoreEvent("propose-name", ("one",), proposed_name="RENAMED"),
              tr.RestoreEvent("choose-policy", policy="replace"),
              tr.RestoreEvent("choose-policy", policy="rename"), tr.RestoreEvent("accept"))
    plan = tr.prepare_restore(projects, archive_sha256="d" * 64, destination_snapshot_sha256="e" * 64,
                              destination_names=("ONE",), history=events)
    report = plan.as_dict()
    assert report["intent_frozen"] is True
    assert [row["row_id"] for row in report["decisions"]] == ["one", "two"]
    assert report["decisions"][0]["destination_name"] == "RENAMED"
    assert report["automatic_rename_rule"] is report["replace_primitive"] is report["batch_atomicity"] is None
    assert report["execution_admitted"] is False
    results = tr.record_restore_results(projects, (tr.RestoreResult("one", "completed"),
        tr.RestoreResult("two", "failed", "supplied failure")), attempt_id="attempt-1",
        decision_sha256=report["report_sha256"])
    observed = results.as_dict()
    assert [row["status"] for row in observed["observations"]] == ["completed", "failed", "not-attempted"]
    assert observed["native_execution_verified"] is observed["rollback_verified"] is False
    assert observed["queue_commands"] == []
    with pytest.raises(ValueError):
        tr.record_restore_results(projects, (tr.RestoreResult("unused", "completed"),), attempt_id="bad")
    recovery = tr.record_restore_results(projects, (), attempt_id="attempt-2",
        previous_attempt_sha256=observed["report_sha256"]).as_dict()
    assert recovery["recovery_is_separate_attempt"] is True
    assert results.as_dict() == observed
    forged = report.copy()
    forged["replace_primitive"] = "DELETE then RESTORE"
    with pytest.raises(ValueError):
        tr.RestoreDecisionPlan.from_dict(forged)


@pytest.mark.parametrize("proposed_name", [None, "TWO", "ONE"])
def test_restore_unresolved_or_duplicate_destinations_cannot_freeze_acceptance(proposed_name):
    from cbus_toolkit.offline_workflows import transfer_restore as tr
    projects = _restore_fixture(tr)
    events = [tr.RestoreEvent("choose-policy", policy="rename")]
    if proposed_name is not None:
        events.append(tr.RestoreEvent("propose-name", ("one",), proposed_name=proposed_name))
    events.append(tr.RestoreEvent("accept"))
    plan = tr.prepare_restore(projects, archive_sha256="d" * 64, destination_snapshot_sha256="e" * 64,
        destination_names=("ONE",), history=events).as_dict()
    assert plan["intent_frozen"] is False
    assert plan["outcome"] == "uncertain"
    assert plan["execution_admitted"] is False


def test_accepted_open_conflicting_receipt_is_suppressed_and_ready_is_independent():
    from cbus_toolkit.offline_workflows import discovery_session as ds
    context = ds.Context("flow", "form", "fake-endpoint")
    state = ds.new_open_networks(context, (ds.RowSpec("one", "fake-endpoint", "P", "254"),))
    active = ds.reduce_open_networks(state, ds.DiscoveryAction("dispatch", ("one",)))
    token = active.effects[0].token
    accepted = ds.reduce_open_networks(active.state, ds.DiscoveryAction("callback",
        callback=ds.Callback(token, ds.Outcome("accepted")))).state
    contradicted = ds.reduce_open_networks(accepted, ds.DiscoveryAction("callback",
        callback=ds.Callback(token, ds.Outcome("refused")))).state
    assert contradicted.rows[0].phase == "accepted"
    assert contradicted.rows[0].terminal.kind == "accepted"
    assert not contradicted.journal[-1].presented
    assert contradicted.journal[-1].reason == "conflicting_terminal"
    ready_callback = ds.Callback(token, ds.Outcome("independently_ready", independent=True))
    ready = ds.reduce_open_networks(contradicted, ds.DiscoveryAction("callback", callback=ready_callback)).state
    assert ready.rows[0].phase == "independently_ready"
    duplicated = ds.reduce_open_networks(ready, ds.DiscoveryAction("callback", callback=ready_callback)).state
    assert duplicated.rows[0] == ready.rows[0]
    assert not duplicated.journal[-1].presented
    assert duplicated.io_performed is duplicated.native_manual_executed is duplicated.hardware_executed is False


@pytest.mark.parametrize("state_kind", ["scan", "session"])
@pytest.mark.parametrize("flag", ["native_manual_executed", "hardware_executed", "io_performed"])
def test_discovery_direct_dataclass_replacement_cannot_forge_execution_authority(state_kind, flag):
    from cbus_toolkit.offline_workflows import discovery_session as ds
    context = ds.Context("flow", "form", "fake-endpoint")
    state = (ds.new_discovery(context, ds.Surface.COM_SCAN, (ds.RowSpec("one", "fake-endpoint"),))
             if state_kind == "scan" else ds.new_session(context))
    with pytest.raises(ValueError):
        replace(state, **{flag: True})
    with pytest.raises(ValueError):
        replace(state, preparation_only=False)
    with pytest.raises(ValueError):
        replace(state, journal=[])
    if state_kind == "scan":
        with pytest.raises(ValueError):
            replace(state, rows=list(state.rows))
        with pytest.raises(ValueError):
            replace(state.rows[0], tokens=[])
    else:
        with pytest.raises(ValueError):
            replace(state, detached_editors=[])
        with pytest.raises(ValueError):
            replace(state, operations=[])


@pytest.mark.parametrize("generation", ["connection_generation", "selection_generation", "model_generation", "form_generation"])
def test_boolean_generation_never_collides_with_integer_callback_identity(generation):
    from cbus_toolkit.offline_workflows import discovery_session as ds
    with pytest.raises(ValueError):
        ds.Context("flow", "form", "fake-endpoint", **{generation: True})


def test_explicit_surface_and_unknown_native_profile_refuse_before_symbolic_dispatch():
    from cbus_toolkit.offline_workflows import discovery_session as ds
    context = ds.Context("flow", "form", "fake-endpoint")
    rows = (ds.RowSpec("one", "fake-endpoint"),)
    with pytest.raises(ValueError):
        ds.new_discovery(context, ds.Surface.COM_SCAN.value, rows)
    with pytest.raises(ds.UnsupportedContract):
        ds.new_discovery(context, ds.Surface.COM_SCAN, rows, profile="original-native-profile")


def test_public_demo_keeps_all_workflow_and_persistence_authority_explicitly_false():
    from cbus_toolkit.offline_workflows.demo import run_demo
    result = run_demo("all")
    assert result["format"] == "cbus-offline-workflows-demo-v1"
    assert result["expectation_origin"] == "proposed-offline-policy"
    assert result["preparation_only"] is True
    for flag in ("execution_enabled", "original_compatibility_verified", "native_acceptance",
                 "hardware_acceptance", "external_persistence_verified"):
        assert result[flag] is False
    assert set(result["scenarios"]) == {"copy-paste", "neo-editor", "catalogue-groups", "discovery-session", "transfer-restore"}
    for scenario in result["scenarios"]:
        separate = run_demo(scenario)
        assert separate["scenarios"][scenario] == result["scenarios"][scenario]
        assert set(separate["scenarios"]) == {scenario}


def test_current_connection_failure_invalidates_after_focus_change_but_old_failure_cannot_close_reconnect():
    from cbus_toolkit.offline_workflows import discovery_session as ds
    state = _session_select_and_confirm(ds, ds.new_session(ds.Context("flow", "form", "fake-endpoint")),
                                       project="A", operation_id="use-A")
    state = ds.reduce_session(state, ds.SessionAction("schedule", operation_id="load-A", operation_kind="load")).state
    dispatched = ds.reduce_session(state, ds.SessionAction("dispatch", operation_id="load-A"))
    state = ds.reduce_session(dispatched.state, ds.SessionAction("select", project="B",
        object_identity="254/p/1-shared-OID", model_generation=1)).state
    failure = ds.Callback(dispatched.effects[0].token, ds.Outcome("transport_error"))
    disconnected = ds.reduce_session(state, ds.SessionAction("callback", callback=failure)).state
    assert not disconnected.connected
    assert disconnected.project_confirmed is None
    assert not disconnected.journal[-1].presented
    reconnected = ds.reduce_session(disconnected, ds.SessionAction("reconnect", endpoint="fake-endpoint")).state
    reconnected = _session_select_and_confirm(ds, reconnected, project="B", operation_id="use-B")
    late = ds.reduce_session(reconnected, ds.SessionAction("callback", callback=failure)).state
    assert late.connected
    assert late.project_confirmed == "B"
    assert late.context == reconnected.context
    assert not late.journal[-1].presented


def test_journal_exhaustion_cannot_complete_unretained_work_or_schedule_more():
    from cbus_toolkit.offline_workflows import discovery_session as ds
    state = _session_select_and_confirm(ds,
        ds.new_session(ds.Context("flow", "form", "fake-endpoint"), journal_limit=1),
        project="A", operation_id="use-A")
    assert len(state.journal) == 1
    state = ds.reduce_session(state, ds.SessionAction("schedule", operation_id="load-A", operation_kind="load")).state
    dispatched = ds.reduce_session(state, ds.SessionAction("dispatch", operation_id="load-A"))
    overflow = ds.reduce_session(dispatched.state, ds.SessionAction("callback",
        callback=ds.Callback(dispatched.effects[0].token, ds.Outcome("completed")))).state
    assert overflow.evidence_incomplete
    assert overflow.dropped_callbacks == 1
    assert len(overflow.journal) == 1
    assert overflow.operations[-1].phase == "dispatched"
    assert overflow.operations[-1].terminal is None
    with pytest.raises(ds.UnsupportedContract):
        ds.reduce_session(overflow, ds.SessionAction("schedule", operation_id="more", operation_kind="load"))


def test_copy_direct_accepted_constructor_cannot_bypass_contract_admission():
    cp, selected, request, _ = _copy_fixture()
    accepted = cp.attempt_paste(selected, request)
    with pytest.raises(cp.CopyPasteError):
        replace(accepted, profile=cp.UNSUPPORTED_TOOLKIT_PROFILE)
    with pytest.raises(cp.CopyPasteError):
        replace(accepted, request=replace(request, source_sha256="f" * 64))
    with pytest.raises(cp.CopyPasteError):
        replace(accepted, phase=cp.CopyPhase.SAVED, history=accepted.history + (cp.CopyPhase.SAVED,))


def test_transfer_raw_report_constructor_cannot_bypass_recomputed_authority():
    from cbus_toolkit.offline_workflows import transfer_restore as tr
    source = tr.prepare_advanced_transfer((tr.TransferRow("one", "source", "a" * 64),))
    forged = source.as_dict()
    forged["execution_admitted"] = True
    forged["native_mutations"] = 1
    with pytest.raises(TypeError):
        tr.AdvancedTransferPlan(json.dumps(forged))
    with pytest.raises(ValueError):
        tr.AdvancedTransferPlan.from_dict(forged)
