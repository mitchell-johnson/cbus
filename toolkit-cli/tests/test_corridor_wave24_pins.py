"""P6 wave-24 narrow offline pins for corridor guards (issue #45).

One narrow slice of ``edlt_corridor.py`` guards with zero prior refs in
``tests/`` (verified via ``grep -rn --fixed-strings`` before writing):
requirements/plan envelope, edit-shape, layout/control/selection/conflict,
and apply/rollback guards. Pure offline: synthetic spec/cache/fake session
only, no hardware, vendor EXE, C-Gate server, or decoded spec. #45 stays
OPEN; Rust, edlt_timer, wireless_unit_globals, firmware_update_cli,
wireless_commissioning, unit_diagnostics, and parity register untouched.
"""
from __future__ import annotations

import unittest
from dataclasses import replace

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_corridor import (
    CorridorApplyError,
    CorridorConflictError,
    CorridorEdit,
    CorridorSelectionError,
    EdltCorridor,
    FIELDS,
)
from cbus_toolkit.edlt_lifecycle import LifecycleMetadataError
from tests.test_edlt import Session
from tests.test_edlt_corridor import cache as make_cache
from tests.test_edlt_corridor import fixture as make_spec


def active_source(editor, session):
    source = editor.snapshot(session.values())
    return {
        **source,
        FIELDS["link_group"]: (42,),
        FIELDS["office_group"]: (1,),
        FIELDS["corridor_group"]: (2,),
    }


class CorridorWave24EnvelopePins(unittest.TestCase):
    """Requirements and plan envelope literals."""

    def test_requirements_and_plan_envelope(self):
        # Next: #45 corridor only; no timer/wireless/firmware/diagnostics/parity.
        spec = make_spec()
        editor = EdltCorridor(spec)
        session = Session(spec)
        active = active_source(editor, session)
        req = editor.requirements(active)
        self.assertEqual(req["format"], "cbus-edlt-corridor-requirements-v1")
        self.assertEqual(req["effective_primary_application"], 56)
        self.assertTrue(req["complete_ordered_primary_group_list_required"])
        self.assertTrue(req["retained_key_function_group_facts_required"])
        self.assertFalse(req["metadata_creation_supported"])
        self.assertEqual(
            req["raw_corridor"],
            {"link_group": 42, "office_group": 1, "corridor_group": 2, "seconds": 300},
        )
        plan = editor.plan(active, cache=make_cache(), edits=())
        doc = plan.as_dict()
        self.assertEqual(
            doc["model_edit_scope"],
            "ordered Corridor controls on unchanged loaded models; private Corridor validation",
        )
        self.assertFalse(doc["widget_control_bindings_invoked"])
        self.assertEqual(doc["metadata_creation_policy"], "disabled")
        self.assertFalse(doc["full_unit_validation_performed"])


class CorridorWave24EditShapePins(unittest.TestCase):
    """Edit-shape guards."""

    def test_field_from_dict_and_sequence_guards(self):
        # Next: same #45 boundary; no device write or metadata creation.
        spec = make_spec()
        editor = EdltCorridor(spec)
        session = Session(spec)
        source = editor.snapshot(session.values())
        with self.assertRaisesRegex(EdltError, "Corridor field must be"):
            CorridorEdit("bad", 1)
        with self.assertRaisesRegex(EdltError, "Invalid Corridor edit fields"):
            CorridorEdit.from_dict({"field": "seconds", "value": 1, "extra": 1})
        with self.assertRaisesRegex(EdltError, "Invalid Corridor edit fields"):
            CorridorEdit.from_dict({})
        for bad in ("x", {}, [CorridorEdit("seconds", 60)] * 65):
            with self.subTest(bad=str(bad)[:30]):
                with self.assertRaisesRegex(
                    EdltError, "Corridor edits must be an ordered sequence of at most64 actions"
                ):
                    editor.plan(source, cache=make_cache(), edits=bad)


class CorridorWave24ControlPins(unittest.TestCase):
    """Layout, primary-application, selection, and conflict messages."""

    def test_layout_primary_selection_conflict(self):
        # Next: same #45 boundary; no timer/wireless/firmware/diagnostics/parity.
        spec = make_spec()
        editor = EdltCorridor(spec)
        session = Session(spec)
        active = active_source(editor, session)
        params = dict(spec.parameters)
        name = FIELDS["seconds"]
        params[name] = replace(
            params[name], fields={**params[name].fields, "BitSize": "8"}
        )
        with self.assertRaisesRegex(EdltError, "Unsupported Corridor layout"):
            EdltCorridor(replace(spec, parameters=params))
        base = make_cache()
        lists = tuple(g for g in base.group_lists if g.application != 56)
        apps = tuple(a for a in base.applications if a.address != 56)
        pruned = replace(
            base, applications_complete=False, applications=apps, group_lists=lists
        )
        with self.assertRaisesRegex(
            LifecycleMetadataError, "Corridor controls require a named primary application"
        ):
            editor.plan(active, cache=pruned, edits=())
        with self.assertRaisesRegex(
            CorridorSelectionError, "Requested Corridor group is unavailable or its control is disabled"
        ):
            editor.plan(active, cache=make_cache(), edits=(CorridorEdit("link_group", 1),))
        conflicted = {
            **active,
            "Widget6WidgetType": (2,),
            "Widget6WidgetByteValue6": (42,),
        }
        with self.assertRaisesRegex(
            CorridorConflictError, "Corridor Link group is also used by a key function"
        ):
            editor.plan(conflicted, cache=make_cache(), edits=())


class CorridorWave24ApplyPins(unittest.TestCase):
    """Apply, staleness, readback, and failure-wrapper guards."""

    def test_apply_stale_readback_and_wrapper(self):
        # Next: same #45 boundary; fake session only, no hardware or server.
        spec = make_spec()
        editor = EdltCorridor(spec)
        session = Session(spec)
        source = editor.snapshot(session.values())
        plan = editor.plan(source, cache=make_cache(), edits=(CorridorEdit("seconds", 256),))
        with self.assertRaisesRegex(EdltError, "Use a Corridor plan returned by EdltCorridor.plan"):
            editor.apply(session, "not-a-plan")
        with self.assertRaisesRegex(
            EdltError, "Plan differs from its validated Corridor controls"
        ):
            editor.apply(session, replace(plan, evidence="{}"))
        stale = Session(spec)
        stale.current[FIELDS["seconds"]] = "0"
        with self.assertRaisesRegex(
            EdltError, "PP values changed since the Corridor plan was made"
        ):
            editor.apply(stale, plan)
        frozen = Session(spec)
        frozen.set = lambda name, value: None
        with self.assertRaises(CorridorApplyError) as caught:
            editor.apply(frozen, plan)
        self.assertRegex(str(caught.exception), "Corridor edit failed")
        self.assertRegex(str(caught.exception), "Native PP readback differs from the Corridor plan")
        self.assertRegex(str(caught.exception.__cause__), "Native PP readback differs from the Corridor plan")
        failing = Session(spec)
        failing.failure = next(iter(plan.changes))
        with self.assertRaises(CorridorApplyError) as failed:
            editor.apply(failing, plan)
        self.assertRegex(str(failed.exception), "Corridor edit failed")


if __name__ == "__main__":
    unittest.main()
