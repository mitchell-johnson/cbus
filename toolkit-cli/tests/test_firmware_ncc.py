"""Independent bounded NCC transcript vectors; no serial or USB backend."""
import hashlib
import itertools
import json
import unittest

from cbus_toolkit.firmware_ncc import PROGRESS_KEYS, evaluate_ncc_post_check


ID = (b'Manufacturer=Clipsal\r\nProduct=eDLT\r\nSerial Number=PRIVATE-SERIAL\r\n'
      b'HW Version=3.0 (Tiva + NCC)\r\nFW Version=1.7.0\r\n'
      b'CPU Speed=120\r\nUnit Address=20\r\n')
PROGRESS = b'Updating NCC Firmware..\r\nUpdate Started\r\nUpdate Complete\r\n'


def nv(current='1.0.0', embedded='1.1.0'):
    return (f'NCC current version: {current}\r\nNCC embedded version: {embedded}\r\n').encode()


def exchange(command, response=b'', outcome='response'):
    return {'command': command, 'response': response, 'outcome': outcome}


def prefix(current='1.0.0', embedded='1.1.0'):
    return [exchange('id', ID), exchange('nv', nv(current, embedded))]


def updated(current='1.1.0', embedded='1.1.0'):
    return prefix() + [exchange('nu', PROGRESS), exchange('nv', nv(current, embedded))]


def evaluate(rows):
    return evaluate_ncc_post_check('1.7.0', rows)


class NCCTranscriptTest(unittest.TestCase):
    def test_empty_and_each_progressive_prefix_select_original_next_command(self):
        full = updated('0.0.0') + [exchange('rs', outcome='write-ok'), exchange('id', ID)]
        expected = [('id', 10000, 10000, False), ('nv', 500, 10000, False),
                    ('nu', 0, 60000, True), ('nv', 0, 10000, False),
                    ('rs', 0, None, True), ('id', 10000, 10000, False)]
        for index, (command, delay, timeout, mutation) in enumerate(expected):
            with self.subTest(index=index):
                result = evaluate(full[:index])
                self.assertEqual(result['status'], 'awaiting-transcript')
                self.assertIsNone(result['native_success'])
                self.assertFalse(result['transcript_checks_passed'])
                step = result['next_step']
                self.assertEqual(step['command'], command)
                self.assertEqual(step['request_hex'], (command + '\r').encode().hex())
                self.assertEqual(step['delay_before_ms'], delay)
                self.assertEqual(step['native_timeout_ms'], timeout)
                self.assertEqual(step['would_mutate_device'], mutation)
                self.assertFalse(step['execution_supported'])

    def test_current_same_or_newer_does_not_request_update(self):
        for current in ('1.1.0', '1.1.0.0', '2.0'):
            with self.subTest(current=current):
                result = evaluate(prefix(current))
                self.assertEqual(result['status'], 'transcript-checks-passed')
                self.assertTrue(result['native_success'])
                self.assertFalse(result['checks']['ncc_update_required'])
                self.assertIsNone(result['next_step'])
                self.assertEqual([s['command'] for s in result['steps']], ['id', 'nv'])

    def test_dotnet_missing_components_signed_and_spaced_components(self):
        for current, embedded in [('1.0', '1.0.0'), ('1.1.0', '1.1.0.0'), ('+1.0', '1. +1')]:
            with self.subTest(current=current, embedded=embedded):
                result = evaluate(prefix(current, embedded))
                self.assertTrue(result['checks']['ncc_update_required'])
                self.assertEqual(result['next_step']['command'], 'nu')

    def test_initial_firmware_version_requires_exact_string_equality(self):
        result = evaluate([exchange('id', ID.replace(b'1.7.0', b'1.7.0.0'))])
        self.assertEqual(result['native_outcome'], 'failed')
        self.assertEqual(result['reason'], 'identify:firmware-version-mismatch')
        self.assertEqual(len(result['steps']), 1)

    def test_initial_version_constructor_precedes_blank_fallback(self):
        for current, embedded in [('', '1.1.0'), ('1.0.0', ''), ('bad', '1.1.0'),
                                  ('1.-1', '1.1.0'), ('2147483648.0', '1.1.0')]:
            with self.subTest(current=current, embedded=embedded):
                result = evaluate(prefix(current, embedded))
                self.assertFalse(result['native_success'])
                self.assertEqual(result['reason'], 'ncc-versions:invalid-version')
                self.assertIsNone(result['next_step'])

    def test_initial_command_not_valid_fails_through_empty_versions(self):
        result = evaluate([exchange('id', ID), exchange('nv', b'COMMAND NOT VALID\r\n')])
        self.assertFalse(result['native_success'])
        self.assertEqual(result['reason'], 'ncc-versions:invalid-version')

    def test_original_update_progress_requires_each_trimmed_key_in_any_order(self):
        for order in itertools.permutations(PROGRESS_KEYS):
            data = ''.join(' \t' + line + ' \t\r\n' for line in order).encode()
            result = evaluate(prefix() + [exchange('nu', data)])
            self.assertEqual(result['next_step']['step'], 'ncc-versions-after-update')
            self.assertEqual(result['steps'][-1]['progress_keys_present'], list(PROGRESS_KEYS))
        for key in PROGRESS_KEYS:
            data = PROGRESS.replace(key.encode() + b'\r\n', b'')
            result = evaluate(prefix() + [exchange('nu', data)])
            self.assertFalse(result['native_success'])
            self.assertEqual(result['reason'], 'ncc-update:incomplete-response')

    def test_progress_colon_case_and_partial_line_do_not_match(self):
        for data in (PROGRESS.replace(b'Update Complete', b'Update Complete:'),
                     PROGRESS.replace(b'Update Complete', b'update complete'),
                     PROGRESS[:-2], PROGRESS.replace(b'\r\n', b'\n')):
            result = evaluate(prefix() + [exchange('nu', data)])
            self.assertEqual(result['native_outcome'], 'failed')

    def test_duplicate_progress_lines_are_native_set_membership(self):
        result = evaluate(prefix() + [exchange('nu', PROGRESS * 2)])
        self.assertEqual(result['next_step']['command'], 'nv')
        self.assertFalse(result['verification_gaps'])

    def test_completed_update_checks_target_separately_from_native_success(self):
        result = evaluate(updated())
        self.assertEqual(result['native_outcome'], 'reported-success')
        self.assertTrue(result['transcript_checks_passed'])
        self.assertTrue(result['checks']['post_update_current_matches_target'])
        self.assertFalse(result['checks']['restart_required'])
        self.assertEqual([s['command'] for s in result['steps']], ['id', 'nv', 'nu', 'nv'])

    def test_native_does_not_compare_post_update_versions(self):
        for current, embedded in [('1.0.0', '1.1.0'), ('1.1.0', '1.2.0'), ('bad', 'bad'), ('', '')]:
            with self.subTest(current=current, embedded=embedded):
                result = evaluate(updated(current, embedded))
                self.assertTrue(result['native_success'])
                self.assertFalse(result['transcript_checks_passed'])
                self.assertEqual(result['status'], 'native-success-with-verification-gaps')

    def test_post_update_command_not_valid_is_native_success_but_unverified(self):
        result = evaluate(prefix() + [exchange('nu', PROGRESS), exchange('nv', b'COMMAND NOT VALID\r\n')])
        self.assertTrue(result['native_success'])
        self.assertFalse(result['transcript_checks_passed'])
        self.assertFalse(result['checks']['post_update_current_matches_target'])

    def test_unsupported_partial_nv_keeps_both_native_out_arguments_empty(self):
        response = b'NCC current version: 0.0.0\r\nCOMMAND NOT VALID\r\n'
        result = evaluate(prefix() + [exchange('nu', PROGRESS), exchange('nv', response)])
        self.assertTrue(result['native_success'])
        self.assertFalse(result['checks']['restart_required'])
        self.assertIsNone(result['next_step'])

    def test_restart_uses_exact_post_update_current_text(self):
        result = evaluate(updated('0.0.0'))
        self.assertEqual(result['next_step']['command'], 'rs')
        for current in ('0.0', '0.0.0.0', '00.0.0', '+0.0.0'):
            with self.subTest(current=current):
                result = evaluate(updated(current))
                self.assertTrue(result['native_success'])
                self.assertFalse(result['checks']['restart_required'])
                self.assertIsNone(result['next_step'])
        result = evaluate(prefix('0.0.0') + [exchange('nu', PROGRESS), exchange('nv', nv('1.1.0'))])
        self.assertTrue(result['native_success'])
        self.assertFalse(result['checks']['restart_required'])

    def test_restart_write_has_no_ack_and_no_final_ncc_verification(self):
        result = evaluate(updated('0.0.0') + [exchange('rs', outcome='write-ok'), exchange('id', ID)])
        self.assertTrue(result['native_success'])
        self.assertTrue(result['checks']['restart_identity_matches'])
        self.assertTrue(result['checks']['restart_firmware_version_exact'])
        self.assertFalse(result['transcript_checks_passed'])
        self.assertFalse(result['steps'][4]['acknowledged'])
        self.assertIn('restart:no-final-ncc-version-read-in-original', result['verification_gaps'])

    def test_failed_restart_identification_is_original_manual_restart_success(self):
        for last in (exchange('id', outcome='timeout'), exchange('id', outcome='io-error'),
                     exchange('id', b'Manufacturer=Clipsal\r\n')):
            result = evaluate(updated('0.0.0') + [exchange('rs', outcome='write-ok'), last])
            self.assertEqual(result['native_outcome'], 'reported-success-manual-restart')
            self.assertTrue(result['native_success'])
            self.assertFalse(result['transcript_checks_passed'])

    def test_original_does_not_compare_identity_or_version_after_restart(self):
        altered = ID.replace(b'PRIVATE-SERIAL', b'OTHER-SERIAL').replace(b'1.7.0', b'1.6.0')
        result = evaluate(updated('0.0.0') + [exchange('rs', outcome='write-ok'), exchange('id', altered)])
        self.assertTrue(result['native_success'])
        self.assertFalse(result['checks']['restart_identity_matches'])
        self.assertFalse(result['checks']['restart_firmware_version_exact'])

    def test_failures_stop_at_every_pre_restart_step_without_replay(self):
        rows = updated('0.0.0') + [exchange('rs', outcome='write-ok')]
        for index in range(len(rows)):
            for outcome in ('timeout', 'io-error'):
                with self.subTest(index=index, outcome=outcome):
                    failed = rows[:index] + [exchange(rows[index]['command'], outcome=outcome)]
                    result = evaluate(failed)
                    self.assertFalse(result['native_success'])
                    self.assertIsNone(result['next_step'])
                    self.assertEqual(len(result['steps']), index + 1)

    def test_initial_complete_non_ncc_or_blank_identity_keeps_native_fact(self):
        for identity in (ID.replace(b'3.0 (Tiva + NCC)', b'2.0 (Tiva + PCI)'),
                         ID.replace(b'Serial Number=PRIVATE-SERIAL', b'Serial Number=')):
            result = evaluate([exchange('id', identity), exchange('nv', nv('1.1.0'))])
            self.assertTrue(result['native_success'])
            self.assertFalse(result['checks']['initial_identity_usable_tiva_ncc'])
            self.assertFalse(result['transcript_checks_passed'])

    def test_last_duplicate_value_is_native_but_cannot_verify(self):
        rows = [exchange('id', ID + b'FW Version=1.6.0\r\nFW Version=1.7.0\r\n'),
                exchange('nv', nv('1.1.0') + b'NCC current version: 2.0.0\r\n')]
        result = evaluate(rows)
        self.assertTrue(result['native_success'])
        self.assertFalse(result['transcript_checks_passed'])
        self.assertEqual(result['verification_gaps'], ['identify:ambiguous-response',
                         'identify:unusable-or-non-ncc-identity', 'ncc-versions:ambiguous-response'])

    def test_both_nv_versions_take_precedence_over_invalid_command_in_native(self):
        result = evaluate([exchange('id', ID), exchange('nv', nv('1.1.0') + b'COMMAND NOT VALID\r\n')])
        self.assertTrue(result['native_success'])
        self.assertFalse(result['transcript_checks_passed'])

    def test_trailing_fragment_preserves_native_result_with_verification_gap(self):
        result = evaluate([exchange('id', ID + b'private partial'), exchange('nv', nv('1.1.0'))])
        self.assertTrue(result['native_success'])
        self.assertFalse(result['transcript_checks_passed'])
        self.assertIn('identify:trailing-fragment', result['verification_gaps'])

    def test_input_shape_and_resource_limits(self):
        bad_inputs = [None, {}, 'id', [exchange('id', ID)] * 7, [None],
                      [{'command': 'id', 'port': 'PRIVATE-PORT'}], [{'command': ['id']}],
                      [exchange('id', 'text')], [exchange('id', b'x' * 65537)],
                      [exchange('id', ID, outcome=True)], [exchange('rs')],
                      [exchange('rs', b'ack', 'write-ok')], [exchange('id\r', ID)]]
        for rows in bad_inputs:
            with self.subTest(kind=type(rows).__name__):
                with self.assertRaises(ValueError):
                    evaluate(rows)
        for version in (None, 123, '', '1.7.0\n', 'x' * 129, '\u00e9'):
            with self.assertRaises(ValueError):
                evaluate_ncc_post_check(version)

    def test_parser_profile_refuses_nonascii_control_long_line_and_fields(self):
        for response in (b'\xff', b'\x00', b'x' * 4097, b'x' * 4097 + b'\r\n',
                         b''.join(f'key{i}=x\r\n'.encode() for i in range(257))):
            with self.assertRaisesRegex(ValueError, 'bounded ASCII transcript profile'):
                evaluate([exchange('id', response)])

    def test_wrong_order_and_extra_exchanges_are_refused(self):
        for rows in ([exchange('nv', nv())], prefix('1.1.0') + [exchange('nu', PROGRESS)],
                     [exchange('id', outcome='timeout'), exchange('nv', nv())]):
            with self.assertRaises(ValueError):
                evaluate(rows)

    def test_receipts_sanitize_transcripts_and_never_claim_hardware_or_native_execution(self):
        result = evaluate([exchange('id', ID + b'PrivateNote=SECRET-EXTRA\r\n'),
                           exchange('nv', nv('1.1.0'))])
        text = json.dumps(result)
        for private in ('PRIVATE-SERIAL', 'SECRET-EXTRA', 'Unit Address', 'PrivateNote', 'Clipsal'):
            self.assertNotIn(private, text)
        self.assertEqual(result['steps'][0]['response_sha256'],
                         hashlib.sha256(ID + b'PrivateNote=SECRET-EXTRA\r\n').hexdigest())
        self.assertEqual(result['commands_sent'], 0)
        for field in ('hardware_accessed', 'native_execution', 'physical_acceptance',
                      'firmware_contents_verified', 'destructive_execution_supported',
                      'timing_modelled', 'raw_responses_reported'):
            self.assertFalse(result[field])
        self.assertEqual(result['source']['sha256'],
                         'f54ea945167436b8a3e95decb1d146d01d60e4af1badcd34f4bad626df1e54d5')


if __name__ == '__main__':
    unittest.main()
