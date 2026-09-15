"""Optional original numeric locales in retained preference control plans."""
import json
from pathlib import Path
import unittest

from cbus_toolkit.toolkit_preferences_controls import ToolkitPreferenceControls, plan_preferences_save
from cbus_toolkit.toolkit_numeric import UnsupportedToolkitNumericInput
from test_toolkit_preferences_controls import initial, display

ROOT=Path(__file__).resolve().parents[1]


class NumericPreferenceControlTests(unittest.TestCase):
    def test_all66_original_validator_outcomes_feed_save_assignments(self):
        cases=json.loads((ROOT/'research/fixtures/toolkit-numeric-validation-vectors.json').read_text())['cases']
        self.assertEqual(len(cases),66)
        for row in cases:
            locale=(row['decimal_separator'],row['thousands_separator'])
            editor=ToolkitPreferenceControls(initial(),display(),numeric_locale=locale)
            before=editor.as_dict()
            with self.subTest(text=row['input'],locale=locale):
                if not row['accepted']:
                    with self.assertRaises(ValueError): editor.set_control('cmbJavaHeapMax',row['input'])
                    self.assertEqual(editor.as_dict(),before)
                else:
                    editor.set_control('cmbJavaHeapMax',row['input'])
                    plan=editor.plan_save()
                    expected=row['converted_integers'][-1]
                    self.assertEqual(dict(plan.values)['JavaHeapMax'],expected)
                    self.assertEqual(dict(plan.values)['JavaHeapMin'],32)
                    self.assertEqual(plan.heap_conversion.value,expected)
                    self.assertEqual(editor.controls['cmbJavaHeapMax'],row['input'])
                    self.assertEqual(plan.as_dict()['numeric_locale'],list(locale))
                    self.assertEqual(len(plan.assignments),19)
                    untouched=set(initial())-set(dict(plan.assignments))
                    self.assertEqual({n:dict(plan.values)[n] for n in untouched},{n:initial()[n] for n in untouched})

    def test_explicit_locale_changes_decimal_interpretation(self):
        for locale,value in [(('.',','),64),((',','.'),645)]:
            editor=ToolkitPreferenceControls(initial(),display(),numeric_locale=locale)
            editor.set_control('cmbJavaHeapMax','64.5')
            result=editor.plan_save().as_dict()
            self.assertEqual(result['values']['JavaHeapMax'],value)
            self.assertEqual(result['heap_conversion']['value'],value)
            self.assertFalse(result['storage_applied'])

    def test_default_canonical_contract_is_unchanged(self):
        editor=ToolkitPreferenceControls(initial(),display())
        for value in ('6A4','64.5',' 64','--64','9e99','4294967360'):
            with self.assertRaises(ValueError): editor.set_control('cmbJavaHeapMax',value)
        editor.set_control('cmbJavaHeapMax','64')
        plan=editor.plan_save().as_dict()
        self.assertNotIn('numeric_locale',plan);self.assertNotIn('heap_conversion',plan)

    def test_int32_wrap_is_reported_and_int64_overflow_remains_unsupported(self):
        editor=ToolkitPreferenceControls(initial(),display(),numeric_locale=('.',','))
        editor.set_control('cmbJavaHeapMax','4294967360')
        plan=editor.plan_save()
        self.assertEqual(dict(plan.values)['JavaHeapMax'],64)
        self.assertTrue(plan.heap_conversion.int32_wrapped)
        before=editor.as_dict()
        with self.assertRaises(UnsupportedToolkitNumericInput):editor.set_control('cmbJavaHeapMax','9223372036854775808')
        self.assertEqual(editor.as_dict(),before)

    def test_bad_locale_and_unsupported_inputs_precede_control_mutation(self):
        for locale in ('dot',['.',','],('.', '.'),(',',','),('',','),(True,False)):
            with self.assertRaises(ValueError):ToolkitPreferenceControls(initial(),display(),numeric_locale=locale)
        editor=ToolkitPreferenceControls(initial(),display(),numeric_locale=('.',','))
        for text in ('６４','64\0','1'*65,True,64):
            before=editor.as_dict()
            with self.assertRaises(ValueError):editor.set_control('cmbJavaHeapMax',text)
            self.assertEqual(editor.as_dict(),before)
        getters=dict(editor.controls)
        getters['cmbJavaHeapMax']='6A4'
        plan=plan_preferences_save(initial(),getters,display(),numeric_locale=('.',','))
        self.assertEqual(dict(plan.values)['JavaHeapMax'],64)
        with self.assertRaises(ValueError):plan_preferences_save(initial(),getters,display())


if __name__=='__main__':unittest.main()
