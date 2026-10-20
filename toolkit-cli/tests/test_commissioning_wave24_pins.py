"""Wave-24 offline pins for wireless commissioning guards (P3 commissioning slice).

Narrow pin: guards in src/cbus_toolkit/wireless_commissioning.py with zero
prior test refs (verified against tests/test_wireless_commissioning.py):
reply_bytes / requires_live_network on composed dicts, refresh_requires_live_network
on composed status entries, LIVE_NETWORK_REASON text, _byte label messages,
_hex padding/clamp, RecallOpStats chunk starts + counter-list copy semantics,
decode_op_stats over-length / bytes-like coercion / full mapping. Offline only.
"""
import unittest

from cbus_toolkit.wireless_commissioning import (
    LIVE_NETWORK_REASON,
    OP_STATS_COUNTERS,
    STATUS_ATTRIBUTES,
    _byte,
    _hex,
    decode_op_stats,
    net_learn_command,
    unit_action_commands,
)


class CommissioningWave24Pins(unittest.TestCase):
    def test_live_network_boundary_flags_and_reason(self):
        learn = net_learn_command(56, 1, 10)
        self.assertTrue(learn['requires_live_network'])
        self.assertFalse(learn['reply_expected'])
        actions = unit_action_commands(20)
        for key in ('MAISync', 'ResetOpStats', 'RecallOpStats'):
            with self.subTest(action=key):
                self.assertTrue(actions[key]['requires_live_network'])
        self.assertTrue(actions['MAISync']['reply_expected'])
        self.assertEqual(actions['MAISync']['reply_bytes'], 8)
        self.assertFalse(actions['ResetOpStats']['reply_expected'])
        for name in STATUS_ATTRIBUTES:
            with self.subTest(status=name):
                entry = actions['status'][name]
                self.assertFalse(entry['requires_live_network'])
                self.assertTrue(entry['refresh_requires_live_network'])
                self.assertTrue(entry['reply_expected'])
                self.assertEqual(entry['cgate'], 'GET <unit> ' + name)
                self.assertEqual(len(entry['refresh_commands']), 1)
        self.assertIn('network interface', LIVE_NETWORK_REASON)
        self.assertIn('physical', LIVE_NETWORK_REASON)

    def test_recall_op_stats_chunks_and_counter_copy(self):
        actions = unit_action_commands(20)
        recall = actions['RecallOpStats']
        self.assertTrue(recall['reply_expected'])
        self.assertEqual(recall['reply_bytes'], 48)
        self.assertEqual(len(recall['commands']), 4)
        starts = [cmd[-4:-2] for cmd in recall['commands']]
        self.assertEqual(starts, ['00', '0C', '18', '24'])
        self.assertTrue(all(cmd.endswith('0C') for cmd in recall['commands']))
        self.assertEqual(recall['counters'], list(OP_STATS_COUNTERS))
        self.assertIsNot(recall['counters'], OP_STATS_COUNTERS)
        recall['counters'].append('MUTATED')
        self.assertEqual(len(unit_action_commands(20)['RecallOpStats']['counters']), 12)

    def test_byte_guards_reject_non_integers_with_labels(self):
        with self.assertRaisesRegex(ValueError, 'Application.*0\\.\\.255'):
            net_learn_command(True, 1, 10)
        with self.assertRaisesRegex(ValueError, 'Group.*0\\.\\.255'):
            net_learn_command(56, 1, -1)
        with self.assertRaisesRegex(ValueError, 'Application.*0\\.\\.255'):
            net_learn_command('x', 1, 10)
        with self.assertRaisesRegex(ValueError, 'Unit address.*0\\.\\.255'):
            unit_action_commands(True)
        with self.assertRaisesRegex(ValueError, 'Unit address.*0\\.\\.255'):
            unit_action_commands(None)
        with self.assertRaisesRegex(ValueError, 'Unit address.*0\\.\\.255'):
            unit_action_commands(1.5)
        self.assertEqual(_byte(0, 'Application'), 0)
        self.assertEqual(_byte(255, 'Group'), 255)
        self.assertEqual((_hex(0), _hex(15), _hex(255), _hex(256)), ('00', '0F', 'FF', 'FF'))

    def test_decode_op_stats_full_map_and_over_length(self):
        data = b''.join(i.to_bytes(4, 'little') for i in range(1, 13))
        decoded = decode_op_stats(bytearray(data))
        self.assertEqual(decoded['PacketsReceived'], 1)
        self.assertEqual(decoded['PacketsReceivedWithError'], 2)
        self.assertEqual(decoded['TransmissionsNAKd'], 12)
        self.assertEqual(len(decoded), 12)
        self.assertEqual(decode_op_stats(list(data))['CollisionsDetected'], 5)
        with self.assertRaisesRegex(ValueError, 'recall failed'):
            decode_op_stats(data + b'\x00')


if __name__ == '__main__':
    unittest.main()
