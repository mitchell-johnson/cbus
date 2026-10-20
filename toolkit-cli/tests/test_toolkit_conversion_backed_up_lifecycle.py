"""Focused backed-up KEY1 -> KEY2 lifecycle vectors for P5.06.

Pure helpers in toolkit_conversion_input_unit only; no vendor files,
no C-Gate I/O, no other conversion families. All literals below are
transcribed expectations, not outputs of the helpers under test.
"""
import unittest

from cbus_toolkit.toolkit_conversion_input_unit import (
    BACKED_UP_EXACT_FIELDS,
    BACKED_UP_FORMAT,
    BACKED_UP_JOURNAL_STAGES,
    lifecycle_plan,
    recover_from_journal,
    require_backup_snapshot,
    require_exact_metadata,
    validate_backed_up_pair,
    validate_readdress,
    verify_save_reopen,
)


# Literal source snapshot for the single backed-up path. Group/indicator
# strings use the same boundary spellings as the InputUnit literal suite.
SOURCE = {
    'Application': '0x38 0xFE',
    'Project': 'SYNTH',
    'UnitAddress': '0x14',
    'UnitName': 'INPUT',
    'GroupAddress': '  0x00 0xFf  254 127 0x42 17  18 19  ',
    'IndicatorFunction': '3 2 1 0 ',
    'LearnAnyApp': '1',
    'LearnMode': '1',
}
NATIVE_PARAMETERS = set(SOURCE) | {'IndicatorBrightness', 'LearnedFlag'}
EXPECTED_EXACT = {
    'Application': '0x38 0xFE',
    'Project': 'SYNTH',
    'UnitAddress': '0x14',
    'UnitName': 'INPUT',
    'GroupAddress': '  0x00 0xFf  254 127 0x42 17  18 19  ',
    'IndicatorFunction': '3 2 1 0 ',
}


class BackedUpPairTests(unittest.TestCase):
    def test_only_key1_to_key2_is_admitted(self):
        validate_backed_up_pair('KEY1', 'KEY2')
        for source, target in (('KEY1', 'KEY4'), ('KEY2', 'KEY1'),
                               ('KEYBC2', 'KEYBC4'), ('BCNC4A', 'BCNC4B')):
            with self.subTest(source=source, target=target):
                with self.assertRaisesRegex(ValueError, 'only KEY1 -> KEY2'):
                    validate_backed_up_pair(source, target)

    def test_readdress_requires_distinct_int_addresses(self):
        self.assertEqual(validate_readdress(20, 21), (20, 21))
        for source, target in ((20, 20), ('20', 21), (20, '21'),
                               (-1, 21), (20, 256), (True, 21), (20, None)):
            with self.subTest(source=source, target=target):
                with self.assertRaises(ValueError):
                    validate_readdress(source, target)


class BackupMetadataTests(unittest.TestCase):
    def test_exact_backup_and_metadata_pass_through(self):
        backup = dict(SOURCE)
        self.assertEqual(require_backup_snapshot(backup, SOURCE), SOURCE)
        self.assertEqual(require_exact_metadata(SOURCE, backup), EXPECTED_EXACT)
        self.assertEqual(tuple(BACKED_UP_EXACT_FIELDS),
                         ('Application', 'Project', 'UnitAddress', 'UnitName',
                          'GroupAddress', 'IndicatorFunction'))

    def test_backup_must_equal_full_source_snapshot(self):
        for name in BACKED_UP_EXACT_FIELDS:
            with self.subTest(field=name):
                backup = dict(SOURCE)
                backup[name] = 'CHANGED'
                with self.assertRaises(ValueError):
                    require_backup_snapshot(backup, SOURCE)
                with self.assertRaises(ValueError):
                    require_exact_metadata(SOURCE, backup)
        backup = {k: v for k, v in SOURCE.items() if k != 'LearnMode'}
        with self.assertRaises(ValueError):
            require_backup_snapshot(backup, SOURCE)
        with self.assertRaises(ValueError):
            require_backup_snapshot({}, SOURCE)
        with self.assertRaises(ValueError):
            require_backup_snapshot('backup', SOURCE)

    def test_lifecycle_plan_binds_backup_readdress_and_native_gate(self):
        plan = lifecycle_plan(dict(SOURCE), source_address=20, target_address=21,
                              backup_values=dict(SOURCE),
                              target_parameters=set(NATIVE_PARAMETERS))
        self.assertEqual(plan['format'], BACKED_UP_FORMAT)
        self.assertEqual((plan['source_type'], plan['target_type']), ('KEY1', 'KEY2'))
        self.assertEqual((plan['source_address'], plan['target_address']), (20, 21))
        self.assertEqual(plan['exact_fields'], list(BACKED_UP_EXACT_FIELDS))
        self.assertFalse(plan['project_saved'])
        self.assertFalse(plan['reopen_verified'])
        self.assertFalse(plan['recovery_replay'])
        self.assertEqual(len(plan['backup_sha256']), 64)
        # Same snapshot always binds the same digest; a one-byte change must not collide.
        again = lifecycle_plan(dict(SOURCE), source_address=20, target_address=21,
                               backup_values=dict(SOURCE),
                               target_parameters=set(NATIVE_PARAMETERS))
        self.assertEqual(again['backup_sha256'], plan['backup_sha256'])
        altered = dict(SOURCE)
        altered['UnitName'] = 'INPUT2'
        other = lifecycle_plan(altered, source_address=20, target_address=21,
                               backup_values=altered,
                               target_parameters=set(NATIVE_PARAMETERS) | {'UnitName'})
        self.assertNotEqual(other['backup_sha256'], plan['backup_sha256'])

    def test_lifecycle_plan_fails_closed_without_silent_defaults(self):
        with self.assertRaises(ValueError):
            lifecycle_plan(dict(SOURCE), source_address=20, target_address=20,
                            backup_values=dict(SOURCE),
                            target_parameters=set(NATIVE_PARAMETERS))
        altered = dict(SOURCE)
        altered['Project'] = 'OTHER'
        with self.assertRaises(ValueError):
            lifecycle_plan(dict(SOURCE), source_address=20, target_address=21,
                            backup_values=altered,
                            target_parameters=set(NATIVE_PARAMETERS))
        with self.assertRaises(ValueError):
            lifecycle_plan(dict(SOURCE), source_address=20, target_address=21,
                            backup_values=dict(SOURCE),
                            target_parameters=set(SOURCE) - {'GroupAddress'})
        empty = dict(SOURCE)
        empty['GroupAddress'] = ''
        with self.assertRaises(ValueError):
            lifecycle_plan(empty, source_address=20, target_address=21,
                            backup_values=empty,
                            target_parameters=set(NATIVE_PARAMETERS))


class SaveReopenRecoveryTests(unittest.TestCase):
    def test_save_reopen_requires_flag_and_exact_readback(self):
        self.assertTrue(verify_save_reopen(project_saved=True,
                                           reopen_values=dict(EXPECTED_EXACT),
                                           expected_values=dict(EXPECTED_EXACT)))
        with self.assertRaises(ValueError):
            verify_save_reopen(project_saved=False,
                               reopen_values=dict(EXPECTED_EXACT),
                               expected_values=dict(EXPECTED_EXACT))
        short = dict(EXPECTED_EXACT)
        del short['GroupAddress']
        with self.assertRaisesRegex(ValueError, 'GroupAddress'):
            verify_save_reopen(project_saved=True, reopen_values=short,
                               expected_values=dict(EXPECTED_EXACT))
        changed = dict(EXPECTED_EXACT)
        changed['IndicatorFunction'] = '0 0 0 0'
        with self.assertRaisesRegex(ValueError, 'IndicatorFunction'):
            verify_save_reopen(project_saved=True, reopen_values=changed,
                               expected_values=dict(EXPECTED_EXACT))

    def test_recovery_is_read_only_and_reports_every_uncertain_stage(self):
        self.assertEqual(tuple(BACKED_UP_JOURNAL_STAGES),
                         ('backup_taken', 'target_created', 'writes_staged',
                          'saved_to_database', 'project_saved', 'reopen_verified'))
        full = {name: True for name in BACKED_UP_JOURNAL_STAGES}
        result = recover_from_journal(full)
        self.assertTrue(result['complete'])
        self.assertEqual(result['uncertain'], [])
        self.assertFalse(result['replay'])
        partial = dict(full)
        partial['project_saved'] = False
        partial['reopen_verified'] = False
        result = recover_from_journal(partial)
        self.assertFalse(result['complete'])
        self.assertEqual(result['uncertain'], ['project_saved', 'reopen_verified'])
        self.assertFalse(result['replay'])
        self.assertIn('read-only', result['next_action'])
        # Lost backup can never be recovered by replay; it needs a fresh backup.
        lost_backup = {name: False for name in BACKED_UP_JOURNAL_STAGES}
        result = recover_from_journal(lost_backup)
        self.assertFalse(result['complete'])
        self.assertIn('backup', result['next_action'])
        with self.assertRaises(ValueError):
            recover_from_journal({name: True for name in BACKED_UP_JOURNAL_STAGES
                                  if name != 'project_saved'})
        with self.assertRaises(ValueError):
            recover_from_journal({**full, 'extra_stage': True})
        with self.assertRaises(ValueError):
            recover_from_journal({**full, 'project_saved': 'yes'})


if __name__ == '__main__':
    unittest.main()
