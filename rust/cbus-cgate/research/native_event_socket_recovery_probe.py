#!/usr/bin/env python3
"""Probe original C-Gate outbound event-socket recovery on owned loopback.

The sink starts bound but not listening, so the native child can never send
events outside this process.  All C-Gate children and project files are owned
by LocalCGate, and no C-Bus endpoint is configured.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import select
import socket
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "toolkit-cli/research"))
from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402
from native_config_event_transport_probe import (  # noqa: E402
    cleanup, command, command_session, start_socket_child,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(peer: socket.socket, duration: float) -> tuple[list[str], bool]:
    data = bytearray()
    closed = False
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        readable, _, _ = select.select([peer], [], [], max(0, deadline - time.monotonic()))
        if not readable:
            break
        chunk = peer.recv(65536)
        if not chunk:
            closed = True
            break
        data.extend(chunk)
    rows = [part.decode("utf-8", "replace").rstrip("\r")
            for part in data.split(b"\n") if part]
    return rows, closed


def codes(rows: list[str]) -> list[int]:
    output = []
    for row in rows:
        match = re.match(r"^\d{8}-\d{6}(?:\.\d{3})? (\d{3}) ", row)
        if match:
            output.append(int(match[1]))
    return output


def absent_at_start(vendor: Path, java: Path, wait_seconds: float) -> dict:
    if wait_seconds < 1 or wait_seconds > 90:
        raise ValueError("wait_seconds must be 1..90")
    server = LocalCGate(vendor, java=java)
    sink = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    event = None
    resumed = None
    peer = None
    child_state = {}
    try:
        # Bound but not listening is an owned, provably unavailable endpoint.
        sink.bind(("127.0.0.1", 0))
        sink.settimeout(wait_seconds)
        port = sink.getsockname()[1]
        assert port not in server.ports
        config = server.work / "config/C-GateConfig.txt"
        content = config.read_text().replace("event-mode=server\n", "event-mode=socket\n")
        content = content.replace(f"event-port={server.event_port}\n", f"event-port={port}\n")
        config.write_text(content + "event-host=127.0.0.1\nglobal-event-level=5\n")

        start_socket_child(server, java, vendor)
        peer, stream, greeting = command_session(server)
        absent_reply = command(stream, "absent", "BROADCAST_EVENT SP class absent-marker")
        time.sleep(1.25)
        listen_at = time.monotonic()
        sink.listen(2)
        first_accept_timeout = False
        try:
            event, address = sink.accept()
        except socket.timeout:
            first_accept_timeout = True
            address = None
        first_delay = round(time.monotonic() - listen_at, 3)
        first_rows: list[str] = []
        online_reply: list[str] = []
        online_rows: list[str] = []
        first_closed = False
        reconnect_delay = None
        reconnect_timeout = None
        reconnect_rows: list[str] = []
        resumed_reply: list[str] = []
        resumed_rows: list[str] = []
        lost_reply: list[str] = []
        if event is not None:
            event.settimeout(2)
            first_rows, first_closed = read_rows(event, .7)
            online_reply = command(stream, "online", "BROADCAST_EVENT SP class online-marker")
            online_rows, was_closed = read_rows(event, .7)
            first_closed |= was_closed
            event.close()
            event = None
            lost_reply = command(stream, "lost", "BROADCAST_EVENT SP class lost-marker")
            reconnect_at = time.monotonic()
            try:
                resumed, _ = sink.accept()
                reconnect_timeout = False
            except socket.timeout:
                reconnect_timeout = True
            reconnect_delay = round(time.monotonic() - reconnect_at, 3)
            if resumed is not None:
                resumed.settimeout(2)
                reconnect_rows, _ = read_rows(resumed, .7)
                resumed_reply = command(stream, "resumed", "BROADCAST_EVENT SP class resumed-marker")
                resumed_rows, _ = read_rows(resumed, .7)
        quit_reply = command(stream, "quit", "QUIT")
        return {
            "schema": "native-cgate-event-socket-recovery-v1",
            "captured_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "One owned original C-Gate child, outbound to an owned loopback sink only; no site project or C-Bus endpoint",
            "oracle": {
                "version": "3.4.0 build 2001", "jar_sha256": JAR_SHA256,
                "java_sha256": digest(java),
                "harness_sha256": digest(ROOT / "toolkit-cli/research/local_cgate.py"),
                "transport_probe_sha256": digest(ROOT / "rust/cbus-cgate/research/native_config_event_transport_probe.py"),
                "capture_script_sha256": digest(Path(__file__)),
                "physical_endpoint": False,
                "child": child_state,
            },
            "greeting": greeting,
            "absent": {"sink_bound_not_listening": True,
                       "broadcast_response": absent_reply, "wait_before_listen_seconds": 1.25},
            "first_connection": {
                "accepted": not first_accept_timeout,
                "accept_delay_seconds": first_delay,
                "sink_peer_ip": address[0] if address else None,
                "rows": first_rows, "codes": codes(first_rows),
                "contains_absent_marker": any("absent-marker" in line for line in first_rows),
                "broadcast_response": online_reply,
                "online_rows": online_rows, "online_codes": codes(online_rows),
                "first_stream_closed_before_local_close": first_closed,
            },
            "reconnection": {
                "broadcast_while_disconnected": lost_reply,
                "accepted": resumed is not None,
                "accept_timeout": reconnect_timeout,
                "accept_delay_seconds": reconnect_delay,
                "rows": reconnect_rows, "codes": codes(reconnect_rows),
                "contains_lost_marker": any("lost-marker" in line for line in reconnect_rows),
                "broadcast_response": resumed_reply,
                "resumed_rows": resumed_rows, "resumed_codes": codes(resumed_rows),
            },
            "quit_response": quit_reply,
        }
    finally:
        if peer is not None:
            peer.close()
        if event is not None:
            event.close()
        if resumed is not None:
            resumed.close()
        sink.close()
        server.close()
        child_state.update(cleanup(server))


def connected_at_start(vendor: Path, java: Path, wait_seconds: float) -> dict:
    server = LocalCGate(vendor, java=java)
    sink = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    event = None
    resumed = None
    peer = None
    child_state = {}
    try:
        sink.bind(("127.0.0.1", 0))
        sink.listen(2)
        sink.settimeout(wait_seconds)
        port = sink.getsockname()[1]
        assert port not in server.ports
        config = server.work / "config/C-GateConfig.txt"
        content = config.read_text().replace("event-mode=server\n", "event-mode=socket\n")
        content = content.replace(f"event-port={server.event_port}\n", f"event-port={port}\n")
        config.write_text(content + "event-host=127.0.0.1\nglobal-event-level=5\n")

        start_socket_child(server, java, vendor)
        event, address = sink.accept()
        event.settimeout(2)
        startup_rows, _ = read_rows(event, .7)
        peer, stream, greeting = command_session(server)
        online_reply = command(stream, "online", "BROADCAST_EVENT SP class connected-marker")
        online_rows, _ = read_rows(event, .7)

        # Force an observable transport break.  A plain FIN may leave the
        # native writer unaware until its next send; RST makes that explicit.
        event.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        event.close()
        event = None
        disconnected_reply = command(stream, "lost", "BROADCAST_EVENT SP class disconnected-marker")
        disconnected_at = time.monotonic()
        try:
            resumed, _ = sink.accept()
        except socket.timeout:
            pass
        reconnect_delay = round(time.monotonic() - disconnected_at, 3)
        reconnect_rows: list[str] = []
        restored_reply: list[str] = []
        restored_rows: list[str] = []
        if resumed is not None:
            resumed.settimeout(2)
            reconnect_rows, _ = read_rows(resumed, .7)
            restored_reply = command(stream, "restored", "BROADCAST_EVENT SP class restored-marker")
            restored_rows, _ = read_rows(resumed, .7)
        quit_reply = command(stream, "quit", "QUIT")
        return {
            "child": child_state,
            "sink_listening_before_start": True,
            "sink_peer_ip": address[0],
            "greeting": greeting,
            "startup_rows": startup_rows,
            "startup_codes": codes(startup_rows),
            "connected_broadcast_response": online_reply,
            "connected_rows": online_rows,
            "connected_codes": codes(online_rows),
            "rst_after_connected_broadcast": True,
            "disconnected_broadcast_response": disconnected_reply,
            "reconnected": resumed is not None,
            "reconnect_delay_seconds": reconnect_delay,
            "reconnect_rows": reconnect_rows,
            "reconnect_codes": codes(reconnect_rows),
            "replayed_disconnected_marker": any("disconnected-marker" in line for line in reconnect_rows),
            "restored_broadcast_response": restored_reply,
            "restored_rows": restored_rows,
            "restored_codes": codes(restored_rows),
            "quit_response": quit_reply,
        }
    finally:
        if peer is not None:
            peer.close()
        if event is not None:
            event.close()
        if resumed is not None:
            resumed.close()
        sink.close()
        server.close()
        child_state.update(cleanup(server))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=float, default=60)
    args = parser.parse_args()
    vendor, java = args.vendor.resolve(), args.java.resolve()
    first = absent_at_start(vendor, java, args.wait_seconds)
    connected = connected_at_start(vendor, java, args.wait_seconds)
    report = {
        "schema": "native-cgate-event-socket-recovery-v2",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Two owned original C-Gate children, outbound to owned loopback sinks only; no site project or C-Bus endpoint",
        "oracle": {
            "version": "3.4.0 build 2001", "jar_sha256": JAR_SHA256,
            "java_sha256": digest(java),
            "harness_sha256": digest(ROOT / "toolkit-cli/research/local_cgate.py"),
            "transport_probe_sha256": digest(ROOT / "rust/cbus-cgate/research/native_config_event_transport_probe.py"),
            "capture_script_sha256": digest(Path(__file__)),
            "physical_endpoint": False,
            "children": {
                "initial_sink_absent": first["oracle"]["child"],
                "initial_sink_present": connected.pop("child"),
            },
        },
        "initial_sink_absent": {key: value for key, value in first.items() if key not in
                                {"schema", "captured_utc", "scope", "oracle"}},
        "initial_sink_present": connected,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"first_accepted_after_absence": report["initial_sink_absent"]["first_connection"]["accepted"],
                      "reconnected_after_rst": report["initial_sink_present"]["reconnected"]}))


if __name__ == "__main__":
    main()
