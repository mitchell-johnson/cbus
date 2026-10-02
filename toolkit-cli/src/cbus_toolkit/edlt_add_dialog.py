"""Blank-address eDLT ``ComboBoxAddEdit`` Add dialogs for parent transactions.

The original parent form hosts twelve group combos and two application combos
built from ``ComboBoxAddEdit``.  Its Add button sends a *blank* address through
``CBusNetwork.AddGroupRequest``/``AddApplicationRequest``.  Toolkit's
``TfrmKEYGL5.AddSharpGroup`` then opens ``TCBusApplicationGUIAgent.AddGroup``
(``TddGroup``/``TfrmGroupAssign``) instead of the exact-address creation path
used by retained model getters.  When the operator accepts, the new group is
saved immediately, its decimal address is returned to eDLT, and the combo
selects that item and writes its ``SelectedValue`` binding.

This module models only the deterministic, database-only part of that flow as
an ``add-dialog`` parent operation.  It resolves the operation into one group
creation receipt and a binding of the created address into the owning parent
panel.  The native manager in :mod:`edlt_parent_metadata` performs creation,
PP staging and persistence.  Expected values are pinned independently in
``research/fixtures/edlt-add-dialog-evidence.json``.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .edlt import EdltError
from .edlt_activation import WAKE_MODES

# Target PP field -> (panel operation, panel option, list application rule).
# The list application is the combo's ``DataSource.ListBaseObject`` from
# ``EDLTUnit`` (lines 1362..1385): Primary for colours/Quick Status,
# 203 for Page Control, and Proximity follows ProximityMode (3 -> 202).
TARGETS = MappingProxyType({
    'ProximityGroup': ('activation', 'group', 'proximity'),
    'BacklightActiveBrightnessControlGroup': ('colours', 'active_screen_group', 'primary'),
    'BacklightIdleBrightnessControlGroup': ('colours', 'idle_screen_group', 'primary'),
    'IndicatorActiveBrightnessControlGroup': ('colours', 'active_indicator_group', 'primary'),
    'IndicatorIdleBrightnessControlGroup': ('colours', 'idle_indicator_group', 'primary'),
    'IndicatorOnColourControlGroup': ('colours', 'indicator_on_group', 'primary'),
    'IndicatorOffColourControlGroup': ('colours', 'indicator_off_group', 'primary'),
    'QuickStatusGroup': ('quick-status', 'group', 'primary'),
    'KeySetsEnableGroup': ('page-control', 'group', 203),
})
# Source-evidenced combos that this operation deliberately refuses.
REFUSED_TARGETS = MappingProxyType({
    'PrimaryApplication': 'use add-application-dialog with explicit creation_preferences',
    'SecondaryApplication': 'use add-application-dialog with explicit creation_preferences',
    'CorridorLinkingLinkGroup': (
        'Corridor consumes the complete ordered group list, and DBGETXML does '
        'not establish where a new group appears in that list'),
    'CorridorLinkingOfficeGroup': (
        'Corridor consumes the complete ordered group list, and DBGETXML does '
        'not establish where a new group appears in that list'),
    'CorridorLinkingCorridorGroup': (
        'Corridor consumes the complete ordered group list, and DBGETXML does '
        'not establish where a new group appears in that list'),
})
OPTION_NAMES = ('field', 'address', 'name')
MAXIMUM_ADDRESS = 254  # TfrmGroupAssign.SetValues defaults max 0 -> 0xfe.

# TCBUSApplication.GetDefaultGroupName seeds the new object's TagName.
_DEFAULT_GROUP_NAMES = MappingProxyType({
    172: 'Communication Group', 202: 'Trigger Group',
    203: 'Enable Network Variable'})
# TStandardCBusApplications.GetGroupName names the dialog noun used by the
# address-change rewrite and by messages 2201..2204 and 2271.
_STANDARD_GROUP_NAMES = MappingProxyType({
    172: 'Communication Group', 192: 'Media Link Group', 202: 'Trigger Group',
    203: 'Enable Network Variable'})
MESSAGES = MappingProxyType({
    2201: "%1 with the address '%2' already exists.",
    2202: '%1 name cannot be blank.',
    2203: "%1 with the name '%2' already exists.",
    2204: '%1 Name can not be the same as the Project Name.',
    2271: 'Cannot create a new %1.  All available addresses are in use.',
})


def default_group_name(application):
    return _DEFAULT_GROUP_NAMES.get(application, 'Group')


def standard_group_name(application):
    return _STANDARD_GROUP_NAMES.get(application, 'Group')


def _upper(text):
    """Delphi ``SysUtils.UpperCase``: ASCII letters only."""
    return ''.join(chr(ord(c) - 32) if 'a' <= c <= 'z' else c for c in text)


def _trim(text):
    """Delphi ``SysUtils.Trim``: strip characters at or below space."""
    start, end = 0, len(text)
    while start < end and text[start] <= ' ':
        start += 1
    while end > start and text[end - 1] <= ' ':
        end -= 1
    return text[start:end]


def _message(code, noun, detail=None):
    text = MESSAGES[code].replace('%1', noun)
    if detail is not None:
        text = text.replace('%2', detail)
    return f'Add dialog error {code}: {text}'


def _rewrite(name, prefix, address):
    """``cmbGroupAddressChange``: a default-looking name follows the address."""
    if name == '' or _upper(name[:len(prefix)]) == _upper(prefix):
        return prefix + ' ' + str(address)
    return name


class AddDialogError(EdltError):
    """An operator input the original dialog would refuse or cannot offer."""


@dataclass(frozen=True)
class AddDialogGroup:
    """One accepted blank-address group dialog."""

    field: str
    application: int
    address: int
    name: str
    first_free_address: int
    seeded_name: str
    shown_name: str
    operator_address: bool
    operator_name: bool

    def as_dict(self):
        return {
            'field': self.field, 'application': self.application,
            'address': self.address, 'name': self.name,
            'kind': 'NetVar' if self.application == 203 else 'Group',
            'first_free_address': self.first_free_address,
            'seeded_name': self.seeded_name, 'shown_name': self.shown_name,
            'operator_address': self.operator_address,
            'operator_name': self.operator_name,
        }


def accept_group_dialog(field, application, groups, project, *,
                        address=None, name=None):
    """Return the group accepted by the original blank-address dialog.

    ``groups`` maps existing addresses to TagNames for ``application`` at the
    moment Add is pressed.  ``address``/``name`` are operator dialog edits.
    """
    noun = standard_group_name(application)
    if len(groups) >= 256:
        raise AddDialogError(_message(2271, noun))
    free = [value for value in range(MAXIMUM_ADDRESS + 1) if value not in groups]
    if not free:
        raise AddDialogError(_message(2271, noun))
    first = free[0]
    seed = default_group_name(application) + ' ' + str(first)
    shown = _rewrite(seed, noun, first)
    selected = first
    if address is not None:
        if type(address) is not int or address not in free:
            raise AddDialogError(
                'Add dialog address must be one of the listed free addresses '
                f'0..{MAXIMUM_ADDRESS} for application {application}')
        selected = address
    text = shown if selected == first else _rewrite(shown, noun, selected)
    if name is not None:
        if type(name) is not str:
            raise AddDialogError('Add dialog name must be text')
        text = name
    accepted = _trim(text)
    if not accepted:
        raise AddDialogError(_message(2202, noun))
    if accepted == project:
        raise AddDialogError(_message(2204, noun))
    if selected in groups:  # Unreachable through the free list; kept for parity.
        raise AddDialogError(_message(2201, noun, str(selected)))
    if any(_upper(tag) == _upper(accepted) for tag in groups.values()):
        raise AddDialogError(_message(2203, noun, text))
    return AddDialogGroup(field, application, selected, accepted, first, seed,
                          shown, address is not None, name is not None)


def normalize(value):
    """Validate one ``add-dialog`` operation shape."""
    unexpected = set(value) - {'op', *OPTION_NAMES}
    if unexpected:
        raise EdltError('add-dialog operation contains unsupported fields: '
                        + ', '.join(sorted(unexpected)))
    field = value.get('field')
    if field in REFUSED_TARGETS:
        raise EdltError(f'add-dialog {field} is not supported: '
                        + REFUSED_TARGETS[field])
    if field not in TARGETS:
        raise EdltError('add-dialog field must be one of: '
                        + ', '.join(TARGETS))
    address = value.get('address')
    if address is not None and (type(address) is not int
                                or not 0 <= address <= MAXIMUM_ADDRESS):
        raise EdltError(f'add-dialog address must be 0..{MAXIMUM_ADDRESS}')
    if value.get('name') is not None and type(value['name']) is not str:
        raise EdltError('add-dialog name must be text')
    return {'op': 'add-dialog',
            **{key: value[key] for key in OPTION_NAMES if key in value}}


def _list_application(rule, values, mode):
    if rule == 'proximity' and mode == 3:
        return 202
    if rule in ('primary', 'proximity'):
        primary = values['PrimaryApplication'][0]
        if primary == 255:
            raise AddDialogError(
                'add-dialog requires a configured primary application because '
                'the combo has no list application')
        return primary
    return rule


def resolve(operations, values, project, existing_groups, preceding_groups):
    """Resolve ``add-dialog`` rows into group dialogs and panel bindings.

    ``existing_groups`` maps application -> {address: TagName} before the
    first operation.  ``preceding_groups(index)`` returns (application,
    address, TagName) objects that earlier non-dialog operations or the parent
    load would already have created by operation ``index``.  The resulting
    operation list replaces each add with its panel binding: the explicit
    panel operation must follow every add it receives, otherwise one panel
    operation is synthesized at the last add's position.
    """
    adds = [index for index, row in enumerate(operations)
            if row['op'] == 'add-dialog']
    if not adds:
        return tuple(operations), ()
    panels = {}
    for index in adds:
        panel = TARGETS[operations[index]['field']][0]
        panels.setdefault(panel, []).append(index)
    explicit = {}
    for index, row in enumerate(operations):
        if row['op'] in panels:
            explicit[row['op']] = index
    groups = {app: dict(rows) for app, rows in existing_groups.items()}
    mode = values['ProximityMode'][0]
    results, bindings, fields = [], {}, set()
    for index in adds:
        row = operations[index]
        field = row['field']
        panel, option, rule = TARGETS[field]
        if field in fields:
            raise EdltError(f'add-dialog {field} may appear only once')
        fields.add(field)
        target = explicit.get(panel)
        if target is not None:
            if target < index:
                raise EdltError(
                    f'add-dialog {field} must precede the {panel} operation '
                    'that receives its binding')
            if operations[target].get(option) is not None:
                raise EdltError(
                    f'{panel} operation {target + 1} also sets {option}; the '
                    f'add-dialog {field} binding would be overwritten')
        application = _list_application(rule, values, mode)
        if rule == 'proximity' and target is not None:
            wake = operations[target].get('wake_mode')
            later = WAKE_MODES.get(wake, mode)
            if _list_application(rule, values, later) != application:
                raise EdltError(
                    'add-dialog ProximityGroup list application would change '
                    'with the receiving activation wake_mode')
        current = groups.setdefault(application, {})
        for app, address, tag in preceding_groups(index):
            groups.setdefault(app, {}).setdefault(address, tag)
        accepted = accept_group_dialog(
            field, application, current, project,
            address=row.get('address'), name=row.get('name'))
        current[accepted.address] = accepted.name
        results.append(accepted)
        bindings.setdefault(panel, {})[option] = accepted.address
    rewritten = []
    for index, row in enumerate(operations):
        if row['op'] == 'add-dialog':
            panel = TARGETS[row['field']][0]
            if panel not in explicit and index == panels[panel][-1]:
                rewritten.append({'op': panel, **bindings[panel]})
            continue
        if row['op'] in bindings:
            row = {**row, **bindings[row['op']]}
        rewritten.append(row)
    return tuple(rewritten), tuple(results)
