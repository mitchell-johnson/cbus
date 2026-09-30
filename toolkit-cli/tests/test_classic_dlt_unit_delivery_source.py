"""Retained static control-flow receipts; no vendor CPU execution in this suite."""
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/classic-dlt-unit-delivery-source.json'


class UnitDeliverySourceTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(FIXTURE.read_text())
        self.checks = {(row['method'], row['check']): row for row in self.report['checks']}

    def test_source_bounds_and_distinct_evidence(self):
        report = self.report
        self.assertEqual(report['format'], 'cbus-classic-dlt-unit-delivery-source-v1')
        self.assertEqual(len(report['methods']), 27)
        self.assertGreater(len(report['checks']), 150)
        self.assertTrue(all(row['verified'] for row in report['checks']))
        self.assertEqual(report['methods']['after_save']['start'], '0x121c268')
        self.assertEqual(report['methods']['inherited_after_save']['start'], '0xcac4ec')
        self.assertIn(('inherited_after_save', 'exact_noop_body'), self.checks)
        for key in ('original_cpu_executed', 'native_cgate_executed', 'physical_acceptance',
                    'executor', 'caller_model_verified', 'whole_pp_serializer'):
            self.assertIs(report['boundary'][key], False)

    def test_retained_handler_only_catches_command_family_and_reset_precedes_send(self):
        table = self.report['exception_table']
        self.assertEqual(table['catch_count'], 1)
        self.assertEqual(table['catch_class'], 'ECGateCommand')
        self.assertEqual(table['ancestry']['ECGateSyntaxError'],
                         ['ECGateSyntaxError', 'ECGateCommand', 'Exception', 'TObject'])
        addresses = {name: int(row['address'], 16) for (method, name), row in self.checks.items()
                     if method == 'after_save' and 'address' in row}
        self.assertLess(addresses['ordinary_load_bitmap'], addresses['local_handler_installed'])
        self.assertLess(addresses['ordinary_unretained_clear'], addresses['local_handler_installed'])
        self.assertLess(addresses['reset_retained_broadcast'], addresses['retained_clear'])
        self.assertLess(addresses['retained_clear'], addresses['mark_only_after_clear_returns'])
        self.assertLess(addresses['retained_broadcast'], addresses['local_handler'])
        self.assertLess(addresses['local_handler'], addresses['missing_flavour_clear'])

    def test_unused_owner_and_missing_bitmap_have_role_specific_branches(self):
        self.assertEqual(self.report['rules']['keys']['unused_group_address'], 255)
        for name in ('modify_unused_predicate', 'modify_unused_skips', 'ordinary_unused_predicate',
                     'ordinary_used_continues', 'scene_missing_skips',
                     'scene_bypasses_bitmap_load', 'modify_bypasses_bitmap_load'):
            self.assertIn(('after_save', name), self.checks)
        self.assertIn('no group IsUnused test', self.report['rules']['keys']['scene'])

    def test_relative_kfi_and_clear_contract_avoids_whole_unit_fallback(self):
        rules = self.report['rules']
        self.assertEqual(rules['kfi']['source_value_range'], [0, 255])
        self.assertEqual(rules['kfi']['portable_value_range'], [0, 15])
        self.assertEqual(rules['kfi']['slots'], 8)
        self.assertEqual(rules['kfi']['missing_key_value'], 0)
        self.assertEqual(rules['clear']['key_range'], [1, 8])
        self.assertIn('whole unit', rules['clear']['other_nonzero'])
        self.assertNotIn('{project}', rules['clear']['key_template'])
        self.assertNotIn('{project}', rules['kfi']['template'])
        self.assertIn(('set_completed', 'preserve_error'), self.checks)

    def test_reblock_session_rules_are_not_save_flavours_session_rules(self):
        rules = self.report['rules']['reblock']
        self.assertEqual(rules['existing_session'], ['SET EnableDynamicLabels=0', 'SAVE'])
        self.assertEqual(rules['owned_session'][-3:], ['SAVE', 'END', 'UNLOCK'])
        self.assertIn('END failure prevents UNLOCK', rules['cleanup'])
        self.assertIn('SAVE failure prevents', rules['save_flavours_contrast'])
        for method, name in (('reblock', 'save_for_both_sessions'), ('reblock', 'finally_cleanup_entry'),
                             ('save_flavours_only', 'existing_skips_save'),
                             ('save_flavours_only', 'owned_save_in_finally')):
            self.assertIn((method, name), self.checks)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_STATIC_EXE'), 'requires pinned original EXE/MAP for static reads only')
class FreshUnitDeliveryStaticTests(unittest.TestCase):
    def test_fresh_static_receipt_matches_retained(self):
        from research.classic_dlt_unit_delivery_source import inspect
        exe = Path(os.environ['CBUS_TOOLKIT_STATIC_EXE'])
        symbols = Path(os.environ.get('CBUS_TOOLKIT_STATIC_MAP', exe.with_suffix('.map')))
        self.assertEqual(inspect(exe, symbols), json.loads(FIXTURE.read_text()))

    def test_unpinned_source_rejected_before_disassembly(self):
        from research.classic_dlt_unit_delivery_source import inspect
        with tempfile.TemporaryDirectory() as directory:
            exe, symbols = Path(directory) / 'fake.exe', Path(directory) / 'fake.map'
            exe.write_bytes(b'not vendor code')
            symbols.write_bytes(b'not vendor symbols')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                inspect(exe, symbols)


if __name__ == '__main__':
    unittest.main()
