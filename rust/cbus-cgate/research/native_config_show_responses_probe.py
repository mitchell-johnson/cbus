"""Capture native C-Gate command.show-responses effects on owned loopback children.

Only a fresh temporary native child, its temporary config and loopback sockets
are used. No existing C-Gate service, project or C-Bus endpoint is adopted.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / "toolkit-cli/research"))
from local_cgate import LocalCGate


def socket_line(sock):
    data = bytearray()
    while len(data) < 8192:
        value = sock.recv(1)
        if not value:
            raise EOFError("native socket closed before line ending")
        data.extend(value)
        if value == b"\n":
            return data.decode("utf-8", errors="replace").rstrip("\r\n")
    raise AssertionError("native line exceeded bounded probe limit")


def command(sock, tag, body):
    sock.sendall(f"[{tag}] {body}\r\n".encode())
    rows = []
    while True:
        row = socket_line(sock)
        if row.startswith("#"):
            continue
        rows.append(row)
        if row.startswith(f"[{tag}] ") and row[len(tag) + 6] == " ":
            return rows


def drain(sock):
    sock.settimeout(0.2)
    data = bytearray()
    while len(data) < 65536:
        try:
            chunk = sock.recv(8192)
        except socket.timeout:
            break
        if not chunk:
            break
        data.extend(chunk)
    if len(data) >= 65536:
        raise AssertionError("event output exceeded bounded probe limit")
    return data.decode("utf-8", errors="replace").splitlines()


def normalize_events(lines):
    result = []
    for line in lines:
        match = re.fullmatch(
            r"#e# ([0-9]{8}-[0-9]{6}\.[0-9]{3}) (761|766) cmd([0-9]+) - (Command|Response): (.*)",
            line,
        )
        if match is None:
            raise AssertionError(f"unexpected native event envelope: {line!r}")
        result.append({
            "event_code": int(match.group(2)),
            "session_id": "cmd<owned-session>",
            "timestamp_shape": "YYYYMMDD-HHMMSS.mmm",
            "message": f"{match.group(4)}: {match.group(5)}",
        })
    return result


def configured_oracle(vendor, java, setting=None):
    oracle = LocalCGate(vendor, java=java)
    if setting is not None:
        if setting not in ("yes", "no"):
            raise ValueError("only yes/no startup values are admitted")
        with (oracle.work / "config/C-GateConfig.txt").open("a") as config:
            config.write(f"command.show-responses={setting}\n")
    return oracle


def session(oracle, commands, *, responses_enabled, saved_value=None):
    try:
        with oracle:
            with socket.create_connection(("127.0.0.1", oracle.port), timeout=15) as subscriber:
                subscriber.settimeout(15)
                greeting = socket_line(subscriber)
                assert greeting.startswith(
                    "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)"
                ), greeting
                with socket.create_connection(("127.0.0.1", oracle.port), timeout=15) as producer:
                    producer.settimeout(15)
                    assert socket_line(producer).startswith("201 Service ready:")
                    assert command(subscriber, "subscribe", "EVENT e9s9c9") == ["[subscribe] 200 OK."]
                    drain(subscriber)
                    result = []
                    for tag, body in commands:
                        reply = command(producer, tag, body)
                        events = normalize_events(drain(subscriber))
                        assert events[0]["message"] == f"Command: [{tag}] {body}"
                        assert [event["event_code"] for event in events] == (
                            [761] + [766] * len(reply) if responses_enabled else [761]
                        ), (body, reply, events)
                        if responses_enabled:
                            assert [event["message"] for event in events[1:]] == [
                                f"Response: {row}" for row in reply
                            ]
                        result.append({"command": body, "response": reply, "events": events})
                    if saved_value is not None:
                        config = (oracle.work / "config/C-GateConfig.txt").read_text()
                        assert f"command.show-responses={saved_value}" in config.splitlines()
                    return result
    finally:
        if not oracle.closed:
            oracle.close()


def self_subscribed_session(oracle):
    """Pin native ordering on a connection that subscribes to its own events."""
    try:
        with oracle:
            with socket.create_connection(("127.0.0.1", oracle.port), timeout=15) as client:
                client.settimeout(15)
                assert socket_line(client).startswith("201 Service ready:")
                client.sendall(b"[subscribe] EVENT e9s0c0\r\n")
                reply = socket_line(client)
                assert reply == "[subscribe] 200 OK.", reply
                after_subscribe = [
                    normalize_events([line])[0] for line in drain(client)
                    if " 761 cmd" in line or " 766 cmd" in line
                ]
                assert [event["event_code"] for event in after_subscribe] == [766], after_subscribe
                assert after_subscribe[0]["message"] == "Response: [subscribe] 200 OK."

                client.settimeout(5)
                client.sendall(b"[self] NOOP\r\n")
                order = []
                while len(order) < 3:
                    line = socket_line(client)
                    if line.startswith("[self] "):
                        assert line == "[self] 200 OK."
                        order.append({"reply": line})
                    elif " 761 cmd" in line or " 766 cmd" in line:
                        order.extend(normalize_events([line]))
                codes = [entry.get("event_code") for entry in order]
                assert codes.count(761) == codes.count(766) == codes.count(None) == 1, order
                assert codes.index(766) > codes.index(None), order
                assert next(entry for entry in order if entry.get("event_code") == 761)["message"] == "Command: [self] NOOP"
                assert next(entry for entry in order if entry.get("event_code") == 766)["message"] == "Response: [self] 200 OK."
                return {"subscribe_reply": reply, "post_subscribe": after_subscribe,
                        "self_noop_order": order}
    finally:
        if not oracle.closed:
            oracle.close()


def capture(vendor, java, output):
    report = {
        "format": "native-cgate-config-command-show-responses-v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "oracle": {
            "product": "Schneider Electric C-Gate",
            "version": "3.4.0.2001",
            "jar_sha256": hashlib.sha256((vendor / "cgate.jar").read_bytes()).hexdigest(),
            "java_sha256": hashlib.sha256(java.read_bytes()).hexdigest(),
            "transport": "fresh owned Java 11 children; IPv4 loopback command/event listeners; no C-Bus endpoint",
        },
        "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "local_cgate_harness_sha256": hashlib.sha256((REPOSITORY / "toolkit-cli/research/local_cgate.py").read_bytes()).hexdigest(),
        "method": "A fresh child starts with the native default yes, SETs no, and saves the owned global config. A second fresh child starts with no, SETs yes and reads it back without restarting. A third fresh child starts with yes. Each command uses a separate producer and e9s9c9 subscriber; 761 and 766 events are checked against exact command and response rows. A fourth fresh child checks same-socket delivery: EVENT enable receives its own 766 but not 761, then NOOP produces one 761, its reply and one 766. The relative order of 761 and the reply is scheduler-dependent in two owned runs; 766 followed the reply in both. Timestamps and generated session IDs are shape-validated then normalized. All four children and listeners are closed and removed before the fixture is retained.",
        "cases": {},
    }
    children = []
    try:
        for setting, commands, responses_enabled, saved_value in [
            (None, [("before", "NOOP"), ("info", "CONFIG INFO command.show-responses"), ("info-network", "CONFIG INFO allow-fast-start"), ("set-no", "CONFIG SET command.show-responses no"), ("after-set", "NOOP"), ("save", "CONFIG SAVE global")], True, "no"),
            ("no", [("after-restart", "NOOP"), ("info-no", "CONFIG INFO command.show-responses"), ("invalid", "CONFIG SET no-such-parameter yes"), ("set-yes", "CONFIG SET command.show-responses yes"), ("read-yes", "CONFIG GET command.show-responses"), ("before-next-restart", "NOOP")], False, None),
            ("yes", [("after-second-restart", "NOOP"), ("info-yes", "CONFIG INFO command.show-responses"), ("info-network-yes", "CONFIG INFO allow-fast-start")], True, None),
        ]:
            oracle = configured_oracle(vendor, java, setting)
            children.append(oracle)
            report["cases"]["startup_" + (setting or "default")] = session(
                oracle, commands, responses_enabled=responses_enabled, saved_value=saved_value,
            )
            report["oracle"]["cleanup_" + (setting or "default")] = {
                key: oracle.report[key] for key in (
                    "listener_ownership_verified", "cleanup_complete",
                    "process_exit_confirmed", "work_removed", "server_log_sha256",
                )
            }
        self_oracle = configured_oracle(vendor, java)
        children.append(self_oracle)
        report["cases"]["self_subscribed"] = self_subscribed_session(self_oracle)
        report["oracle"]["cleanup_self"] = {
            key: self_oracle.report[key] for key in (
                "listener_ownership_verified", "cleanup_complete",
                "process_exit_confirmed", "work_removed", "server_log_sha256",
            )
        }
    finally:
        for child in children:
            if not child.closed:
                child.close()
    if not all(report["oracle"]["cleanup_" + case]["cleanup_complete"] for case in ("default", "no", "yes", "self")):
        raise RuntimeError("owned native cleanup incomplete")
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-dir", required=True, type=Path)
    parser.add_argument("--java", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    evidence = capture(args.vendor_dir.resolve(), args.java.resolve(), args.output.resolve())
    print(json.dumps({
        "output": str(args.output),
        "command_cases": sum(len(rows) for name, rows in evidence["cases"].items() if name.startswith("startup_")),
        "self_ordering": True,
        "cleanup": True,
    }))
