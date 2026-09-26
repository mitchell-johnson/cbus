"""Create thermostat scheduling levels in an existing closed native NetVar.

The native workflow preserves existing level metadata and uses the original
CreateLevels model to calculate missing addresses and labels. It saves a backup
before writes and verifies the result after save/close/load. Model save locks
are not server locks; callers must exclusively own project editing/reloading.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from uuid import UUID, uuid4
from xml.dom import Node

from .addressing import NetworkAddressing, _container
from .native import NativeDatabase, NativeProjects, _project
from .programming import xml_text


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _error(error):
    try:
        message = str(error)
    except BaseException:
        message = '<unprintable>'
    return {'type': type(error).__name__, 'message': message[:2048]}


def _path(value):
    if type(value) is not str:
        raise ValueError('Expected an existing Enable Control NetVar path')
    match = re.fullmatch(r'//([A-Za-z0-9_]{1,8})/(0|[1-9][0-9]{0,2})/203/(0|[1-9][0-9]{0,2})', value)
    if match is None or int(match[2]) > 255 or int(match[3]) > 254:
        raise ValueError('Use //PROJECT/network/203/group; group must be 0..254')
    return value, match[1], '//' + match[1] + '/' + match[2], int(match[3])


def _children(node, name=None):
    return [c for c in node.childNodes if c.nodeType == Node.ELEMENT_NODE and (name is None or c.tagName == name)]


def _field(node, name):
    rows = _children(node, name)
    if len(rows) != 1 or any(c.nodeType not in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE) for c in rows[0].childNodes):
        raise ValueError('Expected one scalar native field: ' + name)
    return ''.join(c.data for c in rows[0].childNodes)


def _byte(value):
    if re.fullmatch(r'0|[1-9][0-9]{0,2}', value) is None or int(value) > 255:
        raise ValueError('Malformed native byte value')
    return int(value)


def _oid(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError('Expected a canonical native object ID')
    return value


def _shape(node, *, level=False):
    if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
        return ('text', node.data)
    if node.nodeType == Node.COMMENT_NODE:
        return ('comment', node.data)
    if node.nodeType == Node.PROCESSING_INSTRUCTION_NODE:
        return ('instruction', node.target, node.data)
    if node.nodeType != Node.ELEMENT_NODE:
        raise ValueError('Unsupported native metadata node')
    attrs = sorted((node.attributes.item(i).name, node.attributes.item(i).value) for i in range(node.attributes.length))
    children = []
    for child in node.childNodes:
        # Native save/reload materializes an empty TagsDLT on a Level. The
        # observed absent and empty forms carry the same metadata here.
        if (level and child.nodeType == Node.ELEMENT_NODE and child.tagName == 'TagsDLT'
                and not child.attributes.length and not child.childNodes):
            continue
        children.append(_shape(child))
    return (node.tagName, attrs, children)


def _group(text, expected_address):
    from .thermostat_schedule_levels import ScheduleLevel
    root = _container(text, 'NetVar').documentElement
    if _byte(_field(root, 'Address')) != expected_address:
        raise ValueError('Native NetVar address differs from the requested path')
    identity = _oid(_field(root, 'OID'))
    _field(root, 'TagName')
    nodes = _children(root, 'Level')
    if len(nodes) > 256:
        raise ValueError('Native level collection exceeds byte address space')
    levels, metadata = [], {}
    for node in nodes:
        address = _byte(_field(node, 'Address'))
        value = _byte(node.getAttribute('Value'))
        oid, tag = _oid(_field(node, 'OID')), _field(node, 'TagName')
        levels.append(ScheduleLevel(oid, address, value, tag))
        if address in metadata:
            raise ValueError('Duplicate native level address')
        metadata[address] = _json(_shape(node, level=True))
    if len({level.identity for level in levels}) != len(levels):
        raise ValueError('Duplicate native level object ID')
    attrs = sorted((root.attributes.item(i).name, root.attributes.item(i).value) for i in range(root.attributes.length))
    nonlevels = [_shape(c) for c in root.childNodes
                 if not(c.nodeType == Node.ELEMENT_NODE and c.tagName == 'Level')]
    return identity, tuple(levels), _json((attrs, nonlevels)), metadata


@dataclass(frozen=True)
class NativeSchedulePlan:
    path: str
    project: str
    network: str
    action: str
    group_oid: str
    networks: tuple[str, ...]
    before_xml: str
    group_metadata: str
    level_metadata: tuple[tuple[int, str], ...]
    initial_levels: tuple
    expected_levels: tuple
    created_addresses: tuple[int, ...]

    def as_dict(self):
        return {'format': 'cbus-native-thermostat-schedule-plan-v1', 'path': self.path,
                'action': self.action, 'group_oid': self.group_oid, 'before_xml_sha256': _hash(self.before_xml),
                'initial_levels': [level.as_dict() for level in self.initial_levels],
                'expected_levels': [level.as_dict() for level in self.expected_levels],
                'created_addresses': list(self.created_addresses), 'closed_networks': list(self.networks),
                'caller_exclusive_project_required': True, 'physical_device_programmed': False,
                'original_ui_workflow_executed': False, 'native_mutation_performed': False,
                'native_collection_order_verified': False}


@dataclass(frozen=True)
class NativeScheduleResult:
    document: str

    def as_dict(self):
        return json.loads(self.document)


class NativeScheduleError(RuntimeError):
    def __init__(self, cause, result):
        self.cause = cause
        self.result = result
        self.details = json.loads(result.document)
        super().__init__('Native thermostat scheduling stopped: ' + _error(cause)['message'])


class NativeThermostatScheduleLevels:
    def __init__(self, client):
        self.client = client
        self.database = NativeDatabase(self)
        self.projects = NativeProjects(self)
        self.network_guard = NetworkAddressing(self)
        self._plans = []
        self._plan_fingerprints = {}
        self._consumed = set()
        self._evidence = None
        self.last_result = None
        self.last_error = None
        self.last_evidence_errors = ()

    def _start(self, operation):
        self.last_result = self.last_error = None
        self.last_evidence_errors = ()
        self._evidence = {'format': 'cbus-native-thermostat-schedule-result-v1', 'operation': operation,
                          'state': 'preconditions', 'complete': False, 'commands': [], 'levels': [],
                          'backup_created': False, 'target_mutation_attempted': False,
                          'backup_source_save_attempted': False,
                          'backup_source_save_confirmed': False,
                          'backup_source_save_outcome_uncertain': False,
                          'backup_copy_attempted': False,
                          'backup_copy_outcome_uncertain': False,
                          'target_save_attempted': False, 'target_save_confirmed': False,
                          'target_save_outcome_uncertain': False,
                          'outcome_uncertain': False, 'uncertain_commands': [],
                          'persistence_verified': False, 'batch_atomic': False, 'automatic_retries': 0,
                          'physical_device_programmed': False, 'original_ui_workflow_executed': False,
                          'native_collection_order_verified': False,
                          'caller_exclusive_project_required': True, 'server_edit_lock_acquired': False}

    def command(self, command):
        row = {'command': command, 'attempted': True, 'completed': False}
        self._evidence['commands'].append(row)
        try:
            result = self.client.command(command)
            row.update(completed=True, code=getattr(result, 'code', None))
            return result
        except BaseException as error:
            row['error'] = _error(error)
            raise

    def _finish(self):
        self.last_result = NativeScheduleResult(_json(self._evidence))
        return self.last_result

    def _fail(self, error):
        self.last_error = error
        incomplete = [row.get('command', '<unknown>')
                      for row in self._evidence.get('commands', ())
                      if row.get('attempted') is True
                      and row.get('completed') is not True]
        last = incomplete[-1] if incomplete else ''
        state = self._evidence.get('state')
        backup_save_uncertain = bool(
            incomplete and state == 'backup'
            and self._evidence.get('backup_source_save_attempted')
            and not self._evidence.get('backup_source_save_confirmed')
            and last.startswith('PROJECT SAVE '))
        backup_copy_uncertain = bool(
            incomplete and state == 'backup'
            and self._evidence.get('backup_copy_attempted')
            and not self._evidence.get('backup_created')
            and last.startswith('PROJECT COPY '))
        target_save_uncertain = bool(
            incomplete and self._evidence.get('target_save_attempted')
            and not self._evidence.get('target_save_confirmed')
            and last.startswith('PROJECT SAVE '))
        mutating_reply_uncertain = bool(
            incomplete and self._evidence.get('target_mutation_attempted')
            and (last.startswith('DBADDSAFE ') or last.startswith('DBSETSAFE ')))
        outcome_uncertain = (backup_save_uncertain or backup_copy_uncertain
                             or target_save_uncertain
                             or mutating_reply_uncertain)
        self._evidence.update(
            complete=False, error=_error(error),
            state=('uncertain' if outcome_uncertain
                   or self._evidence['target_mutation_attempted']
                   or self._evidence['target_save_attempted'] else 'stopped'))
        self._evidence.update(
            outcome_uncertain=outcome_uncertain,
            uncertain_commands=incomplete,
            backup_source_save_outcome_uncertain=backup_save_uncertain,
            backup_copy_outcome_uncertain=backup_copy_uncertain,
            target_save_outcome_uncertain=target_save_uncertain)
        try:
            result = self._finish()
        except BaseException as secondary:
            self.last_evidence_errors = (*self.last_evidence_errors, secondary)
            try:
                document = json.dumps(self._evidence, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
            except BaseException as export_error:
                self.last_evidence_errors = (*self.last_evidence_errors, export_error)
                document = '{"format":"cbus-native-thermostat-schedule-result-v1","complete":false,"state":"evidence_unavailable"}'
            result = NativeScheduleResult(document)
            self.last_result = result
        if not isinstance(error, Exception):
            try:
                error.thermostat_schedule_evidence = result.as_dict()
            except BaseException:
                pass
            raise error
        try:
            wrapper = NativeScheduleError(error, result)
        except BaseException as secondary:
            self.last_evidence_errors = (*self.last_evidence_errors, secondary)
            raise error
        raise wrapper from error

    def _xml(self, path):
        response = self.database.get(path, xml=True)
        if response.code != 344:
            raise RuntimeError('Native XML response did not complete')
        return xml_text(response)

    def _operation(self, action, name, other=None):
        response = self.projects.operation(action, name, other)
        if response.code != 200 or len(response.lines) != 1:
            raise RuntimeError('Native project operation did not return a single completion')
        return response

    def _networks(self, project):
        root = _container(self._xml('//' + project), 'Installation').documentElement
        projects = _children(root, 'Project')
        if len(projects) != 1:
            raise ValueError('Expected exactly one native Project')
        paths = ['//' + project + '/' + str(_byte(_field(node, 'Address'))) for node in _children(projects[0], 'Network')]
        if not paths or len(paths) != len(set(paths)):
            raise ValueError('Project must have unique loaded networks')
        for path in paths:
            runtime = dict(self.network_guard._runtime(path))
            if any(runtime.get(name) != value for name, value in (('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle'))):
                raise ValueError('Every project network must be closed with synchronization idle')
        return tuple(sorted(paths))

    def _read(self, path):
        text = self._xml(path)
        return text, _group(text, _path(path)[3])

    def _fresh(self, plan):
        if self._networks(plan.project) != plan.networks:
            raise ValueError('Project network inventory changed since planning')
        _text, (oid, levels, metadata, level_metadata) = self._read(plan.path)
        if (oid != plan.group_oid or levels != plan.initial_levels or metadata != plan.group_metadata
                or level_metadata != dict(plan.level_metadata)):
            raise ValueError('Native NetVar or levels changed since planning')

    def plan(self, path, action, *, exclusive_project=False):
        from .thermostat_schedule_levels import ScheduleLevelsEngine
        self._start('plan')
        try:
            path, project, network, _address = _path(path)
            if action not in ('Enable', 'Disable', 'Overrd') or type(action) is not str:
                raise ValueError('Action must be Enable, Disable or Overrd')
            if exclusive_project is not True:
                raise ValueError('Caller must exclusively own project editing/reloading')
            if len(self._plans) >= 16:
                raise ValueError('Use a new manager after sixteen issued plans')
            networks = self._networks(project)
            if network not in networks:
                raise ValueError('Requested network is absent from the closed project inventory')
            text, (oid, levels, metadata, level_metadata) = self._read(path)
            engine = ScheduleLevelsEngine()
            expected = engine.create_levels(engine.load(levels), action).state.levels
            old_addresses = {level.address for level in levels}
            created = tuple(level.address for level in expected if level.address not in old_addresses)
            result = NativeSchedulePlan(path, project, network, action, oid, networks, text, metadata,
                                        tuple(level_metadata.items()), levels, expected, created)
            self._plans.append(result)
            self._plan_fingerprints[id(result)] = repr(result)
            self._evidence.update(state='planned', complete=True, plan=result.as_dict())
            self._finish()
            return result
        except BaseException as error:
            self._fail(error)

    def _issued(self, plan):
        if (type(plan) is not NativeSchedulePlan or not any(plan is value for value in self._plans)
                or self._plan_fingerprints.get(id(plan)) != repr(plan)):
            raise ValueError('Use an unchanged plan issued by this manager')

    def apply(self, plan, *, backup_project=None):
        self._start('apply')
        try:
            self._issued(plan)
            backup = _project(backup_project) if backup_project is not None else 'B' + uuid4().hex[:7].upper()
            if backup.upper() == plan.project.upper():
                raise ValueError('Backup project must differ from the edited project')
            if id(plan) in self._consumed:
                raise ValueError('This plan already had an apply attempt; review a fresh plan')
            self._consumed.add(id(plan))
            self._evidence.update(path=plan.path, action=plan.action, backup_project=backup)
            self._fresh(plan)
            if not plan.created_addresses:
                self._evidence.update(state='already_present', complete=True)
                return self._finish()
            self._evidence['state'] = 'backup'
            self._evidence['backup_source_save_attempted'] = True
            self._operation('save', plan.project)
            self._evidence['backup_source_save_confirmed'] = True
            self._evidence['backup_copy_attempted'] = True
            self._operation('copy', plan.project, backup)
            self._evidence['backup_created'] = True
            self._fresh(plan)
            # PROJECT CLOSE clears this command connection's selected tag
            # database. OID addressing requires an explicit current project,
            # even when DBADDSAFE used a fully qualified parent path.
            self._operation('use', plan.project)
            expected = {level.address: level for level in plan.expected_levels}
            known_oids = {level.identity for level in plan.initial_levels}
            created_oids = {}
            for address in plan.created_addresses:
                level = expected[address]
                row = {'address': address, 'default_tag': 'Level ' + str(address), 'tag': level.tag,
                       'create_attempted': True, 'created': False, 'value_confirmed': False, 'tag_confirmed': False}
                self._evidence['levels'].append(row)
                self._evidence.update(state='creating', target_mutation_attempted=True)
                # These steps are deliberately separate so a failed value/tag
                # update retains the issued OID and last confirmed phase.
                reply = self.command('DBADDSAFE ' + plan.path + ' Level ' + str(address) + ' ' + row['default_tag'])
                if reply.code != 301 or len(reply.lines) != 1 or not reply.lines[0].startswith('301 OID='):
                    raise RuntimeError('New level did not return exactly one object ID')
                oid = _oid(reply.lines[0][8:])
                if oid in known_oids:
                    raise RuntimeError('New level returned an existing object ID')
                known_oids.add(oid); created_oids[address] = oid; row.update(created=True, oid=oid)
                identity = self.database.get('!' + oid + '/OID')
                if identity.code != 342 or list(identity.lines) != ['342 !' + oid + '/OID=' + oid]:
                    raise RuntimeError('Created level identity could not be resolved')
                for field, value, flag in (('Value', address, 'value_confirmed'), ('TagName', level.tag, 'tag_confirmed')):
                    row['field_attempted'] = field
                    result = self.database.set('!' + oid + '/' + field, value)
                    if result.code != 200 or len(result.lines) != 1:
                        raise RuntimeError('Native level field update did not complete')
                    row[flag] = True
            self._evidence.update(state='saving', target_save_attempted=True)
            self._operation('save', plan.project)
            self._evidence['target_save_confirmed'] = True
            for action in ('close', 'load'):
                self._evidence['project_operation_attempted'] = action
                self._operation(action, plan.project)
            self._verify(plan, created_oids)
            self._evidence.update(state='verified_saved', complete=True, persistence_verified=True)
            return self._finish()
        except BaseException as error:
            self._fail(error)

    def _verify(self, plan, created_oids):
        if self._networks(plan.project) != plan.networks:
            raise ValueError('Project networks changed after save/reload')
        _text, (oid, levels, metadata, level_metadata) = self._read(plan.path)
        if oid != plan.group_oid or metadata != plan.group_metadata:
            raise ValueError('Native NetVar identity or metadata changed')
        actual = {level.address: level for level in levels}
        expected = {level.address: level for level in plan.expected_levels}
        if set(actual) != set(expected):
            raise ValueError('Saved level address membership differs')
        for address, level in expected.items():
            value = actual[address]
            identity = created_oids.get(address, level.identity)
            if (value.identity, value.address, value.value, value.tag) != (identity, address, level.value, level.tag):
                raise ValueError('Saved level identity/value/tag differs at address ' + str(address))
        if any(level_metadata[address] != saved for address, saved in plan.level_metadata):
            raise ValueError('Existing level metadata changed')
        self._evidence['verified_levels'] = [level.as_dict() for level in levels]
        self._evidence['existing_metadata_preserved'] = True
