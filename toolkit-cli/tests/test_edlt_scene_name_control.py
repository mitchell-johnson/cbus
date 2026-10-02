"""Literal ComboBoxStaticText callbacks, independent of a GUI or allocator."""
from dataclasses import FrozenInstanceError
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_name_control import (
    SceneNameControlState, normalize_events, normalize_operation,
    run_scene_name_control,
)


class Binding:
    def __init__(self, name='Old', transform=lambda text: text):
        self.name = name
        self.calls = []
        self.transform = transform
        self.allocation = {'index': 62, 'reused': False}

    def read(self):
        self.calls.append(('read', self.name))
        return self.name

    def write(self, text):
        self.calls.append(('write', text))
        self.name = self.transform(text)
        return self.allocation

    def run(self, events, **kwargs):
        return run_scene_name_control(events, get_name=self.read, set_name=self.write,
                                      known_names=('Old', 'Known', 'é', 'A' * 64), **kwargs)


def refresh(**kwargs):
    return {'event': 'list-refresh', 'change_type': 'item-changed',
            'new_index': 0, 'old_index': -1, 'selected_index': 2, **kwargs}


class SceneNameControlTests(unittest.TestCase):
    def test_input_alone_is_pending_and_never_changes_binding(self):
        model = Binding()
        result = model.run([{'event': 'input', 'text': 'New'}])
        self.assertEqual(model.name, 'Old')
        self.assertEqual(model.calls, [('read', 'Old')])
        self.assertEqual(result.state, SceneNameControlState('New', True, False))
        self.assertEqual(result.as_dict()['binding_callbacks'], [])
        self.assertFalse(result.as_dict()['implicit_close_inferred'])

    def test_enter_and_leave_write_then_read_actual_property(self):
        for event in ('enter', 'leave'):
            with self.subTest(event=event):
                model = Binding(transform=lambda value: f'bound:{value}')
                result = model.run([{'event': 'input', 'text': 'New'}, {'event': event}])
                self.assertEqual(model.calls, [('read', 'Old'), ('write', 'New'), ('read', 'bound:New')])
                self.assertEqual(result.state, SceneNameControlState('bound:New'))
                self.assertEqual([x['action'] for x in result.as_dict()['binding_callbacks']],
                                 ['WriteValue', 'ReadValue'])

    def test_pending_continuation_resolves_with_one_explicit_commit(self):
        model = Binding()
        pending = model.run([{'event': 'input', 'text': 'New'}])
        result = model.run([{'event': 'enter'}, {'event': 'close'}], initial_state=pending.state)
        self.assertEqual(model.name, 'New')
        self.assertFalse(result.state.pending)
        self.assertTrue(result.as_dict()['closed'])
        self.assertEqual([x for x in model.calls if x[0] == 'write'], [('write', 'New')])

    def test_all_four_arrows_suppress_one_selection_across_operations(self):
        for key in ('left', 'right', 'up', 'down'):
            with self.subTest(key=key):
                model = Binding()
                first = model.run([{'event': 'arrow-preview', 'key': key}])
                suppressed = model.run([{'event': 'selected-name', 'selected_index': 7, 'name': 'Known'}],
                                       initial_state=first.state)
                self.assertEqual(model.name, 'Old')
                self.assertEqual(suppressed.state, SceneNameControlState('Known', True, False))
                self.assertTrue(suppressed.as_dict()['events'][0]['selection_write_suppressed'])
                result = model.run([{'event': 'selected-name', 'selected_index': 7, 'name': 'Known'}],
                                   initial_state=suppressed.state)
                self.assertEqual(result.state, SceneNameControlState('Known'))
                self.assertEqual([x for x in model.calls if x[0] == 'write'], [('write', 'Known')])

    def test_suppression_is_consumed_even_without_source_or_selection(self):
        for row in ({'event': 'selected-name', 'selected_index': -1},
                    {'event': 'selected-name', 'selected_index': 0, 'data_source_present': False}):
            with self.subTest(row=row):
                model = Binding()
                result = model.run([{'event': 'arrow-preview', 'key': 'up'}, row,
                                    {'event': 'selected-name', 'selected_index': 4, 'name': 'Known'}])
                self.assertFalse(result.state.suppress_next_selection)
                self.assertEqual([x for x in model.calls if x[0] == 'write'], [('write', 'Known')])

    def test_selection_no_op_predicates_and_handler_rebinding(self):
        rows = [
            {'event': 'selected-name', 'selected_index': -1},
            {'event': 'selected-name', 'selected_index': 0, 'data_source_present': False},
            {'event': 'selected-name', 'selected_index': 0, 'name': 'Known', 'binding_present': False},
            {'event': 'selected-name', 'selected_index': -1, 'data_manager_present': False},
        ]
        for row in rows:
            with self.subTest(row=row):
                model = Binding()
                result = model.run([row]).as_dict()
                self.assertEqual(model.name, 'Old')
                self.assertEqual(result['binding_callbacks'], [])
                self.assertEqual(result['events'][0]['list_change_handler_rebound'],
                                 row.get('data_manager_present', True))

    def test_known_selection_is_ordinal_and_never_infers_sorted_index(self):
        model = Binding()
        model.run([{'event': 'selected-name', 'selected_index': 99, 'name': 'Known'}])
        self.assertEqual(model.name, 'Known')
        for name in ('known', 'e\u0301', 'Unknown'):
            with self.subTest(name=name):
                model = Binding()
                with self.assertRaises(EdltError):
                    model.run([{'event': 'selected-name', 'selected_index': 0, 'name': name}])
                self.assertEqual([x for x in model.calls if x[0] == 'write'], [])

    def test_selection_reads_live_known_names_after_prior_property_assignment(self):
        model = Binding()
        names = ['Old']
        def write(text):
            names[:] = [text]
            return model.write(text)
        result = run_scene_name_control([
            {'event': 'input', 'text': 'New'}, {'event': 'enter'},
            {'event': 'selected-name', 'selected_index': 7, 'name': 'New'},
        ], get_name=model.read, set_name=write, known_names=names)
        self.assertEqual(result.state.text, 'New')
        self.assertEqual([x for x in model.calls if x[0] == 'write'],
                         [('write', 'New'), ('write', 'New')])

    def test_list_read_discards_pending_without_committing(self):
        model = Binding()
        result = model.run([{'event': 'input', 'text': 'Discarded'}, refresh()])
        self.assertEqual(model.name, 'Old')
        self.assertEqual(result.state, SceneNameControlState('Old'))
        self.assertEqual(result.as_dict()['binding_callbacks'], [
            {'event_index': 1, 'event': 'list-refresh', 'action': 'ReadValue', 'text': 'Old'}])

    def test_list_refresh_uses_both_exact_index_branches(self):
        cases = [
            ({'new_index': 1, 'old_index': -1}, True),
            ({'new_index': 3, 'old_index': 1}, True),
            ({'new_index': 3, 'old_index': -1}, False),
            ({'new_index': 2, 'old_index': 2}, False),
            ({'new_index': -1, 'old_index': -1, 'selected_index': 0}, True),
            ({'new_index': -1, 'old_index': -1, 'selected_index': -1}, False),
        ]
        for facts, read in cases:
            with self.subTest(facts=facts):
                model = Binding()
                result = model.run([{'event': 'input', 'text': 'Pending'}, refresh(**facts)])
                self.assertEqual(result.state.pending, not read)
                self.assertEqual(len(result.as_dict()['binding_callbacks']), int(read))

    def test_only_relevant_visible_enabled_bound_list_changes_read(self):
        cases = [({}, True), ({'change_type': 'reset'}, True),
                 ({'change_type': 'item-added'}, True),
                 ({'change_type': 'item-deleted'}, False),
                 ({'change_type': 'item-moved'}, False),
                 ({'change_type': 'property-descriptor-changed'}, False),
                 ({'visible': False}, False), ({'list_updates_disabled': True}, False),
                 ({'binding_present': False}, False)]
        for facts, read in cases:
            with self.subTest(facts=facts):
                model = Binding()
                result = model.run([{'event': 'input', 'text': 'Pending'}, refresh(**facts)])
                self.assertEqual(len(result.as_dict()['binding_callbacks']), int(read))
                self.assertEqual([x for x in model.calls if x[0] == 'write'], [])

    def test_disabled_list_flag_precedes_async_branch(self):
        model = Binding()
        result = model.run([refresh(list_updates_disabled=True, invoke_required=True)])
        self.assertEqual(result.as_dict()['binding_callbacks'], [])
        with self.assertRaisesRegex(EdltError, 'Asynchronous'):
            model.run([refresh(invoke_required=True)])

    def test_missing_enter_or_leave_binding_preserves_pending(self):
        for event in ('enter', 'leave'):
            with self.subTest(event=event):
                model = Binding()
                result = model.run([{'event': 'input', 'text': 'Pending'},
                                    {'event': event, 'binding_present': False}])
                self.assertTrue(result.state.pending)
                self.assertEqual(model.calls, [('read', 'Old')])

    def test_whitespace_is_passed_verbatim_to_property_callback(self):
        for text in ('', ' \t\u00a0', '\u001c', '\u180e', '\u200b', '\ufeff'):
            with self.subTest(text=repr(text)):
                model = Binding()
                model.run([{'event': 'input', 'text': text}, {'event': 'enter'}])
                self.assertEqual(model.name, text)
                self.assertEqual([x for x in model.calls if x[0] == 'write'], [('write', text)])

    def test_input_limit_is_utf16_not_utf8_and_getters_are_not_rebounded(self):
        for text in ('A' * 64, 'ā' * 64, '😀' * 32):
            with self.subTest(text=text):
                model = Binding()
                self.assertEqual(model.run([{'event': 'input', 'text': text}]).state.text, text)
        for text in ('A' * 65, '😀' * 33, '\ud800', '\udfff'):
            with self.subTest(text=repr(text)), self.assertRaises(EdltError):
                normalize_events([{'event': 'input', 'text': text}])
        model = Binding('A' * 65)
        self.assertEqual(model.run([]).state.text, 'A' * 65)

    def test_host_input_nul_is_refused_without_conflating_property_getter(self):
        for event in ({'event': 'input', 'text': 'A\0B'},
                      {'event': 'selected-name', 'selected_index': 0, 'name': 'A\0B'}):
            with self.subTest(event=event):
                model = Binding('A\0B')
                with self.assertRaisesRegex(EdltError, 'host-text'):
                    model.run([event])
                self.assertEqual(model.calls, [])
        model = Binding('A\0B')
        self.assertEqual(model.run([]).as_dict()['bound_name'], 'A\0B')

    def test_repeated_commits_always_write_read_even_equal_name(self):
        model = Binding()
        result = model.run([{'event': 'enter'}, {'event': 'leave'}])
        self.assertEqual([x['action'] for x in result.as_dict()['binding_callbacks']],
                         ['WriteValue', 'ReadValue', 'WriteValue', 'ReadValue'])
        self.assertFalse(result.state.pending)

    def test_failed_setter_is_not_followed_by_read_or_retry(self):
        model = Binding()
        def fail(text):
            model.calls.append(('failed-write', text))
            raise EdltError('Property capacity refusal')
        with self.assertRaisesRegex(EdltError, 'capacity'):
            run_scene_name_control([{'event': 'enter'}], get_name=model.read,
                                   set_name=fail, known_names=('Old',))
        self.assertEqual(model.calls, [('read', 'Old'), ('failed-write', 'Old')])

    def test_pending_close_refuses_and_clean_close_has_no_callback(self):
        model = Binding()
        with self.assertRaisesRegex(EdltError, 'Pending'):
            model.run([{'event': 'input', 'text': 'Pending'}, {'event': 'close'}])
        self.assertEqual(model.calls, [('read', 'Old')])
        result = Binding().run([{'event': 'close'}]).as_dict()
        self.assertTrue(result['closed'])
        self.assertEqual(result['binding_callbacks'], [])
        with self.assertRaises(EdltError):
            Binding().run([{'event': 'close'}, {'event': 'enter'}])

    def test_result_and_continuation_are_immutable_detached_values(self):
        model = Binding()
        result = model.run([{'event': 'enter'}])
        model.allocation['index'] = 1
        external = result.as_dict()
        external['state']['text'] = 'forged'
        self.assertEqual(result.as_dict()['binding_callbacks'][0]['result']['index'], 62)
        self.assertEqual(result.state.text, 'Old')
        with self.assertRaises(FrozenInstanceError):
            result.state.text = 'forged'
        with self.assertRaises(EdltError):
            model.run([], initial_state={'text': 'forged', 'pending': False})

    def test_shape_validation_and_internal_state_refuse_before_getter(self):
        invalid = [
            {'op': 'scene-name-control', 'scene': True, 'events': []},
            {'op': 'scene-name-control', 'scene': 9, 'events': []},
            {'op': 'scene-name-control', 'scene': 1, 'events': [], 'state': {}},
            {'op': 'scene-name-control', 'scene': 1, 'events': [{'event': 'input', 'text': 1}]},
            {'op': 'scene-name-control', 'scene': 1, 'events': [{'event': 'arrow-preview', 'key': 'home'}]},
            {'op': 'scene-name-control', 'scene': 1, 'events': [{'event': 'selected-name', 'selected_index': True}]},
            {'op': 'scene-name-control', 'scene': 1, 'events': [refresh(visible=1)]},
            {'op': 'scene-name-control', 'scene': 1, 'events': [refresh(new_index=-2)]},
        ]
        for op in invalid:
            with self.subTest(op=op), self.assertRaises(EdltError):
                normalize_operation(op)
        model = Binding()
        with self.assertRaises(EdltError):
            model.run([], initial_state=SceneNameControlState('Old', pending=1))
        self.assertEqual(model.calls, [])
        with self.assertRaises(EdltError):
            model.run([{'event': 'enter', 'binding_present': 'yes'}])
        self.assertEqual(model.calls, [])


if __name__ == '__main__':
    unittest.main()
