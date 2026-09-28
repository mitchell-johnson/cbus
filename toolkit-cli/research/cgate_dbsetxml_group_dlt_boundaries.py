#!/usr/bin/env python3
"""Capture bounded complete-Group TagsDLT acceptance from owned C-Gate 3.4."""

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


def tag(language: str = "1", flavour: str = "1", kind: str = "TEXT",
        value: str = "Boundary label", oid: str | None = None) -> str:
    identity = f"<OID>{oid}</OID>" if oid is not None else ""
    return (f"<TagDLT>{identity}<LanguageID>{language}</LanguageID>"
            f"<FlavourID>{flavour}</FlavourID><TagType>{kind}</TagType>"
            f"<TagValue>{value}</TagValue></TagDLT>")


def collection(*rows: str) -> str:
    return f"<TagsDLT>{''.join(rows)}</TagsDLT>"


def shapes(group_oid: str, level_oid: str) -> list[tuple[str, str]]:
    same = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    return [
        ("empty", "<TagsDLT/>"),
        ("language_zero", collection(tag(language="0"))),
        ("language_two", collection(tag(language="2"))),
        ("language_255", collection(tag(language="255"))),
        ("language_256", collection(tag(language="256"))),
        ("language_text", collection(tag(language="English"))),
        ("flavour_zero", collection(tag(flavour="0"))),
        ("flavour_four", collection(tag(flavour="4"))),
        ("flavour_five", collection(tag(flavour="5"))),
        ("flavour_255", collection(tag(flavour="255"))),
        ("flavour_text", collection(tag(flavour="Primary"))),
        ("type_text", collection(tag(kind="TEXT"))),
        ("type_image", collection(tag(kind="IMAGE"))),
        ("type_lowercase", collection(tag(kind="text"))),
        ("type_unknown", collection(tag(kind="UNRECOGNISED"))),
        ("type_empty", collection(tag(kind=""))),
        ("two_flavours", collection(tag(), tag(flavour="2", value="Second"))),
        ("four_flavours", collection(*(tag(flavour=str(i), value=f"Label{i}")
                                        for i in range(1, 5)))),
        ("five_flavours", collection(*(tag(flavour=str(i), value=f"Label{i}")
                                        for i in range(1, 6)))),
        ("duplicate_variant", collection(tag(), tag(value="Duplicate"))),
        ("duplicate_oid", collection(tag(oid=same), tag(flavour="2", oid=same))),
        ("group_oid", collection(tag(oid=group_oid))),
        ("level_oid", collection(tag(oid=level_oid))),
        ("default_namespace", '<TagsDLT xmlns="urn:unprobed"/>'),
        ("collection_attribute", '<TagsDLT unknown="1"/>'),
        ("tag_namespace", collection('<TagDLT xmlns="urn:unprobed"/>')),
        ("field_namespace", collection(tag().replace("<TagType>",
                                                   '<TagType xmlns="urn:unprobed">'))),
        ("tag_attribute", collection(tag().replace("<TagDLT>",
                                                 '<TagDLT unknown="1">'))),
        ("duplicate_collection", "<TagsDLT/><TagsDLT/>"),
        ("sixty_five", collection(*(tag(language=str(i), flavour="1", value=f"Label{i}")
                                   for i in range(65)))),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = []
    with LocalCGate(args.vendor, java=args.java) as service:
        with socket.create_connection(("127.0.0.1", service.port), timeout=5) as sock:
            sock.settimeout(15)
            stream = sock.makefile("rwb", buffering=0)
            greeting = stream.readline().decode("utf-8")
            next_tag = 2200

            def call(command: str, document: str | None = None) -> dict:
                nonlocal next_tag
                row = exchange_helper.exchange(stream, next_tag, command, document)
                print(next_tag, exchange_helper.status(row), command, flush=True)
                next_tag += 1
                return row

            project = "XGDB"
            group_path = f"//{project}/254/56/1"
            network_path = f"//{project}/254"
            setup = [call(f"PROJECT NEW {project}"), call(f"PROJECT USE {project}"),
                     call("DBCREATENET 254 Local Cni 127.0.0.1:1")]
            baseline = ET.fromstring(exchange_helper.xml(call(f"DBGETXML {network_path}")))
            network_oid = baseline.findtext("OID")
            interface_oid = baseline.findtext("Interface/OID")
            assert network_oid and interface_oid
            network = (f"<Network><OID>{network_oid}</OID><TagName>Local</TagName>"
                       "<Address>254</Address><NetworkNumber>254</NetworkNumber>"
                       f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
                       "<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>"
                       + levels.app("Group", 56) + "</Network>")
            setup.append(call(f"DBSETXML {network_path}", network))
            for command in (f"PROJECT SAVE {project}", f"PROJECT CLOSE {project}",
                            f"PROJECT LOAD {project}", f"PROJECT USE {project}"):
                setup.append(call(command))
            group_xml = exchange_helper.xml(call(f"DBGETXML {group_path}"))
            group_root = ET.fromstring(group_xml)
            group_oid = group_root.findtext("OID")
            level_oid = group_root.findtext("Level/OID")
            assert group_oid and level_oid
            assert group_xml.count("<TagsDLT/>") == 1
            for name, tags in shapes(group_oid, level_oid):
                before = call(f"DBGETXML {group_path}")
                replacement = group_xml.replace("</Group>", tags + "</Group>")
                submitted = call(f"DBSETXML {group_path}", replacement)
                after = call(f"DBGETXML {group_path}")
                cases.append({"name": name, "before": before, "set": submitted,
                              "after": after})

    report = service.report
    data = {
        "schema": "native-cgate-dbsetxml-group-dlt-boundaries-v1",
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
        "group_oid": group_oid,
        "level_oid": level_oid,
        "setup": setup,
        "cases": cases,
    }
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
