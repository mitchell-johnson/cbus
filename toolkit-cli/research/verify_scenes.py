#!/usr/bin/env python3
"""Verify filesystem scenes in a second, isolated native C-Gate server.

Only a uniquely owned runtime directory and fresh synthetic interface are
used. The shared oracle on20023 is never restarted or adopted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import sys
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.scenes import NativeScenes, SceneAction, SceneExecutor, SceneFile
from cbus_toolkit.simulator import PCISimulator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.oracle import IMAGE
from research.local_cgate import LocalCGate, service_backend

BASE = Path(__file__).resolve().parents[1]
CONTAINER = 'cbus-toolkit-scene-oracle'
ROLE = 'cbus-toolkit-owned-scene-oracle-v1'
JDK_IMAGE = 'eclipse-temurin@sha256:7c03acdcca6f44f6fbdfcab2fcad1b7c7a9046392a0d570b4414f6f50c3550cb'


def docker(*arguments):
    return subprocess.run(['docker', *arguments], check=True, text=True, capture_output=True).stdout.strip()


def verify_parser(work, vendor, *, local=None):
    """Call native Java parser/serializer directly, without a server or network."""
    fixture = ('# Independent literal vendor grammar\n'
               'set //SCENE/254/56/12 255\n'
               'SET //SCENE/254/56/24 127 4\n'
               'set //SCENE/254/56/25 0 0 # cleared\n'
               'set //SCENE/254/56/27 0 2147483647\n')
    path = work / 'parser.scene'
    path.write_text(fixture)
    helper = BASE / 'research/NativeSceneFileProbe.java'
    if local:
        javac = Path(os.environ.get('CBUS_CGATE_JAVAC', local.java.parent / 'javac')).resolve()
        if not javac.is_file() or not os.access(javac, os.X_OK):
            raise ValueError('Local scene acceptance requires an explicitly selected javac compiler')
        compiled = subprocess.run([str(javac), '--release', '11', '-cp', str(vendor / 'cgate.jar'), '-d', str(work), str(helper)],
                                  capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise RuntimeError('Original scene probe compilation failed: ' + compiled.stderr[-1500:])
        classpath = os.pathsep.join((str(work), str(vendor / 'cgate.jar'), str(vendor / 'lib/*')))
        result = subprocess.run([str(local.java), '-cp', classpath, 'NativeSceneFileProbe', str(path)],
                                cwd=work, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError('Original scene parser failed: ' + result.stderr[-1500:])
        output = result.stdout.strip()
        execution = {'backend': 'local', 'java': str(local.java), 'javac': str(javac),
                     'javac_sha256': hashlib.sha256(javac.read_bytes()).hexdigest(),
                     'class_sha256': hashlib.sha256((work / 'NativeSceneFileProbe.class').read_bytes()).hexdigest(),
                     'stderr': result.stderr}
    else:
        args = ('run', '--rm', '-v', f'{vendor}:/opt/cgate:ro', '-v', f'{work}:/work', '-v', f'{helper}:/NativeSceneFileProbe.java:ro', '-w', '/work', JDK_IMAGE)
        docker(*args, 'javac', '-cp', '/opt/cgate/cgate.jar', '-d', '/work', '/NativeSceneFileProbe.java')
        output = docker(*args, 'java', '-cp', '/work:/opt/cgate/cgate.jar:/opt/cgate/lib/*', 'NativeSceneFileProbe', '/work/parser.scene')
        execution = {'backend': 'docker', 'image': JDK_IMAGE}
    actual = tuple(SceneAction(parts[1], int(parts[2]), int(parts[3])) for line in output.splitlines() if (parts := line.split('\t'))[0] == 'ACTION')
    if actual != SceneFile.parse(fixture).actions:
        raise RuntimeError('Python and native scene parsers disagree')
    native_written = SceneFile.load(path)
    expected_written = tuple(SceneAction(action.address, action.level, 0) for action in actual)
    if native_written.actions != expected_written:
        raise RuntimeError('Python parser differs from native recorder output')
    return {'passed': True, **execution, 'actions': len(actual), 'native_output': output,
            'native_serialized_text': path.read_text(), 'scope': 'Unmodified AU parser and serializer; no server command or scene playback tested by this probe'}


def verify(*, port=20024, report_path=None, backend=None):
    backend = service_backend() if backend is None else backend
    if backend not in ('docker', 'local'):
        raise ValueError('Native scene backend must be docker or local')
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535 or port == 20023:
        raise ValueError('Use a valid loopback port different from the shared oracle20023')
    if backend == 'docker' and subprocess.run(['docker', 'inspect', CONTAINER], capture_output=True).returncode == 0:
        raise RuntimeError('The dedicated scene container already exists; inspect it before another run')
    vendor = BASE / 'research/vendor/cgate/app'
    if not (vendor / 'cgate.jar').is_file():
        raise RuntimeError('Extract the user-supplied native C-Gate reference first')
    runtime = BASE / 'research/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    local = LocalCGate(vendor, settings={'use-scenes': 'yes', 'scene-base': 'scene'}) if backend == 'local' else None
    work = local.work if local else Path(tempfile.mkdtemp(prefix='scene-oracle-', dir=runtime))
    if local:
        port = local.port
    owner = uuid4().hex
    project = 'SCN' + owner[:5].upper()
    network = f'//{project}/254'
    scene_set = 'CLI_SCENE'
    scene_name = 'evening'
    scene_path = work / 'scene' / scene_set / scene_name
    for name in ('config', 'tag', 'logs', 'scene/' + scene_set):
        (work / name).mkdir(parents=True, exist_ok=True)
    (work / 'owner.json').write_text(json.dumps({'role': ROLE, 'owner': owner, 'backend': backend,
                                               'container': CONTAINER if not local else None}) + '\n')
    if not local:
        (work / 'config/C-GateConfig.txt').write_text('use-scenes=yes\nscene-base=scene\n')
        gateway = docker('network', 'inspect', 'bridge', '--format', '{{(index .IPAM.Config 0).Gateway}}')
        (work / 'config/access.txt').write_text('interface 127.0.0.1 Program\ninterface localhost Program\ninterface 0:0:0:0:0:0:0:1 Program\n' + f'remote {gateway} Clipsal\n')
        for name in ('lib', 'key', 'unitspec', 'help', 'transform', 'dali_catalogue'):
            (work / name).symlink_to('/opt/cgate/' + name, target_is_directory=True)
    SceneFile(tuple(SceneAction(network + '/56/' + str(group), level) for group, level in ((12, 255), (24, 64), (25, 0))), comments=('# Unique offline scene acceptance fixture',)).save(scene_path)
    report = {'format': 'cbus-native-filesystem-scene-acceptance-v1', 'scope': 'Python vendor-format scene execution over native lighting and independent synthetic state; native SCENE commands tested separately; not PP device scenes',
              'project': project, 'scene_set': scene_set, 'scene': scene_name, 'work_directory': str(work), 'port': port,
              'backend': backend, 'image': IMAGE if not local else None, 'owner': owner, 'commands': [], 'checks': {}, 'cleanup_errors': [],
              'source_hashes': {str(path.relative_to(BASE)): hashlib.sha256(path.read_bytes()).hexdigest() for path in (
                  vendor / 'cgate.jar', BASE / 'src/cbus_toolkit/scenes.py', BASE / 'src/cbus_toolkit/cgate.py',
                  BASE / 'research/NativeSceneFileProbe.java', BASE / 'research/local_cgate.py',
                  BASE / 'tests/test_scenes.py', Path(__file__).resolve())}}
    simulator = PCISimulator(profile='synthetic', state_path=work / 'simulator.json', wire_log_path=work / 'wire.jsonl')
    started = False
    def wait_for(predicate, description, timeout=10):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise RuntimeError('Timed out verifying ' + description)
            time.sleep(0.02)
    try:
        report['native_parser'] = verify_parser(work, vendor, local=local)
        report['checks']['vendor_parser_serializer_differential'] = True
        with simulator.running('127.0.0.1' if local else '0.0.0.0', 0) as (_, simulator_port):
            report['simulator_endpoint'] = ('127.0.0.1' if local else 'host.docker.internal') + ':' + str(simulator_port)
            if local:
                local.start()
            else:
                report['container_id'] = docker('run', '-d', '--name', CONTAINER, '--label', f'cbus-toolkit.role={ROLE}', '--label', f'cbus-toolkit.owner={owner}',
                                             '-p', f'127.0.0.1:{port}:20023', '-v', f'{vendor}:/opt/cgate:ro', '-v', f'{work}:/work', '-w', '/work', IMAGE,
                                             'java', '-Xms64M', '-Xmx512M', '-jar', '/opt/cgate/cgate.jar')
            started = True
            def ready():
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.2) as peer:
                        peer.settimeout(0.2)
                        return peer.recv(4096).startswith(b'201 ')
                except OSError:
                    return False
            wait_for(ready, 'dedicated native server startup', 30)
            with CGateClient('127.0.0.1', port, timeout=30) as client:
                report['greeting'] = client.greeting
                created = False
                def command(text):
                    try:
                        response = client.command(text)
                    except Exception as error:
                        report['commands'].append({'command': text, 'error': str(error)})
                        raise
                    report['commands'].append({'command': text, 'lines': list(response.lines)})
                    return response
                class RecordingClient:
                    def command(self, text):
                        return command(text)
                scenes = NativeScenes(RecordingClient())
                executor = SceneExecutor(RecordingClient())
                try:
                    command('EVENT e9s0c0')
                    command('PROJECT NEW ' + project)
                    created = True
                    command('PROJECT USE ' + project)
                    command('DBCREATENET 254 SceneFixture Cni ' + report['simulator_endpoint'])
                    command(f'DBADDSAFE {network} Application 56 Lighting')
                    for group in (12, 24, 25):
                        command(f'DBADDSAFE {network}/56 Group {group} Scene_{group}')
                    command('PROJECT SAVE ' + project)
                    command('NET LOAD DB ' + project)
                    command('NET OPEN ' + network)
                    wait_for(lambda: any('state=ok' in line for line in command('GET ' + network + ' state').lines), 'synthetic network readiness', 20)
                    report['native_scene_commands'] = {'passed': False, 'results': []}
                    command('GET ' + scene_set + ' *')
                    for operation in (scenes.play, scenes.record):
                        try:
                            response = operation(scene_set, scene_name)
                            report['native_scene_commands']['results'].append({'operation': operation.__name__, 'code': response.code, 'lines': list(response.lines)})
                        except CGateError as error:
                            report['native_scene_commands']['results'].append({'operation': operation.__name__, 'code': error.response.code, 'lines': list(error.response.lines)})
                    report['native_scene_commands']['passed'] = all(row['code'] == 200 for row in report['native_scene_commands']['results'])
                    if not report['native_scene_commands']['passed']:
                        report['native_scene_commands']['limitation'] = 'C-Gate 3.4.0 nJ resolves the empty BS registry, but AY registers scene sets in Bm; both commands return401 for the loaded fixture. No native SCENE success is claimed.'
                    executor.play(SceneFile.load(scene_path))
                    expected = {12: 255, 24: 64, 25: 0}
                    wait_for(lambda: all(simulator.lighting.level(56, group) == value for group, value in expected.items()), 'native scene playback')
                    report['checks']['python_playback_via_native_lighting'] = True
                    for group, value in ((12, 0), (24, 153), (25, 255)):
                        command(f'LIGHTING RAMP {network}/56/{group} {value} 0')
                    wait_for(lambda: all(simulator.lighting.level(56, group) == value for group, value in ((12, 0), (24, 153), (25, 255))), 'pre-record levels')
                    # Record exactly the native cached level, after native GET
                    # and independent peer observations agree for this fixture.
                    for group, value in ((12, 0), (24, 153), (25, 255)):
                        wait_for(lambda group=group, value=value: any(f'level={value}' in line for line in command(f'GET {network}/56/{group} level').lines), 'native cached level before recording')
                    recorded = executor.record(SceneFile.load(scene_path))
                    recorded.save(scene_path, overwrite=True)
                    expected_record = tuple(SceneAction(network + '/56/' + str(group), value) for group, value in ((12, 0), (24, 153), (25, 255)))
                    if recorded.actions != expected_record:
                        raise RuntimeError('Native recorded scene differs from cached current levels: ' + repr(recorded.actions))
                    report['checks']['python_recording_from_native_cached_levels'] = True
                    report['recorded_scene'] = recorded.as_dict()
                    ramp_scene = SceneFile((SceneAction(network + '/56/12', 255, 4),))
                    executor.play(ramp_scene)
                    wait_for(lambda: 30 < simulator.lighting.level(56, 12) < 200, 'active ramp before cache recording')
                    ramp_record = executor.record(ramp_scene)
                    report['active_ramp_recording'] = {'cached_level': ramp_record.actions[0].level,
                                                       'peer_interpolated_level': simulator.lighting.level(56, 12),
                                                       'ramp_seconds': ramp_record.actions[0].ramp_seconds}
                    if not 0 < ramp_record.actions[0].level < 255 or ramp_record.actions[0].ramp_seconds != 0:
                        raise RuntimeError('Recording an active ramp did not produce a native cached intermediate byte level')
                    report['checks']['active_ramp_cached_integer_recording'] = True
                    reloaded = recorded.with_action(1, SceneAction(network + '/56/24', 200, 4))
                    reloaded.save(scene_path, overwrite=True)
                    executor.play(SceneFile.load(scene_path))
                    wait_for(lambda: simulator.lighting.level(56, 24) == 200, 'modified scene ramp playback', 10)
                    report['checks']['modified_file_read_and_ramp'] = True
                    command(f'LIGHTING TERMINATERAMP {network}/56/24')
                    wait_for(lambda: next(row for row in json.loads((work / 'simulator.json').read_text())['lighting']['groups'] if row['application'] == 56 and row['group'] == 24)['remaining'] == 0, 'completed ramp persistence')
                    report['native_events'] = list(client.events)
                    report['lighting_state'] = simulator.lighting.snapshot()
                    persisted = PCISimulator(profile='synthetic', state_path=work / 'simulator.json')
                    report['checks']['lighting_state_persisted'] = persisted.lighting.snapshot() == simulator.lighting.snapshot()
                finally:
                    if created:
                        for text in ('NET CLOSE ' + network, 'PROJECT CLOSE ' + project, 'PROJECT DELETE ' + project):
                            try:
                                if not client.connected:
                                    client.connect()
                                command(text)
                            except Exception as error:
                                report['cleanup_errors'].append({'command': text, 'error': str(error)})
    except Exception as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        if local:
            try:
                local.close()
            except BaseException as error:
                report['cleanup_errors'].append({'local_service': type(error).__name__ + ': ' + str(error)})
            report['local_service'] = local.report
        elif started:
            try:
                inspected = json.loads(docker('inspect', CONTAINER))[0]
                if inspected['Config']['Labels'].get('cbus-toolkit.owner') != owner:
                    raise RuntimeError('Dedicated container ownership changed; refusing cleanup')
                report['container_logs'] = docker('logs', CONTAINER)
                docker('rm', '-f', CONTAINER)
            except Exception as error:
                report['cleanup_errors'].append({'container': CONTAINER, 'error': str(error)})
        report['wire'] = list(simulator.wire_log)
        report['wire_rejections'] = [row for row in simulator.wire_log if 'reason' in row]
        report['source_inputs_changed'] = [name for name, digest in report['source_hashes'].items()
            if hashlib.sha256((BASE / name).read_bytes()).hexdigest() != digest]
        report['passed'] = not report.get('error') and not report['cleanup_errors'] and not report['wire_rejections'] and not report['source_inputs_changed'] and len(report['checks']) == 6 and all(report['checks'].values())
        output = Path(report_path) if report_path is not None else runtime / 'scene-acceptance.json'
        output.write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=20024)
    parser.add_argument('--backend', choices=('docker', 'local'))
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report = verify(port=args.port, report_path=args.report, backend=args.backend)
    print(json.dumps({key: report.get(key) for key in ('passed', 'checks', 'error', 'cleanup_errors', 'work_directory')}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
