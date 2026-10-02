"""Explicit SceneManager Add-button handlers, without a WinForms host.

Only an owning editor can issue the immutable observed-control context. Button
operations contain no choices, continuation, modal result or binding facts.
The exact synchronous source callbacks are executed; framework notifications,
automatic selection/rebinding and modal dialog execution are not inferred.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json

from .edlt import EdltError


BUTTONS = ('add-trigger-group', 'add-action-selector', 'new-lighting-group')
_FIELDS = ('trigger_items', 'action_items', 'application_items')


def _integer(value, low, high, description):
    if type(value) is not int or not low <= value <= high:
        raise EdltError(description)
    return value


def _string(value, description, *, nonempty=False):
    if type(value) is not str or nonempty and not value or len(value) > 65536:
        raise EdltError(description)
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise EdltError(description) from error
    return value


def _json(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False)
        if len(encoded.encode('utf-8')) > 4 * 1024 * 1024:
            raise ValueError('bounded context exceeded')
        return encoded
    except (TypeError, ValueError) as error:
        raise EdltError('Scene button owner facts must be bounded JSON-compatible records') from error


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _pin(value):
    if (type(value) is not str or len(value) != 64
            or any(c not in '0123456789abcdef' for c in value)):
        raise EdltError('Scene button context requires exact source/history SHA256 fingerprints')
    return value


def _items(rows):
    if (not isinstance(rows, Sequence) or isinstance(rows, (str, bytes))
            or len(rows) > 65536):
        raise EdltError('Scene button Items require a complete ordered owner list')
    result, identities = [], set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {'identity', 'value', 'name'}:
            raise EdltError('Scene button Items require exact identity/value/name records')
        identity = _string(row['identity'], 'Scene button item identity must be explicit valid Unicode', nonempty=True)
        if '\0' in identity or identity in identities:
            raise EdltError('Scene button Items require unique non-NUL object identities')
        identities.add(identity)
        result.append({'identity': identity,
                       'value': _string(row['value'], 'Scene button DataStore.Value must be an exact string'),
                       'name': _string(row['name'], 'Scene button DataStore.Name must be valid Unicode')})
    return result


def normalize_operation(operation):
    """Reject caller-supplied control facts before metadata or connection I/O."""
    if (not isinstance(operation, Mapping) or not {'op', 'scene', 'button'} <= set(operation)
            or set(operation) - {'op', 'scene', 'button', 'dialog', 'selected_scenes'}
            or operation.get('op') != 'scene-button-control'
            or operation.get('button') not in BUTTONS):
        raise EdltError('Invalid scene-button-control operation')
    result = {'op': 'scene-button-control',
            'scene': _integer(operation['scene'], 1, 8, 'Scene button requires scene 1..8'),
            'button': operation['button']}
    if 'dialog' in operation:
        dialog = operation['dialog']
        if (not isinstance(dialog, Mapping) or 'cancel' not in dialog
                or type(dialog['cancel']) is not bool
                or set(dialog) - {'cancel', 'name'}
                or dialog['cancel'] and set(dialog) != {'cancel'}):
            raise EdltError('Scene button dialog requires cancel Boolean and accepted-only optional name')
        from .edlt_scene_add_dialog import normalize
        checked = normalize({'op': 'add-action-dialog' if result['button'] == 'add-action-selector'
                             else 'add-trigger-dialog', 'scene': result['scene'], **dialog})
        result['dialog'] = {key: checked[key] for key in ('cancel', 'name') if key in checked}
    if 'selected_scenes' in operation:
        selected = operation['selected_scenes']
        if not isinstance(selected, (list, tuple)) or len(selected) > 8:
            raise EdltError('Scene button selected_scenes requires distinct Scene identities 1..8')
        selected = [_integer(value, 1, 8, 'Selected Scene must be 1..8') for value in selected]
        if len(selected) != len(set(selected)):
            raise EdltError('Scene button selected_scenes requires distinct Scene identities 1..8')
        result['selected_scenes'] = selected
    elif result['button'] == 'new-lighting-group':
        raise EdltError('Lighting Add requires explicit selected_scenes; Current does not establish selected rows')
    return result


class _Seal:
    def __init__(self, owner):
        self.owner, self.fingerprint = owner, None


@dataclass(frozen=True)
class SceneButtonContext:
    """Owner-issued facts; as_dict is review output, never an import capability."""

    source_fingerprint: str
    history_fingerprint: str
    _facts_json: str
    _seal: _Seal

    @property
    def fingerprint(self):
        return _digest(_json({'source': self.source_fingerprint,
                              'history': self.history_fingerprint,
                              'facts': json.loads(self._facts_json)}))

    def as_dict(self):
        check_button_context(self)
        return {'source_sha256': self.source_fingerprint,
                'history_sha256': self.history_fingerprint,
                'sha256': self.fingerprint, 'facts': json.loads(self._facts_json)}


def issue_button_context(*, owner, source_fingerprint, history_fingerprint, scene,
                         selected_scene_count=1, current_scene=None,
                         primary_application=None, secondary_application=None,
                         application_selector=0, raw_trigger_group=255,
                         parent_form_present=True, unit_form_present=True,
                         selected_trigger_group=None, candidate_rows_are_groups=True,
                         trigger_items=(), action_items=(), application_items=(),
                         trigger_currency_present=True, trigger_binding_present=True,
                         application_currency_present=True, application_binding_present=True):
    """Issue from observed editor facts, not public operation JSON.

    selected_trigger_group is the actual selected CBusGroup's identity and exact
    Address string. Application addresses here are independently resolved byte
    addresses; application Items keep their separate source selector Values0/1.
    No native inventory, original host observation or same-process security
    capability is implied by the Python factory alone.
    """
    if owner is None:
        raise EdltError('Scene button context requires an owning editor')
    facts = {'scene': _integer(scene, 1, 8, 'Scene button requires scene 1..8'),
             'selected_scene_count': _integer(selected_scene_count, 0, 65536, 'Invalid selected Scene row count'),
             'current_scene': None if current_scene is None else _integer(current_scene, 1, 8, 'Invalid current Scene owner'),
             'application_selector': _integer(application_selector, 0, 255, 'Scene application selector must be a byte'),
             'raw_trigger_group': _integer(raw_trigger_group, 0, 255, 'Raw TriggerGroup must be a byte')}
    for name, address in (('primary_application', primary_application), ('secondary_application', secondary_application)):
        facts[name] = None if address is None else _integer(address, 0, 255, 'Resolved application address must be a byte')
    for name, value in (('parent_form_present', parent_form_present), ('unit_form_present', unit_form_present),
                        ('candidate_rows_are_groups', candidate_rows_are_groups),
                        ('trigger_currency_present', trigger_currency_present), ('trigger_binding_present', trigger_binding_present),
                        ('application_currency_present', application_currency_present), ('application_binding_present', application_binding_present)):
        if type(value) is not bool:
            raise EdltError('Scene button binding/type presence facts must be explicit Booleans')
        facts[name] = value
    if selected_trigger_group is not None:
        if not isinstance(selected_trigger_group, Mapping) or set(selected_trigger_group) != {'identity', 'address'}:
            raise EdltError('Selected trigger must identify the actual CBusGroup object')
        identity = _string(selected_trigger_group['identity'], 'Selected trigger identity must be explicit', nonempty=True)
        address = _string(selected_trigger_group['address'], 'Selected trigger Address must be an exact string', nonempty=True)
        if '\0' in identity or '\0' in address:
            raise EdltError('Selected trigger identity/Address cannot contain NUL')
        selected_trigger_group = {'identity': identity, 'address': address}
    facts['selected_trigger_group'] = selected_trigger_group
    for field, rows in zip(_FIELDS, (trigger_items, action_items, application_items)):
        facts[field] = _items(rows)
    value = SceneButtonContext(_pin(source_fingerprint), _pin(history_fingerprint), _json(facts), _Seal(owner))
    value._seal.fingerprint = value.fingerprint
    return value


def check_button_context(value, *, owner=None, source_fingerprint=None, history_fingerprint=None):
    try:
        valid = (type(value) is SceneButtonContext and type(value._seal) is _Seal
            and (owner is None or value._seal.owner is owner)
            and value._seal.fingerprint == value.fingerprint
            and (source_fingerprint is None or value.source_fingerprint == source_fingerprint)
            and (history_fingerprint is None or value.history_fingerprint == history_fingerprint))
    except (TypeError, ValueError, UnicodeError):
        valid = False
    if not valid:
        raise EdltError('Scene button context is foreign, modified or belongs to a different source/history')
    return value


@dataclass(frozen=True)
class SceneButtonControlResult:
    _receipt_json: str

    def as_dict(self):
        return json.loads(self._receipt_json)


def run_scene_button_control(operation, *, context, owner, source_fingerprint,
                             history_fingerprint, request_add_group, request_add_level,
                             ui_callback, observe_items=None):
    """Execute one explicit source handler; callback exceptions stop immediately.

    ui_callback(action, facts) handles only source synchronous UI assignments,
    currency Position, explicit WriteValue and resets. A SelectedItem assignment
    does not imply WriteValue or any subsequently scheduled handler. The optional
    observe_items(field) returns the actual bound list at the source foreach;
    it must preserve old Levels collection ownership across network refresh.
    No exception is retried, rolled back, or converted to a completed receipt.
    """
    operation = normalize_operation(operation)
    if owner is None:
        raise EdltError('Scene button execution requires its issued owner')
    check_button_context(context, owner=owner, source_fingerprint=_pin(source_fingerprint),
                         history_fingerprint=_pin(history_fingerprint))
    facts = json.loads(context._facts_json)
    if facts['scene'] != operation['scene']:
        raise EdltError('Scene button context belongs to a different operation Scene')
    if (operation['button'] == 'new-lighting-group'
            and len(operation['selected_scenes']) != facts['selected_scene_count']):
        raise EdltError('Lighting Add selected rows disagree with the owner-issued context')
    if (not all(callable(v) for v in (request_add_group, request_add_level, ui_callback))
            or observe_items is not None and not callable(observe_items)):
        raise EdltError('Scene button requires callable owner requests/UI bindings')
    kind, journal, request, selected = operation['button'], [], None, None

    def ui(action, **values):
        row = {'action': action, **values}
        journal.append(row)
        # A callback must not mutate the immutable journal evidence.
        ui_callback(action, json.loads(_json(values)))

    def add(action, callback, *args):
        nonlocal request
        request = {'action': action, 'arguments': list(args)}
        returned = callback(*args)
        if returned is not None:
            returned = _string(returned, 'Add callback result must be null or an exact Unicode string')
        request['returned_value'] = returned
        journal.append(dict(request))
        return returned

    def scan(field, returned):
        rows = _items(observe_items(field)) if observe_items is not None else facts[field]
        journal.append({'action': 'ObserveItems', 'field': field, 'items': rows})
        return next(((index, row) for index, row in enumerate(rows) if row['value'] == returned), None)

    early = kind == 'new-lighting-group' and facts['selected_scene_count'] != 1
    if not early:
        returned = ''  # Distinct from a canceled/null callback result in source.
        if kind == 'new-lighting-group':
            if not facts['candidate_rows_are_groups']:
                raise EdltError('Lighting Add requires observed CBusGroup candidate rows; host cast failure is unestablished')
            if facts['current_scene'] is None:
                raise EdltError('Lighting Add requires an observed current EDLTScene')
            address = facts['secondary_application'] if facts['application_selector'] != 0 else facts['primary_application']
            if facts['unit_form_present'] and (address is None or address == 255):
                raise EdltError('Lighting Add requires the exact resolved primary/secondary Application')
            if facts['unit_form_present']:
                returned = add('AddGroupRequest', request_add_group, str(address))
            field, control = 'application_items', 'application'
        elif facts['parent_form_present']:
            if facts['unit_form_present']:
                if kind == 'add-trigger-group':
                    returned = add('AddGroupRequest', request_add_group, '202')
                elif facts['selected_trigger_group'] is not None:
                    returned = add('AddLevelRequest', request_add_level, '202', facts['selected_trigger_group']['address'])
            field, control = ('trigger_items', 'trigger') if kind == 'add-trigger-group' else ('action_items', 'action')
        else:
            field = control = None
        if returned is not None and field is not None:
            match = scan(field, returned)
            if match is not None:
                index, choice = match
                selected = {'control': control, 'index': index, 'item': choice}
                if kind == 'add-action-selector':
                    ui('SetSelectedItem', control=control, item=choice)
                else:
                    ui('SetSelectedIndex', control=control, index=index, item=choice)
                    if kind == 'new-lighting-group' and not facts['application_currency_present']:
                        raise EdltError('Lighting Add matched an application without a CurrencyManager; original host null failure is unestablished')
                    if facts[control + '_currency_present']:
                        ui('SetCurrencyPosition', control=control, position=index)
                    if facts[control + '_binding_present']:
                        ui('WriteValue', control=control, property='SelectedValue', item=choice,
                           binding_scene=facts['current_scene'])
        ui('ResetCurrentItem', source='scenes')
        ui('ResetBindings', source='scenes', metadata_changed=False)
        ui('ResetBindings', source='available_groups', metadata_changed=False)
    receipt = {'format': 'cbus-edlt-scene-button-control-v1', 'operation': operation,
               'context_sha256': context.fingerprint, 'source_sha256': context.source_fingerprint,
               'history_sha256': context.history_fingerprint, 'request': request,
               'selected_item': selected, 'early_return': early, 'callbacks': journal,
               'scene_items_changed_by_handler': False,
               'implicit_callbacks_inferred': False, 'original_instructions_executed': 0,
               'framework_instructions_executed': 0, 'modal_dialog_executed': False,
               'automatic_currency_selection_verified': False,
               'callback_profile': 'explicit-synchronous-source-handlers'}
    return SceneButtonControlResult(_json(receipt))
