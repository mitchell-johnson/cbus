"""Wave 32 offline pins for Room Courtesy guards with zero prior refs.

P6 narrow slice of ``edlt_room_courtesy`` guard messages and canonical
boundaries. Every pinned message had zero prior refs (verified via
``grep -rn -F`` across tests/*.py before writing: no hits for these
exact substrings; existing room-courtesy tests assert nearby branches
only as bare EdltError or with different substrings).
Pure offline: no hardware, vendor EXE, C-Gate server, or decoded spec.
"""

from dataclasses import replace

import pytest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_room_courtesy import EdltRoomCourtesyWidget
from test_edlt import Session, fixture


def make_editor():
    spec = fixture()
    return EdltRoomCourtesyWidget(spec), Session(spec)


def base_options(**overrides):
    options = dict(page=1, position=1, group=42)
    options.update(overrides)
    return options


def after(plan):
    return {**plan.expected, **plan.changes}


def test_mode_and_colour_option_guards():
    editor, session = make_editor()
    with pytest.raises(
        EdltError, match="Room Courtesy mode must be bell-press or unused"
    ):
        editor.plan(session.values(), **base_options(mode="off-on"))
    with pytest.raises(
        EdltError, match="Room Courtesy colour must be none/white/red/green"
    ):
        editor.plan(session.values(), **base_options(off_colour="RED"))
    with pytest.raises(
        EdltError, match="Room Courtesy colour must be none/white/red/green"
    ):
        editor.plan(session.values(), **base_options(on_colour=2))


def test_assigned_application_and_existing_record_guards():
    editor, session = make_editor()
    current = session.values()
    current["SecondaryApplication"] = (0,)
    with pytest.raises(
        EdltError, match="Room Courtesy requires an assigned application"
    ):
        editor.plan(current, **base_options(application="secondary"))
    plan = editor.plan(session.values(), **base_options())
    current = after(plan)
    invalid_macro = dict(current)
    invalid_macro["Widget6WidgetByteValue7"] = (99,)
    with pytest.raises(
        EdltError, match="Invalid existing Room Courtesy macro"
    ):
        editor.plan(invalid_macro, **base_options())
    invalid_colour = dict(current)
    invalid_colour["Widget6WidgetByteValue10"] = (99,)
    with pytest.raises(
        EdltError, match="Invalid existing Room Courtesy colour"
    ):
        editor.plan(invalid_colour, **base_options())
    # Explicit repair restores the pinned canonical record.
    repaired = editor.plan(invalid_macro, **base_options(mode="unused"))
    assert repaired.record[7] == 255
    repaired_colour = editor.plan(
        invalid_colour, **base_options(off_colour="orange")
    )
    assert repaired_colour.record[10] == 8


def test_label_status_coupling_and_dynamic_guards():
    editor, session = make_editor()
    with pytest.raises(EdltError, match="cannot accompany"):
        editor.plan(
            session.values(), **base_options(label_text="Hi", label_index=1)
        )
    with pytest.raises(EdltError, match="cannot accompany"):
        editor.plan(
            session.values(), **base_options(status_text="Hi", status_index=0)
        )
    with pytest.raises(
        EdltError, match="Unsupported label or status display type"
    ):
        editor.plan(session.values(), **base_options(label_type="bogus"))
    with pytest.raises(
        EdltError, match="Unsupported label or status display type"
    ):
        editor.plan(session.values(), **base_options(status_type="level"))
    with pytest.raises(
        EdltError, match="This label/status display does not use an index"
    ):
        editor.plan(
            session.values(),
            **base_options(label_type="blank", label_index=1),
        )
    with pytest.raises(
        EdltError, match="Invalid existing label/status type or index"
    ):
        plan = editor.plan(session.values(), **base_options())
        current = after(plan)
        current["Widget6WidgetByteValue1"] = (0x40,)
        editor.plan(current, **base_options())
    dynamic = after(
        editor.plan(
            session.values(),
            **base_options(
                label_type="dynamic-text",
                label_index=2,
                status_type="dynamic-icon",
                status_index=0,
            ),
        )
    )
    with pytest.raises(
        EdltError,
        match="Changing a dynamic reference requires explicit label_type",
    ):
        editor.plan(dynamic, **base_options(group=43))


def test_apply_rejects_nonplan_and_forged_settings():
    editor, session = make_editor()
    with pytest.raises(
        EdltError, match="Use a Room Courtesy widget plan"
    ):
        editor.apply(session, None)
    plan = editor.plan(session.values(), **base_options())
    with pytest.raises(
        EdltError, match="Invalid Room Courtesy plan settings"
    ):
        editor.apply(
            session, replace(plan, options={**dict(plan.options), "bogus": 1})
        )
    with pytest.raises(
        EdltError, match="Plan differs from its validated Room Courtesy"
    ):
        editor.apply(
            session,
            replace(plan, changes={**dict(plan.changes), "SceneCount": (8,)}),
        )
