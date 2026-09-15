"""Owned Enable Control backend: distinct Address/Value survive save and reload."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path('/Users/mitchell/source/cbus/toolkit-cli')
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import xml_text

digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
PROJECT = 'T' + uuid.uuid4().hex[:7].upper()
JAR = ROOT / 'research/vendor/cgate/app/cgate.jar'
assert digest(JAR) == '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630'
process = subprocess.run(['/bin/ps', '-p', '36476', '-o', 'pid=,command='],
                         check=True, capture_output=True, text=True, timeout=5)
assert '36476 ' in process.stdout and str(JAR) in process.stdout
assert str(ROOT / 'research/runtime/cgate-macos-owned/tmp') in process.stdout
paths = [Path(__file__), JAR]
paths += [Path(module.__file__).resolve() for name, module in tuple(sys.modules.items())
          if name.startswith('cbus_toolkit') and getattr(module, '__file__', None)]
paths = list(dict.fromkeys(paths))
before = {str(path): digest(path) for path in paths}
with zipfile.ZipFile(OUT / 'inputs-before.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
    for index, path in enumerate(paths):
        if path != JAR:
            archive.write(path, str(index) + '/' + path.name)
    archive.writestr('inputs.json', json.dumps(before, indent=2))
assert {str(path): digest(path) for path in paths} == before
report = {'scope': 'Existing native backend in an owned closed Enable Control database; no original Toolkit workflow execution or physical acceptance',
          'project': PROJECT, 'endpoint': ['127.0.0.1', 20033], 'server_process': process.stdout.strip(),
          'input_hashes_before': before, 'passed': False, 'commands': [], 'cleanup': [],
          'network_open_requested': False, 'device_programming_requested': False}
client = CGateClient('127.0.0.1', 20033, timeout=5, max_response_bytes=1024*1024)
started = time.monotonic()
first = trace = None
created = closed = deleted = False
cleanup_started = None
owned_level_oids = {}
network = '//' + PROJECT + '/254'
group = network + '/203/1'
expected = {0: 'Existing boundary', 1: 'Sched Enable Zone:unsw',
            31: 'Sched Enable Zones:unsw,1,2,3,4'}
expected_values = {0: 200, 1: 205, 31: 31}
level_additions = {f'DBADDSAFE {group} Level {value} {label}': value
                   for value, label in expected.items()}
level_additions[f'DBADDSAFE {group} Level 1 Must not replace existing'] = 1
exact_commands = {'GET cgate version', 'PROJECT LIST', 'PROJECT DIR', 'PROJECT USE',
    'DBCREATENET 254 Offline Cni 127.0.0.1:1', 'NET LOAD DB',
    'GET ' + network + ' InterfaceState', 'DBGETXML ' + group,
    f'DBADDSAFE {network} Application 203 Enable Control',
    f'DBADDSAFE {network}/203 NetVar 1 Owned Schedule'}
exact_commands.update(f'PROJECT {verb} {PROJECT}' for verb in ('NEW', 'USE', 'SAVE', 'CLOSE', 'LOAD', 'DELETE'))
exact_commands.update(level_additions)


def remember(error):
    global first, trace
    if first is None:
        first, trace = error, error.__traceback__


class RecordingClient:
    def command(self, command):
        origin, budget = (started, 90) if cleanup_started is None else (cleanup_started, 30)
        assert time.monotonic() - origin < budget, 'Command admission deadline'
        oid_commands = {f'DBGET !{oid}/OID' for oid in owned_level_oids}
        oid_commands.update(f'DBSETSAFE !{oid}/Value {value}' for oid, value in owned_level_oids.items())
        oid_commands.update(f'DBDELETE !{oid}' for oid in owned_level_oids)
        oid_commands.update(f'DBSETSAFE !{oid}/Value {expected_values[address]}' for oid, address in owned_level_oids.items())
        assert command in exact_commands or command in oid_commands, command
        row = {'command': command, 'attempted': True, 'completed': False}
        report['commands'].append(row)
        try:
            response = client.command(command)
        except CGateError as error:
            row.update(completed=True, error=True, lines=list(error.response.lines), code=error.response.code)
            raise
        else:
            row.update(completed=True, lines=list(response.lines), code=response.code)
            if command in level_additions:
                identifiers = [match[1] for line in response.lines
                               if (match := re.fullmatch(r'301[- ]OID=([0-9a-fA-F-]{36})', line))]
                assert len(identifiers) == 1 and identifiers[0] not in owned_level_oids
                uuid.UUID(identifiers[0])
                owned_level_oids[identifiers[0]] = level_additions[command]
            return response


recording = RecordingClient()
projects, database = NativeProjects(recording), NativeDatabase(recording)


def levels():
    raw = xml_text(database.get(group, xml=True))
    assert '<!DOCTYPE' not in raw.upper() and '<!ENTITY' not in raw.upper()
    node = ET.fromstring(raw)
    assert node.tag == 'NetVar'
    result = {}
    for level in node.findall('Level'):
        address = int(level.findtext('Address'))
        assert address not in result
        result[address] = {'tag': level.findtext('TagName'), 'value': int(level.get('Value')),
                         'oid': level.get('OID') or level.findtext('OID')}
    return result


try:
    client.connect()
    version = recording.command('GET cgate version')
    assert any('3.4.0' in line for line in version.lines)
    report['projects_before'] = list(projects.list().lines)
    report['directory_before'] = list(projects.directory().lines)
    try:
        report['owned_session_context_before'] = list(recording.command('PROJECT USE').lines)
    except CGateError as error:
        report['owned_session_context_query_error'] = list(error.response.lines)
    report['project_use_scope'] = 'Original C-Gate command documentation: current command session only; this owned connection is closed at completion'
    assert not any(PROJECT in line for line in report['projects_before'] + report['directory_before'])
    projects.operation('new', PROJECT); created = True
    database.create_network(PROJECT, 254, 'Offline', 'Cni', '127.0.0.1:1')
    assert 'InterfaceState=closed' in recording.command('GET ' + network + ' InterfaceState').final
    database.add(network, 'application', 203, 'Enable Control')
    database.add(network + '/203', 'netvar', 1, 'Owned Schedule')
    for value, label in expected.items():
        database.add(group, 'level', value, label)
    for oid, address in owned_level_oids.items():
        if expected_values[address] != address:
            database.set('!' + oid + '/Value', expected_values[address])
    initial = levels()
    assert {address: data['value'] for address, data in initial.items()} == expected_values
    assert {value: data['tag'] for value, data in initial.items()} == expected
    assert all(data['oid'] for data in initial.values())
    report['before_save'] = initial
    projects.operation('save', PROJECT)
    projects.operation('close', PROJECT); closed = True
    projects.operation('load', PROJECT); closed = False
    assert 'InterfaceState=closed' in recording.command('GET ' + network + ' InterfaceState').final
    reloaded = levels()
    assert reloaded == initial
    report['after_reload'] = reloaded
    try:
        database.add(group, 'level', 1, 'Must not replace existing')
    except CGateError as error:
        report['duplicate_rejected'] = list(error.response.lines)
    else:
        raise AssertionError('Duplicate level must be rejected')
    assert levels() == initial
    report['existing_levels_preserved'] = True
except BaseException as error:
    remember(error)
finally:
    try:
        cleanup_started = time.monotonic()
    except BaseException as error:
        remember(error)
        # A broken clock cannot authorize unbounded cleanup commands.
        cleanup_started = float('-inf')
    if created and client.connected:
        if not closed:
            try:
                projects.operation('close', PROJECT); closed = True
                report['cleanup'].append({'operation': 'close_owned_project', 'completed': True})
            except BaseException as error:
                remember(error); report['cleanup'].append({'operation': 'close_owned_project', 'completed': False, 'error_type': type(error).__name__})
        if closed:
            try:
                projects.operation('delete', PROJECT); deleted = True
                report['cleanup'].append({'operation': 'delete_owned_project', 'completed': True})
                report['projects_after'] = list(projects.list().lines)
                report['directory_after'] = list(projects.directory().lines)
                assert report['projects_after'] == report['projects_before']
                assert report['directory_after'] == report['directory_before']
            except BaseException as error:
                remember(error); report['cleanup'].append({'operation': 'verify_owned_project_cleanup', 'completed': False, 'error_type': type(error).__name__})
    try:
        client.close(); report['socket_closed'] = True
    except BaseException as error:
        remember(error); report['socket_closed'] = False
    try:
        report['input_hashes_after'] = {str(path): digest(path) for path in paths}
        assert report['input_hashes_after'] == before
    except BaseException as error:
        remember(error)
    report.update(passed=first is None and created and closed and deleted,
                  created=created, closed=closed, deleted=deleted, owned_level_oids=owned_level_oids)
    try:
        report['elapsed_seconds'] = time.monotonic() - started
    except BaseException as error:
        remember(error); report['passed'] = False
    if first is not None:
        try:
            message = str(first)
        except BaseException:
            message = '<unavailable>'
        report['first_error'] = {'type': type(first).__name__, 'message': message}
    stream = None
    try:
        stream = (OUT / 'report.json').open('x')
        stream.write(json.dumps(report, indent=2) + '\n'); stream.flush(); os.fsync(stream.fileno())
    except BaseException as error:
        remember(error)
    finally:
        if stream is not None:
            try:
                stream.close()
            except BaseException as error:
                remember(error)
if first is not None:
    raise BaseException.with_traceback(first, trace)
print(json.dumps({'passed': report['passed'], 'project': PROJECT, 'commands': len(report['commands']),
                  'levels_verified': 3, 'owned_project_deleted': deleted, 'report': str(OUT / 'report.json')}))
