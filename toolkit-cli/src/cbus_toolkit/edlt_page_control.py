"""Exact eDLT Page Control numeric Enable application group configuration."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, _field, _int, _render
from .edlt_mra import MRAPropagation, normalize_mra_globals


@dataclass(frozen=True)
class PageControlPlan:
    group: int
    expected: Mapping
    changes: Mapping
    options: Mapping
    mra_propagation: MRAPropagation

    def __post_init__(self):
        for name in ('expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-page-control-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00',
                'group': self.group, 'application': 203, 'enabled': self.group != 255,
                'database_group_created': False, 'database_group_verified': False,
                'applies_to_whole_unit': True, 'mra_propagation': self.mra_propagation.as_dict(),
                'normalization_changes': {name: list(value) for name, value in self.changes.items()
                                          if name.startswith('Widget') and name != 'WidgetsCRC'},
                'changes': {name: list(value) if isinstance(value, tuple) else value for name, value in self.changes.items()},
                'saved': False, 'physical_device_verified': False, 'physical_page_control_verified': False}


class EdltPageControl:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        try:
            layout = self.codec.layout('KeySetsEnableGroup')
        except (ValueError, KeyError) as error:
            raise EdltError('Unsupported Page Control settings layout: KeySetsEnableGroup') from error
        if (layout.address, layout.parameter.type, layout.bit_address, layout.bit_size,
                layout.array_size, layout.array_skip) != (0x131, 'int', 0, 8, 1, 0):
            raise EdltError('Unsupported Page Control settings layout: KeySetsEnableGroup')

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, group=None):
        if group is not None:
            _int(group, 'Page Control group', 0, 255)
        options = {'group': group}
        original = self.snapshot(current); self.common.static_references(original)
        selected = _int(original['KeySetsEnableGroup'][0] if group is None else group, 'KeySetsEnableGroup', 0, 255)
        updates = dict(original); updates['KeySetsEnableGroup'] = (selected,)
        # The original selector has no standby, page-mode or primary-app dependency.
        mra = normalize_mra_globals(updates, _preserve_stored_multiplexer=True, _preserve_stored_placement=True)
        updates = self.common._place_record(updates, 1, bytes(updates[_field(1, index)][0] for index in range(32)))
        updates.update(mra.changes)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return PageControlPlan(selected, original, changes, options, mra)

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {**plan.as_dict(), 'verified': False, 'saved': False, 'attempted_parameters': list(attempted),
                    'pp_state_uncertain': bool(attempted), 'automatic_retries': 0}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': str(original_error)}
        error.edlt_page_control_evidence = evidence

    def apply(self, session, plan):
        if type(plan) is not PageControlPlan or not isinstance(plan.options, Mapping):
            raise EdltError('Use a Page Control plan returned by EdltPageControl.plan')
        _int(plan.group, 'Plan group', 0, 255)
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid Page Control plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated Page Control settings')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the Page Control plan was made')
        expected = {**plan.expected, **plan.changes}; attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name); session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the Page Control plan')
        except (KeyboardInterrupt, SystemExit) as error:
            self._interrupted(error, plan, attempted); raise
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
                interrupted.edlt_page_control_evidence['rollback_errors'] = rollback_errors
                raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
