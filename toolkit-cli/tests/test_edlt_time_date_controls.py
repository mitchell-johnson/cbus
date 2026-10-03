"""Literal source-conditioned Time/Date properties and issued callback profiles."""
from copy import copy
from dataclasses import replace
import unittest

from cbus_toolkit.edlt import EdltError, _field
from cbus_toolkit.edlt_time_date_control_properties import (
    TimeDatePropertyState, read_time_date_property, write_time_date_property,
    set_time_date_default, time_date_readonly_view,
)
from cbus_toolkit.edlt_time_date_controls import (
    choice_identity, time_date_choices, normalize_time_date_controls,
    issue_time_date_control_binding, project_time_date_controls, prepare_time_date_projection,
)

SELECTED = bytes.fromhex('0affa1a2a3a4a5a6a7a8a9aaabacadaeafb0b1b2b3b4b5b6b7b8b9babbbcbdbe')
NEIGHBOR = bytes.fromhex('0ccd9192939495969798999a9b9c9d9e9fa0a1a2a3a4a5a6a7a8a9aaabacadae')
GROWN = bytes.fromhex('0bffa1a2a3a4a5a6a7a8a9aaabacadaeafb0b1b2b3b4b5b6b7b8b9babbbcbdbe')
CLEARED = bytes.fromhex('00cd9192939495969798999a9b9c9d9e9fa0a1a2a3a4a5a6a7a8a9aaabacadae')
DISPLAY2 = bytes.fromhex('0a02a1a2a3a4a5a6a7a8a9aaabacadaeafb0b1b2b3b4b5b6b7b8b9babbbcbdbe')


def fixture(widget=1, selected=SELECTED, neighbor=NEIGHBOR):
    values = {'NavWidgetType': (0,), 'DateFormat': (7,), 'TimeFormat': (2,),
        'TimeDateLeadingZero': (1,), 'LevelBarStyle': (1,), 'Scene8StartAddress': (65535,),
        'UnitName': 'Time café 日期', 'Project': 'Synthetic\u2003fixture'}
    for slot in range(1, 22):
        record = selected if slot == widget else neighbor if slot == widget + 1 else bytes(32)
        values.update({_field(slot, i): (v,) for i, v in enumerate(record)})
        if slot >= 6:
            values[f'Widget{slot}RestoreLevel'] = (70 + slot,)
    for slot in range(64):
        values[f'StaticTextString{slot}'] = (slot,) + (0,) * 63
    return values


def op(events, widget=1, **extra):
    page, position = (0, widget) if widget < 6 else (1 + (widget - 6) // 4, 1 + (widget - 6) % 4)
    return {'op': 'time-date', 'page': page, 'position': position, 'time_date_controls': events, **extra}


def write(target, value, index):
    return {'event': 'binding-write', 'target': target, 'value': value,
        'choice_index': index, 'identity': choice_identity(target, value)}


def project(values, operation, owner=None, number=1, initial_state=None):
    owner = object() if owner is None else owner
    widget = operation['position'] if operation['page'] == 0 else 6 + (operation['page'] - 1) * 4 + operation['position'] - 1
    binding = issue_time_date_control_binding(owner=owner, operation=operation, values=values,
        widget=widget, operation_number=number, initial_state=initial_state)
    result = project_time_date_controls(binding, owner=owner, operation=operation, values=values)
    return owner, binding, result


class TestTimeDateProperties(unittest.TestCase):
    def model(self, **changes):
        return replace(TimeDatePropertyState(6, SELECTED, NEIGHBOR, 91, 92, 7, 2, 1), **changes)

    def test_invalid_display_read_is_nonmutating(self):
        model = self.model()
        result = read_time_date_property(model, 'DisplayType')
        self.assertEqual(result.value, 255)
        self.assertIs(result.state, model)
        self.assertEqual(result.writes, ())
        self.assertEqual(time_date_readonly_view(model)['record_hex'], SELECTED.hex())

    def test_display_same_value_still_attempts_assignment(self):
        result = write_time_date_property(self.model(), 'DisplayType', 255)
        self.assertEqual(result.state.record, SELECTED)
        self.assertEqual(result.writes, (('Widget6WidgetByteValue1', 255),))
        self.assertEqual(result.notification_intents, ())

    def test_display_signed_model_clamp_is_not_gui_offer(self):
        for value, byte in ((-2147483648, 0), (-1, 0), (256, 255), (2147483647, 255)):
            with self.subTest(value=value):
                result = write_time_date_property(self.model(), 'DisplayType', value)
                self.assertEqual(result.state.record[1], byte)
                self.assertEqual(result.state.record[2:], SELECTED[2:])

    def test_global_same_numeric_value_returns_before_pp_assignment(self):
        for name, value in (('DateFormat', 7), ('TimeFormat', 2), ('TimeDateLeadingZero', 1)):
            with self.subTest(property=name):
                result = write_time_date_property(self.model(), name, value)
                self.assertEqual(result.writes, ())
                self.assertEqual(result.source_calls, (name + '.set.EqualValueReturn',))

    def test_global_guard_precedes_pp_clamp(self):
        model = self.model(date_format=255)
        result = write_time_date_property(model, 'DateFormat', 256)
        self.assertEqual(result.state.date_format, 255)
        self.assertEqual(result.writes, (('DateFormat', 255),))

    def test_default_only_resets_available_restore(self):
        model = self.model()
        result = set_time_date_default(model)
        self.assertEqual(result.state.record, SELECTED)
        self.assertEqual(result.state.adjacent_record, NEIGHBOR)
        self.assertEqual(result.state.restore_level, 0)
        self.assertEqual(result.state.adjacent_restore_level, 92)
        self.assertEqual(result.writes, (('Widget6RestoreLevel', 0),))
        absent = set_time_date_default(self.model(widget=1, restore_level=None, adjacent_restore_level=None))
        self.assertEqual(absent.writes, ())
        self.assertIsNone(absent.state.restore_level)

    def test_source_type_setter_resets_both_functional_restore_fields(self):
        # A direct source-only model call, not an offered functional GUI type11.
        result = write_time_date_property(self.model(), 'WidgetType', 11)
        self.assertEqual(result.state.record, GROWN)
        self.assertEqual(result.state.adjacent_record, CLEARED)
        self.assertEqual((result.state.restore_level, result.state.adjacent_restore_level), (0, 0))
        self.assertEqual(result.restore_reset_widgets, (7, 6))
        self.assertTrue(result.owns_adjacent)
        self.assertEqual(result.writes, (('Widget7WidgetType', 0), ('Widget7RestoreLevel', 0),
            ('Widget6WidgetType', 11), ('Widget6RestoreLevel', 0)))

    def test_next_already_blank_skips_its_restore_default(self):
        result = write_time_date_property(self.model(adjacent_record=CLEARED), 'WidgetType', 11)
        self.assertEqual(result.state.adjacent_record, CLEARED)
        self.assertEqual(result.state.adjacent_restore_level, 92)
        self.assertEqual(result.restore_reset_widgets, (6,))
        self.assertTrue(result.owns_adjacent)
        self.assertIn('Next.WidgetType.set.EqualValueReturn', result.source_calls)

    def test_both_widget_notifications_are_source_calls_after_growth(self):
        result = write_time_date_property(self.model(), 'WidgetType', 11)
        self.assertEqual(result.notification_intents, ('Next.WidgetType', 'WidgetType'))
        blank = write_time_date_property(self.model(adjacent_record=CLEARED), 'WidgetType', 11)
        self.assertEqual(blank.notification_intents, ('WidgetType',))

    def test_same_type_and_shrink_keep_hidden_neighbor(self):
        model = self.model(record=GROWN)
        same = write_time_date_property(model, 'WidgetType', 11)
        self.assertIs(same.state, model)
        self.assertEqual(same.writes, ())
        shrink = write_time_date_property(model, 'WidgetType', 10)
        self.assertEqual(shrink.state.record, SELECTED)
        self.assertEqual(shrink.state.adjacent_record, NEIGHBOR)
        self.assertFalse(shrink.owns_adjacent)
        self.assertEqual(shrink.state.adjacent_restore_level, 92)
        self.assertEqual(shrink.state.restore_level, 0)

    def test_off_unit_source_setter_refuses(self):
        with self.assertRaisesRegex(EdltError, 'actual next widget'):
            write_time_date_property(self.model(widget=21, adjacent_record=None, adjacent_restore_level=None), 'WidgetType', 11)

    def test_direct_model_unknown_family_types_and_booleans_refuse(self):
        for value in (0, 12, True, None, 2147483648):
            with self.subTest(value=value), self.assertRaises(EdltError):
                write_time_date_property(self.model(), 'WidgetType', value)


class TestTimeDateControls(unittest.TestCase):
    def test_exact_source_order_and_display_names(self):
        rows = time_date_choices(1)
        self.assertEqual([(r['value'], r['name']) for r in rows['display']],
            [(1, 'Date'), (0, 'Time'), (2, 'Time & Date')])
        self.assertEqual([r['value'] for r in rows['time-format']], [3, 1, 0, 2])
        self.assertEqual([r['value'] for r in rows['date-format']], list(range(8)))
        self.assertEqual([r['value'] for r in rows['widget-type']], [0, 13, 12, 10, 11])
        self.assertEqual([r['value'] for r in time_date_choices(5)['widget-type']], [0, 13, 12, 10])
        self.assertEqual([r['value'] for r in time_date_choices(6)['widget-type']],
            [0, 14, 4, 13, 2, 12, 7, 8, 9, 16, 6, 3, 5, 10, 15])
        rows['display'][0]['name'] = 'FORGED'
        self.assertEqual(time_date_choices(1)['display'][0]['name'], 'Date')

    def test_raw_invalid_view_all_properties_preserve_full_pp(self):
        values = fixture()
        _, _, result = project(values, op([{'event': 'get-view'}, {'event': 'read-properties',
            'properties': ['DisplayType', 'WidgetType', 'DateFormat', 'TimeFormat', 'TimeDateLeadingZero']}]))
        self.assertEqual(result.changes, ())
        self.assertEqual(result.record, SELECTED)
        self.assertIsNone(result.adjacent_widget)
        view = result.as_dict()['journal'][0]['observed']
        self.assertEqual(view['display_type'], 255)
        self.assertEqual(view['binding_values'], {})
        self.assertEqual(result.as_dict()['journal'][1]['observed'],
            {'DisplayType': 255, 'WidgetType': 10, 'DateFormat': 7, 'TimeFormat': 2, 'TimeDateLeadingZero': 1})
        self.assertEqual(values['Scene8StartAddress'], (65535,))
        self.assertEqual(values['UnitName'], 'Time café 日期')

    def test_display_offered_write_exact_literal_and_all_other_fields(self):
        values = fixture()
        owner, _, result = project(values, op([write('display', 2, 2)]))
        record, changes, receipt = prepare_time_date_projection(result, owner=owner)
        self.assertEqual(record, DISPLAY2)
        self.assertEqual(changes, {'Widget1WidgetByteValue1': (2,)})
        self.assertEqual(receipt['journal'][0]['notification_intents'], [])
        self.assertFalse(receipt['pp_notification_delivery_established'])
        self.assertEqual({**values, **changes}['LevelBarStyle'], (1,))

    def test_all_offered_format_choices_exact_changed_field(self):
        for target, values in (('display', [1, 0, 2]), ('date-format', list(range(8))), ('time-format', [3, 1, 0, 2])):
            for index, val in enumerate(values):
                with self.subTest(target=target, index=index):
                    before = fixture()
                    _, _, result = project(before, op([write(target, val, index)]))
                    expected = {'display': 'Widget1WidgetByteValue1', 'date-format': 'DateFormat', 'time-format': 'TimeFormat'}[target]
                    self.assertEqual(dict(result.changes), {} if before[expected] == (val,) else {expected: (val,)})
                    self.assertEqual(result.record[2:], SELECTED[2:])
                    self.assertEqual({**before, **dict(result.changes)}['LevelBarStyle'], (1,))

    def test_leading_zero_checked_profile_preserves_other_bits_owner(self):
        for val in (0, 1):
            with self.subTest(value=val):
                _, _, result = project(fixture(), op([{'event': 'binding-write', 'target': 'leading-zero', 'value': val}]))
                self.assertEqual(dict(result.changes), {} if val == 1 else {'TimeDateLeadingZero': (0,)})
                self.assertEqual(result.record, SELECTED)

    def test_binding_read_and_setup_do_not_infer_write_or_repair(self):
        _, _, result = project(fixture(), op([{'event': 'binding-read', 'target': 'display'},
            {'event': 'setup-widget-selection'}, {'event': 'widget-type-selected-index-changed'}]))
        receipt = result.as_dict()
        self.assertEqual(result.changes, ())
        self.assertEqual(receipt['state']['binding_values'], {'display': 255, 'widget-type': 10})
        callbacks = [r['action'] for e in receipt['journal'] for r in e['binding_callbacks']]
        self.assertEqual(callbacks, ['Binding.ReadValue', 'DataBindings.SaveFirst', 'DataBindings.Clear',
            'WidgetType.DataSource.Assign', 'DataBindings.AddSameBinding', 'Binding.ReadValue',
            'WidgetType.SelectedIndexChanged.EmptyHandler'])
        self.assertNotIn('Binding.WriteValue', callbacks)

    def test_changed_to11_has_exact_pair_and_absent_standby_restore(self):
        values = fixture()
        _, _, result = project(values, op([write('widget-type', 11, 4)]))
        self.assertEqual(result.record, GROWN)
        self.assertEqual(result.adjacent_widget, 2)
        self.assertEqual(result.adjacent_before, NEIGHBOR)
        self.assertEqual(result.adjacent_after, CLEARED)
        self.assertIsNone(result.restore_level)
        self.assertIsNone(result.adjacent_restore_level)
        self.assertEqual(dict(result.changes), {'Widget1WidgetType': (11,), 'Widget2WidgetType': (0,)})
        self.assertEqual(result.restore_reset_widgets, ())
        self.assertNotIn('Widget1RestoreLevel', values)

    def test_neighbor_types_and_standby4_only_change_type_byte(self):
        for kind in (10, 12, 13, 255):
            neighbor = bytes((kind,)) + NEIGHBOR[1:]
            with self.subTest(kind=kind):
                _, _, result = project(fixture(4, neighbor=neighbor), op([write('widget-type', 11, 4)], 4))
                self.assertEqual(result.adjacent_widget, 5)
                self.assertEqual(result.adjacent_after, CLEARED)
                self.assertEqual(result.record, GROWN)

    def test_changed_to11_reserves_even_alreadyblank_next(self):
        _, _, result = project(fixture(neighbor=CLEARED), op([write('widget-type', 11, 4)]))
        self.assertEqual(result.adjacent_widget, 2)
        self.assertEqual(result.adjacent_before, CLEARED)
        self.assertEqual(result.adjacent_after, CLEARED)
        self.assertEqual(dict(result.changes), {'Widget1WidgetType': (11,)})

    def test_same11_and_shrink_dont_claim_next(self):
        for val, expected in ((11, GROWN), (10, SELECTED)):
            with self.subTest(value=val):
                _, _, result = project(fixture(selected=GROWN), op([write('widget-type', val, 4 if val == 11 else 3)]))
                self.assertEqual(result.record, expected)
                self.assertIsNone(result.adjacent_widget)
                self.assertIsNone(result.adjacent_after)
                self.assertEqual(result.state.model.adjacent_record, NEIGHBOR)

    def test_growth_then_shrink_retains_prior_cleared_slot_ownership(self):
        _, _, result = project(fixture(), op([write('widget-type', 11, 4), write('widget-type', 10, 3)]))
        self.assertEqual(result.record, SELECTED)
        self.assertEqual(result.adjacent_widget, 2)
        self.assertEqual(result.adjacent_after, CLEARED)
        self.assertEqual(dict(result.changes), {'Widget2WidgetType': (0,)})

    def test_widget_choices_location_and_covered_slot_refuse(self):
        for widget in (5, 6, 21):
            with self.subTest(widget=widget), self.assertRaises(EdltError):
                project(fixture(widget), op([write('widget-type', 11, 4)], widget, page_mode='multiple'))
        with self.assertRaisesRegex(EdltError, 'current source ordinal'):
            project(fixture(), op([write('widget-type', 10, 13)]))
        values = fixture(2)
        values['Widget1WidgetType'] = (11,)
        with self.assertRaisesRegex(EdltError, 'covered'):
            project(values, op([{'event': 'get-view'}], 2))

    def test_empty_page_mode_is_not_an_absent_profile(self):
        with self.assertRaisesRegex(EdltError, 'source UI profile'):
            project(fixture(), op([{'event': 'get-view'}], page_mode=''))

    def test_restore_fields_match_actual_keygl5_layout(self):
        absent = fixture(6)
        del absent['Widget6RestoreLevel']
        with self.assertRaisesRegex(EdltError, 'Restore'):
            project(absent, op([{'event': 'get-view'}], 6))
        fabricated = fixture()
        fabricated['Widget1RestoreLevel'] = (90,)
        with self.assertRaisesRegex(EdltError, 'standby'):
            project(fabricated, op([{'event': 'get-view'}]))

    def test_functional_type10_same_assignment_preserves_restore(self):
        values = fixture(6)
        _, _, result = project(values, op([write('widget-type', 10, 13)], 6))
        self.assertEqual(result.restore_level, 76)
        self.assertEqual(result.changes, ())
        self.assertEqual(result.restore_reset_widgets, ())

    def test_illegal_events_choices_and_json_state_refuse(self):
        bad = [[], [{'event': 'enter'}], [{'event': 'get-view', 'state': {}}],
            [{'event': 'binding-write', 'target': 'leading-zero', 'value': True}],
            [write('display', 0, 0)], [write('widget-type', 12, 2)],
            [{'event': 'read-properties', 'properties': ['DateFormat', 'DateFormat']}],
            [{'event': 'binding-read', 'target': 'clock'}],
            [{'event': 'get-property', 'property': 'ToString'}]]
        for rows in bad:
            with self.subTest(rows=rows), self.assertRaises(EdltError):
                normalize_time_date_controls(rows)

    def test_full_source_unicode_uint16_and_named_global_staleness(self):
        owner, values, operation = object(), fixture(), op([{'event': 'get-view'}])
        binding = issue_time_date_control_binding(owner=owner, operation=operation, values=values, widget=1)
        for field, replacement in (('UnitName', 'changed'), ('Scene8StartAddress', (65534,)),
                ('LevelBarStyle', (0,)), ('Widget2WidgetByteValue31', (0,)), ('StaticTextString63', (0,) * 64)):
            changed = dict(values)
            changed[field] = replacement
            with self.subTest(field=field), self.assertRaisesRegex(EdltError, 'stale'):
                project_time_date_controls(binding, owner=owner, operation=operation, values=changed)

    def test_missing_actual_records_globals_and_byte_domain_refuse(self):
        for name, raw in (('DateFormat', None), ('Widget2WidgetByteValue31', None),
                ('Widget1WidgetByteValue31', (256,)), ('DateFormat', (65535,))):
            values = fixture()
            if raw is None:
                del values[name]
            else:
                values[name] = raw
            with self.subTest(name=name), self.assertRaises(EdltError):
                project(values, op([{'event': 'get-view'}]))

    def test_binding_exact_identity_owner_number_and_operation(self):
        owner, binding, result = project(fixture(), op([{'event': 'get-view'}]))
        for forged in (copy(binding), replace(binding, operation_number=2), replace(binding, _owner=object()), binding.as_dict()):
            with self.subTest(forged=type(forged)), self.assertRaises(EdltError):
                project_time_date_controls(forged, owner=owner, operation=op([{'event': 'get-view'}]), values=fixture())
        with self.assertRaises(EdltError):
            project_time_date_controls(binding, owner=object(), operation=op([{'event': 'get-view'}]), values=fixture())
        with self.assertRaisesRegex(EdltError, 'stale'):
            project_time_date_controls(binding, owner=owner, operation=op([{'event': 'binding-read', 'target': 'display'}]), values=fixture())
        with self.assertRaises(EdltError):
            prepare_time_date_projection(replace(result, record=DISPLAY2), owner=owner)
        with self.assertRaises(EdltError):
            prepare_time_date_projection(result, owner=None)

    def test_state_continuation_has_exact_issued_identity_and_forward_number(self):
        owner, _, first = project(fixture(), op([write('display', 2, 2)]), number=4)
        current = {**fixture(), **dict(first.changes)}
        _, _, second = project(current, op([{'event': 'binding-read', 'target': 'display'}]), owner=owner,
            number=5, initial_state=first.state)
        self.assertEqual(second.state.binding_values, (('display', 2),))
        for state, number in ((copy(first.state), 5), (first.state, 4), (first.state.as_dict(), 5)):
            with self.subTest(number=number), self.assertRaises(EdltError):
                project(current, op([{'event': 'get-view'}]), owner=owner, number=number, initial_state=state)

    def test_mutating_nested_frozen_state_cannot_rewrite_issuance_authority(self):
        owner, _, result = project(fixture(), op([{'event': 'get-view'}]))
        object.__setattr__(result.state.model, 'record', DISPLAY2)
        with self.assertRaisesRegex(EdltError, 'unchanged owner-issued result'):
            prepare_time_date_projection(result, owner=owner)
        with self.assertRaises(EdltError):
            project({**fixture(), 'Widget1WidgetByteValue1': (2,)}, op([{'event': 'get-view'}]),
                owner=owner, number=2, initial_state=result.state)

    def test_malformed_issued_nested_state_refuses_as_profile_error(self):
        for field, value in (('model', None), ('binding_values', (([], 2),))):
            owner, _, result = project(fixture(), op([{'event': 'get-view'}]))
            object.__setattr__(result.state, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(EdltError, 'unsupported typed contents'):
                prepare_time_date_projection(result, owner=owner)

    def test_result_detached_receipt_mutation_does_not_change_capability(self):
        owner, _, result = project(fixture(), op([write('display', 2, 2)]))
        detached = result.as_dict()
        detached['record_hex'] = '00' * 32
        detached['journal'][0]['binding_callbacks'].clear()
        self.assertEqual(prepare_time_date_projection(result, owner=owner)[0], DISPLAY2)
        self.assertEqual(result.as_dict()['journal'][0]['binding_callbacks'][0]['action'], 'Binding.WriteValue')

    def test_no_state_or_bindings_are_guessed_at_array_end(self):
        _, _, result = project(fixture(), op([{'event': 'get-view'}]))
        self.assertFalse(result.pending)
        self.assertEqual(result.state.binding_values, ())
        self.assertEqual(result.as_dict()['journal'][0]['binding_callbacks'], [])
        self.assertFalse(result.as_dict()['clock_set'])


if __name__ == '__main__':
    unittest.main()
