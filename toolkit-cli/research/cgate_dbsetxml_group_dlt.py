#!/usr/bin/env python3
"""Capture native complete-Group DLT label replacement and lifecycle."""

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
            next_tag = 1100

            def call(command: str, document: str | None = None) -> dict:
                nonlocal next_tag
                row = exchange_helper.exchange(stream, next_tag, command, document)
                cases.append(row)
                print(next_tag, exchange_helper.status(row), command, flush=True)
                next_tag += 1
                return row

            project = "XGDLT"
            group_path = f"//{project}/254/56/1"
            network_path = f"//{project}/254"
            call(f"PROJECT NEW {project}")
            call(f"PROJECT USE {project}")
            call("DBCREATENET 254 Local Cni 127.0.0.1:1")
            baseline = ET.fromstring(exchange_helper.xml(call(f"DBGETXML {network_path}")))
            network_oid = baseline.findtext("OID")
            interface_oid = baseline.findtext("Interface/OID")
            assert network_oid and interface_oid
            network = (f"<Network><OID>{network_oid}</OID><TagName>Local</TagName>"
                       "<Address>254</Address><NetworkNumber>254</NetworkNumber>"
                       f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
                       "<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>"
                       + levels.app("Group", 56) + "</Network>")
            assert exchange_helper.status(call(f"DBSETXML {network_path}", network)) == 301
            for command in (f"PROJECT SAVE {project}", f"PROJECT CLOSE {project}",
                            f"PROJECT LOAD {project}", f"PROJECT USE {project}"):
                call(command)
            group_xml = exchange_helper.xml(call(f"DBGETXML {group_path}"))
            assert group_xml.count("<TagsDLT/>") == 1  # Level only.
            label = ("<TagsDLT><TagDLT><LanguageID>1</LanguageID>"
                     "<FlavourID>1</FlavourID><TagType>TEXT</TagType>"
                     "<TagValue>Owned group label</TagValue></TagDLT></TagsDLT>")
            call(f"DBSETXML {group_path}", group_xml.replace("</Group>", label + "</Group>"))
            added = exchange_helper.xml(call(f"DBGETXML {group_path}"))
            call(f"DBGETXML {network_path}")
            first_tag_oid = ET.fromstring(added).findtext("TagsDLT/TagDLT/OID")
            assert first_tag_oid
            edited = added.replace("Owned group label", "Owned edited group label")
            call(f"DBSETXML {group_path}", edited)
            edited = exchange_helper.xml(call(f"DBGETXML {group_path}"))
            for command in (f"PROJECT SAVE {project}", f"PROJECT CLOSE {project}",
                            f"PROJECT LOAD {project}", f"PROJECT USE {project}"):
                call(command)
            call(f"DBGETXML {group_path}")
            network_after_load = exchange_helper.xml(call(f"DBGETXML {network_path}"))
            call(f"DBSETXML {network_path}", network_after_load)
            call(f"DBGETXML {network_path}")
            second = ("<TagDLT><LanguageID>1</LanguageID><FlavourID>2</FlavourID>"
                      "<TagType>TEXT</TagType><TagValue>Second flavour</TagValue></TagDLT>")
            two_variants = edited.replace("</TagsDLT>", second + "</TagsDLT>")
            call(f"DBSETXML {group_path}", two_variants)
            two_read = exchange_helper.xml(call(f"DBGETXML {group_path}"))
            second_tag_oid = ET.fromstring(two_read).findtext("TagsDLT/TagDLT[2]/OID")
            for command in (f"PROJECT SAVE {project}", f"PROJECT CLOSE {project}",
                            f"PROJECT LOAD {project}", f"PROJECT USE {project}"):
                call(command)
            call(f"DBGETXML {group_path}")
            call(f"DBGETXML {network_path}")
            call(f"DBSETXML {group_path}", two_read.replace(
                two_read.split("<TagsDLT>", 1)[1].split("</TagsDLT>", 1)[0], ""))
            call(f"DBGETXML {group_path}")
            call(f"DBGETXML {network_path}")

    report = service.report
    data = {
        "schema": "native-cgate-dbsetxml-group-dlt-v1",
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
        "first_tag_oid": first_tag_oid,
        "second_tag_oid": second_tag_oid,
        "cases": cases,
    }
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
