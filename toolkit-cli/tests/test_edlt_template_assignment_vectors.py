"""Detached staging compared with independently captured original PPAttribute.

Original callbacks were synthetic fault injectors; portable staging executes
no callbacks. Those failure cases establish a deliberate atomicity difference,
not a claim to have run the original template dialog or model rebind.
"""
import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt_templates import (
    EdltTemplate, EdltTemplateApplyRefused, EdltTemplateError, edlt_template_crc,
)
from cbus_toolkit.edlt_template_staging import (
    EdltTemplateAssignmentTransaction, TemplatePpSnapshot, TemplateStagingError,
)


FIXTURE = json.loads((Path(__file__).resolve().parents[1] /
                     'research/edlt_template_assignment_vectors.json').read_text())
CASES = FIXTURE['cases']
BY_ID = {row['id']: row for row in CASES}
SOURCE_REFUSALS = {
    'template-raw-null-baseline': 'null tokens',
    'template-first-duplicate-baseline-name': 'duplicate baseline names',
    'template-stale-initialize-cleared': 'already initializing context',
    'application-malformed-retains-stale-initialize': 'already initializing context',
}
TEXT_REFUSALS = {
    'template-null-input-failure': 'null assignment is outside the XML profile',
    'template-dollar-sharp-s': 'non-ASCII current-culture dollar casing',
    'template-dollar-dotless-i': 'non-ASCII current-culture dollar casing',
    'template-dollar-letter-i': 'ASCII i casing varies with current culture',
    'template-dollar-ignorable-prefix': 'culture-sensitive dollar prefix',
    'template-dollar-leading-ignorable-prefix': 'culture-sensitive dollar prefix',
}


def template_cases():
    return [row for row in CASES if all(op['mode'] == 'template' for op in row['operations'])]


def source(case):
    return TemplatePpSnapshot(tuple((row['name'], tuple(row['tokens']), row['dirty'])
                                    for row in case['attributes']), case['initial_initialize_mode'])


def template(case):
    payload = tuple((op['name'], op['value']) for op in case['operations'])
    # Format/CRC construction is setup only. Expected assignment states below
    # come exclusively from the independently executed original fixture.
    return EdltTemplate((('UnitType', 'KEYGL5'), ('FirmwareVersion', '5.5.00'),
                         ('CRC', str(edlt_template_crc(value for _, value in payload)))) + payload)


def outcome(case):
    return next(row for row in case['observations'] if row['kind'] == 'result')


def final_parameters(case):
    final = {}
    for row in case['observations']:
        if row['kind'] == 'state':
            final[row['attribute_index']] = (row['name'], tuple(row['tokens']), row['dirty'])
    return tuple(final[i] for i in sorted(final))


class EdltTemplateAssignmentOriginalTests(unittest.TestCase):
    def test_receipt_scope_and_process_isolation(self):
        self.assertEqual(len(CASES), FIXTURE['case_count'])
        self.assertGreaterEqual(len(CASES), 66)
        for name in ('original_ppattribute_executed', 'fresh_process_per_case', 'network_denied', 'unchanged_inputs'):
            self.assertTrue(FIXTURE[name])
        for name in ('original_dialog_executed', 'original_parent_lifecycle_executed',
                     'original_unit_lookup_executed', 'physical_io'):
            self.assertFalse(FIXTURE[name])
        self.assertEqual(FIXTURE['source_pins']['CBusLogicModel.dll'],
                         '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823')

    def test_all_admitted_original_getter_snapshots(self):
        # Covers exact token retention, empty prefixes, joined spaces, original
        # ValueFull single-token shapes and getter failures without mutation.
        for case in CASES:
            for i, row in enumerate(case['observations']):
                if row['kind'] != 'state':
                    continue
                with self.subTest(case=case['id'], observation=i):
                    if None in row['tokens']:
                        with self.assertRaises(EdltTemplateError):
                            TemplatePpSnapshot(((row['name'], tuple(row['tokens']), row['dirty']),))
                    else:
                        snapshot = TemplatePpSnapshot(((row['name'], tuple(row['tokens']), row['dirty']),))
                        self.assertEqual(snapshot.raw[row['name']], row['value'])
                        self.assertEqual(snapshot.raw[row['name']], row['value_full'])

    def test_admitted_template_sequences_match_original_final_tokens_and_dirty(self):
        compared = []
        for case in template_cases():
            if (case['id'] in SOURCE_REFUSALS | TEXT_REFUSALS
                    or outcome(case)['status'] != 'ok'):
                continue
            with self.subTest(case=case['id']):
                baseline = source(case)
                before = baseline.fingerprint
                transaction = EdltTemplateAssignmentTransaction(baseline)
                result = transaction.stage(template(case))
                self.assertEqual(result.after.parameters, final_parameters(case))
                self.assertEqual(result.after.initializing, outcome(case)['initialize_mode'])
                self.assertEqual(baseline.fingerprint, before)
                self.assertFalse(result.as_dict()['external_callbacks_executed'])
                self.assertFalse(result.as_dict()['saved'])
                self.assertFalse(result.as_dict()['apply_allowed'])
                compared.append(case['id'])
        self.assertGreaterEqual(len(compared), 20)
        self.assertIn('template-normalize-dollar', compared)
        self.assertIn('template-normalize-minus-one', compared)
        self.assertIn('template-dollar-x-sharp-s', compared)
        self.assertIn('template-duplicates-last-prefix-retains-tail', compared)
        self.assertIn('application-negative', compared)

    def test_narrow_source_profiles_refuse_before_transaction(self):
        for case_id, reason in SOURCE_REFUSALS.items():
            with self.subTest(case=case_id, restriction=reason), self.assertRaises(EdltTemplateError):
                EdltTemplateAssignmentTransaction(source(BY_ID[case_id]))

    def test_unproved_text_normalization_refuses_without_candidate(self):
        for case_id, reason in TEXT_REFUSALS.items():
            if case_id not in BY_ID:
                continue
            with self.subTest(case=case_id, restriction=reason):
                case = BY_ID[case_id]
                baseline = source(case)
                before = baseline.fingerprint
                transaction = EdltTemplateAssignmentTransaction(baseline)
                with self.assertRaises(EdltTemplateError):
                    transaction.stage(template(case))
                self.assertIsNone(transaction.candidate)
                self.assertEqual(baseline.fingerprint, before)

    def test_original_application_conversion_failures_are_atomic(self):
        for case_id in ('application-double-space', 'application-unknown-malformed-fails-before-lookup'):
            case = BY_ID[case_id]
            with self.subTest(case=case_id):
                self.assertEqual(outcome(case)['boundary'], 'application_conversion')
                self.assertFalse(outcome(case)['initialize_mode'])
                baseline = source(case)
                before = baseline.fingerprint
                transaction = EdltTemplateAssignmentTransaction(baseline)
                with self.assertRaises(TemplateStagingError) as caught:
                    transaction.stage(template(case))
                self.assertFalse(caught.exception.details['discarded_working_initializing'])
                self.assertFalse(caught.exception.details['candidate_published'])
                self.assertTrue(caught.exception.details['source_preserved'])
                self.assertEqual(baseline.fingerprint, before)
                self.assertIsNone(transaction.candidate)

    def test_original_callback_failure_is_not_relabelled_as_executed_binding(self):
        case = BY_ID['template-list-listener-failure-stale-init']
        self.assertEqual(outcome(case)['status'], 'error')
        self.assertTrue(outcome(case)['initialize_mode'])
        self.assertEqual(final_parameters(case), (('Value', ('X', 'Y', 'C'), False),))
        baseline = source(case)
        transaction = EdltTemplateAssignmentTransaction(baseline)
        result = transaction.stage(template(case))
        # With no external listeners, the detached projection can finish. Its
        # final state matches a separate clean original sequence in the fixture.
        clean = BY_ID['template-duplicates-last-prefix-retains-tail']
        self.assertEqual(result.after.parameters, final_parameters(clean))
        self.assertFalse(result.as_dict()['external_callbacks_executed'])
        self.assertFalse(result.as_dict()['parent_rebind_executed'])
        self.assertEqual(baseline.parameters, (('Value', ('A', 'B', 'C'), False),))

        class ForbiddenTarget:
            def __getattribute__(self, name):
                raise AssertionError('No live target member may be inspected')

        with self.assertRaises(EdltTemplateApplyRefused):
            result.apply(ForbiddenTarget())

    def test_dirty_can_change_without_any_original_token_event(self):
        for case_id in ('template-normalize-dollar', 'template-normalize-dollar-x', 'template-normalize-minus-one'):
            case = BY_ID[case_id]
            with self.subTest(case=case_id):
                self.assertFalse(any(row['kind'].endswith('_event') for row in case['observations']))
                result = EdltTemplateAssignmentTransaction(source(case)).stage(template(case))
                self.assertEqual(result.after.parameters, final_parameters(case))
                self.assertEqual(result.after.parameters[0][1], tuple(case['attributes'][0]['tokens']))
                self.assertTrue(result.after.parameters[0][2])


if __name__ == '__main__':
    unittest.main()
