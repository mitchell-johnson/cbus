"""Literal SceneManager callback ordering, independent of host currency events."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_selector_control import (
    SceneSelectorControlState, normalize_events, normalize_operation,
    run_scene_selector_control,
)


def choice(identity, value, name='Duplicate'):
    return {'identity':identity, 'value':value, 'name':name, 'formatted_display':name}


def selected(event, identity, value, index=0):
    return {'event':event, 'choice_identity':identity, 'value':value, 'choice_index':index}


class Model:
    """Independent literal binding/source fixture, not a production allocator."""

    def __init__(self):
        self.scenes = {1:{'application_selector':0,'trigger_group':42,'action_selector':1,'label_value_index':0},
                       2:{'application_selector':1,'trigger_group':99,'action_selector':5,'label_value_index':2}}
        self.applications = [choice('application:0/56',0,'(P) Main'),choice('application:1/57',1,'(S) Secondary')]
        self.triggers = [choice('trigger:202/42',42),choice('trigger:202/99',99),choice('trigger:202/255',255,'Present unused')]
        self.actions = {42:[choice('action:202/42/1',1),choice('action:202/42/5',5)],
                        99:[choice('action:202/99/5',5)],255:[]}
        self.labels = {1:self.rows(42,1),2:self.rows(99,5)}
        self.calls = []
        self.fail = None

    @staticmethod
    def rows(trigger, action):
        return [{'identity':f'label:202/{trigger}/{action}/{index}', 'value':index,
                 'name':f'Label {index}', 'raw_value':f'raw{index}', 'image_present':index==1}
                for index in range(4)]

    def view(self, scene):
        return {'scene':scene, **self.scenes[scene],
                'application_choices':deepcopy(self.applications),
                'trigger_choices':deepcopy(self.triggers),
                'action_choices':deepcopy(self.actions[self.scenes[scene]['trigger_group']]),
                'dynamic_labels':deepcopy(self.labels[scene]),
                'action_selector_editable':self.scenes[scene]['action_selector']>=0}

    def bind(self, scene):
        self.calls.append(('available',scene))
        return self.view(scene)

    def trigger_current(self, scene):
        self.calls.append(('action-getter',scene))
        values = [row['value'] for row in self.actions[self.scenes[scene]['trigger_group']]]
        if self.scenes[scene]['action_selector'] not in values:
            self.scenes[scene]['action_selector'] = -1
        self.calls.append(('refresh-labels',scene,self.scenes[scene]['action_selector']))
        self.labels[scene] = self.rows(self.scenes[scene]['trigger_group'],self.scenes[scene]['action_selector']) if self.scenes[scene]['action_selector']>=0 else []
        return self.view(scene)

    def write(self, field, scene, value):
        self.calls.append(('write-'+field,scene,value))
        if self.fail == field:
            raise RuntimeError('selected callback failed')
        self.scenes[scene][field] = value
        if field == 'action_selector':
            self.calls.append(('refresh-labels',scene,value))
            self.labels[scene] = self.rows(self.scenes[scene]['trigger_group'],value)
        return self.view(scene)

    def run(self, events, *, scene=1, initial_state=None, **overrides):
        callbacks = {'bind_scene':self.bind, 'trigger_current':self.trigger_current,
            'write_application':lambda scene,value:self.write('application_selector',scene,value),
            'write_trigger':lambda scene,value:self.write('trigger_group',scene,value),
            'write_action':lambda scene,value:self.write('action_selector',scene,value),
            'write_label_index':lambda scene,value:self.write('label_value_index',scene,value)}
        callbacks.update(overrides)
        return run_scene_selector_control(events,scene=scene,initial_state=initial_state,**callbacks)


BIND = {'event':'scene-current-changed','current':True}
NONE = {'event':'scene-current-changed','current':False}


class SceneSelectorControlTests(unittest.TestCase):
    def test_scene_handler_binds_exact_source_properties_in_order(self):
        model = Model(); result = model.run([BIND])
        self.assertEqual(model.calls,[('available',1)])
        self.assertEqual([row['action'] for row in result.as_dict()['binding_callbacks']], [
            'SetControlEnabled','ClearActionBindings','ResolveAvailableActionSelectors',
            'SetActionDataSource','BindActionSelectedValue','ClearDynamicLabelBindings',
            'SetDynamicLabelDataSource','BindLabelSelectedIndex','ClearSceneNameBindings','BindSceneNameText'])
        binds = [row for row in result.as_dict()['binding_callbacks'] if row['action'].startswith('Bind')]
        self.assertEqual([(row['property'],row['update_mode'],row['formatting']) for row in binds],
                         [('ActionSelector',1,True),('LabelValueIndex',1,True),('SceneName',2,True)])
        self.assertEqual(result.state.current_scene,1)
        self.assertEqual(result.state.bound_scene,1)

    def test_no_current_disables_without_clearing_previous_direct_bindings(self):
        model = Model(); first = model.run([BIND]); disabled = model.run([NONE],scene=2,initial_state=first.state)
        self.assertIsNone(disabled.state.current_scene)
        self.assertEqual(disabled.state.bound_scene,1)
        self.assertFalse(disabled.state.controls_enabled)
        self.assertEqual([row['action'] for row in disabled.as_dict()['binding_callbacks']],['SetControlEnabled'])
        self.assertEqual(model.calls,[('available',1)])

    def test_disabled_level_handler_writes_to_stale_binding_not_enclosing_scene(self):
        model = Model(); state = model.run([BIND,NONE]).state
        result = model.run([selected('level-current-changed','action:202/42/5',5,1)],scene=2,initial_state=state)
        self.assertEqual(model.scenes[1]['action_selector'],5)
        self.assertEqual(model.scenes[2]['action_selector'],5)
        self.assertEqual(model.calls,[('available',1),('write-action_selector',1,5),('refresh-labels',1,5)])
        self.assertEqual(result.as_dict()['events'][0]['binding_actions'],['WriteValue'])
        self.assertFalse(result.state.controls_enabled)
        self.assertFalse(result.as_dict()['implicit_read_value_inferred'])

    def test_absent_level_binding_is_noop_with_or_without_selected_fact(self):
        for row in ({'event':'level-current-changed'},selected('level-current-changed','unconsumed',7)):
            with self.subTest(row=row):
                model = Model(); result = model.run([row])
                self.assertEqual(model.calls,[])
                self.assertEqual(result.as_dict()['binding_callbacks'],[])
                self.assertIsNone(result.state.bound_scene)

    def test_bound_level_handler_requires_explicit_selected_object(self):
        model = Model(); state = model.run([BIND]).state
        with self.assertRaisesRegex(EdltError,'explicit non-null'):
            model.run([{'event':'level-current-changed'}],initial_state=state)
        self.assertEqual(model.calls,[('available',1)])

    def test_null_current_application_and_trigger_parsing_is_refused(self):
        for event,identity,value in [('application-selected','application:0/56',0),('trigger-selected','trigger:202/42',42)]:
            with self.subTest(event=event):
                model = Model(); state = model.run([BIND,NONE]).state
                with self.assertRaisesRegex(EdltError,'Null-current'):
                    model.run([selected(event,identity,value)],scene=2,initial_state=state)
                self.assertEqual(model.calls,[('available',1)])

    def test_trigger_handler_no_current_is_noop_and_retains_lists(self):
        model = Model(); first = model.run([BIND,NONE])
        result = model.run([{'event':'trigger-current-changed'}],initial_state=first.state)
        self.assertEqual(first.state,result.state)
        self.assertEqual(model.calls,[('available',1)])

    def test_trigger_property_does_not_infer_current_changed_or_refresh(self):
        model = Model(); result = model.run([BIND,selected('trigger-selected','trigger:202/99',99,1)])
        self.assertEqual(model.calls,[('available',1),('write-trigger_group',1,99)])
        self.assertEqual(result.state.as_dict()['view']['action_choices'],model.actions[42])
        self.assertEqual(result.state.as_dict()['view']['dynamic_labels'],Model.rows(42,1))

    def test_trigger_handler_resolves_getter_before_refresh_and_rebinds(self):
        model = Model(); result = model.run([BIND,selected('trigger-selected','trigger:202/99',99,1),
                                          {'event':'trigger-current-changed'}])
        self.assertEqual(model.calls,[('available',1),('write-trigger_group',1,99),
                                     ('available',1),('action-getter',1),('refresh-labels',1,-1)])
        self.assertEqual(result.state.as_dict()['view']['action_choices'],model.actions[99])
        self.assertEqual(result.state.as_dict()['view']['dynamic_labels'],[])
        self.assertEqual(result.state.as_dict()['view']['action_selector'],-1)

    def test_explicit_255_trigger_object_is_not_synthetic_and_clears_actions(self):
        model = Model(); result = model.run([BIND,selected('trigger-selected','trigger:202/255',255,2),
                                          {'event':'trigger-current-changed'}])
        self.assertEqual(result.state.as_dict()['view']['action_choices'],[])
        self.assertEqual(result.state.as_dict()['view']['dynamic_labels'],[])
        model = Model(); model.triggers.pop()
        with self.assertRaises(EdltError):
            model.run([BIND,selected('trigger-selected','trigger:202/255',255,2)])
        self.assertEqual(model.calls,[('available',1)])

    def test_application_selector_is_primary_secondary_value_not_address(self):
        model = Model(); result = model.run([BIND,selected('application-selected','application:1/57',1,1)])
        self.assertEqual(model.scenes[1]['application_selector'],1)
        self.assertEqual([row['value'] for row in result.state.as_dict()['view']['application_choices']],[0,1])
        model = Model()
        with self.assertRaises(EdltError): model.run([BIND,selected('application-selected','application:0/56',56)])
        self.assertEqual(model.calls,[('available',1)])

    def test_missing_secondary_and_empty_complete_choices_refuse_without_write(self):
        model = Model(); model.applications.pop()
        with self.assertRaises(EdltError): model.run([BIND,selected('application-selected','application:1/57',1,1)])
        self.assertEqual(model.calls,[('available',1)])
        model = Model(); model.triggers = []
        with self.assertRaises(EdltError): model.run([BIND,selected('trigger-selected','trigger:202/42',42)])
        self.assertEqual(model.calls,[('available',1)])

    def test_duplicate_names_use_current_ordinal_identity_and_value(self):
        for row in (selected('action-selected','action:202/42/5',5,0),
                    selected('action-selected','action:202/42/1',5,0),
                    selected('action-selected','Duplicate',1,0),
                    selected('action-selected','action:202/42/1',1,9)):
            with self.subTest(row=row):
                model = Model()
                with self.assertRaises(EdltError): model.run([BIND,row])
                self.assertEqual(model.calls,[('available',1)])
        model = Model(); model.run([BIND,selected('action-selected','action:202/42/5',5,1)])
        self.assertIn(('write-action_selector',1,5),model.calls)

    def test_snapshot_supplier_does_not_borrow_unobserved_future_rows(self):
        model = Model(); state = model.run([BIND]).state
        model.actions[42].append(choice('action:202/42/8',8))
        with self.assertRaises(EdltError):
            model.run([selected('action-selected','action:202/42/8',8,2)],initial_state=state)
        result = model.run([{'event':'trigger-current-changed'},selected('action-selected','action:202/42/8',8,2)],initial_state=state)
        self.assertEqual(result.state.as_dict()['view']['action_selector'],8)

    def test_live_bound_collection_observer_sees_earlier_add_not_new_trigger_list(self):
        model = Model(); state = model.run([BIND]).state
        model.actions[42].append(choice('action:202/42/8',8))
        observations = []
        def observe(field, scene, trigger):
            observations.append((field,scene,trigger))
            return model.actions[trigger]
        result = model.run([selected('level-current-changed','action:202/42/8',8,2)],initial_state=state,observe_choices=observe)
        self.assertEqual(observations,[('action_choices',1,42)])
        self.assertEqual(result.state.as_dict()['view']['action_selector'],8)
        self.assertEqual(len(result.state.as_dict()['view']['action_choices']),3)
        changed = model.run([selected('trigger-selected','trigger:202/99',99,1)],initial_state=result.state)
        with self.assertRaises(EdltError):
            model.run([selected('level-current-changed','action:202/99/5',5)],initial_state=changed.state,observe_choices=observe)
        self.assertEqual(observations[-1],('action_choices',1,42))

    def test_trigger_handler_binds_before_action_getter_mutates_live_collection(self):
        model = Model(); stages = []
        def bind(scene):
            stages.append('available')
            return model.view(scene)
        def current(scene):
            stages.append('getter-refresh')
            model.actions[42].append(choice('action:202/42/9',9))
            model.scenes[1]['action_selector'] = 9
            model.labels[1] = Model.rows(42,9)
            return model.view(scene)
        result = model.run([BIND,{'event':'trigger-current-changed'}],bind_scene=bind,trigger_current=current)
        self.assertEqual(stages,['available','available','getter-refresh'])
        actions = result.as_dict()['events'][1]['binding_actions']
        self.assertEqual(actions,['ClearActionBindings','ResolveAvailableActionSelectors',
            'SetActionDataSource','BindActionSelectedValue','ActionSelectorGetterThenRefreshDynamicLables','RefreshDynamicLables'])
        self.assertEqual(result.state.as_dict()['view']['action_choices'][-1]['value'],9)

    def test_label_selected_index_binds_exact_rows_and_supports_explicit_none(self):
        model = Model(); result = model.run([BIND,{'event':'label-selected','index':1,'choice_identity':'label:202/42/1/1'}])
        self.assertEqual(model.scenes[1]['label_value_index'],1)
        self.assertTrue(result.state.as_dict()['view']['dynamic_labels'][1]['image_present'])
        cleared = model.run([{'event':'label-selected','index':-1}],initial_state=result.state)
        self.assertEqual(cleared.state.as_dict()['view']['label_value_index'],-1)
        self.assertNotIn(('action-getter',1),model.calls)

    def test_label_no_current_retains_bound_scene_but_stale_identity_refuses(self):
        model = Model(); state = model.run([BIND,NONE]).state
        result = model.run([{'event':'label-selected','index':2,'choice_identity':'label:202/42/1/2'}],scene=2,initial_state=state)
        self.assertEqual(model.scenes[1]['label_value_index'],2)
        with self.assertRaises(EdltError):
            model.run([{'event':'label-selected','index':0,'choice_identity':'label:202/99/5/0'}],initial_state=result.state)

    def test_real_scene_switch_rebinds_old_lists_and_exact_targets(self):
        model = Model(); state = model.run([BIND]).state
        result = model.run([BIND,selected('level-current-changed','action:202/99/5',5)],scene=2,initial_state=state)
        self.assertEqual(result.state.current_scene,2)
        self.assertEqual(result.state.bound_scene,2)
        self.assertEqual(result.state.as_dict()['view']['dynamic_labels'],Model.rows(99,5))
        self.assertIn(('write-action_selector',2,5),model.calls)

    def test_state_results_and_callback_views_are_detached_and_immutable(self):
        model = Model(); view = model.view(1)
        result = model.run([BIND],bind_scene=lambda scene:view)
        view['action_choices'].clear()
        detached = result.as_dict(); detached['state']['view']['action_choices'].clear()
        self.assertEqual(len(result.state.as_dict()['view']['action_choices']),2)
        with self.assertRaises(FrozenInstanceError): result.state.bound_scene = 2
        with self.assertRaises(EdltError): model.run([],initial_state=result.state.as_dict())

    def test_new_owner_and_reset_get_fresh_unbound_state_without_global_leak(self):
        first = Model(); first.run([BIND,NONE])
        second = Model(); result = second.run([{'event':'level-current-changed'}],scene=2)
        self.assertIsNone(result.state.bound_scene)
        self.assertEqual(second.calls,[])
        self.assertEqual(result.state,SceneSelectorControlState())

    def test_callback_exception_stops_without_read_following_refresh_or_replay(self):
        model = Model(); model.fail = 'trigger_group'
        with self.assertRaisesRegex(RuntimeError,'selected callback failed'):
            model.run([BIND,selected('trigger-selected','trigger:202/99',99,1),
                       {'event':'trigger-current-changed'}])
        self.assertEqual(model.calls,[('available',1),('write-trigger_group',1,99)])
        self.assertEqual(model.scenes[1]['trigger_group'],42)

    def test_invalid_shapes_fail_before_model_callbacks(self):
        malformed = [None,{},[{'event':'scene-current-changed','current':1}],
            [{'event':'level-current-changed','value':None}],
            [{'event':'label-selected','index':0}], [{'event':'label-selected','index':-1,'choice_identity':'x'}],
            [{'event':'label-selected','index':4,'choice_identity':'x'}],
            [{'event':'action-selected','value':1,'choice_index':False,'choice_identity':'x'}],
            [{'event':'application-selected','value':0,'choice_index':0,'choice_identity':'x','choices':[]}],
            [{'event':'trigger-current-changed','current':True}], [{'event':'close'}],
            [BIND]*513]
        for events in malformed:
            with self.subTest(events=events):
                model = Model()
                with self.assertRaises(EdltError): model.run(events)
                self.assertEqual(model.calls,[])

    def test_operation_cannot_inject_state_rows_or_current_scene(self):
        valid = {'op':'scene-selector-control','scene':2,'events':[BIND]}
        self.assertEqual(normalize_operation(valid),valid)
        for extra in ('state','initial_state','action_choices','bindings','current_scene'):
            with self.subTest(extra=extra), self.assertRaises(EdltError):
                normalize_operation({**valid,extra:{}})
        for scene in (True,0,9,None):
            with self.subTest(scene=scene), self.assertRaises(EdltError):
                normalize_operation({**valid,'scene':scene})

    def test_invalid_owner_view_fails_closed_without_selected_write(self):
        cases = []
        model = Model(); view = model.view(1); view.pop('action_choices'); cases.append(view)
        view = model.view(1); view['scene'] = 2; cases.append(view)
        view = model.view(1); view['action_choices'][1]['identity'] = view['action_choices'][0]['identity']; cases.append(view)
        view = model.view(1); view['dynamic_labels'][1]['value'] = 0; cases.append(view)
        for view in cases:
            with self.subTest(view=view), self.assertRaises(EdltError):
                Model().run([BIND],bind_scene=lambda scene:view)

    def test_unpaired_surrogate_owner_view_refuses_before_selected_write(self):
        model = Model()
        view = model.view(1)
        view['trigger_choices'][0]['name'] = '\ud800'
        with self.assertRaisesRegex(EdltError, 'JSON-compatible'):
            model.run([BIND, selected('trigger-selected', 'trigger:202/99', 99, 1)],
                      bind_scene=lambda scene: view)
        self.assertEqual(model.calls, [])
        self.assertEqual(model.scenes[1]['trigger_group'], 42)


if __name__ == '__main__':
    unittest.main()
