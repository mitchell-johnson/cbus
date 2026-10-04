"""Pure ordinary-Neo editor preparation under a PROPOSED CLI policy.

This is a local state model, not a programming-session or persistence adapter.
Apply accepts a local proposal; it never performs or proves PP/PROJECT SAVE.
Original Apply/Cancel/OK, nested Save Location and Close/Escape semantics remain
unassessed. The exact synthetic KEYM4 profile is the first admitted bound.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import re
from types import MappingProxyType
from typing import Any, Mapping

from ..extended_macros import ExtendedKeys, LAYOUTS
from ..macros import MacroError, TRIGGER_PRESETS
from ..memory import MemoryError, MemoryImage
from ..unitspec import ParameterSpec, UnitSpec


POLICY = "PROPOSED CLI policy: ordinary Neo local stage/apply/discard v1"
ORIGINAL_TERMINAL_SEMANTICS = "original terminal semantics unassessed"
_SOURCE = re.compile(r"/db//([^/\s]+)/([^/\s]+)/p/([0-9]+)\Z")


class NeoEditorError(ValueError):
    """Refused local transition or unsupported editor input."""


def _freeze(value):
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise NeoEditorError("Snapshot mappings require string keys")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, bool, bytes)):
        return value
    raise NeoEditorError("Snapshot values must be immutable scalar or mapping/sequence data")


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, bytes):
        return {"hex": value.hex()}
    return value


def _same_typed_value(left, right):
    """Compare frozen facts without Python's bool/int equality coercion."""
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        if len(left) != len(right):
            return False
        left_items, right_items = sorted(left.items()), sorted(right.items())
        return all(_same_typed_value(left_key, right_key)
                   and _same_typed_value(left_value, right_value)
                   for (left_key, left_value), (right_key, right_value)
                   in zip(left_items, right_items))
    if isinstance(left, tuple):
        return len(left) == len(right) and all(
            _same_typed_value(left_item, right_item)
            for left_item, right_item in zip(left, right))
    return left == right


def _frozen_spec(spec):
    if not isinstance(spec, UnitSpec):
        raise NeoEditorError("Supply an explicit decoded UnitSpec")
    parameters = {
        name: ParameterSpec(row.name, row.type, row.source,
                            MappingProxyType(dict(row.fields)), tuple(row.tags))
        for name, row in spec.parameters.items()
    }
    return UnitSpec(spec.filename, MappingProxyType(dict(spec.metadata)),
                    tuple(spec.sources), MappingProxyType(parameters),
                    tuple(_freeze(row) for row in spec.overrides))


@dataclass(frozen=True)
class NeoProfile:
    """Explicit caller scope; synthetic/closed flags are inputs, not attestations."""

    source: str
    unit_type: str
    firmware: str
    catalogue: str
    serial: str
    network_state: str
    synthetic: bool

    def __post_init__(self):
        if (self.unit_type, self.firmware, self.catalogue, self.serial) != (
                "KEYM4", "2.5.00", "5054NL", ""):
            raise NeoEditorError("Only KEYM4 / 2.5.00 / 5054NL with blank serial is admitted")
        match = _SOURCE.fullmatch(self.source) if isinstance(self.source, str) else None
        if match is None or not 1 <= int(match[3]) <= 255:
            raise NeoEditorError("An explicit /db//PROJECT/NETWORK/p/UNIT source is required")
        if self.network_state != "closed" or self.synthetic is not True:
            raise NeoEditorError("The preparatory profile requires an explicitly closed synthetic network")

    def as_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, eq=False)
class NeoSnapshot:
    """Exact supplied PP/graph data plus known logical memory and group facts.

    Graph bytes and group facts are retained caller inputs. This model does not
    parse a native project, derive an inventory, or establish their provenance.
    Sparse memory omissions stay unknown and are never filled by an edit.
    Equality preserves scalar types recursively: booleans and integers
    remain distinct baseline facts, including inside opaque PP values.
    """

    values: Mapping[str, Any]
    memory: MemoryImage
    graph_bytes: bytes
    existing_groups: tuple[tuple[int, int], ...]

    def __post_init__(self):
        if not isinstance(self.values, Mapping) or not self.values:
            raise NeoEditorError("A nonempty complete caller PP snapshot is required")
        object.__setattr__(self, "values", _freeze(self.values))
        if not isinstance(self.memory, MemoryImage):
            raise NeoEditorError("Supply logical memory as a sparse MemoryImage")
        if not isinstance(self.graph_bytes, bytes) or not self.graph_bytes:
            raise NeoEditorError("Retain the exact nonempty caller project graph bytes")
        groups = []
        for row in self.existing_groups:
            if not isinstance(row, (tuple, list)) or len(row) != 2:
                raise NeoEditorError("Group inventory rows require application/group pairs")
            application, group = row
            if (type(application) is not int or type(group) is not int
                    or not 0 <= application <= 255 or not 0 <= group <= 254):
                raise NeoEditorError("Group inventory requires integer application 0..255 and group 0..254")
            groups.append((application, group))
        if len(set(groups)) != len(groups):
            raise NeoEditorError("Duplicate caller group facts are unsupported")
        object.__setattr__(self, "existing_groups", tuple(groups))

    def __eq__(self, other):
        if type(other) is not type(self):
            return NotImplemented
        return (_same_typed_value(self.values, other.values)
                and _same_typed_value(self.memory.data, other.memory.data)
                and _same_typed_value(self.graph_bytes, other.graph_bytes)
                and _same_typed_value(self.existing_groups, other.existing_groups))

    def as_dict(self):
        return {"values": _thaw(self.values), "memory": self.memory.as_dict(),
                "graph_sha256": sha256(self.graph_bytes).hexdigest(),
                "graph_bytes": len(self.graph_bytes),
                "existing_groups": [list(row) for row in self.existing_groups],
                "snapshot_provenance": "caller supplied; not externally verified"}


@dataclass(frozen=True)
class NeoEvent:
    action: str
    draft_revision: int
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "details", _freeze(self.details))

    def as_dict(self):
        return {"action": self.action, "draft_revision": self.draft_revision,
                "details": _thaw(self.details)}


@dataclass(frozen=True)
class NeoEditor:
    """Immutable opening/applied/working state; all methods return new state."""

    profile: NeoProfile
    opening: NeoSnapshot
    applied: NeoSnapshot
    working: NeoSnapshot
    draft_revision: int = 0
    applied_revision: int = 0
    is_open: bool = True
    destination_action: str | None = None
    local_apply_count: int = 0
    history: tuple[NeoEvent, ...] = ()
    _spec: UnitSpec = field(repr=False, compare=False, default=None)

    @classmethod
    def open(cls, spec: UnitSpec, profile: NeoProfile, snapshot: NeoSnapshot):
        if not isinstance(profile, NeoProfile) or not isinstance(snapshot, NeoSnapshot):
            raise NeoEditorError("Supply a NeoProfile and NeoSnapshot")
        spec = _frozen_spec(spec)
        if spec.filename != "KEYM4.xml" or spec.unit_type != profile.unit_type:
            raise NeoEditorError("This editor requires the exact KEYM4.xml profile")
        if set(spec.parameters) != set(LAYOUTS):
            raise NeoEditorError("Only the exact synthetic Neo parameter layouts are admitted; "
                                 "extra or missing declared parameters are unsupported")
        keys = ExtendedKeys(spec)
        if not spec.supports_version(profile.firmware):
            raise NeoEditorError("Specification does not admit the pinned firmware")
        if not set(spec.parameters).issubset(snapshot.values):
            raise NeoEditorError("Caller PP snapshot omits declared specification fields")
        cls._check_snapshot(keys, snapshot)
        return cls(profile, snapshot, snapshot, snapshot,
                   history=(NeoEvent("open", 0),), _spec=spec)

    @staticmethod
    def _check_snapshot(keys, snapshot):
        try:
            values = keys._snapshot(snapshot.values)
            for name, expected in values.items():
                decoded = keys.codec.decode(name, snapshot.memory)
                actual = tuple(decoded) if isinstance(decoded, list) else (decoded,)
                if actual != expected:
                    raise NeoEditorError("Caller PP and logical memory disagree: " + name)
        except (MacroError, MemoryError) as error:
            raise NeoEditorError(str(error)) from error

    @property
    def dirty(self):
        return self.working != self.applied

    def _ready(self, *, pending=False):
        if not self.is_open:
            raise NeoEditorError("Editor is already closed")
        if pending != (self.destination_action is not None):
            raise NeoEditorError("Destination selection is " + ("required" if pending else "already open"))

    def _event(self, action, *, details=None, **updates):
        revision = updates.get("draft_revision", self.draft_revision)
        return replace(self, history=self.history + (NeoEvent(action, revision, details or {}),), **updates)

    def _project(self, keys, plan, action):
        final = {**plan.expected, **plan.changes}
        mask = final["BlockAllocation"][plan.key - 1]
        if not mask or mask & (mask - 1):
            raise NeoEditorError("An ordinary key requires one explicit block")
        if any(assigned & mask for index, assigned in enumerate(final["BlockAllocation"])
               if index != plan.key - 1):
            raise NeoEditorError("Shared block edits are outside this preparatory editor")
        application = final["Application"][int(bool(final["SecondApplicationBlocks"][0] & mask))]
        if not 48 <= application <= 95:
            raise NeoEditorError("Only ordinary Lighting applications 48..95 are admitted")
        group = final["GroupAddress"][mask.bit_length() - 1]
        if group != 255 and (application, group) not in self.working.existing_groups:
            raise NeoEditorError("Group must already exist in the supplied inventory; Add is unsupported")
        if plan.shared_keys:
            raise NeoEditorError("Shared block edits are outside this preparatory editor")
        patch = keys.codec.encode_many(plan.changes)
        # Whole-byte MemoryPatch writes can establish new bytes. This editor
        # explicitly refuses that behavior to preserve returned validity.
        for edit in patch.edits:
            self.working.memory.byte(edit.address)
        values = dict(self.working.values)
        for name, final in plan.changes.items():
            original = values[name]
            values[name] = " ".join(map(str, final)) if isinstance(original, str) else (
                final[0] if isinstance(original, int) else final)
        snapshot = NeoSnapshot(values, patch.apply(self.working.memory),
                               self.working.graph_bytes, self.working.existing_groups)
        self._check_snapshot(keys, snapshot)
        revision = self.draft_revision + int(snapshot != self.working)
        return self._event(action, details=plan.as_dict(), working=snapshot, draft_revision=revision)

    def edit_preset(self, **options):
        self._ready()
        if options.get("allow_shared_block", False) is not False:
            raise NeoEditorError("Explicit shared block editing is unsupported")
        if options.get("preset") in TRIGGER_PRESETS:
            raise NeoEditorError("Trigger presets are outside the ordinary Lighting editor")
        keys = ExtendedKeys(self._spec)
        try:
            plan = keys.plan(self.working.values, **options)
            return self._project(keys, plan, "edit_preset")
        except (MacroError, MemoryError) as error:
            raise NeoEditorError(str(error)) from error

    def edit_micro_functions(self, *, key, stages):
        self._ready()
        keys = ExtendedKeys(self._spec)
        try:
            plan = keys.plan_micro_functions(self.working.values, key=key, stages=stages)
            return self._project(keys, plan, "edit_micro_functions")
        except (MacroError, MemoryError) as error:
            raise NeoEditorError(str(error)) from error

    def _request(self, action):
        self._ready()
        if not self.dirty:
            raise NeoEditorError("There is no unapplied local draft")
        return self._event("request_" + action, destination_action=action)

    def request_apply(self):
        return self._request("apply")

    def request_ok(self):
        return self._request("ok")

    def cancel_destination(self):
        self._ready(pending=True)
        return self._event("cancel_destination", details={"invoked_by": self.destination_action},
                           destination_action=None)

    def confirm_database(self, *, current: NeoSnapshot, destination="database",
                         entire_unit=False, dlt_labels=False, changed_only=False):
        """Accept the local proposal under the policy, without saving anything.

        ``current`` is an exact caller baseline comparison, not a live read.
        Flags for native Save Unit choices fail closed; their semantics need
        original captures and a separately authorized persistence adapter.
        """
        self._ready(pending=True)
        if destination != "database" or any(flag is not False for flag in (
                entire_unit, dlt_labels, changed_only)):
            raise NeoEditorError("Only local database proposal acceptance is supported")
        if not isinstance(current, NeoSnapshot) or current != self.applied:
            raise NeoEditorError("Caller baseline differs from the applied snapshot")
        self._check_snapshot(ExtendedKeys(self._spec), self.working)
        closes = self.destination_action == "ok"
        return self._event("accept_database_proposal", details={"invoked_by": self.destination_action},
                           applied=self.working, applied_revision=self.draft_revision,
                           destination_action=None, is_open=not closes,
                           local_apply_count=self.local_apply_count + 1)

    def cancel_editor(self, *, route="cancel"):
        self._ready()
        if route != "cancel":
            raise NeoEditorError("Close/Escape aliases require original capture; use explicit cancel")
        return self._event("cancel_editor", details={"requested_route": route},
                           working=self.applied, is_open=False)

    def as_dict(self):
        changes = {name: _thaw(value) for name, value in self.working.values.items()
                   if name not in self.applied.values
                   or not _same_typed_value(value, self.applied.values[name])}
        return {"format": "cbus-offline-neo-editor-v1", "policy": POLICY,
                "original_terminal_semantics": ORIGINAL_TERMINAL_SEMANTICS,
                "profile": self.profile.as_dict(), "is_open": self.is_open, "dirty": self.dirty,
                "draft_revision": self.draft_revision, "applied_revision": self.applied_revision,
                "destination_action": self.destination_action, "local_apply_count": self.local_apply_count,
                "opening": self.opening.as_dict(), "applied": self.applied.as_dict(),
                "working": self.working.as_dict(), "changes_from_applied": changes,
                "history": [event.as_dict() for event in self.history],
                "saved": False, "pp_save_count": 0, "project_save_count": 0,
                "external_persistence_verified": False, "native_acceptance": False,
                "physical_acceptance": False, "eager_graph_effects_observed": False,
                "io_performed": False}
