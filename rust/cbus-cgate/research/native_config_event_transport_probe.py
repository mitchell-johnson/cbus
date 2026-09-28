#!/usr/bin/env python3
"""Capture C-Gate 3.4 event server/socket transport on owned loopback only."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import select
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "toolkit-cli/research"))
from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lines(sock: socket.socket, duration: float) -> list[str]:
    data = b""
    until = time.monotonic() + duration
    while time.monotonic() < until:
        ready, _, _ = select.select([sock], [], [], until - time.monotonic())
        if not ready:
            break
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    return [row.decode().rstrip("\r") for row in data.split(b"\n") if row]


def command(stream, tag: str, body: str) -> list[str]:
    stream.write(f"[{tag}] {body}\r\n".encode())
    out: list[str] = []
    while True:
        row = stream.readline().decode().rstrip("\r\n")
        if not row:
            raise EOFError((body, out))
        out.append(row)
        if row.startswith(f"[{tag}] ") and row[len(tag) + 6] == " ":
            return out


def command_session(server: LocalCGate):
    peer = socket.create_connection(("127.0.0.1", server.port), timeout=3)
    peer.settimeout(3)
    stream = peer.makefile("rwb", buffering=0)
    greeting = stream.readline().decode().rstrip("\r\n")
    assert greeting.startswith("201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)")
    return peer, stream, greeting


def selected(rows: list[str]) -> list[str]:
    """Keep wire rows tied to this probe, avoiding unrelated startup logs."""
    return [row for row in rows if any(f" {code} " in row for code in ("700", "703", "761", "766", "800", "803", "804"))]


def cleanup(server: LocalCGate) -> dict:
    report = server.report
    assert report["listener_ownership_verified"] and report["cleanup_complete"]
    assert report["process_exit_confirmed"] and report["work_removed"]
    return {name: report[name] for name in (
        "listener_ownership_verified", "cleanup_complete", "process_exit_confirmed", "work_removed"
    )}


def server_case(vendor: Path, java: Path, level: int) -> tuple[dict, LocalCGate]:
    server = LocalCGate(vendor, java=java)
    config = server.work / "config/C-GateConfig.txt"
    config.write_text(config.read_text() + f"global-event-level={level}\n")
    with server:
        event = socket.create_connection(("127.0.0.1", server.event_port), timeout=3)
        peer, stream, greeting = command_session(server)
        try:
            first = lines(event, .25)
            broadcast = command(stream, "broadcast", f"BROADCAST_EVENT SP class level-{level}")
            after_broadcast = lines(event, .25)
            extra = {}
            if level == 5:
                with socket.socket() as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    future_port = reservation.getsockname()[1]
                extra["mode_set"] = command(stream, "mode", "CONFIG SET event-mode socket")
                extra["host_set"] = command(stream, "host", "CONFIG SET event-host 127.0.0.1")
                extra["port_set"] = command(stream, "port", f"CONFIG SET event-port {future_port}")
                with socket.create_connection(("127.0.0.1", server.event_port), timeout=2):
                    extra["old_event_port_still_accepts"] = True
                try:
                    with socket.create_connection(("127.0.0.1", future_port), timeout=.5):
                        extra["new_event_port_unbound"] = False
                except ConnectionRefusedError:
                    extra["new_event_port_unbound"] = True
            quit_reply = command(stream, "quit", "QUIT")
            after_close = lines(event, .25)
            result = {
                "level": level,
                "greeting": greeting,
                "no_event_greeting": not any(row.startswith("201 ") for row in first),
                "broadcast_response": broadcast,
                "quit_response": quit_reply,
                "events": selected(first + after_broadcast + after_close),
                "same_process_config": extra,
            }
            return result, server
        finally:
            peer.close()
            event.close()


def start_socket_child(server: LocalCGate, java: Path, vendor: Path) -> None:
    """LocalCGate ownership check adapted for socket mode's five listeners."""
    server._starting = True
    try:
        server.log = (server.work / "process.log").open("wb")
        argv = [str(java), "-Djava.net.preferIPv4Stack=true", "-Djava.io.tmpdir=" + str(server.work / "tmp"),
                "-Xms64M", "-Xmx512M", "-jar", str(vendor / "cgate.jar")]
        server._release_reserved()
        server.process = subprocess.Popen(argv, cwd=server.work, stdin=subprocess.DEVNULL,
                                          stdout=server.log, stderr=subprocess.STDOUT)
        server.report.update(pid=server.process.pid, argv=argv)
        expected = {"127.0.0.1:" + str(port) for port in server.ports - {server.event_port}}
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if server.process.poll() is not None:
                raise RuntimeError("Owned socket-mode C-Gate exited during startup")
            listing = subprocess.run([server.lsof, "-nP", "-a", "-p", str(server.process.pid),
                                      "-iTCP", "-sTCP:LISTEN", "-Fpn"], capture_output=True,
                                     text=True, timeout=5)
            endpoints = [line[1:] for line in listing.stdout.splitlines() if line.startswith("n")]
            pids = [line[1:] for line in listing.stdout.splitlines() if line.startswith("p")]
            if endpoints and (listing.returncode != 0 or pids != [str(server.process.pid)]):
                raise RuntimeError("Socket-mode listener ownership was not the direct child")
            if any(not endpoint.startswith("127.0.0.1:") for endpoint in endpoints):
                raise RuntimeError("Socket-mode C-Gate opened a non-loopback listener")
            if len(endpoints) == 5 and set(endpoints) == expected:
                server.report.update(listener_ownership_verified=True, listeners=sorted(endpoints))
                return
            time.sleep(.1)
        raise RuntimeError("Socket-mode C-Gate did not acquire five owned loopback listeners")
    except BaseException as error:
        server._cleanup_preserving(error)
        raise


def socket_case(vendor: Path, java: Path) -> tuple[dict, LocalCGate]:
    server = LocalCGate(vendor, java=java)
    sink = socket.socket()
    sink.bind(("127.0.0.1", 0))
    sink.listen(1)
    sink.settimeout(10)
    config = server.work / "config/C-GateConfig.txt"
    content = config.read_text().replace("event-mode=server\n", "event-mode=socket\n")
    content = content.replace(f"event-port={server.event_port}\n", f"event-port={sink.getsockname()[1]}\n")
    content += "event-host=127.0.0.1\nglobal-event-level=5\n"
    config.write_text(content)
    try:
        start_socket_child(server, java, vendor)
        event, address = sink.accept()
        event.settimeout(3)
        peer, stream, greeting = command_session(server)
        try:
            first = lines(event, .25)
            broadcast = command(stream, "broadcast", "BROADCAST_EVENT SP class socket")
            after_broadcast = lines(event, .25)
            quit_reply = command(stream, "quit", "QUIT")
            after_close = lines(event, .25)
            return {
                "greeting": greeting,
                "sink_peer_ip": address[0],
                "broadcast_response": broadcast,
                "quit_response": quit_reply,
                "events": selected(first + after_broadcast + after_close),
            }, server
        finally:
            peer.close()
            event.close()
    finally:
        sink.close()
        server.close()


def capture(vendor: Path, java: Path) -> dict:
    cases = {}
    children = {}
    for level in (0, 3, 5, 9):
        case, child = server_case(vendor, java, level)
        cases[str(level)] = case
        children[f"server_{level}"] = cleanup(child)
    socket_result, child = socket_case(vendor, java)
    children["socket"] = cleanup(child)
    return {
        "schema": "native-cgate-config-event-transport-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Owned loopback event server levels 0/3/5/9 and one outbound socket at level 5; no site project or C-Bus endpoint",
        "oracle": {
            "version": "3.4.0 build 2001", "jar_sha256": JAR_SHA256,
            "java_sha256": digest(java),
            "harness_sha256": digest(ROOT / "toolkit-cli/research/local_cgate.py"),
            "capture_script_sha256": digest(Path(__file__)),
            "physical_endpoint": False, "children": children,
        },
        "server": cases,
        "socket": socket_result,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = capture(args.vendor.resolve(), args.java.resolve())
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"children": len(report["oracle"]["children"]), "cleanup": True}))
