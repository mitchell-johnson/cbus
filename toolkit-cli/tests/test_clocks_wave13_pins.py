"""Wave13 narrow offline pins for clocks/scheduling (no I/O, no native writes)."""
import unittest

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.clocks import ClockParseError, parse_clock_report
from cbus_toolkit.thermostat_scheduling import ScheduleGroup, ThermostatScheduling


def response(*lines):
    return CGateResponse(tuple(lines), lines[-1], int(lines[-1][:3]))


class ClocksWave13Pins(unittest.TestCase):
    def test_failure_summary_address_256_rejected(self):
        raw = response('120-Failed to obtain output unit summary from address 256.', '200 OK.')
        with self.assertRaises(ClockParseError):
            parse_clock_report(raw)

    def test_gateway_enabled_message_is_not_a_row(self):
        report = parse_clock_report(response('120-Gateway clock at address 16 is now enabled.', '200 OK.'))
        self.assertEqual(report.rows, ())
        self.assertIn('120-Gateway clock at address 16 is now enabled.', report.messages)
        self.assertEqual(report.failures, ())
        self.assertFalse(report.complete)
        self.assertIsNone(report.clocks_enabled)


class SchedulingWave13Pins(unittest.TestCase):
    def test_button_disabled_noop_declares_offline_scope(self):
        model = ThermostatScheduling()
        state = model.load([ScheduleGroup('a', 1)], on='a', enabled=False)
        doc = model.create_levels(state).as_dict()
        self.assertTrue(doc['complete'])
        self.assertEqual(doc['events'], [{'event': 'enabled', 'value': False}])
        self.assertEqual(doc['input_scope'], 'supplied_resolved_thermostat_state')
        self.assertFalse(doc['native_persistence_verified'])
        self.assertFalse(doc['original_ui_executed'])
        self.assertFalse(doc['original_exception_unwind_executed'])

    def test_direct_run_skips_255_group_but_keeps_it(self):
        model = ThermostatScheduling()
        state = model.load([ScheduleGroup('u', 255), ScheduleGroup('r', 1)],
                           on='u', off='r', enabled=True)
        result = model.create_levels(state, policy='direct')
        self.assertEqual([r['role'] for r in result.as_dict()['roles']], ['off'])
        self.assertIs(result.state.groups[0], state.groups[0])
        self.assertEqual(result.state.groups[0].levels, ())
        self.assertEqual(len(result.state.groups[1].levels), 31)


if __name__ == '__main__':
    unittest.main()
