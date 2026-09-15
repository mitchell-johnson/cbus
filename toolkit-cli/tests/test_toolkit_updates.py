from dataclasses import replace
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch

from cbus_toolkit.toolkit_updates import (
    CATALOGUE_HOST, CATALOGUE_PATH, CATALOGUE_URL, CatalogueHTTPReply,
    HTTPSCatalogueTransport, ToolkitUpdateCatalogue, catalogue_request, toolkit_download_link,
)
from cbus_toolkit.toolkit_preferences_initial_state import constructor_state

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/toolkit-updates-vectors.json'


def fixture():
    return json.loads(FIXTURE.read_text())


def captured():
    return fixture()['collection_cases'][0]['input']['body'].encode('utf-8')


def reply(body=None, status=200):
    body = captured() if body is None else body
    return CatalogueHTTPReply(status, (), body, len(body), True, True)


class Transport:
    def __init__(self, result=None):
        self.result = result if result is not None else reply()
        self.calls = []; self.last_reply = None

    def post(self, body, **kwargs):
        self.calls.append((body, kwargs)); self.last_reply = self.result
        return self.result


class Response:
    status = 200
    def __init__(self, chunks, headers=(), close_error=None):
        self.chunks = list(chunks); self.headers = headers; self.close_error = close_error; self.closed = 0
    def getheaders(self): return self.headers
    def read(self, count):
        item = self.chunks.pop(0) if self.chunks else b''
        if isinstance(item, BaseException): raise item
        return item
    def close(self):
        self.closed += 1
        if self.close_error: raise self.close_error


class Connection:
    def __init__(self, response, close_error=None):
        self.response = response; self.close_error = close_error; self.closed = 0; self.requests = []
    def request(self, *args, **kwargs): self.requests.append((args, kwargs))
    def getresponse(self): return self.response
    def close(self):
        self.closed += 1
        if self.close_error: raise self.close_error


class UpdateTests(unittest.TestCase):
    def test_original_menu_vectors_and_explicit_nul_exclusion(self):
        values = constructor_state()['values']
        for row in fixture()['menu']['cases']:
            values['CISDownloadsURL'] = row['preference_string']
            if '\0' in values['CISDownloadsURL']:
                with self.assertRaises(ValueError): toolkit_download_link(values)
                continue
            result = toolkit_download_link(values).as_dict()
            self.assertEqual(result['url'], row['calls'][-1]['file'])
            self.assertEqual(result['original_verb'], 'open'); self.assertEqual(result['original_show'], 1)
            self.assertFalse(result['version_comparison_performed']); self.assertFalse(result['browser_opened'])
            self.assertFalse(result['original_launch_result_checked']); self.assertIsNone(result['updates_available'])
        with self.assertRaises(ValueError): toolkit_download_link({'CISDownloadsURL': 'https://example.invalid'})

    def test_original_serializer_literals_and_raw_version_domain(self):
        for row in fixture()['collection_cases']:
            version = row['input']['version']
            if not version:
                with self.assertRaises(ValueError): catalogue_request(version)
                continue
            self.assertEqual(catalogue_request(version).decode(), row['request']['body'])
        for version in (True, 1, 'x'*257, '\0', '\ud800'):
            with self.assertRaises(ValueError): catalogue_request(version)

    def test_captured_seven_candidates_preserve_order_links_and_unverified_flags(self):
        transport = Transport(); outcome = ToolkitUpdateCatalogue(transport).query('1.18.0')
        value = outcome.as_dict(); original = json.loads(captured())['data']
        self.assertTrue(value['complete']); self.assertEqual(len(value['candidates']), 7)
        self.assertEqual([x['node_id'] for x in value['candidates']], [x['nodeId'] for x in original])
        for observed, expected in zip(value['candidates'], original):
            self.assertEqual(observed['name'], expected['nodeName'])
            self.assertEqual(observed['additional_info_urls'], expected['data']['additionalInfoUrl'])
            self.assertEqual(observed['files'][0]['url'], expected['files'][0]['url'])
            self.assertTrue(observed['metadata_signature_present'])
            self.assertFalse(observed['metadata_signature_verified']); self.assertFalse(observed['applicability_verified'])
            self.assertIsNone(observed['version'])
        self.assertIsNone(value['updates_available']); self.assertIsNone(value['latest_version'])
        self.assertFalse(value['downloaded']); self.assertFalse(value['installed'])
        self.assertEqual(value['http']['body_sha256'], '4444edb826360c2909b740c6152bc2d9f76f6ce471400cda1bbaf49dfbe97ad9')
        self.assertEqual(len(transport.calls), 1)
        value['candidates'][0]['display_names']['default'] = 'not retained'
        self.assertNotEqual(value, outcome.as_dict())

    def test_original_error_differences_are_explicit_and_never_up_to_date(self):
        names = {'empty-success': True, 'body-failure': False, 'http-failure': False,
                 'http-redirect': False, 'absent-data': False, 'null-data': False,
                 'truncated': False, 'duplicate-data': False, 'unknown-type': False}
        for row in fixture()['collection_cases']:
            if row['name'] not in names: continue
            data = row['input']; outcome = ToolkitUpdateCatalogue(Transport(reply(data['body'].encode(), data['status']))).query('1.18.0')
            self.assertEqual(outcome.complete, names[row['name']], row['name'])
            self.assertIsNone(outcome.as_dict()['updates_available'])
            self.assertIsNone(outcome.as_dict()['latest_version'])
            if not outcome.complete: self.assertIsNotNone(outcome.error)
        # Original lower client returned empty for this body failure; our API keeps it failed.
        row = next(x for x in fixture()['collection_cases'] if x['name'] == 'body-failure')
        self.assertEqual(row['result']['count'], 0)

    def test_json_shapes_bool_integer_confusion_limits_and_no_url_execution(self):
        baseline = json.loads(captured())
        cases = [b'[]', b'null', b'{"data":[],"success":true,"statusCode":true,"message":"x"}',
                 b'{"data":[],"success":1,"statusCode":200,"message":"x"}',
                 b'{"x":NaN}', b'{"x":1e999}', captured()+b'x',
                 b'{"data":[],"success":true,"statusCode":200,"message":"\\ud800"}']
        for mutate in (
            lambda x: x['data'].append(x['data'][0]),
            lambda x: x['data'][0]['files'][0].update(size=True),
            lambda x: x['data'][0]['files'].append(x['data'][0]['files'][0]),
            lambda x: x['data'][0]['data'].update(type='OtherData'),
            lambda x: x['data'][0].update(signatures=[]),
        ):
            value = json.loads(captured()); mutate(value); cases.append(json.dumps(value).encode())
        for body in cases:
            result = ToolkitUpdateCatalogue(Transport(reply(body))).query('1.18.0')
            self.assertFalse(result.complete); self.assertEqual(result.candidates, ())
        self.assertFalse(ToolkitUpdateCatalogue(Transport(), max_packages=6).query('1.18.0').complete)
        self.assertFalse(ToolkitUpdateCatalogue(Transport(), max_response_bytes=100).query('1.18.0').complete)
        baseline['data'][0]['files'][0]['url'] = 'file:///untrusted-candidate'
        baseline['data'][0]['data']['clientConditionData'] = {'expression': 'untrusted'}
        with patch('socket.create_connection', side_effect=AssertionError('No URL or condition execution')):
            result = ToolkitUpdateCatalogue(Transport(reply(json.dumps(baseline).encode()))).query('1.18.0')
        self.assertTrue(result.complete); self.assertFalse(result.as_dict()['applicability_verified'])

    def test_preflight_rejects_before_post_and_clears_previous_outcome(self):
        backend = Transport(); editor = ToolkitUpdateCatalogue(backend); editor.query('1.18.0')
        for timeout in (True, 0, -1, 301, float('inf'), float('nan')):
            with self.assertRaises(ValueError): editor.query('1.18.0', timeout=timeout)
            self.assertIsNone(editor.last_outcome)
        self.assertEqual(len(backend.calls), 1)
        for limits in ({'max_packages': True}, {'max_response_bytes': 0}, {'max_packages': 4097}):
            with self.assertRaises(ValueError): ToolkitUpdateCatalogue(backend, **limits)

    def test_https_request_exact_length_timeout_and_close_once(self):
        body = b'{"data":[],"success":true,"statusCode":200,"message":"ok"}'
        response = Response([body[:5], body[5:]], [('Content-Length', str(len(body)))])
        connection = Connection(response)
        with patch('cbus_toolkit.toolkit_updates.http.client.HTTPSConnection', return_value=connection) as factory:
            result = ToolkitUpdateCatalogue(HTTPSCatalogueTransport()).query('1.18.0', timeout=3)
        self.assertTrue(result.complete)
        args, kwargs = factory.call_args
        self.assertEqual(args, (CATALOGUE_HOST, 443)); self.assertEqual(kwargs['timeout'], 3)
        self.assertEqual(kwargs['context'].verify_mode, ssl.CERT_REQUIRED); self.assertTrue(kwargs['context'].check_hostname)
        self.assertEqual(connection.requests, [(('POST', CATALOGUE_PATH), {'body': catalogue_request('1.18.0'),
            'headers': {'Accept': 'application/json', 'Content-Type': 'application/json; charset=utf-8'}})])
        self.assertEqual(response.closed, 1); self.assertEqual(connection.closed, 1)

    def test_partial_reads_size_framing_and_cleanup_failure_evidence(self):
        cases = [
            (Response([b'ab', http.client.IncompleteRead(b'cd', 3)]), {}, b'abcd', 'response_body'),
            (Response([b'abc'], [('Content-Length', '4')]), {}, b'abc', 'response_body'),
            (Response([b'123456']), {'max_response_bytes': 5}, b'12345', 'response_body'),
            (Response([], [('Content-Length', '6')]), {'max_response_bytes': 5}, b'', 'response_headers'),
            (Response([], [('Content-Length', '1'), ('Content-Length', '1')]), {}, b'', 'response_headers'),
            (Response([], [('Content-Length', '1'), ('Transfer-Encoding', 'chunked')]), {}, b'', 'response_headers'),
            (Response([], [('Content-Encoding', 'gzip')]), {}, b'', 'response_headers'),
            (Response([], [('Transfer-Encoding', 'identity')]), {}, b'', 'response_headers'),
        ]
        for response, limits, retained, stage in cases:
            connection = Connection(response)
            with patch('cbus_toolkit.toolkit_updates.http.client.HTTPSConnection', return_value=connection):
                result = ToolkitUpdateCatalogue(HTTPSCatalogueTransport(), **limits).query('1.18.0')
            self.assertFalse(result.complete); self.assertEqual(result.reply.body, retained)
            self.assertEqual(result.reply.error.stage, stage); self.assertEqual(connection.closed, 1); self.assertEqual(response.closed, 1)
        response = Response([b'{}'], close_error=OSError('response close'))
        connection = Connection(response, OSError('connection close'))
        with patch('cbus_toolkit.toolkit_updates.http.client.HTTPSConnection', return_value=connection):
            result = ToolkitUpdateCatalogue(HTTPSCatalogueTransport()).query('1.18.0')
        self.assertFalse(result.complete); self.assertEqual(result.error.message, 'response close')
        self.assertEqual([x.error.message for x in result.reply.cleanup], ['response close', 'connection close'])

    def test_first_interruption_partial_evidence_and_no_replay(self):
        class Unprintable(KeyboardInterrupt):
            def __str__(self): raise SystemExit('message interrupted')
            def __setattr__(self, name, value):
                if name == 'toolkit_update_evidence': raise SystemExit('attachment interrupted')
                super().__setattr__(name, value)
        for first in (KeyboardInterrupt('first'), SystemExit('first'), Unprintable()):
            response = Response([b'prefix', first], close_error=SystemExit('secondary'))
            connection = Connection(response, KeyboardInterrupt('third'))
            editor = ToolkitUpdateCatalogue(HTTPSCatalogueTransport())
            with patch('cbus_toolkit.toolkit_updates.http.client.HTTPSConnection', return_value=connection):
                with self.assertRaises(type(first)) as observed: editor.query('1.18.0')
            self.assertIs(observed.exception, first); self.assertIs(editor.last_outcome.cause, first)
            self.assertEqual(editor.last_outcome.reply.body, b'prefix')
            self.assertEqual(response.closed, 1); self.assertEqual(connection.closed, 1); self.assertEqual(len(connection.requests), 1)
        first = OSError('transfer'); second = KeyboardInterrupt('cleanup')
        response = Response([first], close_error=second); connection = Connection(response)
        editor = ToolkitUpdateCatalogue(HTTPSCatalogueTransport())
        with patch('cbus_toolkit.toolkit_updates.http.client.HTTPSConnection', return_value=connection):
            result = editor.query('1.18.0')
        self.assertFalse(result.complete); self.assertIs(result.cause, first)
        self.assertIs(editor.last_outcome.reply.cause, first)
        self.assertEqual(editor.last_outcome.reply.cleanup[0].error.message, 'cleanup')

    def test_missing_stale_and_faulting_transport_evidence_never_replace_interrupt(self):
        first = KeyboardInterrupt('first')
        class Broken:
            def __init__(self): self.last_reply = reply()
            def post(self, *args, **kwargs): raise first
        editor = ToolkitUpdateCatalogue(Broken())
        with self.assertRaises(KeyboardInterrupt) as observed: editor.query('1.18.0')
        self.assertIs(observed.exception, first); self.assertIsNone(editor.last_outcome.reply)
        class BadExport:
            def __init__(self): self.calls = 0
            @property
            def last_reply(self):
                self.calls += 1
                if self.calls > 1: raise SystemExit('secondary')
                return None
            def post(self, *args, **kwargs): raise first
        editor = ToolkitUpdateCatalogue(BadExport())
        with self.assertRaises(KeyboardInterrupt) as observed: editor.query('1.18.0')
        self.assertIs(observed.exception, first)
        class BadBaseline:
            calls = 0
            @property
            def last_reply(self):
                self.calls += 1
                if self.calls == 1: raise first
                return reply()
            def post(self, *args, **kwargs): raise AssertionError('No post after baseline failure')
        backend = BadBaseline(); editor = ToolkitUpdateCatalogue(backend)
        with self.assertRaises(KeyboardInterrupt) as observed: editor.query('1.18.0')
        self.assertIs(observed.exception, first); self.assertEqual(backend.calls, 1)
        self.assertIsNone(editor.last_outcome.reply)
        self.assertFalse(ToolkitUpdateCatalogue(Transport(object())).query('1.18.0').complete)

    def test_insecure_or_changed_tls_context_rejected_before_connection(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); context.check_hostname = False
        with self.assertRaises(ValueError): HTTPSCatalogueTransport(context=context)
        context.check_hostname = True; backend = HTTPSCatalogueTransport(context=context)
        context.check_hostname = False
        with patch('cbus_toolkit.toolkit_updates.http.client.HTTPSConnection', side_effect=AssertionError('No insecure connection')):
            result = ToolkitUpdateCatalogue(backend).query('1.18.0')
        self.assertFalse(result.complete); self.assertFalse(result.reply.request_attempted)

    def test_foreign_transport_invalid_evidence_is_rejected_without_export_failure(self):
        baseline = reply()
        for value in (replace(baseline, status=True), replace(baseline, body_complete=1),
                      replace(baseline, headers=(42,)), replace(baseline, cleanup=(False,)),
                      replace(baseline, bytes_received=True), replace(baseline, error=True)):
            outcome = ToolkitUpdateCatalogue(Transport(value)).query('1.18.0')
            self.assertFalse(outcome.complete); self.assertIsNone(outcome.as_dict()['http'])


class LocalTLSUpdateTests(unittest.TestCase):
    def test_real_tls_hostname_verified_one_post_and_redirect_not_followed(self):
        from datetime import datetime, timedelta, timezone
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CATALOGUE_HOST)])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
                .not_valid_after(now+timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(CATALOGUE_HOST)]), critical=False)
                .sign(key, hashes.SHA256()))
        with tempfile.TemporaryDirectory() as directory:
            cert_path = Path(directory)/'owned-cert.pem'; key_path = Path(directory)/'owned-key.pem'
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); server_context.load_cert_chain(cert_path, key_path)
            client_context = ssl.create_default_context(cafile=str(cert_path))
            for status in (200, 302):
                body = b'{"success":true,"statusCode":200,"message":"owned","data":[]}'
                listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(5)
                address = listener.getsockname(); recorded = []; errors = []
                def serve():
                    try:
                        accepted, _ = listener.accept()
                        with server_context.wrap_socket(accepted, server_side=True) as stream:
                            stream.settimeout(5); received = b''
                            while b'\r\n\r\n' not in received: received += stream.recv(4096)
                            header, payload = received.split(b'\r\n\r\n', 1)
                            length = int(next(line.split(b':', 1)[1] for line in header.split(b'\r\n') if line.lower().startswith(b'content-length:')))
                            while len(payload) < length: payload += stream.recv(4096)
                            recorded.append((header, payload))
                            response = (f'HTTP/1.1 {status} Owned\r\nContent-Length: {len(body)}\r\nConnection: close\r\n'
                                        'Location: https://example.invalid/never-follow\r\n\r\n').encode() + body
                            stream.sendall(response)
                    except BaseException as error: errors.append(error)
                    finally: listener.close()
                thread = threading.Thread(target=serve, daemon=True); thread.start()
                original_connect = socket.create_connection; calls = []
                def owned_connect(target, *args, **kwargs):
                    calls.append(target)
                    if target != (CATALOGUE_HOST, 443): raise AssertionError('Unexpected endpoint')
                    return original_connect(address, *args, **kwargs)
                try:
                    with patch('socket.create_connection', side_effect=owned_connect):
                        outcome = ToolkitUpdateCatalogue(HTTPSCatalogueTransport(context=client_context)).query('1.18.0', timeout=3)
                finally:
                    thread.join(6); listener.close()
                self.assertFalse(thread.is_alive()); self.assertEqual(errors, [])
                self.assertEqual(calls, [(CATALOGUE_HOST, 443)]); self.assertEqual(len(recorded), 1)
                self.assertTrue(recorded[0][0].startswith(b'POST /collections/PackageData/list HTTP/1.1\r\n'))
                self.assertEqual(recorded[0][1], catalogue_request('1.18.0'))
                self.assertEqual(outcome.complete, status == 200)
                self.assertEqual([item.succeeded for item in outcome.reply.cleanup], [True, True])


class OriginalUpdateMenuTests(unittest.TestCase):
    def test_fresh_original_handler36_literal_cases(self):
        executable = Path(os.environ.get('CBUS_TOOLKIT_EXE', ROOT/'research/vendor/toolkit/app/CBusToolkit.exe'))
        if not executable.is_file(): self.skipTest('Pinned Toolkit executable unavailable')
        from research.toolkit_updates_original import probe_update_menu
        value = probe_update_menu(executable); expected = fixture()['menu']
        self.assertEqual(value['cases'], expected['cases'])
        self.assertEqual(len(value['cases']), 36); self.assertEqual(value['network_calls'], 0)
        self.assertFalse(value['browser_started']); self.assertFalse(value['native_calls'])

    def test_wrong_executable_rejected_before_emulation(self):
        from research.toolkit_updates_original import probe_update_menu
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'wrong.exe'; path.write_bytes(b'not Toolkit')
            with self.assertRaisesRegex(ValueError, 'exact Toolkit'): probe_update_menu(path)


if __name__ == '__main__': unittest.main()
