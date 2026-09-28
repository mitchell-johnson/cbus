"""Capture the original C-Gate event-millis restart effect on owned loopback children.

The first child's CONFIG SAVE is checked in its temporary directory. Only the
single verified setting is copied into each fresh child's startup config.
No installed daemon, project, C-Bus endpoint, or host configuration is used.
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

from native_config_effects_probe import command, drain_events, socket_line

EVENT = re.compile(
    r"#e# ([0-9]{8}-[0-9]{6}(?:\.[0-9]{3})?) (761|703|766|767) cmd[0-9]+ - (.*)"
)


def configured_oracle(vendor, java, setting=None, *, show_time=False):
    oracle = LocalCGate(vendor, java=java)
    if setting is not None:
        if setting not in ("yes", "no"):
            raise ValueError("Only native yes/no startup values are admitted")
        with (oracle.work / "config/C-GateConfig.txt").open("a") as config:
            config.write(f"event-millis={setting}\n")
    if show_time:
        with (oracle.work / "config/C-GateConfig.txt").open("a") as config:
            config.write("command.show-time=yes\n")
    return oracle


def session(oracle, cases, *, saved=None, timed=False):
    with oracle:
        with socket.create_connection(("127.0.0.1", oracle.port), timeout=15) as subscriber:
            greeting = socket_line(subscriber)
            if not greeting.startswith(
                "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)"
            ):
                raise AssertionError(greeting)
            with socket.create_connection(("127.0.0.1", oracle.port), timeout=15) as producer:
                greeting = socket_line(producer)
                if not greeting.startswith(
                    "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)"
                ):
                    raise AssertionError(greeting)
                subscriber.sendall(b"[subscribe] EVENT e9s0c0\r\n")
                if socket_line(subscriber) != "[subscribe] 200 OK.":
                    raise AssertionError("Native event subscription failed")
                drain_events(subscriber)
                stream = producer.makefile("rwb", buffering=0)
                captured = []
                for tag, body, final, milliseconds in cases:
                    response = command(stream, tag, body)
                    if response[-1] != f"[{tag}] {final}":
                        raise AssertionError((body, response))
                    expected = [(761, f"Command: [{tag}] {body}")]
                    if body.startswith("BROADCAST_EVENT "):
                        expected.append((703, "broadcast_event " + body[len("BROADCAST_EVENT "):]))
                    expected.extend((766, f"Response: {row}") for row in response)
                    if timed:
                        expected.append((767, f"commandId={tag} time=<nonnegative-ms>"))
                    rows = drain_events(subscriber)
                    if len(rows) != len(expected):
                        raise AssertionError((body, rows, expected))
                    events = []
                    for row, (code, text) in zip(rows, expected):
                        match = EVENT.fullmatch(row)
                        if match is None or int(match[2]) != code:
                            raise AssertionError((body, row, code, text))
                        actual_text = match[3]
                        if code == 767:
                            if re.fullmatch(rf"commandId={re.escape(tag)} time=[0-9]+", actual_text) is None:
                                raise AssertionError((body, row, code, text))
                            actual_text = text
                        if actual_text != text:
                            raise AssertionError((body, row, code, text))
                        actual_milliseconds = "." in match[1]
                        if actual_milliseconds != milliseconds:
                            raise AssertionError((body, row, milliseconds))
                        events.append({
                            "code": code,
                            "session": "cmd<owned-session>",
                            "timestamp_shape": "YYYYMMDD-HHMMSS.mmm" if milliseconds else "YYYYMMDD-HHMMSS",
                            "text": text,
                        })
                    captured.append({"command": body, "response": response, "events": events})
                if saved is not None:
                    config = (oracle.work / "config/C-GateConfig.txt").read_text()
                    if f"event-millis={saved}" not in config.splitlines():
                        raise AssertionError("Native CONFIG SAVE did not retain event-millis")
                return captured


def capture(vendor, java, output):
    report = {
        "format": "native-cgate-config-event-millis-v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "oracle": {
            "product": "Schneider Electric C-Gate",
            "version": "3.4.0.2001",
            "jar_sha256": hashlib.sha256((vendor / "cgate.jar").read_bytes()).hexdigest(),
            "java_sha256": hashlib.sha256(java.read_bytes()).hexdigest(),
            "transport": "fresh owned Java 11 child per startup value; IPv4 loopback command/event listeners; no C-Bus endpoint",
        },
        "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "local_cgate_harness_sha256": hashlib.sha256((REPOSITORY / "toolkit-cli/research/local_cgate.py").read_bytes()).hexdigest(),
        "method": "Default yes was changed and saved to no without restarting. The saved key was replayed into a fresh owned child. That child changed and saved no to yes without restarting. A third owned child started with yes. A fourth child started with event-millis=no and command.show-time=yes to check 767 precision. Timestamps, timing durations and owned session numbers are normalized, while event codes, other content, order, command replies and timestamp precision are retained.",
        "cases": {},
    }
    children = []
    try:
        first = configured_oracle(vendor, java)
        children.append(("default", first))
        report["cases"]["default_then_set_no"] = session(first, [
            ("before", "NOOP", "200 OK.", True),
            ("set-no", "CONFIG SET event-millis no", "200 OK.", True),
            ("read-no", "CONFIG GET event-millis", "303 event-millis=no", True),
            ("still-yes", "BROADCAST_EVENT XX class payload", "200 OK.", True),
            ("save-no", "CONFIG SAVE global", "200 OK.", True),
        ], saved="no")
        second = configured_oracle(vendor, java, "no")
        children.append(("no", second))
        report["cases"]["startup_no_then_set_yes"] = session(second, [
            ("after-restart", "NOOP", "200 OK.", False),
            ("broadcast-no", "BROADCAST_EVENT XX class payload", "200 OK.", False),
            ("set-yes", "CONFIG SET event-millis yes", "200 OK.", False),
            ("read-yes", "CONFIG GET event-millis", "303 event-millis=yes", False),
            ("still-no", "NOOP", "200 OK.", False),
            ("save-yes", "CONFIG SAVE global", "200 OK.", False),
        ], saved="yes")
        third = configured_oracle(vendor, java, "yes")
        children.append(("yes", third))
        report["cases"]["startup_yes"] = session(third, [
            ("second-restart", "BROADCAST_EVENT XX class payload", "200 OK.", True),
        ])
        fourth = configured_oracle(vendor, java, "no", show_time=True)
        children.append(("timed_no", fourth))
        report["cases"]["startup_no_with_timing"] = session(fourth, [
            ("timed", "NOOP", "200 OK.", False),
        ], timed=True)
    finally:
        for _, child in children:
            if not child.closed:
                child.close()
    for name, child in children:
        report["oracle"][name + "_cleanup"] = {
            key: child.report[key] for key in (
                "listener_ownership_verified", "cleanup_complete", "process_exit_confirmed",
                "work_removed", "server_log_sha256",
            )
        }
        if not child.report["cleanup_complete"]:
            raise RuntimeError("Owned native cleanup incomplete")
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-dir", required=True, type=Path)
    parser.add_argument("--java", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    evidence = capture(args.vendor_dir.resolve(), args.java.resolve(), args.output.resolve())
    print(json.dumps({"output": str(args.output), "cases": sum(map(len, evidence["cases"].values())), "cleanup": True}))
