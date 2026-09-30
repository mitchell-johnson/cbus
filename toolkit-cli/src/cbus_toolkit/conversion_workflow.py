"""One reviewed, backed-up RELDN4 -> RELDN4A native database move.

No physical programming, automatic rollback, or uncertain operation replay.
Recovery observes the loaded database only; it cannot infer durable save from
an apparently converted loaded tree after a lost PROJECT SAVE reply.
"""
from __future__ import annotations

import copy
import hashlib
import json
import stat
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .conversion import NativeConversions, _unit_path
from .conversion_mapping import (MappingTable, convert_parameters, expected_identity,
                                 load_catalog, render_parameters, session_default)
from .native import NativeDatabase, NativeProjects, _project
from .pci_selected_serial import _Journal, _unique_pairs
from .programming import Programmer, xml_text
from .unitspec import UnitSpecStore

PLAN_FORMAT = 'cbus-native-conversion-move-plan-v1'
JOURNAL_FORMAT = 'cbus-native-conversion-move-journal-v1'
PHASES = ('prepared', 'backup-copy-possible', 'backup-verified', 'convert-possible',
          'convert-confirmed', 'save-possible', 'save-confirmed', 'reopen-possible',
          'complete')


class ConversionWorkflowError(RuntimeError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def _json_parse(raw):
    def reject(value):
        raise ValueError('Nonfinite conversion JSON value: ' + value)
    return json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=reject)


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _xml(raw):
    if not isinstance(raw, str) or len(raw.encode()) > 4 * 1024 * 1024:
        raise ValueError('Conversion XML exceeds its bound')
    if '<!--' in raw or re.search(r'<\?(?!xml(?:\s|\?>))', raw):
        raise ValueError('XML comments/processing instructions are unsupported')
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():
        raise ValueError('Unsupported conversion XML declarations')
    root = ET.fromstring(raw)
    for element in root.iter():
        if ((len(element) and (element.text or '').strip()) or (element.tail or '').strip()):
            raise ValueError('Significant mixed XML content is unsupported')
    return root


def _tree(element):
    """Whitespace-independent tree, preserving ordered children and all attrs."""
    text = (element.text or '') if not len(element) else ''
    return [element.tag, sorted(element.attrib.items()), text, [_tree(child) for child in element]]


def _unit(element):
    if element.tag != 'Unit' or element.attrib:
        raise ValueError('Expected plain native Unit XML')
    scalars, pp, channels = {}, [], []
    for child in element:
        if child.tag == 'PP':
            if set(child.attrib) != {'Name', 'Value'} or len(child):
                raise ValueError('Malformed native PP record')
            pp.append([child.get('Name'), child.get('Value')])
        elif child.tag == 'OutputChannel':
            if child.attrib:
                raise ValueError('Unsupported output channel attributes')
            row = {}
            for field in child:
                if field.tag in row or len(field) or field.attrib:
                    raise ValueError('Malformed native output channel')
                row[field.tag] = field.text or ''
            channels.append(row)
        elif not len(child):
            if child.attrib:
                raise ValueError('Unsupported unit scalar attributes')
            if child.tag in scalars:
                raise ValueError('Duplicate native unit scalar')
            scalars[child.tag] = child.text or ''
        else:
            raise ValueError('Unsupported native unit subtree')
    if len({name for name, _ in pp}) != len(pp):
        raise ValueError('Duplicate native PP parameter')
    return {'scalars': scalars, 'pp': pp, 'channels': channels}


def load_plan(path):
    raw = _Journal(path)._read_current()
    value = _json_parse(raw)
    return validate_plan(value)


def validate_plan(plan):
    if type(plan) is not dict or plan.get('format') != PLAN_FORMAT:
        raise ValueError('Unsupported conversion plan')
    if set(plan) != {'format', 'binding', 'plan_sha256'} or _hash(plan['binding']) != plan['plan_sha256']:
        raise ValueError('Conversion plan hash or fields differ')
    binding = plan['binding']
    if type(binding) is not dict or set(binding) != {
            'source', 'destination', 'project', 'network', 'backup_project', 'endpoint', 'inputs',
            'before_project_xml', 'source_xml', 'destination_xml', 'source_pp',
            'destination_pp', 'expected_pp', 'expected_values', 'expected_identity',
            'expected_project_xml', 'expected_project_sha256'}:
        raise ValueError('Unsupported conversion plan binding')
    endpoint = binding['endpoint']
    if (type(endpoint) is not dict or set(endpoint) != {'host', 'port'}
            or not isinstance(endpoint['host'], str) or not endpoint['host']
            or type(endpoint['port']) is not int or not 1 <= endpoint['port'] <= 65535):
        raise ValueError('Malformed conversion endpoint')
    source, project, network, _ = _unit_path(binding['source'])
    destination, other, target_network, _ = _unit_path(binding['destination'])
    if (source == destination or project != other or network != target_network
            or binding['project'] != project or binding['network'] != source.rsplit('/p/', 1)[0]):
        raise ValueError('Only a same-project/network existing-unit move is admitted')
    if _project(binding['backup_project']).upper() == project.upper():
        raise ValueError('Backup project must be distinct')
    if _hash(_tree(_xml(binding['expected_project_xml']))) != binding['expected_project_sha256']:
        raise ValueError('Expected project hash differs')
    return plan


class ConversionWorkflow:
    def __init__(self, client, spec_dir=None, *, catalog_path=None, mapping_path=None):
        self.client = client
        self.spec_dir = Path(spec_dir).absolute() if spec_dir is not None else None
        self.catalog_path = Path(catalog_path).absolute() if catalog_path else (
            self.spec_dir / 'cbusunits.xml' if self.spec_dir else None)
        self.mapping_path = Path(mapping_path).absolute() if mapping_path else (
            self.spec_dir / 'ConvertUnitMappingTable.xml' if self.spec_dir else None)
        self.projects = NativeProjects(client)
        self.database = NativeDatabase(client)
        self.conversions = NativeConversions(client)

    def _endpoint(self, binding):
        if binding['endpoint'] != {'host': self.client.host, 'port': self.client.port}:
            raise ValueError('Conversion endpoint differs from reviewed plan')

    def _backup_absent(self, name):
        directory = self.projects.directory()
        if re.search(r'(?i)(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])', '\n'.join(directory.lines)):
            raise ValueError('Backup project already exists')

    def _project(self, project):
        raw = xml_text(self.database.get('//' + project, xml=True))
        root = _xml(raw)
        rows = root.findall('Project') if root.tag == 'Installation' else []
        if len(rows) != 1 or rows[0].findtext('Address') != project:
            raise ValueError('Expected exactly one selected native project')
        return raw, root, rows[0]

    def _closed(self, project, document):
        addresses = []
        for row in document.findall('Network'):
            address = row.findtext('Address') or ''
            if not re.fullmatch(r'0|[1-9][0-9]{0,2}', address) or int(address) > 255 or address in addresses:
                raise ValueError('Invalid or duplicate project network')
            addresses.append(address)
            path = '//' + project + '/' + address
            reply = self.client.command('GET ' + path + ' *')
            values = {}
            for line in reply.lines:
                match = re.fullmatch(r'300[- ]([^:]+): ([^=]+)=(.*)', line)
                if not match or match[1] != path or match[2] in values:
                    raise ValueError('Malformed native network state')
                values[match[2]] = match[3]
            if any(values.get(key) != value for key, value in (
                    ('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle'))):
                raise ValueError('Every project network must be closed and idle')
        return addresses

    def _pp(self, path, spec=None):
        with Programmer(self.client).load(path.rsplit('/p/', 1)[0], '/db' + path) as session:
            if spec is not None:
                if session.unit_type != spec.unit_type or not spec.supports_version(session.firmware):
                    raise ValueError('PP identity/specification or firmware differs')
                # Reuse the existing layout verifier without the classic-only
                # alignment constructor or any staging/saving operation.
                from .offline_conversion import OfflineConversion
                OfflineConversion._verify_session(None, session, spec)
            return session.export_parameters()

    def _inputs(self, source, target):
        if self.spec_dir is None:
            raise ValueError('An explicit private specification directory is required')
        catalog = load_catalog(self.catalog_path)
        table = MappingTable.load(self.mapping_path)
        store = UnitSpecStore(self.spec_dir)
        specs = []
        paths = {self.catalog_path, self.mapping_path}
        for row, expected_type in ((source, 'RELDN4'), (target, 'RELDN4A')):
            fields = row['scalars']
            if fields.get('UnitType') != expected_type:
                raise ValueError('Only RELDN4 -> RELDN4A is admitted')
            filename = catalog.select_spec(unit_type=expected_type, firmware=fields.get('FirmwareVersion', ''),
                                           catalog_number=fields.get('CatalogNumber', ''))
            spec = store.load(filename)
            if spec.unit_type != expected_type or not spec.supports_version(fields.get('FirmwareVersion', '')):
                raise ValueError('Wrong specification type or firmware')
            for name, value in row['pp']:
                if name not in spec.parameters or not spec.validate_value(name, value)['valid']:
                    raise ValueError('Malformed or unsupported stored PP: ' + str(name))
            paths.update(self.spec_dir / name for name in spec.sources)
            specs.append(spec)
        if table.find('RELDN4', 'RELDN4A') is None:
            raise ValueError('Explicit RELDN4 -> RELDN4A mapping is required')
        fingerprints = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}
        return catalog, table, specs, fingerprints

    def plan_move(self, source, destination, *, backup_project, exclusive_project=False):
        if exclusive_project is not True:
            raise ValueError('Exclusive project ownership must be explicitly declared')
        source, project, net, address = _unit_path(source)
        destination, other, target_net, target_address = _unit_path(destination)
        backup_project = _project(backup_project)
        if project != other or net != target_net or address == target_address:
            raise ValueError('Only a same-network existing-unit move is admitted')
        if project.upper() == backup_project.upper():
            raise ValueError('Backup project must differ')
        self._backup_absent(backup_project)
        raw, root, document = self._project(project)
        if str(net) not in self._closed(project, document):
            raise ValueError('Selected network is absent')
        network = next(row for row in document.findall('Network') if row.findtext('Address') == str(net))
        source_nodes = [row for row in network.findall('Unit') if row.findtext('Address') == str(address)]
        target_nodes = [row for row in network.findall('Unit') if row.findtext('Address') == str(target_address)]
        if len(source_nodes) != 1 or len(target_nodes) != 1:
            raise ValueError('Source and destination must each identify one existing unit')
        source_node, target_node = source_nodes[0], target_nodes[0]
        source_row, target_row = _unit(source_node), _unit(target_node)
        catalog, table, specs, fingerprints = self._inputs(source_row, target_row)
        source_pp, destination_pp = self._pp(source, specs[0]), self._pp(destination, specs[1])
        for row, snapshot, spec in ((source_row, source_pp, specs[0]), (target_row, destination_pp, specs[1])):
            if any(snapshot[key] != row['scalars'].get(field) for key, field in (
                    ('unit_type', 'UnitType'), ('firmware', 'FirmwareVersion'), ('catalog_number', 'CatalogNumber'))):
                raise ValueError('Fresh PP identity differs from project snapshot')
            expected_current = dict(render_parameters(spec, row['pp']))
            for name, parameter in spec.parameters.items():
                expected_current.setdefault(name, session_default(parameter))
            if snapshot['parameters'] != expected_current:
                raise ValueError('Fresh PP values differ from stored project parameters')
        rendered_source = render_parameters(specs[0], source_row['pp'])
        if rendered_source != [tuple(row) for row in source_row['pp']]:
            raise ValueError('Source PP must use canonical native rendering')
        expected_pp = convert_parameters(table, 'RELDN4', rendered_source, specs[1], 'RELDN4A')
        for name, value in expected_pp:
            if not specs[1].validate_value(name, value)['valid']:
                raise ValueError('Mapped PP is malformed: ' + name)
        expected_values = {name: value for name, value in render_parameters(specs[1], expected_pp)}
        for name, parameter in specs[1].parameters.items():
            expected_values.setdefault(name, session_default(parameter))
        identity = expected_identity(mode=2, source=source_row['scalars'], destination=target_row['scalars'],
                                     target_type='RELDN4A', catalog_number=None, catalog=catalog)
        admitted_scalars = set(identity) - {'OutputChannels'} | {'OID'}
        if set(target_row['scalars']) - admitted_scalars:
            raise ValueError('Unsupported destination scalar metadata: ' + ', '.join(sorted(set(target_row['scalars']) - admitted_scalars)))
        if len(identity['OutputChannels']) != 4:
            raise ValueError('Bounded RELDN4A target requires four catalogue output channels')
        # Identity is determined before CONVERT, never from its returned tree.
        candidate = copy.deepcopy(root)
        candidate_project = candidate.find('Project')
        candidate_network = next(row for row in candidate_project.findall('Network') if row.findtext('Address') == str(net))
        candidate_source = next(row for row in candidate_network.findall('Unit') if row.findtext('Address') == str(address))
        candidate_target = next(row for row in candidate_network.findall('Unit') if row.findtext('Address') == str(target_address))
        candidate_network.remove(candidate_source)
        # Native replaces the destination unit; OID is allocator-owned and
        # checked separately as one nonempty OID, not predicted from output.
        for child in list(candidate_target):
            if child.tag in ('PP', 'OutputChannel', 'OID'):
                candidate_target.remove(child)
        for key, value in identity.items():
            if key == 'OutputChannels':
                continue
            child = candidate_target.find(key)
            if child is None:
                child = ET.SubElement(candidate_target, key)
            child.text = value
        for name, value in expected_pp:
            ET.SubElement(candidate_target, 'PP', Name=name, Value=value)
        for row in identity['OutputChannels']:
            channel = ET.SubElement(candidate_target, 'OutputChannel')
            for key, value in row.items():
                ET.SubElement(channel, key).text = value
        check = self.conversions.check_move(source, destination)
        if not check['allowed']:
            raise ValueError('Native CHECK refused conversion')
        binding = {'source': source, 'destination': destination, 'project': project,
                   'network': source.rsplit('/p/', 1)[0], 'backup_project': backup_project,
                   'endpoint': {'host': self.client.host, 'port': self.client.port},
                   'inputs': fingerprints, 'before_project_xml': raw,
                   'source_xml': ET.tostring(source_node, encoding='unicode'),
                   'destination_xml': ET.tostring(target_node, encoding='unicode'),
                   'source_pp': source_pp, 'destination_pp': destination_pp,
                   'expected_pp': [list(row) for row in expected_pp], 'expected_values': expected_values,
                   'expected_identity': identity, 'expected_project_xml': ET.tostring(candidate, encoding='unicode'),
                   'expected_project_sha256': _hash(_tree(candidate))}
        return validate_plan({'format': PLAN_FORMAT, 'binding': binding, 'plan_sha256': _hash(binding)})

    def _observe(self, binding):
        raw, root, document = self._project(binding['project'])
        net = binding['network'].rsplit('/', 1)[1]
        unit_address = binding['destination'].rsplit('/', 1)[1]
        network = next((row for row in document.findall('Network') if row.findtext('Address') == net), None)
        if network is None:
            raise ValueError('Destination network disappeared')
        target = [row for row in network.findall('Unit') if row.findtext('Address') == unit_address]
        if len(target) != 1:
            raise ValueError('Destination unit disappeared or duplicated')
        row = _unit(target[0])
        pp = self._pp(binding['destination'])
        # Retain the complete observation; compare all other project content.
        observed = copy.deepcopy(root)
        observed_project = observed.find('Project')
        observed_net = next(item for item in observed_project.findall('Network') if item.findtext('Address') == net)
        observed_target = next(item for item in observed_net.findall('Unit') if item.findtext('Address') == unit_address)
        oid = observed_target.find('OID')
        oid_valid = oid is not None and bool(oid.text) and len(observed_target.findall('OID')) == 1
        allocated_oids = {'unit': oid.text if oid is not None else None, 'channels': []}
        if oid is not None:
            observed_target.remove(oid)
        for channel in observed_target.findall('OutputChannel'):
            identifiers = channel.findall('OID')
            if len(identifiers) != 1 or not identifiers[0].text:
                oid_valid = False
            allocated_oids['channels'].append(identifiers[0].text if identifiers else None)
            for identifier in identifiers:
                channel.remove(identifier)
        present_ids = [value for value in [allocated_oids['unit'], *allocated_oids['channels']] if value]
        if len(present_ids) != len(set(present_ids)):
            oid_valid = False
        # Schema order may differ after rebuilding; compare scalar order only
        # independently, preserving order of PP and channels and other subtrees.
        expected = _xml(binding['expected_project_xml'])
        expected_target = next(item for item in expected.find('Project').findall('Network') if item.findtext('Address') == net)
        expected_target = next(item for item in expected_target.findall('Unit') if item.findtext('Address') == unit_address)
        def normalized(node):
            for channel in node.findall('OutputChannel'):
                channel[:] = sorted(channel, key=lambda item: item.tag)
            fixed = sorted([item for item in node if item.tag not in ('PP', 'OutputChannel')], key=lambda item: item.tag)
            ordered = [item for item in node if item.tag in ('PP', 'OutputChannel')]
            node[:] = fixed + ordered
        normalized(observed_target)
        normalized(expected_target)
        matched = (oid_valid and _tree(observed) == _tree(expected)
                   and row['pp'] == binding['expected_pp']
                   and pp['parameters'] == binding['expected_values'])
        return {'matched': matched, 'project_xml': raw, 'destination': row, 'fresh_pp': pp,
                'allocated_oids': allocated_oids,
                'hardware_programmed': False}

    def apply_move(self, plan, *, journal, exclusive_project=False):
        plan = validate_plan(plan)
        binding = plan['binding']
        self._endpoint(binding)
        target = Path(journal).absolute()
        if target.exists() or target.is_symlink():
            raise ConversionWorkflowError('Existing conversion attempt refuses reapply; recover read-only')
        if not target.parent.is_dir():
            raise ValueError('Journal directory must exist')
        entries = list(target.parent.iterdir())
        if len(entries) > 4096:
            raise ValueError('Journal directory exceeds scan bound')
        for entry in entries:
            info = entry.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            if info.st_size > 16 * 1024 * 1024:
                raise ValueError('Journal directory contains oversized file')
            raw = _Journal(entry)._read_current()
            try:
                prior = _json_parse(raw)
            except ValueError:
                if JOURNAL_FORMAT.encode() in raw or b'cbus-native-conversion-move' in raw:
                    raise ValueError('Corrupted conversion journal prevents apply')
                continue
            if not isinstance(prior, dict):
                continue
            if prior.get('format') == JOURNAL_FORMAT:
                prior = read_journal(entry)
                if prior['plan']['plan_sha256'] == plan['plan_sha256']:
                    raise ConversionWorkflowError('This reviewed conversion plan already has an attempt')
            elif JOURNAL_FORMAT.encode() in raw:
                raise ValueError('Corrupted conversion journal prevents apply')
            if (prior.get('format') == JOURNAL_FORMAT and prior.get('phase') != 'complete'
                    and prior.get('plan', {}).get('binding', {}).get('project') == binding['project']):
                raise ConversionWorkflowError('An unresolved conversion journal exists for this project')
        fresh = self.plan_move(binding['source'], binding['destination'], backup_project=binding['backup_project'],
                               exclusive_project=exclusive_project)
        if fresh != plan:
            raise ConversionWorkflowError('Project, PP or specifications changed since review')
        # DIRCHECK is deliberately before all mutating operations, including
        # COPY which can overwrite an existing server project on some backends.
        self._backup_absent(binding['backup_project'])
        writer = _Journal(target)
        state = {'format': JOURNAL_FORMAT, 'plan': plan, 'phase': 'prepared',
                 'history': ['prepared'], 'read_only_recovery_only': True,
                 'project_saved': False, 'backup_verified': False, 'observations': [], 'error': None}
        writer.write(state)
        def phase(name):
            state['phase'] = name
            state['history'].append(name)
            writer.write(state)
        try:
            phase('backup-copy-possible')
            self.projects.operation('copy', binding['project'], binding['backup_project'])
            backup_raw, backup_root, backup_document = self._project(binding['backup_project'])
            before = _xml(binding['before_project_xml'])
            before_project = before.find('Project')
            # Native COPY retains the database object's OIDs; only the copied
            # project Address/TagName identifies the backup project.
            for key in ('Address', 'TagName'):
                old = before_project.find(key)
                new = backup_document.find(key)
                if old is not None and new is not None:
                    new.text = old.text
            if _tree(backup_root) != _tree(before):
                raise ConversionWorkflowError('Complete backup tree differs from reviewed project')
            state['backup_xml'] = backup_raw
            state['backup_sha256'] = _hash(_tree(_xml(backup_raw)))
            state['backup_verified'] = True
            phase('backup-verified')
            phase('convert-possible')
            reply = self.client.command('CONVERTUNIT CONVERT 2 ' + binding['source'] + ' ' + binding['destination'])
            if reply.code != 200:
                raise ConversionWorkflowError('CONVERT did not confirm success: ' + reply.final)
            state['convert_reply'] = list(reply.lines)
            phase('convert-confirmed')
            observation = self._observe(binding)
            state['observations'].append(observation)
            if not observation['matched']:
                raise ConversionWorkflowError('Converted database differs from independent expected project/PP')
            state['project_saved'] = None
            phase('save-possible')
            self.projects.operation('save', binding['project'])
            state['project_saved'] = True
            phase('save-confirmed')
            phase('reopen-possible')
            self.projects.operation('close', binding['project'])
            self.projects.operation('load', binding['project'])
            observation = self._observe(binding)
            state['observations'].append(observation)
            if (not observation['matched'] or observation['allocated_oids'] !=
                    state['observations'][0]['allocated_oids']):
                raise ConversionWorkflowError('Reopened project differs from independent expected project/PP')
            phase('complete')
        except BaseException as error:
            state['error'] = {'type': type(error).__name__, 'message': str(error)}
            error.details = {'journal': str(target), 'phase': state['phase'],
                             'backup_project': binding['backup_project'],
                             'backup_verified': state['backup_verified'],
                             'project_saved': state['project_saved'],
                             'read_only_recovery_only': True}
            if not writer.failed:
                try:
                    writer.write(state)
                except BaseException as cleanup:
                    error.details['journal_update_error'] = {'type': type(cleanup).__name__, 'message': str(cleanup)}
            raise
        return {'complete': True, 'project_saved': True, 'backup_project': binding['backup_project'],
                'journal': str(target), 'source_removed': True, 'fresh_database_verified': True,
                'parameter_address_matches_database': binding['expected_values'].get('UnitAddress') ==
                '0x' + format(int(binding['destination'].rsplit('/', 1)[1]), 'X'),
                'hardware_programmed': False}

    def recover(self, *, journal):
        state = read_journal(journal)
        if (type(state) is not dict or state.get('format') != JOURNAL_FORMAT
                or state.get('phase') not in PHASES or state.get('read_only_recovery_only') is not True):
            raise ValueError('Malformed conversion journal')
        plan = validate_plan(state['plan'])
        binding = plan['binding']
        self._endpoint(binding)
        # No PROJECT USE/CLOSE/LOAD/SAVE/COPY and no conversion or restoration.
        observation = None
        try:
            current_raw, _, _ = self._project(binding['project'])
            unchanged = _tree(_xml(current_raw)) == _tree(_xml(binding['before_project_xml']))
            try:
                observation = self._observe(binding)
            except (ValueError, RuntimeError, OSError) as error:
                observation = {'matched': False, 'project_xml': current_raw,
                               'read_error': {'type': type(error).__name__, 'message': str(error)}}
            if (state['phase'] == 'complete' and observation['matched']
                    and observation.get('allocated_oids') != state['observations'][-1].get('allocated_oids')):
                observation['matched'] = False
                observation['identity_conflict'] = True
            disposition = 'observed-converted' if observation['matched'] else ('observed-before' if unchanged else 'conflict')
        except (ValueError, RuntimeError, OSError) as error:
            observation = {'matched': False, 'read_error': {'type': type(error).__name__, 'message': str(error)}}
            disposition = 'read-unavailable'

        backup = {'backup_project': binding['backup_project'], 'backup_presence': 'unknown',
                  'backup_verified_fresh': False}
        try:
            backup_raw, backup_root, backup_project = self._project(binding['backup_project'])
            backup['backup_presence'] = 'present'
            backup['backup_xml'] = backup_raw
            before = _xml(binding['before_project_xml'])
            for key in ('Address', 'TagName'):
                original = before.find('Project/' + key)
                copied = backup_project.find(key)
                if original is not None and copied is not None:
                    copied.text = original.text
            matches_before = _tree(backup_root) == _tree(before)
            matches_retained = (not state['backup_verified'] or
                                _tree(_xml(backup_raw)) == _tree(_xml(state['backup_xml'])))
            backup['backup_verified_fresh'] = matches_before and matches_retained
            if not backup['backup_verified_fresh']:
                backup['backup_conflict'] = True
        except (ValueError, RuntimeError, OSError) as error:
            response = getattr(error, 'response', None)
            backup['backup_presence'] = 'missing' if getattr(response, 'code', None) == 401 else 'unavailable'
            backup['backup_read_error'] = {'type': type(error).__name__, 'message': str(error)}
        source_present = None
        if observation.get('project_xml'):
            tree = _xml(observation['project_xml'])
            network_number = binding['network'].rsplit('/', 1)[1]
            source_number = binding['source'].rsplit('/', 1)[1]
            source_present = any(unit.findtext('Address') == source_number
                                 for network in tree.findall('Project/Network')
                                 if network.findtext('Address') == network_number
                                 for unit in network.findall('Unit'))
        verification_complete = (state['phase'] == 'complete' and observation['matched']
                                 and backup['backup_verified_fresh'])
        return {'journal': str(Path(journal).absolute()), 'phase': state['phase'],
                'disposition': disposition, 'observation': observation,
                'project_saved': True if verification_complete else None,
                'persistence_verified': verification_complete,
                'source_present': source_present,
                'source_removed': None if source_present is None else not source_present,
                **backup,
                'read_only_recovery_only': True, 'replay_authorized': False,
                'hardware_programmed': False}


def write_plan(path, plan):
    """Create a private, exclusive fsynced review file; never overwrite."""
    _Journal(path).write(validate_plan(plan))


def read_journal(path):
    raw = _Journal(path)._read_current()
    state = _json_parse(raw)
    if (type(state) is not dict or state.get('format') != JOURNAL_FORMAT
            or state.get('phase') not in PHASES or state.get('read_only_recovery_only') is not True
            or not isinstance(state.get('history'), list) or not state['history']
            or state['history'][0] != 'prepared' or state['history'][-1] != state['phase']
            or any(phase not in PHASES for phase in state['history'])
            or any(PHASES.index(a) >= PHASES.index(b) for a, b in zip(state['history'], state['history'][1:]))
            or (state.get('project_saved') is not None and type(state.get('project_saved')) is not bool)
            or type(state.get('backup_verified')) is not bool):
        raise ValueError('Malformed conversion journal')
    validate_plan(state['plan'])
    if state['backup_verified']:
        if (not isinstance(state.get('backup_xml'), str)
                or _hash(_tree(_xml(state['backup_xml']))) != state.get('backup_sha256')):
            raise ValueError('Conversion backup snapshot hash differs')
    if type(state.get('observations')) is not list:
        raise ValueError('Malformed conversion observations')
    if state['phase'] == 'complete' and (len(state['observations']) != 2
            or any(row.get('matched') is not True for row in state['observations'])
            or state['observations'][0].get('allocated_oids') != state['observations'][1].get('allocated_oids')):
        raise ValueError('Complete journal lacks bound reopened observations')
    if state['phase'] in PHASES[PHASES.index('convert-possible'):] and not state['backup_verified']:
        raise ValueError('Conversion journal lacks mandatory verified backup')
    if state['phase'] in PHASES[PHASES.index('save-confirmed'):] and not state['project_saved']:
        raise ValueError('Conversion journal lacks confirmed save')
    return state


# Compatibility spelling used by the public CLI while the workflow landed.
read_plan = load_plan
