"""Typed physical PP workflows for cmqttd's topology-aware C-Gate service.

The generic :mod:`cbus_toolkit.programming` API intentionally exposes native
PP primitives.  This module adds the safety and evidence boundary needed for a
physical unit: require cmqttd's live capability declaration, bind each edit to
one schema ``ProgramMethod``, issue a single SAVE/SAVE_TO_SOURCE, and compare a
fresh physical LOAD with the values staged before that save.

Neither the successful C-Gate reply nor the fresh readback proves persistence
through a power cycle.  No state-changing command is retried automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping, Protocol
from uuid import uuid4

from .programming import (
    Programmer,
    ProgrammingError,
    _integer_value,
    _parameter_name,
    quote_value,
    xml_text,
)


SUPPORTED_METHODS = (
    "direct",
    "paged",
    "ncc",
    "edlt",
    "giu",
    "sgiu",
    "dali",
    "goc",
    "gocbyt",
    "goc2",
)
_METHOD_SET = frozenset(SUPPORTED_METHODS)
_UNIT_PATH = re.compile(
    r"//(?P<project>[A-Za-z0-9_]{1,8})/(?P<network>[0-9]{1,3})/p/"
    r"(?P<unit>[0-9]{1,3})"
)


class CommandClient(Protocol):
    def command(self, command: str) -> Any: ...


class PhysicalProgrammingError(ProgrammingError):
    """A guarded physical workflow failure with machine-readable evidence."""

    def __init__(self, message: str, evidence: Mapping[str, Any] | None = None):
        self.evidence = dict(evidence or {})
        self.details = {"physical_programming_evidence": self.evidence}
        super().__init__(message)


@dataclass(frozen=True)
class PhysicalUnitPath:
    value: str
    project: str
    network: int
    unit: int

    @property
    def lock_address(self) -> str:
        return f"//{self.project}/{self.network}"

    @classmethod
    def parse(cls, value: Any, *, label: str = "source") -> "PhysicalUnitPath":
        match = _UNIT_PATH.fullmatch(value) if isinstance(value, str) else None
        if match is None:
            raise ValueError(
                f"Physical PP {label} must be //PROJECT/NETWORK/p/UNIT with unit 1..254"
            )
        network, unit = int(match["network"]), int(match["unit"])
        if network > 255 or not 1 <= unit <= 254:
            raise ValueError(
                f"Physical PP {label} must use a network in 0..255 and unit in 1..254"
            )
        canonical = f"//{match['project']}/{network}/p/{unit}"
        return cls(canonical, match["project"], network, unit)


def physical_unit_path(value: str) -> str:
    """Argparse adapter returning one canonical, uniquely addressed unit."""
    try:
        return PhysicalUnitPath.parse(value).value
    except ValueError as error:
        # Import lazily so the typed core has no parser dependency.
        import argparse
        raise argparse.ArgumentTypeError(str(error)) from error


@dataclass(frozen=True)
class PhysicalParameter:
    name: str
    value_type: str
    array_size: int
    program_method: str
    protection: str
    address: str | None
    tags: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.value_type,
            "array_size": self.array_size,
            "program_method": self.program_method,
            "protection": self.protection,
            "address": self.address,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class PhysicalEdit:
    parameter: str
    requested_value: str

    def as_dict(self) -> dict[str, str]:
        return {"parameter": self.parameter, "requested_value": self.requested_value}


def _method(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Physical PP method must be text")
    method = value.strip().casefold()
    if method not in _METHOD_SET:
        raise ValueError(
            "Physical PP method must be one of " + ", ".join(SUPPORTED_METHODS)
        )
    return method


def _edits(values: Iterable[tuple[str, str]]) -> tuple[PhysicalEdit, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("Physical PP edits must be parameter/value pairs")
    result: list[PhysicalEdit] = []
    seen: set[str] = set()
    for row in values:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise ValueError("Each physical PP edit must contain a parameter and value")
        name, value = row
        name = _parameter_name(name)
        # Exercise the exact native quoting validation before CMQTT preflight or
        # PP LOAD.  ProgrammingSession.set performs the same escaping at issue.
        quote_value(value)
        if len(name) > 1024 or len(value) > 65535:
            raise ValueError("Physical PP parameter names or values exceed the workflow bound")
        if name in seen:
            raise ValueError(f"Physical PP parameter {name!r} was supplied more than once")
        seen.add(name)
        result.append(PhysicalEdit(name, value))
    if not result:
        raise ValueError("Physical PP apply requires at least one --set parameter value")
    if len(result) > 4096:
        raise ValueError("Physical PP apply accepts at most 4096 parameter edits")
    return tuple(result)


def _schema(reply: Any) -> dict[str, PhysicalParameter]:
    document = xml_text(reply)
    if "<!DOCTYPE" in document or "<!ENTITY" in document:
        raise PhysicalProgrammingError("Native parameter XML contains unsupported declarations")
    try:
        root = ET.fromstring(document)
    except ET.ParseError as error:
        raise PhysicalProgrammingError("Malformed native physical parameter XML") from error
    parameters: dict[str, PhysicalParameter] = {}
    for element in root.iter():
        if element.tag != "Param":
            continue
        fields: dict[str, str] = {}
        tags: list[str] = []
        for child in element:
            text = child.text or ""
            if child.tag == "Tag":
                tags.append(text)
            elif child.tag in fields:
                raise PhysicalProgrammingError(
                    f"Native physical schema repeats field {child.tag!r}"
                )
            else:
                fields[child.tag] = text
        name = fields.get("Name", "").strip()
        if not name:
            raise PhysicalProgrammingError("Native physical schema contains an unnamed parameter")
        if name in parameters:
            raise PhysicalProgrammingError(
                f"Native physical schema repeats parameter {name!r}"
            )
        raw_method = fields.get("ProgramMethod", "").strip().casefold()
        method = raw_method or "direct"
        value_type = fields.get("Type", "").strip().casefold()
        try:
            array_size = _integer_value(fields.get("ArraySize") or "1")
        except ProgrammingError as error:
            raise PhysicalProgrammingError(
                f"Native physical schema has invalid ArraySize for {name!r}"
            ) from error
        if not value_type or not 1 <= array_size <= 65536:
            raise PhysicalProgrammingError(
                f"Native physical schema has invalid type or ArraySize for {name!r}"
            )
        parameters[name] = PhysicalParameter(
            name=name,
            value_type=value_type,
            array_size=array_size,
            program_method=method,
            protection=fields.get("Protection", "").strip().casefold() or "none",
            address=fields.get("Address"),
            tags=tuple(tags),
        )
    if not parameters:
        raise PhysicalProgrammingError("Native physical schema contains no parameters")
    return parameters


def _comparable_value(parameter: PhysicalParameter, value: str) -> Any:
    """Canonicalize the value shape that physical encode/decode preserves.

    PP SET retains the caller's spelling in a live session, while a physical
    LOAD returns native decoder spelling (for example ``0x00`` becomes
    ``0x0``).  Comparison therefore follows the declared parameter type rather
    than treating presentation-only changes as a failed device readback.
    """
    if parameter.value_type in ("int", "long", "bit"):
        try:
            values = tuple(_integer_value(token) for token in value.split())
        except ProgrammingError as error:
            raise PhysicalProgrammingError(
                f"Native value for {parameter.name!r} is not a numeric parameter value"
            ) from error
        if len(values) == 1 and parameter.array_size > 1:
            values *= parameter.array_size
        if len(values) != parameter.array_size:
            raise PhysicalProgrammingError(
                f"Native value for {parameter.name!r} has the wrong element count"
            )
        return values
    if parameter.value_type == "sixbit":
        if len(value.rstrip(" ")) > 8:
            raise PhysicalProgrammingError(
                f"Native six-bit value for {parameter.name!r} exceeds eight characters"
            )
        return value.rstrip(" ").ljust(8, " ")
    return value


def _cmqtt_object(response: Any) -> dict[str, Any]:
    status = getattr(response, "status", getattr(response, "code", None))
    lines = getattr(response, "lines", None)
    final = getattr(response, "final", None)
    if (
        type(status) is not int
        or status != 200
        or type(lines) is not tuple
        or len(lines) != 2
        or any(type(line) is not str for line in lines)
        or final != lines[-1]
        or not lines[0].startswith("200-")
        or not lines[-1].startswith("200 ")
    ):
        raise PhysicalProgrammingError("Unexpected CMQTT CAPABILITIES response envelope")
    try:
        value = json.loads(lines[0][4:])
    except (json.JSONDecodeError, UnicodeError) as error:
        raise PhysicalProgrammingError("CMQTT CAPABILITIES did not contain valid JSON") from error
    if not isinstance(value, dict):
        raise PhysicalProgrammingError("CMQTT CAPABILITIES must contain one JSON object")
    return value


def _capability_evidence(document: Mapping[str, Any]) -> dict[str, Any]:
    names = (
        "service",
        "physical_pp_load",
        "physical_pp_save",
        "physical_pp_routed_load",
        "physical_pp_routed_save",
        "physical_pp_routed_methods",
        "physical_pp_routed_save_protection",
        "physical_pp_routed_lock_methods",
        "physical_pp_routed_unsupported_methods",
        "physical_pp_routed_lock",
        "physical_pp_routed_nvm_commit",
        "physical_pp_routed_delivery_semantics",
        "physical_pp_routed_state_scope",
        "pci_generation",
        "pci_connected",
        "programming_lane_state",
    )
    return {name: document.get(name) for name in names}


def _preflight(client: CommandClient, method: str, *, saving: bool) -> dict[str, Any]:
    document = _cmqtt_object(client.command("CMQTT CAPABILITIES"))
    evidence = _capability_evidence(document)
    methods = document.get("physical_pp_routed_methods")
    unsupported = document.get("physical_pp_routed_unsupported_methods")
    conditions = (
        (document.get("service") == "cmqttd", "selected C-Gate service is not cmqttd"),
        (document.get("physical_pp_load") is True, "physical PP LOAD is unavailable"),
        (document.get("physical_pp_routed_load") is True, "routed physical PP LOAD is unavailable"),
        (isinstance(methods, list) and all(isinstance(item, str) for item in methods),
         "routed physical PP method declaration is malformed"),
        (isinstance(methods, list) and method in methods,
         f"routed physical PP method {method!r} is unavailable"),
        (isinstance(unsupported, list) and all(isinstance(item, str) for item in unsupported),
         "routed physical PP unsupported-method declaration is malformed"),
        (isinstance(unsupported, list) and method not in unsupported,
         f"routed physical PP method {method!r} is explicitly unsupported"),
        (document.get("pci_connected") is True, "cmqttd has no connected PCI"),
        (document.get("programming_lane_state") == "ready",
         "cmqttd programming lane requires reconnect"),
    )
    for accepted, message in conditions:
        if not accepted:
            raise PhysicalProgrammingError(message, {
                "phase": "capability-preflight",
                "method": method,
                "capabilities": evidence,
                "save_attempted": False,
                "automatic_write_retries": 0,
            })
    if saving:
        for accepted, message in (
            (document.get("physical_pp_save") is True, "physical PP SAVE is unavailable"),
            (document.get("physical_pp_routed_save") is True,
             "routed physical PP SAVE is unavailable"),
        ):
            if not accepted:
                raise PhysicalProgrammingError(message, {
                    "phase": "capability-preflight",
                    "method": method,
                    "capabilities": evidence,
                    "save_attempted": False,
                    "automatic_write_retries": 0,
                })
        # NCC is the C-Bus 3 method.  A confirmed STORE/readback is not a
        # nonvolatile save unless this separate capability is present.
        if method == "ncc" and document.get("physical_pp_routed_nvm_commit") is not True:
            raise PhysicalProgrammingError(
                "Routed NCC Save-to-NVM is unavailable on this cmqttd build",
                {
                    "phase": "capability-preflight",
                    "method": method,
                    "capabilities": evidence,
                    "save_attempted": False,
                    "automatic_write_retries": 0,
                },
            )
    return evidence


def _attach(error: BaseException, evidence: Mapping[str, Any]) -> None:
    try:
        if isinstance(error, PhysicalProgrammingError):
            error.evidence = dict(evidence)
        details = getattr(error, "details", None)
        if not isinstance(details, dict):
            details = {}
        else:
            details = dict(details)
        details["physical_programming_evidence"] = dict(evidence)
        error.details = details
        error.physical_programming_evidence = dict(evidence)
    except Exception:
        pass


class PhysicalProgramming:
    """Execute one topology-resolved physical PP inspection or edit."""

    def __init__(self, client: CommandClient, *, operation_id: str | None = None):
        self.client = client
        identifier = uuid4().hex[:12] if operation_id is None else operation_id
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"[A-Za-z0-9_]{1,24}", identifier) is None
        ):
            raise ValueError("Physical PP operation id must be 1..24 letters, digits or underscores")
        self.operation_id = identifier

    def _names(self, phase: str) -> tuple[str, str]:
        session = f"cbus_pp_{self.operation_id}_{phase}"
        return session, session + "_lock"

    @staticmethod
    def _selected_schema(
        schema: Mapping[str, PhysicalParameter],
        method: str,
        parameters: Iterable[str] | None,
    ) -> tuple[PhysicalParameter, ...]:
        if parameters is None:
            selected = tuple(item for item in schema.values() if item.program_method == method)
        else:
            names = tuple(parameters)
            if len(names) > 4096:
                raise ValueError("Physical PP inspect accepts at most 4096 parameters")
            if len(set(names)) != len(names):
                raise ValueError("Physical PP inspect parameter names must be unique")
            selected_list = []
            for name in names:
                name = _parameter_name(name)
                if name not in schema:
                    raise PhysicalProgrammingError(
                        f"Physical unit schema has no parameter named {name!r}"
                    )
                selected_list.append(schema[name])
            selected = tuple(selected_list)
        if not selected:
            raise PhysicalProgrammingError(
                f"Physical unit schema has no {method!r} parameters"
            )
        wrong = [item for item in selected if item.program_method != method]
        if wrong:
            actual = ", ".join(
                f"{item.name}={item.program_method or 'direct'}" for item in wrong
            )
            raise PhysicalProgrammingError(
                f"Selected parameters do not use requested method {method!r}: {actual}"
            )
        return selected

    def inspect(
        self,
        source: str,
        *,
        method: str,
        parameters: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        source_path = PhysicalUnitPath.parse(source)
        method = _method(method)
        requested = None if parameters is None else tuple(parameters)
        if requested is not None:
            # Reject invalid fields before the preflight command.
            requested = tuple(_parameter_name(name) for name in requested)
            if len(requested) > 4096:
                raise ValueError("Physical PP inspect accepts at most 4096 parameters")
            if len(set(requested)) != len(requested):
                raise ValueError("Physical PP inspect parameter names must be unique")
        capabilities = _preflight(self.client, method, saving=False)
        evidence = {
            "format": "cbus-physical-pp-inspection-v1",
            "operation_id": self.operation_id,
            "phase": "physical-load",
            "source": source_path.value,
            "lock_address": source_path.lock_address,
            "method": method,
            "capabilities": capabilities,
            "automatic_write_retries": 0,
            "io_performed": True,
            "save_attempted": False,
            "saved": False,
            "fresh_physical_readback_verified": False,
            "power_cycle_persistence_verified": False,
            "original_toolkit_workflow_executed": False,
            "hardware_method_matrix_accepted": False,
        }
        session_name, lock_name = self._names("inspect")
        try:
            with Programmer(self.client).load(
                source_path.lock_address,
                source_path.value,
                name=session_name,
                lock_name=lock_name,
            ) as session:
                schema = _schema(session.info("*"))
                selected = self._selected_schema(schema, method, requested)
                values = {item.name: session.values(item.name)[item.name] for item in selected}
            evidence.update({
                "phase": "complete",
                "complete": True,
                "parameters": [item.as_dict() for item in selected],
                "values": values,
                "physical_load_completed": True,
                "physical_readback_scope": "one-loaded-session",
            })
            return evidence
        except BaseException as error:
            evidence["phase"] = "physical-load-or-inspection"
            evidence["complete"] = False
            _attach(error, evidence)
            raise

    def apply(
        self,
        source: str,
        edits: Iterable[tuple[str, str]],
        *,
        method: str,
        destination: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        source_path = PhysicalUnitPath.parse(source)
        destination_path = (
            source_path
            if destination is None
            else PhysicalUnitPath.parse(destination, label="destination")
        )
        if destination_path.lock_address != source_path.lock_address:
            raise ValueError(
                "Physical PP destination must be on the source project/network lock"
            )
        method = _method(method)
        edit_rows = _edits(edits)
        saving = not dry_run
        capabilities = _preflight(self.client, method, saving=saving)
        evidence: dict[str, Any] = {
            "format": "cbus-physical-pp-apply-v1",
            "operation_id": self.operation_id,
            "phase": "physical-load",
            "source": source_path.value,
            "destination": destination_path.value,
            "lock_address": source_path.lock_address,
            "method": method,
            "edits": [item.as_dict() for item in edit_rows],
            "capabilities": capabilities,
            "native_save_operation": (
                "PP SAVE_TO_SOURCE" if destination is None else "PP SAVE"
            ),
            "automatic_write_retries": 0,
            "save_attempts": 0,
            "save_attempted": False,
            "saved": False,
            "save_outcome_uncertain": False,
            "staged_readback_verified": False,
            "fresh_physical_readback_verified": False,
            "power_cycle_persistence_verified": False,
            "original_toolkit_workflow_executed": False,
            "hardware_method_matrix_accepted": False,
            "dry_run": bool(dry_run),
        }
        selected: tuple[PhysicalParameter, ...]
        before: dict[str, str]
        staged: dict[str, str]
        session_name, lock_name = self._names("write")
        try:
            with Programmer(self.client).load(
                source_path.lock_address,
                source_path.value,
                name=session_name,
                lock_name=lock_name,
            ) as session:
                schema = _schema(session.info("*"))
                # cmqttd follows native C-Gate's unit-family boundary here:
                # the presence of any NCC parameter marks the complete decoded
                # specification as requiring the C-Bus 3 Save-to-NVM phase.
                # This remains true when a tag/method-selected SAVE changes only
                # a direct or paged parameter.  Refuse before the first PP SET
                # when that separately advertised completion path is absent.
                if (
                    saving
                    and any(item.program_method == "ncc" for item in schema.values())
                    and capabilities.get("physical_pp_routed_nvm_commit") is not True
                ):
                    evidence.update({
                        "phase": "save-capability-preflight",
                        "complete": False,
                        "physical_load_completed": True,
                    })
                    raise PhysicalProgrammingError(
                        "Physical unit specification requires routed C-Bus 3 "
                        "Save-to-NVM, which is unavailable on this cmqttd build",
                        evidence,
                    )
                selected = self._selected_schema(
                    schema, method, (item.parameter for item in edit_rows)
                )
                before = {
                    item.name: session.values(item.name)[item.name] for item in selected
                }
                evidence.update({
                    "parameters": [item.as_dict() for item in selected],
                    "before": before,
                })
                evidence["phase"] = "editing"
                for edit in edit_rows:
                    session.set(edit.parameter, edit.requested_value)
                staged = {
                    item.name: session.values(item.name)[item.name] for item in selected
                }
                selected_by_name = {item.name: item for item in selected}
                staged_mismatches = {
                    edit.parameter: {
                        "requested": edit.requested_value,
                        "staged": staged.get(edit.parameter),
                    }
                    for edit in edit_rows
                    if edit.parameter not in staged
                    or _comparable_value(
                        selected_by_name[edit.parameter], edit.requested_value
                    )
                    != _comparable_value(
                        selected_by_name[edit.parameter], staged[edit.parameter]
                    )
                }
                evidence.update({
                    "staged": staged,
                })
                if staged_mismatches:
                    evidence.update({
                        "phase": "staged-verification",
                        "complete": False,
                        "staged_readback_verified": False,
                        "staged_readback_mismatches": staged_mismatches,
                    })
                    raise PhysicalProgrammingError(
                        "Staged PP readback differed from the requested values",
                        evidence,
                    )
                evidence["staged_readback_verified"] = True
                if dry_run:
                    evidence.update({
                        "phase": "complete",
                        "complete": True,
                        "persistence_requested": False,
                        "fresh_physical_readback_performed": False,
                    })
                    return evidence
                evidence.update({
                    "phase": "save",
                    "save_attempted": True,
                    "save_attempts": 1,
                })
                try:
                    if destination is None:
                        session.save_to_source()
                    else:
                        session.save(destination_path.value)
                except BaseException as error:
                    evidence.update({
                        "phase": "save",
                        "saved": False,
                        "save_outcome_uncertain": True,
                        "complete": False,
                    })
                    _attach(error, evidence)
                    raise
                evidence.update({
                    "saved": True,
                    "save_outcome_uncertain": False,
                    "phase": "fresh-physical-verification",
                })
        except BaseException as error:
            evidence.setdefault("complete", False)
            _attach(error, evidence)
            raise

        verify_name, verify_lock = self._names("verify")
        try:
            with Programmer(self.client).load(
                destination_path.lock_address,
                destination_path.value,
                name=verify_name,
                lock_name=verify_lock,
            ) as session:
                verify_schema = _schema(session.info("*"))
                verified_selection = self._selected_schema(
                    verify_schema, method, (item.parameter for item in edit_rows)
                )
                verified = {
                    item.name: session.values(item.name)[item.name]
                    for item in verified_selection
                }
            evidence["verified"] = verified
            source_parameters = {item.name: item for item in selected}
            verified_parameters = {item.name: item for item in verified_selection}
            schema_mismatches = {
                name: {
                    "staged_schema": source_parameters[name].as_dict(),
                    "verified_schema": verified_parameters[name].as_dict(),
                }
                for name in source_parameters
                if source_parameters[name] != verified_parameters[name]
            }
            value_mismatches = {
                name: {"staged": staged.get(name), "verified": verified.get(name)}
                for name in sorted(set(staged) | set(verified))
                if name not in source_parameters
                or name not in verified_parameters
                or _comparable_value(source_parameters[name], staged[name])
                != _comparable_value(verified_parameters[name], verified[name])
            }
            if schema_mismatches or value_mismatches:
                evidence.update({
                    "phase": "fresh-physical-verification",
                    "complete": False,
                    "fresh_physical_readback_verified": False,
                    "verification_mismatches": value_mismatches,
                    "verification_schema_mismatches": schema_mismatches,
                })
                raise PhysicalProgrammingError(
                    "Fresh physical PP readback differed from the confirmed saved values",
                    evidence,
                )
            evidence.update({
                "phase": "complete",
                "complete": True,
                "fresh_physical_readback_verified": True,
                "fresh_physical_readback_performed": True,
                "physical_readback_scope": "fresh-pp-load-after-confirmed-save",
                "verification_comparison": "native-schema-type-aware",
            })
            return evidence
        except BaseException as error:
            evidence.setdefault("complete", False)
            _attach(error, evidence)
            raise


def physical_programming_error_payload(error: BaseException) -> dict[str, Any]:
    evidence = getattr(error, "physical_programming_evidence", None)
    return (
        {"physical_programming_evidence": evidence}
        if isinstance(evidence, dict)
        else {}
    )
