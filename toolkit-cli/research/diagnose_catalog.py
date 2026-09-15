#!/usr/bin/env python3
"""Test /db LOAD alternatives for failed PP NEW catalogue cases without changing them."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.programming import Programmer
from verify_catalog import digest, error_details, now

PROJECT = "CATDIAG"
NETWORK = "//CATDIAG/254"
UNIT = NETWORK + "/p/240"
MARKER = "cbus-toolkit catalog diagnostics disposable v1"


class DiagnosticClient:
    def __init__(self, transport):
        self.transport = transport
        self.commands = 0

    def command(self, command):
        words = command.split()
        prefix = " ".join(words[:2]).upper()
        allowed = False
        if prefix in ("PROJECT NEW", "PROJECT USE"):
            allowed = words[2:] == [PROJECT]
        elif words[0] in ("DBGET", "DBSET"):
            allowed = len(words) >= 2 and (words[1] == "//CATDIAG/Project/Description" or words[1] == UNIT or words[1].startswith(UNIT + "/"))
        elif command in ("DBCREATENET 254 CATDIAG_Offline Cni 127.0.0.1:1", "NET LOAD DB CATDIAG", "GET //CATDIAG/254 state", "DBADDSAFE //CATDIAG/254 Unit 240 CATDIAG_U240", "DBDELETE " + UNIT):
            allowed = True
        elif prefix == "PP LOCK":
            allowed = len(words) == 4 and words[2].startswith("catdiag_") and words[3] == NETWORK
        elif prefix == "PP START":
            allowed = len(words) == 4 and all(word.startswith("catdiag_") for word in words[2:])
        elif prefix == "PP LOAD":
            allowed = len(words) == 4 and words[2].startswith("catdiag_") and words[3] == "/db/" + UNIT[1:]
        elif prefix in ("PP END", "PP UNLOCK", "PP GET", "PP SET", "PP INFO", "PP RESET_TO_DEFAULTS", "PP LOAD_FROM_FILE", "PP SET_RAW_DATA"):
            allowed = len(words) >= 3 and words[2].startswith("catdiag_")
        if not allowed:
            raise RuntimeError("Offline diagnostic command guard rejected an operation")
        self.commands += 1
        return self.transport.command(command)


def prepare(client):
    try:
        client.command("PROJECT NEW CATDIAG")
        client.command("DBSET //CATDIAG/Project/Description " + MARKER)
    except CGateError as error:
        if not any(text in str(error).lower() for text in ("already exists", "project exists")):
            raise
        reply = client.command("DBGET //CATDIAG/Project/Description")
        if not any(MARKER in line for line in reply.lines):
            raise RuntimeError("Refusing to adopt an unowned CATDIAG project") from None
    client.command("PROJECT USE CATDIAG")
    try:
        client.command("DBCREATENET 254 CATDIAG_Offline Cni 127.0.0.1:1")
    except CGateError as error:
        if not any(text in str(error).lower() for text in ("already exists", "network exists", "duplicate")):
            raise
    client.command("NET LOAD DB CATDIAG")
    state = client.command("GET //CATDIAG/254 state")
    if not any(re.search(r"state\s*=\s*(?:new|closed)\b", line, re.I) for line in state.lines):
        raise RuntimeError("CATDIAG network is not new/closed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=20023)
    parser.add_argument("--source", type=Path, default=Path(__file__).parent / "runtime/catalog-acceptance.json")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "runtime/catalog-diagnostics.json")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Diagnostic output exists; choose another output to preserve evidence")
    source = json.loads(args.source.read_text())
    catalog_path = Path(source["catalog"]["path"])
    catalog_bytes = catalog_path.read_bytes()
    if hashlib.sha256(catalog_bytes).hexdigest() != source["catalog"]["sha256"]:
        raise ValueError("Catalogue has changed since the acceptance run")
    units = ET.fromstring(catalog_bytes).findall(".//Unit")
    excluded = [case for case in source["cases"] if case.get("result", {}).get("status") not in (None, "pass")]
    report = {"format": "cbus-catalog-diagnostics-v1", "started_at": now(),
              "scope": "Alternative offline database LOAD/defaults/import workflow; original PP NEW failures stay unchanged",
              "source_report_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
              "catalog_sha256": source["catalog"]["sha256"], "cases": [], "load_from_file_probes": []}
    with CGateClient(args.host, args.port, timeout=30) as transport:
        report["greeting"] = transport.greeting
        report["host"], report["port"] = args.host, args.port
        report["python_version"] = sys.version
        report["source_sha256"] = {name: hashlib.sha256(Path(__file__).resolve().parents[1].joinpath("src/cbus_toolkit", name).read_bytes()).hexdigest() for name in ("programming.py", "cgate.py")}
        client = DiagnosticClient(transport)
        prepare(client)
        programmer = Programmer(client)
        for case in excluded:
            metadata = units[case["sources"][0]["unit_index"]]
            item = {"id": case["id"], "unit_type": case["unit_type"], "firmware": case["firmware"],
                    "catalog_number": case["catalog_number"], "spec_filename": case["sources"][0]["spec_filename"],
                    "original_status": case["result"]["status"],
                    "catalog_description": metadata.findtext("Description", ""),
                    "addressable": metadata.findtext("IsAddressable", "").lower() == "true",
                    "hidden_in_catalog": "HideInCatalog=true" in metadata.findtext("UnitTitle", ""),
                    "started_at": now(), "stage": "create_database_unit"}
            created = False
            try:
                client.command("DBADDSAFE //CATDIAG/254 Unit 240 CATDIAG_U240")
                created = True
                for field, value in (("UnitType", case["unit_type"]), ("FirmwareVersion", case["firmware"]), ("CatalogNumber", case["catalog_number"])):
                    client.command(f"DBSET {UNIT}/{field} {value}")
                item["stage"] = "load_database"
                with programmer.load(NETWORK, "/db/" + UNIT[1:], name="catdiag_" + case["id"][:12]) as session:
                    item["stage"] = "reset_defaults"
                    session.reset_defaults()
                    item["stage"] = "export"
                    snapshot = session.export_parameters()
                    item["parameter_count"] = len(snapshot["parameters"])
                    item["before_sha256"] = digest(snapshot["parameters"])
                    item["stage"] = "reset_import_compare"
                    session.reset_defaults()
                    session.import_parameters(snapshot)
                    actual = session.values()
                    item["after_sha256"] = digest(actual)
                    item["status"] = "alternative_roundtrip_pass" if actual and actual == snapshot["parameters"] else "alternative_roundtrip_mismatch"
            except Exception as error:
                item["status"] = "alternative_failed"
                item["error"] = error_details(error)
            finally:
                if created:
                    client.command("DBDELETE " + UNIT)
                item["finished_at"] = now()
            report["cases"].append(item)
            print(json.dumps({"unit_type": item["unit_type"], "firmware": item["firmware"], "catalog_number": item["catalog_number"], "status": item["status"], "parameter_count": item.get("parameter_count")}), flush=True)
        for index, filename in enumerate(sorted({item["spec_filename"] for item in report["cases"] if item["spec_filename"]})):
            item = {"filename": filename, "stage": "load_from_file"}
            try:
                with programmer.session(NETWORK, name="catdiag_file_" + str(index)) as session:
                    item["load_status"] = session.load_from_file(filename).status
                    item["stage"] = "get_parameters"
                    item["parameter_count"] = len(session.values())
                    item["status"] = "loaded_parameters" if item["parameter_count"] else "empty_parameters"
            except Exception as error:
                item["status"] = "failed"
                item["error"] = error_details(error)
            report["load_from_file_probes"].append(item)
        report["commands"] = client.commands
    report["finished_at"] = now()
    report["summary"] = {"original_exclusions": len(report["cases"]), "alternative_status_counts": dict(Counter(item["status"] for item in report["cases"])),
                         "successful_alternative_parameter_comparisons": sum(item.get("parameter_count", 0) for item in report["cases"] if item["status"] == "alternative_roundtrip_pass"),
                         "non_addressable_entries": sum(not item["addressable"] for item in report["cases"]),
                         "hidden_entries": sum(item["hidden_in_catalog"] for item in report["cases"])}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["summary"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
