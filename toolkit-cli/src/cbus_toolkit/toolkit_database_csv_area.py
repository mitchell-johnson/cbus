"""Guarded creation of the captured missing Toolkit CSV Area group."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re

from .addressing import _container, _network_canonical
from .native import NativeDatabase, NativeProjects, _project
from .toolkit_database_csv_native import (
    _children,
    _field,
    _oid,
    _one_by_address,
    _parameter,
    _path,
    _tokens,
    native_xml_reply_text,
)


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _fingerprint(network):
    return _digest(repr(_network_canonical(network.toxml())))


def _group_rows(application):
    rows = []
    for group in _children(application, 'Group'):
        rows.append((_tokens(_field(group, 'Address'), 'Group address', count=1)[0],
                     _field(group, 'TagName'), _oid(_field(group, 'OID')), group))
    if len({row[0] for row in rows}) != len(rows):
        raise ValueError('Native primary application contains duplicate group addresses')
    return rows


@dataclass(frozen=True)
class MissingAreaGroupPlan:
    unit_path: str
    project: str
    network: int
    application: int
    address: int
    tag: str
    source_xml_sha256: str
    source_network_sha256: str

    def as_dict(self):
        return {name: getattr(self, name) for name in (
            'unit_path', 'project', 'network', 'application', 'address', 'tag',
            'source_xml_sha256', 'source_network_sha256')}


@dataclass(frozen=True)
class MissingAreaGroupResult:
    plan: MissingAreaGroupPlan
    backup_project: str
    group_oid: str
    final_xml_sha256: str
    final_network_sha256: str
    final_xml: str = field(repr=False)

    def as_dict(self):
        return {**self.plan.as_dict(), 'complete': True, 'created': True,
                'backup_project': self.backup_project, 'group_oid': self.group_oid,
                'target_save_confirmed': True, 'reload_verified': True,
                'native_database_mutated': True, 'physical_device_accessed': False,
                'final_xml_sha256': self.final_xml_sha256,
                'final_network_sha256': self.final_network_sha256}


class MissingAreaGroupError(RuntimeError):
    def __init__(self, message, *, backup_project=None, mutation_attempted=False,
                 rollback_errors=()):
        self.details = {'backup_project': backup_project,
                        'mutation_attempted': mutation_attempted,
                        'rollback_errors': list(rollback_errors)}
        super().__init__(message)


def plan_missing_area_group(text, unit_path):
    """Admit exactly the archived B03 database shape before any mutation."""
    project_name, network_address, unit_address = _path(unit_path)
    root = _container(text, 'Installation').documentElement
    projects = _children(root, 'Project')
    if len(projects) != 1 or _field(projects[0], 'Address') != project_name:
        raise ValueError('Native XML must contain exactly the selected project')
    network = _one_by_address(projects[0], 'Network', network_address)
    if len(_children(network, 'Unit')) != 1 or len(_children(network, 'Application')) != 1:
        raise ValueError('Captured missing-Area profile requires one unit and one application')
    unit = _one_by_address(network, 'Unit', unit_address)
    application = _one_by_address(network, 'Application', 56)
    _oid(_field(unit, 'OID')); _oid(_field(application, 'OID'))
    if (_field(unit, 'UnitType').upper(), _field(unit, 'FirmwareVersion')) != ('RELAY4', '4.4'):
        raise ValueError('Captured missing-Area profile requires RELAY4 firmware 4.4')
    if (_field(unit, 'UnitName'), _field(unit, 'TagName'), _field(unit, 'CatalogNumber'),
            _field(unit, 'SerialNumber'), _field(application, 'TagName')) != (
            'NativeUnit', 'OwnedUnit', 'OWNED', '1.2.3', 'Lighting'):
        raise ValueError('Native scalar metadata differs from the captured missing-Area profile')
    if _tokens(_parameter(unit, 'Application'), 'Application', count=2) != (56, 255):
        raise ValueError('Captured missing-Area profile requires applications 56 and 255')
    if _tokens(_parameter(unit, 'AreaGroupAddress'), 'AreaGroupAddress', count=1) != (13,):
        raise ValueError('Captured missing-Area profile requires stored AreaGroupAddress 13')
    groups = _tokens(_parameter(unit, 'GroupAddress'), 'GroupAddress', count=16)
    if groups != (*range(1, 9), *(255 for _ in range(8))):
        raise ValueError('Captured missing-Area profile requires group addresses 1 through 8')
    rows = _group_rows(application)
    if tuple(row[0] for row in rows) != (*range(1, 9), 12, 255):
        raise ValueError('Captured missing-Area profile requires exact existing group order')
    expected_tags = {**{value: 'Group' + str(value) for value in range(1, 9)},
                     12: 'Group12', 255: '<Unused>'}
    if any(tag != expected_tags[address] for address, tag, _oid_value, _node in rows):
        raise ValueError('Existing group tags differ from the captured missing-Area profile')
    return MissingAreaGroupPlan(unit_path, project_name, network_address, 56, 13,
                                'Group 13', _digest(text), _fingerprint(network))


def _verify_added(text, plan, expected_oid=None):
    root = _container(text, 'Installation').documentElement
    project = _children(root, 'Project')
    if len(project) != 1 or _field(project[0], 'Address') != plan.project:
        raise RuntimeError('Persisted project identity differs')
    network = _one_by_address(project[0], 'Network', plan.network)
    application = _one_by_address(network, 'Application', plan.application)
    rows = _group_rows(application)
    created = [row for row in rows if row[0] == plan.address]
    if len(created) != 1 or created[0][1] != plan.tag:
        raise RuntimeError('Created Area group is absent or has different metadata')
    oid = created[0][2]
    if expected_oid is not None and oid != expected_oid:
        raise RuntimeError('Created Area group identity changed')
    final_fingerprint = _fingerprint(network)
    application.removeChild(created[0][3])
    if _fingerprint(network) != plan.source_network_sha256:
        raise RuntimeError('Area creation changed data outside the one admitted group')
    return oid, final_fingerprint


class NativeCSVAreaGroups:
    def __init__(self, client):
        self.client = client
        self.database = NativeDatabase(client)
        self.projects = NativeProjects(client)
        self.last_result = None

    def _snapshot(self, project):
        return native_xml_reply_text(self.database.get('//' + project, xml=True))

    def plan(self, unit_path):
        project, _network, _unit = _path(unit_path)
        return plan_missing_area_group(self._snapshot(project), unit_path)

    @staticmethod
    def _same_source(first, second):
        names = ('unit_path', 'project', 'network', 'application', 'address', 'tag',
                 'source_network_sha256')
        return all(getattr(first, name) == getattr(second, name) for name in names)

    def _rollback(self, plan):
        current = self._snapshot(plan.project)
        try:
            plan_missing_area_group(current, plan.unit_path)
            return
        except ValueError:
            _verify_added(current, plan)
        self.projects.operation('use', plan.project)
        self.database.delete(f'//{plan.project}/{plan.network}/{plan.application}/{plan.address}')
        self.projects.operation('save', plan.project)
        restored = plan_missing_area_group(self._snapshot(plan.project), plan.unit_path)
        if restored.source_network_sha256 != plan.source_network_sha256:
            raise RuntimeError('Area-group rollback did not restore the source network')

    def apply(self, plan, *, backup_project):
        if not isinstance(plan, MissingAreaGroupPlan):
            raise ValueError('Expected a MissingAreaGroupPlan')
        backup = _project(backup_project)
        if backup.upper() == plan.project.upper():
            raise ValueError('Backup project must differ from the edited project')
        current = self.plan(plan.unit_path)
        if not self._same_source(current, plan):
            raise ValueError('Missing-Area plan is stale or has been modified')
        try:
            self.projects.operation('save', plan.project)
            self.projects.operation('copy', plan.project, backup)
        except Exception as error:
            raise MissingAreaGroupError('Project backup failed; Area group was not created',
                                        backup_project=backup) from error
        attempted = False
        try:
            if not self._same_source(self.plan(plan.unit_path), plan):
                raise ValueError('Project changed while creating the backup')
            attempted = True
            reply = self.database.add(
                f'//{plan.project}/{plan.network}/{plan.application}', 'group',
                plan.address, plan.tag)
            identities = [match[1] for line in reply.lines
                          if (match := re.fullmatch(r'301[- ]OID=([0-9a-fA-F-]{36})', line))]
            if len(identities) != 1:
                raise RuntimeError('Created Area group did not return exactly one OID')
            oid = _oid(identities[0].lower())
            _verify_added(self._snapshot(plan.project), plan, oid)
            self.projects.operation('save', plan.project)
            self.projects.operation('close', plan.project)
            self.projects.operation('load', plan.project)
            final_xml = self._snapshot(plan.project)
            persisted_oid, final_network = _verify_added(final_xml, plan, oid)
            result = MissingAreaGroupResult(plan, backup, persisted_oid,
                                            _digest(final_xml), final_network, final_xml)
            self.last_result = result
            return result
        except Exception as error:
            rollback_errors = []
            if attempted and getattr(self.client, 'connected', None) is not False:
                try:
                    self._rollback(plan)
                except Exception as rollback:
                    rollback_errors.append(str(rollback))
            elif attempted:
                rollback_errors.append('Native connection closed; automatic rollback was not attempted')
            raise MissingAreaGroupError('Missing Area-group creation failed',
                                        backup_project=backup,
                                        mutation_attempted=attempted,
                                        rollback_errors=rollback_errors) from error
