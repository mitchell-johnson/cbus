"""Literal source handler requests; this is not a complete native executor."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_fresh_forms import (
    FormApplication, FormChoice, FormGroup, FormRequest, FreshFormContext, IdentificationContext,
    broadcast_after_change, broadcast_checked, broadcast_choices,
    clean_unit_name_text, input_key_blocks_changed, maintenance_block_changed,
    maintenance_checked, maintenance_choices, maintenance_combo_changed,
    pec_enable_changed, pec_group_included, pir_enable_changed, pir_group_included,
    refresh_broadcast_from_key_blocks, refresh_occupancy_from_key_blocks,
    set_maintenance_group, setup_maintenance_selection, unit_name_exit,
)
from cbus_toolkit.senlla_key_references import SENLLAKeyReferences
from cbus_toolkit.sensors import SensorError


def context(**changes):
    applications = (
        FormApplication('primary', 56, 'LIGHT-A', [
            FormGroup('p255', 'primary', 255, 'UNUSED'),
            FormGroup('p20', 'primary', 20, 'TWENTY'),
            FormGroup('p21', 'primary', 21, 'OTHER'),
            FormGroup('p22', 'primary', 22, 'PEC'),
            FormGroup('p23', 'primary', 23, 'PIR'),
        ]),
        FormApplication('secondary', 57, 'LIGHT-B', [
            FormGroup('s255', 'secondary', 255, 'UNUSED'),
            FormGroup('s20', 'secondary', 20, 'TWENTY'),
            FormGroup('s21', 'secondary', 21, 'LAST'),
        ]),
        FormApplication('enable', 203, 'ENABLE', [
            FormGroup('e255', 'enable', 255, 'UNUSED'),
            FormGroup('e1', 'enable', 1, 'JOIN'),
        ]),
    )
    values = dict(applications=applications, primary_application='primary',
                  secondary_application='secondary', block_groups=['p255'] * 8,
                  block_labels=[f'BLOCK-{index}' for index in range(8)],
                  bank_active=[False] * 8, key_scene=[False] * 8,
                  key_templates=[16] * 8, references=SENLLAKeyReferences(((),) * 8),
                  occupancy_flags=[[False] * 4 for _ in range(8)],
                  pec_group='p22', pir_group='p23', join_group=None,
                  dual_join_group=None, corridor_group=None, corridor_active=False,
                  maintenance_active=False, maintenance_block=0,
                  broadcast_active=False, broadcast_block=1)
    values.update(changes)
    if 'key_scene' in changes and 'key_templates' not in changes:
        values['key_templates'] = [24 if value else 16 for value in values['key_scene']]
    elif 'key_templates' in changes and 'key_scene' not in changes:
        values['key_scene'] = [value in (23, 24, 25) for value in values['key_templates']]
    return FreshFormContext(**values)


def drain(handler, state, after=None):
    """Supply authored owner responses, not a production callback executor."""
    requests = []
    try:
        request = next(handler)
        while True:
            requests.append(request)
            if request.method == 'PopulateBroadcastChoices':
                state = replace(state, broadcast_items=request.value)
            if after is not None:
                state = after(request, state)
            request = handler.send(state)
    except StopIteration as stop:
        return requests, stop.value


class SENLLAFreshFormsTest(unittest.TestCase):
    def test_complete_maintenance_inventory_order_and_equal_numeric_groups(self):
        state = context(block_groups=['p20', 'p255', 'p255', 'p255',
                                      'p255', 'p255', 'p255', 'p255'],
                        bank_active=[False, True, False, False, False, False, False, False],
                        maintenance_active=True, broadcast_active=True, broadcast_block=2)
        choices = maintenance_choices(state)
        self.assertEqual([(item.kind, item.identity) for item in choices], [
            ('block', 0), ('block', 3), ('block', 4), ('block', 5), ('block', 6), ('block', 7),
            ('group', 'p21'), ('group', 'p22'), ('group', 'p23'),
            ('group', 's20'), ('group', 's21'),
        ])
        self.assertEqual(choices[-2].label, 'TWENTY (LIGHT-B)')

    def test_no_free_accepted_block_suppresses_all_extra_groups(self):
        state = context(block_groups=['p20'] * 8)
        self.assertEqual([item.kind for item in maintenance_choices(state)], ['block'] * 8)
        state = context(key_scene=[True] * 8)
        self.assertEqual([item.kind for item in maintenance_choices(state)], ['block'] * 8)

    def test_free_probe_is_same_index_scene_status_and_short_circuits(self):
        state = context(key_scene=[True, False, False, False, False, False, False, False],
                        references=SENLLAKeyReferences(([0], [], [], [], [], [], [], [])))
        self.assertTrue(any(item.kind == 'group' for item in maintenance_choices(state)))
        # Source stops dereferencing Group once an earlier accepted free block exists.
        state = context(block_groups=['p255', None, None, None, None, None, None, None])
        self.assertEqual(len(maintenance_choices(state)), 14)

    def test_secondary_unused_application_is_omitted(self):
        unused = FormApplication('secondary', 255, 'NONE', ())
        state = context()
        state = replace(state, applications=(state.applications[0], unused, state.applications[2]))
        self.assertEqual([item.identity for item in maintenance_choices(state) if item.kind == 'group'],
                         ['p20', 'p21', 'p22', 'p23'])

    def test_nil_secondary_is_pointer_comparison_for_allocation_but_native_dereference_for_choices(self):
        state = context(secondary_application=None)
        requests, _ = drain(set_maintenance_group(state, 'p20'), state)
        self.assertEqual([item.value for item in requests], [False, 'p20', 0])
        with self.assertRaisesRegex(SensorError, 'unavailable application'):
            maintenance_choices(state)
        state = context(secondary_application=None, block_groups=['p20'] * 8)
        self.assertEqual(len(maintenance_choices(state)), 8)

    def test_broadcast_choices_filter_shared_scene_flags_not_banks_or_groups(self):
        state = context(maintenance_active=True, maintenance_block=7,
                        broadcast_active=True, broadcast_block=0,
                        references=SENLLAKeyReferences(([2, 4], [1], [3], [], [], [], [], [])),
                        key_scene=[False, True, False, False, False, False, False, False],
                        occupancy_flags=[[False] * 4, [False] * 4,
                                         [False, False, False, True], *([[False] * 4] * 5)],
                        bank_active=[True] * 8, block_groups=['p20'] * 8)
        self.assertEqual(broadcast_choices(state), (0, 2, 4, 5, 6))

    def test_pec_all_used_collisions_clear_even_when_inactive(self):
        changes = [dict(join_group='p22'), dict(dual_join_group='p22'),
                   dict(pir_group='p22'), dict(corridor_group='p22', corridor_active=True),
                   dict(block_groups=['p255', 'p255', 'p255', 'p255',
                                      'p255', 'p255', 'p255', 'p22'])]
        for change in changes:
            with self.subTest(change=change):
                state = context(**change)
                def response(request, current):
                    return replace(current, pec_group=request.value) if request.method == 'SetLightLevelMaintEnableGroup' else current
                requests, _ = drain(maintenance_checked(state), state, response)
                self.assertEqual([(item.method, item.value) for item in requests[:2]],
                                 [('SetLightLevelMaintEnableGroup', 'p255'),
                                  ('SetLightLevelMaintEnableGroupOff', False)])

    def test_pec_distinct_application_identity_and_inactive_corridor_preserve(self):
        for change in (dict(pec_group='p20', pir_group='s20'),
                       dict(corridor_group='p22', corridor_active=False)):
            with self.subTest(change=change):
                state = context(**change)
                requests, _ = drain(maintenance_checked(state), state)
                self.assertEqual([item.method for item in requests], ['PopulateBroadcastChoices'])

    def test_unused_enable_callbacks_invoke_equal_false_setters(self):
        for handler, group, method in ((pec_enable_changed, 'pec_group', 'SetLightLevelMaintEnableGroupOff'),
                                       (pir_enable_changed, 'pir_group', 'SetOccupancyEnableGroupOff')):
            with self.subTest(handler=handler.__name__):
                state = context(**{group: 'p255'})
                requests, _ = drain(handler(state), state)
                self.assertEqual([(request.method, request.value) for request in requests], [(method, False)])
                requests, _ = drain(handler(context()), context())
                self.assertEqual(requests, [])

    def test_pec_and_pir_group_choice_filters_are_distinct(self):
        state = context(block_groups=['p20'] * 8, pec_group='p22',
                        join_group='e1', dual_join_group='p21', corridor_group='s20')
        self.assertFalse(pec_group_included(state, 'p20'))
        self.assertTrue(pir_group_included(state, 'p20'))
        self.assertTrue(pir_group_included(state, 'p22'))
        self.assertFalse(pir_group_included(replace(state, maintenance_active=True), 'p22'))
        self.assertFalse(pec_group_included(state, 'p21'))
        self.assertFalse(pir_group_included(state, 'e1'))
        self.assertTrue(pec_group_included(state, 's20'))
        self.assertFalse(pec_group_included(replace(state, corridor_active=True), 's20'))
        self.assertTrue(pec_group_included(state, 'p255'))
        self.assertFalse(pir_group_included(state, 'p255', initial_include=False))

    def test_maintenance_same_block_refresh_select_zero_after_callbacks(self):
        state = context(pec_group='p255', maintenance_active=True,
                        broadcast_active=True, maintenance_block=0, broadcast_block=0)
        requests, _ = drain(maintenance_checked(state), state)
        self.assertEqual([request.method for request in requests], [
            'PopulateMaintenanceChoices', 'SetItemIndex',
            'SetLightLevelMaintEnableGroupOff', 'PopulateBroadcastChoices'])
        self.assertEqual(requests[0].value[0].identity, 1)
        self.assertEqual(requests[1].value, 0)

    def test_maintenance_allocation_native_scan_does_not_recheck_choice_filters(self):
        state = context(bank_active=[True] * 8, maintenance_active=True,
                        broadcast_active=True, broadcast_block=0)
        requests, _ = drain(set_maintenance_group(state, 's20'), state)
        self.assertEqual([(request.method, request.target_index, request.value) for request in requests], [
            ('SetSecondaryApplication', 0, True), ('SetGroup', 0, 's20'),
            ('SetLightLevelMaintBlock', None, 0)])

    def test_maintenance_allocation_first_non_scene_and_selected_group_capture(self):
        state = context(block_groups=['p20', 'p255', 'p255', 'p255',
                                      'p255', 'p255', 'p255', 'p255'],
                        key_scene=[False, True, False, False, False, False, False, False])
        def response(request, current):
            # Nested owner callbacks may change the block, but captured choice remains p21.
            return replace(current, block_groups=['s20'] * 8)
        requests, _ = drain(set_maintenance_group(state, 'p21'), state, response)
        self.assertEqual([(request.method, request.target_index, request.value) for request in requests], [
            ('SetSecondaryApplication', 2, False), ('SetGroup', 2, 'p21'),
            ('SetLightLevelMaintBlock', None, 2)])
        state = context(block_groups=['p20'] * 8)
        self.assertEqual(drain(set_maintenance_group(state, 's20'), state)[0], [])

    def test_maintenance_combo_actual_typed_selected_object(self):
        state = context(maintenance_selected=FormChoice('block', 6, 'SAME LABEL'))
        requests, _ = drain(maintenance_combo_changed(state), state)
        self.assertEqual([(item.method, item.value) for item in requests], [('SetLightLevelMaintBlock', 6)])
        state = context(maintenance_selected=FormChoice('group', 's21', 'SAME LABEL'))
        requests, _ = drain(maintenance_combo_changed(state), state)
        self.assertEqual([item.value for item in requests], [True, 's21', 0])
        for selected in (None, FormChoice('other', 'external-object', 'OTHER')):
            state = context(maintenance_selected=selected)
            self.assertEqual(drain(maintenance_combo_changed(state), state)[0], [])

    def test_maintenance_expression_control_boundary_and_source_branch_tail(self):
        state = context()
        requests, _ = drain(maintenance_block_changed(state, 'EXACT Native Text'), state)
        self.assertEqual([(item.method, item.value) for item in requests[:1]],
                         [('IndexOfAndSetItemIndex', 'EXACT Native Text')])
        self.assertEqual(requests[-1].method, 'PopulateBroadcastChoices')
        state = context(maintenance_active=True, broadcast_active=True,
                        maintenance_block=2, broadcast_block=2)
        requests, _ = drain(maintenance_block_changed(state, 'IGNORED'), state)
        self.assertEqual([item.method for item in requests], ['PopulateMaintenanceChoices', 'SetItemIndex'])

    def test_setup_onchange_install_precedes_current_maintenance_label_selection(self):
        state = context(maintenance_block=7)
        requests, _ = drain(setup_maintenance_selection(state), state)
        self.assertEqual([(item.method, item.value) for item in requests], [
            ('InstallOnChange', 'HandleMaintBlockComboChange'),
            ('IndexOfAndSetItemIndex', 'BLOCK-7')])
        handler = setup_maintenance_selection(context(maintenance_block=None))
        next(handler)
        with self.assertRaisesRegex(SensorError, 'nil maintenance'):
            handler.send(context(maintenance_block=None))

    def test_broadcast_native_timer_matrix_and_same_block_gate(self):
        state = context(broadcast_active=True, broadcast_block=3)
        requests, _ = drain(broadcast_after_change(state), state)
        self.assertEqual([(item.target_index, item.value) for item in requests], [
            (0, None), (1, None), (2, None), (3, 8),
            (4, None), (5, None), (6, None), (7, None)])
        state = context(maintenance_active=True, maintenance_block=3,
                        broadcast_active=False, broadcast_block=3)
        requests, _ = drain(broadcast_after_change(state), state)
        self.assertEqual([item.value for item in requests], [None] * 8)
        state = replace(state, broadcast_active=True)
        self.assertEqual(drain(broadcast_after_change(state), state)[0], [])
        state = replace(state, maintenance_block=None, broadcast_block=None)
        self.assertEqual(drain(broadcast_after_change(state), state)[0], [])

    def test_broadcast_function_matrix_after_all_timer_setters(self):
        state = context(broadcast_active=True, broadcast_block=2,
                        references=SENLLAKeyReferences(([2],) * 8),
                        key_templates=[29, 30, 31, 32, 33, 34, 16, 26])
        requests, _ = drain(broadcast_after_change(state), state)
        self.assertEqual([item.target_index for item in requests[:8]], list(range(8)))
        self.assertEqual([(item.target_index, item.value) for item in requests[8:]],
                         [(0, 16), (1, 16), (4, 16), (5, 16)])

    def test_broadcast_timer_and_function_reread_current_owner_between_rows(self):
        state = context(broadcast_active=True, broadcast_block=2,
                        references=SENLLAKeyReferences(([2], [6], [], [], [], [], [], [])),
                        key_templates=[29, 34, 16, 16, 16, 16, 16, 16])
        def response(request, current):
            if request.method == 'SetMacroFunctionTemplate' and request.target_index == 0:
                return replace(current, broadcast_block=6, broadcast_active=False)
            return current
        requests, _ = drain(broadcast_after_change(state), state, response)
        # Active was an entry gate for this key loop, not a per-key gate.
        self.assertEqual([(item.target_index, item.value) for item in requests[8:]], [(0, 16), (1, 16)])
        def timer_response(request, current):
            return replace(current, broadcast_block=6) if request.target_index == 1 else current
        requests, _ = drain(broadcast_after_change(context(broadcast_active=True, broadcast_block=2)),
                            context(broadcast_active=True, broadcast_block=2), timer_response)
        self.assertEqual([item.value for item in requests[:8]], [None, None, None, None, None, None, 8, None])

    def test_manual_broadcast_complete_row_then_scene_and_next_key_current_reads(self):
        state = context(broadcast_active=True, broadcast_block=2,
                        references=SENLLAKeyReferences(([2], [6], [], [], [], [], [], [])),
                        key_scene=[True, True, False, False, False, False, False, False])
        def response(request, current):
            if request.method == 'SetLightAndMovement' and request.target_index == 0:
                return replace(current, broadcast_block=6, broadcast_active=False)
            return current
        requests, _ = drain(broadcast_checked(state), state, response)
        self.assertEqual([(item.method, item.target_index) for item in requests[:10]], [
            ('SetLightAndMovement', 0), ('SetDarkAndMovement', 0), ('SetAnyMovement', 0),
            ('SetSunset', 0), ('SetMacroFunctionTemplate', 0),
            ('SetLightAndMovement', 1), ('SetDarkAndMovement', 1), ('SetAnyMovement', 1),
            ('SetSunset', 1), ('SetMacroFunctionTemplate', 1)])

    def test_manual_broadcast_scene_predicate_after_all_four_callbacks(self):
        state = context(broadcast_active=True, broadcast_block=0,
                        references=SENLLAKeyReferences(([0], [], [], [], [], [], [], [])),
                        key_scene=[True, False, False, False, False, False, False, False])
        def response(request, current):
            return replace(current, key_scene=[False] * 8, key_templates=[16] * 8) if request.method == 'SetSunset' else current
        requests, _ = drain(broadcast_checked(state), state, response)
        self.assertEqual([item.method for item in requests], [
            'SetLightAndMovement', 'SetDarkAndMovement', 'SetAnyMovement',
            'SetSunset', 'PopulateMaintenanceChoices'])

    def test_manual_broadcast_fallback_uses_actual_current_collection_not_new_graph(self):
        state = context(broadcast_active=True, broadcast_block=0,
                        maintenance_active=True, maintenance_block=0)
        def response(request, current):
            if request.method == 'PopulateBroadcastChoices':
                return replace(current, broadcast_items=(5, 6, 7))
            return current
        requests, _ = drain(broadcast_checked(state), state, response)
        self.assertEqual([(item.method, item.value) for item in requests[1:2]],
                         [('SetLightLevelBroadcastBlock', 5)])

    def test_native_empty_broadcast_fallback_and_missing_collection_refuse(self):
        state = context(broadcast_active=True, broadcast_block=0,
                        maintenance_active=True, maintenance_block=0)
        handler = broadcast_checked(state)
        next(handler)
        with self.assertRaisesRegex(SensorError, 'empty candidate'):
            handler.send(replace(state, broadcast_items=()))
        handler = broadcast_checked(state)
        next(handler)
        with self.assertRaisesRegex(SensorError, 'current native candidate'):
            handler.send(state)

    def test_external_broadcast_callback_runs_before_maintenance_repopulation(self):
        state = context(external_broadcast_callback=True)
        requests, _ = drain(broadcast_checked(state), state)
        self.assertEqual([item.method for item in requests], [
            'ExternalBroadcastFormCallback', 'PopulateMaintenanceChoices'])

    def test_reassignment_first_non_nil_compatible_primary_ignores_active(self):
        state = context(broadcast_block=2, broadcast_active=False,
                        references=SENLLAKeyReferences(([], [], [4, 0], [2], [7], [], [], [])),
                        occupancy_flags=[[False] * 4, [False] * 4, [False] * 4,
                                         [True, False, False, False], *([[False] * 4] * 4)])
        requests, _ = drain(refresh_broadcast_from_key_blocks(state), state)
        self.assertEqual([(item.method, item.value) for item in requests], [('SetLightLevelBroadcastBlock', 4)])
        state = replace(state, references=SENLLAKeyReferences(([2], [], [], [2], [], [], [], [])))
        requests, _ = drain(refresh_broadcast_from_key_blocks(state), state)
        self.assertEqual(requests[0].value, 2)  # Equal reference setter is still invoked.

    def test_occupancy_per_row_active_gate_and_complete_inner_setter_order(self):
        state = context(broadcast_active=True, broadcast_block=0,
                        references=SENLLAKeyReferences(([0], [0], [], [], [], [], [], [])))
        def response(request, current):
            return replace(current, broadcast_active=False)
        requests, _ = drain(refresh_occupancy_from_key_blocks(state), state, response)
        self.assertEqual([(item.method, item.target_index) for item in requests], [
            ('SetLightAndMovement', 0), ('SetDarkAndMovement', 0),
            ('SetAnyMovement', 0), ('SetSunset', 0)])

    def test_input_key_blocks_changed_inherited_clear_reassign_direct_refresh_order(self):
        state = context(broadcast_active=False, broadcast_block=2,
                        references=SENLLAKeyReferences(([4], [2], [], [], [], [], [], [])),
                        occupancy_flags=[[False] * 4, [True, False, False, False],
                                         *([[False] * 4] * 6)])
        requests, _ = drain(input_key_blocks_changed(state, 7), state)
        self.assertEqual([(item.method, item.value, item.target_index) for item in requests], [
            ('InheritedInputKeyBlocksChanged', 7, None),
            ('SetLightLevelBroadcastBlock', 4, None),
            ('RefreshEventFlagsFromMacroFunction', None, 7)])

    def test_metadata_actual_control_filter_is_only_logical_settext_target(self):
        cases = [('MIXED_99', 'MIXED_99'), ('Aa B_<C>9z!', 'AB_C9!'),
                 ('newunit', 'NEWUNIT'), ('NewUnit', 'NU'), ('<>a b', 'NEWUNIT'),
                 ('', 'NEWUNIT'), ('A-B_C9!', 'A-B_C9!'), ('A\U0001f600\ud800Bé', 'AB')]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(clean_unit_name_text(raw), expected)

    def test_metadata_exit_rereads_actual_text_and_tag_after_settext_callbacks(self):
        state = IdentificationContext('newunit', 'old', 'old', '')
        handler = unit_name_exit(state)
        first = next(handler)
        self.assertEqual((first.method, first.value), ('SetText', 'NEWUNIT'))
        actual = IdentificationContext('ACTUAL', 'ACTUAL', 'old', '')
        second = handler.send(actual)
        self.assertEqual((second.method, second.value), ('SetTagName', 'ACTUAL'))
        self.assertEqual(second.target_kind, 'unit_metadata')
        self.assertIn('TCISTagAttribute virtual+0x7c', second.callback_contract)
        self.assertIn('TStringAttribute.SetValue0x7f39a0', second.callback_contract)
        self.assertIn('mutable candidate and changed flag', second.callback_contract)
        self.assertIn('exceeding 32 UTF16 code units raises', second.callback_contract)
        self.assertIn('HandleTagNameAfterChange0xf47b04', second.callback_contract)
        self.assertNotIn('CanDoChange', second.callback_contract)
        with self.assertRaises(StopIteration) as stop:
            handler.send(replace(actual, unit_tag_name='ACTUAL'))
        self.assertTrue(stop.exception.value.cached_text_differs)
        for tag in ('KEEP', 'NewUnit', 'newunit'):
            with self.subTest(tag=tag):
                handler = unit_name_exit(state)
                next(handler)
                with self.assertRaises(StopIteration):
                    handler.send(replace(actual, unit_tag_name=tag))

    def test_metadata_unchanged_settext_does_not_infer_a_pending_cache_change(self):
        # Native uppercase rendering can leave original controller cache restored.
        state = IdentificationContext('ABC', 'abc', 'abc', 'KEEP')
        handler = unit_name_exit(state)
        self.assertEqual(next(handler).value, 'ABC')
        with self.assertRaises(StopIteration) as stop:
            handler.send(state)
        self.assertFalse(stop.exception.value.cached_text_differs)
        handler = unit_name_exit(state)
        next(handler)
        with self.assertRaisesRegex(SensorError, 'actual IdentificationContext'):
            next(handler)
        with self.assertRaises(SensorError):
            IdentificationContext('X', None, 'X', 'X')

    def test_missing_accessed_identity_and_nil_template_fail_closed(self):
        state = context(pec_group='unknown')
        with self.assertRaisesRegex(SensorError, 'unavailable group'):
            next(maintenance_checked(state))
        state = context(pec_group='p22', join_group='p22')
        app = state.applications[0]
        state = replace(state, applications=(replace(app, groups=app.groups[1:]), *state.applications[1:]))
        with self.assertRaisesRegex(SensorError, 'existing primary unused'):
            next(maintenance_checked(state))
        state = context(broadcast_active=True, broadcast_block=0,
                        references=SENLLAKeyReferences(([0], [], [], [], [], [], [], [])),
                        key_templates=[None, 16, 16, 16, 16, 16, 16, 16])
        with self.assertRaisesRegex(SensorError, 'nil key template'):
            drain(broadcast_after_change(state), state)

    def test_context_validation_domains_and_manager_identity_canonicalization(self):
        failures = [dict(bank_active=[0] * 8), dict(key_templates=[True] * 8),
                    dict(occupancy_flags=[[False, False, False, 0]] * 8),
                    dict(block_labels=['X'] * 7), dict(broadcast_block=True),
                    dict(broadcast_items=[0, 0]), dict(maintenance_selected={}),
                    dict(references=[[]] * 8), dict(primary_application='')]
        for changes in failures:
            with self.subTest(changes=changes), self.assertRaises(SensorError):
                context(**changes)
        with self.assertRaisesRegex(SensorError, 'Scene status'):
            context(key_scene=[False] * 8, key_templates=[23] * 8)
        state = context(key_templates=[23, 24, 25, None, 16, 26, 34, 6])
        self.assertEqual(state.key_scene, (True, True, True, False, False, False, False, False))
        with self.assertRaises(SensorError):
            FormGroup('g', 'a', True, 'X')
        with self.assertRaises(SensorError):
            FormApplication('a', 56, 'X', [FormGroup('g', 'different', 20, 'X')])
        with self.assertRaises(SensorError):
            FormApplication('a', 56, 'X', [FormGroup('g', 'a', 20, 'X'), FormGroup('h', 'a', 20, 'Y')])
        state = context()
        with self.assertRaises(SensorError):
            replace(state, applications=(*state.applications, replace(state.applications[0], object_id='other')))

    def test_immutable_detached_context_requests_and_required_resume(self):
        groups = ['p255'] * 8
        flags = [[False] * 4 for _ in range(8)]
        state = context(block_groups=groups, occupancy_flags=flags)
        groups[0] = 'p20'
        flags[0][0] = True
        self.assertEqual(state.block_groups[0], 'p255')
        self.assertFalse(state.occupancy_flags[0][0])
        view = state.as_dict()
        view['applications'][0]['groups'][0]['address'] = 1
        view['occupancy_flags'][0][0] = True
        self.assertEqual(state.applications[0].groups[0].address, 255)
        self.assertFalse(state.occupancy_flags[0][0])
        handler = maintenance_checked(context(pec_group='p255'))
        request = next(handler)
        with self.assertRaises(FrozenInstanceError):
            request.value = True
        with self.assertRaisesRegex(SensorError, 'immutable FreshFormContext'):
            next(handler)
        with self.assertRaises(SensorError):
            FormRequest('setter', 'X', 'unit', None, {}, '0x1', 'X')

    def test_source_fixture_is_numeric_path_free_and_binds_handler_pins(self):
        fixture = Path(__file__).resolve().parents[1] / 'research/fixtures/senlla-fresh-forms-source.json'
        receipt = json.loads(fixture.read_text())
        self.assertFalse(receipt['original_instruction_execution'])
        self.assertFalse(receipt['original_gui_execution'])
        self.assertFalse(receipt['physical_acceptance'])
        text = fixture.read_text()
        self.assertNotIn('/Volumes/', text)
        self.assertNotIn('/Users/', text)
        self.assertEqual(receipt['methods']['CIS_TcdLightLevelSensor.TcdST7LightLevelSensor.HandleFormBroadcastChecked']['address'], '0xfa7220')
        self.assertEqual(receipt['methods']['CIS_TStringAttribute.TStringAttribute.SetValue']['address'], '0x7f39a0')
        self.assertEqual(receipt['unit_name']['tag_attribute_writer']['maximum_utf16_code_units'], 32)


if __name__ == '__main__':
    unittest.main()
