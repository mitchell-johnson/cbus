#!/usr/bin/env python3
"""Capture two Application records sharing an OID in owned loopback C-Gate.

Use the pinned build-2001 JAR and an explicit Java 11 executable only.
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

            call(300, "PROJECT NEW XAPP")
            call(301, "PROJECT USE XAPP")
            call(302, "DBCREATENET 254 Local Cni 127.0.0.1:1")
            baseline = ET.fromstring(xml(call(303, "DBGETXML //XAPP/254")))
            network_oid = baseline.findtext("OID")
            interface_oid = baseline.findtext("Interface/OID")
            assert network_oid and interface_oid
            shared = "33333333-3333-4333-8333-333333333333"
            network = (f"<Network><OID>{network_oid}</OID><TagName>Local</TagName>"
                       "<Address>254</Address><NetworkNumber>254</NetworkNumber>"
                       f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
                       "<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>")
            first = (f"<Application><OID>{shared}</OID><TagName>First</TagName>"
                     "<Address>56</Address></Application>")
            second = (f"<Application><OID>{shared}</OID><TagName>Second</TagName>"
                      "<Address>57</Address></Application>")
            call(304, "DBSETXML //XAPP/254", network + first + second + "</Network>")
            call(305, "DBGETXML //XAPP/254")
            call(306, "DBGETXML //XAPP/254/56")
            call(307, "DBGETXML //XAPP/254/57")
            call(308, f"DBGETXML !{shared}")
            call(309, f"DBGET !{shared}/Address")
            call(310, "PROJECT SAVE XAPP")
            call(311, "PROJECT CLOSE XAPP")
            call(312, "PROJECT LOAD XAPP")
            call(313, "PROJECT USE XAPP")
            call(314, "DBGETXML //XAPP/254")
            call(315, "DBGETXML //XAPP/254/56")
            call(316, "DBGETXML //XAPP/254/57")
            call(317, f"DBGETXML !{shared}")

            # Addressed complete replacement should change only App 57.
            changed = second.replace("<TagName>Second</TagName>", "<TagName>Changed</TagName>")
            call(318, "DBSETXML //XAPP/254/57", changed)
            call(319, "DBGETXML //XAPP/254")
            call(320, "DBGETXML //XAPP/254/56")
            call(321, "DBGETXML //XAPP/254/57")
            call(322, f"DBGETXML !{shared}")
            call(323, "PROJECT SAVE XAPP")
            call(324, "PROJECT CLOSE XAPP")
            call(325, "PROJECT LOAD XAPP")
            call(326, "PROJECT USE XAPP")
            call(327, "DBGETXML //XAPP/254")

            # Native OID mutation target and its effect on each path.
            call(328, f"DBSET !{shared}/TagName ByOID")
            call(329, "DBGETXML //XAPP/254")
            call(330, "DBGETXML //XAPP/254/56")
            call(331, "DBGETXML //XAPP/254/57")
            call(332, f"DBGETXML !{shared}")
            call(333, f"DBGET !{shared}/TagName")
            call(334, f"DBSETXML !{shared}", changed.replace("Changed", "ViaXML"))
            call(335, "DBGETXML //XAPP/254")
            call(336, "DBGETXML //XAPP/254/56")
            call(337, "DBGETXML //XAPP/254/57")
            call(338, f"DBGETXML !{shared}")

    report = service.report
    data = {
        "schema": "native-cgate-dbsetxml-duplicate-applications-v1",
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
