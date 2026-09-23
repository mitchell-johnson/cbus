"""One owned native scheduling apply, complete reload and backup corroboration."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import time
from uuid import uuid4
import zipfile

ROOT = Path('/Users/mitchell/source/cbus/toolkit-cli')
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.native_thermostat_schedule import NativeThermostatScheduleLevels, _group
from cbus_toolkit.programming import xml_text
import cbus_toolkit.thermostat_schedule_levels

hash_file = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
PROJECT = 'T' + uuid4().hex[:7].upper()
BACKUP = 'B' + uuid4().hex[:7].upper()
JAR = ROOT / 'research/vendor/cgate/app/cgate.jar'
assert hash_file(JAR) == '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630'
process = subprocess.run(['/bin/ps', '-p', '36476', '-o', 'pid=,command='], check=True, capture_output=True, text=True, timeout=5)
assert '36476 ' in process.stdout and str(JAR) in process.stdout and str(ROOT / 'research/runtime/cgate-macos-owned/tmp') in process.stdout
listeners = subprocess.run(['/usr/sbin/lsof', '-nP', '-a', '-p', '36476', '-iTCP', '-sTCP:LISTEN'], check=True, capture_output=True, text=True, timeout=5)
assert len(listeners.stdout.splitlines()) == 7
assert all('127.0.0.1:' in line for line in listeners.stdout.splitlines()[1:])
files = [Path(__file__), JAR, Path(sys.executable).resolve()]
files += [Path(module.__file__).resolve() for name, module in tuple(sys.modules.items()) if name.startswith('cbus_toolkit') and getattr(module, '__file__', None)]
files = list(dict.fromkeys(files)); before = {str(path): hash_file(path) for path in files}
with zipfile.ZipFile(OUT / 'inputs-before.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
    for index, path in enumerate(files): archive.write(path, str(index) + '/' + path.name)
with zipfile.ZipFile(OUT / 'inputs-before.zip') as archive:
    for index, path in enumerate(files): assert hashlib.sha256(archive.read(str(index) + '/' + path.name)).hexdigest() == before[str(path)]
assert {str(path): hash_file(path) for path in files} == before
report = {'format': 'native-thermostat-adapter-pilot-v2', 'passed': False, 'project': PROJECT, 'backup': BACKUP,
          'endpoint': ['127.0.0.1', 20033], 'server_process': process.stdout.strip(), 'listeners': listeners.stdout,
          'inputs_before': before, 'commands': [], 'cleanup': [], 'physical_device_programmed': False,
          'network_open_requested': False, 'scope': 'Owned closed native NetVar adapter; separate original-provider evidence'}
client = CGateClient('127.0.0.1', 20033, timeout=5, max_response_bytes=1024 * 1024)
network = '//' + PROJECT + '/254'; group = network + '/203/1'
initial = {address: {'value': value, 'tag': 'Existing ' + str(address)} for address, value in ((0, 200), (1, 205), (32, 100), (255, 77))}
labels = {value: ('Zone:' if value in (1, 2, 4, 8, 16) else 'Zones:') + ','.join(name for bit, name in ((1, 'unsw'), (2, '1'), (4, '2'), (8, '3'), (16, '4')) if value & bit) for value in range(1, 32)}
additions = {f'DBADDSAFE {group} Level {address} {value["tag"]}': address for address, value in initial.items()}
additions.update({f'DBADDSAFE {group} Level {address} Level {address}': address for address in range(2, 32)})
commands = {'GET cgate version', 'PROJECT LIST', 'PROJECT DIR', 'DBCREATENET 254 Offline Cni 127.0.0.1:1', 'NET LOAD DB',
            'DBGETXML ' + group, 'DBGETXML //' + PROJECT, 'GET ' + network + ' *',
            f'DBADDSAFE {network} Application 203 Enable Control', f'DBADDSAFE {network}/203 NetVar 1 Owned Schedule',
            f'PROJECT COPY {PROJECT} {BACKUP}', f'DBGETXML //{BACKUP}/254/203/1'}
commands.update(f'PROJECT {verb} {PROJECT}' for verb in ('NEW', 'USE', 'SAVE', 'CLOSE', 'LOAD', 'DELETE'))
commands.update(f'PROJECT {verb} {BACKUP}' for verb in ('CLOSE', 'LOAD', 'DELETE'))
commands.update(additions)
owned_oids = {}; loaded = {}; created = False; backup_created = False; first = trace = None; cleanup_started = None; started = time.monotonic()

def remember(error):
    global first, trace
    if first is None: first, trace = error, error.__traceback__

class Recording:
    def command(self, command):
        global created, backup_created
        origin, budget = (started, 90) if cleanup_started is None else (cleanup_started, 30)
        assert time.monotonic() - origin < budget
        allowed = {f'DBGET !{identity}/OID' for identity in owned_oids}
        for identity, address in owned_oids.items():
            allowed.add(f'DBSETSAFE !{identity}/Value {address}')
            if address in initial: allowed.add(f'DBSETSAFE !{identity}/Value {initial[address]["value"]}')
            if 1 <= address <= 31: allowed.add(f'DBSETSAFE !{identity}/TagName Sched Enable {labels[address]}')
        assert command in commands or command in allowed, command
        row = {'command': command, 'attempted': True, 'completed': False}; report['commands'].append(row)
        if command.startswith(('PROJECT NEW ', 'PROJECT LOAD ', 'PROJECT CLOSE ')):
            loaded[command.split()[-1]] = None
        try:
            response = client.command(command)
        except CGateError as error:
            row.update(completed=True, code=error.response.code, lines=list(error.response.lines), rejected=True); raise
        row.update(completed=True, code=response.code, lines=list(response.lines))
        if response.code == 200 and command.startswith(('PROJECT NEW ', 'PROJECT LOAD ')):
            loaded[command.split()[-1]] = True
        if response.code == 200 and command.startswith('PROJECT CLOSE '):
            loaded[command.split()[-1]] = False
        if command == f'PROJECT NEW {PROJECT}' and response.code == 200: created = True
        if command == f'PROJECT COPY {PROJECT} {BACKUP}' and response.code == 200:
            backup_created = True
            loaded[BACKUP] = False  # Exact backend COPY creates a closed on-disk project.
        if command in additions:
            matches = [match[1] for line in response.lines if (match := re.fullmatch(r'301[- ]OID=([a-f0-9-]{36})', line))]
            assert len(matches) == 1 and matches[0] not in owned_oids
            owned_oids[matches[0]] = additions[command]
        return response

recording = Recording(); projects = NativeProjects(recording); database = NativeDatabase(recording)
engine = NativeThermostatScheduleLevels(recording)
try:
    client.connect()
    assert '3.4.0' in recording.command('GET cgate version').final
    report['projects_before'] = list(projects.list().lines); report['directory_before'] = list(projects.directory().lines)
    assert not any(name in line for line in report['projects_before'] + report['directory_before'] for name in (PROJECT, BACKUP))
    projects.operation('new', PROJECT)
    database.create_network(PROJECT, 254, 'Offline', 'Cni', '127.0.0.1:1')
    database.add(network, 'application', 203, 'Enable Control')
    database.add(network + '/203', 'netvar', 1, 'Owned Schedule')
    for address, value in initial.items():
        database.add(group, 'level', address, value['tag'])
        identity = next(key for key, number in owned_oids.items() if number == address)
        database.set('!' + identity + '/Value', value['value'])
    for action in ('save', 'close', 'load'): projects.operation(action, PROJECT)
    before_xml = xml_text(database.get(group, xml=True)); report['initial_xml'] = before_xml
    initial_levels = _group(before_xml, 1)[1]
    plan = engine.plan(group, 'Enable', exclusive_project=True)
    report['plan'] = plan.as_dict(); assert plan.created_addresses == tuple(range(2, 32))
    result = engine.apply(plan, backup_project=BACKUP).as_dict(); report['result'] = result
    assert result['complete'] and result['persistence_verified'] and result['existing_metadata_preserved']
    final_xml = xml_text(database.get(group, xml=True)); report['final_xml'] = final_xml
    _identity, levels, _metadata, _level_meta = _group(final_xml, 1)
    actual = {level.address: level for level in levels}
    assert set(actual) == set(initial) | set(range(1, 32))
    for level in initial_levels: assert actual[level.address] == level
    for address in range(2, 32): assert actual[address].value == address and actual[address].tag == 'Sched Enable ' + labels[address]
    projects.operation('load', BACKUP)
    backup_xml = xml_text(database.get(f'//{BACKUP}/254/203/1', xml=True)); report['backup_xml'] = backup_xml
    backup_levels = _group(backup_xml, 1)[1]
    assert {level.address: (level.value, level.tag) for level in backup_levels} == {level.address: (level.value, level.tag) for level in initial_levels}
    noop = engine.plan(group, 'Disable', exclusive_project=True); count = len(report['commands'])
    noop_result = engine.apply(noop, backup_project=BACKUP).as_dict(); report['noop'] = noop_result
    assert noop_result['state'] == 'already_present' and not noop_result['target_mutation_attempted']
    assert not any(row['command'].startswith(('PROJECT ', 'DBADD', 'DBSET')) for row in report['commands'][count:])
    report['observations_passed'] = True
except BaseException as error:
    remember(error)
    if engine.last_result is not None: report['partial_result'] = json.loads(engine.last_result.document)
finally:
    try: cleanup_started = time.monotonic()
    except BaseException as error: remember(error); cleanup_started = float('-inf')
    for name, owned in ((BACKUP, backup_created), (PROJECT, created)):
        if not owned: continue
        closed = loaded.get(name) is False
        if loaded.get(name) is True:
            try: projects.operation('close', name); closed = True
            except BaseException as error: remember(error); report['cleanup'].append({'project': name, 'phase': 'close', 'error_type': type(error).__name__})
        elif not closed:
            report['cleanup'].append({'project': name, 'phase': 'unknown_loaded_state', 'manual_inspection_required': True})
        if closed:
            try: projects.operation('delete', name); report['cleanup'].append({'project': name, 'deleted': True})
            except BaseException as error: remember(error); report['cleanup'].append({'project': name, 'phase': 'delete', 'error_type': type(error).__name__})
    if client.connected:
        try:
            report['projects_after'] = list(projects.list().lines); report['directory_after'] = list(projects.directory().lines)
            assert report['projects_after'] == report['projects_before'] and report['directory_after'] == report['directory_before']
        except BaseException as error: remember(error)
    try: client.close(); report['socket_closed'] = True
    except BaseException as error: remember(error)
    try:
        report['inputs_after'] = {str(path): hash_file(path) for path in files}; assert report['inputs_after'] == before
    except BaseException as error: remember(error)
    report['passed'] = first is None and report.get('observations_passed') is True
    if first is not None:
        try: message = str(first)
        except BaseException: message = '<unprintable>'
        report['error'] = {'type': type(first).__name__, 'message': message[:2048]}
    stream = None
    try: stream = (OUT / 'report.json').open('x'); stream.write(json.dumps(report, indent=2) + '\n')
    except BaseException as error: remember(error)
    finally:
        if stream is not None:
            try: stream.close()
            except BaseException as error: remember(error)
if first is not None: raise BaseException.with_traceback(first, trace)
print(json.dumps({'passed': report['passed'], 'project': PROJECT, 'backup': BACKUP, 'commands': len(report['commands'])}))
