"""Immutable, zero-I/O copy/paste intent preparation.

An accepted intent is an offline draft, not a paste, command receipt or save.
Toolkit clipboard/focus handlers, whole-project paste, Unit effects, allocation,
conflict prompts, OID/reference policy and persistence are unverified here.
No existing ProjectDocument or NativeDatabase copy operation is executed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib


class CopyPasteError(ValueError):
    """Malformed input or an illegal offline intent transition."""


class CopyKind(str, Enum):
    PROJECT = "Project"
    NETWORK = "Network"
    APPLICATION = "Application"
    GROUP = "Group"
    LEVEL = "Level"
    UNIT = "Unit"
    NETVAR = "NetVar"
    TRIGGER = "Trigger"
    ACTION = "Action"
    ENABLE = "Enable"


class ProfileMode(str, Enum):
    UNSUPPORTED = "unsupported"
    PROPOSED_OFFLINE_DRAFT = "proposed-offline-draft"


class CopyPhase(str, Enum):
    COPIED = "copied"
    TARGET_SELECTED = "target-selected"
    PASTE_ATTEMPTED = "paste-attempted"
    ACCEPTED = "accepted"
    REFUSED = "refused"
    CANCELLED = "cancelled"
    UNCERTAIN = "uncertain"
    SAVED = "saved"
    REOPENED = "reopened"


# A proposal-only envelope for existing structural child kinds. This is not a
# reconstruction of original Toolkit clipboard eligibility or a copy algorithm.
_DRAFT_PARENTS = {
    CopyKind.NETWORK: CopyKind.PROJECT,
    CopyKind.APPLICATION: CopyKind.NETWORK,
    CopyKind.GROUP: CopyKind.APPLICATION,
    CopyKind.LEVEL: CopyKind.GROUP,
}
_MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
_TERMINAL = {CopyPhase.REFUSED, CopyPhase.CANCELLED, CopyPhase.UNCERTAIN}
_NEXT_PHASES = {
    CopyPhase.COPIED: {CopyPhase.TARGET_SELECTED, CopyPhase.CANCELLED, CopyPhase.UNCERTAIN},
    CopyPhase.TARGET_SELECTED: {CopyPhase.TARGET_SELECTED, CopyPhase.PASTE_ATTEMPTED,
                              CopyPhase.CANCELLED, CopyPhase.UNCERTAIN},
    CopyPhase.PASTE_ATTEMPTED: {CopyPhase.ACCEPTED, CopyPhase.REFUSED,
                               CopyPhase.CANCELLED, CopyPhase.UNCERTAIN},
    CopyPhase.ACCEPTED: {CopyPhase.CANCELLED, CopyPhase.UNCERTAIN},
    CopyPhase.REFUSED: {CopyPhase.CANCELLED},
    CopyPhase.CANCELLED: set(),
    CopyPhase.UNCERTAIN: set(),
}


def _text(value: str, label: str) -> None:
    if (not isinstance(value, str) or not value.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise CopyPasteError(f"{label} must be nonblank text without control characters")


def _kind(value: CopyKind, label: str) -> None:
    if not isinstance(value, CopyKind):
        raise CopyPasteError(f"{label} must be an explicit CopyKind")


@dataclass(frozen=True)
class Ownership:
    """Exact opaque ownership identities, never endpoint or path resolution."""

    endpoint: str
    repository: str
    project: str

    def __post_init__(self) -> None:
        for label in ("endpoint", "repository", "project"):
            _text(getattr(self, label), label)


@dataclass(frozen=True)
class CopySource:
    """Caller-supplied source identity and a detached, byte-preserving snapshot.

    OID/kind are independently supplied facts; hashing does not authenticate
    those facts or parse the snapshot to infer them.
    """

    owner: Ownership
    selector: str
    oid: str
    kind: CopyKind
    snapshot: bytes
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.owner, Ownership):
            raise CopyPasteError("source owner must be Ownership")
        _text(self.selector, "source selector")
        _text(self.oid, "source OID")
        _kind(self.kind, "source kind")
        if not isinstance(self.snapshot, (bytes, bytearray, memoryview)):
            raise CopyPasteError("source snapshot must be bytes-like")
        snapshot = bytes(self.snapshot)
        if not snapshot or len(snapshot) > _MAX_SNAPSHOT_BYTES:
            raise CopyPasteError("source snapshot must contain 1..16777216 bytes")
        object.__setattr__(self, "snapshot", snapshot)
        object.__setattr__(self, "sha256", hashlib.sha256(snapshot).hexdigest())


@dataclass(frozen=True)
class CopyTarget:
    """The caller's actual target selection, with exact lexical identity."""

    owner: Ownership
    selector: str
    oid: str
    kind: CopyKind

    def __post_init__(self) -> None:
        if not isinstance(self.owner, Ownership):
            raise CopyPasteError("target owner must be Ownership")
        _text(self.selector, "target selector")
        _text(self.oid, "target OID")
        _kind(self.kind, "target kind")


@dataclass(frozen=True)
class CopyPasteProfile:
    """A distinct unsupported contract or an explicit offline child proposal."""

    profile_id: str
    mode: ProfileMode = ProfileMode.UNSUPPORTED
    source_kind: CopyKind | None = None
    target_kind: CopyKind | None = None

    def __post_init__(self) -> None:
        _text(self.profile_id, "profile ID")
        if not isinstance(self.mode, ProfileMode):
            raise CopyPasteError("profile mode must be an explicit ProfileMode")
        for label in ("source_kind", "target_kind"):
            value = getattr(self, label)
            if value is not None:
                _kind(value, label)
        if self.mode is ProfileMode.PROPOSED_OFFLINE_DRAFT:
            if (self.source_kind not in _DRAFT_PARENTS
                    or _DRAFT_PARENTS[self.source_kind] is not self.target_kind):
                raise CopyPasteError("unsupported offline child proposal route")

    @property
    def command_sequence(self) -> tuple[()]:
        """No command sequence has been admitted by this module."""
        return ()

    @property
    def native_compatibility(self) -> bool:
        return False


def draft_child_profile(kind: CopyKind) -> CopyPasteProfile:
    """Opt in to one preparatory-only same-owner structural child route."""
    _kind(kind, "profile source kind")
    if kind not in _DRAFT_PARENTS:
        raise CopyPasteError(f"{kind.value} has no supported offline draft profile")
    return CopyPasteProfile(
        f"proposed-offline-{kind.value.lower()}-intent-v1",
        ProfileMode.PROPOSED_OFFLINE_DRAFT, kind, _DRAFT_PARENTS[kind],
    )


UNSUPPORTED_TOOLKIT_PROFILE = CopyPasteProfile("toolkit-original-clipboard-unverified")


@dataclass(frozen=True)
class PasteRequest:
    """Explicit draft inputs and caller-supplied collision facts.

    None means unknown; a false collision fact is never inferred from an empty
    inventory. Address/name remain exact strings and no free address is chosen.
    """

    address: str | None = None
    name: str | None = None
    source_sha256: str | None = None
    address_conflict: bool | None = None
    name_conflict: bool | None = None
    conflict_choice: str = "refuse"

    def __post_init__(self) -> None:
        for label in ("address", "name", "source_sha256"):
            value = getattr(self, label)
            if value is not None:
                _text(value, label)
        for label in ("address_conflict", "name_conflict"):
            if getattr(self, label) is not None and type(getattr(self, label)) is not bool:
                raise CopyPasteError(f"{label} must be Boolean or unknown")
        _text(self.conflict_choice, "conflict choice")


@dataclass(frozen=True)
class Refusal:
    code: str
    detail: str

    def __post_init__(self) -> None:
        _text(self.code, "refusal code")
        _text(self.detail, "refusal detail")


@dataclass(frozen=True)
class CopyPasteIntent:
    """Immutable history. All phases describe the offline proposal only."""

    source: CopySource
    profile: CopyPasteProfile = UNSUPPORTED_TOOLKIT_PROFILE
    target: CopyTarget | None = None
    request: PasteRequest | None = None
    phase: CopyPhase = CopyPhase.COPIED
    history: tuple[CopyPhase, ...] = (CopyPhase.COPIED,)
    refusal: Refusal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, CopySource) or not isinstance(self.profile, CopyPasteProfile):
            raise CopyPasteError("intent needs a CopySource and CopyPasteProfile")
        if self.target is not None and not isinstance(self.target, CopyTarget):
            raise CopyPasteError("intent target must be CopyTarget")
        if self.request is not None and not isinstance(self.request, PasteRequest):
            raise CopyPasteError("intent request must be PasteRequest")
        if (not isinstance(self.phase, CopyPhase) or type(self.history) is not tuple
                or not self.history or any(not isinstance(value, CopyPhase) for value in self.history)
                or self.history[0] is not CopyPhase.COPIED or self.history[-1] is not self.phase):
            raise CopyPasteError("intent phase and immutable history must agree")
        if any(value in (CopyPhase.SAVED, CopyPhase.REOPENED) for value in self.history):
            raise CopyPasteError("external persistence phases are unsupported")
        if self.refusal is not None and not isinstance(self.refusal, Refusal):
            raise CopyPasteError("intent refusal must be Refusal")
        if any(after not in _NEXT_PHASES[before]
               for before, after in zip(self.history, self.history[1:])):
            raise CopyPasteError("intent history contains an illegal transition or replay")
        if CopyPhase.TARGET_SELECTED in self.history and self.target is None:
            raise CopyPasteError("selected history needs a target descriptor")
        if CopyPhase.PASTE_ATTEMPTED in self.history:
            if self.target is None or self.request is None:
                raise CopyPasteError("attempted history needs target and request descriptors")
        if (CopyPhase.REFUSED in self.history or self.phase is CopyPhase.UNCERTAIN) and self.refusal is None:
            raise CopyPasteError("refusal or uncertainty needs a retained reason")
        if CopyPhase.ACCEPTED in self.history:
            if ((self.phase is CopyPhase.ACCEPTED and self.refusal is not None)
                    or _paste_refusal(self, self.request) is not None):
                raise CopyPasteError("accepted draft does not satisfy its explicit profile gates")

    def report(self) -> dict:
        """Return detached diagnostics without emitting source bytes."""
        return {
            "format": "cbus-offline-copy-paste-intent-v1",
            "scope": "proposed-offline-draft",
            "phase": self.phase.value,
            "history": [value.value for value in self.history],
            "profile": self.profile.profile_id,
            "source": {"owner": vars(self.source.owner).copy(),
                       "selector": self.source.selector, "oid": self.source.oid,
                       "kind": self.source.kind.value, "sha256": self.source.sha256,
                       "bytes": len(self.source.snapshot)},
            "target": None if self.target is None else {
                "owner": vars(self.target.owner).copy(), "selector": self.target.selector,
                "oid": self.target.oid, "kind": self.target.kind.value},
            "request": None if self.request is None else vars(self.request).copy(),
            "refusal": None if self.refusal is None else vars(self.refusal).copy(),
            "execution_enabled": False,
            "commands": [],
            "external_mutation_attempted": False,
            "saved": False,
            "reopened": False,
            "native_compatibility": False,
            "source_identity_verified": False,
            "clipboard_representation": None,
            "identity_reference_policy": None,
            "dependency_expansion": None,
            "cancellation_effect": (
                "discarded-offline-intent-only" if self.phase is CopyPhase.CANCELLED else None),
        }


def copy_intent(source: CopySource, *, profile: CopyPasteProfile = UNSUPPORTED_TOOLKIT_PROFILE) -> CopyPasteIntent:
    return CopyPasteIntent(source=source, profile=profile)


def _advance(intent: CopyPasteIntent, phase: CopyPhase, **changes) -> CopyPasteIntent:
    if not isinstance(intent, CopyPasteIntent):
        raise CopyPasteError("expected CopyPasteIntent")
    return replace(intent, phase=phase, history=intent.history + (phase,), **changes)


def select_target(intent: CopyPasteIntent, target: CopyTarget) -> CopyPasteIntent:
    if intent.phase not in (CopyPhase.COPIED, CopyPhase.TARGET_SELECTED):
        raise CopyPasteError("target selection is closed after a paste planning attempt")
    return _advance(intent, CopyPhase.TARGET_SELECTED, target=target)


def _paste_refusal(intent: CopyPasteIntent, request: PasteRequest) -> Refusal | None:
    profile = intent.profile
    if profile.mode is ProfileMode.UNSUPPORTED:
        return Refusal("unsupported_profile", "Original Toolkit clipboard contract is unverified")
    if intent.source.kind is not profile.source_kind:
        return Refusal("unsupported_source_kind", "Source kind differs from the selected draft profile")
    if intent.target.kind is not profile.target_kind:
        return Refusal("wrong_target_kind", "Target kind differs from the selected draft profile")
    if intent.source.owner != intent.target.owner:
        return Refusal("different_owner", "Cross-endpoint, repository or project child paste is unsupported")
    if request.source_sha256 != intent.source.sha256:
        return Refusal("source_binding", "Request must bind the exact immutable source snapshot SHA-256")
    if request.address is None or request.name is None:
        return Refusal("explicit_identity_required", "Address and name must both be explicitly supplied")
    if request.conflict_choice != "refuse":
        return Refusal("unsupported_conflict_choice", "Overwrite, rename and automatic allocation are unsupported")
    if request.address_conflict is None or request.name_conflict is None:
        return Refusal("unknown_conflicts", "Independent address and name collision facts are required")
    if request.address_conflict:
        return Refusal("address_conflict", "The explicit destination address collides")
    if request.name_conflict:
        return Refusal("name_conflict", "The explicit destination name collides")
    return None


def attempt_paste(intent: CopyPasteIntent, request: PasteRequest) -> CopyPasteIntent:
    """Attempt offline admission once; never paste, initialize, save or replay."""
    if intent.phase is not CopyPhase.TARGET_SELECTED or intent.target is None:
        raise CopyPasteError("paste planning requires one selected target and an unattempted intent")
    if not isinstance(request, PasteRequest):
        raise CopyPasteError("expected PasteRequest")
    attempted = _advance(intent, CopyPhase.PASTE_ATTEMPTED, request=request)
    refusal = _paste_refusal(attempted, request)
    return _advance(attempted, CopyPhase.REFUSED if refusal else CopyPhase.ACCEPTED, refusal=refusal)


def cancel_intent(intent: CopyPasteIntent) -> CopyPasteIntent:
    """Discard only the draft; no external cancellation or rollback claim."""
    if intent.phase in (CopyPhase.UNCERTAIN, CopyPhase.CANCELLED):
        raise CopyPasteError("terminal uncertainty/cancellation cannot be replaced")
    return _advance(intent, CopyPhase.CANCELLED)


def mark_uncertain(intent: CopyPasteIntent, detail: str) -> CopyPasteIntent:
    """Retain an explicit unresolved outcome and close all dependent actions."""
    if intent.phase in _TERMINAL:
        raise CopyPasteError("a terminal intent cannot be changed to uncertainty")
    return _advance(intent, CopyPhase.UNCERTAIN, refusal=Refusal("uncertain_outcome", detail))


def persistence_gate(intent: CopyPasteIntent, stage: CopyPhase) -> Refusal:
    """Save/reopen remain unsupported; this gate never creates success phases."""
    if stage not in (CopyPhase.SAVED, CopyPhase.REOPENED):
        raise CopyPasteError("persistence stage must be SAVED or REOPENED")
    if intent.phase is CopyPhase.UNCERTAIN:
        return Refusal("uncertain_outcome", "Uncertainty blocks dependent persistence and replay")
    return Refusal("unsupported_persistence", f"{stage.value} has no admitted execution or observation contract")
