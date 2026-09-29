#!/usr/bin/env python3
"""Capture the owned C-Gate 3.4 event.display-oids CONFIG restart boundary."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import socket
import time

from local_cgate import JAR_SHA256, LocalCGate


STAMP = re.compile(r"^(#e# )?\d{8}-\d{6}(\.\d{3})? ")
SESSION = re.compile(r"\bcmd\d+\b")


class Peer:
    def __init__(self, port: int):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.socket.settimeout(0.1)
        self.pending = b""
        greeting = self.collect(0.2)
        assert greeting == [
            "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001) #cmd-syntax=1.0"
        ], greeting

    def collect(self, seconds: float) -> list[str]:
        deadline = time.monotonic() + seconds
        lines: list[str] = []
        while time.monotonic() < deadline:
            try:
                chunk = self.socket.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            self.pending += chunk
            while b"\n" in self.pending:
                line, self.pending = self.pending.split(b"\n", 1)
                lines.append(line.rstrip(b"\r").decode("utf-8"))
        return lines

    def command(self, tag: str, body: str) -> list[str]:
        self.socket.sendall(f"[{tag}] {body}\r\n".encode())
        lines: list[str] = []
        deadline = time.monotonic() + 5
        final = re.compile(rf"^\[{re.escape(tag)}\] \d{{3}} ")
        while time.monotonic() < deadline:
            lines.extend(self.collect(0.1))
            if any(final.match(line) for line in lines):
                return [line for line in lines if line.startswith(f"[{tag}] ")]
        raise TimeoutError(f"No final reply for {body}")

    def close(self) -> None:
        self.socket.close()


def normalize(lines: list[str]) -> list[str]:
    rows = []
    for line in lines:
        if not STAMP.match(line):
            continue
        line = STAMP.sub(lambda m: (m.group(1) or "") + "<timestamp> ", line)
        line = SESSION.sub("cmd<N>", line)
        line = re.sub(r"port: \d+", "port: <port>", line)
        line = re.sub(r"time=\d+", "time=<ms>", line)
        rows.append(line)
    return rows


def capture(vendor: Path, java: Path, startup: str) -> dict:
    service = LocalCGate(vendor, java=java)
    with (service.work / "config/C-GateConfig.txt").open("a") as config:
        config.write(f"event.display-oids={startup}\nheartbeat-time=1\ncommand.show-time=yes\n")
    with service:
        monitor = Peer(service.port)
        try:
            assert monitor.command("event", "EVENT e9s0c0") == ["[event] 200 OK."]
            monitor.collect(0.3)
            command = Peer(service.port)
            noop = command.command("noop", "NOOP")
            set_reply = command.command("set", "CONFIG SET event.display-oids " + ("no" if startup == "yes" else "yes"))
            broadcast = command.command("bcast", "BROADCAST_EVENT oracle display-oids")
            command.close()
            observed = normalize(monitor.collect(1.6))
            result = {
                "startup_event_display_oids": startup,
                "replies": noop + set_reply + broadcast,
                "monitor_events": sorted(set(observed)),
            }
        finally:
            monitor.close()
    assert service.report["cleanup_complete"] is True
    result["owned_child_cleanup_complete"] = True
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "oracle": {
            "product": "Schneider Electric C-Gate",
            "version": "3.4.0 build 2001",
            "jar_sha256": JAR_SHA256,
            "environment": "owned Java 11 child; verified IPv4 loopback listeners; disposable work directory; no C-Bus endpoint",
        },
        "scope": "Startup event.display-oids yes and no with heartbeat-time=1 and command.show-time=yes; one same-process SET of the opposite value; timestamps, session numbers, ports and durations normalized; distinct monitor rows retained",
        "cases": [capture(args.vendor, args.java, startup) for startup in ("yes", "no")],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
