"""Verified, non-atomic Global Programming for existing closed database units.

The caller must exclusively own project editing/reloading for this operation.
That prerequisite is not a claim that the server's global sessions were proven
exclusive. No network is opened and no physical or label save is available.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import re
from uuid import UUID, uuid4
from xml.dom import Node

from .addressing import _container, NetworkAddressing
from .classic_replacement import _document, _path
from .edlt import EdltError
from .edlt_global_programming import (EdltGlobalProgramming, GlobalMerge, GlobalPayload,
    _Origin, _issue, _issued, _hash, _json, _values, _scope, _payload_native_value)
from .native import NativeDatabase, NativeProjects, _project
from .programming import Programmer, xml_text


def _error_text(error):
    try: return str(error)[:2048]
    except BaseException: return '<unprintable ' + type(error).__name__ + '>'


def _field(root, name):
    rows = [c for c in root.childNodes if c.nodeType == Node.ELEMENT_NODE and c.tagName == name]
    if len(rows) != 1 or any(c.nodeType not in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE) for c in rows[0].childNodes):
        raise EdltError('Expected one scalar native database field: ' + name)
    return ''.join(c.data for c in rows[0].childNodes)


def _shape(node, *, parameter=False):
    if node.nodeType == Node.ELEMENT_NODE:
        attrs = sorted((node.attributes.item(i).name, node.attributes.item(i).value)
                       for i in range(node.attributes.length)
                       if not(parameter and node.attributes.item(i).name == 'Value'))
        return (node.tagName, attrs, [_shape(c) for c in node.childNodes
                if not(c.nodeType == Node.TEXT_NODE and not c.data.strip())])
    if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE): return ('text', node.data)
    if node.nodeType == Node.COMMENT_NODE: return ('comment', node.data)
    if node.nodeType == Node.PROCESSING_INSTRUCTION_NODE: return ('instruction', node.target, node.data)
    raise EdltError('Unsupported native metadata node')


def _metadata(text):
    root = _document(text).documentElement
    return _json((root.tagName, sorted((root.attributes.item(i).name, root.attributes.item(i).value)
        for i in range(root.attributes.length)), sorted((_shape(c, parameter=c.nodeType == Node.ELEMENT_NODE and c.tagName == 'PP') for c in root.childNodes
        if not(c.nodeType == Node.TEXT_NODE and not c.data.strip())), key=repr)))


def _success(reply, operation):
    if (type(getattr(reply, 'code', None)) is not int or reply.code != 200 or
            len(getattr(reply, 'lines', ())) != 1 or re.fullmatch(r'200 [^\r\n]*', reply.lines[0]) is None):
        raise EdltError(operation + ' did not return an exact native200 completion')
    return reply


class NativeGlobalProgrammingError(RuntimeError):
    def __init__(self, cause, evidence):
        self.cause = cause
        self.edlt_global_programming_evidence = evidence
        self.details = evidence
        for name in ('cgate_cleanup_errors', 'programming_cleanup_errors'):
            try:
                value = getattr(cause, name, None)
                if value is not None: setattr(self, name, value)
            except BaseException: pass
        super().__init__('Global Programming stopped; inspect retained target outcomes: ' + _error_text(cause))


class _GuardedClient:
    def __init__(self, client): self.client = client
    def __getattr__(self, name): return getattr(self.client, name)
    def abort(self, original):
        try: self.client.close()
        except BaseException as secondary:
            try:
                previous = tuple(getattr(original, 'cgate_cleanup_errors', ()))
                original.cgate_cleanup_errors = (*previous, secondary)
            except BaseException: pass
    def command(self, *args, **kwargs):
        try: return self.client.command(*args, **kwargs)
        except BaseException as error:
            if not isinstance(error, Exception): self.abort(error)
            raise


@dataclass(frozen=True)
class NativeGlobalTarget:
    path: str
    oid: str
    xml: str
    metadata: str
    merge: GlobalMerge
    raw_before: bytes
    raw_expected: bytes
    crc_expected: bytes

    def as_dict(self):
        return {'path': self.path, 'oid': self.oid, 'xml_hash': _hash(self.xml),
            'metadata_hash': _hash(self.metadata), 'expected': _values(self.merge.expected),
            'final': _values(self.merge.final),
            'forced_unchanged_parameters': [k for k, v in self.merge.payload.ordered_payload if self.merge.expected[k] == v],
            'raw_before_hex': self.raw_before.hex(), 'raw_expected_hex': self.raw_expected.hex(),
            'crc_expected_hex': self.crc_expected.hex()}


@dataclass(frozen=True)
class NativeGlobalPlan:
    project: str
    payload: GlobalPayload
    targets: tuple[NativeGlobalTarget, ...]
    networks: tuple[str, ...]
    source_database: str | None
    source_xml: str | None
    _origin: _Origin = field(repr=False, compare=False)

    def as_dict(self):
        return {'format': 'cbus-native-edlt-global-plan-v1', **_scope(self.payload.source), 'project': self.project,
            'payload': self.payload.as_dict(), 'targets': [t.as_dict() for t in self.targets],
            'closed_networks': list(self.networks), 'source_database': self.source_database,
            'source_xml_hash': None if self.source_xml is None else _hash(self.source_xml),
            'caller_exclusive_project_required': True, 'global_session_exclusivity_verified': False,
            'batch_atomic': False, 'target_saved': False, 'automatic_retries': 0}


@dataclass(frozen=True)
class NativeGlobalResult:
    document: str
    def as_dict(self): return json.loads(self.document)


NativeGlobalVerification = NativeGlobalResult


class NativeEdltGlobalProgramming:
    def __init__(self, client, spec):
        self.client, self._io = client, _GuardedClient(client)
        self.engine = EdltGlobalProgramming(spec)
        self.database, self.projects, self.programmer = NativeDatabase(self._io), NativeProjects(self._io), Programmer(self._io)
        self._network_guard = NetworkAddressing(self._io)
        self._owner = object()
        self.last_evidence = None

    def _start(self, operation):
        self.last_evidence = {'format': 'cbus-native-edlt-global-result-v1', **_scope(),
            'operation': operation, 'state': 'preconditions', 'complete': False,
            'backup_project': None, 'backup_created': False, 'target_save_attempted': False,
            'targets': [], 'batch_atomic': False, 'automatic_retries': 0,
            'caller_exclusive_project_required': True, 'global_session_exclusivity_verified': False}

    def _fail(self, error):
        evidence = self.last_evidence
        evidence.update(complete=False, state='uncertain' if evidence['target_save_attempted'] or evidence['operation'] == 'verify' else 'stopped',
                        cause={'type': type(error).__name__, 'message': _error_text(error)})
        for name in ('cgate_cleanup_errors', 'programming_cleanup_errors'):
            try:
                items = getattr(error, name, ())
                if items: evidence[name] = [{'type': type(item).__name__, 'message': _error_text(item)} for item in items]
            except BaseException: evidence[name] = [{'message': 'Cleanup evidence could not be rendered'}]
        if not isinstance(error, Exception):
            try: error.edlt_global_programming_evidence = evidence
            except BaseException: pass
            raise error
        raise NativeGlobalProgrammingError(error, evidence) from error

    def _xml(self, path): return xml_text(self.database.get(path, xml=True))

    def _project_operation(self, operation, project, other=None):
        return _success(self.projects.operation(operation, project, other), 'PROJECT ' + operation.upper())

    @contextmanager
    def _session(self, path):
        with self.programmer.load(path.rsplit('/p/', 1)[0], '/db' + path) as session:
            try: yield session
            except BaseException as error:
                if not isinstance(error, Exception): self._io.abort(error)
                raise

    def _networks(self, project):
        root = _container(self._xml('//' + project), 'Installation').documentElement
        projects = [node for node in root.childNodes if node.nodeType == Node.ELEMENT_NODE and node.tagName == 'Project']
        if len(projects) != 1: raise EdltError('Expected one native Project under Installation')
        result = []
        for node in projects[0].childNodes:
            if node.nodeType != Node.ELEMENT_NODE or node.tagName != 'Network': continue
            number = _field(node, 'Address')
            if not re.fullmatch(r'0|[1-9][0-9]{0,2}', number) or int(number) > 255:
                raise EdltError('Project has a malformed network address')
            result.append('//' + project + '/' + number)
        if not result or len(result) != len(set(result)):
            raise EdltError('Project must have unique explicitly loaded closed networks')
        for network in result:
            runtime = dict(self._network_guard._runtime(network))
            if any(runtime[name] != value for name, value in (('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle'))):
                raise EdltError('Global Programming requires every project network closed and synchronization idle')
        return tuple(result)

    def _raw(self, session, start, count):
        reply = session.get_raw_data(start, count)
        match = None
        if getattr(reply, 'code', None) == 316 and len(reply.lines) == 1:
            match = re.fullmatch(r'316 RawData=([0-9a-fA-F]{' + str(count * 2) + '})', reply.lines[0])
        if match is None:
            raise EdltError('Native raw PP evidence is missing, sparse or malformed')
        return bytes.fromhex(match[1])

    def _raw_merge(self, before, payload):
        result = bytearray(before)
        for name, value in payload.ordered_payload:
            if name in ('OverallCRC', 'GlobalParameterCRC'): continue
            for edit in self.engine.codec.encode(name, value).edits:
                index = edit.address - 0x110
                if not 0 <= index < len(result): raise EdltError('Global parameter is outside the verified mask range')
                result[index] = (result[index] & ~edit.mask) | edit.value
        return bytes(result)

    def _read(self, path, payload, *, role='Destination'):
        text = self._xml(path); root = _document(text).documentElement
        _canonical, project, network, address = _path(path)
        for name, expected in (('Address', str(address)), ('UnitType', 'KEYGL5'), ('FirmwareVersion', '5.5.00'), ('CatalogNumber', '5055EDL')):
            if _field(root, name) != expected: raise EdltError('Database identity differs: ' + path + '/' + name)
        oid = _field(root, 'OID'); UUID(oid)
        tags = [c.tagName for c in root.childNodes if c.nodeType == Node.ELEMENT_NODE]
        missing = [name for name in ('DeviceName', 'GroupNumber') if tags.count(name) != 1]
        stored = [c.getAttribute('Name') for c in root.childNodes if c.nodeType == Node.ELEMENT_NODE and c.tagName == 'PP']
        if missing or len(stored) != len(set(stored)) or set(stored) != set(self.engine.spec.parameters):
            raise EdltError(role + ' requires separate native materialization before planning; save, close and reload it, then review a new plan: ' + path + '; missing fields=' + ','.join(missing))
        metadata = _metadata(text)
        stored_values = {c.getAttribute('Name'): c.getAttribute('Value') for c in root.childNodes
                         if c.nodeType == Node.ELEMENT_NODE and c.tagName == 'PP'}
        with self._session(path) as session:
            self.engine.common._verify_session(session)
            raw_values = session.values()
            factory = payload.source.factory_preparation
            if role == 'Source' and factory is not None and raw_values != dict(factory.expected_raw):
                raise EdltError('Source raw programming strings changed since factory preparation')
            before = self.engine.snapshot(raw_values)
            if self.engine.snapshot(stored_values) != before:
                raise EdltError('Stored database parameters require separate normalization/materialization; review a new plan after a deliberate save and reload: ' + path)
            if before['UnitAddress'] != (address,): raise EdltError('PP UnitAddress differs from the database target address')
            raw = self._raw(session, 0x110, 39)
        if self._xml(path) != text:
            raise EdltError('Read-only session changed database XML; materialize separately and plan again')
        merge = self.engine.merge(payload, before)
        crc = bytes(n for name in ('OverallCRC', 'GlobalParameterCRC', 'WidgetsCRC', 'StaticTextCRC', 'ScenesCheckSum') for n in merge.final[name])
        return NativeGlobalTarget(path, oid, text, metadata, merge, raw, self._raw_merge(raw, payload), crc)

    def _check_source(self, plan):
        if plan.source_database is None: return
        if self._xml(plan.source_database) != plan.source_xml:
            raise EdltError('Source database XML changed since preparation/planning')
        actual = self._read(plan.source_database, plan.payload, role='Source')
        if dict(actual.merge.expected) != dict(plan.payload.source.expected):
            raise EdltError('Source database programming changed since source preparation')
        if self._xml(plan.source_database) != plan.source_xml:
            raise EdltError('Source database XML changed during read-only source checking')

    def _valid_plan(self, plan):
        _issued(plan, NativeGlobalPlan, self._owner)
        self.engine._payload(plan.payload)
        self._factory_source_guard(plan.payload, plan.source_database)
        for target in plan.targets: self.engine._merge(target.merge)

    def _factory_source_guard(self, payload, source_database):
        factory = payload.source.factory_preparation
        if factory is not None and source_database != factory.context.source:
            raise EdltError('Factory Global Programming requires source_database to equal the exact original source path')

    def plan(self, payload, destinations, *, source_database=None, exclusive_project=False):
        self._start('plan')
        try:
            self.engine._payload(payload)
            self.last_evidence.update(_scope(payload.source))
            self._factory_source_guard(payload, source_database)
            if exclusive_project is not True: raise EdltError('Confirm caller-exclusive project editing/reloading with exclusive_project=True')
            if not isinstance(destinations, (tuple, list)) or not 1 <= len(destinations) <= 64:
                raise EdltError('Select 1..64 distinct existing database destinations')
            if any(type(path) is not str for path in destinations): raise EdltError('Database destinations must be strings')
            paths = tuple(_path(path)[0] for path in destinations)
            project = _path(paths[0])[1]
            if len({path.upper() for path in paths}) != len(paths) or any(_path(path)[1].upper() != project.upper() for path in paths):
                raise EdltError('Destinations must be distinct and belong to one project')
            source_xml = None
            if source_database is not None:
                if type(source_database) is not str: raise EdltError('Source database path must be text')
                source_database, source_project, _network, _address = _path(source_database)
                if source_project.upper() != project.upper() or source_database.upper() in {p.upper() for p in paths}:
                    raise EdltError('Source database must be a separate unit in this same project')
            self._project_operation('use', project)
            networks = self._networks(project)
            if any(path.rsplit('/p/', 1)[0].upper() not in {n.upper() for n in networks} for path in paths):
                raise EdltError('Destination network is not in the closed project inventory')
            targets = tuple(self._read(path, payload) for path in paths)
            if source_database is not None:
                source_target = self._read(source_database, payload, role='Source')
                source_xml = source_target.xml
            plan = _issue(NativeGlobalPlan(project, payload, targets, networks, source_database, source_xml, _Origin(self._owner)))
            self._check_source(plan)
            self.last_evidence.update(state='planned', complete=True, plan=plan.as_dict())
            return plan
        except BaseException as error: self._fail(error)

    def _fresh(self, plan, target):
        if self._networks(plan.project) != plan.networks: raise EdltError('Project network inventory changed')
        actual = self._read(target.path, plan.payload)
        if (actual.oid != target.oid or actual.metadata != target.metadata or
                dict(actual.merge.expected) != dict(target.merge.expected) or actual.raw_before != target.raw_before):
            raise EdltError('Destination changed since planning: ' + target.path)

    def _observe_target(self, target):
        text = self._xml(target.path)
        if _metadata(text) != target.metadata: raise EdltError('Destination metadata changed: ' + target.path)
        with self._session(target.path) as session:
            self.engine.common._verify_session(session)
            current = self.engine.snapshot(session.values())
            raw, crc = self._raw(session, 0x110, 39), self._raw(session, 0x102, 10)
        matches = current == dict(target.merge.final) and raw == target.raw_expected and crc == target.crc_expected
        return {'path': target.path, 'oid': target.oid, 'parameters_verified': current == dict(target.merge.final),
            'raw_verified': raw == target.raw_expected, 'crc_bytes_verified': crc == target.crc_expected,
            'metadata_verified': True, 'matches_expected': matches,
            'parameter_mismatches': [name for name in current if current[name] != target.merge.final[name]]}

    def apply(self, plan, *, backup_project=None):
        self._start('apply')
        try:
            self._valid_plan(plan)
            self.last_evidence.update(_scope(plan.payload.source))
            backup = _project(backup_project) if backup_project is not None else 'B' + uuid4().hex[:7].upper()
            if backup.upper() == plan.project.upper(): raise EdltError('Backup project must differ from the edited project')
            self.last_evidence.update(project=plan.project, backup_project=backup, source_hash=_hash(plan.payload.source.as_dict()),
                                      planned_destinations=[target.path for target in plan.targets])
            self._check_source(plan)
            for target in plan.targets: self._fresh(plan, target)
            self.last_evidence['state'] = 'backup'
            self._project_operation('save', plan.project)
            self._project_operation('copy', plan.project, backup)
            self.last_evidence['backup_created'] = True
            for target in plan.targets:
                self._check_source(plan)
                self._fresh(plan, target)
                row = {'path': target.path, 'state': 'staging', 'attempted_parameters': [],
                    'accepted_parameters': [], 'save_attempted': False, 'verified_saved': False}
                self.last_evidence['targets'].append(row)
                self.last_evidence['state'] = 'staging'
                with self._session(target.path) as session:
                    self.engine.common._verify_session(session)
                    if self.engine.snapshot(session.values()) != dict(target.merge.expected): raise EdltError('Destination changed immediately before staging')
                    for name, value in plan.payload.ordered_payload:
                        row['attempted_parameters'].append(name)
                        # Source/category names and numeric values were validated
                        # before I/O. Preserve the original whole-value quoting.
                        command = 'PP SET ' + session.name + ' ' + name + ' "' + _payload_native_value(plan.payload, name, value) + '"'
                        _success(self._io.command(command), 'PP SET ' + name)
                        row['accepted_parameters'].append(name)
                    if (self.engine.snapshot(session.values()) != dict(target.merge.final) or
                            self._raw(session, 0x110, 39) != target.raw_expected or self._raw(session, 0x102, 10) != target.crc_expected):
                        raise EdltError('Staged native PP values or raw bytes differ; destination was not saved')
                    if _metadata(self._xml(target.path)) != target.metadata: raise EdltError('Destination identity/metadata changed before save')
                    if self._networks(plan.project) != plan.networks: raise EdltError('Project networks changed before save')
                    row.update(state='saving', save_attempted=True)
                    self.last_evidence['target_save_attempted'] = True
                    _success(session.save_to_source(), 'PP SAVE_TO_SOURCE')
                    row['save_accepted'] = True
                for operation in ('save', 'close', 'load'):
                    row['project_operation_attempted'] = operation
                    self._project_operation(operation, plan.project)
                if self._networks(plan.project) != plan.networks: raise EdltError('Project networks changed after reload')
                observation = self._observe_target(target)
                row.update(observation)
                if not observation['matches_expected']: raise EdltError('Saved/reloaded destination differs from the planned complete merge')
                row.update(state='verified_saved', verified_saved=True, project_reloaded=True)
            self._check_source(plan)
            self.last_evidence.update(state='verified_saved', complete=True)
            return NativeGlobalResult(_json(self.last_evidence))
        except BaseException as error: self._fail(error)

    def verify(self, plan):
        """Read current database values; never save, reload a project or send PP SET."""
        self._start('verify')
        try:
            self._valid_plan(plan)
            self.last_evidence.update(_scope(plan.payload.source))
            self.last_evidence.update(project=plan.project, planned_destinations=[target.path for target in plan.targets])
            self._check_source(plan)
            if self._networks(plan.project) != plan.networks: raise EdltError('Project network inventory changed')
            for target in plan.targets: self.last_evidence['targets'].append(self._observe_target(target))
            matched = all(row['matches_expected'] for row in self.last_evidence['targets'])
            self.last_evidence.update(complete=True, matches_expected=matched, state='observed_expected' if matched else 'observed_different',
                                     project_saved=False, persistence_reverified=False)
            return NativeGlobalVerification(_json(self.last_evidence))
        except BaseException as error: self._fail(error)
