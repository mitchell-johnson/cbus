#!/usr/bin/env python3
"""Owned loopback oracle for C-Gate CONFIG hostname and TLS admission.

No installed service, site project, or physical C-Bus endpoint is used. TLS
credentials are generated inside the disposable child and removed on exit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import ssl
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "toolkit-cli/research"))

from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402
from verify_tls import STORE_PASSWORD, generate_pki, run  # noqa: E402


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(stream: object, tag: str, body: str) -> str:
    stream.write(f"[{tag}] {body}\r\n".encode())
    rows = []
    while True:
        raw = stream.readline()
        if not raw:
            raise EOFError((tag, body, rows))
        row = raw.decode().rstrip("\r\n")
        rows.append(row)
        if row.startswith(f"[{tag}] ") and row[len(tag) + 6] == " ":
            return row


def plain_outcome(port: int) -> str:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as peer:
        peer.settimeout(1.2)
        try:
            data = peer.recv(512)
        except socket.timeout:
            return "connected-silent"
        if not data:
            return "connected-eof"
        if not data.startswith(b"201 Service ready:"):
            raise AssertionError("Unexpected original command greeting")
        return "greeting"


def tls_outcome(port: int, pki: Path) -> dict:
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
                    return {"outcome": "handshake-succeeded-silent", "tls_version": peer.version()}
                if not data:
                    return {"outcome": "handshake-succeeded-eof", "tls_version": peer.version()}
                if not data.startswith(b"201 Service ready:"):
                    raise AssertionError("Unexpected original TLS command greeting")
                return {"outcome": "greeting", "tls_version": peer.version()}
    except socket.timeout:
        return {"outcome": "handshake-timeout"}
    except ssl.SSLError as error:
        return {"outcome": "tls-error", "reason": error.reason}


def capture(vendor: Path, java: Path) -> dict:
    script = Path(__file__)
    harness = ROOT / "toolkit-cli/research/local_cgate.py"
    pki_helper = ROOT / "toolkit-cli/research/verify_tls.py"
    inputs = {str(path.relative_to(ROOT)): source_hash(path)
              for path in (script, harness, pki_helper)}
    result = {
        "schema": "native-cgate-config-hostname-tls-admission-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Owned IPv4 loopback command/TLS ports and new sessions; no IPv6 peer, physical endpoint, site project, or event listener",
        "oracle": {
            "version": "3.4.0 build 2001",
            "jar_sha256": JAR_SHA256,
            "java_sha256": source_hash(java),
            "source_hashes": inputs,
            "physical_endpoint": False,
        },
        "cases": [],
        "tls_cases": [],
    }
    values = [
        "LOCALHOST", "localhost.", "127.0.0.1.nip.io",
        "192.0.2.55.nip.io", "localhost 192.0.2.55",
        "192.0.2.55 localhost", "::1", "ip6-localhost",
        "::ffff:127.0.0.1", "127.0.0.1/8",
        "unresolved.invalid", "ALL",
    ]
    for value in values:
        oracle = LocalCGate(vendor, java=java)
        with oracle:
            with socket.create_connection(("127.0.0.1", oracle.port), timeout=3) as peer:
                peer.settimeout(3)
                stream = peer.makefile("rwb", buffering=0)
                greeting = stream.readline().decode().rstrip("\r\n")
                assert greeting.startswith("201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)")
                set_row = command(stream, "set", f"CONFIG SET accept-connections-from {value}")
                get_row = command(stream, "get", "CONFIG GET accept-connections-from")
                existing = command(stream, "old", "NOOP")
                outcome = plain_outcome(oracle.port)
                restore = command(stream, "restore", "CONFIG SET accept-connections-from all")
                restored = plain_outcome(oracle.port)
                result["cases"].append({
                    "value": value, "set": set_row, "get": get_row,
                    "existing_noop": existing, "plain": outcome,
                    "restore": restore, "restored_plain": restored,
                })
        result["cases"][-1]["cleanup"] = {key: oracle.report[key] for key in (
            "listener_ownership_verified", "process_exit_confirmed",
            "cleanup_complete", "work_removed")}

    oracle = LocalCGate(vendor, java=java)
    try:
        pki = oracle.work / "pki"
        pki.mkdir()
        (oracle.work / "key/cis.ks").unlink()
        result["pki_public"] = generate_pki(pki)
        run(str(oracle.keytool), "-importkeystore", "-noprompt", "-srckeystore",
            "pki/server.p12", "-srcstoretype", "PKCS12", "-srcstorepass",
            STORE_PASSWORD, "-destkeystore", "key/cis.ks", "-deststoretype",
            "JKS", "-deststorepass", STORE_PASSWORD, cwd=oracle.work)
        run(str(oracle.keytool), "-importcert", "-noprompt", "-alias", "test-ca",
            "-file", "pki/ca.pem", "-keystore", "key/cis.ks", "-storepass",
            STORE_PASSWORD, cwd=oracle.work)
        with oracle:
            with socket.create_connection(("127.0.0.1", oracle.port), timeout=3) as peer:
                peer.settimeout(3)
                stream = peer.makefile("rwb", buffering=0)
                greeting = stream.readline().decode().rstrip("\r\n")
                assert greeting.startswith("201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)")
                result["baseline"] = {
                    "plain": plain_outcome(oracle.port),
                    "tls": tls_outcome(oracle.tls_port, pki),
                }
                values = [
                    "LOCALHOST", "localhost.", "127.0.0.1.nip.io",
                    "192.0.2.55.nip.io", "all", "::1", "all",
                ]
                for index, value in enumerate(values):
                    set_row = command(stream, f"set{index}",
                                      f"CONFIG SET accept-connections-from {value}")
                    get_row = command(stream, f"get{index}",
                                      "CONFIG GET accept-connections-from")
                    old_row = command(stream, f"old{index}", "NOOP")
                    result["tls_cases"].append({
                        "value": value,
                        "set": set_row,
                        "get": get_row,
                        "existing_noop": old_row,
                        "plain": plain_outcome(oracle.port),
                        "tls": tls_outcome(oracle.tls_port, pki),
                    })
    finally:
        result["oracle"]["tls_cleanup"] = {key: oracle.report[key] for key in (
            "listener_ownership_verified", "process_exit_confirmed",
            "cleanup_complete", "work_removed")}
    result["oracle"]["source_hashes_after"] = {
        key: source_hash(ROOT / key) for key in inputs
    }
    assert inputs == result["oracle"]["source_hashes_after"]
    assert all(all(row["cleanup"].values()) for row in result["cases"])
    assert all(result["oracle"]["tls_cleanup"].values())
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", required=True, type=Path)
    parser.add_argument("--java", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = capture(args.vendor.resolve(), args.java.resolve())
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"cases": len(report["cases"]),
                      "tls_cases": len(report["tls_cases"]),
                      "cleanup": report["oracle"]["tls_cleanup"]["cleanup_complete"]}))
