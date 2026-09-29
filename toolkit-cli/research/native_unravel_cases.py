#!/usr/bin/env python3
"""Capture native C-Gate 3.4 NET UNRAVELUNIT on general duplicate topologies.

One owned loopback ``LocalCGate`` serves every case. Each case opens a fresh
disposable project against a fresh ``UnravelBusFixture`` on an ephemeral
loopback port. Nothing connects to a real CNI, PCI or C-Bus network.

Raw per-case artifacts (full wire, every C-Gate reply) go to the ignored
``research/runtime`` directory. ``--output`` receives the sanitized committed
report: the synthetic fixture topology, exact command/reply text with the
random project name replaced by ``//UNRAVEL/254``, every address-changing PCI
request/reply pair and the final simulator and database state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from cbus_toolkit.cgate import CGateClient, CGateError  # noqa: E402
from cbus_toolkit.native import NativeDatabase, NativeProjects  # noqa: E402
from cbus_toolkit.networks import NativeNetworks  # noqa: E402
from cbus_toolkit.programming import xml_text  # noqa: E402
from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402
from unravel_bus_fixture import UnravelBusFixture, canonical, keye1  # noqa: E402

FORMAT = "cbus-native-unravel-cases-v1"
SANITIZED_NETWORK = "//UNRAVEL/254"
SERIAL = {low: canonical((0x18B10600 | low).to_bytes(4, "big")) for low in range(0x16, 0x1B)}

# name -> (physical nodes [(address, serial low byte)], database {address: serial low}, units argument)
CASES = {
    "n3_at_255_matchdb": ([(255, 0x16), (255, 0x17), (255, 0x18)], {6: 0x16, 7: 0x17, 8: 0x18}, "255 MATCHDB"),
    "n4_at_255_partial_db": ([(255, 0x16), (255, 0x17), (255, 0x18), (255, 0x19)], {6: 0x16, 7: 0x17}, "255 MATCHDB"),
    "n3_ordinary_no_matchdb": ([(20, 0x16), (20, 0x17), (20, 0x18)], {20: 0x16}, "20"),
    "n4_ordinary_matchdb": ([(20, 0x16), (20, 0x17), (20, 0x18), (20, 0x19)], {20: 0x17, 9: 0x18}, "20 MATCHDB"),
    "matchdb_target_occupied_unknown": ([(255, 0x16), (6, 0x1A)], {6: 0x16}, "255 MATCHDB"),
    "matchdb_target_occupied_known": ([(255, 0x16), (6, 0x1A)], {6: 0x16, 9: 0x1A}, "255 MATCHDB"),
    "swap_cycle": ([(7, 0x16), (6, 0x17)], {6: 0x16, 7: 0x17}, "6,7 MATCHDB"),
    "unknown_serial_255": ([(255, 0x1A)], {6: 0x16}, "255 MATCHDB"),
    "unknown_serial_ordinary": ([(20, 0x1A)], {6: 0x16}, "20 MATCHDB"),
    "pci_address_duplicate": ([(16, 0x16)], {6: 0x16}, "16 MATCHDB"),
    "free_address_skips_database": ([(255, 0x1A)], {2: 0x16, 3: 0x17}, "255 MATCHDB"),
    # Response order differs from serial order: separates the two orderings.
    "n3_at_255_reordered_no_db": ([(255, 0x18), (255, 0x16), (255, 0x17)], {30: 0x1A}, "255 MATCHDB"),
    "n3_ordinary_reordered_no_matchdb": ([(20, 0x18), (20, 0x16), (20, 0x17)], {20: 0x16}, "20"),
    "n3_ordinary_matchdb_no_keeper": ([(20, 0x16), (20, 0x17), (20, 0x18)], {30: 0x1A}, "20 MATCHDB"),
}


def sanitize(text, network):
    return text.replace(network, SANITIZED_NETWORK).replace(network.split("/")[2], "UNRAVEL")


def database_units(xml):
    root = ET.fromstring(xml)
    return sorted(({"address": int(unit.findtext("Address")), "serial": unit.findtext("SerialNumber")}
                   for unit in root.iter("Unit")), key=lambda unit: unit["address"])


def address_wire(wire):
    """PCI request/reply pairs that can change an address or local option."""
    pairs, pending = [], None
    for record in wire:
        data = bytes.fromhex(record["hex"])
        if record["direction"] == "rx":
            text = data.decode(errors="replace").strip()
            upper = text.upper()
            pending = None
            # Compressed-header co requests start at 0F00 without 05FF00.
            if any(marker in upper for marker in ("0F0018B106", "A3204E", "1120", "A34297")):
                pending = {"request": text, "reply": ""}
                pairs.append(pending)
        elif record["direction"] == "tx" and pending is not None:
            pending["reply"] += data.decode(errors="replace")
    return pairs


def run_case(client, name, nodes, database, argument, runtime):
    project = "UV" + uuid4().hex[:6].upper()
    network = f"//{project}/254"
    fixture = UnravelBusFixture([keye1(address, low) for address, low in nodes])
    projects, db, networks = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
    commands, created = [], False

    def run(command, check=True):
        try:
            response = client.command(command)
            lines, status = list(response.lines), response.status
        except CGateError as error:
            lines, status = list(error.response.lines), error.response.status
            if check:
                raise
        commands.append({"command": sanitize(command, network), "status": status,
                         "reply": [sanitize(line, network) for line in lines]})
        return lines, status

    report = {"case": name, "passed": False}
    before = fixture.snapshot()
    with fixture.running("127.0.0.1", 0) as (_, port):
        try:
            projects.operation("new", project); created = True
            db.create_network(project, 254, "Unravel_Cases", "Cni", "127.0.0.1:" + str(port))
            for address, low in sorted(database.items()):
                db.create_unit(network, address, f"Db_{address}", "KEYE1", "2.5.00", catalog_number="5031NMML")
                db.set(network + f"/p/{address}/SerialNumber", SERIAL[low])
            projects.operation("save", project)
            xml_before = xml_text(db.get(network, xml=True))
            for setting in ("AutoUnravel no", "AutoUpdate no", "Retries 0"):
                run("SET " + network + " " + setting)
            networks.open(network)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                lines, _ = run("GET " + network + " InterfaceState", check=False)
                if any("InterfaceState=running" in line for line in lines):
                    break
                time.sleep(.2)
            else:
                raise RuntimeError("No running interface")
            commands.clear()
            start = len(fixture.wire_log)
            lines, status = run("NET UNRAVELUNIT " + network + " " + argument, check=False)
            unravel_wire = fixture.wire_log[start:]
            after_topology = fixture.topology()
            post = []
            post.append(run("GET " + network + " Units", check=False))
            for _ in range(50):
                lines_, _ = run("GET " + network + " SyncState", check=False)
                if any("SyncState=idle" in line for line in lines_):
                    break
                time.sleep(.2)
            for command in ("NET SYNC " + network + " fast", "GET " + network + " Units"):
                post.append(run(command, check=False))
            xml_after = xml_text(db.get(network, xml=True))
            report.update(
                passed=True, status=status,
                reply=[sanitize(line, network) for line in lines],
                before_topology={entry["serial"]: entry["address"] for entry in before["nodes"]},
                after_topology=after_topology,
                after_fixture=fixture.snapshot(),
                database_before=database_units(xml_before), database_after=database_units(xml_after),
                database_unchanged=xml_before == xml_after,
                co_operations=fixture.co_operations, store_operations=fixture.store_operations,
                unlock_operations=fixture.unlock_operations, pci_operations=fixture.pci_operations,
                rejected_writes=fixture.rejected_writes, silent_reads=fixture.silent_reads,
                address_wire=address_wire(unravel_wire),
                unravel_wire=[[record["direction"], bytes.fromhex(record["hex"]).decode(errors="replace")]
                              + ([record["reason"]] if record.get("reason") else []) for record in unravel_wire],
                post_commands=[c for c in commands if not c["command"].startswith("NET UNRAVELUNIT")])
        except Exception as error:  # Research capture: retain the failure.
            report["error"] = f"{type(error).__name__}: {sanitize(str(error), network)}"
        finally:
            cleanup = []
            if created:
                for command in ("NET CLOSE " + network, "PROJECT CLOSE " + project, "PROJECT DELETE " + project):
                    try:
                        client.command(command)
                    except Exception as error:
                        cleanup.append(type(error).__name__)
            report["cleanup_errors"] = cleanup
            raw = dict(report, commands=commands, wire=fixture.wire_log, project=project)
            if runtime is not None:
                runtime.mkdir(parents=True, exist_ok=True)
                path = runtime / f"native-unravel-{name}.json"
                path.write_text(json.dumps(raw, indent=2) + "\n")
                report["raw_artifact"] = "research/runtime/" + path.name
                report["raw_artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    report["setup"] = {"nodes": [{"address": address, "serial": SERIAL[low]} for address, low in nodes],
                       "database": {str(address): SERIAL[low] for address, low in sorted(database.items())},
                       "command": f"NET UNRAVELUNIT {SANITIZED_NETWORK} {argument}"}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, default=os.environ.get("CBUS_LOCAL_CGATE_VENDOR"))
    parser.add_argument("--java", type=Path, default=os.environ.get("CBUS_CGATE_JAVA"))
    parser.add_argument("--output", type=Path,
                        default=HERE.parents[1] / "rust/testdata/fixtures/native_cgate_unravel_cases.json")
    parser.add_argument("--runtime", type=Path, default=HERE / "runtime")
    parser.add_argument("--case", action="append", choices=sorted(CASES))
    args = parser.parse_args()
    selected = args.case or list(CASES)
    results = {}
    service = LocalCGate(args.vendor, java=args.java)
    try:
        # Disposable loopback projects need the same level as the owned test host.
        (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
    except BaseException as error:
        service._cleanup_preserving(error)
        raise
    with service:
        with CGateClient("127.0.0.1", service.port, timeout=120) as client:
            for name in selected:
                nodes, database, argument = CASES[name]
                print("case", name, flush=True)
                results[name] = run_case(client, name, nodes, database, argument, args.runtime)
                print("  ->", results[name].get("status"), results[name].get("after_topology"),
                      results[name].get("error"), flush=True)
    oracle = {key: service.report.get(key) for key in (
        "vendor_jar_sha256", "java_sha256", "listener_ownership_verified", "cleanup_complete",
        "process_exit_confirmed", "work_removed")}
    oracle.update(version="3.4.0 build 2001", physical_endpoint=False)
    document = {"format": FORMAT,
                "scope": "Owned loopback native C-Gate 3.4.0 build 2001 against the research-only "
                         "UnravelBusFixture. Synthetic KEYE1 2.5.00 nodes; fixture move policies are "
                         "choices, not firmware claims. No hardware, bridge or power-cycle claim.",
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "jar_sha256": JAR_SHA256, "oracle": oracle,
                "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "fixture_sha256": hashlib.sha256((HERE / "unravel_bus_fixture.py").read_bytes()).hexdigest(),
                "cases": results}
    if args.output.exists() and args.case:
        previous = json.loads(args.output.read_text())
        previous["cases"].update(results)
        results = previous["cases"]
        document["cases"] = {name: results[name] for name in CASES if name in results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    main()
