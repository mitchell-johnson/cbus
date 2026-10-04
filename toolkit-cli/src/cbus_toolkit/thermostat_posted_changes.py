"""Explicit delivery of source-owned thermostat plant message 0x423.

An operation position selects an event issued in this fresh history. It is
not a transferable continuation. This component models the owned handler;
it does not execute PostMessage or reproduce Windows queue timing.
"""
from __future__ import annotations

from .thermostat_templates import ThermostatTemplateError


class _PostedChange:
    __slots__ = ('owner', 'queue', 'position')

    def __init__(self, owner, queue, position):
        self.owner, self.queue, self.position = owner, queue, position


class PlantChangeQueue:
    """Private per-form event authority, with exact-once explicit delivery."""

    def __init__(self, owner, handler):
        if handler is not None and not callable(handler):
            raise ThermostatTemplateError('Plant change requires an owned handler or nil')
        self._owner, self._handler = owner, handler
        self._issued = {}
        self._consumed = set()
        self._events = []

    @staticmethod
    def _position(value):
        if type(value) is not int or value < 1:
            raise ThermostatTemplateError('Plant event position must be a positive integer')
        return value

    def post(self, position):
        """Called only by this owner's explicit plant OnChange producer."""
        position = self._position(position)
        if position in self._issued:
            raise ThermostatTemplateError('Plant OnChange position already issued an event')
        token = _PostedChange(self._owner, self, position)
        self._issued[position] = token
        self._events.append({'event': 'post', 'position': position, 'message': 0x423,
            'wParam': 0, 'lParam': 0, 'target': 'owned-plant-form',
            'host_post_executed': False})
        return token

    def dispatch(self, posted_by, position):
        """Resolve an earlier history selector to its actual private token."""
        posted_by = self._position(posted_by)
        token = self._issued.get(posted_by)
        if token is None:
            raise ThermostatTemplateError('No plant event was issued by this owner at that position')
        return self._dispatch(token, position)

    def _dispatch(self, token, position):
        position = self._position(position)
        if (type(token) is not _PostedChange or token.queue is not self
                or token.owner is not self._owner
                or self._issued.get(token.position) is not token):
            raise ThermostatTemplateError('Plant event does not belong to this fresh owner')
        if token.position >= position:
            raise ThermostatTemplateError('Plant dispatch must follow its OnChange producer')
        if token.position in self._consumed:
            raise ThermostatTemplateError('Plant event has already been consumed')
        # The message has left the queue before its handler runs. An exception
        # cannot authorize a second delivery or an automatic retry.
        self._consumed.add(token.position)
        receipt = {'event': 'dispatch', 'position': position, 'posted_by': token.position,
            'message': 0x423, 'wParam': 0, 'lParam': 0, 'consumed': True,
            'handler_bound': self._handler is not None, 'handler_completed': False}
        self._events.append(receipt)
        if self._handler is not None:
            self._handler()
        receipt['handler_completed'] = True
        return dict(receipt)

    def as_dict(self):
        return {'profile': 'owned-plant-message-explicit-delivery-v1',
            'events': [dict(row) for row in self._events],
            'pending_positions': [p for p in self._issued if p not in self._consumed],
            'host_queue_timing_reproduced': False,
            'detached_continuation_admitted': False}
