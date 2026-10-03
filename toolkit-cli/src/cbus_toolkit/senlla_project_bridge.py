"""Causal project metadata lookup/persistence for the internal SENLLA owner.

The existing project APIs perform actual file or C-Gate database operations.
They do not reproduce native transient Add/Address/Tag attribute callbacks.
Those callbacks and current native manager order require an owning provider.
"""
from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
import re

from .native import NativeDatabase, NativeProjects, _project
from .programming import xml_text
from .project import ProjectDocument, _all_elements, _elements, _field, _name, _oid
from .senlla_inputs import SENLLAInputSnapshot
from .senlla_key_events import SENLLAKeyEvents, SourceLookupRequest, _Object
from .sensors import SensorError


def _byte(value):
    if type(value) is not int or not 0 <= value <= 255:
        raise SensorError('Project source address requires an unsigned byte')
    return value


def _number(node):
    value = (_field(node, 'NetworkNumber') if _name(node) == 'Network'
             and _field(node, 'NetworkNumber') else _field(node, 'Address'))
    if not re.fullmatch(r'[0-9]{1,3}', value) or int(value) > 255:
        raise SensorError('Project entity requires its actual decimal byte address')
    return int(value)


def _unique(parent, names, address):
    rows = [node for node in _elements(parent) if _name(node) in names and _number(node) == address]
    if len(rows) > 1:
        raise SensorError('Project manager contains duplicate numeric identities')
    return rows[0] if rows else None


def _record(node):
    record = dict(kind=_name(node), address=_number(node), tag_name=_field(node, 'TagName'),
                oid=_oid(node), fields={_name(child): _field(node, _name(child))
                                      for child in _elements(node) if not _elements(child)})
    if _name(node) == 'Level':
        record['value'] = _level_value(node)
    return record


def _level_value(node):
    attribute, field = node.getAttribute('Value'), _field(node, 'Value')
    if attribute and field and attribute != field:
        raise SensorError('Actual Level contains conflicting Value representations')
    return attribute or field


def _level_integer(node):
    value = _level_value(node)
    if not re.fullmatch(r'-?[0-9]{1,10}', value) or not -(1 << 31) <= int(value) < (1 << 31):
        raise SensorError('Actual source level requires its signed Integer Value')
    return int(value)


@dataclass(frozen=True)
class MetadataCreationRequest:
    kind: str
    application: int | None
    group: int | None
    address: int
    tag_name: str
    source: str
    stage: str

    def as_dict(self):
        return dict(kind=self.kind, application=self.application, group=self.group,
                    address=self.address, tag_name=self.tag_name, source=self.source, stage=self.stage)


class MetadataOwnerRequired(SensorError):
    def __init__(self, request):
        self._request = request.as_dict()
        super().__init__('Active metadata listeners require the source construction/storage owner')

    @property
    def request(self):
        return dict(self._request)


class _DocumentBackend:
    def __init__(self, project, network, unit, storage_path):
        if not isinstance(project, ProjectDocument):
            raise SensorError('File metadata requires an actual ProjectDocument')
        self.project = project
        self.network = _byte(network)
        self.unit = _byte(unit)
        self.storage_path = Path(storage_path) if storage_path is not None else project.source
        if self.storage_path is None:
            raise SensorError('File StorageSave requires an actual destination path')
        self.project.resolve('/network/' + str(self.network) + '/unit/' + str(self.unit))

    def document(self):
        return self.project

    def add(self, kind, application, group, address, tag):
        parent = '/network/' + str(self.network)
        if application is not None:
            parent += '/application/' + str(application)
        if group is not None:
            parent += '/group/' + str(group)
        return self.project.add(kind, parent, address=address, name=tag)

    def save(self):
        self.project.save(self.storage_path)
        readback = ProjectDocument.load(self.storage_path)
        if readback.to_xml_bytes() != self.project.to_xml_bytes():
            raise SensorError('Project StorageSave readback differs from the current document')
        return {'backend': 'project_file', 'persisted': True, 'native_storage_acceptance': False}


class _NativeBackend:
    def __init__(self, database, project, network, unit):
        if not isinstance(database, NativeDatabase):
            raise SensorError('C-Gate metadata requires the actual NativeDatabase API')
        self.database = database
        self.project_name = _project(project)
        self.network = _byte(network)
        self.unit = _byte(unit)
        self.projects = NativeProjects(database.client)

    def document(self):
        text = xml_text(self.database.get('//' + self.project_name, xml=True))
        return ProjectDocument.from_bytes(text.encode('utf-8'))

    def add(self, kind, application, group, address, tag):
        parent = '//' + self.project_name + '/' + str(self.network)
        if application is not None:
            parent += '/' + str(application)
        if group is not None:
            parent += '/' + str(group)
        known = {value.lower() for node in _all_elements(self.document().project)
                 if (value := _oid(node))}
        issued = []
        def admit(response):
            from uuid import UUID
            ids = [match[1].lower() for line in response.lines
                   if (match := re.fullmatch(r'301[- ]OID=([0-9a-fA-F-]{36})', line))]
            if len(ids) != 1 or getattr(response, 'code', None) != 301:
                raise SensorError('Metadata creation did not return exactly one issued OID')
            try:
                identity = str(UUID(ids[0]))
            except ValueError:
                raise SensorError('Metadata creation returned an invalid OID') from None
            if identity in known:
                raise SensorError('Metadata creation returned an existing OID')
            issued.append(identity)
        self.database.add(parent, 'netvar' if kind == 'group' and application == 203 else kind,
                          address, tag, pre_initializer=admit)
        return {'oid': issued[0]}

    def save(self):
        self.projects.operation('save', self.project_name)
        return {'backend': 'cgate_database', 'persisted': True, 'native_storage_acceptance': False}


class SENLLAProjectBridge:
    """One actual selected project/network/unit and one SAME owning runtime.

    ``creation_dispatch(request, bridge, engine)`` executes required CURRENT
    metadata observer work, synchronously, at each causal boundary. Creation
    always requires that dispatcher: a prekey phase alone does not establish
    that the actual project manager has no listeners. It must account for native
    transient Add/Address/Tag notifications: backend readback proves storage,
    not those notifications. ``manager_order(application, rows, engine)`` must
    return the actual current native Items address order, not XML child order.
    """
    def __init__(self, backend, *, creation_dispatch=None, manager_order=None,
                 application_descriptor=None, tag_name_dispatch=None, display_text=None,
                 metadata_name=None):
        for callback in (creation_dispatch, manager_order, application_descriptor, tag_name_dispatch,
                         display_text, metadata_name):
            if callback is not None and not callable(callback):
                raise SensorError('Project source providers must be callable')
        self.backend = backend
        self.creation_dispatch = creation_dispatch
        self.manager_order = manager_order
        self.application_descriptor = application_descriptor
        self.tag_name_dispatch = tag_name_dispatch
        self.display_text_provider = display_text
        self.metadata_name_provider = metadata_name
        self.runtime = None
        self.failed = False
        self.events = []
        self._application_creating = False

    @classmethod
    def from_document(cls, project, network, unit, *, storage_path=None, **providers):
        return cls(_DocumentBackend(project, network, unit, storage_path), **providers)

    @classmethod
    def from_native(cls, database, project, network, unit, **providers):
        return cls(_NativeBackend(database, project, network, unit), **providers)

    def _nodes(self):
        document = self.backend.document()
        network = _unique(document.project, ('Network',), self.backend.network)
        if network is None:
            raise SensorError('Selected project network no longer exists')
        unit = _unique(network, ('Unit',), self.backend.unit)
        if unit is None:
            raise SensorError('Selected project Unit no longer exists')
        return document, network, unit

    def unit_record(self):
        _, _, unit = self._nodes()
        return {**_record(unit)['fields'], 'TagName': _field(unit, 'TagName'),
                'Address': _number(unit)}

    def metadata(self):
        document, _, unit = self._nodes()
        return dict(project_tag_name=_field(document.project, 'TagName'),
                    unit_address=_number(unit), unit_tag_name=_field(unit, 'TagName'))

    def bind(self, runtime, snapshot):
        if not isinstance(runtime, SENLLAKeyEvents) or not isinstance(snapshot, SENLLAInputSnapshot):
            raise SensorError('Project source binding requires its owning runtime and guarded snapshot')
        if self.runtime is not None:
            raise SensorError('Project bridge cannot bind another or replayed Unit')
        record = self.unit_record()
        identity = (record.get('UnitType'), record.get('FirmwareVersion'), record.get('CatalogNumber'))
        if identity != snapshot.identity:
            raise SensorError('Actual selected Unit identity differs from the guarded SENLLA snapshot')
        self.runtime = runtime

    def _engine(self, engine):
        if self.failed or engine is not self.runtime or engine.failed:
            raise SensorError('Project source bridge requires its uninterrupted SAME runtime')

    def _notify(self, request, engine):
        self.events.append({'operation': 'metadata_owner_boundary', **request.as_dict()})
        if self.creation_dispatch is not None:
            if self.creation_dispatch(request, self, engine) is not None:
                raise SensorError('Metadata owner must complete its actual callbacks before returning')
        else:
            raise MetadataOwnerRequired(request)

    def _name(self, engine, kind, application, address, source):
        if self.metadata_name_provider is not None:
            value = self.metadata_name_provider(kind, application, address, source, engine)
        elif kind == 'application' and self.application_descriptor is not None:
            value = self.application_descriptor(address)
        elif kind in ('application', 'group'):
            # GroupByAddress uses the CURRENT StandardApplications.GetGroupName
            # registry, not Application.GetDefaultGroupName. App titles and
            # unused/default group names also read current resource strings.
            raise SensorError('Metadata creation requires its actual current registry/resource descriptor')
        else:
            value = 'Action Selector ' + str(address)
        if type(value) is not str or not value.strip():
            raise SensorError('Source metadata descriptor requires nonempty text')
        return value

    def _find(self, kind, application, group, address):
        _, network, _ = self._nodes()
        app = _unique(network, ('Application',), address if kind == 'application' else application)
        if kind == 'application' or app is None:
            return app
        grp = _unique(app, ('Group', 'NetVar'), address if kind == 'group' else group)
        if kind == 'group' or grp is None:
            return grp
        return _unique(grp, ('Level',), address)

    def _register(self, engine, kind, application, group, address, *, value=None):
        if kind == 'application':
            return engine.add_source_application(address)
        app = engine.apps.get(application)
        if app is None:
            raise SensorError('Source metadata registration requires its already-returned application')
        if kind == 'group':
            return engine.add_source_group(app, address)
        identity = (application, group, address)
        if (application, group) not in engine.groups:
            raise SensorError('Source level registration requires its actual returned group')
        if hasattr(engine, 'add_source_level'):
            return engine.add_source_level(engine.groups[(application, group)], address, value=value)
        if identity not in engine.levels:
            engine.levels[identity] = _Object('level', identity)
        return engine.levels[identity]

    def _lookup(self, engine, kind, application, group, address, create, source):
        self._engine(engine)
        _byte(address)
        if type(create) is not bool or type(source) is not str or not source:
            raise SensorError('Source metadata lookup requires create and source position')
        self.events.append(dict(operation='actual_metadata_lookup', kind=kind, application=application,
                                group=group, address=address, create=create, source=source))
        node = self._find(kind, application, group, address)
        if node is not None:
            if kind == 'level':
                _level_integer(node)
            return self._register(engine, kind, application, group, address,
                                  value=_level_integer(node) if kind == 'level' else None)
        if not create or kind == 'application' and self._application_creating:
            return None
        tag = self._name(engine, kind, application, address, source)
        request = lambda stage: MetadataCreationRequest(kind, application, group, address, tag, source, stage)
        self._notify(request('before_backend_creation'), engine)
        if kind == 'application':
            self._application_creating = True
        try:
            # Backend Add supplies Address/Tag atomically. The source observer
            # interface must own transient notifications; they are not replayed
            # from this completed backend record.
            issued = self.backend.add(kind, application, group, address, tag)
            self.events.append(dict(operation='backend_metadata_created', kind=kind,
                                    application=application, group=group, address=address))
            self._notify(request('metadata_ready_before_storage'), engine)
            persisted = self.backend.save()
            found = self._find(kind, application, group, address)
            if found is None or _field(found, 'TagName') != tag:
                raise SensorError('Stored source metadata failed exact address/name readback')
            if isinstance(self.backend, _NativeBackend) and (_oid(found) or '').lower() != issued['oid']:
                raise SensorError('Stored metadata OID differs from its issued creation receipt')
            if kind == 'level' and _level_value(found) != str(address):
                raise SensorError('Stored action selector failed exact Value readback')
            canonical = self._register(engine, kind, application, group, address,
                                       value=_level_integer(found) if kind == 'level' else None)
            self.events.append(dict(operation='metadata_storage_readback', kind=kind,
                                    application=application, group=group, address=address, **persisted))
            self._notify(request('stored_readback'), engine)
            return canonical
        except Exception:
            self.failed = True
            raise
        finally:
            if kind == 'application':
                self._application_creating = False

    def dispatch(self, request, engine):
        if type(request) is not SourceLookupRequest:
            raise SensorError('Project dispatcher requires an actual source getter request')
        self._lookup(engine, request.kind, request.application, None, request.address,
                     request.create, request.source)

    def get_level(self, engine, actual_group, value, *, create=True, source):
        self._engine(engine)
        if (not isinstance(actual_group, _Object) or actual_group.kind != 'group'
                or engine.groups.get(actual_group.identity) is not actual_group):
            raise SensorError('Level getter requires the SAME canonical source group')
        application, group = actual_group.identity
        return self._lookup(engine, 'level', application, group, value, create, source)

    def current_record(self, engine, actual_object):
        """Read actual current metadata for one SAME canonical object."""
        self._engine(engine)
        if not isinstance(actual_object, _Object):
            raise SensorError('Metadata record requires a canonical source object')
        kind, identity = actual_object.kind, actual_object.identity
        if kind == 'application' and engine.apps.get(identity) is actual_object:
            node = self._find(kind, None, None, identity)
        elif kind == 'group' and engine.groups.get(identity) is actual_object:
            node = self._find(kind, identity[0], None, identity[1])
        elif kind == 'level' and engine.levels.get(identity) is actual_object:
            node = self._find(kind, identity[0], identity[1], identity[2])
        else:
            raise SensorError('Metadata record requires the SAME canonical source object')
        if node is None:
            raise SensorError('Actual source metadata no longer exists')
        return deepcopy(_record(node))

    def level_value(self, engine, actual_level):
        """CURRENT distinct TLevel.Value; native AsInteger does not resolve.

        This is a read interface only. A live Value setter and its generic
        metadata notifications require the owning metadata attribute provider;
        this bridge never rewrites an existing Value from its Address.
        """
        record = self.current_record(engine, actual_level)
        if record['kind'] != 'Level':
            raise SensorError('Level Value requires the SAME actual level object')
        value = record['value']
        if not re.fullmatch(r'-?[0-9]{1,10}', value) or not -(1 << 31) <= int(value) < (1 << 31):
            raise SensorError('Actual source level requires its signed Integer Value')
        return int(value)

    def display_text(self, engine, actual_object, *, source):
        if self.display_text_provider is None:
            raise SensorError('Native ToString text requires its actual source provider')
        if type(source) is not str or not source:
            raise SensorError('Display text requires its current source position')
        record = self.current_record(engine, actual_object)
        value = self.display_text_provider(actual_object, record, source, engine)
        if type(value) is not str:
            raise SensorError('Native display text requires a string')
        return value

    def form_applications(self, engine):
        """Actual CURRENT full manager inventory, only at an owning list read."""
        from .senlla_fresh_forms import FormApplication, FormGroup
        self._engine(engine)
        if self.manager_order is None:
            raise SensorError('Native current GroupManager Items order requires its actual provider')
        _, network, _ = self._nodes()
        result = []
        for node in _elements(network, 'Application'):
            address = _number(node)
            app = engine.add_source_application(address)
            rows = tuple(_record(group) for group in _elements(node)
                         if _name(group) in ('Group', 'NetVar'))
            for row in rows:
                engine.add_source_group(app, row['address'])
            order = self.manager_order(app, deepcopy(rows), engine)
            engine.bind_source_group_order(app, order)
            current = {row['address']: row for row in rows}
            groups = tuple(FormGroup(f'group:{address}:{group.identity[1]}', f'application:{address}',
                                     group.identity[1], current[group.identity[1]]['tag_name'])
                           for group in engine.current_source_group_order(app))
            result.append(FormApplication(f'application:{address}', address, _field(node, 'TagName'), groups))
        return tuple(result)

    def group_items(self, engine, actual_application):
        """Read only one CURRENT canonical application's actual manager rows.

        The owning control invokes this at its Count/ordinal read position.
        This confirms existing backend objects and native manager order; it
        creates nothing and never seeds unrelated applications or levels.
        A native object-removal/lifetime owner must resolve stale canonical
        registrations before binding a reduced manager inventory.
        """
        self._engine(engine)
        if (not isinstance(actual_application, _Object)
                or actual_application.kind != 'application'
                or engine.apps.get(actual_application.identity) is not actual_application):
            raise SensorError('Group Items requires the SAME canonical application object')
        if self.manager_order is None:
            raise SensorError('Native current GroupManager Items order requires its actual provider')
        node = self._find('application', None, None, actual_application.identity)
        if node is None:
            raise SensorError('Actual source application no longer exists')
        rows = tuple(_record(group) for group in _elements(node)
                     if _name(group) in ('Group', 'NetVar'))
        if len({row['address'] for row in rows}) != len(rows):
            raise SensorError('Actual GroupManager contains ambiguous numeric identities')
        for row in rows:
            engine.add_source_group(actual_application, row['address'])
        order = self.manager_order(actual_application, deepcopy(rows), engine)
        engine.bind_source_group_order(actual_application, order)
        return engine.current_source_group_order(actual_application)

    def unit_tag_name_changed(self, owner):
        self._engine(owner.runtime)
        self.events.append(dict(operation='unit_tag_name_after_change', current=owner.tag_name._value))
        if self.tag_name_dispatch is None:
            raise SensorError('TagName setter requires its actual native notification/timer owner')
        if self.tag_name_dispatch(owner, self) is not None:
            raise SensorError('TagName owner must finish actual notifications before returning')

    def evidence(self):
        return deepcopy(dict(events=self.events, failed=self.failed,
                             actual_backend=type(self.backend).__name__,
                             transient_metadata_notifications_implemented=False,
                             original_execution=False, native_storage_acceptance=False,
                             complete_toolkit_save=False))
