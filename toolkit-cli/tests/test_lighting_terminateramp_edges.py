"""P7.04 slice: terminated-ramp event projection edges without I/O.

The retained native Lighting grammar covers terminated ramps in both rows:
730 ``ramp terminated new level=L sourceunit=S`` and status ``lighting
terminateramp ADDR #level=L #sourceunit=S OID=...``. Fixture replay pins the
valid pair; this file pins the malformed boundary (out-of-range level/group/
source, missing source, bad OID, non-Lighting application, trailing tokens
stay opaque and never acquire a source) plus filter behavior on a valid
terminated projection (group match, literal zero source, overflow survival).
"""
import unittest

from cbus_toolkit.application_events import LightingEventFilter, project_lighting_event
from cbus_toolkit.events import parse_event


TIMESTAMP = "20260929-135954.123"
EVENT_730 = f"#e# {TIMESTAMP} 730 //PROJECT/254/56/1 - ramp terminated new level=66 sourceunit=6"
EVENT_730_ZERO = f"#e# {TIMESTAMP} 730 //PROJECT/254/56/1 - ramp terminated new level=0 sourceunit=0"
STATUS_TERM = "#s# lighting terminateramp //PROJECT/254/56/1 #level=66 #sourceunit=6 OID="


class TerminaterampEdgeTests(unittest.TestCase):
    def test_valid_terminated_rows_project(self):
        projection = project_lighting_event(parse_event(EVENT_730))
        self.assertEqual((projection.kind, projection.level, projection.ramp_seconds,
                          projection.source_unit, projection.group, projection.application),
                         ("ramp_terminated", 66, None, 6, 1, 56))
        self.assertIsNone(projection.oid)
        status = project_lighting_event(parse_event(STATUS_TERM))
        self.assertEqual((status.kind, status.level, status.ramp_seconds, status.source_unit),
                         ("terminateramp", 66, None, 6))

    def test_explicit_zero_source_stays_literal(self):
        projection = project_lighting_event(parse_event(EVENT_730_ZERO))
        self.assertEqual(projection.source_unit, 0)
        self.assertEqual(projection.level, 0)
        self.assertTrue(LightingEventFilter(56, 1, 0).matches(parse_event(EVENT_730_ZERO)))
        self.assertFalse(LightingEventFilter(56, 1, 6).matches(parse_event(EVENT_730_ZERO)))

    def test_malformed_terminated_rows_stay_opaque(self):
        bad = [
            f"#e# {TIMESTAMP} 730 //PROJECT/254/56/1 - ramp terminated new level=256 sourceunit=6",
            f"#e# {TIMESTAMP} 730 //PROJECT/254/56/1 - ramp terminated new level=66",
            f"#e# {TIMESTAMP} 730 //PROJECT/254/56/1 - ramp terminated new level=66 sourceunit=256",
            f"#e# {TIMESTAMP} 730 //PROJECT/254/56/1 - ramp terminated new level=66 sourceunit=6 ramptime=0",
            f"#e# {TIMESTAMP} 730 //PROJECT/254/56/1 - ramp terminated new level=66 sourceunit=6 extra",
            "#s# lighting terminateramp //PROJECT/254/56/1 #level=256 #sourceunit=6 OID=",
            "#s# lighting terminateramp //PROJECT/254/56/1 #level=66 OID=",
            "#s# lighting terminateramp //PROJECT/254/56/1 #level=66 #sourceunit=6 OID=wrong",
            "#s# lighting terminateramp //PROJECT/254/202/1 #level=66 #sourceunit=6 OID=",
            "#s# lighting terminateramp //PROJECT/254/56/256 #level=66 #sourceunit=6 OID=",
            "#s# lighting terminateramp //PROJECT/254/56/1 #level=66 #sourceunit=6 OID= trailing",
        ]
        for raw in bad:
            with self.subTest(raw=raw):
                record = parse_event(raw)
                self.assertIsNone(project_lighting_event(record))
                self.assertFalse(LightingEventFilter(group=1).matches(record))
                self.assertTrue(LightingEventFilter().matches(record))

    def test_filter_matches_terminated_projection(self):
        record = parse_event(EVENT_730)
        self.assertTrue(LightingEventFilter(group=1).matches(record))
        self.assertTrue(LightingEventFilter(56, 1, 6).matches(record))
        self.assertFalse(LightingEventFilter(56, 2, 6).matches(record))
        overflow = parse_event("###!!!Event buffer overflow. Events have been missed.!!!###")
        self.assertTrue(LightingEventFilter(56, 1, 6).matches(overflow))


if __name__ == "__main__":
    unittest.main()
