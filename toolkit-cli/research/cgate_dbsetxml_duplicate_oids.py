#!/usr/bin/env python3
"""Capture duplicate-OID DBSETXML behavior in one owned, loopback C-Gate.

Use only the pinned build 2001 JAR and an explicit Java 11 executable. All
project names and OIDs are synthetic; LocalCGate owns its disposable directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import local_cgate
from local_cgate import JAR_SHA256, LocalCGate


def exchange(stream, tag: int, command: str, document: str | None = None) -> dict:
    request = f"[{tag}] {command}"
    if document is not None:
        request += f" << END{tag}\r\n{document}\r\nEND{tag}"
    request += "\r\n"
    stream.write(request.encode("utf-8"))
    lines = []
    for _ in range(128):
        line = stream.readline().decode("utf-8")
        if not line:
            raise RuntimeError(f"EOF before response {tag}")
        lines.append(line)
        if re.match(rf"^\[{tag}\] \d{{3}} ", line):
            return {"tag": tag, "command": command, "request": request, "response_lines": lines}
    raise RuntimeError(f"Unterminated response {tag}")


def xml(row: dict) -> str:
    prefix = f"[{row['tag']}] 347-"
    return "".join(line[len(prefix):] for line in row["response_lines"] if line.startswith(prefix)).strip()


def status(row: dict) -> int:
    return int(row["response_lines"][-1].split()[1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    with LocalCGate(args.vendor, java=args.java) as service:
        with socket.create_connection(("127.0.0.1", service.port), timeout=5) as sock:
            sock.settimeout(10)
            stream = sock.makefile("rwb", buffering=0)
            greeting = stream.readline().decode("utf-8")

            def call(tag: int, command: str, document: str | None = None) -> dict:
                row = exchange(stream, tag, command, document)
                rows.append(row)
                print(tag, status(row), command)
                return row

            call(200, "PROJECT NEW XDUP")
            call(201, "PROJECT USE XDUP")
            call(202, "DBCREATENET 254 Local Cni 127.0.0.1:1")
            baseline = ET.fromstring(xml(call(203, "DBGETXML //XDUP/254")))
            network_oid = baseline.findtext("OID")
            interface_oid = baseline.findtext("Interface/OID")
            assert network_oid and interface_oid
            shared = "11111111-1111-4111-8111-111111111111"
            other = "22222222-2222-4222-8222-222222222222"
            network = (f"<Network><OID>{network_oid}</OID><TagName>Local</TagName>"
                       "<Address>254</Address><NetworkNumber>254</NetworkNumber>"
                       f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
                       "<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>")
            app = (f"<Application><OID>{shared}</OID><TagName>Lighting</TagName>"
                   "<Address>56</Address></Application>")
            unit20 = (f"<Unit><OID>{shared}</OID><TagName>First</TagName><Address>20</Address>"
                      "<UnitType>KEYE1</UnitType><UnitName>First room</UnitName>"
                      "<FirmwareVersion>1.2.67</FirmwareVersion>"
                      '<PP Name="UnitAddress" Value="20"/></Unit>')
            unit21 = (f"<Unit><OID>{shared}</OID><TagName>Second</TagName><Address>21</Address>"
                      "<UnitType>KEYE1</UnitType><UnitName>Second room</UnitName>"
                      "<FirmwareVersion>1.2.68</FirmwareVersion>"
                      '<PP Name="UnitAddress" Value="21"/></Unit>')
            # Cross-kind duplicate, including a Unit template/PP field.
            call(204, "DBSETXML //XDUP/254", network + app + unit20 + "</Network>")
            call(205, "DBGETXML //XDUP/254")
            call(206, "DBGETXML //XDUP/254/56")
            call(207, "DBGETXML //XDUP/254/p/20")
            call(208, f"DBGETXML !{shared}")
            call(209, f"DBGET !{shared}/Address")
            call(210, "PROJECT SAVE XDUP")
            call(211, "PROJECT CLOSE XDUP")
            call(212, "PROJECT LOAD XDUP")
            call(213, "PROJECT USE XDUP")
            call(214, "DBGETXML //XDUP/254")
            call(215, "DBGETXML //XDUP/254/56")
            call(216, "DBGETXML //XDUP/254/p/20")

            # Two Units with one OID but independent scalar and PP values.
            call(217, "DBSETXML //XDUP/254", network + app.replace(shared, other) + unit20 + unit21 + "</Network>")
            call(218, "DBGETXML //XDUP/254")
            call(219, "DBGETXML //XDUP/254/p/20")
            call(220, "DBGETXML //XDUP/254/p/21")
            call(221, f"DBGETXML !{shared}")
            call(222, f"DBGET !{shared}/Address")
            call(223, "PROJECT SAVE XDUP")
            call(224, "PROJECT CLOSE XDUP")
            call(225, "PROJECT LOAD XDUP")
            call(226, "PROJECT USE XDUP")
            call(227, "DBGETXML //XDUP/254")
            call(228, "DBGETXML //XDUP/254/p/20")
            call(229, "DBGETXML //XDUP/254/p/21")

            # Path-addressed replacement must affect only its selected Unit.
            replaced21 = unit21.replace("Second room", "Changed room").replace("1.2.68", "1.2.69")
            call(230, "DBSETXML //XDUP/254/p/21", replaced21)
            call(231, "DBGETXML //XDUP/254/p/20")
            call(232, "DBGETXML //XDUP/254/p/21")
            call(233, "DBGETXML //XDUP/254")
            call(234, "PROJECT SAVE XDUP")
            call(235, "PROJECT CLOSE XDUP")
            call(236, "PROJECT LOAD XDUP")
            call(237, "PROJECT USE XDUP")
            call(238, "DBGETXML //XDUP/254")
    report = service.report
    data = {
        "schema": "native-cgate-dbsetxml-duplicate-oids-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "oracle": {"jar_sha256": JAR_SHA256, "java_sha256": hashlib.sha256(args.java.read_bytes()).hexdigest(),
                   "version": "3.4.0 build 2001", "owned_loopback_listeners": report["listener_ownership_verified"],
                   "listeners": report["listeners"], "cleanup_complete": report["cleanup_complete"],
                   "process_exit_confirmed": report["process_exit_confirmed"],
                   "work_removed": report["work_removed"], "physical_endpoint": False},
        "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "service_harness_sha256": hashlib.sha256(Path(local_cgate.__file__).read_bytes()).hexdigest(),
        "greeting": greeting,
        "network_oid": network_oid,
        "interface_oid": interface_oid,
        "cases": rows,
    }
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
