#!/usr/bin/env python3
"""Capture CONFIG global-event-level against one owned loopback C-Gate child."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import time

from local_cgate import JAR_SHA256, LocalCGate


GREETING = "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001) #cmd-syntax=1.0"
EVENT = re.compile(r"^(?:#e# )?\d{8}-\d{6}(?:\.\d{3})? (7\d\d) (.*)$")


class FailedStartupCGate(LocalCGate):
    def _cleanup_preserving(self, error):
        # Capture only the exception type, never copy the owned process log
        # or its generated key material into the committed fixture.
        log = self.work / "process.log"
        if log.exists():
            self.report["number_format_exception"] = any(
                line.startswith('Exception in thread "main" java.lang.NumberFormatException:')
                for line in log.read_text(errors="replace").splitlines()
            )
        super()._cleanup_preserving(error)


class Peer:
    def __init__(self, port: int):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.socket.settimeout(.05)
        self.pending = b""
        greeting = []
        deadline = time.monotonic() + 2
        while not greeting and time.monotonic() < deadline:
            greeting.extend(self.collect(.1))
        assert greeting == [GREETING], greeting

    def collect(self, seconds: float) -> list[str]:
        deadline = time.monotonic() + seconds
        lines = []
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
        lines = []
        deadline = time.monotonic() + 5
        final = re.compile(rf"^\[{re.escape(tag)}\] \d{{3}} ")
        while time.monotonic() < deadline:
            lines.extend(self.collect(.05))
            if any(final.match(line) for line in lines):
                return [line for line in lines if line.startswith(f"[{tag}] ")]
        raise TimeoutError(f"No final reply for {body}")

    def close(self):
        self.socket.close()


def normalize(lines: list[str], marker: str, tag: str) -> list[dict]:
    result = []
    for line in lines:
        match = EVENT.fullmatch(line)
        if match and (marker in match.group(2) or tag in match.group(2)):
            result.append({"code": int(match.group(1)), "text": re.sub(r"cmd\d+", "cmd<owned-session>", match.group(2))})
    return result


def startup_case(vendor: Path, java: Path, level: int) -> dict:
    service = LocalCGate(vendor, java=java)
    with (service.work / "config/C-GateConfig.txt").open("a") as config:
        config.write("command.show-time=yes\nheartbeat-time=1\n")
        config.write(f"global-event-level={level}\n")
    with service:
        plus = Peer(service.port)
        nine = Peer(service.port)
        producer = Peer(service.port)
        try:
            assert plus.command("plus", "EVENT e+s0c0") == ["[plus] 200 OK."]
            assert nine.command("nine", "EVENT e9s0c0") == ["[nine] 200 OK."]
            plus.collect(.2)
            nine.collect(.2)
            tag = f"level{level}"
            marker = f"gel-startup-{level}"
            assert producer.command(tag, f"BROADCAST_EVENT XX class {marker}") == [f"[{tag}] 200 OK."]
            plus_lines = plus.collect(1.25)
            nine_lines = nine.collect(.1)
            # The command creates 761, 703, 766 and 767. The heartbeat is
            # independent and distinguishes the level-zero boundary.
            plus_codes = [row["code"] for row in normalize(plus_lines, marker, tag)]
            nine_codes = [row["code"] for row in normalize(nine_lines, marker, tag)]
            plus_heartbeats = sum(bool(re.match(r"^\d{8}-\d{6}\.\d{3} 700 cgate - Heartbeat\.$", line)) for line in plus_lines)
            nine_heartbeats = sum(bool(re.match(r"^#e# \d{8}-\d{6}\.\d{3} 700 cgate - Heartbeat\.$", line)) for line in nine_lines)
            assert sorted(nine_codes) == [703, 761, 766, 767], (level, nine_codes)
            assert nine_heartbeats >= 1, (level, nine_lines)
            result = {"startup_value": str(level), "e_plus_codes": plus_codes,
                      "e9_codes": nine_codes, "e_plus_heartbeats": plus_heartbeats,
                      "e9_heartbeats": nine_heartbeats}
        finally:
            plus.close()
            nine.close()
            producer.close()
    assert service.report["cleanup_complete"] is True
    result["owned_child_cleanup_complete"] = True
    result["listener_ownership_verified"] = service.report["listener_ownership_verified"]
    result["process_exit_confirmed"] = service.report["process_exit_confirmed"]
    result["server_log_sha256"] = service.report["server_log_sha256"]
    return result


def explicit_modes_case(vendor: Path, java: Path) -> dict:
    service = LocalCGate(vendor, java=java)
    with (service.work / "config/C-GateConfig.txt").open("a") as config:
        config.write("command.show-time=yes\nheartbeat-time=1\nglobal-event-level=0\n")
    modes = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    with service:
        peers = {level: Peer(service.port) for level in modes}
        producer = Peer(service.port)
        try:
            for level, peer in peers.items():
                assert peer.command(f"mode{level}", f"EVENT e{level}s0c0") == [f"[mode{level}] 200 OK."]
                peer.collect(.05)
            marker = "gel-explicit-mode"
            tag = "explicit"
            assert producer.command(tag, f"BROADCAST_EVENT XX class {marker}") == [f"[{tag}] 200 OK."]
            time.sleep(1.2)
            rows = {}
            for level, peer in peers.items():
                lines = peer.collect(.1)
                rows[str(level)] = {
                    "codes": [row["code"] for row in normalize(lines, marker, tag)],
                    "heartbeat_count": sum(bool(re.match(r"^#e# \d{8}-\d{6}\.\d{3} 700 cgate - Heartbeat\.$", line)) for line in lines),
                }
        finally:
            for peer in peers.values():
                peer.close()
            producer.close()
    assert service.report["cleanup_complete"] is True
    return {"startup_global_event_level": "0", "modes": rows,
            "owned_child_cleanup_complete": True,
            "listener_ownership_verified": service.report["listener_ownership_verified"],
            "process_exit_confirmed": service.report["process_exit_confirmed"],
            "server_log_sha256": service.report["server_log_sha256"]}


def malformed_startup_case(vendor: Path, java: Path, value: str) -> dict:
    service = FailedStartupCGate(vendor, java=java)
    with (service.work / "config/C-GateConfig.txt").open("a") as config:
        config.write(f"global-event-level={value}\n")
    try:
        with service:
            raise AssertionError("Malformed global event level unexpectedly opened native listeners")
    except RuntimeError as error:
        report = getattr(error, "local_cgate_report", {})
        assert report.get("number_format_exception") is True, report
        assert report.get("listener_ownership_verified") is False, report
        assert report.get("cleanup_complete") is True, report
        return {"startup_value": value, "number_format_exception": True,
                "command_listeners_opened": False,
                "process_exit_confirmed": report["process_exit_confirmed"],
                "owned_child_cleanup_complete": report["cleanup_complete"],
                "server_log_sha256": report["server_log_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", required=True, type=Path)
    parser.add_argument("--java", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    service = LocalCGate(args.vendor, java=args.java)
    with (service.work / "config/C-GateConfig.txt").open("a") as config:
        config.write("command.show-time=yes\n")
    cases = []
    with service:
        plus = Peer(service.port)
        nine = Peer(service.port)
        producer = Peer(service.port)
        try:
            assert plus.command("plus", "EVENT e+s0c0") == ["[plus] 200 OK."]
            assert nine.command("nine", "EVENT e9s0c0") == ["[nine] 200 OK."]
            plus.collect(.2)
            nine.collect(.2)
            for index, value in enumerate([None, *map(str, range(10)), "-1", "10", "abc", ""]):
                if value is None:
                    set_reply = None
                else:
                    set_reply = producer.command(f"set{index}", f"CONFIG SET global-event-level {value}".rstrip())
                readback = producer.command(f"get{index}", "CONFIG GET global-event-level")
                marker = f"gel-phase-{index}"
                plus.collect(.1)
                nine.collect(.1)
                broadcast = producer.command(f"broadcast{index}", f"BROADCAST_EVENT XX class {marker}")
                tag = f"broadcast{index}"
                plus_events = normalize(plus.collect(.2), marker, tag)
                nine_events = normalize(nine.collect(.2), marker, tag)
                cases.append({"input": value, "set_reply": set_reply,
                              "readback": readback, "broadcast_reply": broadcast,
                              "e_plus_events": plus_events, "e9_events": nine_events})
        finally:
            plus.close()
            nine.close()
            producer.close()
    assert service.report["cleanup_complete"] is True
    report = {"format": "native-cgate-config-global-event-level-v1",
              "captured_at": datetime.now(timezone.utc).isoformat(),
              "oracle": {"version": "3.4.0 build 2001", "jar_sha256": JAR_SHA256,
                         "java_sha256": hashlib.sha256(args.java.read_bytes()).hexdigest(),
                         "transport": "fresh owned Java 11 child, six verified IPv4 loopback listeners, no C-Bus endpoint",
                         "listener_ownership_verified": service.report["listener_ownership_verified"],
                         "cleanup_complete": service.report["cleanup_complete"],
                         "process_exit_confirmed": service.report["process_exit_confirmed"],
                         "server_log_sha256": service.report["server_log_sha256"]},
              "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "local_cgate_harness_sha256": hashlib.sha256(Path(__file__).with_name("local_cgate.py").read_bytes()).hexdigest(),
              "method": "Owned Java 11 loopback children with command.show-time=yes and no C-Bus endpoint. One child tests same-process SET across 0..9 and malformed values. Twelve fresh children sample startup -1, 0..9, and 10 with e+ and e9 subscribers, BROADCAST_EVENT and heartbeat-time=1. Two malformed startup children prove main-thread NumberFormatException before command listeners. Timestamps and owned session IDs are normalized.",
              "runtime_updates": cases,
              "startup_levels": [startup_case(args.vendor, args.java, level) for level in (-1, *range(10), 10)],
              "explicit_modes": explicit_modes_case(args.vendor, args.java),
              "malformed_startups": [malformed_startup_case(args.vendor, args.java, value) for value in ("abc", "")]}
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
