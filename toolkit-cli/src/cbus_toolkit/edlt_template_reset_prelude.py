"""Issue exact bounded Reset provenance before template preamble callbacks.

This local stage stops after Reset's Time/Date insertion. The later template
PopulateWidgetPanels and BeforeChangePpAttributes callbacks are unresolved;
an after-reset snapshot is not an attested post-BeforeChange assignment source.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from types import MappingProxyType
import weakref

from .edlt import EdltError
from .edlt_application_cache import ApplicationCache
from .edlt_lifecycle import ResetEdlt, _LoadedOrigin
from .edlt_reset import EdltResetControls, ResetPhase, _RawState, _EXCLUDED, _validate_context
from .edlt_template_model_stage import _copy_spec, _spec_document, _sha, _retained
from .edlt_template_staging import TemplatePpSnapshot
from .edlt_templates import EdltTemplateError


_BOUNDARY = 'after_bounded_ResetUnit_controls_before_template_PopulateWidgetPanels'
UNRESOLVED_CALLBACKS = (
    'PopulateWidgetPanels: dispose old panels, construct and bind replacement panels, '
    'populate applications, show widget and resume drawing',
    'BeforeChangePpAttributes: stop redraw timer and set seven radio controls; '
    'retain every notification and PP mutation',
    'Capture caught binding/setup errors and OnFormClosed outcomes; normal method '
    'return is not successful-control attestation',
)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def _text(error):
    try:
        return str(error)[:1024]
    except BaseException:
        return '<unprintable ' + type(error).__name__ + '>'


class TemplateResetPreludeError(EdltTemplateError):
    def __init__(self, cause, details):
        self.cause = cause
        self._details = _json(details)
        super().__init__('Template Reset prelude failed without publishing a candidate: ' + _text(cause))

    @property
    def details(self):
        return json.loads(self._details)


class TemplateResetPreludeApplyRefused(EdltTemplateError):
    def __init__(self):
        self.details = {'status': 'refused', 'apply_allowed': False,
            'source_boundary': _BOUNDARY, 'assignment_source_attested': False,
            'unresolved_callbacks': list(UNRESOLVED_CALLBACKS),
            'target_mutation_attempted': False, 'saved': False, 'physical_device_verified': False}
        super().__init__('Reset prelude cannot Apply or attest the later template assignment boundary')


class _PreludeOrigin:
    def __init__(self, owner):
        self.owner = owner
        self.reference = None
        self.signature = None
        self.retained = ()


@dataclass(frozen=True)
class TemplateResetPrelude:
    source: TemplatePpSnapshot
    after_reset: TemplatePpSnapshot
    reset: ResetEdlt
    phases: object
    metadata: ApplicationCache
    active_tab: str
    binding_variant: str
    specification_sha256: str
    cache_sha256: str
    context_sha256: str
    _origin: _PreludeOrigin = field(repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'phases', MappingProxyType(dict(self.phases)))

    def as_dict(self):
        return {'format': 'cbus-edlt-template-reset-prelude-v1', 'status': 'reset_prelude_staged',
            'unit_type': 'KEYGL5', 'catalog_number': '5055EDL', 'firmware': '5.5.00',
            'source_sha256': self.source.fingerprint, 'after_reset_sha256': self.after_reset.fingerprint,
            'specification_sha256': self.specification_sha256, 'cache_sha256': self.cache_sha256,
            'context_sha256': self.context_sha256, 'active_tab': self.active_tab,
            'binding_variant': self.binding_variant, 'source': self.source.as_dict(),
            'after_reset': self.after_reset.as_dict(),
            'phases': {name: phase.as_dict() for name, phase in self.phases.items()},
            'reset_model': self.reset.as_dict(), 'output_boundary': _BOUNDARY,
            'input_scope': 'caller PP snapshot before bounded partial-dialog initialization and Reset; '
            'not an arbitrary already-loaded Toolkit history',
            'initialization_context': 'caller source is non-initializing; the isolated model input '
            'starts initializing=true before its first AfterLoadPPData',
            'computed_reset_postconditions_verified': True,
            'reset_result_boolean_used': False,
            'original_reset_result_boolean_observed': False,
            'model_load_count': 2, 'terminal_before_save_performed': False,
            'terminal_crc_performed': False, 'third_model_load_performed': False,
            'template_assignments_performed': False, 'post_reset_callbacks_executed': False,
            'callback_obligations_status': 'unresolved',
            'unresolved_callbacks': list(UNRESOLVED_CALLBACKS),
            'assignment_source_attested': False, 'automatic_assignment_chain_available': False,
            'cache_freshness_verified': False, 'original_form_executed': False,
            'full_form_initialization_verified': False, 'apply_allowed': False,
            'target_mutation_attempted': False, 'saved': False, 'physical_device_verified': False}

    def apply(self, target=None):
        raise TemplateResetPreludeApplyRefused()


def _content(candidate):
    reset = candidate.reset
    return _sha({'receipt': candidate.as_dict(), 'expected': dict(reset.expected),
        'after_controls': dict(reset.after_controls),
        'widgets': [widget.as_dict() for widget in reset.widgets],
        'context_raw': dict(reset.context.expected_raw),
        'context_dirty': reset.context.dirty_parameters,
        'context_tab': reset.context.active_tab, 'context_binding': reset.context.binding_variant,
        'context_cache': reset.context.metadata.as_dict(),
        'loaded': [{'expected': dict(loaded.expected), 'after_load': dict(loaded.after_load),
                    'model': loaded.as_dict(), 'cache': loaded.metadata.as_dict(),
                    'requirements': loaded.requirements.as_dict()}
                   for loaded in (reset.base, reset.fresh)]})


def _objects(candidate):
    reset = candidate.reset
    return (candidate.source, candidate.after_reset, candidate.metadata,
            candidate.phases, *candidate.phases.values(), reset, reset.context,
            reset.widgets, *reset.widgets, reset.raw_phases, *reset.raw_phases.values(),
            *_retained(reset.base), *_retained(reset.fresh))


class EdltTemplateResetPrelude:
    """Single-use, source-bound Reset stage; no callbacks, assignments or saves."""
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        if (catalog_number, firmware) != ('5055EDL', '5.5.00'):
            raise EdltError('Template Reset prelude supports only KEYGL5 / 5055EDL / 5.5.00')
        self._source_spec = spec
        self._spec = _copy_spec(spec)
        self.specification_sha256 = _sha(_spec_document(self._spec))
        self._reset = EdltResetControls(self._spec, catalog_number=catalog_number, firmware=firmware)
        self._lifecycle = self._reset.lifecycle
        self._owner = object()
        self._state = 'open'
        self._candidate = None
        self._failure = None

    @property
    def state(self):
        return self._state

    @property
    def candidate(self):
        return self._candidate if self._state == 'staged' else None

    @property
    def last_failure(self):
        return None if self._failure is None else json.loads(self._failure)

    def _inputs(self, source, metadata, active_tab, binding_variant):
        if (_sha(_spec_document(self._source_spec)) != self.specification_sha256
                or _sha(_spec_document(self._spec)) != self.specification_sha256
                or self._reset.spec is not self._spec or self._reset.lifecycle is not self._lifecycle
                or self._lifecycle.spec is not self._spec):
            raise EdltError('Specification changed since the Reset prelude session began')
        if type(source) is not TemplatePpSnapshot or source.initializing:
            raise EdltError('Reset prelude requires an exact non-initializing TemplatePpSnapshot')
        if tuple(name for name, _tokens, _dirty in source.parameters) != tuple(self._spec.parameters):
            raise EdltError('Reset prelude requires the complete PP collection in specification order')
        copied = TemplatePpSnapshot(source.parameters, source.initializing)
        raw = self._reset.raw_input(copied.raw)
        state = _RawState(raw)
        if any(tuple(state.tokens[name]) != tokens for name, tokens, _dirty in copied.parameters):
            raise EdltError('Exact source token arrays cannot cross the raw Reset boundary')
        if type(metadata) is not ApplicationCache:
            raise EdltError('Reset prelude requires an explicit ApplicationCache')
        cache = ApplicationCache.from_dict(metadata.as_dict())
        dirty = tuple(name for name, _tokens, dirty in copied.parameters if dirty)
        context = {'active_tab': active_tab, 'binding_variant': binding_variant,
                   'dirty_parameters': sorted(dirty)}
        return copied, raw, dirty, cache, _sha(context)

    def _postconditions(self, reset):
        lifecycle = self._reset.lifecycle
        if (type(reset) is not ResetEdlt or type(reset._origin) is not _LoadedOrigin
                or reset._origin.owner is not lifecycle._loaded_owner
                or reset._origin.reference is None or reset._origin.reference() is not reset):
            raise EdltError('Reset prelude requires the intact ResetEdlt issued by its own engine')
        lifecycle._validate_loaded(reset.base)
        lifecycle._validate_loaded(reset.fresh)
        _validate_context(lifecycle, reset.base, reset.context)
        phases = reset.raw_phases
        needed = ('component-before-change', 'component-reset-defaults', 'component-zero-byte1',
                  'component-after-change', 'after-reset')
        if any(name not in phases or type(phases[name]) is not ResetPhase for name in needed):
            raise EdltError('Reset prelude is missing an exact raw component phase')
        defaults = self._reset.snapshot(_RawState(self._reset.defaults).raw())
        default_phase = self._reset.snapshot(phases['component-reset-defaults'].raw)
        before = phases['component-before-change']
        for name in self._spec.parameters:
            if name in _EXCLUDED:
                if phases['component-reset-defaults'].tokens[name] != before.tokens[name]:
                    raise EdltError('Reset changed an excluded default parameter: ' + name)
            elif default_phase[name] != defaults[name]:
                raise EdltError('Reset default postcondition differs: ' + name)
        if (phases['component-reset-defaults'].initializing is not True
                or phases['component-zero-byte1'].initializing is not True):
            raise EdltError('Reset default and byte-one phases require initializing=true')
        if any(phases['component-zero-byte1'].raw[f'Widget{i}WidgetByteValue1'] != '0x0'
               for i in range(1, 22)):
            raise EdltError('Reset did not clear all 21 old widget byte-one values')
        if any(widget.stored_type != 0 for widget in reset.fresh.widgets):
            raise EdltError('Reset fresh graph must contain 21 Blank models')
        final = phases['after-reset']
        if final.initializing or self._reset.snapshot(final.raw) != dict(reset.after_controls):
            raise EdltError('Reset after-reset raw state differs from the issued model')
        if (final.raw['Widget10WidgetType'], final.raw['Widget10RestoreLevel'],
                final.raw['Widget10WidgetByteValue1']) != ('0xA', '0x0', '0x2'):
            raise EdltError('Reset did not insert the exact Widget10 Time/Date values')
        if (len(reset.widgets) != 21 or reset.widgets[9].model_family != 'TimeAndDateData'
                or reset.widgets[9].stored_type != 10
                or any(a is not b for i, (a, b) in enumerate(zip(reset.widgets, reset.fresh.widgets)) if i != 9)):
            raise EdltError('Reset post-control graph has unverified widget replacements')
        return final

    def stage(self, source, *, metadata, active_tab, binding_variant):
        if self._state != 'open':
            raise EdltError('Use a new Reset prelude after staging, failure or cancellation')
        self._state = 'staging'
        phase = 'input_validation'
        try:
            source, raw, dirty, cache, context_hash = self._inputs(source, metadata, active_tab, binding_variant)
            phase = 'bounded_reset_preparation'
            _raw, _dirty, issued_cache, reset = self._reset.prepare_unit_reset(raw, metadata=cache,
                active_tab=active_tab, binding_variant=binding_variant, dirty_parameters=dirty)
            phase = 'reset_postconditions'
            if (_raw != raw or _dirty != tuple(sorted(dirty))
                    or issued_cache.as_dict() != cache.as_dict()
                    or dict(reset.expected) != self._reset.snapshot(raw)
                    or dict(reset.context.expected_raw) != raw
                    or reset.context.dirty_parameters != tuple(sorted(dirty))
                    or reset.context.metadata is not issued_cache
                    or (reset.context.active_tab, reset.context.binding_variant) != (active_tab, binding_variant)):
                raise EdltError('Reset preparation differs from the supplied source/cache/control context')
            final = self._postconditions(reset)
            after_reset = TemplatePpSnapshot(tuple((name, final.tokens[name], name in final.dirty_parameters)
                                                  for name in self._spec.parameters), final.initializing)
            origin = _PreludeOrigin(self._owner)
            candidate = TemplateResetPrelude(source, after_reset, reset, reset.raw_phases,
                issued_cache, active_tab, binding_variant, self.specification_sha256,
                _sha(issued_cache.as_dict()), context_hash, origin)
            origin.reference = weakref.ref(candidate)
            origin.retained = _objects(candidate)
            origin.signature = _content(candidate)
            self._candidate = candidate
            self._state = 'staged'
            return candidate
        except BaseException as error:
            failure = {'format': 'cbus-edlt-template-reset-prelude-failure-v1',
                'status': 'failed', 'phase': phase, 'error_type': type(error).__name__, 'error': _text(error),
                'candidate_published': False, 'source_preserved': True,
                'target_mutation_attempted': False, 'saved': False}
            self._candidate = None
            self._failure = _json(failure)
            self._state = 'failed'
            if isinstance(error, Exception):
                raise TemplateResetPreludeError(error, failure) from error
            try:
                error.edlt_template_reset_prelude_evidence = failure
            except BaseException:
                pass
            raise

    def validate(self, candidate, *, current_source, metadata, active_tab, binding_variant):
        if (self._state != 'staged' or candidate is not self._candidate
                or type(candidate) is not TemplateResetPrelude or type(candidate._origin) is not _PreludeOrigin
                or candidate._origin.owner is not self._owner or candidate._origin.reference is None
                or candidate._origin.reference() is not candidate):
            raise EdltError('Use the intact active Reset prelude issued by this staging session')
        source, _raw, _dirty, cache, context_hash = self._inputs(current_source, metadata, active_tab, binding_variant)
        if (source != candidate.source or _sha(cache.as_dict()) != candidate.cache_sha256
                or context_hash != candidate.context_sha256):
            raise EdltError('Source, cache or control context changed since Reset prelude staging')
        objects = _objects(candidate)
        if (len(objects) != len(candidate._origin.retained)
                or any(a is not b for a, b in zip(objects, candidate._origin.retained))
                or _content(candidate) != candidate._origin.signature):
            raise EdltError('Reset prelude differs from its issued phases or retained graph')
        self._postconditions(candidate.reset)
        return candidate

    def cancel(self):
        if self._state == 'staging':
            raise EdltError('Cannot cancel during an internal Reset prelude call')
        self._candidate = None
        self._state = 'cancelled'
        return {'status': 'cancelled', 'local_candidate_discarded': True,
                'source_preserved': True, 'original_cancel_replayed': False,
                'target_mutation_attempted': False, 'saved': False}

    def apply(self, target=None):
        raise TemplateResetPreludeApplyRefused()
