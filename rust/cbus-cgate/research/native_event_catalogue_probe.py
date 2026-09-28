#!/usr/bin/env python3
"""Capture bounded C-Gate 3.4 event codes and command traces on owned loopback.

The only original process is a fresh LocalCGate child for each level. No site
project, installed service, physical interface, or external listener is used.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import select
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "toolkit-cli/research"))
from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EventReader:
    def __init__(self, peer: socket.socket) -> None:
        self.peer = peer
        self.pending = b""

    def take(self, duration: float = 0.3) -> list[str]:
        end = time.monotonic() + duration
        while time.monotonic() < end:
            ready, _, _ = select.select([self.peer], [], [], end - time.monotonic())
            if not ready:
                break
            chunk = self.peer.recv(65536)
            if not chunk:
                break
            self.pending += chunk
        *rows, self.pending = self.pending.split(b"\n")
        return [row.decode("utf-8").rstrip("\r") for row in rows]


def command(stream, tag: str, body: str) -> list[str]:
    stream.write(f"[{tag}] {body}\r\n".encode())
    rows = []
    while True:
        line = stream.readline().decode().rstrip("\r\n")
        if not line:
            raise EOFError((body, rows))
        rows.append(line)
        if line.startswith(f"[{tag}] ") and line[len(tag) + 6] == " ":
            return rows


def codes(rows: list[str]) -> list[str]:
    return [row.split(" ", 2)[1] for row in rows]


def capture_level(vendor: Path, java: Path, level: int) -> dict:
    server = LocalCGate(vendor, java=java)
    config = server.work / "config/C-GateConfig.txt"
    config.write_text(config.read_text() + f"global-event-level={level}\n")
    try:
        with server:
            with socket.create_connection(("127.0.0.1", server.event_port), timeout=3) as event_peer:
                events = EventReader(event_peer)
                # The original logs its startup warnings shortly after all
                # six listeners bind. This early peer observes that window.
                time.sleep(0.4)
                early = events.take(0.15)
                with socket.create_connection(("127.0.0.1", server.port), timeout=3) as command_peer:
                    command_peer.settimeout(3)
                    stream = command_peer.makefile("rwb", buffering=0)
                    greeting = stream.readline().decode().rstrip("\r\n")
                    assert greeting.startswith("201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)")
                    time.sleep(0.1)
                    accepted = events.take(0.2)
                    exchanges = []
                    if level == 9:
                        for tag, body in (
                            ("set", "CONFIG SET heartbeat-time 7"),
                            ("get", "CONFIG GET heartbeat-time"),
                            ("known", "CONFIG BOGUS"),
                            ("failed", "CONFIG GET nonexistent"),
                            ("unknown", "UNKNOWN_CMD"),
                            ("noop", "NOOP"),
                            ("quit", "QUIT"),
                        ):
                            reply = command(stream, tag, body)
                            # Separate envelopes without depending on native
                            # millisecond scheduling of individual trace rows.
                            time.sleep(0.04)
                            exchanges.append({"tag": tag, "command": body, "reply": reply,
                                              "events": events.take(0.15)})
                    result = {
                        "level": level,
                        "greeting": greeting,
                        "early_event_rows": early,
                        "accepted_event_rows": accepted,
                        "exchanges": exchanges,
                    }
    finally:
        server.close()
    result["cleanup"] = {key: server.report[key] for key in (
        "listener_ownership_verified", "process_exit_confirmed",
        "cleanup_complete", "work_removed")}
    assert all(result["cleanup"].values())
    return result


def capture(vendor: Path, java: Path) -> dict:
    sources = [Path(__file__), ROOT / "toolkit-cli/research/local_cgate.py"]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    cases = {}
    for level in (7, 8, 9):
        cases[str(level)] = capture_level(vendor, java, level)
    assert hashes == {str(path.relative_to(ROOT)): digest(path) for path in sources}
    assert "938" not in codes(cases["7"]["early_event_rows"])
    assert "938" in codes(cases["8"]["early_event_rows"])
    assert "899" in codes(cases["9"]["early_event_rows"])
    assert "999" in codes(cases["9"]["accepted_event_rows"])
    unknown = next(row for row in cases["9"]["exchanges"] if row["tag"] == "unknown")
    assert unknown["reply"] == ["[unknown] 400 Syntax Error."]
    assert "766" in codes(unknown["events"]) and "761" not in codes(unknown["events"])
    known = next(row for row in cases["9"]["exchanges"] if row["tag"] == "known")
    assert "761" in codes(known["events"]) and "766" in codes(known["events"])
    return {
        "schema": "native-cgate-event-catalogue-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Owned loopback global levels 7/8/9, CONFIG read/write/failure, unknown command, NOOP, QUIT; no physical endpoint",
        "oracle": {"version": "3.4.0 build 2001", "jar_sha256": JAR_SHA256,
                   "java_sha256": digest(java), "source_hashes": hashes,
                   "physical_endpoint": False},
        "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = capture(args.vendor.resolve(), args.java.resolve())
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"levels": list(report["cases"]), "source_bound": True}))
