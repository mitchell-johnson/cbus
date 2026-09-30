"""Thermostat "Load Template" catalogue, overlay plans and native apply.

The original Toolkit dialog offers a fixed installation list per thermostat
class and loads the selected template with ``PP LOAD_FROM_FILE``, without a
preceding reset.  Native C-Gate writes only the template's declared parameter
bytes into the open PP session.  This module reproduces that rule from
caller-supplied decoded specifications (``CBUS_UNITSPEC_DIR``), refuses the
pairs the original never offers, and applies the overlay to one closed
database unit with a backup, one PP save and reload verification.

By default the original dialog's later Toolkit object-model adjustments are
replayed for the fields they touch (``thermostat_post_load``): output and
relay group reassignment with output-application group creation/renaming,
fan settings, damper modulation encoding and the programmable Evap flags.
The replay fails closed outside its recovered precondition; ``post_load=False``
keeps the pure native overlay.  No physical thermostat is programmed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import uuid4
from xml.dom import Node

from .addressing import NetworkAddressing, _container
from .classic_replacement import _document, _path
from .native import NativeDatabase, NativeProjects, _project
from .programming import Programmer, xml_text
from .thermostat_post_load import (PostLoadReplay, ThermostatPostLoadError, replay_post_load,
                                   validate_group_sort)
from .unitspec import UnitSpecError, UnitSpecStore, _integer, version_matches


class ThermostatTemplateError(ValueError):
    """An incompatible, malformed or unsupported thermostat template request."""


# TCBusThermostatCGateAgent.LoadThermostatInstallations: installation index
# N (1..9) uses template N.  TProgrammableThermostat units (PC_TSA/PC_TSA5)
# get THERMOSTATA_TEMPLATEnn for every index; other thermostat classes
# (TBasicThermostat: PC_TSB/PC_TSB5) get THERMOSTAT_TEMPLATEnn and never see
# installations 2, 3 and 7.  Index 0 is "<Custom>" with no template file.
FAMILIES = {
    'programmable': {'unit_types': ('PC_TSA', 'PC_TSA5'), 'prefix': 'THERMOSTATA_TEMPLATE',
                     'spec_type': 'THERMOSTATA', 'unit_spec': 'THERMOSTATA.xml',
                     'offered': (1, 2, 3, 4, 5, 6, 7, 8, 9)},
    'basic': {'unit_types': ('PC_TSB', 'PC_TSB5'), 'prefix': 'THERMOSTAT_TEMPLATE',
              'spec_type': 'THERMOSTAT', 'unit_spec': 'THERMOSTATB.xml',
              'offered': (1, 4, 5, 6, 8, 9)},
}
PROGRAMMABLE_ONLY = (2, 3, 7)
# Steps TcdThermostatTemplates.HandleBtnLoadClick performs on the Toolkit
# object model around the PP load; the form writes the model on a later save.
ORIGINAL_POST_LOAD_ADJUSTMENTS = (
    'ClearOriginalDamperGroups: clears four retained plant-control damper group references before loading',
    'ZoneManagerMasterSlave: a master/slave value of 1 is set to 0 before loading; AfterLoad then derives it '
    'from ControlledZones (0 when ControlledZones > 0, else 1), so the pre-load value does not persist',
    'AfterLoadProgrammingInformation: the normal agent model load runs after PP GET *, resolving output '
    'groups per virtual plant type and creating/renaming [CGnn] groups',
    'UpdateParametersForPlantType: reassigns output/relay groups by virtual plant type and installation',
    'UpdateFanSpeedsForPlantType: sets the eight heating/cooling fan settings by plant type',
    'UpdateEvapProgramParameters (programmable only): EvapProgramEnabled=0; NonEvapProgramEnabled=0 for '
    'virtual plant type 0 or 2',
    'Form save (BeforeSaveProgrammingInformation): writes the model back, including the fan interlock, '
    'damper modulation encoding and InstallationCode',
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def _error(error):
    try:
        message = str(error)
    except BaseException:
        message = '<unprintable>'
    return {'type': type(error).__name__, 'message': message[:2048]}


def family_for_unit_type(unit_type: Any) -> str:
    for name, family in FAMILIES.items():
        if unit_type in family['unit_types']:
            return name
    raise ThermostatTemplateError(
        'Load Template is available only for PC_TSA/PC_TSA5 and PC_TSB/PC_TSB5 thermostats; got '
        + repr(unit_type))


def template_filename(family: str, number: int) -> str:
    return FAMILIES[family]['prefix'] + format(number, '02d') + '.xml'


def _number(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= 9:
        raise ThermostatTemplateError('Template number must be an integer in 1..9')
    return value


def _byte_span(parameter) -> set[int]:
    kind, count = parameter.type, parameter.array_size
    address, bits = parameter.address, parameter.bit_size
    if kind == 'bit':
        offset = _integer(parameter.fields.get('BitAddress') or '0')
        return set(range(address, address + (offset + count - 1) // 8 + 1))
    if kind in ('int', 'long'):
        width, skip = max(1, bits // 8), _integer(parameter.fields.get('ArraySkip') or '0')
        return {address + index * width * (skip + 1) + byte
                for index in range(count) for byte in range(width)}
    if kind == 'string':
        return set(range(address, address + count))
    if kind == 'sixbit':
        return set(range(address, address + 6))
    raise ThermostatTemplateError('Unsupported parameter type in thermostat unit specification')


def _native_integer(text: Any, name: str) -> int:
    if type(text) is not str or re.fullmatch(r'0x[0-9a-fA-F]{1,2}|[0-9]{1,3}', text.strip()) is None:
        raise ThermostatTemplateError('Native parameter is not one byte integer: ' + name)
    value = int(text.strip(), 0)
    if value > 255:
        raise ThermostatTemplateError('Native parameter exceeds one byte: ' + name)
    return value


@dataclass(frozen=True)
class ThermostatTemplate:
    family: str
    number: int
    filename: str
    sha256: str  # SHA-256 over the included source bytes followed by this file
    description: str
    min_version: str
    max_version: str
    values: tuple[tuple[str, int], ...]

    def as_dict(self):
        return {'family': self.family, 'number': self.number, 'filename': self.filename,
                'specification_sha256': self.sha256, 'specification_description': self.description,
                'minimum_version': self.min_version, 'maximum_version': self.max_version,
                'parameter_count': len(self.values),
                'values': {name: value for name, value in self.values}}


class ThermostatTemplateCatalog:
    """Validate original template specifications from a private directory."""

    def __init__(self, directory):
        if directory is None:
            raise ThermostatTemplateError('Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications')
        self.store = UnitSpecStore(directory)
        self._cache: dict[tuple[str, int], ThermostatTemplate] = {}

    def load(self, family: str, number: int) -> ThermostatTemplate:
        if family not in FAMILIES:
            raise ThermostatTemplateError('Unknown thermostat template family')
        number = _number(number)
        if number not in FAMILIES[family]['offered']:
            raise ThermostatTemplateError(
                'Template ' + str(number) + ' is not offered by the original Toolkit for '
                + '/'.join(FAMILIES[family]['unit_types']) + ' units')
        key = (family, number)
        if key in self._cache:
            return self._cache[key]
        filename = template_filename(family, number)
        try:
            data = self.store._path(filename).read_bytes()
            spec = self.store.load(filename)
            unit = self.store.load(FAMILIES[family]['unit_spec'])
        except UnitSpecError as error:
            raise ThermostatTemplateError(str(error)) from error
        # Each THERMOSTATA template includes the same-numbered THERMOSTAT
        # template and then overrides/extends it; basic templates stand alone.
        sources = ((filename,) if family == 'basic'
                   else (template_filename('basic', number), filename))
        if spec.unit_type != FAMILIES[family]['spec_type'] or spec.sources != sources:
            raise ThermostatTemplateError('Template specification type or include set is not the original form: ' + filename)
        if len(sources) == 2:
            data = self.store._path(sources[0]).read_bytes() + data
        used = {}
        for name, parameter in unit.parameters.items():
            for byte in _byte_span(parameter):
                used.setdefault(byte, []).append(name)
        values = []
        for name, parameter in spec.parameters.items():
            target = unit.parameters.get(name)
            if (parameter.type != 'int' or parameter.array_size != 1 or parameter.bit_size != 8
                    or parameter.fields.get('BitAddress') or parameter.default is None):
                raise ThermostatTemplateError('Template parameter is not one declared byte with a default: ' + name)
            if (target is None or target.type != 'int' or target.array_size != 1 or target.bit_size != 8
                    or target.fields.get('BitAddress') or target.address != parameter.address):
                raise ThermostatTemplateError('Template parameter does not match the unit specification: ' + name)
            if used.get(parameter.address) != [name]:
                raise ThermostatTemplateError('Template byte aliases another unit parameter: ' + name)
            own = parameter.validate_value(parameter.default)
            checked = target.validate_value(parameter.default)
            if not own['valid'] or not checked['valid']:
                raise ThermostatTemplateError('Template default is outside the declared range: ' + name)
            values.append((name, checked['parsed']))
        if not values:
            raise ThermostatTemplateError('Template specification declares no parameters')
        template = ThermostatTemplate(family, number, filename, _sha(data),
                                      spec.metadata.get('Description', '').strip(),
                                      spec.metadata.get('MinVersion', '').strip(),
                                      spec.metadata.get('MaxVersion', '').strip(), tuple(values))
        self._cache[key] = template
        return template

    def listing(self, family: str | None = None):
        families = FAMILIES if family is None else {family: FAMILIES[family]}
        rows = []
        for name, record in families.items():
            for number in range(1, 10):
                row = {'family': name, 'unit_types': list(record['unit_types']), 'number': number,
                       'filename': template_filename(name, number),
                       'offered_by_original': number in record['offered']}
                if row['offered_by_original']:
                    template = self.load(name, number)
                    row.update(specification_sha256=template.sha256,
                               specification_description=template.description,
                               parameter_count=len(template.values),
                               firmware_range=[template.min_version, template.max_version])
                else:
                    row['refusal'] = 'Installation is listed only for TProgrammableThermostat units'
                rows.append(row)
        return rows


@dataclass(frozen=True)
class TemplateOverlay:
    template: ThermostatTemplate
    unit_type: str
    firmware: str
    before: tuple[tuple[str, str], ...]
    changes: tuple[tuple[str, int, int], ...]
    post_load: PostLoadReplay | None = None
    groups: tuple[tuple[int, str], ...] = ()
    application: int | None = None

    @property
    def overlay(self) -> dict[str, int]:
        return dict(self.template.values)

    @property
    def expected(self) -> dict[str, int]:
        result = dict(self.template.values)
        if self.post_load is not None:
            result.update(self.post_load.expected)
        return result

    @property
    def post_load_changes(self) -> dict[str, int]:
        overlay = {**{n: _safe_int(v) for n, v in self.before}, **self.overlay}
        if self.post_load is None:
            return {}
        return {n: v for n, v in self.post_load.expected.items() if overlay.get(n) != v}

    @property
    def would_mutate(self) -> bool:
        return bool(self.changes or (self.post_load is not None and self.post_load.group_operations))

    def as_dict(self):
        template_names = set(self.expected)
        result = {'template': self.template.as_dict(), 'unit_type': self.unit_type, 'firmware': self.firmware,
                  'changed_parameters': [{'name': n, 'before': a, 'after': b} for n, a, b in self.changes],
                  'unchanged_template_parameters': sorted(template_names - {n for n, _a, _b in self.changes}),
                  'preserved_parameter_count': len([n for n, _ in self.before if n not in template_names]),
                  'reset_before_load': False,
                  'original_post_load_adjustments_replayed': self.post_load is not None,
                  'original_post_load_adjustments': list(ORIGINAL_POST_LOAD_ADJUSTMENTS)}
        if self.post_load is not None:
            result['post_load'] = {**self.post_load.as_dict(), 'output_application': self.application,
                                   'parameters_changed_after_overlay': self.post_load_changes,
                                   'untouched_field_normalization_replayed': False}
        return result


def plan_overlay(template: ThermostatTemplate, unit_type: str, firmware: str,
                 snapshot: Mapping[str, str], *, groups: Mapping[int, str] | None = None,
                 application: int | None = None, group_sort: str | None = None) -> TemplateOverlay:
    """Plan the byte overlay of one template onto a complete PP snapshot.

    With ``groups`` (the output application's address -> tag inventory) the
    original post-load pipeline and form save are replayed as well.
    """
    try:
        validate_group_sort(group_sort, post_load=groups is not None)
    except ThermostatPostLoadError as error:
        raise ThermostatTemplateError(str(error)) from error
    if group_sort is not None and application in (172, 203):
        raise ThermostatTemplateError('Explicit group sort excludes zone/remote applications 172 and 203; '
                                      'their other form-load group effects are not replayed')
    if family_for_unit_type(unit_type) != template.family:
        raise ThermostatTemplateError(template.filename + ' is not compatible with unit type ' + unit_type)
    if type(firmware) is not str or not firmware.strip():
        raise ThermostatTemplateError('Unit firmware version is required')
    try:
        compatible = version_matches(firmware, template.min_version, template.max_version)
    except UnitSpecError as error:
        raise ThermostatTemplateError(str(error)) from error
    if not compatible:
        raise ThermostatTemplateError('Firmware ' + firmware + ' is outside the template range')
    if not isinstance(snapshot, Mapping) or any(type(k) is not str or type(v) is not str
                                                 for k, v in snapshot.items()):
        raise ThermostatTemplateError('Snapshot must map parameter names to native value text')
    for name, _value in template.values:
        if name not in snapshot:
            raise ThermostatTemplateError('Unit snapshot lacks template parameter: ' + name)
    replay = None
    if groups is not None:
        loaded = {n: _safe_int(v) for n, v in snapshot.items()}
        loaded.update(template.values)
        try:
            replay = replay_post_load({n: v for n, v in loaded.items() if v is not None},
                                      template.family, template.number, groups, group_sort=group_sort)
        except (ThermostatPostLoadError, KeyError) as error:
            raise ThermostatTemplateError('Original post-load replay is outside its precondition: '
                                          + str(error)) from error
    expected = dict(template.values)
    if replay is not None:
        expected.update(replay.expected)
    changes = []
    for name, value in sorted(expected.items()):
        if name not in snapshot:
            raise ThermostatTemplateError('Unit snapshot lacks replayed parameter: ' + name)
        current = _native_integer(snapshot[name], name)
        if current != value:
            changes.append((name, current, value))
    return TemplateOverlay(template, unit_type, firmware, tuple(sorted(snapshot.items())), tuple(changes),
                           replay, tuple(sorted((groups or {}).items())), application)


def compare_overlay(overlay: TemplateOverlay, actual: Mapping[str, str], *,
                    overlay_only: bool = False) -> dict[str, list[str]]:
    """Return template mismatches and non-template changes in an observed snapshot."""
    expected = overlay.overlay if overlay_only else overlay.expected
    before = dict(overlay.before)
    mismatched = sorted(name for name, value in expected.items()
                        if name not in actual or _safe_int(actual[name]) != value)
    changed = sorted(name for name in set(before) | set(actual)
                     if name not in expected and before.get(name) != actual.get(name))
    return {'template_mismatches': mismatched, 'unrelated_changes': changed}


def _safe_int(text):
    try:
        return _native_integer(text, '')
    except ThermostatTemplateError:
        return None


def _children(node, name=None):
    return [c for c in node.childNodes if c.nodeType == Node.ELEMENT_NODE and (name is None or c.tagName == name)]


def _field(node, name, *, optional=False):
    rows = _children(node, name)
    if optional and not rows:
        return None
    if len(rows) != 1 or any(c.nodeType not in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE) for c in rows[0].childNodes):
        raise ThermostatTemplateError('Expected one scalar native unit field: ' + name)
    return ''.join(c.data for c in rows[0].childNodes)


def _shape(node):
    if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
        return ('text', node.data.strip())
    if node.nodeType == Node.COMMENT_NODE:
        return ('comment', node.data)
    attrs = sorted((node.attributes.item(i).name, node.attributes.item(i).value)
                   for i in range(node.attributes.length))
    return (node.tagName, attrs, [_shape(c) for c in node.childNodes
                                  if not (c.nodeType == Node.TEXT_NODE and not c.data.strip())])


def _unit_record(text, address):
    root = _document(text).documentElement
    if _field(root, 'Address') != str(address):
        raise ThermostatTemplateError('Native unit address differs from the requested path')
    identity = {name: _field(root, name, optional=name == 'CatalogNumber')
                for name in ('OID', 'UnitType', 'FirmwareVersion', 'CatalogNumber')}
    stored, other = {}, []
    for child in _children(root):
        if child.tagName == 'PP' and child.hasAttribute('Name'):
            name = child.getAttribute('Name')
            if name in stored:
                raise ThermostatTemplateError('Duplicate stored native parameter: ' + name)
            stored[name] = _json(_shape(child))
        else:
            other.append(_shape(child))
    root_attrs = sorted((root.attributes.item(i).name, root.attributes.item(i).value)
                        for i in range(root.attributes.length))
    return identity, _json((root_attrs, other)), stored


@dataclass(frozen=True)
class NativeTemplatePlan:
    path: str
    project: str
    network: str
    overlay: TemplateOverlay
    unit_xml: str
    identity: tuple[tuple[str, Any], ...]
    networks: tuple[str, ...]

    def as_dict(self):
        return {'format': 'cbus-native-thermostat-template-plan-v1', 'path': self.path,
                'identity': dict(self.identity), 'unit_xml_sha256': _sha(self.unit_xml.encode('utf-8')),
                **self.overlay.as_dict(), 'closed_networks': list(self.networks),
                'apply_would_mutate': self.overlay.would_mutate,
                'native_load_command': 'PP LOAD_FROM_FILE <session> ' + self.overlay.template.filename,
                'caller_exclusive_project_required': True, 'server_edit_lock_acquired': False,
                'physical_device_programmed': False, 'original_ui_workflow_executed': False}


class NativeThermostatTemplateError(RuntimeError):
    def __init__(self, cause, evidence):
        self.cause = cause
        self.details = {'thermostat_template_evidence': evidence}
        super().__init__('Thermostat template stopped: ' + _error(cause)['message'])


class NativeThermostatTemplates:
    """Plan and apply one original thermostat template to a closed database unit."""

    def __init__(self, client, catalog: ThermostatTemplateCatalog):
        if not isinstance(catalog, ThermostatTemplateCatalog):
            raise TypeError('catalog must be a ThermostatTemplateCatalog')
        self.client, self.catalog = client, catalog
        self.database, self.projects = NativeDatabase(client), NativeProjects(client)
        self.programmer, self.network_guard = Programmer(client), NetworkAddressing(client)
        self._plans: dict[int, str] = {}
        self._consumed: set[int] = set()
        self.last_evidence = None

    def _start(self, operation):
        self.last_evidence = {
            'format': 'cbus-native-thermostat-template-result-v1', 'operation': operation,
            'state': 'preconditions', 'complete': False, 'backup_project': None,
            'backup_created': False, 'staged_verified': False, 'pp_save_attempted': False,
            'pp_save_confirmed': False, 'target_save_attempted': False, 'target_save_confirmed': False,
            'outcome_uncertain': False, 'persistence_verified': False,
            'unrelated_parameters_preserved': False, 'unit_record_preserved': False,
            'automatic_retries': 0, 'rollback_performed': False,
            'original_post_load_adjustments_replayed': False, 'physical_device_programmed': False,
            'group_operations_confirmed': [],
            'caller_exclusive_project_required': True, 'server_edit_lock_acquired': False}

    def _fail(self, error):
        evidence = self.last_evidence
        uncertain = ((evidence['pp_save_attempted'] and not evidence['pp_save_confirmed'])
                     or (evidence['target_save_attempted'] and not evidence['target_save_confirmed']))
        evidence.update(complete=False, error=_error(error), outcome_uncertain=uncertain,
                        state='uncertain' if uncertain or evidence['pp_save_confirmed'] else 'stopped')
        for name in ('programming_cleanup_errors', 'cgate_cleanup_errors'):
            items = getattr(error, name, ())
            if items:
                evidence[name] = [_error(item) for item in items]
        if not isinstance(error, Exception):
            try:
                error.thermostat_template_evidence = evidence
            except BaseException:
                pass
            raise error
        raise NativeThermostatTemplateError(error, evidence) from error

    def _xml(self, path):
        response = self.database.get(path, xml=True)
        if response.code != 344:
            raise RuntimeError('Native XML response did not complete')
        return xml_text(response)

    def _operation(self, action, name, other=None):
        response = self.projects.operation(action, name, other)
        if response.code != 200 or len(response.lines) != 1:
            raise RuntimeError('Native project ' + action + ' did not return one completion')
        return response

    def _networks(self, project):
        root = _container(self._xml('//' + project), 'Installation').documentElement
        projects = _children(root, 'Project')
        if len(projects) != 1:
            raise ThermostatTemplateError('Expected exactly one native Project')
        paths = ['//' + project + '/' + _field(node, 'Address') for node in _children(projects[0], 'Network')]
        if not paths or len(paths) != len(set(paths)):
            raise ThermostatTemplateError('Project must have unique loaded networks')
        for path in paths:
            runtime = dict(self.network_guard._runtime(path))
            if any(runtime.get(k) != v for k, v in (('InterfaceState', 'closed'),
                                                    ('TargetInterfaceState', 'closed'), ('SyncState', 'idle'))):
                raise ThermostatTemplateError('Every project network must be closed with synchronization idle')
        return tuple(sorted(paths))

    def _session(self, plan_path, network):
        return self.programmer.load(network, '/db' + plan_path)

    def _read(self, path, network, address):
        text = self._xml(path)
        identity, _shape_json, _stored = _unit_record(text, address)
        with self._session(path, network) as session:
            values = session.values()
        if self._xml(path) != text:
            raise ThermostatTemplateError('Read-only PP session changed database XML; save/reload it and plan again')
        return text, identity, values

    def _output_groups(self, network, values):
        # Thermostat AfterLoad sets TCBUSUnit.ApplicationObject from the scalar
        # ApplicationNumber. The plant getters use that object through VMT
        # +0xb0; the generic Application array does not select these groups.
        application = _native_integer(values.get('ApplicationNumber'), 'ApplicationNumber')
        text = self._xml(network)
        root = _container(text, 'Network').documentElement
        matches = [node for node in _children(root, 'Application') if _field(node, 'Address') == str(application)]
        if len(matches) != 1:
            raise ThermostatTemplateError('Output ApplicationNumber ' + str(application)
                                          + ' is absent from the network')
        groups = {}
        for node in _children(matches[0], 'Group'):
            address = int(_field(node, 'Address'))
            if address in groups:
                raise ThermostatTemplateError('Duplicate output group address')
            groups[address] = _field(node, 'TagName')
        return application, groups

    def plan(self, path, number, *, exclusive_project=False, post_load=True, group_sort=None):
        self._start('plan')
        try:
            try:
                validate_group_sort(group_sort, post_load=post_load)
            except ThermostatPostLoadError as error:
                raise ThermostatTemplateError(str(error)) from error
            path, project, network_address, address = _path(path)
            network = '//' + project + '/' + str(network_address)
            if exclusive_project is not True:
                raise ThermostatTemplateError('Caller must exclusively own project editing/reloading')
            if len(self._plans) >= 16:
                raise ThermostatTemplateError('Use a new manager after sixteen issued plans')
            self._operation('use', project)
            networks = self._networks(project)
            if network not in networks:
                raise ThermostatTemplateError('Unit network is absent from the closed project inventory')
            text, identity, values = self._read(path, network, address)
            template = self.catalog.load(family_for_unit_type(identity['UnitType']), _number(number))
            groups = application = None
            if post_load:
                application, groups = self._output_groups(network, values)
            overlay = plan_overlay(template, identity['UnitType'], identity['FirmwareVersion'], values,
                                   groups=groups, application=application, group_sort=group_sort)
            plan = NativeTemplatePlan(path, project, network, overlay, text,
                                      tuple(sorted(identity.items())), networks)
            self._plans[id(plan)] = repr(plan)
            self.last_evidence.update(state='planned', complete=True, plan=plan.as_dict())
            return plan
        except BaseException as error:
            self._fail(error)

    def _fresh(self, plan):
        if self._networks(plan.project) != plan.networks:
            raise ThermostatTemplateError('Project network inventory changed since planning')
        address = int(plan.path.rsplit('/', 1)[1])
        text, _identity, values = self._read(plan.path, plan.network, address)
        if text != plan.unit_xml or tuple(sorted(values.items())) != plan.overlay.before:
            raise ThermostatTemplateError('Unit record or PP parameters changed since planning')
        if plan.overlay.post_load is not None:
            _application, groups = self._output_groups(plan.network, values)
            if tuple(sorted(groups.items())) != plan.overlay.groups:
                raise ThermostatTemplateError('Output application groups changed since planning')

    def apply(self, plan, *, backup_project=None):
        self._start('apply')
        try:
            if type(plan) is not NativeTemplatePlan or self._plans.get(id(plan)) != repr(plan):
                raise ThermostatTemplateError('Use an unchanged plan issued by this manager')
            if id(plan) in self._consumed:
                raise ThermostatTemplateError('This plan already had an apply attempt; review a fresh plan')
            backup = _project(backup_project) if backup_project is not None else 'B' + uuid4().hex[:7].upper()
            if backup.upper() == plan.project.upper():
                raise ThermostatTemplateError('Backup project must differ from the edited project')
            self._consumed.add(id(plan))
            overlay = plan.overlay
            self.last_evidence.update(original_post_load_adjustments_replayed=overlay.post_load is not None)
            self.last_evidence.update(path=plan.path, template=overlay.template.filename,
                                      template_sha256=overlay.template.sha256, backup_project=backup,
                                      changed_parameters=[n for n, _a, _b in overlay.changes])
            self._operation('use', plan.project)
            self._fresh(plan)
            if not overlay.would_mutate:
                self.last_evidence.update(state='already_applied', complete=True, backup_project=None)
                return self.last_evidence
            self.last_evidence['state'] = 'backup'
            self._operation('save', plan.project)
            self._operation('copy', plan.project, backup)
            self.last_evidence['backup_created'] = True
            self._operation('use', plan.project)
            self._fresh(plan)
            self.last_evidence['state'] = 'staging'
            with self._session(plan.path, plan.network) as session:
                if tuple(sorted(session.values().items())) != overlay.before:
                    raise ThermostatTemplateError('Unit changed immediately before staging')
                reply = session.load_from_file(overlay.template.filename, overlay=True)
                if getattr(reply, 'code', None) != 200:
                    raise RuntimeError('PP LOAD_FROM_FILE did not complete')
                staged = compare_overlay(overlay, session.values(), overlay_only=True)
                self.last_evidence['staged_comparison'] = staged
                if staged['template_mismatches'] or staged['unrelated_changes']:
                    raise ThermostatTemplateError('Staged native overlay differs from the independent plan; not saved')
                if overlay.post_load is not None:
                    for name, value in sorted(overlay.post_load_changes.items()):
                        reply = session.set(name, str(value))
                        if getattr(reply, 'code', None) != 200:
                            raise RuntimeError('PP SET for the post-load replay did not complete')
                    staged = compare_overlay(overlay, session.values())
                    self.last_evidence['staged_post_load_comparison'] = staged
                    if staged['template_mismatches'] or staged['unrelated_changes']:
                        raise ThermostatTemplateError('Staged post-load replay differs from the plan; not saved')
                    self._group_operations(plan)
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
            self._verify(plan)
            self.last_evidence.update(state='verified_saved', complete=True, persistence_verified=True)
            return self.last_evidence
        except BaseException as error:
            self._fail(error)

    def _group_operations(self, plan):
        base = plan.network + '/' + str(plan.overlay.application)
        done = self.last_evidence.setdefault('group_operations_confirmed', [])
        for operation in plan.overlay.post_load.group_operations:
            self.last_evidence['group_operation_attempted'] = operation.as_dict()
            if operation.action == 'create':
                self.database.add(base, 'group', operation.address, operation.tag)
            else:
                self.database.set(base + '/' + str(operation.address) + '/TagName', operation.tag)
            done.append(operation.as_dict())
        self.last_evidence.pop('group_operation_attempted', None)

    def _verify(self, plan):
        if self._networks(plan.project) != plan.networks:
            raise ThermostatTemplateError('Project networks changed after save/reload')
        address = int(plan.path.rsplit('/', 1)[1])
        text, identity, values = self._read(plan.path, plan.network, address)
        before_identity, before_shape, before_stored = _unit_record(plan.unit_xml, address)
        _identity, after_shape, after_stored = _unit_record(text, address)
        names = set(plan.overlay.expected)
        record_preserved = (identity == before_identity and after_shape == before_shape
                            and {k: v for k, v in after_stored.items() if k not in names}
                            == {k: v for k, v in before_stored.items() if k not in names})
        comparison = compare_overlay(plan.overlay, values)
        self.last_evidence.update(reloaded_comparison=comparison, unit_record_preserved=record_preserved,
                                  unrelated_parameters_preserved=not comparison['unrelated_changes'])
        if comparison['template_mismatches'] or comparison['unrelated_changes'] or not record_preserved:
            raise ThermostatTemplateError('Saved/reloaded unit differs from the planned overlay')
        if plan.overlay.post_load is not None:
            expected = dict(plan.overlay.groups)
            for operation in plan.overlay.post_load.group_operations:
                expected[operation.address] = operation.tag
            _application, groups = self._output_groups(plan.network, values)
            self.last_evidence['output_groups_verified'] = groups == expected
            if groups != expected:
                raise ThermostatTemplateError('Saved/reloaded output application groups differ from the replay')


def default_spec_dir():
    import os
    value = os.environ.get('CBUS_UNITSPEC_DIR')
    return Path(value) if value else None
