#!/usr/bin/env python3
"""Probe large and cross-Network shared OIDs on an owned original C-Gate.

Only synthetic, closed Networks using the loopback CNI 127.0.0.1:1 are made.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
from xml.etree import ElementTree as ET

import cgate_dbsetxml_duplicate_oids as wire
import local_cgate
from local_cgate import JAR_SHA256, LocalCGate


PROJECT = "XULARGE"
SHARED = "11111111-1111-4111-8111-111111111111"


def unit(address: int, name: str) -> str:
    return (
        f"<Unit><OID>{SHARED}</OID><TagName>{name}</TagName><Address>{address}</Address>"
        f"<UnitType>KEYE1</UnitType><UnitName>{name} room</UnitName>"
        '<FirmwareVersion>1.2.67</FirmwareVersion>'
        f'<PP Name="UnitAddress" Value="{address}"/></Unit>'
    )


def application() -> str:
    return (
        f"<Application><OID>{SHARED}</OID><TagName>Lighting</TagName>"
        "<Address>56</Address></Application>"
    )


def network_prefix(address: int, oid: str, interface_oid: str) -> str:
    return (
        f"<Network><OID>{oid}</OID><TagName>Local{address}</TagName>"
        f"<Address>{address}</Address><NetworkNumber>{address}</NetworkNumber>"
        f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
        "<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows: list[dict] = []
    cardinality: list[dict] = []
    cross_network: list[dict] = []
    tag = 1000
    with LocalCGate(args.vendor, java=args.java) as service:
        with socket.create_connection(("127.0.0.1", service.port), timeout=5) as sock:
            sock.settimeout(15)
            stream = sock.makefile("rwb", buffering=0)
            greeting = stream.readline().decode("utf-8")

            def call(command: str, document: str | None = None) -> dict:
                nonlocal tag
                row = wire.exchange(stream, tag, command, document)
                rows.append(row)
                tag += 1
                return row

            def lifecycle() -> list[dict]:
                return [call(f"PROJECT {verb} {PROJECT}")
                        for verb in ("SAVE", "CLOSE", "LOAD", "USE")]

            for command in (f"PROJECT NEW {PROJECT}", f"PROJECT USE {PROJECT}",
                            "DBCREATENET 254 Local254 Cni 127.0.0.1:1"):
                assert wire.status(call(command)) in (200, 301)
            original = ET.fromstring(wire.xml(call(f"DBGETXML //{PROJECT}/254")))
            network_oids = {254: original.findtext("OID")}
            interface_oids = {254: original.findtext("Interface/OID")}
            assert all(network_oids.values()) and all(interface_oids.values())

            for submitted in ((26, 24, 21, 20, 25, 23, 22),
                              (27, 25, 20, 24, 21, 26, 23, 22)):
                paths = [f"//{PROJECT}/254/p/{address}" for address in (*submitted, 30)]
                document = (network_prefix(254, network_oids[254], interface_oids[254])
                            + "".join(unit(address, f"Unit{address}") for address in submitted)
                            + "</Network>")
                selected = submitted[-1]
                commands = (
                    ("set_safe", f"DBSETSAFE !{SHARED}/UnitName ByOID", None),
                    ("set_unsafe", f"DBSET !{SHARED}/UnitName ByOID", None),
                    ("set_xml", f"DBSETXML !{SHARED}", unit(selected, "Changed")),
                    ("copy_safe", f"DBCOPYSAFE !{SHARED} //{PROJECT}/254 30 Copied", None),
                    ("delete", f"DBDELETE !{SHARED}", None),
                )
                for name, command, replacement in commands:
                    reset = call(f"DBSETXML //{PROJECT}/254", document)
                    before = [call(f"DBGETXML {path}") for path in paths]
                    oid_before = call(f"DBGETXML !{SHARED}")
                    applied = call(command, replacement)
                    after = [call(f"DBGETXML {path}") for path in paths]
                    oid_after = call(f"DBGETXML !{SHARED}")
                    project_lifecycle = lifecycle()
                    reloaded = [call(f"DBGETXML {path}") for path in paths]
                    oid_reloaded = call(f"DBGETXML !{SHARED}")
                    cardinality.append({"name": name, "submitted_addresses": submitted,
                                        "selected_address": selected, "reset": reset,
                                        "before": before, "oid_before": oid_before,
                                        "applied": applied, "after": after,
                                        "oid_after": oid_after, "lifecycle": project_lifecycle,
                                        "reloaded": reloaded, "oid_reloaded": oid_reloaded})

            created = call("DBCREATENET 253 Local253 Cni 127.0.0.1:1")
            assert wire.status(created) in (200, 301)
            original = ET.fromstring(wire.xml(call(f"DBGETXML //{PROJECT}/253")))
            network_oids[253] = original.findtext("OID")
            interface_oids[253] = original.findtext("Interface/OID")
            assert all(network_oids.values()) and all(interface_oids.values())

            for shape in ("unit_unit", "unit_unit_reversed_addresses",
                          "application_unit", "unit_application"):
                for first in (254, 253):
                    second = 253 if first == 254 else 254
                    objects = {
                        "unit_unit": {254: unit(20, "Unit20"), 253: unit(21, "Unit21")},
                        "unit_unit_reversed_addresses":
                            {254: unit(21, "Unit21"), 253: unit(20, "Unit20")},
                        "application_unit": {254: application(), 253: unit(21, "Unit21")},
                        "unit_application": {254: unit(20, "Unit20"), 253: application()},
                    }[shape]
                    for name in ("set_safe", "set_unsafe", "set_xml", "copy_safe", "delete"):
                        cleared = [call(f"DBSETXML //{PROJECT}/{net}",
                                        network_prefix(net, network_oids[net], interface_oids[net])
                                        + "</Network>") for net in (254, 253)]
                        inserts = [call(f"DBSETXML //{PROJECT}/{net}",
                                        network_prefix(net, network_oids[net], interface_oids[net])
                                        + objects[net] + "</Network>")
                                   for net in (first, second)]
                        paths = [f"//{PROJECT}/{net}/{kind}/{address}"
                                 for net, kind, address in (
                                     (254, "56", "") if shape == "application_unit" else
                                     (254, "p", 21 if shape == "unit_unit_reversed_addresses" else 20),
                                     (253, "56", "") if shape == "unit_application" else
                                     (253, "p", 20 if shape == "unit_unit_reversed_addresses" else 21))]
                        paths = [path.rstrip("/") for path in paths]
                        paths += [f"//{PROJECT}/253/p/30", f"//{PROJECT}/254/p/30",
                                  f"//{PROJECT}/253/30", f"//{PROJECT}/254/30"]
                        before = [call(f"DBGETXML {path}") for path in paths]
                        oid_before = call(f"DBGETXML !{SHARED}")
                        accepted = all(wire.status(row) == 301 for row in inserts)
                        if accepted:
                            selected = ET.fromstring(wire.xml(oid_before))
                            address = int(selected.findtext("Address"))
                            selected_kind = selected.tag
                            selected_net = next(
                                int(path.split("/")[3])
                                for path, row in zip(paths[:2], before[:2])
                                if wire.status(row) == 344
                                and (node := ET.fromstring(wire.xml(row))).tag == selected_kind
                                and int(node.findtext("Address")) == address
                            )
                            field = "UnitName" if selected_kind == "Unit" else "TagName"
                            changed = (unit(address, "Changed") if selected_kind == "Unit"
                                       else application().replace("Lighting", "Changed"))
                            command, replacement = {
                                "set_safe": (f"DBSETSAFE !{SHARED}/{field} ByOID", None),
                                "set_unsafe": (f"DBSET !{SHARED}/{field} ByOID", None),
                                "set_xml": (f"DBSETXML !{SHARED}", changed),
                                "copy_safe": (f"DBCOPYSAFE !{SHARED} //{PROJECT}/{selected_net} 30 Copied", None),
                                "delete": (f"DBDELETE !{SHARED}", None),
                            }[name]
                            applied = call(command, replacement)
                            after = [call(f"DBGETXML {path}") for path in paths]
                            oid_after = call(f"DBGETXML !{SHARED}")
                            project_lifecycle = lifecycle()
                            reloaded = [call(f"DBGETXML {path}") for path in paths]
                            oid_reloaded = call(f"DBGETXML !{SHARED}")
                        else:
                            applied = after = oid_after = project_lifecycle = reloaded = oid_reloaded = None
                            selected_net = None
                        cross_network.append({"shape": shape, "network_order": [first, second],
                                              "name": name, "cleared": cleared, "inserts": inserts,
                                              "accepted": accepted, "paths": paths,
                                              "before": before, "oid_before": oid_before,
                                              "selected_network": selected_net,
                                              "selected_kind": selected_kind if accepted else None,
                                              "applied": applied, "after": after,
                                              "oid_after": oid_after, "lifecycle": project_lifecycle,
                                              "reloaded": reloaded, "oid_reloaded": oid_reloaded})
    report = service.report
    payload = {
        "schema": "native-cgate-large-cross-network-oid-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "oracle": {"jar_sha256": JAR_SHA256,
                   "java_sha256": hashlib.sha256(args.java.read_bytes()).hexdigest(),
                   "version": "3.4.0 build 2001",
                   "owned_loopback_listeners": report["listener_ownership_verified"],
                   "listeners": report["listeners"],
                   "cleanup_complete": report["cleanup_complete"],
                   "process_exit_confirmed": report["process_exit_confirmed"],
                   "work_removed": report["work_removed"], "physical_endpoint": False},
        "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "exchange_helper_sha256": hashlib.sha256(Path(wire.__file__).read_bytes()).hexdigest(),
        "service_harness_sha256": hashlib.sha256(Path(local_cgate.__file__).read_bytes()).hexdigest(),
        "greeting": greeting, "project": PROJECT, "shared_oid": SHARED,
        "network_oids": network_oids, "interface_oids": interface_oids,
        "setup": rows[:4], "created_second_network": created,
        "second_network_baseline": rows[next(i for i, row in enumerate(rows)
                                              if row["command"] == f"DBGETXML //{PROJECT}/253")],
        "cardinality": cardinality, "cross_network": cross_network,
        "request_count": len(rows),
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cardinality_cases": len(cardinality),
                      "cross_network_cases": len(cross_network),
                      "cross_network_accepted": sum(case["accepted"] for case in cross_network),
                      "requests": len(rows), "cleanup": report["cleanup_complete"]}))


if __name__ == "__main__":
    main()
