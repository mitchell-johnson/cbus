"""Explicit classic DLT Block Dynamic Updates control and optional variants.

The original classic model loads BlockDynamicUpdates as the inverse of
EnableDynamicLabels. This bounded database editor owns that bit and explicitly
selected variants only; it does not execute the complete original dialog save
or transfer any labels. See research/fixtures/classic-dlt-controls-original.json.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType

from .dlt_labels import (CHANGED, DYNAMIC_FLAG, FIELDS,
                         ClassicDltLabels, DltLabelApplyError, DltLabelError,
                         _values)

FORMAT = 'cbus-classic-dlt-control-plan-v1'
FLAG = DYNAMIC_FLAG[0]
ADDRESS = 0x3E
MASK = 0x40


def _flag(value):
    values = _values(value, FLAG)
    if len(values) != 1 or type(values[0]) is not int or values[0] not in (0, 1):
        raise DltLabelError('EnableDynamicLabels must contain one bit value')
    return values


@dataclass(frozen=True)
class DltControlPlan:
    unit_type: str
    identity: tuple | None
    expected: dict
    changes: dict
    variants: tuple
    block_dynamic_updates: bool

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))

    def as_dict(self):
        firmware, catalog = self.identity[1:] if self.identity else (None, None)
        return {'format': FORMAT, 'unit_type': self.unit_type, 'firmware': firmware,
                'catalog_number': catalog,
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()},
                'requested': {'variants': [list(row) for row in self.variants],
                              'block_dynamic_updates': self.block_dynamic_updates},
                'block_dynamic_updates_before': not bool(self.expected[FLAG][0]),
                'block_dynamic_updates_after': self.block_dynamic_updates,
                'dynamic_control_mask': {'address': ADDRESS, 'mask': MASK},
                'saved': False, 'device_verified': False, 'labels_transferred': False,
                'original_full_form_save_executed': False}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('format') != FORMAT:
            raise DltLabelError('Expected a ' + FORMAT + ' document')
        try:
            expected = {k: tuple(v) for k, v in data['expected'].items()}
            changes = {k: tuple(v) for k, v in data['changes'].items()}
            requested = data['requested']
            variants = tuple(tuple(row) for row in requested['variants'])
            block = requested['block_dynamic_updates']
            if type(block) is not bool or any(len(row) != 2 for row in variants):
                raise ValueError('Invalid control selection')
            if len(dict(variants)) != len(variants):
                raise ValueError('Duplicate variant selection')
            unit_type = data['unit_type']
            firmware = data.get('firmware')
            identity = None if firmware is None else (unit_type, firmware, data.get('catalog_number'))
            return cls(unit_type, identity, expected, changes, variants, block)
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            raise DltLabelError('Invalid classic DLT control plan') from error


class ClassicDltControls(ClassicDltLabels):
    def control_snapshot(self, current):
        values = self.snapshot(current)
        if FLAG not in current:
            raise DltLabelError('Missing current DLT label parameter: ' + FLAG)
        values[FLAG] = _flag(current[FLAG])
        return values

    def show(self, current, identity=None):
        result = super().show(current, identity)
        result['block_dynamic_updates'] = None if FLAG not in current else not bool(_flag(current[FLAG])[0])
        return result

    def plan_controls(self, current, *, block_dynamic_updates, variants=None, identity=None):
        if type(block_dynamic_updates) is not bool:
            raise DltLabelError('Block Dynamic Updates must be a boolean')
        if identity is not None:
            identity = self.check_identity(*identity)
        if variants is not None and not isinstance(variants, dict):
            raise DltLabelError('Variants must be a slot=variant mapping')
        expected = self.control_snapshot(current)
        changes, selected = {}, ()
        if variants:
            variant_plan = self.plan(current, variants=variants, identity=identity)
            changes, selected = dict(variant_plan.changes), variant_plan.requested
        value = (int(not block_dynamic_updates),)
        if value != expected[FLAG]:
            changes[FLAG] = value
        return DltControlPlan(self.unit_type, identity, expected, changes, selected, block_dynamic_updates)

    @staticmethod
    def _raw_flag(session):
        if not hasattr(session, 'get_raw_data'):
            return None
        line = session.get_raw_data(ADDRESS, 1).lines[-1]
        if 'RawData=' not in line:
            raise DltLabelError('Native raw readback did not return RawData')
        raw = bytes.fromhex(line.split('RawData=', 1)[1].strip())
        if len(raw) != 1:
            raise DltLabelError('Native dynamic-label control readback must contain one byte')
        return raw[0]

    def apply_controls(self, session, plan):
        if (not isinstance(plan, DltControlPlan) or plan.unit_type != self.unit_type
                or set(plan.expected) != {*FIELDS, FLAG}
                or set(plan.changes) - {*CHANGED, FLAG}):
            raise DltLabelError('Plan contains fields outside the classic DLT controls')
        # Python equality aliases False/0 and 0.0/0. Neither may reach SET as
        # a text token, even when it compares equal to the canonical bit.
        if any(type(value) is not int for values in (*plan.expected.values(), *plan.changes.values())
               for value in values):
            raise DltLabelError('Classic DLT plan PP values must be exact integers')
        # Re-derive ownership from the request; serialized changes are never an
        # authority to write other slots or a contradictory dynamic-label bit.
        if len(dict(plan.variants)) != len(plan.variants):
            raise DltLabelError('Duplicate variant selection')
        canonical = self.plan_controls(plan.expected, block_dynamic_updates=plan.block_dynamic_updates,
                                       variants=dict(plan.variants), identity=plan.identity)
        if canonical != plan:
            raise DltLabelError('Classic DLT control plan differs from its requested controls')
        identity = self._verify_profile(session)
        if plan.identity is not None and plan.identity != identity:
            raise DltLabelError('Plan was created for another unit identity')
        self._verify_session(session, fields=(*FIELDS, FLAG))
        if self.control_snapshot(session.values()) != dict(plan.expected):
            raise DltLabelError('PP parameters changed since the DLT control plan was created')
        before_raw = self._raw_flag(session)
        if before_raw is not None and ((before_raw & MASK) >> 6) != plan.expected[FLAG][0]:
            raise DltLabelError('Native dynamic-label control raw bit disagrees with PP values')
        expected = {**plan.expected, **plan.changes}
        attempted = []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, ' '.join(map(str, values)))
            if self.control_snapshot(session.values()) != expected:
                raise DltLabelError('Native DLT control readback differs from the plan')
            after_raw = self._raw_flag(session)
            if before_raw is not None and after_raw != ((before_raw & ~MASK) | (expected[FLAG][0] << 6)):
                raise DltLabelError('Native dynamic-label control changed unrelated bits or differs from the plan')
            slot_raw = self._raw_readback(session)
            if slot_raw is not None and slot_raw != self._raw({name: expected[name] for name in FIELDS}):
                raise DltLabelError('Native raw bytes 0x60..0x67 differ from the planned image')
        except (RuntimeError, OSError, ValueError) as error:
            raise DltLabelApplyError(error, attempted) from error
        return {**replace(plan, identity=identity).as_dict(), 'verified': True,
                'raw_bytes_verified': after_raw is not None and slot_raw is not None,
                'dynamic_control_raw_before': before_raw, 'dynamic_control_raw_after': after_raw,
                'raw_after_hex': None if slot_raw is None else slot_raw.hex()}

    def configure_controls(self, session, *, block_dynamic_updates, variants=None):
        identity = self._verify_profile(session)
        return self.apply_controls(session, self.plan_controls(
            session.values(), block_dynamic_updates=block_dynamic_updates, variants=variants, identity=identity))
