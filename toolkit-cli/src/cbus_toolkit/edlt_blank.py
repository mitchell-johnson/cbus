"""Select Blank on one retained eDLT widget, then perform the model save cycle."""
from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltError, EdltApplyError, _field, _int, _render
from .edlt_lifecycle import EdltLifecycle, LifecycleCache, _delta, _json, _error_text


@dataclass(frozen=True)
class BlankPlan:
    page: int
    position: int
    slot: int
    type_changed: bool
    expected: Mapping
    after_load: Mapping
    after_controls: Mapping
    before_save: Mapping
    changes: Mapping
    metadata: LifecycleCache
    evidence: str

    def __post_init__(self):
        for name in ('expected', 'after_load', 'after_controls', 'before_save', 'changes'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        final = {**self.expected, **self.changes}
        return {'format': 'cbus-edlt-blank-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00',
                'page': self.page, 'position': self.position, 'widget': self.slot,
                'type_changed': self.type_changed, 'requested_type': 0,
                'stored_type_after_save': final[_field(self.slot)][0],
                'phases': {'after_load': _delta(self.expected, self.after_load),
                           'controls': _delta(self.after_load, self.after_controls),
                           'before_save': _delta(self.after_controls, self.before_save),
                           'crc': _delta(self.before_save, final)},
                'changes': {k: list(v) if isinstance(v, tuple) else v for k, v in self.changes.items()},
                **json.loads(self.evidence), 'metadata_provenance': 'caller-supplied-cache',
                'database_metadata_created': False, 'cache_freshness_verified': False,
                'full_form_initialization_verified': False, 'physical_device_verified': False,
                'saved': False}


class EdltBlankWidget:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.lifecycle = EdltLifecycle(spec, catalog_number=catalog_number, firmware=firmware)
        self.common = self.lifecycle.common
        self.spec, self.codec = self.common.spec, self.common.codec
        self.last_evidence = None

    def snapshot(self, values): return self.common.snapshot(values)
    def crcs(self, values): return self.common.crcs(values)
    def requirements(self, current): return self.lifecycle.requirements(current)

    @staticmethod
    def _slot(values, page, position):
        _int(page, 'Page (0 is standby)', 0, 4)
        _int(position, 'Widget position', 1, 5)
        mode = values['NavWidgetType'][0]
        if mode not in (0, 1):
            raise EdltError('Blank selection requires a canonical single or multiple page layout (NavWidgetType0 or1)')
        if page == 0:
            slot = position
            if slot > 1 and values[_field(slot - 1)] == (11,):
                raise EdltError('Standby position is covered by the preceding two-slice widget')
        elif mode == 0:
            if page != 1:
                raise EdltError('Single-page layout exposes only functional page1')
            slot = position + 5
        else:
            if position == 5:
                raise EdltError('The navigation position has no Blank widget choice')
            slot = 6 + (page - 1) * 4 + position - 1
        return slot

    def plan(self, current, *, metadata, page, position):
        original = self.snapshot(current)
        # Validate simple inputs/layout before loading dependency-sensitive models.
        _int(page, 'Page (0 is standby)', 0, 4); _int(position, 'Widget position', 1, 5)
        if original['NavWidgetType'][0] not in (0, 1):
            raise EdltError('Blank selection requires a canonical single or multiple page layout (NavWidgetType0 or1)')
        loaded = self.lifecycle.load(original, metadata=metadata)
        slot = self._slot(loaded.after_load, page, position)
        edited = self.lifecycle.blank_widget(loaded, slot)
        saved = self.lifecycle.prepare_save(edited)
        evidence = {'model_edit_scope': 'one bound Blank selection on retained loaded models; model BeforeSave and CRCs',
                    'lifecycle': saved.as_dict(), 'blank_transition': edited.as_dict(),
                    'scene_references_retained': True, 'static_references_retained': True,
                    'source_model_family': loaded.widgets[slot - 1].model_family,
                    'source_stored_type': loaded.widgets[slot - 1].stored_type,
                    'row_navigation_handlers_invoked': False,
                    'physical_factory_reset_performed': False, 'unit_defaults_reset_performed': False}
        return BlankPlan(page, position, slot, edited.type_changed, loaded.expected,
                         loaded.after_load, edited.after_controls, saved.before_save,
                         saved.changes, loaded.metadata, _json(evidence))

    def _interrupted(self, error, plan, attempted, original_error=None):
        try:
            evidence = {**plan.as_dict(), 'verified': False, 'saved': False,
                        'attempted_parameters': list(attempted), 'pp_state_uncertain': bool(attempted),
                        'automatic_retries': 0}
        except BaseException as secondary:
            evidence = {'verified': False, 'saved': False, 'attempted_parameters': list(attempted),
                        'evidence_export_complete': False, 'evidence_error': _error_text(secondary)}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': _error_text(original_error)}
        self.last_evidence = evidence
        try: error.edlt_blank_evidence = evidence
        except BaseException: pass
        return evidence

    def apply(self, session, plan):
        self.last_evidence = None
        if type(plan) is not BlankPlan or type(plan.metadata) is not LifecycleCache:
            raise EdltError('Use a Blank plan returned by EdltBlankWidget.plan')
        _int(plan.page, 'Plan page', 0, 4); _int(plan.position, 'Plan position', 1, 5)
        _int(plan.slot, 'Plan widget slot', 1, 21)
        if type(plan.type_changed) is not bool:
            raise EdltError('Plan type_changed must be boolean')
        for values in (plan.expected, plan.after_load, plan.after_controls,
                       plan.before_save, {**plan.expected, **plan.changes}):
            self.snapshot(values)
        canonical = self.plan(plan.expected, metadata=plan.metadata, page=plan.page, position=plan.position)
        if canonical != plan or _json(canonical.as_dict()) != _json(plan.as_dict()):
            raise EdltError('Plan differs from its validated Blank selection')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the Blank plan was made')
        expected = {**plan.expected, **plan.changes}; attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name); session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the Blank plan')
        except (KeyboardInterrupt, SystemExit) as error:
            self._interrupted(error, plan, attempted); raise
        except Exception as error:
            rollback_errors = []
            try:
                for name in reversed(attempted):
                    if not getattr(session.programmer.client, 'connected', True):
                        rollback_errors.append('Connection lost; rollback stopped without recovery I/O; PP state is uncertain'); break
                    try: session.set(name, _render(plan.expected[name]))
                    except Exception as rollback: rollback_errors.append(_error_text(rollback))
                if getattr(session.programmer.client, 'connected', True):
                    try:
                        if self.snapshot(session.values()) != dict(plan.expected):
                            rollback_errors.append('Original PP values could not be verified')
                    except Exception as rollback: rollback_errors.append(_error_text(rollback))
            except (KeyboardInterrupt, SystemExit) as interrupted:
                self._interrupted(interrupted, plan, attempted, error)
                self.last_evidence['rollback_errors'] = rollback_errors
                raise
            wrapped = EdltApplyError(error, rollback_errors, attempted)
            self._interrupted(wrapped, plan, attempted, error)
            if hasattr(error, 'cgate_cleanup_errors'): wrapped.cgate_cleanup_errors = error.cgate_cleanup_errors
            raise wrapped from error
        self.last_evidence = {**plan.as_dict(), 'verified': True}
        return self.last_evidence

    def configure(self, session, *, metadata, page, position):
        self.last_evidence = None
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), metadata=metadata, page=page, position=position))
