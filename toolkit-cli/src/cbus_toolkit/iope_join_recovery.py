"""The source-pinned IOPE Join Mode Recovery radio and its five-bit save.

Group/application edits and complete SaveJoinModeAttributes are excluded.
Caller group metadata establishes the actual first-Join object predicate.
"""
from __future__ import annotations

from copy import deepcopy
import json
from types import MappingProxyType

from .iope_environment import CACHE_FORMAT, _cache
from .iope_settings import PROFILES, profile_refusal
from .pp_editor import PPEditError, PPEditor, PPPlan

FORMAT = "cbus-iope-join-recovery-plan-v1"
RECOVERY = ("first-join", "second-join", "quad-join", "restore")
STARTUP = ("PrimJoin1EnabledStartup", "PrimJoin2EnabledStartup",
           "ControlJoin1EnabledStartup", "ControlJoin2EnabledStartup")
STORE = "JoinEnableStateStoreEnabled"
GROUPS = ("FirstJoinPrimaryApplication", "SecondJoinPrimaryApplication",
          "FirstJoinEnableControlApplication", "SecondJoinEnableControlApplication")
LAYOUTS = MappingProxyType({
    **{name: ("bit", 0x1C, 1, 1, index + 2, 0) for index, name in enumerate(STARTUP)},
    "Application": ("int", 0x21, 2, 8, 0, 0),
    STORE: ("bit", 0x3E, 1, 1, 7, 0),
    **{name: ("int", 0x63 + index, 1, 8, 0, 0) for index, name in enumerate(GROUPS)},
})
WRITABLE = frozenset((*STARTUP, STORE))
DETAILS = frozenset(("firmware", "catalog_number", "options", "join_application", "derived",
                     "metadata_evidence", "whole_dialog_save", "device_verified"))


class IopeJoinRecovery(PPEditor):
    FORMAT = FORMAT

    def __init__(self, spec, unit_type=None):
        unit_type = spec.unit_type if unit_type is None else unit_type
        if unit_type not in PROFILES:
            raise PPEditError("Only IOPE1R1, IOPE2R2 and IOPE2C4 use this workflow")
        if spec.filename != unit_type + ".xml" or spec.unit_type != unit_type:
            raise PPEditError(f"Use {unit_type}.xml for {unit_type}")
        self.profile = PROFILES[unit_type]
        super().__init__(spec, unit_type, LAYOUTS)

    def _identity(self, identity):
        if not isinstance(identity, (tuple, list)) or len(identity) != 3:
            raise PPEditError("Exact unit type, firmware and catalogue identity are required")
        unit_type, firmware, catalog = identity
        reason = profile_refusal(unit_type, firmware)
        if reason or unit_type != self.unit_type:
            raise PPEditError("Unit identity is not admitted: " + (reason or "type differs"))
        if catalog not in (None, "", self.profile.catalog_number):
            raise PPEditError("Unit catalogue differs from the admitted profile")
        return unit_type, firmware, catalog

    @staticmethod
    def recovery(values):
        """Original load priority spans both applications, including odd pairs."""
        if values[STORE][0]:
            return "restore"
        first = bool(values[STARTUP[0]][0] or values[STARTUP[2]][0])
        second = bool(values[STARTUP[1]][0] or values[STARTUP[3]][0])
        if first and second:
            return "quad-join"
        return "second-join" if second else "first-join"

    def show(self, current):
        v = self.snapshot(current)
        return {"format": "cbus-iope-join-recovery-v1", "unit_type": self.unit_type,
                "recovery": self.recovery(v), "choices": list(RECOVERY),
                "raw_dependencies": {name: list(v[name]) for name in LAYOUTS if name not in WRITABLE},
                "raw_recovery": {name: v[name][0] for name in (*STARTUP, STORE)},
                "group_objects_resolved": False, "device_verified": False,
                "warnings": ["Radio eligibility requires an assigned first Join group object",
                             "Applying a recovery choice normalizes all five recovery bits"]}

    def plan(self, current, *, identity=None, group_cache=None, recovery=None):
        identity = self._identity(identity)
        if recovery not in RECOVERY:
            raise PPEditError("recovery must be first-join, second-join, quad-join or restore")
        cache = _cache(group_cache)
        original = self.snapshot(current)
        primary = original["Application"][0]
        if not 48 <= primary <= 95:
            raise PPEditError("This bounded workflow requires a primary Lighting application 48..95")
        applications = {row["address"]: set(row["groups"]) for row in cache["applications"]}
        if primary not in applications:
            raise PPEditError("group_cache is missing the primary application")
        effective = []
        for prefix in ("First", "Second"):
            prim = original[f"{prefix}JoinPrimaryApplication"][0]
            control = original[f"{prefix}JoinEnableControlApplication"][0]
            if prim != 255 and control != 255:
                raise PPEditError("Dual-populated Join application fields require the full group workflow")
            if control != 255:
                app, group = 203, control
            elif prim != 255:
                app, group = primary, prim
            else:
                effective.append(None)
                continue
            if app not in applications or group not in applications[app]:
                raise PPEditError(f"group_cache has no positive group object evidence for {app}/{group}")
            effective.append((app, group))
        if effective[0] is None:
            raise PPEditError("Join Mode Recovery is disabled without an assigned first Join group")
        application = effective[0][0]
        if effective[1] is not None and effective[1][0] != application:
            raise PPEditError("Mixed-application Join groups require the full group workflow")
        updates = {name: list(values) for name, values in original.items()}
        for name in WRITABLE:
            updates[name][0] = 0
        if recovery == "restore":
            updates[STORE][0] = 1
        else:
            offset = 2 if application == 203 else 0
            updates[STARTUP[offset]][0] = int(recovery in ("first-join", "quad-join"))
            updates[STARTUP[offset + 1]][0] = int(recovery in ("second-join", "quad-join"))
        details = {"firmware": identity[1], "catalog_number": self.profile.catalog_number,
                   "options": {"recovery": recovery, "group_cache": deepcopy(cache)},
                   "join_application": application,
                   "derived": ["All four startup bits and the store bit are normalized together"],
                   "metadata_evidence": "caller group objects; database freshness requires external verification",
                   "whole_dialog_save": False, "device_verified": False}
        return self.make_plan(original, updates, details)

    def verify_profile(self, session):
        return self._identity((getattr(session, "unit_type", None), getattr(session, "firmware", None),
                               getattr(session, "catalog_number", None)))

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
        if not isinstance(options, dict) or set(options) != {"recovery", "group_cache"}:
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
        return self.apply(session, self.plan(session.values(), identity=self.verify_profile(session), **options))


def plan_from_dict(data):
    fields = {"format", "unit_type", "spec_filename", "expected", "changes", "saved"} | DETAILS
    if not isinstance(data, dict) or set(data) != fields or data.get("format") != FORMAT:
        raise PPEditError("Expected a complete " + FORMAT + " document")
    if data["saved"] is not False or data["unit_type"] not in PROFILES:
        raise PPEditError("Saved plan has unsupported identity or saved state")
    for key in ("expected", "changes"):
        if not isinstance(data[key], dict) or any(
                not isinstance(name, str) or not isinstance(values, list) or
                any(type(value) is not int for value in values) for name, values in data[key].items()):
            raise PPEditError("Saved plan parameter arrays require exact integers")
    return PPPlan(FORMAT, data["unit_type"], data["spec_filename"],
                  {k: tuple(v) for k, v in data["expected"].items()},
                  {k: tuple(v) for k, v in data["changes"].items()},
                  {k: deepcopy(data[k]) for k in DETAILS})
