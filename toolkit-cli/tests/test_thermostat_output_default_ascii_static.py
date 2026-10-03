"""Pin source-data dependencies; original instructions never execute here."""
import json
import os
from pathlib import Path
import sys
import unittest

from cbus_toolkit.edlt_add_dialog import _upper

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / 'research'
FIXTURE = RESEARCH / 'fixtures/thermostat-output-default-ascii-source.json'


class ASCIIDefaultSourceTests(unittest.TestCase):
    def test_exact_dependencies_and_reachable_default_table_are_pinned(self):
        value = json.loads(FIXTURE.read_text())
        self.assertEqual(value['format'], 'cbus-thermostat-output-default-ascii-static-v1')
        self.assertEqual(len(value['methods']), 5)
        self.assertEqual(len(value['checks']), 15)
        self.assertTrue(all(value['checks'].values()))
        self.assertEqual(value['methods']['CIS_TThermostat.TPlantControlService.FindExistingGroup']['sha256'],
                         'b375c529b20d7d4bdcf23c94e14b660eae67fe67fbdf31e31c172d8173bc8087')
        self.assertEqual(value['methods']['SysUtils.LowerCase']['sha256'],
                         'a673244ff7f84d8f63b2ad8c2d29b56a0c89489c85b2b1e0876378e75b6259ce')
        self.assertEqual(value['methods']['SysUtils.LowerCaseFromAnsiString']['sha256'],
                         'b4640869f66a5c2091be6745558069deefb057e79f0baa9b34e044795dac22a2')
        self.assertEqual(value['methods']['SysUtils.UpperCase']['sha256'],
                         '31d49e2c60709181dfc1e9cf67b3f0aeed856589842419b8ba2a7b8fc7205753')
        self.assertEqual(value['methods']['System.@UStrEqual']['sha256'],
                         '6af8d82e87766e21661a77b583dcdbcf966b8d7420d2d0bbc56913bd54b4ba25')
        self.assertEqual(value['table'], dict(default_rows=174, non_None_labels=48,
            all_actual_default_labels_ASCII=True, damper_labels=4))
        self.assertEqual(value['default_table_receipt_sha256'],
                         'e74a356b9467f03b6f796652199149a9c978033577b0b074b366f7f3dfd596f3')
        self.assertEqual(value['scope'], dict(missing_reference_lookup_only=True,
            application_migration_implemented=False, arbitrary_Unicode_generated_defaults_admitted=False))
        self.assertFalse(value['original_executed'])
        self.assertFalse(value['vendor_instructions_executed'])
        self.assertFalse(value['physical_io'])
        self.assertTrue(value['source_data_read_only'])

    def test_source_ASCII_equality_leaves_other_native_characters_distinct(self):
        self.assertEqual(_upper('[CG07] G (fan)'), _upper('[cg07] g (FAN)'))
        for lower, upper in zip('abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
            with self.subTest(character=lower):
                self.assertEqual(_upper(lower), upper)
        for left, right in (('é', 'É'), ('Ω', 'ω'), ('straße', 'STRASSE')):
            with self.subTest(pair=(left, right)):
                self.assertNotEqual(_upper(left), _upper(right))
        self.assertEqual(_upper('Unrelated Ω é Straße'), 'UNRELATED Ω é STRAßE')

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_TOOLKIT_MAP'),
                         'Explicit original EXE/MAP required for source-data-only verification')
    def test_fresh_pinned_source_data_matches_published_facts(self):
        sys.path.insert(0, str(RESEARCH))
        self.addCleanup(lambda: sys.path.remove(str(RESEARCH)))
        from thermostat_output_default_ascii_static import inspect
        actual = inspect(Path(os.environ['CBUS_TOOLKIT_EXE']), Path(os.environ['CBUS_TOOLKIT_MAP']))
        self.assertEqual(actual, json.loads(FIXTURE.read_text()))


if __name__ == '__main__':
    unittest.main()
