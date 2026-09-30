"""Existing-application IOPE Environment JOIN selectors and group-field projection.

The complete Environment Save and application changes are outside this component.
"""
from __future__ import annotations

from copy import deepcopy
import json
from types import MappingProxyType

from .iope_environment import CACHE_FORMAT, LAYOUTS as ENV_LAYOUTS, IopeEnvironment, _cache, _range
from .iope_join_recovery import GROUPS
from .iope_settings import PROFILES
from .pp_editor import PPEditError, PPEditor, PPPlan

FORMAT = "cbus-iope-join-groups-plan-v1"
LAYOUTS = MappingProxyType({**ENV_LAYOUTS, "AreaGroupAddress": ("int", 0x68, 1, 8, 0, 0)})
WRITABLE = frozenset(GROUPS)
DETAILS = frozenset(("firmware", "catalog_number", "options", "join_application", "selector_order",
                     "initialization", "projection", "metadata_evidence", "whole_dialog_save",
                     "device_verified"))


class IopeJoinGroups(PPEditor):
    FORMAT = FORMAT

    def __init__(self, spec, unit_type=None):
        unit_type = spec.unit_type if unit_type is None else unit_type
        self.environment = IopeEnvironment(spec, unit_type)
        self.profile = PROFILES[unit_type]
        super().__init__(spec, unit_type, LAYOUTS)

    def _identity(self, identity):
        return self.environment._identity(identity)

    def show(self, current):
        values = self.snapshot(current)
        primary = values["Application"][0]
        effective = []
        for prefix in ("First", "Second"):
            control = values[prefix + "JoinEnableControlApplication"][0]
            prim = values[prefix + "JoinPrimaryApplication"][0]
            effective.append([203, control] if control != 255 else [primary, prim] if prim != 255 else None)
        return {"format": "cbus-iope-join-groups-v1", "unit_type": self.unit_type,
                "effective_groups": effective, "load_priority": "Enable Control before Primary",
                "raw_dependencies": {name: list(value) for name, value in values.items()},
                "group_objects_resolved": False, "whole_dialog_save": False, "device_verified": False}

    def plan(self, current, *, identity=None, group_cache=None, first_group=None, second_group=None):
        identity = self._identity(identity)
        cache = _cache(group_cache)
        if first_group is None and second_group is None:
            raise PPEditError("Select at least one Join group")
        # Clearing first would disable the second selector and lose the loaded
        # application on reload; that parent lifecycle is not this component.
        options = {"group_cache": cache}
        if first_group is not None:
            options["first_group"] = _range(first_group, "first_group", 0, 254)
        if second_group is not None:
            options["second_group"] = _range(second_group, "second_group", 0, 255)
        original = self.snapshot(current)
        primary, secondary = original["Application"]
        if not 48 <= primary <= 95:
            raise PPEditError("Primary application must be Lighting 48..95")
        applications = {row["address"]: set(row["groups"]) for row in cache["applications"]}

        def group(app, address):
            if address == 255:
                return None
            if app not in applications or address not in applications[app]:
                raise PPEditError(f"group_cache has no positive group object evidence for {app}/{address}")
            return app, address

        joins = []
        for prefix in ("First", "Second"):
            prim = original[prefix + "JoinPrimaryApplication"][0]
            control = original[prefix + "JoinEnableControlApplication"][0]
            if prim != 255 and control != 255:
                raise PPEditError("Dual-populated Join fields require the complete application workflow")
            joins.append(group(203, control) if control != 255 else group(primary, prim))
        if joins[0] is None:
            raise PPEditError("An assigned first Join group is required for this existing-application component")
        application = joins[0][0]
        if joins[1] is not None and joins[1][0] != application:
            raise PPEditError("Mixed-application Join groups require the complete application workflow")
        # SetCBusUnit invokes the inherited corridor initializer. Admit its
        # already-canonical states, so group selections own no corridor writes.
        initialized = self.environment.plan(current, identity=identity, group_cache=cache)
        if initialized.changes:
            raise PPEditError("Environment initialization would change corridor fields; initialize separately")
        blocks = []
        for index, address in enumerate(original["InputGroupAddress"]):
            app = secondary if original["SecondApplicationBlocks"][0] & (1 << index) else primary
            if address != 255 and not 48 <= app <= 95:
                raise PPEditError("Referenced input blocks require a Lighting application 48..95")
            blocks.append(group(app, address))
        area = group(primary, original["AreaGroupAddress"][0])
        corridor = blocks[original["CorridorGroupBlock"][0]] if original["FirstCorridorLinkEnable"][0] else None
        order = []
        for index, name in enumerate(("first_group", "second_group")):
            if name not in options:
                continue
            selected = group(application, options[name])
            # Original IsUnused fast-path accepts the second unused object
            # before any conflicts. First unused is outside this component.
            if selected is not None:
                if selected in blocks:
                    raise PPEditError(f"{name} is already assigned to an input block")
                if selected == area:
                    raise PPEditError(f"{name} is already the Area group")
                if selected == joins[1 - index]:
                    raise PPEditError(f"{name} is already the other Join group")
                if selected == corridor:
                    raise PPEditError(f"{name} is the active corridor link group")
            joins[index] = selected
            order.append(name)
        updated = {name: list(value) for name, value in original.items()}
        for name in GROUPS:
            updated[name][0] = 255
        suffix = "JoinEnableControlApplication" if application == 203 else "JoinPrimaryApplication"
        for prefix, selected in zip(("First", "Second"), joins):
            updated[prefix + suffix][0] = selected[1] if selected is not None else 255
        details = {"firmware": identity[1], "catalog_number": self.profile.catalog_number,
                   "options": deepcopy(options), "join_application": application,
                   "selector_order": order, "initialization": "canonical corridor state; no dependent writes",
                   "projection": "four Join group fields only; both groups use first Join application",
                   "metadata_evidence": "caller same-network objects; freshness requires external verification",
                   "whole_dialog_save": False, "device_verified": False}
        return self.make_plan(original, updated, details)

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
        if not isinstance(options, dict) or set(options) - {"group_cache", "first_group", "second_group"}:
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
