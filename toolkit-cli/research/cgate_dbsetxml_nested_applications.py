#!/usr/bin/env python3
"""Capture nested same-OID Applications from an owned original C-Gate.

Synthetic projects use a loopback-only CNI that is never opened. The complete
tagged request/reply transcript is retained for exact Rust compatibility tests.
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
SHAPES = (("XNG1", "Group", (56,)),
          ("XNG2", "Group", (56, 57)),
          ("XNN2", "NetVar", (56, 57)))


def app(kind: str, address: int, *, changed: bool = False) -> str:
    leaf_oid = f"44444444-4444-4444-8444-0000000000{address}"
    tag = f"{'Changed' if changed else 'App'}{address}"
    child = (f"<{kind}><OID>{leaf_oid}</OID><TagName>{kind}{address}</TagName>"
             f"<Address>1</Address></{kind}>")
    return (f"<Application><OID>{SHARED}</OID><TagName>{tag}</TagName>"
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
            next_tag = 700

            def call(command: str, document: str | None = None) -> dict:
                nonlocal next_tag
                row = previous.exchange(stream, next_tag, command, document)
                cases.append(row)
                print(next_tag, previous.status(row), command, flush=True)
                next_tag += 1
                return row

            for project, kind, addresses in SHAPES:
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
                           + "".join(app(kind, address) for address in addresses) + "</Network>")
                submit_tag = next_tag
                assert previous.status(call(f"DBSETXML //{project}/254", network)) == 301
                call(f"DBGETXML //{project}/254")
                for address in addresses:
                    call(f"DBGETXML //{project}/254/{address}")
                    call(f"DBGETXML //{project}/254/{address}/1")
                call(f"DBGETXML !{SHARED}")
                call(f"PROJECT SAVE {project}")
                call(f"PROJECT CLOSE {project}")
                call(f"PROJECT LOAD {project}")
                call(f"PROJECT USE {project}")
                call(f"DBGETXML //{project}/254")
                call(f"DBGETXML !{SHARED}")
                if len(addresses) == 2:
                    first = addresses[0]
                    assert previous.status(call(f"DBSETXML //{project}/254/{first}",
                                                app(kind, first, changed=True))) == 301
                    call(f"DBGETXML //{project}/254")
                    call(f"DBGETXML !{SHARED}")
                    call(f"DBGETXML //{project}/254/{addresses[1]}/1")
                    call(f"PROJECT SAVE {project}")
                    call(f"PROJECT CLOSE {project}")
                    call(f"PROJECT LOAD {project}")
                    call(f"PROJECT USE {project}")
                    call(f"DBGETXML //{project}/254")
                shapes.append({"project": project, "kind": kind, "addresses": addresses,
                               "network_oid": network_oid, "interface_oid": interface_oid,
                               "submit_tag": submit_tag})

    report = service.report
    data = {
        "schema": "native-cgate-dbsetxml-nested-applications-v1",
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
