"""Source-bound Corridor and Activation Add histories, without native I/O.

Accepted replies are lowered to the owning panel's SelectedValue binding.
The outer parent metadata manager owns database creation and persistence.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from .edlt import EdltError
from .edlt_add_dialog import (accept_group_dialog, _rewrite, _message,
                             default_group_name, standard_group_name, TARGETS, _list_application)
from .edlt_activation import WAKE_MODES
from .edlt_corridor import FIELDS
from .edlt_scene_add_dialog import resolve as level_dialog

KINDS = ('add-corridor-dialog', 'add-activation-group-dialog',
         'add-activation-action-dialog', 'add-application-dialog')


@dataclass(frozen=True)
class ParentAddDialog:
    document: str

    def as_dict(self):
        return json.loads(self.document)


def normalize(value):
    kind = value.get('op')
    if kind == 'add-application-dialog':
        from .edlt_application_add_dialog import normalize as application_normalize
        return application_normalize(value)
    fields = {'op', 'address', 'name', 'cancel'}
    if kind == KINDS[0]:
        fields.add('field')
        if value.get('field') not in ('link_group', 'office_group', 'corridor_group'):
            raise EdltError('add-corridor-dialog field must be link_group, office_group or corridor_group')
    if kind not in KINDS or set(value) - fields:
        raise EdltError('Parent Add dialog contains unsupported fields')
    if 'address' in value and (type(value['address']) is not int
                              or not 0 <= value['address'] <= 254):
        raise EdltError('Parent Add dialog address must be 0..254')
    if 'name' in value and type(value['name']) is not str:
        raise EdltError('Parent Add dialog name must be text')
    if 'cancel' in value and type(value['cancel']) is not bool:
        raise EdltError('Parent Add dialog cancel must be boolean')
    return {key: value[key] for key in ('op', 'field', 'address', 'name', 'cancel')
            if key in value}


def resolve(operations, values, project_name, existing_groups, existing_levels,
            preceding_groups, *, advance=None, application_names=None, other_networks=()):
    """Replay controls and Add replies in order against complete inventories.

    ``advance`` projects ordinary controls using the owning source-bound
    editor. It may return exact additional objects (SceneManager getters),
    which become visible only to subsequent dialogs. Later controls never
    supply an earlier dialog's application, enabled state or inventory.
    """
    groups = {app: dict(rows) for app, rows in existing_groups.items()}
    levels = {key: dict(rows) for key, rows in existing_levels.items()}
    state = dict(values)
    application_names = ({app: 'Application ' + str(app) for app in groups}
                         if application_names is None else dict(application_names))
    receipts, accepted_groups, accepted_levels, rewritten = [], [], [], []
    for index, original in enumerate(operations):
        for app, address, tag in preceding_groups(index):
            groups.setdefault(app, {}).setdefault(address, tag)
        row = dict(original)
        if row['op'] not in (*KINDS, 'add-dialog'):
            if advance is not None:
                state, row = advance(index, row, state, groups, levels)
            rewritten.append(row)
            continue
        if row['op'] == 'add-application-dialog':
            from .edlt_application_add_dialog import resolve as application_dialog
            receipt = application_dialog(row, application_names, project_name, other_networks)
            receipt.update(operation_index=index + 1, object_created=False,
                           created_before_pp_staging=False)
            receipts.append(ParentAddDialog(json.dumps(receipt, sort_keys=True)))
            binding = dict(op='parent-add-binding', panel='applications', option=row['field'])
            if receipt['outcome'] == 'cancelled':
                binding['cancelled'] = True
            else:
                application_names[receipt['address']] = receipt['name']
                groups[receipt['address']] = {}
                accepted_levels.append(receipt)
                binding['value'] = receipt['address']
                if advance is not None:
                    binding['_application_name'] = receipt['name']
            if advance is not None:
                state, binding = advance(index, binding, state, groups, levels)
            elif receipt['outcome'] == 'accepted':
                state['PrimaryApplication' if row['field'] == 'primary' else 'SecondaryApplication'] = (receipt['address'],)
            rewritten.append(binding)
            continue
        primary = state['PrimaryApplication'][0]
        mode, trigger = state['ProximityMode'][0], state['ProximityGroup'][0]
        show_missing = ()
        if row['op'] == 'add-dialog':
            field = row['field']
            panel, option, rule = TARGETS[field]
            application = _list_application(rule, state, mode)
        elif row['op'] == KINDS[0]:
            panel, option = 'corridor', row['field']
            field = FIELDS[option]
            if primary == 255 or primary not in groups:
                raise EdltError('Corridor Add requires an existing named primary application')
            # Show binding clears missing stored selections before Add.
            raw = {role: state[name][0] for role, name in FIELDS.items()}
            show_missing = tuple((FIELDS[role], raw[role])
                for role in ('link_group', 'office_group', 'corridor_group')
                if raw[role] != 255 and raw[role] not in groups[primary])
            for role in ('link_group', 'office_group', 'corridor_group'):
                if raw[role] != 255 and raw[role] not in groups[primary]:
                    raw[role] = 255
                    state[FIELDS[role]] = (255,)
            if option != 'link_group' and raw['link_group'] == 255:
                raise EdltError('Office/Corridor Add is disabled while Link group is255')
            application = primary
        else:
            panel = 'activation'
            if not state['ActivityDuration'][0] or mode not in (2, 3):
                raise EdltError('Activation Add requires enabled standby and an event wake mode')
            application = 202 if mode == 3 else primary
            if application == 255:
                raise EdltError('Activation Add requires a configured list application')
            field = 'ProximityLevel' if row['op'] == KINDS[2] else 'ProximityGroup'
            option = 'action' if field == 'ProximityLevel' else 'group'
        if field == 'ProximityLevel':
            if mode != 3 or trigger == 255 or trigger not in groups.get(202, {}):
                raise EdltError('Activation action Add requires a selected existing or earlier added trigger group')
            current = levels.setdefault((202, trigger), {})
            receipt = level_dialog({'op': 'add-action-dialog', 'scene': 1,
                                    **{k: row[k] for k in ('address', 'name', 'cancel') if k in row}},
                                   current, project_name, group=trigger)
            receipt['operation'] = row
        else:
            current = groups.setdefault(application, {})
            if row.get('cancel', False):
                free = [n for n in range(255) if n not in current]
                if len(current) >= 256 or not free:
                    raise EdltError(_message(2271, standard_group_name(application)))
                first = free[0]
                seed = default_group_name(application) + ' ' + str(first)
                receipt = dict(operation=row, kind='Group', application=application,
                               first_free_address=first, seeded_name=seed,
                               shown_name=_rewrite(seed, standard_group_name(application), first),
                               outcome='cancelled')
            else:
                accepted = accept_group_dialog(field, application, current, project_name,
                                               address=row.get('address'), name=row.get('name'))
                accepted_groups.append(accepted)
                receipt = {**accepted.as_dict(), 'operation': row, 'outcome': 'accepted'}
        receipt.update(field=field, operation_index=index + 1,
                       object_created=False, created_before_pp_staging=False,
                       original_dialog_executed=False)
        if show_missing:
            receipt['show_missing'] = {
                'application': primary,
                'selections': [{'parameter': name, 'before': [address], 'after': [255]}
                               for name, address in show_missing],
            }
        receipts.append(ParentAddDialog(json.dumps(receipt, sort_keys=True)))
        binding = dict(op='parent-add-binding', panel=panel, option=option)
        if receipt['outcome'] == 'cancelled':
            binding['cancelled'] = True
        else:
            current[receipt['address']] = receipt['name']
            binding['value'] = receipt['address']
            state[field] = (receipt['address'],)
            if field == 'ProximityLevel':
                accepted_levels.append(receipt)
        if advance is not None:
            if show_missing:
                # Private replay facts describe the inventory before this
                # creation, rather than the complete final creation graph.
                binding['_show_missing'] = (primary, show_missing)
            state, binding = advance(index, binding, state, groups, levels)
        rewritten.append(binding)
    return tuple(rewritten), tuple(receipts), tuple(accepted_groups), tuple(accepted_levels)
