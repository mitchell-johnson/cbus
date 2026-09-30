"""Actual Rust CLI journals reconciled offline against synthetic XML and CBZ.

Opt in with CBUS_TOOLS_BIN=/absolute/path/to/cbus-tools. No hardware or vendor
software is used. The two costly CLI runs are cached; each test gets its own
project, journal and genuine attempt marker. Wire frames are made from literal
protocol bytes, never a Rust or production Python encoder/decoder.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from cbus_toolkit.pci_selected_serial import SelectedSerialPlan, route_from_project
from cbus_toolkit.project import ProjectDocument
from cbus_toolkit.serial_reconcile import (ProjectFileDatabase, ReconcileError,
    ReconcileRecord, default_record_path, reconcile, verify_journal)
from tests.test_pci_selected_serial_routed import (A, B, C, BEFORE, AFTER, ONE,
    SIX, before_responses, manager, peer, mmi, identify4, receipt, packed)
from tests.test_serial_reconcile_routed import OID, project_bytes

BIN = os.environ.get('CBUS_TOOLS_BIN')


def request(payload, checksum=False):
    """Independent confirmed command with the canonical g allocation."""
    payload = bytes(payload)
    if checksum:
        payload += bytes([-sum(payload) & 255])
    return b'\\' + payload.hex().upper().encode() + b'g\r'


def expected_requests(route, checksum):
    prefix = [0x03, route[0], 9 * len(route), *route[1:]]
    mmi_request = request([*prefix, 255, 0xFA, 255, 0], checksum)
    ids = {unit: request([0x46, route[0], 9 * len(route), *route[1:], unit, 0x21, 4], checksum)
           for unit in (6, 16, 255)}
    body = b'\x00' + packed(A) + b'\x06'
    co = request(bytes([*prefix, 255, 0x0F]) + body + bytes([-sum(body) & 255]), checksum)
    return mmi_request, ids, co


@contextmanager
def rust_peer(route, checksum):
    """Persistent loopback PCI with literal replies and one remote CO transition."""
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(1)
    state = {'requests': [], 'errors': [], 'moves': 0}
    stop = threading.Event()
    mmi_request, ids, co = expected_requests(route, checksum)
    local_id = request([0x46, 16, 0, 0x21, 4], checksum)
    local_options = request([0x46, 16, 0, 0x1A, 66, 1], checksum)

    def direct(payload):
        payload = bytes(payload)
        if checksum: payload += bytes([-sum(payload) & 255])
        return payload.hex().upper().encode() + b'\r\n'

    def routed(response):
        if checksum:
            return response
        # The attached PCI is in SRCHK-off mode. Omit each literal routed
        # response's checksum too, rather than exercising only direct replies.
        return b''.join(line[:-2] + b'\r\n' for line in response.split(b'\r\n') if line)

    def serve():
        try:
            while not stop.is_set():
                try: connection, _ = listener.accept()
                except socket.timeout: continue
                with connection:
                    connection.settimeout(1)
                    pending = b''
                    while not stop.is_set():
                        try: chunk = connection.recv(4096)
                        except socket.timeout: continue
                        if not chunk: break
                        pending += chunk
                        while b'\r' in pending:
                            line, pending = pending.split(b'\r', 1)
                            line += b'\r'
                            if not line.startswith(b'\\'): continue  # reset/header options
                            confirmed = ord('g') <= line[-2] <= ord('z')
                            normalized = line[:-2] + b'g\r' if confirmed else line
                            state['requests'].append(normalized)
                            if confirmed: connection.sendall(line[-2:-1] + b'.')
                            if normalized == local_id:
                                # Synthetic attached PCI 100966.1187, bare CAL reply.
                                response = direct(bytes.fromhex('8D04FFFFFF000018A664A3B10005'))
                            elif normalized == local_options:
                                response = direct([0x86, 16, 16, 0, 0x82, 66, 5])
                            elif normalized == mmi_request:
                                response = routed(mmi(route, AFTER if state['moves'] else BEFORE))
                            elif normalized == co:
                                if state['moves']: raise AssertionError('CO replayed')
                                state['moves'] += 1
                                response = routed(receipt(route, 6, A))
                            elif normalized in ids.values():
                                unit = next(unit for unit, value in ids.items() if value == normalized)
                                identities = ({6: [A], 16: [C], 255: [B]} if state['moves']
                                              else {16: [C], 255: [A, B]})
                                response = routed(b''.join(identify4(route, unit, serial)
                                                          for serial in identities[unit]))
                            else:
                                raise AssertionError(f'unexpected literal request {line!r}')
                            connection.sendall(response)
        except Exception as error:
            if not stop.is_set(): state['errors'].append(repr(error))

    thread = threading.Thread(target=serve, daemon=True); thread.start()
    try: yield listener.getsockname(), state
    finally:
        stop.set(); thread.join(3); listener.close()
        if thread.is_alive(): raise AssertionError('Rust PCI peer did not stop')


@unittest.skipUnless(BIN, 'set CBUS_TOOLS_BIN to run actual Rust serial-apply interoperability')
class RustSerialReconcileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = tempfile.TemporaryDirectory(prefix='rust-reconcile-cache-')
        cls.addClassCleanup(cls.cache.cleanup)
        cls.fixtures = {}
        for depth, cbz, checksum in ((1, False, False), (6, True, True)):
            directory = Path(cls.cache.name) / str(depth); directory.mkdir()
            project = directory / ('project.cbz' if cbz else 'project.xml')
            raw = project_bytes(depth)
            if cbz:
                with ZipFile(project, 'w') as archive:
                    archive.writestr('project.xml', raw)
                    archive.writestr('attachments/opaque.bin', b'\x00opaque\xff')
            else: project.write_bytes(raw)
            route, digest = route_from_project(project, source_network=254, target_network=254-depth)
            assert route == (ONE if depth == 1 else SIX)
            with peer(before_responses(route)) as (endpoint, _):
                plan = manager(endpoint, command_checksum=checksum).plan(A, 6, route=route,
                                                                        project_sha256=digest)
            journal = directory / 'journal.json'
            with rust_peer(route, checksum) as (endpoint, state):
                value = plan.as_dict(); value['endpoint'] = dict(host=endpoint[0], port=endpoint[1])
                value['before']['endpoint'] = dict(value['endpoint'])
                value = SelectedSerialPlan.from_dict(value).as_dict()
                plan_file = directory / 'plan.json'; plan_file.write_text(json.dumps(value))
                command = [str(Path(BIN).resolve()), 'serial-apply', '--pci', f'{endpoint[0]}:{endpoint[1]}',
                    '--plan', str(plan_file), '--project', str(project), '--source-network', '254',
                    '--target-network', str(254-depth), '--journal', str(journal), '--timeout', '60']
                result = subprocess.run(command, capture_output=True, text=True, timeout=90)
            assert not state['errors'], state['errors']
            assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
            assert state['moves'] == 1, state
            mmi_request, ids, co = expected_requests(route, checksum)
            assert state['requests'].count(co) == 1, state
            assert state['requests'].count(mmi_request) == 4, state
            assert state['requests'].count(ids[6]) == 1, state
            retained = json.loads(journal.read_text())
            assert retained['format'] == 'cbus-selected-serial-apply-v2', retained
            assert retained['outcome'] == 'observed_expected_change', retained
            # Verify the original producer artifact before tests relocate its
            # journal/marker paths into their private working directories.
            move = verify_journal(journal)
            assert move.receipt_matches_request is True
            cls.fixtures[depth] = (project, journal, result.stdout, tuple(state['requests']))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def fixture(self, depth=1):
        source_project, source_journal, output, requests = self.fixtures[depth]
        project = self.directory / source_project.name
        journal = self.directory / 'journal.json'
        shutil.copyfile(source_project, project)
        value = json.loads(source_journal.read_text())
        marker_key = next(key for key in ('attempt_identity', 'attempt_marker') if key in value)
        old_marker = Path(value[marker_key]); marker = self.directory / old_marker.name
        # Preserve the CLI-produced marker's exact plan and attempt identity;
        # relocating its journal path does not alter the canonical plan.
        marker_value = json.loads(old_marker.read_text())
        self.relocate(marker_value, source_journal.parent.resolve() / source_journal.name,
                      journal.parent.resolve() / journal.name)
        self.relocate(value, old_marker, marker)
        self.relocate(value, source_journal, journal)
        marker.write_text(json.dumps(marker_value)); journal.write_text(json.dumps(value))
        return project, journal, project.read_bytes()

    @staticmethod
    def relocate(value, old, new):
        if isinstance(value, dict):
            for key, child in value.items():
                if child == str(old): value[key] = str(new)
                else: RustSerialReconcileTests.relocate(child, old, new)
        elif isinstance(value, list):
            for child in value: RustSerialReconcileTests.relocate(child, old, new)

    def assert_preserved(self, project, original, depth):
        document = ProjectDocument.load(project)
        target = f'/network/{254-depth}/unit/6'
        self.assertEqual(document.path_of(document.resolve('oid:' + OID)), target)
        self.assertEqual(document.get_field(f'/network/{254-depth}/unit/21', 'Partner'), OID)
        self.assertEqual(document.parameters(target), {'UnitAddress': '0x6', 'GroupAddress': '0x1 0xff'})
        document.update(target, {'Address': '255'})
        document.set_parameter(f'/network/{254-depth}/unit/255', 'UnitAddress', '0xff')
        self.assertEqual(document.raw_xml(), ProjectDocument.from_snapshot(original).raw_xml())
        if project.suffix == '.cbz':
            with ZipFile(project) as archive:
                self.assertEqual(archive.read('attachments/opaque.bin'), b'\x00opaque\xff')

    def test_actual_cli_xml_and_cbz_journals_reconcile_offline(self):
        for depth in (1, 6):
            with self.subTest(depth=depth), tempfile.TemporaryDirectory() as directory:
                self.directory = Path(directory)
                project, journal, original = self.fixture(depth)
                move = verify_journal(journal)
                self.assertEqual(move.route, tuple(ONE if depth == 1 else SIX))
                self.assertEqual((move.source_network, move.target_network), (254, 254-depth))
                self.assertEqual(reconcile(journal, ProjectFileDatabase(project))['outcome'], 'planned')
                self.assertEqual(project.read_bytes(), original)
                self.assertFalse(default_record_path(journal).exists())
                result = reconcile(journal, ProjectFileDatabase(project), apply=True, network=254-depth)
                self.assertEqual(result['outcome'], 'reconciled')
                self.assertFalse(result['bus_io_performed'])
                self.assert_preserved(project, original, depth)
                saved = project.read_bytes()
                with patch.object(ProjectDocument, 'save', side_effect=AssertionError('no-op saved')):
                    self.assertEqual(reconcile(journal, ProjectFileDatabase(project), apply=True)['outcome'],
                                     'already_reconciled')
                self.assertEqual(project.read_bytes(), saved)

    def assert_refused(self, project, journal, original):
        with patch.object(ProjectDocument, 'save', side_effect=AssertionError('invalid journal wrote')):
            with self.assertRaises(ReconcileError): reconcile(journal, ProjectFileDatabase(project), apply=True)
        self.assertEqual(project.read_bytes(), original)
        self.assertFalse(default_record_path(journal).exists())

    def test_legacy_rust_v1_and_missing_raw_proof_are_refused(self):
        project, journal, original = self.fixture()
        pristine = json.loads(journal.read_text())
        for legacy in (False, True):
            value = deepcopy(pristine); value.pop('reconciliation_evidence', None)
            if legacy: value['format'] = 'cbus-selected-serial-apply-v1'
            journal.write_text(json.dumps(value)); self.assert_refused(project, journal, original)

    def test_strict_raw_capture_and_summary_mutations_refuse_before_writes(self):
        project, journal, original = self.fixture(6)
        pristine = json.loads(journal.read_text())
        proof = ('reconciliation_evidence',)
        initial = (*proof, 'before', 'initial_mmi')
        identity = (*proof, 'before', 'serial_observations', 0, 'capture')
        mutations = [
            ('journal-version', ('format',), 'cbus-selected-serial-apply-v3'),
            ('serial-summary', ('serial',), B),
            ('source-network', ('route_binding', 'source_network'), 253),
            ('route-summary', ('route_binding', 'route'), ONE),
            ('project-digest', ('route_binding', 'project_sha256'), '0'*64),
            ('proof-version', (*proof, 'format'), 'cbus-rust-selected-serial-reconciliation-v2'),
            ('proof-source', (*proof, 'source'), 'another-producer'),
            ('connection-claim', (*proof, 'raw_connection_capture'), True),
            ('capture-scope', (*proof, 'frame_capture_scope'), 'all_connection_bytes'),
            ('before-route', (*proof, 'before', 'route'), ONE),
            ('after-route', (*proof, 'after', 'route'), ONE),
            ('before-local', (*proof, 'before', 'local_unit'), 17),
            ('capture-source', (*identity, 'source'), 'another-producer'),
            ('capture-version', (*identity, 'format'), 'cbus-selected-serial-frame-capture-v2'),
            ('request', (*identity, 'request_hex'), '00'),
            ('confirmation', (*identity, 'confirmation'), 'f'),
            ('incomplete', (*initial, 'complete'), False),
            ('truncated-stream', (*identity, 'stream_complete'), False),
            ('termination', (*initial, 'termination'), 'quiet_window_elapsed'),
            ('options-request', (*proof, 'local_options', 'request_hex'), '00'),
            ('local-identity-request', (*proof, 'local_identity', 'request_hex'), '00'),
            ('exchange-request', (*proof, 'exchange', 'request_hex'), '00'),
            ('send-count', ('sends',), 2),
            ('receipt-summary', ('receipt_matched',), False),
            ('metadata', ('options_verified',), [4]),
            ('after-metadata', ('after_collection_complete',), False),
        ]
        for name, path, replacement in mutations:
            with self.subTest(mutation=name):
                value = deepcopy(pristine); parent = value
                for part in path[:-1]: parent = parent[part]
                parent[path[-1]] = replacement
                journal.write_text(json.dumps(value)); self.assert_refused(project, journal, original)
        for name in ('raw-byte', 'raw-tail', 'raw-extra-tail', 'wire-lowercase',
                     'parser-checksum', 'checksum-on-omission', 'missing-block',
                     'block-order', 'probe-order', 'unknown-field', 'before-after',
                     'before-local-duplicate', 'preintent-local-duplicate', 'after-local-duplicate',
                     'remote-reply-overflow'):
            with self.subTest(mutation=name):
                value = deepcopy(pristine); evidence = value['reconciliation_evidence']
                capture = evidence['before']['initial_mmi']
                if name == 'raw-byte':
                    raw = bytearray.fromhex(capture['raw_frames_hex'][1]); raw[0] = ord('0')
                    capture['raw_frames_hex'][1] = raw.hex()
                elif name == 'raw-tail':
                    capture['raw_frames_hex'][1] = bytes.fromhex(capture['raw_frames_hex'][1]).rstrip(b'\r\n').hex()
                elif name == 'raw-extra-tail':
                    capture['raw_frames_hex'][1] = (bytes.fromhex(capture['raw_frames_hex'][1]) + b'\r\n').hex()
                elif name == 'wire-lowercase':
                    for key in ('raw_frames_hex', 'parser_frames_hex'):
                        raw = bytes.fromhex(capture[key][1])
                        self.assertNotEqual(raw, raw.lower())
                        capture[key][1] = raw.lower().hex()
                elif name == 'parser-checksum':
                    raw = bytearray.fromhex(capture['parser_frames_hex'][1]); raw[-3] ^= 1
                    capture['parser_frames_hex'][1] = raw.hex()
                elif name == 'checksum-on-omission':
                    raw = bytes.fromhex(capture['raw_frames_hex'][1])
                    body = raw.rstrip(b'\r\n')
                    self.assertEqual(sum(bytes.fromhex(body.decode())) & 255, 0)
                    # Keep the valid parser copy; checksum-on Rust could never
                    # publish this now checksum-free original as a valid frame.
                    capture['raw_frames_hex'][1] = (body[:-2] + raw[len(body):]).hex()
                elif name == 'missing-block':
                    capture['raw_frames_hex'].pop(); capture['parser_frames_hex'].pop()
                elif name == 'block-order':
                    for key in ('raw_frames_hex', 'parser_frames_hex'):
                        capture[key][1], capture[key][2] = capture[key][2], capture[key][1]
                elif name == 'probe-order':
                    evidence['after']['serial_observations'].reverse()
                elif name == 'unknown-field':
                    capture['unrecognized'] = True
                elif name == 'before-after':
                    evidence['before'], evidence['after'] = evidence['after'], evidence['before']
                elif name in ('before-local-duplicate', 'preintent-local-duplicate', 'after-local-duplicate'):
                    capture = (evidence['local_identity'] if name == 'preintent-local-duplicate' else
                               evidence['before' if name == 'before-local-duplicate' else 'after']['local_identity'])
                    for key in ('raw_frames_hex', 'parser_frames_hex'):
                        capture[key].append(capture[key][1])
                elif name == 'remote-reply-overflow':
                    capture = evidence['before']['serial_observations'][0]['capture']
                    for key in ('raw_frames_hex', 'parser_frames_hex'):
                        capture[key].extend([capture[key][1]] * 7)
                journal.write_text(json.dumps(value)); self.assert_refused(project, journal, original)

    def test_valid_checksums_cannot_hide_wrong_wire_identity_route_or_options(self):
        project, journal, original = self.fixture(6)
        pristine = json.loads(journal.read_text())
        for name in ('reply-source', 'reply-route', 'reply-unit', 'serial', 'options'):
            with self.subTest(mutation=name):
                value = deepcopy(pristine); proof = value['reconciliation_evidence']
                if name == 'options': capture = proof['local_options']
                else: capture = proof['before']['serial_observations'][0]['capture']
                raw = bytes.fromhex(capture['raw_frames_hex'][1])
                body = bytearray.fromhex(raw.rstrip(b'\r\n').decode())
                self.assertEqual(sum(body) & 255, 0)  # checksum-on fixture
                if name == 'reply-source': body[1] = 252
                elif name == 'reply-route': body[4] = 251
                elif name == 'reply-unit': body[9] = 17  # six-hop Reply Network unit
                elif name == 'serial':
                    source_serial = packed(C); offset = bytes(body).index(source_serial)
                    body[offset:offset+4] = packed(A)
                else: body[-2] = 4  # direct parameter 66 option byte
                body[-1] = -sum(body[:-1]) & 255
                wire_text = body.hex().upper().encode()
                capture['raw_frames_hex'][1] = (wire_text + raw[len(raw.rstrip(b'\r\n')):]).hex()
                capture['parser_frames_hex'][1] = (wire_text + b'\r\n').hex()
                journal.write_text(json.dumps(value)); self.assert_refused(project, journal, original)

    def test_target_scope_and_project_pin_refused_before_writes(self):
        project, journal, original = self.fixture()
        with self.assertRaises(ReconcileError):
            reconcile(journal, ProjectFileDatabase(project), apply=True, network=254)
        self.assertFalse(default_record_path(journal).exists())
        project.write_bytes(original + b' ')
        self.assert_refused(project, journal, original + b' ')

    def test_restart_after_save_preserves_backup_and_does_not_repeat_write(self):
        project, journal, original = self.fixture(6)
        advance = ReconcileRecord.advance
        def interrupt(record, phase, **fields):
            if phase == 'db_done': raise KeyboardInterrupt
            return advance(record, phase, **fields)
        with patch.object(ReconcileRecord, 'advance', interrupt), self.assertRaises(KeyboardInterrupt):
            reconcile(journal, ProjectFileDatabase(project), apply=True)
        record = json.loads(default_record_path(journal).read_text())
        self.assertEqual(record['phase'], 'db_pending')
        self.assertEqual(Path(record['backup']).read_bytes(), original)
        saved = project.read_bytes()
        with patch.object(ProjectDocument, 'save', side_effect=AssertionError('restart saved')):
            self.assertEqual(reconcile(journal, ProjectFileDatabase(project), apply=True)['outcome'],
                             'resumed_complete')
        self.assertEqual(project.read_bytes(), saved)
        self.assert_preserved(project, original, 6)

    def test_attempt_marker_missing_or_changed_refused(self):
        project, journal, original = self.fixture()
        value = json.loads(journal.read_text())
        marker = Path(value.get('attempt_identity', value.get('attempt_marker')))
        raw = marker.read_bytes(); marker.unlink()
        self.assert_refused(project, journal, original)
        record = json.loads(raw); record['plan']['serial'] = B
        marker.write_text(json.dumps(record))
        self.assert_refused(project, journal, original)


    def test_actual_cli_symlink_parent_binds_canonical_marker_and_refuses_alias_abuse(self):
        real = self.directory / 'real'; real.mkdir()
        alias = self.directory / 'operator-path'; alias.symlink_to(real, target_is_directory=True)
        project = real / 'project.xml'; project.write_bytes(project_bytes(1))
        route, digest = route_from_project(project, source_network=254, target_network=253)
        with peer(before_responses(route)) as (endpoint, _):
            plan = manager(endpoint, command_checksum=False).plan(A, 6, route=route, project_sha256=digest)
        journal = alias / 'journal.json'
        with rust_peer(route, False) as (endpoint, state):
            value = plan.as_dict(); value['endpoint'] = dict(host=endpoint[0], port=endpoint[1])
            value['before']['endpoint'] = dict(value['endpoint'])
            value = SelectedSerialPlan.from_dict(value).as_dict()
            plan_file = real / 'plan.json'; plan_file.write_text(json.dumps(value))
            result = subprocess.run([str(Path(BIN).resolve()), 'serial-apply', '--pci',
                f'{endpoint[0]}:{endpoint[1]}', '--plan', str(plan_file), '--project', str(project),
                '--source-network', '254', '--target-network', '253', '--journal', str(journal),
                '--timeout', '60'], capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(state['moves'], 1); self.assertEqual(state['errors'], [])
        artifact = json.loads(journal.read_bytes())
        marker = Path(artifact['attempt_identity']); marker_raw = marker.read_bytes()
        record = json.loads(marker_raw)
        self.assertEqual(artifact['journal'], str(journal.absolute()))
        self.assertEqual(record['journal'], str(real.resolve() / journal.name))
        self.assertTrue(verify_journal(journal).receipt_matches_request)
        original = project.read_bytes()
        self.assertEqual(reconcile(journal, ProjectFileDatabase(project))['outcome'], 'planned')
        for field, changed in (('journal', str(real.resolve() / 'unrelated.json')),
                               ('scope', 'operator_selected_attempt_store')):
            forged = dict(record); forged[field] = changed
            marker.write_text(json.dumps(forged))
            self.assert_refused(project, journal, original)
            marker.write_bytes(marker_raw)
        # Even an exact copied journal cannot be relocated by changing the alias target.
        rebound = self.directory / 'rebound'; rebound.mkdir()
        shutil.copyfile(journal, rebound / journal.name)
        alias.unlink(); alias.symlink_to(rebound, target_is_directory=True)
        self.assert_refused(project, journal, original)
        alias.unlink(); alias.symlink_to(real, target_is_directory=True)
        # Do not resolve the journal filename and accidentally accept a symlink.
        held = real / 'held.json'; journal.rename(held); journal.symlink_to(held)
        self.assert_refused(project, journal, original)
        journal.unlink(); held.rename(journal)
        self.assertTrue(verify_journal(journal).receipt_matches_request)


if __name__ == '__main__': unittest.main()
