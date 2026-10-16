"""Authored complete schemas and raw values; no original or device execution."""
import copy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_inputs import SCHEMA, SENLLAInputs, SENLLAInputSnapshot
from cbus_toolkit.sensors import SensorError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


IDENTITY = ('SENLLA', '2.4.00', '5754PE')
# The independent source receipt contains only derived layout facts. Synthetic
# values and schemas below never consume vendor defaults or descriptions.
FACTS = json.loads((Path(__file__).resolve().parents[1] /
                   'research/fixtures/senlla-inherited-scalars-source.json').read_text())[
                       'decoded_effective_layouts']


def fixture(*, omit_bit_metadata=False):
    parameters = {}
    for name, fact in FACTS.items():
        fields = {'Name': name, 'Type': fact['type'], 'Address': str(fact['address']),
                  'ArraySize': str(fact['array_size']), 'BitSize': str(fact['bit_size']),
                  'BitAddress': str(fact['bit_address']), 'ArraySkip': str(fact['array_skip'])}
        if fact['type'] == 'bit' and omit_bit_metadata:
            del fields['BitSize'], fields['ArraySkip']
        parameters[name] = ParameterSpec(name, fact['type'], 'authored-senlla-inputs.xml', fields)
    return UnitSpec('SENLLA.xml', {'Type': 'SENLLA'}, ('authored-senlla-inputs.xml',), parameters)


def current():
    return {name: ('site?' if name == 'Project' else 'sensor01') if fact['type'] == 'sixbit'
            else [(index * 17 + row) % (1 << fact['bit_size'])
                  for index in range(fact['array_size'])]
            for row, (name, fact) in enumerate(FACTS.items())}


def changed_spec(spec, name, **fields):
    parameter = spec.get(name)
    return replace(spec, parameters={**spec.parameters, name: replace(
        parameter, fields={**parameter.fields, **fields})})


class SENLLAInputsTests(unittest.TestCase):
    def setUp(self):
        self.spec, self.raw = fixture(), current()
        self.inputs = SENLLAInputs(self.spec)

    def test_complete_derived_schema_exactly_matches_independent_receipt(self):
        rows = {name: (fact['type'], fact['address'], fact['array_size'], fact['bit_size'],
                       fact['bit_address'], fact['array_skip']) for name, fact in FACTS.items()}
        self.assertEqual(len(rows), 93)
        self.assertEqual(dict(SCHEMA), rows)
        self.assertEqual(sum(row[0] == 'bit' for row in SCHEMA.values()), 21)
        self.assertEqual([name for name, row in SCHEMA.items() if row[0] == 'sixbit'],
                         ['Project', 'UnitName'])

    def test_complete_snapshot_preserves_authored_values_without_normalization(self):
        before = copy.deepcopy(self.raw)
        snapshot = self.inputs.snapshot(self.raw, identity=IDENTITY)
        self.assertEqual(snapshot.parameters(), self.raw)
        self.assertEqual(self.raw, before)
        self.assertEqual(snapshot.expected['Project'], 'site?')
        self.assertEqual(snapshot.expected['UnitName'], 'sensor01')
        self.assertEqual(snapshot.expected['SceneTable'], tuple(self.raw['SceneTable']))
        receipt = snapshot.as_dict()
        self.assertEqual(receipt['expected'], self.raw)
        self.assertEqual(receipt['consumed_parameter_count'], 93)
        self.assertEqual(receipt['runtime_input_key_count'], 8)
        self.assertTrue(receipt['read_only'])
        for flag in ('complete_toolkit_save', 'saved', 'original_execution', 'physical_acceptance'):
            self.assertFalse(receipt[flag])

    def test_canonical_identity_and_firmware_band(self):
        for firmware in ('2.4.00', '2.4.01', '2.4.50', '2.4.99'):
            with self.subTest(firmware=firmware):
                identity = ('SENLLA', firmware, '5754PE')
                self.assertEqual(self.inputs.snapshot(self.raw, identity=identity).identity, identity)
        for identity in (('SENLL', '2.4.00', '5031PE'), ('senlla', '2.4.00', '5754PE'),
                         ('SENLLA', '2.3.99', '5754PE'), ('SENLLA', '2.5.00', '5754PE'),
                         ('SENLLA', '2.4.0', '5754PE'), ('SENLLA', '2.4.000', '5754PE'),
                         ('SENLLA', '2.4.100', '5754PE'), ('SENLLA', '2.4.00', '5754pe'),
                         ('SENLLA', True, '5754PE'), ('SENLLA', None, '5754PE'),
                         None, list(IDENTITY), IDENTITY[:2], IDENTITY + ('extra',)):
            with self.subTest(identity=identity), self.assertRaises(SensorError):
                self.inputs.snapshot(self.raw, identity=identity)

    def test_canonical_provider_filename_and_decoded_type(self):
        for spec in (replace(self.spec, filename='SENLL_ST7.xml'),
                     replace(self.spec, filename='senlla.xml'),
                     replace(self.spec, metadata={'Type': 'SENLL'}),
                     replace(self.spec, metadata={'Type': 'senlla'}),
                     replace(self.spec, metadata={})):
            with self.subTest(spec=spec.filename, type=spec.unit_type), self.assertRaises(SensorError):
                SENLLAInputs(spec)
        # Use the decoded UnitSpec type, whose quoting/whitespace is canonical.
        quoted = replace(self.spec, metadata={'Type': ' "SENLLA" '})
        self.assertEqual(SENLLAInputs(quoted).snapshot(self.raw, identity=IDENTITY).parameters(), self.raw)

    def test_every_missing_schema_parameter_refuses(self):
        for name in FACTS:
            spec = replace(self.spec, parameters={key: value for key, value in self.spec.parameters.items()
                                                  if key != name})
            with self.subTest(name=name), self.assertRaisesRegex(SensorError, name):
                SENLLAInputs(spec)

    def test_every_changed_type_or_name_refuses(self):
        for name, parameter in self.spec.parameters.items():
            for kind in ('int', 'bit', 'sixbit', 'long', 'string'):
                if kind == parameter.type:
                    continue
                wrong = replace(parameter, type=kind, fields={**parameter.fields, 'Type': kind})
                with self.subTest(name=name, kind=kind), self.assertRaisesRegex(SensorError, name):
                    SENLLAInputs(replace(self.spec, parameters={**self.spec.parameters, name: wrong}))
            with self.subTest(name=name, bad_name=True), self.assertRaisesRegex(SensorError, name):
                SENLLAInputs(replace(self.spec, parameters={**self.spec.parameters, name: replace(
                    parameter, name='DifferentParameter')}))

    def test_every_changed_effective_layout_refuses(self):
        for name, parameter in self.spec.parameters.items():
            for field in ('Address', 'ArraySize', 'BitSize', 'BitAddress', 'ArraySkip'):
                if parameter.type == 'bit' and field in ('BitSize', 'ArraySkip'):
                    continue
                spec = changed_spec(self.spec, name, **{field: str(int(parameter.fields[field]) + 1)})
                with self.subTest(name=name, field=field), self.assertRaisesRegex(SensorError, name):
                    SENLLAInputs(spec)

    def test_malformed_layouts_refuse_as_sensor_errors(self):
        for field, value in (('Address', 'garbage'), ('Address', '-1'), ('ArraySize', '0'),
                             ('BitSize', '0'), ('BitAddress', '-1'), ('ArraySkip', '-1')):
            with self.subTest(field=field, value=value), self.assertRaises(SensorError):
                SENLLAInputs(changed_spec(self.spec, 'Application', **{field: value}))

    def test_omitted_and_ignored_bit_metadata_use_effective_one_bit_layout(self):
        spec = fixture(omit_bit_metadata=True)
        expected = self.inputs.snapshot(self.raw, identity=IDENTITY).as_dict()
        inputs = SENLLAInputs(spec)
        self.assertEqual(inputs.snapshot(self.raw, identity=IDENTITY).as_dict(), expected)
        for name, parameter in spec.parameters.items():
            if parameter.type != 'bit':
                continue
            self.assertEqual(parameter.bit_size, 8)
            self.assertEqual(inputs.codec.layout(name).bit_size, 1)
            for width in (2, 8, 64):
                modified = changed_spec(spec, name, BitSize=str(width), ArraySkip='3')
                with self.subTest(name=name, width=width):
                    self.assertEqual(SENLLAInputs(modified).snapshot(self.raw, identity=IDENTITY).as_dict(),
                                     expected)
                    with self.assertRaisesRegex(SensorError, name):
                        SENLLAInputs(modified).snapshot({**self.raw, name: [2]}, identity=IDENTITY)

    def test_each_missing_current_field_refuses_without_input_mutation(self):
        for name in FACTS:
            raw = {key: value for key, value in self.raw.items() if key != name}
            before = copy.deepcopy(raw)
            with self.subTest(name=name), self.assertRaisesRegex(SensorError, name):
                self.inputs.snapshot(raw, identity=IDENTITY)
            self.assertEqual(raw, before)
        for raw in (None, [], 'PP', 1, True):
            with self.subTest(raw=raw), self.assertRaises(SensorError):
                self.inputs.snapshot(raw, identity=IDENTITY)

    def test_every_numeric_field_requires_exact_count_and_unsigned_width(self):
        for name, fact in FACTS.items():
            if fact['type'] == 'sixbit':
                continue
            count, limit = fact['array_size'], 1 << fact['bit_size']
            for values in ([0] * (count - 1), [0] * (count + 1),
                           [-1] + [0] * (count - 1), [limit] + [0] * (count - 1),
                           [True] + [0] * (count - 1), [False] + [0] * (count - 1),
                           [1.0] + [0] * (count - 1)):
                with self.subTest(name=name, values=values), self.assertRaisesRegex(SensorError, name):
                    self.inputs.snapshot({**self.raw, name: values}, identity=IDENTITY)
            maximum = [limit - 1] * count
            with self.subTest(name=name, maximum=True):
                self.assertEqual(self.inputs.snapshot({**self.raw, name: maximum}, identity=IDENTITY).
                                 parameters()[name], maximum)

    def test_numeric_pp_text_and_tuples_preserve_complete_arrays(self):
        raw = {name: value if isinstance(value, str) else ' '.join(map(str, value))
               for name, value in self.raw.items()}
        self.assertEqual(self.inputs.snapshot(raw, identity=IDENTITY).parameters(), self.raw)
        raw = {name: value if isinstance(value, str) else tuple(value) for name, value in self.raw.items()}
        self.assertEqual(self.inputs.snapshot(raw, identity=IDENTITY).parameters(), self.raw)
        result = self.inputs.snapshot({**self.raw, 'AreaGroupAddress': '$ff'}, identity=IDENTITY)
        self.assertEqual(result.expected['AreaGroupAddress'], (255,))
        for value in ('True', '1.0', '', {}, object()):
            with self.subTest(value=value), self.assertRaisesRegex(SensorError, 'AreaGroupAddress'):
                self.inputs.snapshot({**self.raw, 'AreaGroupAddress': value}, identity=IDENTITY)

    def test_sixbit_strings_are_representable_and_lexically_preserved(self):
        for name in ('Project', 'UnitName'):
            for value in ('', 'abcdefgh', 'Ab C? !', '`[]^_@', '        '):
                with self.subTest(name=name, value=value):
                    result = self.inputs.snapshot({**self.raw, name: value}, identity=IDENTITY)
                    self.assertEqual(result.expected[name], value)
                    self.assertEqual(result.as_dict()['expected'][name], value)
            for value in ('123456789', '\x00', '\n', '\x7f', 'é', 'ß', 'ı', None, True, 1, ['TEXT']):
                with self.subTest(name=name, value=value), self.assertRaisesRegex(SensorError, name):
                    self.inputs.snapshot({**self.raw, name: value}, identity=IDENTITY)

    def test_provider_minimum_and_maximum_are_enforced_after_unsigned_domain(self):
        spec = changed_spec(self.spec, 'AreaGroupAddress', MinValue='10', MaxValue='20')
        inputs = SENLLAInputs(spec)
        for value in (10, 20):
            with self.subTest(value=value):
                self.assertEqual(inputs.snapshot({**self.raw, 'AreaGroupAddress': value}, identity=IDENTITY).
                                 parameters()['AreaGroupAddress'], [value])
        for value in (0, 9, 21, 255):
            with self.subTest(value=value), self.assertRaisesRegex(SensorError, 'AreaGroupAddress'):
                inputs.snapshot({**self.raw, 'AreaGroupAddress': value}, identity=IDENTITY)
        bad = SENLLAInputs(changed_spec(self.spec, 'AreaGroupAddress', MinValue='20', MaxValue='10'))
        with self.assertRaisesRegex(SensorError, 'AreaGroupAddress'):
            bad.snapshot(self.raw, identity=IDENTITY)

    def test_extra_schema_and_current_fields_are_excluded_from_snapshot_ownership(self):
        # Unsupported extras do not enter this exact 93-field ownership boundary.
        extra = ParameterSpec('Extra', 'unknown', 'authored.xml', {})
        spec = replace(self.spec, parameters={**self.spec.parameters, 'Extra': extra})
        raw = {**self.raw, 'Extra': object()}
        result = SENLLAInputs(spec).snapshot(raw, identity=IDENTITY)
        self.assertEqual(result.parameters(), self.raw)
        self.assertNotIn('Extra', result.expected)
        self.assertEqual(len(result.expected), 93)

    def test_adapter_rechecks_mutable_provider_metadata_and_layouts(self):
        spec = fixture()
        inputs = SENLLAInputs(spec)
        spec.parameters.pop('Application')
        with self.assertRaisesRegex(SensorError, 'Application'):
            inputs.snapshot(self.raw, identity=IDENTITY)
        spec = fixture()
        inputs = SENLLAInputs(spec)
        spec.parameters['Application'].fields['Address'] = '34'
        with self.assertRaisesRegex(SensorError, 'Application'):
            inputs.snapshot(self.raw, identity=IDENTITY)
        spec = fixture()
        inputs = SENLLAInputs(spec)
        spec.metadata['Type'] = 'SENLL'
        with self.assertRaisesRegex(SensorError, 'canonical'):
            inputs.snapshot(self.raw, identity=IDENTITY)

    def test_snapshot_and_all_exports_are_detached_and_immutable(self):
        result = self.inputs.snapshot(self.raw, identity=IDENTITY)
        self.raw['SceneTable'][0] = 255
        self.raw['UnitName'] = 'CHANGED'
        self.assertNotEqual(result.expected['SceneTable'][0], 255)
        self.assertEqual(result.expected['UnitName'], 'sensor01')
        with self.assertRaises(TypeError):
            result.expected['SceneTable'] = (0,) * 80
        with self.assertRaises(TypeError):
            result.expected['SceneTable'][0] = 255
        with self.assertRaises(FrozenInstanceError):
            result.identity = ('SENLLA', '2.4.01', '5754PE')
        exported = result.parameters()
        exported['SceneTable'][0] = 255
        receipt = result.as_dict()
        receipt['expected']['SceneTable'][0] = 255
        receipt['expected']['UnitName'] = 'CHANGED'
        self.assertNotEqual(result.expected['SceneTable'][0], 255)
        self.assertEqual(result.expected['UnitName'], 'sensor01')
        rebound = replace(result, identity=('SENLLA', '2.4.99', '5754PE'))
        self.assertEqual(rebound.expected, result.expected)
        self.assertEqual(rebound.identity[1], '2.4.99')

    def test_direct_snapshot_construction_enforces_full_shape_identity_and_domains(self):
        raw = current()
        self.assertEqual(SENLLAInputSnapshot(IDENTITY, raw).parameters(), raw)
        for expected in ({}, {**raw, 'Extra': [0]}, {**raw, 'JPCommand': [16] * 8},
                         {**raw, 'Project': 'ß'}, None):
            with self.subTest(expected=expected), self.assertRaises(SensorError):
                SENLLAInputSnapshot(IDENTITY, expected)
        with self.assertRaises(SensorError):
            SENLLAInputSnapshot(list(IDENTITY), raw)


if __name__ == '__main__':
    unittest.main()
