"""Owned plant-message delivery, independent of Windows or a C-Gate server."""
import copy

import pytest

from cbus_toolkit.thermostat_posted_changes import PlantChangeQueue
from cbus_toolkit.thermostat_templates import ThermostatTemplateError


def test_explicit_delivery_invokes_current_owned_handler_once():
    calls = []
    queue = PlantChangeQueue(object(), lambda: calls.append('plant-update'))
    queue.post(2)
    assert calls == []
    assert queue.as_dict()['pending_positions'] == [2]
    assert queue.dispatch(2, 4) == {'event': 'dispatch', 'position': 4, 'posted_by': 2,
        'message': 1059, 'wParam': 0, 'lParam': 0, 'consumed': True,
        'handler_bound': True, 'handler_completed': True}
    assert calls == ['plant-update']
    with pytest.raises(ThermostatTemplateError, match='already been consumed'):
        queue.dispatch(2, 5)
    assert calls == ['plant-update']
    assert queue.as_dict()['pending_positions'] == []


def test_nil_handler_consumes_without_invocation():
    queue = PlantChangeQueue(object(), None)
    queue.post(1)
    assert queue.dispatch(1, 2)['handler_bound'] is False
    assert queue.as_dict()['pending_positions'] == []


def test_handler_failure_preserves_consumption_and_partial_effect():
    calls = []
    def fail():
        calls.append('before-fault')
        raise RuntimeError('handler-fault')
    queue = PlantChangeQueue(object(), fail)
    queue.post(1)
    with pytest.raises(RuntimeError, match='handler-fault'):
        queue.dispatch(1, 2)
    with pytest.raises(ThermostatTemplateError, match='already been consumed'):
        queue.dispatch(1, 3)
    assert calls == ['before-fault']
    state = queue.as_dict()
    assert state['pending_positions'] == []
    assert state['events'][-1]['consumed'] is True
    assert state['events'][-1]['handler_completed'] is False


@pytest.mark.parametrize('position', [0, -1, True, None, '1', 1.0])
def test_position_schema_refuses_without_issuing(position):
    queue = PlantChangeQueue(object(), None)
    with pytest.raises(ThermostatTemplateError, match='positive integer'):
        queue.post(position)
    assert queue.as_dict()['events'] == []


def test_unknown_and_future_selectors_preserve_pending_event():
    calls = []
    queue = PlantChangeQueue(object(), lambda: calls.append(1))
    queue.post(3)
    for anchor, position in [(1, 4), (3, 3), (3, 2)]:
        with pytest.raises(ThermostatTemplateError):
            queue.dispatch(anchor, position)
    assert calls == []
    assert queue.as_dict()['pending_positions'] == [3]
    queue.dispatch(3, 4)
    assert calls == [1]


def test_copied_and_foreign_tokens_cannot_deliver_owned_event():
    calls = []
    owner = object()
    queue = PlantChangeQueue(owner, lambda: calls.append(1))
    token = queue.post(1)
    foreign = PlantChangeQueue(owner, None).post(1)
    for invalid in [copy.copy(token), copy.deepcopy(token), foreign, {'posted_by': 1}]:
        with pytest.raises(ThermostatTemplateError, match='fresh owner'):
            queue._dispatch(invalid, 2)
    assert calls == []
    assert queue.as_dict()['pending_positions'] == [1]
    queue.dispatch(1, 2)
    assert calls == [1]


def test_duplicate_producer_refuses_and_receipt_has_no_authority():
    queue = PlantChangeQueue(object(), None)
    queue.post(1)
    with pytest.raises(ThermostatTemplateError, match='already issued'):
        queue.post(1)
    state = queue.as_dict()
    state['events'][0]['position'] = 99
    state['pending_positions'].append(99)
    assert queue.as_dict()['pending_positions'] == [1]
    assert queue.as_dict()['events'][0]['position'] == 1
    with pytest.raises(ThermostatTemplateError):
        queue.dispatch(99, 100)


def test_multiple_posts_remain_distinct_and_explicit_order_is_preserved():
    state = {'plant': 3}
    calls = []
    queue = PlantChangeQueue(object(), lambda: calls.append(state['plant']))
    queue.post(1)
    state['plant'] = 7
    queue.post(2)
    queue.dispatch(1, 3)
    state['plant'] = 9
    queue.dispatch(2, 4)
    assert calls == [7, 9]
    assert queue.as_dict()['pending_positions'] == []
