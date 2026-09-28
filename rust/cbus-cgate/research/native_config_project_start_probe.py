#!/usr/bin/env python3
"""Capture original C-Gate project.start startup and CONFIG lifecycle.

Each server is a directly owned, loopback-only child with disposable synthetic
projects. The oracle never adopts an installed service or a physical endpoint.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "toolkit-cli/research"))

from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402


def connect(server: LocalCGate):
    peer = socket.create_connection(("127.0.0.1", server.port), timeout=10)
    peer.settimeout(10)
    stream = peer.makefile("rwb", buffering=0)
    greeting = stream.readline().decode().rstrip("\r\n")
    assert greeting.startswith(
        "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)"
    ), greeting
    return peer, stream


def command(stream, tag: str, body: str) -> dict:
    stream.write(f"[{tag}] {body}\r\n".encode())
    rows = []
    while True:
        row = stream.readline().decode().rstrip("\r\n")
        if not row:
            raise EOFError((tag, body, rows))
        rows.append(row)
        if row.startswith(f"[{tag}] ") and len(row) > len(tag) + 6 and row[len(tag) + 6] == " ":
            return {"command": body, "response": rows}


def run_commands(server: LocalCGate, specs: list[tuple[str, str]]) -> list[dict]:
    peer, stream = connect(server)
    try:
        rows = [command(stream, tag, body) for tag, body in specs]
        # Native missing-file errors include the random owned temporary root.
        # Preserve the wire wording while making the checked-in receipt stable.
        for row in rows:
            row["response"] = [
                line.replace(str(server.work.resolve()), "%OWNED_WORK%")
                    .replace(str(server.work), "%OWNED_WORK%")
                for line in row["response"]
            ]
        return rows
    finally:
        peer.close()


def configure(server: LocalCGate, *, start: str = "", default: str = "") -> None:
    path = server.work / "config/C-GateConfig.txt"
    source = path.read_text()
    assert source.count("project.start=\n") == 1
    assert source.count("project.default=\n") == 1
    path.write_text(source.replace("project.start=\n", f"project.start={start}\n")
                    .replace("project.default=\n", f"project.default={default}\n"))


def install_projects(server: LocalCGate, blobs: dict[str, bytes]) -> None:
    for name, data in blobs.items():
        path = server.work / f"Projects/{name}/{name}.db"
        path.parent.mkdir(parents=True)
        path.write_bytes(data)


def child_receipt(server: LocalCGate) -> dict:
    assert server.report["listener_ownership_verified"]
    assert server.report["cleanup_complete"]
    return {
        "listeners_owned": True,
        "process_exit_confirmed": server.report["process_exit_confirmed"],
        "cleanup_complete": server.report["cleanup_complete"],
        "work_removed": server.report["work_removed"],
    }


def await_startup(server: LocalCGate, expected: str) -> list[dict]:
    """Observe the asynchronous startup load before treating LIST as settled."""
    peer, stream = connect(server)
    probes = []
    try:
        for attempt in range(80):
            row = command(stream, f"poll-{attempt}", "PROJECT LIST")
            probes.append(row)
            if any(f"project={expected} state=started" in line for line in row["response"]):
                return probes
            time.sleep(.1)
    finally:
        peer.close()
    raise AssertionError((expected, probes[-4:]))


def capture(vendor: Path, java: Path) -> dict:
    seed = LocalCGate(vendor, java=java)
    with seed:
        seed_rows = run_commands(seed, [
            ("new-a", "PROJECT NEW XSTARTA"),
            ("save-a", "PROJECT SAVE XSTARTA"),
            ("new-b", "PROJECT NEW XSTARTB"),
            ("save-b", "PROJECT SAVE XSTARTB"),
        ])
        blobs = {}
        for name in ("XSTARTA", "XSTARTB"):
            blobs[name] = (seed.work / f"Projects/{name}/{name}.db").read_bytes()
    receipts = {"seed": child_receipt(seed)}

    # One named project starts cold, while the default names the other saved
    # project. CONFIG SET and CONFIG LOAD are exercised in the same process.
    first = LocalCGate(vendor, java=java)
    install_projects(first, blobs)
    configure(first, start="XSTARTA", default="XSTARTB")
    with first:
        cold = run_commands(first, [
            ("start-get", "CONFIG GET project.start"),
            ("default-get", "CONFIG GET project.default"),
            ("list", "PROJECT LIST"),
            ("use", "PROJECT USE"),
            ("dir", "PROJECT DIRFULL"),
        ])
        startup_poll = await_startup(first, "XSTARTA")
        settled = run_commands(first, [
            ("settled-list", "PROJECT LIST"),
            ("settled-use", "PROJECT USE"),
        ])
        runtime = run_commands(first, [
            ("save-config", "CONFIG SAVE global retained.conf"),
            ("set-start", "CONFIG SET project.start XSTARTB"),
            ("start-read", "CONFIG GET project.start"),
            ("list-after-set", "PROJECT LIST"),
            ("load-config", "CONFIG LOAD global retained.conf"),
            ("start-after-load", "CONFIG GET project.start"),
            ("list-after-load", "PROJECT LIST"),
        ])
        fresh = run_commands(first, [
            ("fresh-list", "PROJECT LIST"),
            ("fresh-use", "PROJECT USE"),
            ("load-b", "PROJECT LOAD XSTARTB"),
        ])
        default_after_load = run_commands(first, [
            ("loaded-list", "PROJECT LIST"),
            ("loaded-use", "PROJECT USE"),
        ])
        restart_preparation = run_commands(first, [
            ("set-for-restart", "CONFIG SET project.start XSTARTB"),
            ("save-for-restart", "CONFIG SAVE global"),
        ])
        saved_config = (first.work / "config/C-GateConfig.txt").read_text()
        assert saved_config.splitlines().count("project.start=XSTARTB") == 1
        saved_start = next(line.split("=", 1)[1] for line in saved_config.splitlines()
                           if line.startswith("project.start="))
    receipts["single_start"] = child_receipt(first)

    restart = LocalCGate(vendor, java=java)
    install_projects(restart, blobs)
    configure(restart, start=saved_start, default="XSTARTB")
    with restart:
        restart_poll = await_startup(restart, "XSTARTB")
        restart_settled = run_commands(restart, [
            ("restart-get", "CONFIG GET project.start"),
            ("restart-list", "PROJECT LIST"),
            ("restart-use", "PROJECT USE"),
        ])
    receipts["saved_restart"] = child_receipt(restart)

    # A two-name list and a missing name establish split behavior and failure
    # handling at startup without touching any installed project directory.
    second = LocalCGate(vendor, java=java)
    install_projects(second, blobs)
    configure(second, start="XSTARTA XMISSING XSTARTB", default="XSTARTB")
    with second:
        multiple = run_commands(second, [
            ("start-get", "CONFIG GET project.start"),
            ("list", "PROJECT LIST"),
            ("use", "PROJECT USE"),
            ("missing-load", "PROJECT LOAD XMISSING"),
        ])
        multiple_poll = await_startup(second, "XSTARTA")
        multiple_settled = run_commands(second, [
            ("settled-list", "PROJECT LIST"),
            ("settled-use", "PROJECT USE"),
        ])
        multiple_fresh = run_commands(second, [
            ("fresh-list", "PROJECT LIST"),
            ("fresh-use", "PROJECT USE"),
        ])
    receipts["multiple_start"] = child_receipt(second)

    third = LocalCGate(vendor, java=java)
    install_projects(third, blobs)
    configure(third, start="XMISSING", default="XSTARTB")
    with third:
        missing = run_commands(third, [
            ("start-get", "CONFIG GET project.start"),
            ("list", "PROJECT LIST"),
            ("use", "PROJECT USE"),
        ])
        time.sleep(1)
        missing_settled = run_commands(third, [
            ("settled-list", "PROJECT LIST"),
            ("settled-use", "PROJECT USE"),
        ])
        missing_manual = run_commands(third, [
            ("manual-load", "PROJECT LOAD XSTARTB"),
        ])
        missing_fresh = run_commands(third, [
            ("fresh-list", "PROJECT LIST"),
            ("fresh-use", "PROJECT USE"),
        ])
    receipts["missing_start"] = child_receipt(third)

    return {
        "schema": "native-cgate-config-project-start-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "oracle": {
            "version": "3.4.0 build 2001",
            "jar_sha256": JAR_SHA256,
            "java_sha256": hashlib.sha256(java.read_bytes()).hexdigest(),
            "harness_sha256": hashlib.sha256((ROOT / "toolkit-cli/research/local_cgate.py").read_bytes()).hexdigest(),
            "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "physical_endpoint": False,
            "synthetic_project_db_sha256": {name: hashlib.sha256(blob).hexdigest() for name, blob in blobs.items()},
            "children": receipts,
        },
        "seed": seed_rows,
        "single_start": {"cold": cold, "startup_poll": startup_poll, "settled": settled, "runtime": runtime, "fresh": fresh, "default_after_load": default_after_load, "restart_preparation": restart_preparation},
        "saved_restart": {"startup_poll": restart_poll, "settled": restart_settled},
        "multiple_start": {"cold": multiple, "startup_poll": multiple_poll, "settled": multiple_settled, "fresh": multiple_fresh},
        "missing_start": {"cold": missing, "settled": missing_settled, "manual": missing_manual, "fresh": missing_fresh},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", required=True, type=Path)
    parser.add_argument("--java", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = capture(args.vendor.resolve(), args.java.resolve())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"children": len(result["oracle"]["children"]), "cleanup": True}))
