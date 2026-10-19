"""Wave19 offline pins for original eDLT MRA guards with zero prior refs."""
import unittest
from dataclasses import replace

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_mra import EdltMRAWidget, normalize_mra_globals
from tests.test_edlt import Session
from tests.test_edlt_hvac import fixture


def _empty_mra_current():
    current = {}
    for widget in range(1, 22):
        current[f"Widget{widget}WidgetType"] = (0,)
        current[f"Widget{widget}WidgetByteValue1"] = (0,)
    return current


class MRAWave19Pins(unittest.TestCase):
    def test_normalize_rejects_non_mapping_and_standby_placement(self):
        with self.assertRaisesRegex(EdltError, "normalized PP mapping"):
            normalize_mra_globals("not-a-mapping")
        standby = _empty_mra_current()
        standby["Widget3WidgetType"] = (7,)
        standby["Widget3WidgetByteValue1"] = (0,)
        with self.assertRaisesRegex(EdltError, "standby positions"):
            normalize_mra_globals(standby)

    def test_normalize_internal_preservation_flags_require_bool(self):
        empty = {f"Widget{i}WidgetType": (0,) for i in range(1, 22)}
        for i in range(1, 22):
            empty[f"Widget{i}WidgetByteValue1"] = (0,)
        with self.assertRaisesRegex(EdltError, "placement preservation flag must be boolean"):
            normalize_mra_globals(empty, _preserve_stored_placement="yes")
        with self.assertRaisesRegex(EdltError, "Internal preservation flag must be boolean"):
            normalize_mra_globals(empty, _preserve_stored_multiplexer=1)

    def test_plan_rejects_nonfunctional_source_and_parent_composition_type(self):
        editor = EdltMRAWidget(fixture())
        session = Session(editor.spec)
        current = session.values()
        current["Widget6WidgetType"] = "11"
        with self.assertRaisesRegex(EdltError, "outside original functional UI types"):
            editor.plan(current, page=1, position=1, kind="zone-control")
        with self.assertRaisesRegex(EdltError, "parent-composition flag must be boolean"):
            editor.plan(session.values(), page=1, position=1, kind="zone-control",
                        _parent_composition="yes")

    def test_apply_rejects_foreign_plan_and_truncated_record(self):
        editor = EdltMRAWidget(fixture())
        session = Session(editor.spec)
        with self.assertRaisesRegex(EdltError, "Use an MRA plan returned by EdltMRAWidget"):
            editor.apply(session, object())
        plan = editor.plan(session.values(), page=1, position=1, kind="zone-control")
        forged = replace(plan, record=b"\x00" * 31)
        with self.assertRaisesRegex(EdltError, "Plan MRA record must contain"):
            editor.apply(session, forged)
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
