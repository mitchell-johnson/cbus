"""Accepted/cancelled blank-address Trigger and Action dialogs.

This is a pure projection of the pinned AddGroup/AddLevel dialog branches.
The existing native SceneManager transaction owns creation and persistence;
this module never performs I/O or claims original WinForms execution.
"""
from __future__ import annotations

from .edlt import EdltError
from .edlt_add_dialog import (
    AddDialogError, _message, _rewrite, _trim, _upper, accept_group_dialog,
)

KINDS = ('add-trigger-dialog', 'add-action-dialog')


def normalize(operation):
    row = dict(operation)
    if row['op'] not in KINDS:
        raise EdltError('Unsupported SceneManager Add dialog')
    if set(row) - {'op', 'scene', 'address', 'name', 'cancel'} or 'scene' not in row:
        raise EdltError('SceneManager Add dialog requires scene and only address/name/cancel options')
    if type(row['scene']) is not int or not 1 <= row['scene'] <= 8:
        raise EdltError('Scene must be 1..8')
    if 'address' in row and (type(row['address']) is not int or not 0 <= row['address'] <= 254):
        raise EdltError('SceneManager Add dialog address must be 0..254')
    if 'name' in row and type(row['name']) is not str:
        raise EdltError('SceneManager Add dialog name must be text')
    if 'cancel' in row and type(row['cancel']) is not bool:
        raise EdltError('SceneManager Add dialog cancel must be boolean')
    return {key: row[key] for key in ('op', 'scene', 'address', 'name', 'cancel') if key in row}


def resolve(operation, existing, project, *, group=None):
    """Resolve against the complete inventory at this operation's position.

    Add Level checks duplicate *entered* names before trimming the stored
    name; unlike Group Add this intentionally admits a spaced duplicate.
    Both allocators reserve255. Cancel frees the seeded provisional object.
    """
    row = normalize(operation)
    kind = 'Group' if row['op'] == KINDS[0] else 'Level'
    free = [n for n in range(255) if n not in existing]
    noun = 'Trigger Group' if kind == 'Group' else 'Action Selector'
    if not free:
        raise AddDialogError(_message(2271, noun))
    first = free[0]
    seed = ('Trigger Group' if kind == 'Group' else 'Level') + ' ' + str(first)
    shown = _rewrite(seed, noun, first)
    receipt = dict(operation=row, kind=kind, application=202,
                   first_free_address=first, seeded_name=seed, shown_name=shown,
                   outcome='cancelled' if row.get('cancel', False) else 'accepted',
                   object_created=False, original_dialog_executed=False)
    if kind == 'Level':
        receipt['group'] = group
    if row.get('cancel', False):
        return receipt
    if kind == 'Group':
        accepted = accept_group_dialog('SceneTriggerGroup', 202, existing, project,
                                       address=row.get('address'), name=row.get('name'))
        receipt.update(address=accepted.address, name=accepted.name,
                       shown_name=accepted.shown_name)
    else:
        selected = row.get('address', first)
        if selected not in free:
            raise AddDialogError('Add dialog address must be one of the listed free addresses 0..254')
        text = _rewrite(shown, noun, selected)
        text = row.get('name', text)
        accepted = _trim(text)
        if not accepted:
            raise AddDialogError('Add dialog error2211: Action Selector name cannot be blank')
        if accepted == project:
            raise AddDialogError('Add dialog error2213: Action Selector name cannot equal Project Name')
        if any(_upper(tag) == _upper(text) for tag in existing.values()):
            raise AddDialogError('Add dialog error2212: Action Selector entered name already exists')
        receipt.update(address=selected, value=selected, name=accepted)
    return receipt
