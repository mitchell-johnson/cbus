"""Routed selected-serial plan/apply/verify over scripted one- and six-bridge peers.

Every far-network frame is built here from literal header, Reply Network and
CAL bytes, independently of the implementation's encoders and parsers. Each
observation owns one connection, so a peer-side close models a reconnect.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import select
import socket
import tempfile
import threading
import time
import unittest

from cbus_toolkit import pci_selected_serial as implementation
from cbus_toolkit.pci_selected_serial import (SelectedSerialCoordinator, SelectedSerialPlan,
                                              SelectedSerialPlanError, SelectedSerialUncertain,
                                              route_from_project)
from tests.test_commissioning_route import line
from tests.test_pci_selected_serial import LOCAL, LOCAL_REQUEST, OPTIONS, OPTIONS_REQUEST, SETTINGS
from tests.test_pci_serials import BARE_PCI


A, B, C = '101136.1558', '101136.1559', '101136.1560'
ONE = [253]
SIX = [253, 252, 251, 250, 249, 248]


def packed(serial):
    first, second = map(int, serial.split('.'))
    return ((first << 12) | second).to_bytes(4, 'big')


def checksummed(payload):
    return bytes(payload) + bytes([-sum(payload) & 255])


def reply_network(route, unit, cal, *, local=16, header=0x86):
    """One Reply Network line: nearest bridge, PCI, count, later bridges, unit, CAL."""
    payload = [header, route[0], local, len(route), *route[1:], unit, *cal]
    return checksummed(payload).hex().upper().encode() + b'\r\n'


def mmi_block(route, start, count, states, **options):
    values = [states.get(address, 0) for address in range(start, start + count)]
    report = bytes(sum(value << (2 * index) for index, value in enumerate(values[offset:offset + 4]))
                   for offset in range(0, count, 4))
    return reply_network(route, 1, [0xE0 | (len(report) + 3), 0x00, 0xFF, start, *report], **options)


def mmi(route, states, **options):
    return b''.join(mmi_block(route, start, count, states, **options)
                    for start, count in ((0, 88), (88, 88), (176, 80)))


def identify4(route, unit, serial, **options):
    data = b'\x38\xff\xff\xff\xff' + packed(serial) + b'\xa2\x00\x05'
    return reply_network(route, unit, [0x8D, 0x04, *data], **options)


def receipt(route, destination, serial, **options):
    return reply_network(route, destination, [0x87, 0x00, *packed(serial), 0, 0], **options)


def routed_identify_request(route, unit):
    payload = [0x46, route[0], 9 * len(route), *route[1:], unit, 0x21, 0x04]
    return b'\\' + bytes(payload).hex().upper().encode() + b'g\r'


def routed_mmi_request(route):
    payload = [0x03, route[0], 9 * len(route), *route[1:], 0xFF, 0xFA, 0xFF, 0x00]
    return b'\\' + bytes(payload).hex().upper().encode() + b'g\r'


def routed_co(route, serial, destination):
    body = b'\x00' + packed(serial) + bytes([destination])
    payload = bytes([0x03, route[0], 9 * len(route), *route[1:], 0xFF, 0x0F]) + body + bytes([-sum(body) & 255])
    return b'\\' + payload.hex().upper().encode() + b'g\r'


BEFORE = {16: 1, 255: 2}  # Unit 16 on the far network is not the local PCI.
AFTER = {6: 2, 16: 1, 255: 2}


def far_inventory(route, states, identities):
    """Routed MMI, one IDENTIFY4 window per present address, final MMI."""
    responses = [b'g.' + mmi(route, states)]
    for address in sorted(states):
        responses.append(b'g.' + b''.join(identify4(route, address, serial) for serial in identities[address]))
    return responses + [b'g.' + mmi(route, states)]


def far_requests(route, states):
    return ([routed_mmi_request(route)] + [routed_identify_request(route, address) for address in sorted(states)]
            + [routed_mmi_request(route)])


def before_responses(route):
    return far_inventory(route, BEFORE, {16: [C], 255: [A, B]}) + [b'g.' + BARE_PCI, OPTIONS]


def after_responses(route, moved=True):
    if moved: return far_inventory(route, AFTER, {6: [A], 16: [C], 255: [B]})
    return far_inventory(route, BEFORE, {16: [C], 255: [A, B]})


def before_requests(route):
    return far_requests(route, BEFORE) + [LOCAL_REQUEST, OPTIONS_REQUEST]


@contextmanager
def peer(responses, port=0):
    """One connection per response. ('close', bytes) sends then closes first.

    ``port`` reopens a previous peer's endpoint, so a plan (whose canonical
    identity includes its endpoint) is reused unchanged across reconnects.
    """
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', port)); listener.listen(1); listener.settimeout(3)
    state = {'requests': [], 'extra': [], 'errors': []}

    def serve():
        try:
            for response in responses:
                with listener.accept()[0] as connection:
                    connection.settimeout(3)
                    request = b''
                    while not request.endswith(b'\r'):
                        chunk = connection.recv(512)
                        if not chunk: raise AssertionError('Disconnected before request')
                        request += chunk
                    state['requests'].append(request)
                    if isinstance(response, tuple) and response[0] == 'close':
                        connection.sendall(response[1])
                        connection.shutdown(socket.SHUT_RDWR)
                        continue
                    connection.sendall(response)
                    extra = b''
                    while chunk := connection.recv(512): extra += chunk
                    state['extra'].append(extra)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            state['errors'].append(repr(error))

    thread = threading.Thread(target=serve, daemon=True); thread.start()
    try: yield listener.getsockname(), state
    finally:
        thread.join(5)
        pending = select.select([listener], [], [], 0)[0]
        listener.close()
        if thread.is_alive(): raise AssertionError('Peer conversation did not complete')
        if pending: raise AssertionError('Unexpected additional connection (replay?)')
        if state['errors']: raise AssertionError(state['errors'])


def manager(endpoint, **options):
    return SelectedSerialCoordinator(*endpoint, **(SETTINGS | options))


class RoutedSelectedSerialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def project(self, depth, name='project.xml'):
        raw, _ = line(depth)
        path = self.dir / name; path.write_bytes(raw)
        return path, dict(project=path, source_network=254, target_network=254 - depth)

    def plan(self, route, depth):
        path, binding = self.project(depth)
        derived, digest = route_from_project(path, source_network=254, target_network=254 - depth)
        self.assertEqual(derived, route)
        with peer(before_responses(route)) as (endpoint, state):
            subject = manager(endpoint)
            plan = subject.plan(A, 6, route=derived, project_sha256=digest)
        self.assertEqual(state['requests'], before_requests(route))
        return endpoint, plan, binding

    def test_one_and_six_bridge_plan_apply_verify_and_journal_recovery(self):
        for route, depth in ((ONE, 1), (SIX, 6)):
            with self.subTest(bridges=len(route)):
                _, plan, binding = self.plan(route, depth)
                document = plan.as_dict()
                self.assertEqual(document['route'], route)
                self.assertEqual(document['before']['route'], route)
                self.assertEqual(document['request_hex'], routed_co(route, A, 6).hex())
                # The destination shares no identity with the local PCI network.
                self.assertEqual(document['expected_after']['identities'],
                                 [{'address': 6, 'serials': [A]}, {'address': 16, 'serials': [C]},
                                  {'address': 255, 'serials': [B]}])
                saved = SelectedSerialPlan.from_dict(json.loads(json.dumps(document)))
                responses = before_responses(route) + [b'g.' + receipt(route, 6, A)] + after_responses(route)
                journal = self.dir / f'journal-{depth}.json'
                with peer(responses) as (endpoint, state):
                    # The plan's recorded endpoint is rebound to this fresh peer.
                    rebound = dict(document, endpoint={'host': endpoint[0], 'port': endpoint[1]})
                    rebound['before'] = dict(document['before'], endpoint=rebound['endpoint'])
                    saved = SelectedSerialPlan.from_dict(rebound)
                    result = manager(endpoint).apply(saved, recovery_path=journal, **binding)
                self.assertEqual(state['requests'], before_requests(route) + [routed_co(route, A, 6)]
                                 + far_requests(route, AFTER))
                evidence = result.as_dict()
                self.assertEqual(result.outcome, 'observed_expected_change')
                self.assertTrue(evidence['receipt_matches_request'])
                self.assertEqual(evidence['route_binding']['route'], route)
                self.assertTrue(evidence['route_binding']['topology_fresh_at_handoff'])
                self.assertFalse(evidence['route_binding']['physical_bridge_acceptance_verified'])
                self.assertEqual(evidence['exchange']['receipt']['route'], route)
                recovered = SelectedSerialCoordinator.load_recovery(journal)
                with peer(after_responses(route)) as (endpoint2, state2):
                    rebound2 = dict(recovered.as_dict(), endpoint={'host': endpoint2[0], 'port': endpoint2[1]})
                    rebound2['before'] = dict(rebound2['before'], endpoint=rebound2['endpoint'])
                    observed = manager(endpoint2).verify(SelectedSerialPlan.from_dict(rebound2), **binding)
                self.assertEqual(observed.outcome, 'observed_expected_change')
                self.assertEqual(state2['requests'], far_requests(route, AFTER))
                self.assertFalse(observed.as_dict()['send_attempted'])

    def rebound(self, plan, endpoint):
        document = plan.as_dict()
        document['endpoint'] = {'host': endpoint[0], 'port': endpoint[1]}
        document['before'] = dict(document['before'], endpoint=document['endpoint'])
        return SelectedSerialPlan.from_dict(document)

    def run_apply(self, route, depth, exchange, after, *, binding=None, name='journal.json'):
        _, plan, default = self.plan(route, depth)
        journal = self.dir / name
        with peer(before_responses(route) + [exchange] + after) as (endpoint, state):
            subject = manager(endpoint)
            plan = self.rebound(plan, endpoint)
            try:
                result = subject.apply(plan, recovery_path=journal, **(binding or default))
                error = None
            except SelectedSerialUncertain as caught:
                result, error = None, caught
        return plan, default, journal, state, result, error

    def test_binding_refusals_happen_before_any_io_or_file(self):
        _, plan, binding = self.plan(ONE, 1)
        other, _ = self.project(2, 'other.xml')
        changed = self.dir / 'changed.xml'; changed.write_bytes(binding['project'].read_bytes() + b' ')
        cases = (
            ({}, 'route_binding'),
            (dict(binding, project=changed), 'route_binding'),
            (dict(project=other, source_network=254, target_network=252), 'route_binding'),
            (dict(binding, target_network=252), 'route_binding'),  # absent from this topology
        )
        with peer([]) as (endpoint, state):
            subject = manager(endpoint)
            rebound = self.rebound(plan, endpoint)
            for options, reason in cases:
                for action in (lambda: subject.apply(rebound, recovery_path=self.dir / 'j.json', **options),
                               lambda: subject.verify(rebound, **options)):
                    with self.subTest(options=options), self.assertRaises(SelectedSerialPlanError) as caught:
                        action()
                    self.assertEqual(caught.exception.reason, reason)
            self.assertFalse(subject._apply_used)
        self.assertEqual(state['requests'], [])
        self.assertFalse((self.dir / 'j.json').exists())

    def test_wrong_route_is_refused_before_io(self):
        # A plan whose bridges differ from the bound project's topology.
        path, binding = self.project(2)
        _, digest = route_from_project(path, source_network=254, target_network=252)
        with peer(before_responses([253, 251])) as (endpoint, _):
            plan = manager(endpoint).plan(A, 6, route=[253, 251], project_sha256=digest)
        with peer([]) as (endpoint, state):
            subject = manager(endpoint)
            for action in (lambda: subject.apply(self.rebound(plan, endpoint), recovery_path=self.dir / 'w.json',
                                                 **binding),
                           lambda: subject.verify(self.rebound(plan, endpoint), **binding)):
                with self.assertRaises(SelectedSerialPlanError) as caught: action()
                self.assertEqual(caught.exception.reason, 'wrong_route')
        self.assertEqual(state['requests'], [])
        self.assertEqual(sorted(item.name for item in self.dir.iterdir()), ['project.xml'])

    def test_direct_plan_refuses_a_route_binding(self):
        from tests.test_pci_full_inventory import successful_responses
        with peer(successful_responses() + [b'g.' + BARE_PCI, OPTIONS]) as (endpoint, _):
            plan = manager(endpoint).plan(A, 6)
        path, binding = self.project(1)
        with peer([]) as (endpoint, state):
            with self.assertRaises(SelectedSerialPlanError) as caught:
                manager(endpoint).verify(self.rebound(plan, endpoint), **binding)
        self.assertEqual(caught.exception.reason, 'route_binding')
        self.assertEqual(state['requests'], [])

    def test_stale_project_at_handoff_refuses_before_marker_or_send(self):
        _, plan, binding = self.plan(ONE, 1)
        original = implementation.SelectedSerialCoordinator._transport

        def replace_project(self, route=()):
            binding['project'].write_bytes(binding['project'].read_bytes() + b'<!-- edited -->')
            return original(self, route) if route else original(self)

        with peer(before_responses(ONE)) as (endpoint, state):
            subject = manager(endpoint)
            subject._transport = replace_project.__get__(subject)
            with self.assertRaises(Exception) as caught:
                subject.apply(self.rebound(plan, endpoint), recovery_path=self.dir / 'stale.json', **binding)
        self.assertIn('stale', str(caught.exception))
        self.assertEqual(caught.exception.selected_serial_evidence['outcome'], 'preconditions_failed')
        self.assertEqual(state['requests'], before_requests(ONE))
        self.assertEqual(sorted(item.name for item in self.dir.iterdir()), ['project.xml'])

    def test_routed_evidence_is_bound_to_its_route(self):
        _, plan, _ = self.plan(SIX, 6)
        document = plan.as_dict()
        mutations = {
            'direct_marker': lambda d: d.pop('route'),
            'other_route': lambda d: d.update(route=[253, 252, 251, 250, 249, 247]),
            'observation_route': lambda d: d['before']['initial_mmi'].update(route=ONE),
        }
        for name, mutate in mutations.items():
            with self.subTest(name):
                changed = json.loads(json.dumps(document)); mutate(changed)
                changed.pop('project_sha256') if name == 'direct_marker' else None
                with self.assertRaises(ValueError): SelectedSerialPlan.from_dict(changed)

    def test_loss_duplicate_reorder_and_wrong_route_receipts_never_replay(self):
        route = SIX
        cases = {
            # A lost receipt is not evidence; the independent inventory decides.
            'lost_receipt': (b'g.', True, 'observed_expected_change', False),
            'lost_everything': (b'', False, 'observed_unchanged', False),
            'duplicate_receipt': (b'g.' + receipt(route, 6, A) * 2, True, 'observed_expected_change', False),
            'reordered_receipt': (receipt(route, 6, A) + b'g.', True, 'observed_expected_change', False),
            'wrong_route_receipt': (b'g.' + receipt([253, 252, 251, 250, 249, 247], 6, A), True,
                                    'observed_expected_change', False),
            'direct_receipt': (b'g.86061000870018B106160000F8\r\n', False, 'observed_unchanged', False),
        }
        for name, (exchange, moved, outcome, matched) in cases.items():
            with self.subTest(name):
                _, _, journal, state, result, error = self.run_apply(
                    route, 6, exchange, after_responses(route, moved), name=name + '.json')
                self.assertIsNone(error)
                self.assertEqual(result.outcome, outcome)
                self.assertEqual(result.as_dict()['receipt_matches_request'], matched)
                self.assertEqual(state['requests'].count(routed_co(route, A, 6)), 1)
                self.assertEqual(state['requests'][-len(far_requests(route, AFTER if moved else BEFORE)):],
                                 far_requests(route, AFTER if moved else BEFORE))
                self.assertEqual(json.loads(journal.read_text())['outcome'], outcome)

    def test_reconnect_mid_receipt_is_uncertain_then_verified_read_only(self):
        route = ONE
        partial = ('close', b'g.' + receipt(route, 6, A)[:9])
        plan, binding, journal, state, result, error = self.run_apply(route, 1, partial, [])
        self.assertIsNone(result)
        self.assertEqual(error.selected_serial_evidence['outcome'], 'uncertain')
        self.assertTrue(error.selected_serial_evidence['send_attempted'])
        self.assertEqual(state['requests'], before_requests(route) + [routed_co(route, A, 6)])
        recorded = json.loads(journal.read_text())
        self.assertEqual((recorded['state'], recorded['outcome']), ('receipt_collected', 'uncertain'))
        # Recovery reconnects for a read-only far-network observation only.
        recovered = SelectedSerialCoordinator.load_recovery(journal)
        self.assertEqual(recovered.as_dict(), plan.as_dict())
        port = plan.as_dict()['endpoint']['port']
        with peer(after_responses(route), port) as (endpoint, state2):
            observed = manager(endpoint).verify(recovered, **binding)
        self.assertEqual(observed.outcome, 'observed_expected_change')
        self.assertNotIn(routed_co(route, A, 6), state2['requests'])
        # The attempt marker refuses a second apply of that plan before any I/O.
        with peer([], port) as (endpoint, state3), self.assertRaises(SelectedSerialUncertain):
            manager(endpoint).apply(recovered, recovery_path=self.dir / 'again.json', **binding)
        self.assertEqual(state3['requests'], [])

    def test_after_inventory_loss_duplicate_reorder_and_foreign_route_are_uncertain(self):
        route = ONE
        full = after_responses(route)
        blocks = mmi(route, AFTER).split(b'\r\n')[:-1]
        variants = {
            'lost_block': [b'g.' + blocks[0] + b'\r\n' + blocks[2] + b'\r\n'] + full[1:],
            'reordered_blocks': [b'g.' + blocks[1] + b'\r\n' + blocks[0] + b'\r\n' + blocks[2] + b'\r\n'] + full[1:],
            'duplicate_block': [b'g.' + blocks[0] + b'\r\n' + blocks[0] + b'\r\n'] + full[1:],
            'foreign_route_serial': full[:1] + [b'g.' + identify4(route, 6, A) + identify4([252], 6, A)] + full[2:],
            'lost_serial_reply': full[:1] + [b'g.'] + full[2:],
        }
        for name, after in variants.items():
            with self.subTest(name):
                # A failed child stops the inventory; remaining scripted
                # windows are simply never requested.
                stop = {'lost_block': 1, 'reordered_blocks': 1, 'duplicate_block': 1}.get(name)
                script = after[:stop] if stop else after
                _, _, _, state, result, error = self.run_apply(route, 1, b'g.' + receipt(route, 6, A), script,
                                                                name=name + '.json')
                self.assertIsNone(error)
                self.assertEqual(result.outcome, 'uncertain')
                self.assertTrue(result.as_dict()['receipt_matches_request'])
                self.assertEqual(state['requests'].count(routed_co(route, A, 6)), 1)


class RoutedSelectedSerialCLITests(unittest.TestCase):
    def invoke(self, args, status):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from cbus_toolkit import cli
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): actual = cli.main(list(map(str, args)))
        self.assertEqual(actual, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def test_cli_plans_applies_and_verifies_a_two_bridge_route_bound_to_its_project(self):
        from tests.test_cli_selected_serial import FAST
        route = [253, 252]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); project = tmp / 'house.xml'; project.write_bytes(line(2)[0])
            binding = ['--project', project, '--source-network', '254', '--target-network', '252']
            plan_file, journal = tmp / 'plan.json', tmp / 'journal.json'
            with peer(before_responses(route)) as (endpoint, state):
                exported = self.invoke(['serial-address', 'plan', A, '6', '--host', endpoint[0], '--port', endpoint[1],
                                        '--local-unit', '16', '--expected-local-serial', LOCAL, '--output', plan_file,
                                        *FAST, '--quiet-period', '.2', *binding], 0)
            self.assertEqual(exported['plan']['route'], route)
            self.assertEqual(state['requests'], before_requests(route))
            port = endpoint[1]
            # Missing binding refuses before any connection or journal.
            with peer([], port):
                refused = self.invoke(['serial-address', 'apply', plan_file, '--recovery', journal], 1)
            self.assertEqual(refused['type'], 'SelectedSerialPlanError'); self.assertIn('project', refused['error'])
            self.assertFalse(journal.exists())
            with peer(before_responses(route) + [b'g.' + receipt(route, 6, A)] + after_responses(route), port) as (_, state):
                result = self.invoke(['serial-address', 'apply', plan_file, '--recovery', journal, *binding], 0)
            self.assertEqual(result['outcome'], 'observed_expected_change')
            self.assertEqual(state['requests'].count(routed_co(route, A, 6)), 1)
            with peer(after_responses(route), port) as (_, state):
                verified = self.invoke(['serial-address', 'verify', '--recovery', journal, *binding], 0)
            self.assertEqual(verified['outcome'], 'observed_expected_change')
            self.assertEqual(state['requests'], far_requests(route, AFTER))


if __name__ == '__main__':
    unittest.main()
