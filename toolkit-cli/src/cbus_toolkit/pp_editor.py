"""Transactional PP edits for small, layout-pinned Toolkit dialog workflows.

An editor names every parameter it reads, with the exact layout it was proven
against. Plans are immutable snapshots; application checks the native unit
type and schema, rejects stale snapshots, sends whole parameters, verifies
readback and restores attempted parameters on failure. Nothing is saved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from .memory import MemoryCodec, MemoryError
from .programming import xml_text


class PPEditError(ValueError):
    pass


class PPApplyError(RuntimeError):
    def __init__(self, cause, rollback_errors=()):
        self.cause = cause
        self.rollback_errors = tuple(rollback_errors)
        super().__init__("PP edit failed; " + ("rollback had errors" if rollback_errors else "changed parameters were restored") + ": " + str(cause))


def integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise PPEditError(label + " must be an integer")
    return value


def boolean(value, label):
    if not isinstance(value, bool):
        raise PPEditError(label + " must be true or false")
    return value


def parse_values(value) -> tuple[int, ...]:
    tokens = value.split() if isinstance(value, str) else value if isinstance(value, (list, tuple)) else [value]
    result = []
    for token in tokens:
        if isinstance(token, bool):
            result.append(int(token))
            continue
        text = str(token).strip().lower()
        if text in ("true", "false"):
            result.append(int(text == "true"))
            continue
        try:
            result.append(int(text.replace("$", "0x"), 0) if text.startswith(("$", "0x", "0b")) else int(text, 10))
        except ValueError as exc:
            raise PPEditError("Expected numeric PP parameter values") from exc
    return tuple(result)


@dataclass(frozen=True)
class PPPlan:
    format: str
    unit_type: str
    spec_filename: str
    expected: Mapping[str, tuple[int, ...]]
    changes: Mapping[str, tuple[int, ...]]
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("expected", "changes"):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))

    def as_dict(self):
        return {"format": self.format, "unit_type": self.unit_type, "spec_filename": self.spec_filename,
                **dict(self.details), "expected": {k: list(v) for k, v in self.expected.items()},
                "changes": {k: list(v) for k, v in self.changes.items()}, "saved": False}


class PPEditor:
    """Base class; subclasses set FORMAT and pass their pinned layouts."""
    FORMAT = "cbus-pp-edit-v1"

    def __init__(self, spec, unit_type: str, layouts: Mapping[str, tuple]):
        self.spec = spec
        self.unit_type = unit_type
        self.layouts = MappingProxyType(dict(layouts))
        self.codec = MemoryCodec(spec)
        try:
            for name, expected in self.layouts.items():
                layout = self.codec.layout(name)
                shape = (layout.parameter.type, layout.address, layout.array_size, layout.bit_size,
                         layout.bit_address, layout.array_skip)
                if shape != expected:
                    raise PPEditError("Unsupported parameter layout: " + name)
        except MemoryError as exc:
            raise PPEditError(str(exc)) from exc

    def snapshot(self, values: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
        result = {}
        for name in self.layouts:
            if name not in values:
                raise PPEditError("Current PP values are missing " + name)
            parsed = parse_values(values[name])
            valid = self.spec.get(name).validate_value(list(parsed))
            if not valid["valid"]:
                raise PPEditError(f"Invalid current {name}: " + "; ".join(valid["errors"]))
            result[name] = parsed
        return result

    def make_plan(self, original, updates, details) -> PPPlan:
        changes = {name: tuple(values) for name, values in updates.items() if tuple(values) != original[name]}
        for name, values in changes.items():
            valid = self.spec.get(name).validate_value(list(values))
            if not valid["valid"]:
                raise PPEditError(f"Invalid planned {name}: " + "; ".join(valid["errors"]))
        try:
            self.codec.encode_many(changes)
        except MemoryError as exc:
            raise PPEditError(str(exc)) from exc
        return PPPlan(self.FORMAT, self.unit_type, self.spec.filename, original, changes, details)

    def _verify_session(self, session):
        if getattr(session, "unit_type", None) != self.unit_type:
            raise PPEditError("Programming session unit type differs from the plan")
        document = xml_text(session.info("*"))
        if "<!DOCTYPE" in document.upper() or "<!ENTITY" in document.upper():
            raise PPEditError("Unsupported native schema declarations")
        try:
            root = ET.fromstring(document)
        except ET.ParseError as exc:
            raise PPEditError("Invalid native parameter schema") from exc
        fields = {}
        for param in root.iter():
            if param.tag.rsplit("}", 1)[-1] == "Param":
                row = {child.tag.rsplit("}", 1)[-1]: child.text or "" for child in param}
                if row.get("Name") in fields:
                    raise PPEditError("Duplicate native parameter schema")
                fields[row.get("Name")] = row
        for name in self.layouts:
            native, local = fields.get(name, {}), self.spec.get(name).fields
            if native.get("Type", "").lower() != self.spec.get(name).type:
                raise PPEditError("Native parameter type mismatch: " + name)
            for key, default in (("Address", None), ("ArraySize", "1"), ("BitSize", "8"), ("BitAddress", "0"), ("ArraySkip", "0")):
                if parse_values(native.get(key, default) or "") != parse_values(local.get(key, default) or ""):
                    raise PPEditError(f"Native parameter layout mismatch: {name}/{key}")

    def apply(self, session, plan: PPPlan):
        if not isinstance(plan, PPPlan) or (plan.format, plan.unit_type, plan.spec_filename) != (self.FORMAT, self.unit_type, self.spec.filename):
            raise PPEditError("Plan differs from this editor")
        if set(plan.expected) != set(self.layouts) or any(name not in self.layouts for name in plan.changes):
            raise PPEditError("Plan contains fields outside this workflow")
        try:
            self.codec.encode_many(plan.changes)
        except MemoryError as exc:
            raise PPEditError(str(exc)) from exc
        self._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise PPEditError("PP parameters changed since this plan was created")
        attempted = []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, " ".join(str(value) for value in values))
            expected = {**plan.expected, **plan.changes}
            if self.snapshot(session.values()) != expected:
                raise PPEditError("Native readback differs from the plan")
        except Exception as error:
            rollback_errors = []
            for name in reversed(attempted):
                try:
                    session.set(name, " ".join(str(value) for value in plan.expected[name]))
                except Exception as rollback:
                    rollback_errors.append(str(rollback))
            try:
                if self.snapshot(session.values()) != dict(plan.expected):
                    rollback_errors.append("Original parameters were not restored")
            except Exception as rollback:
                rollback_errors.append(str(rollback))
            raise PPApplyError(error, rollback_errors) from error
        return {**plan.as_dict(), "verified": True, "device_verified": False}
