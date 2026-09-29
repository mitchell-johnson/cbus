"""Catalogue-bound package download against an owned ephemeral-CA TLS server."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch

from cbus_toolkit.toolkit_update_download import (
    UpdateDownloadError,
    bind_download_source,
    download_update_package,
)
from cbus_toolkit.toolkit_updates import (
    CatalogueHTTPReply,
    ToolkitUpdateCatalogue,
    UpdateCleanup,
)


HOST = "downloads.invalid"
NODE_ID = "selected-node"
FILE_ID = "package-1"
PACKAGE = b"owned synthetic installer bytes\x00\xff" * 97


def response_body(path="/ok/Owned-Setup.exe", *, host=HOST, port=443, package=PACKAGE, extra_files=()):
    files = [{
        "id": FILE_ID,
        "name": "Owned-Setup.exe",
        "size": len(package),
        "url": f"https://{host}:{port}{path}",
        "security": {"sha1": hashlib.sha1(package).hexdigest().upper()},
        "metadata": {"architecture": "windows_x86_64", "mediatype": "singleFileExecutable"},
    }, *extra_files]
    return json.dumps({
        "success": True, "statusCode": 200, "message": "owned",
        "data": [{"nodeId": NODE_ID, "nodeName": "Owned update", "data": {"type": "PackageData"},
                  "files": files, "signatures": {}}],
    }, sort_keys=True, separators=(",", ":")).encode()


class _Transport:
    last_reply = None

    def __init__(self, body):
        self.body = body

    def post(self, body, *, timeout, max_response_bytes):
        self.last_reply = CatalogueHTTPReply(
            200, (("Content-Type", "application/json"),), self.body, len(self.body), True, True,
            None, (UpdateCleanup("response", True), UpdateCleanup("connection", True)))
        return self.last_reply


def catalogue_report(body):
    outcome = ToolkitUpdateCatalogue(_Transport(body)).query("1.18.0")
    assert outcome.complete, outcome.as_dict()
    return json.dumps(outcome.as_dict(), indent=2).encode()


def _pki(names):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Owned test CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name) for name in names]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    pem = serialization.Encoding.PEM
    return (ca.public_bytes(pem), leaf.public_bytes(pem),
            key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


class OwnedTLSServer:
    """Minimal HTTPS/1.1 responder with per-path owned behaviors."""

    def __init__(self, directory: Path):
        self.ca, leaf, key = _pki([HOST])
        self.other_ca = _pki([HOST])[0]
        (directory / "leaf.pem").write_bytes(leaf)
        (directory / "key.pem").write_bytes(key)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(directory / "leaf.pem", directory / "key.pem")
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.listener.settimeout(0.2)
        self.port = self.listener.getsockname()[1]
        self.requests = []
        self.connections = []
        self.stopping = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self):
        self.stopping = True
        self.thread.join(5)
        self.listener.close()

    def _serve(self):
        while not self.stopping:
            try:
                accepted, _ = self.listener.accept()
            except (socket.timeout, OSError):
                continue
            self.connections.append(1)
            try:
                with self.context.wrap_socket(accepted, server_side=True) as stream:
                    stream.settimeout(5)
                    received = b""
                    while b"\r\n\r\n" not in received:
                        chunk = stream.recv(4096)
                        if not chunk:
                            break
                        received += chunk
                    if not received:
                        continue
                    line = received.split(b"\r\n", 1)[0].decode()
                    self.requests.append(received.split(b"\r\n\r\n", 1)[0].decode())
                    self._respond(stream, line.split(" ")[1])
            except (ssl.SSLError, OSError):
                continue

    def _respond(self, stream, target):
        kind = target.split("/")[1]
        package = PACKAGE
        head = "HTTP/1.1 200 OK\r\nConnection: close\r\n"
        if kind == "ok":
            stream.sendall(f"{head}Content-Length: {len(package)}\r\n\r\n".encode() + package)
        elif kind == "wrong":
            stream.sendall(f"{head}Content-Length: {len(package)}\r\n\r\n".encode() + b"!" * len(package))
        elif kind == "big":
            stream.sendall(head.encode() + b"\r\n" + package + b"extra bytes")
        elif kind == "biglength":
            stream.sendall(f"{head}Content-Length: {len(package) + 1}\r\n\r\n".encode() + package + b"!")
        elif kind == "truncated":
            stream.sendall(f"{head}Content-Length: {len(package)}\r\n\r\n".encode() + package[:100])
        elif kind == "same":
            stream.sendall(b"HTTP/1.1 302 Found\r\nConnection: close\r\nContent-Length: 0\r\n"
                           b"Location: /ok/Owned-Setup.exe\r\n\r\n")
        elif kind == "cross":
            stream.sendall(f"HTTP/1.1 302 Found\r\nConnection: close\r\nContent-Length: 0\r\n"
                           f"Location: https://elsewhere.invalid:{self.port}/ok/Owned-Setup.exe\r\n\r\n".encode())
        elif kind == "loop":
            stream.sendall(b"HTTP/1.1 307 Again\r\nConnection: close\r\nContent-Length: 0\r\n"
                           b"Location: /loop/Owned-Setup.exe\r\n\r\n")
        else:
            stream.sendall(b"HTTP/1.1 404 Missing\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")


class OwnedTLSFixture:
    """Owned server, scratch output and routed ``*.invalid`` connections."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "out"
        self.output.mkdir()
        self.server = OwnedTLSServer(self.root)
        self.addCleanup(self.server.close)
        self.targets = []
        original = socket.create_connection

        def routed(address, *args, **kwargs):
            self.targets.append(address)
            if address[1] != self.server.port or not address[0].endswith(".invalid"):
                raise AssertionError("Unexpected endpoint " + repr(address))
            return original(("127.0.0.1", self.server.port), *args, **kwargs)

        routing = patch("socket.create_connection", side_effect=routed)
        routing.start()
        self.addCleanup(routing.stop)


class UpdateDownloadTLSTests(OwnedTLSFixture, unittest.TestCase):

    def download(self, path="/ok/Owned-Setup.exe", *, host=HOST, ca=None, body=None, report=None, **kwargs):
        body = body or response_body(path, host=host, port=self.server.port)
        return download_update_package(
            report or catalogue_report(body), body, node_id=NODE_ID, file_id=FILE_ID,
            output_dir=self.output, ca_bytes=self.server.ca if ca is None else ca, timeout=5, **kwargs)

    def assert_failed(self, result, stage, kind, *, partial=None):
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual((result["failure"]["stage"], result["failure"]["type"]), (stage, kind), result["failure"])
        self.assertFalse((self.output / "Owned-Setup.exe").exists())
        artifacts = result["failure_artifacts"]
        record = json.loads((self.output / artifacts["record"]).read_text())
        self.assertEqual(record["failure"], result["failure"])
        self.assertTrue(artifacts["record"].endswith(".failed.json"))
        if partial is None:
            self.assertIsNone(artifacts["partial"])
        else:
            self.assertTrue(artifacts["partial"].endswith(".failed.partial"))
            self.assertEqual((self.output / artifacts["partial"]).read_bytes(), partial)
            self.assertEqual(result["observed_sha256"], hashlib.sha256(partial).hexdigest())
        self.assertEqual([name for name in os.listdir(self.output) if name.endswith(".download")], [])
        for name in ("installed", "executed", "install_permitted", "publisher_trust_evaluated"):
            self.assertFalse(result[name])

    def test_success_streams_verifies_and_publishes_without_install(self):
        result = self.download()
        self.assertEqual(result["outcome"], "downloaded", result["failure"])
        self.assertEqual((self.output / "Owned-Setup.exe").read_bytes(), PACKAGE)
        self.assertEqual(os.listdir(self.output), ["Owned-Setup.exe"])
        self.assertEqual(result["observed_sha256"], hashlib.sha256(PACKAGE).hexdigest())
        self.assertTrue(result["package_receipt"]["bytes_match_catalogue_descriptor"])
        self.assertTrue(result["tls"]["certificate_verified"])
        self.assertEqual(result["tls"]["trust"], "explicit_ca_file")
        self.assertEqual(result["tls"]["ca_file_sha256"], hashlib.sha256(self.server.ca).hexdigest())
        self.assertIn(result["tls"]["protocol"], ("TLSv1.2", "TLSv1.3"))
        provenance = result["provenance"]
        body = response_body(port=self.server.port)
        self.assertEqual(provenance["catalogue_response_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(provenance["url"], f"https://{HOST}:{self.server.port}/ok/Owned-Setup.exe")
        self.assertTrue(provenance["url_bound_to_catalogue_report"])
        self.assertEqual(self.targets, [(HOST, self.server.port)])
        self.assertIn("Accept-Encoding: identity", self.server.requests[0])
        for name in ("installed", "executed", "install_permitted", "catalogue_claims_trusted"):
            self.assertFalse(result[name])

    def test_wrong_hash_is_retained_as_failure_artifact(self):
        result = self.download("/wrong/Owned-Setup.exe")
        self.assert_failed(result, "verify", "HashMismatch", partial=b"!" * len(PACKAGE))

    def test_oversize_body_and_content_length_are_refused(self):
        result = self.download("/big/Owned-Setup.exe")
        self.assert_failed(result, "response_body", "Oversize", partial=PACKAGE)
        for name in os.listdir(self.output):
            (self.output / name).unlink()
        result = self.download("/biglength/Owned-Setup.exe")
        self.assert_failed(result, "response_headers", "Oversize")

    def test_hard_cap_refuses_before_connecting(self):
        with self.assertRaises(ValueError):
            self.download(max_package_bytes=len(PACKAGE) - 1)
        self.assertEqual(self.targets, [])

    def test_truncated_connection_keeps_partial_bytes(self):
        result = self.download("/truncated/Owned-Setup.exe")
        self.assert_failed(result, "response_body", "Truncated", partial=PACKAGE[:100])
        self.assertEqual(result["bytes_received"], 100)

    def test_same_origin_redirect_followed_cross_origin_refused(self):
        result = self.download("/same/Owned-Setup.exe")
        self.assertEqual(result["outcome"], "downloaded", result["failure"])
        self.assertEqual([item["status"] for item in result["http"]["requests"]], [302, 200])
        (self.output / "Owned-Setup.exe").unlink()
        result = self.download("/cross/Owned-Setup.exe")
        self.assert_failed(result, "redirect", "CrossOriginRedirectRefused")
        self.assertNotIn(("elsewhere.invalid", self.server.port), self.targets)
        for name in os.listdir(self.output):
            (self.output / name).unlink()
        result = self.download("/loop/Owned-Setup.exe")
        self.assert_failed(result, "redirect", "TooManyRedirects")
        self.assertEqual(len(result["http"]["requests"]), 6)

    def test_untrusted_ca_and_hostname_mismatch_fail_tls(self):
        result = self.download(ca=self.server.other_ca)
        self.assert_failed(result, "tls", "CertificateVerificationFailed")
        self.assertEqual(self.server.requests, [])
        for name in os.listdir(self.output):
            (self.output / name).unlink()
        result = self.download(host="mismatch.invalid")
        self.assert_failed(result, "tls", "CertificateVerificationFailed")
        self.assertEqual(self.server.requests, [])

    def test_system_trust_does_not_accept_owned_ca(self):
        body = response_body(port=self.server.port)
        result = download_update_package(catalogue_report(body), body, node_id=NODE_ID, file_id=FILE_ID,
                                         output_dir=self.output, timeout=5)
        self.assert_failed(result, "tls", "CertificateVerificationFailed")
        self.assertEqual(result["tls"]["trust"], "system_default")

    def test_http_error_status_is_a_failure(self):
        result = self.download("/missing/Owned-Setup.exe")
        self.assert_failed(result, "http_status", "UnexpectedStatus")

    def test_existing_output_refused_before_network_and_left_unchanged(self):
        (self.output / "Owned-Setup.exe").write_bytes(b"keep")
        with self.assertRaises(UpdateDownloadError):
            self.download()
        self.assertEqual((self.output / "Owned-Setup.exe").read_bytes(), b"keep")
        self.assertEqual(self.targets, [])

    def test_output_appearing_during_download_is_not_overwritten(self):
        from cbus_toolkit import toolkit_update_download as module
        original = module.inspect_update_package_file

        def racing(*args, **kwargs):
            (self.output / "Owned-Setup.exe").write_bytes(b"raced")
            return original(*args, **kwargs)

        with patch.object(module, "inspect_update_package_file", side_effect=racing):
            result = self.download()
        self.assertEqual(result["failure"]["type"], "OutputExists")
        self.assertEqual((self.output / "Owned-Setup.exe").read_bytes(), b"raced")
        self.assertEqual((self.output / result["failure_artifacts"]["partial"]).read_bytes(), PACKAGE)

    def test_unbound_or_unsafe_urls_are_refused_before_network(self):
        body = response_body(port=self.server.port)
        report = json.loads(catalogue_report(body))
        forged = copy.deepcopy(report)
        forged["candidates"][0]["files"][0]["url"] = f"https://{HOST}:{self.server.port}/wrong/Owned-Setup.exe"
        substituted = response_body("/wrong/Owned-Setup.exe", port=self.server.port)
        cases = [
            (json.dumps(forged).encode(), body),                 # report URL not in exact response
            (catalogue_report(body), substituted),                # response not described by report
            (catalogue_report(response_body("/ok/x.exe", host="h.invalid", port=1).replace(b"https", b"http")),
             response_body("/ok/x.exe", host="h.invalid", port=1).replace(b"https", b"http")),
            (catalogue_report(response_body("/ok/..", port=1)), response_body("/ok/..", port=1)),
            (catalogue_report(response_body("/ok/CON", port=1)), response_body("/ok/CON", port=1)),
        ]
        for report_bytes, response_bytes in cases:
            with self.subTest(response=response_bytes[-120:]), self.assertRaises(ValueError):
                download_update_package(report_bytes, response_bytes, node_id=NODE_ID, file_id=FILE_ID,
                                        output_dir=self.output, ca_bytes=self.server.ca, timeout=5)
        incomplete = copy.deepcopy(report)
        incomplete["complete"] = False
        with self.assertRaises(ValueError):
            download_update_package(json.dumps(incomplete).encode(), body, node_id=NODE_ID, file_id=FILE_ID,
                                    output_dir=self.output, ca_bytes=self.server.ca)
        with self.assertRaises(ValueError):
            download_update_package(catalogue_report(body), body, node_id=NODE_ID, file_id="other",
                                    output_dir=self.output, ca_bytes=self.server.ca)
        self.assertEqual(self.targets, [])
        self.assertEqual(os.listdir(self.output), [])

    def test_binding_uses_raw_descriptor_and_report_provenance(self):
        body = response_body(port=443)
        source = bind_download_source(catalogue_report(body), body, node_id=NODE_ID, file_id=FILE_ID)
        self.assertEqual((source.host, source.port, source.file_name), (HOST, 443, "Owned-Setup.exe"))
        self.assertEqual(source.declared_sha1, hashlib.sha1(PACKAGE).hexdigest())
        self.assertEqual(source.provenance["catalogue_report_sha256"],
                         hashlib.sha256(catalogue_report(body)).hexdigest())


if __name__ == "__main__":
    unittest.main()
