"""Source-owned per-unit Neo indicator panel, distinct from Unit Magic.

The admitted thirty ordinary Neo profiles use physical LED columns and eight
runtime indicator entries. A plan replays one load, ordered explicit controls,
and one indicator-owned agent save. It does not save a PP session or a project.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping

from .extended_macros import PROFILES
from .neo_indicators import AVANTI, FAMILIES, OPTION_LAYOUTS, STYLE_LAYOUTS, STYLES
from .pp_editor import PPPlan, PPEditError, PPEditor, boolean, integer

PLAN_FORMAT = "cbus-neo-indicator-editor-plan-v1"
LAYOUTS = MappingProxyType({**OPTION_LAYOUTS, **STYLE_LAYOUTS,
    "NightlightColour": ("bit", 0x34, 1, 1, 2, 0),
    "EnableNightlightControl": ("bit", 0x34, 1, 1, 7, 0)})
PROFILE_COUNTS = MappingProxyType({kind: count for filename, (kind, count, _) in PROFILES.items()
                                 if kind != "KEYE1" and filename == kind + ".xml"})
BOOL_CONTROLS = frozenset({"key_press_brightness_enabled", "nightlight_enabled", "first_press_ignored",
                           "timer_flash_enabled", "id_backlight_enabled"})
INT_CONTROLS = MappingProxyType({"fixed_brightness_percent": (0, 100),
                                "key_press_brightness_level": (0, 15), "key_press_duration": (1, 15)})
GLOBAL_CONTROLS = BOOL_CONTROLS | INT_CONTROLS.keys() | {"brightness_source", "nightlight_colour"}
DOCUMENT_KEYS = frozenset({"format", "unit_type", "spec_filename", "identity", "operations", "expected",
    "changes", "load_normalization", "save_normalization", "initial_panel", "final_panel", "control_history",
    "saved", "device_verified"})


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PPEditError("Neo indicator plan must contain ordinary JSON values") from exc


def _identity(unit_type, value=None):
    if value is None:
        value = {"unit_type": unit_type, "firmware": "2.5.00", "catalog_number": None}
    if not isinstance(value, Mapping):
        raise PPEditError("Neo indicator identity must be an object")
    result = {name: value.get(name) for name in ("unit_type", "firmware", "catalog_number")}
    if result["unit_type"] != unit_type or result["firmware"] != "2.5.00":
        raise PPEditError("Neo indicator identity requires the selected unit type and firmware 2.5.00")
    catalog = result["catalog_number"]
    if catalog is not None and (not isinstance(catalog, str) or not catalog or len(catalog) > 128):
        raise PPEditError("Neo indicator catalogue identity must be a nonempty string or null")
    return result


def _values(values, *, serialized=False):
    if not isinstance(values, Mapping) or (serialized and set(values) != set(LAYOUTS)):
        raise PPEditError("Neo indicator snapshot must contain every owned parameter")
    result = {}
    for name, (_, _, count, bits, _, _) in LAYOUTS.items():
        if name not in values:
            raise PPEditError("Current PP values are missing " + name)
        value = values[name]
        if serialized:
            if not isinstance(value, list):
                raise PPEditError("Serialized Neo parameter must be an integer array: " + name)
            tokens = value
        else:
            tokens = value.split() if isinstance(value, str) else value if isinstance(value, (list, tuple)) else [value]
        parsed = []
        for token in tokens:
            if not serialized and isinstance(token, str):
                lower = token.lower()
                try:
                    token = int(lower == "true") if lower in ("true", "false") else int(
                        lower.replace("$", "0x"), 0 if lower.startswith(("$", "0x", "0b")) else 10)
                except ValueError as exc:
                    raise PPEditError("Invalid numeric PP value: " + name) from exc
            number = integer(token, name)
            if not 0 <= number < (1 << bits):
                raise PPEditError("PP value outside its owned bit width: " + name)
            parsed.append(number)
        if len(parsed) != count:
            raise PPEditError("PP value has the wrong array length: " + name)
        result[name] = parsed
    return result


def _operations(operations):
    if not isinstance(operations, list) or len(operations) > 512:
        raise PPEditError("Neo controls must be an ordered JSON array of at most 512 operations")
    result = []
    for operation in operations:
        if not isinstance(operation, dict):
            raise PPEditError("Each Neo control operation must be an object")
        keys = set(operation)
        if "led" in keys:
            if keys not in ({"led", "style"}, {"led", "on_colour"}):
                raise PPEditError("A physical LED operation needs exactly one style or on_colour control")
            integer(operation["led"], "Physical LED")
            name = "style" if "style" in keys else "on_colour"
            if not isinstance(operation[name], str):
                raise PPEditError(name + " must be a supported label")
        else:
            if len(keys) != 1 or not keys <= GLOBAL_CONTROLS:
                raise PPEditError("Expected exactly one admitted Neo panel control")
            name = next(iter(keys))
            if name in BOOL_CONTROLS:
                boolean(operation[name], name)
            elif name in INT_CONTROLS:
                number = integer(operation[name], name)
                lo, hi = INT_CONTROLS[name]
                if not lo <= number <= hi:
                    raise PPEditError(f"{name} must be in {lo}..{hi}")
            elif not isinstance(operation[name], str):
                raise PPEditError(name + " must be a supported label")
        result.append(dict(operation))
    return result


def _differences(before, after):
    return {name: list(after[name]) for name in LAYOUTS if before[name] != after[name]}


class _Panel:
    def __init__(self, unit_type, expected, identity):
        self.kind = unit_type
        self.count = PROFILE_COUNTS[unit_type]
        self.family = FAMILIES[unit_type]
        self.standard = self.family == "standard"
        self.decorator = unit_type.startswith("KEYDV")
        self.saturn = self.family == "saturn" or self.decorator
        self.reflection = self.family == "reflection"
        self.classic = self.family == "classic"
        self.independent = self.standard and not self.decorator
        self.raw = {name: list(value) for name, value in expected.items()}
        self.load_normalization = {}
        if self.classic or self.reflection:
            self.raw["IndicatorFunction"] = [min(value, 2) for value in self.raw["IndicatorFunction"]]
        if self.reflection:
            self.raw["PrimaryColour"] = [0] * 8
        if self.classic:
            for name in ("FirstKeyThrowAway", "IndicatorPressedLevel", "TimerDuration",
                         "EnableNightlightControl"):
                self.raw[name] = [0]
        self.load_normalization = _differences(expected, self.raw)
        bright = expected["IndicatorBrightness"][0]
        self.brightness_source = "group" if bright == 0 else "first_block" if bright <= 3 else "fixed"
        self.brightness_level = 0 if bright <= 3 else {4: 0, 5: 2, 6: 5}.get(bright, bright)
        if self.classic and 1 <= bright <= 3:
            self.brightness_source, self.brightness_level = "fixed", bright
        self.fixed_position = (self.brightness_level + 2) * 100 // 255
        self.keypress_level = self.raw["IndicatorPressedLevel"][0]
        self.duration = self.raw["TimerDuration"][0]
        self.duration_selection = self.duration or 1
        self.checked = {
            "key_press_brightness_enabled": self.duration > 0,
            "nightlight_enabled": bool(self.raw[self.night_parameter][0]) if not self.classic else False,
            "first_press_ignored": bool(self.raw["FirstKeyThrowAway"][0]) if not self.classic else False,
            "timer_flash_enabled": not bool(self.raw["DisableTimerFlash"][0]),
            "id_backlight_enabled": bool(self.raw["IDBacklightIllumination"][0]) if self.independent else False,
        }
        special = (identity["catalog_number"] or "").upper() == "5041NMML"
        self.colours = ("red", "green") if unit_type in AVANTI else ("blue", "red" if special else "orange")
        self.night_colours = ("green", "red") if unit_type in AVANTI else ("red" if special else "orange", "blue")
        self.visible = {name: True for name in GLOBAL_CONTROLS}
        for name in ("key_press_brightness_enabled", "key_press_brightness_level", "key_press_duration",
                     "nightlight_enabled", "first_press_ignored"):
            self.visible[name] = not self.classic
        self.visible["nightlight_colour"] = self.saturn and not self.decorator
        self.visible["id_backlight_enabled"] = self.independent
        self.enabled = {name: True for name in GLOBAL_CONTROLS}
        self.enabled["id_backlight_enabled"] = self.independent
        self._brightness_enabled()
        # Populate calls these handlers in this order, with nil Sender. It does
        # not emulate an explicit uncheck and preserves disabled checked flags.
        self._keypress_handler(explicit=False)
        self._night_handler()
        self.load_normalization = _differences(expected, self.raw)

    @property
    def night_parameter(self):
        return "EnableNightlightOnPA6" if self.standard else "EnableNightlightOnPCx"

    def _brightness_enabled(self):
        self.enabled["fixed_brightness_percent"] = self.brightness_source == "fixed"

    def _store_duration(self):
        self.duration = self.duration_selection if self.checked["key_press_brightness_enabled"] else 0
        self.raw["TimerDuration"] = [self.duration]

    def _keypress_handler(self, *, explicit):
        key = self.checked["key_press_brightness_enabled"]
        if explicit and not key and self.checked["nightlight_enabled"]:
            if not self.independent:
                self._set_checked("nightlight_enabled", False)
            if self.checked["first_press_ignored"]:
                self._set_checked("first_press_ignored", False)
        self.enabled["key_press_brightness_level"] = key
        self.enabled["key_press_duration"] = key
        self.enabled["nightlight_enabled"] = key or self.independent
        self.enabled["nightlight_colour"] = key and self.checked["nightlight_enabled"]
        self.enabled["first_press_ignored"] = key and self.checked["nightlight_enabled"]
        self._store_duration()

    def _night_handler(self):
        if not self.checked["nightlight_enabled"]:
            self._set_checked("first_press_ignored", False)
        self.enabled["first_press_ignored"] = all((self.visible["nightlight_enabled"],
            self.enabled["nightlight_enabled"], self.checked["nightlight_enabled"],
            self.visible["key_press_brightness_enabled"], self.enabled["key_press_brightness_enabled"],
            self.checked["key_press_brightness_enabled"]))
        self.enabled["nightlight_colour"] = all((self.visible["nightlight_colour"],
            self.checked["nightlight_enabled"], self.enabled["nightlight_enabled"]))

    def _set_checked(self, name, value):
        if self.checked[name] == value:
            return
        self.checked[name] = value
        if name == "nightlight_enabled":
            self.raw[self.night_parameter] = [int(value)]
            self._night_handler()
        elif name == "key_press_brightness_enabled":
            self._keypress_handler(explicit=True)
        else:
            parameter = {"first_press_ignored": "FirstKeyThrowAway", "timer_flash_enabled": "DisableTimerFlash",
                         "id_backlight_enabled": "IDBacklightIllumination"}[name]
            self.raw[parameter] = [int(not value if name == "timer_flash_enabled" else value)]

    def view(self):
        values = {**self.checked, "brightness_source": self.brightness_source,
            "fixed_brightness_percent": self.fixed_position, "key_press_brightness_level": self.keypress_level,
            "key_press_duration": self.duration_selection,
            "nightlight_colour": self.night_colours[self.raw["NightlightColour"][0]]
                if self.visible["nightlight_colour"] else None}
        controls = {name: {"visible": self.visible[name], "enabled": self.enabled[name], "value": values[name]}
                    for name in sorted(GLOBAL_CONTROLS)}
        leds = []
        styles = tuple(STYLES)
        for index in range(self.count):
            style, colour = self.raw["IndicatorFunction"][index], self.raw["PrimaryColour"][index]
            leds.append({"led": index + 1, "style": styles[style],
                "on_colour": self.colours[colour] if style and not self.classic else None,
                "off_colour": self.colours[1 - colour] if style == 3 and not self.reflection and not self.classic else None,
                "on_colour_editable": bool(style) and not self.reflection and not self.classic,
                "off_colour_editable": False})
        return {"physical_led_count": self.count, "indicator_array_size": 8,
            "style_choices": list(styles[:3] if self.classic or self.reflection else styles),
            "on_colour_choices": list(self.colours), "nightlight_colour_choices": list(self.night_colours),
            "colour_rows_visible": not self.classic, "brightness_group": self.raw["GroupAddress"][8],
            "controls": controls, "leds": leds}

    def operate(self, operation):
        if "led" in operation:
            index = operation["led"] - 1
            if not 0 <= index < self.count:
                raise PPEditError("Physical LED is outside this unit's visible columns")
            if "style" in operation:
                label = operation["style"]
                if label not in STYLES or (label == "status_dual" and (self.classic or self.reflection)):
                    raise PPEditError("Style is unavailable for this Neo profile")
                self.raw["IndicatorFunction"][index] = STYLES[label]
            else:
                if not self.view()["leds"][index]["on_colour_editable"]:
                    raise PPEditError("This LED on-colour cell is read-only")
                if operation["on_colour"] not in self.colours:
                    raise PPEditError("On colour is not a supported catalogue label")
                self.raw["PrimaryColour"][index] = self.colours.index(operation["on_colour"])
            return
        name, value = next(iter(operation.items()))
        if not self.visible[name] or not self.enabled[name]:
            raise PPEditError("Neo panel control is hidden or disabled: " + name)
        if name in BOOL_CONTROLS:
            self._set_checked(name, value)
        elif name == "brightness_source":
            if value not in ("fixed", "group", "first_block"):
                raise PPEditError("Brightness source must be fixed, group or first_block")
            self.brightness_source = value
            self._brightness_enabled()
        elif name == "fixed_brightness_percent":
            if value != self.fixed_position:
                self.fixed_position = value
                self.brightness_level = value * 255 // 100
        elif name == "key_press_brightness_level":
            if value != self.keypress_level:
                self.keypress_level = value
                self.raw["IndicatorPressedLevel"] = [value]
        elif name == "key_press_duration":
            self.duration_selection = value
            self._store_duration()
        elif name == "nightlight_colour":
            if value not in self.night_colours:
                raise PPEditError("Nightlight colour is not a supported catalogue label")
            self.raw["NightlightColour"] = [self.night_colours.index(value)]

    def save(self):
        final = {name: list(values) for name, values in self.raw.items()}
        level = self.brightness_level
        if self.brightness_source == "fixed" or (self.classic and self.brightness_source == "first_block"):
            for old, new in ((5, 6), (2, 5), (0, 4)):
                if level == old:
                    level = new
            final["IndicatorBrightness"] = [level]
        else:
            final["IndicatorBrightness"] = [int(self.brightness_source == "first_block")]
        final["EnableNightlight"] = [0]
        other = "EnableNightlightOnPCx" if self.standard else "EnableNightlightOnPA6"
        final[other] = [0]
        if self.classic:
            for name in ("EnableNightlightOnPCx", "EnableNightlightOnPA6", "FirstKeyThrowAway",
                         "IndicatorPressedLevel", "TimerDuration", "IDBacklightIllumination",
                         "EnableNightlightControl"):
                final[name] = [0]
        if self.reflection:
            final["PrimaryColour"] = [1] * 8
        # NightlightColour is programmed by NeoPro only for IsNeoSaturn.
        # No other admitted profile exposes its selector or changes its raw bit.
        return final


def _project(unit_type, filename, expected, operations, identity):
    if not isinstance(unit_type, str) or unit_type not in PROFILE_COUNTS or filename != unit_type + ".xml":
        raise PPEditError("Neo indicator editor supports the thirty admitted ordinary profiles only")
    identity = _identity(unit_type, identity)
    operations = _operations(operations)
    panel = _Panel(unit_type, expected, identity)
    initial = panel.view()
    history = []
    for index, operation in enumerate(operations, 1):
        before = panel.view()
        panel.operate(operation)
        history.append({"index": index, "operation": operation, "before": before, "after": panel.view()})
    final = panel.save()
    return {"format": PLAN_FORMAT, "unit_type": unit_type, "spec_filename": filename,
        "identity": identity, "operations": operations, "expected": expected,
        "changes": _differences(expected, final), "load_normalization": panel.load_normalization,
        "save_normalization": _differences(panel.raw, final), "initial_panel": initial,
        "final_panel": panel.view(), "control_history": history, "saved": False, "device_verified": False}


@dataclass(frozen=True)
class NeoIndicatorPlan:
    """Immutable replay document; every receipt is recomputed on import/apply."""
    _document: str

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != DOCUMENT_KEYS or value.get("format") != PLAN_FORMAT:
            raise PPEditError("Invalid Neo indicator plan format or fields")
        if value.get("saved") is not False or value.get("device_verified") is not False:
            raise PPEditError("A Neo indicator plan cannot claim persistence or device verification")
        expected = _values(value["expected"], serialized=True)
        canonical = _project(value["unit_type"], value["spec_filename"], expected,
                             value["operations"], value["identity"])
        if _json(value) != _json(canonical):
            raise PPEditError("Neo indicator plan differs from its ordered control replay")
        return cls(_json(canonical))

    def as_dict(self):
        return json.loads(self._document)

    @property
    def expected(self):
        return MappingProxyType({name: tuple(values) for name, values in self.as_dict()["expected"].items()})

    @property
    def changes(self):
        return MappingProxyType({name: tuple(values) for name, values in self.as_dict()["changes"].items()})


class NeoIndicatorEditor(PPEditor):
    FORMAT = PLAN_FORMAT

    def __init__(self, spec):
        if spec.unit_type not in PROFILE_COUNTS or spec.filename != spec.unit_type + ".xml":
            raise PPEditError("Neo indicator editor supports the thirty admitted ordinary profiles only")
        super().__init__(spec, spec.unit_type, LAYOUTS)
        self.default_identity = _identity(spec.unit_type)

    def snapshot(self, current):
        return {name: tuple(values) for name, values in _values(current).items()}

    def show(self, current, *, identity=None):
        identity = _identity(self.unit_type, identity)
        expected = _values(current)
        panel = _Panel(self.unit_type, expected, identity)
        return {"unit_type": self.unit_type, "spec_filename": self.spec.filename, "identity": identity,
                "parameters": expected, "load_normalization": panel.load_normalization, "panel": panel.view()}

    def plan(self, current, operations, *, identity=None):
        document = _project(self.unit_type, self.spec.filename, _values(current), operations,
                            _identity(self.unit_type, identity))
        self.codec.encode_many(document["changes"])
        return NeoIndicatorPlan.from_dict(document)

    def apply(self, session, plan):
        if not isinstance(plan, NeoIndicatorPlan):
            raise PPEditError("Expected a Neo indicator editor plan")
        # Reconstruct before even inspecting session identity: serialized claims
        # and coherent forged changes cannot bypass the control state machine.
        document = NeoIndicatorPlan.from_dict(plan.as_dict()).as_dict()
        if (document["unit_type"], document["spec_filename"]) != (self.unit_type, self.spec.filename):
            raise PPEditError("Neo indicator plan differs from this editor")
        self.codec.encode_many(document["changes"])
        identity = _identity(self.unit_type, {name: getattr(session, name, None)
                                            for name in ("unit_type", "firmware", "catalog_number")})
        if identity != document["identity"]:
            raise PPEditError("Programming session identity differs from the Neo indicator plan")
        # The common staging transaction checks schema and the full snapshot,
        # verifies readback, and restores attempted fields on a staging failure.
        # It never issues SAVE and therefore cannot replay an uncertain save.
        trusted = PPPlan(self.FORMAT, self.unit_type, self.spec.filename,
                         document["expected"], {name: document["changes"][name]
                                               for name in LAYOUTS if name in document["changes"]})
        applied = super().apply(session, trusted)
        return {**document, "verified": applied["verified"]}

    def configure(self, session, operations):
        identity = {name: getattr(session, name, None) for name in ("unit_type", "firmware", "catalog_number")}
        return self.apply(session, self.plan(session.values(), operations, identity=identity))
