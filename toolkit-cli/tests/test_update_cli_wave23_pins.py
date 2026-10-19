"""Wave23 offline pins for firmware_update_cli guards with zero prior refs.

Offline only: no USB backend, no hardware, no journal I/O (missing path or
patched loader). Pins derived dataclass guards, unsupported inventory,
strict scalar guards, and the export-failure fallback.
"""
from __future__ import annotations

import json
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cbus_toolkit.firmware_update_cli import error_payload


def _args(journal, action='update-run'):
    return Namespace(area='firmware', action=action, journal=journal)


class Wave23CliPins(unittest.TestCase):
    def test_exact_dataclass_projects_derived_guards_with_labels(self):
        from cbus_toolkit.usb_dfu import USBReleaseOutcome
        with TemporaryDirectory() as tmp:
            args = _args(Path(tmp) / 'missing-journal')
            outcome = USBReleaseOutcome(
                complete=False, release_policy='reset-first-alternate',
                claim_attempted=True, claimed_before_release=False,
                release_attempted=True, release_succeeded=False,
                release_error='SECRET-PASSWORD-PATH', close_attempted=True,
                close_succeeded=True, close_error=None,
                elapsed_seconds=1.25, timing_error=None)
            error = RuntimeError('primary stays')
            error.usb_release = outcome
            result = error_payload(error, args)
            release = result['usb_release']
            self.assertFalse(release['complete'])
            self.assertEqual(release['release_error'], 'USB release failed')
            self.assertTrue(release['implicit_set_interface_possible'])
            self.assertTrue(release['state_after_release_unknown'])
            self.assertFalse(release['deadline_bounded'])
            self.assertEqual(release['elapsed_seconds'], 1.25)
            self.assertNotIn('SECRET-PASSWORD-PATH', json.dumps(result))
            # Lifecycle row is still emitted but never authorizes replay.
            evidence = result['firmware_update_evidence']
            self.assertFalse(evidence['complete'])
            self.assertFalse(evidence['physical_device_verified'])
            self.assertFalse(evidence['replay_authorized'])

    def test_unsupported_stage_inventory_never_replays(self):
        with TemporaryDirectory() as tmp:
            args = _args(Path(tmp) / 'journal')
            error = RuntimeError('primary')
            error.firmware_update_evidence = {'operation': 'program', 'stage': 'main'}
            bad_docs = (
                {'status': 'interrupted',
                 'stages': {'font': 'verified', 'main': 'verified', 'extra': 'verified'}},
                {'status': 'interrupted',
                 'stages': {'font': 'verified', 'oops': 'verified'}},
            )
            for doc in bad_docs:
                with self.subTest(stages=sorted(doc['stages'])):
                    with patch('cbus_toolkit.firmware_update_run.load_journal',
                               return_value=(doc, None)):
                        evidence = error_payload(error, args)['firmware_update_evidence']
                        self.assertFalse(evidence['journal']['snapshot_available'])
                        self.assertTrue(evidence['journal']['snapshot_only'])
                        self.assertFalse(evidence['replay_authorized'])
                        self.assertFalse(evidence['complete'])
                        self.assertFalse(evidence['physical_device_verified'])

    def test_strict_scalars_keep_valid_elapsed_drop_bool_as_int(self):
        with TemporaryDirectory() as tmp:
            args = _args(Path(tmp) / 'missing')
            error = RuntimeError('primary')
            error.firmware_update_evidence = {
                'operation': 'program', 'stage': 'main',
                'transfer': {'complete': True, 'operation': 'program', 'stage': 'complete',
                             'address': True, 'payload_transferred': 5,
                             'first_mismatch': None},
                'release': {'complete': 1, 'release_attempted': True,
                            'release_policy': 'reset-first-alternate',
                            'elapsed_seconds': 1.5},
            }
            evidence = error_payload(error, args)['firmware_update_evidence']
            # type(x) is int excludes bool; type(x) is bool excludes int 1.
            self.assertNotIn('address', evidence['transfer'])
            self.assertEqual(evidence['transfer']['payload_transferred'], 5)
            self.assertIsNone(evidence['transfer']['first_mismatch'])
            self.assertNotIn('complete', evidence['release'])
            self.assertTrue(evidence['release']['release_attempted'])
            self.assertEqual(evidence['release']['elapsed_seconds'], 1.5)

    def test_export_failure_fallback_never_masks_unmatched(self):
        with TemporaryDirectory() as tmp:
            args = _args(Path(tmp) / 'missing')
            matched = RuntimeError('primary')
            matched.firmware_update_evidence = {'operation': 'program', 'stage': 'main'}
            with patch('cbus_toolkit.firmware_update_cli._transfer',
                       side_effect=RuntimeError('boom')):
                result = error_payload(matched, args)
            self.assertFalse(result['firmware_update_evidence']['complete'])
            self.assertTrue(result['firmware_update_evidence']['evidence_export_failed'])
            self.assertFalse(result['firmware_update_evidence']['physical_device_verified'])
            self.assertFalse(result['firmware_update_evidence']['replay_authorized'])
            # Unmatched errors stay silent even when the exporter itself fails.
            with patch('cbus_toolkit.firmware_update_cli._transfer',
                       side_effect=RuntimeError('boom')):
                self.assertEqual(error_payload(RuntimeError('plain'), args), {})
            # Bare namespace without area/action never exports.
            self.assertEqual(error_payload(matched, Namespace()), {})


if __name__ == '__main__':
    unittest.main()
