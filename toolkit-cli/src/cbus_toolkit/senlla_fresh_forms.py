"""Internal SENLLA fresh-form handlers, with owning callback boundaries.

These generators issue native setter/control requests. After each request the
executor must finish its synchronous notifications and send a new immutable
context. They never flatten application, key, Scene or bank side effects into
an inferred final PP image. Control requests retain the original Windows list
comparison/rendering boundary rather than guessing a host locale.
"""
from dataclasses import dataclass

from .senlla_key_references import SENLLAKeyReferences
from .sensors import SensorError


def _integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise SensorError(f'{label} requires an integer in {minimum}..{maximum}')
    return value


def _identity(value, label, *, nil=False):
    if nil and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise SensorError(f'{label} requires a nonempty canonical object identity')
    return value


def _text(value, label):
    if not isinstance(value, str):
        raise SensorError(f'{label} requires text')
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise SensorError(f'{label} requires a Boolean')
    return value


def _eight(values, label, validate):
    if not isinstance(values, (list, tuple)) or len(values) != 8:
        raise SensorError(f'{label} requires exactly eight entries')
    return tuple(validate(value) for value in values)


def _detached(value):
    if hasattr(value, 'as_dict'):
        return value.as_dict()
    if isinstance(value, tuple):
        return [_detached(item) for item in value]
    return value


@dataclass(frozen=True)
class FormGroup:
    """One existing group in its actual application's manager inventory."""
    object_id: str
    application_id: str
    address: int
    tag_name: str

    def __post_init__(self):
        _identity(self.object_id, 'Group')
        _identity(self.application_id, 'Group application')
        _integer(self.address, 0, 255, 'Group address')
        _text(self.tag_name, 'Group TagName')

    def as_dict(self):
        return dict(object_id=self.object_id, application_id=self.application_id,
                    address=self.address, tag_name=self.tag_name)


@dataclass(frozen=True)
class FormApplication:
    """Complete ordered existing group inventory, without inferred creations."""
    object_id: str
    address: int
    tag_name: str
    groups: tuple[FormGroup, ...]

    def __post_init__(self):
        _identity(self.object_id, 'Application')
        _integer(self.address, 0, 255, 'Application address')
        _text(self.tag_name, 'Application TagName')
        if not isinstance(self.groups, (list, tuple)):
            raise SensorError('Application groups require an ordered inventory')
        groups = tuple(self.groups)
        if any(type(group) is not FormGroup or group.application_id != self.object_id
               for group in groups):
            raise SensorError('Every group must belong to its owning application')
        if (len({group.object_id for group in groups}) != len(groups)
                or len({group.address for group in groups}) != len(groups)):
            raise SensorError('Application inventory contains duplicate group objects or addresses')
        object.__setattr__(self, 'groups', groups)

    def as_dict(self):
        return dict(object_id=self.object_id, address=self.address, tag_name=self.tag_name,
                    groups=[group.as_dict() for group in self.groups])


@dataclass(frozen=True)
class FormChoice:
    kind: str
    identity: int | str
    label: str

    def __post_init__(self):
        if self.kind == 'block':
            _integer(self.identity, 0, 7, 'Choice block')
        elif self.kind in ('group', 'other'):
            _identity(self.identity, 'Choice object')
        else:
            raise SensorError('Choice kind requires block, group or other')
        _text(self.label, 'Choice label')

    def as_dict(self):
        return dict(kind=self.kind, identity=self.identity, label=self.label)


@dataclass(frozen=True)
class FreshFormContext:
    """Current owning graph and native control facts at one callback position.

Object IDs identify actual manager-owned objects; equal numeric addresses in
different applications remain distinct. Inventories must come from the owning
snapshot, not guesses or an edited subset. Unknown/nil references are refused
when a source handler actually dereferences them.
"""
    applications: tuple[FormApplication, ...]
    primary_application: str | None
    secondary_application: str | None
    block_groups: tuple[str | None, ...]
    block_labels: tuple[str, ...]
    bank_active: tuple[bool, ...]
    key_scene: tuple[bool, ...]
    key_templates: tuple[int | None, ...]
    references: SENLLAKeyReferences
    occupancy_flags: tuple[tuple[bool, bool, bool, bool], ...]
    pec_group: str | None
    pir_group: str | None
    join_group: str | None
    dual_join_group: str | None
    corridor_group: str | None
    corridor_active: bool
    maintenance_active: bool
    maintenance_block: int | None
    broadcast_active: bool
    broadcast_block: int | None
    maintenance_selected: FormChoice | None = None
    external_broadcast_callback: bool = False
    broadcast_items: tuple[int, ...] | None = None

    def __post_init__(self):
        if (not isinstance(self.applications, (list, tuple))
                or any(type(app) is not FormApplication for app in self.applications)):
            raise SensorError('Form context requires complete application inventories')
        apps = tuple(self.applications)
        if (len({app.object_id for app in apps}) != len(apps)
                or len({app.address for app in apps}) != len(apps)):
            raise SensorError('Application objects and addresses must be canonical and unique')
        groups = [group for app in apps for group in app.groups]
        if len({group.object_id for group in groups}) != len(groups):
            raise SensorError('Group identity cannot belong to multiple applications')
        object.__setattr__(self, 'applications', apps)
        for name in ('primary_application', 'secondary_application', 'pec_group',
                     'pir_group', 'join_group', 'dual_join_group', 'corridor_group'):
            _identity(getattr(self, name), name, nil=True)
        object.__setattr__(self, 'block_groups', _eight(
            self.block_groups, 'Block groups', lambda item: _identity(item, 'Block group', nil=True)))
        object.__setattr__(self, 'block_labels', _eight(
            self.block_labels, 'Block labels', lambda item: _text(item, 'Block display text')))
        for name in ('bank_active', 'key_scene'):
            object.__setattr__(self, name, _eight(
                getattr(self, name), name, lambda item: _boolean(item, name)))
        object.__setattr__(self, 'key_templates', _eight(
            self.key_templates, 'Key templates',
            lambda item: None if item is None else _integer(item, 0, 255, 'Template type')))
        if self.key_scene != tuple(value in (23, 24, 25) for value in self.key_templates):
            raise SensorError('Current Scene status must match native template types23/24/25')
        if type(self.references) is not SENLLAKeyReferences:
            raise SensorError('Form context requires resolved ordered key references')
        def flags(row):
            if not isinstance(row, (list, tuple)) or len(row) != 4:
                raise SensorError('Occupancy flags require Light/Dark/Any/Sunset Booleans')
            return tuple(_boolean(item, 'Occupancy flag') for item in row)
        object.__setattr__(self, 'occupancy_flags', _eight(self.occupancy_flags, 'Occupancy', flags))
        for name in ('corridor_active', 'maintenance_active', 'broadcast_active',
                     'external_broadcast_callback'):
            _boolean(getattr(self, name), name)
        for name in ('maintenance_block', 'broadcast_block'):
            value = getattr(self, name)
            if value is not None:
                _integer(value, 0, 7, name)
        if self.maintenance_selected is not None and type(self.maintenance_selected) is not FormChoice:
            raise SensorError('Selected maintenance item requires an actual typed control object')
        if self.broadcast_items is not None:
            if not isinstance(self.broadcast_items, (list, tuple)):
                raise SensorError('Current broadcast items require an ordered native collection')
            items = tuple(_integer(item, 0, 7, 'Broadcast candidate') for item in self.broadcast_items)
            if len(items) != len(set(items)):
                raise SensorError('Native broadcast candidates cannot contain duplicate blocks')
            object.__setattr__(self, 'broadcast_items', items)

    def application(self, identity):
        for application in self.applications:
            if application.object_id == identity:
                return application
        raise SensorError('Source accessed an unavailable application object identity')

    def group(self, identity):
        for application in self.applications:
            for group in application.groups:
                if group.object_id == identity:
                    return group
        raise SensorError('Source accessed a nil or unavailable group object identity')

    def unused_primary_group(self):
        for group in self.application(self.primary_application).groups:
            if group.address == 255:
                return group.object_id
        raise SensorError('Source requires the existing primary unused group object; creation is disabled')

    def has_block(self, key, block):
        return block is not None and block in self.references.ordered_references[key]

    def as_dict(self):
        return {name: _detached(getattr(self, name)) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class FormRequest:
    kind: str
    method: str
    target_kind: str
    target_index: int | None
    value: object
    source_address: str
    callback_contract: str

    def __post_init__(self):
        def immutable(value):
            if type(value) in (str, int, bool, type(None), FormChoice):
                return
            if type(value) is tuple:
                for item in value:
                    immutable(item)
                return
            raise SensorError('Form request values must be immutable source facts')
        immutable(self.value)

    def as_dict(self):
        return {name: _detached(getattr(self, name)) for name in self.__dataclass_fields__}


_SETTER_CONTRACT = (
    'Use the owning senlla_lifecycle attribute substrate, retaining CanDoChange '
    'refusal while the reference attribute itself updates, BeforeChange changed '
    'flag semantics and nonnil-to-nil reset notifications. Execute the native '
    'setter with attribute-manager parent Begin/EndUpdate; '
    'complete generic publication, dedicated AfterChange and nested callbacks '
    'and native exception unwinding before resuming. Equal references that '
    'pass the attribute guard retain dedicated callbacks; '
    'equal Booleans produce no notification.')
_TAG_NAME_CONTRACT = (
    'Execute TCBUSUnit+0x9c TCISTagAttribute virtual+0x7c through '
    'TStringAttribute.SetValue0x7f39a0, SetAsString0x7f3b28 and '
    'InternalSetAsString0x7f37d4. BeforeChange runs before Begin, including '
    'equal requests; honor its mutable candidate and changed flag. The native '
    'owner TagNameBeforeChange0xf48228 is empty. A false changed flag returns '
    'without update; a changed candidate exceeding 32 UTF16 code units raises '
    'before Begin without clamping. Execute attribute/manager Begin and End '
    'with native finally/unwinding, generic publication and dedicated '
    'HandleTagNameAfterChange0xf47b04 before resuming. Delegate its optional '
    'owner OnTagNameChange and conditional manager after-change timer using '
    'actual owning callback facts. This string route has no reference '
    'updating guard or nil-reset notifications.')
_CONTROL_CONTRACT = (
    'Execute the exact native control/list operation, including installed callbacks, '
    'then return current selected-object facts. Preserve Windows comparison/rendering '
    'semantics; do not infer them from Python casefold or host locale.')


def _request(method, value, source, *, target_kind='unit', target_index=None,
             kind='setter'):
    contract = (_TAG_NAME_CONTRACT if target_kind == 'unit_metadata' else _SETTER_CONTRACT)
    return FormRequest(kind, method, target_kind, target_index, value, source,
                       contract if kind == 'setter' else _CONTROL_CONTRACT)


def _context(value):
    if type(value) is not FreshFormContext:
        raise SensorError('Resume each form request with a current immutable FreshFormContext')
    return value


def maintenance_choices(context):
    """Block choices, then unallocated used primary/secondary group objects."""
    context = _context(context)
    choices, free = [], False
    for block in range(8):
        if (context.broadcast_active and context.maintenance_active
                and block == context.broadcast_block) or context.bank_active[block]:
            continue
        choices.append(FormChoice('block', block, context.block_labels[block]))
        if not free:
            free = (context.group(context.block_groups[block]).address == 255
                    and not context.key_scene[block])
    if free:
        primary = context.application(context.primary_application)
        secondary = context.application(context.secondary_application)
        applications = (primary,) if secondary.address == 255 else (primary, secondary)
        for application in applications:
            for group in application.groups:
                if group.address != 255 and group.object_id not in context.block_groups:
                    label = f'{group.tag_name} ({application.tag_name})'
                    choices.append(FormChoice('group', group.object_id, label))
    return tuple(choices)


def broadcast_choices(context):
    """All block candidates in source order, with current shared-key exclusions."""
    context = _context(context)
    return tuple(block for block in range(8)
                 if not (context.maintenance_active and context.broadcast_active
                         and block == context.maintenance_block)
                 and not any(context.has_block(key, block)
                             and (context.key_scene[key] or any(context.occupancy_flags[key]))
                             for key in range(8)))


def pec_group_included(context, group_id):
    """PEC IncludeItem explicitly sets True before its used-group exclusions."""
    context = _context(context)
    if context.group(group_id).address == 255:
        return True
    return not (group_id in (context.join_group, context.dual_join_group, context.pir_group)
                or group_id in context.block_groups
                or (group_id == context.corridor_group and context.corridor_active))


def pir_group_included(context, group_id, *, initial_include=True):
    """PIR IncludeItem only clears the incoming flag; it has no block filter."""
    context = _context(context)
    _boolean(initial_include, 'Incoming IncludeItem')
    if context.group(group_id).address == 255:
        return initial_include
    return initial_include and not (
        group_id in (context.join_group, context.dual_join_group)
        or (group_id == context.pec_group and context.maintenance_active)
        or (group_id == context.corridor_group and context.corridor_active))


def _populate_maintenance(context, source):
    return _request('PopulateMaintenanceChoices', maintenance_choices(context), source,
                    kind='control', target_kind='maintenance_combo')


def _populate_broadcast(context, source):
    return _request('PopulateBroadcastChoices', broadcast_choices(context), source,
                    kind='control', target_kind='broadcast_combo')


def pec_enable_changed(context):
    context = _context(context)
    if context.group(context.pec_group).address == 255:
        return _context((yield _request('SetLightLevelMaintEnableGroupOff', False, '0xfa7891')))
    return context


def pir_enable_changed(context):
    context = _context(context)
    if context.group(context.pir_group).address == 255:
        return _context((yield _request('SetOccupancyEnableGroupOff', False, '0xfaf7c9')))
    return context


def maintenance_checked(context):
    """Manual fresh PEC handler; its predicate does not inspect UI Checked."""
    context = _context(context)
    if context.group(context.pec_group).address != 255:
        collision = (context.pec_group in (context.join_group, context.dual_join_group,
                                          context.pir_group)
                     or (context.pec_group == context.corridor_group and context.corridor_active)
                     or context.pec_group in context.block_groups)
        if collision:
            context = _context((yield _request('SetLightLevelMaintEnableGroup',
                                               context.unused_primary_group(), '0xfa74ee')))
    if (context.broadcast_active and context.maintenance_active
            and context.broadcast_block == context.maintenance_block):
        context = _context((yield _populate_maintenance(context, '0xfa7530')))
        context = _context((yield _request('SetItemIndex', 0, '0xfa7545',
                                          kind='control', target_kind='maintenance_combo')))
    # Source explicitly invokes this callback even if no group setter ran.
    context = yield from pec_enable_changed(context)
    return _context((yield _populate_broadcast(context, '0xfa7583')))


def set_maintenance_group(context, group_id):
    """Source allocates the first unused non-Scene same-index block.

    The scan intentionally does not repeat bank-active/broadcast choice filters.
    The selected group object is captured across the three native setters.
    """
    context = _context(context)
    group = context.group(group_id)
    for block in range(8):
        if context.group(context.block_groups[block]).address != 255 or context.key_scene[block]:
            continue
        # Native code compares the App2 pointer; unlike choice population it
        # never dereferences it. An actual nil App2 therefore selects False.
        secondary = group.application_id == context.secondary_application
        context = _context((yield _request('SetSecondaryApplication', secondary, '0xfa8738',
                                          target_kind='block', target_index=block)))
        context = _context((yield _request('SetGroup', group_id, '0xfa8754',
                                          target_kind='block', target_index=block)))
        return _context((yield _request('SetLightLevelMaintBlock', block, '0xfa8775')))
    return context


def maintenance_combo_changed(context):
    context = _context(context)
    selected = context.maintenance_selected
    if selected is not None and selected.kind == 'block':
        return _context((yield _request('SetLightLevelMaintBlock', selected.identity, '0xfa77f3')))
    if selected is not None and selected.kind == 'group':
        return (yield from set_maintenance_group(context, selected.identity))
    return context


def maintenance_block_changed(context, expression_text):
    context = _context(context)
    _text(expression_text, 'Maintenance expression text')
    if (context.maintenance_active and context.broadcast_active
            and context.maintenance_block == context.broadcast_block):
        context = _context((yield _populate_maintenance(context, '0xfa772b')))
        return _context((yield _request('SetItemIndex', 0, '0xfa7740', kind='control',
                                       target_kind='maintenance_combo')))
    context = _context((yield _request('IndexOfAndSetItemIndex', expression_text, '0xfa7763',
                                      kind='control', target_kind='maintenance_combo')))
    return _context((yield _populate_broadcast(context, '0xfa777f')))


def setup_maintenance_selection(context):
    """ST7 SetupNonFlash tail, after the owner's separate target clamp."""
    context = _context(context)
    context = _context((yield _request('InstallOnChange', 'HandleMaintBlockComboChange', '0xfa8c54',
                                      kind='control', target_kind='maintenance_combo')))
    if context.maintenance_block is None:
        raise SensorError('Native SetupNonFlash dereferences a nil maintenance block')
    return _context((yield _request('IndexOfAndSetItemIndex',
                                   context.block_labels[context.maintenance_block], '0xfa8c8b',
                                   kind='control', target_kind='maintenance_combo')))


_FLAGS = ('LightAndMovement', 'DarkAndMovement', 'AnyMovement', 'Sunset')


def broadcast_checked(context):
    """Manual fresh PEC broadcast callback, with row-level CURRENT reads."""
    context = _context(context)
    if context.broadcast_active:
        for key in range(8):
            if not context.has_block(key, context.broadcast_block):
                continue
            for field, source in zip(_FLAGS, ('0xfa72d2', '0xfa72ed', '0xfa7308', '0xfa7323')):
                context = _context((yield _request(f'Set{field}', False, source,
                                                  target_kind='occupancy', target_index=key)))
            if context.key_scene[key]:
                context = _context((yield _request('SetMacroFunctionTemplate', 16, '0xfa7369',
                                                  target_kind='key', target_index=key)))
        if context.maintenance_active and context.broadcast_block == context.maintenance_block:
            context = _context((yield _populate_broadcast(context, '0xfa73a8')))
            # Count<0 in native source does not protect GetItems(0) when empty.
            choices = context.broadcast_items
            if choices is None:
                raise SensorError('Broadcast fallback requires the current native candidate collection')
            if not choices:
                raise SensorError('Native broadcast fallback indexes an empty candidate collection')
            context = _context((yield _request('SetLightLevelBroadcastBlock', choices[0], '0xfa73d1')))
    if context.external_broadcast_callback:
        context = _context((yield _request('ExternalBroadcastFormCallback', None, '0xfa73e9',
                                          kind='callback', target_kind='form')))
    return _context((yield _populate_maintenance(context, '0xfa73ef')))


def broadcast_after_change(context):
    """Both unit broadcast attribute AfterChange handlers share this body."""
    context = _context(context)
    if (context.maintenance_active and context.broadcast_active
            and context.maintenance_block == context.broadcast_block):
        return context
    for block in range(8):
        value = 8 if block == context.broadcast_block and context.broadcast_active else None
        context = _context((yield _request('SetTimerExpiryCommandOverride', value, '0xcfc820',
                                          target_kind='block', target_index=block)))
    # These entry conditions are checked after every timer callback has finished.
    if context.broadcast_active and context.broadcast_block is not None:
        for key in range(8):
            if not context.has_block(key, context.broadcast_block):
                continue
            if context.key_templates[key] is None:
                raise SensorError('Native broadcast function refresh dereferences a nil key template')
            if context.key_templates[key] in (29, 30, 33, 34):
                context = _context((yield _request('SetMacroFunctionTemplate', 16, '0xcfc80d',
                                                  target_kind='key', target_index=key)))
    return context


def refresh_broadcast_from_key_blocks(context):
    context = _context(context)
    candidate, conflict = None, False
    for key in range(8):
        if not any(context.occupancy_flags[key]):
            if candidate is None:
                candidate = context.references.primary_block(key)
        elif context.has_block(key, context.broadcast_block):
            conflict = True
    if conflict and candidate is not None:
        return _context((yield _request('SetLightLevelBroadcastBlock', candidate, '0xcfc74a')))
    return context


def refresh_occupancy_from_key_blocks(context):
    context = _context(context)
    for key in range(8):
        if not context.broadcast_active or not context.has_block(key, context.broadcast_block):
            continue
        for field, source in zip(_FLAGS, ('0xcfcd7c', '0xcfcd86', '0xcfcd90', '0xcfcd9a')):
            context = _context((yield _request(f'Set{field}', False, source,
                                              target_kind='occupancy', target_index=key)))
    return context


def input_key_blocks_changed(context, changed_key):
    context = _context(context)
    changed_key = _integer(changed_key, 0, 7, 'Changed key')
    context = _context((yield _request('InheritedInputKeyBlocksChanged', changed_key, '0xcfb716',
                                      kind='callback', target_kind='unit')))
    context = yield from refresh_occupancy_from_key_blocks(context)
    context = yield from refresh_broadcast_from_key_blocks(context)
    return _context((yield _request('RefreshEventFlagsFromMacroFunction', None, '0xcfb748',
                                   kind='callback', target_kind='occupancy', target_index=changed_key)))


@dataclass(frozen=True)
class IdentificationContext:
    """Actual control/cache/model metadata after native rendering or callbacks."""
    control_text: str
    controller_text: str
    model_unit_name: str
    unit_tag_name: str

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            _text(getattr(self, name), name)

    @property
    def cached_text_differs(self):
        return self.controller_text != self.model_unit_name

    def as_dict(self):
        return {**{name: getattr(self, name) for name in self.__dataclass_fields__},
                'cached_text_differs': self.cached_text_differs}


def _filtered_unit_name(control_text):
    _text(control_text, 'Actual unit-name control text')
    return ''.join(char for char in control_text
                   if 33 <= ord(char) <= 59 or ord(char) == 61 or 63 <= ord(char) <= 96)


def clean_unit_name_text(control_text):
    """Logical target of native SetText, without assuming its resulting state."""
    return _filtered_unit_name(control_text) or 'NEWUNIT'


def _identification_context(value):
    if type(value) is not IdentificationContext:
        raise SensorError('Resume identification requests with an actual IdentificationContext')
    return value


def unit_name_exit(context):
    """Direct fresh form Exit; actual umExit Apply remains a later owner event.

    SetText may be equal and deliver no Change notification. It may also deliver
    framework notifications before TagName is reread. The executor returns
    actual control/cache/model facts instead of this helper inferring them.
    """
    context = _identification_context(context)
    filtered = _filtered_unit_name(context.control_text)
    target = filtered or 'NEWUNIT'
    context = _identification_context((yield _request(
        'SetText', target, '0xdc14a6' if filtered else '0xdc14bb',
        kind='control', target_kind='unit_name_edit')))
    if context.unit_tag_name in ('', 'NEWUNIT'):
        context = _identification_context((yield _request(
            'SetTagName', context.control_text, '0xdc1532', target_kind='unit_metadata')))
    return context
