"""Wave 33 offline pins for eDLT activation guards with zero prior refs.

P6 narrow slice of ``edlt_activation`` guard messages. Every pinned
substring had zero prior refs (verified via ``grep -rn`` across
tests/*.py before writing: no hits for these exact activation-specific
substrings; existing activation tests assert nearby branches only as
bare EdltError or with different substrings).
Pure offline: no hardware, vendor EXE, C-Gate server, or decoded spec.
"""

from dataclasses import replace

import pytest

from cbus_toolkit.edlt import EdltApplyError, EdltError
from cbus_toolkit.edlt_activation import EdltActivation
from tests.test_edlt import Session
from tests.test_edlt_activation import fixture


def make_editor():
    spec = fixture()
    return EdltActivation(spec), Session(spec)


def test_input_guards_pin_stable_messages():
    editor, session = make_editor()
    with pytest.raises(
        EdltError, match="ignore_first_key_press must be boolean"
    ):
        editor.plan(session.values(), ignore_first_key_press=1)
    with pytest.raises(
        EdltError,
        match="level and action select the same ProximityLevel field",
    ):
        editor.plan(
            session.values(),
            wake_mode="primary-event",
            group=7,
            level=1,
            action=1,
        )


def test_apply_rejects_nonplan_and_forged_settings():
    editor, session = make_editor()
    with pytest.raises(
        EdltError, match="Use an activation plan returned by EdltActivation.plan"
    ):
        editor.apply(session, None)
    plan = editor.plan(
        session.values(), wake_mode="primary-event", group=42, level=173
    )
    with pytest.raises(EdltError, match="Plan boolean fields are invalid"):
        editor.apply(session, replace(plan, ignore_first_key_press=0))
    with pytest.raises(EdltError, match="Invalid activation plan settings"):
        editor.apply(
            session, replace(plan, options={**dict(plan.options), "bogus": 1})
        )
    with pytest.raises(
        EdltError, match="Plan differs from its validated activation settings"
    ):
        editor.apply(
            session,
            replace(plan, changes={**dict(plan.changes), "SceneCount": (8,)}),
        )


def test_stale_and_readback_guards():
    editor, session = make_editor()
    plan = editor.plan(
        session.values(), wake_mode="primary-event", group=42, level=173
    )
    session.current["ActivityDuration"] = (0,)
    with pytest.raises(
        EdltError, match="PP values changed since the activation plan was made"
    ):
        editor.apply(session, plan)
    editor2, session2 = make_editor()
    original_set = session2.set

    def drop_value(name, value):
        if name != "ProximityLevel":
            original_set(name, value)

    session2.set = drop_value
    with pytest.raises(
        EdltApplyError,
        match="Native PP readback differs from the activation plan",
    ):
        editor2.configure(
            session2, wake_mode="primary-event", group=42, level=173
        )
    assert editor2.snapshot(session2.values()) == editor2.snapshot(
        fixture().defaults()
    )


def test_rollback_verification_guard():
    editor, session = make_editor()
    plan = editor.plan(
        session.values(), wake_mode="primary-event", group=42, level=173
    )
    first = True

    def flaky_set(name, value):
        nonlocal first
        if first:
            first = False
            session.current[name] = value
            raise RuntimeError("injected forward failure")
        return None

    session.set = flaky_set
    with pytest.raises(EdltApplyError) as caught:
        editor.apply(session, plan)
    assert (
        "Original PP values could not be verified"
        in caught.value.rollback_errors
    )
