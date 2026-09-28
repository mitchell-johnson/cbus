#!/usr/bin/env python3
"""Capture bounded DBSETXML replacement edges from an owned C-Gate 3.4 service.

Run only with an explicitly selected, hash-pinned original install and Java 11.
LocalCGate creates a disposable project and verifies its six loopback listeners.
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
    if document is None:
        request = f"[{tag}] {command}\r\n"
    else:
        request = f"[{tag}] {command} << END{tag}\r\n{document}\r\nEND{tag}\r\n"
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
                print(tag, status(row), command, xml(row)[:220] if command.startswith("DBGETXML") else row["response_lines"][-1].strip())
                return row

            call(100, "PROJECT NEW XEDGE")
            call(101, "PROJECT USE XEDGE")
            call(102, "DBCREATENET 254 Local Cni 127.0.0.1:1")
            baseline = ET.fromstring(xml(call(103, "DBGETXML //XEDGE/254")))
            network_oid = baseline.findtext("OID")
            interface_oid = baseline.findtext("Interface/OID")
            assert network_oid and interface_oid
            network = (f"<Network><OID>{network_oid}</OID><TagName>Local</TagName>"
                       "<Address>254</Address><NetworkNumber>254</NetworkNumber>"
                       f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
                       "<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>")
            unit = ("<Unit><OID>11111111-1111-4111-8111-111111111111</OID>"
                    "<TagName>Bedroom</TagName><Address>20</Address><UnitType>KEYE1</UnitType>"
                    "<UnitName>Room</UnitName><FirmwareVersion>1.2.67</FirmwareVersion>"
                    "<CatalogNumber>5031N</CatalogNumber><SerialNumber>123.4</SerialNumber>"
                    '<PP Name="UnitAddress" Value="20"/></Unit>')
            app = ("<Application><OID>22222222-2222-4222-8222-222222222222</OID>"
                   "<TagName>Lighting</TagName><Address>56</Address></Application>")
            base = network + app + unit + "</Network>"
            call(104, "DBSETXML //XEDGE/254", base)
            call(105, "DBGETXML //XEDGE/254")
            call(106, "DBGETXML //XEDGE/254/p/20")

            # Comments and processing instructions at three mapper levels.
            decorated = (network.replace("<Network>", '<Network xmlns:x="urn:edge">')
                         .replace("</Interface>", "<!--interface-comment--><?edge interface?></Interface>")
                         + app.replace("</Application>", "<!--application-comment--><?edge application?></Application>")
                         + unit.replace("</Unit>", "<!--unit-comment--><?edge unit?></Unit>")
                         + "<!--network-comment--><?edge network?></Network>")
            call(107, "DBSETXML //XEDGE/254", decorated)
            call(108, "DBGETXML //XEDGE/254")
            call(109, "DBGETXML //XEDGE/254/p/20")
            call(110, "DBGETXML //XEDGE/254/56")

            # Unknown namespaced metadata on each typed container independently.
            namespaced = (network.replace("<Network>", '<Network xmlns:x="urn:edge" x:flag="network">')
                          .replace("</Interface>", '<x:Diagnostic>interface</x:Diagnostic></Interface>')
                          + app.replace("<Application>", '<Application x:flag="application">')
                          .replace("</Application>", '<x:Diagnostic>application</x:Diagnostic></Application>')
                          + unit + '<x:Diagnostic>network</x:Diagnostic></Network>')
            call(111, "DBSETXML //XEDGE/254", namespaced)
            call(112, "DBGETXML //XEDGE/254")
            call(113, "DBGETXML //XEDGE/254/56")

            direct = (unit.replace("<Unit>", '<Unit xmlns:x="urn:edge">')
                      .replace("</Unit>", "<!--direct-comment--><?edge direct?></Unit>"))
            call(114, "DBSETXML //XEDGE/254/p/20", direct)
            call(115, "DBGETXML //XEDGE/254/p/20")
            nested = (unit.replace("<Unit>", '<Unit xmlns:x="urn:edge">')
                      .replace("</Unit>", "<Description><x:Nested>opaque</x:Nested></Description></Unit>"))
            call(116, "DBSETXML //XEDGE/254/p/20", nested)
            call(117, "DBGETXML //XEDGE/254/p/20")

            # A successful replacement removes omitted optional Unit fields and PP.
            minimal_unit = unit.replace("<CatalogNumber>5031N</CatalogNumber>", "").replace(
                "<SerialNumber>123.4</SerialNumber>", "").replace('<PP Name="UnitAddress" Value="20"/>', "")
            call(118, "DBSETXML //XEDGE/254", network + app + minimal_unit + "</Network>")
            call(119, "DBGETXML //XEDGE/254/p/20")
            call(120, "DBGET //XEDGE/254/p/20/CatalogNumber")
            call(121, "DBGET //XEDGE/254/p/20/SerialNumber")

            # Save, unload, and reload this clean replacement before conflict probes.
            call(122, "PROJECT SAVE XEDGE")
            call(123, "PROJECT CLOSE XEDGE")
            call(124, "PROJECT LOAD XEDGE")
            call(125, "DBGETXML //XEDGE/254")
            call(126, "DBGETXML //XEDGE/254/p/20")

            mixed = (minimal_unit.replace("<Unit>", '<Unit xmlns:x="urn:edge">')
                     .replace("</Unit>", "<Foo>bar</Foo><Description>A<x:Nested/>B</Description></Unit>"))
            call(127, "DBSETXML //XEDGE/254/p/20", mixed)
            call(128, "DBGETXML //XEDGE/254/p/20")

            nested_catalog = minimal_unit.replace(
                "</Unit>", "<CatalogNumber><Opaque keep=\"yes\">VENDOR</Opaque></CatalogNumber></Unit>")
            call(129, "DBSETXML //XEDGE/254/p/20", nested_catalog)
            call(130, "DBGETXML //XEDGE/254/p/20")

            # Failed whole-tree replacements must leave the last accepted graph intact.
            duplicate_oid = app.replace("22222222-2222-4222-8222-222222222222", "11111111-1111-4111-8111-111111111111")
            call(131, "DBSETXML //XEDGE/254", network + duplicate_oid + minimal_unit + "</Network>")
            call(132, "DBGETXML //XEDGE/254")
            duplicate_unit = minimal_unit.replace("<Address>20</Address>", "<Address>21</Address>")
            call(133, "DBSETXML //XEDGE/254", network + app + minimal_unit + duplicate_unit + "</Network>")
            call(134, "DBGETXML //XEDGE/254")
            call(135, "DBSETXML //XEDGE/254", network + app + minimal_unit.replace("<UnitName>Room</UnitName>", "") + "</Network>")
            call(136, "DBGETXML //XEDGE/254")
    report = service.report
    data = {
        "schema": "native-cgate-dbsetxml-replacement-edges-v1",
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
