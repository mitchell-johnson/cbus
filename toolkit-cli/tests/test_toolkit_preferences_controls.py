import copy
import hashlib
import json
from pathlib import Path
import unittest

from cbus_toolkit.toolkit_preferences_controls import (
    BOOLEAN_CONTROLS, DISPLAY_NAMES, SAVE_CONTROLS,
    ToolkitPreferenceControls, canonical_java_heap, plan_preferences_save,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/toolkit-preferences-controls-vectors.json'
EXPECTED_SHA = 'afc5e844408d5296d8f43874acab5f6a4a360d629e398cc9d8232cae8d176f0a'


def vectors():
    data = FIXTURE.read_bytes()
    if hashlib.sha256(data).hexdigest() != EXPECTED_SHA:
        raise AssertionError('Original preferences vector evidence changed')
    return json.loads(data)


def initial():
    return {**vectors()['initial_values_fixture'], 'JavaHeapMax': 256, 'FeedbackLogSize': 200}


def display(): return dict.fromkeys(DISPLAY_NAMES, False)


class PreferenceControlsTests(unittest.TestCase):
    def test_original_load_48_cases_and_original_spin_clamp(self):
        v = vectors()
        for row in v['load']:
            with self.subTest(row['name']):
                source = {**v['initial_values_fixture'], **row['settings_fixture']}
                editor = ToolkitPreferenceControls(source,
                    {**display(), **{k:bool(n) for k,n in row['display_fixture'].items()}})
                controls = dict(editor.controls)
                for name, value in row['assigned_control_values'].items():
                    if name in BOOLEAN_CONTROLS: value = bool(value)
                    elif name == 'spnFeedbackLogSize': value = int(value)
                    self.assertEqual(controls[name], value, name)
                self.assertEqual(editor.application_log_enabled, row['application_log_enabled'])
                self.assertEqual(source, {**v['initial_values_fixture'], **row['settings_fixture']})

    def test_original_ok_handler_assignments_and_21_unrelated_values(self):
        v = vectors()
        for row in v['save']:
            if not row['validation_result']: continue
            with self.subTest(row['name']):
                source = dict(v['initial_values_fixture'])
                source['Default Language 8'] = 1033
                source['Default CNI Address'] = 'retained.example'
                getters = {name:False for name in BOOLEAN_CONTROLS}
                getters.update(cmbTemperatureUnit=0, cmbJavaHeapMax='256', spnFeedbackLogSize=100)
                getters.update(row['input'])
                for name in set(getters) & set(BOOLEAN_CONTROLS): getters[name] = bool(getters[name])
                plan = plan_preferences_save(source, getters, display())
                self.assertEqual(dict(plan.assignments), row['assignments'])
                self.assertEqual(plan.feedback_log_enabled, bool(row['feedback_log_enabled']))
                self.assertEqual([plan.feedback_size_argument], row['size_arguments'])
                after = dict(plan.values)
                untouched = set(source) - set(row['assignments'])
                self.assertEqual(len(untouched), 21)
                self.assertEqual({k:after[k] for k in untouched}, {k:source[k] for k in untouched})
                self.assertFalse(plan.as_dict()['storage_applied'])

    def test_load_change_port_original_event_and_disabled_application_log(self):
        e = ToolkitPreferenceControls(initial(), display())
        e.set_control('chkLoadChangePort', False)
        self.assertFalse(e.application_log_enabled)
        self.assertFalse(e.controls['chkApplicationLog'])
        self.assertEqual(e.message_resource_ids, (0xb054,))
        before = e.as_dict()
        with self.assertRaisesRegex(ValueError, 'disabled'):
            e.set_control('chkApplicationLog', True)
        self.assertEqual(e.as_dict(), before)
        e.set_control('chkLoadChangePort', True)
        self.assertTrue(e.controls['chkApplicationLog'])
        self.assertTrue(e.application_log_enabled)
        e.set_control('chkApplicationLog', False)
        self.assertTrue(dict(e.plan_save().values)['ApplicationLogDisable'])

    def test_original_tag_and_sort_events_in_supported_selection_domain(self):
        events = vectors()['events']
        for row in events:
            operation = row['operation']
            names = {'tag-standard':'rdoTagNamesStandard', 'tag-hex':'rdoTagNamesUseHex',
                     'tag-value':'rdoTagNamesUseValue', 'sort-applications':'rgSortApplications',
                     'sort-groups':'rgSortGroups', 'sort-levels':'rgSortLevels'}
            if operation not in names: continue
            name = names[operation]
            value = row['initial_nonzero_controls'].get(name, 0) if operation.startswith('sort-') else True
            if operation.startswith('sort-') and value not in (0, 1): continue
            with self.subTest(operation=operation, value=value):
                globals_ = {**display(), **{k:bool(n) for k,n in row['initial_globals'].items()}}
                e = ToolkitPreferenceControls(initial(), globals_).set_control(name, value)
                self.assertEqual(dict(e.display_values), {k:bool(n) for k,n in row['final_globals'].items()})

    def test_shutdown_priority_and_ordered_selection(self):
        e = ToolkitPreferenceControls({**initial(), 'CGateShutdownOnExitAsk':True,
             'CGateShutdownOnExit':True, 'CloseProjectsOnExit':True}, display())
        self.assertTrue(e.controls['rdbShutdownAsk'])
        self.assertFalse(e.controls['chkShutdownCGate'])
        e.set_control('chkShutdownCGate', False)
        self.assertTrue(e.controls['rdbCloseProjects'])
        self.assertFalse(e.controls['rdbShutdownAsk'])
        e.set_control('chkShutdownCGate', True)
        e.set_control('rdbDoNothing', True)
        self.assertFalse(e.controls['chkShutdownCGate'])
        values = dict(e.plan_save().values)
        self.assertFalse(values['CloseProjectsOnExit'])
        self.assertFalse(values['CGateShutdownOnExit'])
        self.assertFalse(values['CGateShutdownOnExitAsk'])

    def test_unit_selection_overrides_and_remember_normalization(self):
        e = ToolkitPreferenceControls({**initial(), 'UnitDialogOverride':False,
             'UnitDialogModeAdvanced':True}, display())
        self.assertTrue(e.controls['rdbUnitRemember'])
        self.assertFalse(dict(e.plan_save().values)['UnitDialogModeAdvanced'])
        for selection, override, advanced in [('rdbUnitAdvanced',True,True),
                ('rdbUnitSimple',True,False), ('rdbUnitRemember',False,False)]:
            e.set_control(selection, True)
            plan = dict(e.plan_save().values)
            self.assertEqual((plan['UnitDialogOverride'],plan['UnitDialogModeAdvanced']), (override,advanced))

    def test_strict_java_heap_domain_and_invalid_loaded_value(self):
        for value in ('64', '256', '9999'): self.assertEqual(canonical_java_heap(value), int(value))
        for value in ('', '0', '63', '10000', '064', ' 64', '64.0', '6A4', '9e99', '６４', '64\0', 256, True):
            with self.subTest(value=value), self.assertRaises(ValueError): canonical_java_heap(value)
        e = ToolkitPreferenceControls({**initial(), 'JavaHeapMax':0}, display())
        before = e.as_dict()
        with self.assertRaises(ValueError): e.plan_save()
        self.assertEqual(e.as_dict(), before)
        e.set_control('cmbJavaHeapMax', '64')
        self.assertEqual(dict(e.plan_save().values)['JavaHeapMin'], 32)

    def test_spin_selection_clamps_and_serialized_plan_is_detached(self):
        e = ToolkitPreferenceControls(initial(), display())
        for value, wanted in [(-2**31,100),(100,100),(200,200),(9900,9900),(2**31-1,9900)]:
            e.set_control('spnFeedbackLogSize', value)
            plan = e.plan_save()
            self.assertEqual(dict(plan.values)['FeedbackLogSize'], wanted)
            self.assertEqual(plan.feedback_size_argument, wanted*1000)
        rendered = plan.as_dict();rendered['values']['JavaHeapMax'] = 1
        self.assertEqual(dict(plan.values)['JavaHeapMax'], 256)
        with self.assertRaises(TypeError): e.controls['chkFeedbackLog'] = True

    def test_order_matters_for_load_port_and_application_log(self):
        a = ToolkitPreferenceControls(initial(), display())
        a.set_control('chkApplicationLog', False).set_control('chkLoadChangePort', True)
        b = ToolkitPreferenceControls(initial(), display())
        b.set_control('chkLoadChangePort', True).set_control('chkApplicationLog', False)
        self.assertFalse(dict(a.plan_save().values)['ApplicationLogDisable'])
        self.assertTrue(dict(b.plan_save().values)['ApplicationLogDisable'])

    def test_invalid_operations_leave_state_unchanged(self):
        e = ToolkitPreferenceControls(initial(), display())
        for name,value in [('unknown',True), ('chkFeedbackLog',1), ('rdbDoNothing',False),
                ('rgSortGroups',2), ('rgSortGroups',True), ('spnFeedbackLogSize',2**31),
                ('cmbJavaHeapMax','+64'), ('cmbTemperatureUnit',-1)]:
            before = e.as_dict()
            with self.subTest(name=name,value=value), self.assertRaises(ValueError): e.set_control(name,value)
            self.assertEqual(e.as_dict(),before)

    def test_input_type_missing_and_unknown_field_rejections(self):
        for source in [{}, {**initial(), 'JavaHeapMin':True}, {**initial(),'invented':False}]:
            with self.assertRaises(ValueError): ToolkitPreferenceControls(source, display())
        for d in [{}, {**display(),'sort_groups':2}, {**display(),'extra':False}]:
            with self.assertRaises(ValueError): ToolkitPreferenceControls(initial(),d)
        c = dict(ToolkitPreferenceControls(initial(),display()).controls)
        for bad in [{k:v for k,v in c.items() if k!='chkFeedbackLog'}, {**c,'invented':False},
                    {**c,'spnFeedbackLogSize':True}, {**c,'cmbTemperatureUnit':2**31}]:
            with self.assertRaises(ValueError): plan_preferences_save(initial(),bad,display())

    def test_retained_inputs_are_copied(self):
        source, d = initial(), display()
        e = ToolkitPreferenceControls(source,d)
        source['Default Language 8'] = 77;d['sort_groups'] = True
        plan=e.plan_save()
        self.assertNotEqual(dict(plan.values)['Default Language 8'],77)
        self.assertFalse(dict(plan.display_values)['sort_groups'])


if __name__ == '__main__': unittest.main()
