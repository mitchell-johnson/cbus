"""Pure post-template-assignment eDLT model reconstruction, without controls.

The caller supplies the complete PPAttribute.Value strings *after* ordered XML
assignments. This boundary does not execute ResetUnit, BeforeChangePpAttributes,
SetupForm, recursive binding, navigation, or persistence. It cannot establish
those boundaries from PP values alone and deliberately exposes no Apply API.
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
from .edlt_lifecycle import EdltLifecycle, LifecycleCache, LoadedEdlt
from .edlt_reset import EdltResetControls, _RawState, _dirty
from .unitspec import ParameterSpec, UnitSpec


FORMAT = 'cbus-edlt-template-second-model-stage-v1'
UNEXECUTED_PHASES = (
    'ResetUnit(true)', 'PopulateWidgetPanels', 'BeforeChangePpAttributes',
    'SetupForm', 'recursive control setup and application population',
    'binding reset', 'navigation/selected-widget/page refresh', 'redraw timer',
    'BeforeSavePPData', 'Apply/OK persistence',
)
_NUMERIC = re.compile(r'(?:0[xX][0-9A-Fa-f]+|[0-9]+)(?: (?:0[xX][0-9A-Fa-f]+|[0-9]+))*\Z')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def _sha(value):
    return hashlib.sha256(_json(value).encode('ascii')).hexdigest()


def _spec_document(spec):
    return {'filename': spec.filename, 'metadata': dict(spec.metadata),
            'sources': list(spec.sources), 'overrides': [dict(row) for row in spec.overrides],
            # Parameter order is significant provenance, even though load looks up names.
            'parameters': [(name, parameter.name, parameter.type, parameter.source,
                            dict(parameter.fields), list(parameter.tags))
                           for name, parameter in spec.parameters.items()]}


def _copy_spec(spec):
    if type(spec) is not UnitSpec or any(type(p) is not ParameterSpec for p in spec.parameters.values()):
        raise EdltError('Second model staging requires an explicit UnitSpec')
    return UnitSpec(spec.filename, MappingProxyType(dict(spec.metadata)), tuple(spec.sources),
        MappingProxyType({name: ParameterSpec(p.name, p.type, p.source,
            MappingProxyType(dict(p.fields)), tuple(p.tags)) for name, p in spec.parameters.items()}),
        tuple(MappingProxyType(dict(row)) for row in spec.overrides))


def _retained(loaded):
    result = [loaded, loaded.metadata, loaded.requirements, loaded.widgets, *loaded.widgets,
              loaded.scenes, *loaded.scenes, loaded.static_labels, *loaded.static_labels,
              loaded.page_widget, loaded.mra]
    for scene in loaded.scenes:
        result.extend((scene.trigger, scene.items, *scene.items, *(item.group for item in scene.items)))
    return tuple(result)


class _StageOrigin:
    def __init__(self, owner):
        self.owner = owner
        self.reference = None
        self.signature = None
        self.retained = ()


@dataclass(frozen=True)
class SecondModelLoadStage:
    """Issued stage receipt. Diagnostic JSON is not a resumption format."""
    raw_before: Mapping
    raw_after_load: Mapping
    before: Mapping
    after_load: Mapping
    dirty_before: tuple[str, ...]
    dirty_after_load: tuple[str, ...]
    loaded: LoadedEdlt
    model_snapshot: str
    specification_sha256: str
    source_sha256: str
    cache_sha256: str
    dirty_sha256: str
    _origin: _StageOrigin = field(repr=False, compare=False)

    def __post_init__(self):
        for name in ('raw_before', 'raw_after_load', 'before', 'after_load'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': FORMAT, 'unit_type': 'KEYGL5', 'catalog_number': '5055EDL',
            'firmware': '5.5.00', 'status': 'model_staged',
            'input_boundary': 'caller-supplied post-assignment PPAttribute.Value strings',
            'specification_sha256': self.specification_sha256, 'source_sha256': self.source_sha256,
            'cache_sha256': self.cache_sha256, 'dirty_sha256': self.dirty_sha256,
            'parameter_count': len(self.raw_before),
            'raw_before': dict(self.raw_before), 'raw_after_load': dict(self.raw_after_load),
            'raw_changes': {name: {'before': self.raw_before[name], 'after': value}
                            for name, value in self.raw_after_load.items()
                            if value != self.raw_before[name]},
            'before': json.loads(_json(dict(self.before))),
            'after_load': json.loads(_json(dict(self.after_load))),
            'dirty_before': list(self.dirty_before), 'dirty_after_load': list(self.dirty_after_load),
            'initializing_after_load': False, 'model': json.loads(self.model_snapshot),
            'executed_phases': ['EdltLifecycle.load', 'raw AfterLoad assignment projection'],
            'unexecuted_phases': list(UNEXECUTED_PHASES),
            'raw_projection_scope': 'numeric AfterLoad writes and Blank RestoreLevel setter casing',
            'original_differences': [
                'Original mutable BindingLists retain identity while replacing their elements; '
                'this pure stage publishes separate immutable graph snapshots.',
                'An original failed load may leave partial model lists; this stage publishes no failed candidate.',
            ],
            'original_token_arrays_reconstructed': False,
            'caller_boundary_provenance_verified': False,
            'cache_freshness_verified': False, 'complete_parent_lifecycle_verified': False,
            'model_state_resumption_supported': False, 'apply_allowed': False,
            'mutation_attempted': False, 'saved': False, 'physical_device_verified': False}


def _signature(stage):
    return _sha({'receipt': stage.as_dict(), 'loaded': stage.loaded.as_dict(),
        'loaded_expected': dict(stage.loaded.expected), 'loaded_after_load': dict(stage.loaded.after_load),
        'loaded_cache': stage.loaded.metadata.as_dict(),
        'loaded_requirements': stage.loaded.requirements.as_dict()})


class EdltTemplateModelStage:
    """Snapshot-bound model stage, with explicit cache and issuance guards.

    This object owns copied inputs only. ``validate`` checks a receipt against
    current caller facts without rerunning a model load or touching a session.
    Raw string spelling is significant, as is the inherited dirty-name set.
    """
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        if (catalog_number, firmware) != ('5055EDL', '5.5.00'):
            raise EdltError('Second model staging supports only KEYGL5 / 5055EDL / 5.5.00')
        self._source_spec = spec
        self._spec = _copy_spec(spec)
        self.specification_sha256 = _sha(_spec_document(self._spec))
        self._lifecycle = EdltLifecycle(self._spec, catalog_number=catalog_number, firmware=firmware)
        self._owner = object()

    def _check_spec(self):
        if (self._lifecycle.spec is not self._spec
                or _sha(_spec_document(self._source_spec)) != self.specification_sha256
                or _sha(_spec_document(self._spec)) != self.specification_sha256):
            raise EdltError('Specification changed since this second-model staging session began')

    def snapshot(self, values):
        """Numeric projection used by the shared, bounded raw AfterLoad helper."""
        return self._lifecycle.snapshot(values)

    def _inputs(self, raw_parameters, metadata, dirty_parameters):
        self._check_spec()
        if not isinstance(raw_parameters, Mapping) or set(raw_parameters) != set(self._spec.parameters):
            raise EdltError('Second model staging requires every raw PP value matching the specification')
        raw = dict(raw_parameters)
        if (any(type(value) is not str or len(value) > 8192
                or any(ord(c) < 32 or ord(c) == 127 for c in value) for value in raw.values())
                or sum(len(value) for value in raw.values()) > 262144):
            raise EdltError('Second model staging requires bounded raw PP strings without control characters')
        for name, value in raw.items():
            if self._spec.get(name).type not in ('string', 'sixbit') and not _NUMERIC.fullmatch(value):
                raise EdltError('Numeric raw PP requires decimal or 0x tokens separated by single spaces: ' + name)
        before = self.snapshot(raw)
        if _RawState(raw).raw() != raw:
            raise EdltError('Raw PP strings would lose token information; supply already-normalized Value strings')
        if type(metadata) is not LifecycleCache:
            raise EdltError('Second model staging requires an explicit LifecycleCache')
        cache = LifecycleCache.from_dict(metadata.as_dict())
        dirty = _dirty(dirty_parameters, self._spec.parameters)
        return raw, before, cache, dirty

    def stage(self, raw_parameters, *, metadata, dirty_parameters=()):
        """Reconstruct an unbound model from complete post-assignment values.

        A failed reconstruction never publishes a partial candidate. All inputs
        are copied before the load; neither caller values nor cache are mutated.
        """
        raw, before, cache, dirty = self._inputs(raw_parameters, metadata, dirty_parameters)
        loaded = self._lifecycle.load(before, metadata=cache)
        state = _RawState(raw, dirty)
        # Reuse only the independent raw model-load projection, never Reset's
        # constructor, reset transition, control setup or save machinery.
        EdltResetControls._raw_load(self, state, loaded)
        origin = _StageOrigin(self._owner)
        result = SecondModelLoadStage(raw, state.raw(), before, loaded.after_load,
            dirty, tuple(sorted(state.dirty)), loaded, _json(loaded.as_dict()),
            self.specification_sha256, _sha(raw), _sha(cache.as_dict()), _sha(dirty), origin)
        origin.reference = weakref.ref(result)
        origin.retained = _retained(loaded)
        origin.signature = _signature(result)
        return result

    def validate(self, stage, raw_parameters, *, metadata, dirty_parameters=()):
        """Return the intact issued stage only if all caller facts still match."""
        if (type(stage) is not SecondModelLoadStage or type(stage._origin) is not _StageOrigin
                or stage._origin.owner is not self._owner or stage._origin.reference is None
                or stage._origin.reference() is not stage):
            raise EdltError('Use an intact second-model stage issued by this staging session')
        raw, before, cache, dirty = self._inputs(raw_parameters, metadata, dirty_parameters)
        if (_sha(raw) != stage.source_sha256 or before != dict(stage.before)
                or _sha(cache.as_dict()) != stage.cache_sha256 or _sha(dirty) != stage.dirty_sha256):
            raise EdltError('Raw PP values, cache, or dirty parameters changed since model staging')
        self._lifecycle._validate_loaded(stage.loaded)
        retained = _retained(stage.loaded)
        if (len(retained) != len(stage._origin.retained)
                or any(a is not b for a, b in zip(retained, stage._origin.retained))
                or _signature(stage) != stage._origin.signature):
            raise EdltError('Second-model stage differs from its issued model or immutable receipt')
        return stage


def stage_second_model_load(spec, raw_parameters, *, metadata, dirty_parameters=()):
    """One-shot pure diagnostic stage; use the class to validate later facts."""
    return EdltTemplateModelStage(spec).stage(raw_parameters, metadata=metadata,
                                             dirty_parameters=dirty_parameters)
