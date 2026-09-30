"""Bounded IOPE Environment block-timer controls; no save or physical I/O.

Only an already-valid, enabled Environment role with an existing group and a
simple retained expiry command is admitted. See docs/iope-block-timer.md.
"""
from __future__ import annotations

from copy import deepcopy
import json
from types import MappingProxyType

from .iope_environment import (
    CORRIDOR, ENABLED, FIRST, SECOND, SECOND_ENABLED,
    IopeEnvironment, LAYOUTS as ENVIRONMENT_LAYOUTS,
)
from .iope_settings import PROFILES
from .pp_editor import PPEditError, PPEditor, PPPlan, integer

FORMAT = "cbus-iope-block-timer-plan-v1"
# TKeyMicroFunction registrations and GetMicrofunctionCodeForRampRateAndRecallLevel.
# These full-byte IOPE commands are not the classic keypad nibble encodings.
EXPIRY = MappingProxyType({"idle": 0x00, "toggle": 0x4F, "on": 0x47, "off": 0x40})
LAYOUTS = MappingProxyType({
    **ENVIRONMENT_LAYOUTS,
    "TimerExpiryCommand": ("int", 0x36, 8, 8, 0, 0),
    "TimerHighByte": ("int", 0x40, 8, 8, 0, 0),
    "TimerLowByte": ("int", 0x48, 8, 8, 0, 0),
})
WRITABLE = frozenset(("TimerExpiryCommand", "TimerHighByte", "TimerLowByte"))
OPTION_NAMES = frozenset(("block", "seconds", "expiry", "group_cache"))


class IopeBlockTimer(PPEditor):
    FORMAT = FORMAT

    def __init__(self, spec, unit_type=None):
        self.environment = IopeEnvironment(spec, unit_type)
        self.profile = self.environment.profile
        super().__init__(spec, self.environment.unit_type, LAYOUTS)

    def verify_profile(self, session):
        return self.environment.verify_profile(session)

    def show(self, current):
        v = self.snapshot(current)
        names = {code: name for name, code in EXPIRY.items()}
        roles = {v[CORRIDOR][0]: "corridor", v[FIRST][0]: "first-office"}
        if v[SECOND_ENABLED][0]:
            roles[v[SECOND][0]] = "second-office"
        return {
            "format": "cbus-iope-block-timer-v1", "unit_type": self.unit_type,
            "environment_enabled": bool(v[ENABLED][0]),
            "blocks": [
                {"block": i + 1, "seconds": (v["TimerHighByte"][i] << 8) | v["TimerLowByte"][i],
                 "expiry": names.get(v["TimerExpiryCommand"][i]),
                 "expiry_code": v["TimerExpiryCommand"][i], "environment_role": roles.get(i)}
                for i in range(8)
            ],
            "group_objects_resolved": False, "device_verified": False,
            "warnings": [
                "Planning requires an enabled stable Environment role and positive group_cache evidence",
                "Only retained and selected idle, toggle, on and off expiry commands are admitted",
                "An existing corridor duration below 60 seconds requires separate recovery",
            ],
        }

    def plan(self, current, *, identity=None, block=None, seconds=None, expiry=None, group_cache=None):
        identity = self.environment._identity(identity)
        block = integer(block, "block")
        if not 1 <= block <= 8:
            raise PPEditError("block must be 1..8")
        if seconds is not None:
            seconds = integer(seconds, "seconds")
            if not 0 <= seconds <= 65535:
                raise PPEditError("seconds must be 0..65535")
        if expiry is not None and (not isinstance(expiry, str) or expiry not in EXPIRY):
            raise PPEditError("expiry must be idle, toggle, on or off")
        original = self.snapshot(current)
        environment = self.environment.plan(original, identity=identity, group_cache=group_cache)
        if environment.changes:
            raise PPEditError("Environment initialization would change state; apply its separate reviewed plan first")
        if not original[ENABLED][0]:
            raise PPEditError("Environment block timer controls are disabled")
        index = block - 1
        roles = {original[CORRIDOR][0]: "corridor", original[FIRST][0]: "first-office"}
        if original[SECOND_ENABLED][0]:
            roles[original[SECOND][0]] = "second-office"
        role = roles.get(index)
        if role is None:
            raise PPEditError("block is not an enabled Environment timer role")
        if original["InputGroupAddress"][index] == 255:
            raise PPEditError("Environment timer requires an existing assigned group")
        retained = original["TimerExpiryCommand"][index]
        if retained not in EXPIRY.values():
            raise PPEditError("Retained expiry command is outside the bounded simple-command initialization")
        before_seconds = (original["TimerHighByte"][index] << 8) | original["TimerLowByte"][index]
        minimum = 60 if role == "corridor" else 0
        if before_seconds < minimum:
            raise PPEditError("Retained corridor duration below 60 seconds has unmodelled initial control normalization")
        if seconds is not None and seconds < minimum:
            raise PPEditError("Corridor duration must be at least 60 seconds")
        updates = {name: list(values) for name, values in original.items()}
        if seconds is not None:
            updates["TimerHighByte"][index], updates["TimerLowByte"][index] = divmod(seconds, 256)
        if expiry is not None:
            updates["TimerExpiryCommand"][index] = EXPIRY[expiry]
        options = {"block": block, "group_cache": deepcopy(environment.details["options"]["group_cache"])}
        if seconds is not None:
            options["seconds"] = seconds
        if expiry is not None:
            options["expiry"] = expiry
        details = {
            "firmware": identity[1], "catalog_number": self.profile.catalog_number,
            "options": options, "environment_role": role, "timer_variant": 1,
            "minimum_seconds": minimum, "input_source_bound": False,
            "metadata_evidence": environment.details["metadata_evidence"],
            "whole_dialog_save": False, "device_verified": False,
        }
        return self.make_plan(original, updates, details)

    def apply(self, session, plan):
        identity = self.verify_profile(session)
        if not isinstance(plan, PPPlan) or plan.format != FORMAT or plan.unit_type != self.unit_type:
            raise PPEditError("Plan differs from this editor")
        if plan.details.get("firmware") != identity[1]:
            raise PPEditError("Plan firmware differs from the programming session")
        for values in (*plan.expected.values(), *plan.changes.values()):
            if any(type(value) is not int for value in values):
                raise PPEditError("Saved plan parameter arrays require exact integers")
        options = plan.details.get("options")
        if not isinstance(options, dict) or set(options) - OPTION_NAMES:
            raise PPEditError("Plan has invalid canonical options")
        canonical = self.plan(plan.expected, identity=identity, **deepcopy(options))
        try:
            same = json.dumps(canonical.as_dict(), sort_keys=True, allow_nan=False) == json.dumps(
                plan.as_dict(), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise PPEditError("Saved plan is not a canonical JSON document") from error
        if not same:
            raise PPEditError("Saved plan differs from its canonical options and source rules")
        return super().apply(session, canonical)

    def configure(self, session, **options):
        identity = self.verify_profile(session)
        return self.apply(session, self.plan(session.values(), identity=identity, **options))


def plan_from_dict(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("unit_type") not in PROFILES:
        raise PPEditError("Expected a " + FORMAT + " document")
    fields = {"format", "unit_type", "spec_filename", "expected", "changes", "saved",
              "firmware", "catalog_number", "options", "environment_role", "timer_variant",
              "minimum_seconds", "input_source_bound", "metadata_evidence",
              "whole_dialog_save", "device_verified"}
    if set(data) != fields or data["saved"] is not False:
        raise PPEditError("Saved plan has unsupported fields or saved state")
    for key in ("expected", "changes"):
        if not isinstance(data[key], dict) or any(
                not isinstance(name, str) or not isinstance(values, list) or
                any(type(value) is not int for value in values)
                for name, values in data[key].items()):
            raise PPEditError("Saved plan parameter arrays require exact integers")
    reserved = {"format", "unit_type", "spec_filename", "expected", "changes", "saved"}
    return PPPlan(FORMAT, data["unit_type"], data["spec_filename"],
                  {k: tuple(v) for k, v in data["expected"].items()},
                  {k: tuple(v) for k, v in data["changes"].items()},
                  {k: deepcopy(v) for k, v in data.items() if k not in reserved})
