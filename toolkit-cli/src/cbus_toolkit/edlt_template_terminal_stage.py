"""Retained eDLT model terminal projection, without validation UI or saving.

An intact upstream issuer is mandatory. The output is a complete numeric PP
image with configuration CRCs, not permission to apply a template or save it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from .edlt import CRC_RANGES, EdltError, _render
from .edlt_lifecycle import LifecyclePlan, _error_text
from .edlt_template_lifecycle_stage import EdltTemplateLifecycleStage
from .edlt_template_model_stage import EdltTemplateModelStage, _json, _sha
from .edlt_templates import EdltTemplateError


FORMAT = 'cbus-edlt-template-terminal-model-stage-v1'
UNEXECUTED_PHASES = (
    'active-control focus/validation and binding flush',
    'FrmBaseUnit.ValidateSerialNumber', 'ValidateSceneWidgetConfig',
    'EDLTUnit.IsValid', 'full parent Reset/BeforeChange/AfterChange controls',
    'FrmBaseUnit.SaveDialog/native host dispatch',
    'PP SAVE_TO_SOURCE', 'project file save and fresh reload',
)


class TemplateTerminalApplyRefused(EdltTemplateError):
    def __init__(self):
        super().__init__('Terminal model projection does not authorize template Apply/OK or persistence')
        self.details = {'status': 'refused', 'blockers': list(UNEXECUTED_PHASES),
            'apply_allowed': False, 'target_mutation_attempted': False,
            'saved': False, 'complete_parent_lifecycle_verified': False}


class TemplateTerminalStageError(EdltTemplateError):
    def __init__(self, message, evidence):
        import json
        super().__init__(message)
        self.details = json.loads(_json(evidence))


@dataclass(frozen=True)
class TemplateTerminalStage:
    """Immutable diagnostic result; use its issuer to check current facts."""
    source_receipt_sha256: str
    specification_sha256: str
    cache_sha256: str
    after_load: Mapping
    before_crc: Mapping
    final: Mapping
    rendered_parameters: Mapping
    crcs: Mapping
    model_plan: str
    _owner: object = field(repr=False, compare=False)

    def __post_init__(self):
        for name in ('after_load', 'before_crc', 'final', 'rendered_parameters', 'crcs'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        import json
        return {'format': FORMAT, 'status': 'terminal_model_staged',
            'unit_type': 'KEYGL5', 'catalog_number': '5055EDL', 'firmware': '5.5.00',
            'source_receipt_sha256': self.source_receipt_sha256,
            'specification_sha256': self.specification_sha256, 'cache_sha256': self.cache_sha256,
            'final_image_sha256': _sha(dict(self.final)), 'parameter_count': len(self.final),
            'after_load': json.loads(_json(dict(self.after_load))),
            'before_crc': json.loads(_json(dict(self.before_crc))),
            'final': json.loads(_json(dict(self.final))),
            'rendered_parameters': dict(self.rendered_parameters),
            'crcs': json.loads(_json(dict(self.crcs))), 'model_plan': json.loads(self.model_plan),
            'executed_phases': ['retained EdltLifecycle.prepare_save(saveDb=true,saveNw=false)',
                                'configuration CRC calculation'],
            'unexecuted_phases': list(UNEXECUTED_PHASES),
            'terminal_model_projection_passes': 1, 'terminal_crc_passes': 1,
            'model_reloaded_for_terminal_projection': False,
            'raw_spelling_scope': 'canonical decimal PP rendering; not original raw setter spelling',
            'original_raw_terminal_spelling_verified': False,
            'original_save_validation_verified': False,
            'active_control_flush_verified': False, 'caller_boundary_provenance_verified': False,
            'cache_freshness_verified': False, 'complete_parent_lifecycle_verified': False,
            'apply_allowed': False, 'target_mutation_attempted': False,
            'save_dispatched': False, 'saved': False, 'physical_device_verified': False,
            'model_state_resumption_supported': False}

    def apply(self, target=None):
        raise TemplateTerminalApplyRefused()


class EdltTemplateTerminalStage:
    """One local terminal projection bound to an existing model-stage issuer.

``current_source`` is the original TemplatePpSnapshot for a lifecycle issuer,
or complete post-assignment raw PP strings for a model-only issuer. For the
latter, pass the same inherited dirty-name facts used for model staging.
Neither a deserialized receipt nor a caller-supplied projection is accepted.
"""
    def __init__(self, issuer):
        if type(issuer) not in (EdltTemplateLifecycleStage, EdltTemplateModelStage):
            raise EdltTemplateError('Use the original lifecycle or second-model stage issuer')
        self._issuer = issuer
        self._owner = object()
        self._state = 'open'
        self._upstream = self._candidate = self._signature = self._failure = None

    @property
    def state(self): return self._state

    @property
    def candidate(self): return self._candidate if self._state == 'staged' else None

    @property
    def last_failure(self):
        import json
        return None if self._failure is None else json.loads(self._failure)

    def _validate_upstream(self, upstream, current_source, metadata, dirty_parameters):
        if type(self._issuer) is EdltTemplateLifecycleStage:
            if tuple(dirty_parameters):
                raise EdltTemplateError('Lifecycle-stage dirty facts are issued by its assignment stage')
            self._issuer.validate(upstream, current_source=current_source, metadata=metadata)
            return self._issuer._model, upstream.second_model
        self._issuer.validate(upstream, current_source, metadata=metadata,
                              dirty_parameters=dirty_parameters)
        return self._issuer, upstream

    def stage(self, upstream, *, current_source, metadata, dirty_parameters=()):
        if self._state != 'open':
            raise EdltTemplateError('Terminal stage is no longer open')
        self._state = 'staging'
        phase = 'upstream_validation'
        try:
            dirty_parameters = tuple(dirty_parameters)
            model, source = self._validate_upstream(upstream, current_source, metadata, dirty_parameters)
            phase = 'retained_before_save_and_crc'
            # Private access is restricted to the two exact issuer types above.
            # Calling EdltLifecycle.plan/apply here would reload the model.
            plan = model._lifecycle.prepare_save(source.loaded)
            phase = 'terminal_projection_validation'
            if (type(plan) is not LifecyclePlan or dict(plan.expected) != dict(source.before)
                    or dict(plan.after_load) != dict(source.after_load)
                    or plan.metadata is not source.loaded.metadata
                    or plan.requirements is not source.loaded.requirements):
                raise EdltError('Terminal projection differs from the issued retained model')
            final = {**plan.expected, **plan.changes}
            if (set(final) != set(source.before) or set(plan.before_save) != set(final)
                    or model.snapshot(final) != final or model.snapshot(plan.before_save) != dict(plan.before_save)):
                raise EdltError('Terminal projection must contain the complete valid PP image')
            rendered = {name: _render(value) for name, value in final.items()}
            if model.snapshot(rendered) != final:
                raise EdltError('Terminal PP rendering is not lossless')
            self._validate_upstream(upstream, current_source, metadata, dirty_parameters)
            candidate = TemplateTerminalStage(_sha(upstream.as_dict()), source.specification_sha256,
                source.cache_sha256, source.after_load, plan.before_save, final, rendered,
                {name: final[name] for name in CRC_RANGES}, _json(plan.as_dict()), self._owner)
            self._signature = _sha(candidate.as_dict())
            self._upstream, self._candidate, self._state = upstream, candidate, 'staged'
            return candidate
        except BaseException as error:
            self._candidate = self._upstream = self._signature = None
            self._state = 'failed'
            evidence = {'status': 'failed', 'phase': phase, 'error': _error_text(error),
                'candidate_published': False, 'local_terminal_candidate_discarded': True,
                'target_mutation_attempted': False, 'saved': False, 'automatic_retries': 0}
            self._failure = _json(evidence)
            if not isinstance(error, Exception):
                try:
                    error.edlt_template_terminal_stage_evidence = self.last_failure
                except BaseException:
                    pass  # last_failure remains available on the issuer.
                raise
            raise TemplateTerminalStageError('Terminal model staging failed: ' + _error_text(error), evidence) from error

    def validate(self, candidate, *, current_source, metadata, dirty_parameters=()):
        if (self._state != 'staged' or type(candidate) is not TemplateTerminalStage
                or candidate is not self._candidate or candidate._owner is not self._owner):
            raise EdltTemplateError('Use an intact active terminal stage returned by this issuer')
        self._validate_upstream(self._upstream, current_source, metadata, tuple(dirty_parameters))
        if (_sha(self._upstream.as_dict()) != candidate.source_receipt_sha256
                or _sha(candidate.as_dict()) != self._signature):
            raise EdltTemplateError('Terminal stage differs from its issued projection')
        return candidate

    def cancel(self):
        if self._state == 'staging':
            raise EdltTemplateError('Cannot cancel while terminal staging is in progress')
        self._candidate = self._upstream = self._signature = None
        self._state = 'cancelled'
        return {'status': 'cancelled', 'local_terminal_candidate_discarded': True,
            'upstream_issuer_cancelled': False, 'original_cancel_replayed': False,
            'target_mutation_attempted': False, 'saved': False}

    def apply(self, target=None):
        raise TemplateTerminalApplyRefused()
