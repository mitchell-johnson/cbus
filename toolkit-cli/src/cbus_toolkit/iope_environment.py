"""Source-pinned IOPE Environment corridor controls; no save or physical I/O.

The bounded edit order is dialog initialization, main enable, corridor block,
first office block, second-office enable, second office block, master group.
Positive group objects require caller metadata. See docs/iope-environment.md.
"""
from __future__ import annotations

from copy import deepcopy
import json
from types import MappingProxyType

from .iope_settings import PROFILES, profile_refusal
from .pp_editor import PPEditError, PPEditor, PPPlan, boolean, integer

FORMAT = "cbus-iope-environment-plan-v1"
CACHE_FORMAT = "cbus-iope-environment-groups-v1"
LAYOUTS = MappingProxyType({
    "Application": ("int", 0x21, 2, 8, 0, 0),
    "InputGroupAddress": ("int", 0x50, 8, 8, 0, 0),
    "CorridorMasterGroup": ("int", 0x60, 1, 8, 0, 0),
    "FirstJoinPrimaryApplication": ("int", 0x63, 1, 8, 0, 0),
    "SecondJoinPrimaryApplication": ("int", 0x64, 1, 8, 0, 0),
    "FirstJoinEnableControlApplication": ("int", 0x65, 1, 8, 0, 0),
    "SecondJoinEnableControlApplication": ("int", 0x66, 1, 8, 0, 0),
    "SecondApplicationBlocks": ("int", 0x69, 1, 8, 0, 0),
    "FirstCorridorOfficeGroupBlock": ("int", 0x6B, 1, 3, 0, 0),
    "CorridorGroupBlock": ("int", 0x6B, 1, 3, 3, 0),
    "FirstCorridorLinkEnable": ("bit", 0x6B, 1, 1, 7, 0),
    "SecondCorridorOfficeGroupBlock": ("int", 0x6C, 1, 3, 0, 0),
    "SecondCorridorLinkEnable": ("bit", 0x6C, 1, 1, 3, 0),
})
CORRIDOR = "CorridorGroupBlock"
FIRST = "FirstCorridorOfficeGroupBlock"
SECOND = "SecondCorridorOfficeGroupBlock"
MASTER = "CorridorMasterGroup"
ENABLED = "FirstCorridorLinkEnable"
SECOND_ENABLED = "SecondCorridorLinkEnable"
WRITABLE = frozenset((CORRIDOR, FIRST, SECOND, MASTER, ENABLED, SECOND_ENABLED))
OPTION_NAMES = frozenset(("enabled", "master_group", "corridor_block", "first_office_block",
                          "second_office_enabled", "second_office_block", "group_cache"))


def _range(value, label, low, high):
    value = integer(value, label)
    if not low <= value <= high:
        raise PPEditError(f"{label} must be {low}..{high}")
    return value


def _cache(value):
    if not isinstance(value, dict) or set(value) != {"format", "source", "applications"}:
        raise PPEditError("group_cache requires format, source and applications")
    if value["format"] != CACHE_FORMAT or not isinstance(value["source"], str) or not value["source"].strip():
        raise PPEditError("group_cache requires the supported format and a nonblank evidence source")
    if not isinstance(value["applications"], list):
        raise PPEditError("group_cache applications must be a list")
    rows, seen = [], set()
    for row in value["applications"]:
        if not isinstance(row, dict) or set(row) != {"address", "groups"}:
            raise PPEditError("Each cached application requires address and groups")
        address = _range(row["address"], "Cached application", 0, 254)
        if address in seen:
            raise PPEditError("Duplicate cached application")
        seen.add(address)
        if not isinstance(row["groups"], list):
            raise PPEditError("Cached groups must be a list")
        groups = [_range(group, "Cached group", 0, 254) for group in row["groups"]]
        if len(set(groups)) != len(groups):
            raise PPEditError("Duplicate cached group")
        rows.append({"address": address, "groups": sorted(groups)})
    return {"format": CACHE_FORMAT, "source": value["source"],
            "applications": sorted(rows, key=lambda row: row["address"])}


class IopeEnvironment(PPEditor):
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

    def show(self, current):
        v = self.snapshot(current)
        return {"format": "cbus-iope-environment-v1", "unit_type": self.unit_type,
                "enabled": bool(v[ENABLED][0]), "master_group": v[MASTER][0],
                "corridor_block": v[CORRIDOR][0] + 1,
                "first_office_block": v[FIRST][0] + 1,
                "second_office_enabled": bool(v[SECOND_ENABLED][0]),
                "second_office_block": v[SECOND][0] + 1,
                "raw_dependencies": {k: list(v[k]) for k in LAYOUTS if k not in WRITABLE},
                "group_objects_resolved": False, "device_verified": False,
                "warnings": ["Group object presence and conflicts require explicit group_cache evidence",
                             "Dialog initialization may normalize dependent corridor controls"]}

    def plan(self, current, *, identity=None, group_cache=None, enabled=None, master_group=None,
             corridor_block=None, first_office_block=None, second_office_enabled=None,
             second_office_block=None):
        identity = self._identity(identity)
        cache = _cache(group_cache)
        options = {"group_cache": cache}
        for key, value in (("enabled", enabled), ("second_office_enabled", second_office_enabled)):
            if value is not None:
                options[key] = boolean(value, key)
        for key, value in (("corridor_block", corridor_block), ("first_office_block", first_office_block),
                           ("second_office_block", second_office_block)):
            if value is not None:
                options[key] = _range(value, key, 1, 8)
        if master_group is not None:
            options["master_group"] = _range(master_group, "master_group", 0, 255)
        original = self.snapshot(current)
        u = {name: list(values) for name, values in original.items()}
        primary, secondary = u["Application"]
        if not 48 <= primary <= 95:
            raise PPEditError("This bounded corridor workflow requires a primary Lighting application 48..95")
        applications = {row["address"]: set(row["groups"]) for row in cache["applications"]}
        if primary not in applications:
            raise PPEditError("group_cache is missing the primary application")

        def group(app, address):
            if address == 255:
                return None
            if app not in applications or address not in applications[app]:
                raise PPEditError(f"group_cache has no positive group object evidence for {app}/{address}")
            return app, address

        blocks = []
        for index, address in enumerate(u["InputGroupAddress"]):
            app = secondary if u["SecondApplicationBlocks"][0] & (1 << index) else primary
            if address != 255 and not 48 <= app <= 95:
                raise PPEditError("Referenced input blocks require a Lighting application 48..95")
            blocks.append(group(app, address))
        joins = []
        for prefix in ("First", "Second"):
            enable_group = u[f"{prefix}JoinEnableControlApplication"][0]
            # LoadJoinModeAttributes chooses Enable Control before Primary.
            joins.append(group(203, enable_group) if enable_group != 255 else
                         group(primary, u[f"{prefix}JoinPrimaryApplication"][0]))
        group(primary, u[MASTER][0])
        if master_group is not None:
            group(primary, master_group)
        derived = []

        def set_value(name, value, cause):
            if u[name][0] != value:
                u[name][0] = value
                derived.append({"parameter": name, "value": value, "cause": cause})

        def first_unused():
            used = {u[name][0] for name in (CORRIDOR, FIRST, SECOND)}
            return next(index for index in range(8) if index not in used)

        def second_click():
            master = group(primary, u[MASTER][0])
            if master is not None and master == blocks[u[SECOND][0]]:
                set_value(MASTER, 255, "second-office event clears a conflicting master group")
            if u[SECOND][0] in (u[CORRIDOR][0], u[FIRST][0]):
                set_value(SECOND, first_unused(), "second-office event repairs a duplicate block")

        initial_active = bool(u[ENABLED][0])

        def enable_event():
            if not initial_active and u[ENABLED][0]:
                for name, threshold, default in ((CORRIDOR, 1, 2), (FIRST, 1, 3), (SECOND, 3, 4)):
                    if u[name][0] <= threshold:
                        set_value(name, default, "first-enable reserved-block relocation")
            master = group(primary, u[MASTER][0])
            if master is not None and (master in blocks or master in joins):
                set_value(MASTER, 255, "enable event clears a master used by an input block or join")
            if u[SECOND_ENABLED][0] and u[SECOND][0] in (u[CORRIDOR][0], u[FIRST][0]):
                set_value(SECOND, first_unused(), "enable event repairs second-office block")
            if u[FIRST][0] == u[CORRIDOR][0]:
                set_value(FIRST, first_unused(), "enable event repairs first-office block")
            if not u[ENABLED][0]:
                set_value(SECOND_ENABLED, 0, "disabling corridor also disables second office")
            second_click()

        # InitialiseCorridorLinking captures initial active state then invokes
        # the virtual enable handler. It runs even when linking is disabled.
        enable_event()
        if enabled is not None and int(enabled) != u[ENABLED][0]:
            u[ENABLED][0] = int(enabled)
            enable_event()
        if not u[ENABLED][0] and any(value is not None for value in
                                   (master_group, corridor_block, first_office_block, second_office_block)):
            raise PPEditError("Corridor controls are disabled; enable linking first")

        def select_block(name, number):
            if number is None:
                return
            index = number - 1
            other = {u[CORRIDOR][0], u[FIRST][0]} if name == SECOND else {
                u[FIRST if name == CORRIDOR else CORRIDOR][0]}
            if name != SECOND and u[SECOND_ENABLED][0]:
                other.add(u[SECOND][0])
            master = group(primary, u[MASTER][0])
            if index in other or (master is not None and blocks[index] == master):
                raise PPEditError("Block is excluded by the original corridor role/group selector")
            u[name][0] = index

        select_block(CORRIDOR, corridor_block)
        select_block(FIRST, first_office_block)
        if second_office_enabled is not None:
            if second_office_enabled and not u[ENABLED][0]:
                raise PPEditError("Second office requires corridor linking enabled")
            if int(second_office_enabled) != u[SECOND_ENABLED][0]:
                u[SECOND_ENABLED][0] = int(second_office_enabled)
                second_click()
        if second_office_block is not None and not u[SECOND_ENABLED][0]:
            raise PPEditError("Second office block is disabled")
        select_block(SECOND, second_office_block)
        if master_group is not None:
            master = group(primary, master_group)
            if master is not None and (master in blocks or master in joins):
                raise PPEditError("Master group is excluded because an input block or join uses it")
            u[MASTER][0] = master_group
        details = {"firmware": identity[1], "catalog_number": self.profile.catalog_number,
                   "options": deepcopy(options), "derived": derived,
                   "metadata_evidence": "caller group objects; database freshness requires external verification",
                   "whole_dialog_save": False, "device_verified": False}
        return self.make_plan(original, u, details)

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
              "firmware", "catalog_number", "options", "derived", "metadata_evidence",
              "whole_dialog_save", "device_verified"}
    if set(data) != fields or data["saved"] is not False:
        raise PPEditError("Saved plan has unsupported fields or saved state")
    for key in ("expected", "changes"):
        if not isinstance(data[key], dict) or any(
                not isinstance(name, str) or not isinstance(values, list) or
                any(type(value) is not int for value in values)
                for name, values in data[key].items()):
            raise PPEditError("Saved plan parameter arrays require exact integers")
    try:
        expected = {k: tuple(v) for k, v in data["expected"].items()}
        changes = {k: tuple(v) for k, v in data["changes"].items()}
    except (KeyError, TypeError, AttributeError) as error:
        raise PPEditError("Plan requires numeric expected and changes mappings") from error
    reserved = {"format", "unit_type", "spec_filename", "expected", "changes", "saved"}
    details = {k: deepcopy(v) for k, v in data.items() if k not in reserved}
    return PPPlan(FORMAT, data["unit_type"], data.get("spec_filename"), expected, changes, details)
