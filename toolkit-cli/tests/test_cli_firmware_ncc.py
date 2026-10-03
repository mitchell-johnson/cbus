"""Public offline NCC transcript CLI admission and model interoperability."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from cbus_toolkit.firmware_ncc import evaluate_ncc_post_check
from cbus_toolkit.firmware_ncc_cli import INPUT_FORMAT, MAX_INPUT_BYTES, read_exchanges


IDENTITY = (b'Manufacturer=Clipsal\r\nProduct=eDLT\r\nSerial Number=CLI-PRIVATE-SERIAL-717171\r\n'
            b'HW Version=3.0 (Tiva + NCC)\r\nFW Version=1.7.0\r\n'
            b'CPU Speed=120\r\nUnit Address=20\r\nPrivate Note=CLI-PRIVATE-NOTE-818181\r\n')
PROGRESS = b'Updating NCC Firmware..\r\nUpdate Started\r\nUpdate Complete\r\n'


def versions(current='1.0.0', embedded='1.1.0'):
    return (f'NCC current version: {current}\r\nNCC embedded version: {embedded}\r\n').encode()


def row(command, response=b'', outcome=None):
    result = {'command': command, 'response_hex': response.hex()}
    if outcome is not None:
        result['outcome'] = outcome
    return result


def prefix(current='1.0.0'):
    return [row('id', IDENTITY), row('nv', versions(current))]


def updated(current='1.1.0'):
    return prefix() + [row('nu', PROGRESS), row('nv', versions(current))]


def envelope(rows):
    return {'format': INPUT_FORMAT, 'exchanges': rows}


class FirmwareNCCCLITest(unittest.TestCase):
    def command(self, *args, status, env=None, timeout=10):
        process = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                                 capture_output=True, text=True, timeout=timeout, env=env)
        self.assertEqual(process.returncode, status, process.stdout + process.stderr)
        return process

    def cli(self, file=None, *, status=1, version='1.7.0', compact=False, env=None, timeout=10):
        args = ['--compact'] if compact else []
        args += ['firmware', 'ncc-transcript']
        if file is not None:
            args.append(file)
        args += ['--expected-version', version]
        process = self.command(*args, status=status, env=env, timeout=timeout)
        if process.stdout:
            self.assertEqual(process.stderr, '')
            if compact:
                self.assertEqual(len(process.stdout.splitlines()), 1)
            result = json.loads(process.stdout)
        else:
            result = json.loads(process.stderr)
        return result

    def write(self, directory, rows):
        path = Path(directory) / 'transcript.json'
        path.write_text(json.dumps(envelope(rows)), encoding='utf-8')
        return path

    def assert_model(self, result, rows):
        exchanges = [{'command': item['command'], 'response': bytes.fromhex(item.get('response_hex', '')),
                      'outcome': item.get('outcome', 'response')} for item in rows]
        self.assertEqual(result, evaluate_ncc_post_check('1.7.0', exchanges))

    def assert_error(self, result):
        self.assertEqual(set(result), {'error', 'type'})
        self.assertEqual(result['type'], 'ValueError')
        self.assertNotIn('CLI-PRIVATE', json.dumps(result))

    def test_public_help_empty_prefix_and_argument_status(self):
        help_text = self.command('firmware', 'ncc-transcript', '--help', status=0).stdout
        self.assertIn('--expected-version', help_text)
        self.assertIn('file', help_text)
        self.command('firmware', 'ncc-transcript', status=2)
        result = self.cli(compact=True)
        self.assertEqual(result['status'], 'awaiting-transcript')
        self.assertEqual(result['next_step']['request_hex'], '69640d')
        self.assertEqual(result['next_step']['delay_before_ms'], 10000)
        self.assertFalse(result['next_step']['execution_supported'])
        self.assertFalse(result['transcript_checks_passed'])
        self.assert_model(result, [])

    def test_each_supplied_prefix_reports_the_same_next_original_step(self):
        rows = updated('0.0.0') + [row('rs', outcome='write-ok'), row('id', IDENTITY)]
        commands = ['id', 'nv', 'nu', 'nv', 'rs', 'id']
        with tempfile.TemporaryDirectory() as directory:
            for index, command in enumerate(commands):
                with self.subTest(index=index):
                    result = self.cli(self.write(directory, rows[:index]))
                    self.assertEqual(result['status'], 'awaiting-transcript')
                    self.assertEqual(result['next_step']['command'], command)
                    self.assert_model(result, rows[:index])

    def test_same_or_newer_current_versions_pass_without_update_and_sanitize(self):
        with tempfile.TemporaryDirectory() as directory:
            for current in ('1.1.0', '2.0'):
                with self.subTest(current=current):
                    rows = prefix(current)
                    rows[0]['response_hex'] = rows[0]['response_hex'].upper()
                    result = self.cli(self.write(directory, rows), status=0, compact=True)
                    self.assertEqual(result['status'], 'transcript-checks-passed')
                    self.assertEqual([step['command'] for step in result['steps']], ['id', 'nv'])
                    self.assertFalse(result['checks']['ncc_update_required'])
                    self.assert_model(result, rows)
                    output = json.dumps(result)
                    for private in ('CLI-PRIVATE', 'Serial Number', 'Private Note', directory, 'response_hex'):
                        self.assertNotIn(private, output)
                    self.assertEqual(result['commands_sent'], 0)
                    for flag in ('hardware_accessed', 'native_execution', 'physical_acceptance',
                                 'firmware_contents_verified', 'destructive_execution_supported',
                                 'timing_modelled', 'raw_responses_reported'):
                        self.assertIs(result[flag], False)

    def test_completed_update_keeps_exact_response_bytes_and_original_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = updated()
            result = self.cli(self.write(directory, rows), status=0)
            self.assert_model(result, rows)
            self.assertEqual([step['command'] for step in result['steps']], ['id', 'nv', 'nu', 'nv'])
            self.assertTrue(result['checks']['post_update_current_matches_target'])
            self.assertFalse(result['checks']['restart_required'])
            self.assertEqual(result['steps'][0]['response_sha256'], hashlib.sha256(IDENTITY).hexdigest())
            self.assertEqual(result['steps'][0]['response_bytes'], len(IDENTITY))
            self.assertTrue(result['steps'][2]['would_mutate_device'])
            self.assertFalse(result['steps'][2]['execution_supported'])

    def test_failed_outcomes_retain_partial_bytes_without_parsing_and_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            for outcome in ('timeout', 'io-error'):
                with self.subTest(outcome=outcome):
                    partial = b'CLI-PRIVATE-PARTIAL\x00\xff'
                    rows = [row('id', partial, outcome)]
                    result = self.cli(self.write(directory, rows))
                    self.assertEqual(result['status'], 'native-failure')
                    self.assertEqual(result['reason'], 'identify:' + outcome)
                    self.assertEqual(result['steps'][0]['response_sha256'], hashlib.sha256(partial).hexdigest())
                    self.assert_model(result, rows)
                    self.assertNotIn('CLI-PRIVATE', json.dumps(result))
            rows = [row('id', IDENTITY.replace(b'1.7.0', b'1.7.0.0'))]
            result = self.cli(self.write(directory, rows))
            self.assertEqual(result['reason'], 'identify:firmware-version-mismatch')
            self.assertFalse(result['native_success'])

    def test_native_success_with_unconfirmed_target_is_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = updated('1.0.0')
            result = self.cli(self.write(directory, rows))
            self.assertEqual(result['status'], 'native-success-with-verification-gaps')
            self.assertTrue(result['native_success'])
            self.assertFalse(result['transcript_checks_passed'])
            self.assertIn('ncc-versions-after-update:target-not-confirmed', result['verification_gaps'])
            self.assert_model(result, rows)

    def test_restart_ack_and_manual_restart_gaps_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            for final in (row('id', IDENTITY), row('id', outcome='timeout')):
                with self.subTest(final=final.get('outcome')):
                    rows = updated('0.0.0') + [row('rs', outcome='write-ok'), final]
                    result = self.cli(self.write(directory, rows))
                    self.assertTrue(result['native_success'])
                    self.assertFalse(result['steps'][4]['acknowledged'])
                    self.assertIn('restart:no-final-ncc-version-read-in-original', result['verification_gaps'])
                    self.assert_model(result, rows)
                    if final.get('outcome') == 'timeout':
                        self.assertEqual(result['native_outcome'], 'reported-success-manual-restart')

    def test_exact_schema_and_command_outcome_admission(self):
        invalid = [[], {}, {'format': INPUT_FORMAT, 'exchanges': [], 'CLI-PRIVATE-KEY': True},
                   {'format': 'wrong', 'exchanges': []}, {'format': INPUT_FORMAT, 'exchanges': {}},
                   envelope([row('id')] * 7), envelope([[]]), envelope([{}]),
                   envelope([{'command': 'id', 'response': 'CLI-PRIVATE-RESPONSE'}]),
                   envelope([{'command': 'id', 'CLI-PRIVATE-FIELD': 'CLI-PRIVATE-VALUE'}]),
                   envelope([{'command': 'CLI-PRIVATE-COMMAND'}]),
                   envelope([{'command': True}]), envelope([{'command': 'id', 'outcome': True}]),
                   envelope([{'command': 'id', 'outcome': 'write-ok'}]),
                   envelope([{'command': 'id', 'outcome': 'CLI-PRIVATE-OUTCOME'}])]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'transcript.json'
            for document in invalid:
                with self.subTest(document=document):
                    path.write_text(json.dumps(document), encoding='utf-8')
                    self.assert_error(self.cli(path))
            for restart in ({'command': 'rs'}, row('rs', b'ACK\r\n', 'write-ok'),
                            row('rs', outcome='response')):
                with self.subTest(restart=restart):
                    self.assert_error(self.cli(self.write(directory, updated('0.0.0') + [restart])))

    def test_hex_bounds_ascii_profile_and_no_whitespace(self):
        with tempfile.TemporaryDirectory() as directory:
            for hexadecimal in ('0', 'gg', '69 64', '69\n64', 'é0', ['69'], 69, None, '00' * 65537):
                with self.subTest(hexadecimal_type=type(hexadecimal).__name__, length=len(hexadecimal)
                                  if isinstance(hexadecimal, (str, list)) else None):
                    self.assert_error(self.cli(self.write(directory, [{'command': 'id', 'response_hex': hexadecimal}])))
            for response in (b'CLI-PRIVATE\xff\r\n', b'CLI-PRIVATE\x00\r\n'):
                self.assert_error(self.cli(self.write(directory, [row('id', response)])))
            rows = [row('id', b'A' * 65536, 'timeout')]
            result = self.cli(self.write(directory, rows))
            self.assertEqual(result['reason'], 'identify:timeout')
            self.assertEqual(result['steps'][0]['response_bytes'], 65536)

    def test_json_refusals_are_sanitized_and_input_file_limit_is_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'CLI-PRIVATE-PATH.json'
            invalid = [b'\xff', b'\xef\xbb\xbf' + json.dumps(envelope([])).encode(), b'{',
                       b'{"format":"' + INPUT_FORMAT.encode() + b'","exchanges":[],"CLI-PRIVATE":1,"CLI-PRIVATE":2}',
                       b'{"format":"' + INPUT_FORMAT.encode() + b'","exchanges":[{"command":"id","command":"CLI-PRIVATE"}]}',
                       b'{"format":"' + INPUT_FORMAT.encode() + b'","exchanges":NaN}',
                       b'{"format":"' + INPUT_FORMAT.encode() + b'","exchanges":Infinity}',
                       b'[' * 1500 + b']' * 1500]
            for raw in invalid:
                with self.subTest(length=len(raw)):
                    path.write_bytes(raw)
                    self.assert_error(self.cli(path))
            raw = json.dumps(envelope([])).encode()
            path.write_bytes(raw + b' ' * (MAX_INPUT_BYTES - len(raw)))
            self.assertEqual(self.cli(path)['status'], 'awaiting-transcript')
            path.write_bytes(raw + b' ' * (MAX_INPUT_BYTES + 1 - len(raw)))
            result = self.cli(path)
            self.assert_error(result)
            self.assertIn('1 MiB', result['error'])

    def test_missing_nonregular_files_and_symlink_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for path in (directory, directory / 'CLI-PRIVATE-MISSING.json'):
                result = self.cli(path)
                self.assert_error(result)
                self.assertNotIn(str(directory), json.dumps(result))
            if hasattr(os, 'mkfifo'):
                fifo = directory / 'CLI-PRIVATE-FIFO'
                os.mkfifo(fifo)
                self.assert_error(self.cli(fifo, timeout=3))
            if hasattr(os, 'symlink'):
                path = self.write(directory, prefix('1.1.0'))
                link = directory / 'link.json'
                try:
                    link.symlink_to(path)
                except OSError:
                    pass  # Hosts may require elevated privileges for symlinks.
                else:
                    self.assertEqual(self.cli(link, status=0)['status'], 'transcript-checks-passed')

    def test_nonregular_device_path_is_rejected_before_any_open(self):
        info = os.stat_result((stat.S_IFCHR | 0o600, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        with mock.patch('cbus_toolkit.firmware_ncc_cli.os.stat', return_value=info), \
                mock.patch('cbus_toolkit.firmware_ncc_cli.os.open') as open_file:
            with self.assertRaisesRegex(ValueError, 'regular file'):
                read_exchanges(Path('explicit-mocked-device'))
            open_file.assert_not_called()

    def test_wrong_order_extra_terminal_rows_and_expected_version_grammar(self):
        with tempfile.TemporaryDirectory() as directory:
            for rows in ([row('nv', versions())], prefix('1.1.0') + [row('nu', PROGRESS)],
                         [row('id', outcome='timeout'), row('nv', versions())]):
                with self.subTest(rows=len(rows)):
                    self.assert_error(self.cli(self.write(directory, rows)))
        for version in ('', 'A' * 129, 'CLI-PRIVATE\nVERSION', 'é'):
            self.assert_error(self.cli(version=version))
        for version in ('A' * 128, 'literal printable version'):
            result = self.cli(version=version)
            self.assertEqual(result['status'], 'awaiting-transcript')
            self.assertEqual(result['expected_firmware_version_sha256'], hashlib.sha256(version.encode()).hexdigest())
            self.assertNotIn(version, json.dumps(result))

    def test_offline_command_runs_with_transports_timing_and_child_execution_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            guard = directory / 'sitecustomize.py'
            guard.write_text('''import builtins, socket, subprocess, time
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == 'serial' or name.startswith('serial.') or name == 'usb' or name.startswith('usb.'):
        raise AssertionError('Offline transcript imported a device backend')
    return original_import(name, *args, **kwargs)
def forbidden(*args, **kwargs):
    raise AssertionError('Offline transcript attempted transport, timing or child execution')
class BlockedSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        return forbidden(*args, **kwargs)
builtins.__import__ = guarded_import
socket.socket = BlockedSocket
socket.create_connection = forbidden
time.sleep = forbidden
subprocess.Popen = forbidden
''', encoding='utf-8')
            environment = dict(os.environ)
            environment['PYTHONPATH'] = str(directory) + os.pathsep + environment.get('PYTHONPATH', '')
            result = self.cli(self.write(directory, updated()), status=0, env=environment)
            self.assertEqual(result['commands_sent'], 0)
            self.assertTrue(result['transcript_checks_passed'])
            rows = updated('0.0.0') + [row('rs', outcome='write-ok'), row('id', IDENTITY)]
            result = self.cli(self.write(directory, rows), env=environment)
            self.assertFalse(result['destructive_execution_supported'])
            self.assertEqual(result['native_outcome'], 'reported-success')


if __name__ == '__main__':
    unittest.main()
