"""Literal dz/bJ native replies and no-replay outcome tests."""
import json
from pathlib import Path
import unittest

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.clocks import ClockParseError, NativeClocks, parse_clock_report


def response(*lines):
    return CGateResponse(tuple(lines), lines[-1], int(lines[-1][:3]))


ONE = response('120-address=16 output_units=1 clocks_enabled=1 clocks_active=1 burdens_enabled=0',
               '120-address=17 output_units=1 clocks_enabled=0 clocks_active=0 burdens_enabled=0', '200 OK.')
TWO = response('120-address=16 output_units=1 clocks_enabled=1 clocks_active=1 burdens_enabled=0',
               '120-address=17 output_units=1 clocks_enabled=1 clocks_active=0 burdens_enabled=1', '200 OK.')
ENABLED = response('120-Keeping the master clock at address 16 enabled.',
                   '120-Clock at address 17 is now enabled.', '200 OK.')
FAILED = response('120-Keeping the master clock at address 16 enabled.',
                  '120-Clock at address 17 could NOT be enabled: Set clock failed: Failed to set parameter.', '200 OK.')


class ScriptClient:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.commands = []

    def command(self, text):
        self.commands.append(text)
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class ClockReportTests(unittest.TestCase):
    def test_exact_literal_native_report_and_aggregate_counts(self):
        report = parse_clock_report(TWO)
        self.assertTrue(report.complete)
        self.assertEqual((report.clocks_enabled, report.clocks_active, report.burdens_enabled), (2, 1, 1))
        self.assertEqual(report.rows[1].address, 17)
        self.assertEqual(report.messages, ('200 OK.',))
        self.assertIs(report.response, TWO)
        self.assertEqual(report.as_dict()['clocks_enabled'], 2)

    def test_zero_output_row_keeps_native_omissions(self):
        result = parse_clock_report(response('120-address=4 output_units=0', *ONE.lines))
        self.assertTrue(result.complete)
        self.assertIsNone(result.rows[0].clocks_enabled)
        self.assertIsNone(result.rows[0].clocks_active)
        self.assertIsNone(result.rows[0].burdens_enabled)
        self.assertEqual(result.clocks_enabled, 1)

    def test_counts_at_duplicate_physical_address_are_not_boolean_flags(self):
        result = parse_clock_report(response('120-address=16 output_units=3 clocks_enabled=2 clocks_active=1 burdens_enabled=2', '200 OK.'))
        self.assertEqual((result.rows[0].output_units, result.clocks_enabled), (3, 2))

    def test_each_native_failure_phrase_survives_final200(self):
        literals = (
            ('Failed to obtain output unit summary from address 4.', 'summary_unavailable', 4),
            ('First clock at address 16 could NOT be enabled: Set clock failed: No unit available', 'unit_change_failed', 16),
            ('Clock at address 5 could NOT be enabled: Set clock failed: Unit type KEYGL5 does not support clock', 'unit_change_failed', 5),
            ('Master clock at address 16 could NOT be disabled: Set clock failed: Failed to set parameter.', 'unit_change_failed', 16),
            ('FAILED - Operation already in progress.', 'native_operation_failed', None),
        )
        for text, kind, address in literals:
            with self.subTest(text=text):
                raw = response('120-' + text, *ONE.lines)
                result = parse_clock_report(raw)
                self.assertFalse(result.complete)
                self.assertEqual(result.failures[0].kind, kind)
                self.assertEqual(result.failures[0].address, address)
                self.assertEqual(result.failures[0].message, text)
                self.assertIn('120-' + text, result.messages)

    def test_unknown_progress_messages_are_preserved(self):
        report = parse_clock_report(response('120-Future vendor progress message: keep exact text', *ONE.lines))
        self.assertTrue(report.complete)
        self.assertEqual(report.messages[0], '120-Future vendor progress message: keep exact text')

    def test_missing_duplicate_extra_and_impossible_fields_are_rejected(self):
        rows = (
            'address=16 output_units=1 clocks_enabled=1 clocks_active=1',
            'address=16 address=17 output_units=0',
            'address=16 output_units=0 unknown=1',
            'address=16 output_units=0 clocks_enabled=0 clocks_active=0 burdens_enabled=0',
            'address=256 output_units=0',
            'address=16 output_units=256 clocks_enabled=1 clocks_active=0 burdens_enabled=0',
            'address=16 output_units=1 clocks_enabled=2 clocks_active=1 burdens_enabled=0',
            'address=16 output_units=-1',
            'address=16 output_units=NaN',
        )
        for row in rows:
            with self.subTest(row=row), self.assertRaises(ClockParseError):
                parse_clock_report(response('120-' + row, '200 OK.'))

    def test_duplicate_address_rejection_retains_partial_parse(self):
        raw = response(ONE.lines[0], ONE.lines[0], '200 OK.')
        with self.assertRaises(ClockParseError) as caught:
            parse_clock_report(raw)
        self.assertIs(caught.exception.response, raw)
        self.assertEqual(len(caught.exception.rows), 1)

    def test_limits_prefix_and_final_frame_validation(self):
        invalid = (
            response('120-' + 'x' * 8192, '200 OK.'),
            response(*(['120-x'] * 2048), '200 OK.'),
            response(*(['120-' + 'x' * 8188] * 129), '200 OK.'),
            response('120-x\n200 OK.', '200 OK.'),
            response('address=16 output_units=0', '200 OK.'),
            response('300-address=16 output_units=0', '200 OK.'),
            CGateResponse(('200 OK.',), '200 Different', 200),
        )
        for raw in invalid:
            with self.subTest(lines=len(raw.lines)), self.assertRaises(ClockParseError):
                parse_clock_report(raw)

    def test_status_failure_and_empty_inspection_are_incomplete(self):
        failed = parse_clock_report(response('120-FAILED - Operation already in progress.', '408 Operation already in progress.'))
        self.assertFalse(failed.complete)
        self.assertEqual(len(failed.failures), 2)
        empty = parse_clock_report(response('200 OK.'))
        self.assertFalse(empty.complete)
        self.assertIsNone(empty.clocks_enabled)

    def test_permanent_native_failure_fixture(self):
        fixture = Path(__file__).resolve().parents[1] / 'research/fixtures/native-clocks-acceptance.json'
        document = json.loads(fixture.read_text())
        for lines in document['failure_response']:
            report = parse_clock_report(response(*lines))
            self.assertEqual(report.response.code, 200)
            self.assertEqual(report.failures[0].kind, 'unit_change_failed')
            self.assertFalse(report.complete)


class ClockOutcomeTests(unittest.TestCase):
    def test_inspect_is_one_readonly_command(self):
        client = ScriptClient(ONE)
        result = NativeClocks(client).inspect('//TEST/254')
        self.assertTrue(result.complete)
        self.assertEqual(client.commands, ['NET CLOCKS //TEST/254'])

    def test_configure_requires_fresh_observed_target(self):
        client = ScriptClient(ENABLED, TWO)
        result = NativeClocks(client).configure('//TEST/254', 2)
        self.assertTrue(result.complete)
        self.assertEqual((result.requested_enabled, result.observed_enabled), (2, 2))
        self.assertFalse(result.device_verified)
        self.assertIs(result.action_response, ENABLED)
        self.assertIs(result.inspection_response, TWO)
        self.assertEqual(client.commands, ['NET CLOCKS //TEST/254 2', 'NET CLOCKS //TEST/254'])

    def test_unmet_target_is_incomplete_without_retry(self):
        client = ScriptClient(ENABLED, ONE)
        result = NativeClocks(client).configure('//TEST/254', 2)
        self.assertFalse(result.complete)
        self.assertEqual(result.observed_enabled, 1)
        self.assertIn('Requested 2 enabled clocks; observed 1', result.issues)
        self.assertEqual(len(client.commands), 2)

    def test_per_unit_failure_is_incomplete_even_when_count_matches(self):
        client = ScriptClient(FAILED, TWO)
        result = NativeClocks(client).configure('//TEST/254', 2)
        self.assertFalse(result.complete)
        self.assertEqual(result.observed_enabled, 2)
        self.assertIs(result.action_response, FAILED)
        self.assertIn('could NOT be enabled', result.issues[0])
        self.assertEqual(len(client.commands), 2)

    def test_summary_failure_in_fresh_inspection_is_not_hidden_by_matching_count(self):
        incomplete = response('120-Failed to obtain output unit summary from address 4.', *TWO.lines)
        result = NativeClocks(ScriptClient(ENABLED, incomplete)).configure('//TEST/254', 2)
        self.assertFalse(result.complete)
        self.assertEqual(result.observed_enabled, 2)

    def test_recover_disabled_gateway_uses_old_row_and_fresh_enabled_state(self):
        recovered = response('120-address=16 output_units=1 clocks_enabled=0 clocks_active=0 burdens_enabled=1',
                             '120-Gateway clock at address 16 is now enabled.', '200 OK.')
        client = ScriptClient(recovered, TWO)
        result = NativeClocks(client).recover('//TEST/254')
        self.assertTrue(result.complete)
        self.assertEqual(result.recovery_gateway, 16)
        self.assertIsNone(result.requested_enabled)
        self.assertEqual(result.observed_enabled, 2)
        self.assertIn('no network-wide target count', result.recovery_semantics)
        self.assertEqual(client.commands, ['NET CLOCKS //TEST/254 R', 'NET CLOCKS //TEST/254'])

    def test_recover_already_enabled_gateway_needs_no_success_message(self):
        result = NativeClocks(ScriptClient(response(ONE.lines[0], '200 OK.'), ONE)).recover('//TEST/254')
        self.assertTrue(result.complete)
        self.assertEqual(result.recovery_gateway, 16)

    def test_recover_cannot_claim_success_from_another_enabled_clock(self):
        old = response('120-address=16 output_units=1 clocks_enabled=0 clocks_active=0 burdens_enabled=0', '200 OK.')
        other = response('120-address=17 output_units=1 clocks_enabled=1 clocks_active=1 burdens_enabled=0', '200 OK.')
        result = NativeClocks(ScriptClient(old, other)).recover('//TEST/254')
        self.assertFalse(result.complete)
        self.assertEqual(result.observed_enabled, 1)

    def test_recovery_identity_conflict_is_incomplete(self):
        conflict = response(ONE.lines[0], '120-Gateway clock at address 17 is now enabled.', '200 OK.')
        result = NativeClocks(ScriptClient(conflict, TWO)).recover('//TEST/254')
        self.assertFalse(result.complete)
        self.assertIsNone(result.recovery_gateway)

    def test_action_transport_failure_stops_without_query_or_reconnect(self):
        for error in (OSError('connection reset'), RuntimeError('framing failure')):
            client = ScriptClient(error, TWO)
            result = NativeClocks(client).configure('//TEST/254', 2)
            self.assertFalse(result.complete)
            self.assertIsNone(result.action_response)
            self.assertIsNone(result.inspection)
            self.assertEqual(client.commands, ['NET CLOCKS //TEST/254 2'])

    def test_action_parse_failure_retains_response_and_stops(self):
        malformed = response('120-address=16 output_units=1', '200 OK.')
        client = ScriptClient(malformed, TWO)
        result = NativeClocks(client).configure('//TEST/254', 2)
        self.assertFalse(result.complete)
        self.assertIs(result.action_response, malformed)
        self.assertEqual(len(client.commands), 1)

    def test_fresh_query_failure_retains_action_and_partial_inspection_response(self):
        malformed = response('120-address=16 output_units=1', '200 OK.')
        client = ScriptClient(ENABLED, malformed)
        result = NativeClocks(client).configure('//TEST/254', 2)
        self.assertFalse(result.complete)
        self.assertIs(result.action_response, ENABLED)
        self.assertIs(result.inspection_response, malformed)
        self.assertIsNone(result.inspection)
        self.assertEqual(len(client.commands), 2)

    def test_complete_native_error_reply_preserved_with_one_inspection(self):
        rejected = response('120-FAILED - Operation already in progress.', '408 Operation already in progress.')
        client = ScriptClient(CGateError(rejected), TWO)
        result = NativeClocks(client).configure('//TEST/254', 2)
        self.assertFalse(result.complete)
        self.assertIs(result.action_response, rejected)
        self.assertEqual(result.observed_enabled, 2)
        self.assertEqual(len(client.commands), 2)

    def test_target_and_single_network_validation_precede_io(self):
        client = ScriptClient()
        for target in (0, 11, True, False, 1.0, '2', None):
            with self.subTest(target=target), self.assertRaises(ValueError):
                NativeClocks(client).configure('//TEST/254', target)
        for address in ('*', '//TEST/*', '254,253', '254\nNET OPEN *'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                NativeClocks(client).recover(address)
        self.assertEqual(client.commands, [])


if __name__ == '__main__':
    unittest.main()
