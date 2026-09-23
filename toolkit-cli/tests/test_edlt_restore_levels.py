"""Preset controls: original event coupling, phase preservation and failures."""
from dataclasses import replace
import unittest

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_lifecycle import LifecycleMetadataError
from cbus_toolkit.edlt_restore_levels import EdltRestoreLevels, RestoreLevelCache, FORMAT
from cbus_toolkit.unitspec import ParameterSpec
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import fixture as lifecycle_fixture, cache, scene_values


def fixture():
    spec = lifecycle_fixture(); parameters = dict(spec.parameters)
    parameters['EnableLevelStore'] = ParameterSpec('EnableLevelStore', 'bit', 'synthetic.xml',
        {'Name': 'EnableLevelStore', 'Type': 'bit', 'Address': '0x116', 'BitAddress': '1',
         'BitSize': '1', 'DefaultValue': '0'})
    return replace(spec, parameters=parameters)


def metadata(editor, source, mode='complete'):
    facts = cache(editor.lifecycle, source, mode)
    return {'format': FORMAT, 'lifecycle': facts,
            'applications': [{'application': a, 'name': 'Same application' if mode == 'duplicate-app-groups'
                              else 'Owned application' + str(a)} for a in facts['applications']],
            'groups': [{'application': r['application'], 'group': r['group'],
                        'name': 'Same group' if mode.startswith('duplicate-') else 'Owned group' + str(r['group'])}
                       for r in facts['groups'] if r['exists']]}


class RestoreLevelTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltRestoreLevels(self.spec); self.session = Session(self.spec)
        self.source = self.editor.snapshot(self.session.values())
        self.source.update({'NavWidgetType': (1,), 'Widget6WidgetType': (2,),
            'Widget6WidgetByteValue6': (42,), 'Widget6RestoreLevel': (73,),
            'Widget7WidgetType': (3,), 'Widget7WidgetByteValue6': (42,), 'Widget7RestoreLevel': (17,),
            'Widget8WidgetType': (4,), 'Widget8WidgetByteValue6': (12,), 'Widget8RestoreLevel': (83,),
            'Widget9WidgetType': (5,), 'Widget9WidgetByteValue1': (128,),
            'Widget9WidgetByteValue6': (42,), 'Widget9RestoreLevel': (93,)})

    def plan(self, source=None, mode='complete', **options):
        source = self.source if source is None else source
        return self.editor.plan(source, metadata=metadata(self.editor, source, mode), **options)

    def test_linked_event_uses_display_names_across_types_and_addresses(self):
        plan = self.plan(widget=6, level=42)
        self.assertEqual(plan.as_dict()['event_target_widgets'], [6, 7])
        self.assertEqual(plan.after_controls['Widget7RestoreLevel'], (42,))
        self.assertEqual(plan.after_controls['Widget9RestoreLevel'], (93,))
        self.assertEqual(self.plan(mode='duplicate-groups', widget=6, level=42).as_dict()['event_target_widgets'], [6, 7, 8])
        self.assertEqual(self.plan(mode='duplicate-app-groups', widget=6, level=42).as_dict()['event_target_widgets'], [6, 7, 8, 9])
        controls = plan.as_dict()['controls']
        self.assertTrue(controls[0]['visible']); self.assertFalse(controls[1]['visible'])

    def test_same_value_does_not_propagate_even_when_synchronise_checked(self):
        plan = self.plan(widget=6, level=73, synchronise=True)
        self.assertFalse(plan.as_dict()['changed_event_fired'])
        self.assertEqual(plan.after_controls['Widget7RestoreLevel'], (17,))

    def test_sync_updates_all_constructed_controls_and_save_resets_new_terminator(self):
        plan = self.plan(widget=6, level=42, synchronise=True)
        self.assertEqual(plan.as_dict()['event_target_widgets'], list(range(6, 22)))
        self.assertEqual([plan.after_controls[f'Widget{i}RestoreLevel'] for i in range(6, 22)], [(42,)] * 16)
        self.assertEqual(plan.before_save['Widget10WidgetType'], (255,))
        self.assertEqual(plan.before_save['Widget10RestoreLevel'], (0,))
        self.assertEqual(plan.before_save['Widget21RestoreLevel'], (42,))

    def test_page_and_restore_mode_determine_editable_representatives(self):
        for opts in ({'widget': 7, 'level': 42}, {'widget': 6, 'level': 42, 'restore_mode': 'previous'}):
            with self.assertRaisesRegex(EdltError, 'hidden'): self.plan(**opts)
        source = {**self.source, 'Widget10WidgetType': (0,), 'Widget11WidgetType': (2,),
                  'Widget11WidgetByteValue6': (1,), 'NavWidgetType': (0,)}
        with self.assertRaisesRegex(EdltError, 'hidden'): self.plan(source, widget=11, level=42)
        plan = self.plan(source, widget=11, level=42, page_mode='multiple')
        self.assertEqual(plan.after_controls['Widget11RestoreLevel'], (42,))
        plan = self.plan({**self.source, 'EnableLevelStore': (1,)}, widget=6, level=42, restore_mode='preset')
        self.assertEqual(plan.after_controls['EnableLevelStore'], (0,))
        self.assertEqual(self.plan({**self.source, 'NavWidgetType': (255,)}).after_controls['NavWidgetType'], (0,))

    def test_save_composition_preserves_resolved_scenes_mra_and_raw_text(self):
        source = {**self.source, **scene_values((0xfb, 1, 42, 2, 26), ((0xf1, 12, 123),)),
                  'Widget2WidgetType': (7,), 'Widget2WidgetByteValue1': (0xed,),
                  'Widget8WidgetType': (8,), 'Widget8WidgetByteValue1': (0x12,),
                  'StaticTextString0': tuple(b'\xff\xfe\0'.ljust(64, b'\0'))}
        plan = self.plan(source, widget=6, level=254, synchronise=True)
        base = self.editor.lifecycle.plan(source, metadata=metadata(self.editor, source)['lifecycle'])
        for name in ('SceneBucket', 'SceneCount', 'Widget8WidgetByteValue1', 'StaticTextString0'):
            self.assertEqual(plan.before_save[name], base.before_save[name])
        self.assertEqual(plan.before_save['SceneBucket'][:8], (3, 1, 42, 2, 26, 17, 12, 123))
        final = {**source, **plan.changes}
        self.assertEqual({k: final[k] for k in self.editor.crcs(final)}, self.editor.crcs(final))

    def test_cache_rejects_unknown_absent_groups_and_missing_names_before_io(self):
        facts = metadata(self.editor, self.source)
        for bad in ({**facts, 'groups': []},
                    {**facts, 'applications': []},
                    {**facts, 'lifecycle': {**facts['lifecycle'], 'groups': []}, 'groups': []}):
            with self.assertRaises(LifecycleMetadataError): self.editor.plan(self.source, metadata=bad)
        with self.assertRaisesRegex(LifecycleMetadataError, 'explicitly present'):
            self.plan({**self.source, 'Widget6WidgetByteValue6': (99,)})
        for bad in ({**facts, 'extra': True}, {**facts, 'groups': facts['groups'] * 2},
                    {**facts, 'applications': [{'application': True, 'name': 'bad'}]},
                    {**facts, 'groups': [{**facts['groups'][0], 'name': 1}]}):
            with self.assertRaises(EdltError): RestoreLevelCache.from_dict(bad)
        self.assertFalse(self.session.calls)

    def test_argument_validation_and_layout(self):
        for options in ({'widget': 6}, {'level': 1}, {'widget': True, 'level': 1},
                        {'widget': 5, 'level': 1}, {'widget': 6, 'level': -1},
                        {'widget': 6, 'level': 256}, {'synchronise': 1},
                        {'synchronise': True}, {'page_mode': 'wrong'}, {'restore_mode': 'wrong'}):
            with self.assertRaises(EdltError): self.plan(**options)
        params = dict(self.spec.parameters)
        params['EnableLevelStore'] = replace(params['EnableLevelStore'], fields={**params['EnableLevelStore'].fields, 'BitAddress': '2'})
        with self.assertRaisesRegex(EdltError, 'layout'): EdltRestoreLevels(replace(self.spec, parameters=params))

    def test_canonical_plan_stale_guard_and_native_staging(self):
        plan = self.plan(widget=6, level=42); self.session.current = dict(self.source)
        for bad in (replace(plan, evidence='{}'), replace(plan, changes={}),
                    replace(plan, after_controls={**plan.after_controls, 'Widget6RestoreLevel': (True,)})):
            with self.assertRaises(EdltError): self.editor.apply(self.session, bad)
        self.assertFalse(self.session.calls)
        self.session.current['Widget6RestoreLevel'] = (17,)
        with self.assertRaisesRegex(EdltError, 'changed'): self.editor.apply(self.session, plan)
        self.session.current = dict(self.source)
        result = self.editor.apply(self.session, plan)
        self.assertTrue(result['verified']); self.assertFalse(result['saved'])
        self.assertEqual(self.editor.snapshot(self.session.values()), {**self.source, **plan.changes})

    def test_write_failure_rolls_back_and_interruption_is_not_replayed(self):
        plan = self.plan(widget=6, level=42); self.session.current = dict(self.source)
        self.session.failure = 'Widget6RestoreLevel'
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertFalse(caught.exception.rollback_errors)
        self.assertEqual(self.editor.snapshot(self.session.values()), self.source)
        class InterruptedSession(Session):
            def set(self, name, value):
                super().set(name, value); raise KeyboardInterrupt()
        session = InterruptedSession(self.spec); session.current = dict(self.source)
        with self.assertRaises(KeyboardInterrupt) as caught: self.editor.apply(session, plan)
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(caught.exception.edlt_restore_levels_evidence['pp_state_uncertain'])

    def test_rollback_interrupt_survives_unprintable_primary_error(self):
        class UnprintableError(Exception):
            def __str__(self): raise SystemExit('secondary formatting failure')
        class InterruptedRollback(Session):
            def set(self, name, value):
                super().set(name, value)
                if len(self.calls) == 1: raise UnprintableError()
                raise KeyboardInterrupt('original rollback interruption')
        plan = self.plan(widget=6, level=42); session = InterruptedRollback(self.spec)
        session.current = dict(self.source)
        with self.assertRaises(KeyboardInterrupt) as caught: self.editor.apply(session, plan)
        evidence = caught.exception.edlt_restore_levels_evidence
        self.assertEqual(evidence['original_error']['type'], 'UnprintableError')
        self.assertEqual(evidence['original_error']['error'], '<unprintable UnprintableError>')
        self.assertEqual(len(session.calls), 2)


if __name__ == '__main__': unittest.main()
