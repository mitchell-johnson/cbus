"""Thermostat zone, plant, fan and user-interface settings editor.

Edits one closed database PC_TSA/PC_TSA5 (THERMOSTATA) or PC_TSB/PC_TSB5
(THERMOSTATB) unit at PP level.  Each value is checked against the caller's
decoded unit specification.  Edits are also checked against the recovered
Toolkit 1.18 form save (``thermostat_post_load``): a value that the original
BeforeSaveProgrammingInformation would rewrite on its next save is refused,
and the dependent fields the form save would rewrite are reported.  Apply
makes a backup, one PP save and a reload readback.  No physical thermostat
is programmed.  Dialog enable/visibility rules are not reproduced.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from uuid import uuid4

from .addressing import NetworkAddressing
from .native import NativeDatabase, NativeProjects, _project
from .programming import Programmer
from .thermostat_post_load import damper_modulation_save, form_save_fans, virtual_plant_type
from .thermostat_templates import (FAMILIES, NativeThermostatTemplates, ThermostatTemplateError,
                                   _native_integer, _path, _unit_record, family_for_unit_type)
from .unitspec import UnitSpecError, UnitSpecStore

ZONES = ('InstalledZones', 'ControlledZones', 'HeatingPlantInstalledZones', 'CoolingPlantInstalledZones',
         'VentingPlantInstalledZones', 'InternalPlantZones', 'MeasuredZones', 'UIAllocatedZones')
PLANT = ('HeatingPlantType', 'CoolingPlantType', 'HeatCoolPlantType', 'VentingPlantType', 'InternalPlantType',
         'InternalPlantModes', 'VentPlantType', 'HeatingPlantStages', 'CoolingPlantStages', 'FanOperationMode',
         'PlantMinimumOnTime', 'PlantMinimumOffTime', 'PlantCycleTime', 'DamperModulationEnable',
         'VariableFanCoilEnable', 'VariableFanCoilTiming', 'EvapCoolerFillTime', 'EvapCoolerIdleTime',
         'EvapCoolerDumpTime', 'EvapCoolerPrewetTime', 'EvapCoolerDryTime')
FANS = tuple(side + 'PlantFan' + field for side in ('Heating', 'Cooling')
             for field in ('SpeedControlEnable', 'Speeds', 'DefaultSpeed', 'OnDelay', 'OffDelay', 'Enable'))
INTERFACE = ('DisplayBacklightIdleBrightness', 'DisplayBacklightActiveBrightness', 'KeyBacklightIdleBrightness',
             'KeyBacklightActiveBrightness', 'BacklightActiveTime', 'BacklightDimTime', 'BeepEnable',
             'TemperatureUnits', 'ZoneTemperatureDisplay', 'HeatCoolIntegralFactor', 'HeatCoolDifferentialFactor',
             'TemperatureOffset', 'TemperatureSendDifferential')
FAMILY_SPECIFIC = {'programmable': ('TimeUnits', 'EvapProgramEnabled', 'NonEvapProgramEnabled', 'SendInterval',
                                    'ScheduleControlledZones'),
                   'basic': ('TimerEnable',)}
COMMON = ZONES + PLANT + FANS + INTERFACE
# Settings whose original AfterLoad normalises out-of-range values.
AFTERLOAD_FLAGS = {'EvapProgramEnabled': (0, 1), 'NonEvapProgramEnabled': (0, 1)}


def admitted(family):
    return COMMON + FAMILY_SPECIFIC[family]


def form_save(values: Mapping[str, int], family: str) -> dict[str, int]:
    """Values the original form save writes for the replayed dependent fields."""
    result = form_save_fans(values)
    result['DamperModulationEnable'] = damper_modulation_save(values['DamperModulationEnable'],
                                                              virtual_plant_type(values))
    if family == 'programmable':
        result['EvapProgramEnabled'] = 0 if values['EvapProgramEnabled'] > 1 else values['EvapProgramEnabled']
        result['NonEvapProgramEnabled'] = 1 if values['NonEvapProgramEnabled'] > 1 else values['NonEvapProgramEnabled']
    return result


@dataclass(frozen=True)
class SettingsPlan:
    family: str
    unit_type: str
    before: tuple[tuple[str, str], ...]
    edits: tuple[tuple[str, int], ...]
    dependent: tuple[tuple[str, int, int], ...]

    @property
    def expected(self):
        return dict(self.edits)

    def as_dict(self):
        before = dict(self.before)
        return {'family': self.family, 'unit_type': self.unit_type,
                'changed_parameters': [{'name': n, 'before': _native_integer(before[n], n), 'after': v}
                                       for n, v in self.edits if _native_integer(before[n], n) != v],
                'requested': dict(self.edits),
                'dependent_form_save_changes': [{'name': n, 'after_edit': a, 'form_save': b}
                                                for n, a, b in self.dependent],
                'dialog_enable_rules_reproduced': False, 'physical_device_programmed': False}


def plan_settings(store: UnitSpecStore, unit_type: str, snapshot: Mapping[str, str],
                  edits: Mapping[str, object]) -> SettingsPlan:
    family = family_for_unit_type(unit_type)
    if not isinstance(edits, Mapping) or not edits:
        raise ThermostatTemplateError('Supply at least one setting edit')
    try:
        spec = store.load(FAMILIES[family]['unit_spec'])
    except UnitSpecError as error:
        raise ThermostatTemplateError(str(error)) from error
    allowed = admitted(family)
    parsed = {}
    for name, value in edits.items():
        if name not in allowed:
            raise ThermostatTemplateError('Setting is not admitted for ' + unit_type + ': ' + str(name))
        parameter = spec.parameters.get(name)
        if parameter is None or parameter.type != 'int' or parameter.array_size != 1:
            raise ThermostatTemplateError('Unit specification lacks one-byte setting: ' + name)
        if type(value) is bool or not isinstance(value, (int, str)):
            raise ThermostatTemplateError('Setting value must be an integer: ' + name)
        checked = parameter.validate_value(str(value) if isinstance(value, int) else value)
        if not checked['valid']:
            raise ThermostatTemplateError(name + ': ' + '; '.join(checked['errors']))
        parsed[name] = checked['parsed']
    for name, (low, high) in AFTERLOAD_FLAGS.items():
        if name in parsed and not low <= parsed[name] <= high:
            raise ThermostatTemplateError(name + ' must be 0 or 1; the original load normalises other values')
    current = {}
    for name, text in snapshot.items():
        try:
            current[name] = _native_integer(text, name)
        except ThermostatTemplateError:
            continue
    after = dict(current, **parsed)
    try:
        saved = form_save(after, family)
    except KeyError as error:
        raise ThermostatTemplateError('Unit snapshot lacks a form-save dependency: ' + str(error)) from error
    rewritten = sorted(name for name in parsed if name in saved and saved[name] != parsed[name])
    if rewritten:
        raise ThermostatTemplateError('The original form save would rewrite ' + ', '.join(
            f'{n}={saved[n]}' for n in rewritten) + '; choose values that survive it')
    dependent = tuple((n, after[n], v) for n, v in sorted(saved.items()) if after.get(n) != v)
    return SettingsPlan(family, unit_type, tuple(sorted(snapshot.items())), tuple(sorted(parsed.items())),
                        dependent)


@dataclass(frozen=True)
class NativeSettingsPlan:
    path: str
    project: str
    network: str
    settings: SettingsPlan
    unit_xml: str
    identity: tuple[tuple[str, object], ...]
    networks: tuple[str, ...]

    def as_dict(self):
        return {'format': 'cbus-native-thermostat-settings-plan-v1', 'path': self.path,
                'identity': dict(self.identity), **self.settings.as_dict(),
                'closed_networks': list(self.networks),
                'apply_would_mutate': bool(self.settings.as_dict()['changed_parameters']),
                'caller_exclusive_project_required': True, 'server_edit_lock_acquired': False}


class NativeThermostatSettings(NativeThermostatTemplates):
    """Plan and apply thermostat settings to one closed database unit."""

    def __init__(self, client, store: UnitSpecStore):
        if not isinstance(store, UnitSpecStore):
            raise TypeError('store must be a UnitSpecStore')
        self.client, self.catalog, self.store = client, None, store
        self.database, self.projects = NativeDatabase(client), NativeProjects(client)
        self.programmer, self.network_guard = Programmer(client), NetworkAddressing(client)
        self._plans: dict[int, str] = {}
        self._consumed: set[int] = set()
        self.last_evidence = None

    def _start(self, operation):
        super()._start(operation)
        self.last_evidence['format'] = 'cbus-native-thermostat-settings-result-v1'
        del self.last_evidence['original_post_load_adjustments_replayed']

    def plan(self, path, edits, *, exclusive_project=False):
        self._start('settings-plan')
        try:
            path, project, network_address, address = _path(path)
            network = '//' + project + '/' + str(network_address)
            if exclusive_project is not True:
                raise ThermostatTemplateError('Caller must exclusively own project editing/reloading')
            self._operation('use', project)
            networks = self._networks(project)
            if network not in networks:
                raise ThermostatTemplateError('Unit network is absent from the closed project inventory')
            text, identity, values = self._read(path, network, address)
            settings = plan_settings(self.store, identity['UnitType'], values, edits)
            plan = NativeSettingsPlan(path, project, network, settings, text,
                                      tuple(sorted(identity.items())), networks)
            self._plans[id(plan)] = repr(plan)
            self.last_evidence.update(state='planned', complete=True, plan=plan.as_dict())
            return plan
        except BaseException as error:
            self._fail(error)

    def _changed(self, plan, actual):
        before = dict(plan.settings.before)
        expected = plan.settings.expected
        mismatched = sorted(n for n, v in expected.items() if n not in actual or _safe(actual[n]) != v)
        unrelated = sorted(n for n in set(before) | set(actual)
                           if n not in expected and before.get(n) != actual.get(n))
        return {'setting_mismatches': mismatched, 'unrelated_changes': unrelated}

    def apply(self, plan, *, backup_project=None):
        self._start('settings-apply')
        try:
            if type(plan) is not NativeSettingsPlan or self._plans.get(id(plan)) != repr(plan):
                raise ThermostatTemplateError('Use an unchanged plan issued by this manager')
            if id(plan) in self._consumed:
                raise ThermostatTemplateError('This plan already had an apply attempt; review a fresh plan')
            backup = _project(backup_project) if backup_project is not None else 'B' + uuid4().hex[:7].upper()
            if backup.upper() == plan.project.upper():
                raise ThermostatTemplateError('Backup project must differ from the edited project')
            self._consumed.add(id(plan))
            changes = plan.settings.as_dict()['changed_parameters']
            self.last_evidence.update(path=plan.path, backup_project=backup,
                                      changed_parameters=[row['name'] for row in changes])
            self._operation('use', plan.project)
            self._fresh_settings(plan)
            if not changes:
                self.last_evidence.update(state='already_applied', complete=True, backup_project=None)
                return self.last_evidence
            self.last_evidence['state'] = 'backup'
            self._operation('save', plan.project)
            self._operation('copy', plan.project, backup)
            self.last_evidence['backup_created'] = True
            self._operation('use', plan.project)
            self._fresh_settings(plan)
            self.last_evidence['state'] = 'staging'
            with self._session(plan.path, plan.network) as session:
                if tuple(sorted(session.values().items())) != plan.settings.before:
                    raise ThermostatTemplateError('Unit changed immediately before staging')
                for row in changes:
                    reply = session.set(row['name'], str(row['after']))
                    if getattr(reply, 'code', None) != 200:
                        raise RuntimeError('PP SET did not complete')
                staged = self._changed(plan, session.values())
                self.last_evidence['staged_comparison'] = staged
                if staged['setting_mismatches'] or staged['unrelated_changes']:
                    raise ThermostatTemplateError('Staged settings differ from the plan; not saved')
                self.last_evidence.update(staged_verified=True, state='saving', pp_save_attempted=True)
                reply = session.save_to_source()
                if getattr(reply, 'code', None) != 200:
                    raise RuntimeError('PP SAVE_TO_SOURCE did not complete')
                self.last_evidence['pp_save_confirmed'] = True
            self.last_evidence['target_save_attempted'] = True
            self._operation('save', plan.project)
            self.last_evidence['target_save_confirmed'] = True
            for action in ('close', 'load'):
                self.last_evidence['project_operation_attempted'] = action
                self._operation(action, plan.project)
            self._operation('use', plan.project)
            address = int(plan.path.rsplit('/', 1)[1])
            text, identity, values = self._read(plan.path, plan.network, address)
            comparison = self._changed(plan, values)
            before_identity, before_shape, _stored = _unit_record(plan.unit_xml, address)
            _identity, after_shape, _stored = _unit_record(text, address)
            preserved = identity == before_identity and after_shape == before_shape
            self.last_evidence.update(reloaded_comparison=comparison, unit_record_preserved=preserved,
                                      unrelated_parameters_preserved=not comparison['unrelated_changes'])
            if comparison['setting_mismatches'] or comparison['unrelated_changes'] or not preserved:
                raise ThermostatTemplateError('Saved/reloaded unit differs from the planned settings')
            self.last_evidence.update(state='verified_saved', complete=True, persistence_verified=True)
            return self.last_evidence
        except BaseException as error:
            self._fail(error)

    def _fresh_settings(self, plan):
        if self._networks(plan.project) != plan.networks:
            raise ThermostatTemplateError('Project network inventory changed since planning')
        address = int(plan.path.rsplit('/', 1)[1])
        text, _identity, values = self._read(plan.path, plan.network, address)
        if text != plan.unit_xml or tuple(sorted(values.items())) != plan.settings.before:
            raise ThermostatTemplateError('Unit record or PP parameters changed since planning')


def _safe(text):
    try:
        return _native_integer(text, '')
    except ThermostatTemplateError:
        return None
