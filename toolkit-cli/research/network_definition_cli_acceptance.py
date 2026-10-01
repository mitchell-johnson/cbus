#!/usr/bin/env python3
"""Public CLI network-new/definition lifecycle on an owned cmqttd service.

Records full subprocess and literal C-Gate traffic. All network definitions
stay closed. An owned endpoint trap detects connections and a separate daemon
PCI wire log detects post-startup traffic. A missing Serial path remaining
absent is a filesystem observation, not syscall tracing of attempted opens.
Original vendor lifecycle fixture bindings are provenance, not fresh native
execution or evidence for unobserved network/interface combinations.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
import re
from pathlib import Path
import select
import socket
import socketserver
import subprocess
import sys
import threading
import time
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from research.known_serial_commissioning_journey import fingerprint, package_probe as commissioning_package_probe, require, ROOT, PACKAGE
from research.known_serial_journey_support import CLIRecorder, artifact, digest, owned_cmqttd, port_closed


@contextmanager
def recording_proxy(target, capture, cleanup):
    """Lossless forwarding for only this owned fixture's C-Gate endpoint."""
    errors = []
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            row = {'sequence': len(capture), 'client_to_server_hex': '', 'server_to_client_hex': '', 'closed': False}
            capture.append(row)
            try:
                with socket.create_connection(target, timeout=5) as upstream:
                    streams = (self.request, upstream)
                    while True:
                        ready = select.select(streams, [], [], 5)[0]
                        if not ready:
                            raise TimeoutError('Owned proxy stalled')
                        for source in ready:
                            data = source.recv(65536)
                            if not data:
                                row['closed'] = True
                                return
                            key = 'client_to_server_hex' if source is self.request else 'server_to_client_hex'
                            row[key] += data.hex()
                            (upstream if source is self.request else self.request).sendall(data)
            except (ConnectionResetError, BrokenPipeError):
                row['closed'] = True
            except Exception as error:
                errors.append(repr(error))
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    server = Server(('127.0.0.1', 0), Handler)
    endpoint = server.server_address
    cleanup.update(endpoint=list(endpoint), completed=False)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown(); server.server_close(); thread.join(5)
        cleanup.update(thread_stopped=not thread.is_alive(), port_closed=port_closed(endpoint),
                       errors=errors, completed=True)
        require(not thread.is_alive() and not errors, 'Owned recording proxy failed: ' + repr(errors))


def closure():
    value = fingerprint()
    for relative in ('toolkit-cli/research/network_definition_cli_acceptance.py',
                     'toolkit-cli/tests/test_cmqtt_network_new_cli.py',
                     'toolkit-cli/Makefile', '.github/workflows/ci.yml',
                     'rust/testdata/fixtures/native_cgate_net_lifecycle.json',
                     'rust/testdata/fixtures/native_cgate_net_db_reconciliation.json',
                     'rust/cbus-cgate/research/native_net_db_reconciliation_probe.py',
                     'rust/testdata/fixtures/native_cgate_net_save_db_materialization.json',
                     'rust/testdata/vectors/cgate_net_save_db_materialization.jsonl',
                     'rust/cbus-cgate/research/native_net_save_db_materialization_probe.py',
                     'toolkit-cli/research/experiments/2026-10-01/net-save-db-materialization-native-contract.json',
                     'toolkit-cli/research/network_save_db_cli_acceptance.py',
                     'toolkit-cli/tests/test_cmqtt_network_save_db_cli.py',
                     'toolkit-cli/research/fixtures/project-legacy-transform-historical-native-d217b0d2.zip',
                     'toolkit-cli/research/local_cgate.py',
                     'toolkit-cli/research/experiments/2026-10-01/net-db-reconciliation-native-contract.json',
                     'rust/testdata/fixtures/native_cgate_cgl_routes.json',
                     'rust/testdata/fixtures/native_cgate_programmer_lifecycle.json'):
        path = ROOT / relative
        if path.is_file():
            value[relative] = digest(path)
    return value


def package_probe(interpreter):
    observed = commissioning_package_probe(interpreter)
    code = ('import cbus_toolkit.native,cbus_toolkit.network_definitions,json; '
            'print(json.dumps(dict(native_path=cbus_toolkit.native.__file__,'
            'network_definitions_path=cbus_toolkit.network_definitions.__file__)))')
    argv = [str(interpreter), '-c', code]
    result = subprocess.run(argv, capture_output=True, check=True, text=True)
    modules = json.loads(result.stdout)
    root = Path(observed['package_path']).resolve()
    require(all(Path(path).resolve().parent == root for path in modules.values()),
            'Actual network/native imports are outside the observed package')
    observed['network_modules'] = modules
    observed['network_module_probe'] = {'argv': argv, 'exit_status': result.returncode,
                                        'stdout': result.stdout, 'stderr': result.stderr}
    return observed


def listed_names(response):
    require(response.get('status') in (131, 132), 'Unexpected network list status')
    names = sorted(re.findall(r'network=([^\s]+)', '\n'.join(response.get('lines', ()))))
    require(len(names) == len(set(names)), 'Runtime catalogue contains duplicate names')
    require((response['status'] == 132) == (not names), 'Empty/nonempty list envelope disagrees')
    require(all('InterfaceState=closed' in line for line in response.get('lines', ()) if 'network=' in line),
            'Runtime catalogue contains an opened interface')
    return names


def native_fixture_binding():
    path = ROOT / 'rust/testdata/fixtures/native_cgate_net_db_reconciliation.json'
    value = json.loads(path.read_text())
    require(value.get('format') == 'cbus-native-net-db-reconciliation-v1'
            and value.get('closed_model_only') is True
            and value.get('physical_or_windows_acceptance') is False,
            'Original fixture has an unexpected provenance/scope envelope')
    pins = value.get('source_pins', {})
    require(pins and all(digest(ROOT / name) == expected for name, expected in pins.items()),
            'Original fixture probe/helper source pins are stale')
    experiment = ROOT / 'toolkit-cli/research/experiments/2026-10-01/net-db-reconciliation-native-contract.json'
    return {'fixture': artifact(path), 'contract_experiment': artifact(experiment),
            'source_pins': pins, 'oracle': value['oracle'],
            'command_count': len(value['commands']), 'fresh_native_execution_by_this_producer': False}


def network_fields(xml, project, network):
    tree = ET.fromstring(xml)
    node = tree.find(f"Project/Network[Address='{network}']") if tree.tag == 'Installation' else tree
    require(node is not None and node.tag == 'Network', 'Network absent from exported model')
    result = {field: node.findtext(field) for field in ('OID', 'TagName', 'Address', 'NetworkNumber')}
    result.update({field: node.findtext('Interface/' + field) for field in ('InterfaceType', 'InterfaceAddress')})
    result['InterfaceOID'] = node.findtext('Interface/OID')
    require(result['OID'] and result['InterfaceOID'], 'Network/Interface OIDs missing')
    require(result['Address'] == str(network) and result['NetworkNumber'] == str(network), 'Network numeric identity changed')
    return result


def execute(args, report, output):
    cli = CLIRecorder(args.python, output / 'commands', cwd=ROOT / 'toolkit-cli')
    report.update(commands=cli.commands, cgate_connections=[], backend={}, proxy_cleanup={}, completed=False)
    with owned_cmqttd(args.cmqttd_bin, output / 'daemon', report['backend']) as daemon_port, \
            socket.socket() as trap, recording_proxy(('127.0.0.1', daemon_port), report['cgate_connections'], report['proxy_cleanup']) as proxy:
        trap.bind(('127.0.0.1', 0)); trap.listen(4)
        trap_endpoint = f'127.0.0.1:{trap.getsockname()[1]}'
        report['unopened_cni_endpoint_trap'] = list(trap.getsockname())
        report['recording_proxy_endpoint'] = list(proxy)
        gate = ['cgate', '--host', proxy[0], '--port', proxy[1], '--timeout', 15]
        def invoke(arguments, expected=0, label=None, exact_commands=None):
            first = len(report['cgate_connections'])
            try:
                try:
                    value = cli.invoke([*gate, *arguments], expected=0 if expected is None else expected, label=label)
                except AssertionError:
                    if expected is not None:
                        raise
                    row = cli.commands[-1]
                    # A baseline GET may legitimately be absent in generic
                    # dispatch. Observe only a confirmed failure of command2,
                    # never a failed selection, timeout or malformed response.
                    require(row.get('exit_status') == 1, 'Generic GET baseline did not complete with a known exit')
                    value = json.loads(row['stderr_utf8'] or row['stdout_utf8'])
                    require(value.get('type') == 'BatchCommandError'
                            and value.get('completed_count') == 1 and value.get('failed_command_index') == 2
                            and value.get('error', '').startswith('C-Gate error: ')
                            and value.get('completed_responses', [{}])[0].get('status') == 200,
                            'Generic GET baseline failed outside its confirmed read response')
                if expected is None:
                    cli.commands[-1]['expected_exit_status'] = cli.commands[-1]['exit_status']
                    cli.commands[-1]['baseline_response_observation'] = True
                    cli.commands[-1]['baseline_exit_policy'] = 'Observe success0 or confirmed command2 generic GET refusal1'
            finally:
                # Retain exact traffic even when CLIRecorder raises for a
                # genuinely unexpected exit. The evidence remains inspectable.
                limit = time.monotonic() + 2
                while any(not row['closed'] for row in report['cgate_connections'][first:]) and time.monotonic() < limit:
                    time.sleep(.005)
                rows = report['cgate_connections'][first:]
                cli.commands[-1]['cgate_connection_sequences'] = [row['sequence'] for row in rows]
                command_path = cli.directory / f"{cli.commands[-1]['sequence']:03d}-command.json"
                command_path.write_text(json.dumps(cli.commands[-1], indent=2) + '\n')
            if exact_commands is not None:
                require(len(rows) == 1 and rows[0]['closed'], 'CLI operation did not own one completed C-Gate connection')
                actual = b''.join(bytes.fromhex(row['client_to_server_hex']) for row in rows)
                expected_wire = b''.join(f'[{index}] {command}\r\n'.encode() for index, command in enumerate(exact_commands, 1))
                require(actual == expected_wire, f'Unexpected exact CLI command sequence: {actual!r}')
                cli.commands[-1]['exact_wire_sequence_verified'] = True
                command_path.write_text(json.dumps(cli.commands[-1], indent=2) + '\n')
            return value
        def export(project, label):
            target = output / (label + '.xml')
            invoke(['database', 'get-xml', '//' + project, '--project', project, '--output', target], label=label,
                   exact_commands=[f'PROJECT USE {project}', f'DBGETXML //{project}'])
            return target.read_text()
        base = ['network', 'definition']
        report['definition_lifecycle'] = []
        def definition(action, arguments=(), *, project='NEWNET', expected=0, label=None):
            # Expected commands are literal protocol contracts, independent of
            # the product's definition_command implementation.
            if action == 'list':
                wire = f'NET LIST {project}'
            elif action in ('load', 'save'):
                wire = f'NET {action.upper()} {arguments[0]} {project}'
            elif action == 'create':
                wire = 'NET CREATE ' + ' '.join(arguments[:3])
                require(all(arguments[index] == '--option' for index in range(3, len(arguments), 2)),
                        'Producer option syntax is malformed')
                wire += ''.join(' ' + arguments[index] for index in range(4, len(arguments), 2))
            else:
                wire = f'NET {action.upper()} ' + ' '.join(argument for argument in arguments if argument != '--no-fix-references')
                if '--no-fix-references' in arguments:
                    wire += ' nofixrefs'
            value = invoke([*base, action, '--project', project, *arguments], expected=expected,
                           label=label or 'definition-' + action,
                           exact_commands=[f'PROJECT USE {project}', wire])
            report['definition_lifecycle'].append({'action': action, 'project': project, 'response': value,
                                                   'command_sequence': cli.commands[-1]['sequence']})
            return value
        def names(*, project='NEWNET', label=None):
            return listed_names(definition('list', project=project, label=label))
        def property_value(name, attribute, expected):
            value = invoke(['exec', f'GET //NEWNET/{name} {attribute}'], label='get-' + name + '-' + attribute,
                           exact_commands=[f'GET //NEWNET/{name} {attribute}'])
            require(value.get('status') == 300 and any(line.endswith(attribute + '=' + expected) for line in value.get('lines', ())),
                    f'{name} runtime {attribute} does not match {expected!r}')
            return value
        # The daemon always initializes its own separate PCI. Establish the
        # checkpoint after that connection is ready, before any model operation.
        for attempt in range(30):
            capabilities = invoke(['exec', 'CMQTT CAPABILITIES'], label=f'fixture-ready-{attempt}',
                                  exact_commands=['CMQTT CAPABILITIES'])
            lines = capabilities.get('lines', []) if isinstance(capabilities, dict) else []
            payloads = [line[4:] for line in lines if len(line) > 4 and line[:3].isdigit() and line[3] in '- ' and line[4:].startswith('{')]
            if payloads and json.loads(payloads[-1]).get('pci_connected') is True:
                break
            time.sleep(.05)
        else:
            raise AssertionError('Owned daemon PCI did not become ready')
        wire_path = output / 'daemon/daemon-pci-wire.jsonl'
        expected_startup = ['7e0d', '7e0d', '7e0d', '7c0d', '41333231303046460d',
                            '41333232303046460d', '41333432303030450d', '41333330303037390d']
        # pci_connected is published before asynchronous setup finishes. Wait
        # for the independently expected literal initialization transcript
        # before the first model command, rather than hiding its later frames.
        startup_deadline = time.monotonic() + 10
        while time.monotonic() < startup_deadline:
            startup_bytes = wire_path.read_bytes() if wire_path.exists() else b''
            startup = [json.loads(line) for line in startup_bytes.splitlines()]
            observed = [row.get('hex') for row in startup]
            require(observed == expected_startup[:len(observed)]
                    and all(row.get('direction') == 'rx' and row.get('connection') == 0 for row in startup),
                    'Owned daemon issued traffic outside exact startup fixture')
            if observed == expected_startup:
                break
            time.sleep(.02)
        else:
            raise AssertionError('Owned daemon literal PCI initialization did not finish')
        report['daemon_pci_initialization_verified_before_model_commands'] = True
        before_wire = wire_path.read_bytes() if wire_path.exists() else b''
        report['daemon_pci_before_hex'] = before_wire.hex()
        project = 'NEWNET'
        invoke(['project', 'new', project], label='new-project', exact_commands=[f'PROJECT NEW {project}'])
        if not args.network_new_only:
            require(names(label='empty-list') == [], 'New project catalogue not empty')
            definition('load', ['DB'], label='empty-db-load')
            require(names(label='empty-list-after-db') == [], 'Empty DB load manufactured a runtime definition')
            definition('load', ['FILE'], label='empty-missing-file')
            require(names(label='empty-list-after-missing-file') == [], 'Missing FILE manufactured a runtime definition')
            report['empty_db_and_missing_file_loads_are_noop'] = True
        definitions = ((240, 'OwnedCni', 'Cni', trap_endpoint),
                       (241, 'OwnedSerial', 'Serial', str(output / 'unopened-serial')),
                       (242, 'OwnedBridge', 'Bridge', '240/p/242'))
        report['network_new_cases'] = []
        for address, name, kind, endpoint in definitions:
            creation = invoke(['database', 'network-new', project, address, name, kind, endpoint], label='network-new-' + kind,
                              exact_commands=[f'PROJECT USE {project}', f'DBCREATENET {address} {name} {kind} {endpoint}', 'NET LOAD DB'])
            loaded = export(project, 'loaded-' + kind)
            fields = network_fields(loaded, project, address)
            require(fields['TagName'] == name and fields['InterfaceType'].lower() == kind.lower()
                    and fields['InterfaceAddress'] == endpoint, 'Network-new fields differ from explicit arguments')
            closed = invoke(['exec', f'GET //{project}/{address} InterfaceState'], label='closed-' + kind,
                            exact_commands=[f'GET //{project}/{address} InterfaceState'])
            require('InterfaceState=closed' in json.dumps(closed), 'Created model interface is not closed')
            report['network_new_cases'].append({'interface_type': kind, 'fields': fields, 'closed': True,
                                                 'creation_response': creation})
            if not args.network_new_only:
                property_value(str(address), 'Name', str(address))
                property_value(str(address), 'Type', kind)
                property_value(str(address), 'Interface', endpoint)
                expected_names = sorted(str(case['fields']['Address']) for case in report['network_new_cases'])
                require(names(label='sequential-list-' + kind) == expected_names, 'Sequential DB load lost an earlier network')
        original = export(project, 'before-save')
        invoke(['project', 'save', project], label='save-new-networks', exact_commands=[f'PROJECT SAVE {project}'])
        invoke(['project', 'close', project], label='close-new-networks', exact_commands=[f'PROJECT CLOSE {project}'])
        invoke(['project', 'load', project], label='reload-new-networks', exact_commands=[f'PROJECT LOAD {project}'])
        reopened = export(project, 'reopened-new-networks')
        require(reopened == original, 'Saved/reopened network XML differs')
        report['saved_reopened_xml_equal'] = True
        # Duplicate admission must not replace the retained first identity or
        # silently rebind its interface. Exact native error text is retained.
        invoke(['database', 'network-new', project, 240, 'Replacement', 'Cni', trap_endpoint], expected=1,
               label='duplicate-network-refusal', exact_commands=[f'PROJECT USE {project}', f'DBCREATENET 240 Replacement Cni {trap_endpoint}'])
        require(export(project, 'after-duplicate-refusal') == reopened, 'Duplicate network changed the saved model')
        if not args.network_new_only:
            report['reserved_and_oid_get_dispatch_preserved'] = False
            collision_names = ('cgate', 'projects', 'cbus', '!' + report['network_new_cases'][0]['fields']['OID'])
            report['generic_get_collision_checks'] = []
            baseline = []
            def generic_get(name, field, label, expected):
                script = output / (label + '.cgate')
                script.write_text(f'PROJECT USE NEWNET\nGET {name} {field}\n')
                value = invoke(['run', script], expected=expected, label=label,
                               exact_commands=['PROJECT USE NEWNET', f'GET {name} {field}'])
                if cli.commands[-1]['exit_status'] == 0:
                    require(isinstance(value, list) and len(value) == 2 and value[0].get('status') == 200,
                            'Generic GET did not retain both exact selected-session replies')
                return value, cli.commands[-1]
            for index, name in enumerate(collision_names):
                for field in ('Name', 'Type'):
                    value, command = generic_get(name, field, f'generic-get-before-{index}-{field}', None)
                    baseline.append((name, field, value, command))
            for index, name in enumerate(collision_names):
                definition('create', [name, 'cni', trap_endpoint], label=f'create-legal-get-collision-{index}')
            for index, (name, field, before, before_command) in enumerate(baseline):
                # Observe both possible exits after the mutation as well, then
                # require the exact baseline exit and full returned payload.
                after, after_command = generic_get(name, field, f'generic-get-after-{index}-{field}', None)
                check = {'selector': name, 'field': field,
                         'before_command_sequence': before_command['sequence'],
                         'after_command_sequence': after_command['sequence'],
                         'before_exit': before_command['exit_status'], 'after_exit': after_command['exit_status'],
                         'before_response': before, 'after_response': after,
                         'full_response_equal': before == after,
                         'stdout_bytes_equal': before_command['stdout_hex'] == after_command['stdout_hex'],
                         'stderr_bytes_equal': before_command['stderr_hex'] == after_command['stderr_hex']}
                report['generic_get_collision_checks'].append(check)
                require(check['before_exit'] == check['after_exit'] and check['full_response_equal']
                        and check['stdout_bytes_equal'] and check['stderr_bytes_equal'],
                        f'Legal runtime definition shadowed generic GET {name} {field}')
            for name in collision_names:
                property_value(name, 'Name', name)
                property_value(name, 'Type', 'cni')
                definition('delete', [name], label='delete-legal-get-collision-' + name)
            require(names(label='catalogue-after-get-collision-cleanup') == ['240', '241', '242'],
                    'Generic GET collision fixture cleanup changed original catalogue')
            report['reserved_and_oid_get_dispatch_preserved'] = True
            report['generic_get_scope'] = 'Generic bare and !OID responses preserved; runtime metadata read only through exact //PROJECT/NAME paths'
            initial_names = names(label='before-missing-file')
            definition('load', ['FILE'], label='nonempty-missing-file')
            require(names(label='after-missing-file') == initial_names, 'Missing FILE load changed nonempty catalogue')
            report['missing_file_nonempty_noop'] = True
            definition('create', ['Extra', 'cni', trap_endpoint, '--option', 'alpha=beta', '--option', 'baud=9600'])
            property_value('Extra', 'Options', 'alpha=beta baud=9600')
            definition('rename', ['Extra', 'Alias', '--no-fix-references'], label='rename-nofixrefs')
            property_value('Alias', 'Options', 'alpha=beta baud=9600')
            definition('flush', ['Alias'])
            definition('save', ['DB'])
            db_saved = export(project, 'after-definition-save-db')
            from research.network_save_db_cli_acceptance import element_model, materialized_rows, native_binding
            report['native_materialization_fixture_binding'] = native_binding()
            actual_tree = ET.fromstring(db_saved)
            original_tree = ET.fromstring(reopened)
            alias = actual_tree.find("Project/Network[Address='Alias']")
            require(alias is not None, 'NET SAVE DB did not materialize custom Alias')
            alias_document = '<Installation><Project>' + ET.tostring(alias, encoding='unicode') + '</Project></Installation>'
            alias_facts = materialized_rows(alias_document, {'Alias': dict(type='cni', address=trap_endpoint,
                                             properties=[('alpha', 'beta'), ('baud', '9600')])})['Alias']
            prior_oids = {node.text for node in original_tree.iter('OID')}
            require(not prior_oids.intersection([alias_facts['network_oid'], alias_facts['interface_oid'], *alias_facts['property_oids']]),
                    'New materialization reused an existing project OID')
            # Build the complete expected projection independently: all old
            # model nodes remain, the newly explicit native schema marker is
            # known, and only the fully validated generated Alias is appended.
            expected_tree = ET.fromstring(reopened)
            if expected_tree.find('DBVersion') is None:
                schema = ET.Element('DBVersion'); schema.text = '2.3'
                expected_tree.insert(1 if expected_tree.find('OID') is not None else 0, schema)
            expected_alias = ET.Element('Network')
            for field, value in (('OID', alias_facts['network_oid']), ('TagName', 'nAlias'), ('Address', 'Alias'), ('NetworkNumber', '0xff')):
                ET.SubElement(expected_alias, field).text = value
            expected_interface = ET.SubElement(expected_alias, 'Interface')
            for field, value in (('OID', alias_facts['interface_oid']), ('InterfaceType', alias.findtext('Interface/InterfaceType')),
                                 ('InterfaceAddress', trap_endpoint)):
                ET.SubElement(expected_interface, field).text = value
            for oid, (name, value) in zip(alias_facts['property_oids'], [('alpha', 'beta'), ('baud', '9600')]):
                prop = ET.SubElement(expected_interface, 'Property')
                for field, text in (('OID', oid), ('Name', name), ('Value', value)):
                    ET.SubElement(prop, field).text = text
            expected_tree.find('Project').append(expected_alias)
            require(element_model(actual_tree) == element_model(expected_tree),
                    'NET SAVE DB whole-project projection changed existing or unexpected model data')
            report['definition_save_db_preserves_existing_network_fields'] = True
            report['net_save_db_materializes_custom_tag_row'] = True
            report['save_db_scope'] = 'Complete named Network/Interface/Property materialization; explicit PROJECT SAVE remains separate'
            definition('delete', ['Alias'], label='delete-saved-custom')
            require('Alias' not in names(), 'Deleted custom definition remains active')
            definition('load', ['DB'], label='restore-current-custom-tag-network')
            require('Alias' in names(), 'Materialized custom tag Network was not restored')
            property_value('Alias', 'Options', 'alpha=beta baud=9600')
            stable_names = names(label='before-repeated-db')
            definition('load', ['DB'], label='repeated-db-load-1')
            require(names() == stable_names, 'Repeated DB load changed catalogue names')
            definition('load', ['DB'], label='repeated-db-load-2')
            require(names() == stable_names and export(project, 'after-repeated-db') == db_saved,
                    'Repeated DB load changed catalogue/tag graph')
            report['db_load_idempotent_graph'] = True
            report['tagged_custom_network_restored'] = True

            definition('rename', ['240', 'RenamedLocal'], label='rename-numeric-default-fixrefs')
            definition('load', ['DB'], label='db-load-after-numeric-rename')
            require(names() == ['240', '241', '242', 'Alias', 'RenamedLocal'],
                    'DB load did not retain renamed definition and restore numeric DB name')
            report['renamed_definition_retained'] = True
            definition('delete', ['240'], label='delete-before-runtime-conflict')
            definition('create', ['240', 'serial', str(output / 'unopened-serial'), '--option', 'stale=yes'], label='create-runtime-conflict')
            property_value('240', 'InterfaceAddress', str(output / 'unopened-serial'))
            property_value('240', 'Interface', str(output / 'unopened-serial'))
            property_value('240', 'Options', 'stale=yes')
            require(export(project, 'after-runtime-conflict') == db_saved, 'Runtime create mutated database fields')
            definition('load', ['DB'], label='refresh-conflicting-runtime-from-db')
            property_value('240', 'InterfaceAddress', trap_endpoint)
            property_value('240', 'Interface', trap_endpoint)
            property_value('240', 'Options', '')
            report['conflicting_numeric_runtime_refreshed_from_db'] = True

            # A complete database Network document changes the source only.
            # Runtime GET must retain its old fields until the explicit DB LOAD.
            original_node = ET.fromstring(db_saved).find("Project/Network[Address='240']")
            require(original_node is not None, 'Original network source missing')
            edited_node = ET.fromstring(ET.tostring(original_node))
            edited_node.find('Interface/InterfaceType').text = 'Serial'
            edited_node.find('Interface/InterfaceAddress').text = str(output / 'unopened-serial')
            def set_network(node, label):
                target = output / (label + '.xml')
                document = ET.tostring(node, encoding='unicode')
                target.write_text(document)
                value = invoke(['database', 'set-xml', '//NEWNET/240', target, '--project', project], label=label)
                row = cli.commands[-1]
                require(len(row['cgate_connection_sequences']) == 1, 'DBSETXML used multiple connections')
                connection = report['cgate_connections'][row['cgate_connection_sequences'][0]]
                actual = bytes.fromhex(connection['client_to_server_hex'])
                match = re.fullmatch(rb'\[1\] PROJECT USE NEWNET\r\n\[2\] DBSETXML //NEWNET/240 << ([A-Za-z0-9_]+)\r\n(.*)\n\1\r\n', actual, re.S)
                require(match is not None and match[2] == document.encode(), 'DBSETXML document wire was not issued exactly once')
                row['exact_document_wire_verified'] = True
                (cli.directory / f"{row['sequence']:03d}-command.json").write_text(json.dumps(row, indent=2) + '\n')
                return value
            set_network(edited_node, 'edit-db-interface-source')
            property_value('240', 'InterfaceAddress', trap_endpoint)
            property_value('240', 'Interface', trap_endpoint)
            definition('load', ['DB'], label='refresh-edited-db-source')
            property_value('240', 'InterfaceAddress', str(output / 'unopened-serial'))
            property_value('240', 'Interface', str(output / 'unopened-serial'))
            set_network(original_node, 'restore-db-interface-source')
            definition('load', ['DB'], label='refresh-restored-db-source')
            property_value('240', 'InterfaceAddress', trap_endpoint)
            property_value('240', 'Interface', trap_endpoint)
            require(export(project, 'after-interface-restore') == db_saved, 'Restoring DB interface changed unrelated project data')
            report['runtime_refresh_requires_explicit_db_load'] = True

            # Previously active definitions survive DB row deletion, but a
            # stale numeric DB snapshot cannot resurrect one explicitly deleted.
            deletion_script = output / 'delete-db-source-network.cgate'
            deletion_script.write_text('PROJECT USE NEWNET\nDBDELETE //NEWNET/241\n')
            deletion = invoke(['run', deletion_script], label='delete-db-source-network-explicit-session',
                              exact_commands=['PROJECT USE NEWNET', 'DBDELETE //NEWNET/241'])
            require(isinstance(deletion, list) and len(deletion) == 2 and deletion[-1].get('status') == 200,
                    'Explicit-session fixture DBDELETE did not complete')
            definition('load', ['DB'], label='load-after-tag-network-delete')
            require('241' in names(), 'DB load removed a previously active definition')
            definition('delete', ['241'], label='delete-stale-numeric-runtime')
            definition('load', ['DB'], label='load-with-stale-numeric-snapshot')
            require('241' not in names(), 'Old numeric snapshot resurrected a removed database network')
            report['deleted_db_row_preserves_active_runtime'] = True
            report['stale_numeric_snapshot_not_resurrected'] = True

            definition('create', ['0FileOnly', 'cni', trap_endpoint], label='create-file-only-definition')
            definition('save', ['FILE'], label='file-snapshot-save')
            saved_file_names = names(label='file-snapshot-names')
            definition('delete', ['0FileOnly'], label='delete-noncolliding-file-name')
            before_collision = names(label='file-collision-before-names')
            definition('load', ['FILE'], expected=1, label='file-collision-refusal')
            require(names(label='file-collision-names') == before_collision and '0FileOnly' not in before_collision,
                    'cmqttd FILE collision inserted the earlier noncolliding name')
            report['file_collision_atomic_refusal'] = True
            report['file_collision_scope'] = 'cmqttd safety deviation: native may insert noncolliding names before a later 408'
            for name in before_collision:
                definition('delete', [name], label='delete-for-file-restore-' + name)
            require(names(label='empty-before-file-restore') == [], 'Catalogue not empty before FILE restore')
            definition('load', ['FILE'], label='file-snapshot-restore')
            require(names(label='file-restored-names') == saved_file_names, 'FILE snapshot did not restore every saved name')
            property_value('Alias', 'Options', 'alpha=beta baud=9600')
            definition('create', ['Alias', 'cni', trap_endpoint], expected=1)
            definition('rename', ['Alias', '240'], expected=1)
            definition('delete', ['MISSING'], expected=1)
            isolated_xml = export(project, 'before-other-project')
            isolated_names = names(label='before-other-project-names')
            invoke(['project', 'new', 'NETB'], label='other-project-new', exact_commands=['PROJECT NEW NETB'])
            require(names(project='NETB', label='other-project-empty-list') == [], 'Other project catalogue not empty')
            definition('load', ['DB'], project='NETB', label='other-project-empty-db')
            definition('load', ['FILE'], project='NETB', label='other-project-missing-file')
            definition('create', ['240', 'cni', trap_endpoint], project='NETB', label='other-project-create')
            require(names(project='NETB', label='other-project-list') == ['240'], 'Other project definition not selected')
            require(names(label='after-other-project-names') == isolated_names, 'Other project operation changed original catalogue')
            require(export(project, 'after-other-project') == isolated_xml, 'Other project operation changed original database')
            report['explicit_project_selection_isolated'] = True
        report['functional_catalogue_steps_completed'] = True
        after_wire = wire_path.read_bytes() if wire_path.exists() else b''
        report['daemon_pci_after_hex'] = after_wire.hex()
        require(before_wire == after_wire, 'Network catalogue workflow issued daemon PCI I/O')
        require(not select.select([trap], [], [], 0)[0], 'Closed Cni definition opened an endpoint')
        require(not (output / 'unopened-serial').exists(), 'Closed Serial workflow created the absent host path')
        report.update(physical_io_performed=False, daemon_pci_capture_unchanged=True,
                      cni_trap_connections=0, serial_path_created=False,
                      serial_open_syscalls_assessed=False, completed=True)
        require(all(row['closed'] for row in report['cgate_connections']), 'C-Gate capture contains an incomplete connection')
        report['all_cgate_connections_closed'] = True
    report['recording_proxy_port_closed'] = port_closed(proxy)
    require(report['backend']['process_cleanup_verified'] and report['backend']['cgate_port_closed']
            and report['backend']['pci_port_closed'] and report['backend']['broker_socket_closed']
            and report['recording_proxy_port_closed'], 'Owned backend/proxy cleanup failed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cmqttd-bin', type=Path, required=True)
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--network-new-only', action='store_true', help='Exploratory network-new scope only; typed definitions acceptance remains incomplete')
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if output.exists() or output.is_relative_to(ROOT) or not output.parent.is_dir():
        parser.error('Use a fresh raw directory outside Git')
    output.mkdir(mode=0o700)
    args.cmqttd_bin = args.cmqttd_bin.resolve()
    # Keep a venv symlink rather than resolving it to the base interpreter,
    # while making subprocess cwd independent of the caller's relative path.
    args.python = args.python.absolute()
    if args.wheel:
        args.wheel = args.wheel.resolve()
    report = {'format': 'cbus-network-definition-cli-acceptance-v1', 'result': 'failed',
              'producer_argv': [sys.executable, *sys.argv], 'hardware_io': False, 'native_process_launched': False,
              'producer_arguments': list(sys.argv[1:] if argv is None else argv),
              'producer_entry': 'standalone' if argv is None else 'in_process_harness',
              'network_new_only': args.network_new_only, 'full_network_workflow_parity': False,
              'native_creation_receipt_parity': False,
              'creation_receipt_scope': 'cmqttd legacy200; original301 UUID OID admitted by CLI and covered by separate literal wire tests',
              'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    try:
        report['source_before'] = closure(); report['package_before'] = package_probe(args.python)
        report['binary_before'] = artifact(args.cmqttd_bin)
        report['native_fixture_binding'] = native_fixture_binding()
        if Path(report['package_before']['package_path']).resolve() != PACKAGE.resolve():
            require(args.wheel is not None, 'Installed package acceptance requires exact wheel binding')
        if args.wheel:
            report['wheel_before'] = artifact(args.wheel)
            with ZipFile(args.wheel) as archive:
                values = {name.removeprefix('cbus_toolkit/'): sha256(archive.read(name)).hexdigest()
                          for name in archive.namelist() if name.startswith('cbus_toolkit/') and Path(name).suffix in ('.py', '.json')}
            require(values == report['package_before']['package_files'], 'Executed package differs from bound wheel')
        execute(args, report, output)
        report['source_after'] = closure(); report['package_after'] = package_probe(args.python)
        report['binary_after'] = artifact(args.cmqttd_bin)
        require(report['source_before'] == report['source_after'] and report['package_before'] == report['package_after']
                and report['binary_before'] == report['binary_after'], 'Acceptance inputs changed during execution')
        if args.wheel:
            report['wheel_after'] = artifact(args.wheel)
            require(report['wheel_before'] == report['wheel_after'], 'Wheel changed during execution')
        report['result'] = 'passed'
    except BaseException as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        if 'source_before' in report and 'source_after' not in report:
            report['source_after'] = closure()
            report['inputs_unchanged_after_failure'] = False
            try:
                report['binary_after'] = artifact(args.cmqttd_bin)
                report['package_after'] = package_probe(args.python)
                report['inputs_unchanged_after_failure'] = (report['source_before'] == report['source_after']
                    and report.get('binary_before') == report['binary_after'] and report.get('package_before') == report['package_after'])
                if args.wheel:
                    report['wheel_after'] = artifact(args.wheel)
                    report['inputs_unchanged_after_failure'] &= report.get('wheel_before') == report['wheel_after']
            except BaseException as error:
                # A recheck failure is additional evidence, never a reason to
                # discard the first actual CLI failure or its retained outputs.
                report['failure_input_recheck_error'] = {'type': type(error).__name__, 'message': str(error)}
        report['retained_files'] = {str(path.relative_to(output)): artifact(path) for path in output.rglob('*') if path.is_file()}
        (output / 'acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
