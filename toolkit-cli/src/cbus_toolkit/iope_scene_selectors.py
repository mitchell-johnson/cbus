"""Bounded existing IOPE scene action selectors; whole scene-manager save excluded."""
from __future__ import annotations

from copy import deepcopy
import json
from types import MappingProxyType

from .iope_environment import IopeEnvironment, _range
from .iope_settings import PROFILES
from .pp_editor import PPEditError, PPEditor, PPPlan

FORMAT = "cbus-iope-scene-selectors-plan-v1"
CACHE_FORMAT = "cbus-iope-scene-selector-groups-v1"
LAYOUTS = MappingProxyType({
    "Application": ("int", 0x21, 2, 8, 0, 0),
    "SceneTriggerGroup": ("int", 0x67, 1, 8, 0, 0),
    "SceneIndex": ("int", 0xA2, 4, 3, 0, 0),
    "SceneCommandRampRate": ("int", 0xA2, 4, 4, 4, 0),
    "ActionSelector": ("int", 0xA6, 4, 8, 0, 0),
    "ActionSelectorAllOff": ("int", 0xAA, 4, 8, 0, 0),
    "SceneTablePointer": ("int", 0xAE, 4, 8, 0, 0),
    "SceneTable": ("int", 0xB2, 64, 8, 0, 0),
})
WRITABLE = frozenset(("ActionSelector", "ActionSelectorAllOff"))
OPTION_NAMES = frozenset(("scene", "normal_selector", "all_off_selector", "group_cache"))
SOURCE = MappingProxyType({
    "exe_sha256": "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab",
    "map_sha256": "f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb",
    "unitspec_sha256": "955f26d0422bb3c02860545f9e7402da6fcbc9674f518a2434bb462df8795d13",
    "resource_sha256": "18d3e7e79180f53c462f37c84d9080ebfb0e76f2492c2db07dbf5d54a18a0c8d",
})


def _cache(value, trigger):
    if not isinstance(value, dict) or set(value) != {"format", "source", "applications", "action_selectors"}:
        raise PPEditError("group_cache requires format, source, applications and action_selectors")
    if value["format"] != CACHE_FORMAT or not isinstance(value["source"], str) or not value["source"].strip():
        raise PPEditError("group_cache requires the supported format and nonblank evidence source")
    if not isinstance(value["applications"], list) or len(value["applications"]) > 255:
        raise PPEditError("Cached applications require a bounded list")
    rows, seen = [], set()
    for row in value["applications"]:
        if not isinstance(row, dict) or set(row) != {"address", "groups"}:
            raise PPEditError("Each cached application requires address and groups")
        address = _range(row["address"], "Cached application", 0, 254)
        if address in seen:
            raise PPEditError("Duplicate cached application")
        seen.add(address)
        if not isinstance(row["groups"], list) or len(row["groups"]) > 255:
            raise PPEditError("Cached groups require a bounded list")
        groups = [_range(g, "Cached group", 0, 254) for g in row["groups"]]
        if len(set(groups)) != len(groups):
            raise PPEditError("Duplicate cached group")
        rows.append({"address": address, "groups": sorted(groups)})
    inventories = value["action_selectors"]
    if not isinstance(inventories, list) or len(inventories) != 1:
        raise PPEditError("Exactly one complete target LevelManager inventory is required")
    row = inventories[0]
    if not isinstance(row, dict) or set(row) != {"application", "group", "addresses"}:
        raise PPEditError("Action inventory requires application, group and addresses")
    application = _range(row["application"], "Action application", 0, 254)
    group = _range(row["group"], "Action group", 0, 254)
    if application != 202 or group != trigger:
        raise PPEditError("Action inventory must name the retained app202 Trigger group")
    if not isinstance(row["addresses"], list) or len(row["addresses"]) > 254:
        raise PPEditError("Action inventory requires a bounded complete address list")
    addresses = [_range(a, "Action address", 1, 254) for a in row["addresses"]]
    if len(set(addresses)) != len(addresses):
        raise PPEditError("Duplicate action inventory object identity")
    return {"format": CACHE_FORMAT, "source": value["source"],
            "applications": sorted(rows, key=lambda r: r["address"]),
            "action_selectors": [{"application": 202, "group": trigger, "addresses": sorted(addresses)}]}


class IopeSceneSelectors(PPEditor):
    FORMAT = FORMAT

    def __init__(self, spec, unit_type=None):
        # Reuse profile identity admission without requiring unrelated Environment layouts.
        unit_type = spec.unit_type if unit_type is None else unit_type
        if unit_type not in PROFILES or spec.unit_type != unit_type or spec.filename != unit_type + ".xml":
            raise PPEditError("Use the exact IOPE1R1, IOPE2R2 or IOPE2C4 specification")
        self.profile = PROFILES[unit_type]
        super().__init__(spec, unit_type, LAYOUTS)

    def _identity(self, identity):
        return IopeEnvironment._identity(self, identity)

    def verify_profile(self, session):
        return self._identity((getattr(session, "unit_type", None), getattr(session, "firmware", None),
                               getattr(session, "catalog_number", None)))

    def show(self, current):
        v = self.snapshot(current)
        return {"format": "cbus-iope-scene-selectors-v1", "unit_type": self.unit_type,
                "trigger_group": v["SceneTriggerGroup"][0],
                "scenes": [{"scene": i + 1, "normal_selector": v["ActionSelector"][i],
                            "all_off_selector": v["ActionSelectorAllOff"][i]} for i in range(4)],
                "group_objects_resolved": False, "whole_dialog_save": False, "device_verified": False,
                "warnings": ["Requires complete positive existing Trigger action inventory and stable four-scene graph",
                             "Only one existing normal or all-off selector may be selected; whole SceneManager save is excluded"]}

    def plan(self, current, *, identity=None, scene=None, normal_selector=None,
             all_off_selector=None, group_cache=None):
        identity = self._identity(identity)
        scene = _range(scene, "Scene", 1, 4)
        if (normal_selector is None) == (all_off_selector is None):
            raise PPEditError("Select exactly one normal_selector or all_off_selector")
        field = "ActionSelector" if normal_selector is not None else "ActionSelectorAllOff"
        selected = _range(normal_selector if normal_selector is not None else all_off_selector,
                          "Selected action", 1, 254)
        original = self.snapshot(current)
        trigger = original["SceneTriggerGroup"][0]
        if trigger == 255:
            raise PPEditError("A retained existing Trigger group is required")
        cache = _cache(group_cache, trigger)
        groups = {r["address"]: set(r["groups"]) for r in cache["applications"]}
        if trigger not in groups.get(202, set()):
            raise PPEditError("Retained Trigger group lacks positive app202 group evidence")
        primary = original["Application"][0]
        if not 48 <= primary <= 95:
            raise PPEditError("Retained scene content requires a Lighting primary application")
        if original["SceneIndex"] != (0, 1, 2, 3):
            raise PPEditError("Retained SceneIndex must be canonical 0 1 2 3")
        if original["SceneTablePointer"] != (0xB2, 0xC2, 0xD2, 0xE2):
            raise PPEditError("Retained scene pointers must describe four complete eight-command scenes; external pointers are excluded")
        table = original["SceneTable"]
        if any(g == 255 or g not in groups.get(primary, set()) for g in table[::2]):
            raise PPEditError("Every retained scene command requires positive existing primary Lighting group evidence")
        if any(len(set(table[start:start + 16:2])) != 8 for start in range(0, 64, 16)):
            raise PPEditError("Each retained scene requires eight distinct command groups; native loading collapses duplicates")
        retained = (*original["ActionSelector"], *original["ActionSelectorAllOff"])
        if any(not 1 <= a <= 254 for a in retained) or len(set(retained)) != 8:
            raise PPEditError("All eight retained selectors require distinct positive action identities")
        inventory = set(cache["action_selectors"][0]["addresses"])
        if not set(retained).issubset(inventory) or selected not in inventory:
            raise PPEditError("Retained and selected actions require complete positive existing LevelManager inventory evidence")
        blocked = set(retained)
        blocked.remove(original[field][scene - 1])
        if selected in blocked:
            raise PPEditError("Selected action is used by the opposite selector or another scene")
        updates = {name: list(values) for name, values in original.items()}
        updates[field][scene - 1] = selected
        option = "normal_selector" if field == "ActionSelector" else "all_off_selector"
        details = {"firmware": identity[1], "catalog_number": self.profile.catalog_number,
                   "options": {"scene": scene, option: selected, "group_cache": cache},
                   "source": dict(SOURCE), "selector_identity": {"application": 202, "group": trigger, "address": selected},
                   "metadata_evidence": "caller complete existing group and LevelManager objects; database freshness requires external verification",
                   "initialization_creations": [], "whole_dialog_save": False,
                   "scene_content_repacked": False, "device_verified": False}
        return self.make_plan(original, updates, details)

    def apply(self, session, plan):
        identity = self.verify_profile(session)
        if not isinstance(plan, PPPlan) or plan.format != FORMAT or plan.unit_type != self.unit_type:
            raise PPEditError("Plan differs from this editor")
        if plan.details.get("firmware") != identity[1]:
            raise PPEditError("Plan firmware differs from the programming session")
        for values in (*plan.expected.values(), *plan.changes.values()):
            if any(type(v) is not int for v in values):
                raise PPEditError("Saved plan parameter arrays require exact integers")
        options = plan.details.get("options")
        if not isinstance(options, dict) or set(options) - OPTION_NAMES:
            raise PPEditError("Plan has invalid canonical options")
        canonical = self.plan(plan.expected, identity=identity, **deepcopy(options))
        try:
            same = json.dumps(canonical.as_dict(), sort_keys=True, allow_nan=False) == json.dumps(plan.as_dict(), sort_keys=True, allow_nan=False)
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
    reserved = {"format", "unit_type", "spec_filename", "expected", "changes", "saved"}
    details = {"firmware", "catalog_number", "options", "source", "selector_identity", "metadata_evidence",
               "initialization_creations", "whole_dialog_save", "scene_content_repacked", "device_verified"}
    if set(data) != reserved | details or data["saved"] is not False:
        raise PPEditError("Saved plan has unsupported fields or saved state")
    for key in ("expected", "changes"):
        if not isinstance(data[key], dict) or any(not isinstance(n, str) or not isinstance(v, list)
                or any(type(x) is not int for x in v) for n, v in data[key].items()):
            raise PPEditError("Saved plan parameter arrays require exact integers")
    return PPPlan(FORMAT, data["unit_type"], data["spec_filename"],
                  {k: tuple(v) for k, v in data["expected"].items()},
                  {k: tuple(v) for k, v in data["changes"].items()},
                  {k: deepcopy(v) for k, v in data.items() if k not in reserved})
