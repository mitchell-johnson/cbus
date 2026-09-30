"""C-Gate wireless learn and unit-action boundary: composed commands match the source fixture."""
import json
from pathlib import Path
import unittest

from cbus_toolkit.wireless_commissioning import (
    LEARN_GRADES, OP_STATS_COUNTERS, STATUS_ATTRIBUTES, decode_op_stats, net_learn_command, unit_action_commands)

FIXTURE = Path(__file__).resolve().parents[1] / 'research/fixtures/wireless-cgate-boundary.json'


class BoundaryFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text())
        self.actions = {row['id']: row for row in self.fixture['actions']}

    def test_fixture_is_sanitized_and_cached_status_does_not_need_a_live_network(self):
        text = FIXTURE.read_text()
        for forbidden in ('/Volumes/', 'password', 'C:\\\\'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(len(self.fixture['inputs']['cgate_jar_sha256']), 64)
        self.assertIn('no bus', self.fixture['evidence'])
        self.assertTrue(all(row['requires_live_network'] and row['why_live'] for key, row in self.actions.items()
                            if key != 'cgate-wireless:status'))
        self.assertFalse(self.actions['cgate-wireless:status']['requires_live_network'])
        self.assertTrue(self.actions['cgate-wireless:status']['refresh_requires_live_network'])

    def test_unit_actions_reproduce_the_recorded_commands(self):
        commands = unit_action_commands(20)
        self.assertEqual(commands['MAISync']['commands'], [self.actions['cgate-wireless:MAISync']['example']])
        self.assertEqual(commands['ResetOpStats']['commands'], [self.actions['cgate-wireless:ResetOpStats']['example']])
        self.assertFalse(commands['ResetOpStats']['reply_expected'])
        self.assertEqual(commands['RecallOpStats']['commands'], self.actions['cgate-wireless:RecallOpStats']['example'])
        self.assertEqual(list(OP_STATS_COUNTERS), self.actions['cgate-wireless:RecallOpStats']['counters'])
        self.assertEqual([commands['status'][name]['refresh_commands'][0] for name in STATUS_ATTRIBUTES],
                         self.actions['cgate-wireless:status']['refresh_example'])
        self.assertTrue(all(row['commands'] == [] and row['cached_only'] and not row['requires_live_network']
                            for row in commands['status'].values()))
        self.assertEqual(unit_action_commands(255)['ResetOpStats']['commands'], ['\\46FF0008'])
        with self.assertRaises(ValueError):
            unit_action_commands(256)

    def test_net_learn_reproduces_the_recorded_command_and_grade_rules(self):
        row = self.actions['cgate-wireless:NET LEARN']
        self.assertEqual(net_learn_command(*row['example_arguments'])['command'], row['example'])
        self.assertEqual({str(k): v for k, v in LEARN_GRADES.items()}, row['grades'])
        self.assertEqual(net_learn_command(255, 0x83, 255)['command'], '\\05FF000383FF7E')
        self.assertEqual(net_learn_command(0, 0x80, 0x80)['command'], '\\050000038080' + '00')
        for grade in (0, 3, 127, 132, 256, True):
            with self.subTest(grade=grade):
                with self.assertRaises(ValueError):
                    net_learn_command(56, grade, 1)

    def test_op_stats_decode(self):
        data = b''.join(i.to_bytes(4, 'little') for i in range(1, 13))
        self.assertEqual(decode_op_stats(data)['TransmissionsNAKd'], 12)
        with self.assertRaisesRegex(ValueError, 'recall failed'):
            decode_op_stats(data[:47])


if __name__ == '__main__':
    unittest.main()
