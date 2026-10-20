"""Wave-15 narrow pins for P6.01 (#45): classic DLT control/binding guards.

Offline only: exercises ``cbus_toolkit.dlt_controls`` with no I/O, no
vendor fixtures and no network. Each edge below had zero prior refs in
``tests/test_dlt_controls.py`` (only neighbouring inputs or bare
non-None assertions existed).
"""

from cbus_toolkit.dlt_controls import DltControlPlan, ClassicDltControls
from cbus_toolkit.dlt_labels import DltLabelError
from test_dlt_labels import fixture, session


def _editor(unit_type='KEYBL5'):
    return ClassicDltControls(fixture(), unit_type)


def test_show_without_flag_reports_unknown_block_state():
    # ``show`` tolerates a missing EnableDynamicLabels row and reports the
    # derived Block Dynamic Updates state as unknown, while the slot view
    # still renders; ``control_snapshot`` instead refuses the same input.
    editor = _editor()
    live = session()
    values = live.values()
    del values['EnableDynamicLabels']
    view = editor.show(values)
    assert view['block_dynamic_updates'] is None
    assert len(view['slots']) == 8
    try:
        editor.control_snapshot(values)
    except DltLabelError as error:
        assert 'EnableDynamicLabels' in str(error)
    else:
        raise AssertionError('control_snapshot accepted a missing flag')


def test_plan_controls_rejects_non_mapping_variants():
    # The variants binding must be a slot=variant mapping; a list or string
    # selection is refused before any plan is produced.
    editor = _editor()
    live = session()
    for variants in ([(1, 2)], '1=2', ((1, 2),)):
        try:
            editor.plan_controls(live.values(), block_dynamic_updates=True, variants=variants)
        except DltLabelError:
            pass
        else:
            raise AssertionError(f'accepted non-mapping variants: {variants!r}')
    assert live.calls == []


def test_serialized_control_plan_rejects_format_and_duplicate_rows():
    # Serialized control documents are bound to their format marker and to
    # unique variant rows; both forgeries are refused on load.
    editor = _editor()
    live = session()
    plan = editor.plan_controls(live.values(), block_dynamic_updates=True, variants={1: 4})
    bad_format = dict(plan.as_dict())
    bad_format['format'] = 'cbus-classic-dlt-control-plan-v0'
    try:
        DltControlPlan.from_dict(bad_format)
    except DltLabelError as error:
        assert 'cbus-classic-dlt-control-plan-v1' in str(error)
    else:
        raise AssertionError('accepted a foreign control plan format')
    duplicate = plan.as_dict()
    duplicate['requested']['variants'] = [[1, 4], [1, 2]]
    try:
        DltControlPlan.from_dict(duplicate)
    except DltLabelError:
        pass
    else:
        raise AssertionError('accepted duplicate variant rows')


def test_apply_controls_refuses_foreign_unit_binding():
    # A control plan bound to KEYML5 cannot be applied through the KEYBL5
    # editor; the unit-type binding is checked before any PP write.
    editor = _editor('KEYBL5')
    other = _editor('KEYML5')
    live = session('KEYML5', '2.0.00', '5055DL')
    plan = other.plan_controls(live.values(), block_dynamic_updates=True)
    try:
        editor.apply_controls(live, plan)
    except DltLabelError as error:
        assert 'outside the classic DLT controls' in str(error)
    else:
        raise AssertionError('applied a foreign unit-type control plan')
    assert live.calls == []


def test_raw_flag_readback_guards():
    # The native raw readback binding requires a RawData line with exactly
    # one byte; a marker-less reply and a two-byte reply both fail closed.
    editor = _editor()
    live = session()

    class NoMarker:
        lines = ('347 OK',)

    class TwoBytes:
        lines = ('347 RawData=00ff',)

    live.get_raw_data = lambda start, count: NoMarker()
    try:
        editor.configure_controls(live, block_dynamic_updates=True)
    except DltLabelError as error:
        assert 'did not return RawData' in str(error)
    else:
        raise AssertionError('accepted a raw reply without RawData')
    live.get_raw_data = lambda start, count: TwoBytes()
    try:
        editor.configure_controls(live, block_dynamic_updates=True)
    except DltLabelError as error:
        assert 'one byte' in str(error)
    else:
        raise AssertionError('accepted a two-byte control readback')
    assert live.calls == []
