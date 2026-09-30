"""Bounded WTXU project metadata creation for an admitted wireless gateway.

This implements the statically recovered creation/save sequence, not pairing,
gateway mapping edits, PP defaults or the original GUI. Three project saves
are separate irreversible boundaries; no uncertain operation is replayed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import xml.etree.ElementTree as ET

from .native import NativeDatabase, NativeProjects
from .programming import xml_text
from .serials import parse_native_serial
from .wireless_gateway import check_profile


PLAN_FORMAT = 'cbus-wireless-project-remote-plan-v1'
PROJECT_FORMAT = 'cbus-wireless-project-remote-project-v1'
CATALOGUE_FORMAT = 'cbus-wireless-project-remote-catalogue-v1'
MAX_PROJECT_XML_BYTES = 16 * 1024 * 1024
MAX_CATALOGUE_XML_BYTES = 16 * 1024 * 1024
MAX_PLAN_JSON_BYTES = 32 * 1024 * 1024
SAVE_STAGES = ('constructor', 'database_agent', 'creation_caller')
# Exact, independently observed catalogue profile. Spec defaults are not copied
# into the new Unit: the original metadata-only save does not perform PP SAVE.
_CATALOGUE = {'unit_type': 'WTXU', 'catalog_number': '5888TXBA',
              'minimum_version': '0', 'maximum_version': '9',
              'spec_filename': 'WTXU.xml', 'class_name': 'CBusPCI',
              'is_default': 'true', 'is_addressable': 'false',
              'input_count': '0', 'output_count': '0', 'group_count': '0'}


class RemoteCreationError(ValueError):
    pass


class RemoteCreationApplyError(RuntimeError):
    def __init__(self, cause, details):
        self.details = json.loads(_canonical(details))
        super().__init__('Project remote creation stopped; inspect its partial-result receipt '
                         'before manual recovery, and do not replay: ' + str(cause))


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _sha(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise RemoteCreationError('Invalid source SHA-256')
    return value


def _tag(node):
    return node.tag.rsplit('}', 1)[-1]


def _children(node, name):
    return [child for child in node if _tag(child) == name]


def _field(node, name, *, required=False):
    fields = _children(node, name)
    if len(fields) > 1 or fields and (len(fields[0]) or fields[0].attrib):
        raise RemoteCreationError('Ambiguous or nonscalar ' + name)
    if not fields:
        if required:
            raise RemoteCreationError('Missing ' + name)
        return None
    return fields[0].text or ''


def _byte(value, label, maximum=255):
    if type(value) is not int or not 0 <= value <= maximum:
        raise RemoteCreationError(label + ' must be an integer in 0..' + str(maximum))
    return value


def _address(node):
    value = _field(node, 'Address', required=True)
    if re.fullmatch(r'[0-9]{1,3}', value) is None:
        raise RemoteCreationError('Invalid database Address')
    return _byte(int(value), 'Address')


def _parse(payload, cap):
    if type(payload) is not bytes or not payload or len(payload) > cap:
        raise RemoteCreationError('XML must be nonempty bytes within the command size cap')
    if b'\x00' in payload or b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
        raise RemoteCreationError('Unsupported XML declarations')
    try:
        text = payload.decode('utf-8')
        declaration = re.match(r'\s*<\?xml\s+[^?]*encoding=[\'"]([^\'"]+)', text, re.I)
        if declaration and declaration[1].lower() not in ('utf-8', 'utf8'):
            raise RemoteCreationError('Expected UTF-8 XML encoding')
        return ET.fromstring(text)
    except (ValueError, ET.ParseError) as error:
        raise RemoteCreationError('Expected valid UTF-8 XML') from error


def _tree(node):
    # Retain all values, attributes, namespace names and child order, including
    # unknown project content. Only XML indentation is insignificant.
    text = node.text or ''
    if len(node) and not text.strip():
        text = ''
    tail = node.tail or ''
    if not tail.strip():
        tail = ''
    return [node.tag, sorted(node.attrib.items()), text,
            [_tree(child) for child in node], tail]


@dataclass(frozen=True)
class FrozenRemoteProject:
    payload: bytes

    def __post_init__(self):
        project = self.root
        name = _field(project, 'Address') or _field(project, 'TagName', required=True)
        if re.fullmatch(r'[A-Za-z0-9_]{1,8}', name) is None:
            raise RemoteCreationError('Project requires a native 1..8 character identity')
        networks = _children(project, 'Network')
        addresses = [_address(network) for network in networks]
        if not networks or len(set(addresses)) != len(addresses):
            raise RemoteCreationError('Project requires unique network addresses')
        for network in networks:
            units = _children(network, 'Unit')
            addresses = [_address(unit) for unit in units]
            if len(set(addresses)) != len(addresses):
                raise RemoteCreationError('Duplicate unit address')
            names = [_field(unit, 'TagName', required=True) for unit in units]
            if len(set(names)) != len(names):
                raise RemoteCreationError('Duplicate unit TagName in one network')
            serials = set()
            for unit in units:
                _field(unit, 'UnitType', required=True)
                serial = _field(unit, 'SerialNumber')
                if serial:
                    try:
                        identity = parse_native_serial(serial)
                    except ValueError:
                        continue  # Selected source-network admission is stricter.
                    if identity.known and identity in serials:
                        raise RemoteCreationError('Duplicate unit SerialNumber in one network')
                    if identity.known:
                        serials.add(identity)

    @property
    def root(self):
        root = _parse(self.payload, MAX_PROJECT_XML_BYTES)
        projects = [root] if _tag(root) == 'Project' else _children(root, 'Project')
        if len(projects) != 1:
            raise RemoteCreationError('Expected exactly one native project')
        return projects[0]

    @property
    def name(self):
        return _field(self.root, 'Address') or _field(self.root, 'TagName', required=True)

    @property
    def fingerprint(self):
        return _digest(_canonical(_tree(self.root)).encode())

    @classmethod
    def from_xml(cls, payload):
        return cls(payload)

    def as_dict(self):
        return {'format': PROJECT_FORMAT, 'xml': self.payload.decode('utf-8'),
                'source_sha256': _digest(self.payload), 'facts_sha256': self.fingerprint}

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, dict) or set(value) !=
                {'format', 'xml', 'source_sha256', 'facts_sha256'}
                or value['format'] != PROJECT_FORMAT or not isinstance(value['xml'], str)):
            raise RemoteCreationError('Invalid frozen remote project')
        result = cls(value['xml'].encode('utf-8'))
        if result.as_dict() != value:
            raise RemoteCreationError('Frozen project fingerprint mismatch')
        return result


@dataclass(frozen=True)
class RemoteCatalogue:
    source_sha256: str

    def __post_init__(self):
        _sha(self.source_sha256)

    @classmethod
    def from_xml(cls, payload):
        root = _parse(payload, MAX_CATALOGUE_XML_BYTES)
        if _tag(root) != 'CBusUnits':
            raise RemoteCreationError('Expected a CBusUnits catalogue')
        matches, resolved_catalogues = [], []
        for unit in root.iter():
            if _tag(unit) != 'Unit':
                continue
            catalog = _field(unit, 'CatalogNumber') or ''
            alternatives = _field(unit, 'AlternativeCatalogNumbers') or ''
            # The remote AgentSave resolves the catalogue back to a UnitType.
            # Refuse any competing exact/prefix/alternate resolution; do not
            # guess which installation-wide catalogue object won that lookup.
            candidates = [catalog, *re.split('[,;]', alternatives)]
            for candidate in candidates:
                candidate = candidate.strip().upper()
                if not candidate:
                    continue
                prefix = candidate.split(',', 1)[0].split('-', 1)[0]
                target = _CATALOGUE['catalog_number']
                if prefix == target or '*' in prefix and target.startswith(prefix.split('*', 1)[0]):
                    resolved_catalogues.append(unit)
                    break
            for container in _children(unit, 'FirmwareRevisions'):
                for revision in _children(container, 'Revision'):
                    if (_field(revision, 'UnitType') or '').upper() != 'WTXU':
                        continue
                    if alternatives:
                        raise RemoteCreationError('WTXU catalogue alternatives are outside the admitted profile')
                    matches.append({
                        'unit_type': _field(revision, 'UnitType'),
                        'catalog_number': _field(unit, 'CatalogNumber'),
                        'minimum_version': _field(revision, 'MinVersion'),
                        'maximum_version': _field(revision, 'MaxVersion'),
                        'spec_filename': _field(revision, 'UnitSpecName'),
                        'class_name': _field(revision, 'ClassName'),
                        'is_default': _field(revision, 'IsDefault'),
                        'is_addressable': _field(unit, 'IsAddressable'),
                        'input_count': _field(unit, 'InputCount'),
                        'output_count': _field(unit, 'OutputCount'),
                        'group_count': _field(unit, 'GroupCount')})
        if matches != [_CATALOGUE]:
            raise RemoteCreationError('Catalogue must contain exactly one admitted WTXU/5888TXBA row')
        if len(resolved_catalogues) != 1:
            raise RemoteCreationError('Ambiguous catalogue-to-remote UnitType resolution')
        return cls(_digest(payload))

    def as_dict(self):
        return {'format': CATALOGUE_FORMAT, 'source_sha256': self.source_sha256,
                'profile': dict(_CATALOGUE)}

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, dict) or set(value) != {'format', 'source_sha256', 'profile'}
                or value['format'] != CATALOGUE_FORMAT or value['profile'] != _CATALOGUE):
            raise RemoteCreationError('Unsupported remote catalogue profile')
        return cls(value['source_sha256'])


def _serial(value):
    try:
        parsed = parse_native_serial(value)
    except ValueError as error:
        raise RemoteCreationError('Remote serial must be a known native decimal-dot serial') from error
    if not parsed.known or value != parsed.canonical:
        raise RemoteCreationError('Remote serial must be known and in canonical decimal-dot form')
    return parsed


def _selection(project, source_network, gateway_address, serial, catalogue):
    if type(project) is not FrozenRemoteProject or type(catalogue) is not RemoteCatalogue:
        raise RemoteCreationError('Use a frozen project and admitted remote catalogue')
    _byte(source_network, 'Source network', 254)
    _byte(gateway_address, 'Gateway address', 254)
    serial_number = _serial(serial)
    networks = {_address(n): n for n in _children(project.root, 'Network')}
    if source_network not in networks:
        raise RemoteCreationError('Missing selected source network')
    units = {_address(u): u for u in _children(networks[source_network], 'Unit')}
    if gateway_address not in units:
        raise RemoteCreationError('Missing selected gateway')
    gateway = units[gateway_address]
    try:
        check_profile(_field(gateway, 'UnitType'), _field(gateway, 'FirmwareVersion'),
                      _field(gateway, 'CatalogNumber'))
    except ValueError as error:
        raise RemoteCreationError('Unsupported project remote gateway profile: ' + str(error)) from error
    for unit in units.values():
        existing = _field(unit, 'SerialNumber')
        if existing:
            try:
                if parse_native_serial(existing) == serial_number:
                    raise RemoteCreationError('Remote serial already exists in the source network')
            except RemoteCreationError:
                raise
            except ValueError as error:
                # A malformed serial could conceal a duplicate; do not normalize
                # arbitrary original database text into an invented identity.
                raise RemoteCreationError('Cannot exclude duplicate: existing unit serial is malformed') from error
    available = next((address for address in range(100, 256) if address not in units), None)
    if available is None:
        # Original returns0 when exhausted. Never overwrite/fall back to that slot.
        raise RemoteCreationError('No free project remote address in 100..255')
    names = {_field(unit, 'TagName', required=True) for unit in units.values()}
    index = 1
    while f'Remote {index:02d}' in names:
        index += 1
    return available, f'Remote {index:02d}'


@dataclass(frozen=True)
class RemoteCreationPlan:
    project: FrozenRemoteProject
    catalogue: RemoteCatalogue
    source_network: int
    gateway_address: int
    serial: str

    def __post_init__(self):
        _selection(self.project, self.source_network, self.gateway_address, self.serial, self.catalogue)

    @property
    def address(self):
        return _selection(self.project, self.source_network, self.gateway_address, self.serial, self.catalogue)[0]

    @property
    def tag_name(self):
        return _selection(self.project, self.source_network, self.gateway_address, self.serial, self.catalogue)[1]

    @property
    def network_path(self):
        return f'//{self.project.name}/{self.source_network}'

    @property
    def gateway_source(self):
        return f'/db{self.network_path}/p/{self.gateway_address}'

    @property
    def path(self):
        return f'{self.network_path}/p/{self.address}'

    def as_dict(self):
        result = {'format': PLAN_FORMAT, 'project': self.project.as_dict(),
                  'catalogue': self.catalogue.as_dict(), 'source_network': self.source_network,
                  'gateway_address': self.gateway_address, 'serial': self.serial,
                  'created_address': self.address, 'tag_name': self.tag_name,
                  'constructor_fields': {'UnitType': 'WTXU', 'FirmwareVersion': '0',
                                         'UnitName': 'REMOTE'},
                  'database_fields': {'SerialNumber': self.serial, 'Description': '',
                                      'CatalogNumber': _CATALOGUE['catalog_number']},
                  'project_save_stages': list(SAVE_STAGES), 'pp_initialized': False,
                  'gateway_mappings_changed': False, 'physical_pairing_verified': False}
        if len(_canonical(result).encode()) > MAX_PLAN_JSON_BYTES:
            raise RemoteCreationError('Remote creation plan exceeds the command size cap')
        return result

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or value.get('format') != PLAN_FORMAT:
            raise RemoteCreationError('Invalid project remote creation plan')
        try:
            result = cls(FrozenRemoteProject.from_dict(value['project']),
                         RemoteCatalogue.from_dict(value['catalogue']),
                         value['source_network'], value['gateway_address'], value['serial'])
        except (KeyError, TypeError) as error:
            raise RemoteCreationError('Incomplete project remote creation plan') from error
        if result.as_dict() != value:
            raise RemoteCreationError('Remote creation plan differs from reproduced source rules')
        return result


def plan_project_remote(project, *, source_network, gateway_address, serial, catalogue):
    return RemoteCreationPlan(project, catalogue, source_network, gateway_address, serial)


def _read_project(client, name):
    response = NativeDatabase(client).get('//' + name, xml=True)
    if response.code != 344:
        raise RemoteCreationError('Expected a complete native project XML response')
    return FrozenRemoteProject.from_xml(xml_text(response).encode('utf-8'))


def _closed(client, project):
    from .addressing import NetworkAddressing
    guard = NetworkAddressing(client)
    for network in _children(project.root, 'Network'):
        runtime = dict(guard._runtime(f'//{project.name}/{_address(network)}'))
        if any(runtime.get(key) != value for key, value in (
                ('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle'))):
            raise RemoteCreationError('Every project network must be closed and idle')


def _preserved_tree(root, *, allow_config_oids=False):
    if allow_config_oids:
        # C-Gate 3.4 regenerates these exact bookkeeping identities on every
        # PROJECT SAVE. Keep their presence/shape and every other field, including
        # names, values, child order and all unit/PP OIDs, under comparison.
        for config in _children(root, 'Config'):
            if _field(config, 'Application') != 'cgate':
                continue
            for node in (config, *_children(config, 'Property')):
                for oid in _children(node, 'OID'):
                    if (not len(oid) and not oid.attrib and re.fullmatch(
                            r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', oid.text or '')):
                        oid.text = '<native-regenerated-cgate-config-oid>'
    return _tree(root)


def _verify_after(client, plan, fields, *, created_oid, allow_config_oids=False):
    after = _read_project(client, plan.project.name)
    root = after.root
    network = next(n for n in _children(root, 'Network') if _address(n) == plan.source_network)
    created = [u for u in _children(network, 'Unit') if _address(u) == plan.address]
    if len(created) != 1:
        raise RemoteCreationError('New remote could not be uniquely read back')
    unit = created[0]
    expected = {'Address': str(plan.address), 'TagName': plan.tag_name, **fields}
    if any(_field(unit, key) != value for key, value in expected.items()):
        raise RemoteCreationError('New remote metadata readback mismatch')
    names = [_tag(child) for child in unit]
    if len(names) != len(set(names)) or set(names) != set(expected) | {'OID'}:
        raise RemoteCreationError('New remote has unexpected inherited metadata or PP content')
    oid = _field(unit, 'OID', required=True)
    if re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', oid) is None:
        raise RemoteCreationError('New remote has no valid native OID')
    if oid.lower() != created_oid.lower():
        raise RemoteCreationError('New remote OID differs from the native creation receipt')
    network.remove(unit)
    if (_preserved_tree(root, allow_config_oids=allow_config_oids)
            != _preserved_tree(plan.project.root, allow_config_oids=allow_config_oids)):
        raise RemoteCreationError('Existing project content changed during remote creation')
    return after.fingerprint


def _preflight_project_remote(client, plan, *, exclusive_project):
    if type(plan) is not RemoteCreationPlan or exclusive_project is not True:
        raise RemoteCreationError('Remote creation requires a valid plan and exclusive project ownership')
    plan = RemoteCreationPlan.from_dict(plan.as_dict())
    fresh = _read_project(client, plan.project.name)
    if fresh.fingerprint != plan.project.fingerprint:
        raise RemoteCreationError('Project changed since the remote creation plan was made')
    _closed(client, fresh)
    # Bookend runtime observation with a fresh database snapshot.
    if _read_project(client, plan.project.name).fingerprint != plan.project.fingerprint:
        raise RemoteCreationError('Project changed during the closed-project preflight')
    return plan, fresh


def preview_project_remote(client, plan, *, exclusive_project=False):
    """Verify current closed database state without creating a unit or PP session."""
    plan, _ = _preflight_project_remote(client, plan, exclusive_project=exclusive_project)
    return {'format': 'cbus-wireless-project-remote-preview-v1', 'dry_run': True,
            'preflight_verified': True, 'created_path': plan.path,
            'created_address': plan.address, 'tag_name': plan.tag_name,
            'project_save_stages': list(SAVE_STAGES), 'saved': False,
            'pp_initialized': False, 'gateway_mappings_changed': False,
            'physical_pairing_verified': False, 'original_toolkit_executed': False}


def apply_project_remote(client, plan, *, exclusive_project=False):
    """Apply once to an exclusively owned, closed native project; never retry.

    Validation and exact whole-project stale checking precede any mutation.
    Failure retains the possibly created row and a receipt, including each save
    attempt. No rollback runs across an uncertain add, metadata write or save.
    """
    plan, fresh = _preflight_project_remote(client, plan, exclusive_project=exclusive_project)
    report = {'format': 'cbus-wireless-project-remote-apply-v1', 'created_path': plan.path,
              'created_address': plan.address, 'tag_name': plan.tag_name,
              'stage': 'constructor', 'project_save_attempts': [], 'attempted_commands_count': 0,
              'creation_attempted': False, 'creation_confirmed': False, 'created_oid': None,
              'saved': False, 'uncertain_save': False, 'retry_performed': False,
              'rollback_performed': False, 'preserved_existing_project': False,
              'native_config_oid_changes_allowed_after_save': True,
              'pp_initialized': False, 'gateway_mappings_changed': False,
              'physical_pairing_verified': False, 'original_toolkit_executed': False}
    database = NativeDatabase(client)
    projects = NativeProjects(client)

    def attempt(action, *args):
        report['attempted_commands_count'] += 1
        return action(*args)

    def save(stage):
        report['stage'] = stage
        record = {'stage': stage, 'attempted': True, 'completed': False}
        report['project_save_attempts'].append(record)
        report['uncertain_save'] = True
        attempt(projects.operation, 'save', plan.project.name)
        record['completed'] = True
        report['uncertain_save'] = False

    def set_field(field, value):
        response = attempt(database.set, plan.path + '/' + field, value)
        if response.code != 200:
            raise RemoteCreationError('Native metadata write did not confirm completion')

    constructor = {'UnitType': 'WTXU', 'FirmwareVersion': '0', 'UnitName': 'REMOTE'}
    metadata = {'SerialNumber': plan.serial, 'Description': '', 'CatalogNumber': _CATALOGUE['catalog_number']}
    try:
        report['creation_attempted'] = True
        response = attempt(database.add, plan.network_path, 'unit', plan.address, plan.tag_name)
        if response.code != 301:
            raise RemoteCreationError('Native add did not confirm creation')
        identifiers = [match[1] for line in response.lines if (match := re.fullmatch(
            r'301[- ]OID=([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})', line))]
        if len(identifiers) != 1:
            raise RemoteCreationError('Native add did not return exactly one unit OID')
        created_oid = identifiers[0]
        report['created_oid'] = created_oid
        report['creation_confirmed'] = True
        for field, value in constructor.items():
            set_field(field, value)
        _verify_after(client, plan, constructor, created_oid=created_oid)
        save('constructor')
        report['stage'] = 'database_metadata'
        for field, value in metadata.items():
            set_field(field, value)
        # Original DBSET repeats the unchanged tag. DBSETSAFE refuses that
        # self-collision, so retain the verified name without rewriting it.
        _verify_after(client, plan, {**constructor, **metadata},
                      created_oid=created_oid, allow_config_oids=True)
        save('database_agent')
        report['stage'] = 'remote_agent_unit_type'
        # Remote AgentSave resolves the catalogue after the inherited save.
        set_field('UnitType', 'WTXU')
        save('creation_caller')
        report['stage'] = 'readback'
        report['result_project_sha256'] = _verify_after(
            client, plan, {**constructor, **metadata}, created_oid=created_oid, allow_config_oids=True)
        _closed(client, fresh)
        report['preserved_existing_project'] = True
        report['saved'] = True
        report['stage'] = 'complete'
        return report
    except Exception as error:
        raise RemoteCreationApplyError(error, report) from error
