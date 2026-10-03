"""Authored scalar vectors against independent static-source numeric facts."""
import copy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_inputs import SCHEMA, SENLLAInputs, SENLLAInputSnapshot
from cbus_toolkit.senlla_scalars import (
    CLASSIFICATION, NON_SENT_PARAMETERS, SCALAR_PARAMETERS, InheritedScalarState,
    ScalarSaveMetadata, load_inherited_scalars,
)
from cbus_toolkit.sensors import SensorError
from test_senlla_inputs import IDENTITY, current, fixture


SOURCE = json.loads((Path(__file__).resolve().parents[1] /
                     'research/fixtures/senlla-baseline-scalars-source.json').read_text())
METADATA = ScalarSaveMetadata('site?', 42, 'sensor01')


class SENLLAInheritedScalarTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.inputs = current(), SENLLAInputs(fixture())

    def state(self, **changes):
        values = {**self.raw, **changes}
        return load_inherited_scalars(self.inputs.snapshot(values, identity=IDENTITY))

    def test_complete_classification_matches_independent_source(self):
        self.assertEqual(dict(CLASSIFICATION), SOURCE['classification'])
        self.assertEqual(set(CLASSIFICATION), set(SCHEMA))
        self.assertEqual(len(CLASSIFICATION), 93)
        self.assertEqual(len(SCALAR_PARAMETERS), 11)
        self.assertEqual(len(NON_SENT_PARAMETERS), 13)
        self.assertEqual(len(set(SCALAR_PARAMETERS)), 11)
        self.assertEqual(set(SCALAR_PARAMETERS) & set(NON_SENT_PARAMETERS), set())
        self.assertEqual(SOURCE['classification_count'], 93)
        self.assertEqual(SOURCE['method_count'], len(SOURCE['methods']))
        for flag in ('original_execution', 'original_gui_execution', 'physical_acceptance',
                     'complete_owning_save_implemented'):
            self.assertFalse(SOURCE[flag])

    def test_literal_ramp_vectors(self):
        for raw, expected in SOURCE['literal_vectors']['ramp']:
            with self.subTest(raw=raw):
                state = self.state(RampRate=[raw, raw])
                self.assertEqual(state.loaded_scalars['RampRate'], (expected, expected))
                self.assertEqual(state.parameters(metadata=METADATA)['RampRate'], [expected, expected])
                self.assertEqual(state.snapshot.expected['RampRate'], (raw, raw))

    def test_complete_unsigned_ramp_domain(self):
        # Check each channel independently; the second must not inherit the first.
        for raw in range(256):
            expected = raw if raw < 16 else 1 if raw == 255 else 15
            with self.subTest(raw=raw):
                state = self.state(RampRate=[raw, 7])
                self.assertEqual(state.parameters(metadata=METADATA)['RampRate'], [expected, 7])

    def test_all_timing_ordinals_round_trip(self):
        for value in range(64):
            with self.subTest(value=value):
                state = self.state(DebounceTime=[value], LongPressTime=[63-value])
                result = state.initialize_global().parameters(metadata=METADATA)
                self.assertEqual(result['DebounceTime'], [value])
                self.assertEqual(result['LongPressTime'], [63-value])

    def test_each_neo_pro_ir_bank_and_bit_polarity(self):
        for bank in range(4):
            for clipsal in range(2):
                for nec in range(2):
                    for store in range(2):
                        with self.subTest(bank=bank, clipsal=clipsal, nec=nec, store=store):
                            state = self.state(IRBank=[bank], DisableIR=[clipsal],
                                               DisableIRNEC=[nec], EEPROMLevelStore=[store])
                            loaded = state.loaded_scalars
                            self.assertIs(loaded['InfraredClipsalEnabled'], not bool(clipsal))
                            self.assertIs(loaded['InfraredNECEnabled'], not bool(nec))
                            self.assertIs(loaded['EEPROMLevelStore'], bool(store))
                            result = state.parameters(metadata=METADATA)
                            self.assertEqual(result['IRBank'], [bank])
                            self.assertEqual(result['DisableIR'], [clipsal])
                            self.assertEqual(result['DisableIRNEC'], [nec])
                            self.assertEqual(result['EEPROMLevelStore'], [store])

    def test_global_is_a_distinct_ordered_initialization_phase(self):
        state = self.state(StatusReportInterval=[2])
        self.assertEqual(state.loaded_scalars['StatusReportInterval'], 2)
        self.assertEqual(state.current_scalars['StatusReportInterval'], 2)
        self.assertEqual(state.parameters(metadata=METADATA)['StatusReportInterval'], [2])
        self.assertEqual(state.as_dict(metadata=METADATA)['global_initialization'], [])
        initialized = state.initialize_global()
        self.assertEqual(initialized.loaded_scalars['StatusReportInterval'], 2)
        self.assertEqual(initialized.current_scalars['StatusReportInterval'], 3)
        self.assertEqual(initialized.parameters(metadata=METADATA)['StatusReportInterval'], [3])
        self.assertEqual(initialized.snapshot.expected['StatusReportInterval'], (2,))
        self.assertEqual(initialized.as_dict(metadata=METADATA)['global_initialization'], [{
            'phase': 'global_status_initialization', 'raw': 2, 'initialized': 3}])
        self.assertIs(initialized.initialize_global(), initialized)
        self.assertFalse(state.global_initialized)

    def test_global_full_byte_domain_and_source_literals(self):
        for raw in range(256):
            with self.subTest(raw=raw):
                state = self.state(StatusReportInterval=[raw]).initialize_global()
                self.assertEqual(state.parameters(metadata=METADATA)['StatusReportInterval'], [max(raw, 3)])
                self.assertEqual(state.snapshot.expected['StatusReportInterval'], (raw,))
        for raw, saved in SOURCE['literal_vectors']['status']:
            with self.subTest(literal=raw):
                self.assertEqual(self.state(StatusReportInterval=[raw]).initialize_global().parameters(
                    metadata=METADATA)['StatusReportInterval'], [saved])

    def test_actual_metadata_overwrites_different_raw_pp_values(self):
        state = self.state(Project='RAW', UnitName='OTHER', UnitAddress=[9])
        result = state.parameters(metadata=METADATA)
        self.assertEqual(result['Project'], 'SITE?')
        self.assertEqual(result['UnitName'], 'SENSOR01')
        self.assertEqual(result['UnitAddress'], [42])
        self.assertEqual(state.snapshot.expected['Project'], 'RAW')
        self.assertEqual(state.snapshot.expected['UnitName'], 'OTHER')
        self.assertEqual(state.snapshot.expected['UnitAddress'], (9,))
        self.assertEqual(state.as_dict(metadata=METADATA)['final_owning_metadata'], {
            'project_tag_name': 'site?', 'unit_name': 'sensor01', 'unit_address': 42})

    def test_metadata_preserves_spaces_and_punctuation_without_fresh_cleanup(self):
        metadata = ScalarSaveMetadata(' a?<> ', 0, 'b c!?')
        result = self.state().parameters(metadata=metadata)
        self.assertEqual(result['Project'], ' A?<> ')
        self.assertEqual(result['UnitName'], 'B C!?')
        self.assertEqual(metadata.project_tag_name, ' a?<> ')
        self.assertEqual(ScalarSaveMetadata('', 255, '').unit_name, '')

    def test_metadata_is_required_and_strictly_bounded(self):
        state = self.state()
        with self.assertRaises(TypeError):
            state.parameters()
        for invalid in (None, {}, ('SITE', 42, 'SENSOR')):
            with self.subTest(invalid=invalid), self.assertRaises(SensorError):
                state.parameters(metadata=invalid)
        for invalid in (None, True, 1, [], 'ABCDEFGHI', 'é', 'ß', '\n', '{'):
            for field in ('project_tag_name', 'unit_name'):
                args = METADATA.as_dict()
                args[field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaises(SensorError):
                    ScalarSaveMetadata(**args)
        for invalid in (True, False, -1, 256, '42', 42.0, None):
            with self.subTest(address=invalid), self.assertRaises(SensorError):
                replace(METADATA, unit_address=invalid)

    def test_exact_eleven_fields_exclude_all_delegated_and_non_sent_fields(self):
        result = self.state().initialize_global().parameters(metadata=METADATA)
        self.assertEqual(set(result), set(SCALAR_PARAMETERS))
        self.assertEqual(len(result), 11)
        for name, category in CLASSIFICATION.items():
            if category.endswith('_delegated') or category == 'non_sent_or_protected':
                with self.subTest(name=name):
                    self.assertNotIn(name, result)

    def test_non_sent_raw_bytes_are_kept_without_boolean_checksum_coercion(self):
        for active in (0, 1, 2, 127, 254, 255):
            state = self.state(EEPROMCheckSumActive=[active],
                               **{'EEPROM Checksum': [199]}, RetardationIndex=[237])
            with self.subTest(active=active):
                protected = state.initialize_global().non_sent_parameters()
                self.assertEqual(set(protected), set(NON_SENT_PARAMETERS))
                self.assertEqual(protected['EEPROMCheckSumActive'], [active])
                self.assertEqual(protected['EEPROM Checksum'], [199])
                self.assertEqual(protected['RetardationIndex'], [237])
                self.assertNotIn('EEPROMCheckSumActive', state.parameters(metadata=METADATA))

    def test_all_disabled_learn_bits_remain_raw_non_sent(self):
        for mode in range(2):
            for any_app in range(2):
                for learned in range(2):
                    with self.subTest(mode=mode, any_app=any_app, learned=learned):
                        state = self.state(LearnMode=[mode], LearnAnyApp=[any_app], LearnedFlag=[learned])
                        kept = state.initialize_global().non_sent_parameters()
                        self.assertEqual([kept[n] for n in ('LearnMode', 'LearnAnyApp', 'LearnedFlag')],
                                         [[mode], [any_app], [learned]])

    def test_input_state_and_all_receipts_are_detached(self):
        before = copy.deepcopy(self.raw)
        snapshot = self.inputs.snapshot(self.raw, identity=IDENTITY)
        state = load_inherited_scalars(snapshot).initialize_global()
        with self.assertRaises(TypeError):
            state.snapshot.expected['DebounceTime'] = (9,)
        with self.assertRaises(TypeError):
            state.loaded_scalars['DebounceTime'] = 9
        with self.assertRaises(FrozenInstanceError):
            state.global_initialized = False
        with self.assertRaises(FrozenInstanceError):
            METADATA.unit_address = 99
        self.assertEqual(self.raw, before)
        receipt = state.as_dict(metadata=METADATA)
        receipt['expected']['RampRate'][0] = 0
        receipt['parameters']['RampRate'][0] = 0
        receipt['loaded_scalars']['RampRate'][0] = 0
        receipt['current_scalars']['RampRate'][0] = 0
        receipt['non_sent_parameters']['PatchEnable'][0] = 0
        receipt['global_initialization'][0]['raw'] = 0
        receipt['final_owning_metadata']['unit_name'] = 'FORGED'
        self.raw['RampRate'][0] = 0
        self.assertEqual(state.snapshot.parameters(), before)
        self.assertEqual(state.as_dict(metadata=METADATA)['expected'], before)
        self.assertEqual(state.as_dict(metadata=METADATA), replace(state).as_dict(metadata=METADATA))

    def test_state_requires_valid_complete_input_and_boolean_phase(self):
        for value in (None, self.raw, {}, [], 'SENLLA'):
            with self.subTest(value=type(value).__name__), self.assertRaises(SensorError):
                load_inherited_scalars(value)
        for phase in (0, 1, None, 'true'):
            with self.subTest(phase=phase), self.assertRaises(SensorError):
                InheritedScalarState(self.state().snapshot, phase)
        for name, bad in (('DebounceTime', [64]), ('LongPressTime', [-1]), ('IRBank', [4]),
                          ('EEPROMLevelStore', [True]), ('DisableIR', [2]),
                          ('RampRate', [16]), ('StatusReportInterval', [256])):
            raw = {**self.raw, name: bad}
            with self.subTest(name=name), self.assertRaises(SensorError):
                load_inherited_scalars(SENLLAInputSnapshot(IDENTITY, raw))

    def test_receipt_keeps_component_scope_and_no_acceptance_claim(self):
        receipt = self.state().initialize_global().as_dict(metadata=METADATA)
        self.assertEqual(receipt['format'], 'cbus-senlla-inherited-scalars-v1')
        self.assertEqual(receipt['identity'], list(IDENTITY))
        self.assertEqual(receipt['projected_parameter_count'], 11)
        for flag in ('complete_toolkit_save', 'saved', 'original_execution', 'physical_acceptance'):
            self.assertFalse(receipt[flag])


if __name__ == '__main__':
    unittest.main()
