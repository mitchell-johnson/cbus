"""Atomic local staging of the original template PP assignment loop.

Inputs are explicit PPAttribute.Values token arrays at the post-BeforeChange
boundary. This models raw setters, including retained tails and dirty flags;
it never calls the parent controls, a PP session, or a persistence operation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import unicodedata
from types import MappingProxyType

from .edlt_templates import (EdltTemplate, EdltTemplateApplyRefused,
                             EdltTemplateError, _assignment_value)


_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]*\Z')
_MAX_TOKENS = 65536
_MAX_TEXT = 262144
_BOUNDARY = 'after_BeforeChangePpAttributes_before_XML_assignments'


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _error_text(error):
    try:
        return str(error)
    except BaseException:
        return '<' + type(error).__name__ + ': error text unavailable>'


def _join(tokens):
    # PPAttribute.Value uses StringBuilder.Length when adding separators.
    result = ''
    for token in tokens:
        if result:
            result += ' '
        result += token
    return result


def _normalize(token):
    if not token.startswith('$'):
        visible = ''.join(c for c in token
                          if unicodedata.category(c) not in ('Cc', 'Cf', 'Mn', 'Mc', 'Me'))
        if visible.startswith('$'):
            raise EdltTemplateError('Culture-sensitive dollar-token prefix is outside the staged profile')
    if token == '0xffffffff':
        return '0xff'
    if token.startswith('$x'):
        return '0' + token[1:]
    if token.startswith('$'):
        if (not token.isascii() or 'i' in token
                or any(ord(char) < 32 or ord(char) == 127 for char in token)):
            raise EdltTemplateError('Culture-sensitive dollar-token casing requires an explicit original culture')
        return '0x' + token[1:].upper()
    return token


@dataclass(frozen=True)
class TemplatePpSnapshot:
    """Exact, ordered local PP tokens; no lossy reconstruction from Value."""

    parameters: tuple[tuple[str, tuple[str, ...], bool], ...]
    initializing: bool = False

    def __post_init__(self):
        if type(self.initializing) is not bool:
            raise EdltTemplateError('Initializing state must be Boolean')
        if not isinstance(self.parameters, (list, tuple)) or len(self.parameters) > 4096:
            raise EdltTemplateError('Supply a bounded ordered PP token collection')
        rows, seen, count, text_size = [], set(), 0, 0
        for row in self.parameters:
            if not isinstance(row, (list, tuple)) or len(row) != 3:
                raise EdltTemplateError('PP rows require name, exact tokens, and dirty Boolean')
            name, tokens, dirty = row
            if (type(name) is not str or not _NAME.fullmatch(name) or name in seen
                    or not isinstance(tokens, (tuple, list)) or type(dirty) is not bool):
                raise EdltTemplateError('PP names must be unique; tokens ordered; dirty state Boolean')
            if any(type(token) is not str for token in tokens):
                raise EdltTemplateError('Null/non-string PP tokens are outside the staged profile')
            count += len(tokens)
            text_size += sum(len(token) for token in tokens)
            if count > _MAX_TOKENS or text_size > _MAX_TEXT:
                raise EdltTemplateError('PP snapshot exceeds the token/text bound')
            seen.add(name)
            rows.append((name, tuple(tokens), dirty))
        object.__setattr__(self, 'parameters', tuple(rows))

    @property
    def raw(self):
        return MappingProxyType({name: _join(tokens) for name, tokens, _ in self.parameters})

    @property
    def fingerprint(self):
        return _digest(self.as_dict())

    def as_dict(self):
        return {'format': 'cbus-edlt-template-pp-snapshot-v1',
                'parameters': [{'name': name, 'tokens': list(tokens), 'dirty': dirty,
                                'raw': _join(tokens)} for name, tokens, dirty in self.parameters],
                'initializing': self.initializing}


@dataclass(frozen=True)
class TemplateAssignmentStep:
    child_index: int
    name: str
    input_value: str
    setter_value: str
    disposition: str
    before_tokens: tuple[str, ...] | None
    after_tokens: tuple[str, ...] | None
    before_dirty: bool | None
    after_dirty: bool | None

    def as_dict(self):
        return {'child_index': self.child_index, 'name': self.name, 'input_value': self.input_value,
                'setter_value': self.setter_value, 'disposition': self.disposition,
                'before_tokens': None if self.before_tokens is None else list(self.before_tokens),
                'after_tokens': None if self.after_tokens is None else list(self.after_tokens),
                'before_dirty': self.before_dirty, 'after_dirty': self.after_dirty}


@dataclass(frozen=True)
class TemplateAssignmentStage:
    source: TemplatePpSnapshot
    after: TemplatePpSnapshot
    template_sha256: str
    steps: tuple[TemplateAssignmentStep, ...]
    _owner: object = field(repr=False, compare=False)

    def as_dict(self):
        return {'format': 'cbus-edlt-template-assignment-stage-v1', 'status': 'locally_staged',
                'source_boundary': _BOUNDARY, 'source_boundary_observed_by_this_API': False,
                'source_sha256': self.source.fingerprint, 'after_sha256': self.after.fingerprint,
                'template_sha256': self.template_sha256,
                'source': self.source.as_dict(), 'after': self.after.as_dict(),
                'steps': [step.as_dict() for step in self.steps],
                'local_candidate_published_atomically': True,
                'raw_setter_projection_complete': True, 'external_callbacks_executed': False,
                'culture_profile': 'culture-invariant admitted dollar-token subset',
                'parent_rebind_executed': False, 'native_parameter_validation_performed': False,
                'target_mutation_attempted': False, 'saved': False, 'apply_allowed': False,
                'remaining_steps': ['prove source Reset/PopulateWidgetPanels/BeforeChange context',
                                    'AfterLoadPPData and all parent rebind callbacks',
                                    'separate validated Apply/OK persistence transaction']}

    def apply(self, target=None):
        raise EdltTemplateApplyRefused()


class TemplateStagingError(EdltTemplateError):
    def __init__(self, cause, evidence):
        self.cause = cause
        self.details = evidence
        super().__init__('Template assignment staging failed without publishing a candidate: ' + _error_text(cause))


class EdltTemplateAssignmentTransaction:
    """Single-use local transaction with discard-on-failure/cancel semantics.

    This intentionally avoids the original partial editor writes. No user
    callbacks run here. In particular, BindingList events are not projected as
    successful control bindings. A successful stage only publishes a local
    immutable assignment candidate, never a unit edit.
    """

    def __init__(self, source):
        if type(source) is not TemplatePpSnapshot:
            raise EdltTemplateError('Supply an exact TemplatePpSnapshot')
        if source.initializing:
            raise EdltTemplateError('Cannot begin template staging in an already-initializing context')
        self._source = TemplatePpSnapshot(source.parameters, source.initializing)
        self._source_sha256 = self._source.fingerprint
        self._state = 'open'
        self._candidate = None
        self._owner = object()
        self._failure_json = None
        self._candidate_sha256 = None
        self._published_after = None

    @property
    def source(self):
        return self._source

    @property
    def state(self):
        return self._state

    @property
    def candidate(self):
        return self._candidate if self._state == 'staged' else None

    @property
    def last_failure(self):
        return None if self._failure_json is None else json.loads(self._failure_json)

    @staticmethod
    def _set_value(target, value):
        for index, token in enumerate(value.split(' ')):
            token = _normalize(token)
            if index < len(target):
                target[index] = token
            else:
                target.append(token)

    def stage(self, template):
        if self._state != 'open':
            raise EdltTemplateError('Use a new transaction after staging, failure or cancellation')
        if type(template) is not EdltTemplate:
            raise EdltTemplateError('Parse an EdltTemplate before staging')
        if self.source.fingerprint != self._source_sha256:
            raise EdltTemplateError('Owned source snapshot changed after transaction creation')
        parameters = {name: [list(tokens), dirty] for name, tokens, dirty in self.source.parameters}
        steps, current_index, initializing = [], None, False
        self._state = 'staging'
        try:
            for current_index, (name, raw) in enumerate(template.fields):
                # Source conversion is before bInitialiseMode=true and before
                # name lookup, even when Application is unknown to the model.
                value = _assignment_value(name, raw)
                initializing = True
                if name not in parameters:
                    steps.append(TemplateAssignmentStep(current_index, name, raw, value,
                                                         'unknown_attribute', None, None, None, None))
                else:
                    target, dirty = parameters[name]
                    before = tuple(target)
                    disposition = 'unchanged'
                    if _join(target) != value:
                        self._set_value(target, value)
                        # The source explicitly marks dirty even if normalized
                        # tokens equal the previous ones or dirty was true.
                        parameters[name][1] = True
                        disposition = 'assigned'
                    steps.append(TemplateAssignmentStep(current_index, name, raw, value, disposition,
                                                         before, tuple(target), dirty, parameters[name][1]))
                initializing = False
            after = TemplatePpSnapshot(tuple((name, tuple(tokens), dirty)
                                             for name, (tokens, dirty) in parameters.items()), False)
            result = TemplateAssignmentStage(self.source, after,
                hashlib.sha256(template.to_xml().encode('utf-8')).hexdigest(), tuple(steps), self._owner)
            # The sole publication point: validation or setter failure has no
            # observable partially staged candidate.
            signature = _digest(result.as_dict())
            self._candidate_sha256 = signature
            self._published_after = after
            self._candidate = result
            self._state = 'staged'
            return result
        except BaseException as error:
            # Retire the transaction before exporting diagnostics. A broken
            # exception formatter must not strand it in an active state.
            self._candidate = None
            self._candidate_sha256 = None
            self._published_after = None
            self._state = 'failed'
            evidence = {'format': 'cbus-edlt-template-staging-failure-v1', 'status': 'failed',
                        'child_index': current_index, 'completed_child_count': len(steps),
                        'failure_type': type(error).__name__, 'failure': _error_text(error),
                        'source_sha256': self._source_sha256,
                        'discarded_working_initializing': initializing,
                        'candidate_published': False, 'source_preserved': True,
                        'target_mutation_attempted': False, 'saved': False,
                        'steps': [step.as_dict() for step in steps]}
            self._failure_json = _json(evidence)
            if isinstance(error, Exception):
                raise TemplateStagingError(error, evidence) from error
            try:
                error.edlt_template_staging_evidence = evidence
            except BaseException:
                pass
            raise

    def validate(self, candidate, *, current_source):
        if (self._state != 'staged' or candidate is not self._candidate
                or type(candidate) is not TemplateAssignmentStage or candidate._owner is not self._owner):
            raise EdltTemplateError('Use the intact active candidate issued by this transaction')
        if type(current_source) is not TemplatePpSnapshot or current_source != self.source:
            raise EdltTemplateError('Source PP tokens, order, dirty flags or initialize state changed')
        if (self.source.fingerprint != self._source_sha256 or candidate.source is not self.source
                or candidate.after is not self._published_after
                or _digest(candidate.as_dict()) != self._candidate_sha256):
            raise EdltTemplateError('Assignment stage differs from its issued immutable receipt')
        return candidate

    def cancel(self):
        if self._state == 'staging':
            raise EdltTemplateError('Cannot cancel while an internal staging call is active')
        self._candidate = None
        self._candidate_sha256 = None
        self._published_after = None
        self._state = 'cancelled'
        return {'format': 'cbus-edlt-template-staging-cancel-v1', 'status': 'cancelled',
                'source_sha256': self._source_sha256, 'local_candidate_discarded': True,
                'source_preserved': True, 'original_cancel_replayed': False,
                'target_mutation_attempted': False, 'saved': False}

    def apply(self, target=None):
        raise EdltTemplateApplyRefused()
