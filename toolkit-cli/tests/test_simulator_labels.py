"""Independent receiver tests use literal native SAL captures, no client codec."""
import unittest

from cbus_toolkit.simulator_labels import LabelPacketError, LabelState


class SimulatorLabelTests(unittest.TestCase):
    def setUp(self):
        self.state = LabelState()

    def receive(self, hex_string, app=56):
        return self.state.receive(app, bytes.fromhex(hex_string))

    def test_native_text_icon_and_unicode_stored_by_variant(self):
        self.assertTrue(self.receive('a90140004c6f756e6765'))
        self.assertTrue(self.receive('a6016200010102'))
        self.assertTrue(self.receive('ca01ee01004dc4816f7269'))
        self.assertEqual(self.state.labels[(56, 1, None, 0, 2)]['text'], 'Lounge')
        self.assertEqual(self.state.labels[(56, 1, None, 0, 3)]['icon'], 258)
        self.assertEqual(self.state.labels[(56, 1, None, 0, 1)]['text'], 'Māori')

    def test_dynamic_only_commits_after_complete_native_sequence(self):
        for packet in ('a401080020', 'a80104000001080100', 'a401080021', 'a3010480'):
            self.assertFalse(self.receive(packet))
            self.assertEqual(self.state.snapshot()['labels'], [])
        self.assertTrue(self.receive('a401080022'))
        self.assertEqual(self.state.labels[(56, 1, None, 0, 0)], {'kind': 'dynamic', 'icon': 1, 'width': 8, 'height': 1, 'vertical_offset': 0, 'data_hex': '80'})

    def test_incomplete_dynamic_or_missing_append_is_rejected(self):
        for packets in [('a401080022',), ('a80104000001080100',), ('a401080020', 'a80104000001080100', 'a401080022'), ('a401080020', 'a80104000001080100', 'a3010480')]:
            self.state = LabelState()
            for packet in packets[:-1]:
                self.receive(packet)
            with self.assertRaises(LabelPacketError):
                self.receive(packets[-1])
            self.assertEqual(self.state.labels, {})

    def test_unicode_reassembles_before_decoding_multibyte_character(self):
        self.assertFalse(self.receive('d102320000313233343536373839303132c4'))
        self.assertEqual(self.state.labels, {})
        self.assertTrue(self.receive('c6024a00008121'))
        self.assertEqual(self.state.labels[(56, 2, None, 0, 0)]['text'], '123456789012ā!')

    def test_unicode_missing_or_invalid_fragments_cannot_commit(self):
        with self.assertRaisesRegex(LabelPacketError, 'out-of-order'):
            self.receive('c6024a00008121')
        self.receive('d102320000313233343536373839303132c4')
        with self.assertRaisesRegex(LabelPacketError, 'out-of-order'):
            self.receive('c6025a00008121')
        with self.assertRaisesRegex(LabelPacketError, 'invalid UTF-8'):
            self.receive('c5010e0000ff')
        self.assertEqual(self.state.labels, {})

    def test_unicode_precedence_clear_then_ascii(self):
        self.receive('ca01ee01004dc4816f7269')
        self.assertFalse(self.receive('a401200041'))
        self.assertEqual(self.state.labels[(56, 1, None, 0, 1)]['text'], 'Māori')
        self.receive('c4010e0100')
        self.assertTrue(self.receive('a401200041'))
        self.assertEqual(self.state.labels[(56, 1, None, 0, 1)]['text'], 'A')

    def test_action_selector_language_and_application_are_separate(self):
        self.receive('a50161090241', app=202)
        self.assertEqual(self.state.labels[(202, 1, 9, 2, 3)]['text'], 'A')
        self.receive('a401070903', app=202)
        self.assertEqual(self.state.languages[(202, 1, 9)], 3)
        self.receive('c5070f830902', app=202)
        self.assertEqual(self.state.labels[(202, 7, 9, 2, 3)]['text'], '')

    def test_snapshot_roundtrip_and_unfinished_upload_exclusion(self):
        self.receive('a90140004c6f756e6765')
        self.receive('a401080020')
        saved = self.state.snapshot()
        loaded = LabelState.from_snapshot(saved)
        self.assertEqual(loaded.snapshot(), saved)
        with self.assertRaises(LabelPacketError):
            loaded.receive(56, bytes.fromhex('a80104000001080100'))
        for changes in ({'data_hex': 'x'}, {'data_hex': '00'*15}, {'text': 'different'}, {'unexpected': 'field'}):
            invalid = self.state.snapshot()
            invalid['labels'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(LabelPacketError):
                LabelState.from_snapshot(invalid)

    def test_unsupported_or_bad_length_packets_rejected(self):
        for packet in ('', 'a3', 'a401', 'a40100004142', 'a401800041', 'a3010a00', 'c5011d000041', 'a6010200020102'):
            with self.subTest(packet=packet), self.assertRaises(LabelPacketError):
                self.receive(packet)
        with self.assertRaises(LabelPacketError):
            self.receive('a401000041', app=1)
        self.assertEqual(self.state.labels, {})


if __name__ == '__main__':
    unittest.main()
