"""Public CLI bounded export against one explicitly owned loopback wire peer."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.large_xml_export import MAX_XML_BYTES, limits
from test_cgate import peer


class LargeXmlExportTest(unittest.TestCase):
    def args(self, address, output, limit=None):
        tokens = ["cgate", "--host", address[0], "--port", str(address[1]),
                  "database", "get-xml", "//SYNTH", "--output", str(output)]
        if limit is not None:
            tokens += ["--max-xml-bytes", str(limit)]
        return cli.build_parser().parse_args(tokens)

    def test_large_single_line_exceeds_old_line_and_response_limits(self):
        # 17 MiB is above the old 4 MiB CLI line and 16 MiB response bounds,
        # but below the separately documented owned-server 32 MiB wire cap.
        raw = b"<Installation><Note>" + b"x" * (17 * 1024 * 1024) + b"</Note></Installation>"
        reply = [b"[1] 347-" + raw + b"\r\n[1] 344 End XML snippet\r\n"]
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "large.xml"
            with peer([reply], connection_timeout=5) as (address, sent):
                with self.assertRaisesRegex(RuntimeError, "line.*limit"):
                    cli.run(self.args(address, destination))
                self.assertFalse(destination.exists())
            self.assertEqual(sent, [b"[1] DBGETXML //SYNTH\r\n"])
            with peer([reply], connection_timeout=5) as (address, sent):
                result, status = cli.run(self.args(address, destination, len(raw)))
            self.assertEqual(status, 0)
            self.assertEqual(destination.read_bytes(), raw)
            self.assertEqual(result["bytes"], len(raw))
            self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(sent, [b"[1] DBGETXML //SYNTH\r\n"])

    def test_declared_document_limit_and_wire_limit_publish_nothing_and_never_replay(self):
        for raw in (b"<Note>" + b"x" * 128 + b"</Note>", b"x" * (70 * 1024)):
            with self.subTest(size=len(raw)), tempfile.TemporaryDirectory() as folder:
                destination = Path(folder) / "rejected.xml"
                with peer([[b"[1] 347-" + raw + b"\r\n[1] 344 End XML snippet\r\n"]]) as (address, sent):
                    with self.assertRaises((ValueError, RuntimeError)):
                        cli.run(self.args(address, destination, 64))
                self.assertFalse(destination.exists())
                self.assertEqual(list(Path(folder).iterdir()), [])
                self.assertEqual(sent, [b"[1] DBGETXML //SYNTH\r\n"])

    def test_non_success_reply_and_existing_destination_never_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "out.xml"
            with peer([[b"[1] 347-<Note/>\r\n[1] 500 Read failed\r\n"]]) as (address, sent):
                with self.assertRaises(RuntimeError):
                    cli.run(self.args(address, destination, 1024))
            self.assertFalse(destination.exists())
            self.assertEqual(sent, [b"[1] DBGETXML //SYNTH\r\n"])
            destination.write_bytes(b"preserve")
            with patch("cbus_toolkit.cgate.CGateClient", side_effect=AssertionError("must not connect")):
                with self.assertRaisesRegex(ValueError, "already exists"):
                    cli.run(self.args(("127.0.0.1", 1), destination, 1024))
            self.assertEqual(destination.read_bytes(), b"preserve")

    def test_unsolicited_event_overflow_stops_export_without_replay(self):
        wire = b"#e# first-event\r\n#e# second-event\r\n[1] 347-<Note/>\r\n[1] 344 End XML snippet\r\n"
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "out.xml"
            with peer([[wire]]) as (address, sent):
                with self.assertRaisesRegex(RuntimeError, "event queue"):
                    cli.run(self.args(address, destination, 1024))
            self.assertFalse(destination.exists())
            self.assertEqual(sent, [b"[1] DBGETXML //SYNTH\r\n"])

    def test_option_is_export_only_and_preflight_bounds_are_explicit(self):
        selected = cli.build_parser().parse_args(["cgate", "database", "get-xml", "//SYNTH"])
        self.assertEqual(limits(selected), {})
        with patch("cbus_toolkit.cgate.CGateClient", side_effect=AssertionError("must not connect")):
            for limit in (0, -1, MAX_XML_BYTES + 1, True):
                selected.max_xml_bytes = limit
                with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "integer"):
                    cli.run(selected)
            selected.max_xml_bytes = 1024
            with self.assertRaisesRegex(ValueError, "requires --output"):
                cli.run(selected)
        selected.output = Path("unused.xml")
        selected.max_xml_bytes = MAX_XML_BYTES
        self.assertEqual(limits(selected)["max_response_bytes"], MAX_XML_BYTES + 65536)
