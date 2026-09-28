#!/usr/bin/env python3
"""Capture the owned C-Gate 3.4 heartbeat CONFIG restart boundary."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import socket
import time

from local_cgate import JAR_SHA256, LocalCGate


HEARTBEAT = re.compile(r"^#e# (\d{8}-\d{6}\.\d{3}) 700 cgate - Heartbeat\.$")


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


def heartbeat_rows(lines: list[str]) -> dict:
    stamps = [datetime.strptime(match.group(1), "%Y%m%d-%H%M%S.%f")
              for line in lines if (match := HEARTBEAT.fullmatch(line))]
    return {
        "count": len(stamps),
        "normalized_wire": "#e# <timestamp> 700 cgate - Heartbeat." if stamps else None,
        "spacings_seconds": [round((b - a).total_seconds(), 3)
                             for a, b in zip(stamps, stamps[1:])],
    }


def capture(vendor: Path, java: Path, startup: int) -> dict:
    service = LocalCGate(vendor, java=java)
    with (service.work / "config/C-GateConfig.txt").open("a") as config:
        config.write(f"heartbeat-time={startup}\n")
    with service:
        monitor = Peer(service.port)
        command = Peer(service.port)
        try:
            assert monitor.command("event", "EVENT e9s0c0") == ["[event] 200 OK."]
            monitor.collect(0.25)
            before = heartbeat_rows(monitor.collect({0: 2.2, 1: 3.2, 2: 4.6}[startup]))
            set_reply = command.command("set", "CONFIG SET heartbeat-time 0")
            get_reply = command.command("get", "CONFIG GET heartbeat-time")
            after = heartbeat_rows(monitor.collect({0: 1.2, 1: 2.2, 2: 2.7}[startup]))
            assert set_reply == ["[set] 200 OK."] and get_reply == ["[get] 303 heartbeat-time=0"]
            assert (before["count"] == 0) if startup == 0 else (before["count"] >= 2)
            assert (after["count"] == 0) if startup == 0 else (after["count"] >= 1)
            for row in (before, after):
                if startup:
                    assert all(abs(seconds - startup) < 0.4 for seconds in row["spacings_seconds"]), row
            result = {
                "startup_heartbeat_time": str(startup),
                "subscription_reply": "[event] 200 OK.",
                "before_set": before,
                "set_reply": set_reply[0],
                "readback_reply": get_reply[0],
                "after_set": after,
            }
        finally:
            monitor.close()
            command.close()
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
            "environment": "owned Java 11 child; six verified IPv4 loopback listeners; disposable work directory; no C-Bus endpoint",
        },
        "scope": "Valid startup values 0, 1 and 2 seconds; one same-process SET 0 per start; timestamp and child session identity normalized",
        "cases": [capture(args.vendor, args.java, startup) for startup in (0, 1, 2)],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
