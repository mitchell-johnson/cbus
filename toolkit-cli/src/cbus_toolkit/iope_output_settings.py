"""Source-pinned IOPE Turn On and Restrike edits; no save or physical I/O.

Only explicit controls and their paired-slider effects are staged. This is
not TfrmIOPE's whole-dialog SaveOutputs/BeforeSaveProgrammingInformation.
See docs/iope-output-settings.md for source hashes and the evidence boundary.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
from types import MappingProxyType

from .din_output_settings import level_to_percent, percent_to_level
from .iope_settings import PROFILES, profile_refusal
from .pp_editor import PPEditError, PPEditor, PPPlan, boolean, integer

FORMAT = "cbus-iope-output-settings-plan-v1"
LAYOUTS = MappingProxyType({
    "MinDimmingLevel": ("int", 0x78, 4, 8, 0, 0),
    "MaxDimmingLevel": ("int", 0x7C, 2, 8, 0, 0),
    "RestrikeChannel": ("int", 0x70, 4, 1, 6, 0),
    "RestrikeDelay": ("int", 0x6F, 1, 8, 0, 0),
})
SOURCE_EXE_SHA256 = "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab"
SOURCE_MAP_SHA256 = "f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb"
_DETAIL_KEYS = ("firmware", "catalog_number", "options", "derived", "source_exe_sha256",
                "whole_dialog_save", "device_verified")


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


def _replay_options(options):
    if not isinstance(options, dict) or set(options) != {"channels", "restrike_delay"}:
        raise PPEditError("Plan requires canonical output options")
    rows = options["channels"]
    if not isinstance(rows, dict):
        raise PPEditError("Plan channels must be a mapping")
    channels = {}
    for key, value in rows.items():
        if not isinstance(key, str) or key not in ("1", "2", "3", "4"):
            raise PPEditError("Plan channel keys must be canonical numbers")
        channels[int(key)] = value
    return {"channels": channels, "restrike_delay": options["restrike_delay"]}


class IopeOutputSettings(PPEditor):
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
            raise PPEditError("Output planning requires explicit (unit type, firmware, catalogue) identity")
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
            relay = index < self.profile.relays
            row = {"channel": index + 1, "relay": relay,
                   "min_level": values["MinDimmingLevel"][index],
                   "min_percent": level_to_percent(values["MinDimmingLevel"][index]),
                   "restrike_editable": relay,
                   "restrike_stored": bool(values["RestrikeChannel"][index])}
            if not relay:
                maximum = values["MaxDimmingLevel"][index - 2]
                row.update(max_level=maximum, max_percent=level_to_percent(maximum))
            channels.append(row)
        delay = values["RestrikeDelay"][0]
        return {"format": "cbus-iope-output-settings-v1", "unit_type": self.unit_type,
                "channels": channels, "restrike_delay": delay, "restrike_delay_seconds": delay * 10,
                "restrike_delay_listed": 1 <= delay <= 254,
                "restrike_delay_editable": any(values["RestrikeChannel"][:self.profile.relays]),
                "whole_dialog_save": False, "device_verified": False}

    def plan(self, current, *, identity=None, channels=None, restrike_delay=None):
        """Plan channel controls, ordered minimum then maximum, then restrike.

        ``min_percent``/``max_percent`` are Toolkit slider selections. Raw
        level setters are deliberately absent. The common delay is a raw
        ordinal in 1..254 (10 seconds per ordinal), after relay selections.
        """
        identity = self._identity(identity)
        if channels is None:
            channels = {}
        if not isinstance(channels, Mapping):
            raise PPEditError("Channels must be a mapping of channel numbers to controls")
        original = self.snapshot(current)
        updates = {name: list(values) for name, values in original.items()}
        derived, selected = [], {}
        for channel, options in channels.items():
            _range(channel, "Output channel", 1, self.profile.outputs)
            if not isinstance(options, Mapping) or not options:
                raise PPEditError("Channel controls must be a nonempty mapping")
            if any(not isinstance(name, str) for name in options) or set(options) - {"min_percent", "max_percent", "restrike"}:
                raise PPEditError("Only min_percent, max_percent and restrike are output controls")
        for channel in sorted(channels):
            options = channels[channel]
            index = channel - 1
            relay = index < self.profile.relays
            if relay and "max_percent" in options:
                raise PPEditError("The relay Turn On frame has no maximum-level control")
            if not relay and "restrike" in options:
                raise PPEditError("Restrike is editable only on relay channels")
            selected[str(channel)] = {}
            if "min_percent" in options:
                minimum = _range(options["min_percent"], "Minimum percent", 0, 100)
                selected[str(channel)]["min_percent"] = minimum
                updates["MinDimmingLevel"][index] = percent_to_level(minimum)
                # trkMinPropertiesChange 0x119370e..0x11937c0: displayed
                # maximum <= minimum moves its inverse position down one.
                if not relay and level_to_percent(updates["MaxDimmingLevel"][index - 2]) <= minimum:
                    updates["MaxDimmingLevel"][index - 2] = percent_to_level(min(minimum + 1, 100))
                    derived.append(f"MaxDimmingLevel[{index - 2}]:minimum-slider-cascade")
            if "max_percent" in options:
                maximum = _range(options["max_percent"], "Maximum percent", 0, 100)
                selected[str(channel)]["max_percent"] = maximum
                updates["MaxDimmingLevel"][index - 2] = percent_to_level(maximum)
                # trkMaxPropertiesChange 0x11933af..0x11934cc: minimum
                # >= maximum moves its inverse position up one. Uncrossed
                # minimum raw bytes are preserved (branch at 0x11933cf).
                if level_to_percent(updates["MinDimmingLevel"][index]) >= maximum:
                    updates["MinDimmingLevel"][index] = percent_to_level(max(maximum - 1, 0))
                    derived.append(f"MinDimmingLevel[{index}]:maximum-slider-cascade")
            if "restrike" in options:
                value = boolean(options["restrike"], "Restrike")
                selected[str(channel)]["restrike"] = value
                updates["RestrikeChannel"][index] = int(value)
        if restrike_delay is not None:
            restrike_delay = _range(restrike_delay, "Restrike delay", 1, 254)
            # HandleRestrikeChannelClick examines only IsRelayChannel rows;
            # stale dimmer/inactive bits do not enable the control.
            if not any(updates["RestrikeChannel"][:self.profile.relays]):
                raise PPEditError("Toolkit disables the restrike delay until a relay has restrike enabled")
            updates["RestrikeDelay"][0] = restrike_delay
        return self.make_plan(original, updates, {
            "firmware": identity[1], "catalog_number": identity[2],
            "options": {"channels": selected, "restrike_delay": restrike_delay},
            "derived": derived, "source_exe_sha256": SOURCE_EXE_SHA256,
            "whole_dialog_save": False, "device_verified": False})

    def apply(self, session, plan):
        if not isinstance(plan, PPPlan) or (plan.format, plan.unit_type, plan.spec_filename) != (
                FORMAT, self.unit_type, self.spec.filename):
            raise PPEditError("Plan differs from this editor")
        if set(plan.expected) != set(LAYOUTS) or set(plan.changes) - set(LAYOUTS):
            raise PPEditError("Plan contains fields outside this workflow")
        if not isinstance(plan.details, Mapping):
            raise PPEditError("Plan details must be a mapping")
        identity = self.verify_profile(session)
        planned_identity = (plan.unit_type, plan.details.get("firmware"), plan.details.get("catalog_number"))
        self._identity(planned_identity)
        if identity[1] != planned_identity[1] or (planned_identity[2] is not None and identity[2] != planned_identity[2]):
            raise PPEditError("Plan was created for another firmware or catalogue")
        canonical = self.plan(plan.expected, identity=planned_identity,
                              **_replay_options(plan.details.get("options")))
        if _json(canonical.as_dict()) != _json(plan.as_dict()):
            raise PPEditError("Plan does not reproduce its canonical controls and dependent writes")
        return super().apply(session, canonical)

    def configure(self, session, **options):
        return self.apply(session, self.plan(session.values(), identity=self.verify_profile(session), **options))


def plan_from_dict(data):
    """Read a plan; apply replays its controls and checks all derived writes."""
    if (not isinstance(data, dict) or data.get("format") != FORMAT
            or not isinstance(data.get("unit_type"), str) or data["unit_type"] not in PROFILES):
        raise PPEditError("Expected a " + FORMAT + " document")
    required = {"format", "unit_type", "spec_filename", "expected", "changes", "saved", *_DETAIL_KEYS}
    if set(data) != required or data["saved"] is not False:
        raise PPEditError("Expected the complete unsaved output plan document")
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
