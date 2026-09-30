"""Verified native copy/default transactions for supported UnitTemplate profiles.

The original Toolkit template format and selected fields live in
``unit_templates``.  This module composes that bounded format with C-Gate PP
sessions: it reads one source or the decoded specification defaults, stages a
database destination, confirms every template field, saves once, then opens a
fresh session for verification.  It never retries an uncertain save.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from .unit_templates import PARAMETERS, UnitTemplate, UnitTemplates


_DATABASE_UNIT = re.compile(
    r"^/db//(?P<project>[^/\s]+?)/(?P<network>[0-9]{1,3})/p/(?P<unit>[0-9]{1,3})$",
    re.IGNORECASE,
)

# Stable, template-excluded values that the original classic key-input agent
# keeps outside its template list.  Some C-Gate schemas omit SerialNo/State and
# expose NetworkAddress/CUSTYPE instead, so verification uses the intersection
# present in the destination snapshot.
PRESERVED_PARAMETERS = (
    "CUSTYPE",
    "EEPROMChecksumActive",
    "EEPROMLevelRecall",
    "LearnedFlag",
    "NetworkAddress",
    "PatchEnable",
    "Project",
    "SerialNo",
    "State",
    "UnitAddress",
)


class UnitTemplateTransactionError(RuntimeError):
    """A template transaction failed after its evidence record was started."""

    def __init__(self, message: str, evidence: dict[str, Any]):
        self.evidence = copy.deepcopy(evidence)
        self.details = {"unit_template_transaction_evidence": self.evidence}
        super().__init__(message)


def _database_path(path: Any, label: str) -> tuple[str, str, int]:
    if not isinstance(path, str):
        raise ValueError(label + " must be a /db//PROJECT/network/p/unit path")
    match = _DATABASE_UNIT.fullmatch(path)
    if match is None:
        raise ValueError(label + " must be a /db//PROJECT/network/p/unit path")
    network, unit = int(match.group("network")), int(match.group("unit"))
    if network > 255 or unit > 255:
        raise ValueError(label + " network and unit addresses must be in 0..255")
    return match.group("project"), str(network), unit


class NativeTemplateTransaction:
    """Copy or default one exact classic template profile through native PP."""

    def __init__(self, programmer: Any, templates: UnitTemplates, lock_address: str):
        if not isinstance(templates, UnitTemplates):
            raise TypeError("templates must be UnitTemplates")
        if templates.family.name != "classic":
            # NeoPro templates include PatchEnable, which this transaction preserves.
            raise ValueError("Template transactions support the classic KEY1/KEY2/KEY4 profiles only")
        self.programmer = programmer
        self.templates = templates
        self.lock_address = lock_address
        self.last_evidence: dict[str, Any] | None = None

    def _check_path(self, path: Any, label: str) -> str:
        project, network, _unit = _database_path(path, label)
        expected = f"//{project}/{network}"
        if self.lock_address != expected:
            raise ValueError(
                f"{label} requires --lock-address {expected}; got {self.lock_address!r}"
            )
        return path

    def _new_evidence(
        self, operation: str, source: str | None, destination: str, dry_run: bool
    ) -> dict[str, Any]:
        profile = self.templates.profile
        return {
            "format": "cbus-native-unit-template-transaction-v1",
            "operation": operation,
            "profile": {
                "unit_type": profile[0],
                "firmware": profile[1],
                "catalog_number": profile[2],
                "specification": profile[3],
            },
            "source": source,
            "destination": destination,
            "dry_run": dry_run,
            "state": "initialized",
            "template_crc": None,
            "template_parameter_count": len(PARAMETERS),
            "changed_parameters": [],
            "preserved_parameters": [],
            "staged_verified": False,
            "save_attempted": False,
            "save_confirmed": False,
            "save_outcome_uncertain": False,
            "reload_attempted": False,
            "reload_verified": False,
            "complete": False,
            "physical_hardware_verified": False,
            "project_file_saved": False,
        }

    @staticmethod
    def _preserved(values: dict[str, str]) -> dict[str, str]:
        return {name: values[name] for name in PRESERVED_PARAMETERS if name in values}

    @staticmethod
    def _same_preserved(expected: dict[str, str], actual: dict[str, str]) -> bool:
        return all(actual.get(name) == value for name, value in expected.items())

    def _fail(self, error: BaseException) -> None:
        evidence = copy.deepcopy(self.last_evidence or {})
        if evidence.get("save_attempted") and not evidence.get("save_confirmed"):
            evidence["save_outcome_uncertain"] = True
        evidence["complete"] = False
        self.last_evidence = evidence
        try:
            error.unit_template_transaction_evidence = copy.deepcopy(evidence)
        except BaseException:
            pass
        if isinstance(error, (ValueError, OSError, RuntimeError)):
            wrapped = UnitTemplateTransactionError(str(error), evidence)
            try:
                wrapped.__cause__ = error
            except BaseException:
                pass
            raise wrapped from error
        raise error

    def _source_template(self, source: str) -> UnitTemplate:
        self.last_evidence["state"] = "reading_source"
        with self.programmer.load(self.lock_address, source) as session:
            template = self.templates.export(session)
        self.last_evidence["template_crc"] = template.crc
        return template

    def _defaults_template(self) -> UnitTemplate:
        self.last_evidence["state"] = "reading_specification_defaults"
        template = self.templates.from_values(
            self.templates.spec.defaults(), description="Decoded unit specification defaults"
        )
        self.last_evidence["template_crc"] = template.crc
        return template

    def _execute(
        self,
        template: UnitTemplate,
        destination: str,
        *,
        dry_run: bool,
    ) -> dict[str, Any]:
        self.last_evidence["state"] = "staging_destination"
        preserved: dict[str, str]
        with self.programmer.load(self.lock_address, destination) as session:
            before = session.values()
            preserved = self._preserved(before)
            applied = self.templates.apply(session, template)
            staged = session.values()
            if not self._same_preserved(preserved, staged):
                raise RuntimeError(
                    "Template staging changed a destination value outside the template field set"
                )
            if self.templates.export(session).attributes != template.attributes:
                raise RuntimeError("Template staging verification differed from the requested template")
            self.last_evidence.update(
                changed_parameters=list(applied["changed_parameters"]),
                preserved_parameters=list(preserved),
                staged_verified=True,
            )
            if dry_run:
                self.last_evidence.update(state="previewed", complete=True)
                return copy.deepcopy(self.last_evidence)
            self.last_evidence.update(state="saving_destination", save_attempted=True)
            session.save_to_source()
            self.last_evidence["save_confirmed"] = True

        self.last_evidence.update(state="reloading_destination", reload_attempted=True)
        with self.programmer.load(self.lock_address, destination) as session:
            reloaded = session.values()
            if self.templates.export(session).attributes != template.attributes:
                raise RuntimeError("Reloaded template fields differ after the confirmed PP SAVE")
            if not self._same_preserved(preserved, reloaded):
                raise RuntimeError(
                    "Reloaded destination value outside the template field set was not preserved"
                )
        self.last_evidence.update(
            state="verified_saved", reload_verified=True, complete=True
        )
        return copy.deepcopy(self.last_evidence)

    def copy(
        self,
        source: str,
        destination: str,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Copy the exact supported profile without an intermediate file."""
        source = self._check_path(source, "Template source")
        destination = self._check_path(destination, "Template destination")
        if source.casefold() == destination.casefold():
            raise ValueError("Template copy source and destination must differ")
        self.last_evidence = self._new_evidence("copy", source, destination, dry_run)
        try:
            template = self._source_template(source)
            return self._execute(template, destination, dry_run=dry_run)
        except BaseException as error:
            self._fail(error)
        raise AssertionError("unreachable")

    def reset_template_defaults(
        self, destination: str, *, dry_run: bool = False
    ) -> dict[str, Any]:
        """Reset only the original template-selected fields to schema defaults."""
        destination = self._check_path(destination, "Template destination")
        self.last_evidence = self._new_evidence(
            "reset-template-defaults", None, destination, dry_run
        )
        try:
            template = self._defaults_template()
            return self._execute(template, destination, dry_run=dry_run)
        except BaseException as error:
            self._fail(error)
        raise AssertionError("unreachable")
