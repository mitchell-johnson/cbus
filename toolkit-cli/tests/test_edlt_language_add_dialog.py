"""Native selected-list policy, retained row identity and ordered defaults."""
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_language_add_dialog import (
    LANGUAGE_NAMES, LanguageRow, initialise, normalize, project, _native_default_id,
)


def row(identifier, name, identity):
    return LanguageRow(identifier, name, identity)


def operation(selected=(), *, cancel=False, preferences='registered-defaults'):
    return dict(op='add-language-dialog', selected_ids=list(selected), cancel=cancel,
                preferences=preferences)


class LanguageAddTests(unittest.TestCase):
    def test_literal_native_integer_aliases_and_unknown_rows(self):
        for spelling, expected in [('  +74',74),('$4A',74),('0x4a',74),('X4A',74),
                                   ('74 ',0),('７４',0),('7_4',0),('2147483648',0),
                                   ('$FFFFFFFF',1),('-2147483648',1),('74\0suffix',74)]:
            with self.subTest(spelling=spelling):
                state=initialise((row(999,'unknown','U'),row(-1,'unknown','N'),row(0,spelling,'M')),
                                 'registered-defaults')
                self.assertEqual(state.default,expected)
                self.assertEqual(state.cache,(1,))

    def test_reopening_dialog_does_not_reimport_removed_preference(self):
        preferences=[1,8,-1,-1,-1,-1,-1,-1]
        state=initialise((),preferences)
        state,_=project(state,operation([1,74],preferences=preferences))
        state,receipt=project(state,operation(cancel=True,preferences=preferences))
        self.assertEqual(state.cache,(1,74))
        self.assertEqual(receipt['cache_before'],[1,74])


    def test_native_marker_huge_leading_zeros_do_not_borrow_python_digit_limit(self):
        zeros='0'*5000
        for spelling, expected in [(zeros+'1',1),('-'+zeros+'1',-1),
                                   (zeros+'2147483648',0),(zeros+'bad',0),
                                   ('$'+zeros+'FFFFFFFF',-1),('$'+zeros+'100000000',0)]:
            with self.subTest(kind=spelling[-12:]):
                self.assertEqual(_native_default_id(spelling),expected)


    def test_xml_import_precedes_preference_order_and_is_not_capped(self):
        state = initialise((row(8, 'local NZ', 'NZ'), row(74, 'local French', 'FR'),
                            row(0, '8', 'DEFAULT')), [80, 2, -1, -1, -1, -1, -1, -1])
        self.assertEqual(state.cache, (8, 74, 80, 2))
        self.assertEqual(state.default, 8)
        rows = tuple(row(i, str(i), str(i)) for i in range(1, 10))
        self.assertEqual(len(initialise(rows, 'registered-defaults').cache), 9)

    def test_registered_default_english_and_zero_marker_are_distinct(self):
        self.assertEqual(initialise((), 'registered-defaults').cache, (1,))
        self.assertEqual(initialise((), 'registered-defaults').default, 1)
        self.assertEqual(initialise((row(0, '0', 'M'),), 'registered-defaults').default, 0)
        self.assertEqual(initialise((row(0, 'unknown', 'M'),), 'registered-defaults').default, 0)
        self.assertEqual(initialise((row(0, '999', 'M'),), 'registered-defaults').default, 1)

    def test_complete_prior_cache_is_retained_and_later_marker_wins(self):
        state = initialise((row(0, '8', 'M1'), row(2, 'AU', 'AU'), row(0, '74', 'M2')),
                           'registered-defaults', cache=(80,), default=8)
        self.assertEqual(state.cache, (80, 2, 1))
        self.assertEqual(state.default, 74)

    def test_cancel_does_not_finalise_or_change_rows_default_or_order(self):
        before = initialise((row(8, 'NZ', 'NZ'), row(0, '8', 'M')), 'registered-defaults')
        after, receipt = project(before, operation(cancel=True))
        self.assertEqual(after, before)
        self.assertEqual(receipt['out_result'], '0')
        self.assertFalse(receipt['marker_updated'])
        self.assertEqual(receipt['created_rows'], [])

    def test_english_cannot_be_unselected_but_cancel_can_close_empty_selection(self):
        before = initialise((), 'registered-defaults')
        with self.assertRaisesRegex(EdltError, 'English'):
            project(before, operation([8]))
        project(before, operation(cancel=True))

    def test_default_repair_chooses_first_selected_order_not_name_or_identifier(self):
        before = initialise((row(8, 'NZ', 'NZ'), row(0, '8', 'M')), 'registered-defaults')
        after, receipt = project(before, operation([74, 1, 80]))
        self.assertEqual(after.default, 74)
        self.assertEqual(after.cache, (74, 1, 80))
        self.assertEqual(after.rows[-1].name, 'German')
        self.assertTrue(receipt['default_chooses_first'])
        self.assertEqual(receipt['original_finalise_calls'], 2)
        self.assertEqual(next(r for r in after.rows if r.identifier == 0).oid, 'M')

    def test_matching_rows_and_duplicate_names_preserved_last_marker_identity_retained(self):
        before = initialise((row(0, '8', 'OLD'), row(1, 'custom English', 'E'),
                             row(8, 'custom NZ', 'NZ1'), row(8, 'second NZ', 'NZ2'),
                             row(0, '8', 'LAST')), 'registered-defaults')
        after, receipt = project(before, operation([8, 1, 202]))
        self.assertEqual([(r.identifier, r.name, r.oid) for r in after.rows],
                         [(1, 'custom English', 'E'), (8, 'custom NZ', 'NZ1'),
                          (8, 'second NZ', 'NZ2'), (0, '8', 'LAST'), (202, 'Chinese', None)])
        self.assertEqual(receipt['deleted_rows'], [row(0, '8', 'OLD').as_dict()])
        self.assertFalse(receipt['default_chooses_first'])

    def test_repeated_acceptance_removes_prior_new_row_and_keeps_marker(self):
        state = initialise((row(0, '1', 'M'), row(1, 'English', 'E')), 'registered-defaults')
        state, _ = project(state, operation([1, 8]))
        state, receipt = project(state, operation([1, 74]))
        self.assertEqual([r.identifier for r in state.rows], [0, 1, 74])
        self.assertEqual(receipt['deleted_rows'][0]['id'], 8)
        self.assertEqual(state.default, 1)

    def test_every_factory_choice_is_admitted_with_english_and_exact_name(self):
        for identifier, name in LANGUAGE_NAMES.items():
            if identifier in (0, 1): continue
            with self.subTest(identifier=identifier):
                after, _ = project(initialise((), 'registered-defaults'), operation([1, identifier]))
                self.assertEqual(next(r for r in after.rows if r.identifier == identifier).name, name)

    def test_selection_bounds_unknown_factory_bool_duplicates_and_implicit_preferences_refused(self):
        for op in (operation(), operation([1] * 2), operation([0]), operation([True]),
                   operation([255]), operation(list(range(1, 10))),
                   operation([1], preferences=[1]),
                   operation([1], preferences=[255, -1, -1, -1, -1, -1, -1, -1]),
                   {'op': 'add-language-dialog', 'selected_ids': [1]}):
            with self.subTest(op=op), self.assertRaises(EdltError): normalize(op)


if __name__ == '__main__': unittest.main()
