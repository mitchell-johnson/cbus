#!/usr/bin/env python3
"""Capture DBSETXML error and conflict classes on owned original C-Gate 3.4.

A saved synthetic Network (one Application, one Unit) is the baseline. Every
probe is followed by a complete Network readback so the fixture records
whether a refused document mutated the tag database. The CNI address
127.0.0.1:1 is never opened; no PCI, CNI, broker or site project is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import cgate_dbsetxml_replacement_edges as edge
import local_cgate
from local_cgate import JAR_SHA256, LocalCGate

PROJECT = "XERR"
UNIT_OID = "11111111-1111-4111-8111-111111111111"
APP_OID = "22222222-2222-4222-8222-222222222222"


def unit(address: int = 20, *, name: str = "Bedroom", oid: str = UNIT_OID, extra: str = "") -> str:
    return (f"<Unit><OID>{oid}</OID><TagName>{name}</TagName><Address>{address}</Address>"
            "<UnitType>KEYE1</UnitType><UnitName>Room</UnitName>"
            f"<FirmwareVersion>1.2.67</FirmwareVersion>{extra}</Unit>")


def application(address: int = 56, *, extra: str = "") -> str:
    return (f"<Application><OID>{APP_OID}</OID><TagName>Lighting</TagName>"
            f"<Address>{address}</Address>{extra}</Application>")


def network(net: str, iface: str, *, address: str = "254", number: str = "254",
            iface_type: str = "Cni", iface_address: str = "127.0.0.1:1", body: str | None = None,
            head: str = "") -> str:
    children = application() + unit() if body is None else body
    return (f"<Network>{head}<OID>{net}</OID><TagName>Local</TagName>"
            f"<Address>{address}</Address><NetworkNumber>{number}</NetworkNumber>"
            f"<Interface><OID>{iface}</OID><InterfaceType>{iface_type}</InterfaceType>"
            f"<InterfaceAddress>{iface_address}</InterfaceAddress></Interface>{children}</Network>")


def cases(net: str, iface: str) -> list[tuple[str, str, str]]:
    """Return (case id, target path, document) for every refused-or-probed class."""
    p = f"//{PROJECT}/254"
    u = f"{p}/p/20"
    a = f"{p}/56"
    return [
        # Malformed documents.
        ("malformed-unclosed-network", p, network(net, iface)[:-len("</Network>")]),
        ("malformed-not-xml", p, "hello"),
        ("malformed-mismatched-tag", u, unit().replace("</Unit>", "</Units>")),
        ("malformed-two-roots", u, unit() + unit()),
        ("malformed-undeclared-prefix", u, unit(extra="<x:Diagnostic>u</x:Diagnostic>")),
        ("empty-document", u, ""),
        # Path/body root mismatches.
        ("root-unit-at-network-path", p, unit()),
        ("root-network-at-unit-path", u, network(net, iface)),
        ("root-application-at-unit-path", u, application()),
        ("root-unit-at-application-path", a, unit()),
        ("root-unknown-element", u, "<Foo><OID>" + UNIT_OID + "</OID></Foo>"),
        ("root-project-at-network-path", p, "<Project><TagName>X</TagName></Project>"),
        # Address mismatches between path and body.
        ("address-unit-body-21-at-20", u, unit(21)),
        ("address-application-body-57-at-56", a, application(57)),
        ("address-network-body-253-at-254", p, network(net, iface, address="253", number="253")),
        ("address-network-number-only-253", p, network(net, iface, number="253")),
        ("address-unit-non-numeric", u, unit().replace("<Address>20</Address>", "<Address>abc</Address>")),
        ("address-unit-out-of-range", u, unit().replace("<Address>20</Address>", "<Address>300</Address>")),
        ("address-unit-missing", u, unit().replace("<Address>20</Address>", "")),
        # Interface rebinding on the (unopened) Network.
        ("interface-address-change", p, network(net, iface, iface_address="127.0.0.1:2")),
        ("interface-type-change", p, network(net, iface, iface_type="Serial", iface_address="COM9")),
        ("interface-oid-change", p, network(net, "44444444-4444-4444-8444-444444444444")),
        ("interface-missing", p, network(net, iface).split("<Interface>")[0]
         + network(net, iface).split("</Interface>")[1]),
        ("network-oid-change", p, network("55555555-5555-4555-8555-555555555555", iface)),
        # Unknown or misplaced elements in typed positions.
        ("unit-inside-application", p, network(net, iface, body=application(extra=unit()))),
        ("interface-inside-unit", u, unit(extra="<Interface><InterfaceType>Cni</InterfaceType></Interface>")),
        ("application-inside-unit", u, unit(extra=application())),
        ("unknown-network-child", p, network(net, iface, body=application() + unit() + "<Widget/>")),
        ("duplicate-unit-tagname", u, unit(extra="<TagName>Second</TagName>")),
        ("duplicate-unit-address", u, unit(extra="<Address>20</Address>")),
        ("root-text-content", u, unit().replace("</Unit>", "stray</Unit>")),
        ("unit-oid-malformed", u, unit(oid="not-a-uuid")),
        ("unit-oid-missing", u, unit().replace(f"<OID>{UNIT_OID}</OID>", "")),
        ("unit-tagname-missing", u, unit().replace("<TagName>Bedroom</TagName>", "")),
        ("unit-unittype-missing", u, unit().replace("<UnitType>KEYE1</UnitType>", "")),
        ("unit-pp-missing-value", u, unit(extra='<PP Name="UnitAddress"/>')),
        ("unit-pp-unknown-name", u, unit(extra='<PP Name="NoSuchParameter" Value="1"/>')),
        ("tagname-32", u, unit(name="T" * 32)),
        ("oversize-tagname-33", u, unit(name="T" * 33)),
        ("oversize-tagname-4096", u, unit(name="T" * 4096)),
        # Targets that do not name an existing object.
        ("target-missing-unit", f"{p}/p/99", unit(99)),
        ("target-missing-network", f"//{PROJECT}/253", network(net, iface, address="253", number="253")),
        ("target-missing-project", "//NOPROJ/254", network(net, iface)),
        ("target-oid-unit", f"!{UNIT_OID}", unit()),
    ]


def digest(document: str) -> str:
    return hashlib.sha256(document.encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows: list[dict] = []
    probes: list[dict] = []
    with LocalCGate(args.vendor, java=args.java) as service:
        def connect():
            sock = socket.create_connection(("127.0.0.1", service.port), timeout=5)
            sock.settimeout(30)
            stream = sock.makefile("rwb", buffering=0)
            return sock, stream, stream.readline().decode("utf-8")

        sock, stream, greeting = connect()
        tag = 100

        def call(command: str, document: str | None = None, case: str | None = None) -> dict:
            nonlocal tag
            row = edge.exchange(stream, tag, command, document)
            if case is not None:
                row["case"] = case
            rows.append(row)
            tag += 1
            print(row["tag"], edge.status(row), case or command, row["response_lines"][-1].strip()[:140])
            return row

        call(f"PROJECT NEW {PROJECT}")
        call(f"PROJECT USE {PROJECT}")
        call("DBCREATENET 254 Local Cni 127.0.0.1:1")
        base = ET.fromstring(edge.xml(call(f"DBGETXML //{PROJECT}/254")))
        net, iface = base.findtext("OID"), base.findtext("Interface/OID")
        assert net and iface
        call(f"DBSETXML //{PROJECT}/254", network(net, iface))
        call(f"PROJECT SAVE {PROJECT}")
        baseline = edge.xml(call(f"DBGETXML //{PROJECT}/254"))
        # A saved-and-reloaded Network gains native load defaults; make that
        # the comparison baseline so every probe starts from the same graph.
        call(f"PROJECT CLOSE {PROJECT}")
        call(f"PROJECT LOAD {PROJECT}")
        call(f"PROJECT USE {PROJECT}")
        reloaded = baseline = edge.xml(call(f"DBGETXML //{PROJECT}/254"))
        for case, target, document in cases(net, iface):
            set_row = call(f"DBSETXML {target}", document, case)
            read_row = call(f"DBGETXML //{PROJECT}/254")
            unchanged = edge.xml(read_row) == baseline
            probes.append({"case": case, "set_tag": set_row["tag"], "readback_tag": read_row["tag"],
                           "status": edge.status(set_row), "network_unchanged": unchanged})
            if not unchanged:
                # Record the mutated target, then discard the unsaved edit:
                # native PROJECT CLOSE/LOAD reverts to the saved baseline.
                if not target.startswith("//NOPROJ"):
                    call(f"DBGETXML {target}", None, case + "#target")
                call(f"PROJECT CLOSE {PROJECT}", None, case + "#restore")
                call(f"PROJECT LOAD {PROJECT}", None, case + "#restore")
                call(f"PROJECT USE {PROJECT}", None, case + "#restore")
                assert edge.xml(call(f"DBGETXML //{PROJECT}/254")) == reloaded
        call(f"DBGETXML //{PROJECT}/254/p/20")
        stream.close()
        sock.close()
        # Size probes run last, each on a fresh connection, because a native
        # reply that never arrives desynchronizes that command stream. Bodies
        # are spread over 1 KiB lines; Rust bounds a here-document at 16 MiB.
        for case, kib, wait in (("document-64kib", 64, 60), ("document-1mib", 1024, 120)):
            sock, stream, _ = connect()
            sock.settimeout(wait)
            document = unit(extra="<!--" + ("c" * 1022 + "\r\n") * kib + "-->")
            started = time.monotonic()
            try:
                row = call(f"DBSETXML //{PROJECT}/254/p/20", document, case)
                row["request"] = f"<{len(document.encode())}-byte here-document, sha256 {digest(document)}>"
                probes.append({"case": case, "set_tag": row["tag"], "status": edge.status(row),
                               "document_bytes": len(document.encode())})
            except TimeoutError:
                rows.append({"tag": tag, "case": case, "request_sha256": digest(document),
                             "timed_out_after_seconds": wait})
                probes.append({"case": case, "set_tag": tag, "status": None, "timed_out": True,
                               "elapsed_seconds": round(time.monotonic() - started),
                               "document_bytes": len(document.encode())})
                tag += 1
            stream.close()
            sock.close()
    report = service.report
    data = {
        "schema": "native-cgate-dbsetxml-errors-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "oracle": {"jar_sha256": JAR_SHA256, "java_sha256": hashlib.sha256(args.java.read_bytes()).hexdigest(),
                   "version": "3.4.0 build 2001", "owned_loopback_listeners": report["listener_ownership_verified"],
                   "listeners": report["listeners"], "cleanup_complete": report["cleanup_complete"],
                   "process_exit_confirmed": report["process_exit_confirmed"],
                   "work_removed": report["work_removed"], "physical_endpoint": False},
        "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "service_harness_sha256": hashlib.sha256(Path(local_cgate.__file__).read_bytes()).hexdigest(),
        "greeting": greeting,
        "network_oid": net,
        "interface_oid": iface,
        "baseline": baseline,
        "probes": probes,
        "cases": rows,
    }
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
