"""Committed key-family equivalence receipt against the admitted preset tables."""
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.extended_macros import LAYOUTS, PROFILES, REFUSED_PROFILES
from cbus_toolkit.macros import (EXCLUDED_PRESETS, GUARDED_PARAMETERS, HELP_TABLE_EVENTS, MICRO_FUNCTIONS,
                                 PRESETS, REFUSED_UNITS, SUPPORTED_UNITS, TRIGGER_APPLICATION, TRIGGER_PRESETS,
                                 _READ_FIELDS)


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'research/fixtures/key-preset-family-equivalence.json'


def receipt():
    return json.loads(RECEIPT.read_text(encoding='utf-8'))


def rows(family):
    return {row['spec_filename']: row for row in receipt()['families'][family]['types']}


class ReceiptTableTests(unittest.TestCase):
    def test_receipt_is_sanitized_and_pinned(self):
        data = receipt()
        self.assertEqual(data['format'], 'cbus-key-preset-family-equivalence-v1')
        self.assertFalse(data['original_code_executed'])
        self.assertEqual(data['original_exe_sha256'], '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab')
        text = RECEIPT.read_text(encoding='utf-8')
        # Hashes, names and decisions only: no specification XML or defaults.
        for marker in ('<Param', 'DefaultValue', 'MinValue', '<Address>'):
            self.assertNotIn(marker, text)

    def test_classic_table_matches_admitted_receipt_rows(self):
        self.assertEqual(receipt()['families']['classic']['workflow_parameters'], list(_READ_FIELDS))
        table = rows('classic')
        admitted = {row['unit_type']: row for row in table.values() if row['decision'] == 'admitted'}
        self.assertEqual(set(admitted), set(SUPPORTED_UNITS))
        for unit_type, row in admitted.items():
            with self.subTest(unit_type=unit_type):
                self.assertEqual(row['spec_filename'], unit_type + '.xml')
                self.assertTrue(row['workflow_layout_matches_reference'])
                self.assertEqual(row['toolkit_agent_class'], 'TCBusKeyInputCGateAgent')
                self.assertIn('TCBusKeyInputUnit', row['toolkit_class_chain'])
                self.assertEqual(row['maximum_key_count'], SUPPORTED_UNITS[unit_type])
                self.assertEqual(tuple(row['differing_layout_parameters']), GUARDED_PARAMETERS.get(unit_type, ()))
                self.assertFalse(set(row['differing_layout_parameters']) & set(_READ_FIELDS))
                self.assertEqual(set(row['subset_excluded_presets']), set(EXCLUDED_PRESETS.get(unit_type, ())))
        self.assertEqual(table['BCNC4A.xml']['decision'], 'refused')
        self.assertIn('BCNC4A', REFUSED_UNITS)

    def test_neo_table_matches_admitted_receipt_rows(self):
        self.assertEqual(receipt()['families']['neo']['workflow_parameters'], list(LAYOUTS))
        table = rows('neo')
        admitted = {name for name, row in table.items() if row['decision'] == 'admitted'}
        self.assertEqual(admitted, set(PROFILES))
        for filename, (unit_type, count, _family) in PROFILES.items():
            row = table[filename]
            with self.subTest(spec=filename):
                self.assertEqual(row['unit_type'], unit_type)
                self.assertTrue(row['workflow_layout_matches_reference'])
                self.assertIn(row['toolkit_agent_class'], ('TCBusNeoProInputCGateAgent', 'TCBusKEYExCGateAgent'))
                self.assertIn('TCBusNeoProInputUnit', row['toolkit_class_chain'])
                self.assertEqual(row['subset_excluded_presets'], [])
                self.assertEqual(row['catalog_selection']['spec_filenames'], [filename])
                # KEYE1 keeps its accepted one-key profile under the shared TKEYEx class.
                self.assertEqual(count, 1 if unit_type == 'KEYE1' else row['maximum_key_count'])
                self.assertEqual(row['differing_layout_parameters'], ['KeyMask'] if unit_type == 'KEYE1' else [])
        for filename in REFUSED_PROFILES:
            self.assertEqual(table[filename]['decision'], 'refused')
        self.assertTrue(all(row['decision'] == 'refused' for name, row in table.items() if name.endswith('_A.xml')))

    def test_preset_template_types_cover_every_preset(self):
        data = receipt()
        self.assertEqual(set(data['preset_template_types']), set(PRESETS))
        self.assertEqual(data['aux_template_override']['replaced_template_types'], [27, 7])
        self.assertNotIn(data['preset_template_types']['bellpress'], data['macro_function_subsets']['AUX']['0'])

    def test_presets_are_the_micro_function_groups_toolkit_assigns(self):
        data = receipt()['preset_micro_function_groups']
        self.assertEqual(data['stage_order'], ['JPCommand', 'SRCommand', 'LPCommand', 'LRCommand'])
        self.assertEqual(data['template_assignment']['default_group_index'], 0)
        self.assertEqual(set(data['presets']), set(PRESETS))
        for name, preset in PRESETS.items():
            row = data['presets'][name]
            with self.subTest(preset=name):
                self.assertEqual(list(preset.codes), row['stages'])
                self.assertEqual(row['template_type'], receipt()['preset_template_types'][name])
                self.assertEqual(row['group_type'], row['template_groups'][row['group_index']])
                help_events = HELP_TABLE_EVENTS.get(name)
                self.assertEqual(row.get('help_table_stages'),
                                 None if help_events is None else [MICRO_FUNCTIONS[e] for e in help_events])
        self.assertEqual(set(HELP_TABLE_EVENTS), {'bellpress', 'soft_up', 'soft_down'})

    def test_trigger_templates_only_in_trigger_control_subsets(self):
        data = receipt()
        self.assertEqual(TRIGGER_APPLICATION, 202)
        types = {data['preset_template_types'][name] for name in TRIGGER_PRESETS}
        for subset, applications in data['macro_function_subsets'].items():
            with self.subTest(subset=subset):
                self.assertLessEqual(types, set(applications[str(TRIGGER_APPLICATION)]))
                self.assertFalse(types & set(applications['0']))


@unittest.skipUnless(os.environ.get('CBUS_UNITSPEC_DIR') and os.environ.get('CBUS_TOOLKIT_EXE')
                     and os.environ.get('CBUS_UNIT_CATALOG'),
                     'Set CBUS_UNITSPEC_DIR, CBUS_TOOLKIT_EXE and CBUS_UNIT_CATALOG to regenerate the receipt')
class RegenerateReceiptTests(unittest.TestCase):
    def test_vendor_inputs_reproduce_the_committed_receipt(self):
        from research.key_preset_families import inspect, render
        exe = Path(os.environ['CBUS_TOOLKIT_EXE'])
        map_file = Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map')))
        generated = render(inspect(Path(os.environ['CBUS_UNITSPEC_DIR']), exe, map_file,
                                   Path(os.environ['CBUS_UNIT_CATALOG'])))
        self.assertEqual(generated, RECEIPT.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
