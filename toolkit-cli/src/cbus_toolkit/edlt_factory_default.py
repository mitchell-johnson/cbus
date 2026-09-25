"""Guarded one-shot physical eDLT FactoryDefault requests.

The native 202 receipt proves only that C-Gate received the unit ACK for the
captured OEM control. It does not prove post-reboot values or persistence.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .cgate import CGateError
from .edlt_label_clear import EdltDynamicLabelClear, EdltLabelClearPlan, _path
from .serials import parse_native_serial


@dataclass(frozen=True)
class EdltFactoryDefaultPlan:
    source: str
    serial: str
    unit_type: str
    firmware: str
    inventory: tuple[tuple, ...]
    runtime: tuple[tuple[str, str], ...]
    database_hash: str

    def as_dict(self):
        return {
            "format": "cbus-edlt-factory-default-plan-v1",
            "source": self.source,
            "serial": self.serial,
            "unit_type": self.unit_type,
            "firmware": self.firmware,
            "inventory": [list(row) for row in self.inventory],
            "runtime": dict(self.runtime),
            "database_hash": self.database_hash,
            "physical_refresh_scope": "entire_network",
            "native_command": "DO " + self.source + " FactoryDefault",
            "native_retries": 0,
            "automatic_retries": 0,
            "request_attempted": False,
            "factory_default_control_accepted": False,
            "physical_factory_reset_verified": False,
            "factory_defaults_readback_verified": False,
            "address_preserved_verified": False,
            "device_reboot_verified": False,
            "persistence_verified": False,
            "database_updated": False,
        }


class EdltFactoryDefaultUncertain(RuntimeError):
    def __init__(self, message, evidence):
        self.details = evidence
        super().__init__(message)


class EdltFactoryDefault:
    """Guard identity and topology, then issue one non-replayed reset control."""

    def __init__(self, client):
        self.client = client
        self._identity = EdltDynamicLabelClear(client)
        self.last_evidence = None

    @staticmethod
    def _as_identity_plan(plan):
        return EdltLabelClearPlan(
            plan.source,
            plan.serial,
            plan.unit_type,
            plan.firmware,
            plan.inventory,
            plan.runtime,
            plan.database_hash,
        )

    @classmethod
    def _validate(cls, plan):
        if type(plan) is not EdltFactoryDefaultPlan:
            raise ValueError("Use an EdltFactoryDefaultPlan returned by plan()")
        try:
            EdltDynamicLabelClear._validate(cls._as_identity_plan(plan))
        except ValueError as error:
            message = str(error).replace("Clear plan", "Factory-default plan").replace(
                "clear plan", "factory-default plan"
            )
            raise ValueError(message) from error

    def plan(self, source, *, expected_serial):
        try:
            _path(source)
        except ValueError as error:
            message = str(error).replace("Clear", "Factory default").replace(
                "clear", "factory default"
            )
            raise ValueError(message) from error
        if type(expected_serial) is not str or not parse_native_serial(expected_serial).known:
            raise ValueError("Factory default requires a known expected native serial")
        try:
            guarded = self._identity.plan(source, expected_serial=expected_serial)
        except ValueError as error:
            message = str(error).replace("Clear", "Factory default").replace(
                "clear", "factory default"
            )
            raise ValueError(message) from error
        result = EdltFactoryDefaultPlan(
            guarded.source,
            guarded.serial,
            guarded.unit_type,
            guarded.firmware,
            guarded.inventory,
            guarded.runtime,
            guarded.database_hash,
        )
        self._validate(result)
        return result

    @staticmethod
    def _failure(evidence, error):
        evidence["cause_type"] = type(error).__name__
        try:
            evidence["cause"] = str(error)
        except BaseException as secondary:
            evidence["cause"] = "Exception message unavailable"
            evidence["cause_export_error_type"] = type(secondary).__name__

    @staticmethod
    def _uncertain(message, evidence, cause):
        result = EdltFactoryDefaultUncertain(message, evidence)
        if hasattr(cause, "cgate_cleanup_errors"):
            result.cgate_cleanup_errors = cause.cgate_cleanup_errors
        return result

    def request(self, plan):
        self._validate(plan)
        self.last_evidence = None
        fresh = self.plan(plan.source, expected_serial=plan.serial)
        if fresh != plan:
            raise ValueError("Factory-default preconditions changed since the plan was made")
        evidence = {
            **plan.as_dict(),
            "outcome": "outcome_uncertain",
            "request_attempted": True,
            "native_accepted": False,
            "factory_default_control_accepted": False,
            "device_side_effect_possible": True,
            "post_request_io_performed": False,
            "reply": None,
        }
        self.last_evidence = evidence
        command = "DO " + plan.source + " FactoryDefault"
        try:
            response = self.client.command(command)
            evidence.update(reply=list(response.lines), native_code=response.code)
            if response.code == 202 and response.lines == ("202 Done: " + plan.source,):
                evidence.update(
                    outcome="native_accepted",
                    native_accepted=True,
                    factory_default_control_accepted=True,
                )
                return evidence
            raise EdltFactoryDefaultUncertain(
                "Unexpected native factory-default reply; request was not replayed",
                evidence,
            )
        except EdltFactoryDefaultUncertain:
            raise
        except CGateError as error:
            response = error.response
            if (
                400 <= response.code <= 599
                and response.lines
                and all(re.fullmatch(r"[45][0-9]{2}[- ].+", line) for line in response.lines)
            ):
                evidence.update(
                    outcome="native_rejected",
                    reply=list(response.lines),
                    native_code=response.code,
                )
                return evidence
            self._failure(evidence, error)
            evidence.update(reply=list(response.lines))
            raise self._uncertain(
                "Factory-default request outcome is uncertain; request was not replayed",
                evidence,
                error,
            ) from error
        except BaseException as error:
            self._failure(evidence, error)
            if not isinstance(error, Exception):
                error.edlt_factory_default_evidence = evidence
                raise
            raise self._uncertain(
                "Factory-default request outcome is uncertain; request was not replayed",
                evidence,
                error,
            ) from error
