#!/usr/bin/env python3
"""Exercise vendor catalogue defaults through a real, explicitly selected C-Gate.

This checks offline unit schemas and Python programming-session round trips.
It does not test device EEPROM encoding, physical communications, or all Toolkit
features. The default run selects every declared default revision; --all-revisions
selects all revisions. Firmware is each range's minimum, or both endpoints with
--boundaries. Neither mode claims to cover every firmware value in each range.

Example:
  .venv/bin/python research/verify_catalog.py --host 127.0.0.1
  .venv/bin/python research/verify_catalog.py --host 127.0.0.1 --resume
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
from typing import Any
import xml.etree.ElementTree as ET

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.programming import Programmer, ProgrammingError, NativeCommandLimitation

PROJECT = "CATTEST"
NETWORK = "//CATTEST/254"
MARKER = "cbus-toolkit catalog acceptance disposable project v1"
FORMAT = "cbus-catalog-acceptance-v1"
DEFAULT_CATALOG = Path(__file__).parent / "vendor/cgate/app/unitspec/cbusunits.xml"
DEFAULT_OUTPUT = Path(__file__).parent / "runtime/catalog-acceptance.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def load_cases(path: Path, all_revisions: bool = False, boundaries: bool = False) -> tuple[list[dict], dict]:
    data = path.read_bytes()
    if len(data) > 16 * 1024 * 1024 or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("Catalogue exceeds limits or includes unsupported declarations")
    root = ET.fromstring(data)
    if root.tag != "CBusUnits":
        raise ValueError("Expected a CBusUnits catalogue")
    units = root.findall(".//Unit")
    selected: dict[tuple, dict] = {}
    missing_defaults = []
    multiple_defaults = []
    revision_count = 0
    default_count = 0
    for unit_index, unit in enumerate(units):
        catalog = unit.findtext("CatalogNumber", "")
        revisions = unit.findall("./FirmwareRevisions/Revision")
        revision_count += len(revisions)
        defaults = [revision for revision in revisions if revision.findtext("IsDefault", "").lower() == "true"]
        default_count += len(defaults)
        if not defaults:
            missing_defaults.append({"unit_index": unit_index, "catalog_number": catalog, "revision_count": len(revisions)})
        if len(defaults) > 1:
            multiple_defaults.append({"unit_index": unit_index, "catalog_number": catalog, "default_count": len(defaults)})
        for revision_index, revision in enumerate(revisions):
            if not all_revisions and revision not in defaults:
                continue
            record = {child.tag: child.text or "" for child in revision}
            versions = [record.get("MinVersion", "")]
            if boundaries and record.get("MaxVersion") not in versions:
                versions.append(record["MaxVersion"])
            for firmware in versions:
                key = (record.get("UnitType", ""), firmware, catalog)
                source = {"unit_index": unit_index, "revision_index": revision_index,
                          "minimum_version": record.get("MinVersion", ""),
                          "maximum_version": record.get("MaxVersion", ""),
                          "spec_filename": record.get("UnitSpecName", ""),
                          "default": revision in defaults,
                          "revision": record}
                if key not in selected:
                    selected[key] = {"id": digest(key)[:24], "unit_type": key[0], "firmware": firmware,
                                     "catalog_number": catalog, "sources": []}
                selected[key]["sources"].append(source)
    summary = {"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest(),
               "unit_entries": len(units), "revision_entries": revision_count,
               "declared_default_revisions": default_count,
               "unit_entries_without_default": missing_defaults,
               "unit_entries_with_multiple_defaults": multiple_defaults,
               "distinct_selected_cases": len(selected),
               "firmware_selection": "minimum and maximum boundaries" if boundaries else "minimum boundary",
               "revision_selection": "all" if all_revisions else "declared defaults"}
    return list(selected.values()), summary


class OfflineAuditClient:
    """Limit this acceptance runner to offline operations and its own namespace."""
    def __init__(self, client: CGateClient, network: int = 254):
        if not 250 <= network <= 254:
            raise ValueError("Acceptance network must be in reserved range250..254")
        self.network_number = network
        self.network = f"//CATTEST/{network}"
        self.client = client
        self.command_count = 0
        self.last_command = None
        self.last_reply = None
        self.failed_command = None

    def command(self, command: str):
        words = command.split()
        operation = " ".join(words[:2]).upper()
        allowed = False
        if operation in ("PROJECT NEW", "PROJECT USE"):
            allowed = words[2:] == [PROJECT]
        elif words and words[0].upper() in ("DBGET", "DBSET"):
            allowed = len(words) > 1 and words[1] == "//CATTEST/Project/Description"
        elif command == f"DBCREATENET {self.network_number} CATTEST_Offline Cni 127.0.0.1:1":
            allowed = True
        elif command == "NET LOAD DB CATTEST":
            allowed = True
        elif command == f"GET {self.network} state":
            allowed = True
        elif operation in ("PP CATALOG_INFO", "PP PATCH_VERSION"):
            allowed = len(words) == 2
        elif operation == "PP LOCK":
            allowed = len(words) == 4 and words[2].startswith("cat_") and words[3] == self.network
        elif operation == "PP START":
            allowed = len(words) == 4 and all(word.startswith("cat_") for word in words[2:])
        elif operation in ("PP END", "PP UNLOCK", "PP NEW", "PP GET", "PP SET", "PP INFO", "PP SET_RAW_DATA", "PP RESET_TO_DEFAULTS"):
            allowed = len(words) >= 3 and words[2].startswith("cat_")
        if not allowed:
            raise RuntimeError("Offline acceptance command guard rejected an operation")
        self.command_count += 1
        self.last_command = command
        self.last_reply = None
        try:
            self.last_reply = self.client.command(command)
            return self.last_reply
        except Exception:
            self.failed_command = command
            raise


def prepare_project(client: OfflineAuditClient) -> None:
    # Refuse to adopt a coincidentally named project. No network is ever opened.
    try:
        client.command("PROJECT NEW CATTEST")
        client.command("DBSET //CATTEST/Project/Description " + MARKER)
    except CGateError as error:
        if error.response.status != 433 and not any(text in str(error).lower() for text in ("already exists", "project exists")):
            raise
        reply = client.command("DBGET //CATTEST/Project/Description")
        if not any(MARKER in line for line in reply.lines):
            raise RuntimeError("CATTEST already exists without this runner's ownership marker") from None
    client.command("PROJECT USE CATTEST")
    try:
        client.command(f"DBCREATENET {client.network_number} CATTEST_Offline Cni 127.0.0.1:1")
    except CGateError as error:
        if not any(text in str(error).lower() for text in ("already exists", "network exists", "duplicate")):
            raise
    client.command("NET LOAD DB CATTEST")
    state = client.command(f"GET {client.network} state")
    if not any(re.search(r"state\s*=\s*(?:new|closed)\b", line, re.I) for line in state.lines):
        raise RuntimeError("CATTEST network is not new/closed; refusing unit acceptance")


def error_details(error: BaseException) -> dict:
    response = getattr(error, "response", getattr(error, "reply", None))
    details = {"type": type(error).__name__, "message": str(error)}
    if response is not None:
        details["response_status"] = getattr(response, "status", getattr(response, "code", None))
        details["response_lines"] = list(getattr(response, "lines", ()))
    cleanup = getattr(error, "programming_cleanup_errors", ())
    if cleanup:
        details["cleanup_errors"] = [error_details(item) for item in cleanup]
    return details


def run_case(programmer: Programmer, audit: OfflineAuditClient, case: dict) -> dict:
    start = time.monotonic()
    first_command = audit.command_count
    result = {"id": case["id"], "started_at": now(), "status": "in_progress", "stage": "new"}
    audit.failed_command = None
    snapshot = None
    session_name = "cat_" + case["id"][:16]
    try:
        with programmer.session(audit.network, name=session_name) as session:
            try:
                session.new(case["unit_type"], case["firmware"], catalog_number=case["catalog_number"])
                result["stage"] = "export"
                snapshot = session.export_parameters()
                values = snapshot["parameters"]
                result["parameter_count"] = len(values)
                result["before_sha256"] = digest(values)
                if not values:
                    result.update(status="empty_parameters", attribution="unresolved", reason="Native PP GET exported no parameters; not counted as pass")
                    return result
                result["stage"] = "reset"
                session.reset_defaults()
                reset = session.values()
                result["reset_sha256"] = digest(reset)
                result["stage"] = "import"
                session.import_parameters(snapshot)
                result["stage"] = "compare"
                actual = session.values()
                result["after_sha256"] = digest(actual)
                differences = [{"parameter": name, "expected": values.get(name), "actual": actual.get(name),
                                "expected_present": name in values, "actual_present": name in actual}
                               for name in sorted(set(values) | set(actual)) if values.get(name) != actual.get(name) or (name in values) != (name in actual)]
                if differences:
                    result.update(status="roundtrip_mismatch", attribution="unresolved_client_or_vendor_normalization", differences=differences)
                else:
                    result.update(status="pass", attribution="verified_offline_roundtrip")
            except Exception as error:
                # Replay only a rejected, complete native reply within this
                # disposable memory session. Never retry ambiguous transport
                # failures. This separates native rejections from Python errors.
                failed_command = audit.failed_command
                result["error"] = error_details(error)
                result["failed_command"] = failed_command
                if not failed_command:
                    result["last_completed_command"] = audit.last_command
                if isinstance(error, CGateError) and audit.client.connected and failed_command:
                    try:
                        raw_reply = audit.command(failed_command)
                        result.update(status="inconsistent_native_result", attribution="unresolved", probe={"status": raw_reply.status, "lines": list(raw_reply.lines)})
                    except CGateError as repeated:
                        result.update(status="vendor_catalog_rejected" if result["stage"] == "new" else "vendor_parameter_rejected",
                                      attribution="native_server_reproduced_rejection_not_proof_of_vendor_defect", probe=error_details(repeated))
                    except Exception as probe_error:
                        result.update(status="transport_or_protocol_failure", attribution="unresolved", probe=error_details(probe_error))
                elif isinstance(error, NativeCommandLimitation):
                    result.update(status="vendor_command_limitation", attribution="vendor_token_grammar_cannot_represent_catalogue_unit_type")
                elif isinstance(error, ProgrammingError):
                    result.update(status="client_validation_or_response_failure", attribution="client_wrapper_or_exported_data_requires_investigation")
                else:
                    result.update(status="transport_or_protocol_failure", attribution="unresolved")
                if snapshot:
                    result["exported_parameters"] = snapshot["parameters"]
    except Exception as error:
        result.setdefault("error", error_details(error))
        if result["status"] in ("pass", "in_progress"):
            result.update(status="session_or_cleanup_failure", attribution="unresolved")
        else:
            result["session_error"] = error_details(error)
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - start, 6)
        result["commands"] = audit.command_count - first_command
        result["finished_at"] = now()
    return result


def checkpoint(path: Path, report: dict) -> None:
    counts = Counter(item["result"]["status"] for item in report["cases"] if "result" in item)
    report["summary"] = {"selected": len(report["cases"]), "completed": sum(counts.values()),
                         "not_run": len(report["cases"]) - sum(counts.values()), "status_counts": dict(sorted(counts.items())),
                         "all_selected_cases_passed": bool(report["cases"]) and counts.get("pass", 0) == len(report["cases"])}
    report["updated_at"] = now()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", required=True, help="Explicit isolated C-Gate test server")
    parser.add_argument("--port", type=int, default=20023)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--network", type=int, choices=range(250, 255), default=254, help="Reserved closed acceptance network")
    parser.add_argument("--shard", help="Deterministic zero-based INDEX/COUNT for independent parallel reports")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--all-revisions", action="store_true")
    parser.add_argument("--boundaries", action="store_true", help="Test both minimum and maximum firmware, not every intermediate version")
    parser.add_argument("--filter", default="", help="Case-insensitive substring in unit type, catalogue number or firmware")
    parser.add_argument("--limit", type=int, help="Maximum additional cases; remaining cases remain not_run")
    parser.add_argument("--resume", action="store_true", help="Continue missing cases in the same exact catalogue and selection")
    parser.add_argument("--retry-failures", action="store_true", help="With --resume, explicitly repeat failed offline cases")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be nonnegative")
    if args.retry_failures and not args.resume:
        parser.error("--retry-failures requires --resume")
    cases, catalog = load_cases(args.catalog, args.all_revisions, args.boundaries)
    cases = [case for case in cases if args.filter.lower() in " ".join([case["unit_type"], case["firmware"], case["catalog_number"]]).lower()]
    if args.shard:
        try:
            shard_index, shard_count = map(int, args.shard.split("/"))
            if not 0 <= shard_index < shard_count <= 16:
                raise ValueError
        except ValueError:
            parser.error("--shard must be INDEX/COUNT with 0 <= INDEX < COUNT <= 16")
        cases = [case for index, case in enumerate(cases) if index % shard_count == shard_index]
    selection = {"all_revisions": args.all_revisions, "boundaries": args.boundaries, "filter": args.filter,
                 "case_ids_sha256": digest([case["id"] for case in cases])}
    if args.shard:
        selection["shard"] = args.shard
    report = {"format": FORMAT, "created_at": now(), "scope": "Offline C-Gate catalogue schema and Python PP session export/reset/import equality; not hardware or full Toolkit parity",
              "catalog": catalog, "selection": selection, "project": PROJECT,
              "cases": cases, "runs": []}
    if args.resume:
        old = json.loads(args.output.read_text())
        if old.get("format") != FORMAT or old.get("catalog", {}).get("sha256") != catalog["sha256"] or old.get("selection") != selection:
            raise ValueError("Resume report has a different format, catalogue, or selected cases")
        report = old
    elif args.output.exists():
        raise ValueError("Output already exists; choose --resume or another --output")
    with CGateClient(args.host, args.port, timeout=args.timeout) as transport:
        audit = OfflineAuditClient(transport, network=args.network)
        run = {"started_at": now(), "host": args.host, "port": args.port, "greeting": transport.greeting,
               "python_version": sys.version, "platform": platform.platform(), "limit": args.limit, "network": args.network,
               "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "source_sha256": {name: hashlib.sha256(Path(__file__).resolve().parents[1].joinpath("src/cbus_toolkit", name).read_bytes()).hexdigest()
                                 for name in ("cgate.py", "programming.py")}}
        report["runs"].append(run)
        checkpoint(args.output, report)
        try:
            prepare_project(audit)
        except Exception as error:
            run["setup_error"] = error_details(error)
            run["finished_at"] = now()
            checkpoint(args.output, report)
            raise
        for field, command in (("catalog_info", "PP CATALOG_INFO"), ("patch_version", "PP PATCH_VERSION")):
            try:
                run[field] = list(audit.command(command).lines)
            except CGateError as error:
                run[field + "_error"] = error_details(error)
        completed = 0
        try:
            for case in report["cases"]:
                previous = case.get("result")
                if previous and not (args.retry_failures and previous["status"] != "pass"):
                    continue
                if args.limit is not None and completed >= args.limit:
                    break
                if not transport.connected:
                    run["stopped_reason"] = "Transport closed; no automatic reconnect or replay"
                    break
                if previous:
                    case.setdefault("previous_results", []).append(previous)
                case["result"] = run_case(Programmer(audit), audit, case)
                case["result"]["run_index"] = len(report["runs"]) - 1
                completed += 1
                checkpoint(args.output, report)
                if completed == 1 or completed % 10 == 0 or case["result"]["status"] != "pass":
                    print(json.dumps({"completed_this_run": completed, "case": case["id"], "catalog_number": case["catalog_number"], "unit_type": case["unit_type"], "firmware": case["firmware"], "status": case["result"]["status"], "totals": report["summary"]}), flush=True)
        except KeyboardInterrupt:
            run["stopped_reason"] = "Interrupted by user; resume explicitly"
        finally:
            run["finished_at"] = now()
            run["commands"] = audit.command_count
            checkpoint(args.output, report)
        print(json.dumps({"output": str(args.output.resolve()), **report["summary"]}), flush=True)
    return 0 if report["summary"]["all_selected_cases_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
