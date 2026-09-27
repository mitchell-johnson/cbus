#!/usr/bin/env python3
"""Compare the retained native SESSION_ID trace with a fresh mock TCP run.

This covers only the owned, external, IPv4 loopback command-session profile
captured in September 2026. It never connects to a C-Bus network. A receipt
is written on both pass and failure; a missing provision is a blocked run,
not an implicit pass or a silently skipped acceptance case.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import select
import shlex
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "toolkit-cli/research/experiments/2026-09-25/cgate-session-native-acceptance.json"
PILOT = ROOT / "toolkit-cli/research/functional-obligation-pilot.json"
CASE_SPECS = (
    ("session-query-a", "a", "SESSION_ID", "cgate-function:session-id-query"),
    ("session-query-b", "b", "SESSION_ID", "cgate-function:session-id-query"),
    ("session-all-initial", "a", "SESSION_ID ALL", "cgate-function:session-id-all"),
    ("session-tag-initial", "a", "SESSION_ID TAG C-Bus   Toolkit test", "cgate-function:session-id-tag"),
    ("session-all-tagged", "b", "SESSION_ID ALL", "cgate-function:session-id-all"),
    ("session-tag-reassign", "a", "SESSION_ID TAG replacement", "cgate-function:session-id-tag"),
    ("session-tag-missing", "a", "SESSION_ID TAG", "cgate-function:session-id-tag"),
    ("session-query-invalid", "a", "SESSION_ID bogus", "cgate-function:session-id-query"),
    ("session-all-trailing", "a", "SESSION_ID ALL ignored-by-native", "cgate-function:session-id-all"),
)
QUERY_RE = re.compile(r"^300 sessionID=cmd([0-9]+)$")
ROW_RE = re.compile(
    r"^(300[- ])sessionID=cmd([0-9]+) origin=(/127\.0\.0\.1:([0-9]+)) "
    r"from=([0-9]{8}-[0-9]{6})(?: tag=(.*))?$"
)
INTERNAL_RE = re.compile(
    r"^300-sessionID=cmd1 origin=internal from=[0-9]{8}-[0-9]{6} tag=Console$"
)
STATUS_RE = re.compile(r"^[0-9]{3}[ -]")
LISTEN_RE = re.compile(r"^cgate-mock listening on 127\.0\.0\.1:([0-9]+)$")


class ProbeBehaviorError(Exception):
    def __init__(self, completed: list[dict], failed_case_id: str, cause: Exception):
        super().__init__(f"{failed_case_id}: {type(cause).__name__}: {cause}")
        self.completed = completed
        self.failed_case_id = failed_case_id


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def source_fingerprint(*, daemon: bool = False) -> dict[str, str]:
    """Conservatively invalidate receipts after any C-Gate crate source edit."""
    paths = sorted((ROOT / "rust/cbus-cgate/src").rglob("*.rs"))
    paths += [ROOT / "rust/Cargo.toml", ROOT / "rust/cbus-cgate/Cargo.toml",
              ROOT / "rust/cbus-cgate/tests/tcp.rs"]
    if daemon:
        paths += sorted((ROOT / "rust/cmqttd/src").rglob("*.rs"))
        paths += [ROOT / "rust/cmqttd/Cargo.toml", ROOT / "rust/cbus-cgate/src/service/tests.rs",
                  ROOT / "toolkit-cli/research/run_cgate_session_cmqttd_differential.py"]
    paths += [ROOT / "rust/Cargo.lock", PILOT, Path(__file__).resolve(),
              ROOT / "toolkit-cli/tests/test_cgate_session_differential.py",
              ROOT / "toolkit-cli/research/build_parity_register.py",
              ROOT / "toolkit-cli/src/cbus_toolkit/parity.py",
              ROOT / "toolkit-cli/tests/test_parity_register.py"]
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def validate_native() -> dict:
    pilot = json.loads(PILOT.read_text(encoding="utf-8"))
    oracle = pilot["native_oracle"]
    if oracle["sha256"] != digest(NATIVE):
        raise ValueError("retained native capture hash changed")
    native = json.loads(NATIVE.read_text(encoding="utf-8"))
    if (
        native.get("format") != "cbus-cgate-session-native-acceptance-v1"
        or native.get("passed") is not True
        or native.get("vendor_jar_sha256") != oracle["vendor_jar_sha256"]
        or native.get("environment", {}).get("physical_networks_opened") is not False
        or native.get("cleanup", {}).get("cleanup_complete") is not True
    ):
        raise ValueError("native source is not the passed owned loopback capture")
    captured = native.get("cases", [])
    if len(captured) < len(CASE_SPECS):
        raise ValueError("native capture has fewer than nine scoped cases")
    for index, (_, connection, command, _) in enumerate(CASE_SPECS):
        case = captured[index]
        if case.get("connection") != connection or case.get("command") != command:
            raise ValueError(f"native case {index} changed identity or order")
        reply = case.get("reply")
        if not isinstance(reply, list) or not reply or not all(STATUS_RE.match(line) for line in reply):
            raise ValueError(f"native case {index} has invalid reply framing")
        if int(reply[-1][:3]) != case.get("status") or reply[-1][3] != " ":
            raise ValueError(f"native case {index} has invalid terminal status")
    return native


def query_ids(cases: list[dict]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for index in (0, 1):
        match = QUERY_RE.fullmatch(cases[index]["reply"][0])
        if match is None or len(cases[index]["reply"]) != 1:
            raise ValueError(f"{CASE_SPECS[index][0]} did not return a single 300 session ID")
        ids[match.group(1)] = CASE_SPECS[index][1]
    if set(ids.values()) != {"a", "b"}:
        raise ValueError("query returned duplicate external session IDs")
    return ids


def canonicalize(cases: list[dict], *, native: bool, peer_ports: dict[str, int] | None = None) -> tuple[list[list[str]], list[str]]:
    ids = query_ids(cases)
    seen_ports: dict[str, int] = {}
    seen_times: dict[str, str] = {}
    excluded: list[str] = []
    canonical: list[list[str]] = []
    for index, (_, _, command, _) in enumerate(CASE_SPECS):
        rows = []
        for line in cases[index]["reply"]:
            if command.startswith("SESSION_ID ALL") and native and INTERNAL_RE.fullmatch(line):
                datetime.strptime(line.split(" from=", 1)[1].split(" tag=", 1)[0], "%Y%m%d-%H%M%S")
                excluded.append(line)
                continue
            if command == "SESSION_ID":
                match = QUERY_RE.fullmatch(line)
                if match is None or match.group(1) not in ids:
                    raise ValueError(f"{CASE_SPECS[index][0]} has unknown query identity: {line}")
                rows.append(f"300 sessionID=<{ids[match.group(1)]}>")
            elif command.startswith("SESSION_ID ALL"):
                match = ROW_RE.fullmatch(line)
                if match is None or match.group(2) not in ids:
                    raise ValueError(f"{CASE_SPECS[index][0]} has an unexpected external row: {line}")
                prefix, _, _, port_text, stamp, session_tag = match.groups()
                connection = ids[match.group(2)]
                port = int(port_text)
                if not (1 <= port <= 65535):
                    raise ValueError(f"{CASE_SPECS[index][0]} has an invalid peer port")
                if peer_ports is not None and port != peer_ports[connection]:
                    raise ValueError(f"{CASE_SPECS[index][0]} reports the wrong peer port")
                datetime.strptime(stamp, "%Y%m%d-%H%M%S")
                if connection in seen_ports and seen_ports[connection] != port:
                    raise ValueError(f"{CASE_SPECS[index][0]} changed a live peer port")
                if connection in seen_times and seen_times[connection] != stamp:
                    raise ValueError(f"{CASE_SPECS[index][0]} changed a connection time")
                seen_ports[connection] = port
                seen_times[connection] = stamp
                rows.append(
                    f"{prefix}sessionID=<{connection}> origin=/127.0.0.1:<port-{connection}> "
                    f"from=<time-{connection}>" + (f" tag={session_tag}" if session_tag is not None else "")
                )
            else:
                rows.append(line)
        canonical.append(rows)
    if native and len(excluded) != 3:
        raise ValueError(f"native ALL must contain exactly three excluded internal Console rows; got {len(excluded)}")
    if set(seen_ports) != {"a", "b"} or seen_ports["a"] == seen_ports["b"]:
        raise ValueError("ALL did not identify two distinct live external peers")
    return canonical, excluded


def read_reply(stream: socket.SocketIO, tag: str) -> list[str]:
    reply = []
    for _ in range(20):
        raw = stream.readline()
        if not raw:
            raise ConnectionError("mock closed before a terminal reply")
        line = raw.decode("utf-8").rstrip("\r\n")
        prefix = f"[{tag}] "
        if not line.startswith(prefix):
            raise ValueError(f"mock did not echo client-assigned tag {tag}: {line}")
        body = line[len(prefix):]
        if not STATUS_RE.match(body):
            raise ValueError(f"mock emitted invalid status framing: {line}")
        reply.append(body)
        if body[3] == " ":
            return reply
    raise ValueError("mock reply exceeded twenty lines without terminal framing")


def probe_port(port: int) -> tuple[list[dict], dict[str, int]]:
    sessions: dict[str, socket.socket] = {}
    files = {}
    try:
        for connection in ("a", "b"):
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            sock.settimeout(5)
            stream = sock.makefile("rwb", buffering=0)
            hello = stream.readline().decode("utf-8").rstrip("\r\n")
            if not hello.startswith("201 ") or "ready" not in hello.lower():
                raise ValueError(f"Rust C-Gate greeting changed: {hello}")
            sessions[connection], files[connection] = sock, stream
        peer_ports = {name: sock.getsockname()[1] for name, sock in sessions.items()}
        cases = []
        for index, (case_id, connection, command, _) in enumerate(CASE_SPECS):
            tag = f"d{index:02d}"
            stream = files[connection]
            try:
                sessions[connection].sendall(f"[{tag}] {command}\n".encode("utf-8"))
                reply = read_reply(stream, tag)
            except (OSError, ValueError, ConnectionError, TimeoutError) as exc:
                raise ProbeBehaviorError(cases, case_id, exc) from exc
            cases.append({"id": case_id, "connection": connection, "command": command,
                          "client_tag": tag, "status": int(reply[-1][:3]), "reply": reply})
        return cases, peer_ports
    finally:
        for stream in files.values():
            stream.close()
        for sock in sessions.values():
            sock.close()


def probe(binary: Path) -> tuple[list[dict], dict[str, int]]:
    process = subprocess.Popen(
        [str(binary), "--bind", "127.0.0.1:0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        ready, _, _ = select.select([process.stdout], [], [], 5)
        if not ready:
            raise TimeoutError("mock did not publish its loopback listener")
        greeting = process.stdout.readline().strip()
        match = LISTEN_RE.fullmatch(greeting)
        if match is None:
            raise ValueError(f"mock listener announcement changed: {greeting}")
        port = int(match.group(1))
        return probe_port(port)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def run(binary: Path, provenance: str, endpoint_port: int | None = None) -> tuple[dict, int]:
    receipt = {
        "format": "cgate-session-differential-v1",
        "scope": "nine SESSION_ID cases on two owned IPv4 loopback command connections",
        "obligation_ids": sorted({item[3] for item in CASE_SPECS}),
        "native_capture": {"path": str(NATIVE.relative_to(ROOT)), "sha256": digest(NATIVE)},
        "pilot_manifest": {"path": str(PILOT.relative_to(ROOT)), "sha256": digest(PILOT)},
        "vendor_jar_sha256": json.loads(PILOT.read_text(encoding="utf-8"))["native_oracle"]["vendor_jar_sha256"],
        "rust_artifact": {"path": str(binary), "sha256": digest(binary) if binary.is_file() else None,
                          "provenance": provenance},
        "product": "cmqttd" if endpoint_port is not None else "cgate-mock",
        "source_fingerprint": source_fingerprint(daemon=endpoint_port is not None),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "normalization": [
            "map queried cmdN IDs to connection a/b; require distinct IDs",
            "validate external IPv4 loopback peer ports and stable connection timestamps, then replace only their values",
            "exclude only native cmd1 origin=internal tag=Console rows; retain external 300-/300 framing",
            "require every Rust reply line to echo its exact client-assigned tag",
        ],
        "cases": [], "excluded_native_rows": [], "result": "blocked", "errors": [],
        "normalization_errors": [],
        "executed": 0, "passed": 0, "failed": 0, "skipped": 9,
    }
    try:
        native = validate_native()
        if not binary.is_file() or not binary.stat().st_mode & 0o111:
            raise FileNotFoundError(f"executable mock binary missing: {binary}")
        expected_cases = native["cases"][:len(CASE_SPECS)]
        expected, excluded = canonicalize(expected_cases, native=True)
        receipt["excluded_native_rows"] = excluded
        actual_cases, peer_ports = (
            probe_port(endpoint_port) if endpoint_port is not None else probe(binary)
        )
        try:
            actual, _ = canonicalize(actual_cases, native=False, peer_ports=peer_ports)
        except ValueError as exc:
            # A syntactically wrong but fully executed mock run is a failed
            # differential, never an infrastructure skip.
            receipt["normalization_errors"].append(str(exc))
            actual = [case["reply"] for case in actual_cases]
        for index, (case_id, connection, command, obligation_id) in enumerate(CASE_SPECS):
            native_case, actual_case = expected_cases[index], actual_cases[index]
            matched = (expected[index] == actual[index]
                       and native_case["status"] == actual_case["status"])
            receipt["cases"].append({
                "id": case_id, "obligation_id": obligation_id, "connection": connection,
                "command": command, "result": "passed" if matched else "failed",
                "native_status": native_case["status"], "rust_status": actual_case["status"],
                "native_normalized": expected[index], "rust_normalized": actual[index],
                "client_tag_echoed": True,
            })
        receipt["executed"] = len(CASE_SPECS)
        receipt["passed"] = sum(case["result"] == "passed" for case in receipt["cases"])
        receipt["failed"] = len(CASE_SPECS) - receipt["passed"]
        receipt["skipped"] = 0
        receipt["result"] = (
            "passed" if receipt["failed"] == 0 and not receipt["normalization_errors"]
            else "failed"
        )
        return receipt, 0 if receipt["result"] == "passed" else 1
    except ProbeBehaviorError as exc:
        receipt["result"] = "failed"
        receipt["errors"].append(str(exc))
        receipt["executed"] = len(exc.completed) + 1
        receipt["failed"] = receipt["executed"]
        receipt["skipped"] = len(CASE_SPECS) - receipt["executed"]
        receipt["cases"] = [
            {"id": case["id"], "result": "failed",
             "reason": "differential interrupted before the full sequence"}
            for case in exc.completed
        ] + [{"id": exc.failed_case_id, "result": "failed", "reason": str(exc)}]
        return receipt, 1
    except Exception as exc:
        receipt["errors"].append(f"{type(exc).__name__}: {exc}")
        return receipt, 2


def validate_passed_receipt(receipt: dict) -> None:
    """Reject stale or partial captures before using one as parity evidence."""
    native = validate_native()
    canonical_native, excluded_native = canonicalize(native["cases"][:9], native=True)
    if receipt.get("format") != "cgate-session-differential-v1":
        raise ValueError("SESSION_ID differential receipt format changed")
    product = receipt.get("product")
    if product not in {"cgate-mock", "cmqttd"}:
        raise ValueError("SESSION_ID differential product changed")
    if receipt.get("source_fingerprint") != source_fingerprint(daemon=product == "cmqttd"):
        raise ValueError("SESSION_ID differential source fingerprint is stale")
    if not re.fullmatch(r"[0-9a-f]{40}", receipt.get("source_revision", "")):
        raise ValueError("SESSION_ID differential lacks a source revision")
    if receipt.get("native_capture") != {
        "path": str(NATIVE.relative_to(ROOT)), "sha256": digest(NATIVE)
    } or receipt.get("pilot_manifest") != {
        "path": str(PILOT.relative_to(ROOT)), "sha256": digest(PILOT)
    }:
        raise ValueError("SESSION_ID differential oracle or manifest hash changed")
    if receipt.get("vendor_jar_sha256") != json.loads(PILOT.read_text(encoding="utf-8"))["native_oracle"]["vendor_jar_sha256"]:
        raise ValueError("SESSION_ID differential vendor oracle hash changed")
    binary = receipt.get("rust_artifact")
    if (not isinstance(binary, dict) or binary.get("provenance") != "current-build"
            or not isinstance(binary.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", binary["sha256"])):
        raise ValueError("SESSION_ID differential lacks exact current Rust artifact hash")
    if (receipt.get("result") != "passed" or receipt.get("executed") != 9
            or receipt.get("passed") != 9 or receipt.get("failed") != 0
            or receipt.get("skipped") != 0 or receipt.get("errors")
            or receipt.get("normalization_errors")):
        raise ValueError("SESSION_ID differential did not pass all nine required cases")
    cases = receipt.get("cases")
    if (not isinstance(cases, list) or len(cases) != len(CASE_SPECS)
            or any(case.get("id") != spec[0]
                   or case.get("obligation_id") != spec[3]
                   or case.get("connection") != spec[1]
                   or case.get("command") != spec[2]
                   or case.get("result") != "passed"
                   or case.get("client_tag_echoed") is not True
                   or case.get("native_status") != native["cases"][index]["status"]
                   or case.get("rust_status") != native["cases"][index]["status"]
                   or case.get("native_normalized") != canonical_native[index]
                   or case.get("native_normalized") != case.get("rust_normalized")
                   for index, (case, spec) in enumerate(zip(cases, CASE_SPECS)))):
        raise ValueError("SESSION_ID differential case evidence changed")
    excluded = receipt.get("excluded_native_rows")
    if excluded != excluded_native:
        raise ValueError("SESSION_ID differential internal Console exclusion changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provenance", choices=("pre-fix-binary", "current-build"),
                        default="current-build")
    parser.add_argument("--endpoint-port", type=int,
                        help="probe an already running cmqttd C-Gate listener on loopback")
    args = parser.parse_args()
    receipt, code = run(args.mock_bin.resolve(), args.provenance, args.endpoint_port)
    receipt["command"] = shlex.join([sys.executable, *sys.argv])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("result", "executed", "passed", "failed", "skipped", "errors")}))
    return code


if __name__ == "__main__":
    sys.exit(main())
