"""Atomic local assignment + unbound model stage at an explicit PP boundary.

The caller owns and supplies the post-BeforeChange PP snapshot. This adapter
does not establish Reset, PopulateWidgetPanels, BeforeChange or later control
callbacks from that snapshot and cannot be used as a parent Apply operation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from .edlt_templates import EdltTemplate, EdltTemplateError
from .edlt_template_staging import (
    EdltTemplateAssignmentTransaction, TemplateAssignmentStage, TemplatePpSnapshot,
)
from .edlt_template_model_stage import EdltTemplateModelStage, SecondModelLoadStage


APPLY_BLOCKERS = (
    'The supplied post-BeforeChange PP boundary does not prove the preceding '
    'ResetUnit(true), PopulateWidgetPanels, or BeforeChangePpAttributes context.',
    'SetupForm, recursive control setup and application population, binding reset, '
    'navigation/selected-widget/page refresh, and redraw callbacks are not executed.',
    'Original swallowed callback failures, cancellation and the later single '
    'Apply/OK persistence transaction are not accepted by this local stage.',
)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_json(value).encode('ascii')).hexdigest()


def _error_text(error):
    try:
        return str(error)[:1024]
    except BaseException:
        return '<unprintable ' + type(error).__name__ + '>'


class TemplateLifecycleStageError(EdltTemplateError):
    def __init__(self, cause, evidence):
        self.cause = cause
        self._evidence = _json(evidence)
        super().__init__('Template lifecycle staging failed without publishing a candidate: ' + _error_text(cause))

    @property
    def details(self):
        return json.loads(self._evidence)


class TemplateLifecycleApplyRefused(EdltTemplateError):
    def __init__(self):
        self.details = {'status': 'refused', 'apply_allowed': False,
                        'blockers': list(APPLY_BLOCKERS), 'target_mutation_attempted': False,
                        'saved': False, 'physical_device_verified': False}
        super().__init__('eDLT template Apply is unavailable: ' + ' '.join(APPLY_BLOCKERS))


@dataclass(frozen=True)
class TemplateLifecycleStage:
    assignment: TemplateAssignmentStage
    second_model: SecondModelLoadStage
    _owner: object = field(repr=False, compare=False)

    @property
    def source(self):
        return self.assignment.source

    def as_dict(self):
        return {'format': 'cbus-edlt-template-lifecycle-stage-v1', 'status': 'locally_staged',
            'source_boundary': 'after_BeforeChangePpAttributes_before_XML_assignments',
            'source_boundary_observed_by_this_API': False,
            'source_sha256': self.source.fingerprint,
            'template_sha256': self.assignment.template_sha256,
            'specification_sha256': self.second_model.specification_sha256,
            'cache_sha256': self.second_model.cache_sha256,
            'assignment': self.assignment.as_dict(), 'second_model': self.second_model.as_dict(),
            'published_phases': ['ordered PP assignments', 'unbound second AfterLoadPPData model'],
            'local_candidate_published_atomically': True,
            'raw_to_model_seam_verified': True,
            'complete_parent_lifecycle_verified': False,
            'original_cancel_replayed': False, 'apply_allowed': False,
            'target_mutation_attempted': False, 'saved': False, 'physical_device_verified': False,
            'blockers': list(APPLY_BLOCKERS)}

    def apply(self, target=None):
        raise TemplateLifecycleApplyRefused()


class EdltTemplateLifecycleStage:
    """Single-use local composition. Failure and cancel discard its candidate."""
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self._model = EdltTemplateModelStage(spec, catalog_number=catalog_number, firmware=firmware)
        self._owner = object()
        self._state = 'open'
        self._candidate = None
        self._assignment = None
        self._signature = None
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

    def stage(self, template, *, source, metadata):
        if self._state != 'open':
            raise EdltTemplateError('Use a new lifecycle stage after staging, failure or cancellation')
        if type(template) is not EdltTemplate or type(source) is not TemplatePpSnapshot:
            raise EdltTemplateError('Supply an EdltTemplate and an exact TemplatePpSnapshot')
        if template.firmware != '5.5.00':
            raise EdltTemplateError('Combined model staging requires template firmware 5.5.00; '
                                    'the original importer did not enforce this safety restriction')
        transaction = EdltTemplateAssignmentTransaction(source)
        self._assignment = transaction
        self._state = 'staging'
        phase = 'ordered_assignments'
        try:
            assignment = transaction.stage(template)
            phase = 'raw_to_model_seam'
            raw = assignment.after.raw
            # Value cannot reveal leading empty elements, empty arrays or spaces
            # embedded inside an individual Values entry. Reject that lossy
            # bridge instead of pretending the model consumed those exact arrays.
            for name, tokens, _dirty in assignment.after.parameters:
                if tuple(raw[name].split(' ')) != tokens:
                    raise EdltTemplateError('Post-assignment token array cannot cross the raw model boundary: ' + name)
            dirty = tuple(name for name, _tokens, dirty in assignment.after.parameters if dirty)
            phase = 'second_model_load'
            model = self._model.stage(raw, metadata=metadata, dirty_parameters=dirty)
            candidate = TemplateLifecycleStage(assignment, model, self._owner)
            self._signature = _digest(candidate.as_dict())
            self._candidate = candidate
            self._state = 'staged'
            return candidate
        except BaseException as error:
            failure = {'format': 'cbus-edlt-template-lifecycle-stage-failure-v1',
                'status': 'failed', 'phase': phase, 'error_type': type(error).__name__,
                'error': _error_text(error), 'source_sha256': source.fingerprint,
                'assignment_failure': transaction.last_failure,
                'candidate_published': False, 'local_assignment_discarded': True,
                'source_preserved': True, 'target_mutation_attempted': False, 'saved': False}
            # Assignment stage itself discards working data before propagating
            # its exception. Successful local assignment candidates are also
            # cancelled when the raw seam or second model cannot be established.
            transaction.cancel()
            self._candidate = None
            self._signature = None
            self._failure = _json(failure)
            self._state = 'failed'
            if isinstance(error, Exception):
                raise TemplateLifecycleStageError(error, failure) from error
            try:
                error.edlt_template_lifecycle_stage_evidence = failure
            except BaseException:
                pass
            raise

    def validate(self, candidate, *, current_source, metadata):
        if (self._state != 'staged' or candidate is not self._candidate
                or type(candidate) is not TemplateLifecycleStage or candidate._owner is not self._owner):
            raise EdltTemplateError('Use the intact active lifecycle candidate issued by this staging session')
        self._assignment.validate(candidate.assignment, current_source=current_source)
        dirty = tuple(name for name, _tokens, dirty in candidate.assignment.after.parameters if dirty)
        self._model.validate(candidate.second_model, candidate.assignment.after.raw,
                             metadata=metadata, dirty_parameters=dirty)
        if _digest(candidate.as_dict()) != self._signature:
            raise EdltTemplateError('Lifecycle candidate differs from its issued assignment or model receipt')
        return candidate

    def cancel(self):
        if self._state == 'staging':
            raise EdltTemplateError('Cannot cancel during an internal lifecycle staging call')
        source_sha256 = None
        if self._assignment is not None:
            source_sha256 = self._assignment.source.fingerprint
            self._assignment.cancel()
        self._candidate = None
        self._signature = None
        self._state = 'cancelled'
        return {'format': 'cbus-edlt-template-lifecycle-stage-cancel-v1', 'status': 'cancelled',
                'source_sha256': source_sha256, 'local_candidate_discarded': True,
                'source_preserved': True, 'original_cancel_replayed': False,
                'target_mutation_attempted': False, 'saved': False}

    def apply(self, target=None):
        # Refuse before dereferencing target, even for an otherwise valid stage.
        raise TemplateLifecycleApplyRefused()
