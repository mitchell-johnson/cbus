#!/usr/bin/env python3
"""Run native direct/combined Unit XML mapper and TCP framing cases offline.

The receipt retains exact original and Rust wire rows. Both XML payload and
343/347/344 framing must match; DBSETXML writes retain their separate 301
receipt and mapper checks.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
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
import xml.etree.ElementTree as ET

from research.cgate_session_differential import rust_source_paths


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_unit_vm.json"
NATIVE_SHA256 = "6ae63e7a36de13cdd5af034ba132dcda9b452dc5bc3a5e403a3213423e9ce70d"
COMBINED = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_combined_vm.json"
COMBINED_SHA256 = "7d850980d52a05103796bfcb01ca49a4fda5db23177387c0ad1d72978953abae"
TAGS = tuple(str(tag) for tag in range(808, 820))
COMBINED_CHECKS = {"816": ("908", "909", "716"), "818": ("910", "911", "718")}
SOURCE_FILES = (
    "rust/Cargo.toml", "rust/Cargo.lock",
    "rust/cbus-cgate/tests/server.rs", "rust/cbus-cgate/tests/tcp.rs",
    "rust/cmqttd/tests/system_cgate_admin.rs",
    "toolkit-cli/research/cgate_dbsetxml_unit_differential.py",
    "toolkit-cli/research/cgate_session_differential.py",
    "toolkit-cli/tests/test_cgate_dbsetxml_unit_differential.py",
    "toolkit-cli/tests/test_rust_cgate_interop.py",
    "toolkit-cli/Makefile", ".github/workflows/ci.yml",
    "rust/testdata/fixtures/native_cgate_dbsetxml_unit_vm.json",
    "rust/testdata/fixtures/native_cgate_dbsetxml_combined_vm.json",
    "rust/testdata/fixtures/native_cgate_dbgetxml_framing_vm.json",
    "rust/testdata/vectors/cgate_dbgetxml_wire.json",
    "toolkit-cli/tests/test_native_cgate_dbgetxml_framing_vm.py",
    "toolkit-cli/src/cbus_toolkit/simulator.py",
)
STATUS = re.compile(r"^[1-6][0-9]{2}[- ][^\r\n]+\r\n$")


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def fingerprint(daemon: bool) -> dict[str, str]:
    paths = rust_source_paths(daemon=daemon)
    paths.update(ROOT / name for name in SOURCE_FILES)
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(paths)}


def native_cases() -> tuple[dict, list[dict]]:
    if digest(NATIVE) != NATIVE_SHA256:
        raise ValueError("native Unit mapper fixture digest changed")
    native = json.loads(NATIVE.read_text(encoding="utf-8"))
    if (native["format"] != "native-cgate-dbsetxml-unit-vm-fixture-v1"
            or native["jar_sha256"] != "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
            or native["default_route_count"] != 0):
        raise ValueError("original C-Gate provenance changed")
    cases = [row for row in native["cases"] if row["tag"] in TAGS]
    if [row["tag"] for row in cases] != list(TAGS):
        raise ValueError("Unit mapper differential needs exactly twelve ordered cases")
    return native, cases


def combined_cases(native: dict) -> dict[str, dict]:
    if digest(COMBINED) != COMBINED_SHA256:
        raise ValueError("combined Network fixture digest changed")
    prior = json.loads(COMBINED.read_text(encoding="utf-8"))
    if (prior["format"] != "native-cgate-dbsetxml-vm-fixture-v1"
            or prior["jar_sha256"] != native["jar_sha256"]
            or prior["default_route_count"] != 0):
        raise ValueError("combined Network original provenance changed")
    by_tag = {row["tag"]: row for row in prior["cases"]}
    current = {row["tag"]: row for row in native["cases"]}
    for current_set, (prior_set, prior_get, _) in COMBINED_CHECKS.items():
        current_body = current[current_set]["request"].split("\r\n", 1)[1].rsplit("\r\nEND", 1)[0]
        prior_body = by_tag[prior_set]["request"].split("\r\n", 1)[1].rsplit("\r\nEND", 1)[0]
        if current_body != prior_body.replace(prior["network_oid"], native["network_oid"]):
            raise ValueError(f"combined Network submission differs at {current_set}/{prior_set}")
        xml_payload(by_tag[prior_get]["response_lines"], prior_get, original=True)
    return by_tag


def prior_network_oid(prior: dict[str, dict]) -> str:
    oid = ET.fromstring(xml_payload(prior["909"]["response_lines"], "909", original=True)).findtext("OID")
    if not oid:
        raise ValueError("combined Network oracle lacks its root OID")
    return oid


def xml_payload(lines: list[str], tag: str, *, original: bool) -> str:
    prefix = f"[{tag}] 347-"
    rows = [line for line in lines if line.startswith(prefix)]
    if (len(lines) != 4 or len(rows) != 2
            or lines[0] != f"[{tag}] 343-Begin XML snippet\r\n"
            or lines[1] != f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
            or lines[3] != f"[{tag}] 344 End XML snippet\r\n"
            or not rows[1].endswith("\r\n")):
        raise ValueError(f"{'native' if original else 'Rust'} XML envelope changed for {tag}")
    result = rows[1][len(prefix):-2]
    ET.fromstring(result)
    return result


def read_reply(stream, tag: str) -> tuple[list[str], list[str]]:
    rows: list[str] = []
    events: list[str] = []
    for _ in range(40):
        raw = stream.readline()
        if not raw:
            raise ConnectionError(f"server closed before reply to {tag}")
        line = raw.decode("utf-8")
        if line.startswith("#e# "):
            events.append(line)
            continue
        prefix = f"[{tag}] "
        if line == f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n':
            rows.append(line)
            continue
        if not line.startswith(prefix) or not STATUS.fullmatch(line[len(prefix):]):
            raise ValueError(f"unexpected tagged row for {tag}: {line!r}")
        rows.append(line)
        if line[len(prefix) + 3] == " ":
            return rows, events
    raise ValueError(f"server did not terminate reply to {tag}")


def send(sock, stream, tag: str, request: str) -> tuple[list[str], list[str]]:
    sock.sendall(request.encode("utf-8"))
    return read_reply(stream, tag)


@contextmanager
def owned_server(product: str, binary: Path):
    if product == "cgate-mock":
        process = subprocess.Popen(
            [str(binary), "--bind", "127.0.0.1:0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            if not select.select([process.stdout], [], [], 10)[0]:
                raise TimeoutError("mock listener announcement timed out")
            match = re.fullmatch(
                r"cgate-mock listening on 127\.0\.0\.1:([0-9]+)",
                process.stdout.readline().strip(),
            )
            if match is None:
                raise ValueError("mock listener is not owned IPv4 loopback")
            yield int(match[1])
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()
        return
    from cbus_toolkit.simulator import PCISimulator

    class InitializedPCI(PCISimulator):
        def _command(self, line, context):
            if line in (b"~", b"A32100FF", b"A32200FF", b"A342000E", b"A3300079"):
                return b"", None
            return super()._command(line, context)

    with tempfile.TemporaryDirectory(prefix="cbus-dbsetxml-unit-cmqttd-") as tmp:
        scratch = Path(tmp)
        project = scratch / "project.xml"
        project.write_text(
            "<Installation><Project><TagName>BRIDGE_TEST</TagName>"
            "<Network><Address>254</Address><TagName>Loopback</TagName>"
            "</Network></Project></Installation>", encoding="utf-8",
        )
        with socket.socket() as broker, InitializedPCI(profile="captured", command_checksum=True).running() as pci:
            broker.bind(("127.0.0.1", 0))
            broker.listen(1)
            with (scratch / "cmqttd.log").open("w+") as log:
                process = subprocess.Popen([
                    str(binary), "--tcp", f"{pci[0]}:{pci[1]}",
                    "--broker-address", "127.0.0.1", "--broker-port", str(broker.getsockname()[1]),
                    "--broker-disable-tls", "--timesync", "0", "--status-resync", "0",
                    "--project-file", str(project), "--cgate-bind", "127.0.0.1:0",
                    "--cgate-state", str(scratch / "state.json"),
                ], stdout=subprocess.DEVNULL, stderr=log)
                try:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        log.seek(0)
                        match = re.search(r"C-Gate service listening on 127\.0\.0\.1:([0-9]+)", log.read())
                        if match:
                            yield int(match[1])
                            break
                        if process.poll() is not None:
                            raise RuntimeError("cmqttd exited before owned listener opened")
                        time.sleep(.02)
                    else:
                        raise TimeoutError("cmqttd owned listener timed out")
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


def probe(product: str, binary: Path) -> dict:
    native, cases = native_cases()
    prior = combined_cases(native)
    receipt = {
        "format": "cgate-dbsetxml-unit-mapper-differential-v1",
        "scope": "twelve original direct/combined Unit mapper cases, owned IPv4 loopback only",
        "product": product,
        "native_fixture": {"path": NATIVE.relative_to(ROOT).as_posix(), "sha256": digest(NATIVE)},
        "combined_native_fixture": {"path": COMBINED.relative_to(ROOT).as_posix(), "sha256": digest(COMBINED)},
        "vendor_jar_sha256": native["jar_sha256"],
        "binary": {"path": str(binary), "sha256": digest(binary)},
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_fingerprint": fingerprint(product == "cmqttd"),
        "normalization": "generated Network and Interface OIDs only; all XML bytes otherwise exact",
        "xml_wire_boundary": "native and Rust 343/347/344 with LF-only declaration; raw rows retained",
        "offline_provision": {"loopback_cgate": True, "disposable_pci_and_broker": product == "cmqttd", "physical_networks_opened": False},
        "cases": [], "combined_network_checks": [], "setup": {},
        "passed": 0, "failed": 0, "wire_equal": 0, "combined_network_passed": 0,
    }
    with owned_server(product, binary) as port, socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.settimeout(5)
        stream = sock.makefile("rb")
        try:
            greeting = stream.readline().decode("utf-8")
            if not greeting.startswith("201 ") or not greeting.endswith("\r\n"):
                raise ValueError("Rust greeting lost 201/CRLF")
            receipt["setup"]["greeting"] = greeting
            for tag, command in (("701", "PROJECT NEW XUNIT"),
                                 ("702", "PROJECT USE XUNIT"),
                                 ("703", "DBCREATENET 254 Local Cni 127.0.0.1:1")):
                rows, events = send(sock, stream, tag, f"[{tag}] {command}\r\n")
                if not rows[-1].startswith(f"[{tag}] 200 "):
                    raise ValueError(f"seed {command} failed: {rows}")
                receipt["setup"][tag] = {"rows": rows, "events": events}
            rows, events = send(sock, stream, "704", "[704] DBGETXML //XUNIT/254\r\n")
            seeded = xml_payload(rows, "704", original=False)
            document = ET.fromstring(seeded)
            network_oid = document.findtext("OID")
            interface_oid = document.findtext("Interface/OID")
            if not network_oid or not interface_oid:
                raise ValueError("seeded Network lacks generated identities")
            receipt["setup"]["704"] = {"rows": rows, "events": events}
            substitutions = {native["network_oid"]: network_oid, native["interface_oid"]: interface_oid}
            prior_substitutions = {**substitutions, prior_network_oid(prior): network_oid}
            for original in cases:
                tag = original["tag"]
                request = original["request"]
                expected_rows = original["response_lines"]
                for old, new in substitutions.items():
                    request = request.replace(old, new)
                    expected_rows = [row.replace(old, new) for row in expected_rows]
                rows, events = send(sock, stream, tag, request)
                is_xml = original["command"].startswith("DBGETXML ")
                if is_xml:
                    expected = xml_payload(expected_rows, tag, original=True)
                    actual = xml_payload(rows, tag, original=False)
                else:
                    expected = expected_rows[-1]
                    actual = rows[-1]
                matched = expected == actual
                receipt["cases"].append({
                    "tag": tag, "original_request": original["request"], "mapped_request": request,
                    "original_wire": original["response_lines"], "mapped_original_wire": expected_rows,
                    "rust_wire": rows, "unsolicited_events": events,
                    "expected_mapper_result": expected, "rust_mapper_result": actual,
                    "mapper_equal": matched, "wire_equal": expected_rows == rows,
                })
                if tag in COMBINED_CHECKS:
                    prior_set, prior_get, rust_tag = COMBINED_CHECKS[tag]
                    rust_request = f"[{rust_tag}] DBGETXML //XUNIT/254\r\n"
                    rust_rows, rust_events = send(sock, stream, rust_tag, rust_request)
                    original_rows = prior[prior_get]["response_lines"]
                    mapped_rows = original_rows
                    for old, new in prior_substitutions.items():
                        mapped_rows = [row.replace(old, new) for row in mapped_rows]
                    expected_network = xml_payload(mapped_rows, prior_get, original=True)
                    mapped_wire = [row.replace(f"[{prior_get}]", f"[{rust_tag}]", 1)
                                   for row in mapped_rows]
                    actual_network = xml_payload(rust_rows, rust_tag, original=False)
                    receipt["combined_network_checks"].append({
                        "after_current_tag": tag, "original_set_tag": prior_set,
                        "original_tag": prior_get, "rust_tag": rust_tag,
                        "original_request": prior[prior_get]["request"],
                        "rust_request": rust_request, "original_wire": original_rows,
                        "mapped_original_wire": mapped_wire, "rust_wire": rust_rows,
                        "unsolicited_events": rust_events,
                        "expected_mapper_result": expected_network,
                        "rust_mapper_result": actual_network,
                        "mapper_equal": expected_network == actual_network,
                        "wire_equal": mapped_wire == rust_rows,
                    })
            receipt["passed"] = sum(case["mapper_equal"] for case in receipt["cases"])
            receipt["failed"] = len(TAGS) - receipt["passed"]
            receipt["wire_equal"] = sum(case["wire_equal"] for case in receipt["cases"])
            receipt["combined_network_passed"] = sum(
                case["mapper_equal"] for case in receipt["combined_network_checks"]
            )
            receipt["result"] = "passed" if (receipt["failed"] == 0
                and receipt["wire_equal"] == len(TAGS)
                and receipt["combined_network_passed"] == 2
                and all(check["wire_equal"] for check in receipt["combined_network_checks"])) else "failed"
        finally:
            stream.close()
    return receipt


def validate_receipt(receipt: dict) -> None:
    native, cases = native_cases()
    prior = combined_cases(native)
    product = receipt.get("product")
    if product not in ("cgate-mock", "cmqttd") or receipt.get("format") != "cgate-dbsetxml-unit-mapper-differential-v1":
        raise ValueError("Unit mapper receipt identity changed")
    if receipt.get("native_fixture") != {"path": NATIVE.relative_to(ROOT).as_posix(), "sha256": NATIVE_SHA256}:
        raise ValueError("Unit mapper native fixture binding changed")
    if receipt.get("combined_native_fixture") != {"path": COMBINED.relative_to(ROOT).as_posix(), "sha256": COMBINED_SHA256}:
        raise ValueError("combined Network native fixture binding changed")
    if receipt.get("vendor_jar_sha256") != native["jar_sha256"]:
        raise ValueError("Unit mapper original binary binding changed")
    if receipt.get("source_fingerprint") != fingerprint(product == "cmqttd"):
        raise ValueError("Unit mapper Rust/source closure changed")
    if (receipt.get("passed") != 12 or receipt.get("failed") != 0
            or receipt.get("wire_equal") != 12 or receipt.get("combined_network_passed") != 2
            or receipt.get("result") != "passed"):
        raise ValueError("Unit mapper result is not 12/12 exact wire plus 2/2 combined Network")
    if receipt.get("offline_provision", {}).get("physical_networks_opened") is not False:
        raise ValueError("Unit mapper receipt is not offline")
    observed = receipt.get("cases")
    if not isinstance(observed, list) or [row.get("tag") for row in observed] != list(TAGS):
        raise ValueError("Unit mapper case sequence changed")
    setup = receipt.get("setup", {})
    greeting = setup.get("greeting", "")
    if not greeting.startswith("201 ") or not greeting.endswith("\r\n"):
        raise ValueError("Unit mapper greeting framing changed")
    for tag in ("701", "702", "703"):
        if not setup.get(tag, {}).get("rows", [""])[-1].startswith(f"[{tag}] 200 "):
            raise ValueError(f"Unit mapper seed {tag} changed")
    seeded = ET.fromstring(xml_payload(setup["704"]["rows"], "704", original=False))
    network_oid = seeded.findtext("OID")
    interface_oid = seeded.findtext("Interface/OID")
    if not network_oid or not interface_oid or network_oid == interface_oid:
        raise ValueError("Unit mapper seeded identities changed")
    substitutions = {native["network_oid"]: network_oid, native["interface_oid"]: interface_oid}
    prior_substitutions = {**substitutions, prior_network_oid(prior): network_oid}
    for original, actual in zip(cases, observed, strict=True):
        tag = original["tag"]
        if actual["original_request"] != original["request"] or actual["original_wire"] != original["response_lines"]:
            raise ValueError(f"original wire changed at {tag}")
        mapped_request = original["request"]
        mapped_original_wire = original["response_lines"]
        for old, new in substitutions.items():
            mapped_request = mapped_request.replace(old, new)
            mapped_original_wire = [row.replace(old, new) for row in mapped_original_wire]
        if actual["mapped_request"] != mapped_request or actual["mapped_original_wire"] != mapped_original_wire:
            raise ValueError(f"Unit mapper OID substitution changed at {tag}")
        if actual["expected_mapper_result"] != actual["rust_mapper_result"] or not actual["mapper_equal"]:
            raise ValueError(f"mapper mismatch at {tag}")
        if original["command"].startswith("DBGETXML "):
            if xml_payload(actual["mapped_original_wire"], tag, original=True) != xml_payload(actual["rust_wire"], tag, original=False):
                raise ValueError(f"XML reply changed at {tag}")
        elif actual["mapped_original_wire"] != actual["rust_wire"]:
            raise ValueError(f"301 reply changed at {tag}")
        if actual["wire_equal"] != (actual["mapped_original_wire"] == actual["rust_wire"]):
            raise ValueError(f"wire comparison changed at {tag}")
    if receipt.get("wire_equal") != sum(case["wire_equal"] for case in observed):
        raise ValueError("wire divergence count changed")
    combined = receipt.get("combined_network_checks")
    if not isinstance(combined, list) or len(combined) != 2:
        raise ValueError("combined Network checks missing")
    for check, (current_tag, (prior_set, prior_get, rust_tag)) in zip(
        combined, COMBINED_CHECKS.items(), strict=True
    ):
        original = prior[prior_get]
        mapped = original["response_lines"]
        for old, new in prior_substitutions.items():
            mapped = [row.replace(old, new) for row in mapped]
        expected_wire = [row.replace(f"[{prior_get}]", f"[{rust_tag}]", 1)
                         for row in mapped]
        if (check.get("after_current_tag") != current_tag or check.get("original_set_tag") != prior_set
                or check.get("original_tag") != prior_get or check.get("rust_tag") != rust_tag
                or check.get("original_request") != original["request"]
                or check.get("rust_request") != f"[{rust_tag}] DBGETXML //XUNIT/254\r\n"
                or check.get("original_wire") != original["response_lines"]
                or check.get("mapped_original_wire") != expected_wire):
            raise ValueError(f"combined Network provenance changed at {prior_get}")
        expected = xml_payload(mapped, prior_get, original=True)
        actual = xml_payload(check["rust_wire"], rust_tag, original=False)
        if (expected != actual or check.get("expected_mapper_result") != expected
                or check.get("rust_mapper_result") != actual or check.get("mapper_equal") is not True
                or check.get("wire_equal") is not True or check["rust_wire"] != expected_wire):
            raise ValueError(f"combined Network mapper changed at {prior_get}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-bin", type=Path, required=True)
    parser.add_argument("--cmqttd-bin", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for product, binary, filename in (
        ("cgate-mock", args.mock_bin, "cgate-dbsetxml-unit-differential-mock.json"),
        ("cmqttd", args.cmqttd_bin, "cgate-dbsetxml-unit-differential-cmqttd.json"),
    ):
        receipt = probe(product, binary.resolve())
        receipt["command"] = shlex.join([sys.executable, *sys.argv])
        (args.output_dir / filename).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"product": product, "result": receipt["result"],
                          "passed": receipt["passed"], "failed": receipt["failed"],
                          "combined_network_passed": receipt["combined_network_passed"],
                          "wire_equal": receipt["wire_equal"]}))
        failures += (receipt["failed"] + len(TAGS) - receipt["wire_equal"]
                     + 2 - receipt["combined_network_passed"]
                     + sum(not check["wire_equal"] for check in receipt["combined_network_checks"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
