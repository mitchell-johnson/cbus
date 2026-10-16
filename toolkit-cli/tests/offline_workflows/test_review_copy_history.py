"""Bounded reconstruction regressions for source-bound copy/paste history."""
from dataclasses import replace

import pytest

from cbus_toolkit.offline_workflows.copy_paste import (
    CopyKind, CopyPasteError, CopyPasteIntent, CopyPhase, CopySource, CopyTarget,
    Ownership, PasteRequest, UNSUPPORTED_TOOLKIT_PROFILE, attempt_paste,
    cancel_intent, copy_intent, draft_child_profile, mark_uncertain, select_target,
)


def selected():
    owner = Ownership("offline:history-fixture", "history-repository", "HISTORY")
    source = CopySource(owner, "//HISTORY/0254/56/1", "group-1", CopyKind.GROUP,
                        b'<!--synthetic--><Group oid="group-1"/>')
    target = CopyTarget(owner, "//HISTORY/0254/56", "application-1", CopyKind.APPLICATION)
    return select_target(copy_intent(source, profile=draft_child_profile(CopyKind.GROUP)), target)


def terminal_accepted(phase):
    intent = selected()
    request = PasteRequest("0042", "Explicit draft", intent.source.sha256, False, False)
    accepted = attempt_paste(intent, request)
    return (cancel_intent(accepted) if phase is CopyPhase.CANCELLED
            else mark_uncertain(accepted, "Explicitly unresolved local history"))


def reconstruct(intent, mode, **changes):
    if mode == "direct":
        return CopyPasteIntent(**(vars(intent) | changes))
    return replace(intent, **changes)


@pytest.mark.parametrize("phase", (CopyPhase.CANCELLED, CopyPhase.UNCERTAIN))
@pytest.mark.parametrize("mode", ("direct", "replace"))
@pytest.mark.parametrize("changed_binding", ("unsupported_profile", "cross_owner", "stale_hash", "source_snapshot"))
def test_historical_acceptance_cannot_bypass_profile_owner_or_snapshot_gates(phase, mode, changed_binding):
    intent = terminal_accepted(phase)
    if changed_binding == "unsupported_profile":
        changes = {"profile": UNSUPPORTED_TOOLKIT_PROFILE}
    elif changed_binding == "cross_owner":
        other_owner = replace(intent.target.owner, project="OTHER")
        changes = {"target": replace(intent.target, owner=other_owner)}
    elif changed_binding == "stale_hash":
        changes = {"request": replace(intent.request, source_sha256="0" * 64)}
    else:
        changes = {"source": replace(intent.source, snapshot=b'<Group oid="changed"/>')}
    with pytest.raises(CopyPasteError, match="profile gates"):
        reconstruct(intent, mode, **changes)
    assert intent.phase is phase
    assert intent.history[-2:] == (CopyPhase.ACCEPTED, phase)
    assert intent.report()["execution_enabled"] is False


@pytest.mark.parametrize("phase", (CopyPhase.CANCELLED, CopyPhase.UNCERTAIN))
@pytest.mark.parametrize("mode", ("direct", "replace"))
def test_valid_historical_acceptance_retains_terminal_state_and_uncertainty_reason(phase, mode):
    intent = terminal_accepted(phase)
    rebuilt = reconstruct(intent, mode)
    assert rebuilt == intent
    assert rebuilt.history[-2:] == (CopyPhase.ACCEPTED, phase)
    assert rebuilt.source.sha256 == rebuilt.request.source_sha256
    if phase is CopyPhase.UNCERTAIN:
        assert rebuilt.refusal.code == "uncertain_outcome"
        assert rebuilt.refusal.detail == "Explicitly unresolved local history"
    else:
        assert rebuilt.refusal is None
    report = rebuilt.report()
    assert report["commands"] == []
    assert report["execution_enabled"] is False
    assert report["native_compatibility"] is False
    assert report["saved"] is False and report["reopened"] is False


@pytest.mark.parametrize("mode", ("direct", "replace"))
def test_historical_refusal_reason_cannot_be_removed_after_cancellation(mode):
    intent = selected()
    request = PasteRequest("0042", "Explicit draft", intent.source.sha256, True, False)
    refused = attempt_paste(intent, request)
    cancelled = cancel_intent(refused)
    assert cancelled.history[-2:] == (CopyPhase.REFUSED, CopyPhase.CANCELLED)
    with pytest.raises(CopyPasteError, match="retained reason"):
        reconstruct(cancelled, mode, refusal=None)
    assert cancelled.refusal is refused.refusal


@pytest.mark.parametrize("mode", ("direct", "replace"))
def test_valid_historical_refusal_preserves_its_exact_reason_after_cancellation(mode):
    intent = selected()
    request = PasteRequest("0042", "Explicit draft", intent.source.sha256, True, False)
    refused = attempt_paste(intent, request)
    cancelled = cancel_intent(refused)
    rebuilt = reconstruct(cancelled, mode)
    assert rebuilt == cancelled
    assert rebuilt.refusal == refused.refusal
    assert rebuilt.refusal.code == "address_conflict"
    assert rebuilt.refusal.detail == "The explicit destination address collides"
    assert rebuilt.report()["cancellation_effect"] == "discarded-offline-intent-only"
