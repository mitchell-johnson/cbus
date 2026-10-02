"""Explicit retained SceneManager selector callbacks without a WinForms host.

The SceneManager owns the scene properties and complete ordered choice objects.
This coordinator owns only the synchronous callback/binding history. It never
creates metadata, guesses currency selection, or resolves a null SelectedValue.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json

from .edlt import EdltError


_CHOICES = ('application_choices', 'trigger_choices', 'action_choices', 'dynamic_labels')
_SELECTION = frozenset(('value', 'choice_index', 'choice_identity'))


def _integer(value, low, high, description):
    if type(value) is not int or not low <= value <= high:
        raise EdltError(description)
    return value


def _identity(value):
    if type(value) is not str or not value or len(value) > 2048 or '\0' in value:
        raise EdltError('Selector choices require an explicit nonempty object identity')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise EdltError('Selector identity must be valid Unicode') from error
    return value


def _selection(row):
    return {'value': _integer(row['value'], -1, 255, 'Selector value must be -1..255'),
            'choice_index': _integer(row['choice_index'], 0, 65535, 'Selector choice index must be 0..65535'),
            'choice_identity': _identity(row['choice_identity'])}


def normalize_events(events):
    """Validate public callback shape before any model read or connection."""
    if not isinstance(events, (list, tuple)) or len(events) > 512:
        raise EdltError('Selector events require an ordered array of at most 512 callbacks')
    result = []
    for row in events:
        if not isinstance(row, Mapping):
            raise EdltError('Selector callbacks require explicit records')
        kind = row.get('event')
        if kind == 'scene-current-changed' and set(row) == {'event', 'current'}:
            if type(row['current']) is not bool:
                raise EdltError('Scene current must explicitly identify a scene or no current')
            item = {'event': kind, 'current': row['current']}
        elif kind == 'trigger-current-changed' and set(row) == {'event'}:
            item = {'event': kind}
        elif kind == 'level-current-changed' and set(row) in (
                {'event'}, {'event', *_SELECTION}):
            item = {'event': kind}
            if 'value' in row:
                item.update(_selection(row))
        elif kind in ('application-selected', 'trigger-selected', 'action-selected') and set(row) == {'event', *_SELECTION}:
            item = {'event': kind, **_selection(row)}
        elif kind == 'label-selected' and set(row) in (
                {'event', 'index'}, {'event', 'index', 'choice_identity'}):
            index = _integer(row['index'], -1, 3, 'Dynamic label SelectedIndex must be -1..3')
            if (index >= 0) != ('choice_identity' in row):
                raise EdltError('A selected dynamic label requires its exact identity; -1 has no selected object')
            item = {'event': kind, 'index': index}
            if index >= 0:
                item['choice_identity'] = _identity(row['choice_identity'])
        else:
            raise EdltError('Unsupported SceneManager selector callback')
        result.append(item)
    return result


def normalize_operation(operation):
    if (not isinstance(operation, Mapping) or set(operation) != {'op', 'scene', 'events'}
            or operation.get('op') != 'scene-selector-control'):
        raise EdltError('Invalid scene-selector-control operation')
    return {'op': 'scene-selector-control',
            'scene': _integer(operation['scene'], 1, 8, 'Selector control requires scene 1..8'),
            'events': normalize_events(operation['events'])}


def _view(value, scene):
    """Detach bounded owner facts; these are never operation JSON inputs."""
    if not isinstance(value, Mapping):
        raise EdltError('Selector property callback must return an owner view')
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        encoded_bytes = encoded.encode('utf-8')
        detached = json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise EdltError('Selector owner view must be JSON-compatible') from error
    if len(encoded_bytes) > 4 * 1024 * 1024:
        raise EdltError('Selector owner view exceeds its bounded profile')
    if detached.get('scene') != scene or type(detached.get('scene')) is not int:
        raise EdltError('Selector owner view must bind the exact retained scene')
    _integer(detached.get('trigger_group'), 0, 255, 'Selector owner view requires the exact TriggerGroup')
    for field in _CHOICES:
        rows = detached.get(field)
        if not isinstance(rows, list) or len(rows) > 65536:
            raise EdltError(f'Selector owner requires complete ordered {field}')
        identities = set()
        for row in rows:
            if not isinstance(row, dict) or not {'identity', 'value', 'name'} <= set(row):
                raise EdltError('Selector owner choices require identity/value/name facts')
            identity = _identity(row['identity'])
            if identity in identities:
                raise EdltError('Selector owner choices have ambiguous object identities')
            identities.add(identity)
            _integer(row['value'], -1, 255, 'Selector owner choice value must be -1..255')
            if type(row['name']) is not str:
                raise EdltError('Selector owner choice Name must be a string')
        if field == 'dynamic_labels' and (len(rows) > 4 or any(row['value'] != i for i,row in enumerate(rows))):
            raise EdltError('Dynamic labels must preserve complete SelectedIndex order 0..3')
    return detached


@dataclass(frozen=True)
class SceneSelectorControlState:
    """Internal continuation for one global form binding, not eight controls."""

    current_scene: int | None = None
    bound_scene: int | None = None
    controls_enabled: bool = False
    action_source_trigger: int | None = None
    _view_json: str = '{}'

    def as_dict(self):
        return {'current_scene': self.current_scene, 'bound_scene': self.bound_scene,
                'controls_enabled': self.controls_enabled,
                'action_source_trigger': self.action_source_trigger,
                'action_binding_present': self.bound_scene is not None,
                'dynamic_label_binding_present': self.bound_scene is not None,
                'scene_name_binding_present': self.bound_scene is not None,
                'view': json.loads(self._view_json)}


@dataclass(frozen=True)
class SceneSelectorControlResult:
    state: SceneSelectorControlState
    _receipt_json: str

    def as_dict(self):
        return json.loads(self._receipt_json)


def update_selector_properties(state, scene, *, trigger_group=None, application_selector=None):
    """Owner callback projection after a button's explicit SelectedValue write.

    This updates observed scalar properties only. Bound choice collections,
    DynamicAll references, direct targets and pending Name controls do not
    acquire an implicit current-changed or ReadValue callback.
    """
    if type(state) is not SceneSelectorControlState or state.current_scene != scene or state.bound_scene != scene:
        raise EdltError('Button property projection requires the actual current selector binding')
    view = _view(json.loads(state._view_json), scene)
    if trigger_group is not None:
        view['trigger_group'] = _integer(trigger_group, 0, 255, 'TriggerGroup must be a byte')
    if application_selector is not None:
        view['application_selector'] = _integer(application_selector, 0, 1, 'Application selector must be0/1')
    return SceneSelectorControlState(state.current_scene, state.bound_scene,
        state.controls_enabled, state.action_source_trigger,
        json.dumps(view, ensure_ascii=False, allow_nan=False))


def run_scene_selector_control(
        events, *, scene: int, bind_scene: Callable[[int], Mapping],
        trigger_current: Callable[[int], Mapping],
        write_application: Callable[[int, int], Mapping],
        write_trigger: Callable[[int, int], Mapping],
        write_action: Callable[[int, int], Mapping],
        write_label_index: Callable[[int, int], Mapping],
        observe_choices: Callable[[str, int, int | None], Sequence[Mapping]] | None = None,
        initial_state: SceneSelectorControlState | None = None):
    """Run explicit source handlers; returned views do not imply ReadValue.

    Owner bind_scene implements AvailableActionSelectors resolution. Owner
    trigger_current implements ActionSelector getter and RefreshDynamicLables,
    after the coordinator has called bind_scene and rebound the action control.
    Setter callbacks implement only the
    corresponding source property setter and return a detached observation.
    """
    rows = normalize_events(events)
    _integer(scene, 1, 8, 'Selector control requires scene 1..8')
    callbacks = (bind_scene, trigger_current, write_application, write_trigger, write_action, write_label_index)
    if not all(callable(callback) for callback in callbacks):
        raise EdltError('Selector coordinator requires callable model property bindings')
    if observe_choices is not None and not callable(observe_choices):
        raise EdltError('Selector bound-list observer must be callable')
    if initial_state is not None and type(initial_state) is not SceneSelectorControlState:
        raise EdltError('Selector continuation requires internal typed state only')
    state = initial_state or SceneSelectorControlState()
    for target in (state.current_scene, state.bound_scene):
        if target is not None:
            _integer(target, 1, 8, 'Invalid internal selector binding target')
    if (type(state.controls_enabled) is not bool
            or state.controls_enabled != (state.current_scene is not None)
            or (state.current_scene is not None and state.current_scene != state.bound_scene)):
        raise EdltError('Invalid internal selector current/bound state')
    try:
        view = json.loads(state._view_json)
    except (TypeError, ValueError) as error:
        raise EdltError('Invalid internal selector owner view') from error
    if state.bound_scene is not None:
        view = _view(view, state.bound_scene)
        _integer(state.action_source_trigger, 0, 255, 'Invalid internal action data-source identity')
    elif view != {}:
        raise EdltError('Unbound selector state cannot carry owner facts')
    elif state.action_source_trigger is not None:
        raise EdltError('Unbound selector state cannot carry a data-source identity')
    initial = state.as_dict()
    current, bound, enabled = state.current_scene, state.bound_scene, state.controls_enabled
    source_trigger = state.action_source_trigger
    journal, projected = [], []

    def record(index, event, action, **facts):
        journal.append({'event_index': index, 'event': event, 'action': action, **facts})

    def invoke(index, kind, action, callback, target, *values):
        returned = _view(callback(target, *values), target)
        record(index, kind, action, binding_scene=target, values=list(values), result=returned)
        return returned

    def match(row, field):
        if observe_choices is not None:
            # Observe the actual bound collection, not Binding.ReadValue or an
            # automatic currency/PropertyChanged handler. The owner must retain
            # the old action collection identity until explicit rebinding.
            candidate = dict(view)
            candidate[field] = observe_choices(field, bound, source_trigger)
            view[field] = _view(candidate, bound)[field]
        choices = view[field]
        index = row['choice_index']
        if index >= len(choices):
            raise EdltError('Selected choice is outside the current ordered owner list')
        choice = choices[index]
        if choice['identity'] != row['choice_identity'] or choice['value'] != row['value']:
            raise EdltError('Selected choice must match current ordinal, identity and value')

    def merge(returned, *, labels=False, actions=False):
        nonlocal view
        previous = view
        view = returned
        # BindingSource data sources are changed by the explicit handlers, not
        # by inferred PropertyChanged callbacks following a scalar setter.
        for key in _CHOICES:
            keep_live = ((key == 'dynamic_labels' and labels)
                         or (key == 'action_choices' and actions
                             and returned['trigger_group'] == source_trigger))
            if not keep_live:
                view[key] = previous[key]

    for index, row in enumerate(rows):
        kind, start = row['event'], len(journal)
        if kind == 'scene-current-changed':
            enabled = row['current']
            current = scene if enabled else None
            record(index, kind, 'SetControlEnabled', enabled=enabled)
            if enabled:
                record(index, kind, 'ClearActionBindings')
                view = invoke(index, kind, 'ResolveAvailableActionSelectors', bind_scene, scene)
                bound = scene
                source_trigger = view['trigger_group']
                record(index, kind, 'SetActionDataSource', choices=view['action_choices'])
                record(index, kind, 'BindActionSelectedValue', binding_scene=scene, property='ActionSelector', formatting=True, update_mode=1)
                record(index, kind, 'ClearDynamicLabelBindings')
                record(index, kind, 'SetDynamicLabelDataSource', choices=view['dynamic_labels'])
                record(index, kind, 'BindLabelSelectedIndex', binding_scene=scene, property='LabelValueIndex', formatting=True, update_mode=1)
                record(index, kind, 'ClearSceneNameBindings')
                record(index, kind, 'BindSceneNameText', binding_scene=scene, property='SceneName', formatting=True, update_mode=2)
        elif kind == 'trigger-current-changed':
            if current is not None:
                record(index, kind, 'ClearActionBindings')
                view = invoke(index, kind, 'ResolveAvailableActionSelectors', bind_scene, current)
                source_trigger = view['trigger_group']
                record(index, kind, 'SetActionDataSource', choices=view['action_choices'])
                record(index, kind, 'BindActionSelectedValue', binding_scene=current, property='ActionSelector', formatting=True, update_mode=1)
                view = invoke(index, kind, 'ActionSelectorGetterThenRefreshDynamicLables', trigger_current, current)
                record(index, kind, 'RefreshDynamicLables', binding_scene=current, choices=view['dynamic_labels'])
        elif kind in ('level-current-changed', 'action-selected'):
            if bound is not None:
                if not _SELECTION <= set(row):
                    raise EdltError('A bound action WriteValue requires an explicit non-null selected object')
                match(row, 'action_choices')
                merge(invoke(index, kind, 'WriteValue', write_action, bound, row['value']), labels=True, actions=True)
            elif kind == 'action-selected':
                raise EdltError('Action selection requires an established direct scene binding')
        elif kind in ('application-selected', 'trigger-selected'):
            if current is None:
                raise EdltError('Null-current application/trigger Binding parsing is not source-qualified')
            application = kind == 'application-selected'
            match(row, 'application_choices' if application else 'trigger_choices')
            callback = write_application if application else write_trigger
            merge(invoke(index, kind, 'WriteValue', callback, current, row['value']))
        elif kind == 'label-selected':
            if bound is None:
                raise EdltError('Dynamic-label selection requires an established direct scene binding')
            selected = row['index']
            if selected >= 0:
                if observe_choices is not None:
                    candidate = dict(view)
                    candidate['dynamic_labels'] = observe_choices('dynamic_labels', bound, source_trigger)
                    view['dynamic_labels'] = _view(candidate, bound)['dynamic_labels']
                labels = view['dynamic_labels']
                if selected >= len(labels) or labels[selected]['identity'] != row['choice_identity']:
                    raise EdltError('Dynamic-label selection must match the current ordered identity')
            merge(invoke(index, kind, 'WriteValue', write_label_index, bound, selected))
        projected.append({**row, 'current_scene':current, 'bound_scene':bound,
                          'controls_enabled':enabled,
                          'binding_actions':[entry['action'] for entry in journal[start:]]})
    final = SceneSelectorControlState(current, bound, enabled, source_trigger,
                                     json.dumps(view, ensure_ascii=False, allow_nan=False))
    receipt = {'format':'cbus-edlt-scene-selector-control-v1',
        'initial_state':initial, 'state':final.as_dict(), 'events':projected,
        'binding_callbacks':journal, 'binding_scope':'one-retained-global-form',
        'choice_identity':'exact-current-ordinal-object-identity-and-value',
        'automatic_notify_schedule_inferred':False, 'automatic_currency_selection_inferred':False,
        'null_selected_value_parsing_verified':False, 'host_gui_executed':False,
        'bound_collection_observer_supplied':observe_choices is not None,
        'implicit_read_value_inferred':False, 'scene_name_pending_committed_or_discarded':False}
    return SceneSelectorControlResult(final, json.dumps(receipt, ensure_ascii=False, allow_nan=False))
