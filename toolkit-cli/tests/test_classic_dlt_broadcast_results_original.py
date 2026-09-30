"""Independent LABEL parser evidence, distinct from portable acceptance policy."""
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/classic-dlt-broadcast-results-original.json'


def expected(lines):
    state, error, history, steps = 'pending', None, [], []
    for line in lines:
        if line.startswith('200 OK') and state != 'error':
            state = 'completed'
        failures = []
        if '400' in line and 'Syntax Error' in line:
            failures.append({'class': 'ECGateSyntaxError',
                             'message': 'Syntax Error' + line.partition('Syntax Error')[2]})
        for ending in ('System Exception', 'Send failed'):
            if all(token in line for token in ('408', 'Operation failed', ending)):
                failures.append({'class': 'ECGateException', 'message': 'Operation Failed'})
        if '402' in line and 'Operation not supported' in line:
            failures.append({'class': 'ECGateException', 'message': 'Operation Not Supported'})
        if failures:
            history.extend(failures)
            state, error = 'error', failures[-1]
        if 'bad object' in line.lower() and state != 'error':
            state = 'completed'
        steps.append({'line': line, 'state': state, 'exception': error})
    return {'responses': lines, 'steps': steps, 'exception_history': history}


class BroadcastResultsEvidenceTests(unittest.TestCase):
    def test_original_case_sensitive_patterns_and_sticky_error_state(self):
        report = json.loads(FIXTURE.read_text())
        self.assertEqual(report['format'], 'cbus-classic-dlt-broadcast-results-original-v1')
        self.assertEqual(len(report['observations']), 25)
        for row in report['observations']:
            with self.subTest(responses=row['responses']):
                self.assertEqual(row, expected(row['responses']))
        indexed = {tuple(row['responses']): row for row in report['observations']}
        for responses in (('200 OKextra',), ('401 BAD OBJECT',)):
            self.assertEqual(indexed[responses]['steps'][-1]['state'], 'completed')
        for responses in ((' 200 OK',), ('402 Operation Not Supported',), ('408 Operation failed',)):
            self.assertEqual(indexed[responses]['steps'][-1]['state'], 'pending')
        self.assertEqual(len(report['observations'][-2]['exception_history']), 4)

    def test_methods_pin_predicates_and_command_adapter(self):
        report = json.loads(FIXTURE.read_text())
        self.assertEqual(len(report['methods']), 14)
        for key, address in (('parser', '0x120d9e0'), ('contains_all', '0x7b78f4'),
                              ('complete', '0x843de4'), ('exception', '0x843e5c')):
            self.assertEqual(report['methods'][key]['start'], address)
        self.assertIn('!OID', report['rules']['target'])
        self.assertIn('Transport framing/timeouts are outside', report['rules']['response_scope'])
        self.assertEqual(report['rules']['timeout_ms']['ordinary'], 20000)
        self.assertEqual(report['rules']['timeout_ms']['DYNAMIC'], 30000)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires pinned original Toolkit EXE/MAP')
class BroadcastResultsReplayTests(unittest.TestCase):
    def test_fresh_original_parser_matches_retained_receipt(self):
        from research.classic_dlt_broadcast_results_original import results_facts
        from research.classic_dlt_controls_original import ClassicControlsProbe
        executable = Path(os.environ['CBUS_TOOLKIT_EXE'])
        symbols = Path(os.environ.get('CBUS_TOOLKIT_MAP', executable.with_suffix('.map')))
        self.assertEqual(results_facts(ClassicControlsProbe(executable, symbols)),
                         json.loads(FIXTURE.read_text()))


if __name__ == '__main__':
    unittest.main()
