"""Source counter/setter boundaries with nested synthetic owner callbacks."""
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_bank_graph import SENLLABankGraph
from cbus_toolkit.senlla_key_references import SENLLAKeyReferences
from cbus_toolkit.senlla_lifecycle import (
    AttributeManager, BooleanAttribute, FlashObject, IntegerAttribute,
    ManagedUpdateObject, NotificationPublisher, ObjectReferenceAttribute, TrackedReferenceHandle, UpdateObject,
)
from cbus_toolkit.sensors import SensorError


class SENLLALifecycleTests(unittest.TestCase):
    def test_independently_derived_reference_vectors(self):
        fixture = Path(__file__).resolve().parents[1] / 'research/fixtures/senlla-lifecycle-source.json'
        source = json.loads(fixture.read_text())
        objects = {None: None, **{index: object() for index in (1, 2, 3)}}
        for case in source['reference_vectors']:
            calls = []

            def before(attribute, decision):
                decision.changed = case['before_changed']
                if 'before_candidate' in case:
                    decision.proposed = objects[case['before_candidate']]

            attribute = ObjectReferenceAttribute(None, objects[case['old']], before_change=before,
                after_change=lambda item: calls.append(item.depth))
            attribute.set(objects[case['original_requested']])
            with self.subTest(case=case):
                self.assertIs(attribute.value, objects[case['assigned']])
                self.assertEqual(calls, case['dedicated_depths'])

    def test_independently_derived_tracked_reference_vectors(self):
        fixture = Path(__file__).resolve().parents[1] / 'research/fixtures/senlla-lifecycle-source.json'
        source = json.loads(fixture.read_text())
        for case in source['tracked_reference_vectors']:
            objects = {None: None, **{index: FlashObject(str(index)) for index in (1, 2)}}
            calls = []
            attribute = ObjectReferenceAttribute(AttributeManager(FlashObject('key0')),
                                                 objects[case['prior']])
            handle = TrackedReferenceHandle(attribute, lambda item: calls.append(item.current))
            handle.activate()
            calls.clear()
            if case['route'] == 'root_update':
                attribute.set(objects[case['current']])
            else:
                objects[case['current']].changed()
            with self.subTest(case=case):
                self.assertEqual(len(calls), case['handler_count'])
                self.assertIs(handle.current, objects[case['current']])

    def test_outer_end_publishes_without_a_dirty_value(self):
        events = []
        owner = UpdateObject('key0', lambda item: events.append(item.depth))
        owner.begin_update()
        owner.begin_update()
        owner.changed()
        owner.end_update()
        self.assertEqual(events, [])
        owner.end_update()
        self.assertEqual(events, [0])
        owner.begin_update()
        owner.end_update()
        self.assertEqual(events, [0, 0])

    def test_equal_boolean_has_no_counter_or_callback_events(self):
        trace, callbacks = [], []
        owner = FlashObject('block0', lambda item: callbacks.append('block'), trace=trace.append)
        manager = AttributeManager(owner, trace=trace.append)
        attribute = BooleanAttribute(manager, False, name='secondary', trace=trace.append,
                                     after_change=lambda item: callbacks.append('secondary'))
        attribute.set(False)
        self.assertEqual((trace, callbacks), ([], []))
        attribute.set(True)
        self.assertEqual(callbacks, ['secondary', 'block'])
        self.assertFalse(owner.updating)

    def test_equal_reference_runs_dedicated_before_parent_publication(self):
        callbacks, trace = [], []
        owner = FlashObject('key0', lambda item: callbacks.append(('key', item.depth)), trace=trace.append)
        manager = AttributeManager(owner, trace=trace.append)
        template = object()
        attribute = ObjectReferenceAttribute(manager, template, name='template', trace=trace.append,
            on_changed=lambda item: callbacks.append(('attribute', item.depth, owner.depth)),
            after_change=lambda item: callbacks.append(('template', item.depth, owner.depth)))
        attribute.set(template)
        self.assertEqual(callbacks, [('attribute', 0, 1), ('template', 0, 1), ('key', 0)])
        self.assertEqual([(item.object_name, item.operation, item.depth) for item in trace
                          if item.operation in ('begin', 'end')],
                         [('key0', 'begin', 1), ('key0.attributes', 'begin', 1), ('template', 'begin', 1),
                          ('template', 'end', 0), ('key0.attributes', 'end', 0), ('key0', 'end', 0)])

    def test_template_parent_update_suppresses_add_block_direct_refresh(self):
        references = SENLLAKeyReferences.from_masks([0] * 8)
        direct, generic, depths = [], [], []
        owner = FlashObject('key0', lambda item: generic.append(item.depth))
        manager = AttributeManager(owner)

        def claim(attribute):
            nonlocal references
            owner.begin_update()
            result = references.add_block(0, 0, key_updating=True)
            references = result.state
            owner.end_update()
            depths.append(owner.depth)
            if not owner.updating:
                direct.extend(references.add_block(0, 0).events[0].direct_refreshes)

        attribute = ObjectReferenceAttribute(manager, None, name='template', after_change=claim)
        attribute.set(object())
        self.assertEqual(references.ordered_references[0], (0,))
        self.assertEqual((depths, direct, generic), ([1], [], [0]))
        # The source does not defer a skipped direct refresh to outer End.
        self.assertEqual(owner.depth, 0)

    def test_nil_reset_dedicated_twice_and_mid_update_recursive_write_ignored(self):
        events = []
        owner = FlashObject('key0', lambda item: events.append(('key', item.depth)))
        manager = AttributeManager(owner)
        replacement = object()

        def reset(attribute):
            events.append(('dedicated', attribute.depth, owner.depth, attribute.value is None))
            if attribute.updating:
                attribute.set(replacement)

        attribute = ObjectReferenceAttribute(manager, object(), name='template', after_change=reset)
        attribute.set(None)
        self.assertEqual(events, [('dedicated', 1, 1, True), ('dedicated', 0, 1, True), ('key', 0)])
        self.assertIsNone(attribute.value)

    def test_equal_nil_has_one_dedicated_callback(self):
        calls = []
        owner = FlashObject('block0')
        attribute = ObjectReferenceAttribute(AttributeManager(owner), None,
            after_change=lambda item: calls.append((item.depth, owner.depth)))
        attribute.set(None)
        self.assertEqual(calls, [(0, 1)])

    def test_forced_equal_nil_calls_reset_and_dedicated_twice(self):
        calls = []
        attribute = ObjectReferenceAttribute(None, None,
            before_change=lambda item, decision: setattr(decision, 'changed', True),
            after_change=lambda item: calls.append(item.depth))
        attribute.set(None)
        self.assertEqual(calls, [1, 0])

    def test_nonnil_replacement_has_one_dedicated_callback(self):
        calls = []
        owner = FlashObject('block0')
        old, new = object(), object()
        attribute = ObjectReferenceAttribute(AttributeManager(owner), old,
            after_change=lambda item: calls.append((item.depth, owner.depth, item.value is new)))
        attribute.set(new)
        self.assertEqual(calls, [(0, 1, True)])

    def test_reference_identity_ignores_value_equality(self):
        class EqualObjects:
            def __eq__(self, other):
                return True
        old, new = EqualObjects(), EqualObjects()
        attribute = ObjectReferenceAttribute(None, old)
        attribute.set(new)
        self.assertIs(attribute.value, new)

    def test_reference_before_change_cancels_assignment_but_not_end_callbacks(self):
        old, new, replacement = object(), object(), object()
        calls = []

        def cancel(attribute, decision):
            self.assertIs(decision.previous, old)
            self.assertIs(decision.proposed, new)
            decision.changed = False
            decision.proposed = replacement

        attribute = ObjectReferenceAttribute(None, old, before_change=cancel,
            after_change=lambda item: calls.append(item.value is old))
        attribute.set(new)
        self.assertIs(attribute.value, old)
        self.assertEqual(calls, [True])

    def test_reference_before_change_proposal_is_ignored(self):
        requested, replacement = object(), object()
        attribute = ObjectReferenceAttribute(None, None,
            before_change=lambda item, decision: setattr(decision, 'proposed', replacement))
        attribute.set(requested)
        self.assertIs(attribute.value, requested)

    def test_nested_other_attribute_callbacks_complete_before_outer_tail(self):
        calls = []
        owner = FlashObject('block0', lambda item: calls.append(('block', item.depth)))
        manager = AttributeManager(owner)
        second = BooleanAttribute(manager, False, name='second',
            after_change=lambda item: calls.append(('second', owner.depth)))

        def first_changed(attribute):
            calls.append(('first-entry', owner.depth))
            second.set(True)
            calls.append(('first-tail', owner.depth))

        first = ObjectReferenceAttribute(manager, None, after_change=first_changed)
        first.set(object())
        self.assertEqual(calls, [('first-entry', 1), ('second', 2), ('first-tail', 1), ('block', 0)])

    def test_final_callback_can_reenter_same_reference_while_parent_still_updating(self):
        calls = []
        owner = FlashObject('key0', lambda item: calls.append(('key', item.depth)))
        pinned = False

        def changed(attribute):
            nonlocal pinned
            calls.append(('template', attribute.depth, owner.depth))
            if not pinned:
                pinned = True
                attribute.set(attribute.value)
                calls.append(('outer-tail', owner.depth))

        attribute = ObjectReferenceAttribute(AttributeManager(owner), None, after_change=changed)
        attribute.set(FlashObject('template24'))
        self.assertEqual(calls, [('template', 0, 1), ('template', 0, 2), ('outer-tail', 1), ('key', 0)])

    def test_tracked_initial_equal_pointer_target_change_and_nil_transition(self):
        calls = []
        owner = FlashObject('key0')
        current = FlashObject('template24')
        attribute = ObjectReferenceAttribute(AttributeManager(owner), current)
        handle = TrackedReferenceHandle(attribute, lambda item: calls.append(item.current))
        handle.activate()
        handle.activate()
        self.assertEqual(calls, [current])
        attribute.set(current)
        self.assertEqual(calls, [current])
        owner.begin_update()
        current.changed()
        owner.end_update()
        self.assertEqual(calls, [current, current])
        attribute.set(None)
        self.assertEqual(calls, [current, current, None])
        current.changed()
        self.assertEqual(calls, [current, current, None])

    def test_tracked_older_observer_reads_newer_observers_nested_current_template(self):
        calls = []
        owner = FlashObject('key0')
        first, final = FlashObject('template17'), FlashObject('template16')
        attribute = ObjectReferenceAttribute(AttributeManager(owner), None)
        old = TrackedReferenceHandle(attribute, lambda item: calls.append(('older', item.current.name)))

        def newer(item):
            calls.append(('newer', item.current.name))
            if item.current is first:
                attribute.set(final)

        new = TrackedReferenceHandle(attribute, newer)
        old.activate()
        new.activate()
        attribute.set(first)
        self.assertEqual(calls, [('newer', 'template17'), ('newer', 'template16'), ('older', 'template16')])
        self.assertIs(old.current, final)
        self.assertIs(new.current, final)

    def test_tracked_callback_error_propagates_without_rolling_back_subscription(self):
        current = FlashObject('template24')
        attribute = ObjectReferenceAttribute(None, current)

        def fail(handle):
            raise ValueError('tracked')

        handle = TrackedReferenceHandle(attribute, fail)
        with self.assertRaisesRegex(ValueError, 'tracked'):
            handle.activate()
        self.assertTrue(handle.active)
        self.assertIs(handle.current, current)

    def test_final_dedicated_error_leaves_manager_parent_updating_without_rollback(self):
        owner = FlashObject('key0')
        manager = AttributeManager(owner)
        requested = object()

        def fail(attribute):
            raise ValueError('synthetic source callback error')

        attribute = ObjectReferenceAttribute(manager, None, after_change=fail)
        with self.assertRaisesRegex(ValueError, 'synthetic'):
            attribute.set(requested)
        self.assertIs(attribute.value, requested)
        self.assertEqual((attribute.depth, manager.depth, owner.depth), (0, 1, 1))

    def test_before_change_error_still_finishes_the_attribute_update(self):
        calls = []
        owner = FlashObject('key0', lambda item: calls.append('key'))
        manager = AttributeManager(owner)

        def fail(attribute, decision):
            raise ValueError('before')

        attribute = ObjectReferenceAttribute(manager, None, before_change=fail,
            after_change=lambda item: calls.append('after'))
        with self.assertRaisesRegex(ValueError, 'before'):
            attribute.set(object())
        self.assertIsNone(attribute.value)
        self.assertEqual(calls, ['after', 'key'])
        self.assertEqual((attribute.depth, manager.depth, owner.depth), (0, 0, 0))

    def test_managed_reentry_guard_and_explicit_rearm(self):
        calls = []

        def subscriber(item):
            calls.append('managed')
            item.changed()

        owner = ManagedUpdateObject('managed', lambda item: calls.append('generic'),
                                    generic_subscribers=(subscriber,))
        owner.changed()
        self.assertEqual(calls, ['managed', 'generic', 'generic'])
        owner.changed()
        self.assertEqual(calls[-1], 'generic')
        self.assertEqual(calls.count('managed'), 1)
        owner.resolve_change()
        owner.changed()
        self.assertEqual(calls.count('managed'), 2)

    def test_custom_object_rearms_each_changed_reference_notification_before_generic(self):
        calls = []
        owner = FlashObject('block0', lambda item: calls.append('generic'),
            generic_subscribers=(lambda item: calls.append('managed'),),
            reference_notification=lambda item: calls.append('references'))
        owner.changed()
        owner.changed()
        self.assertEqual(calls, ['managed', 'references', 'generic'] * 2)

    def test_object_getter_rearms_attribute_and_parent_without_notification(self):
        calls = []
        owner = ManagedUpdateObject('key0')
        attribute = ObjectReferenceAttribute(AttributeManager(owner), None,
            generic_subscribers=(lambda item: calls.append('attribute'),))
        attribute.changed()
        attribute.changed()
        self.assertEqual(calls, ['attribute'])
        self.assertTrue(attribute.snapshot()['published'])
        self.assertTrue(owner.snapshot()['published'])
        self.assertIsNone(attribute.value)
        self.assertFalse(attribute.snapshot()['published'])
        self.assertFalse(owner.snapshot()['published'])
        self.assertEqual(calls, ['attribute'])
        attribute.changed()
        self.assertEqual(calls, ['attribute', 'attribute'])

    def test_publisher_visits_newest_first_and_current_indices(self):
        calls = []
        publisher = NotificationPublisher()
        first = lambda item: calls.append('first')

        def second(item):
            calls.append('second')
            publisher.subscribe(lambda other: calls.append('later'))

        publisher.subscribe(first)
        publisher.subscribe(first)
        publisher.subscribe(second)
        publisher.notify(None)
        self.assertEqual(calls, ['second', 'first'])
        publisher.unsubscribe(second)
        publisher.notify(None)
        self.assertEqual(calls, ['second', 'first', 'later', 'first'])

    def test_boolean_getter_rearms_attribute_and_parent(self):
        owner = ManagedUpdateObject('block0')
        attribute = BooleanAttribute(AttributeManager(owner))
        attribute.changed()
        self.assertTrue(attribute.snapshot()['published'])
        self.assertTrue(owner.snapshot()['published'])
        self.assertFalse(attribute.value)
        self.assertFalse(attribute.snapshot()['published'])
        self.assertFalse(owner.snapshot()['published'])

    def test_integer_callback_replacement_cancellation_and_inclusive_bounds(self):
        calls = []
        owner = FlashObject('block0', lambda item: calls.append('block'))
        manager = AttributeManager(owner)

        def normalize(attribute, decision):
            decision.proposed = min(decision.proposed, 255)

        attribute = IntegerAttribute(manager, 0, minimum=0, maximum=255, before_change=normalize,
            after_change=lambda item: calls.append(item.value))
        attribute.set(300)
        self.assertEqual(attribute.value, 255)
        self.assertEqual(calls, [255, 'block'])
        attribute.set(255)
        self.assertEqual(calls, [255, 'block'])
        attribute.set(0)
        self.assertEqual(attribute.value, 0)
        with self.assertRaises(SensorError):
            attribute.set(-1)
        self.assertEqual((attribute.depth, manager.depth, owner.depth), (0, 0, 0))
        attribute.before_change = lambda item, decision: setattr(decision, 'changed', False)
        attribute.set(-1)
        self.assertEqual(attribute.value, 0)

    def test_integer_before_runs_on_equal_disabled_attribute_without_update(self):
        calls = []
        owner = FlashObject('block0')
        attribute = IntegerAttribute(AttributeManager(owner), 4, enabled=False,
            before_change=lambda item, decision: calls.append((item.depth, owner.depth, decision.changed)))
        attribute.set(4)
        self.assertEqual(calls, [(0, 0, False)])

    def test_integer_equal_bounds_disable_range_check_and_direct_getter_does_not_rearm(self):
        attribute = IntegerAttribute(AttributeManager(FlashObject('block0')), 0,
                                     minimum=0, maximum=0)
        for value in (-(1 << 31), -1, 0, (1 << 31) - 1):
            with self.subTest(value=value):
                attribute.set(value)
                self.assertEqual(attribute.value, value)
        self.assertTrue(attribute.snapshot()['published'])
        for bad in (True, None, 1.0, -(1 << 31) - 1, 1 << 31):
            with self.subTest(bad=bad), self.assertRaises(SensorError):
                attribute.set(bad)

    def test_equal_expiry_override_reference_publishes_actual_block_observer(self):
        graph = SENLLABankGraph.fresh().with_references(SENLLAKeyReferences(((0,),) + ((),) * 7))
        graph = graph.with_maintenance(active=True, block=0)
        self.assertTrue(graph.banks[0].switch_allowed)

        def block_changed(item):
            nonlocal graph
            graph = graph.block_changed(0)

        block = FlashObject('block0', reference_notification=block_changed)
        override = ObjectReferenceAttribute(AttributeManager(block), None)
        override.set(None)
        self.assertFalse(graph.banks[0].switch_allowed)

    def test_balanced_source_domain_refuses_unmatched_end(self):
        owner = UpdateObject('key0')
        with self.assertRaises(SensorError):
            owner.end_update()
        self.assertEqual(owner.depth, 0)

    def test_snapshot_is_detached_and_does_not_resolve_or_publish(self):
        owner = FlashObject('block0')
        owner.changed()
        snapshot = owner.snapshot()
        snapshot['depth'] = 8
        snapshot['published'] = False
        self.assertEqual(owner.depth, 0)
        self.assertTrue(owner.snapshot()['published'])


if __name__ == '__main__':
    unittest.main()
