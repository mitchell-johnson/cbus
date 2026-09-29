"""Original C-Gate routed WRITE ACK matcher vectors compared with Python and Rust decisions."""
import collections
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

from cbus_toolkit.pci import WriteCAL
from cbus_toolkit.pci_routed_recall import RoutedReplyPath
from cbus_toolkit.pci_routed_write import RoutedWriteClient
from cbus_toolkit.pci_routing import RoutedCALCommand
from research.pci_routed_write_original import cases, native_success, plan_tsv, run_original

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/pci-routed-write-original-vectors.json'
DECODE_VECTORS = ROOT.parent / 'rust/testdata/vectors/decode_from_pci.jsonl'

# Relation of the Python one-shot client to the original matcher per family.
# "agree": same success/refusal. "python-stricter": original accepts, Python refuses.
# "python-wider": Python accepts what the original refuses; each is a declared limit.
RELATIONS = {
    'nominal': {'agree'},
    'wrong-parameter': {'agree'},
    'wrong-tag': {'agree'},
    'wrong-unit': {'agree'},
    'wrong-route': {'agree'},
    'route-count': {'agree'},
    'negative': {'agree'},
    'negative-confirmation': {'agree'},
    'confirmation-tag': {'agree'},
    # Original accepts a destination it never compares, an unchecked checksum, a
    # trailing CAL, any 0bxxxxx110 header or a bare ACK when no route is involved.
    'destination': {'python-stricter'},
    'checksum': {'python-stricter'},
    'trailing-cal': {'python-stricter'},
    'header': {'python-stricter', 'agree'},
    'bare-ack': {'python-stricter', 'agree'},
    # Original tolerates duplicates, unconfirmed n=false sends and '#' with t=true.
    'duplicate': {'python-stricter'},
    'confirmation-required': {'python-stricter'},
    'hash-confirmation': {'python-stricter'},
    # Original n=true drops an ACK arriving before the PCI confirmation; Python
    # accepts either order but refuses a later duplicate.
    'ack-before-confirmation': {'python-wider', 'python-stricter'},
    # Original compares uppercase text; Python decodes hex case-insensitively.
    'lowercase-hex': {'python-wider'},
    # Original resolves the reply's cached bridge objects to a logical network;
    # Python correlates the declared byte path only.
    'cached-network-identity': {'python-wider'},
}
PYTHON_WIDER = {'ack-before-confirmation': 7, 'lowercase-hex': 3, 'cached-network-identity': 6}


class _ScriptedSocket:
    """Deterministic one-connection peer: one scripted chunk, then EOF."""

    def __init__(self, script):
        self.script, self.sent, self.closed = script, [], False

    def __call__(self, *args):
        return self

    def settimeout(self, value):
        pass

    def connect(self, endpoint):
        pass

    def sendall(self, data):
        self.sent.append(bytes(data))

    def recv(self, size):
        chunk, self.script = self.script[:size], self.script[size:]
        return chunk

    def close(self):
        self.closed = True


def script(plan):
    parts = []
    for op in plan['operations']:
        if op[0] == 'C':
            parts.append(op[1:].encode('ascii'))
        else:
            parts.append(plan['raws'][int(op[1])].encode('ascii') + b'\r')
    return b''.join(parts)


def python_decision(plan):
    expected = plan['python_expected']
    command = RoutedCALCommand(plan['unit'], WriteCAL(plan['parameter'], bytes([plan['key'], *plan['data']])),
                               bridges=tuple(plan['outgoing']), addressing='direct')
    peer = _ScriptedSocket(script(plan))
    client = RoutedWriteClient('127.0.0.1', 10001, timeout=5.0)
    with patch('cbus_toolkit.pci_routed_write.socket.socket', peer):
        try:
            result = client.exchange(command, expected=RoutedReplyPath(
                expected['outer_source_byte'], expected['destination_byte'], tuple(expected['route_entries'])),
                expected_ack_tag=plan['key'])
            outcome = {'success': True, 'error': None}
        except Exception as error:
            result, outcome = None, {'success': False, 'error': type(error).__name__}
    outcome.update(sent=peer.sent, closed=peer.closed, evidence=client.last_evidence, result=result)
    return outcome


class RoutedWriteOriginalVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())
        cls.decisions = {c['input']['id']: python_decision(c['input']) for c in cls.fixture['cases']}

    def test_fixture_binds_probe_source_generator_and_tsv(self):
        fixture = self.fixture
        self.assertEqual(fixture['format'], 'pci-routed-write-original-vectors-v1')
        source = hashlib.sha256((ROOT / 'research/NativeRoutedWriteProbe.java').read_bytes()).hexdigest()
        self.assertEqual(source, fixture['source_sha256'])
        plans = [row['input'] for row in fixture['cases']]
        self.assertEqual(plans, cases())
        self.assertEqual(hashlib.sha256(plan_tsv(plans)).hexdigest(), fixture['tsv_sha256'])
        self.assertEqual(len(plans), 150)
        self.assertEqual(len({p['id'] for p in plans}), 150)
        self.assertFalse(fixture['runtime']['sender_receiver_dispatch_invoked'])
        self.assertEqual(set(RELATIONS), {p['family'] for p in plans})
        for plan in plans:
            self.assertLessEqual(len(plan['outgoing']), 6)
            self.assertEqual(plan['bridges'], list(reversed(plan['outgoing'])))

    def test_every_bridge_depth_has_nominal_and_wrong_route_unit_parameter_tag(self):
        by_family = collections.defaultdict(set)
        for row in self.fixture['cases']:
            by_family[row['input']['family']].add(row['input']['depth'])
        for family in ('nominal', 'wrong-parameter', 'wrong-tag', 'wrong-unit'):
            self.assertEqual(by_family[family], set(range(7)), family)
        self.assertEqual(by_family['wrong-route'], set(range(1, 7)))
        self.assertEqual(by_family['cached-network-identity'], set(range(1, 7)))

    def test_original_outbound_route_prepend_equals_python_wire(self):
        for row in self.fixture['cases']:
            plan, native = row['input'], row['native']
            self.assertEqual(native['prepend_accepted'], [True] * len(plan['outgoing']), plan['id'])
            sent = self.decisions[plan['id']]['sent']
            self.assertEqual(sent, [(native['command'] + plan['tag'] + '\r').encode('ascii')], plan['id'])

    def test_python_client_relation_to_original_matcher_per_family(self):
        wider = collections.Counter()
        for row in self.fixture['cases']:
            plan = row['input']
            original = native_success(row['native'], plan)
            python = self.decisions[plan['id']]['success']
            relation = ('agree' if original == python else 'python-stricter' if original else 'python-wider')
            self.assertIn(relation, RELATIONS[plan['family']], plan['id'])
            if relation == 'python-wider':
                wider[plan['family']] += 1
        self.assertEqual(dict(wider), PYTHON_WIDER)

    def test_original_ack_tag_is_first_write_byte_and_negative_is_distinct(self):
        for row in self.fixture['cases']:
            plan, native = row['input'], row['native']
            if plan['family'] == 'nominal':
                self.assertTrue(native_success(native, plan), plan['id'])
                self.assertEqual((native['acknowledgements'], native['negative_acknowledgements']), (1, 0))
                self.assertTrue(self.decisions[plan['id']]['success'], plan['id'])
            if plan['family'] == 'wrong-tag':
                self.assertFalse(native['received'], plan['id'])
            if plan['family'] == 'negative':
                self.assertTrue(native['received'] and native['negative'], plan['id'])
                self.assertEqual(native['negative_acknowledgements'], 1)

    def test_python_refusal_after_send_is_uncertain_and_never_replayed(self):
        for row in self.fixture['cases']:
            plan = row['input']
            decision = self.decisions[plan['id']]
            self.assertEqual(len(decision['sent']), 1, plan['id'])
            self.assertTrue(decision['closed'], plan['id'])
            evidence = decision['evidence']
            self.assertFalse(evidence['resubmitted'])
            self.assertFalse(evidence['original_cached_object_correlation_verified'])
            if decision['success']:
                self.assertTrue(evidence['complete'])
                self.assertFalse(decision['result'].as_dict()['parameter_commit_verified'])
            else:
                self.assertTrue(evidence['write_outcome_uncertain'], plan['id'])

    def test_rust_decodes_every_original_accepted_nominal_route_depth(self):
        rows = {}
        for line in DECODE_VECTORS.read_text().splitlines():
            if '"fp-native-routed-write-ack-d' in line:
                row = json.loads(line)
                rows[row['id']] = row
        for row in self.fixture['cases']:
            plan = row['input']
            if not plan['id'].startswith('nominal-d'):
                continue
            vector = rows.pop(f"fp-native-routed-write-ack-d{plan['depth']}")
            self.assertEqual(bytes.fromhex(vector['wire_hex']), plan['raws'][0].encode('ascii') + b'\r\n')
            packet, expected = vector['expect_packet'], plan['python_expected']
            self.assertEqual(packet['cals'], [{'cal': 'ack', 'data_hex': f"{plan['key']:02x}",
                                               'parameter': plan['parameter']}])
            if plan['depth']:
                self.assertEqual([packet['source_address'], *packet['hops'], packet['unit_address']],
                                 [expected['outer_source_byte'], *expected['route_entries']])
            else:
                self.assertEqual((packet['source_address'], packet['unit_address']), (plan['unit'], 0x10))
        self.assertEqual(rows, {})


@unittest.skipUnless(sys.platform == 'darwin' and all(os.environ.get(name) for name in
                     ('CBUS_CGATE_JAVA', 'CBUS_CGATE_JAVAC', 'CBUS_LOCAL_CGATE_VENDOR')),
                     'Explicit owned macOS JDK/compiler and original C-Gate files required')
class OriginalRoutedWriteTests(unittest.TestCase):
    def test_fresh_original_matrix_matches_committed_semantics(self):
        parent = Path(os.environ.get('CBUS_PCI_ROUTED_WRITE_REPORT_DIR',
                                     str(ROOT / 'research/runtime/pci-routed-write-original'))).resolve()
        parent.mkdir(parents=True, exist_ok=True)
        report = run_original(ROOT, java=os.environ['CBUS_CGATE_JAVA'], javac=os.environ['CBUS_CGATE_JAVAC'],
                              jar=Path(os.environ['CBUS_LOCAL_CGATE_VENDOR']) / 'cgate.jar',
                              destination=parent / uuid.uuid4().hex)
        self.assertTrue(report['passed'])
        self.assertEqual(report['cases'], 150)
        self.assertEqual(report['comparisons'], 150)
        self.assertTrue(report['inputs_unchanged'])
        self.assertTrue(report['compiled_unchanged'])
        self.assertEqual([r['exit_code'] for r in report['processes']], [0, 0])
        self.assertTrue(all(not r['resubmitted'] for r in report['processes']))


if __name__ == '__main__':
    unittest.main()
