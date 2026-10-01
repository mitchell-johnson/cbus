#!/usr/bin/env python3
"""Public closed NET SAVE DB materialization and persistence acceptance.

Uses only owned loopback peers. Every command is an actual Toolkit subprocess
with lossless wire/output recording. Native fixture provenance is retained;
this producer itself does not launch original software or physical hardware.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import ExitStack, contextmanager
from hashlib import sha256
import json
from pathlib import Path
import re
import socket
import socketserver
import subprocess
import sys
import threading
import time
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from cbus_toolkit.simulator import PCISimulator
from research.known_serial_commissioning_journey import require, ROOT, PACKAGE
from research.known_serial_journey_support import CLIRecorder, artifact, digest, port_closed
from research.network_definition_cli_acceptance import closure as catalogue_closure, package_probe as catalogue_package_probe, recording_proxy

STARTUP = ['7e0d'] * 3 + ['7c0d', '41333231303046460d', '41333232303046460d', '41333432303030450d', '41333330303037390d']
NATIVE = ROOT / 'rust/testdata/fixtures/native_cgate_net_save_db_materialization.json'
EXPERIMENT = ROOT / 'toolkit-cli/research/experiments/2026-10-01/net-save-db-materialization-native-contract.json'


def closure():
    values = catalogue_closure()
    for relative in ('toolkit-cli/research/network_save_db_cli_acceptance.py',
                     'toolkit-cli/tests/test_cmqtt_network_save_db_cli.py',
                     'toolkit-cli/tests/test_cgate_file_upload.py',
                     'rust/testdata/fixtures/native_cgate_file.json',
                     'rust/testdata/fixtures/native_cgate_net_save_db_materialization.json',
                     'rust/cbus-cgate/research/native_net_save_db_materialization_probe.py',
                     'toolkit-cli/research/experiments/2026-10-01/net-save-db-materialization-native-contract.json'):
        path = ROOT / relative
        if path.is_file():
            values[relative] = digest(path)
    return values


def package_probe(interpreter):
    value = catalogue_package_probe(interpreter)
    code = ('import cbus_toolkit.project,cbus_toolkit.file_transfer,json; '
            'print(json.dumps(dict(project=cbus_toolkit.project.__file__,file_transfer=cbus_toolkit.file_transfer.__file__)))')
    argv = [str(interpreter), '-c', code]
    result = subprocess.run(argv, capture_output=True, text=True, check=True)
    paths = json.loads(result.stdout)
    require(all(Path(path).resolve().parent == Path(value['package_path']).resolve() for path in paths.values()),
            'Project/upload imports are outside executed package')
    value['project_upload_imports'] = paths
    value['project_upload_import_probe'] = dict(argv=argv, exit_status=result.returncode, stdout=result.stdout, stderr=result.stderr)
    return value


def native_binding():
    value = json.loads(NATIVE.read_text())
    require(value['format'] == 'cbus-native-net-save-db-materialization-v1', 'Unexpected native provenance')
    require(value.get('closed_model_only') is True and value.get('physical_or_windows_acceptance') is False,
            'Native evidence scope is not closed model only')
    require(all(digest(ROOT / name) == expected for name, expected in value['source_pins'].items()),
            'Native materialization producer pins are stale')
    return dict(fixture=artifact(NATIVE), experiment=artifact(EXPERIMENT), source_pins=value['source_pins'],
                file_protocol_fixture=artifact(ROOT / 'rust/testdata/fixtures/native_cgate_file.json'),
                raw_commands=len(value['commands']), fresh_native_execution_by_this_producer=False)


def element_model(node):
    """Compare the complete XML element, including opaque children and order."""
    return [node.tag, dict(node.attrib), node.text or '', [element_model(child) for child in node]]


def network_models(xml):
    tree = ET.fromstring(xml)
    project = tree if tree.tag == 'Project' else tree.find('Project')
    require(project is not None, 'Export has no Project')
    rows = project.findall('Network')
    names = [row.findtext('Address') for row in rows]
    require(all(names) and len(names) == len(set(names)), 'Network Address identity is absent or duplicated')
    return {name: element_model(row) for name, row in zip(names, rows)}


def materialized_rows(xml, expected):
    tree = ET.fromstring(xml)
    project = tree if tree.tag == 'Project' else tree.find('Project')
    require(project is not None, 'Export has no Project')
    nodes = project.findall('Network')
    names = [node.findtext('Address') for node in nodes]
    require(all(names) and len(names) == len(set(names)) and set(names) == set(expected),
            'Materialized Network rows do not match unique runtime names')
    rows = dict(zip(names, nodes))
    oids = []
    result = {}
    for name, facts in expected.items():
        node = rows[name]
        require(node.findtext('TagName') == facts.get('tag_name', 'n' + name), 'Generated or retained TagName differs')
        require(node.findtext('NetworkNumber') == facts.get('number', '0xff'), 'NetworkNumber is not the expected independent field')
        interface = node.find('Interface')
        require(interface is not None, 'Complete Interface missing')
        require(interface.findtext('InterfaceType') == facts['type']
                and interface.findtext('InterfaceAddress') == facts['address'], 'Materialized interface fields differ')
        properties = interface.findall('Property')
        require([(p.findtext('Name'), p.findtext('Value')) for p in properties] == facts.get('properties', []),
                'Ordered interface properties differ')
        ids = [node.findtext('OID'), interface.findtext('OID'), *[p.findtext('OID') for p in properties]]
        require(all(re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value or '') for value in ids),
                'Missing or malformed Network/Interface/Property OID')
        oids.extend(ids)
        result[name] = dict(network_oid=ids[0], interface_oid=ids[1], property_oids=ids[2:],
                            model=element_model(node), xml=ET.tostring(node, encoding='unicode'))
    require(len(oids) == len({value.lower() for value in oids}), 'Materialized object OIDs collide')
    all_oids = [node.text for node in tree.iter('OID') if node.text]
    require(len(all_oids) == len({value.lower() for value in all_oids}), 'Whole-project object OIDs collide')
    return result


def repeated_save_identity(before, after):
    require(before.keys() == after.keys(), 'Repeated SAVE changed Network membership')
    for name in before:
        first, second = before[name], after[name]
        require(first['network_oid'] == second['network_oid'] and first['interface_oid'] == second['interface_oid'],
                'Repeated SAVE replaced stable Network/Interface OIDs')
        require(len(first['property_oids']) == len(second['property_oids'])
                and {value.lower() for value in first['property_oids']}.isdisjoint(value.lower() for value in second['property_oids']),
                'Repeated SAVE did not rebuild Property OIDs as captured natively')
        expected = ET.fromstring(first['xml'])
        for node, oid in zip(expected.findall('Interface/Property/OID'), second['property_oids']):
            node.text = oid
        require(element_model(expected) == second['model'], 'Repeated SAVE changed metadata beyond fresh Property OIDs')


def require_initial_projection(before_xml, after_xml, facts):
    """Permit only the complete new rows and the witnessed schema marker."""
    result = materialized_rows(after_xml, facts)
    expected = ET.fromstring(before_xml)
    require(not expected.findall('Project/Network'), 'Initial projection baseline already has rows')
    if expected.find('DBVersion') is None:
        schema = ET.Element('DBVersion'); schema.text = '2.3'
        expected.insert(1 if expected.find('OID') is not None else 0, schema)
    project = expected.find('Project')
    for name, entry in result.items():
        row = ET.SubElement(project, 'Network')
        for key, value in (('OID', entry['network_oid']), ('TagName', 'n' + name), ('Address', name), ('NetworkNumber', '0xff')):
            ET.SubElement(row, key).text = value
        interface = ET.SubElement(row, 'Interface')
        for key, value in (('OID', entry['interface_oid']), ('InterfaceType', facts[name]['type']), ('InterfaceAddress', facts[name]['address'])):
            ET.SubElement(interface, key).text = value
        for oid, (property_name, value) in zip(entry['property_oids'], facts[name].get('properties', [])):
            prop = ET.SubElement(interface, 'Property')
            for key, text in (('OID', oid), ('Name', property_name), ('Value', value)):
                ET.SubElement(prop, key).text = text
    require(element_model(expected) == element_model(ET.fromstring(after_xml)), 'Initial SAVE changed unexpected whole-project data')
    return result


class OwnedBroker:
    """Minimal real MQTT handshake peer; never publishes a C-Bus command."""
    def __init__(self, record):
        self.record = record
        self.record.update(connections=[], packets=[], errors=[], cleanup_verified=False)
        owner = self
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                number = len(owner.record['connections'])
                owner.record['connections'].append({'sequence': number, 'closed': False})
                self.request.settimeout(.2)
                buffer = bytearray()
                try:
                    while not owner.stopping.is_set():
                        try:
                            data = self.request.recv(65536)
                        except socket.timeout:
                            continue
                        if not data:
                            break
                        buffer.extend(data)
                        while len(buffer) >= 2:
                            length, multiplier, index = 0, 1, 1
                            while index < len(buffer):
                                byte = buffer[index]; length += (byte & 127) * multiplier; index += 1
                                if not byte & 128:
                                    break
                                multiplier *= 128
                            else:
                                break
                            if len(buffer) < index + length:
                                break
                            packet = bytes(buffer[:index + length]); del buffer[:index + length]
                            kind = packet[0] >> 4
                            owner.record['packets'].append(dict(connection=number, type=kind, hex=packet.hex()))
                            if kind == 1:
                                self.request.sendall(b'\x20\x02\x00\x00')
                            elif kind == 8:
                                self.request.sendall(b'\x90\x03' + packet[index:index + 2] + b'\x00')
                            elif kind == 12:
                                self.request.sendall(b'\xd0\x00')
                            elif kind == 3 and ((packet[0] >> 1) & 3) == 1:
                                topic_size = int.from_bytes(packet[index:index + 2], 'big')
                                packet_id = packet[index + 2 + topic_size:index + 4 + topic_size]
                                self.request.sendall(b'\x40\x02' + packet_id)
                except (ConnectionResetError, BrokenPipeError):
                    pass
                except BaseException as error:
                    owner.record['errors'].append(repr(error))
                finally:
                    owner.record['connections'][number]['closed'] = True
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = False
        self.server = Server(('127.0.0.1', 0), Handler)
        self.endpoint = self.server.server_address
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopping.set(); self.server.shutdown(); self.server.server_close(); self.thread.join(5)
        self.record['cleanup_verified'] = not self.thread.is_alive() and port_closed(self.endpoint)
        require(self.record['cleanup_verified'] and not self.record['errors'], 'Owned broker cleanup failed')


@contextmanager
def owned_backend(binary, work, record):
    work.mkdir(exist_ok=False)
    project = work / 'bridge-project.xml'
    # A retained empty Lighting application admits an actual MQTT handshake
    # without triggering the daemon's fallback full-bus startup discovery.
    # Keep the exact eight-frame PCI setup guard; no status request is excused.
    project.write_text('<Installation><Project><TagName>BRIDGE_TEST</TagName><Network><Address>254</Address>'
                       '<TagName>Loopback</TagName><Application><Address>48</Address>'
                       '<TagName>Empty owned Lighting</TagName></Application></Network></Project></Installation>')
    state = work / 'durable-state.json'
    record.update(state_path=str(state), processes=[], broker={},
                  startup_status_fixture=dict(application=48, groups=[], expected_status_requests=0))
    class InitializedPCI(PCISimulator):
        def _command(self, line, context):
            if line in (b'~', b'A32100FF', b'A32200FF', b'A342000E', b'A3300079'):
                return b'', None
            return super()._command(line, context)
    with ExitStack() as resources:
        broker = resources.enter_context(OwnedBroker(record['broker']))
        pci = resources.enter_context(InitializedPCI(profile='captured', command_checksum=True,
             wire_log_path=work / 'daemon-pci-wire.jsonl').running())
        record.update(pci_endpoint=list(pci), broker_endpoint=list(broker.endpoint))
        @contextmanager
        def session():
            index = len(record['processes'])
            row = dict(index=index, process_cleanup_verified=False)
            record['processes'].append(row)
            argv = [str(binary), '--tcp', f'{pci[0]}:{pci[1]}', '--broker-address', broker.endpoint[0],
                    '--broker-port', str(broker.endpoint[1]), '--broker-disable-tls', '--timesync', '0',
                    '--status-resync', '0', '--project-file', str(project), '--cgate-bind', '127.0.0.1:0',
                    '--cgate-state', str(state)]
            row.update(argv=argv, binary=artifact(binary))
            error_file = work / f'cmqttd-{index}.stderr.log'
            output_file = work / f'cmqttd-{index}.stdout.log'
            with error_file.open('wb') as errors, output_file.open('wb') as stdout:
                process = subprocess.Popen(argv, stderr=errors, stdout=stdout)
                row['pid'] = process.pid
                endpoint = None
                try:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        found = re.search(r'C-Gate service listening on 127\.0\.0\.1:([0-9]+)', error_file.read_text(errors='replace'))
                        if found:
                            endpoint = ('127.0.0.1', int(found[1])); row['cgate_endpoint'] = list(endpoint)
                            yield endpoint
                            break
                        require(process.poll() is None, 'Owned daemon exited before readiness')
                        time.sleep(.02)
                    else:
                        raise TimeoutError('Owned daemon listener did not start')
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
                    row.update(exit_status=process.returncode, process_waited=True,
                               process_cleanup_verified=process.poll() is not None,
                               cgate_port_closed=endpoint is not None and port_closed(endpoint))
                    row.update(stderr=artifact(error_file), stdout=artifact(output_file))
        try:
            yield session
        finally:
            resources.close()
            record.update(pci_port_closed=port_closed(pci), broker_port_closed=port_closed(broker.endpoint))


@contextmanager
def owned_targets(output, report):
    """Retain target-connection and path audits even when a CLI step fails."""
    serial = output / 'absent-serial-interface'
    with socket.socket() as trap:
        trap.bind(('127.0.0.1', 0)); trap.listen(4)
        endpoint = f'127.0.0.1:{trap.getsockname()[1]}'
        try:
            yield endpoint, serial
        finally:
            trap.setblocking(False)
            connections = 0
            while True:
                try:
                    connection, _ = trap.accept()
                except BlockingIOError:
                    break
                connection.close(); connections += 1
            report.update(cni_trap_connections=connections, serial_path_absent=not serial.exists(),
                          serial_open_syscalls_assessed=False, target_guard_checked_on_exit=True)


def execute(args, report, output):
    cli = CLIRecorder(args.python, output / 'commands', cwd=ROOT / 'toolkit-cli')
    report.update(commands=cli.commands, cgate_connections=[], backend={}, proxy_sessions=[], flags={})
    project = 'NSAVEDB'
    with owned_backend(args.cmqttd_bin, output / 'daemon', report['backend']) as start, owned_targets(output, report) as (endpoint, serial):
        facts = {'42': dict(type='cni', address=endpoint), 'CustomA': dict(type='serial', address=str(serial)),
                 'Extra': dict(type='bridge', address='254/p/252', properties=[('owned', 'yes'), ('second', 'two')])}
        facts.update({name: dict(type='cni', address=endpoint) for name in ('0254', '256', '255', '0xff', 'Customa')})
        report['fixture_facts'] = facts
        pci_file = output / 'daemon/daemon-pci-wire.jsonl'
        expected_saved = None
        for phase in ('initial', 'restart'):
            cleanup = {}; report['proxy_sessions'].append(cleanup)
            with start() as daemon, recording_proxy(daemon, report['cgate_connections'], cleanup) as proxy:
                gate = ['cgate', '--host', proxy[0], '--port', proxy[1], '--timeout', 15]
                export_paths = {}
                def invoke(arguments, commands, *, expected=0, label=None, document=None, document_index=None):
                    first = len(report['cgate_connections'])
                    try:
                        result = cli.invoke([*gate, *arguments], expected=expected, label=label)
                    finally:
                        deadline = time.monotonic() + 2
                        while any(not r['closed'] for r in report['cgate_connections'][first:]) and time.monotonic() < deadline:
                            time.sleep(.005)
                        rows = report['cgate_connections'][first:]
                        cli.commands[-1]['cgate_connection_sequences'] = [r['sequence'] for r in rows]
                    require(len(rows) == 1 and rows[0]['closed'], 'CLI did not own one completed connection')
                    actual = bytes.fromhex(rows[0]['client_to_server_hex'])
                    if document is None:
                        wire = ''.join(f'[{i}] {line}\r\n' for i, line in enumerate(commands, 1)).encode()
                        cli.commands[-1]['exact_wire_verified'] = True
                    else:
                        matches = re.findall(rb'\[[0-9]+\] (?:DBSETXML|FILE UPLOAD) [^\r\n]+ << (CBUS_END_[0-9a-f]{32})\r\n', actual)
                        require(len(matches) == 1 and document_index is not None, 'Document delimiter envelope differs')
                        delimiter = matches[0]
                        parts = []
                        for index, line in enumerate(commands):
                            if index == document_index:
                                parts.append(f'[{index + 1}] {line} << '.encode() + delimiter + b'\r\n')
                                body = document.replace('\r\n', '\n').encode()
                                parts.append(body + (b'' if body.endswith(b'\n') else b'\n') + delimiter + b'\r\n')
                            else:
                                parts.append(f'[{index + 1}] {line}\r\n'.encode())
                        wire = b''.join(parts)
                        cli.commands[-1]['exact_document_wire_verified'] = True
                    require(actual == wire, 'Unexpected public command sequence or complete document')
                    (cli.directory / f"{cli.commands[-1]['sequence']:03d}-command.json").write_text(json.dumps(cli.commands[-1], indent=2) + '\n')
                    return result
                def selected(commands, *, expected=0, label):
                    script = output / (phase + '-' + label + '.cgate')
                    script.write_text('\n'.join([f'PROJECT USE {project}', *commands]) + '\n')
                    return invoke(['run', script], [f'PROJECT USE {project}', *commands], expected=expected, label=label)
                def project_op(action, name=project, other=None):
                    command = f'PROJECT {action.upper()} {name}' + (f' {other}' if other else '')
                    return invoke(['project', action, name, *([other] if other else [])], [command], label=phase + '-' + action + '-' + name)
                def export(path='//' + project, label='project-export', selected=project):
                    # Native identities are case-sensitive even on a host
                    # whose filesystem aliases CustomA and Customa filenames.
                    target = output / (f'{len(cli.commands):03d}-' + phase + '-' + label + '.xml')
                    export_paths[label] = target
                    invoke(['database', 'get-xml', path, '--project', selected, '--output', target],
                           [f'PROJECT USE {selected}', f'DBGETXML {path}'], label=label)
                    return target.read_text()
                def definition(action, name=None, selected=project):
                    arguments = ['network', 'definition', action, '--project', selected]
                    if action == 'create':
                        entry = facts[name]
                        arguments += [name, entry['type'], entry['address']]
                        options = [f'{k}={v}' for k, v in entry.get('properties', [])]
                        arguments += [arg for option in options for arg in ('--option', option)]
                        command = 'NET CREATE ' + ' '.join((name, entry['type'], entry['address'], *options))
                    elif action == 'save':
                        arguments += ['DB']; command = f'NET SAVE DB {selected}'
                    else:
                        arguments += [name]; command = f'NET {action.upper()} {name}'
                    return invoke(arguments, [f'PROJECT USE {selected}', command], label=phase + '-definition-' + action)
                invoke(['exec', 'CMQTT CAPABILITIES'], ['CMQTT CAPABILITIES'], label=phase + '-ready')
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    rows = [json.loads(line) for line in pci_file.read_text().splitlines()]
                    current_rows = [row for row in rows if row['connection'] == (0 if phase == 'initial' else 1)]
                    current = [row['hex'] for row in current_rows]
                    require(current == STARTUP[:len(current)] and all(row['direction'] == 'rx' for row in current_rows),
                            'Owned daemon issued traffic outside exact startup fixture')
                    if current == STARTUP:
                        break
                    time.sleep(.02)
                require(current == STARTUP, 'Exact owned initialization did not complete')
                checkpoint = pci_file.read_bytes()
                report.setdefault('pci_checkpoints', []).append(checkpoint.hex())
                deadline = time.monotonic() + 5
                connection = 0 if phase == 'initial' else 1
                while not any(p['type'] == 8 and p['connection'] == connection for p in report['backend']['broker']['packets']) and time.monotonic() < deadline:
                    time.sleep(.02)
                require(any(p['type'] == 1 and p['connection'] == connection for p in report['backend']['broker']['packets'])
                        and any(p['type'] == 8 and p['connection'] == connection for p in report['backend']['broker']['packets']),
                        'Owned MQTT handshake/subscription missing')
                if phase == 'restart':
                    reopened = export(label='after-daemon-restart')
                    require(element_model(ET.fromstring(reopened)) == expected_saved, 'Daemon restart lost complete saved project data')
                    report['flags']['daemon_restart_preserves_complete_rows'] = True
                else:
                    project_op('new'); project_op('save')
                    baseline = export(label='saved-empty-baseline')
                    require(not network_models(baseline), 'New baseline contains Network rows')
                    for name in facts:
                        definition('create', name)
                    definition('save')
                    first_xml = export(label='first-materialization')
                    first = require_initial_projection(baseline, first_xml, facts)
                    report['first_materialization'] = first
                    report['flags']['complete_runtime_rows_materialized'] = True
                    definition('save')
                    second_xml = export(label='repeated-materialization')
                    second = materialized_rows(second_xml, facts)
                    repeated_save_identity(first, second)
                    report['flags']['repeated_save_stable_roots_fresh_properties'] = True
                    project_op('close'); project_op('load')
                    require(element_model(ET.fromstring(export(label='unsaved-close-load'))) == element_model(ET.fromstring(baseline)),
                            'NET SAVE DB improperly crossed explicit PROJECT SAVE boundary')
                    report['flags']['explicit_project_save_boundary'] = True
                    for name in facts:
                        definition('create', name)
                    definition('save')
                    committed_xml = export(label='materialization-to-commit')
                    committed = require_initial_projection(baseline, committed_xml, facts)
                    project_op('save'); project_op('close'); project_op('load')
                    require(element_model(ET.fromstring(export(label='committed-close-load'))) == element_model(ET.fromstring(committed_xml)),
                            'Explicit project SAVE/CLOSE/LOAD lost complete rows')
                    report['flags']['project_save_close_load_preserves_complete_rows'] = True
                    for name, entry in committed.items():
                        direct = export(f'//{project}/{name}', label='direct-' + name)
                        by_oid = export('!' + entry['network_oid'], label='oid-' + name)
                        require(element_model(ET.fromstring(direct)) == entry['model']
                                and element_model(ET.fromstring(by_oid)) == entry['model'], 'Direct/OID Network read differs')
                        interface = ET.fromstring(direct).find('Interface')
                        interface_xml = export('!' + entry['interface_oid'], label='interface-oid-' + name)
                        require(element_model(ET.fromstring(interface_xml)) == element_model(interface), 'Interface OID read differs')
                        for index, property_node in enumerate(interface.findall('Property')):
                            property_xml = export('!' + entry['property_oids'][index], label=f'property-oid-{name}-{index}')
                            require(element_model(ET.fromstring(property_xml)) == element_model(property_node), 'Property OID read differs')
                    report['flags']['direct_and_oid_network_reads_equal'] = True
                    # These are public offline CLI calls, not in-process DOM assertions.
                    exported = export_paths['materialization-to-commit']
                    inspect = cli.invoke(['project', 'inspect', exported], label='offline-inspect')
                    require(inspect['counts']['network'] == len(facts) and not inspect['validation'], 'Offline reader rejects native Network rows')
                    listed = cli.invoke(['project', 'list', exported, '--kind', 'network'], label='offline-list')
                    require({row['fields']['Address'] for row in listed} == set(facts), 'Offline list collapses string Network identity')
                    for name in facts:
                        value = cli.invoke(['project', 'get', exported, '/network/' + name], label='offline-get-' + name)
                        require(value['fields']['Address'] == name and value['fields']['NetworkNumber'] == '0xff', 'Offline get conflates Address and NetworkNumber')
                    for kind in ('xml', 'cbz'):
                        target = output / ('offline-roundtrip.' + kind)
                        cli.invoke(['project', 'export', exported, target, '--format', kind], label='offline-export-' + kind)
                        if kind == 'cbz':
                            with ZipFile(target) as archive:
                                restored = archive.read(next(n for n in archive.namelist() if n.lower().endswith('.xml')))
                        else:
                            restored = target.read_bytes()
                        require(network_models(restored) == network_models(committed_xml), 'Offline export changed complete materialized rows')
                    copy_file = output / 'offline-copy-edit.xml'
                    cli.invoke(['project', 'copy', exported, '/network/CustomA', '--parent', '/',
                                '--address', 'OfflineCopy', '--name', 'Offline copy', '--output', copy_file], label='offline-copy-named')
                    copied = cli.invoke(['project', 'get', copy_file, '/network/OfflineCopy'], label='offline-get-named-copy')
                    require(copied['fields']['Address'] == 'OfflineCopy' and copied['fields']['NetworkNumber'] == '0xff',
                            'Offline copy conflates independent Network fields')
                    cli.invoke(['project', 'delete', copy_file, '/network/OfflineCopy'], label='offline-delete-named-copy')
                    require(network_models(copy_file.read_text()) == network_models(committed_xml), 'Offline named copy/delete changed original rows')
                    report['flags']['offline_cli_preserves_native_rows'] = True
                    # Metadata field changes address the database independently
                    # of the closed runtime catalogue; OID operations select it
                    # explicitly on the same public command-file connection.
                    path = f'//{project}/CustomA'
                    before_unselected = export(label='before-unselected-named-mutation')
                    refused = invoke(['database', 'set', path + '/TagName', 'UnselectedEdit'],
                                     [f'DBSETSAFE {path}/TagName UnselectedEdit'], expected=1,
                                     label='unselected-named-mutation-refusal')
                    require(refused.get('type') == 'CGateError'
                            and re.match(r'C-Gate error: 401(?:\s|$)', refused.get('error', '')),
                            'Unselected known named mutation did not produce exact 401')
                    require(element_model(ET.fromstring(export(label='after-unselected-named-mutation')))
                            == element_model(ET.fromstring(before_unselected)),
                            'Refused unselected mutation changed the complete target project')
                    report['flags']['unselected_named_mutation_refused_without_change'] = True
                    report['unselected_named_mutation_scope'] = (
                        'cmqttd refusal when a known named tag project is not selected; '
                        'native 126-command evidence covers explicitly selected successful mutations only')
                    selected([f'DBSET {path}/TagName NamedEdit'], label='named-field-edit')
                    edited = ET.fromstring(export(path, label='after-named-field-edit'))
                    require(edited.findtext('TagName') == 'NamedEdit' and edited.findtext('OID') == committed['CustomA']['network_oid'],
                            'Named field mutation lost Network identity')
                    selected(['DBSET !' + committed['CustomA']['network_oid'] + '/TagName OidEdit'], label='oid-field-edit')
                    edited = ET.fromstring(export(path, label='after-oid-field-edit'))
                    require(edited.findtext('TagName') == 'OidEdit', 'OID field mutation was not visible in complete row')
                    ET.SubElement(edited, 'Description').text = 'Retained public materialization metadata'
                    xml_path = output / 'edited-named-network.xml'
                    document = ET.tostring(edited, encoding='unicode')
                    xml_path.write_text(document)
                    invoke(['database', 'set-xml', path, xml_path, '--project', project, '--readback'],
                           [f'PROJECT USE {project}', f'DBSETXML {path}', f'DBGETXML {path}'],
                           document=document, document_index=1, label='complete-named-row-edit')
                    require(element_model(ET.fromstring(export(path, label='after-complete-named-row-edit'))) == element_model(edited),
                            'Complete named row mutation dropped metadata')
                    definition('save')
                    saved_edit = ET.fromstring(export(path, label='after-save-existing-named-row'))
                    require(saved_edit.findtext('TagName') == 'OidEdit' and saved_edit.findtext('Description') == edited.findtext('Description')
                            and saved_edit.findtext('OID') == committed['CustomA']['network_oid']
                            and saved_edit.findtext('Interface/OID') == committed['CustomA']['interface_oid'],
                            'SAVE existing row lost metadata or stable root identities')
                    report['flags']['named_oid_and_complete_xml_mutations_preserved'] = True
                    selected(['DBDELETE !' + committed['CustomA']['network_oid']], label='delete-by-issued-oid')
                    without = network_models(export(label='whole-tree-after-oid-delete'))
                    require('CustomA' not in without and set(without) == set(facts) - {'CustomA'}, 'OID delete failed whole-project removal')
                    # cmqttd's fresh tree lookup intentionally does not expose
                    # the stale native named-snippet cache observed after delete.
                    for selector, label in ((path, 'fresh-named-after-oid-delete'),
                                             ('!' + committed['CustomA']['network_oid'], 'fresh-network-oid-after-delete'),
                                             ('!' + committed['CustomA']['interface_oid'], 'fresh-interface-oid-after-delete')):
                        missing = invoke(['database', 'get-xml', selector, '--project', project],
                                         [f'PROJECT USE {project}', f'DBGETXML {selector}'], expected=1, label=label)
                        require(missing.get('type') == 'CGateError'
                                and re.match(r'C-Gate error: 401(?:\s|$)', missing.get('error', '')),
                                'Deleted object did not produce exact 401 through its named or issued-OID selector')
                    report['native_named_snippet_cache_scope'] = 'Original OID deletion can leave a stale named snippet; cmqttd reads its current complete tree'
                    definition('save')
                    remade_xml = export(label='rematerialized-after-oid-delete')
                    remade = materialized_rows(remade_xml, facts)
                    require(remade['CustomA']['network_oid'] != committed['CustomA']['network_oid']
                            and remade['CustomA']['interface_oid'] != committed['CustomA']['interface_oid'],
                            'Rematerialization reused deleted Network/Interface OIDs')
                    report['flags']['oid_delete_and_fresh_rematerialization'] = True
                    # Explicit other-project SAVE and local repository/archive
                    # workflows retain the complete tag rows. These are cmqttd
                    # model assertions, not Schneider archive/schema interchange.
                    project_op('new', 'NSOTHER')
                    empty_other = export('//NSOTHER', label='other-before-save', selected='NSOTHER')
                    require(not network_models(empty_other), 'Other project baseline not empty')
                    facts['Other'] = dict(type='cni', address=endpoint)
                    definition('create', 'Other', selected='NSOTHER'); definition('save', selected='NSOTHER')
                    other = export('//NSOTHER', label='other-after-save', selected='NSOTHER')
                    materialized_rows(other, {'Other': facts.pop('Other')})
                    require(element_model(ET.fromstring(export(label='main-after-other-save'))) == element_model(ET.fromstring(remade_xml)),
                            'Other project materialization mutated selected main project')
                    report['flags']['explicit_project_isolation'] = True
                    project_op('save')
                    final_xml = export(label='final-saved-main')
                    expected_saved = element_model(ET.fromstring(final_xml))
                    expected_rows = network_models(final_xml)
                    project_op('copy', project, 'NSCOPY')
                    require(network_models(export('//NSCOPY', label='project-copy', selected='NSCOPY')) == expected_rows,
                            'Project copy lost complete named Network rows')
                    project_op('archive', project, 'cmqttd:net-save-db-slot')
                    project_op('restore', 'NSARCH', 'cmqttd:net-save-db-slot')
                    require(network_models(export('//NSARCH', label='project-archive-restored', selected='NSARCH')) == expected_rows,
                            'Local project archive/restore lost complete named rows')
                    invoke(['exec', 'REPOSITORY USE 1'], ['REPOSITORY USE 1'], label='select-local-repository')
                    require(element_model(ET.fromstring(export(label='after-repository-use'))) == expected_saved, 'Repository selection lost complete project data')
                    source_xml = export_paths['final-saved-main']
                    from cbus_toolkit.file_transfer import prepare_upload
                    upload_plan = prepare_upload('netsave.xml', source_xml, project=project)
                    invoke(['file-upload', 'netsave.xml', source_xml, '--project', project],
                           [f'PROJECT USE {project}', 'FILE UPLOAD netsave.xml'], document=upload_plan.document,
                           document_index=1, label='upload-portable-transform-source')
                    for command in ('TRANSFORM XML_TO_SQL netsave netsavedb', 'TRANSFORM MIGRATE_SQL netsavedb',
                                    'TRANSFORM SQL_TO_XML netsavedb netsaveback'):
                        result = invoke(['exec', command], [command], label='portable-' + command.split()[1])
                        require(result.get('status') == 200, 'Portable transform did not complete exactly')
                    downloaded = invoke(['exec', 'FILE DOWNLOAD netsaveback.xml'], ['FILE DOWNLOAD netsaveback.xml'], label='portable-download')
                    payload = ''.join(line[4:] for line in downloaded['lines'] if line.startswith('347-'))
                    require(downloaded.get('status') == 346 and element_model(ET.fromstring(base64.b64decode(payload, validate=True))) == expected_saved,
                            'Portable SQLite XML roundtrip lost complete string-addressed Network rows')
                    report['flags']['copy_archive_repository_portable_transform_preserves_rows'] = True
                    report['portable_container_scope'] = 'cmqttd own JSON repository and portable SQLite FILE container; not vendor repository/schema interchange'
                require(pci_file.read_bytes() == checkpoint, 'Database workflow emitted post-startup PCI traffic')
                report.setdefault('pci_unchanged_per_session', []).append(True)
        require(len(report['backend']['broker']['connections']) == len(report['backend']['processes']),
                'Database workflow created an extra MQTT connection')
        report['flags']['mqtt_one_connection_per_owned_daemon'] = True
    # Retain the phase checks above and also cover traffic emitted while the
    # daemon and its peers close. The complete log may contain only the two
    # owned startup sequences, including their literal direction and order.
    final_pci_bytes = pci_file.read_bytes()
    final_pci_rows = [json.loads(line) for line in final_pci_bytes.splitlines()]
    require([(row['connection'], row['direction'], row['hex']) for row in final_pci_rows]
            == [(connection, 'rx', frame) for connection in (0, 1) for frame in STARTUP],
            'Complete PCI log after cleanup differs from the two literal startup sequences')
    report['pci_final_after_cleanup_hex'] = final_pci_bytes.hex()
    report['flags']['literal_pci_after_cleanup_verified'] = True
    require(report['cni_trap_connections'] == 0, 'Closed model workflow connected to materialized CNI')
    require(report['serial_path_absent'], 'Closed model workflow created synthetic serial path')
    require(all(row['process_cleanup_verified'] and row['cgate_port_closed'] for row in report['backend']['processes'])
            and report['backend']['pci_port_closed'] and report['backend']['broker_port_closed'], 'Owned backend cleanup incomplete')
    report['completed'] = True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cmqttd-bin', type=Path, required=True)
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--baseline-binaries', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if output.exists() or output.is_relative_to(ROOT) or not output.parent.is_dir():
        parser.error('Use a fresh private raw directory outside Git')
    output.mkdir(mode=0o700)
    args.python = args.python.absolute(); args.cmqttd_bin = args.cmqttd_bin.resolve()
    report = dict(format='cbus-network-save-db-cli-acceptance-v1', result='failed', hardware_io=False,
                  native_process_launched=False, full_cgate_parity=False, full_toolkit_parity=False,
                  source_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  producer_argv=[sys.executable, *sys.argv], producer_arguments=list(sys.argv[1:] if argv is None else argv),
                  producer_entry='standalone' if argv is None else 'in_process_harness')
    try:
        report.update(source_before=closure(), package_before=package_probe(args.python), binary_before=artifact(args.cmqttd_bin),
                      native_fixture_binding=native_binding())
        if args.baseline_binaries:
            report['baseline_binary_provenance'] = artifact(args.baseline_binaries)
        if Path(report['package_before']['package_path']).resolve() != PACKAGE.resolve():
            require(args.wheel is not None, 'Installed package acceptance requires exact wheel')
        if args.wheel:
            report['wheel_before'] = artifact(args.wheel)
            with ZipFile(args.wheel) as archive:
                actual = {name.removeprefix('cbus_toolkit/'): sha256(archive.read(name)).hexdigest()
                          for name in archive.namelist() if name.startswith('cbus_toolkit/') and Path(name).suffix in ('.py', '.json')}
            require(actual == report['package_before']['package_files'], 'Executed package does not match wheel')
        execute(args, report, output)
        report['result'] = 'passed'
    except BaseException as error:
        report['error'] = dict(type=type(error).__name__, message=str(error))
        raise
    finally:
        if 'source_before' in report:
            report['inputs_unchanged'] = False
            try:
                report.update(source_after=closure(), package_after=package_probe(args.python), binary_after=artifact(args.cmqttd_bin))
                unchanged = (report['source_before'] == report['source_after'] and report['package_before'] == report['package_after']
                             and report['binary_before'] == report['binary_after'])
                if args.wheel:
                    report['wheel_after'] = artifact(args.wheel); unchanged &= report['wheel_before'] == report['wheel_after']
                if args.baseline_binaries:
                    report['baseline_binary_provenance_after'] = artifact(args.baseline_binaries)
                    unchanged &= report['baseline_binary_provenance'] == report['baseline_binary_provenance_after']
                report['inputs_unchanged'] = unchanged
                if not unchanged and report['result'] == 'passed':
                    report.update(result='failed', error=dict(type='InputBindingError', message='Acceptance inputs changed'))
            except BaseException as error:
                report['input_recheck_error'] = dict(type=type(error).__name__, message=str(error))
                if report['result'] == 'passed':
                    report.update(result='failed', error=report['input_recheck_error'])
        report['retained_files'] = {str(p.relative_to(output)): artifact(p) for p in output.rglob('*') if p.is_file()}
        (output / 'acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    require(report['result'] == 'passed', 'Acceptance did not pass')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
