"""Original eDLT navigation page modes, formats and label references."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, StaticTextAllocation, _field, _int, _render
from .edlt_mra import MRAPropagation, normalize_mra_globals

PAGE_MODES = MappingProxyType({'single': 0, 'multiple': 1})
NAVIGATION_VARIANTS = MappingProxyType({'time': 0, 'date': 1, 'time-date': 2,
    'time-temperature': 3, 'date-temperature': 4, 'logo': 5, 'page-names': 6,
    'dynamic-labels': 7, 'blank': 15})
TEMPERATURE_SOURCES = MappingProxyType({'measurement': 0, 'hvac': 1})


@dataclass(frozen=True)
class NavigationGroup:
    application: int
    group: int
    dynamic_variants: tuple[int, ...]

    def __post_init__(self):
        _int(self.application, 'Metadata application'); _int(self.group, 'Metadata group')
        if not isinstance(self.dynamic_variants, tuple) or len(self.dynamic_variants) > 4:
            raise EdltError('Metadata dynamic_variants must have at most four indices')
        for index in self.dynamic_variants: _int(index, 'Metadata dynamic variant', 0, 3)
        if len(set(self.dynamic_variants)) != len(self.dynamic_variants):
            raise EdltError('Duplicate metadata dynamic variant')
        if self.group == 255 and self.dynamic_variants:
            raise EdltError('Unused group255 has no selectable dynamic variants')

    def as_dict(self):
        return {'application': self.application, 'group': self.group, 'dynamic_variants': list(self.dynamic_variants)}


@dataclass(frozen=True)
class NavigationMetadata:
    """Caller-supplied cached group evidence; no live reads or label verification."""
    groups: tuple[NavigationGroup, ...]

    def __post_init__(self):
        if not isinstance(self.groups, tuple) or len(self.groups) > 512 or any(type(group) is not NavigationGroup for group in self.groups):
            raise EdltError('Metadata must contain at most512 group records')
        if len({(group.application, group.group) for group in self.groups}) != len(self.groups):
            raise EdltError('Duplicate metadata application/group')

    @classmethod
    def from_dict(cls, document):
        if not isinstance(document, Mapping) or set(document) != {'format', 'groups'} or document['format'] != 'cbus-edlt-navigation-metadata-v1':
            raise EdltError('Invalid navigation metadata document')
        rows = document['groups']
        if not isinstance(rows, (list, tuple)) or len(rows) > 512:
            raise EdltError('Metadata must contain at most512 group records')
        result = []
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {'application', 'group', 'dynamic_variants'} or not isinstance(row['dynamic_variants'], (list, tuple)):
                raise EdltError('Invalid metadata group record')
            result.append(NavigationGroup(row['application'], row['group'], tuple(row['dynamic_variants'])))
        return cls(tuple(result))

    def as_dict(self):
        return {'format': 'cbus-edlt-navigation-metadata-v1', 'groups': [group.as_dict() for group in self.groups]}

    def find(self, application, group):
        return next((row for row in self.groups if (row.application, row.group) == (application, group)), None)


def _page_map(value, name):
    if value is None: return MappingProxyType({})
    if not isinstance(value, Mapping) or len(value) > 4:
        raise EdltError(name + ' must map pages1..4 to values')
    result = {}
    for key, item in value.items():
        page = int(key) if isinstance(key, str) and key in ('1', '2', '3', '4') else key
        _int(page, name + ' page', 1, 4)
        if page in result: raise EdltError('Duplicate page in ' + name)
        result[page] = item
    return MappingProxyType(dict(sorted(result.items())))


@dataclass(frozen=True)
class NavigationPlan:
    page_mode: str
    variant_raw: int
    temperature_raw: int
    device_or_group: int
    channel_or_zone: int
    dynamic_group: int
    page_name_indices: tuple[int, ...]
    expected: Mapping
    changes: Mapping
    options: Mapping
    allocations: Mapping[int, StaticTextAllocation]
    mra_propagation: MRAPropagation

    def __post_init__(self):
        for name in ('expected', 'changes', 'options', 'allocations'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        metadata = self.options['metadata']
        application = self.expected['PrimaryApplication'][0]
        def evidence(app, group):
            row = metadata.find(app, group) if metadata else None
            status = 'unused' if group == 255 else 'caller-cache-match' if row else 'missing-from-caller-cache' if metadata else 'unverified'
            return {'application': app, 'group': group, 'status': status,
                    'available_dynamic_variants': list(row.dynamic_variants) if row else [],
                    'physical_device_verified': False}
        return {'format': 'cbus-edlt-navigation-plan-v1', 'unit_type': 'KEYGL5', 'catalog_number': '5055EDL', 'firmware': '5.5.00',
            'page_mode': self.page_mode,
            'variant': next((name for name, value in NAVIGATION_VARIANTS.items() if value == self.variant_raw), None),
            'variant_raw': self.variant_raw, 'variant_ui_canonical': self.variant_raw in NAVIGATION_VARIANTS.values(),
            'temperature_source': 'hvac' if self.temperature_raw else 'measurement',
            'device_or_group': self.device_or_group, 'channel_or_zone': self.channel_or_zone,
            'temperature_channel_ui_canonical': not self.temperature_raw or self.channel_or_zone <= 4,
            'dynamic_group': self.dynamic_group, 'page_name_indices': {str(page): value for page, value in enumerate(self.page_name_indices, 1)},
            'static_allocations': {str(page): allocation.as_dict() for page, allocation in self.allocations.items()},
            'metadata': metadata.as_dict() if metadata else None, 'metadata_provenance': 'caller-supplied-cache' if metadata else None,
            'dynamic_group_metadata': evidence(application, self.dynamic_group),
            'temperature_group_metadata': evidence(172, self.device_or_group) if self.temperature_raw else None,
            'physical_dynamic_labels_verified': False, 'applies_to_whole_unit': True,
            'mra_propagation': self.mra_propagation.as_dict(),
            'normalization_changes': {name: list(value) for name, value in self.changes.items() if name.startswith('Widget') and name != 'WidgetsCRC'},
            'changes': {name: list(value) if isinstance(value, tuple) else value for name, value in self.changes.items()},
            'saved': False, 'physical_device_verified': False}


class EdltNavigation:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        shapes = {'NavWidgetType': (0x200, 0, 8), 'NavWidgetVariant': (0x201, 0, 4),
                  'TemperatureApplication': (0x201, 7, 1), 'NavDevIDZoneGroup': (0x202, 0, 8),
                  'NavChannelZoneNumber': (0x203, 0, 8), 'DynamicGroup': (0x204, 0, 8)}
        shapes.update({f'PageNameIndex{page}': (0x204 + page, 0, 8) for page in range(1, 5)})
        for name, shape in shapes.items():
            try: layout = self.codec.layout(name)
            except (ValueError, KeyError) as error: raise EdltError('Unsupported navigation layout: ' + name) from error
            if (layout.address, layout.bit_address, layout.bit_size) != shape or layout.parameter.type != 'int' or (layout.array_size, layout.array_skip) != (1, 0):
                raise EdltError('Unsupported navigation layout: ' + name)

    def snapshot(self, values): return self.common.snapshot(values)
    def crcs(self, values): return self.common.crcs(values)

    def plan(self, current, *, page_mode=None, variant=None, temperature_source=None, device_or_group=None,
             channel_or_zone=None, dynamic_group=None, page_names=None, page_name_indices=None, metadata=None):
        for name, option, choices in (('page_mode', page_mode, PAGE_MODES), ('variant', variant, NAVIGATION_VARIANTS), ('temperature_source', temperature_source, TEMPERATURE_SOURCES)):
            if option is not None and (not isinstance(option, str) or option not in choices):
                raise EdltError(name + ' must be one of ' + ', '.join(choices))
        for name, value in (('device_or_group', device_or_group), ('channel_or_zone', channel_or_zone), ('dynamic_group', dynamic_group)):
            if value is not None: _int(value, name)
        names, indices = _page_map(page_names, 'page_names'), _page_map(page_name_indices, 'page_name_indices')
        if set(names) & set(indices): raise EdltError('A page cannot specify both text and index')
        for text in names.values():
            if not isinstance(text, str) or '\0' in text: raise EdltError('Page names must be strings without NUL')
        for index in indices.values(): _int(index, 'Page name index')
        if metadata is not None and type(metadata) is not NavigationMetadata:
            metadata = NavigationMetadata.from_dict(metadata)
        options = dict(page_mode=page_mode, variant=variant, temperature_source=temperature_source, device_or_group=device_or_group,
                       channel_or_zone=channel_or_zone, dynamic_group=dynamic_group, page_names=names, page_name_indices=indices, metadata=metadata)
        original = self.snapshot(current); self.common.static_references(original)
        updates = dict(original)
        # Original MultiPage getter normalizes a stored value above1 to0.
        nav = 1 if original['NavWidgetType'][0] == 1 else 0
        if page_mode is not None: nav = PAGE_MODES[page_mode]
        updates['NavWidgetType'] = (nav,)
        if nav != 1 and (any(value is not None for value in (variant, temperature_source, device_or_group, channel_or_zone, dynamic_group)) or names or indices):
            raise EdltError('Navigation controls require multiple page mode')
        selected = original['NavWidgetVariant'][0]
        if variant is not None:
            selected = NAVIGATION_VARIANTS[variant]
            if selected != original['NavWidgetVariant'][0] and selected in (6, 7):
                for page in range(1, 5): updates[f'PageNameIndex{page}'] = (255 if selected == 6 else 0,)
        updates['NavWidgetVariant'] = (selected,)
        if any(value is not None for value in (temperature_source, device_or_group, channel_or_zone)) and selected not in (3, 4):
            raise EdltError('Temperature controls require time-temperature or date-temperature')
        if temperature_source is not None: updates['TemperatureApplication'] = (TEMPERATURE_SOURCES[temperature_source],)
        if device_or_group is not None: updates['NavDevIDZoneGroup'] = (device_or_group,)
        if channel_or_zone is not None:
            _int(channel_or_zone, 'channel_or_zone', 0, 4 if updates['TemperatureApplication'] == (1,) else 255)
            updates['NavChannelZoneNumber'] = (channel_or_zone,)
        if dynamic_group is not None:
            if selected not in (5, 7): raise EdltError('Dynamic group requires logo or dynamic-labels')
            updates['DynamicGroup'] = (dynamic_group,)
        if names and selected != 6: raise EdltError('Static page names require page-names variant')
        if indices and selected not in (6, 7): raise EdltError('Page indices require page-names or dynamic-labels variant')
        if selected == 7 and indices:
            group = updates['DynamicGroup'][0]
            row = metadata.find(original['PrimaryApplication'][0], group) if metadata else None
            if group == 255 or row is None: raise EdltError('Dynamic page selection requires matching cached group metadata')
            if any(index not in row.dynamic_variants for index in indices.values()):
                raise EdltError('Dynamic page index is unavailable in the supplied group metadata')
        allocations = {}
        for page in range(1, 5):
            field = f'PageNameIndex{page}'
            if page in names:
                text = names[page]
                if not text.strip(): updates[field] = (255,)
                else:
                    allocation = self.common.allocate_static_text(updates, text)
                    allocations[page] = allocation; updates.update(allocation.changes); updates[field] = (allocation.index,)
            elif page in indices:
                index = indices[page]
                if selected == 6 and index > 63 and index != 255: raise EdltError('Static page index must be0..63 or255')
                updates[field] = (index,)
        mra = normalize_mra_globals(updates, _preserve_stored_multiplexer=True, _preserve_stored_placement=True)
        updates = self.common._place_record(updates, 1, bytes(updates[_field(1, index)][0] for index in range(32)))
        updates.update(mra.changes)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return NavigationPlan('multiple' if nav else 'single', selected, updates['TemperatureApplication'][0],
            updates['NavDevIDZoneGroup'][0], updates['NavChannelZoneNumber'][0], updates['DynamicGroup'][0],
            tuple(updates[f'PageNameIndex{page}'][0] for page in range(1, 5)), original, changes, options, allocations, mra)

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {**plan.as_dict(), 'verified': False, 'saved': False,
                    'attempted_parameters': list(attempted), 'pp_state_uncertain': bool(attempted),
                    'automatic_retries': 0}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': str(original_error)}
        error.edlt_navigation_evidence = evidence

    def apply(self, session, plan):
        if not isinstance(plan, NavigationPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use a navigation plan returned by EdltNavigation.plan')
        if not isinstance(plan.page_mode, str) or plan.page_mode not in PAGE_MODES:
            raise EdltError('Invalid plan page mode')
        _int(plan.variant_raw, 'Plan navigation variant', 0, 15)
        _int(plan.temperature_raw, 'Plan temperature source', 0, 1)
        _int(plan.device_or_group, 'Plan device or group')
        _int(plan.channel_or_zone, 'Plan channel or zone')
        _int(plan.dynamic_group, 'Plan dynamic group')
        if not isinstance(plan.page_name_indices, tuple) or len(plan.page_name_indices) != 4:
            raise EdltError('Invalid plan page indices')
        for value in plan.page_name_indices: _int(value, 'Plan page index')
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid navigation plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated navigation settings')
        expected = {**plan.expected, **plan.changes}
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the navigation plan was made')
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the navigation plan')
        except (KeyboardInterrupt, SystemExit) as error:
            self._interrupted(error, plan, attempted)
            raise
        except Exception as error:
            rollback_errors = []
            try:
                for name in reversed(attempted):
                    if not getattr(session.programmer.client, 'connected', True):
                        rollback_errors.append('Connection lost; rollback stopped without recovery I/O; PP state is uncertain')
                        break
                    try:
                        session.set(name, _render(plan.expected[name]))
                    except Exception as rollback:
                        rollback_errors.append(str(rollback))
                if getattr(session.programmer.client, 'connected', True):
                    try:
                        if self.snapshot(session.values()) != dict(plan.expected):
                            rollback_errors.append('Original PP values could not be verified')
                    except Exception as rollback:
                        rollback_errors.append(str(rollback))
            except (KeyboardInterrupt, SystemExit) as interrupted:
                self._interrupted(interrupted, plan, attempted, error)
                interrupted.edlt_navigation_evidence['rollback_errors'] = rollback_errors
                raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
