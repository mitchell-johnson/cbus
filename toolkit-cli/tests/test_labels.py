"""Label grammar and SAL vectors transcribed from the native oracle capture."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

from cbus_toolkit.labels import LabelError, NativeLabels, encode_label, encode_unicode_label, encode_dynamic_icon


class Client:
    def __init__(self):
        self.commands = []
        self.failure = None

    def command(self, command):
        self.commands.append(command)
        if self.failure:
            raise self.failure
        return 'accepted'


class LabelTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.labels = NativeLabels(self.client)
        self.app = '//TEST/254/56'

    def test_native_ascii_icon_and_unicode_vectors(self):
        self.assertEqual(encode_label(1, 0, 0, b'Lounge', variant=2).hex(), 'a90140004c6f756e6765')
        self.assertEqual(encode_label(1, 0, 2, bytes.fromhex('010102'), variant=3).hex(), 'a6016200010102')
        self.assertEqual(encode_unicode_label(1, 0, 'Māori'.encode(), variant=1, sequence=14), (bytes.fromhex('ca01ee01004dc4816f7269'),))

    def test_native_dynamic_vector_and_multichunk_length(self):
        packets = encode_dynamic_icon(1, 0, 1, 8, 1, b'\x80')
        self.assertEqual(tuple(packet.hex() for packet in packets), ('a401080020', 'a80104000001080100', 'a401080021', 'a3010480', 'a401080022'))
        packets = encode_dynamic_icon(255, 7, 65535, 8, 7, b'1234567', action_selector=8, variant=3, vertical_offset=255)
        self.assertEqual(len(packets), 7)
        self.assertEqual(packets[3], bytes.fromhex('a9ff6508') + b'123456')
        self.assertEqual(packets[5], bytes.fromhex('a4ff6508') + b'7')

    def test_unicode_fragment_boundaries_and_action_selector(self):
        packets = encode_unicode_label(2, 0, '123456789012ā!'.encode(), sequence=3)
        self.assertEqual(packets, (bytes.fromhex('d102320000313233343536373839303132c4'), bytes.fromhex('c6024a00008121')))
        self.assertEqual(encode_unicode_label(7, 2, b'', action_selector=9, variant=3), (bytes.fromhex('c5070f830902'),))
        packets = encode_unicode_label(1, 0, b'x' * 234, sequence=15)
        self.assertEqual(len(packets), 18)
        self.assertEqual(len({packet[2] for packet in packets}), 18)
        for data, action in ((b'x'*235, None), (b'x'*217, 1)):
            with self.assertRaises(LabelError):
                encode_unicode_label(1, 0, data, action_selector=action)

    def test_text_preserves_quotes_spaces_and_clear_without_injection(self):
        self.assertEqual(self.labels.text(self.app, 1, ' A  "B" ', variant=2), 'accepted')
        self.assertEqual(self.client.commands[-1], 'LIGHTING LABEL //TEST/254/56 0 1 - F2 0 2041202022422220')
        self.labels.text(self.app, 1, '')
        self.assertEqual(self.client.commands[-1], 'LIGHTING LABEL //TEST/254/56 0 1 - F0 0 00')

    def test_unicode_is_explicit_utf8_raw_and_empty_clear(self):
        self.labels.unicode(self.app, 1, 'Māori', language=2, variant=1)
        self.assertEqual(self.client.commands[-1], 'LIGHTING UNICODELABEL //TEST/254/56 2 1 - F1 RAW 4dc4816f7269')
        self.labels.unicode(self.app, 1, '')
        self.assertEqual(self.client.commands[-1], 'LIGHTING UNICODELABEL //TEST/254/56 0 1 - F0 RAW')

    def test_icon_dynamic_language_raw_and_trigger_family(self):
        labels = NativeLabels(self.client, 'trigger')
        labels.icon('//TEST/254/202', 5, 65535, action_selector=6, variant=3)
        self.assertEqual(self.client.commands[-1], 'TRIGGER LABEL //TEST/254/202 0 5 6 F3 ICON 65535')
        self.labels.dynamic(self.app, 1, 258, 8, 1, b'\x80', language=7, vertical_offset=2)
        self.assertEqual(self.client.commands[-1], 'LIGHTING LABEL //TEST/254/56 7 1 - F0 DYNAMIC 258 8 1 2 80')
        self.labels.set_language(self.app, 1, 255)
        self.assertEqual(self.client.commands[-1], 'LIGHTING LABEL //TEST/254/56 255 1 - F0 SET_LANGUAGE')
        self.labels.raw(self.app, 1, 128, b'')
        self.assertEqual(self.client.commands[-1], 'LIGHTING LABEL //TEST/254/56 0 1 - F0 128')

    def test_vendor_enable_unicode_is_explicitly_unsupported(self):
        labels = NativeLabels(self.client, 'enable')
        labels.text('//TEST/254/203', 1, 'Enable')
        self.assertTrue(self.client.commands[-1].startswith('ENABLE LABEL '))
        with self.assertRaisesRegex(LabelError, 'has no UNICODELABEL'):
            labels.unicode('//TEST/254/203', 1, 'Hello')

    def test_validation_happens_before_any_command(self):
        invalid = [lambda: self.labels.text(self.app, True, 'a'), lambda: self.labels.text(self.app, 256, 'a'),
                   lambda: self.labels.text(self.app, 1, 'a'*15), lambda: self.labels.text(self.app, 1, 'ā'),
                   lambda: self.labels.text(self.app, 1, 'line\nnext'), lambda: self.labels.text(self.app+'\nNOOP', 1, 'a'),
                   lambda: self.labels.text(self.app, 1, 'a', variant=4), lambda: self.labels.text(self.app, 1, 'a', action_selector=-1),
                   lambda: self.labels.raw(self.app, 1, 256, b'x'), lambda: self.labels.raw(self.app, 1, 0, '00'),
                   lambda: self.labels.unicode_raw(self.app, 1, b'\xff'), lambda: self.labels.unicode(self.app, 1, '\ud800'),
                   lambda: self.labels.dynamic(self.app, 1, 0, 241, 1, bytes(31)), lambda: self.labels.dynamic(self.app, 1, 0, 8, 61, bytes(61)),
                   lambda: self.labels.dynamic(self.app, 1, 0, 9, 1, b'x'), lambda: self.labels.icon(self.app, 1, 65536)]
        for index, call in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                call()
        self.assertEqual(self.client.commands, [])

    def test_errors_are_not_retried(self):
        self.client.failure = RuntimeError('network closed')
        with self.assertRaisesRegex(RuntimeError, 'network closed'):
            self.labels.text(self.app, 1, 'Label')
        self.assertEqual(len(self.client.commands), 1)


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'), 'Set CBUS_CGATE_TEST_HOST for disposable native label acceptance')
class NativeLabelTests(unittest.TestCase):
    def test_native_commands_commit_exact_labels_and_persist_in_independent_peer(self):
        from cbus_toolkit.cgate import CGateClient, CGateError
        from cbus_toolkit.simulator import PCISimulator
        project = 'LBL' + uuid4().hex[:5].upper()
        network = f'//{project}/254'
        report = {'project': project, 'scope': 'Native C-Gate encoding to independent synthetic receiver and persisted state; no physical display claim', 'commands': []}
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / 'state.json'
            simulator = PCISimulator(profile='synthetic', state_path=state_path)
            with simulator.running('0.0.0.0', 0) as (_, port), CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], port=int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
                report['greeting'] = client.greeting
                simulator_host = os.environ.get('CBUS_CGATE_SIMULATOR_HOST', 'host.docker.internal')
                created = False
                def command(text):
                    response = client.command(text)
                    report['commands'].append({'command': text, 'lines': list(response.lines)})
                    return response
                class RecordingClient:
                    def command(self, text):
                        return command(text)
                labels = NativeLabels(RecordingClient())
                trigger = NativeLabels(RecordingClient(), 'trigger')
                enable = NativeLabels(RecordingClient(), 'enable')
                def eventually(predicate):
                    deadline = time.monotonic() + 5
                    while not predicate() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(predicate(), simulator.labels.snapshot())
                try:
                    command('PROJECT NEW ' + project)
                    created = True
                    command('PROJECT USE ' + project)
                    command(f'DBCREATENET 254 Labels Cni {simulator_host}:{port}')
                    for application, name in ((56, 'Lighting'), (202, 'Trigger'), (203, 'Enable')):
                        command(f'DBADDSAFE {network} Application {application} {name}')
                    command('PROJECT SAVE ' + project)
                    command('NET LOAD DB ' + project)
                    command('NET OPEN ' + network)
                    deadline = time.monotonic() + 20
                    while True:
                        state = command('GET ' + network + ' state')
                        if any('state=ok' in line for line in state.lines):
                            break
                        self.assertLess(time.monotonic(), deadline, state.lines)
                        time.sleep(0.1)
                    app = network + '/56'
                    labels.text(app, 1, ' A  "B" ', variant=2)
                    labels.icon(app, 2, 258, variant=3)
                    labels.dynamic(app, 3, 65535, 8, 7, bytes.fromhex('01020408102040'), language=7, vertical_offset=2)
                    labels.unicode(app, 4, 'Māori āāāāāāāāāāāāāā', variant=1)
                    labels.unicode(app, 5, 'x' * 234)
                    labels.raw(app, 6, 0, b'RAW')
                    labels.set_language(app, 1, 3)
                    trigger.text(network + '/202', 7, 'Scene', action_selector=9, variant=3)
                    trigger.unicode(network + '/202', 8, '夜間', language=2)
                    enable.text(network + '/203', 9, 'Enable', action_selector=0)
                    expected = {
                        (56, 1, None, 0, 2): {'kind': 'text', 'text': ' A  "B" ', 'data_hex': '2041202022422220'},
                        (56, 2, None, 0, 3): {'kind': 'icon', 'icon': 258, 'data_hex': '010102'},
                        (56, 3, None, 7, 0): {'kind': 'dynamic', 'icon': 65535, 'width': 8, 'height': 7, 'vertical_offset': 2, 'data_hex': '01020408102040'},
                        (56, 4, None, 0, 1): {'kind': 'unicode', 'text': 'Māori āāāāāāāāāāāāāā', 'data_hex': 'Māori āāāāāāāāāāāāāā'.encode().hex()},
                        (56, 5, None, 0, 0): {'kind': 'unicode', 'text': 'x' * 234, 'data_hex': (b'x' * 234).hex()},
                        (56, 6, None, 0, 0): {'kind': 'text', 'text': 'RAW', 'data_hex': '524157'},
                        (202, 7, 9, 0, 3): {'kind': 'text', 'text': 'Scene', 'data_hex': '5363656e65'},
                        (202, 8, None, 2, 0): {'kind': 'unicode', 'text': '夜間', 'data_hex': '夜間'.encode().hex()},
                        (203, 9, 0, 0, 0): {'kind': 'text', 'text': 'Enable', 'data_hex': '456e61626c65'},
                    }
                    eventually(lambda: simulator.labels.labels == expected and simulator.labels.languages == {(56, 1, None): 3})
                    # Clear both label types through their actual native encoders.
                    labels.text(app, 6, '')
                    labels.unicode(app, 4, '', variant=1)
                    expected[(56, 6, None, 0, 0)] = {'kind': 'text', 'text': '', 'data_hex': '00'}
                    expected[(56, 4, None, 0, 1)] = {'kind': 'unicode', 'text': '', 'data_hex': ''}
                    eventually(lambda: simulator.labels.labels == expected)
                    # These are vendor limitations, not successful queued labels.
                    with self.assertRaises(CGateError) as captured:
                        client.command(f'ENABLE UNICODELABEL {network}/203 0 1 - F0 RAW 41')
                    report['unsupported_enable_unicode'] = list(captured.exception.response.lines)
                    self.assertEqual(captured.exception.response.code, 400)
                    with self.assertRaises(CGateError):
                        client.command(f'LIGHTING LABEL {app} 0 1 - F0 DYNAMIC 1 8 1 0 80:00')
                    self.assertFalse([record for record in simulator.wire_log if 'reason' in record])
                    reloaded = PCISimulator(profile='synthetic', state_path=state_path)
                    self.assertEqual(reloaded.labels.snapshot(), simulator.labels.snapshot())
                    report.update(passed=True, labels=simulator.labels.snapshot(), wire=list(simulator.wire_log), persisted=True)
                finally:
                    if created:
                        for text in ('NET CLOSE ' + network, 'PROJECT CLOSE ' + project, 'PROJECT DELETE ' + project):
                            if not client.connected:
                                client.connect()
                            command(text)
            if os.environ.get('CBUS_LABEL_REPORT'):
                output = Path(os.environ['CBUS_LABEL_REPORT'])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
