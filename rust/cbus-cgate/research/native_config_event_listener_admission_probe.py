#!/usr/bin/env python3
"""Capture original C-Gate event-port admission on owned loopback sockets.

Each case starts a fresh build-2001 child with an isolated config and project
directory. The TLS case generates disposable server/client certificates in that
child; no installed service, site project, or physical endpoint is touched.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import select
import socket
import ssl
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "toolkit-cli/research"))
from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402
from verify_tls import STORE_PASSWORD, generate_pki, run  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(stream, tag: str, body: str) -> str:
    stream.write(f"[{tag}] {body}\r\n".encode())
    while True:
        line = stream.readline().decode().rstrip("\r\n")
        if not line:
            raise EOFError(body)
        if line.startswith(f"[{tag}] ") and line[len(tag) + 6] == " ":
            return line


def plain_greeting(port: int) -> str:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as peer:
        peer.settimeout(1.2)
        try:
            data = peer.recv(512)
        except socket.timeout:
            return "connected-silent"
        if data.startswith(b"201 Service ready:"):
            return "greeting"
        if not data:
            return "connected-eof"
        raise AssertionError("Unexpected command-listener data")


def tls_greeting(port: int, pki: Path) -> str:
    context = ssl.create_default_context(cafile=str(pki / "ca.pem"))
    context.load_cert_chain(str(pki / "client.pem"), str(pki / "client.key"))
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3) as raw:
            raw.settimeout(2)
            with context.wrap_socket(raw, server_hostname="localhost") as peer:
                peer.settimeout(2)
                try:
                    data = peer.recv(512)
                except socket.timeout:
                    return "handshake-succeeded-silent"
                if data.startswith(b"201 Service ready:"):
                    return "greeting"
                if not data:
                    return "handshake-succeeded-eof"
                raise AssertionError("Unexpected TLS command-listener data")
    except socket.timeout:
        return "handshake-timeout"
    except ssl.SSLError as error:
        return f"tls-error:{error.reason}"


def event_rows(peer: socket.socket, marker: bytes) -> list[str]:
    data = b""
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        ready, _, _ = select.select([peer], [], [], deadline - time.monotonic())
        if not ready:
            break
        chunk = peer.recv(65536)
        if not chunk:
            break
        data += chunk
        if marker in data and b"\r\n" in data.split(marker, 1)[1]:
            break
    return [line.decode().rstrip("\r") for line in data.split(b"\n") if line]


def install_owned_mtls(server: LocalCGate) -> Path:
    pki = server.work / "pki"
    pki.mkdir()
    (server.work / "key/cis.ks").unlink()
    generate_pki(pki)
    run(str(server.keytool), "-importkeystore", "-noprompt", "-srckeystore",
        "pki/server.p12", "-srcstoretype", "PKCS12", "-srcstorepass",
        STORE_PASSWORD, "-destkeystore", "key/cis.ks", "-deststoretype",
        "JKS", "-deststorepass", STORE_PASSWORD, cwd=server.work)
    run(str(server.keytool), "-importcert", "-noprompt", "-alias", "test-ca",
        "-file", "pki/ca.pem", "-keystore", "key/cis.ks", "-storepass",
        STORE_PASSWORD, cwd=server.work)
    return pki


def capture_case(vendor: Path, java: Path, *, mtls: bool) -> dict:
    server = LocalCGate(vendor, java=java)
    pki = None
    try:
        if mtls:
            pki = install_owned_mtls(server)
        with server:
            with socket.create_connection(("127.0.0.1", server.port), timeout=3) as command_peer:
                command_peer.settimeout(3)
                stream = command_peer.makefile("rwb", buffering=0)
                greeting = stream.readline().decode().rstrip("\r\n")
                assert greeting.startswith("201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)")
                baseline_tls = tls_greeting(server.tls_port, pki) if pki else None
                assert baseline_tls in (None, "greeting")
                denied = command(stream, "deny", "CONFIG SET accept-connections-from 192.0.2.55")
                assert denied == "[deny] 200 OK."
                denied_plain = plain_greeting(server.port)
                denied_tls = tls_greeting(server.tls_port, pki) if pki else None
                assert denied_plain == "connected-silent"
                assert denied_tls in (None, "handshake-timeout")
                with socket.create_connection(("127.0.0.1", server.event_port), timeout=3) as event_peer:
                    event_peer.settimeout(3)
                    # Let the original listener accept the new peer before
                    # the existing command session emits its event.
                    time.sleep(.3)
                    marker = f"broadcast_event SP class event-admission-{'mtls' if mtls else 'plain'}".encode()
                    broadcast = command(stream, "broadcast", "BROADCAST_EVENT SP class " + marker.decode().split("class ", 1)[1])
                    rows = event_rows(event_peer, marker)
                matches = [row for row in rows if " 703 cmd" in row and marker.decode() in row]
                assert len(matches) == 1, rows
                assert broadcast == "[broadcast] 200 OK."
                result = {
                    "mtls_configured": mtls,
                    "command_greeting": greeting,
                    "baseline_tls_greeting": baseline_tls,
                    "allowlist_set": denied,
                    "new_plain_command": denied_plain,
                    "new_tls_command": denied_tls,
                    "new_event_peer_ip": "127.0.0.1",
                    "broadcast_response": broadcast,
                    "event_rows": rows,
                    "broadcast_event_row": matches[0],
                }
        result["cleanup"] = {key: server.report[key] for key in (
            "listener_ownership_verified", "process_exit_confirmed",
            "cleanup_complete", "work_removed")}
        assert all(result["cleanup"].values())
        return result
    finally:
        server.close()


def capture(vendor: Path, java: Path) -> dict:
    inputs = [Path(__file__), ROOT / "toolkit-cli/research/local_cgate.py",
              ROOT / "toolkit-cli/research/verify_tls.py"]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in inputs}
    cases = {
        "plain": capture_case(vendor, java, mtls=False),
        "mtls": capture_case(vendor, java, mtls=True),
    }
    assert hashes == {str(path.relative_to(ROOT)): digest(path) for path in inputs}
    return {
        "schema": "native-cgate-config-event-listener-admission-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Owned IPv4 loopback command, event, and mutual-TLS listeners; no physical endpoint, site project, or IPv6 peer",
        "oracle": {
            "version": "3.4.0 build 2001", "jar_sha256": JAR_SHA256,
            "java_sha256": digest(java), "source_hashes": hashes,
            "source_hashes_after": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
            "physical_endpoint": False,
        },
        "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = capture(args.vendor.resolve(), args.java.resolve())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"cases": len(result["cases"]), "cleanup": all(
        all(case["cleanup"].values()) for case in result["cases"].values())}))
