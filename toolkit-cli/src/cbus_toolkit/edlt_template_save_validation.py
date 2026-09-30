"""Ordered, source-derived eDLT Save predicates on an intact unbound model.

This stage substitutes explicit frozen lookup facts only where original getters
have no writes or add requests. It never runs controls, dialogs, BeforeSave,
native dispatch or persistence. An accepted projection cannot authorize Apply.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json

from .edlt import _field
from .edlt_corridor import _GROUP_FAMILIES
from .edlt_lifecycle import _error_text
from .edlt_template_lifecycle_stage import EdltTemplateLifecycleStage
from .edlt_template_model_stage import EdltTemplateModelStage, _json, _sha
from .edlt_template_save_predicates import (
    KeyGroup, check_scene_widget_variants, validate_serial_text, validate_unit,
)
from .edlt_templates import EdltTemplateError


FORMAT = 'cbus-edlt-template-save-validation-stage-v1'
UNEXECUTED_PHASES = (
    'active-control focus validation and binding flush',
    'original WinForms serial, Scene-widget and unit validator execution',
    'SceneCycle BindingList event suppression/rebuild',
    'lookup add requests, getter setters and property notifications',
    'validation dialogs and help callbacks',
    'complete parent Reset/BeforeChange/AfterChange controls',
    'BeforeSavePPData and CRC generation',
    'SaveDialog/native host callback and save acknowledgement',
    'PP SAVE_TO_SOURCE and project save with fresh reload',
)


@dataclass(frozen=True)
class ValidationGroupName:
    application: int
    group: int
    tag_name: str | None


@dataclass(frozen=True)
class ValidationDynamicVariant:
    name: str | None
    image_present: bool


@dataclass(frozen=True)
class ValidationLevel:
    application: int
    group: int
    level: int
    variants: tuple[ValidationDynamicVariant, ...]


@dataclass(frozen=True)
class SaveValidationContext:
    """Explicit control text and additional native metadata, without freshness proof.

    Serial text is the exact non-null tbSerialVer.Text snapshot, not a PP serial
    number. Level variants are the complete ordered DynamicAll objects, including
    null Names and image presence. Missing rows mean unknown, never absent.
    """
    serial_text: str
    group_names: tuple[ValidationGroupName, ...] = ()
    levels: tuple[ValidationLevel, ...] = ()

    def __post_init__(self):
        self._check()

    def _check(self):
        def address(value):
            return type(value) is int and 0 <= value <= 255
        def name(value):
            return value is None or (type(value) is str and len(value) <= 4096)
        if type(self.serial_text) is not str or len(self.serial_text) > 4096:
            raise EdltTemplateError('Supply bounded exact non-null serial verification control text')
        if (type(self.group_names) is not tuple or len(self.group_names) > 512
                or any(type(row) is not ValidationGroupName or not address(row.application)
                       or not address(row.group) or not name(row.tag_name) for row in self.group_names)):
            raise EdltTemplateError('Invalid explicit validation group names')
        if len({(r.application, r.group) for r in self.group_names}) != len(self.group_names):
            raise EdltTemplateError('Duplicate validation group name')
        if type(self.levels) is not tuple or len(self.levels) > 8192:
            raise EdltTemplateError('Invalid explicit validation levels')
        for row in self.levels:
            if (type(row) is not ValidationLevel or not all(address(v) for v in
                    (row.application, row.group, row.level)) or type(row.variants) is not tuple
                    or len(row.variants) > 4 or any(type(v) is not ValidationDynamicVariant
                    or not name(v.name) or type(v.image_present) is not bool for v in row.variants)):
                raise EdltTemplateError('Invalid complete ordered validation DynamicAll facts')
        if len({(r.application, r.group, r.level) for r in self.levels}) != len(self.levels):
            raise EdltTemplateError('Duplicate validation level')

    def as_dict(self):
        self._check()
        return asdict(self)


class TemplateSaveValidationApplyRefused(EdltTemplateError):
    def __init__(self):
        super().__init__('Source-derived Save predicates do not authorize template Apply/OK or persistence')
        self.details = {'status': 'refused', 'blockers': list(UNEXECUTED_PHASES),
                        'apply_allowed': False, 'target_mutation_attempted': False, 'saved': False}


class TemplateSaveValidationStageError(EdltTemplateError):
    def __init__(self, message, evidence):
        super().__init__(message)
        self.details = json.loads(_json(evidence))


@dataclass(frozen=True)
class TemplateSaveValidationStage:
    source_receipt_sha256: str
    specification_sha256: str
    cache_sha256: str
    context_sha256: str
    projection: str
    _owner: object = field(repr=False, compare=False)

    def as_dict(self):
        return {'format': FORMAT, **json.loads(self.projection),
            'source_receipt_sha256': self.source_receipt_sha256,
            'specification_sha256': self.specification_sha256, 'cache_sha256': self.cache_sha256,
            'context_sha256': self.context_sha256,
            'evidence_class': 'source-predicate-projection',
            'metadata_provenance': 'caller-supplied frozen cache and control facts',
            'getter_admission_policy': 'refuse reads requiring writes or add-enabled missing objects',
            'report_order_scope': 'label before status; local slot order; native hash enumeration unproved',
            'model_reloaded': False, 'before_save_executed': False,
            'original_save_validation_verified': False, 'active_control_flush_verified': False,
            'cache_freshness_verified': False, 'complete_parent_lifecycle_verified': False,
            'validation_getter_side_effects_executed': False,
            'unexecuted_phases': list(UNEXECUTED_PHASES),
            'apply_allowed': False, 'target_mutation_attempted': False,
            'save_dispatched': False, 'saved': False, 'physical_device_verified': False}

    def apply(self, target=None):
        raise TemplateSaveValidationApplyRefused()


class _Stop(Exception):
    def __init__(self, outcome, **facts):
        self.outcome, self.facts = outcome, facts


class _Projection:
    def __init__(self, source, context):
        self.loaded, self.values, self.context = source.loaded, source.after_load, context
        self.raw = source.raw_after_load
        self.cache = self.loaded.metadata
        self.consumed = []

    def group(self, application, number, *, reason):
        if application not in self.cache.applications:
            raise _Stop('required_fact_missing', application=application, reason=reason)
        row = self.cache.find(application, number)
        if row is None:
            raise _Stop('required_fact_missing', application=application, group=number, reason=reason)
        self.consumed.append({'application': application, 'group': number, 'reason': reason,
                              'exists': row.exists})
        if not row.exists:
            raise _Stop('requires_validation_mutation', application=application, group=number,
                        reason=reason, original_operation='add-enabled group lookup')
        return row

    def trigger(self, scene):
        return self.group(202, scene.trigger.group, reason='Scene trigger getter').group

    def action(self, scene):
        trigger = self.trigger(scene)
        if trigger == 255:
            return -1
        row = self.group(202, trigger, reason='Scene action getter')
        action = scene.action_selector
        if action == -1:
            raise _Stop('requires_validation_mutation', scene=scene.slot,
                        original_operation='ActionSelector setter(-1), dynamic labels and notifications')
        if row.levels is None:
            raise _Stop('required_fact_missing', scene=scene.slot, field='complete level addresses')
        if action not in row.levels:
            raise _Stop('requires_validation_mutation', scene=scene.slot, level=action,
                        original_operation='add-enabled level lookup and possible selector normalization')
        self.consumed.append({'application': 202, 'group': trigger, 'level': action,
                              'reason': 'existing Scene action getter level'})
        return action

    def widget_validation(self):
        labels, statuses = [], []
        for widget in self.loaded.widgets:
            if widget.stored_type != 6:
                continue
            slot = widget.slot
            control = self.values[_field(slot, 1)][0] & 255
            label_mode = {1: 'text', 2: 'icon'}.get(control >> 4)
            status_mode = {6: 'text', 7: 'icon'}.get(control & 15)
            label_variant = self.values[_field(slot, 11)][0]
            status_variant = self.values[_field(slot, 12)][0]
            if label_mode is None and status_mode is None:
                continue
            # An intact second model already requires App202. The source null-app
            # early-true branch cannot be asserted for this retained profile.
            if 202 not in self.cache.applications:
                raise _Stop('required_fact_missing', application=202, reason='Scene widget application')
            cycle = [self.values[_field(slot, byte)][0] for byte in range(13, 22)]
            picks = []
            for index, pick in enumerate(cycle):
                if not 0 <= pick < 9:
                    if any(self.raw[_field(slot, byte)] != '0xFF'
                           for byte in range(14 + index, 22)):
                        raise _Stop('requires_validation_mutation', widget=slot,
                            first_invalid_byte=13 + index, original_operation='SceneCycle trailing byte normalization')
                    break
                picks.append(pick)
            bad_labels, bad_statuses = [], []
            for pick in picks:
                scene = next((s for s in self.loaded.scenes if s.slot == pick + 1), None)
                if scene is None:
                    continue
                trigger = self.trigger(scene)
                action = self.action(scene)
                row = self.cache.find(202, trigger)
                # A noneditable group has action=-1; the outer false level lookup
                # cannot find byte-address -1 and therefore has no DynamicAll.
                level_present = action >= 0 and action in (row.levels or ())
                variants = ()
                if level_present:
                    fact = next((r for r in self.context.levels if
                        (r.application, r.group, r.level) == (202, trigger, action)), None)
                    if fact is None:
                        raise _Stop('required_fact_missing', application=202, group=trigger,
                                    level=action, field='complete ordered DynamicAll')
                    variants = tuple((v.name, v.image_present) for v in fact.variants)
                    self.consumed.append({'application': 202, 'group': trigger, 'level': action,
                                          'reason': 'Scene widget DynamicAll'})
                check = check_scene_widget_variants(label_mode, status_mode, label_variant,
                    status_variant, variants, level_present=level_present)
                if check.outcome == 'expected_index_exception':
                    raise _Stop('expected_original_exception', widget=slot, scene=scene.slot,
                                original_exception='DynamicAll index access')
                if check.label_inconsistent and scene.slot not in bad_labels:
                    bad_labels.append(scene.slot)
                if check.status_inconsistent and scene.slot not in bad_statuses:
                    bad_statuses.append(scene.slot)
            if bad_labels:
                labels.append({'widget': slot, 'variant': label_variant, 'mode': label_mode,
                               'scenes': bad_labels})
            if bad_statuses:
                statuses.append({'widget': slot, 'variant': status_variant, 'mode': status_mode,
                                 'scenes': bad_statuses})
        return {'valid': not labels and not statuses, 'label_errors': labels, 'status_errors': statuses,
                'original_dialog_required': bool(labels or statuses),
                'original_dialog_result_consumed': False}

    def unit_validation(self):
        # Every GetGroup executes before corridor's 255 early return. Reuse the
        # established seven-family KEYGL5 mapping; the retained models are checked
        # by the issuer, so no caller group-order override is accepted.
        groups = []
        primary = self.values['PrimaryApplication'][0]
        link = self.values['CorridorLinkingLinkGroup'][0]
        for widget in self.loaded.widgets:
            if widget.model_family not in _GROUP_FAMILIES:
                continue
            application = 203 if widget.model_family == 'EnableData' else (
                self.values['SecondaryApplication'][0]
                if self.values[_field(widget.slot, 1)][0] & 128 else primary)
            number = self.values[_field(widget.slot, 6)][0]
            self.group(application, number, reason='Widget GetGroup ' + str(widget.slot))
            # TagName is read only for the first corridor match, after acquisition.
            groups.append((application, number))
        key_groups = []
        first = next((key for key in groups if link != 255 and key == (primary, link)), None)
        for application, number in groups:
            tag = ''
            if (application, number) == first:
                fact = next((r for r in self.context.group_names if
                    (r.application, r.group) == first), None)
                if fact is None:
                    raise _Stop('required_fact_missing', application=application, group=number,
                                field='first corridor matching group TagName')
                tag = fact.tag_name or ''
            key_groups.append(KeyGroup(application, number, tag))
        projection = self
        class Scene:
            def __init__(self, scene):
                self._scene = scene
                self.slot, self.item_count, self.name_index = scene.slot, len(scene.items), scene.name_index
            @property
            def trigger(self): return projection.trigger(self._scene)
            @property
            def action(self): return projection.action(self._scene)
        result = validate_unit(primary, link, key_groups, [Scene(s) for s in self.loaded.scenes])
        return asdict(result)

    def run(self):
        order = ['serial']
        serial = validate_serial_text(self.context.serial_text)
        result = {'validator_order': order, 'serial': asdict(serial), 'scene_widget': None, 'unit': None}
        if serial.outcome != 'accepted':
            result['outcome'] = 'serial_rejected' if serial.outcome == 'rejected' else 'unproven_serial_parse'
        else:
            try:
                order.append('scene_widget')
                widgets = self.widget_validation()
                result['scene_widget'] = widgets
                if not widgets['valid']:
                    result['outcome'] = 'scene_widget_rejected'
                else:
                    order.append('unit')
                    unit = self.unit_validation()
                    result['unit'] = unit
                    result['outcome'] = 'source_predicates_passed' if unit['valid'] else 'unit_rejected'
            except _Stop as stop:
                result['outcome'], result['stop'] = stop.outcome, {'validator': order[-1], **stop.facts}
        result['source_predicates_passed'] = result['outcome'] == 'source_predicates_passed'
        result['consumed_facts'] = self.consumed
        return result


class EdltTemplateSaveValidationStage:
    """Single-use diagnostic issuer bound to a model or template lifecycle issuer."""
    def __init__(self, issuer):
        if type(issuer) not in (EdltTemplateModelStage, EdltTemplateLifecycleStage):
            raise EdltTemplateError('Use the original lifecycle or second-model stage issuer')
        self._issuer, self._owner, self._state = issuer, object(), 'open'
        self._upstream = self._candidate = self._signature = self._failure = None

    @property
    def state(self): return self._state

    @property
    def candidate(self): return self._candidate if self._state == 'staged' else None

    @property
    def last_failure(self):
        return None if self._failure is None else json.loads(self._failure)

    def _validate_upstream(self, upstream, current_source, metadata, dirty_parameters):
        if type(self._issuer) is EdltTemplateLifecycleStage:
            if tuple(dirty_parameters):
                raise EdltTemplateError('Lifecycle-stage dirty facts are issued by its assignment stage')
            self._issuer.validate(upstream, current_source=current_source, metadata=metadata)
            return upstream.second_model
        self._issuer.validate(upstream, current_source, metadata=metadata, dirty_parameters=dirty_parameters)
        return upstream

    def stage(self, upstream, *, current_source, metadata, context, dirty_parameters=()):
        if self._state != 'open':
            raise EdltTemplateError('Save validation stage is no longer open')
        self._state = 'staging'
        phase = 'upstream_validation'
        try:
            dirty_parameters = tuple(dirty_parameters)
            source = self._validate_upstream(upstream, current_source, metadata, dirty_parameters)
            if type(context) is not SaveValidationContext:
                raise EdltTemplateError('Supply an explicit SaveValidationContext')
            context_hash = _sha(context.as_dict())
            phase = 'ordered_source_predicates'
            result = _Projection(source, context).run()
            phase = 'projection_validation'
            self._validate_upstream(upstream, current_source, metadata, dirty_parameters)
            if _sha(context.as_dict()) != context_hash:
                raise EdltTemplateError('Validation context changed during staging')
            candidate = TemplateSaveValidationStage(_sha(upstream.as_dict()), source.specification_sha256,
                source.cache_sha256, context_hash, _json(result), self._owner)
            self._upstream, self._candidate, self._signature = upstream, candidate, _sha(candidate.as_dict())
            self._state = 'staged'
            return candidate
        except BaseException as error:
            self._candidate = self._upstream = self._signature = None
            self._state = 'failed'
            evidence = {'status': 'failed', 'phase': phase, 'error': _error_text(error),
                'candidate_published': False, 'local_validation_candidate_discarded': True,
                'target_mutation_attempted': False, 'saved': False, 'automatic_retries': 0}
            self._failure = _json(evidence)
            if not isinstance(error, Exception):
                try: error.edlt_template_save_validation_evidence = self.last_failure
                except BaseException: pass
                raise
            raise TemplateSaveValidationStageError('Save validation staging failed: ' + _error_text(error),
                                                  evidence) from error

    def validate(self, candidate, *, current_source, metadata, context, dirty_parameters=()):
        if (self._state != 'staged' or type(candidate) is not TemplateSaveValidationStage
                or candidate is not self._candidate or candidate._owner is not self._owner):
            raise EdltTemplateError('Use an intact active Save validation stage issued here')
        self._validate_upstream(self._upstream, current_source, metadata, tuple(dirty_parameters))
        if (type(context) is not SaveValidationContext or _sha(context.as_dict()) != candidate.context_sha256
                or _sha(self._upstream.as_dict()) != candidate.source_receipt_sha256
                or _sha(candidate.as_dict()) != self._signature):
            raise EdltTemplateError('Validation stage differs from its issued context or projection')
        return candidate

    def cancel(self):
        if self._state == 'staging':
            raise EdltTemplateError('Cannot cancel while Save validation staging is in progress')
        self._candidate = self._upstream = self._signature = None
        self._state = 'cancelled'
        return {'status': 'cancelled', 'local_validation_candidate_discarded': True,
                'upstream_issuer_cancelled': False, 'original_cancel_replayed': False,
                'target_mutation_attempted': False, 'saved': False}

    def apply(self, target=None):
        raise TemplateSaveValidationApplyRefused()
