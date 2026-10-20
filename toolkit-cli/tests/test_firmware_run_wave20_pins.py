"""Wave20 offline pins for firmware run guards (P10).

Narrow scope: only ``cbus_toolkit.firmware_update_run``. No hardware,
network, broker, vendor archives, passwords, or fixture ZIPs. Synthetic
plans and images only. Pins run guards with zero prior test refs
(verified 2026-10-16 via ``grep -rn`` over ``tests/`` for the
run-qualified symbols and exact literals below):

* envelope constants ``JOURNAL_FORMAT`` / ``RESULT_FORMAT`` /
  ``PLAN_FORMAT``, ``PHASES`` / ``STATUSES`` / ``EVENTS``,
  ``APPLICATION_START_VARIANTS``, ``STAGE_STATES``
* pure helpers ``descriptor_identity`` and ``_release_error``
  (run-qualified; the bare ``descriptor_identity`` name appears once for
  an unrelated update-package-bundle test)
* ``plan_stages`` refusals before any I/O (``plan`` / ``geometry`` /
  ``image``) and the success shape (main erase 1024-byte rounding, font
  erase passthrough, sha256 binding, flash-bounds refusal)
* refusal result envelope (never retried, no resume, mode/target/post
  literals, offline scope, ``physical_device_verified`` False)
"""

from __future__ import annotations

import hashlib
import struct
import unittest
from types import SimpleNamespace

from cbus_toolkit import firmware_update_run as run

FLASH = 262144
EXTERNAL = 131072
ADDRESS = 0x4000


def main_image(size, address=ADDRESS):
    """Synthetic main image whose reset handler lies inside the image."""
    reset = (address + 8) | 1  # thumb handler inside the image
    return struct.pack('<II', 0x20001000, reset) + bytes(size - 8)


def main_plan(entry='main.bin', nbytes=1024, address='0x4000',
              variant='TivaPCI', supported=True, steps=None):
    return {'format': run.PLAN_FORMAT, 'supported': supported,
            'issues': [] if supported else ['synthetic unsupported'],
            'variant': variant, 'main_address': address,
            'dfuprog_steps': (steps if steps is not None
                              else [{'step': 'main-write', 'entry': entry,
                                     'bytes': nbytes}])}


def font_steps(font_bytes=100, main_bytes=1024, font_erase=EXTERNAL):
    return [{'step': 'font-erase', 'length': font_erase},
            {'step': 'font-write', 'entry': 'font.bin', 'bytes': font_bytes},
            {'step': 'main-write', 'entry': 'main.bin', 'bytes': main_bytes}]


class NeverOpen:
    """Opener that proves plan refusal precedes any device access."""

    def __init__(self):
        self.opens = 0

    def open(self):  # pragma: no cover - must never be called
        self.opens += 1
        raise AssertionError('plan refusal must precede any device open')


class FirmwareRunWave20PinsTests(unittest.TestCase):
    def test_wave20_run_envelope_constants(self):
        self.assertEqual(run.JOURNAL_FORMAT,
                         'cbus-edlt-firmware-update-journal-v1')
        self.assertEqual(run.RESULT_FORMAT, 'cbus-edlt-firmware-update-run-v1')
        self.assertEqual(run.PLAN_FORMAT, 'cbus-edlt-firmware-update-plan-v1')
        self.assertEqual(run.PHASES,
                         ('pending', 'erase-sent', 'erased', 'write-sent',
                          'verified'))
        self.assertEqual(run.STATUSES,
                         ('in-progress', 'interrupted', 'failed', 'complete'))
        self.assertIn('journal-created', run.EVENTS)
        self.assertIn('run-complete', run.EVENTS)
        self.assertIn('resume-refused', run.EVENTS)
        self.assertEqual(run.APPLICATION_START_VARIANTS,
                         {0x2000: ('StellarisPCI',),
                          0x4000: ('TivaPCI', 'TivaNCC')})
        self.assertEqual(run.STAGE_STATES['pending'],
                         'untouched by this journal')
        self.assertEqual(run.STAGE_STATES['erase-sent'],
                         'unknown: erase may be partial')
        self.assertEqual(run.STAGE_STATES['write-sent'],
                         'unknown: image may be partial or unverified')
        self.assertEqual(run.STAGE_STATES['verified'],
                         'image read back byte-for-byte')
        self.assertEqual(set(run.STAGE_STATES), set(run.PHASES))

    def test_wave20_pure_identity_and_release_helpers(self):
        descriptor = SimpleNamespace(device_descriptor=b'\x12\x01 suatu',
                                     configuration_descriptor=b'\x09\x02 cfg')
        identity = run.descriptor_identity(descriptor, 'ABC123')
        self.assertEqual(identity['usb_serial'], 'ABC123')
        self.assertEqual(identity['device_descriptor_sha256'],
                         hashlib.sha256(b'\x12\x01 suatu').hexdigest())
        self.assertEqual(identity['configuration_descriptor_sha256'],
                         hashlib.sha256(b'\x09\x02 cfg').hexdigest())
        self.assertEqual(identity,
                         run.descriptor_identity(descriptor, 'ABC123'))
        self.assertNotEqual(identity['device_descriptor_sha256'],
                            identity['configuration_descriptor_sha256'])
        self.assertNotEqual(
            identity, run.descriptor_identity(descriptor, 'OTHER1'))
        self.assertIsNone(run._release_error(None))
        self.assertIsNone(run._release_error({'complete': True}))
        self.assertEqual(run._release_error({'complete': False, 'error': 'x'}),
                         'x')
        self.assertEqual(run._release_error({'complete': False,
                                             'release_error': 'a',
                                             'close_error': 'b'}), 'a; b')
        self.assertEqual(run._release_error({'complete': False}),
                         'USB session release did not complete')

    def test_wave20_plan_stages_refuse_before_any_io(self):
        # The run_update envelope path reads plan['main_address' ] for its
        # bookkeeping, so the wrong-format plan carries that key; plan_stages
        # itself refuses before touching it.
        cases = [
            ({'format': 'not-a-plan', 'main_address': '0x4000'}, {}, EXTERNAL,
             'plan', 'cbus-edlt-firmware-update-plan-v1 plan is required'),
            (main_plan(supported=False), {}, EXTERNAL,
             'plan', 'Only a supported plan can be executed'),
            (main_plan(steps=font_steps()), {'font.bin': b'\0' * 100,
                                             'main.bin': main_image(1024)},
             None, 'geometry',
             'The font stage requires an explicit external flash size'),
            (main_plan(), {}, EXTERNAL,
             'image', 'is missing or differs from the plan'),
        ]
        for faulty_plan, images, external, kind, fragment in cases:
            with self.subTest(kind=kind, fragment=fragment):
                opener = NeverOpen()
                with self.assertRaises(run._Refusal) as caught:
                    run.plan_stages(faulty_plan, images, flash_size=FLASH,
                                    external_size=external)
                self.assertEqual(caught.exception.kind, kind)
                self.assertIn(fragment, str(caught.exception))
                import tempfile
                from pathlib import Path
                with tempfile.TemporaryDirectory() as directory:
                    journal = Path(directory, 'update.journal')
                    result = run.run_update(faulty_plan, images, opener=opener,
                                            journal_path=journal,
                                            flash_size=FLASH,
                                            external_size=external)
                    self.assertTrue(result['refused'])
                    self.assertEqual(result['refusal_kind'], kind)
                    self.assertIn(fragment, result['error'])
                    self.assertEqual(opener.opens, 0)
                    self.assertFalse(result['journal_created'])
                    self.assertFalse(journal.exists())
                    self.assertFalse(result['complete'])
                    self.assertFalse(result['retried'])
                    self.assertFalse(result['resume_required'])
                    self.assertIsNone(result['next_action'])
                    self.assertFalse(result['physical_device_verified'])
                    self.assertEqual(result['mode_switch'],
                                     'not sent: the device must already be '
                                     'in DFU mode')
                    self.assertEqual(result['target_reset'], 'not sent')
                    self.assertEqual(result['post_check'], 'not executed')
                    self.assertIn('Journaled stage execution',
                                  result['scope'])
                    self.assertIn('hardware acceptance is not established',
                                  result['scope'])

    def test_wave20_plan_stages_success_shape_and_bounds(self):
        for size, rounded in ((1000, 1024), (1024, 1024), (1025, 2048)):
            with self.subTest(size=size):
                data = main_image(size)
                stages = run.plan_stages(main_plan(nbytes=size),
                                         {'main.bin': data}, flash_size=FLASH,
                                         external_size=None)
                self.assertEqual(len(stages), 1)
                stage = stages[0]
                self.assertEqual(stage['name'], 'main')
                self.assertFalse(stage['external'])
                self.assertEqual(stage['erase_address'], ADDRESS)
                self.assertEqual(stage['erase_length'], rounded)
                self.assertEqual(stage['address'], ADDRESS)
                self.assertEqual(stage['bytes'], size)
                self.assertEqual(stage['sha256'],
                                 hashlib.sha256(data).hexdigest())
        font_data, main_data = b'\0' * 100, main_image(1024)
        stages = run.plan_stages(main_plan(steps=font_steps()),
                                 {'font.bin': font_data,
                                  'main.bin': main_data}, flash_size=FLASH,
                                 external_size=EXTERNAL)
        self.assertEqual([stage['name'] for stage in stages], ['font', 'main'])
        self.assertTrue(stages[0]['external'])
        self.assertEqual((stages[0]['erase_address'],
                          stages[0]['erase_length']), (0, EXTERNAL))
        oversized = main_plan()
        with self.assertRaises(run._Refusal) as caught:
            run.plan_stages(oversized, {'main.bin': main_image(1024)},
                            flash_size=ADDRESS + 512, external_size=None)
        self.assertEqual(caught.exception.kind, 'geometry')
        self.assertIn('does not fit the explicit flash bounds',
                      str(caught.exception))
        opener = NeverOpen()
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory, 'update.journal')
            result = run.run_update(oversized, {'main.bin': main_image(1024)},
                                    opener=opener, journal_path=journal,
                                    flash_size=ADDRESS + 512,
                                    external_size=None)
            self.assertEqual(result['refusal_kind'], 'geometry')
            self.assertEqual(opener.opens, 0)
            self.assertFalse(journal.exists())


if __name__ == '__main__':
    unittest.main()
