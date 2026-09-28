#!/usr/bin/env python3
"""Capture nonempty Level TagsDLT replacement against owned C-Gate 3.4."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import cgate_dbsetxml_duplicate_applications as exchange_helper
import cgate_dbsetxml_nested_levels as levels
import local_cgate
from local_cgate import JAR_SHA256, LocalCGate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = []
    with LocalCGate(args.vendor, java=args.java) as service:
        with socket.create_connection(("127.0.0.1", service.port), timeout=5) as sock:
            sock.settimeout(10)
            stream = sock.makefile("rwb", buffering=0)
            greeting = stream.readline().decode("utf-8")
            next_tag = 1000

            def call(command: str, document: str | None = None) -> dict:
                nonlocal next_tag
                row = exchange_helper.exchange(stream, next_tag, command, document)
                cases.append(row)
                print(next_tag, exchange_helper.status(row), command, flush=True)
                next_tag += 1
                return row

            project = "XLDLT"
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
                       + levels.app("Group", 56) + "</Network>")
            assert exchange_helper.status(call(f"DBSETXML //{project}/254", network)) == 301
            call(f"PROJECT SAVE {project}")
            call(f"PROJECT CLOSE {project}")
            call(f"PROJECT LOAD {project}")
            call(f"PROJECT USE {project}")
            level_path = f"//{project}/254/56/1/2"
            level = exchange_helper.xml(call(f"DBGETXML {level_path}"))
            assert level.count("<TagsDLT/>") == 1
            nonempty = ("<TagsDLT><TagDLT><LanguageID>1</LanguageID>"
                        "<FlavourID>1</FlavourID><TagType>TEXT</TagType>"
                        "<TagValue>Owned label</TagValue></TagDLT></TagsDLT>")
            changed = level.replace("<TagsDLT/>", nonempty)
            call(f"DBSETXML {level_path}", changed)
            changed_reply = call(f"DBGETXML {level_path}")
            changed_xml = exchange_helper.xml(changed_reply)
            generated_oid = ET.fromstring(changed_xml).findtext("TagsDLT/TagDLT/OID")
            assert generated_oid
            call(f"DBGETXML //{project}/254")
            explicit = changed_xml.replace("Owned label", "Owned edited label")
            call(f"DBSETXML {level_path}", explicit)
            call(f"DBGETXML {level_path}")
            call(f"DBGETXML //{project}/254")
            call(f"PROJECT SAVE {project}")
            call(f"PROJECT CLOSE {project}")
            call(f"PROJECT LOAD {project}")
            call(f"PROJECT USE {project}")
            call(f"DBGETXML {level_path}")
            network_after_load = exchange_helper.xml(call(f"DBGETXML //{project}/254"))
            call(f"DBSETXML //{project}/254", network_after_load)
            call(f"DBGETXML //{project}/254")

    report = service.report
    data = {
        "schema": "native-cgate-dbsetxml-level-dlt-v1",
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
        "source_shape_sha256": hashlib.sha256(Path(levels.__file__).read_bytes()).hexdigest(),
        "exchange_helper_sha256": hashlib.sha256(Path(exchange_helper.__file__).read_bytes()).hexdigest(),
        "service_harness_sha256": hashlib.sha256(Path(local_cgate.__file__).read_bytes()).hexdigest(),
        "greeting": greeting,
        "network_oid": network_oid,
        "interface_oid": interface_oid,
        "generated_tag_oid": generated_oid,
        "cases": cases,
    }
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
