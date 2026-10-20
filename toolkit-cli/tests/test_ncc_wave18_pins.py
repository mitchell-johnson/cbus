"""Offline P10.01 wave-18 pins: NCC guards with zero prior test references.

Pure offline: caller-supplied transcript bytes only. No hardware, transport,
timing, subprocess, or firmware execution. Advances #64 without touching
``rust/``, commissioning, or the parity register. Each test pins a guard
literal that has no prior reference in ``toolkit-cli/tests/*.py``:

* ``nu`` progress responses with more than 256 distinct trimmed lines are
  refused (exact 256 still admitted).
* a post-update embedded version that differs from the pre-update target
  pins ``ncc-versions-after-update:embedded-target-changed-or-invalid``
  while native success is preserved.
* a failed post-restart identification pins
  ``identify-after-restart:failed`` under ``reported-success-manual-restart``.
* a mismatched post-restart identity pins both
  ``identify-after-restart:identity-not-matched`` and
  ``identify-after-restart:firmware-version-mismatch``.
"""

from __future__ import annotations

import unittest

from cbus_toolkit.firmware_ncc import evaluate_ncc_post_check

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


def filler_progress(extra):
    """PROGRESS keys plus ``extra`` distinct lines sharing one parser key."""
    lines = [b'Updating NCC Firmware..', b'Update Started', b'Update Complete']
    lines += [f'k : filler-{i:03d}'.encode() for i in range(extra)]
    return b'\r\n'.join(lines) + b'\r\n'


class NCCWave18Pins(unittest.TestCase):
    def test_progress_beyond_256_distinct_lines_refused_at_boundary(self):
        """P10.01: >256 distinct trimmed ``nu`` lines refused; 256 admitted."""
        with self.assertRaisesRegex(ValueError, '256 distinct lines'):
            evaluate_ncc_post_check('1.7.0', prefix() + [exchange('nu', filler_progress(254))])
        result = evaluate_ncc_post_check('1.7.0', prefix() + [exchange('nu', filler_progress(253))])
        self.assertEqual(result['next_step']['step'], 'ncc-versions-after-update')
        self.assertEqual(result['steps'][-1]['progress_keys_present'],
                         ['Updating NCC Firmware..', 'Update Started', 'Update Complete'])

    def test_changed_embedded_target_pins_gap_without_native_failure(self):
        """P10.01: post-update embedded drift keeps native success, pins gap."""
        result = evaluate_ncc_post_check(
            '1.7.0', prefix() + [exchange('nu', PROGRESS),
                                 exchange('nv', nv('1.1.0', '1.2.0'))])
        self.assertTrue(result['native_success'])
        self.assertEqual(result['status'], 'native-success-with-verification-gaps')
        self.assertTrue(result['checks']['post_update_current_matches_target'])
        self.assertFalse(result['checks']['embedded_target_unchanged'])
        self.assertIn('ncc-versions-after-update:embedded-target-changed-or-invalid',
                      result['verification_gaps'])
        self.assertFalse(result['checks']['restart_required'])
        self.assertIsNone(result['next_step'])

    def test_failed_restart_identification_pins_manual_restart_gap(self):
        """P10.01: timed-out post-restart read pins the manual-restart gap."""
        rows = (updated('0.0.0') + [exchange('rs', outcome='write-ok'),
                                    exchange('id', outcome='timeout')])
        result = evaluate_ncc_post_check('1.7.0', rows)
        self.assertEqual(result['native_outcome'], 'reported-success-manual-restart')
        self.assertTrue(result['native_success'])
        self.assertEqual(result['reason'], 'identify-after-restart:timeout')
        self.assertIn('restart:no-final-ncc-version-read-in-original',
                      result['verification_gaps'])
        self.assertIn('identify-after-restart:failed', result['verification_gaps'])
        self.assertFalse(result['transcript_checks_passed'])

    def test_mismatched_restart_identity_pins_both_restart_gaps(self):
        """P10.01: altered serial+firmware after restart pins both gaps."""
        altered = ID.replace(b'PRIVATE-SERIAL', b'OTHER-SERIAL').replace(b'1.7.0', b'1.6.0')
        rows = updated('0.0.0') + [exchange('rs', outcome='write-ok'), exchange('id', altered)]
        result = evaluate_ncc_post_check('1.7.0', rows)
        self.assertTrue(result['native_success'])
        self.assertFalse(result['checks']['restart_identity_matches'])
        self.assertFalse(result['checks']['restart_firmware_version_exact'])
        self.assertIn('identify-after-restart:identity-not-matched',
                      result['verification_gaps'])
        self.assertIn('identify-after-restart:firmware-version-mismatch',
                      result['verification_gaps'])
        self.assertFalse(result['transcript_checks_passed'])


if __name__ == '__main__':
    unittest.main()
