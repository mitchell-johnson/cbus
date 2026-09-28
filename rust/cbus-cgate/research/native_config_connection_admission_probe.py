#!/usr/bin/env python3
"""Probe native C-Gate command admission on owned loopback listeners only.

The existing LocalCGate harness creates an isolated project/config directory,
verifies ownership of all six listeners, and removes it after the child exits.
No installed service, site project, or C-Bus interface is adopted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "toolkit-cli/research"))

from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402


def configure(server: LocalCGate, value: str | None) -> None:
    path = server.work / "config/C-GateConfig.txt"
    source = path.read_text()
    original = "accept-connections-from=127.0.0.1\n"
    assert source.count(original) == 1
    replacement = "" if value is None else f"accept-connections-from={value}\n"
    path.write_text(source.replace(original, replacement))


def open_command(server: LocalCGate) -> tuple[socket.socket, object, str]:
    peer = socket.create_connection(("127.0.0.1", server.port), timeout=3)
    peer.settimeout(3)
    stream = peer.makefile("rwb", buffering=0)
    greeting = stream.readline().decode().rstrip("\r\n")
    assert greeting.startswith(
        "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)"
    ), greeting
    return peer, stream, greeting


def command(stream: object, tag: str, body: str) -> dict:
    stream.write(f"[{tag}] {body}\r\n".encode())
    rows = []
    while True:
        row = stream.readline().decode().rstrip("\r\n")
        if not row:
            raise EOFError((body, rows))
        rows.append(row)
        if row.startswith(f"[{tag}] ") and row[len(tag) + 6] == " ":
            return {"command": body, "response": rows}


def connection_outcome(server: LocalCGate) -> dict:
    """Observe only a loopback command connection, with a bounded timeout."""
    try:
        peer = socket.create_connection(("127.0.0.1", server.port), timeout=3)
    except OSError as error:
        return {"outcome": "connect-error", "error_type": type(error).__name__}
    try:
        peer.settimeout(3)
        try:
            data = peer.recv(512)
        except socket.timeout:
            return {"outcome": "connected-no-greeting-timeout"}
        except OSError as error:
            return {"outcome": "connected-read-error", "error_type": type(error).__name__}
        if not data:
            return {"outcome": "connected-eof"}
        return {"outcome": "greeting", "bytes": data.decode(errors="replace").rstrip("\r\n")}
    finally:
        peer.close()


def denied_long_observation(server: LocalCGate) -> dict:
    """Bound a denied socket's silence before and after an attempted command."""
    peer = socket.create_connection(("127.0.0.1", server.port), timeout=3)
    try:
        peer.settimeout(12)
        try:
            first = peer.recv(512)
            first_outcome = "eof" if not first else "data"
        except socket.timeout:
            first_outcome = "silent-timeout"
        peer.sendall(b"NOOP\r\n")
        peer.settimeout(3)
        try:
            second = peer.recv(512)
            second_outcome = "eof" if not second else "data"
        except socket.timeout:
            second_outcome = "silent-timeout"
        assert (first_outcome, second_outcome) == ("silent-timeout", "silent-timeout")
        return {"passive_wait_seconds": 12, "after_noop_wait_seconds": 3,
                "passive_outcome": first_outcome, "after_noop_outcome": second_outcome}
    finally:
        peer.close()


def cleanup(server: LocalCGate) -> dict:
    report = server.report
    assert report["listener_ownership_verified"] and report["cleanup_complete"]
    assert report["process_exit_confirmed"] and report["work_removed"]
    return {key: report[key] for key in (
        "listener_ownership_verified", "process_exit_confirmed", "cleanup_complete", "work_removed"
    )}


def capture(vendor: Path, java: Path) -> dict:
    default = LocalCGate(vendor, java=java)
    configure(default, None)
    with default:
        peer, stream, greeting = open_command(default)
        try:
            default_rows = [
                command(stream, "default", "CONFIG GET accept-connections-from"),
                command(stream, "info", "CONFIG INFO accept-connections-from"),
            ]
        finally:
            peer.close()
        default_connection = connection_outcome(default)

    runtime = LocalCGate(vendor, java=java)
    configure(runtime, "127.0.0.1")
    with runtime:
        peer, stream, _ = open_command(runtime)
        try:
            runtime_rows = [
                command(stream, "before", "CONFIG GET accept-connections-from"),
                command(stream, "set", "CONFIG SET accept-connections-from 192.0.2.55"),
                command(stream, "after", "CONFIG GET accept-connections-from"),
            ]
            after_set_connection = connection_outcome(runtime)
            runtime_rows.append(command(stream, "save", "CONFIG SAVE global"))
            after_save_connection = connection_outcome(runtime)
            runtime_rows.append(command(stream, "existing", "NOOP"))
            runtime_rows.append(command(stream, "reallow", "CONFIG SET accept-connections-from all"))
            after_reallow_connection = connection_outcome(runtime)
            runtime_rows.append(command(stream, "reload", "CONFIG LOAD global"))
            after_reload_connection = connection_outcome(runtime)
        finally:
            peer.close()
        saved_config = (runtime.work / "config/C-GateConfig.txt").read_text()
        assert saved_config.splitlines().count("accept-connections-from=192.0.2.55") == 1

    denied = LocalCGate(vendor, java=java)
    configure(denied, "192.0.2.55")
    with denied:
        fresh_denied_connection = connection_outcome(denied)
        long_denial = denied_long_observation(denied)

    allowed = LocalCGate(vendor, java=java)
    configure(allowed, "127.0.0.1")
    with allowed:
        fresh_allowed_connection = connection_outcome(allowed)

    multiple = LocalCGate(vendor, java=java)
    configure(multiple, "192.0.2.55 127.0.0.1")
    with multiple:
        fresh_multiple_connection = connection_outcome(multiple)

    hostname = LocalCGate(vendor, java=java)
    configure(hostname, "localhost")
    with hostname:
        fresh_hostname_connection = connection_outcome(hostname)

    return {
        "schema": "native-cgate-config-connection-admission-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Owned IPv4 loopback command listeners including exact localhost spelling; no physical endpoint, site project, event listener, TLS listener, arbitrary hostname, or IPv6 assertion",
        "oracle": {
            "version": "3.4.0 build 2001",
            "jar_sha256": JAR_SHA256,
            "java_sha256": hashlib.sha256(java.read_bytes()).hexdigest(),
            "harness_sha256": hashlib.sha256((ROOT / "toolkit-cli/research/local_cgate.py").read_bytes()).hexdigest(),
            "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "physical_endpoint": False,
            "children": {"default": cleanup(default), "runtime": cleanup(runtime),
                         "denied": cleanup(denied), "allowed": cleanup(allowed),
                         "multiple": cleanup(multiple), "hostname": cleanup(hostname)},
        },
        "default": {"greeting": greeting, "commands": default_rows, "new_connection": default_connection},
        "runtime": {"commands": runtime_rows, "after_set": after_set_connection,
                    "after_save": after_save_connection,
                    "after_reallow": after_reallow_connection,
                    "after_reload": after_reload_connection},
        "fresh_denied": fresh_denied_connection,
        "fresh_denied_long": long_denial,
        "fresh_allowed": fresh_allowed_connection,
        "fresh_multiple": fresh_multiple_connection,
        "fresh_hostname": fresh_hostname_connection,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", required=True, type=Path)
    parser.add_argument("--java", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = capture(args.vendor.resolve(), args.java.resolve())
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"children": len(receipt["oracle"]["children"]), "cleanup": True}))
