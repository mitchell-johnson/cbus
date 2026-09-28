#!/usr/bin/env python3
"""Capture native mutations through a shared Unit OID in an owned C-Gate.

The project, OIDs and CNI address are synthetic. No network is opened.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
from xml.etree import ElementTree as ET

import cgate_dbsetxml_duplicate_oids as exchange_helper
import local_cgate
from local_cgate import JAR_SHA256, LocalCGate


PROJECT = "XOIDM"
SHARED = "11111111-1111-4111-8111-111111111111"


def unit(address: int, name: str) -> str:
    return (
        f"<Unit><OID>{SHARED}</OID><TagName>{name}</TagName><Address>{address}</Address>"
        f"<UnitType>KEYE1</UnitType><UnitName>{name} room</UnitName>"
        '<FirmwareVersion>1.2.67</FirmwareVersion>'
        f'<PP Name="UnitAddress" Value="{address}"/></Unit>'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows: list[dict] = []
    cases: list[dict] = []
    tag = 300
    with LocalCGate(args.vendor, java=args.java) as service:
        with socket.create_connection(("127.0.0.1", service.port), timeout=5) as sock:
            sock.settimeout(15)
            stream = sock.makefile("rwb", buffering=0)
            greeting = stream.readline().decode("utf-8")

            def call(command: str, document: str | None = None) -> dict:
                nonlocal tag
                row = exchange_helper.exchange(stream, tag, command, document)
                rows.append(row)
                tag += 1
                return row

            for command in (f"PROJECT NEW {PROJECT}", f"PROJECT USE {PROJECT}",
                            "DBCREATENET 254 Local Cni 127.0.0.1:1"):
                assert exchange_helper.status(call(command)) in (200, 301)
            baseline = ET.fromstring(exchange_helper.xml(call(f"DBGETXML //{PROJECT}/254")))
            network_oid = baseline.findtext("OID")
            interface_oid = baseline.findtext("Interface/OID")
            assert network_oid and interface_oid
            network = (
                f"<Network><OID>{network_oid}</OID><TagName>Local</TagName>"
                "<Address>254</Address><NetworkNumber>254</NetworkNumber>"
                f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
                "<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>"
                + unit(20, "First") + unit(21, "Second") + "</Network>"
            )
            for name, command, document in (
                ("set_safe", f"DBSETSAFE !{SHARED}/UnitName ByOID", None),
                ("set_unsafe", f"DBSET !{SHARED}/UnitName ByOID", None),
                ("set_xml", f"DBSETXML !{SHARED}", unit(21, "Changed")),
                ("copy_safe", f"DBCOPYSAFE !{SHARED} //{PROJECT}/254 22 Copied", None),
                ("delete", f"DBDELETE !{SHARED}", None),
            ):
                reset = call(f"DBSETXML //{PROJECT}/254", network)
                before = [call(f"DBGETXML //{PROJECT}/254/p/{address}")
                          for address in (20, 21)]
                oid_before = call(f"DBGETXML !{SHARED}")
                applied = call(command, document)
                after = [call(f"DBGETXML //{PROJECT}/254/p/{address}")
                         for address in (20, 21, 22)]
                oid_after = call(f"DBGETXML !{SHARED}")
                lifecycle = [call(f"PROJECT {verb} {PROJECT}")
                             for verb in ("SAVE", "CLOSE", "LOAD", "USE")]
                reloaded = [call(f"DBGETXML //{PROJECT}/254/p/{address}")
                            for address in (20, 21, 22)]
                oid_reloaded = call(f"DBGETXML !{SHARED}")
                cases.append({"name": name, "reset": reset, "before": before,
                              "oid_before": oid_before, "applied": applied,
                              "after": after, "oid_after": oid_after,
                              "lifecycle": lifecycle, "reloaded": reloaded,
                              "oid_reloaded": oid_reloaded})
    report = service.report
    payload = {
        "schema": "native-cgate-duplicate-unit-oid-mutations-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "oracle": {
            "jar_sha256": JAR_SHA256,
            "java_sha256": hashlib.sha256(args.java.read_bytes()).hexdigest(),
            "version": "3.4.0 build 2001",
            "owned_loopback_listeners": report["listener_ownership_verified"],
            "listeners": report["listeners"],
            "cleanup_complete": report["cleanup_complete"],
            "process_exit_confirmed": report["process_exit_confirmed"],
            "work_removed": report["work_removed"],
            "physical_endpoint": False,
        },
        "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "exchange_helper_sha256": hashlib.sha256(Path(exchange_helper.__file__).read_bytes()).hexdigest(),
        "service_harness_sha256": hashlib.sha256(Path(local_cgate.__file__).read_bytes()).hexdigest(),
        "greeting": greeting,
        "project": PROJECT,
        "shared_oid": SHARED,
        "network_oid": network_oid,
        "interface_oid": interface_oid,
        "setup": rows[:4],
        "cases": cases,
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(cases), "requests": tag - 300,
                      "cleanup": report["cleanup_complete"]}))


if __name__ == "__main__":
    main()
