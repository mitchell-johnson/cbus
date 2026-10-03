"""Standalone synthetic offline examples; only main prints returned JSON.

run_demo is pure. Its locally accepted proposals and supplied observations
never admit execution, establish persistence, or close original capture gates.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json

SCENARIOS = ("copy-paste", "neo-editor", "catalogue-groups", "discovery-session", "transfer-restore")


def _demo_copy_paste():
    from .copy_paste import (CopyKind, CopySource, CopyTarget, Ownership, PasteRequest,
                            attempt_paste, copy_intent, draft_child_profile, select_target)
    owner = Ownership("offline:synthetic", "synthetic-repository", "OFFLINE")
    raw = b'<!--retained--><Group OID="source-group"><TagName>DeskLamp</TagName><Opaque keep="true"/></Group>'
    source = CopySource(owner, "//OFFLINE/254/56/1", "source-group", CopyKind.GROUP, raw)
    target = CopyTarget(owner, "//OFFLINE/254/56", "lighting-application", CopyKind.APPLICATION)
    request = PasteRequest("2", "SecondLamp", source.sha256, False, False)
    default = attempt_paste(select_target(copy_intent(source), target), request)
    proposed = attempt_paste(select_target(copy_intent(source, profile=draft_child_profile(CopyKind.GROUP)), target), request)
    collision = attempt_paste(select_target(copy_intent(source, profile=draft_child_profile(CopyKind.GROUP)), target),
                              PasteRequest("1", "DeskLamp", source.sha256, True, True))
    return {"default_original_contract": default.report(), "explicit_offline_draft": proposed.report(),
            "collision": collision.report(), "source_bytes_preserved": proposed.source.snapshot == raw}


def _synthetic_neo():
    from ..extended_macros import ExtendedKeys, LAYOUTS
    from ..memory import MemoryImage
    from ..unitspec import ParameterSpec, UnitSpec
    from .neo_editor import NeoEditor, NeoProfile, NeoSnapshot
    defaults = {
        "JPCommand": [0] * 8, "SRCommand": [0] * 8, "LPCommand": [0] * 8, "LRCommand": [0] * 8,
        "BlockAllocation": [1, 2, 4, 8, 16, 32, 64, 128], "GroupAddress": [255] * 9,
        "Application": [56, 57], "SecondApplicationBlocks": [0], "TimerHighByte": [0] * 8,
        "TimerLowByte": [0] * 8, "TimerExpiryCommand": [15] * 8,
        "LightLevelStore1": [255] * 8, "LightLevelStore2": [255] * 8,
        "SceneKeySelector": [0] * 8, "IndicatorBlockAssignment": list(range(8)),
    }
    parameters = {}
    for name, (address, count, bits, bit, skip) in LAYOUTS.items():
        fields = {"Name": name, "Type": "int", "Address": str(address), "ArraySize": str(count),
                  "BitSize": str(bits), "BitAddress": str(bit), "ArraySkip": str(skip),
                  "DefaultValue": " ".join(map(str, defaults[name]))}
        parameters[name] = ParameterSpec(name, "int", "synthetic-in-memory.xml", fields)
    spec = UnitSpec("KEYM4.xml", {"Type": "KEYM4", "MinVersion": "2.5.00", "MaxVersion": "2.5.00"},
                    ("synthetic-in-memory.xml",), parameters)
    values = spec.defaults()
    values["OpaquePP"] = {"preserve": ["opaque", 42]}
    memory = ExtendedKeys(spec).codec.encode_many(spec.defaults()).apply(MemoryImage.from_bytes(b"\xa5" * 256))
    # Explicit fixture validity: these unrelated omitted bytes stay unknown.
    memory = MemoryImage({address: value for address, value in memory.data.items() if address not in (0, 255)})
    graph = b'<!--synthetic--><Project OID="project"><Network Address="254"><Application Address="56"><Group Address="1"/><Group Address="2"/></Application><Unit Address="1" OID="neo"/></Network></Project>'
    snapshot = NeoSnapshot(values, memory, graph, ((56, 1), (56, 2)))
    profile = NeoProfile("/db//OFFLINE/254/p/1", "KEYM4", "2.5.00", "5054NL", "", "closed", True)
    return NeoEditor.open(spec, profile, snapshot)


def _neo_summary(editor):
    report = editor.as_dict()
    return {"is_open": editor.is_open, "dirty": editor.dirty, "destination_action": editor.destination_action,
            "local_apply_count": editor.local_apply_count, "draft_revision": editor.draft_revision,
            "applied_revision": editor.applied_revision,
            "working_key1_stage_byte": f"{editor.working.memory.byte(0x68):02x}",
            "working_group1": editor.working.memory.byte(0x50),
            "applied_key1_stage_byte": f"{editor.applied.memory.byte(0x68):02x}",
            "applied_group1": editor.applied.memory.byte(0x50),
            "known_memory_bytes": len(editor.working.memory.data),
            "graph_sha256": sha256(editor.working.graph_bytes).hexdigest(),
            "history": [event.action for event in editor.history],
            "saved": report["saved"], "pp_save_count": report["pp_save_count"],
            "project_save_count": report["project_save_count"],
            "external_persistence_verified": report["external_persistence_verified"],
            "native_acceptance": report["native_acceptance"], "physical_acceptance": report["physical_acceptance"],
            "original_terminal_semantics": report["original_terminal_semantics"]}


def _demo_neo_editor():
    opening = _synthetic_neo()
    a = opening.edit_preset(key=1, preset="toggle", group=1, block=1, application="primary")
    pending = a.request_apply()
    applied_a = pending.confirm_database(current=opening.applied)
    b = applied_a.edit_preset(key=1, preset="off", group=2, block=1, application="primary")
    cancelled = b.cancel_editor()
    nested = b.request_apply().cancel_destination()
    applied_b = nested.request_apply().confirm_database(current=applied_a.applied)
    return {"expectation_origin": "proposed local policy; existing pure Neo field planner",
            "opening": _neo_summary(opening), "applied_a": _neo_summary(applied_a),
            "dirty_b": _neo_summary(b), "cancel_preserves_a": _neo_summary(cancelled),
            "nested_cancel_retains_b": _neo_summary(nested), "local_accept_b": _neo_summary(applied_b),
            "graph_bytes_preserved": cancelled.working.graph_bytes == opening.opening.graph_bytes,
            "opaque_pp_preserved": cancelled.working.values["OpaquePP"] == opening.opening.values["OpaquePP"],
            "sparse_validity_preserved": set(applied_b.working.memory.data) == set(opening.opening.memory.data)}


def _demo_catalogue_groups():
    from .catalogue_groups import (CATALOGUE_PROFILE, CatalogueGroupsError, CatalogueIndex,
                                  GroupDraft, GroupPolicy, GroupRow, validate_group_draft)
    raw = b'<CBusUnits><Units><Unit><CatalogNumber>5054NL</CatalogNumber><UnitTitle>family=Neo;category=Input</UnitTitle><IsAddressable>true</IsAddressable><HideInCatalog>false</HideInCatalog><FirmwareRevisions><Revision><UnitType>KEYM4</UnitType><MinVersion>2.5.00</MinVersion><MaxVersion>2.5.00</MaxVersion><IsDefault>true</IsDefault><UnitSpecName>KEYM4.xml</UnitSpecName></Revision></FirmwareRevisions></Unit></Units></CBusUnits>'
    index = CatalogueIndex.from_bytes(raw)
    unit = index.units[0]
    selected = index.select_default(unit.unit_id, profile=CATALOGUE_PROFILE)
    missing_raw = raw.replace(b"<IsDefault>true</IsDefault>", b"<IsDefault>false</IsDefault>")
    missing = CatalogueIndex.from_bytes(missing_raw)
    try:
        missing.select_default(missing.units[0].unit_id, profile=CATALOGUE_PROFILE)
    except CatalogueGroupsError as error:
        refusal = error.code
    policy = GroupPolicy(tuple(range(255)), 255, "reject-exact", max_tag_name_chars=64)
    baseline = b'<Application Address="56"><Group Address="1"><TagName>DeskLamp</TagName></Group></Application>'
    options = {"existing_groups": (GroupRow("existing-1", 1, "DeskLamp"),), "policy": policy,
               "target_identity": "offline:synthetic/repository/OFFLINE/254/56",
               "baseline_sha256": sha256(baseline).hexdigest()}
    draft = GroupDraft((GroupRow("row-2", 2, "SecondLamp"), GroupRow("row-3", 3, "ThirdLamp")))
    valid = validate_group_draft(draft, **options)
    invalid = validate_group_draft(draft.edit("row-3", address="02", tag_name="SecondLamp"), **options)
    return {"selected_source": selected.as_dict(), "source_bytes_preserved": index.snapshot == raw,
            "missing_default_refusal": refusal, "valid_complete_draft": valid.as_dict(),
            "invalid_complete_draft": invalid.as_dict(), "cancelled_rows": len(draft.cancel().rows),
            "baseline_bytes_preserved": sha256(baseline).hexdigest() == valid.baseline_sha256}


def _discovery_summary(state):
    return {"surface": state.surface.value, "rows": [{"row_id": row.spec.row_id, "phase": row.phase,
            "outcome": None if row.terminal is None else row.terminal.kind} for row in state.rows],
            "observations": [{"row_id": record.callback.token.row_id, "outcome": record.callback.outcome.kind,
                              "presented": record.presented, "reason": record.reason} for record in state.journal],
            "stopped": state.stopped, "paused": state.paused, "closed": state.closed,
            "absence_proven": state.absence_proven, "evidence_incomplete": state.evidence_incomplete,
            "io_performed": state.io_performed}


def _demo_discovery_session():
    from .discovery_session import (Callback, Context, DiscoveryAction, EditorSnapshot, Outcome, RowSpec,
                                    ScriptedFakeAdapter, SessionAction, Surface, cni_outcome,
                                    new_discovery, new_open_networks, new_session,
                                    reduce_discovery, reduce_open_networks, reduce_session)
    context = Context("discovery-demo", "serial-form", "offline:synthetic")
    serial = new_discovery(context, Surface.COM_SCAN,
                           (RowSpec("serial-1", "synthetic:COM1"), RowSpec("serial-2", "synthetic:COM2")))
    adapter = ScriptedFakeAdapter((Outcome("present"), Outcome("present")))
    first = reduce_discovery(serial, DiscoveryAction("dispatch", ("serial-1",)))
    completed = reduce_discovery(first.state, DiscoveryAction("callback", callback=adapter.observe(first.effects[0], 0))).state
    second = reduce_discovery(completed, DiscoveryAction("dispatch", ("serial-2",)))
    cancelled = reduce_discovery(second.state, DiscoveryAction("com_cancel")).state
    late = reduce_discovery(cancelled, DiscoveryAction("callback", callback=adapter.observe(second.effects[0], 1))).state
    cni = new_discovery(Context("cni-demo", "cni-form", "offline:synthetic"), Surface.CNI_SCAN,
                        (RowSpec("cni-route", "synthetic:route", window_seconds=5),))
    cni_request = reduce_discovery(cni, DiscoveryAction("dispatch", ("cni-route",)))
    paused = reduce_discovery(cni_request.state, DiscoveryAction("cni_pause")).state
    silence = cni_outcome(collection_complete=True, devices=0, hidden_ignored=0, malformed=0)
    cni_final = reduce_discovery(paused, DiscoveryAction("callback", callback=Callback(cni_request.effects[0].token, silence))).state
    opening = new_open_networks(Context("open-demo", "open-form", "offline:synthetic"),
                                (RowSpec("net-254", "offline:synthetic", "OFFLINE", "//OFFLINE/254"),
                                 RowSpec("net-253", "offline:synthetic", "OFFLINE", "//OFFLINE/253")))
    open_request = reduce_open_networks(opening, DiscoveryAction("dispatch", ("net-254",)))
    accepted = reduce_open_networks(open_request.state, DiscoveryAction("callback", callback=Callback(open_request.effects[0].token, Outcome("accepted")))).state
    stopped_open = reduce_open_networks(accepted, DiscoveryAction("stop")).state
    shell = new_session(Context("session-demo", "shell", "offline:synthetic", project="A", object_identity="//A/254/p/1"))
    shell = reduce_session(shell, SessionAction("schedule", operation_id="use-A", operation_kind="project_use")).state
    use = reduce_session(shell, SessionAction("dispatch", operation_id="use-A"))
    shell = reduce_session(use.state, SessionAction("callback", callback=Callback(use.effects[0].token, Outcome("completed", code=200)))).state
    shell = reduce_session(shell, SessionAction("schedule", operation_id="refresh-A", operation_kind="focus_refresh")).state
    refresh = reduce_session(shell, SessionAction("dispatch", operation_id="refresh-A"))
    switched = reduce_session(refresh.state, SessionAction("select", project="B", object_identity="//B/254/p/1", model_generation=1)).state
    stale = reduce_session(switched, SessionAction("callback", callback=Callback(refresh.effects[0].token, Outcome("completed")))).state
    dirty = reduce_session(stale, SessionAction("dirty_editor", editor=EditorSnapshot(stale.context, b"synthetic dirty B draft"))).state
    disconnected = reduce_session(dirty, SessionAction("disconnect")).state
    reconnected = reduce_session(disconnected, SessionAction("reconnect", endpoint="offline:synthetic")).state
    return {"expectation_origin": "scripted fake observations under proposed local safety policy",
            "serial_cancel_retains_completed_and_late": _discovery_summary(late),
            "cni_pause_silence": _discovery_summary(cni_final),
            "open_ack_then_stop": _discovery_summary(stopped_open),
            "shell_focus_change": {"selected_project": stale.context.project,
                "last_callback_presented": stale.journal[-1].presented,
                "suppression_reason": stale.journal[-1].reason, "project_confirmation": stale.project_confirmed},
            "shell_reconnect": {"connection_generation_before": dirty.context.connection_generation,
                "connection_generation_after": reconnected.context.connection_generation,
                "selection_cleared": reconnected.context.project is None,
                "detached_dirty_editors": len(reconnected.detached_editors),
                "retained_dirty_bytes": reconnected.detached_editors[0].payload.decode("ascii"),
                "io_performed": reconnected.io_performed}}


def _demo_transfer_restore():
    from .transfer_restore import (AdvancedTransferEvent, QuickTransferEvent, RestoreEvent, RestoreProject,
                                  RestoreResult, TransferRow, prepare_advanced_transfer, prepare_label_transfer,
                                  prepare_restore, prepare_transfer_direction, record_quick_transfer,
                                  record_restore_results)
    source_digest = sha256(b"synthetic source snapshot").hexdigest()
    staged_digest = sha256(b"synthetic staged data").hexdigest()
    rows = (TransferRow("unit-1", "offline:source/OFFLINE/254/p/1", source_digest,
                        destination_identity="offline:target/OFFLINE/254/p/2", staged_data_sha256=staged_digest,
                        action="programming-only"),)
    advanced = prepare_advanced_transfer(rows, (AdvancedTransferEvent("accept"),))
    cleared = prepare_advanced_transfer(rows, (AdvancedTransferEvent("clear-actions", ("unit-1",)), AdvancedTransferEvent("accept")))
    direction = prepare_transfer_direction("rdbDatabase", decision="accept", context_sha256=source_digest)
    quick = record_quick_transfer(("unit-1", "unit-2"),
                                  (QuickTransferEvent("completed", "unit-1", 100), QuickTransferEvent("failed", "unit-2", 40, "supplied failure"), QuickTransferEvent("close")),
                                  attempt_id="synthetic-quick-attempt")
    projects = (RestoreProject("project-A", "archive/A.xml", "A", source_digest, proposed_name="A_REVIEW"),
                RestoreProject("project-B", "archive/B.xml", "B", staged_digest),
                RestoreProject("project-C", "archive/C.xml", "C", source_digest, selected=False))
    options = {"archive_sha256": sha256(b"synthetic archive bytes").hexdigest(),
               "destination_snapshot_sha256": sha256(b"synthetic destination snapshot").hexdigest(),
               "destination_names": ("A",)}
    restore = prepare_restore(projects, history=(RestoreEvent("choose-policy", policy="rename"), RestoreEvent("accept")), **options)
    cancelled = prepare_restore(projects, history=(RestoreEvent("cancel"),), **options)
    results = record_restore_results(projects, (RestoreResult("project-A", "completed"), RestoreResult("project-B", "failed", "supplied failure")),
                                     attempt_id="synthetic-restore-results", decision_sha256=restore.as_dict()["report_sha256"])
    labels = prepare_label_transfer(({"text": "DeskLamp", "slot": 1}, {"text": "SecondLamp"}), 4)
    return {"advanced_intent": advanced.as_dict(), "clear_intent_only": cleared.as_dict(),
            "direction_is_separate": direction.as_dict(), "quick_supplied_results": quick.as_dict(),
            "restore_decision": restore.as_dict(), "restore_cancel": cancelled.as_dict(),
            "restore_supplied_results": results.as_dict(), "reused_structural_label_planner": labels.as_dict()}


_BUILDERS = {"copy-paste": _demo_copy_paste, "neo-editor": _demo_neo_editor,
             "catalogue-groups": _demo_catalogue_groups, "discovery-session": _demo_discovery_session,
             "transfer-restore": _demo_transfer_restore}


def run_demo(scenario="all"):
    """Return a fresh deterministic synthetic report without any I/O."""
    if scenario != "all" and scenario not in SCENARIOS:
        raise ValueError("Unknown offline demo scenario")
    selected = SCENARIOS if scenario == "all" else (scenario,)
    return {"format": "cbus-offline-workflows-demo-v1", "expectation_origin": "proposed-offline-policy",
            "fixture": "synthetic in-memory data", "preparation_only": True, "execution_enabled": False,
            "original_compatibility_verified": False, "native_acceptance": False, "hardware_acceptance": False,
            "external_persistence_verified": False,
            "scenarios": {name: _BUILDERS[name]() for name in selected}}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print synthetic pure offline workflow preparation examples.")
    parser.add_argument("--compact", action="store_true", help="Print one JSON line.")
    parser.add_argument("scenario", choices=("all",) + SCENARIOS, nargs="?", default="all")
    arguments = parser.parse_args(argv)
    print(json.dumps(run_demo(arguments.scenario), sort_keys=True, ensure_ascii=True,
                     indent=None if arguments.compact else 2, separators=(",", ":") if arguments.compact else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
