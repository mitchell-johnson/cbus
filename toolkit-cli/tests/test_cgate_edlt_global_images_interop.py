"""Automatic Global Programming through the public CLI on owned services."""
from contextlib import contextmanager
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.file_transfer import prepare_upload, upload
from test_cgate_barcode_database_interop import FaultGate, selected_binary, graph, parse_wire
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)
from test_edlt_global_programming import fixture

BACKENDS = [('cgate-mock', 'CBUS_CGATE_MOCK_BIN'), ('cmqttd', 'CBUS_CMQTTD_BIN')]
VECTOR = Path(__file__).resolve().parents[1] / 'research/fixtures/edlt-global-image-vectors.json'
GLOBAL_PROCESS_BUDGET = 180


def invoke(relay, evidence, args, *, expected=0, complete=True):
    """Bound the whole multi-target journey without changing wire deadlines.

    A Global apply performs hundreds of separately bounded commands. Retain
    an outer timeout as an incomplete attempt, including the relay's actual
    last request and replies; it never becomes a successful call.
    """
    start = len(relay.rows)
    argv = [sys.executable, '-m', 'cbus_toolkit', 'cgate', '--host', relay.endpoint[0],
            '--port', str(relay.endpoint[1]), '--timeout', '3', *map(str, args)]
    call = {'argv': argv, 'process_budget_seconds': GLOBAL_PROCESS_BUDGET,
            'wire_timeout_seconds': 3, 'relay_connection_index': start}
    evidence['calls'].append(call)
    begun = time.monotonic()
    try:
        process = subprocess.run(argv, capture_output=True, text=True,
                                 timeout=GLOBAL_PROCESS_BUDGET)
    except subprocess.TimeoutExpired as error:
        def text(value):
            return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
        call.update({'exit': None, 'stdout': text(error.stdout), 'stderr': text(error.stderr),
                     'wall_seconds': time.monotonic() - begun,
                     'outer_timeout': True, 'accepted_terminal': False,
                     'subprocess_error': type(error).__name__})
        if len(relay.rows) > start:
            wire = relay.rows[start]
            call['relay_closed_after_timeout'] = wire['done'].wait(5)
            requests = bytes.fromhex(wire['request_hex']).decode('utf-8').splitlines()
            replies = bytes.fromhex(wire['response_hex']).decode('utf-8').splitlines()
            call['partial_wire'] = {
                'request_hex': wire['request_hex'], 'response_hex': wire['response_hex'],
                'request_lines': len(requests), 'response_lines': len(replies),
                'last_request': requests[-1] if requests else None,
                'last_reply_prefix': replies[-1][:200] if replies else None}
        raise
    call.update({'exit': process.returncode, 'stdout': process.stdout,
                 'stderr': process.stderr, 'wall_seconds': time.monotonic() - begun,
                 'outer_timeout': False})
    assert process.returncode == expected, call
    value = json.loads(process.stdout or process.stderr)
    call['result'] = value
    assert len(relay.rows) == start + 1, call
    wire = relay.rows[start]
    assert wire['done'].wait(5)
    call.update(parse_wire(wire, complete=complete))
    call['request_bytes'] = len(wire['request_hex']) // 2
    call['response_bytes'] = len(wire['response_hex']) // 2
    return value, call


def snapshot(owner, project):
    from cbus_toolkit.programming import xml_text
    return xml_text(owner.command('DBGETXML //' + project))


def parameters(root, path):
    _, _, project, network, _, unit = path.split('/')
    node = root.find(f"Project[Address='{project}']/Network[Address='{network}']/Unit[Address='{unit}']")
    assert node is not None
    return {p.get('Name'): p.get('Value') for p in node.findall('PP')}


def normalized(value):
    return tuple(int(part, 16) if part.lower().startswith('0x') else int(part)
                 for part in value.split())


def owned_command(owner, commands, command):
    """Record fixture cleanup separately from the public CLI's wire."""
    response = owner.command(command)
    commands.append({'command': command, 'status': response.code,
                     'lines': list(response.lines), 'final': response.final})
    assert response.code == 200, commands[-1]
    return response


def project_names(owner, commands):
    response = owned_command(owner, commands, 'PROJECT LIST')
    assert response.final == '200 OK'
    assert all(line.startswith('200-') for line in response.lines[:-1]), response
    names = [line[4:] for line in response.lines[:-1]]
    assert names == sorted(set(names)), names
    return names


def copied_project_graph(before, project, backup):
    """The owned COPY profile changes the project name, retaining its tree."""
    document = ET.fromstring(before, parser=ET.XMLParser(target=ET.TreeBuilder(
        insert_comments=True, insert_pis=True)))
    node = document.find('Project')
    assert node is not None
    for name in ('Address', 'TagName'):
        field = node.find(name)
        assert field is not None and field.text == project, (name, before)
        field.text = backup
    return graph(ET.tostring(document, encoding='unicode'))


def preservation(before, after, targets, payload):
    old, new = ET.fromstring(before), ET.fromstring(after)
    for path in targets:
        previous, current = parameters(old, path), parameters(new, path)
        assert len(previous) == len(current) == 874
        for name, value in current.items():
            if name in payload:
                assert normalized(value) == normalized(payload[name]), (path, name, value, payload[name])
            else:
                assert value == previous[name], (path, name)
        _, _, project, network, _, unit = path.split('/')
        node = new.find(f"Project[Address='{project}']/Network[Address='{network}']/Unit[Address='{unit}']")
        for row in node.findall('PP'):
            if row.get('Name') in payload:
                row.set('Value', previous[row.get('Name')])
    assert graph(ET.tostring(new, encoding='unicode')) == graph(before)


def assert_lost_successful_save(fault):
    """The loss followed an actual accepted upstream save, not a rejection."""
    assert len(fault.rows) == 1
    row = fault.rows[0]
    tag = re.escape(row['fault']['tag'])
    terminal = bytes.fromhex(row['lost_backend_terminal_hex']).decode()
    assert re.fullmatch(r'\[' + tag + r'\] 200 [^\r\n]*\r?\n', terminal)
    assert terminal.encode().hex() in row['backend_response_hex']
    assert terminal.encode().hex() not in row['response_hex']


@contextmanager
def journey(backend, variable, tmp_path):
    vectors = json.loads(VECTOR.read_text())
    source = vectors['fixture']
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'owned-global-images')
    specs = tmp_path / 'synthetic-specs'; specs.mkdir()
    root = ET.Element('UnitSpecification')
    for name, value in [('Type', 'KEYGL5'), ('MinVersion', '5.5.00'),
                        ('MaxVersion', '5.5.00'), ('MemorySize', '16384')]:
        ET.SubElement(root, name).text = value
    params = ET.SubElement(root, 'Parameters')
    for parameter in fixture().parameters.values():
        node = ET.SubElement(params, 'Param')
        for name, value in parameter.fields.items():
            ET.SubElement(node, name).text = value
    spec_path = specs / 'KEYGL5.xml'; spec_path.write_bytes(ET.tostring(root))
    launcher = work / 'owned-global-images-backend'
    flag = '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec'
    launcher.write_text('#!' + sys.executable + '\nimport os,sys\nos.execv(' + repr(str(binary))
        + ', [' + repr(str(binary)) + ', *sys.argv[1:], ' + repr(flag) + ', ' + repr(str(specs)) + '])\n')
    launcher.chmod(0o700)
    image_path = tmp_path / 'images.json'
    image_path.write_bytes(source['project_images_raw'].encode())
    assert hashlib.sha256(image_path.read_bytes()).hexdigest() == source['project_images_sha256']
    evidence = {'format': 'cbus-edlt-global-images-owned-v1', 'backend': backend,
                'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'specification_sha256': hashlib.sha256(spec_path.read_bytes()).hexdigest(),
                'vector_sha256': hashlib.sha256(VECTOR.read_bytes()).hexdigest(),
                'calls': [], 'processes': [], 'cases': [],
                'original_execution': False, 'physical_acceptance': False}
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(backend, launcher, work) as (endpoint, record):
            evidence['processes'].append(record)
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                document = ET.fromstring(source['project_xml'])
                removed = 0
                # The pure preservation vectors retain synthetic foreign
                # elements. The owned FILE/RESTORE import has a narrower
                # native object schema. Start interaction acceptance from
                # its eligible shape, then preserve the actual live graph.
                for parent in document.iter():
                    for child in list(parent):
                        if child.tag == 'Opaque':
                            parent.remove(child)
                            removed += 1
                evidence['owned_import_projection'] = {
                    'synthetic_opaque_children_removed': removed,
                    'public_preservation_baseline': 'actual post-RESTORE DBGETXML',
                    'arbitrary_foreign_element_acceptance': False}
                ET.SubElement(document, 'DBVersion').text = '2.3'
                project = document.find('Project')
                ET.SubElement(project, 'OID').text = str(uuid.uuid4())
                for network in project.findall('Network'):
                    ET.SubElement(network, 'OID').text = str(uuid.uuid4())
                    interface = ET.SubElement(network, 'Interface')
                    for name, value in [('OID', str(uuid.uuid4())), ('InterfaceType', 'cni'),
                                        ('InterfaceAddress', trap)]:
                        ET.SubElement(interface, name).text = value
                    for unit in network.findall('Unit'):
                        ET.SubElement(unit, 'TagName').text = unit.findtext('UnitName')
                project_path = work / (source['project'] + '.xml')
                project_path.write_bytes(ET.tostring(document))
                for command in ('FILE MKDIR Projects', 'FILE MKDIR Projects/archived'):
                    assert owner.command(command).code == 200
                assert upload(prepare_upload('Projects/archived/' + project_path.name, project_path), owner)['upload_completed']
                for command in ('PROJECT RESTORE ' + source['project'] + ' ' + project_path.name,
                                'PROJECT USE ' + source['project'], 'PROJECT SAVE ' + source['project']):
                    assert owner.command(command).code == 200
                argv = ['edlt-global', '--spec-dir', specs, '--auto-metadata',
                        '--source-database', source['source_unit'], '--exclusive-project',
                        '--project-images-export', image_path,
                        '--project-images-sha256', source['project_images_sha256']]
                for target in source['targets']:
                    argv.extend(['--destination', target['path']])
                yield owner, relay, evidence, argv, source, vectors, endpoint
    finally:
        if relay is not None:
            evidence['wire'] = relay.evidence()
        associated_evidence(tmp_path / 'global-images-evidence.json', evidence)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
def test_public_automatic_global_all_16_masks_preserve_two_divergent_targets(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, argv, source, vectors, _endpoint):
        targets = tuple(row['path'] for row in source['targets'])
        for case in vectors['masks']:
            backup = 'GB' + str(case['mask'])
            cleanup = {'backup_project': backup, 'commands': [],
                       'fixture_owned_cleanup': True, 'cli_backup_deletion': False}
            evidence.setdefault('backup_cleanup', []).append(cleanup)
            previous_projects = project_names(owner, cleanup['commands'])
            assert source['project'] in previous_projects and backup not in previous_projects
            cleanup['projects_before_apply'] = previous_projects
            before = snapshot(owner, source['project'])
            flags = [part for category in case['categories'] for part in ('--category', category)]
            preview, preview_call = invoke(relay, evidence, [*argv, *flags, '--dry-run'])
            assert not any(command.startswith(('PP SET ', 'PP SAVE', 'PROJECT SAVE ', 'PROJECT COPY ',
                                               'DBADD', 'DBSET', 'DBDELETE', 'FILE UPLOAD'))
                           for command in preview_call['commands'])
            assert graph(snapshot(owner, source['project'])) == graph(before)
            expected = {name: value for name, value in case['ordered_payload']}
            assert [(row['parameter'], ' '.join(hex(v) for v in row['value']))
                    for row in preview['payload']['ordered_payload']] == [tuple(row) for row in case['ordered_payload']]
            result, call = invoke(relay, evidence, [*argv, *flags, '--backup-project', backup])
            assert result['complete']
            assert sum(command.startswith('PP SAVE_TO_SOURCE ') for command in call['commands']) == 2
            after = snapshot(owner, source['project'])
            preservation(before, after, targets, expected)
            for command in ('PROJECT CLOSE ' + source['project'], 'PROJECT LOAD ' + source['project']):
                assert owner.command(command).code == 200
            assert graph(snapshot(owner, source['project'])) == graph(after)
            evidence['cases'].append({'mask': case['mask'], 'before': before, 'after': after})

            # Each mask owns one backup. Verify the complete pre-apply copy
            # and its saved image before releasing that test-only project;
            # retaining sixteen full copies would test repository capacity.
            relay_connections = len(relay.rows)
            assert project_names(owner, cleanup['commands']) == sorted([*previous_projects, backup])
            backup_before = snapshot(owner, backup)
            cleanup['backup_before_close'] = backup_before
            assert graph(backup_before) == copied_project_graph(before, source['project'], backup)
            original, copied = ET.fromstring(before), ET.fromstring(backup_before)
            for path in (source['source_unit'], *targets):
                backup_path = '//' + backup + path[len('//' + source['project']):]
                previous, retained = parameters(original, path), parameters(copied, backup_path)
                assert len(previous) == len(retained) == 874
                assert retained == previous, (backup_path, retained, previous)
            for command in ('PROJECT CLOSE ' + backup, 'PROJECT LOAD ' + backup):
                owned_command(owner, cleanup['commands'], command)
            backup_reloaded = snapshot(owner, backup)
            cleanup['backup_after_load'] = backup_reloaded
            assert graph(backup_reloaded) == graph(backup_before)
            assert graph(snapshot(owner, source['project'])) == graph(after)
            cleanup['backup_saved_image_verified'] = True

            for command in ('PROJECT CLOSE ' + backup, 'PROJECT DELETE ' + backup):
                owned_command(owner, cleanup['commands'], command)
            cleanup['projects_after_delete'] = project_names(owner, cleanup['commands'])
            assert cleanup['projects_after_delete'] == previous_projects
            after_cleanup = snapshot(owner, source['project'])
            cleanup['main_after_delete'] = after_cleanup
            assert graph(after_cleanup) == graph(after)
            owned_command(owner, cleanup['commands'], 'PROJECT USE ' + source['project'])
            assert len(relay.rows) == relay_connections
            cleanup.update(deleted=True, main_project_preserved=True,
                           reused_owner_connection=True, extra_cli_connections=0)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
def test_public_global_lost_first_target_save_stops_without_replay(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, _relay, evidence, argv, source, vectors, endpoint):
        before = snapshot(owner, source['project'])
        with FaultGate(endpoint, 'PP SAVE_TO_SOURCE', 'drop') as fault:
            result, call = invoke(fault, evidence, [*argv, '--category', 'general', '--backup-project', 'GLOST'],
                                  expected=1, complete=False)
            assert fault.matches == 1
            assert_lost_successful_save(fault)
            assert sum(command.startswith('PP SAVE_TO_SOURCE ') for command in call['commands']) == 1
            saved = next(i for i, command in enumerate(call['commands']) if command.startswith('PP SAVE_TO_SOURCE '))
            assert not any(command.startswith(('PP SET ', 'PP SAVE', 'PROJECT SAVE ', 'PROJECT LOAD ',
                                               'PROJECT CLOSE ', 'DBSET', 'DBDELETE'))
                           for command in call['commands'][saved + 1:])
            assert result['edlt_global_programming_evidence']['automatic_retries'] == 0
            evidence['lost_save_wires'] = fault.evidence()
        after = snapshot(owner, source['project'])
        general = next(case for case in vectors['masks'] if case['categories'] == ['general'])
        preservation(before, after, (source['targets'][0]['path'],), dict(general['ordered_payload']))
        # The second destination and exact source remain untouched; the first
        # destination's attempted persistence is separately marked uncertain.
        second = source['targets'][1]['path']
        assert parameters(ET.fromstring(before), second) == parameters(ET.fromstring(after), second)
        assert parameters(ET.fromstring(before), source['source_unit']) == parameters(ET.fromstring(after), source['source_unit'])
        evidence['cases'].append({'before': before, 'after': after, 'save_outcome_uncertain': True})
