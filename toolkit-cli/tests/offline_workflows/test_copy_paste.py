"""Synthetic, zero-I/O intent contract tests; no original acceptance claim."""
from dataclasses import FrozenInstanceError, replace
import hashlib

import pytest

from cbus_toolkit.offline_workflows.copy_paste import (
    CopyKind, CopyPasteError, CopyPasteIntent, CopyPasteProfile, CopyPhase,
    CopySource, CopyTarget, Ownership, PasteRequest, ProfileMode,
    attempt_paste, cancel_intent, copy_intent, draft_child_profile,
    mark_uncertain, persistence_gate, select_target,
)


OWNER = Ownership("offline:fixture", "fixture-repository", "DEMO")
RAW = b'<?xml version="1.0"?><!--keep--><Group OID="g"><TagName>Original</TagName><Unknown a="1"/><Unknown a="2"/></Group>'


def source(kind=CopyKind.GROUP, *, owner=OWNER, raw=RAW):
    return CopySource(owner, "//DEMO/0254/56/1", "group-oid", kind, raw)


def target(kind=CopyKind.APPLICATION, *, owner=OWNER):
    return CopyTarget(owner, "//DEMO/0254/56", "application-oid", kind)


def selected(kind=CopyKind.GROUP):
    profile = draft_child_profile(kind)
    return select_target(copy_intent(source(kind), profile=profile), target(profile.target_kind))


def request(intent, **changes):
    value = PasteRequest("0042", " Draft name ", intent.source.sha256, False, False)
    return replace(value, **changes)


def test_source_detaches_mutable_buffer_and_preserves_bytes_exactly():
    buffer = bytearray(RAW)
    captured = source(raw=buffer)
    buffer[:] = b"changed"
    assert captured.snapshot == RAW
    assert captured.sha256 == hashlib.sha256(RAW).hexdigest()
    assert captured.selector == "//DEMO/0254/56/1"
    assert captured.oid == "group-oid"
    assert captured.kind is CopyKind.GROUP
    with pytest.raises(FrozenInstanceError):
        captured.oid = "changed"


def test_descriptor_and_profile_validation_reject_implicit_types():
    with pytest.raises(CopyPasteError):
        source(kind="Group")
    with pytest.raises(CopyPasteError):
        CopySource(OWNER, "x", "oid", CopyKind.GROUP, "xml")
    with pytest.raises(CopyPasteError):
        source(raw=b"")
    with pytest.raises(CopyPasteError):
        Ownership("endpoint\ncommand", "repo", "project")
    with pytest.raises(CopyPasteError):
        CopyPasteProfile("profile", "proposed-offline-draft", CopyKind.GROUP, CopyKind.APPLICATION)
    with pytest.raises(CopyPasteError):
        CopyPasteProfile("profile", ProfileMode.PROPOSED_OFFLINE_DRAFT, CopyKind.GROUP, CopyKind.NETWORK)
    with pytest.raises(CopyPasteError):
        PasteRequest(address_conflict=0)


def test_default_original_toolkit_profile_refuses_without_commands():
    initial = copy_intent(source())
    bound = select_target(initial, target())
    refused = attempt_paste(bound, request(bound))
    assert refused.phase is CopyPhase.REFUSED
    assert refused.refusal.code == "unsupported_profile"
    assert refused.history == (CopyPhase.COPIED, CopyPhase.TARGET_SELECTED,
                               CopyPhase.PASTE_ATTEMPTED, CopyPhase.REFUSED)
    report = refused.report()
    assert report["commands"] == []
    assert report["external_mutation_attempted"] is False
    assert report["native_compatibility"] is False
    assert initial.phase is CopyPhase.COPIED
    assert initial.target is None


@pytest.mark.parametrize("kind,parent", [
    (CopyKind.NETWORK, CopyKind.PROJECT),
    (CopyKind.APPLICATION, CopyKind.NETWORK),
    (CopyKind.GROUP, CopyKind.APPLICATION),
    (CopyKind.LEVEL, CopyKind.GROUP),
])
def test_distinct_profiles_accept_only_offline_drafts(kind, parent):
    intent = selected(kind)
    accepted = attempt_paste(intent, request(intent))
    assert accepted.phase is CopyPhase.ACCEPTED
    assert accepted.profile.source_kind is kind
    assert accepted.profile.target_kind is parent
    assert accepted.profile.command_sequence == ()
    assert accepted.request.address == "0042"
    assert accepted.request.name == " Draft name "
    report = accepted.report()
    assert report["scope"] == "proposed-offline-draft"
    assert report["saved"] is False and report["reopened"] is False
    assert report["execution_enabled"] is False
    assert report["identity_reference_policy"] is None
    assert report["source_identity_verified"] is False
    assert "snapshot" not in report["source"]
    assert accepted.source.snapshot == RAW


@pytest.mark.parametrize("kind", [CopyKind.PROJECT, CopyKind.UNIT, CopyKind.NETVAR,
                                 CopyKind.TRIGGER, CopyKind.ACTION, CopyKind.ENABLE])
def test_unverified_routes_have_no_draft_profile(kind):
    with pytest.raises(CopyPasteError, match="no supported offline draft profile"):
        draft_child_profile(kind)


def test_source_kind_and_target_kind_must_match_the_distinct_profile():
    group_profile = draft_child_profile(CopyKind.GROUP)
    wrong_source = select_target(copy_intent(source(CopyKind.LEVEL), profile=group_profile), target())
    wrong_target = select_target(copy_intent(source(), profile=group_profile), target(CopyKind.NETWORK))
    assert attempt_paste(wrong_source, request(wrong_source)).refusal.code == "unsupported_source_kind"
    assert attempt_paste(wrong_target, request(wrong_target)).refusal.code == "wrong_target_kind"


@pytest.mark.parametrize("field", ["endpoint", "repository", "project"])
def test_project_scoped_oid_does_not_allow_any_owner_change(field):
    different = replace(OWNER, **{field: getattr(OWNER, field).lower() + "-other"})
    intent = select_target(copy_intent(source(), profile=draft_child_profile(CopyKind.GROUP)),
                           target(owner=different))
    refused = attempt_paste(intent, request(intent))
    assert refused.refusal.code == "different_owner"
    assert refused.target.oid == "application-oid"
    assert refused.source.owner is OWNER


@pytest.mark.parametrize("changes,code", [
    ({"source_sha256": None}, "source_binding"),
    ({"source_sha256": "0" * 64}, "source_binding"),
    ({"address": None}, "explicit_identity_required"),
    ({"name": None}, "explicit_identity_required"),
    ({"address_conflict": None}, "unknown_conflicts"),
    ({"name_conflict": None}, "unknown_conflicts"),
    ({"address_conflict": True}, "address_conflict"),
    ({"name_conflict": True}, "name_conflict"),
    ({"conflict_choice": "overwrite"}, "unsupported_conflict_choice"),
    ({"conflict_choice": "rename"}, "unsupported_conflict_choice"),
    ({"conflict_choice": "first-free"}, "unsupported_conflict_choice"),
])
def test_explicit_identity_hash_and_collision_gates(changes, code):
    intent = selected()
    refused = attempt_paste(intent, request(intent, **changes))
    assert refused.refusal.code == code
    assert refused.phase is CopyPhase.REFUSED
    assert refused.source.snapshot == RAW
    assert intent.phase is CopyPhase.TARGET_SELECTED


def test_attempt_is_exactly_once_and_refusal_cannot_be_reselected_or_replayed():
    intent = selected()
    for result in (attempt_paste(intent, request(intent)),
                   attempt_paste(intent, request(intent, address_conflict=True))):
        with pytest.raises(CopyPasteError):
            attempt_paste(result, request(result))
        with pytest.raises(CopyPasteError):
            select_target(result, target())
    with pytest.raises(CopyPasteError):
        attempt_paste(copy_intent(source()), PasteRequest())


def test_cancel_discards_only_the_draft_and_retains_source_and_request():
    intent = selected()
    accepted = attempt_paste(intent, request(intent))
    cancelled = cancel_intent(accepted)
    assert cancelled.phase is CopyPhase.CANCELLED
    assert cancelled.source is accepted.source
    assert cancelled.request is accepted.request
    assert accepted.phase is CopyPhase.ACCEPTED
    report = cancelled.report()
    assert report["cancellation_effect"] == "discarded-offline-intent-only"
    assert report["external_mutation_attempted"] is False
    with pytest.raises(CopyPasteError):
        cancel_intent(cancelled)


def test_uncertainty_is_retained_and_blocks_dependents_without_replay():
    intent = selected()
    accepted = attempt_paste(intent, request(intent))
    uncertain = mark_uncertain(accepted, "Interrupted caller-supplied planning history")
    assert uncertain.phase is CopyPhase.UNCERTAIN
    assert uncertain.refusal.code == "uncertain_outcome"
    assert uncertain.history[-2:] == (CopyPhase.ACCEPTED, CopyPhase.UNCERTAIN)
    for action in (lambda: cancel_intent(uncertain),
                   lambda: select_target(uncertain, target()),
                   lambda: attempt_paste(uncertain, request(uncertain)),
                   lambda: mark_uncertain(uncertain, "retry")):
        with pytest.raises(CopyPasteError):
            action()
    assert persistence_gate(uncertain, CopyPhase.SAVED).code == "uncertain_outcome"


def test_persistence_stages_cannot_be_forged_or_turn_drafts_into_save_receipts():
    intent = selected()
    accepted = attempt_paste(intent, request(intent))
    for stage in (CopyPhase.SAVED, CopyPhase.REOPENED):
        assert persistence_gate(accepted, stage).code == "unsupported_persistence"
        assert accepted.phase is CopyPhase.ACCEPTED
        with pytest.raises(CopyPasteError, match="persistence phases"):
            replace(accepted, phase=stage, history=accepted.history + (stage,))
    with pytest.raises(CopyPasteError):
        persistence_gate(accepted, CopyPhase.ACCEPTED)


def test_report_is_detached_from_immutable_intent_and_preserves_exact_owners():
    intent = selected()
    report = intent.report()
    report["source"]["owner"]["project"] = "changed"
    report["history"].append("saved")
    report["commands"].append("DBCOPYSAFE")
    assert intent.source.owner.project == "DEMO"
    assert intent.history == (CopyPhase.COPIED, CopyPhase.TARGET_SELECTED)
    assert intent.report()["commands"] == []


def test_history_requires_an_immutable_consistent_envelope():
    with pytest.raises(CopyPasteError):
        CopyPasteIntent(source(), history=[CopyPhase.COPIED])
    with pytest.raises(CopyPasteError):
        CopyPasteIntent(source(), phase=CopyPhase.ACCEPTED)


def test_direct_envelopes_cannot_bypass_profile_gates_or_terminal_history():
    selected_original = select_target(copy_intent(source()), target())
    attempt = request(selected_original)
    with pytest.raises(CopyPasteError, match="profile gates"):
        replace(selected_original, request=attempt, phase=CopyPhase.ACCEPTED,
                history=selected_original.history + (CopyPhase.PASTE_ATTEMPTED, CopyPhase.ACCEPTED))
    refused = attempt_paste(selected(), request(selected(), address_conflict=True))
    with pytest.raises(CopyPasteError, match="illegal transition"):
        replace(refused, phase=CopyPhase.ACCEPTED, refusal=None,
                history=refused.history + (CopyPhase.ACCEPTED,))
    cancelled = cancel_intent(selected())
    with pytest.raises(CopyPasteError, match="illegal transition"):
        replace(cancelled, phase=CopyPhase.TARGET_SELECTED,
                history=cancelled.history + (CopyPhase.TARGET_SELECTED,))
    with pytest.raises(CopyPasteError, match="target descriptor"):
        CopyPasteIntent(source(), phase=CopyPhase.TARGET_SELECTED,
                        history=(CopyPhase.COPIED, CopyPhase.TARGET_SELECTED))


def test_explicit_pending_attempt_can_retain_interruption_without_admission():
    intent = selected()
    pending = replace(intent, request=request(intent), phase=CopyPhase.PASTE_ATTEMPTED,
                      history=intent.history + (CopyPhase.PASTE_ATTEMPTED,))
    uncertain = mark_uncertain(pending, "Interrupted offline planning attempt")
    assert uncertain.history[-2:] == (CopyPhase.PASTE_ATTEMPTED, CopyPhase.UNCERTAIN)
    assert uncertain.report()["external_mutation_attempted"] is False
    assert cancel_intent(pending).phase is CopyPhase.CANCELLED
