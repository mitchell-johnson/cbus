#!/usr/bin/env python3
"""Capture same-OID Applications with Level-bearing Group/NetVar children."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import cgate_dbsetxml_duplicate_applications as exchange_helper
import local_cgate
from local_cgate import JAR_SHA256, LocalCGate


SHARED = "33333333-3333-4333-8333-333333333333"
SHAPES = (("XLGR", "Group"), ("XLNV", "NetVar"))


def app(kind: str, address: int) -> str:
    child_oid = f"44444444-4444-4444-8444-0000000000{address}"
    level_oid = f"55555555-5555-4555-8555-0000000000{address}"
    level = (f'<Level Value="{address}"><OID>{level_oid}</OID>'
             f"<TagName>Level{address}</TagName><Address>2</Address></Level>")
    child = (f"<{kind}><OID>{child_oid}</OID><TagName>{kind}{address}</TagName>"
             f"<Address>1</Address>{level}</{kind}>")
    return (f"<Application><OID>{SHARED}</OID><TagName>App{address}</TagName>"
            f"<Address>{address}</Address>{child}</Application>")


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
            next_tag = 800

            def call(command: str, document: str | None = None) -> dict:
                nonlocal next_tag
                row = exchange_helper.exchange(stream, next_tag, command, document)
                cases.append(row)
                print(next_tag, exchange_helper.status(row), command, flush=True)
                next_tag += 1
                return row

            for project, kind in SHAPES:
                call(f"PROJECT NEW {project}")
                call(f"PROJECT USE {project}")
                call("DBCREATENET 254 Local Cni 127.0.0.1:1")
                baseline = ET.fromstring(exchange_helper.xml(call(f"DBGETXML //{project}/254")))
                network_oid = baseline.findtext("OID")
                interface_oid = baseline.findtext("Interface/OID")
                assert network_oid and interface_oid
                network = (f"<Network><OID>{network_oid}</OID><TagName>Local</TagName>"
                           "<Address>254</Address><NetworkNumber>254</NetworkNumber>"
                           f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
                           "<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>"
                           + "".join(app(kind, address) for address in (56, 57)) + "</Network>")
                submit_tag = next_tag
                call(f"DBSETXML //{project}/254", network)
                for phase in ("before_save", "after_load"):
                    if phase == "after_load":
                        call(f"PROJECT SAVE {project}")
                        call(f"DBGETXML //{project}/254")
                        call(f"PROJECT CLOSE {project}")
                        call(f"PROJECT LOAD {project}")
                        call(f"DBGETXML //{project}/254")
                        call(f"PROJECT USE {project}")
                    call(f"DBGETXML //{project}/254")
                    for address in (56, 57):
                        call(f"DBGETXML //{project}/254/{address}")
                        call(f"DBGETXML //{project}/254/{address}/1")
                        call(f"DBGETXML //{project}/254/{address}/1/2")
                        call(f"DBGETXML !55555555-5555-4555-8555-0000000000{address}")
                    call(f"DBGETXML !{SHARED}")
                shapes.append({"project": project, "kind": kind, "addresses": [56, 57],
                               "network_oid": network_oid, "interface_oid": interface_oid,
                               "submit_tag": submit_tag})

    report = service.report
    data = {
        "schema": "native-cgate-dbsetxml-nested-levels-v1",
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
        "exchange_helper_sha256": hashlib.sha256(Path(exchange_helper.__file__).read_bytes()).hexdigest(),
        "service_harness_sha256": hashlib.sha256(Path(local_cgate.__file__).read_bytes()).hexdigest(),
        "greeting": greeting, "shared_oid": SHARED, "shapes": shapes, "cases": cases,
    }
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
