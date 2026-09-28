#!/usr/bin/env python3
"""Capture C-Gate's startup-only project.default session selection.

The two original-daemon children own their loopback listeners and a disposable
synthetic project.  No installed service or C-Bus endpoint is adopted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / "toolkit-cli/research"))

from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402


def connect(service: LocalCGate):
    peer = socket.create_connection(("127.0.0.1", service.port), timeout=10)
    peer.settimeout(10)
    stream = peer.makefile("rwb", buffering=0)
    greeting = stream.readline().decode().rstrip("\r\n")
    assert greeting.startswith(
        "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)"
    ), greeting
    return peer, stream


def command(stream, tag: str, body: str, expected: str) -> dict:
    stream.write(f"[{tag}] {body}\r\n".encode())
    rows = []
    while True:
        row = stream.readline().decode().rstrip("\r\n")
        if not row:
            raise EOFError((tag, body, rows))
        rows.append(row)
        if row.startswith(f"[{tag}] ") and len(row) > len(tag) + 6 and row[len(tag) + 6] == " ":
            assert row == f"[{tag}] {expected}", (body, rows)
            return {"command": body, "response": rows}


def report_child(service: LocalCGate) -> dict:
    assert service.report["listener_ownership_verified"]
    assert service.report["cleanup_complete"]
    return {
        "listeners_owned": service.report["listener_ownership_verified"],
        "process_exit_confirmed": service.report["process_exit_confirmed"],
        "cleanup_complete": service.report["cleanup_complete"],
        "work_removed": service.report["work_removed"],
    }


def capture(vendor: Path, java: Path) -> dict:
    first = LocalCGate(vendor, java=java)
    first_rows = []
    with first:
        peer, stream = connect(first)
        try:
            for tag, body, final in [
                ("initial", "PROJECT USE", "123 project=null"),
                ("create", "PROJECT NEW XDFLT", "200 OK."),
                ("save-project", "PROJECT SAVE XDFLT", "200 OK."),
                ("close-project", "PROJECT CLOSE XDFLT", "200 OK."),
                ("load-project", "PROJECT LOAD XDFLT", "200 OK."),
                ("set", "CONFIG SET project.default XDFLT", "200 OK."),
                ("read", "CONFIG GET project.default", "303 project.default=XDFLT"),
                ("save-config", "CONFIG SAVE global", "200 OK."),
            ]:
                first_rows.append(command(stream, tag, body, final))
            db_file = first.work / "Projects/XDFLT/XDFLT.db"
            project_bytes = db_file.read_bytes()
            saved_config = (first.work / "config/C-GateConfig.txt").read_text()
            assert "project.default=XDFLT" in saved_config.splitlines()
            pending_peer, pending_stream = connect(first)
            try:
                first_rows.append(
                    command(pending_stream, "pending", "PROJECT USE", "123 project=")
                )
            finally:
                pending_peer.close()
        finally:
            peer.close()
    first_cleanup = report_child(first)

    second = LocalCGate(vendor, java=java)
    project_file = second.work / "Projects/XDFLT/XDFLT.db"
    project_file.parent.mkdir(parents=True)
    project_file.write_bytes(project_bytes)
    config = second.work / "config/C-GateConfig.txt"
    source = config.read_text()
    assert source.count("project.default=\n") == 1
    config.write_text(source.replace("project.default=\n", "project.default=XDFLT\n"))
    second_rows = []
    with second:
        peer, stream = connect(second)
        try:
            # C-Gate selects a configured default only after that project is
            # loaded.  cmqttd's repository currently loads all projects.
            second_rows.append(command(stream, "unloaded", "PROJECT USE", "123 project=null"))
            second_rows.append(command(stream, "load", "PROJECT LOAD XDFLT", "200 OK."))
            loaded_peer, loaded_stream = connect(second)
            try:
                second_rows.append(
                    command(loaded_stream, "loaded", "PROJECT USE", "123 project=XDFLT")
                )
                second_rows.append(
                    command(loaded_stream, "set-later", "CONFIG SET project.default XOTHER", "200 OK.")
                )
                second_rows.append(
                    command(loaded_stream, "read-later", "CONFIG GET project.default", "303 project.default=XOTHER")
                )
            finally:
                loaded_peer.close()
            still_peer, still_stream = connect(second)
            try:
                second_rows.append(
                    command(still_stream, "still-startup", "PROJECT USE", "123 project=XDFLT")
                )
            finally:
                still_peer.close()
        finally:
            peer.close()
    second_cleanup = report_child(second)

    return {
        "schema": "native-cgate-config-project-default-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "oracle": {
            "version": "3.4.0 build 2001",
            "jar_sha256": JAR_SHA256,
            "java_sha256": hashlib.sha256(java.read_bytes()).hexdigest(),
            "harness_sha256": hashlib.sha256((REPOSITORY / "toolkit-cli/research/local_cgate.py").read_bytes()).hexdigest(),
            "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "physical_endpoint": False,
            "synthetic_project_db_sha256": hashlib.sha256(project_bytes).hexdigest(),
            "first_child": first_cleanup,
            "second_child": second_cleanup,
        },
        "scope": "One saved synthetic project; project.default startup read, loaded-project requirement, and same-process SET deferral; no vendor project format claim for cmqttd",
        "first_child": first_rows,
        "second_child": second_rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", required=True, type=Path)
    parser.add_argument("--java", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = capture(args.vendor.resolve(), args.java.resolve())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"first": len(result["first_child"]), "second": len(result["second_child"]), "cleanup": True}))
