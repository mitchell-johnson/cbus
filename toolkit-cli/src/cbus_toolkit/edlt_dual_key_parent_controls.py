"""Retained Timer, Shutter and Room Courtesy callback bases for one parent save.

Explicit scalar configuration uses the existing family planner. A callback-only
retained record is not implicitly repaired by that planner. Conversions retain
its existing source-proven default/allocation and group admission contract.
"""
from dataclasses import dataclass, replace
from types import MappingProxyType

from .edlt import EdltError, _field, _int
from .edlt_scene_names import load_names
from .edlt_static_grid import current, adopt_retained_names

FAMILY_TYPES = {'timer': 5, 'shutter': 3, 'room-courtesy': 15}


def retained_names(values):
    grid = current(values)
    return tuple(grid.names) if grid is not None else load_names(values)


def external_references(common, values, widget):
    """The selected callback model owns its references; others stay strict."""
    return tuple(common.static_references({**values, _field(widget): (0,)}))


@dataclass(frozen=True)
class DualKeyWidgetPlan:
    page: int
    position: int
    widget: int
    page_mode: str
    group: int
    application: int
    restore_level: int
    expected: object
    changes: object
    record: bytes
    options: object

    def __post_init__(self):
        for name in ('expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-dual-key-retained-base-v1',
                'page': self.page, 'position': self.position, 'widget': self.widget,
                'page_mode': self.page_mode, 'application': self.application,
                'group': self.group, 'restore_level': self.restore_level,
                'record_hex': self.record.hex(), 'raw_model_fields_preserved': True,
                'saved': False, 'physical_device_verified': False}


def plan_control_base(editor, values, *, kind, options):
    if kind not in FAMILY_TYPES:
        raise EdltError('Dual-key callbacks require Timer, Shutter or Room Courtesy')
    original = editor.snapshot(values)
    page, position = options['page'], options['position']
    nav = original['NavWidgetType'][0]
    if nav not in (0, 1, 255):
        raise EdltError('Unsupported navigation widget mode')
    mode = options.get('page_mode') or ('multiple' if nav == 1 else 'single')
    if mode not in ('single', 'multiple'):
        raise EdltError('page_mode must be single or multiple')
    _int(page, 'Page', 1, 4 if mode == 'multiple' else 1)
    _int(position, 'Position', 1, 4 if mode == 'multiple' else 5)
    slot = 6 + (page - 1) * 4 + position - 1
    raw = bytes(original[_field(slot, i)][0] for i in range(32))
    scalar = any(name not in ('page', 'position', 'page_mode') and value is not None
                 for name, value in options.items())
    if scalar or raw[0] != FAMILY_TYPES[kind]:
        if options.get('group') is None:
            raise EdltError('Dual-key conversion requires explicit group and the existing ordinary configuration profile')
        ordinary = editor.plan(values, **options)
        return ordinary, {'mode': 'ordinary configuration/defaults before callbacks',
                          'converted': raw[0] != FAMILY_TYPES[kind],
                          'implicit_framework_dispatch': False}
    external_references(editor.common, original, slot)
    updates = editor.common._place_record(original, slot, raw, normalize_mra=False)
    updates['NavWidgetType'] = (1 if mode == 'multiple' else 0,)
    for name, value in (('ConfigVersionMajor', 1), ('ConfigVersionMinor', 0)):
        if original[name] == (255,):
            updates[name] = (value,)
    updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
    updates.update(editor.crcs(updates))
    from .edlt_parent_transaction import _selected_application
    application = _selected_application(updates, raw, kind)
    plan = DualKeyWidgetPlan(page, position, slot, mode, raw[6], application,
        original[f'Widget{slot}RestoreLevel'][0], original,
        {name: value for name, value in updates.items() if value != original[name]},
        raw, options)
    return plan, {'mode': 'retained callbacks without ordinary mutation getters',
                  'converted': False, 'implicit_framework_dispatch': False}


def project_owned_controls(owner, binding, operation, values, plan):
    from .edlt_dual_key_controls import project_dual_key_controls, prepare_dual_key_projection
    if (binding.family != operation['op'] or binding.widget != plan.widget):
        raise EdltError('Dual-key binding differs from the owning operation family/widget')
    result = project_dual_key_controls(binding, owner=owner, operation=operation,
                                      values=values, retained_names=retained_names(values))
    record, changes, receipt = prepare_dual_key_projection(result, owner=owner)
    # A rejected or pending projection cannot install speculative Names.
    adopt_retained_names(values, result.retained_names)
    return replace(plan, record=record, restore_level=result.restore_level,
                   changes={**plan.changes, **changes}), receipt
