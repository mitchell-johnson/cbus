"""Selected-category eDLT database payloads from one explicit model load.

The source Project value is preserved. This is the original model/category
path, not the outer global form, its ResetUnit or its Project setter preamble.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from types import MappingProxyType
from typing import Mapping
import weakref

from .edlt import EdltError
from .edlt_lifecycle import EdltLifecycle, LifecycleCache


CATEGORIES = MappingProxyType({
    'key-settings': ('UseBigIcon', 'FontStyle', 'DateFormat', 'TimeFormat',
        'TimeDateLeadingZero', 'EnableTimerFlash', 'EnableFanControlLevelWrap'),
    'standby': ('ActivityDuration', 'TimeoutPage', 'IndicatorIdleBrightnessControlGroup',
        'BacklightIdleBrightnessControlGroup', 'IdleIndicatorBrightness', 'IdleBacklightBrightness',
        'EnableNightlightUserKey', 'EnableNightlightPageKey', 'NightlightColour', 'ProximityMode',
        'IgnoreFirstKeyPress', 'ProximityGroup', 'ProximityLevel', 'DeafultPage'),
    'colour': ('LCDBackground', 'LCDForeground', 'BacklightActiveBrightnessControlGroup',
        'IndicatorOffColourControlGroup', 'IndicatorOnColourControlGroup', 'IndicatorActiveBrightnessControlGroup',
        'IndicatorOffColour', 'IndicatorOnColour', 'ActiveIndicatorBrightness', 'ActiveBacklightBrightness',
        'NavigationIndicatorColour', 'QuickStatusMode', 'QuickStatusGroup', 'QuickStatusColour1',
        'QuickStatusColour2', 'QuickStatusColour3', 'QuickStatusLevel1', 'QuickStatusLevel2'),
    'general': ('CorridorLinkingCorridorGroup', 'CorridorLinkingOfficeGroup', 'CorridorLinkingLinkGroup',
        'CorridorLinkingCorridorTime', 'KeySetsEnableGroup', 'LongPressTime', 'DebounceTime',
        'StatusRequestInterval', 'ToolsPageLocked'),
})
CRC_NAMES = ('OverallCRC', 'GlobalParameterCRC', 'WidgetsCRC', 'StaticTextCRC', 'ScenesCheckSum')
# Independent exact KEYGL5 layouts, in the category declaration order above.
_LAYOUTS = (
    (0x118,4,1),(0x118,0,3),(0x119,0,4),(0x119,5,2),(0x119,4,1),(0x116,2,1),(0x117,5,1),
    (0x11b,0,8),(0x11a,5,2),(0x12d,0,8),(0x12e,0,8),(0x11f,0,8),(0x120,0,8),
    (0x116,6,1),(0x116,7,1),(0x117,3,2),(0x117,0,3),(0x116,0,1),(0x123,0,8),(0x124,0,8),(0x11a,0,4),
    (0x113,0,3),(0x113,3,3),(0x130,0,8),(0x12c,0,8),(0x12b,0,8),(0x12f,0,8),
    (0x11d,0,8),(0x11c,0,8),(0x121,0,8),(0x122,0,8),(0x11e,0,8),(0x116,3,3),
    (0x125,0,8),(0x126,0,8),(0x127,0,8),(0x128,0,8),(0x129,0,8),(0x12a,0,8),
    (0x136,0,8),(0x133,0,8),(0x132,0,8),(0x134,0,16),(0x131,0,8),(0x114,0,8),
    (0x115,0,8),(0x112,0,8),(0x11a,4,1),
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _values(value):
    return {name: list(item) if isinstance(item, tuple) else item for name, item in value.items()}


def _native_value(value):
    """Original PP numeric spelling; category fields contain only integers."""
    return ' '.join(hex(number) for number in value)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _scope(source=None):
    result = {'unit_type': 'KEYGL5', 'catalog_number': '5055EDL', 'firmware': '5.5.00',
        'source_project_policy': 'preserve', 'full_form_preamble_applied': False,
        'default_template_reset_verified': False, 'physical_device_verified': False,
        'destination_full_crc_validity_verified': False, 'export_is_review_only': True}
    if source is not None and source.factory_preparation is not None:
        result.update(source_project_policy='explicit cached-network Project setter in model sidecar',
            default_template_reset_verified=True, factory_model_preparation_applied=True,
            full_form_executed=False, physical_codec_relaxed=False,
            source_database_required=True, arbitrary_source_history_verified=False)
    return result


def _payload_native_value(payload, name, value):
    """Render only a selected numeric value, retaining factory raw spellings."""
    if (type(name) is not str or type(value) is not tuple or not value
            or any(type(number) is not int for number in value)
            or name not in dict(payload.ordered_payload) or dict(payload.ordered_payload)[name] != value):
        raise EdltError('Invalid selected numeric Global payload value')
    prepared = payload.source.factory_preparation
    if prepared is None: return _native_value(value)
    text = '0x0 0x0' if name == 'GlobalParameterCRC' else prepared.raw_phases['final'].raw[name]
    if (type(text) is not str or not re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|[0-9]+)(?: (?:0[xX][0-9a-fA-F]+|[0-9]+))*', text)
            or tuple(int(n,16) if n.lower().startswith('0x') else int(n) for n in text.split(' ')) != value):
        raise EdltError('Factory literal payload differs from its validated numeric projection')
    return text


class _Origin:
    def __init__(self, owner):
        self.owner, self.reference = owner, None


def _issue(value):
    value._origin.reference = weakref.ref(value)
    return value


def _issued(value, kind, owner):
    if (type(value) is not kind or type(value._origin) is not _Origin or
            value._origin.owner is not owner or value._origin.reference is None or
            value._origin.reference() is not value):
        raise EdltError('Use an intact issued ' + kind.__name__ + ' from this engine')


@dataclass(frozen=True)
class GlobalSource:
    expected: Mapping
    after_load: Mapping
    before_save: Mapping
    final: Mapping
    metadata: LifecycleCache
    parameter_order: tuple[str, ...]
    lifecycle: str
    _origin: _Origin = field(repr=False, compare=False)
    factory_preparation: object | None = field(default=None, repr=False)

    def __post_init__(self):
        for name in ('expected', 'after_load', 'before_save', 'final'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        result = {'format': 'cbus-edlt-global-source-v1', **_scope(self),
            'source_preparation': 'one unbound AfterLoad followed by BeforeSave and source CRCs',
            'expected': _values(self.expected), 'after_load': _values(self.after_load),
            'before_save': _values(self.before_save), 'final': _values(self.final),
            'parameter_order': list(self.parameter_order), 'metadata': self.metadata.as_dict(),
            'lifecycle': json.loads(self.lifecycle), 'source_crcs': _values({k: self.final[k] for k in CRC_NAMES}),
            'saved': False}
        if self.factory_preparation is not None:
            result['source_preparation'] = 'issued factory Reset, tab removal and explicit Project preworker'
            result['factory_preparation'] = self.factory_preparation.as_dict()
        return result


@dataclass(frozen=True)
class GlobalPayload:
    source: GlobalSource
    categories: tuple[str, ...]
    ordered_payload: tuple[tuple[str, tuple[int, ...]], ...]
    _origin: _Origin = field(repr=False, compare=False)

    @property
    def values(self):
        return MappingProxyType(dict(self.ordered_payload))

    def as_dict(self):
        result = {'format': 'cbus-edlt-global-payload-v1', **_scope(self.source),
            'source': self.source.as_dict(), 'source_hash': _hash(self.source.as_dict()),
            'categories': list(self.categories),
            'ordered_payload': [{'parameter': name, 'value': list(value), 'native_value': _payload_native_value(self, name, value)}
                                for name, value in self.ordered_payload],
            'forced_parameter_count': len(self.ordered_payload),
            'wire_order_policy': 'source-attribute-order-then-zero-global-crc',
            'arbitrary_original_dirty_history_wire_order_verified': False,
            'destination_crc_policy': 'source OverallCRC; zero GlobalParameterCRC; preserve three destination section CRCs',
            'repeat_policy': 'reuse frozen prepared payload; no second AfterLoad or mutable UI history', 'saved': False}
        if self.source.factory_preparation is not None:
            dirty = set(self.source.factory_preparation.raw_phases['final'].dirty_parameters)
            dirty.update(name for name, _ in self.ordered_payload if name != 'GlobalParameterCRC')
            result['factory_worker_dirty_parameters'] = sorted(dirty)
            result['factory_literal_values_preserved'] = True
            result['full_factory_original_worker_masks_verified'] = [0, 15]
        return result


@dataclass(frozen=True)
class GlobalMerge:
    payload: GlobalPayload
    expected: Mapping
    final: Mapping
    _origin: _Origin = field(repr=False, compare=False)

    def __post_init__(self):
        for name in ('expected', 'final'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-global-merge-v1', **_scope(self.payload.source),
            'expected': _values(self.expected), 'final': _values(self.final),
            'changes': _values({k: v for k, v in self.final.items() if self.expected[k] != v}),
            'payload': self.payload.as_dict(),
            'forced_unchanged_parameters': [k for k, v in self.payload.ordered_payload if self.expected[k] == v],
            'saved': False}


class EdltGlobalProgramming:
    def __init__(self, spec):
        self.lifecycle = EdltLifecycle(spec)
        self.common = self.lifecycle.common
        self.spec, self.codec = spec, self.common.codec
        self._owner = object()
        for name, layout in zip((n for names in CATEGORIES.values() for n in names), _LAYOUTS):
            if name not in spec.parameters:
                raise EdltError('Global Programming schema is missing ' + name)
            actual = self.codec.layout(name)
            if (actual.address, actual.bit_address, actual.bit_size) != layout or actual.array_size != 1:
                raise EdltError('Unsupported Global Programming layout for ' + name)

    def snapshot(self, values):
        return self.common.snapshot(values)

    def prepare_source(self, values, *, metadata, parameter_order=None):
        if not isinstance(values, Mapping):
            raise EdltError('Source parameters must be a complete mapping')
        order = tuple(values) if parameter_order is None else parameter_order
        if (not isinstance(order, (tuple, list)) or any(type(name) is not str for name in order) or
                len(order) != len(self.spec.parameters) or len(set(order)) != len(order) or set(order) != set(self.spec.parameters)):
            raise EdltError('parameter_order must contain every schema parameter exactly once')
        plan = self.lifecycle.plan(values, metadata=metadata)
        final = {**plan.expected, **plan.changes}
        return _issue(GlobalSource(plan.expected, plan.after_load, plan.before_save, final,
            plan.metadata, tuple(order), _json(plan.as_dict()), _Origin(self._owner)))

    def _source(self, source):
        _issued(source, GlobalSource, self._owner)
        if source.factory_preparation is not getattr(source._origin, 'factory_preparation', None):
            raise EdltError('Global source factory preparation identity changed')
        for value in (source.expected, source.after_load, source.before_save, source.final):
            self.snapshot(value)
        if source.factory_preparation is not None:
            from .edlt_global_preparation import _validate_prepared_factory
            prepared = _validate_prepared_factory(source.factory_preparation, self)
            if (any(dict(getattr(source, name)) != dict(getattr(prepared, name))
                    for name in ('expected','after_load','before_save','final'))
                    or source.parameter_order != prepared.parameter_order
                    or source.metadata is not prepared.metadata.lifecycle
                    or source.lifecycle != prepared.model_plan):
                raise EdltError('Factory Global source differs from its issued preparation')

    def prepare_factory_source(self, prepared):
        """Bridge an issued factory preparation without another load or save."""
        from .edlt_global_preparation import _validate_prepared_factory
        prepared = _validate_prepared_factory(prepared, self)
        source = _issue(GlobalSource(prepared.expected, prepared.after_load,
            prepared.before_save, prepared.final, prepared.metadata.lifecycle,
            prepared.parameter_order, prepared.model_plan, _Origin(self._owner), prepared))
        source._origin.factory_preparation = prepared
        self._source(source)
        return source

    def select(self, source, *, categories=()):
        self._source(source)
        if (not isinstance(categories, (tuple, list)) or any(type(name) is not str or name not in CATEGORIES for name in categories)
                or len(categories) != len(set(categories))):
            raise EdltError('Select each known Global Programming category at most once')
        selected = tuple(name for name in CATEGORIES if name in categories)
        allowed = {'OverallCRC'} | {name for category in selected for name in CATEGORIES[category]}
        payload = tuple((name, source.final[name]) for name in source.parameter_order if name in allowed)
        payload += (('GlobalParameterCRC', (0, 0)),)
        return _issue(GlobalPayload(source, selected, payload, _Origin(self._owner)))

    def _payload(self, payload):
        _issued(payload, GlobalPayload, self._owner)
        self._source(payload.source)
        expected = self.select(payload.source, categories=payload.categories)
        if payload.ordered_payload != expected.ordered_payload:
            raise EdltError('Global Programming payload differs from its source/category policy')
        for name, value in payload.ordered_payload: _payload_native_value(payload, name, value)

    def merge(self, payload, destination_values):
        self._payload(payload)
        before = self.snapshot(destination_values)
        final = self.snapshot({**before, **payload.values})
        return _issue(GlobalMerge(payload, before, final, _Origin(self._owner)))

    def _merge(self, merge):
        _issued(merge, GlobalMerge, self._owner)
        self._payload(merge.payload)
        self.snapshot(merge.expected)
        self.snapshot(merge.final)
        if dict(merge.final) != self.snapshot({**merge.expected, **merge.payload.values}):
            raise EdltError('Global Programming merge differs from its complete target preconditions')
