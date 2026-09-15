"""Independent original model/category vectors and strict pure merge guards."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_global_programming import EdltGlobalProgramming, CATEGORIES, _native_value
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from tests.test_edlt_corridor import cache

ROOT = Path(__file__).resolve().parents[1]
VECTOR_PATH = ROOT / 'research/fixtures/edlt-global-programming-vectors.json'
VECTOR_HASH = 'e0ac5e0747279cc11e1c697045ec245f063905c8c11a6aae365f1941b6b0a415'


def vectors():
    data = VECTOR_PATH.read_bytes()
    if hashlib.sha256(data).hexdigest() != VECTOR_HASH: raise AssertionError('Original vector artifact changed')
    return json.loads(data)


def fixture():
    parameters = {p['name']: ParameterSpec(p['name'], p['type'], 'original-vector-layout', p['fields'])
                  for p in vectors()['parameters']}
    return UnitSpec('KEYGL5.xml', {'Type': 'KEYGL5'}, ('original-vector-layout',), parameters)


def categories(mask):
    return tuple(name for i, name in enumerate(CATEGORIES) if mask & (1 << i))


class GlobalProgrammingTests(unittest.TestCase):
    def setUp(self):
        self.editor = EdltGlobalProgramming(fixture())
        self.vectors = vectors()
        self.row = self.vectors['sources'][1]

    def prepare(self, row=None, **kwargs):
        row = self.row if row is None else row
        return self.editor.prepare_source(row['input'], metadata=cache().lifecycle,
                                          parameter_order=row['parameter_order'], **kwargs)

    def test_original_all_masks_full_source_phases_payload_order_and_zero_crc(self):
        for row in self.vectors['sources']:
            source = self.prepare(row)
            expected_load = self.editor.snapshot({**row['input'], **row['after_load_delta']})
            expected_save = self.editor.snapshot({**row['input'], **row['after_load_delta'], **row['after_save_delta']})
            self.assertEqual(dict(source.after_load), expected_load)
            self.assertEqual(dict(source.final), expected_save)
            self.assertEqual(source.expected['Project'], source.final['Project'])
            self.assertEqual(len(source.final), 874)
            for case in row['masks']:
                with self.subTest(context=row['context'], mask=case['mask']):
                    payload = self.editor.select(source, categories=categories(case['mask']))
                    self.assertEqual([(k, _native_value(v)) for k, v in payload.ordered_payload],
                                     [tuple(pair) for pair in case['ordered_payload']])
                    self.assertEqual(len(payload.ordered_payload), 2 + sum(len(CATEGORIES[k]) for k in categories(case['mask'])))
                    self.assertEqual(payload.ordered_payload[-1], ('GlobalParameterCRC', (0, 0)))
                    self.assertFalse(payload.as_dict()['destination_full_crc_validity_verified'])
                    self.assertFalse(payload.as_dict()['full_form_preamble_applied'])

    def test_actual_reversed_874_attribute_order_preserves_values(self):
        row = self.vectors['sources'][1]
        forward = self.prepare(row)
        for case in self.vectors['reversed_order']:
            source = self.editor.prepare_source(row['input'], metadata=cache().lifecycle, parameter_order=case['parameter_order'])
            self.assertEqual(source.final, forward.final)
            payload = self.editor.select(source, categories=categories(case['mask']))
            self.assertEqual([(k, _native_value(v)) for k, v in payload.ordered_payload],
                             [tuple(pair) for pair in case['ordered_payload']])
            self.assertEqual(payload.values, self.editor.select(forward, categories=categories(case['mask'])).values)
        ordered = dict(reversed(list(row['input'].items())))
        inferred = self.editor.prepare_source(ordered, metadata=cache().lifecycle)
        self.assertEqual(inferred.parameter_order, tuple(ordered))

    def test_selected_unchanged_parameters_still_present_and_empty_categories_are_two_writes(self):
        source = self.prepare()
        payload = self.editor.select(source, categories=tuple(CATEGORIES))
        merged = self.editor.merge(payload, source.final)
        forced = merged.as_dict()['forced_unchanged_parameters']
        self.assertEqual(len(forced), 49)
        self.assertEqual(list(merged.as_dict()['changes']), ['GlobalParameterCRC'])
        empty = self.editor.select(source)
        self.assertEqual(tuple(empty.values), ('OverallCRC', 'GlobalParameterCRC'))
        self.assertEqual(len(empty.ordered_payload), 2)

    def test_independent_destination_fields_and_identity_are_preserved(self):
        source = self.prepare()
        original = dict(source.final)
        original.update(UnitAddress=(21,), Project='DEST', UnitName='TARGET', SerialNumber=(1,2,3,4),
                        Widget6RestoreLevel=(201,), WidgetsCRC=(1,2), StaticTextCRC=(3,4), ScenesCheckSum=(5,6))
        payload = self.editor.select(source, categories=('key-settings',))
        merge = self.editor.merge(payload, original)
        for name, value in original.items():
            self.assertEqual(merge.final[name], payload.values[name] if name in payload.values else value)
        self.assertEqual(merge.final['OverallCRC'], source.final['OverallCRC'])
        self.assertEqual(merge.final['GlobalParameterCRC'], (0,0))
        self.assertNotEqual(merge.final, source.final)
        self.assertEqual(source.expected, self.editor.snapshot(self.row['input']))

    def test_retained_original_sequential_vectors_use_one_frozen_source(self):
        source = self.prepare()
        before = source.as_dict()
        with patch.object(self.editor.lifecycle, 'load', side_effect=AssertionError('second load')):
            for case in self.vectors['sequential']:
                payload = self.editor.select(source, categories=tuple(CATEGORIES))
                self.assertEqual([(k, _native_value(v)) for k, v in payload.ordered_payload], [tuple(pair) for pair in case['ordered_payload']])
                self.editor.merge(payload, source.final)
        self.assertEqual(source.as_dict(), before)
        self.assertEqual(len(self.vectors['sequential'][0]['source_changes']), 20)
        self.assertFalse(self.vectors['sequential'][1]['source_changes'])
        self.assertTrue(self.vectors['sequential'][1]['dirty_after'])

    def test_invalid_schema_categories_order_cache_and_strict_numeric_values(self):
        source = self.prepare()
        for value in ('colour', ('bad',), ('colour','colour'), (True,)):
            with self.assertRaises(EdltError): self.editor.select(source, categories=value)
        order = self.row['parameter_order']
        for value in ('invalid', order[:-1], [*order[:-1], order[0]], [True, *order[1:]]):
            with self.assertRaises(EdltError): self.editor.prepare_source(self.row['input'], metadata=cache().lifecycle, parameter_order=value)
        values = dict(self.row['input'])
        for name, value in (('UseBigIcon', True), ('FontStyle', (False,)), ('CorridorLinkingCorridorTime', (65536,))):
            with self.assertRaises((EdltError, ValueError)): self.editor.prepare_source({**values, name:value}, metadata=cache().lifecycle)
        del values['OverallCRC']
        with self.assertRaises(EdltError): self.editor.prepare_source(values, metadata=cache().lifecycle)
        with self.assertRaises(EdltError): self.editor.prepare_source(self.row['input'], metadata={'format':'invalid'})
        spec = fixture(); parameters = dict(spec.parameters)
        parameters['UseBigIcon'] = replace(parameters['UseBigIcon'], fields={**parameters['UseBigIcon'].fields, 'BitAddress':'3'})
        with self.assertRaises(EdltError): EdltGlobalProgramming(replace(spec, parameters=parameters))

    def test_issued_objects_reject_dataclass_replacement_other_engine_and_bool_forgery(self):
        source = self.prepare(); payload = self.editor.select(source); merge = self.editor.merge(payload, source.final)
        for forged in (replace(source), replace(source, final={**source.final, 'Widget1WidgetByteValue31':(False,)})):
            with self.assertRaises(EdltError): self.editor.select(forged)
        with self.assertRaises(EdltError): self.editor.merge(replace(payload), source.final)
        with self.assertRaises(EdltError): self.editor._merge(replace(merge))
        other = EdltGlobalProgramming(fixture())
        with self.assertRaises(EdltError): other.select(source)
        with self.assertRaises(EdltError): self.editor.merge(payload.as_dict(), source.final)
        with self.assertRaises(TypeError): source.final['FontStyle'] = (0,)

    def test_original_rejected_set_false_complete_evidence_is_not_typed_success(self):
        row = next(r for r in self.vectors['negative_results'] if r['name']=='pp-set-rejected')
        self.assertTrue(row['save_calls'][0]['original_return'])
        self.assertTrue(row['save_calls'][0]['false_complete'])
        self.assertIn('FontStyle', str(row['save_calls'][0]['rejected_parameters']))


if __name__ == '__main__': unittest.main()
