"""Indexed StaticTextEditor edits and explicit cell transactions, without a GUI."""
from __future__ import annotations

from collections.abc import Mapping

from .edlt import EdltError
from .edlt_static_grid import StaticGrid, current, loaded_name, row_bytes


def _text(value):
    if type(value) is not str:
        raise EdltError('Static text cells require string text')
    try:
        utf16 = value.encode('utf-16-le')
    except UnicodeEncodeError as error:
        raise EdltError('Static text cannot contain an unpaired surrogate') from error
    if len(utf16) > 128:
        raise EdltError('Static text grid permits at most 64 UTF-16 units per cell')
    return value


def _index(value):
    if type(value) is not int or not 0 <= value < 64:
        raise EdltError('Static text cells require index0..63')
    return value


def normalize(operation):
    if (not isinstance(operation, Mapping)
            or operation.get('op') != 'static-text-dialog'
            or set(operation) - {'op', 'edits', 'events', 'close'}):
        raise EdltError('Invalid static-text-dialog operation')
    close = operation.get('close', 'button')
    if close not in ('button', 'window'):
        raise EdltError('Static text close must be button or window; the original has no cancel rollback')
    if ('edits' in operation) == ('events' in operation):
        raise EdltError('Static text requires exactly one ordered edits or events array')
    if 'edits' in operation:
        edits = operation['edits']
        if not isinstance(edits, (tuple, list)) or len(edits) > 256:
            raise EdltError('Static text edits must be an ordered array of at most 256 committed cells')
        result = []
        for row in edits:
            if not isinstance(row, Mapping) or set(row) != {'index', 'text'}:
                raise EdltError('Static text cells require index0..63 and string text')
            result.append({'index': _index(row['index']), 'text': _text(row['text'])})
        return {'op': 'static-text-dialog', 'edits': result, 'close': close}
    events = operation['events']
    if not isinstance(events, (tuple, list)) or len(events) > 512:
        raise EdltError('Static text events must be an ordered array of at most 512 events')
    result = []
    for row in events:
        if not isinstance(row, Mapping):
            raise EdltError('Static text events require explicit event records')
        kind = row.get('event')
        if kind in ('begin', 'focus') and set(row) <= {'event', 'index', 'column'} and 'index' in row:
            column = row.get('column', 'name')
            if column not in ('name', 'value'):
                raise EdltError('Static grid columns are name and read-only value')
            result.append({'event': kind, 'index': _index(row['index']), 'column': column})
        elif kind == 'input' and set(row) == {'event', 'text'}:
            result.append({'event': kind, 'text': _text(row['text'])})
        elif kind in ('commit', 'cancel') and set(row) == {'event'}:
            result.append({'event': kind})
        else:
            raise EdltError('Unsupported static text cell event')
    return {'op': 'static-text-dialog', 'events': result, 'close': close}


def project(values, operation):
    """Commit a typed grid history and call its source-established close save.

    The original source does not pin the framework's pending-cell modal-close
    sequence. Such a history must explicitly commit, cancel or leave its cell;
    neither close route invents an automatic pending-text result.
    """
    operation = normalize(operation)
    grid = current(values)
    if grid is None:
        grid = StaticGrid(values)
    original = tuple(grid.names)
    names = list(original)
    events, committed, cancelled, pending = [], [], [], None
    # A typed history establishes focus explicitly; it does not assume a GUI
    # activation/focus outcome from a prior host form.
    cell = (None, None)

    def commit(cause):
        nonlocal pending
        if pending is not None:
            index, text = pending
            names[index] = text
            committed.append({'index': index, 'text': text, 'cause': cause})
            pending = None

    for row in operation.get('edits', ()):
        names[row['index']] = row['text']
        committed.append({**row, 'cause': 'supplied-committed-cell'})
    for row in operation.get('events', ()):
        kind = row['event']
        if kind == 'begin':
            if pending is not None:
                raise EdltError('Finish the current static cell before beginning another edit')
            if row['column'] != 'name':
                raise EdltError('Static grid Value cells are read-only')
            cell = (row['index'], row['column'])
            pending = (row['index'], names[row['index']])
        elif kind == 'input':
            if pending is None:
                raise EdltError('Static text input requires an active cell editor')
            pending = (pending[0], row['text'])
        elif kind == 'commit':
            commit('explicit-cell-commit')
        elif kind == 'cancel':
            if pending is not None:
                cancelled.append({'index': pending[0], 'discarded_text': pending[1]})
                pending = None
        elif kind == 'focus':
            selected = (row['index'], row['column'])
            if selected != cell:
                commit('cell-focus-validation')
            cell = selected
        events.append({**row, 'active_editor': pending is not None,
                       'current_index': cell[0], 'current_column': cell[1]})
    if pending is not None:
        raise EdltError('Pending static cell close is not source-established; commit, cancel or move cell focus first')
    grid.names[:] = names
    changes, setters = grid.save(values)
    receipts = []
    for index in setters:
        data = bytes(changes.get(f'StaticTextString{index}', row_bytes(values, index)))
        head = data.split(b'\0', 1)[0]
        try:
            strict = head.decode('utf-8')
        except UnicodeDecodeError:
            strict = None
        receipts.append({'index': index, 'before': original[index],
                         'committed_text': names[index], 'stored_bytes': list(data),
                         'stored_text': strict, 'loaded_text': loaded_name(data),
                         'utf8_prefix_split': strict is None,
                         'bytes_changed': f'StaticTextString{index}' in changes})
    return changes, {
        'format': 'cbus-edlt-static-text-dialog-operation-v2',
        'close': operation['close'],
        'committed_edits': [{'index': row['index'], 'text': row['text']} for row in committed],
        'cell_commits': committed, 'cancelled_cell_edits': cancelled,
        'editor_events': events, 'pending_editor_at_close': False,
        'pending_close_inferred': False,
        'rows': receipts, 'save_static_text_called_on_close': True,
        'accepted_result_checked': False, 'cancel_rollback': False,
        'allocated_indices': [], 'automatic_selection': False,
        'existing_references_reindexed': False,
        'retained_static_labels_used': current(values) is not None,
        'loaded_utf8_fallback': 'dotnet-framework-replacement',
        'uncommitted_gui_cell_behavior_verified': False,
        'native_dialog_executed': False,
    }
