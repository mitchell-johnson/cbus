"""Source-pinned IOPE Logic tab followed by optional logic recovery modal.

The editor stages verified PP values only. It neither saves nor opens hardware.
See docs/iope-logic.md for the exact event order and preservation boundary.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
from types import MappingProxyType

from .din_output_settings import level_to_percent, percent_to_level
from .iope_settings import PROFILES, profile_refusal
from .pp_editor import PPEditError, PPEditor, PPPlan, boolean, integer

FORMAT = "cbus-iope-logic-plan-v1"
CACHE_FORMAT = "cbus-iope-logic-groups-v1"
ASSOCIATIONS = tuple(f"LogicGA{number}Associations" for number in range(13, 17))
LAYOUTS = MappingProxyType({
    "Application": ("int", 0x21, 2, 8, 0, 0),
    "OutputGroupAddress": ("int", 0x58, 4, 8, 0, 0),
    "OutputLogicGroupAddress": ("int", 0x5C, 4, 8, 0, 0),
    **{name: ("int", 0x70, 4, 1, index, 0) for index, name in enumerate(ASSOCIATIONS)},
    "LogicFunction": ("int", 0x70, 4, 1, 7, 0),
    "LevelStoreEnable": ("bit", 0x6E, 4, 1, 0, 0),
    "LogicLevelStoreEnable": ("bit", 0x6E, 4, 1, 4, 0),
    "LightLevelOutput": ("int", 0x08, 8, 8, 0, 0),
})
WRITABLE = frozenset((*ASSOCIATIONS, "LogicFunction", "OutputLogicGroupAddress",
                      "LogicLevelStoreEnable", "LightLevelOutput"))
SOURCE_EXE_SHA256 = "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab"
SOURCE_MAP_SHA256 = "f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb"
_DETAIL_KEYS = ("firmware", "catalog_number", "options", "derived", "recovery_modal_opened",
                "source_exe_sha256", "whole_dialog_save", "device_verified")


def _range(value, label, low, high):
    value = integer(value, label)
    if not low <= value <= high:
        raise PPEditError(f"{label} must be {low}..{high}")
    return value


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise PPEditError("Plan must contain ordinary JSON values") from error


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


def _rows(value, label, maximum, allowed):
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PPEditError(label + " must be a mapping")
    for number, controls in value.items():
        _range(number, label + " number", 1, maximum)
        if not isinstance(controls, Mapping) or not controls or set(controls) - allowed:
            raise PPEditError(label + " requires a nonempty mapping of supported controls")
    return value


def _replay_options(options):
    if not isinstance(options, dict) or set(options) != {"channels", "logic_groups", "group_cache"}:
        raise PPEditError("Plan requires canonical logic options")
    result = {"group_cache": options["group_cache"]}
    for name in ("channels", "logic_groups"):
        rows = options[name]
        if not isinstance(rows, dict) or any(not isinstance(key, str) or key not in ("1", "2", "3", "4") for key in rows):
            raise PPEditError("Plan row keys must be canonical numbers")
        result[name] = {int(key): value for key, value in rows.items()}
    return result


class IopeLogic(PPEditor):
    FORMAT = FORMAT

    def __init__(self, spec, unit_type=None):
        unit_type = spec.unit_type if unit_type is None else unit_type
        if not isinstance(unit_type, str) or unit_type not in PROFILES:
            raise PPEditError("Only IOPE1R1, IOPE2R2 and IOPE2C4 use this workflow")
        if spec.filename != unit_type + ".xml" or spec.unit_type != unit_type:
            raise PPEditError(f"Use the matching {unit_type}.xml specification")
        self.profile = PROFILES[unit_type]
        super().__init__(spec, unit_type, LAYOUTS)

    def _identity(self, identity):
        if not isinstance(identity, (tuple, list)) or len(identity) != 3:
            raise PPEditError("Logic planning requires explicit (unit type, firmware, catalogue) identity")
        unit_type, firmware, catalog = identity
        if not isinstance(unit_type, str):
            raise PPEditError("Unit identity type must be text")
        reason = profile_refusal(unit_type, firmware)
        if reason or unit_type != self.unit_type:
            raise PPEditError(reason or "Unit identity differs from the selected IOPE schema")
        if catalog not in (None, self.profile.catalog_number):
            raise PPEditError("Catalogue identity differs from the selected IOPE profile")
        return tuple(identity)

    def verify_profile(self, session):
        return self._identity((getattr(session, "unit_type", None), getattr(session, "firmware", None),
                               getattr(session, "catalog_number", None)))

    def show(self, current):
        values = self.snapshot(current)
        channels = []
        for index in range(self.profile.outputs):
            groups = [group + 1 for group, name in enumerate(ASSOCIATIONS) if values[name][index]]
            channels.append({"channel": index + 1, "logic_groups": groups,
                             "logic_function": ("and", "or")[values["LogicFunction"][index]],
                             "logic_function_editable": bool(groups)})
        groups = []
        for index in range(4):
            level = values["LightLevelOutput"][index + 4]
            store = bool(values["LogicLevelStoreEnable"][index])
            groups.append({"logic_group": index + 1, "group_address": values["OutputLogicGroupAddress"][index],
                           "group_address_editable": any(values[ASSOCIATIONS[index]][:self.profile.outputs]),
                           "level_store": store, "recovery_level": level,
                           "recovery_percent": level_to_percent(level), "recovery_percent_editable": not store})
        return {"format": "cbus-iope-logic-v1", "unit_type": self.unit_type,
                "application": values["Application"][0], "channels": channels, "logic_groups": groups,
                "group_objects_resolved": False, "whole_dialog_save": False, "device_verified": False}

    def plan(self, current, *, identity=None, channels=None, logic_groups=None, group_cache=None):
        """Edit Logic controls, then optionally open the four-row recovery modal.

        The modal opens iff a recovery control is supplied, normalizing all four
        logic recovery bytes. Main-tab group assignments precede this phase.
        """
        identity = self._identity(identity)
        cache = _cache(group_cache)
        channels = _rows(channels, "Channels", self.profile.outputs, {"logic_groups", "logic_function"})
        logic_groups = _rows(logic_groups, "Logic groups", 4, {"group_address", "level_store", "recovery_percent"})
        original = self.snapshot(current)
        u = {name: list(values) for name, values in original.items()}
        primary = u["Application"][0]
        if not 48 <= primary <= 95:
            raise PPEditError("This bounded logic workflow requires a primary Lighting application 48..95")
        applications = {row["address"]: set(row["groups"]) for row in cache["applications"]}
        if primary not in applications:
            raise PPEditError("group_cache is missing the primary application")

        def require_group(address):
            if address != 255 and address not in applications[primary]:
                raise PPEditError(f"group_cache has no positive group object evidence for {primary}/{address}")

        # All four model logic objects and only existing output channel objects
        # participate in GroupChanged. Never resolve hidden stored output slots.
        for address in (*u["OutputLogicGroupAddress"], *u["OutputGroupAddress"][:self.profile.outputs]):
            require_group(address)
        selected_channels, selected_groups, derived = {}, {}, []
        for channel in sorted(channels):
            index, controls = channel - 1, channels[channel]
            selected = selected_channels[str(channel)] = {}
            if "logic_groups" in controls:
                groups = controls["logic_groups"]
                if not isinstance(groups, list):
                    raise PPEditError("Channel logic_groups must be a list of row numbers")
                groups = [_range(group, "Logic group", 1, 4) for group in groups]
                if len(set(groups)) != len(groups):
                    raise PPEditError("Channel logic_groups must not contain duplicates")
                selected["logic_groups"] = sorted(groups)
                for group, name in enumerate(ASSOCIATIONS):
                    u[name][index] = int(group + 1 in groups)
            if "logic_function" in controls:
                function = controls["logic_function"]
                if not isinstance(function, str) or function not in ("and", "or"):
                    raise PPEditError("IOPE logic_function must be and or or, including dimmer channels")
                if not any(u[name][index] for name in ASSOCIATIONS):
                    raise PPEditError("Toolkit disables logic_function when the channel has no logic associations")
                selected["logic_function"] = function
                u["LogicFunction"][index] = ("and", "or").index(function)
        for group in sorted(logic_groups):
            index, controls = group - 1, logic_groups[group]
            selected = selected_groups[str(group)] = {}
            if "group_address" in controls:
                address = _range(controls["group_address"], "Group address", 0, 255)
                require_group(address)
                if not any(u[ASSOCIATIONS[index]][:self.profile.outputs]):
                    raise PPEditError("Toolkit disables group_address when the logic row has no active channel associations")
                selected["group_address"] = address
                u["OutputLogicGroupAddress"][index] = address
                if address != 255:
                    # GroupChanged includes self. The same-pointer setter also
                    # calls Changed; do not optimize an equal address away.
                    for peer in range(4):
                        if u["OutputLogicGroupAddress"][peer] == address:
                            u["LightLevelOutput"][index + 4] = u["LightLevelOutput"][peer + 4]
                            u["LogicLevelStoreEnable"][index] = u["LogicLevelStoreEnable"][peer]
                            derived.append({"logic_group": group, "copied_from_logic_group": peer + 1})
                    for peer in range(self.profile.outputs):
                        if u["OutputGroupAddress"][peer] == address:
                            u["LightLevelOutput"][index + 4] = u["LightLevelOutput"][peer]
                            u["LogicLevelStoreEnable"][index] = u["LevelStoreEnable"][peer]
                            derived.append({"logic_group": group, "copied_from_channel": peer + 1})
            if "level_store" in controls:
                selected["level_store"] = boolean(controls["level_store"], "Logic level_store")
            if "recovery_percent" in controls:
                selected["recovery_percent"] = _range(controls["recovery_percent"], "Logic recovery percent", 0, 100)
        recovery = any(set(controls) & {"level_store", "recovery_percent"} for controls in logic_groups.values())
        if recovery:
            # SetupRecoveryLevels binds all four rows, including unused rows.
            # Each SetCBusUnit calls chkLevelStoreEnableClick -> Properties.Changed.
            for index in range(4):
                u["LightLevelOutput"][index + 4] = percent_to_level(level_to_percent(u["LightLevelOutput"][index + 4]))
            derived.append({"recovery_modal_initialization": [1, 2, 3, 4]})
            for group in sorted(logic_groups):
                index, controls = group - 1, selected_groups[str(group)]
                if "level_store" in controls:
                    u["LogicLevelStoreEnable"][index] = int(controls["level_store"])
                    # Explicit checkbox click writes the displayed slider even
                    # while disabled. Logic SaveOutputs never forces level255.
                    u["LightLevelOutput"][index + 4] = percent_to_level(level_to_percent(u["LightLevelOutput"][index + 4]))
                if "recovery_percent" in controls:
                    if u["LogicLevelStoreEnable"][index]:
                        raise PPEditError("Toolkit disables recovery_percent while logic level_store is enabled")
                    u["LightLevelOutput"][index + 4] = percent_to_level(controls["recovery_percent"])
        return self.make_plan(original, u, {
            "firmware": identity[1], "catalog_number": identity[2],
            "options": {"channels": selected_channels, "logic_groups": selected_groups, "group_cache": cache},
            "derived": derived, "recovery_modal_opened": recovery, "source_exe_sha256": SOURCE_EXE_SHA256,
            "whole_dialog_save": False, "device_verified": False})

    def apply(self, session, plan):
        if not isinstance(plan, PPPlan) or (plan.format, plan.unit_type, plan.spec_filename) != (
                FORMAT, self.unit_type, self.spec.filename):
            raise PPEditError("Plan differs from this editor")
        if set(plan.expected) != set(LAYOUTS) or set(plan.changes) - WRITABLE:
            raise PPEditError("Plan contains fields outside this workflow")
        if not isinstance(plan.details, Mapping):
            raise PPEditError("Plan details must be a mapping")
        identity = self.verify_profile(session)
        planned_identity = (plan.unit_type, plan.details.get("firmware"), plan.details.get("catalog_number"))
        self._identity(planned_identity)
        if identity[1] != planned_identity[1] or (planned_identity[2] is not None and identity[2] != planned_identity[2]):
            raise PPEditError("Plan was created for another firmware or catalogue")
        canonical = self.plan(plan.expected, identity=planned_identity, **_replay_options(plan.details.get("options")))
        if _json(canonical.as_dict()) != _json(plan.as_dict()):
            raise PPEditError("Plan does not reproduce its canonical controls and dependent writes")
        return super().apply(session, canonical)

    def configure(self, session, **options):
        return self.apply(session, self.plan(session.values(), identity=self.verify_profile(session), **options))


def plan_from_dict(data):
    """Read an unsaved plan; apply replays controls and all hidden writes."""
    if (not isinstance(data, dict) or data.get("format") != FORMAT
            or not isinstance(data.get("unit_type"), str) or data["unit_type"] not in PROFILES):
        raise PPEditError("Expected a " + FORMAT + " document")
    required = {"format", "unit_type", "spec_filename", "expected", "changes", "saved", *_DETAIL_KEYS}
    if set(data) != required or data["saved"] is not False:
        raise PPEditError("Expected the complete unsaved logic plan document")
    values = {}
    for key in ("expected", "changes"):
        rows = data[key]
        if not isinstance(rows, dict) or any(not isinstance(name, str) or not isinstance(row, list)
                or any(type(value) is not int for value in row) for name, row in rows.items()):
            raise PPEditError("Plan parameters must contain integer arrays")
        values[key] = rows
    _replay_options(data["options"])
    _json(data)
    return PPPlan(FORMAT, data["unit_type"], data["spec_filename"], values["expected"], values["changes"],
                  {key: deepcopy(data[key]) for key in _DETAIL_KEYS})
