"""Pure catalogue inspection/selection and proposed bulk Group draft validation.

All inputs are caller-supplied values or bytes. No files, sockets, native calls,
UUID allocation or project edits occur here. The two explicit profiles describe
conservative offline policies, not original chooser/grid compatibility. A
catalogue selection does not admit a Unit creation schema or default PP state;
a valid Group draft does not admit a replacement XML graph or database write.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any
import unicodedata
import xml.etree.ElementTree as ET
from xml.parsers import expat

from ..project import ProjectError, _address, _xml_string
from ..unitspec import MAX_SPEC_BYTES, UnitSpecError, compare_versions, version_matches

CATALOGUE_PROFILE = "proposed-offline-catalogue-v1"
GROUP_PROFILE = "proposed-offline-groups-v1"
GROUP_ROWS_FORMAT = "cbus-offline-group-rows-v1"


class CatalogueGroupsError(ValueError):
    """A refused pure input/selection; ``code`` is stable for callers."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _refuse(message: str, code: str) -> None:
    raise CatalogueGroupsError(message, code=code)


def _profile(actual: str, expected: str) -> None:
    if actual != expected:
        _refuse("Unknown profile; original/native behavior is not admitted", "unsupported_profile")


def _fields(node: ET.Element) -> tuple[tuple[str, str], ...]:
    # Retain repetitions and exact parsed values rather than last-value wins.
    return tuple((child.tag, child.text or "") for child in node)


def _scalar(fields: tuple[tuple[str, str], ...], name: str,
            diagnostics: list[str], *, required: bool = False) -> str | None:
    values = [value for key, value in fields if key == name]
    if len(values) > 1:
        diagnostics.append("ambiguous_" + name)
        return None
    if not values:
        if required:
            diagnostics.append("missing_" + name)
        return None
    if required and not values[0].strip():
        diagnostics.append("missing_" + name)
    return values[0]


def _boolean(value: str | None) -> bool | None:
    if value is None:
        return None
    return {"true": True, "false": False}.get(value.strip().lower())


def _title_fields(title: str | None) -> tuple[tuple[str, str], ...]:
    return tuple((key.strip().lower(), value.strip())
                 for segment in (title or "").split(";") if "=" in segment
                 for key, value in [segment.split("=", 1)])


@dataclass(frozen=True)
class CatalogueRevision:
    item_id: str
    revision_index: int
    source_path: str
    raw_fields: tuple[tuple[str, str], ...]
    unit_type: str | None
    minimum_version: str | None
    maximum_version: str | None
    spec_filename: str | None
    is_default: bool | None
    diagnostics: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"item_id": self.item_id, "revision_index": self.revision_index,
                "source_path": self.source_path, "raw_fields": list(self.raw_fields),
                "unit_type": self.unit_type, "minimum_version": self.minimum_version,
                "maximum_version": self.maximum_version, "spec_filename": self.spec_filename,
                "is_default": self.is_default, "diagnostics": list(self.diagnostics)}


@dataclass(frozen=True)
class CatalogueUnit:
    unit_id: str
    source_path: str
    raw_fields: tuple[tuple[str, str], ...]
    catalog_number: str | None
    alternative_catalog_numbers: str | None
    unit_title: str | None
    family: str | None
    category: str | None
    is_addressable: bool | None
    hide_in_catalog: bool | None
    revisions: tuple[CatalogueRevision, ...]
    diagnostics: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"unit_id": self.unit_id, "source_path": self.source_path,
                "raw_fields": list(self.raw_fields), "catalog_number": self.catalog_number,
                "alternative_catalog_numbers": self.alternative_catalog_numbers,
                "unit_title": self.unit_title, "family": self.family, "category": self.category,
                "is_addressable": self.is_addressable, "hide_in_catalog": self.hide_in_catalog,
                "revisions": [item.as_dict() for item in self.revisions],
                "diagnostics": list(self.diagnostics)}


@dataclass(frozen=True)
class CatalogueSelection:
    catalogue_sha256: str
    unit: CatalogueUnit
    revision: CatalogueRevision
    firmware: str
    mode: str

    def as_dict(self) -> dict[str, Any]:
        return {"profile": CATALOGUE_PROFILE, "catalogue_sha256": self.catalogue_sha256,
                "unit_id": self.unit.unit_id, "item_id": self.revision.item_id,
                "source_path": self.revision.source_path, "mode": self.mode,
                "catalog_number": self.unit.catalog_number, "unit_type": self.revision.unit_type,
                "firmware": self.firmware, "spec_filename": self.revision.spec_filename,
                "creation_admitted": False, "default_pp_admitted": False,
                "native_compatibility_verified": False}


@dataclass(frozen=True)
class CatalogueIndex:
    snapshot: bytes
    sha256: str
    units: tuple[CatalogueUnit, ...]

    @classmethod
    def from_bytes(cls, data: bytes) -> CatalogueIndex:
        """Index all Units and revisions, preserving source order and identity."""
        if type(data) is not bytes or len(data) > MAX_SPEC_BYTES:
            _refuse("Catalogue must be bytes within the specification size limit", "invalid_catalogue")
        checker = expat.ParserCreate()
        def reject(*_args: Any) -> None:
            _refuse("DTD/entity declarations are unsupported", "invalid_catalogue")
        checker.StartDoctypeDeclHandler = reject
        try:
            checker.Parse(data, True)
            root = ET.fromstring(data)
        except (expat.ExpatError, ET.ParseError) as exc:
            raise CatalogueGroupsError("Invalid catalogue XML", code="invalid_catalogue") from exc
        if root.tag != "CBusUnits" or any(not isinstance(node.tag, str) or "}" in node.tag
                                          for node in root.iter()):
            _refuse("Only the explicit unnamespaced CBusUnits profile is supported", "unsupported_catalogue_shape")
        # Refuse unsupported wrappers rather than silently omit their typed
        # descendants from an apparently complete source index.
        owners = {"Units": {"CBusUnits"}, "Unit": {"Units", "SubUnits"},
                  "SubUnits": {"Unit"}, "FirmwareRevisions": {"Unit"},
                  "Revision": {"FirmwareRevisions"}}
        children = {"Units": "Unit", "SubUnits": "Unit", "FirmwareRevisions": "Revision"}
        pending = [(root, None)]
        while pending:
            node, parent_tag = pending.pop()
            if node.tag in owners and parent_tag not in owners[node.tag]:
                _refuse("Catalogue structural node has an unsupported owner", "unsupported_catalogue_shape")
            if node.tag in children and any(child.tag != children[node.tag] for child in node):
                _refuse("Catalogue structural container has unsupported children", "unsupported_catalogue_shape")
            if node is root and any(child.tag != "Units" and len(child) for child in node):
                _refuse("Catalogue root contains an unsupported nested wrapper", "unsupported_catalogue_shape")
            pending.extend((child, node.tag) for child in node)
        digest = hashlib.sha256(data).hexdigest()
        units: list[CatalogueUnit] = []
        def visit(unit: ET.Element, path: str) -> None:
            fields = _fields(unit)
            problems: list[str] = []
            for child in unit:
                if child.tag not in {"FirmwareRevisions", "SubUnits"} and len(child):
                    problems.append("nested_scalar_" + child.tag)
            number = _scalar(fields, "CatalogNumber", problems, required=True)
            alternatives = _scalar(fields, "AlternativeCatalogNumbers", problems)
            title = _scalar(fields, "UnitTitle", problems)
            title_fields = _title_fields(title)
            family = _scalar(title_fields, "family", problems)
            category = _scalar(title_fields, "category", problems)
            addressable = _boolean(_scalar(fields, "IsAddressable", problems))
            declarations = [value for key, value in fields if key == "HideInCatalog"]
            declarations.extend(value for key, value in title_fields if key == "hideincatalog")
            hidden = _boolean(declarations[0]) if len(declarations) == 1 else None
            if len(declarations) > 1:
                problems.append("ambiguous_HideInCatalog")
            if addressable is None:
                problems.append("unresolved_IsAddressable")
            elif not addressable:
                problems.append("non_addressable")
            if hidden is None:
                problems.append("unresolved_HideInCatalog")
            elif hidden:
                problems.append("hidden_in_catalog")
            unit_id = digest + ":" + path
            revisions: list[CatalogueRevision] = []
            for container_index, container in enumerate(unit.findall("FirmwareRevisions"), 1):
                for revision_index, revision in enumerate(container.findall("Revision"), 1):
                    revision_path = f"{path}/FirmwareRevisions[{container_index}]/Revision[{revision_index}]"
                    raw = _fields(revision)
                    issues = ["nested_scalar_" + child.tag for child in revision if len(child)]
                    kind = _scalar(raw, "UnitType", issues, required=True)
                    minimum = _scalar(raw, "MinVersion", issues, required=True)
                    maximum = _scalar(raw, "MaxVersion", issues)
                    spec = _scalar(raw, "UnitSpecName", issues, required=True)
                    default = _boolean(_scalar(raw, "IsDefault", issues))
                    if default is None:
                        issues.append("unresolved_IsDefault")
                    try:
                        if minimum:
                            compare_versions(minimum, minimum)
                        if maximum:
                            compare_versions(maximum, maximum)
                        if minimum and maximum and compare_versions(minimum, maximum) > 0:
                            issues.append("invalid_firmware_range")
                    except UnitSpecError:
                        issues.append("invalid_firmware_range")
                    revisions.append(CatalogueRevision(digest + ":" + revision_path,
                        len(revisions) + 1, revision_path, raw, kind, minimum, maximum, spec,
                        default, tuple(issues)))
            if not revisions:
                problems.append("missing_revisions")
            defaults = sum(item.is_default is True for item in revisions)
            if defaults == 0:
                problems.append("missing_default")
            elif defaults > 1:
                problems.append("multiple_defaults")
            units.append(CatalogueUnit(unit_id, path, fields, number, alternatives, title,
                family, category, addressable, hidden, tuple(revisions), tuple(problems)))
            for container_index, container in enumerate(unit.findall("SubUnits"), 1):
                for child_index, child in enumerate(container.findall("Unit"), 1):
                    visit(child, f"{path}/SubUnits[{container_index}]/Unit[{child_index}]")
        for container_index, container in enumerate(root.findall("Units"), 1):
            for unit_index, unit in enumerate(container.findall("Unit"), 1):
                visit(unit, f"/CBusUnits/Units[{container_index}]/Unit[{unit_index}]")
        if not units:
            _refuse("Catalogue contains no source Units", "invalid_catalogue")
        return cls(data, digest, tuple(units))

    def as_dict(self) -> dict[str, Any]:
        return {"catalogue_sha256": self.sha256, "units": [unit.as_dict() for unit in self.units],
                "profile": CATALOGUE_PROFILE, "native_compatibility_verified": False}

    def _select(self, unit: CatalogueUnit, revision: CatalogueRevision,
                firmware: str, mode: str) -> CatalogueSelection:
        # Default diagnostics are relevant to default mode only. An explicit
        # revision can select a source Unit with no/multiple declared defaults.
        eligibility = [problem for problem in unit.diagnostics
                       if problem not in {"missing_default", "multiple_defaults"}]
        revision_problems = [problem for problem in revision.diagnostics
                             if mode == "default" or problem != "unresolved_IsDefault"]
        if eligibility or revision_problems:
            _refuse("Unresolved/ineligible catalogue entry: " + ", ".join(eligibility + revision_problems),
                    "catalogue_ineligible")
        if type(firmware) is not str or not firmware.strip():
            _refuse("Explicit firmware must be a nonempty string", "invalid_firmware")
        try:
            matches = version_matches(firmware, revision.minimum_version or "", revision.maximum_version or "")
        except UnitSpecError as exc:
            raise CatalogueGroupsError(str(exc), code="invalid_firmware") from exc
        if not matches:
            _refuse("Firmware is outside this exact source revision", "firmware_out_of_range")
        return CatalogueSelection(self.sha256, unit, revision, firmware, mode)

    def select_revision(self, item_id: str, firmware: str, *, profile: str) -> CatalogueSelection:
        _profile(profile, CATALOGUE_PROFILE)
        for unit in self.units:
            for revision in unit.revisions:
                if revision.item_id == item_id:
                    return self._select(unit, revision, firmware, "explicit")
        _refuse("Revision identity is absent from these exact catalogue bytes", "unknown_item")

    def select_default(self, unit_id: str, *, profile: str) -> CatalogueSelection:
        _profile(profile, CATALOGUE_PROFILE)
        for unit in self.units:
            if unit.unit_id == unit_id:
                defaults = [revision for revision in unit.revisions if revision.is_default is True]
                if len(defaults) != 1 or any(revision.is_default is None for revision in unit.revisions):
                    _refuse("Exact source Unit must have one unambiguous declared default", "ambiguous_default")
                return self._select(unit, defaults[0], defaults[0].minimum_version or "", "default")
        _refuse("Unit identity is absent from these exact catalogue bytes", "unknown_item")


@dataclass(frozen=True)
class GroupRow:
    row_id: str
    address: int | str
    tag_name: str

    def __post_init__(self) -> None:
        if type(self.row_id) is not str or not self.row_id or self.row_id != self.row_id.strip():
            _refuse("Row identity must be explicit nonempty text without surrounding whitespace", "invalid_row_id")
        if any(unicodedata.category(char) == "Cc" for char in self.row_id):
            _refuse("Row identity contains a control character", "invalid_row_id")
        if type(self.address) not in (int, str) or type(self.tag_name) is not str:
            _refuse("Rows require an integer/text address and text TagName", "invalid_rows")

    def as_dict(self) -> dict[str, Any]:
        return {"row_id": self.row_id, "address": self.address, "tag_name": self.tag_name}


@dataclass(frozen=True)
class GroupDraft:
    rows: tuple[GroupRow, ...] = ()
    state: str = "editing"

    def __post_init__(self) -> None:
        if type(self.rows) is not tuple or any(type(row) is not GroupRow for row in self.rows):
            _refuse("Draft rows must be an immutable tuple of GroupRow", "invalid_rows")
        if len({row.row_id for row in self.rows}) != len(self.rows):
            _refuse("Draft row identities must be unique", "duplicate_row_id")
        if type(self.state) is not str or self.state not in {"editing", "cancelled"} or self.state == "cancelled" and self.rows:
            _refuse("Invalid draft state", "invalid_draft_state")

    def _editing(self) -> None:
        if self.state != "editing":
            _refuse("Cancelled drafts cannot be reused", "draft_cancelled")

    def add(self, row: GroupRow) -> GroupDraft:
        self._editing()
        return GroupDraft(self.rows + (row,))

    def edit(self, row_id: str, *, address: int | str, tag_name: str) -> GroupDraft:
        self._editing()
        if not any(row.row_id == row_id for row in self.rows):
            _refuse("Unknown draft row identity", "unknown_row")
        return GroupDraft(tuple(GroupRow(row_id, address, tag_name) if row.row_id == row_id else row
                                for row in self.rows))

    def delete(self, row_id: str) -> GroupDraft:
        self._editing()
        if not any(row.row_id == row_id for row in self.rows):
            _refuse("Unknown draft row identity", "unknown_row")
        return GroupDraft(tuple(row for row in self.rows if row.row_id != row_id))

    def cancel(self) -> GroupDraft:
        self._editing()
        return GroupDraft((), "cancelled")


def parse_group_rows(data: bytes) -> GroupDraft:
    """Parse one complete versioned JSON document; this is not Toolkit paste."""
    if type(data) is not bytes or len(data) > MAX_SPEC_BYTES:
        _refuse("Group input must be bounded bytes", "invalid_rows")
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _refuse("Duplicate JSON field", "invalid_rows")
            result[key] = value
        return result
    try:
        payload = json.loads(data, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, CatalogueGroupsError):
            raise
        raise CatalogueGroupsError("Invalid complete Group JSON document", code="invalid_rows") from exc
    if type(payload) is not dict or set(payload) != {"format", "rows"} or payload["format"] != GROUP_ROWS_FORMAT:
        _refuse("Expected the explicit versioned Group row document", "unsupported_rows_format")
    if type(payload["rows"]) is not list:
        _refuse("rows must be an ordered array", "invalid_rows")
    rows: list[GroupRow] = []
    for row in payload["rows"]:
        if type(row) is not dict or set(row) != {"row_id", "address", "tag_name"}:
            _refuse("Every row requires exactly row_id/address/tag_name", "invalid_rows")
        rows.append(GroupRow(**row))
    return GroupDraft(tuple(rows))


@dataclass(frozen=True)
class GroupPolicy:
    """Caller-selected proposed policy; no implicit native reserved/name rules."""
    allowed_addresses: tuple[int, ...]
    capacity: int
    duplicate_names: str
    max_tag_name_chars: int | None = None
    profile: str = GROUP_PROFILE

    def __post_init__(self) -> None:
        _profile(self.profile, GROUP_PROFILE)
        if type(self.allowed_addresses) is not tuple or not self.allowed_addresses:
            _refuse("Address domain must be an explicit nonempty tuple", "invalid_group_policy")
        if any(type(value) is not int or not 0 <= value <= 255 for value in self.allowed_addresses):
            _refuse("Address domain must contain integer bytes", "invalid_group_policy")
        if len(set(self.allowed_addresses)) != len(self.allowed_addresses):
            _refuse("Address domain contains duplicates", "invalid_group_policy")
        if type(self.capacity) is not int or not 0 <= self.capacity <= len(self.allowed_addresses):
            _refuse("Capacity must be explicit and fit the address domain", "invalid_group_policy")
        if type(self.duplicate_names) is not str or self.duplicate_names not in {"allow", "reject-exact"}:
            _refuse("Explicit duplicate-name policy is required", "invalid_group_policy")
        if self.max_tag_name_chars is not None and (type(self.max_tag_name_chars) is not int or self.max_tag_name_chars < 1):
            _refuse("Name limit must be an explicit positive character count", "invalid_group_policy")


@dataclass(frozen=True)
class GroupValidation:
    target_identity: str
    baseline_sha256: str
    policy: GroupPolicy
    rows: tuple[GroupRow, ...]
    errors: tuple[tuple[str | None, str], ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {"profile": GROUP_PROFILE, "target_identity": self.target_identity,
                "baseline_sha256": self.baseline_sha256, "valid": self.valid,
                "proposed_rows": [row.as_dict() for row in self.rows],
                "accepted_rows": [row.as_dict() for row in self.rows] if self.valid else [],
                "errors": [{"row_id": row_id, "code": code} for row_id, code in self.errors],
                "policy": {"allowed_addresses": list(self.policy.allowed_addresses),
                           "capacity": self.policy.capacity, "duplicate_names": self.policy.duplicate_names,
                           "max_tag_name_chars": self.policy.max_tag_name_chars},
                "replacement_graph_admitted": False, "native_compatibility_verified": False}


def _canonical_address(value: int | str) -> int:
    if type(value) is int:
        return _address(value)
    if type(value) is not str or not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise ProjectError("Canonical decimal byte address required")
    return _address(value)


def validate_group_draft(draft: GroupDraft, *, existing_groups: tuple[GroupRow, ...],
                         policy: GroupPolicy, target_identity: str,
                         baseline_sha256: str) -> GroupValidation:
    """Validate all rows together against explicit caller baseline facts.

    The digest identifies the supplied baseline; this function cannot establish
    that the caller's existing rows exhaust a graph, or that it is serializable.
    """
    if type(draft) is not GroupDraft or type(policy) is not GroupPolicy:
        _refuse("Explicit draft and proposed policy are required", "invalid_group_policy")
    draft._editing()
    _profile(policy.profile, GROUP_PROFILE)
    if type(target_identity) is not str or not target_identity or target_identity != target_identity.strip():
        _refuse("Exact nonempty target identity is required", "invalid_target")
    if type(baseline_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", baseline_sha256):
        _refuse("Exact lowercase baseline SHA256 is required", "invalid_baseline")
    if type(existing_groups) is not tuple or any(type(row) is not GroupRow for row in existing_groups):
        _refuse("Existing Group facts must be an immutable tuple", "invalid_baseline")
    errors: list[tuple[str | None, str]] = []
    occupied: set[int] = set()
    names: set[str] = set()
    for existing in existing_groups:
        try:
            # A baseline may retain legacy numeric aliases. Normalize them with
            # the owning project parser solely to detect occupied identities.
            address = _address(existing.address)
        except ProjectError:
            errors.append((None, "invalid_existing_address"))
            continue
        if address in occupied:
            errors.append((None, "ambiguous_existing_address"))
        occupied.add(address)
        names.add(existing.tag_name)
        if address not in policy.allowed_addresses:
            errors.append((None, "existing_address_outside_policy"))
    if len(existing_groups) + len(draft.rows) > policy.capacity:
        errors.append((None, "capacity_exceeded"))
    staged: set[int] = set()
    staged_names: set[str] = set()
    for row in draft.rows:
        try:
            address = _canonical_address(row.address)
        except ProjectError:
            errors.append((row.row_id, "invalid_address"))
        else:
            if address not in policy.allowed_addresses:
                errors.append((row.row_id, "address_outside_policy"))
            if address in occupied:
                errors.append((row.row_id, "existing_address_collision"))
            if address in staged:
                errors.append((row.row_id, "duplicate_staged_address"))
            staged.add(address)
        try:
            _xml_string(row.tag_name)
            valid_name = bool(row.tag_name) and row.tag_name == row.tag_name.strip() and not any(
                unicodedata.category(char) == "Cc" for char in row.tag_name)
        except ProjectError:
            valid_name = False
        if not valid_name:
            errors.append((row.row_id, "invalid_tag_name"))
        if policy.max_tag_name_chars is not None and len(row.tag_name) > policy.max_tag_name_chars:
            errors.append((row.row_id, "tag_name_too_long"))
        if policy.duplicate_names == "reject-exact" and (row.tag_name in names or row.tag_name in staged_names):
            errors.append((row.row_id, "duplicate_tag_name"))
        staged_names.add(row.tag_name)
    return GroupValidation(target_identity, baseline_sha256, policy, draft.rows, tuple(errors))
