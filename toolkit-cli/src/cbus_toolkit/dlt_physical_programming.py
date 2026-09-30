"""Deliver one saved classic DLT Indicators edit through the guarded PP lane.

The database must already hold the plan's result. The physical unit must still
hold its original baseline. Those are separate checks, never interchangeable.
Physical admission requires loaded-session identity in PP INFO. Older servers
without that contract fail closed; database identity cannot replace it.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from .dlt_indicators import (
    ADDRESS, FIELDS, LAYOUT, DltIndicatorPlan, _raw, _snapshot, _trace,
)
from .dlt_labels import DltLabelError, WORKFLOW
from .dlt_profiles import require
from .physical_pp_journal import refuse_unresolved
from .physical_programming import (
    PhysicalProgramming, PhysicalUnitPath,
    _cmqtt_object, _schema, _session_memory,
)
from .programming import Programmer, _integer_value, _rows, xml_text


LOADED_IDENTITY_CONTRACT = "pp-info-loaded-identity-v1"
_IDENTITY_ATTRIBUTES = frozenset(("UnitType", "FirmwareVersion", "Source"))


def _loaded_identity(reply, source, identity):
    """Parse the proposed three-attribute contract without any DB fallback.

    XML parsers reject repeated attributes. Exact root/attribute names and a
    canonical physical Source make absence, namespaces and ambiguous metadata
    admission failures. Compatibility needs the centrally reviewed server.
    """
    document = xml_text(reply)
    if "<!DOCTYPE" in document or "<!ENTITY" in document:
        raise DltLabelError("Loaded physical identity XML contains unsupported declarations")
    try:
        root = ET.fromstring(document)
    except ET.ParseError as error:
        raise DltLabelError("Malformed loaded physical identity XML") from error
    if root.tag != "Parameters" or set(root.attrib) != _IDENTITY_ATTRIBUTES:
        raise DltLabelError("Loaded physical identity contract is missing or unsupported")
    actual_source = root.attrib["Source"]
    try:
        canonical = PhysicalUnitPath.parse(actual_source).value
    except ValueError as error:
        raise DltLabelError("Loaded physical identity Source is malformed") from error
    if actual_source != canonical or actual_source != source:
        raise DltLabelError("Loaded physical identity Source differs from the canonical target")
    if (root.attrib["UnitType"], root.attrib["FirmwareVersion"]) != identity[:2]:
        raise DltLabelError("Loaded physical identity differs from the exact DLT indicator plan")
    return dict(root.attrib)


def _connected_generation(capabilities):
    generation = capabilities.get("pci_generation")
    if (capabilities.get("pci_connected") is not True
            or type(generation) is not int or generation < 0):
        raise DltLabelError("Loaded physical identity requires a connected PCI generation")
    return generation


def _plan(document):
    plan = DltIndicatorPlan.from_dict(document)
    if plan.identity is None or plan.identity[2] is None:
        raise DltLabelError("Physical DLT Indicators require exact type, firmware and catalogue identity")
    require(WORKFLOW, *plan.identity, error=DltLabelError)
    if plan.identity != ("KEYML5", "2.1.00", "5055DL"):
        raise DltLabelError("Physical DLT Indicators currently admit KEYML5 2.1.00 / 5055DL only")
    _, after = _trace(plan.expected, plan.operations)
    changes = {name: value for name, value in after.items() if value != plan.expected[name]}
    if changes != dict(plan.changes):
        raise DltLabelError("Indicator plan changes differ from its ordered controls")
    if not changes:
        raise DltLabelError("Physical DLT Indicators require a meaningful changed control")
    return plan


def _layout(schema):
    for name, (address, bit, width, kind) in LAYOUT.items():
        item = schema.get(name)
        if item is None or item.address is None:
            raise DltLabelError("Missing DLT indicator layout: " + name)
        actual = (_integer_value(item.address), item.bit_address,
                  1 if item.value_type == "bit" else item.bit_size, item.value_type)
        if (actual != (address, bit, width, kind) or item.array_size != 1
                or item.array_skip != 0 or item.program_method != "direct"
                or item.protection not in ("none", "checksum", "lock")):
            raise DltLabelError("Unsupported DLT indicator layout/method/protection: " + name)
    return {name: schema[name] for name in FIELDS}


def _values(session):
    return _snapshot({name: session.values(name)[name] for name in FIELDS})


class DltPhysicalProgramming:
    def __init__(self, client):
        self.client = client

    def apply(self, source, document, *, dry_run=False, journal=None):
        path = PhysicalUnitPath.parse(source)
        plan = _plan(document)
        if not dry_run and journal is None:
            raise ValueError("Physical PP save requires a durable attempt journal (--journal PATH)")
        if dry_run and journal is not None:
            raise ValueError("Physical PP dry-run never saves; omit the attempt journal")
        if not dry_run:
            refuse_unresolved(journal, path.value)
        expected = {**plan.expected, **plan.changes}
        evidence = {
            "format": "cbus-dlt-indicators-physical-v1", "source": path.value,
            "database_source": "/db" + path.value, "plan": plan.as_dict(),
            "database_edited_state_verified": False,
            "physical_original_baseline_verified": False,
            "unchanged_indicator_fields_verified": False,
            "complete_indicator_bytes_verified": False,
            "profile_verification": "database-catalogue-and-physical-loaded-session-identity",
            "loaded_identity_contract": LOADED_IDENTITY_CONTRACT,
            "physical_loaded_identity_verified": False,
            "fresh_physical_identity_verified": False,
            "catalogue_verification_scope": "saved-project-database",
            "loaded_pci_generation_binding_verified": False,
            "physical_serial_verified": False,
            "project_disk_persistence_verified": False,
            "display_behavior_verified": False,
        }
        try:
            with Programmer(self.client).load(path.lock_address, "/db" + path.value) as session:
                if (session.unit_type, session.firmware, session.catalog_number) != plan.identity:
                    raise DltLabelError("Saved database identity differs from the DLT indicator plan")
                database_schema = _layout(_schema(session.info("*")))
                if _values(session) != expected:
                    raise DltLabelError("Saved database indicator state differs from the edited plan result")
            evidence["database_edited_state_verified"] = True
            evidence["database_raw_hex"] = _raw(expected).hex()

            def validate(session, schema, phase, capabilities):
                # PP INFO must describe this physically loaded session. Neither
                # the edited DB nor the plan supplies missing live metadata.
                loaded_identity = _loaded_identity(session.info("*"), path.value, plan.identity)
                generation = _connected_generation(
                    _cmqtt_object(self.client.command("CMQTT CAPABILITIES")))
                if generation != _connected_generation(capabilities):
                    raise DltLabelError("PCI generation changed during the physical indicator workflow")
                if phase == "loaded":
                    evidence["physical_loaded_identity_verified"] = True
                elif phase == "fresh":
                    evidence["fresh_physical_identity_verified"] = True
                # Bind the database identity again inside each physical session.
                fields = {}
                for code, row in _rows(self.client.command("DBGET " + path.value)):
                    name, separator, value = row.partition("=")
                    name = name.rsplit("/", 1)[-1]
                    if code == 342 and separator and name in ("UnitType", "FirmwareVersion", "CatalogNumber"):
                        if name in fields:
                            raise DltLabelError("Duplicate database identity field")
                        fields[name] = value
                if tuple(fields.get(key) for key in ("UnitType", "FirmwareVersion", "CatalogNumber")) != plan.identity:
                    raise DltLabelError("Unit identity changed since the DLT indicator plan")
                if _layout(schema) != database_schema:
                    raise DltLabelError("Physical DLT indicator schema differs from its database schema")
                wanted = dict(plan.expected) if phase == "loaded" else expected
                if _values(session) != wanted:
                    raise DltLabelError("Physical DLT indicator " + phase + " values differ from the plan")
                memory = _session_memory(session, ADDRESS, 2)
                cells = memory["unit" if phase in ("loaded", "fresh") else "current"]
                if None in cells or bytes(cells) != _raw(wanted):
                    raise DltLabelError("Complete physical indicator bytes differ from the named fields")
                if phase == "loaded":
                    evidence["physical_original_baseline_verified"] = True
                if phase == "fresh":
                    evidence["unchanged_indicator_fields_verified"] = True
                    evidence["complete_indicator_bytes_verified"] = True
                return {"phase": phase, "raw_hex": bytes(cells).hex(),
                        "all_fields_verified": True, "loaded_identity": loaded_identity,
                        "observed_pci_generation": generation}

            # Stage every field in the two-byte control extent. Unchanged values
            # stay identical; cmqttd stores only changed bytes. Journaling all ten
            # fields binds both complete bytes for existing read-only recovery,
            # even when the requested control changes only one of them.
            edits = [(name, str(expected[name][0])) for name in FIELDS]
            result = PhysicalProgramming(self.client).apply(
                path.value, edits, method="direct", dry_run=dry_run, journal=journal,
                validate_session=validate,
            )
            return {**result, "dlt_indicators_evidence": evidence}
        except BaseException as error:
            details = dict(getattr(error, "details", {}))
            details["dlt_indicators_evidence"] = evidence
            try:
                error.details = details
                physical = getattr(error, "physical_programming_evidence", None)
                if isinstance(physical, dict):
                    physical["dlt_indicators_evidence"] = evidence
            except Exception:
                pass
            raise
