"""Source-owned explicit quick-zone and plant controls on one loaded owner.

The fresh owner contains its fixed callbacks and a private posted-message
queue. It never accepts subscriber JSON or a detached continuation. This
profile requires settled source controls; it does not schedule Windows
messages, migrate applications, save, or reproduce physical operation.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json

from .thermostat_damper_controls import DamperControlModel, normalize_damper_operation
from .thermostat_output_groups import OutputGroupModel, normalize_output_operations
from .thermostat_plant_types import PlantTypeModel, PlantGroupCapacityError
from .thermostat_posted_changes import PlantChangeQueue
from .thermostat_post_load import OUTPUTS, DAMPERS, RELAYS, pp_name, virtual_plant_type, INSTALLATION_NAMES
from .thermostat_templates import ThermostatTemplateError
from .thermostat_zone_defaults import ZoneDefaultsModel

_TYPE_FIELDS = {"heating": "HeatingPlantType", "cooling": "CoolingPlantType",
                "heatcool": "HeatCoolPlantType", "venting": "VentingPlantType"}
_ZONE_FIELDS = {"ui": "UIAllocatedZones", "internal": "InternalPlantZones",
                "measured": "MeasuredZones", "schedule": "ScheduleControlledZones",
                "cbus": "InstalledZones", "controlled": "ControlledZones",
                "heating": "HeatingPlantInstalledZones", "cooling": "CoolingPlantInstalledZones",
                "venting": "VentingPlantInstalledZones", "modes": "InternalPlantModes"}
# Source PrepareFlashCheckbox binds Boolean elements of these exact TZones.
_CONTROL_ZONE_ROLES = frozenset(("ui", "internal", "measured", "heating", "cooling", "venting", "modes"))
_BOOL_FIELDS = tuple(side + "PlantFan" + name for side in ("Heating", "Cooling")
                     for name in ("SpeedControlEnable", "Enable"))
_GUARDS = ("zone120", "zone130", "plant15c", "plant15d", "unit1c0",
           "templates28", "templates29", "panel29", "panel2a")


def _fail(message):
    raise ThermostatTemplateError(message)


def _integer(value, maximum, label):
    if type(value) is not int or not 0 <= value <= maximum:
        _fail(label + " requires an exact integer in 0.." + str(maximum))
    return value


def normalize_quick_zone_operation(row):
    """Normalize explicit actions; no scheduling or supplied callback list."""
    if not isinstance(row, Mapping):
        _fail("Quick-zone operation must be a record")
    op = row.get("op")
    if type(op) is not str:
        _fail("Thermostat operation op must be text")
    if op in ("quick-zone-view", "quick-zone-refresh"):
        if set(row) != {"op"}:
            _fail(op + " takes no fields")
    elif op == "select-plant-type":
        if set(row) != {"op", "value"}:
            _fail("Plant selection requires exactly op and value")
        _integer(row["value"], 11, "Plant selection")
    elif op == "dispatch-plant-type-change":
        if set(row) != {"op", "posted_by"}:
            _fail("Plant dispatch requires exactly op and posted_by")
        if type(row["posted_by"]) is not int or row["posted_by"] < 1:
            _fail("posted_by must select a positive earlier operation position")
    elif op == "quick-zone-click":
        if not {"op", "zone", "checked"} <= set(row) or set(row) - {
                "op", "zone", "checked", "confirm_unswitched"}:
            _fail("Quick-zone click requires op, zone, checked and optional confirm_unswitched")
        _integer(row["zone"], 4, "Quick zone")
        if type(row["checked"]) is not bool:
            _fail("Quick-zone checked must be an exact Boolean")
        if "confirm_unswitched" in row:
            if type(row["confirm_unswitched"]) is not bool or row["zone"] != 0 or row["checked"]:
                _fail("Confirmation belongs only to an unchecked unswitched-zone action")
    else:
        return None
    return dict(row)


READ_FIELDS = tuple(sorted(set(_TYPE_FIELDS.values()) | set(_ZONE_FIELDS.values()) | {
    "InternalPlantType", "VentPlantType", "HeatingPlantStages", "CoolingPlantStages",
    "InstallationCode", "MinimumSetTemperature", "MaximumSetTemperature", "GuardEnable",
    "PlantMinimumOnTime", "PlantMinimumOffTime", "PlantCycleTime"} | set(_BOOL_FIELDS)))
FULL_CONTROL_READ_FIELDS = {'basic': ('ApplicationNumber', 'BacklightActiveTime', 'BacklightDimTime', 'BeepEnable', 'ControlledZones', 'CoolActivationOutput', 'CoolFanHighOutput', 'CoolFanLowOutput', 'CoolFanMediumOutput', 'CoolStage1Output', 'CoolStage2Output', 'CoolStage3Output', 'CoolingPlantFanDefaultSpeed', 'CoolingPlantFanEnable', 'CoolingPlantFanOffDelay', 'CoolingPlantFanOnDelay', 'CoolingPlantFanSpeedControlEnable', 'CoolingPlantFanSpeeds', 'CoolingPlantInstalledZones', 'CoolingPlantStages', 'CoolingPlantType', 'DamperModulationEnable', 'DamperZone1Output', 'DamperZone2Output', 'DamperZone3Output', 'DamperZone4Output', 'DisplayBacklightActiveBrightness', 'DisplayBacklightIdleBrightness', 'EvapComfortStartTemp', 'EvapComfortStepSize', 'EvapCoolerDryTime', 'EvapCoolerDumpTime', 'EvapCoolerFillTime', 'EvapCoolerIdleTime', 'EvapCoolerPrewetTime', 'EvapStartProportionalTemperature', 'EvapStopProportionalTemperature', 'FanOperationMode', 'GuardEnable', 'GuardLowerTemperature', 'GuardMaximumLowerTemperature', 'GuardMaximumUpperTemperature', 'GuardMinimumLowerTemperature', 'GuardMinimumUpperTemperature', 'GuardUpperTemperature', 'HeatActivationOutput', 'HeatCoolDifferentialFactor', 'HeatCoolIntegralFactor', 'HeatCoolPlantType', 'HeatFanHighOutput', 'HeatFanLowOutput', 'HeatFanMediumOutput', 'HeatStage1Output', 'HeatStage2Output', 'HeatStage3Output', 'HeatingPlantFanDefaultSpeed', 'HeatingPlantFanEnable', 'HeatingPlantFanOffDelay', 'HeatingPlantFanOnDelay', 'HeatingPlantFanSpeedControlEnable', 'HeatingPlantFanSpeeds', 'HeatingPlantInstalledZones', 'HeatingPlantStages', 'HeatingPlantType', 'InstallationCode', 'InstalledZones', 'InternalPlantModes', 'InternalPlantType', 'InternalPlantZones', 'InternalRelay1GroupNumber', 'InternalRelay2GroupNumber', 'InternalRelay3GroupNumber', 'InternalRelay4GroupNumber', 'InternalRelay5GroupNumber', 'KeyBacklightActiveBrightness', 'KeyBacklightIdleBrightness', 'MaximumSetTemperature', 'MeasuredZones', 'MinimumSetTemperature', 'PlantCycleTime', 'PlantMinimumOffTime', 'PlantMinimumOnTime', 'RemoteSetbackControlSource', 'RemoteSetbackOffGroup', 'RemoteSetbackOnGroup', 'SetbackLevel', 'TemperatureOffset', 'TemperatureSendDifferential', 'TemperatureUnits', 'TimerEnable', 'UIAllocatedZones', 'VariableFanCoilEnable', 'VariableFanCoilTiming', 'VentPlantType', 'VentingPlantInstalledZones', 'VentingPlantType', 'ZoneGroup', 'ZoneTemperatureDisplay'), 'programmable': ('ApplicationNumber', 'BacklightActiveTime', 'BacklightDimTime', 'BeepEnable', 'ControlledZones', 'CoolActivationOutput', 'CoolFanHighOutput', 'CoolFanLowOutput', 'CoolFanMediumOutput', 'CoolStage1Output', 'CoolStage2Output', 'CoolStage3Output', 'CoolingPlantFanDefaultSpeed', 'CoolingPlantFanEnable', 'CoolingPlantFanOffDelay', 'CoolingPlantFanOnDelay', 'CoolingPlantFanSpeedControlEnable', 'CoolingPlantFanSpeeds', 'CoolingPlantInstalledZones', 'CoolingPlantStages', 'CoolingPlantType', 'DamperModulationEnable', 'DamperZone1Output', 'DamperZone2Output', 'DamperZone3Output', 'DamperZone4Output', 'DisplayBacklightActiveBrightness', 'DisplayBacklightIdleBrightness', 'EvapComfortStartTemp', 'EvapComfortStepSize', 'EvapCoolerDryTime', 'EvapCoolerDumpTime', 'EvapCoolerFillTime', 'EvapCoolerIdleTime', 'EvapCoolerPrewetTime', 'EvapProgramEnabled', 'EvapStartProportionalTemperature', 'EvapStopProportionalTemperature', 'FanOperationMode', 'GuardEnable', 'GuardLowerTemperature', 'GuardMaximumLowerTemperature', 'GuardMaximumUpperTemperature', 'GuardMinimumLowerTemperature', 'GuardMinimumUpperTemperature', 'GuardUpperTemperature', 'HeatActivationOutput', 'HeatCoolDifferentialFactor', 'HeatCoolIntegralFactor', 'HeatCoolPlantType', 'HeatFanHighOutput', 'HeatFanLowOutput', 'HeatFanMediumOutput', 'HeatStage1Output', 'HeatStage2Output', 'HeatStage3Output', 'HeatingPlantFanDefaultSpeed', 'HeatingPlantFanEnable', 'HeatingPlantFanOffDelay', 'HeatingPlantFanOnDelay', 'HeatingPlantFanSpeedControlEnable', 'HeatingPlantFanSpeeds', 'HeatingPlantInstalledZones', 'HeatingPlantStages', 'HeatingPlantType', 'InstallationCode', 'InstalledZones', 'InternalPlantModes', 'InternalPlantType', 'InternalPlantZones', 'InternalRelay1GroupNumber', 'InternalRelay2GroupNumber', 'InternalRelay3GroupNumber', 'InternalRelay4GroupNumber', 'InternalRelay5GroupNumber', 'KeyBacklightActiveBrightness', 'KeyBacklightIdleBrightness', 'MaximumSetTemperature', 'MeasuredZones', 'MinimumSetTemperature', 'NonEvapProgramEnabled', 'PlantCycleTime', 'PlantMinimumOffTime', 'PlantMinimumOnTime', 'RemoteScheduleEnable', 'RemoteScheduleOffGroup', 'RemoteScheduleOnGroup', 'RemoteScheduleOverrideGroup', 'RemoteSetbackControlSource', 'RemoteSetbackOffGroup', 'RemoteSetbackOnGroup', 'ScheduleControlledZones', 'SendInterval', 'SetbackLevel', 'TemperatureOffset', 'TemperatureSendDifferential', 'TemperatureUnits', 'TimeUnits', 'UIAllocatedZones', 'VariableFanCoilEnable', 'VariableFanCoilTiming', 'VentPlantType', 'VentingPlantInstalledZones', 'VentingPlantType', 'ZoneGroup', 'ZoneTemperatureDisplay')}
PROGRAM_READ_FIELDS = ("EvapProgramEnabled", "NonEvapProgramEnabled", "RemoteScheduleEnable")
# Parent defers only these later source-owned field writes; unrelated scalar
# rules remain the existing settings planner's responsibility.
MODEL_SAVED_FIELDS = tuple(sorted(set(_TYPE_FIELDS.values()) | set(_ZONE_FIELDS.values()) | {
    "InternalPlantType", "VentPlantType", "HeatingPlantStages", "CoolingPlantStages",
    "InstallationCode", "EvapProgramEnabled", "NonEvapProgramEnabled", "RemoteScheduleEnable",
    "DamperModulationEnable", "ZoneTemperatureDisplay", "GuardEnable"} | {pp_name(role) for role in OUTPUTS + DAMPERS + RELAYS} | {
    side + "PlantFan" + name for side in ("Heating", "Cooling") for name in (
        "SpeedControlEnable", "Speeds", "DefaultSpeed", "Enable", "OnDelay", "OffDelay")}))


@dataclass(frozen=True)
class QuickZoneSave:
    """Diagnostic sealed result; exact originally issued instance is required."""
    expected: tuple[tuple[str, int], ...]
    model_overrides: tuple[tuple[str, int], ...]
    retained_master: bool
    signature: str

    def as_dict(self):
        return {"expected": dict(self.expected), "model_overrides": dict(self.model_overrides),
                "retained_master": self.retained_master, "signature": self.signature}


class _Installation:
    __slots__ = ("owner", "code", "name")
    def __init__(self, owner, code, name):
        self.owner, self.code, self.name = owner, code, name


def prepare_quick_zone_save(model, result):
    if (type(model) is not ThermostatControlModel or type(result) is not QuickZoneSave
            or model._issued_save is not result or model._signature() != result.signature
            or model._save_ledger != (result.expected, result.model_overrides, result.retained_master, result.signature)):
        _fail("Quick-zone save requires the original current owner-issued result")
    return dict(result.expected)


class _PlantChoice:
    __slots__ = ("owner", "value")

    def __init__(self, owner, value):
        self.owner, self.value = owner, value


class ThermostatControlModel:
    """Fresh source model and settled controls, issued from a loaded settings owner.

    The complete loaded model is inspected with source getters before the
    explicit history. This resolves its dirty flags without invoking setters.
    The exact inspection phase is recorded; it is not a claim that Windows
    focus, rendering, or queue initialization ran.
    """

    def __init__(self, owner, *, temperature_preference, remote_references=None):
        if type(owner) is not OutputGroupModel:
            _fail("Quick-zone model requires the exact owning OutputGroupModel")
        if set(owner.references) != set(OUTPUTS + DAMPERS + RELAYS) or not owner.loaded:
            _fail("Quick-zone model requires complete ordinary source loading")
        for group in owner.references.values():
            if group is not None and owner.resolver.current(group).identity != group.identity:
                _fail("Quick-zone references do not belong to the current source owner")
        source = owner.values
        if (temperature_preference != "celsius" or source.get("MinimumSetTemperature") != 15
                or source.get("MaximumSetTemperature") != 32 or source.get("GuardEnable") != 0):
            _fail("Settled quick-zone controls require source Celsius minimum15/maximum32/Guard0")
        on, off, cycle = (source.get(name) for name in ("PlantMinimumOnTime", "PlantMinimumOffTime", "PlantCycleTime"))
        if any(type(v) is not int for v in (on, off, cycle)) or not (
                0 <= on < 9 and 0 <= off < 9 and on + off + 2 < cycle < 35):
            _fail("Settled time controls require on/off below9 and on+off+2<cycle<35")
        fields = set(_ZONE_FIELDS.values()) - ({"ScheduleControlledZones"} if owner.family == "basic" else set())
        for name in fields:
            _integer(source[name], 31, name)
        # These are validated EnumeratedTypeAttributes during source AfterLoad.
        # Refuse raw invalid values before Basic master setup can assign zero.
        for name in _TYPE_FIELDS.values():
            _integer(source[name], 11, name)
        _integer(source["VentPlantType"], 2, "VentPlantType")
        _integer(source["ZoneTemperatureDisplay"], 4, "ZoneTemperatureDisplay")
        _integer(source["InternalPlantType"], 11, "InternalPlantType")
        self.output = owner
        self.source = dict(source)
        self._source_record = tuple(sorted(self.source.items()))
        self.values = owner.values
        self.values["InternalPlantType"] = virtual_plant_type(source)
        for name in _BOOL_FIELDS:
            self.values[name] = int(source[name] != 0)
        if self.is_programmable():
            for name, fallback in (("EvapProgramEnabled", 0), ("NonEvapProgramEnabled", 1)):
                value = source[name]
                self.values[name] = value if value in (0, 1) else fallback
        self._loaded_master = bool(owner.master)
        self._basic_user_enabled = self.source["UIAllocatedZones"] > 0
        self._sensor_enabled = self.source["MeasuredZones"] != 0
        if self.is_programmable():
            if not isinstance(remote_references, dict) or not {"schedule_on", "schedule_off", "schedule_override"} <= set(remote_references):
                _fail("Programmable quick-zone owner requires its exact causal remote-reference store")
            self.values["RemoteScheduleEnable"] = int(bool(self.values["EvapProgramEnabled"] or self.values["NonEvapProgramEnabled"]))
        self.remote_references = remote_references if remote_references is not None else {}
        for group in self.remote_references.values():
            if group is not None and owner.resolver.current(group).identity != group.identity:
                _fail("Inherited remote reference does not belong to the same live resolver")
        self._guards = {name: False for name in _GUARDS}
        self._unit_lock = self._manager_lock = 0
        self._scheduling_initializing = False
        self._scheduling_visible = False
        self._zone_dirty = {role: True for role in _ZONE_FIELDS}
        self._zone_dirty["used"] = True
        # Source creates UsedZones as a fresh empty TZones, with no PP load.
        self._used = 0
        self._trace = []
        self._alerts = []
        self._operations = []
        self._position = 0
        self._choices = tuple(_PlantChoice(self, n) for n in range(12))
        self._quick_checked = [False] * 5
        self._quick_state = [0] * 5
        self._old_plant = self.values["InternalPlantType"]
        self._installations = tuple(_Installation(self, code, "<Custom>" if code == 0 else INSTALLATION_NAMES[code])
            for code in range(10) if self.is_programmable() or code not in (2, 3, 7))
        self._installation_records = tuple((item, item.code, item.name) for item in self._installations)
        self._installation = next((item for item in self._installations if item.code == owner.installation), None)
        self._issued_save = None
        self._save_ledger = None
        self._hooks = {
            "zone_manager_plant_type_change": self._zone_manager_type_hook,
            "zone_after_change": self._unit_zone_change,
            "templates_zone_change": self._templates_zone_change,
            "enable_disable_plant_modes": self._enable_disable_plant_modes,
        }
        self.defaults = ZoneDefaultsModel(self)
        self.plant = PlantTypeModel(self.values, owner.references, owner.resolver,
            zone_group=self._zone_group, current_installation=self._current_installation,
            plant_type=self.get_internal_plant_type,
            reference_assigned=self._reference_assigned, scalar_assigned=self._plant_scalar_assigned)
        self.damper = owner.damper_controls
        if self.damper is None:
            self.damper = DamperControlModel(owner)
            owner.damper_controls = self.damper
        elif type(self.damper) is not DamperControlModel or self.damper._owner is not owner:
            _fail("Damper state belongs to another settings owner")
        self.queue = PlantChangeQueue(self, self._plant_after_change)
        self._initialize_settled_controls()

    def _record(self, method, **fields):
        self._trace.append({"method": method, "position": self._position, **fields})

    def _read(self, field):
        self._record("ResolveChange", field=field, setter=False)
        return self.values[field]

    def _zone_group(self):
        group = next((g for g in self.output.resolver.live.values()
                      if g.identity == self.output.zone_identity), None)
        if group is None:
            _fail("The source zone-group owner has become stale")
        return self.output.resolver.current(group)

    def _verify_owner(self):
        if (type(self.output) is not OutputGroupModel or self.values is not self.output.values
                or self.plant.values is not self.values or self.plant.references is not self.output.references
                or self.damper._owner is not self.output or self.queue._owner is not self
                or self._loaded_master != self.output.master
                or tuple(sorted(self.source.items())) != self._source_record):
            _fail("Quick-zone model no longer has its original shared source owner")
        if (len(self._installations) != len(self._installation_records)
                or any(item is not old or item.owner is not self or item.code != code or item.name != name
                       for item, (old, code, name) in zip(self._installations, self._installation_records))):
            _fail("Installation manager no longer contains its original source objects")

    def _current_installation(self):
        item = self._installation
        if item is not None and (item.owner is not self or not any(item is x for x in self._installations)):
            _fail("Installation pointer no longer belongs to this initialized manager")
        self._record("GetCurrentInstallation", code=None if item is None else item.code,
                     name=None if item is None else item.name, exact_owned_object=True)
        return None if item is None else item.name

    def _initialize_settled_controls(self):
        self._record("fresh-owner-model-inspection", writes=False,
                     phase="after-source-load-before-explicit-history")
        for role in _ZONE_FIELDS:
            if role == "schedule" and not self.is_programmable():
                continue
            self.get_zone_mask(role)
        self.get_used_zones()
        self._record("InitializeSubForms", order=["CBus", "UI", "ZoneManagement", "Plant", "TempControl", "Templates"])
        self.set_guard("templates29", True)
        self.set_guard("templates28", True)
        self._record("Templates.bind-owned-unit-and-child-links", subscribers_from_caller=False)
        self.set_guard("templates28", False)
        # SetupFlashComponents first prepares the actual source enum combo,
        # then the Basic master helper assigns zero, before SetupComponents
        # reaches the first quick-option refresh.
        self._record("Templates.PrepareFlashComboBox", property="ZoneTemperatureDisplay")
        if not self.is_programmable() and self._loaded_master:
            self._set_scalar("ZoneTemperatureDisplay", 0)
            self._record("Templates.EnableZoneTemperatureDisplay", basic_master=True,
                         value=0, initial_combo_callback_not_inferred=True)
        try:
            self._refresh_quick_options()
        finally:
            self.set_guard("templates29", False)
        if self.is_programmable():
            self._scheduling_initializing = True
            try:
                self._record("Scheduling.Initialise", after_templates=True)
                # CreateSubForm passes the actual child form to this method;
                # it sets its Visible property true, not merely the parent.
                self._scheduling_visible = True
                self._record("InitialiseFormAsTab:SetVisible", child="Scheduling", value=True,
                             source_call="0x112fd7c->0xdc1b72->0xdc1b77", native_show_executed=False)
                self._record("Scheduling.EnableControlsForMasterDisableForSlave:direct-Click")
                self._scheduling_controls()
            finally:
                self._scheduling_initializing = False

    def get_guard(self, name):
        if name not in self._guards:
            _fail("Unknown source guard: " + str(name))
        return self._guards[name]

    def set_guard(self, name, value):
        if name not in self._guards or type(value) is not bool:
            _fail("Source guard requires its exact owned name and Boolean")
        self._guards[name] = value
        self._record("guard", name=name, value=value)

    def has_registered_hook(self, name):
        return name in self._hooks

    def invoke_registered_hook(self, name, *args):
        if name not in self._hooks:
            _fail("No such hook is registered by this fresh source owner")
        self._record("owned-hook", name=name)
        return self._hooks[name](*args)

    def is_programmable(self):
        return self.output.family == "programmable"

    def get_master_slave(self):
        self._record("GetZoneManagerMasterSlave", value=0 if self._loaded_master else 1, retained_loaded_fact=True)
        return 0 if self._loaded_master else 1

    def get_internal_plant_type(self):
        return self._read("InternalPlantType")

    def get_type(self, role):
        return self._read(_TYPE_FIELDS[role])

    def set_type(self, role, value):
        value = _integer(value, 11, "Source type")
        field = _TYPE_FIELDS[role]
        if self._set_scalar(field, value):
            getattr(self.defaults, "handle_" + role + "_type_after_change")()

    def get_modes(self):
        return self.get_zone_mask("modes")

    def set_modes(self, value):
        self.set_zone_mask("modes", value)

    def get_vent_type(self):
        return self._read("VentPlantType")

    def set_vent_type(self, value):
        if self._set_scalar("VentPlantType", _integer(value, 2, "VentPlantType")):
            self.defaults.handle_vent_plant_type_change()

    def get_used_zones(self):
        return self.get_zone_mask("used")

    def installed_zones_is_present(self, role):
        self._record("GetInstalledZones-object", role=role, resolved_state=3, lazy_initialization=False)
        return role in ("heating", "cooling", "venting")

    def get_installed_zones(self, role):
        if not self.installed_zones_is_present(role):
            return None
        return self.get_zone_mask(role)

    def set_installed_zones(self, role, value):
        if role not in ("heating", "cooling", "venting"):
            _fail("Source has no separate HeatCool installed-zone object")
        self.set_zone_mask(role, value)

    def get_zone_mask(self, role):
        if role == "schedule" and not self.is_programmable():
            _fail("Basic thermostat has no Schedule service")
        if role not in self._zone_dirty:
            _fail("Unknown owned TZones")
        self._zone_dirty[role] = False
        self._record("TZones.GetZones", role=role, ordered_boolean_reads=[0, 1, 2, 3, 4],
                     value=self._used if role == "used" else self.values[_ZONE_FIELDS[role]])
        return self._used if role == "used" else self.values[_ZONE_FIELDS[role]]

    def _publish_zone(self, role):
        # This is the final owner EndUpdate, after both locked intermediate
        # Changed routes. Managed publication remains gated by dirty state.
        if self._zone_dirty[role]:
            self._record("TZones.Changed-suppressed", role=role, dirty=True)
            return
        self._zone_dirty[role] = True
        self._record("TZones.Managed.Changed", role=role,
                     publisher_order="reverse-registration", reference_order="forward-registration")
        if role in _CONTROL_ZONE_ROLES:
            # Bound Boolean-control current getters rearm the containing
            # TZones through AttributeManager.ResolveChange; render guard
            # prevents any setter/Click producer here.
            self._zone_dirty[role] = False
            self._record("owned-Boolean-control-read", role=role, model_write=False, render_guard=True)
        self._record("owning-ObjectAttribute.Changed", role=role, optional_external_hooks=False)
        if role == "cbus":
            self._unit_zone_change()
            self._installed_zones_change()
        elif role in ("internal", "modes"):
            if not self.get_guard("plant15c"):
                self.set_guard("plant15c", True)
                try:
                    self._unit_zone_change()
                finally:
                    self.set_guard("plant15c", False)
        elif role in ("heating", "cooling", "venting", "controlled"):
            self.defaults.handle_zone_after_change()
        elif role == "measured" or role == "schedule" or (role == "ui" and not self.is_programmable()):
            self._unit_zone_change()

    def _set_zone_boolean(self, role, zone, checked):
        if role == "schedule" and not self.is_programmable():
            _fail("Basic thermostat has no Schedule service")
        mask = self._used if role == "used" else self.values[_ZONE_FIELDS[role]]
        bit, old = 1 << zone, bool(mask & (1 << zone))
        self._record("Boolean.SetAsBoolean", role=role, zone=zone, value=checked, changed=old != checked)
        if old == checked:
            return
        updated = mask | bit if checked else mask & ~bit
        if role == "used":
            self._used = updated
        else:
            self.values[_ZONE_FIELDS[role]] = updated
        self._record("Boolean.Begin/store/End", role=role, zone=zone, before=mask, after=updated,
                     locked_intermediate_changes=2, outer_end=1)
        self._publish_zone(role)

    def set_zone_mask(self, role, value):
        value = _integer(value, 31, "TZones mask")
        for zone in range(5):
            self._set_zone_boolean(role, zone, bool(value & (1 << zone)))

    def include_zone(self, role, zone):
        zone = _integer(zone, 255, "Source zone enum")
        self._record("TZones.IncludeZone", role=role, zone=zone)
        if zone <= 4:
            self._set_zone_boolean(role, zone, True)

    def exclude_zone(self, role, zone):
        zone = _integer(zone, 255, "Source zone enum")
        self._record("TZones.ExcludeZone", role=role, zone=zone)
        if zone <= 4:
            self._set_zone_boolean(role, zone, False)

    def _set_scalar(self, field, value):
        old = self.values[field]
        self._record("Integer.SetAsInteger", field=field, old=old, value=value,
                     changed=old != value, fresh_before_change_nil=True)
        if old == value:
            return False
        self.values[field] = value
        self._record("Attribute.Changed", field=field, independent_of_managed_dirty=True)
        return True

    def set_program_enabled(self, name, value):
        if not self.is_programmable() or name not in ("non_evap", "evap") or type(value) is not bool:
            _fail("Program enable belongs to the owned AdvancedUI Boolean attribute")
        field = "NonEvapProgramEnabled" if name == "non_evap" else "EvapProgramEnabled"
        if self._set_scalar(field, int(value)):
            self._record("AdvancedUI.HandleEvapProgramEnabledAfterChange", field=field)
            self._program_enabled_change()

    def _program_enabled_change(self):
        self._record("Programmable.HandleEvapProgramEnableChange")
        # Source uses short-circuit OR and separate live UI getters.
        enabled = bool(self._read("EvapProgramEnabled"))
        if not enabled:
            enabled = bool(self._read("NonEvapProgramEnabled"))
        if self._set_scalar("RemoteScheduleEnable", int(enabled)):
            self._record("Scheduling.HandleRemoteScheduleEnableAfterChange",
                         initializing=self._scheduling_initializing, visible=self._scheduling_visible)
            if not self._scheduling_initializing and self._scheduling_visible:
                self._scheduling_controls()

    def _scheduling_controls(self):
        # Source OR order differs from the programmable model callback.
        enabled = bool(self._read("RemoteScheduleEnable"))
        if not enabled:
            enabled = bool(self._read("NonEvapProgramEnabled"))
        if not enabled:
            enabled = bool(self._read("EvapProgramEnabled"))
        if not enabled:
            for role in ("schedule_on", "schedule_off", "schedule_override"):
                group = self.output.resolver.group(203, 255, False, "quick-zone-schedule-disabled:" + role,
                                                  enable_application=False)
                self.remote_references[role] = group
                self._record("SetRemoteScheduleGroup", role=role,
                             identity=None if group is None else group.identity,
                             create=False, address=255)
        self._record("Scheduling.enabled-controls", enabled=enabled and self._loaded_master,
                     model_write=False)

    def _reference_assigned(self, role, old, group):
        self._record("Reference-value-adopted", role=role, identity=group.identity if group else None)

    def _plant_scalar_assigned(self, field, old, value):
        self._record("Plant-scalar-adopted", field=field, old=old, value=value)

    def update_fan_speeds(self):
        self._record("UpdateFanSpeedsForPlantType")
        self.plant.update_fan_speeds()

    def _zone_manager_type_hook(self, role, value):
        self._record("Thermostat.HandleZoneManagerPlantTypeChange", role=role, value=value)
        self.defaults.handle_zone_manager_plant_type_change()

    def _unit_zone_change(self):
        if self.get_guard("unit1c0"):
            self._record("Thermostat.HandleZoneChange-suppressed")
            return
        self.set_guard("unit1c0", True)
        try:
            self._record("Templates.HandleUnitZoneChange")
            self._refresh_quick_options()
        finally:
            self.set_guard("unit1c0", False)

    def _installed_zones_change(self):
        self._record("Thermostat.HandleInstalledZonesChange")
        self.damper.installed_zones = self.get_zone_mask("cbus")
        self.damper._update()

    def _templates_zone_change(self, zone, included):
        self._record("Templates.parent-zone-callback", zone=zone, included=included,
                     order=["UI.EnableDisableZone", "ZoneManagement.EnableDisableZone",
                            "Plant.EnableDisableZone", "TempControl.EnableSliders"])
        self._record("TempControl.min/max/min", initial_pair=[15, 32], guard=False, model_writes=0)

    def _enable_disable_plant_modes(self):
        self._record("Plant.EnableDisablePlantModes", native_window_messages=False)

    def get_quick_checked(self, zone):
        return self._quick_checked[zone]

    def _refresh_quick_options(self):
        if self.get_guard("templates28"):
            self._record("Templates.UpdateQuickOptions-suppressed")
            return
        self.set_guard("templates28", True)
        try:
            for zone in range(5):
                self._quick_checked[zone] = self.defaults.templates_zone_partially_on(zone)
            for zone in range(5):
                self._quick_state[zone] = self.defaults.templates_checkbox_state_for_zone(zone)
            self._record("Templates.checkbox-refresh", checked=list(self._quick_checked), state=list(self._quick_state))
            if not self.get_guard("templates29"):
                self.defaults.update_flash_zone_variables()
        finally:
            self.set_guard("templates28", False)

    def _alert(self, code):
        self._alerts.append({"code": code, "position": self._position})
        self._record("CISError", code=code)

    def _quick_click(self, row):
        if self.get_guard("templates28"):
            self._record("Templates.HandleChbUsedZoneClick-suppressed")
            return
        zone, checked = row["zone"], row["checked"]
        self._quick_checked[zone] = checked
        self.set_guard("templates28", True)
        try:
            if checked:
                self.defaults.templates_include_zone(zone)
            elif sum(self._quick_checked) == 0:
                self._alert(7321)
                self._quick_checked[zone] = True
            elif zone == 0:
                self._alert(7320)
                if "confirm_unswitched" not in row:
                    _fail("Reached unswitched-zone warning requires an explicit confirmation outcome")
                if row["confirm_unswitched"]:
                    self.defaults.templates_exclude_zone(zone)
                else:
                    self._quick_checked[0] = True
            else:
                self.defaults.templates_exclude_zone(zone)
        finally:
            self.set_guard("templates28", False)

    def _plant_before_change(self):
        self._old_plant = self.get_internal_plant_type()
        self._record("Plant.HandleInternalPlantTypeBeforeChange", old=self._old_plant)
        self.set_guard("plant15d", True)

    def _select_choice(self, choice, position):
        if (type(choice) is not _PlantChoice or choice.owner is not self
                or type(choice.value) is not int or not 0 <= choice.value <= 11
                or self._choices[choice.value] is not choice):
            _fail("Plant selection requires the originally issued offered object")
        self._plant_before_change()
        self._record("Combo.DoIndexChange", value=choice.value, immediate_apply=True)
        self._set_scalar("InternalPlantType", choice.value)
        self.output.plant = self.get_internal_plant_type()
        self._record("Combo.dynamicChange->DFM.OnChange")
        self.queue.post(position)

    def _plant_after_change(self):
        self._update_parameters_to_match_plant_type()
        self.set_guard("plant15d", False)
        self._record("Plant.EnableCycleLimitingControls", enabled=self.get_internal_plant_type() != 2)

    def _update_parameters_to_match_plant_type(self):
        if self.get_guard("panel29"):
            self._record("Plant.UpdateParameters-suppressed")
            return
        prior120 = self.get_guard("zone120")
        self.set_guard("panel29", True)
        self._unit_lock += 1
        self._manager_lock += 1
        self._record("Plant.owner-and-GroupManager.BeginUpdate", unit_depth=self._unit_lock, manager_depth=self._manager_lock)
        try:
            self.set_guard("plant15c", True)
            self.set_guard("zone120", True)
            try:
                self.defaults.set_default_plant_modes()
                self.defaults.update_vent_plant_type()
            finally:
                if not prior120:
                    self.set_guard("zone120", False)
                self.set_guard("plant15c", False)
            try:
                self.plant.update_parameters()
            except PlantGroupCapacityError:
                self._alert(7327)
                return
            if not self.get_guard("zone120"):
                self.set_guard("zone120", True)
                try:
                    self.defaults.set_default_plant_types(self.get_internal_plant_type())
                    if self.get_internal_plant_type() == 0:
                        for role in ("cooling", "heating", "heatcool", "venting"):
                            self.set_type(role, 0)
                finally:
                    self.set_guard("zone120", False)
            item = self._installations[0]
            self._record("InstallationManager.GetItem", index=0, code=item.code,
                         name=item.name, exact_owned_object=True, resolved_reference=True)
            self._installation = item
            self.output.installation, self.output.installation_name = item.code, item.name
            self.values["InstallationCode"] = item.code
            if self.get_internal_plant_type() in (0, 2, 5):
                self._set_scalar("HeatingPlantStages", 0)
            elif self._read("HeatingPlantStages") == 0:
                self._set_scalar("HeatingPlantStages", 1)
            if self.get_internal_plant_type() in (0, 1, 4, 8):
                self._set_scalar("CoolingPlantStages", 0)
            elif self._read("CoolingPlantStages") == 0:
                self._set_scalar("CoolingPlantStages", 1)
            self._record("Plant.parent30-callback", order=["Templates.UpdateTypicalInstallationEdit", "ZoneManagement.RefreshZoneCheckboxes"])
            self._refresh_parent_views()
        finally:
            self.set_guard("panel29", False)
            self._manager_lock -= 1
            self._record("GroupManager.EndUpdate", depth=self._manager_lock)
            self._unit_lock -= 1
            self._record("Thermostat.EndUpdate", depth=self._unit_lock)
            self._record("cursor-restored")
        self._record("Plant.EnableControlsForMasterDisableForSlave", loaded_master=self._loaded_master)

    def _refresh_parent_views(self):
        # Templates checks current nil, then separately gets name and description.
        name = self._current_installation()
        if name is not None:
            self._current_installation()
            self._current_installation()
        self._record("Templates.UpdateTypicalInstallationEdit", model_write=False)
        if self.is_programmable():
            for zone in range(5):
                enabled = bool(self.get_used_zones() & (1 << zone))
                self._record("ZoneManagement.EnableDisableZone", zone=zone, enabled=enabled,
                             model_write=False, loaded_master=self._loaded_master)

    def process(self, row, position, *, project_tag_name=None, validate_address=None):
        self._verify_owner()
        if type(position) is not int or position <= self._position:
            _fail("Thermostat control positions must strictly increase in this fresh history")
        operation = normalize_quick_zone_operation(row)
        if operation is None and normalize_damper_operation(row) is None:
            # The internal adapter consumes only an existing normalized ordinary
            # operation. Do not allow arbitrary records to reach its getters.
            row = json.loads(normalize_output_operations([row])[0])
        self._position = position
        before = self._diagnostic_values()
        if operation is None:
            damper = normalize_damper_operation(row)
            if damper is not None:
                if damper["op"] == "damper-installed-zones":
                    # Each Boolean callback sees the actual intermediate mask.
                    state_before = self.damper._state()
                    start = len(self._trace)
                    self.set_zone_mask("cbus", damper["value"])
                    self.damper.installed_zones = self.values["InstalledZones"]
                    self.damper.overrides["InstalledZones"] = self.values["InstalledZones"]
                    self.damper.operations.append({"position": position, **damper,
                        "before": state_before, "after": self.damper._state(),
                        "source_calls": deepcopy(self._trace[start:]), "owned_subscriber_dispatch": True})
                else:
                    self.damper.process(damper, position)
                    if damper["op"] == "damper-modulation-binding":
                        self.values["DamperModulationEnable"] = int(self.damper.modulation)
            else:
                receipt = self.output._operate_output_operation(row, position, project_tag_name, validate_address)
                if self.output.operations is None:
                    self.output.operations = []
                self.output.operations.append(receipt)
                # Bound reference assignment applies even when target identical.
                if row.get("op") == "select-output-group" or (row.get("op") == "add-output-group" and row.get("outcome") == "accept"):
                    self._record("ObjectReferenceAttribute.SetFlashObject", parameter=row["parameter"],
                                 attribute_changed_even_same=True, optional_role_callback_unbound=True)
                self._record("ordinary-output-control", operation=dict(row), exact_shared_owner=True)
        else:
            op = operation["op"]
            if op == "quick-zone-refresh":
                self._refresh_quick_options()
            elif op == "quick-zone-click":
                self._quick_click(operation)
            elif op == "select-plant-type":
                self._select_choice(self._choices[operation["value"]], position)
            elif op == "dispatch-plant-type-change":
                self.queue.dispatch(operation["posted_by"], position)
            else:
                self._record("quick-zone-view", writes=False)
        self._operations.append({"position": position, "operation": dict(row),
                                 "before": before, "after": self._diagnostic_values()})
        return deepcopy(self._operations[-1])

    def _diagnostic_values(self):
        return {"plant_type": self.values["InternalPlantType"],
                "modes": self.values["InternalPlantModes"], "used_zones": self._used,
                "masks": {role: self.values[field] for role, field in _ZONE_FIELDS.items() if field in self.values},
                "checked": list(self._quick_checked), "states": list(self._quick_state),
                "loaded_master": self._loaded_master, "guards": dict(self._guards),
                "installation": {"code": None if self._installation is None else self._installation.code,
                                 "name": None if self._installation is None else self._installation.name}}

    @property
    def model_overrides(self):
        return {name: value for name, value in self.values.items() if self.source.get(name) != value}

    @property
    def save_facts(self):
        value = self.values["InternalPlantType"]
        return {"loaded_master": self._loaded_master,
                "controlled_zones": (self._operation_zone() if not self.is_programmable()
                                      else self.values["InstalledZones"]) if self._loaded_master else 0,
                "plant_type": 0 if not self._loaded_master else 8 if value == 11 else value,
                "model_type_before_save": value,
                "mutable_zone_manager_mask_is_not_master_authority": True}

    def _operation_zone(self):
        value = self.values["ZoneTemperatureDisplay"] & 255
        return (1 << value) if value <= 7 else 0

    def _basic_save_tail(self, expected):
        operation = self._operation_zone()
        expected["ZoneTemperatureDisplay"] = self.values["ZoneTemperatureDisplay"] & 255
        expected["UIAllocatedZones"] = operation if self._basic_user_enabled else 0
        if self._loaded_master:
            expected.update(InstalledZones=operation, ControlledZones=operation,
                            InternalPlantZones=operation,
                            HeatingPlantInstalledZones=operation if self.values["HeatingPlantType"] else 0,
                            CoolingPlantInstalledZones=operation if self.values["CoolingPlantType"] else 0,
                            # Source deliberately uses Cooling here too.
                            VentingPlantInstalledZones=operation if self.values["CoolingPlantType"] else 0,
                            GuardEnable=0)
        expected["MeasuredZones"] = operation if self._sensor_enabled else 0

    def _signature(self):
        self._verify_owner()
        payload = {"source": self._source_record, "values": self.values, "references": {role: None if group is None else group.identity
                    for role, group in self.output.references.items()},
                   "groups": [(app, address, group.identity, group.name)
                              for (app, address), group in sorted(self.output.resolver.live.items())],
                   "group_records": [group.as_dict() for _, group in sorted(self.output.resolver.live.items())],
                   "remote_references": {role: None if group is None else group.identity
                                         for role, group in self.remote_references.items()},
                   "installation": None if self._installation is None else (self._installation.code, self._installation.name),
                   "position": self._position, "master": self._loaded_master}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True,
                           separators=(",", ":")).encode()).hexdigest()

    def issue_save(self):
        self._verify_owner()
        from .thermostat_settings import form_save
        if self.queue.as_dict()["pending_positions"] or self.get_guard("plant15d"):
            _fail("Terminal save refuses pending explicit plant-change delivery")
        self.output.validate()
        # Legacy scalar/fan save helpers infer role from ControlledZones. Supply
        # the retained master fact in a temporary serializer input; do not write
        # the live zone-manager mask or reclassify the loaded model.
        serialization = dict(self.values)
        serialization["ControlledZones"] = int(self._loaded_master)
        expected = dict(self.values)
        expected.update(form_save(serialization, self.output.family, temperature_preference="celsius"))
        expected.update(self.output.expected)
        # Common BeforeSave reads the actual current installation twice when
        # nonnil; its Code field is saved, and nil saves literal zero.
        self._current_installation()
        if self._installation is not None:
            self._current_installation()
        expected["InstallationCode"] = 0 if self._installation is None else self._installation.code
        if self.is_programmable():
            enabled = bool(self.values["EvapProgramEnabled"] or self.values["NonEvapProgramEnabled"])
            expected["RemoteScheduleEnable"] = int(enabled)
            for field, role, default in (("RemoteScheduleOnGroup", "schedule_on", 32),
                                         ("RemoteScheduleOffGroup", "schedule_off", 33),
                                         ("RemoteScheduleOverrideGroup", "schedule_override", 34)):
                group = self.remote_references[role]
                if enabled and (group is None or self.output.resolver.current(group) is None):
                    _fail("Enabled remote schedule lacks a live owned group")
                expected[field] = group.address if enabled else default
        expected["ControlledZones"] = self.values["InstalledZones"] if self._loaded_master else 0
        if not self._loaded_master:
            expected.update(InternalPlantType=0, InternalPlantZones=0)
        if not self.is_programmable():
            self._basic_save_tail(expected)
        self._issued_save = QuickZoneSave(tuple(sorted(expected.items())),
            tuple(sorted(self.model_overrides.items())), self._loaded_master, self._signature())
        self._save_ledger = (self._issued_save.expected, self._issued_save.model_overrides,
                             self._issued_save.retained_master, self._issued_save.signature)
        return self._issued_save

    def as_dict(self):
        return {"profile": "fresh-source-owner-settled-explicit-quick-zone-controls-v1",
                "state": self._diagnostic_values(), "operations": deepcopy(self._operations),
                "source_calls": deepcopy(self._trace), "alerts": deepcopy(self._alerts),
                "posted_changes": self.queue.as_dict(), "model_overrides": self.model_overrides,
                "save_facts": self.save_facts, "damper_controls": self.damper.as_dict(),
                "full_toolkit_parity": False, "native_control_scheduling_reproduced": False,
                "original_form_executed": False, "physical_device_programmed": False,
                "detached_continuation_admitted": False}
