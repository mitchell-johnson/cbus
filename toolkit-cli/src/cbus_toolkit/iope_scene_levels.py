"""Fresh IOPE SceneManager command-level projection on a stable retained graph."""
from __future__ import annotations

from copy import deepcopy
import json
from types import MappingProxyType

from .din_output_settings import level_to_percent, percent_to_level
from .iope_environment import _range
from .iope_scene_selectors import CACHE_FORMAT, LAYOUTS, SOURCE, IopeSceneSelectors
from .iope_settings import PROFILES
from .pp_editor import PPEditError, PPEditor, PPPlan, boolean

FORMAT = "cbus-iope-scene-levels-plan-v1"
WRITABLE = frozenset(("SceneTable",))
OPTION_NAMES = frozenset(("scene", "command", "raw_level", "percent", "sync_levels", "group_cache"))
INITIALIZATION = MappingProxyType({
    "entry": "fresh SceneManager loaded from canonical IOPE PP graph",
    "live_groups": False, "sync_levels": False, "use_percent": True,
    "constructor_use_percent": False,
    "external_scene_table": False,
})
DETAIL_NAMES = frozenset(("firmware", "catalog_number", "options", "source", "command_identity",
    "metadata_evidence", "initialization", "initialization_creations", "control_state", "level_writes",
    "whole_dialog_save", "scene_content_repacked", "stable_table_projection", "device_verified"))


class IopeSceneLevels(IopeSceneSelectors):
    FORMAT = FORMAT

    def show(self, current):
        v = self.snapshot(current)
        return {"format": "cbus-iope-scene-levels-v1", "unit_type": self.unit_type,
                "trigger_group": v["SceneTriggerGroup"][0],
                "scenes": [{"scene": s + 1, "commands": [
                    {"command": c + 1, "group": v["SceneTable"][s * 16 + c * 2],
                     "raw_level": v["SceneTable"][s * 16 + c * 2 + 1],
                     "percent": level_to_percent(v["SceneTable"][s * 16 + c * 2 + 1])}
                    for c in range(8)]} for s in range(4)],
                "group_objects_resolved": False, "whole_dialog_save": False, "device_verified": False,
                "warnings": ["Requires a complete positive existing graph and fresh SceneManager initialization",
                             "Live scene mode and whole SceneManager save are excluded"]}

    def plan(self, current, *, identity=None, scene=None, command=None, raw_level=None,
             percent=None, sync_levels=False, group_cache=None):
        identity = self._identity(identity)
        scene = _range(scene, "Scene", 1, 4)
        command = _range(command, "Command", 1, 8)
        sync_levels = boolean(sync_levels, "Sync levels")
        if (raw_level is None) == (percent is None):
            raise PPEditError("Select exactly one raw_level or percent")
        if percent is not None:
            selection = _range(percent, "Percent", 0, 100)
            level = percent_to_level(selection)
            option = "percent"
        else:
            selection = level = _range(raw_level, "Raw level", 0, 255)
            option = "raw_level"
        original = self.snapshot(current)
        # The retained selector no-op validates the full graph and canonicalizes
        # its positive group/LevelManager inventory without changing headers.
        graph = IopeSceneSelectors.plan(self, original, identity=identity, scene=scene,
            normal_selector=original["ActionSelector"][scene - 1], group_cache=group_cache)
        if graph.changes:
            raise PPEditError("Retained graph validation unexpectedly changed a selector")
        cache = deepcopy(graph.details["options"]["group_cache"])
        start = (scene - 1) * 16
        selected = start + (command - 1) * 2
        rows = range(8) if sync_levels else (command - 1,)
        updates = {name: list(values) for name, values in original.items()}
        writes = []
        for row in rows:
            index = start + row * 2 + 1
            before = original["SceneTable"][index]
            # Native integer attribute equality skips its AfterChange callback.
            # Matching display percentages therefore preserve noncanonical raw bytes.
            before_percent = level_to_percent(before)
            converted = option == "percent" and before_percent != selection
            after = (level if converted else before) if option == "percent" else level
            updates["SceneTable"][index] = after
            writes.append({"command": row + 1, "group": original["SceneTable"][index - 1],
                "before": before, "after": after, "table_index": index,
                "before_percent": before_percent, "after_percent": level_to_percent(after),
                "callback_conversion": converted,
                "byte_address": 0xB2 + index, "changed": before != after,
                "selected": row == command - 1,
                "setter_calls": (3 if sync_levels else 2) if row == command - 1 else 1})
        details = {"firmware": identity[1], "catalog_number": self.profile.catalog_number,
            "options": {"scene": scene, "command": command, option: selection,
                        "sync_levels": sync_levels, "group_cache": cache},
            "source": dict(SOURCE),
            "command_identity": {"application": original["Application"][0],
                                 "group": original["SceneTable"][selected],
                                 "scene": scene, "command": command},
            "metadata_evidence": graph.details["metadata_evidence"],
            "initialization": dict(INITIALIZATION), "initialization_creations": [],
            "control_state": {"live_groups": False, "sync_levels": sync_levels,
                              "use_percent": option == "percent",
                              "use_percent_action_toggles_after_entry": 1 if option == "raw_level" else 0,
                              "sync_action_toggles_after_entry": 1 if sync_levels else 0},
            "level_writes": writes, "whole_dialog_save": False,
            "scene_content_repacked": False, "stable_table_projection": True,
            "device_verified": False}
        return self.make_plan(original, updates, details)

    def apply(self, session, plan):
        identity = self.verify_profile(session)
        if not isinstance(plan, PPPlan) or plan.format != FORMAT or plan.unit_type != self.unit_type:
            raise PPEditError("Plan differs from this editor")
        if plan.details.get("firmware") != identity[1]:
            raise PPEditError("Plan firmware differs from the programming session")
        if set(plan.details) != DETAIL_NAMES:
            raise PPEditError("Plan has unsupported details")
        for values in (*plan.expected.values(), *plan.changes.values()):
            if any(type(v) is not int for v in values):
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
        return PPEditor.apply(self, session, canonical)


def plan_from_dict(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("unit_type") not in PROFILES:
        raise PPEditError("Expected a " + FORMAT + " document")
    reserved = {"format", "unit_type", "spec_filename", "expected", "changes", "saved"}
    if set(data) != reserved | DETAIL_NAMES or data["saved"] is not False:
        raise PPEditError("Saved plan has unsupported fields or saved state")
    for key in ("expected", "changes"):
        if not isinstance(data[key], dict) or any(not isinstance(n, str) or not isinstance(v, list)
                or any(type(x) is not int for x in v) for n, v in data[key].items()):
            raise PPEditError("Saved plan parameter arrays require exact integers")
    return PPPlan(FORMAT, data["unit_type"], data["spec_filename"],
                  {k: tuple(v) for k, v in data["expected"].items()},
                  {k: tuple(v) for k, v in data["changes"].items()},
                  {k: deepcopy(v) for k, v in data.items() if k not in reserved})
