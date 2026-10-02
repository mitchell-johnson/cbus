"""Source-established indexed StaticTextEditor edits, without a GUI.

Closing the original form always calls SaveStaticText.  There is no accepted
result check and no index allocation: committed cell edits change their existing
rows, including rows currently referenced by a widget, page or scene.
"""
from __future__ import annotations

from collections.abc import Mapping

from .edlt import EdltError


def normalize(operation):
    if (not isinstance(operation, Mapping)
            or operation.get('op') != 'static-text-dialog'
            or set(operation) - {'op', 'edits', 'close'}):
        raise EdltError('Invalid static-text-dialog operation')
    close = operation.get('close', 'button')
    if close not in ('button', 'window'):
        raise EdltError('Static text close must be button or window; the original has no cancel rollback')
    edits = operation.get('edits')
    if not isinstance(edits, (tuple, list)) or len(edits) > 256:
        raise EdltError('Static text edits must be an ordered array of at most 256 committed cells')
    result = []
    for row in edits:
        if (not isinstance(row, Mapping) or set(row) != {'index', 'text'}
                or type(row['index']) is not int or not 0 <= row['index'] < 64
                or type(row['text']) is not str):
            raise EdltError('Static text cells require index0..63 and string text')
        try:
            utf16 = row['text'].encode('utf-16-le')
        except UnicodeEncodeError as error:
            raise EdltError('Static text cannot contain an unpaired surrogate') from error
        if len(utf16) > 128:
            raise EdltError('Static text grid permits at most 64 UTF-16 units per cell')
        result.append({'index': row['index'], 'text': row['text']})
    return {'op': 'static-text-dialog', 'edits': result, 'close': close}


def project(values, operation):
    """Return changed PP bytes and an ordered dialog receipt.

    PPAttribute.ValueAsUtf8String writes the first 63 encoded bytes (including a
    NUL if encountered), then a terminator.  It can split a UTF-8 character.
    This differs intentionally from the existing label-allocation API.
    """
    operation = normalize(operation)
    labels = {}
    for index in range(64):
        name = f'StaticTextString{index}'
        try:
            data = bytes(values[name])
        except (KeyError, TypeError, ValueError) as error:
            raise EdltError('Static text requires all 64 complete byte rows') from error
        if len(data) != 64:
            raise EdltError('Static text rows must contain exactly 64 bytes')
        # The retained parent deliberately refuses evaluation of malformed
        # existing UTF-8 rather than guessing Encoding.UTF8 replacement rules.
        try:
            labels[index] = data.split(b'\0', 1)[0].decode('utf-8')
        except UnicodeDecodeError as error:
            raise EdltError('Static text grid requires valid loaded UTF-8 rows') from error
    original = dict(labels)
    for row in operation['edits']:
        labels[row['index']] = row['text']
    changes, receipts = {}, []
    for index, label in labels.items():
        if label == original[index]:
            continue
        encoded = label.encode('utf-8')[:63]
        if b'\0' in encoded:
            encoded = encoded[:encoded.index(0) + 1]
        data = (encoded + b'\0').ljust(64, b'\0')
        changes[f'StaticTextString{index}'] = tuple(data)
        try:
            decoded = data.split(b'\0', 1)[0].decode('utf-8')
        except UnicodeDecodeError:
            decoded = None
        receipts.append({'index': index, 'before': original[index],
                         'committed_text': label, 'stored_bytes': list(data),
                         'stored_text': decoded,
                         'utf8_prefix_split': decoded is None})
    return changes, {
        'format': 'cbus-edlt-static-text-dialog-operation-v1',
        'close': operation['close'], 'committed_edits': operation['edits'],
        'rows': receipts, 'save_static_text_called_on_close': True,
        'accepted_result_checked': False, 'cancel_rollback': False,
        'allocated_indices': [], 'automatic_selection': False,
        'existing_references_reindexed': False,
        'uncommitted_gui_cell_behavior_verified': False,
        'native_dialog_executed': False,
    }
