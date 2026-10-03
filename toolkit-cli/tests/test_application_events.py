"""Lighting projections against retained original rows and real client framing."""
import json
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from cbus_toolkit.application_events import LightingEventFilter, project_lighting_event
from cbus_toolkit.events import parse_event
from test_cgate import peer


FIXTURE = Path(__file__).resolve().parents[2] / "rust/testdata/fixtures/native_cgate_lighting_events.json"
TIMESTAMP = "20260929-135954.123"


def original_row(raw):
    return raw.replace("<timestamp>", TIMESTAMP).replace("cmd<session>", "cmd17")


class LightingProjectionTests(unittest.TestCase):
    def test_retained_original_lighting_cases(self):
        fixture = json.loads(FIXTURE.read_text())
        self.assertEqual(fixture["oracle"]["version"], "3.4.0.2001")
        # Independent expected source/level facts, including native deviations
        # which are still legitimate recorded input to this client parser.
        expected = {
            "on_source_4": [(56, 1, 4, 255, 0)],
            "off_source_4": [(56, 1, 4, 0, 0)],
            "off_repeat_source_4": [(56, 1, 4, 0, 0)],
            "ramp_instant_128_source_5": [(56, 1, 5, 128, 0)],
            "ramp_instant_255_source_5": [(56, 1, 5, 255, 0)],
            "ramp_instant_0_source_5": [(56, 1, 5, 0, 0)],
            "ramp_4s_200_source_6": [(56, 1, 6, 200, 4)],
            "terminate_source_6": [(56, 1, 6, 66, None)],
            "ramp_4s_0_source_6": [(56, 1, 6, 0, 4)],
            "ramp_1020s_77_source_6": [(56, 1, 6, 77, 1020)],
            "terminate_idle_source_7": [],
            "on_source_0": [(56, 2, 0, 255, 0)],
            "on_source_255": [(56, 3, 255, 255, 0)],
            "concatenated_source_7": [(56, 4, 7, 255, 0), (56, 5, 7, 0, 0), (56, 6, 7, 128, 0)],
            "application_48_source_7": [(48, 1, 7, 255, 0)],
            "database_group_source_8": [(56, 7, 8, 255, 0)],
            "database_group_ramp_source_8": [(56, 7, 8, 64, 8)],
            "pm_routing_byte_source_9": [(56, 10, 9, 255, 0)],
            "ppm_one_bridge_source_9": [],
            "command_on": [(56, 9, 16, 255, 0)],
            "command_ramp": [(56, 9, 16, 100, 4)],
            "command_terminate": [(56, 9, 16, 100, None)],
            "command_off_database_group": [(56, 7, 16, 0, 0)],
        }
        cases = fixture["cases"] + fixture["commands"]
        self.assertEqual({case["label"] for case in cases}, set(expected))
        for case in cases:
            with self.subTest(case=case["label"]):
                facts = []
                for raw in case["native_rows"]:
                    record = parse_event(original_row(raw))
                    projection = project_lighting_event(record)
                    if projection is None:
                        continue
                    facts.append((projection.application, projection.group, projection.source_unit,
                                  projection.level, projection.ramp_seconds))
                    self.assertEqual((projection.project, projection.network), ("PROJECT", "254"))
                    self.assertEqual(record.raw, original_row(raw))
                    self.assertEqual(record.timestamp, TIMESTAMP if record.category == "event" else None)
                    if projection.group == 7:
                        self.assertEqual(projection.oid, "77777777-7777-4777-8777-000000000007")
                    else:
                        self.assertIsNone(projection.oid)
                    self.assertEqual(projection.session_id, "cmd17" if "sessionId=cmd17" in record.raw else None)
                    self.assertEqual(projection.command_id, {"command_on": "c0", "command_ramp": "c1",
                                                           "command_terminate": "c2", "command_off_database_group": "c3"}.get(case["label"])
                                     if projection.session_id else None)
                # Native emits both a level-change event and a separate status
                # row. Their order varies in the capture; preserve both.
                self.assertCountEqual(facts, expected[case["label"]] * 2)

    def test_opaque_and_invalid_input_never_acquires_a_source(self):
        unknown = [
            "#e# lighting //PROJECT/254/56/1 on 255",
            "#e# lighting //PROJECT/254/56/1 level=255",
            "#s# lighting on //PROJECT/254/56/1  OID=",
            "#s# lighting on //PROJECT/254/56/1  #sourceunit=256 OID=",
            "#s# lighting ramp //PROJECT/254/56/1 256 4 #sourceunit=4 OID=",
            "#s# lighting ramp //PROJECT/254/56/1 128 1021 #sourceunit=4 OID=",
            "#s# lighting on //PROJECT/254/202/1  #sourceunit=4 OID=",
            "#s# lighting on //PROJECT/254/56/256  #sourceunit=4 OID=",
            "#s# lighting on //PROJECT/254/56/1  #sourceunit=4 OID=wrong",
            "#s# lighting on //PROJECT/254/56/1  #sourceunit=4 OID= trailing",
            "#s# lighting on //PROJECT/254/56/1  #sourceunit=4 OID= sessionId=cmd17",
            "#s# trigger event //PROJECT/254/202/1 3 #sourceunit=4 OID=",
            "#e# " + TIMESTAMP + " 730 //PROJECT/254/251/1 - new level=255 sourceunit=4 ramptime=0",
            "#e# " + TIMESTAMP + " 730 //PROJECT/254/56/1 - new level=255 sourceunit=4 ramptime=0 arbitrary",
            "#s# lighting on //PROJECT/254/56/1  #sourceunit=" + "4" * 5000 + " OID=",
            "#e# " + TIMESTAMP + " 730 //PROJECT/254/56/1 - new level=" + "4" * 5000 + " sourceunit=4 ramptime=0",
        ]
        for raw in unknown:
            with self.subTest(raw=raw):
                record = parse_event(raw)
                self.assertIsNone(project_lighting_event(record))
                self.assertFalse(LightingEventFilter(group=1).matches(record))
                self.assertTrue(LightingEventFilter().matches(record))

    def test_exact_address_spelling_and_no_oid_column(self):
        raw = "#e# " + TIMESTAMP + " 730 //ProjectCase/nUpstairs/56/1 new level=255 sourceunit=4 ramptime=0"
        projection = project_lighting_event(parse_event(raw))
        self.assertEqual((projection.address, projection.project, projection.network),
                         ("//ProjectCase/nUpstairs/56/1", "ProjectCase", "nUpstairs"))
        self.assertIsNone(projection.oid)

    def test_filters_and_literal_zero(self):
        record = parse_event("#s# lighting off //PROJECT/254/56/1  #sourceunit=0 OID=")
        self.assertEqual(project_lighting_event(record).source_unit, 0)
        self.assertTrue(LightingEventFilter(56, 1, 0).matches(record))
        self.assertFalse(LightingEventFilter(56, 1, 4).matches(record))
        self.assertFalse(LightingEventFilter(48, 1, 0).matches(record))
        self.assertFalse(LightingEventFilter(56, 2, 0).matches(record))
        overflow = parse_event("###!!!Event buffer overflow. Events have been missed.!!!###")
        self.assertTrue(LightingEventFilter(48, 2, 255).matches(overflow))
        for kwargs in ({"application": 47}, {"application": 96}, {"group": -1},
                       {"source_unit": 256}, {"group": True}, {"source_unit": "4"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                LightingEventFilter(**kwargs)


class LightingCLIEventsTests(unittest.TestCase):
    def invoke(self, address, *options):
        host, port = address
        return subprocess.run([sys.executable, "-m", "cbus_toolkit", "cgate", "--host", host,
                               "--port", str(port), "--timeout", "0.5", "events", *options],
                              text=True, capture_output=True, timeout=20)

    def test_filtered_count_order_raw_time_duplicates_and_unknown(self):
        fixture = json.loads(FIXTURE.read_text())
        selected = {case["label"]: case for case in fixture["cases"]}
        raw = ["#e# lighting //PROJECT/254/56/1 on 255"]
        for label in ("on_source_4", "on_source_0", "off_source_4", "off_repeat_source_4"):
            raw.extend(original_row(row) for row in selected[label]["native_rows"])
        wire = ("[1] 200 OK.\r\n" + "\r\n".join(raw) + "\r\n").encode()
        with peer([[wire]]) as (address, commands):
            result = self.invoke(address, "--application", "56", "--group", "1", "--source-unit", "4", "--count", "6")
            self.assertEqual(result.returncode, 0, result.stderr)
            items = [json.loads(line) for line in result.stdout.splitlines()]
            rows, summary = items[:-1], items[-1]
            expected_raw = [original_row(row) for label in ("on_source_4", "off_source_4", "off_repeat_source_4")
                            for row in selected[label]["native_rows"] if "sourceunit=4" in row]
            self.assertEqual([row["raw"] for row in rows], expected_raw)
            self.assertEqual([row["lighting"]["level"] for row in rows], [255, 255, 0, 0, 0, 0])
            self.assertTrue(all(row["lighting"]["source_unit"] == 4 for row in rows))
            self.assertEqual([row["timestamp"] for row in rows], [TIMESTAMP, None] * 3)
            self.assertEqual(summary, {"type": "event-summary", "received": 6, "events_lost": False,
                                       "observed": len(raw), "filtered": len(raw) - 6,
                                       "filters": {"application": 56, "group": 1, "source_unit": 4}})
            self.assertEqual(commands, [b"[1] EVENT e8s1c1\r\n"])

    def test_overflow_cannot_be_hidden(self):
        wire = b"[1] 200 OK.\r\n#s# unknown\r\n###!!!Event buffer overflow. Events have been missed.!!!###\r\n"
        with peer([[wire]]) as (address, commands):
            result = self.invoke(address, "--source-unit", "4", "--count", "2")
            self.assertEqual(result.returncode, 1, result.stderr)
            event, summary = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(event["category"], "overflow")
            self.assertIsNone(event["lighting"])
            self.assertTrue(summary["events_lost"])
            self.assertEqual((summary["received"], summary["observed"], summary["filtered"]), (1, 2, 1))
            self.assertEqual(commands, [b"[1] EVENT e8s1c1\r\n"])

    def test_default_json_shape_and_opaque_rows_are_unchanged(self):
        raw = "#e# lighting //PROJECT/254/56/1 on 255"
        with peer([[("[1] 200 OK.\r\n" + raw + "\r\n").encode()]]) as (address, _):
            result = self.invoke(address)
            self.assertEqual(result.returncode, 0, result.stderr)
            event, summary = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(event, {"type": "event", "category": "event", "text": raw[4:],
                                     "raw": raw, "timestamp": None, "code": None})
            self.assertEqual(summary, {"type": "event-summary", "received": 1, "events_lost": False})

    def test_disconnect_after_filtered_opaque_record_fails_without_replay(self):
        with peer([[b"[1] 200 OK.\r\n#e# lighting //PROJECT/254/56/1 on 255\r\n"]]) as (address, commands):
            result = self.invoke(address, "--source-unit", "4")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("connection ended", json.loads(result.stderr)["error"])
            self.assertEqual(commands, [b"[1] EVENT e8s1c1\r\n"])

    def test_invalid_selectors_fail_before_connection(self):
        for options in (("--application", "47"), ("--application", "96"), ("--group", "256"), ("--source-unit", "-1")):
            with self.subTest(options=options), peer([]) as (address, commands):
                result = self.invoke(address, *options)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(commands, [])

    def test_overflow_result_is_independent_of_client_flag(self):
        from cbus_toolkit.cli import build_parser, _cgate
        client = mock.Mock(events_lost=False)
        client.__enter__ = mock.Mock(return_value=client)
        client.__exit__ = mock.Mock(return_value=False)
        overflow = parse_event("###!!!Event buffer overflow. Events have been missed.!!!###")
        args = build_parser().parse_args(["cgate", "events"])
        # Preserve library callers that constructed the old argument shape.
        del args.application, args.group, args.source_unit
        with mock.patch("cbus_toolkit.cgate.CGateClient", return_value=client), \
                mock.patch("cbus_toolkit.events.NativeEvents") as monitor_class, \
                contextlib.redirect_stdout(io.StringIO()):
            monitor_class.return_value.read.return_value = overflow
            summary, status = _cgate(args)
        self.assertEqual(status, 1)
        self.assertEqual(summary, {"type": "event-summary", "received": 1, "events_lost": True})


if __name__ == "__main__":
    unittest.main()
