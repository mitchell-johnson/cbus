import json
import os
import subprocess
import sys
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.events import NativeEvents, parse_event
from test_cgate import peer


class EventTests(unittest.TestCase):
    def test_parse_preserves_raw_event_and_native_timestamp_without_inventing_timezone(self):
        raw = "#e# 20260915-012345.678 751 //HOME/254/p/4 unit ready"
        record = parse_event(raw)
        self.assertEqual((record.category, record.timestamp, record.code), ("event", "20260915-012345.678", 751))
        self.assertEqual(record.text, "//HOME/254/p/4 unit ready")
        self.assertEqual(record.raw, raw)
        self.assertEqual(parse_event("#s# //HOME/254 state=ok").category, "status")
        self.assertEqual(parse_event("#c# //HOME/254/p/4 changed").category, "configuration")
        self.assertEqual(parse_event("20260915-012345 751 Ready").code, 751)
        for invalid in ("200 OK.", "[1] 200 OK.", "#s# x\ny", None):
            with self.assertRaises(ValueError):
                parse_event(invalid)

    def test_subscription_state_and_interleaved_events(self):
        responses = [[b"#s# before\r\n[1] 200 OK.\r\n"],
                     [b"#c# after\r\n[2] 200 OK.\r\n"]]
        with peer(responses) as (address, commands), CGateClient(*address) as client:
            monitor = NativeEvents(client)
            monitor.subscribe()
            monitor.request_state("//HOME/254")
            self.assertEqual(monitor.read().text, "before")
            self.assertEqual(monitor.read().text, "after")
            self.assertEqual(commands, [b"[1] EVENT e8s1c1\r\n", b"[2] GETSTATE //HOME/254\r\n"])

    def test_invalid_modes_rejected_without_io(self):
        monitor = NativeEvents(None)
        for invalid in ("e10s1c1", "e8s2c0", "e8s1c2", "ON\nNOOP", "", None):
            with self.assertRaises(ValueError):
                monitor.subscribe(invalid)

    def test_cli_streams_json_lines_and_fails_if_events_are_lost(self):
        overflow = b"###!!!Event buffer overflow. Events have been missed.!!!###"
        for records, expected in ((b"#s# ready\r\n#c# changed", 0), (overflow, 1)):
            with peer([[b"[1] 200 OK.\r\n" + records + b"\r\n"]]) as ((host, port), commands):
                result = subprocess.run([sys.executable, "-m", "cbus_toolkit", "cgate", "--host", host,
                                         "--port", str(port), "events", "--count", "2"], text=True, capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                items = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(items[-1]["type"], "event-summary")
                self.assertEqual(items[-1]["events_lost"], bool(expected))
                self.assertTrue(all(item["type"] == "event" for item in items[:-1]))


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "set CBUS_CGATE_TEST_HOST for native event acceptance")
class NativeEventTests(unittest.TestCase):
    def test_native_configuration_stream_observes_owned_project_creation(self):
        project = "E" + uuid4().hex[:7].upper()
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        with CGateClient(host, port, timeout=5) as stream, CGateClient(host, port, timeout=5) as writer:
            monitor = NativeEvents(stream)
            monitor.subscribe("e8s1c1")
            writer.command("PROJECT NEW " + project)
            try:
                records = []
                for _ in range(100):
                    event = monitor.read()
                    records.append(event)
                    if project in event.raw:
                        break
                self.assertTrue(any(project in event.raw for event in records))
                self.assertFalse(stream.events_lost)
                monitor.subscribe("OFF")
                self.assertEqual(stream.command("NOOP").code, 200)
            finally:
                writer.command("PROJECT CLOSE " + project)


if __name__ == "__main__":
    unittest.main()
