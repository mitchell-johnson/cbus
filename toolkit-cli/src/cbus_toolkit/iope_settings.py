"""Toolkit IOPE occupancy-controller Global, Power Failure and block-timer settings.

IOPE1R1, IOPE2R2 and IOPE2C4 have no static node manager. Toolkit 1.18 binds
their editor through ``TUnitDialogFactory.RegisterUnitDialog`` (type name ->
``TfrmIOPE``), consulted by ``TddCommonCBusUnit.Initialise``, and loads/saves
through ``TIOPECGateAgent``. This module reproduces the recovered subset of
that dialog: the Global tab, the sensor enable controls, the Power Failure
sensor-state, power-up broadcast and output-channel recovery controls, and
per-block timer durations, each with the agent's save transform. Scenes,
input functions, join modes, corridor linking, output logic/turn-on/restrike
and expiry functions are outside this editor. Nothing is saved or
transferred. See docs/iope-settings.md.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType

from .din_output_settings import level_to_percent, percent_to_level
from .pp_editor import PPEditError, PPEditor, boolean, integer


@dataclass(frozen=True)
class Profile:
    unit_type: str
    catalog_number: str
    sensors: int
    auxiliaries: int
    outputs: int
    relays: int


# TIOPEUnit/TIOPE1R1/TIOPE2R2/TIOPE2C4 GetMaximumInput{Sensor,Auxiliary}Count,
# GetMaximumOutputCount and TIOPE2C4.IsRelayChannel (channel index <= 1).
PROFILES = MappingProxyType({p.unit_type: p for p in (
    Profile("IOPE1R1", "5752PP/1R", 1, 1, 1, 1),
    Profile("IOPE2R2", "5752PP/2R", 2, 2, 2, 2),
    Profile("IOPE2C4", "5752PP/2R/2D", 2, 2, 4, 2),
)})
BLOCKS = 8  # TIOPEUnit.GetMaximumInputBlockCount
# Catalogue revisions for all three types cover 0.0.00..1.2.99; the spec
# starts at 1.0.00. Toolkit registers one class for 0.0.0..9.
FIRMWARE_RANGE = ((1, 0, 0), (1, 2, 99))
FORMAT = "cbus-iope-settings-plan-v1"

LAYOUTS = MappingProxyType({
    "Memory1": ("int", 0x10, 1, 8, 0, 0), "Memory2": ("int", 0x11, 1, 8, 0, 0),
    "Memory3": ("int", 0x12, 1, 8, 0, 0), "Memory4": ("int", 0x13, 1, 8, 0, 0),
    "Sensor1EnabledStartup": ("bit", 0x1C, 1, 1, 0, 0), "Sensor2EnabledStartup": ("bit", 0x1C, 1, 1, 1, 0),
    "GroupAssertOnPowerup": ("int", 0x1D, 1, 8, 0, 0),
    "BistableAuxiliary1": ("bit", 0x30, 1, 1, 0, 0), "BistableAuxiliary2": ("bit", 0x30, 1, 1, 1, 0),
    "Sensor1EnableGroupInEnableControlApp": ("bit", 0x30, 1, 1, 6, 0),
    "Sensor2EnableGroupInEnableControlApp": ("bit", 0x30, 1, 1, 7, 0),
    "LongPressTime": ("int", 0x31, 1, 6, 0, 0),
    "RampRateA": ("int", 0x32, 1, 4, 0, 0), "RampRateC": ("int", 0x32, 1, 4, 4, 0),
    "RampRateB": ("int", 0x33, 1, 4, 0, 0), "RampRateS": ("int", 0x33, 1, 4, 4, 0),
    "ClockGenEnable": ("bit", 0x3E, 1, 1, 0, 0),
    "Sensor1Enabled": ("bit", 0x3E, 1, 1, 2, 0), "Sensor2Enabled": ("bit", 0x3E, 1, 1, 3, 0),
    "Sensor1EnableStateStoreEnabled": ("bit", 0x3E, 1, 1, 4, 0),
    "Sensor2EnableStateStoreEnabled": ("bit", 0x3E, 1, 1, 5, 0),
    "Burden": ("bit", 0x3E, 1, 1, 6, 0),
    "TimerHighByte": ("int", 0x40, 8, 8, 0, 0), "TimerLowByte": ("int", 0x48, 8, 8, 0, 0),
    "InputGroupAddress": ("int", 0x50, 8, 8, 0, 0),
    "OutputGroupAddress": ("int", 0x58, 4, 8, 0, 0),
    "Sensor1EnableGroup": ("int", 0x61, 1, 8, 0, 0), "Sensor2EnableGroup": ("int", 0x62, 1, 8, 0, 0),
    "StatusReportInterval": ("int", 0x6A, 1, 8, 0, 0),
    "SensorOccupancyDebounce": ("int", 0x6C, 1, 3, 4, 0),
    "LightStateMachine": ("bit", 0x6C, 1, 1, 7, 0),
    "LevelStoreEnable": ("bit", 0x6E, 4, 1, 0, 0),
    "LightLevelOutput": ("int", 0x08, 8, 8, 0, 0),
    "Auxiliary1BlockAllocation": ("bit", 0x92, 8, 1, 0, 0),
    "Auxiliary2BlockAllocation": ("bit", 0x9A, 8, 1, 0, 0),
})

# TCommonCBus.RegisterEnumerations: TCBusMSecSetting n = n*16 ms (0..63);
# cmbLongPressTimeIncludeItem drops ordinals below 6.
LONG_PRESS = (6, 63)
# TCBusRampRate ordinals 0..15, displayed with these labels.
RAMP_RATES = ("Instant", "4 secs", "8 secs", "12 secs", "20 secs", "30 secs", "40 secs", "60 secs",
              "90 secs", "120 secs", "180 secs", "300 secs", "420 secs", "600 secs", "900 secs", "1020 secs")
RAMP_FIELDS = MappingProxyType({"global1": "RampRateA", "global2": "RampRateB",
                                "global3": "RampRateC", "scene": "RampRateS"})
# TfrmIOPEGlobal.SetCBusUnit adds 3..255 via StatusReportIntegerToString.
STATUS_REPORT = (3, 255)
# cmbSensorOccupancyDebounce: seven enumeration ordinals, stored unchanged.
DEBOUNCE = ("3 Counts", "0.010 sec", "0.020 sec", "0.050 sec", "0.100 sec", "0.200 sec", "0.500 sec")
# TIOPEUnit.RegisterEnumerations sensor state-recovery ordinals.
STATE_RECOVERY = ("enabled", "disabled", "restore")
APPLICATIONS = ("primary", "enable-control")
TIMER_SECONDS = (0, 0xFFFF)  # CIS_Dates.EncodeCBusTime h*3600+m*60+s, at most 65535


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,4}(\.[0-9]{1,4}){2}", value):
        return None
    return tuple(int(part) for part in value.split("."))


def profile_refusal(unit_type, firmware):
    if unit_type not in PROFILES:
        return "Only IOPE1R1, IOPE2R2 and IOPE2C4 use this workflow"
    version = _version(firmware)
    if version is None or not FIRMWARE_RANGE[0] <= version <= FIRMWARE_RANGE[1]:
        return f"{unit_type} firmware outside the catalogued 1.0.00..1.2.99 revisions has not been reviewed"
    return None


def timer_seconds(value):
    """Accept seconds or an H:MM:SS string, as the TTimeEdit entry allows."""
    if isinstance(value, str):
        match = re.fullmatch(r"(\d{1,2}):([0-5]\d):([0-5]\d)", value)
        if not match:
            raise PPEditError("Timer must be seconds or H:MM:SS")
        value = int(match[1]) * 3600 + int(match[2]) * 60 + int(match[3])
    value = integer(value, "Timer")
    if not TIMER_SECONDS[0] <= value <= TIMER_SECONDS[1]:
        raise PPEditError("Timer must be 0..65535 s (at most 18:12:15)")
    return value


def _range(value, label, low, high):
    value = integer(value, label)
    if not low <= value <= high:
        raise PPEditError(f"{label} must be {low}..{high}")
    return value


class IopeSettings(PPEditor):
    FORMAT = FORMAT

    def __init__(self, spec, unit_type=None):
        unit_type = spec.unit_type if unit_type is None else unit_type
        if unit_type not in PROFILES:
            raise PPEditError(profile_refusal(unit_type, None))
        if spec.filename != unit_type + ".xml":
            raise PPEditError(f"Use {unit_type}.xml for {unit_type}")
        self.profile = PROFILES[unit_type]
        super().__init__(spec, unit_type, LAYOUTS)

    # ---- derived rules -----------------------------------------------
    def broadcast_eligible(self, values):
        """Blocks a Toolkit save may keep in GroupAssertOnPowerup.

        SaveGroupAssertOnPowerupAttribute sets bit b only when the block has
        a group and IsBlockAssociatedWithBistableKey(b): some bistable
        auxiliary input references block b through its block allocation.
        """
        blocks = set()
        for n in range(1, self.profile.auxiliaries + 1):
            if values[f"BistableAuxiliary{n}"][0]:
                blocks |= {b + 1 for b, bit in enumerate(values[f"Auxiliary{n}BlockAllocation"]) if bit}
        return {b for b in blocks if values["InputGroupAddress"][b - 1] != 255}

    @staticmethod
    def state_recovery(values, n):
        """AfterLoadProgrammingInformation: store flag wins, then startup flag."""
        if values[f"Sensor{n}EnableStateStoreEnabled"][0]:
            return "restore"
        return "enabled" if values[f"Sensor{n}EnabledStartup"][0] else "disabled"

    # ---- read model --------------------------------------------------
    def show(self, current):
        v, p = self.snapshot(current), self.profile
        sensors = []
        for n in range(1, p.sensors + 1):
            recovery = self.state_recovery(v, n)
            group = v[f"Sensor{n}EnableGroup"][0]
            sensors.append({
                "sensor": n,
                # Load inverts the bit: 0 = disabled while the group is Off.
                "disabled_when": "on" if v[f"Sensor{n}Enabled"][0] else "off",
                "enable_group": None if group == 255 else group,
                "enable_application": APPLICATIONS[v[f"Sensor{n}EnableGroupInEnableControlApp"][0]],
                "state_recovery": recovery,
                "toolkit_save_rewrites_state_bits": (v[f"Sensor{n}EnableStateStoreEnabled"][0]
                                                     and v[f"Sensor{n}EnabledStartup"][0]) == 1})
        eligible = self.broadcast_eligible(v)
        asserted = {b for b in range(1, BLOCKS + 1) if v["GroupAssertOnPowerup"][0] >> (b - 1) & 1}
        outputs = []
        for c in range(1, p.outputs + 1):
            store, level = bool(v["LevelStoreEnable"][c - 1]), v["LightLevelOutput"][c - 1]
            outputs.append({"channel": c, "relay": c <= p.relays, "group": v["OutputGroupAddress"][c - 1],
                            "level_store": store, "recovery_level": level,
                            "recovery_percent": None if store else level_to_percent(level),
                            "toolkit_save_rewrites_recovery_level": store and level != 255})
        timers = [{"block": b + 1, "seconds": v["TimerHighByte"][b] << 8 | v["TimerLowByte"][b]}
                  for b in range(BLOCKS)]
        long_press = v["LongPressTime"][0]
        return {
            "format": "cbus-iope-settings-v1", "unit_type": p.unit_type,
            "global": {
                "long_press": long_press, "long_press_ms": long_press * 16,
                "long_press_listed": LONG_PRESS[0] <= long_press <= LONG_PRESS[1],
                "ramp_rates": {k: {"raw": v[f][0], "label": RAMP_RATES[v[f][0]]} for k, f in RAMP_FIELDS.items()},
                "status_report": v["StatusReportInterval"][0],
                "status_report_listed": STATUS_REPORT[0] <= v["StatusReportInterval"][0],
                "debounce": v["SensorOccupancyDebounce"][0],
                "debounce_label": DEBOUNCE[v["SensorOccupancyDebounce"][0]] if v["SensorOccupancyDebounce"][0] < 7 else None,
                "recall_levels": [{"global": g, "raw": v[f"Memory{g}"][0],
                                   "percent": level_to_percent(v[f"Memory{g}"][0])} for g in range(1, 5)],
                "clock_gen": bool(v["ClockGenEnable"][0]), "burden": bool(v["Burden"][0])},
            "sensors": sensors,
            "power_up_broadcast": {"blocks": sorted(asserted), "eligible_blocks": sorted(eligible),
                                   "toolkit_save_clears": sorted(asserted - eligible)},
            "outputs": outputs, "block_timers": timers,
            # BeforeSaveProgrammingInformation always writes LightStateMachine false.
            "toolkit_save_clears_light_state_machine": bool(v["LightStateMachine"][0]),
        }

    # ---- plan ----------------------------------------------------------
    def plan(self, current, *, long_press=None, ramp_rates=None, status_report=None, debounce=None,
             recall_levels=None, recall_percents=None, clock_gen=None, burden=None, sensors=None,
             enable_broadcast=(), disable_broadcast=(), outputs=None, block_timers=None, identity=None):
        """Plan edits. ``sensors``, ``outputs`` and ``block_timers`` map a
        1-based number to its options; recall levels map global 1..4 to a
        raw byte or a percentage."""
        p = self.profile
        if identity is not None:
            reason = profile_refusal(identity[0], identity[1])
            if reason or identity[0] != p.unit_type:
                raise PPEditError("Unit identity is not admitted: " + (reason or "type differs"))
        original = self.snapshot(current)
        u = {name: list(values) for name, values in original.items()}
        derived = []
        if long_press is not None:
            u["LongPressTime"][0] = _range(long_press, "Long press (x16 ms)", *LONG_PRESS)
        for key, value in (ramp_rates or {}).items():
            if key not in RAMP_FIELDS:
                raise PPEditError("Ramp rates are global1, global2, global3 and scene")
            if isinstance(value, str) and value in RAMP_RATES:
                value = RAMP_RATES.index(value)
            u[RAMP_FIELDS[key]][0] = _range(value, "Ramp rate", 0, 15)
        if status_report is not None:
            u["StatusReportInterval"][0] = _range(status_report, "Status report interval", *STATUS_REPORT)
        if debounce is not None:
            u["SensorOccupancyDebounce"][0] = _range(debounce, "Sensor debounce", 0, len(DEBOUNCE) - 1)
        recall_levels, recall_percents = recall_levels or {}, recall_percents or {}
        if set(recall_levels) & set(recall_percents):
            raise PPEditError("Use either a raw recall level or a percentage for each global")
        for g, value in recall_levels.items():
            u[f"Memory{_range(g, 'Global', 1, 4)}"][0] = _range(value, "Recall level", 0, 255)
        for g, value in recall_percents.items():
            # cmbGlobalNRecallLevel lists 0..100 and stores PercentToLevel.
            u[f"Memory{_range(g, 'Global', 1, 4)}"][0] = percent_to_level(_range(value, "Recall percent", 0, 100))
        if clock_gen is not None:
            u["ClockGenEnable"][0] = int(boolean(clock_gen, "clock_gen"))
        if burden is not None:
            u["Burden"][0] = int(boolean(burden, "burden"))
        for n, options in (sensors or {}).items():
            self._sensor(u, _range(n, "Sensor", 1, p.sensors), dict(options))
        self._broadcast(u, enable_broadcast, disable_broadcast, derived)
        for c, options in (outputs or {}).items():
            self._output(u, _range(c, "Output channel", 1, p.outputs), dict(options), derived)
        for b, seconds in (block_timers or {}).items():
            b = _range(b, "Block", 1, BLOCKS)
            seconds = timer_seconds(seconds)
            # SaveTimerHighAndLowBytes: HighByte/LowByte of the block timer word.
            u["TimerHighByte"][b - 1], u["TimerLowByte"][b - 1] = seconds >> 8, seconds & 0xFF
        details = {"catalog_number": p.catalog_number, "firmware": identity[1] if identity else None,
                   "derived": list(dict.fromkeys(derived)), "device_verified": False}
        return self.make_plan(original, u, details)

    def _sensor(self, u, n, options):
        unknown = set(options) - {"disabled_when", "enable_group", "enable_application", "state_recovery"}
        if unknown:
            raise PPEditError("Unknown sensor options: " + ", ".join(sorted(unknown)))
        if "disabled_when" in options:
            when = options["disabled_when"]
            if when not in ("on", "off"):
                raise PPEditError("disabled_when must be on or off")
            # rgSensorNEnabled item 1 'Off' = unit True; save writes not(unit).
            u[f"Sensor{n}Enabled"][0] = int(when == "on")
        if "enable_group" in options:
            group = options["enable_group"]
            u[f"Sensor{n}EnableGroup"][0] = 255 if group is None else _range(group, "Sensor enable group", 0, 254)
        if "enable_application" in options:
            if options["enable_application"] not in APPLICATIONS:
                raise PPEditError("enable_application must be primary or enable-control")
            # Save: group application == network enable-control application.
            u[f"Sensor{n}EnableGroupInEnableControlApp"][0] = APPLICATIONS.index(options["enable_application"])
        if "state_recovery" in options:
            state = options["state_recovery"]
            if state not in STATE_RECOVERY:
                raise PPEditError("state_recovery must be enabled, disabled or restore")
            # Save: StateStoreEnabled = (restore), EnabledStartup = (enabled).
            u[f"Sensor{n}EnableStateStoreEnabled"][0] = int(state == "restore")
            u[f"Sensor{n}EnabledStartup"][0] = int(state == "enabled")

    def _broadcast(self, u, enable, disable, derived):
        enable, disable = self._blocks(enable), self._blocks(disable)
        if not enable and not disable:
            return
        if enable & disable:
            raise PPEditError("A block cannot be both enabled and disabled")
        values = {name: tuple(row) for name, row in u.items()}
        eligible = self.broadcast_eligible(values)
        refused = sorted(enable - eligible)
        if refused:
            raise PPEditError(f"Blocks {refused} have no group or no bistable auxiliary input; "
                              "Toolkit saves their power-up broadcast as off")
        before = {b for b in range(1, BLOCKS + 1) if u["GroupAssertOnPowerup"][0] >> (b - 1) & 1}
        cleared = before - eligible
        if cleared:
            derived.append("GroupAssertOnPowerup:cleared-ineligible")
        selected = ((before & eligible) | enable) - disable
        u["GroupAssertOnPowerup"][0] = sum(1 << (b - 1) for b in selected)

    @staticmethod
    def _blocks(values):
        if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
            raise PPEditError("Blocks must be a list of block numbers")
        return {_range(value, "Block", 1, BLOCKS) for value in values}

    def _output(self, u, c, options, derived):
        unknown = set(options) - {"level_store", "recovery_level", "recovery_percent"}
        if unknown:
            raise PPEditError("Unknown output options: " + ", ".join(sorted(unknown)))
        if "recovery_level" in options and "recovery_percent" in options:
            raise PPEditError("Use either recovery_level or recovery_percent")
        group = u["OutputGroupAddress"][c - 1]
        if group != 255 and any(u["OutputGroupAddress"][j] == group for j in range(self.profile.outputs) if j != c - 1):
            # The recovery frame couples channels on a shared group; not admitted.
            raise PPEditError("Output recovery on a group shared by another channel is not admitted")
        i = c - 1
        if "level_store" in options:
            u["LevelStoreEnable"][i] = int(boolean(options["level_store"], "level_store"))
        if u["LevelStoreEnable"][i]:
            if "recovery_level" in options or "recovery_percent" in options:
                raise PPEditError("Auto Level Store is enabled; Toolkit saves the recovery level as 255")
            if u["LightLevelOutput"][i] != 255:
                # SaveOutputs writes "255 " for every level-store channel.
                u["LightLevelOutput"][i] = 255
                derived.append(f"LightLevelOutput[{i}]")
            return
        if "recovery_level" in options:
            u["LightLevelOutput"][i] = _range(options["recovery_level"], "Recovery level", 0, 255)
        elif "recovery_percent" in options:
            u["LightLevelOutput"][i] = percent_to_level(_range(options["recovery_percent"], "Recovery percent", 0, 100))

    # ---- apply -----------------------------------------------------------
    def verify_profile(self, session):
        reason = profile_refusal(getattr(session, "unit_type", None), getattr(session, "firmware", None))
        if reason is not None:
            raise PPEditError("Native session is not an admitted IOPE unit: " + reason)
        if session.unit_type != self.unit_type:
            raise PPEditError("Native session unit type differs from the selected schema")
        return (session.unit_type, session.firmware, getattr(session, "catalog_number", None))

    def apply(self, session, plan):
        self.verify_profile(session)
        if plan.details.get("firmware") not in (None, session.firmware):
            raise PPEditError("Plan was created for another firmware")
        return super().apply(session, plan)

    def configure(self, session, **options):
        identity = self.verify_profile(session)
        return self.apply(session, self.plan(session.values(), identity=identity, **options))


def plan_from_dict(data):
    """Rebuild a saved plan document; the stale check happens on apply."""
    from .pp_editor import PPPlan
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("unit_type") not in PROFILES:
        raise PPEditError("Expected a " + FORMAT + " document for an IOPE unit")
    try:
        expected = {str(k): tuple(v) for k, v in data["expected"].items()}
        changes = {str(k): tuple(v) for k, v in data["changes"].items()}
    except (KeyError, AttributeError, TypeError) as error:
        raise PPEditError("Plan requires expected and changes mappings") from error
    details = {k: data.get(k) for k in ("catalog_number", "firmware", "derived", "device_verified")}
    return PPPlan(FORMAT, data["unit_type"], data.get("spec_filename"), expected, changes, details)
