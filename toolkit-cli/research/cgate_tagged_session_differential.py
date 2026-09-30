#!/usr/bin/env python3
"""Compare eleven retained native tagged SESSION_ID exchanges with Rust TCP servers.

Only two owned IPv4 loopback command connections are in scope. A fresh mock or
offline cmqttd process is launched for each receipt; no house endpoint is used.
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
import tempfile
import time

from research.cgate_session_differential import rust_source_paths


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "toolkit-cli/research/experiments/2026-09-28/cgate-tagged-session-native.json"
NATIVE_SHA256 = "76f77ea955a6575700ea350aba52f8b136599119c07d955f4d04cce3ab5469c8"
VENDOR_JAR_SHA256 = "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
CASE_SPECS = (
    ("a", "501", "SESSION_ID"),
    ("b", "601", "SESSION_ID"),
    ("a", "502", "SESSION_ID ALL"),
    ("a", "503", "SESSION_ID TAG native-a"),
    ("b", "602", "SESSION_ID TAG native-b"),
    ("a", "504", "SESSION_ID ALL"),
    ("b", "603", "SESSION_ID ALL"),
    ("a", "505", "SESSION_ID TAG replacement-a"),
    ("b", "604", "SESSION_ID ALL"),
    ("a", "506", "SESSION_ID TAG"),
    ("b", "605", "SESSION_ID"),
)
STATUS_RE = re.compile(r"^[1-6][0-9]{2}[- ][^\r\n]+$")
QUERY_RE = re.compile(r"^300 sessionID=(cmd[0-9]+)$")
CONSOLE_RE = re.compile(
    r"^(300-sessionID=cmd1 origin=internal from=)([0-9]{8}-[0-9]{6})( tag=Console)$"
)
EXTERNAL_RE = re.compile(
    r"^(300[- ]sessionID=)(cmd[0-9]+)( origin=/127\.0\.0\.1:)([0-9]+)"
    r"( from=)([0-9]{8}-[0-9]{6})( tag=[^\r\n]*)?$"
)
MOCK_LISTEN_RE = re.compile(r"^cgate-mock listening on 127\.0\.0\.1:([0-9]+)$")
DAEMON_LISTEN_RE = re.compile(r"C-Gate service listening on 127\.0\.0\.1:([0-9]+)")
FINGERPRINT_FILES = (
    "rust/Cargo.toml",
    "rust/Cargo.lock",
    "toolkit-cli/research/cgate_tagged_session_differential.py",
    "toolkit-cli/research/cgate_session_differential.py",  # source-closure helper
    "toolkit-cli/research/experiments/2026-09-28/cgate-tagged-session-native.json",
    "toolkit-cli/research/build_parity_register.py",
    "toolkit-cli/src/cbus_toolkit/parity.py",
    "toolkit-cli/tests/test_parity_register.py",
    "toolkit-cli/tests/test_cgate_tagged_session_differential.py",
    "toolkit-cli/Makefile",
    ".github/workflows/ci.yml",
)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def source_fingerprint(*, daemon: bool) -> dict[str, str]:
    paths = rust_source_paths(daemon=daemon)
    paths.update(ROOT / name for name in FINGERPRINT_FILES)
    if daemon:
        paths.add(ROOT / "toolkit-cli/src/cbus_toolkit/simulator.py")
    for path in paths:
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError(f"Tagged differential source escapes repository: {path}")
        if not path.is_file():
            raise ValueError(f"Tagged differential source missing: {path}")
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(paths)}


def validate_native() -> dict:
    if digest(NATIVE) != NATIVE_SHA256:
        raise ValueError("tagged native capture hash changed")
    native = json.loads(NATIVE.read_text(encoding="utf-8"))
    if (native.get("format") != "cbus-cgate-tagged-session-native-envelope-v1"
            or native.get("vendor_jar_sha256") != VENDOR_JAR_SHA256
            or native.get("scope", {}).get("two_owned_ipv4_command_sessions") is not True
            or native.get("scope", {}).get("all_six_listeners_owned_and_loopback") is not True
            or native.get("scope", {}).get("physical_networks_opened") is not False
            or native.get("scope", {}).get("projects_adopted") is not False
            or native.get("cleanup", {}).get("cleanup_complete") is not True):
        raise ValueError("tagged source is not the owned native loopback capture")
    cases = native.get("cases")
    if not isinstance(cases, list) or len(cases) != len(CASE_SPECS):
        raise ValueError("tagged native capture must have exactly eleven cases")
    for index, (connection, tag, command) in enumerate(CASE_SPECS):
        case = cases[index]
        prefix = f"[{tag}] "
        if (case.get("connection") != connection or case.get("client_tag") != tag
                or case.get("command") != command
                or case.get("request") != f"{prefix}{command}\r\n"):
            raise ValueError(f"tagged native request {index} changed")
        lines = case.get("response_lines")
        if not isinstance(lines, list) or not lines or len(lines) > 20:
            raise ValueError(f"tagged native response {index} missing or too long")
        for row_index, line in enumerate(lines):
            if not isinstance(line, str) or not line.startswith(prefix) or not line.endswith("\r\n"):
                raise ValueError(f"tagged native response {index} changed prefix or CRLF")
            body = line[len(prefix):-2]
            if not STATUS_RE.fullmatch(body) or body[3] != (" " if row_index == len(lines) - 1 else "-"):
                raise ValueError(f"tagged native response {index} changed status framing")
        if command == "SESSION_ID ALL" and len(lines) != 3:
            raise ValueError("tagged native ALL must contain Console and two external rows")
    return native


def _timestamp(value: str) -> None:
    datetime.strptime(value, "%Y%m%d-%H%M%S")


def normalize_wire(cases: list[dict], peer_ports: dict[str, int]) -> list[list[str]]:
    """Replace only queried IDs, owned peer ports and stable role timestamps."""
    if len(cases) != len(CASE_SPECS) or set(peer_ports) != {"a", "b"}:
        raise ValueError("tagged run has wrong case count or peer roles")
    if any(type(port) is not int or not 1 <= port <= 65535 for port in peer_ports.values()):
        raise ValueError("tagged run has an invalid peer port")
    if peer_ports["a"] == peer_ports["b"]:
        raise ValueError("tagged run has duplicate peer ports")
    identities: dict[str, str] = {}
    for index, role in ((0, "a"), (1, "b")):
        lines = cases[index]["response_lines"]
        if len(lines) != 1:
            raise ValueError("tagged query did not return one line")
        prefix = f"[{CASE_SPECS[index][1]}] "
        body = lines[0][len(prefix):-2]
        match = QUERY_RE.fullmatch(body)
        if match is None:
            raise ValueError("tagged query did not return a session ID")
        identities[match[1]] = role
    if len(identities) != 2 or "cmd1" in identities:
        raise ValueError("tagged queries did not identify two external sessions")
    times: dict[str, str] = {}
    normalized: list[list[str]] = []
    for index, (connection, tag, command) in enumerate(CASE_SPECS):
        case = cases[index]
        prefix = f"[{tag}] "
        if (case.get("connection") != connection or case.get("client_tag") != tag
                or case.get("command") != command
                or case.get("request") != f"{prefix}{command}\r\n"):
            raise ValueError(f"tagged case {index} request changed")
        lines = case.get("response_lines")
        if not isinstance(lines, list) or not lines or len(lines) > 20:
            raise ValueError(f"tagged case {index} response count changed")
        rows: list[str] = []
        for row_index, line in enumerate(lines):
            if not isinstance(line, str) or not line.startswith(prefix) or not line.endswith("\r\n"):
                raise ValueError(f"tagged case {index} lost its numeric prefix or CRLF")
            body = line[len(prefix):-2]
            if not STATUS_RE.fullmatch(body) or body[3] != (" " if row_index == len(lines) - 1 else "-"):
                raise ValueError(f"tagged case {index} has wrong continuation or terminal framing")
            if command == "SESSION_ID":
                match = QUERY_RE.fullmatch(body)
                if match is None or identities.get(match[1]) != connection:
                    raise ValueError(f"tagged case {index} has wrong queried identity")
                body = f"300 sessionID=<session:{connection}>"
            elif command == "SESSION_ID ALL":
                if row_index == 0:
                    match = CONSOLE_RE.fullmatch(body)
                    if match is None:
                        raise ValueError(f"tagged case {index} lacks internal Console row")
                    stamp = match[2]
                    _timestamp(stamp)
                    if "console" in times and times["console"] != stamp:
                        raise ValueError("tagged Console timestamp changed")
                    times["console"] = stamp
                    body = f"{match[1]}<timestamp:console>{match[3]}"
                else:
                    match = EXTERNAL_RE.fullmatch(body)
                    if match is None:
                        raise ValueError(f"tagged case {index} has invalid external row")
                    role = identities.get(match[2])
                    if role != ("a" if row_index == 1 else "b"):
                        raise ValueError(f"tagged case {index} changed external row order")
                    if int(match[4]) != peer_ports[role]:
                        raise ValueError(f"tagged case {index} changed owned peer port")
                    stamp = match[6]
                    _timestamp(stamp)
                    if role in times and times[role] != stamp:
                        raise ValueError(f"tagged {role} timestamp changed")
                    times[role] = stamp
                    body = (f"{match[1]}<session:{role}>{match[3]}<port:{role}>"
                            f"{match[5]}<timestamp:{role}>{match[7] or ''}")
            rows.append(f"{prefix}{body}\r\n")
        if command == "SESSION_ID ALL" and len(rows) != 3:
            raise ValueError(f"tagged case {index} changed ALL row count")
        normalized.append(rows)
    if set(times) != {"console", "a", "b"}:
        raise ValueError("tagged run omitted a stable session timestamp")
    return normalized


def read_response(stream, tag: str) -> list[str]:
    rows: list[str] = []
    for _ in range(20):
        raw = stream.readline()
        if not raw:
            raise ConnectionError("Rust server closed before terminal reply")
        if not raw.endswith(b"\r\n"):
            raise ValueError("Rust response lost native CRLF")
        line = raw.decode("utf-8")
        prefix = f"[{tag}] "
        if not line.startswith(prefix):
            raise ValueError(f"Rust response did not echo numeric tag {tag}")
        body = line[len(prefix):-2]
        if not STATUS_RE.fullmatch(body):
            raise ValueError("Rust response has invalid status framing")
        rows.append(line)
        if body[3] == " ":
            return rows
    raise ValueError("Rust response has no terminal line within twenty rows")


class ProbeError(Exception):
    def __init__(self, completed: list[dict], index: int, cause: Exception):
        super().__init__(f"case {index}: {type(cause).__name__}: {cause}")
        self.completed = completed
        self.index = index


def probe_port(port: int, native: dict) -> tuple[list[dict], dict[str, int], dict[str, str]]:
    sockets: dict[str, socket.socket] = {}
    streams = {}
    greetings = {}
    try:
        for role in ("a", "b"):
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            sock.settimeout(5)
            stream = sock.makefile("rwb", buffering=0)
            sockets[role], streams[role] = sock, stream
            greeting = stream.readline()
            if not greeting.endswith(b"\r\n") or not greeting.startswith(b"201 "):
                raise ValueError("Rust greeting lost 201/CRLF framing")
            decoded = greeting.decode("utf-8")
            if "ready" not in decoded.lower():
                raise ValueError("Rust greeting does not indicate readiness")
            greetings[role] = decoded
        ports = {role: sock.getsockname()[1] for role, sock in sockets.items()}
        cases = []
        for index, (role, tag, command) in enumerate(CASE_SPECS):
            request = native["cases"][index]["request"]
            try:
                sockets[role].sendall(request.encode("ascii"))
                lines = read_response(streams[role], tag)
            except (OSError, ValueError, ConnectionError, TimeoutError) as exc:
                raise ProbeError(cases, index, exc) from exc
            cases.append({"connection": role, "client_tag": tag, "command": command,
                          "request": request, "response_lines": lines})
        return cases, ports, greetings
    finally:
        for stream in streams.values():
            stream.close()
        for sock in sockets.values():
            sock.close()


def probe_mock(binary: Path, native: dict):
    process = subprocess.Popen([str(binary), "--bind", "127.0.0.1:0"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 5)
        if not ready:
            raise TimeoutError("mock did not announce its owned listener")
        announcement = process.stdout.readline().strip()
        match = MOCK_LISTEN_RE.fullmatch(announcement)
        if match is None:
            raise ValueError(f"mock listener announcement changed: {announcement}")
        return probe_port(int(match[1]), native)
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


def probe_daemon(binary: Path, native: dict):
    from cbus_toolkit.simulator import PCISimulator

    class InitializedPCI(PCISimulator):
        def _command(self, line, context):
            if line in (b"~", b"A32100FF", b"A32200FF", b"A342000E", b"A3300079"):
                return b"", None
            return super()._command(line, context)

    with tempfile.TemporaryDirectory(prefix="cbus-tagged-cmqttd-") as tmp:
        scratch = Path(tmp)
        project = scratch / "project.xml"
        project.write_text(
            "<Installation><Project><TagName>SESSION_TEST</TagName>"
            "<Network><Address>254</Address><TagName>Loopback</TagName>"
            "</Network></Project></Installation>", encoding="utf-8"
        )
        sim = InitializedPCI(profile="captured", command_checksum=True)
        with socket.socket() as broker, sim.running() as pci:
            broker.bind(("127.0.0.1", 0))
            broker.listen(1)
            log_path = scratch / "cmqttd.log"
            with log_path.open("w") as log:
                process = subprocess.Popen([
                    str(binary), "--tcp", f"{pci[0]}:{pci[1]}",
                    "--broker-address", "127.0.0.1", "--broker-port", str(broker.getsockname()[1]),
                    "--broker-disable-tls", "--timesync", "0", "--status-resync", "0",
                    "--project-file", str(project), "--cgate-bind", "127.0.0.1:0",
                    "--cgate-state", str(scratch / "state.json"),
                ], stdout=subprocess.DEVNULL, stderr=log)
                try:
                    deadline = time.monotonic() + 15
                    port = None
                    while time.monotonic() < deadline:
                        output = log_path.read_text(encoding="utf-8")
                        match = DAEMON_LISTEN_RE.search(output)
                        if match:
                            port = int(match[1])
                            break
                        if process.poll() is not None:
                            raise RuntimeError("cmqttd exited before opening owned C-Gate listener")
                        time.sleep(.02)
                    if port is None:
                        raise TimeoutError("cmqttd did not open owned C-Gate listener")
                    return probe_port(port, native)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


def run(binary: Path, product: str) -> tuple[dict, int]:
    if product not in {"cgate-mock", "cmqttd"}:
        raise ValueError("product must be cgate-mock or cmqttd")
    receipt = {
        "format": "cgate-tagged-session-differential-v1",
        "scope": "eleven numeric-tag SESSION_ID cases on two owned IPv4 loopback command sessions",
        "product": product,
        "native_capture": {"path": NATIVE.relative_to(ROOT).as_posix(), "sha256": digest(NATIVE)},
        "vendor_jar_sha256": VENDOR_JAR_SHA256,
        "rust_artifact": {"path": str(binary), "sha256": digest(binary) if binary.is_file() else None,
                          "provenance": "current-build"},
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_fingerprint": source_fingerprint(daemon=product == "cmqttd"),
        "normalization": ["queried external cmdN identity", "owned IPv4 loopback client port",
                          "stable connection timestamp per Console/a/b role"],
        "greeting_scope": "201 ready and CRLF framing; product text is outside differential",
        "greetings": {}, "peer_ports": {}, "cases": [],
        "result": "blocked", "errors": [], "executed": 0, "passed": 0,
        "failed": 0, "skipped": len(CASE_SPECS),
        "offline_provision": {"physical_networks_opened": False},
    }
    try:
        native = validate_native()
        if not binary.is_file() or not binary.stat().st_mode & 0o111:
            raise FileNotFoundError(f"executable Rust binary missing: {binary}")
        actual_cases, ports, greetings = (
            probe_mock(binary, native) if product == "cgate-mock" else probe_daemon(binary, native)
        )
        receipt["peer_ports"] = ports
        receipt["greetings"] = greetings
        canonical = normalize_wire(actual_cases, ports)
        for index, actual in enumerate(actual_cases):
            expected = native["cases"][index]["response_lines"]
            matched = canonical[index] == expected
            receipt["cases"].append({
                "index": index, "connection": actual["connection"],
                "client_tag": actual["client_tag"], "command": actual["command"],
                "request": actual["request"], "native_normalized": expected,
                "rust_normalized": canonical[index], "rust_wire_reply": actual["response_lines"],
                "result": "passed" if matched else "failed",
            })
        receipt["executed"] = len(CASE_SPECS)
        receipt["passed"] = sum(case["result"] == "passed" for case in receipt["cases"])
        receipt["failed"] = len(CASE_SPECS) - receipt["passed"]
        receipt["skipped"] = 0
        receipt["result"] = "passed" if receipt["failed"] == 0 else "failed"
        return receipt, 0 if receipt["result"] == "passed" else 1
    except ProbeError as exc:
        receipt["result"] = "failed"
        receipt["errors"].append(str(exc))
        receipt["executed"] = len(exc.completed) + 1
        receipt["failed"] = receipt["executed"]
        receipt["skipped"] = len(CASE_SPECS) - receipt["executed"]
        return receipt, 1
    except (ValueError, ConnectionError, UnicodeDecodeError) as exc:
        receipt["result"] = "failed"
        receipt["errors"].append(f"{type(exc).__name__}: {exc}")
        receipt["executed"] = len(CASE_SPECS) if receipt["peer_ports"] else 0
        receipt["failed"] = receipt["executed"]
        receipt["skipped"] = len(CASE_SPECS) - receipt["executed"]
        return receipt, 1
    except Exception as exc:
        receipt["errors"].append(f"{type(exc).__name__}: {exc}")
        return receipt, 2


def validate_passed_receipt(receipt: dict) -> None:
    native = validate_native()
    product = receipt.get("product")
    if receipt.get("format") != "cgate-tagged-session-differential-v1" or product not in {"cgate-mock", "cmqttd"}:
        raise ValueError("tagged differential format or product changed")
    if receipt.get("native_capture") != {"path": NATIVE.relative_to(ROOT).as_posix(), "sha256": NATIVE_SHA256}:
        raise ValueError("tagged native capture binding changed")
    if receipt.get("vendor_jar_sha256") != VENDOR_JAR_SHA256:
        raise ValueError("tagged vendor oracle changed")
    if receipt.get("source_fingerprint") != source_fingerprint(daemon=product == "cmqttd"):
        raise ValueError("tagged differential source fingerprint is stale")
    if not re.fullmatch(r"[0-9a-f]{40}", receipt.get("source_revision", "")):
        raise ValueError("tagged differential source revision missing")
    artifact = receipt.get("rust_artifact")
    if (not isinstance(artifact, dict) or artifact.get("provenance") != "current-build"
            or not isinstance(artifact.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])):
        raise ValueError("tagged differential lacks exact Rust binary digest")
    if (receipt.get("result") != "passed" or receipt.get("executed") != 11
            or receipt.get("passed") != 11 or receipt.get("failed") != 0
            or receipt.get("skipped") != 0 or receipt.get("errors")
            or receipt.get("offline_provision", {}).get("physical_networks_opened") is not False):
        raise ValueError("tagged differential did not pass all eleven cases")
    ports = receipt.get("peer_ports")
    cases = receipt.get("cases")
    if not isinstance(cases, list) or len(cases) != 11:
        raise ValueError("tagged differential case evidence missing")
    for index, case in enumerate(cases):
        native_case = native["cases"][index]
        role, tag, command = CASE_SPECS[index]
        if (case.get("index") != index or case.get("connection") != role
                or case.get("client_tag") != tag or case.get("command") != command
                or case.get("request") != native_case["request"]
                or case.get("native_normalized") != native_case["response_lines"]
                or case.get("rust_normalized") != native_case["response_lines"]
                or case.get("result") != "passed"):
            raise ValueError(f"tagged differential case {index} changed")
    raw_cases = [{"connection": case["connection"], "client_tag": case["client_tag"],
                  "command": case["command"], "request": case["request"],
                  "response_lines": case.get("rust_wire_reply")}
                 for case in cases]
    try:
        normalized = normalize_wire(raw_cases, ports)
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(f"tagged differential raw wire changed: {exc}") from exc
    if normalized != [case["rust_normalized"] for case in cases]:
        raise ValueError("tagged differential raw normalization changed")
    greetings = receipt.get("greetings")
    if (not isinstance(greetings, dict) or set(greetings) != {"a", "b"}
            or any(not isinstance(greet, str) or not greet.startswith("201 ")
                   or not greet.endswith("\r\n") or "ready" not in greet.lower()
                   for greet in greetings.values())):
        raise ValueError("tagged differential greeting framing changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-bin", type=Path, required=True)
    parser.add_argument("--cmqttd-bin", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    exit_code = 0
    for product, binary, filename in (
        ("cgate-mock", args.mock_bin, "cgate-tagged-session-differential-mock.json"),
        ("cmqttd", args.cmqttd_bin, "cgate-tagged-session-differential-cmqttd.json"),
    ):
        receipt, code = run(binary.resolve(), product)
        receipt["command"] = shlex.join([sys.executable, *sys.argv])
        (args.output_dir / filename).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"product": product, **{
            key: receipt[key] for key in ("result", "executed", "passed", "failed", "skipped", "errors")
        }}))
        exit_code = max(exit_code, code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
