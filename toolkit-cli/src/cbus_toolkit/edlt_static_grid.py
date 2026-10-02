"""Retained StaticLabels and explicit DataGridView cell transactions.

Only the parent planner activates the private context. JSON cannot provide a
cache. The ordinary standalone label allocator keeps its existing policy.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from collections.abc import Mapping
from inspect import signature


def _error(message):
    from .edlt import EdltError
    return EdltError(message)


def decode_utf8(data):
    """.NET Framework UTF8Encoding fallback, including invalid-second groups.

    Its slow path consumes a continuation byte before rejecting an overlong,
    surrogate or out-of-range prefix. Python's replacement decoder instead
    rejects that prefix before consuming its second byte.
    """
    result, index = [], 0
    while index < len(data):
        first = data[index]
        if first < 128:
            result.append(chr(first)); index += 1
            continue
        length = (2 if 194 <= first <= 223 else 3 if 224 <= first <= 239
                  else 4 if 240 <= first <= 244 else 0)
        if not length:
            result.append('\ufffd'); index += 1
            continue
        end = index + 1
        while end < min(index + length, len(data)):
            value = data[end]
            if not 128 <= value <= 191:
                break
            end += 1
            if end == index + 2 and (
                    (first == 224 and value < 160)
                    or (first == 237 and value >= 160)
                    or (first == 240 and value < 144)
                    or (first == 244 and value >= 144)):
                break
        chunk = bytes(data[index:end])
        try:
            result.append(chunk.decode('utf-8'))
        except UnicodeDecodeError:
            result.append('\ufffd')
        index = end
    return ''.join(result)


def row_bytes(values, index):
    try:
        data = bytes(values[f'StaticTextString{index}'])
    except (KeyError, TypeError, ValueError) as error:
        raise _error('Static text requires all 64 complete byte rows') from error
    if len(data) != 64:
        raise _error('Static text rows must contain exactly 64 bytes')
    return data


def loaded_name(data):
    return decode_utf8(data.split(b'\0', 1)[0])


def stored_row(text):
    encoded = text.encode('utf-8')[:63]
    if b'\0' in encoded:
        encoded = encoded[:encoded.index(0) + 1]
    return (encoded + b'\0').ljust(64, b'\0')


class StaticGrid:
    """One parent unit's 64 retained DataStore.Name values."""
    def __init__(self, values):
        self.names = [loaded_name(row_bytes(values, i)) for i in range(64)]

    def find(self, text):
        return next((i for i, name in enumerate(self.names) if name == text), None)

    def allocate(self, index, text):
        self.names[index] = text

    def save(self, values):
        changes, setters = {}, []
        for index, name in enumerate(self.names):
            previous = row_bytes(values, index)
            if loaded_name(previous) == name:
                continue
            data = stored_row(name)
            setters.append(index)
            if data != previous:
                changes[f'StaticTextString{index}'] = tuple(data)
        return changes, setters


class _Holder:
    def __init__(self):
        self.grid = None


_current = ContextVar('cbus_edlt_private_static_grid', default=None)


@contextmanager
def scope():
    token = _current.set(_Holder())
    try:
        yield
    finally:
        _current.reset(token)


def initialize(values):
    holder = _current.get()
    if holder is not None:
        holder.grid = StaticGrid(values)


def current(values):
    holder = _current.get()
    if holder is None:
        return None
    if holder.grid is None:
        holder.grid = StaticGrid(values)
    return holder.grid


def _parent_history_active():
    """Private shape deferral only; the allocator still proves Name reuse."""
    return _current.get() is not None


def retained_history(function):
    """Each replay gets a fresh cache, including nested and failed plans."""
    parameters = signature(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        operations = parameters.bind_partial(*args, **kwargs).arguments.get('operations', ())
        enabled = isinstance(operations, (list, tuple)) and any(
                isinstance(row, Mapping) and row.get('op') == 'static-text-dialog'
                for row in operations)
        if enabled:
            with scope():
                return function(*args, **kwargs)
        # A nested ordinary parent must not borrow the enclosing grid table.
        token = _current.set(None)
        try:
            return function(*args, **kwargs)
        finally:
            _current.reset(token)
    return wrapped
