"""Wire fixtures use literal protocol records, independently of client framing."""
from __future__ import annotations

import contextlib
import os
import shutil
import ssl
import subprocess
import tempfile
from pathlib import Path
import socket
import socketserver
import threading
import time
import unittest
from unittest import mock

from cbus_toolkit.cgate import CGateClient, CGateError


@contextlib.contextmanager
def peer(responses, *, greeting=(b"201 Service ready: fixture\r\n",), pause=0.0, tls_context=None):
    commands = []
    failures = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(1)
            try:
                for fragment in greeting:
                    self.connection.sendall(fragment)
                for fragments in responses:
                    command = self.rfile.readline()
                    if not command:
                        return
                    commands.append(command)
                    if pause:
                        time.sleep(pause)
                    for fragment in fragments:
                        if isinstance(fragment, float):
                            time.sleep(fragment)
                        else:
                            self.connection.sendall(fragment)
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                pass  # Expected when timeout/limit tests close their connection.
            except BaseException as exc:
                failures.append(exc)

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

        def get_request(self):
            connection, address = super().get_request()
            if tls_context is not None:
                try:
                    connection.settimeout(1)
                    connection = tls_context.wrap_socket(connection, server_side=True)
                except BaseException:
                    connection.close()
                    raise
            return connection, address

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_address, commands
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        if failures:
            raise failures[0]


class CGateTests(unittest.TestCase):
    def test_interrupted_connect_invalidates_socket_and_preserves_interruption(self):
        for interruption in (KeyboardInterrupt, SystemExit):
            for close_error in (None, OSError('close failed')):
                with self.subTest(interruption=interruption, close_error=close_error):
                    client = CGateClient('127.0.0.1')
                    client._buffer.extend(b'partial abandoned reply')
                    sock = mock.Mock()
                    sock.close.side_effect = close_error
                    with mock.patch('socket.create_connection', return_value=sock), \
                            mock.patch.object(client, '_readline', side_effect=interruption):
                        with self.assertRaises(interruption):
                            client.connect()
                    self.assertFalse(client.connected)
                    self.assertEqual(client._buffer, bytearray())
                    sock.close.assert_called_once_with()

    def test_interrupted_command_cannot_reuse_stream_or_replay_write(self):
        for interruption in (KeyboardInterrupt, SystemExit):
            with self.subTest(interruption=interruption), peer([
                    [b'[1] 200 OK.\r\n'], [b'[2] 200 OK.\r\n']]) as (address, sent):
                client = CGateClient(*address).connect()
                try:
                    with mock.patch.object(client, '_readline', side_effect=interruption):
                        with self.assertRaises(interruption):
                            client.command('ON //HOME/254/56/1')
                    self.assertFalse(client.connected)
                    with self.assertRaisesRegex(RuntimeError, 'connect.*explicitly'):
                        client.command('ON //HOME/254/56/1')
                finally:
                    client.close()
            self.assertEqual(sent, [b'[1] ON //HOME/254/56/1\r\n'])

    def test_interrupted_event_read_invalidates_the_stream(self):
        with peer([]) as (address, sent):
            client = CGateClient(*address).connect()
            with mock.patch.object(client, '_readline', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    client.read_event()
            self.assertFalse(client.connected)
            self.assertEqual(sent, [])

    def test_document_body_is_sent_once_under_one_command_id(self):
        with peer([[], [], [], [b"[1] 380-Imported\r\n[1] 200 OK.\r\n"],
                   [b"[2] 200 OK.\r\n"]]) as (address, sent):
            with CGateClient(*address) as client:
                reply = client.command_document("CGL IMPORT HOME", '{\r\n"name": "Lounge"}')
                self.assertEqual(reply.code, 200)
                self.assertEqual(client.command("NOOP").code, 200)
            delimiter = sent[0].decode().strip().split(" << ")[1]
            self.assertEqual(sent, [f"[1] CGL IMPORT HOME << {delimiter}\r\n".encode(),
                                    b'{\n', b'"name": "Lounge"}\n',
                                    delimiter.encode() + b"\r\n", b"[2] NOOP\r\n"])

    def test_document_preflight_rejects_unsafe_commands_and_limits(self):
        with peer([[b"[1] 200 OK.\r\n"]]) as (address, sent):
            with CGateClient(*address, max_line_bytes=100, max_response_bytes=200) as client:
                for cmd, body in [("NOOP", "PROJECT DELETE HOME"), ("CGL IMPORT HOME << x", "{}"),
                                  ("CGL IMPORT HOME\nNOOP", "{}"), ("CGL IMPORT HOME", ""),
                                  ("CGL IMPORT HOME", "a\rb"), ("CGL IMPORT HOME", "\x00"),
                                  ("CGL IMPORT HOME", "a" * 101),
                                  ("CGL IMPORT HOME", "a\n" * 101),
                                  ("CGL IMPORT HOME", "\ud800")]:
                    with self.subTest(cmd=cmd, length=len(body)), self.assertRaises(ValueError):
                        client.command_document(cmd, body)
                client.command("NOOP")
            self.assertEqual(sent, [b"[1] NOOP\r\n"])

    def test_document_failure_keeps_following_command_synchronized(self):
        with peer([[], [], [b"[1] 400 Invalid CGL\r\n"], [b"[2] 200 OK.\r\n"]]) as (address, _):
            with CGateClient(*address) as client:
                with self.assertRaises(CGateError):
                    client.command_document("CGL IMPORT HOME", "{}")
                self.assertEqual(client.command("NOOP").code, 200)

    def test_fragmented_greeting_and_two_tagged_commands(self):
        with peer([[b"[1] 20", b"0 OK.\r", b"\n"], [b"[2] 300 level=255\r\n"]],
                  greeting=(b"20", b"1 Service ", b"ready\r", b"\n")) as (address, sent):
            with CGateClient(*address) as client:
                self.assertEqual(client.greeting, "201 Service ready")
                self.assertEqual(client.command("NOOP").lines, ("200 OK.",))
                reply = client.command("GET //HOME/254/56/1 level")
                self.assertEqual(reply.status, 300)
                self.assertEqual(reply.code, 300)
                self.assertEqual(reply.final, "300 level=255")
                self.assertTrue(reply.successful)
            self.assertFalse(client.connected)
            self.assertEqual(sent, [b"[1] NOOP\r\n", b"[2] GET //HOME/254/56/1 level\r\n"])

    def test_informational_final_ends_reply_without_waiting_for_2xx(self):
        with peer([[b"[1] 101-Help: line one\r\n[1] 101 line two\r\n"],
                   [b"[2] 123 project=HOME state=stopped\r\n"]]) as (address, _):
            with CGateClient(*address) as client:
                reply = client.command("HELP")
                self.assertEqual(reply.lines, ("101-Help: line one", "101 line two"))
                self.assertEqual(reply.code, 101)
                self.assertEqual(client.command("PROJECT LIST").code, 123)

    def test_events_separate_from_multiline_reply(self):
        events = ["#e# 20260914-120001 734 response: 200 OK.",
                  "#s# lighting on //HOME/254/56/1 255 #sourceunit=1",
                  "#c# dbchange //HOME/254",
                  "20260914-120002.123 702 //HOME/254 network open",
                  "###!!!Event buffer overflow. Events have been missed.!!!###"]
        raw = (events[0] + "\r\n[1] 300-one\r\n" + "\r\n".join(events[1:]) +
               "\r\n[1] 300 two\r\n").encode()
        with peer([[raw]]) as (address, _):
            with CGateClient(*address) as client:
                reply = client.command("GET //HOME/254/* level")
                self.assertEqual(reply.lines, ("300-one", "300 two"))
                self.assertEqual(list(client.events), events)
                self.assertTrue(client.events_lost)
                self.assertEqual([client.read_event() for _ in events], events)
                self.assertEqual(len(client.events), 0)

    def test_xml_payload_and_mixed_native_line_endings(self):
        # C-Gate 3.4 DBGETXML emits LF after its XML declaration. Some multiline
        # XML payload lines also have a tag without a repeated numeric code.
        raw = (b'[1] 343-Begin XML snippet\r\n'
               b'[1] 347-<?xml version="1.0" encoding="utf-8"?>\n'
               b'[1] <Project>\n[1]   <TagName>HOME</TagName>\r\n'
               b'[1] </Project>\r\n[1] 344 End XML snippet\r\n')
        with peer([[bytes([b]) for b in raw]]) as (address, _):
            with CGateClient(*address) as client:
                reply = client.command("DBGETXML //HOME")
                self.assertEqual(reply.status, 344)
                self.assertEqual(reply.lines[2:5], ("<Project>", "  <TagName>HOME</TagName>", "</Project>"))

    def test_six_hundred_confirmation_is_returned(self):
        with peer([[b"[1] 600 Please confirm\r\n"]]) as (address, _):
            with CGateClient(*address) as client:
                reply = client.command("RESTART")
                self.assertEqual(reply.status, 600)
                self.assertFalse(reply.successful)

    def test_server_error_attaches_reply_and_connection_stays_synchronized(self):
        for status in (400, 401, 500):
            with self.subTest(status=status), peer([
                    [f"[1] {status}-details\r\n[1] {status} Failed\r\n".encode()],
                    [b"[2] 200 OK.\r\n"]]) as (address, _):
                with CGateClient(*address) as client:
                    with self.assertRaises(CGateError) as raised:
                        client.command("BOGUS")
                    self.assertEqual(raised.exception.response.code, status)
                    self.assertEqual(len(raised.exception.response.lines), 2)
                    self.assertTrue(client.connected)
                    self.assertEqual(client.command("NOOP").status, 200)

    def test_login_error_and_success_do_not_echo_credentials(self):
        for status in (200, 401):
            with self.subTest(status=status), peer([
                    [f"[1] {status} LOGIN admin very-secret rejected\r\n".encode()]]) as (address, sent):
                with CGateClient(*address) as client:
                    try:
                        result = client.command("login admin very-secret")
                    except CGateError as exc:
                        result = (str(exc), repr(exc.response))
                    self.assertNotIn("very-secret", str(result))
                    self.assertNotIn("admin", str(result))
                self.assertEqual(sent, [b"[1] login admin very-secret\r\n"])

    def test_command_injection_rejected_without_sending(self):
        with peer([[b"[1] 200 OK.\r\n"]]) as (address, sent):
            with CGateClient(*address) as client:
                for command in ("NOOP\r\nRESTART", "NOOP\n", "\x00", "\x7f", "", "  ", "[2] NOOP"):
                    with self.subTest(command=repr(command)), self.assertRaises(ValueError):
                        client.command(command)
                self.assertEqual(sent, [])
                client.command("NOOP")
            self.assertEqual(sent, [b"[1] NOOP\r\n"])

    def test_bad_greeting_closes(self):
        for raw in (b"400 Access denied\r\n", b"[1] 201 wrong\r\n", b"201-invalid\r\n"):
            with self.subTest(raw=raw), peer([], greeting=(raw,)) as (address, _):
                client = CGateClient(*address)
                with self.assertRaises(RuntimeError):
                    client.connect()
                self.assertFalse(client.connected)

    def test_wrong_id_missing_id_and_invalid_payload_close(self):
        for raw in (b"[9] 200 OK\r\n", b"200 OK\r\n", b"[1] <XML>\r\n",
                    b"[1] 200 a\rb\r\n", b"[1] 200 a\x00b\r\n", b"[1] 200 \xff\r\n"):
            with self.subTest(raw=raw), peer([[raw]]) as (address, _):
                with CGateClient(*address) as client:
                    with self.assertRaises(RuntimeError):
                        client.command("NOOP")
                    self.assertFalse(client.connected)

    def test_eof_before_final_response_is_failure(self):
        with peer([[b"[1] 300-more\r\n[1] 300 incom"]]) as (address, _):
            with CGateClient(*address) as client:
                with self.assertRaisesRegex(RuntimeError, "ended before"):
                    client.command("GET x")
                self.assertFalse(client.connected)

    def test_timeout_closes_without_retransmitting(self):
        with peer([[b"[1] 200 OK\r\n"]], pause=0.2) as (address, sent):
            with CGateClient(*address, timeout=0.04) as client:
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    client.command("SET target level 255")
                self.assertFalse(client.connected)
                with self.assertRaisesRegex(RuntimeError, "not connected"):
                    client.command("SET target level 255")
            self.assertEqual(sent, [b"[1] SET target level 255\r\n"])

    def test_deadline_is_not_extended_by_incoming_lines(self):
        with peer([[b"[1] 300-first\r\n", 0.035, b"[1] 300-second\r\n",
                    0.035, b"[1] 300 final\r\n"]]) as (address, _):
            with CGateClient(*address, timeout=0.055) as client:
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    client.command("GET x")
                self.assertFalse(client.connected)

    def test_line_response_and_event_limits(self):
        cases = [({"max_line_bytes": 40}, b"[1] 300-" + b"x" * 41),
                 ({"max_response_bytes": 35}, b"[1] 300-first\r\n[1] 300-second\r\n[1] 300 last\r\n"),
                 ({"max_response_lines": 1}, b"[1] 300-first\r\n[1] 300 last\r\n"),
                 ({"max_events": 1}, b"#s# first\r\n#s# second\r\n[1] 200 OK\r\n")]
        for limits, raw in cases:
            with self.subTest(limits=limits), peer([[raw]]) as (address, _):
                with CGateClient(*address, **limits) as client:
                    with self.assertRaisesRegex(RuntimeError, "limit"):
                        client.command("NOOP")
                    self.assertFalse(client.connected)

    def test_command_length_rejected_before_send(self):
        with peer([[b"[1] 200 OK\r\n"]]) as (address, sent):
            with CGateClient(*address, max_line_bytes=40) as client:
                with self.assertRaises(ValueError):
                    client.command("X" * 40)
                client.command("NOOP")
            self.assertEqual(sent, [b"[1] NOOP\r\n"])

    def test_read_new_event_from_buffer_after_command(self):
        with peer([[b"[1] 200 OK\r\n#e# 20260914-120000 702 //HOME/254 open\r\n"]]) as (address, _):
            with CGateClient(*address) as client:
                client.command("EVENT e1s0c0")
                self.assertEqual(client.read_event(), "#e# 20260914-120000 702 //HOME/254 open")

    def test_tls_uses_supplied_context_and_server_hostname(self):
        context = mock.Mock()
        context.wrap_socket.side_effect = lambda sock, **_kwargs: sock
        with peer([[b"[1] 200 OK\r\n"]]) as (address, _):
            with CGateClient(*address, ssl_context=context) as client:
                client.command("NOOP")
            self.assertEqual(context.wrap_socket.call_args.kwargs, {"server_hostname": "127.0.0.1"})

    def test_invalid_connection_options(self):
        for options in ({"timeout": 0}, {"timeout": float("nan")}, {"timeout": float("inf")},
                        {"port": 0}, {"port": 65536}, {"port": True}, {"max_events": 0},
                        {"max_line_bytes": 1.5}, {"max_response_lines": -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                CGateClient("localhost", **options)

    def test_explicit_connect_required_and_close_idempotent(self):
        client = CGateClient("localhost")
        with self.assertRaises(RuntimeError):
            client.command("NOOP")
        client.close()
        client.close()


@unittest.skipUnless(shutil.which("openssl") and ssl.HAS_TLSv1_3,
                     "TLS 1.3 and openssl executable are required for real TLS tests")
class CGateTLSVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="cbus-cgate-tls-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        extensions = cls.directory / "extensions.cnf"
        extensions.write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\n"
                              "extendedKeyUsage=serverAuth\n"
                              "keyUsage=critical,digitalSignature,keyEncipherment\n"
                              "basicConstraints=critical,CA:FALSE\n"
                              "subjectKeyIdentifier=hash\n"
                              "authorityKeyIdentifier=keyid,issuer\n")
        (cls.directory / "ca.cnf").write_text(
            "[req]\ndistinguished_name=dn\nx509_extensions=v3_ca\nprompt=no\n"
            "[dn]\nCN=C-Bus test CA\n[v3_ca]\nbasicConstraints=critical,CA:TRUE\n"
            "keyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n"
            "authorityKeyIdentifier=keyid:always\n")
        commands = [
            ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
             "-config", "ca.cnf", "-keyout", "ca.key", "-out", "ca.pem"],
            ["req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=localhost",
             "-keyout", "server.key", "-out", "server.csr"],
            ["x509", "-req", "-in", "server.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
             "-CAcreateserial", "-days", "1", "-extfile", "extensions.cnf", "-out", "server.pem"],
        ]
        for command in commands:
            subprocess.run([shutil.which("openssl"), *command], cwd=cls.directory,
                           check=True, capture_output=True, timeout=15)

    def server_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(str(self.directory / "server.pem"), str(self.directory / "server.key"))
        return context

    def test_tls13_trusted_ca_hostname_verification_and_command(self):
        context = ssl.create_default_context(cafile=str(self.directory / "ca.pem"))
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        with peer([[b"[1] 200 OK.\r\n"]], tls_context=self.server_context()) as (address, sent):
            with CGateClient(*address, ssl_context=context) as client:
                self.assertEqual(client._socket.version(), "TLSv1.3")
                self.assertEqual(client.command("NOOP").status, 200)
            self.assertEqual(sent, [b"[1] NOOP\r\n"])

    def test_tls13_untrusted_ca_rejected_before_command(self):
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        with peer([[b"[1] 200 OK.\r\n"]], tls_context=self.server_context()) as (address, sent):
            client = CGateClient(*address, ssl_context=context)
            with self.assertRaisesRegex(RuntimeError, "Unable to establish"):
                client.connect()
            self.assertFalse(client.connected)
            self.assertEqual(sent, [])
            with self.assertRaisesRegex(RuntimeError, "not connected"):
                client.command("LOGIN admin very-secret")

    def test_tls13_hostname_mismatch_rejected_even_with_trusted_ca(self):
        context = ssl.create_default_context(cafile=str(self.directory / "ca.pem"))
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        create_connection = socket.create_connection
        with peer([[b"[1] 200 OK.\r\n"]], tls_context=self.server_context()) as (address, sent):
            # Route a deliberately mismatched DNS hostname to the local test
            # server, preserving the true TLS hostname verification step.
            with mock.patch("cbus_toolkit.cgate.socket.create_connection",
                            side_effect=lambda _address, timeout: create_connection(address, timeout)):
                client = CGateClient("wrong-host.invalid", address[1], ssl_context=context)
                with self.assertRaisesRegex(RuntimeError, "Unable to establish"):
                    client.connect()
                self.assertFalse(client.connected)
            self.assertEqual(sent, [])


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for C-Gate acceptance tests")
class NativeCGateTests(unittest.TestCase):
    """Server acceptance using read-only queries and an owned XML fixture."""

    def test_native_command_surface_and_information_framing(self):
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"],
                         int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            self.assertIn("C-Gate", client.greeting)
            self.assertEqual(client.command("NOOP").status, 200)
            self.assertTrue(client.command("HELP NOOP").successful)
            self.assertTrue(client.command("PROJECT LIST").successful)
            with self.assertRaises(CGateError):
                client.command("THIS_IS_NOT_A_CGATE_COMMAND")
            self.assertEqual(client.command("NOOP").status, 200)

    def test_native_xml_framing(self):
        from uuid import uuid4
        project = "Q" + uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"],
                         int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            client.command("PROJECT NEW " + project)
            try:
                reply = client.command("DBGETXML //" + project)
                self.assertEqual(reply.status, 344)
                self.assertTrue(any("<Installation>" in line or "<Project>" in line for line in reply.lines))
                self.assertEqual(client.command("NOOP").status, 200)
            finally:
                client.command("PROJECT CLOSE " + project)


if __name__ == "__main__":
    unittest.main()
