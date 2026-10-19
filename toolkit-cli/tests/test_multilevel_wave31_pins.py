"""Wave 31 offline pins for MultiLevel guards with zero prior refs.

P6 narrow slice of ``edlt_multilevel`` guard messages and canonical
boundaries. Every pinned message had zero prior refs (verified via
``grep -rn`` across tests/*.py before writing: existing multilevel tests
use only generic assertRaises or other substrings, never these strings).
Pure offline: no hardware, vendor EXE, C-Gate server, or decoded spec.
"""

from dataclasses import replace

import pytest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_multilevel import EdltMultiLevelWidget
from tests.test_edlt import Session, fixture


def make_editor():
    spec = fixture()
    return EdltMultiLevelWidget(spec), Session(spec)


def base_options(**overrides):
    options = dict(page=1, position=1, group=42)
    options.update(overrides)
    return options


def test_level_threshold_combination_guards():
    editor, session = make_editor()
    with pytest.raises(
        EdltError, match="One-level MultiLevel does not use thresholds"
    ):
        editor.plan(session.values(), **base_options(levels=1, low_threshold=10))
    with pytest.raises(
        EdltError, match="One-level MultiLevel does not use thresholds"
    ):
        editor.plan(session.values(), **base_options(levels=1, high_threshold=10))
    with pytest.raises(
        EdltError, match="Two-level MultiLevel uses low_threshold"
    ):
        editor.plan(session.values(), **base_options(levels=2, high_threshold=10))
    with pytest.raises(
        EdltError, match="Three-level MultiLevel requires"
    ):
        editor.plan(
            session.values(),
            **base_options(low_threshold=171, high_threshold=84),
        )


def test_unsupported_label_display_guard():
    editor, session = make_editor()
    with pytest.raises(EdltError, match="Unsupported label display type"):
        editor.plan(session.values(), **base_options(label_type="bogus"))


def test_apply_rejects_nonplan_and_bad_record():
    editor, session = make_editor()
    with pytest.raises(EdltError, match="Use a MultiLevel widget plan"):
        editor.apply(session, None)
    plan = editor.plan(session.values(), **base_options())
    with pytest.raises(EdltError, match="Plan widget record must contain 32 bytes"):
        editor.apply(session, replace(plan, record=b"bad"))


def test_apply_rejects_forged_status_settings_and_drift():
    editor, session = make_editor()
    plan = editor.plan(session.values(), **base_options())
    with pytest.raises(EdltError, match="Plan status_forced must be boolean"):
        editor.apply(session, replace(plan, status_forced=0))
    with pytest.raises(EdltError, match="Invalid MultiLevel plan settings"):
        editor.apply(
            session, replace(plan, options={**dict(plan.options), "bogus": 1})
        )
    with pytest.raises(
        EdltError, match="Plan differs from its validated MultiLevel"
    ):
        editor.apply(
            session,
            replace(plan, changes={**dict(plan.changes), "SceneCount": (8,)}),
        )
