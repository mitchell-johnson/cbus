"""Public scheduling dispatch and output failures after confirmed operations."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import unittest
from unittest.mock import patch

from cbus_toolkit.cli import build_parser, main
from tests.test_native_thermostat_schedule import FixtureClient, PATH, existing


COMMAND = ['cgate', 'thermostat-schedule-levels', PATH, '--action', 'Enable', '--exclusive-project']


class Context:
    def __init__(self, peer):
        self.peer = peer
        self.exits = 0

    def __enter__(self):
        return self.peer

    def __exit__(self, typ, error, trace):
        self.exits += 1


class NoExceptionEvidence(KeyboardInterrupt):
    def __getattribute__(self, key):
        if key.endswith('_evidence'):
            raise SystemExit('Hostile evidence getter')
        return super().__getattribute__(key)

    def __setattr__(self, key, value):
        if key.endswith('_evidence'):
            raise SystemExit('Hostile evidence setter')
        super().__setattr__(key, value)


class SchedulingDispatchTests(unittest.TestCase):
    def test_public_parser_and_preview_dispatch(self):
        args = build_parser().parse_args(COMMAND)
        self.assertEqual(args.action, 'thermostat-schedule-levels')
        self.assertEqual(args.schedule_action, 'Enable')
        self.assertFalse(args.apply)
        peer = FixtureClient(existing((0, 1, 32, 255)))
        context = Context(peer)
        output, errors = io.StringIO(), io.StringIO()
        with patch('cbus_toolkit.cgate.CGateClient', return_value=context), redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main(COMMAND), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['created_addresses'], list(range(2, 32)))
        self.assertFalse(result['native_mutation_performed'])
        self.assertEqual(errors.getvalue(), '')
        self.assertEqual(context.exits, 1)
        self.assertTrue(all(command.startswith(('DBGETXML ', 'GET ')) for command in peer.commands))

    def test_interrupt_payload_avoids_unrelated_hostile_exception_getters(self):
        peer = FixtureClient(existing((1,)))
        first = NoExceptionEvidence('native interruption')
        peer.failure = lambda command: first if command.startswith('DBSETSAFE !') and '/Value ' in command else None
        context = Context(peer)
        output, errors = io.StringIO(), io.StringIO()
        with patch('cbus_toolkit.cgate.CGateClient', return_value=context), redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main(COMMAND + ['--apply', '--backup-project', 'BACKUP']), 130)
        evidence = json.loads(errors.getvalue())['thermostat_schedule_evidence']
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(evidence['phase'], 'apply')
        self.assertTrue(evidence['native_result']['backup_created'])
        self.assertTrue(evidence['native_result']['levels'][0]['created'])
        self.assertFalse(evidence['native_result']['target_save_confirmed'])
        self.assertEqual(context.exits, 1)

    def test_output_failure_preserves_confirmed_save_and_first_error(self):
        for first, expected in ((BrokenPipeError('output pipe'), 1), (NoExceptionEvidence('output interrupt'), 130)):
            with self.subTest(first=type(first).__name__):
                peer = FixtureClient(existing((1,)))
                context = Context(peer)
                class Output:
                    def write(self, text):
                        raise first
                    def flush(self):
                        pass
                errors = io.StringIO()
                with patch('cbus_toolkit.cgate.CGateClient', return_value=context), redirect_stdout(Output()), redirect_stderr(errors):
                    self.assertEqual(main(COMMAND + ['--apply', '--backup-project', 'BACKUP']), expected)
                evidence = json.loads(errors.getvalue())['thermostat_schedule_evidence']
                self.assertFalse(evidence['complete'])
                self.assertEqual(evidence['phase'], 'output')
                self.assertTrue(evidence['native_operation_completed'])
                self.assertTrue(evidence['native_result']['target_save_confirmed'])
                self.assertTrue(evidence['native_result']['persistence_verified'])
                self.assertEqual(context.exits, 1)
                self.assertEqual(peer.commands.count('PROJECT SAVE TEST'), 2)
                self.assertEqual(len(peer.saved), 31)
