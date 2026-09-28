#!/usr/bin/env python3
"""Capture repeated-OID leaf Application order/count in owned C-Gate 3.4.0.

Each shape uses a new synthetic project, an unopened loopback CNI, and the
pinned original build-2001 JAR. The complete tagged requests and replies are
saved so the Rust service can be checked against exact native behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import cgate_dbsetxml_duplicate_applications as previous
import local_cgate
from local_cgate import JAR_SHA256, LocalCGate


SHARED = "33333333-3333-4333-8333-333333333333"
SHAPES = (
    ("XREVA", ((57, "Second"), (56, "First"))),
    ("XTRIA", ((56, "First"), (57, "Second"), (58, "Third"))),
    ("XQUAD", ((59, "Fourth"), (57, "Second"), (56, "First"), (58, "Third"))),
)


def app(address: int, name: str) -> str:
    return (f"<Application><OID>{SHARED}</OID><TagName>{name}</TagName>"
            f"<Address>{address}</Address></Application>")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = []
    shapes = []
    with LocalCGate(args.vendor, java=args.java) as service:
        with socket.create_connection(("127.0.0.1", service.port), timeout=5) as sock:
            sock.settimeout(10)
            stream = sock.makefile("rwb", buffering=0)
            greeting = stream.readline().decode("utf-8")
            next_tag = 400

            def call(command: str, document: str | None = None) -> dict:
                nonlocal next_tag
                row = previous.exchange(stream, next_tag, command, document)
                cases.append(row)
                print(next_tag, previous.status(row), command, flush=True)
                next_tag += 1
                return row

            for project, applications in SHAPES:
                call(f"PROJECT NEW {project}")
                call(f"PROJECT USE {project}")
                call("DBCREATENET 254 Local Cni 127.0.0.1:1")
                baseline = ET.fromstring(previous.xml(call(f"DBGETXML //{project}/254")))
                network_oid = baseline.findtext("OID")
                interface_oid = baseline.findtext("Interface/OID")
                assert network_oid and interface_oid
                network = (f"<Network><OID>{network_oid}</OID><TagName>Local</TagName>"
                           "<Address>254</Address><NetworkNumber>254</NetworkNumber>"
                           f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
                           "<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>"
                           + "".join(app(address, name) for address, name in applications) + "</Network>")
                shapes.append({"project": project, "submitted": [address for address, _ in applications],
                               "network_oid": network_oid, "interface_oid": interface_oid,
                               "submit_tag": next_tag})
                call(f"DBSETXML //{project}/254", network)
                call(f"DBGETXML //{project}/254")
                for address, _ in applications:
                    call(f"DBGETXML //{project}/254/{address}")
                call(f"DBGETXML !{SHARED}")
                call(f"DBGET !{SHARED}/Address")
                call(f"PROJECT SAVE {project}")
                call(f"PROJECT CLOSE {project}")
                call(f"PROJECT LOAD {project}")
                call(f"PROJECT USE {project}")
                call(f"DBGETXML //{project}/254")
                for address, _ in applications:
                    call(f"DBGETXML //{project}/254/{address}")
                call(f"DBGETXML !{SHARED}")
                call(f"DBGET !{SHARED}/Address")
                # Replace an explicit path, then mutate the OID-selected record.
                address, name = applications[0]
                call(f"DBSETXML //{project}/254/{address}", app(address, f"Changed{name}"))
                call(f"DBGETXML //{project}/254")
                call(f"DBGETXML !{SHARED}")
                call(f"DBSET !{SHARED}/TagName ByOID")
                call(f"DBGETXML //{project}/254")
                call(f"DBGETXML !{SHARED}")
                selected_address = applications[-1][0]
                call(f"DBSETXML !{SHARED}", app(selected_address, "ViaXML"))
                call(f"DBGETXML //{project}/254")
                call(f"DBGETXML !{SHARED}")
                call(f"DBGETXML //{project}/254/{address}")
                call(f"DBGETXML //{project}/254/{selected_address}")
                call(f"PROJECT SAVE {project}")
                call(f"PROJECT CLOSE {project}")
                call(f"PROJECT LOAD {project}")
                call(f"PROJECT USE {project}")
                call(f"DBGETXML //{project}/254")
                call(f"DBGETXML !{SHARED}")

    report = service.report
    data = {
        "schema": "native-cgate-dbsetxml-application-shapes-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "oracle": {"jar_sha256": JAR_SHA256,
                   "java_sha256": hashlib.sha256(args.java.read_bytes()).hexdigest(),
                   "version": "3.4.0 build 2001",
                   "owned_loopback_listeners": report["listener_ownership_verified"],
                   "listeners": report["listeners"],
                   "cleanup_complete": report["cleanup_complete"],
                   "process_exit_confirmed": report["process_exit_confirmed"],
                   "work_removed": report["work_removed"],
                   "physical_endpoint": False},
        "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "exchange_helper_sha256": hashlib.sha256(Path(previous.__file__).read_bytes()).hexdigest(),
        "service_harness_sha256": hashlib.sha256(Path(local_cgate.__file__).read_bytes()).hexdigest(),
        "greeting": greeting, "shared_oid": SHARED, "shapes": shapes, "cases": cases,
    }
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
