#!/usr/bin/env python3
"""Probe the real disposable C-Gate oracle against an isolated PCI simulator.

Creates a uniquely marked disposable project, whose only CNI endpoint points
at this process's ephemeral simulator. Never adopts existing projects or opens
any other network. Exact wire bytes and the next unsupported request are saved.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.pci import PCIClient
from cbus_toolkit.programming import Programmer, parameter_values
from cbus_toolkit.simulator import PCISimulator, UnitState, default_units

MARKER = "cbus-toolkit-isolated-pci-oracle-v1"


def key4_simulator(log_path, state_path):
    """Explicit sparse fixture; checksum mutation remains unverified."""
    fixture = json.loads((Path(__file__).parent / "fixtures/key4-synthetic.json").read_text())
    memory = {int(address): value for address, value in fixture["legacy_memory"].items()}
    # CBusUnit.g reads the configured change byte F2; this test chooses FF.
    memory[0xF2] = 255
    protected = {0x1F, 0x20, 0x70, 0x71, *range(0xF7, 0xFF)}
    unit = UnitState(4, {1: b"KEY4    ", 2: b"1.2.67  ", 8: bytes(5),
                         4: bytes.fromhex("38FFFFFFFF18000000000001")}, mmi_state=1)
    return PCISimulator([unit, default_units()[-1]], profile="synthetic", physical_memory={},
                        legacy_memory={4: memory}, legacy_writable={4: set(memory) - protected},
                        status_blocks={4: {0: b"\x00", 1: bytes(8)}},
                        wire_log_path=log_path, state_path=state_path)


def verify_native_pp(command, address, simulator_port, state_path):
    class RecordedClient:
        def command(self, text):
            return command(text)
    programmer = Programmer(RecordedClient())
    result = {"verified": False, "checksum_mutation_verified": False,
              "scope": "Native PP legacy field transfer; hardware checksum mutation remains unsupported"}
    target = address + "/p/4"
    with PCIClient("127.0.0.1", simulator_port, local_unit=16) as client:
        original = client.recall(4, 0x2A, 6)
        result["checksum_registers_before"] = client.recall(4, 0x1E, 2).hex()
    with programmer.load(address, target) as session:
        result["before"] = parameter_values(session.get("UnitName"))["UnitName"]
        session.set("UnitName", "PPWRITE")
        session.save_to_source()
    with PCIClient("127.0.0.1", simulator_port, local_unit=16) as client:
        result["independent_bytes"] = client.recall(4, 0x2A, 6).hex()
        result["checksum_registers_after"] = client.recall(4, 0x1E, 2).hex()
    with programmer.load(address, target) as session:
        result["after"] = parameter_values(session.get("UnitName"))["UnitName"]
        session.set("UnitName", result["before"])
        session.save_to_source()
    with PCIClient("127.0.0.1", simulator_port, local_unit=16) as client:
        restored = client.recall(4, 0x2A, 6)
    reloaded = PCISimulator(profile="synthetic", state_path=state_path)
    with reloaded.running() as endpoint, PCIClient(*endpoint, local_unit=16) as client:
        persisted = client.recall(4, 0x2A, 6)
    result["restoration_verified"] = restored == persisted == original
    result["checksum_observation"] = (
        "The fixture retains the explicit checksum registers. Native field SAVE did not send a checksum update; "
        "this is not evidence of the device firmware checksum algorithm.")
    result["verified"] = (result["before"].strip() == "SIMKEY4" and result["after"].strip() == "PPWRITE"
                          and result["independent_bytes"] == "befdb1a3391e"
                          and result["restoration_verified"])
    return result


def verify_physical_write(simulator_port, state_path):
    """After C-Gate closes its fixture connection, prove raw transport writes.

    This deliberately tests PCIClient, not PP SAVE or a hardware flash workflow.
    Read back through both the active socket peer and a new server loaded from
    disk. Restore the fixture's application bytes before returning.
    """
    with PCIClient("127.0.0.1", simulator_port, local_unit=16) as client:
        client.write(5, 0, b"\x41\x10\x00", addressing="programming", ack_tag=0x41)
        original = client.recall(5, 1, 2, addressing="programming")
        changed = bytes([original[0] ^ 1, original[1]])
        client.write(5, 0, b"\x41\x10\x00", addressing="programming", ack_tag=0x41)
        client.write(5, 1, b"\x42" + changed, addressing="programming", ack_tag=0x42)
        client.write(5, 0, b"\x41\x10\x00", addressing="programming", ack_tag=0x41)
        immediate = client.recall(5, 1, 2, addressing="programming")
    reloaded = PCISimulator(profile="synthetic", state_path=state_path)
    with reloaded.running() as address, PCIClient(*address, local_unit=16) as client:
        client.write(5, 0, b"\x41\x10\x00", addressing="programming", ack_tag=0x41)
        persisted = client.recall(5, 1, 2, addressing="programming")
    with PCIClient("127.0.0.1", simulator_port, local_unit=16) as client:
        client.write(5, 0, b"\x41\x10\x00", addressing="programming", ack_tag=0x41)
        client.write(5, 1, b"\x42" + original, addressing="programming", ack_tag=0x42)
        client.write(5, 0, b"\x41\x10\x00", addressing="programming", ack_tag=0x41)
        restored = client.recall(5, 1, 2, addressing="programming")
    return {"verified": immediate == persisted == changed and restored == original,
            "scope": "PCIClient programming memory, not native PP SAVE or hardware flash",
            "original": original.hex(), "written": changed.hex(),
            "read_back": immediate.hex(), "reloaded_read_back": persisted.hex(), "restored": restored.hex()}


def verify(*, oracle_port=20023, duration=15, output_dir=None, container="cbus-toolkit-oracle", fixture="synthetic", backend=None):
    from research.local_cgate import LocalCGate, service_backend
    backend = service_backend() if backend is None else backend
    if backend not in ("local", "docker"):
        raise ValueError("Native network backend must be local or docker")
    if not 0 < duration <= 120:
        raise ValueError("Probe duration must be in 0..120 seconds")
    if fixture not in ("synthetic", "key4"):
        raise ValueError("Unknown acceptance fixture")
    if backend == "local":
        vendor = Path(os.environ.get("CBUS_LOCAL_CGATE_VENDOR", Path(__file__).parent / "vendor/cgate/app"))
        service = LocalCGate(vendor)
        with service:
            report = _verify_in_service(oracle_port=service.port, duration=duration,
                output_dir=output_dir, fixture=fixture, backend=backend)
        report['local_service'] = service.report
        report['service_cleanup_verified'] = service.report.get('cleanup_complete') is True
        if not report['service_cleanup_verified']: report['acceptance_status'] = 'incomplete'
        Path(report['report_path']).write_text(json.dumps(report, indent=2) + '\n')
        return report
    # The server must be the explicitly labelled disposable vendor oracle.
    inspected = subprocess.run(["docker", "inspect", container],
                               check=True, capture_output=True, text=True)
    metadata = json.loads(inspected.stdout)[0]
    expected = (Path(__file__).parent / "runtime/cgate").resolve()
    isolated_mount = any(m.get("Destination") == "/work" and Path(m.get("Source", "")).resolve() == expected
                         for m in metadata.get("Mounts", []))
    ports = metadata.get("NetworkSettings", {}).get("Ports", {}).get("20023/tcp") or []
    isolated_port = any(p.get("HostIp") == "127.0.0.1" and p.get("HostPort") == str(oracle_port) for p in ports)
    labelled = metadata.get("Config", {}).get("Labels", {}).get("cbus-toolkit.role") == "disposable-oracle"
    if not isolated_mount or not isolated_port or not labelled:
        raise RuntimeError("Oracle must use the isolated research state and requested loopback port")
    return _verify_in_service(oracle_port=oracle_port, duration=duration,
        output_dir=output_dir, fixture=fixture, backend=backend)


def _verify_in_service(*, oracle_port, duration, output_dir, fixture, backend):
    project = "PCI" + uuid.uuid4().hex[:5].upper()
    output = Path(output_dir) if output_dir is not None else Path(__file__).parent / "runtime/network-oracle"
    output.mkdir(parents=True, exist_ok=True)
    log_path = output / (project + "-wire.jsonl")
    state_path = output / (project + "-state.json")
    if fixture not in ("synthetic", "key4"):
        raise ValueError("Unknown acceptance fixture")
    simulator = (key4_simulator(log_path, state_path) if fixture == "key4" else
                 PCISimulator(wire_log_path=log_path, state_path=state_path, profile="synthetic"))
    report = {"project": project, "marker": MARKER, "oracle_port": oracle_port, "backend": backend,
              "wire_log": str(log_path), "fixture": fixture, "commands": [], "cleanup_errors": [], "healthy": False,
              "scope": "Isolated SIMTEST fixture with captured identities and schema-encoded names; no hardware or scanner parity claim"}
    with simulator.running("127.0.0.1" if backend == "local" else "0.0.0.0", 0) as (_, simulator_port):
        endpoint = ("127.0.0.1:" if backend == "local" else "host.docker.internal:") + str(simulator_port)
        report["simulator_endpoint"] = endpoint
        address = "//" + project + "/254"
        with CGateClient("127.0.0.1", oracle_port, timeout=30) as client:
            created = False

            def command(text):
                # Every effectful command is constructed solely from this
                # unique project and simulator endpoint, never caller input.
                try:
                    response = client.command(text)
                    report["commands"].append({"command": text, "lines": list(response.lines)})
                    return response
                except CGateError as error:
                    report["commands"].append({"command": text, "lines": list(error.response.lines)})
                    raise

            try:
                command("PROJECT NEW " + project)
                created = True
                command("DBSET //" + project + "/Project/Description " + MARKER)
                command("PROJECT USE " + project)
                command("DBCREATENET 254 PCI_Oracle Cni " + endpoint)
                command("PROJECT SAVE " + project)
                command("NET LOAD DB " + project)
                try:
                    command("NET OPEN " + address)
                    report["open_completed"] = True
                except (CGateError, RuntimeError) as error:
                    report["open_error"] = str(error)
                    if not client.connected:
                        client.connect()
                deadline = time.monotonic() + duration
                while time.monotonic() < deadline:
                    state = command("GET " + address + " state")
                    if any(re.search(r"state\s*=\s*(?:ok|online)\b", line, re.I) for line in state.lines):
                        report["healthy"] = True
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
                for text in ("NET LIST " + project, "TREE " + address):
                    try:
                        command(text)
                    except CGateError:
                        pass
                if report["healthy"]:
                    if fixture == "key4":
                        try:
                            report["native_pp"] = verify_native_pp(command, address, simulator_port, state_path)
                        except Exception as error:
                            report["native_pp"] = {"verified": False, "error": str(error)}
                    else:
                        command("NET CLOSE " + address)
                        try:
                            report["physical_write"] = verify_physical_write(simulator_port, state_path)
                        except Exception as error:
                            report["physical_write"] = {"verified": False, "error": str(error)}
            finally:
                if created:
                    for text in ("NET CLOSE " + address, "PROJECT CLOSE " + project, "PROJECT DELETE " + project):
                        try:
                            if not client.connected:
                                client.connect()
                            command(text)
                        except Exception as error:
                            if not client.connected:
                                client.connect()
                            report["cleanup_errors"].append({"command": text, "error": str(error)})
    report["discovered_units"] = []
    for item in report["commands"]:
        for line in item["lines"]:
            match = re.search(re.escape("//" + project + "/254/p/") + r"(\d+).*type=(\S+).*state=(\S+)", line)
            if match:
                report["discovered_units"].append({"unit": int(match[1]), "type": match[2], "state": match[3]})
            if item["command"].startswith("NET LIST"):
                report["network_status"] = line
    report["unsupported_requests"] = []
    previous_request = None
    for item in simulator.wire_log:
        if item["direction"] == "rx":
            previous_request = item
        elif "reason" in item:
            report["unsupported_requests"].append({
                "request_hex": previous_request["hex"] if previous_request else None,
                "reply_hex": item["hex"], "reason": item["reason"]})
    report["wire_records"] = len(simulator.wire_log)
    report["unsupported"] = [record for record in simulator.wire_log if "reason" in record]
    required_units = {4, 16} if fixture == "key4" else {4, 5, 16}
    good_units = {unit["unit"] for unit in report["discovered_units"] if unit["state"] == "ok"}
    write_verified = (report.get("native_pp", {}).get("verified")
                      and report.get("native_pp", {}).get("checksum_mutation_verified")) if fixture == "key4" else report.get("physical_write", {}).get("verified")
    passed = (report["healthy"] and required_units <= good_units and write_verified
              and re.search(r"\bState=ok\b", report.get("network_status", ""))
              and not report["unsupported"] and not report["cleanup_errors"])
    report["acceptance_status"] = "passed" if passed else "incomplete"
    report["wire"] = simulator.wire_log
    report['report_path'] = str((output / (project + "-report.json")).resolve())
    Path(report['report_path']).write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle-port", type=int, default=20023)
    parser.add_argument("--duration", type=float, default=15)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--fixture", choices=("synthetic", "key4"), default="synthetic")
    parser.add_argument("--backend", choices=("local", "docker"), help="Explicit owned service backend; defaults to CBUS_NATIVE_SERVICE_BACKEND or docker")
    args = parser.parse_args()
    report = verify(oracle_port=args.oracle_port, duration=args.duration, output_dir=args.output_dir, fixture=args.fixture, backend=args.backend)
    print(json.dumps({key: value for key, value in report.items() if key not in ("commands", "wire")}, indent=2))
    return 0 if report["acceptance_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
