"""Capture one complete original eDLT Page Control workflow and compare the CLI.

The unchanged Toolkit 1.18 ``CBusLogicModel`` runs under the task-local macOS
Mono runtime and talks to an owned native C-Gate 3.4.0.2001 through a loopback
recording relay. It opens a synthetic KEYGL5 database unit, applies the Page
Control edit through its own binding, computes PP values/CRCs and saves through
its own C-Gate client. The harness then closes the project; the original model
reloads it by itself and reads the unit back. The Python CLI performs the same
plan/apply/readback on an identically seeded second project through the same
kind of relay. Both final raw memory images and parameter sets are compared.

Usage (writes the full private receipt; nothing is committed automatically)::

    CBUS_MONO_MACOS_ROOT=.../Mono.framework/Versions/6.12.0 \\
    CBUS_TOOLKIT_EXE=.../toolkit/app/CBusToolkit.exe \\
    CBUS_LOCAL_CGATE_VENDOR=.../cgate/app CBUS_CGATE_JAVA=.../bin/java \\
    CBUS_UNITSPEC_DIR=.../unitspec-plain \\
    PYTHONPATH=src:tests:. python research/original_workflow_capture.py receipt.json
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'research/OriginalEdltPageControlWorkflowProbe.cs'
FORMAT = 'cbus-original-workflow-receipt-v1'
WORKFLOW = 'edlt-page-control-database-unit'
GROUP = 42
NETWORK, UNIT = 254, 20
PROJECT = 'ORIGWF'
MEMORY_SIZE = 9216  # upper bound; C-Gate reports the end of KEYGL5 memory
# Assemblies the probe must load from the original application directory.
ORIGINAL_HASHES = {
    'CBusLogicModel.dll': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823',
    'SharpCGateCommunicator.dll': 'fd589789f2c40c0853c06a7d836add0f81a6afe3f397a8d6965a1a1f549a2d6e',
    'SharpLogger.dll': '496a1434da3a592519e94b3eb025a98f0fc91d88341a28d58f33025ce043905c',
    'CBusToolkit.exe': '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab',
}
# Synthetic seed, applied identically to the original and CLI projects.
SEED = (
    ('network', NETWORK, 'Workflow_Fixture', 'Cni', '127.0.0.1:1'),
    ('unit', UNIT, 'eDLT', 'KEYGL5', '5.5.00', '5055EDL'),
    ('application', '', 56, 'Lighting'), ('group', '/56', 1, 'Kitchen'),
    ('application', '', 202, 'Trigger Control'),
    ('application', '', 203, 'Enable'), ('group', '/203', GROUP, 'Pages'),
)


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


class RecordingRelay:
    """Loopback TCP relay that records both directions in one global order.

    Each accepted client gets its own upstream connection. Records are
    ``(connection, direction, bytes)``; nothing is altered or replayed.
    """

    def __init__(self, upstream_port):
        self.upstream = upstream_port
        self.records = []
        self._lock = threading.Lock()
        self._connections = 0
        self._threads, self._sockets = [], []
        self._server = socket.create_server(('127.0.0.1', 0))
        self.port = self._server.getsockname()[1]
        self._closed = False
        self._acceptor = threading.Thread(target=self._accept, daemon=True)
        self._acceptor.start()

    def _accept(self):
        while not self._closed:
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            upstream = socket.create_connection(('127.0.0.1', self.upstream))
            with self._lock:
                self._connections += 1
                number = self._connections
                self._sockets += [client, upstream]
            for source, target, direction in ((client, upstream, '>'), (upstream, client, '<')):
                thread = threading.Thread(target=self._pump, args=(number, source, target, direction), daemon=True)
                self._threads.append(thread)
                thread.start()

    def _pump(self, number, source, target, direction):
        try:
            while True:
                data = source.recv(65536)
                if not data:
                    break
                # Record before forwarding so a reply can never precede its request.
                with self._lock:
                    self.records.append((number, direction, data))
                target.sendall(data)
        except OSError:
            pass
        finally:
            for peer in (source, target):
                try:
                    peer.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def mark(self):
        with self._lock:
            return len(self.records), self._connections

    def close(self):
        self._closed = True
        self._server.close()
        for thread in self._threads:
            thread.join(timeout=10)
        # Close relayed sockets deterministically; later GC warnings would reach other tests' stderr.
        for peer in self._sockets:
            peer.close()


def transcript(records, start=0):
    """Split recorded bytes into ordered protocol lines per connection."""
    buffers, lines = {}, []
    for number, direction, data in records[start:]:
        key = (number, direction)
        buffers[key] = buffers.get(key, b'') + data
        *complete, buffers[key] = buffers[key].split(b'\n')
        for raw in complete:
            lines.append({'connection': number, 'direction': direction,
                          'line': raw.rstrip(b'\r').decode('utf-8', 'replace')})
    for (number, direction), rest in buffers.items():
        if rest:
            lines.append({'connection': number, 'direction': direction, 'line': rest.decode('utf-8', 'replace'), 'unterminated': True})
    return lines


def command_summary(lines, *, project=None):
    """Client commands and their numeric response codes, with bulk replies hashed.

    ``project`` is replaced by ``{PROJECT}`` so identically seeded projects can
    be compared. Response bodies other than final status lines are hashed.
    """
    replies, commands = {}, []
    for entry in lines:
        text = entry['line'] if project is None else entry['line'].replace(project, '{PROJECT}')
        # CLI programming-session names are random per invocation.
        text = re.sub(r'cbus_cli_[0-9a-f]{16}', 'cbus_cli_{SESSION}', text)
        if entry['direction'] == '>':
            tag = re.match(r'^(?:&\d+)?\[(\d+)\]\s*', text)
            commands.append({'connection': entry['connection'], 'id': tag and tag.group(1),
                             'command': text[tag.end():] if tag else text, 'codes': [], 'body': []})
        else:
            tag = re.match(r'^\[(\d+)\]\s*(\d{3})([ -])', text)
            if tag:
                replies.setdefault((entry['connection'], tag.group(1)), []).append((tag.group(2), tag.group(3), text))
    for command in commands:
        rows = replies.get((command['connection'], command['id']), [])
        command['codes'] = sorted({code for code, _, _ in rows})
        command['final'] = next((text.split(' ', 1)[1] for code, sep, text in rows if sep == ' '), None)
        command['reply_lines'] = len(rows)
        command['reply_sha256'] = sha256('\n'.join(text for _, _, text in rows))
        del command['body']
    return commands


def command_sequence_sha256(commands):
    """Run-independent fingerprint: commands, response codes and final status lines."""
    return sha256(canonical([[c['command'], c['codes'], c['final']] for c in commands]))


def parse_probe(stdout):
    result = {'pp': {}, 'lines': [], 'changed': [], 'host_requests': [], 'assemblies': {}, 'applications': []}
    for line in stdout.replace('\r\n', '\n').splitlines():
        match = re.match(r'^(loaded|edited|saved)-pp:([^\t]+)\t(.*)$', line)
        if match:
            result['pp'].setdefault(match.group(1), {})[match.group(2)] = match.group(3)
            continue
        key, _, value = line.partition(':')
        if key == 'changed':
            result['changed'].append(value)
        elif key == 'host-request':
            result['host_requests'].append(value)
        elif key == 'assembly':
            name, _, location = value.partition('\t')
            result['assemblies'][name] = location
        elif key == 'application':
            result['applications'].append(value)
        else:
            result['lines'].append(line)
            if key in ('load-result', 'save-result', 'identity', 'binding-before', 'binding-after',
                       'page-control', 'complete', 'failure-stage', 'failure'):
                result[key.replace('-', '_')] = value
    return result


class OriginalModelRunner:
    """Pinned task-local Mono and original assemblies; one compile, sequential runs."""

    def __init__(self, app, mono_root, work):
        from research import firmware_oracle
        if platform.system() != 'Darwin':
            raise ValueError('The original workflow capture uses the macOS Mono runtime')
        self.app, self.runtime, self.work = Path(app).resolve(), Path(mono_root).resolve(), Path(work)
        self._runtime_hashes = firmware_oracle.RUNTIME_HASHES
        self.verify()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('MONO_', 'DYLD_'))}
        self.env.update(MONO_CFG_DIR=str(self.runtime / 'etc'),
                        MONO_PATH=str(self.app) + ':' + str(self.runtime / 'lib/mono/4.5'),
                        DYLD_FALLBACK_LIBRARY_PATH=str(self.runtime / 'lib'))
        source = self.work / PROBE.name
        source.write_bytes(PROBE.read_bytes())
        compiled = subprocess.run([str(self.runtime / 'bin/mono-sgen64'), str(self.runtime / 'lib/mono/4.5/mcs.exe'),
                                   '-r:' + str(self.app / 'CBusLogicModel.dll'), '-r:' + str(self.app / 'SharpCGateCommunicator.dll'),
                                   '-r:System.Xml.Linq', PROBE.name], cwd=self.work, env=self.env,
                                  capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise RuntimeError('Original workflow probe compilation failed: ' + compiled.stdout[-2000:] + compiled.stderr[-2000:])
        self.executable = self.work / (PROBE.stem + '.exe')
        self.compiled_sha256 = sha256(self.executable.read_bytes())

    def verify(self):
        from research import firmware_oracle
        firmware_oracle.MacOSFirmwareOracle._check_files(self.runtime, self._runtime_hashes)
        firmware_oracle.MacOSFirmwareOracle._check_files(self.app, ORIGINAL_HASHES)

    def run(self, *arguments, timeout=240):
        self.verify()
        completed = subprocess.run([str(self.runtime / 'bin/mono-sgen64'), str(self.executable), *map(str, arguments)],
                                   cwd=self.work, env=self.env, capture_output=True, text=True, timeout=timeout)
        self.verify()
        return completed


def seed_project(client, project):
    from cbus_toolkit.native import NativeDatabase, NativeProjects
    database, projects = NativeDatabase(client), NativeProjects(client)
    network = f'//{project}/{NETWORK}'
    projects.operation('new', project)
    for step in SEED:
        if step[0] == 'network':
            database.create_network(project, *step[1:])
        elif step[0] == 'unit':
            database.create_unit(network, step[1], step[2], step[3], step[4], catalog_number=step[5])
        else:
            database.add(network + step[1], step[0], step[2], step[3])
    projects.operation('save', project)
    return network


def network_xml(client, network):
    reply = client.command('DBGETXML ' + network)
    return '\n'.join(line[4:] for line in reply.lines if line.startswith('347-'))


def normalized_database(xml, project):
    """Stable network document: generated OIDs and the project name removed."""
    root = ET.fromstring(xml)
    for element in root.iter():
        for child in list(element):
            if child.tag == 'OID':
                element.remove(child)
    text = ET.tostring(root, encoding='unicode')
    return text.replace(project, '{PROJECT}')


def database_leaves(xml):
    """Leaf element values keyed by a stable path (PP elements keyed by Name)."""
    leaves = {}

    def walk(element, path):
        children = list(element)
        if not children:
            leaves[path] = (element.text or '') + ''.join(f' @{k}={v}' for k, v in sorted(element.attrib.items()) if k != 'Name')
        counts = {}
        for child in children:
            key = child.tag + (f"[{child.get('Name')}]" if child.get('Name') else '')
            counts[key] = counts.get(key, 0) + 1
            walk(child, f'{path}/{key}#{counts[key]}')

    walk(ET.fromstring(xml), '')
    return leaves


def database_differences(original, other):
    left, right = database_leaves(original), database_leaves(other)
    return {path: [left.get(path), right.get(path)] for path in sorted(set(left) | set(right)) if left.get(path) != right.get(path)}


def raw_image(client, network, source):
    """Full database PP memory as C-Gate reports it; ``??`` marks invalid bytes."""
    from cbus_toolkit.cgate import CGateError
    from cbus_toolkit.programming import Programmer
    chunks, start, step = [], 0, 256
    with Programmer(client).load(network, source) as session:
        while start < MEMORY_SIZE:
            try:
                reply = session.get_raw_data(start, min(step, MEMORY_SIZE - start))
            except CGateError as error:
                if 'out of range' not in str(error) or step == 1:
                    if 'out of range' in str(error):
                        break
                    raise
                step //= 16
                continue
            text = reply.lines[-1].split('RawData=')[1].strip().lower()
            if re.fullmatch(r'(?:[0-9a-f]{2}|\?\?)+', text) is None:
                raise ValueError('Unexpected raw PP data')
            chunks.append(text)
            start += len(text) // 2
        values = session.values()
    return ''.join(chunks), values


def run_cli(port, *arguments, status=0):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(str(ROOT / p) for p in ('src', 'tests', '.')))
    completed = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, arguments)], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=300)
    if completed.returncode != status:
        raise RuntimeError(f'CLI {arguments} exited {completed.returncode}: {completed.stdout[-2000:]}{completed.stderr[-2000:]}')
    return json.loads(completed.stdout or completed.stderr)


def lifecycle_cache(requirements, xml):
    """Cache facts for ``edlt-lifecycle`` read from one exact DBGETXML snapshot.

    Only the facts this fixture's requirements ask for are supported: present
    applications and group existence. Application objects contain the virtual
    unused group 255. Any image or level requirement fails closed.
    """
    root = ET.fromstring(xml)
    present = {int(a.findtext('Address')): {int(g.findtext('Address')) for g in a.findall('Group')}
               for a in root.findall('Application')}
    applications = sorted(entry['application'] for entry in requirements['applications'])
    missing = [a for a in applications if a not in present]
    if missing:
        raise ValueError(f'Required applications are absent: {missing}')
    groups = []
    for entry in requirements['groups']:
        if set(entry['facts']) != {'exists'} or entry.get('conditional_reasons'):
            raise ValueError('Only group existence facts are supported by this harness')
        application, group = entry['application'], entry['group']
        groups.append({'application': application, 'group': group,
                       'exists': group == 255 or group in present[application]})
    return {'format': 'cbus-edlt-lifecycle-cache-v1', 'applications': applications, 'groups': groups}


def capture(*, mono_root, app, vendor, java, specs, runtime_report=None):
    """Run the original and CLI workflows on one owned native C-Gate and build the receipt.

    Variants run sequentially on the same project name, so the name-derived
    ``Project`` PP value is identical: ``original`` (unchanged Toolkit model),
    ``cli`` (lifecycle then Page Control), ``cli_first_open`` (Page Control
    alone; the CLI applies the original first open to the never-opened unit)
    and ``cli_direct`` (Page Control with ``--no-first-open``).
    """
    from research.local_cgate import LocalCGate
    from cbus_toolkit.cgate import CGateClient
    from cbus_toolkit.native import NativeProjects
    from cbus_toolkit.unitspec import UnitSpecStore
    from cbus_toolkit.edlt_page_control import EdltPageControl

    spec = UnitSpecStore(Path(specs)).load('KEYGL5.xml')
    editor = EdltPageControl(spec)
    snap = editor.snapshot
    # The owned C-Gate starts empty; a fixed name keeps the name-derived Project PP reproducible.
    project = PROJECT
    network, source = f'//{project}/{NETWORK}', f'/db//{project}/{NETWORK}/p/{UNIT}'
    receipt = {'format': FORMAT, 'workflow': WORKFLOW, 'group': GROUP, 'passed': False,
               'evidence_class': 'original-model+native-cgate', 'physical_device_verified': False}
    raw, variants = {}, {}
    service = LocalCGate(vendor, java=java)
    # Owned loopback clients may create, program and delete disposable projects.
    (service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
    with tempfile.TemporaryDirectory(prefix='cbus-original-workflow-') as work, service:
        work = Path(work)
        runner = OriginalModelRunner(app, mono_root, work)
        relay = RecordingRelay(service.port)
        base = ('cgate', '--host', '127.0.0.1', '--port', relay.port, '--timeout', 60, 'unit',
                '--lock-address', network, '--source', source)
        try:
            with CGateClient('127.0.0.1', service.port, timeout=60) as client:
                projects = NativeProjects(client)

                def finish(result, lines):
                    image, values = raw_image(client, network, source)
                    result.update(image=image, values=values, transcript=lines,
                                  database=normalized_database(network_xml(client, network), project),
                                  state=client.command(f'GET {network} state').lines)
                    for action in ('close', 'delete'):
                        projects.operation(action, project)
                    return result

                for kind in ('original', 'cli', 'cli_first_open', 'cli_direct'):
                    seed_project(client, project)
                    image, values = raw_image(client, network, source)
                    result = {'seeded_database': normalized_database(network_xml(client, network), project),
                              'initial_image': image, 'initial_values': values}
                    mark, _ = relay.mark()
                    if kind == 'original':
                        oid = next(line.split('=', 1)[1] for line in client.command(f'DBGET {network}/p/{UNIT}').lines if '/OID=' in line)
                        # Open, edit and save entirely inside the original model.
                        edit = runner.run(relay.port, project, NETWORK, UNIT, oid, 'edit', GROUP)
                        result['edit'] = parse_probe(edit.stdout)
                        result['edit_exit'] = edit.returncode
                        edit_lines = transcript(relay.records, mark)
                        # The harness only closes; the model's useProject() issues PROJECT LOAD itself.
                        projects.operation('close', project)
                        mark, _ = relay.mark()
                        reopen = runner.run(relay.port, project, NETWORK, UNIT, oid, 'readback')
                        result['reopen'] = parse_probe(reopen.stdout)
                        result['reopen_exit'] = reopen.returncode
                        result['reopen_transcript'] = transcript(relay.records, mark)
                        raw['original'] = {'edit_stdout': edit.stdout, 'edit_stderr': edit.stderr[-8000:],
                                           'reopen_stdout': reopen.stdout, 'reopen_stderr': reopen.stderr[-8000:]}
                        variants[kind] = finish(result, edit_lines)
                        continue
                    initial = work / f'{kind}-initial.json'
                    run_cli(relay.port, *base, 'export', initial)
                    steps = []
                    if kind == 'cli':
                        requirements = run_cli(relay.port, 'edlt', 'lifecycle-requirements', initial)
                        cache = lifecycle_cache(requirements, network_xml(client, network))
                        (work / 'cache.json').write_text(json.dumps(cache))
                        lifecycle = run_cli(relay.port, *base, 'edlt-lifecycle', '--metadata', work / 'cache.json')
                        steps.append({'command': 'edlt-lifecycle', 'saved': lifecycle.get('saved'),
                                      'verified': lifecycle.get('verified'), 'cache': cache,
                                      'changed_parameters': sorted(lifecycle.get('changes', {}))})
                        initial = work / f'{kind}-lifecycle.json'
                        run_cli(relay.port, *base, 'export', initial)
                    if kind == 'cli_first_open':
                        # One command: the CLI detects the never-opened unit, derives the
                        # lifecycle cache from DBGETXML and stages first open before the edit.
                        preview = run_cli(relay.port, *base, '--dry-run', 'edlt-page-control', '--group', GROUP)
                        result['plan_after'] = preview['parameters']
                        applied = run_cli(relay.port, *base, 'edlt-page-control', '--group', GROUP)
                        first_open = applied.get('first_open') or {}
                        steps.append({'command': 'edlt-page-control', 'saved': applied.get('saved'),
                                      'verified': applied.get('verified'),
                                      'first_open': {key: first_open.get(key) for key in (
                                          'config_version', 'never_initialized', 'applied', 'metadata_provenance', 'metadata')},
                                      'first_open_changed_parameters': sorted(first_open.get('lifecycle_changes', {})),
                                      'changed_parameters': sorted(applied.get('changes', {}))})
                    else:
                        direct = ('--no-first-open',) if kind == 'cli_direct' else ()
                        plan = run_cli(relay.port, 'edlt', 'page-control-plan', initial, '--group', GROUP)
                        before = snap(json.loads(initial.read_text())['parameters'])
                        result['plan_after'] = {**before, **{k: tuple(v) if isinstance(v, list) else v for k, v in plan['changes'].items()}}
                        applied = run_cli(relay.port, *base, 'edlt-page-control', *direct, '--group', GROUP)
                        steps.append({'command': 'edlt-page-control', 'options': list(direct), 'saved': applied.get('saved'),
                                      'verified': applied.get('verified'), 'changed_parameters': sorted(plan['changes'])})
                    for action in ('save', 'close', 'load'):
                        projects.operation(action, project)
                    result['shown'] = run_cli(relay.port, *base, 'show')
                    result['steps'] = steps
                    variants[kind] = finish(result, transcript(relay.records, mark))
        finally:
            relay.close()

    original, cli, direct = variants['original'], variants['cli'], variants['cli_direct']
    first_open = variants['cli_first_open']
    edited, readback = original['edit'], original['reopen']
    saved = snap(edited['pp']['saved'])

    def listed(values):
        return {k: list(v) if isinstance(v, tuple) else v for k, v in values.items()}

    def differences(left, right):
        return sorted(name for name in left if left[name] != right.get(name))

    original_commands = {entry['command'] for entry in command_summary(original['transcript'], project=project)}

    def database_equal_except_null_writes(other):
        # The original writes DB fields it read as C-Gate's "null" display back as literal
        # "null" strings; any other database difference fails this comparison.
        return all(values[0] == 'null' and values[1] is None and re.fullmatch(r'/Unit#1/(\w+)#1', path)
                   and f'dbset //{{PROJECT}}/{NETWORK}/p/{UNIT}/{path.split("/")[2][:-2]} "null"' in original_commands
                   for path, values in database_differences(original['database'], other['database']).items())
    stages = {
        'original_open': edited.get('load_result') == 'True',
        'original_edit_through_binding': edited.get('binding_after', '').startswith(f'{GROUP}:'),
        'original_save': edited.get('save_result') == 'True' and original['edit_exit'] == 0,
        'original_reopen_after_close': readback.get('load_result') == 'True' and readback.get('complete') == 'true',
        'original_reopened_page_control': readback.get('page_control') == str(GROUP),
        'cli_steps_saved_and_verified': all(step['saved'] and step['verified'] for step in cli['steps']),
        'cli_first_open_detected_and_applied': all(step['saved'] and step['verified'] for step in first_open['steps'])
            and first_open['steps'][0]['first_open'].get('applied') is True
            and first_open['steps'][0]['first_open'].get('metadata_provenance') == 'native-database-network-xml',
    }
    comparisons = {
        'identical_seeded_inputs': all(v['seeded_database'] == original['seeded_database'] and v['initial_image'] == original['initial_image']
                                       and v['initial_values'] == original['initial_values'] for v in variants.values()),
        'original_saved_pp_equals_cgate_readback': saved == snap(original['values']),
        'cli_plan_equals_original_saved_pp': snap(cli['plan_after']) == saved,
        'cli_readback_equals_original_readback': snap(cli['shown']) == snap(original['values']),
        'cli_cgate_parameters_equal_original': snap(cli['values']) == snap(original['values']),
        'cli_crcs_equal_original': editor.crcs(snap(cli['values'])) == editor.crcs(saved),
        'raw_images_identical': cli['image'] == original['image'],
        'database_equal_except_original_literal_null_writes': database_equal_except_null_writes(cli),
        # Page Control alone, without a separate lifecycle step, must equal the original.
        'cli_first_open_preview_equals_original_saved_pp': snap(first_open['plan_after']) == saved,
        'cli_first_open_readback_equals_original_readback': snap(first_open['shown']) == snap(original['values']),
        'cli_first_open_cgate_parameters_equal_original': snap(first_open['values']) == snap(original['values']),
        'cli_first_open_crcs_equal_original': editor.crcs(snap(first_open['values'])) == editor.crcs(saved),
        'cli_first_open_raw_images_identical': first_open['image'] == original['image'],
        'cli_first_open_database_equal_except_original_literal_null_writes': database_equal_except_null_writes(first_open),
        'network_never_opened': all(any('state=new' in line for line in v['state']) for v in variants.values()),
    }
    loaded = {name: location for name, location in edited['assemblies'].items()
              if Path(location).resolve().parent == Path(app).resolve()}
    receipt.update(
        stages=stages, comparisons=comparisons,
        inputs={'seed': [list(step) for step in SEED], 'seed_sha256': sha256(canonical([list(s) for s in SEED])),
                'seeded_database_sha256': sha256(original['seeded_database']),
                'initial_raw_image_sha256': sha256(original['initial_image']),
                'initial_parameters_sha256': sha256(canonical(original['initial_values'])),
                'unit_specification_sha256': sha256((Path(specs) / 'KEYGL5.xml').read_bytes()),
                'probe_source_sha256': sha256(PROBE.read_bytes()),
                'harness_source_sha256': sha256(Path(__file__).read_bytes())},
        original_runtime={'mono_version': '6.12.0.206', 'compiled_probe_sha256': runner.compiled_sha256,
                          'runtime_files_sha256': sha256(canonical(runner._runtime_hashes)),
                          'platform_adaptation': 'Environment.NewLine set to the Windows value \\r\\n before any original code runs'},
        original_assemblies={Path(loc).name: sha256(Path(loc).read_bytes()) for loc in sorted(loaded.values())},
        native_cgate={'jar_sha256': service.report.get('vendor_jar_sha256'), 'java_sha256': service.report.get('java_sha256'),
                      'cleanup_complete': service.report.get('cleanup_complete')},
        original={
            'identity': edited.get('identity'), 'binding_before': edited.get('binding_before'),
            'binding_after': edited.get('binding_after'), 'changed_parameters': edited['changed'],
            'edit_load_normalization': differences(snap(edited['pp']['loaded']), snap(original['initial_values'])),
            'save_stage_changes': differences(saved, snap(edited['pp']['edited'])),
            'reopen_load_normalization': differences(snap(readback['pp']['loaded']), saved),
            'host_requests': {'edit': edited['host_requests'], 'reopen': readback['host_requests']},
            'saved_parameters_sha256': sha256(canonical(listed(saved))),
            'crcs': listed(editor.crcs(saved)),
            'page_control_byte': original['image'][0x131 * 2:0x132 * 2],
            'memory_bytes': len(original['image']) // 2,
            'invalid_bytes': sum(original['image'][i:i + 2] == '??' for i in range(0, len(original['image']), 2)),
            'final_raw_image_sha256': sha256(original['image']),
            'final_database_sha256': sha256(original['database']),
            'database_differences_from_cli': database_differences(original['database'], cli['database']),
            'edit_transcript': command_summary(original['transcript'], project=project),
            'reopen_transcript': command_summary(original['reopen_transcript'], project=project),
            'command_sequence_sha256': command_sequence_sha256(
                command_summary(original['transcript'] + original['reopen_transcript'], project=project)),
            'transcript_sha256': sha256(canonical(original['transcript'] + original['reopen_transcript']).replace(project, '{PROJECT}'))},
        cli={'steps': cli['steps'], 'page_control_byte': cli['image'][0x131 * 2:0x132 * 2],
             'final_raw_image_sha256': sha256(cli['image']), 'final_database_sha256': sha256(cli['database']),
             'transcript': command_summary(cli['transcript'], project=project),
             'command_sequence_sha256': command_sequence_sha256(command_summary(cli['transcript'], project=project)),
             'transcript_sha256': sha256(canonical(cli['transcript']).replace(project, '{PROJECT}'))},
        cli_first_open={'steps': first_open['steps'], 'page_control_byte': first_open['image'][0x131 * 2:0x132 * 2],
                        'final_raw_image_sha256': sha256(first_open['image']),
                        'final_database_sha256': sha256(first_open['database']),
                        'parameter_differences_from_original': differences(saved, snap(first_open['values'])),
                        'transcript': command_summary(first_open['transcript'], project=project),
                        'command_sequence_sha256': command_sequence_sha256(command_summary(first_open['transcript'], project=project)),
                        'transcript_sha256': sha256(canonical(first_open['transcript']).replace(project, '{PROJECT}'))},
        cli_direct={'steps': direct['steps'], 'final_raw_image_sha256': sha256(direct['image']),
                    'raw_images_identical_to_original': direct['image'] == original['image'],
                    'parameter_differences_from_original': differences(saved, snap(direct['values']))},
    )
    receipt['passed'] = all(stages.values()) and all(comparisons.values())
    if runtime_report:
        Path(runtime_report).write_text(json.dumps({'receipt': receipt, 'raw': raw, 'variants': {
            kind: {key: value for key, value in variant.items() if key not in ('edit', 'reopen')}
            for kind, variant in variants.items()}}, indent=1, default=list) + '\n')
    return receipt


def from_environment(runtime_report=None):
    names = ('CBUS_MONO_MACOS_ROOT', 'CBUS_TOOLKIT_EXE', 'CBUS_LOCAL_CGATE_VENDOR', 'CBUS_CGATE_JAVA', 'CBUS_UNITSPEC_DIR')
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise ValueError('Set ' + ', '.join(missing))
    return capture(mono_root=os.environ['CBUS_MONO_MACOS_ROOT'], app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent,
                   vendor=os.environ['CBUS_LOCAL_CGATE_VENDOR'], java=os.environ['CBUS_CGATE_JAVA'],
                   specs=os.environ['CBUS_UNITSPEC_DIR'], runtime_report=runtime_report)


if __name__ == '__main__':
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'research/runtime/original-workflow-page-control.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    result = from_environment(runtime_report=output.with_suffix('.raw.json'))
    output.write_text(json.dumps(result, indent=1) + '\n')
    print(json.dumps({'passed': result['passed'], 'stages': result['stages'], 'comparisons': result['comparisons'],
                      'cli_direct': result['cli_direct']}, indent=1))
    sys.exit(0 if result['passed'] else 1)
