"""Source-owned MRA callback bases inside one retained parent transaction."""
from dataclasses import replace

from .edlt import EdltError, _field, _int
from .edlt_mra import (MRAWidgetPlan, MRA_WIDGET_TYPES, MRA_VARIANTS,
                       MRAPropagation, _mra_records)
from .edlt_mra_control_properties import (MRAPropertyState,
    default_mra_properties, write_mra_property)
from .edlt_scene_names import assign_name, load_names
from .edlt_static_grid import current, adopt_retained_names


def retained_names(values):
    grid = current(values)
    return tuple(grid.names) if grid is not None else load_names(values)


def external_references(common, values, widget):
    """Keep unrelated admission strict; selected MRA owns its raw references."""
    shadow = {**values, _field(widget): (0,)}
    return tuple(common.static_references(shadow))


def initial_global_context(values):
    """First surviving initialized model, captured before any type conversion."""
    records = _mra_records(values, allow_stored_placement=True)
    first = next(iter(records), None)
    raw = 0 if first is None else records[first]
    return (1 + (raw >> 6), 1 + ((raw >> 3) & 7), first)


def effective_propagation(values, context, options):
    if (type(context) is not tuple or len(context) != 3
            or type(context[0]) is not int or not 1 <= context[0] <= 4
            or type(context[1]) is not int or not 1 <= context[1] <= 8):
        raise EdltError('MRA callbacks require initialized parent global context')
    mux, zone, first = context
    if options.get('multiplexer') is not None:
        mux = _int(options['multiplexer'], 'MRA multiplexer', 1, 3)
    if options.get('zone') is not None:
        zone = _int(options['zone'], 'MRA zone', 1, 8)
    records = _mra_records(values, allow_stored_placement=True)
    upper = ((mux - 1) << 6) | ((zone - 1) << 3)
    changes = {_field(slot, 1): (upper | (raw & 7),)
               for slot, raw in records.items() if upper | (raw & 7) != raw}
    previous = {slot: (raw >> 6, (raw >> 3) & 7, raw & 7) for slot, raw in records.items()}
    return MRAPropagation(mux, zone, first, tuple(records), previous, changes)


def plan_control_globals(editor, values, options, context):
    original = editor.snapshot(values)
    propagation = effective_propagation(original, context, options)
    if not propagation.widgets:
        raise EdltError('Create an MRA widget before storing distributed MRA globals')
    mode = 'multiple' if original['NavWidgetType'] == (1,) else 'single'
    return MRAWidgetPlan('globals', None, None, None, None, mode, None, None,
        None, None, None, propagation, None, None, None, False, original, {}, options)


def plan_control_base(editor, values, *, kind, options, controls, global_context):
    """Explicit ordinary edits keep their existing normalizer.

    A callback-only retained record never reads the mutating Zone macro getter.
    A type conversion executes the exact recovered defaults before callbacks.
    The enclosing parent remains the only terminal lifecycle/save owner.
    """
    if any(row.get('event') == 'binding-write' and
           row.get('target') in ('icon-on', 'icon-off') for row in controls):
        if values.get('UseBigIcon') != (1,):
            raise EdltError('MRA icon Index bindings require UseBigIcon enabled')
    base_fields = {'page', 'position', 'page_mode', 'multiplexer', 'zone'}
    if any(name not in base_fields and value is not None
           for name, value in options.items()):
        ordinary = editor.plan(values, kind=kind, _parent_composition=True, **options)
        before = ordinary.record_before
        record = bytes((ordinary.record[0], (before[1] & 0xF8) | (ordinary.record[1] & 7),
                        *ordinary.record[2:]))
        updates = {**ordinary.expected, **ordinary.changes}
        for slot in _mra_records(ordinary.expected, allow_stored_placement=True):
            updates[_field(slot, 1)] = ordinary.expected[_field(slot, 1)]
        updates = editor.common._place_record(updates, ordinary.widget, record, normalize_mra=False)
        updates.update(editor.crcs(updates))
        propagation = effective_propagation(updates, global_context, options)
        changes = {name: value for name, value in updates.items() if value != ordinary.expected[name]}
        return replace(ordinary, record=record, propagation=propagation, changes=changes), {
            'mode': 'explicit ordinary configuration before callbacks; globals deferred to terminal save',
            'implicit_framework_dispatch': False}
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
    widget = 6 + (page - 1) * 4 + position - 1
    before = bytes(original[_field(widget, i)][0] for i in range(32))
    if before[0] not in (0, *range(2, 11), *range(12, 17), 255):
        raise EdltError('Selected source widget is outside original functional UI types')
    external = external_references(editor.common, original, widget)
    converted = before[0] != MRA_WIDGET_TYPES[kind]
    raw = bytes((MRA_WIDGET_TYPES[kind], *before[1:]))
    state = MRAPropertyState(kind, raw, original[f'Widget{widget}RestoreLevel'][0])
    updates = dict(original)
    names = retained_names(original)
    default_receipt = None
    if converted:
        allocations = []

        def set_text(current_state, target, text):
            nonlocal names
            assignment = assign_name(names, current_state.index(target), text,
                values=updates, used_indices=lambda: tuple(sorted(
                    set(external) | set(current_state.used_static_text()))))
            names = assignment.names
            updates.update(assignment.changes)
            outcome = write_mra_property(current_state,
                'LabelValueIndex' if target == 'label' else 'StatusValueIndex',
                assignment.index)
            allocations.append(assignment.as_dict())
            return outcome, assignment.as_dict()

        outcome, actions, _extra = default_mra_properties(state, set_text=set_text)
        state = outcome.state
        default_receipt = {**outcome.as_dict(), 'actions': list(actions),
            'allocations': allocations, 'implicit_framework_dispatch': False}
    updates = editor.common._place_record(updates, widget, state.record,
                                         normalize_mra=False)
    updates[f'Widget{widget}RestoreLevel'] = (state.restore_level,)
    propagation = effective_propagation(updates, global_context, options)
    updates['NavWidgetType'] = (1 if mode == 'multiple' else 0,)
    for name, value in (('ConfigVersionMajor', 1), ('ConfigVersionMinor', 0)):
        if original[name] == (255,):
            updates[name] = (value,)
    updates['Application'] = (original['PrimaryApplication'][0],
                              original['SecondaryApplication'][0])
    updates.update(editor.crcs(updates))
    record = bytes(updates[_field(widget, i)][0] for i in range(32))
    changes = {name: value for name, value in updates.items()
               if value != original[name]}
    plan = MRAWidgetPlan('widget', kind, page, position, widget, mode,
        next((name for name, value in MRA_VARIANTS[kind].items()
              if value == record[6]), None), None, before, record,
        state.restore_level, propagation, None, None, None, False,
        original, changes, options)
    # Only completed defaults may enter this branch's retained table.
    if converted:
        adopt_retained_names(updates, tuple(names))
    return plan, {'mode': 'source defaults before callbacks' if converted else
                 'retained callback-only record without mutation getters',
                 'converted': converted, 'defaults': default_receipt,
                 'implicit_framework_dispatch': False}


def project_owned_controls(owner, binding, operation, values, plan):
    from .edlt_mra_controls import project_mra_controls, prepare_mra_projection
    if binding.family != plan.kind or binding.widget != plan.widget:
        raise EdltError('MRA binding differs from the owning operation family/widget')
    result = project_mra_controls(binding, owner=owner, operation=operation,
                                  values=values, retained_names=retained_names(values))
    record, changes, receipt = prepare_mra_projection(result, owner=owner)
    adopt_retained_names(values, result.retained_names)
    return replace(plan, record=record, restore_level=result.restore_level,
                   changes={**plan.changes, **changes}), receipt
