#!/usr/bin/env python3
"""Run the current known-serial public CLI -> loaded-project recovery journey.

All endpoints and projects are owned loopback fixtures. Retained command rows
contain exact subprocess stdout/stderr/argv, not hand-written summaries.
Interruption injection runs in process and is labelled separately from the
fresh public CLI recovery subprocesses. This is synthetic acceptance, never
native Toolkit, real bridge, hardware, power-cycle or bus-wide exclusivity proof.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from zipfile import ZipFile
from xml.dom import minidom
import xml.etree.ElementTree as ET

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.classic_replacement import _canonical, _document, _field, _shape
from cbus_toolkit.native import NativeProjects
from cbus_toolkit.project import ProjectDocument
from cbus_toolkit.serial_reconcile import CGateDatabase, ReconcileError, ReconcileRecord, reconcile
from research.cgate_session_differential import rust_source_paths
from research.known_serial_journey_support import (
    CLIRecorder, artifact, commissioning_fixture, digest, owned_cmqttd, port_closed,
)
from tests.test_serial_reconcile import PROJECT, OID
from tests.test_simulator_duplicate_addressing import A, CO_A
from tests.test_pci_selected_serial_routed import routed_co

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "toolkit-cli/src/cbus_toolkit"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def fingerprint():
    paths = rust_source_paths(daemon=True)
    paths.update(path for path in PACKAGE.rglob("*") if path.is_file() and path.suffix in (".py", ".json"))
    paths.update((ROOT / "rust/Cargo.toml", ROOT / "rust/Cargo.lock",
                  ROOT / "toolkit-cli/pyproject.toml", Path(__file__).resolve(),
                  ROOT / "toolkit-cli/research/known_serial_journey_support.py"))
    # The independently defined literal peers and project preimages participate
    # in this acceptance closure, rather than being hidden fixture dependencies.
    paths.update(path for path in (ROOT / "toolkit-cli/tests").rglob("*.py"))
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(paths)}


def package_probe(interpreter):
    code = ("import cbus_toolkit,cbus_toolkit.serial_reconcile,cbus_toolkit.pci_selected_serial,json,sys; "
            "from pathlib import Path; from hashlib import sha256; "
            "root=Path(cbus_toolkit.__file__).parent; "
            "print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,package_path=str(root),"
            "serial_reconcile_path=cbus_toolkit.serial_reconcile.__file__,"
            "selected_serial_path=cbus_toolkit.pci_selected_serial.__file__,"
            "package_files={str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() "
            "for p in root.rglob('*') if p.is_file() and p.suffix in ('.py','.json')})))")
    argv = [str(interpreter), "-c", code]
    result = subprocess.run(argv, capture_output=True, check=True, text=True)
    observed = json.loads(result.stdout)
    observed["probe"] = {"argv": argv, "exit_status": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr}
    expected = {str(path.relative_to(PACKAGE)): digest(path) for path in PACKAGE.rglob("*")
                if path.is_file() and path.suffix in (".py", ".json")}
    require(observed["package_files"] == expected, "Executed interpreter package differs from current source")
    import cbus_toolkit
    require(Path(cbus_toolkit.__file__).parent.resolve() == Path(observed["package_path"]).resolve(),
            "Run producer under the same package environment as --python; in-process faults need exact imports")
    return observed


def same_project_except_move(before, after, network):
    """Restore exactly Address and PP UnitAddress, then compare the whole graph."""
    original, restored = ProjectDocument.from_bytes(before.encode()), ProjectDocument.from_bytes(after.encode())
    source, destination = f"/network/{network}/unit/255", f"/network/{network}/unit/6"
    pp = original.parameters(source)
    require(restored.path_of(restored.resolve("oid:" + OID)) == destination, "OID changed or move missing")
    require(int(restored.parameters(destination)["UnitAddress"], 0) == 6, "PP UnitAddress not moved")
    require({key: value for key, value in pp.items() if key != "UnitAddress"} ==
            {key: value for key, value in restored.parameters(destination).items() if key != "UnitAddress"},
            "Other programmed parameters changed")
    restored.update(destination, {"Address": "255"})
    restored.set_parameter(source, "UnitAddress", pp["UnitAddress"])
    require(_shape(minidom.parseString(original.raw_xml()).documentElement) ==
            _shape(minidom.parseString(restored.raw_xml()).documentElement),
            "Whole project changed beyond the exact two admitted fields")
    return {"oid_preserved": True, "unit_metadata_preserved": True, "other_pp_preserved": True,
            "whole_project_two_field_only": True}


def journey(args, profile, work, report):
    work.mkdir(exist_ok=False)
    cli = CLIRecorder(args.python, work / "commands", cwd=ROOT / "toolkit-cli")
    report.update(profile=profile, commands=cli.commands, cmqttd={}, fault_injections=[],
                  record_tamper_refusals=[], handoff_tamper_refusals=[], finished_workflow=False)
    network = 252 if profile == "routed" else 254
    sim = commissioning_fixture(profile, work)
    with ExitStack() as stack:
        endpoint = stack.enter_context(sim.running())
        report["selected_serial_pci_endpoint"] = list(endpoint)
        port = stack.enter_context(owned_cmqttd(args.cmqttd_bin, work / "daemon", report["cmqttd"]))
        host, pci_port = endpoint
        gate = ["cgate", "--host", "127.0.0.1", "--port", port, "--timeout", 15]

        def invoke(arguments, expected=0, label=None):
            return cli.invoke(arguments, expected=expected, label=label)

        def exported(path, name):
            target = work / name
            invoke([*gate, "database", "get-xml", path, "--project", "SYNTH", "--output", target], label=name)
            return target.read_text()

        invoke([*gate, "project", "new", "SYNTH"], label="project-new")
        commands = ["PROJECT USE SYNTH", f"DBCREATENET 254 Root Cni {host}:{pci_port}"]
        if profile == "routed":
            commands.append("DBCREATENET 252 Far Bridge 254/p/252")
        seed_commands = work / "seed-commands.txt"
        seed_commands.write_text("\n".join(commands) + "\n")
        invoke([*gate, "run", seed_commands], label="public-raw-network-setup")
        seed_paths = []
        if profile == "routed":
            root = ET.fromstring(exported("//SYNTH/254", "empty-root.xml"))
            bridge = ET.SubElement(root, "Unit")
            for key, value in (("OID", "7c0e0f10-1111-4222-8333-944455556699"), ("TagName", "Owned bridge"),
                               ("Address", "252"), ("UnitType", "BRIDGE2N"), ("UnitName", "BRIDGE2N"),
                               ("SerialNumber", "101000.100"), ("FirmwareVersion", "4.0.00")):
                ET.SubElement(bridge, key).text = value
            ET.SubElement(bridge, "PP", Name="UnitAddress", Value="252")
            path = work / "seed-root.xml"; path.write_text(ET.tostring(root, encoding="unicode"))
            invoke([*gate, "database", "set-xml", "//SYNTH/254", path, "--project", "SYNTH", "--readback"], label="seed-bridge")
            seed_paths.append((254, path))
        target = ET.fromstring(exported(f"//SYNTH/{network}", "empty-target.xml"))
        for unit in ET.fromstring(PROJECT).findall("Project/Network/Unit"):
            # The authoritative baseline is the admitted DBGETXML result. This
            # fixture deliberately avoids claiming private extension import.
            for child in list(unit):
                if child.tag.startswith("{") or child.tag == "Partner":
                    unit.remove(child)
            if unit.find("UnitName") is None:
                ET.SubElement(unit, "UnitName").text = "KEYE1"
            if unit.findtext("Address") == "20":
                ET.SubElement(unit, "Description").text = OID
            target.append(unit)
        path = work / "seed-target.xml"; path.write_text(ET.tostring(target, encoding="unicode"))
        invoke([*gate, "database", "set-xml", f"//SYNTH/{network}", path, "--project", "SYNTH", "--readback"], label="seed-target")
        seed_paths.append((network, path))
        invoke([*gate, "project", "save", "SYNTH"], label="save-baseline")
        invoke([*gate, "project", "close", "SYNTH"], label="close-baseline")
        invoke([*gate, "project", "load", "SYNTH"], label="load-baseline")
        invoke([*gate, "project", "use", "SYNTH"], label="use-baseline")
        baseline = exported("//SYNTH", "before.xml")
        route_project = work / "before.xml"
        original_unit = exported(f"//SYNTH/{network}/p/255", "before-unit.xml")
        before_bus = sim.snapshot(); (work / "physical-before.json").write_text(json.dumps(before_bus, indent=2) + "\n")
        plan, journal, handoff = work / "plan.json", work / "apply.json", work / "verified.json"
        attempts = work / "attempts"; attempts.mkdir()
        route = ["--project", route_project, "--source-network", 254, "--target-network", network] if profile == "routed" else []
        invoke(["serial-address", "plan", A, 6, "--host", host, "--port", pci_port,
                "--local-unit", 16, "--expected-local-serial", "100966.1187", "--output", plan,
                "--timeout", 15, "--observation-timeout", 2, "--confirmation-timeout", .2,
                "--mmi-response-timeout", .2, "--quiet-period", .1,
                "--options-response-timeout", .1, "--address-response-timeout", .1, *route], label="plan")
        sim.acceptance_corrupt_receipt = True
        invoke(["serial-address", "apply", plan, "--recovery", journal, "--attempt-store", attempts, *route],
               expected=1, label="single-address-uncertain")
        sim.acceptance_corrupt_receipt = False
        original_journal = journal.read_bytes()
        marker = Path(json.loads(original_journal)["attempt_identity"])
        original_marker = marker.read_bytes()
        verified = invoke(["serial-address", "verify", "--recovery", journal, "--output", handoff, *route], label="fresh-independent-verify-export")
        require(verified["verification"]["outcome"] == "observed_expected_change", "Independent verification failed")
        require(json.loads(original_journal)["outcome"] == "uncertain", "Apply must remain uncertain")
        require(journal.read_bytes() == original_journal and marker.read_bytes() == original_marker, "Verification mutated original evidence")
        require(len(sim.co_operations) == 1, "Address request was replayed")
        after_bus = sim.snapshot(); (work / "physical-after.json").write_text(json.dumps(after_bus, indent=2) + "\n")
        require(before_bus["physical_nodes"][A]["parameters"] == after_bus["physical_nodes"][A]["parameters"], "Physical parameters changed")
        report["independent_verification"] = {"apply": "uncertain", "verification": "observed_expected_change",
            "original_journal_unchanged": True, "attempt_marker_unchanged": True, "address_commands": 1,
            "physical_parameters_unchanged": True, "fixture_memory_policy": "bus_only"}
        options = ["serial-address", "reconcile", "--journal", handoff, "--cgate", f"127.0.0.1:{port}",
                   "--project-name", "SYNTH", "--network", network, "--unit-type", "KEYE1", "--firmware", "2.5.00",
                   "--exclusive-project"]
        if profile == "routed":
            options += ["--route-project", route_project]

        def reset_database(label):
            invoke([*gate, "project", "load", "SYNTH"], label=label + "-load")
            for number, source in seed_paths:
                invoke([*gate, "database", "set-xml", f"//SYNTH/{number}", source, "--project", "SYNTH", "--readback"], label=label + "-seed")
            invoke([*gate, "project", "save", "SYNTH"], label=label + "-save")
            require(exported("//SYNTH", label + "-baseline.xml") == baseline, "Synthetic restoration differs from exact bound baseline")

        # Deliberate in-process library faults: their fresh-process recovery is
        # public CLI evidence, but fault delivery itself is NOT a CLI execution.
        faults = [("before_database_write", "write", "before"), ("after_database_write", "write", "after"),
                  ("before_target_save", "save", "before"), ("during_target_save_unsent", "save", "unsent"),
                  ("during_target_save_reply_lost", "save", "after"),
                  ("before_close", "close", "before"), ("after_close", "close", "after"),
                  ("before_load", "load", "before"), ("after_load", "load", "after"),
                  ("after_saved_readback", "db_done", "before")]
        operation, advance, document_write = NativeProjects.operation, ReconcileRecord.advance, CGateClient.command_document
        for label, action, position in faults:
            reset_database(label)
            record_path = work / (label + ".json")
            fired, operations = [], []
            def interrupt(manager, operation_name, project, other=None, **kwargs):
                operations.append({"operation": operation_name, "project": project, "other": other})
                selected = operation_name == action and project == "SYNTH" and not fired
                if action == "load":
                    selected = selected and any(row["operation"] == "close" and row["project"] == "SYNTH" for row in operations)
                if action == "save":
                    selected = selected and sum(row["operation"] == "save" and row["project"] == "SYNTH" for row in operations) == 2
                if selected:
                    fired.append(True)
                    if position == "before":
                        raise KeyboardInterrupt("Owned in-process fixture: " + label)
                    if position == "unsent":
                        raise ConnectionError("Owned in-process send failure before target SAVE delivery")
                    operation(manager, operation_name, project, other, **kwargs)
                    raise KeyboardInterrupt("Owned in-process lost reply: " + label)
                return operation(manager, operation_name, project, other, **kwargs)
            def interrupt_write(client, command, xml, *rest, **kwargs):
                selected = action == "write" and command.startswith("DBSETXML ") and not fired
                if selected:
                    fired.append(True)
                    if position == "before":
                        raise KeyboardInterrupt("Owned in-process fixture: " + label)
                    document_write(client, command, xml, *rest, **kwargs)
                    raise KeyboardInterrupt("Owned in-process lost reply: " + label)
                return document_write(client, command, xml, *rest, **kwargs)
            def interrupt_record(record, phase, **fields):
                if action == "db_done" and phase == "db_done" and not fired:
                    fired.append(True)
                    raise KeyboardInterrupt("Owned in-process interruption after saved readback")
                return advance(record, phase, **fields)
            fault = {"case": label, "execution": "in_process_library_fault_injection",
                     "operations": operations, "public_cli_fault_injection": False}
            report["fault_injections"].append(fault)
            with CGateClient("127.0.0.1", port, timeout=15) as client:
                database_args = dict(endpoint=f"127.0.0.1:{port}", exclusive_project=True)
                if profile == "routed":
                    database_args["route_project"] = route_project
                database = CGateDatabase(client, "SYNTH", **database_args)
                with patch.object(NativeProjects, "operation", interrupt), patch.object(ReconcileRecord, "advance", interrupt_record), patch.object(CGateClient, "command_document", interrupt_write):
                    try:
                        reconcile(handoff, database, apply=True, record_path=record_path, network=network)
                    except (KeyboardInterrupt, ReconcileError) as error:
                        fault["exception"] = {"type": type(error).__name__, "message": str(error)}
                    else:
                        raise AssertionError("Fault hook not reached: " + label)
            require(fired and json.loads(record_path.read_text())["phase"] == "db_pending", "Fault record not pending: " + label)
            require(sum(row["operation"] == "save" and row["project"] == "SYNTH" for row in operations) ==
                    (1 if action == "write" else 2), "Fault triggered an automatic rollback or additional SAVE")
            pending = json.loads(record_path.read_text())
            pending_path = work / (label + "-pending.json"); pending_path.write_text(json.dumps(pending, indent=2) + "\n")
            old_saves = sum(row.get("event") == "target_save_intent" for row in pending["history"])
            old_writes = sum(row.get("event") == "database_write_intent" for row in pending["history"])
            prefix = [*options, "--record", record_path, "--apply"]
            explicit = action == "write" or label in ("before_target_save", "during_target_save_unsent")
            if explicit:
                invoke(prefix, expected=1, label=label + "-saved-original-refusal")
                require(json.loads(record_path.read_text())["phase"] == "db_pending", "Refusal completed pending record")
                recovered = invoke([*prefix, "--retry-database"], label=label + "-explicit-db-only-recovery")
                require(recovered["outcome"] == "reconciled", "Explicit DB-only recovery failed")
            else:
                recovered = invoke(prefix, label=label + "-read-only-recovery")
                require(recovered["outcome"] == "resumed_complete", "Saved candidate recovery failed")
            final_record = json.loads(record_path.read_text())
            require(final_record["phase"] == "db_done" and final_record["cgate"]["saved_readback_verified"] is True, "Saved readback not established")
            require(final_record["cgate"]["backup_readback_sha256"] == final_record["cgate"]["before_project_sha256"], "Backup differs from original")
            new_saves = sum(row.get("event") == "target_save_intent" for row in final_record["history"])
            new_writes = sum(row.get("event") == "database_write_intent" for row in final_record["history"])
            require(new_saves == old_saves + int(explicit), "Unexpected target SAVE replay")
            require(new_writes == old_writes + int(explicit), "Unexpected database mutation replay")
            again = invoke(prefix, label=label + "-fresh-process-noop")
            require(again["outcome"] == "already_reconciled" and again["current_database_matches_record"] is True, "Recovery no-op mismatch")
            require(len(sim.co_operations) == 1, "Fault recovery replayed physical address request")
            fault.update(fault_delivered=True, recovery=recovered["outcome"], fresh_process_rerun=again["outcome"],
                         explicit_database_only_retry=explicit, target_save_intents_before=old_saves,
                         target_save_intents_after=new_saves, database_write_intents_before=old_writes,
                         database_write_intents_after=new_writes, pending_record=artifact(pending_path),
                         final_record=artifact(record_path), physical_address_commands_total=1)

        reset_database("normal")
        record_path = work / "complete-db.json"
        complete_options = [*options, "--record", record_path]
        dry = invoke(complete_options, label="reconcile-dry-run")
        completed = invoke([*complete_options, "--apply"], label="reconcile-apply")
        require((dry["outcome"], completed["outcome"]) == ("planned", "reconciled"), "Normal reconciliation failed")
        invoke([*gate, "project", "close", "SYNTH"], label="independent-close")
        invoke([*gate, "project", "load", "SYNTH"], label="independent-load")
        invoke([*gate, "project", "use", "SYNTH"], label="independent-use")
        reopened = exported(f"//SYNTH/{network}/p/6", "reopened-unit.xml")
        whole = exported("//SYNTH", "reopened-project.xml")
        preservation = same_project_except_move(baseline, whole, network)
        require(_canonical(reopened, exclude=("Address", "PP")) == _canonical(original_unit, exclude=("Address", "PP")), "Unit metadata changed")
        final_record = json.loads(record_path.read_text())
        again = invoke([*complete_options, "--apply"], label="normal-fresh-process-noop")
        require(again["outcome"] == "already_reconciled" and again["current_database_matches_record"] is True, "Normal repeat not a no-op")
        report["successful_journey"] = {"outcome": completed["outcome"], "reopened_address": 6,
            **preservation, "reference_preserved": ProjectDocument.from_bytes(whole.encode()).get_field(f"/network/{network}/unit/20", "Description") == OID,
            "rerun": again["outcome"], "current_database_matches_record": True, "physical_address_commands_total": 1}
        require(report["successful_journey"]["reference_preserved"], "Cross-unit OID reference changed")
        mutations = [("before_project_digest", lambda v: v["cgate"].update(before_project_sha256="0" * 64)),
                     ("expected_project_digest", lambda v: v["cgate"].update(expected_project_sha256="0" * 64)),
                     ("backup_project", lambda v: v.update(backup="NO_SUCH_SYNTHETIC_BACKUP")),
                     ("unit_oid", lambda v: v["unit"].update(oid="1c0e0f10-1111-4222-8333-944455556667")),
                     ("source_path", lambda v: v["unit"].update(source_path=f"//SYNTH/{network}/p/20")),
                     ("candidate_address", lambda v: v["cgate"].update(unit_address_after="7")),
                     ("backup_digest", lambda v: v["cgate"].update(backup_readback_sha256="0" * 64)),
                     ("missing_saved_readback", lambda v: v["cgate"].update(saved_readback_verified=False))]
        for label, mutate in mutations:
            value = json.loads(json.dumps(final_record)); mutate(value)
            poisoned = work / ("tampered-record-" + label + ".json"); poisoned.write_text(json.dumps(value))
            invoke([*options, "--record", poisoned, "--apply"], expected=1, label="poisoned-record-" + label)
            require(exported("//SYNTH", label + "-unchanged.xml") == whole, "Poisoned record mutated project")
            report["record_tamper_refusals"].append({"case": label, "exit_status": 1, "project_unchanged": True})
        pristine_handoff = handoff.read_bytes()
        handoff_mutations = [("original_digest", lambda v: v["original"].update(sha256="0" * 64)),
                             ("raw_inventory", lambda v: v["verification"]["after"]["initial_mmi"].update(received_hex="")),
                             ("replay_flag", lambda v: v.update(address_command_replayed=True))]
        if profile == "routed":
            handoff_mutations.append(("wrong_route", lambda v: v["verification"]["route_binding"].update(route=[253])))
        for label, mutate in handoff_mutations:
            value = json.loads(pristine_handoff); mutate(value)
            poisoned = work / ("tampered-handoff-" + label + ".json"); poisoned.write_text(json.dumps(value))
            bad_options = options.copy(); bad_options[bad_options.index("--journal") + 1] = poisoned
            invoke([*bad_options, "--record", work / (label + "-unused-record.json"), "--apply"], expected=1, label="poisoned-handoff-" + label)
            require(exported("//SYNTH", label + "-handoff-unchanged.xml") == whole, "Poisoned evidence mutated project")
            report["handoff_tamper_refusals"].append({"case": label, "exit_status": 1, "project_unchanged": True})
        if profile == "routed":
            stale = work / "stale-route-project.xml"; stale.write_bytes(route_project.read_bytes() + b" ")
            bad_options = options.copy(); bad_options[bad_options.index("--route-project") + 1] = stale
            invoke([*bad_options, "--apply"], expected=1, label="stale-route-project")
            require(exported("//SYNTH", "stale-route-unchanged.xml") == whole, "Stale topology mutated project")
            report["stale_route_project_refused"] = True
            # Mutate the actual loaded far-network topology through the public
            # DB API. Reconciliation must preserve this conflicting state and
            # refuse before any close/save, rather than silently reloading it.
            candidate_network = ET.fromstring(whole).find(f"Project/Network[Address='{network}']")
            require(candidate_network is not None, "Missing candidate far network")
            candidate_path = work / "saved-candidate-network.xml"
            candidate_path.write_text(ET.tostring(candidate_network, encoding="unicode"))
            candidate_network.find("Interface/InterfaceAddress").text = "254/p/253"
            poison_path = work / "poisoned-loaded-topology.xml"
            poison_path.write_text(ET.tostring(candidate_network, encoding="unicode"))
            invoke([*gate, "database", "set-xml", f"//SYNTH/{network}", poison_path,
                    "--project", "SYNTH", "--readback"], label="poison-loaded-topology")
            poisoned_whole = exported("//SYNTH", "poisoned-loaded-project.xml")
            require(poisoned_whole != whole, "Poisoned topology was not installed")
            invoke([*complete_options, "--apply"], expected=1, label="loaded-topology-conflict")
            require(exported("//SYNTH", "loaded-topology-conflict-unchanged.xml") == poisoned_whole,
                    "Conflicting loaded topology was discarded or mutated")
            report["poisoned_loaded_topology_refused"] = {"project_unchanged": True, "exit_status": 1}
            invoke([*gate, "database", "set-xml", f"//SYNTH/{network}", candidate_path,
                    "--project", "SYNTH", "--readback"], label="restore-owned-candidate-topology")
            require(exported("//SYNTH", "restored-owned-candidate.xml") == whole, "Owned candidate restoration differs")
        final_verify = invoke(["serial-address", "verify", "--recovery", journal, *route], label="final-independent-inventory")
        require(final_verify["outcome"] == "observed_expected_change", "Final inventory failed")
        require(journal.read_bytes() == original_journal and marker.read_bytes() == original_marker and handoff.read_bytes() == pristine_handoff,
                "Original immutable evidence changed")
        request = routed_co([252], A, 6) if profile == "routed" else CO_A
        requests = [bytes.fromhex(row["hex"]) for row in sim.wire_log if row["direction"] == "rx"]
        require(sum(request.rstrip(b"\r") in row for row in requests) == 1 and len(sim.co_operations) == 1,
                "Literal PCI capture contains a replay or omitted request")
        report["literal_pci_address_request"] = {"request_hex": request.hex(), "count": 1}
        report["co_operations"] = sim.co_operations
        report["pci_wire_log"] = sim.wire_log
        report["retained_files"] = {str(path.relative_to(work)): artifact(path) for path in work.rglob("*")
                                    if path.is_file() and not path.is_relative_to(work / "commands")}
    report["selected_serial_pci_port_closed"] = port_closed(endpoint)
    require(report["selected_serial_pci_port_closed"] and report["cmqttd"]["process_cleanup_verified"]
            and report["cmqttd"]["cgate_port_closed"], "Owned fixture process/listener cleanup failed")
    # Backend logs/state changed on shutdown, so bind their final bytes last.
    report["retained_files"] = {str(path.relative_to(work)): artifact(path) for path in work.rglob("*")
                                if path.is_file() and not path.is_relative_to(work / "commands")}
    report["finished_workflow"] = True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmqttd-bin", required=True, type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--wheel", type=Path, help="Required for installed-package acceptance; bind exact built wheel bytes")
    parser.add_argument("--output-dir", type=Path, required=True, help="New private raw evidence directory; never overwritten")
    parser.add_argument("--profile", choices=("direct", "routed", "both"), default="both")
    args = parser.parse_args(argv)
    args.cmqttd_bin = args.cmqttd_bin.resolve(); args.python = args.python.absolute()
    if not args.cmqttd_bin.is_file() or not os.access(args.cmqttd_bin, os.X_OK):
        parser.error("Select an explicitly built executable cmqttd")
    output = args.output_dir.resolve()
    if output.exists() or not output.parent.is_dir() or output.is_relative_to(ROOT):
        parser.error("Use a new raw output directory outside Git, in an existing owned parent")
    output.mkdir(mode=0o700)
    report = {"format": "cbus-known-serial-loaded-project-journey-v2", "result": "failed",
              "hardware_io": False, "native_process_launched": False, "physical_bridge_acceptance_verified": False,
              "power_cycle_persistence_verified": False, "fault_execution_boundary": "in-process library injection, public CLI subprocess recovery",
              "producer_argv": [sys.executable, *sys.argv], "profiles": [], "binary_before": artifact(args.cmqttd_bin)}
    try:
        report["source_revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        report["source_fingerprint_before"] = fingerprint()
        report["executed_package_before"] = package_probe(args.python)
        if Path(report["executed_package_before"]["package_path"]).resolve() != PACKAGE.resolve():
            require(args.wheel is not None, "Installed-package acceptance requires --wheel binding")
        if args.wheel is not None:
            report["wheel_before"] = artifact(args.wheel)
            with ZipFile(args.wheel) as archive:
                wheel_package = {name.removeprefix("cbus_toolkit/"): sha256(archive.read(name)).hexdigest()
                                 for name in archive.namelist() if name.startswith("cbus_toolkit/")
                                 and Path(name).suffix in (".py", ".json")}
            require(wheel_package == report["executed_package_before"]["package_files"], "Wheel package differs from executed imports")
            report["wheel_package_matches_executed_imports"] = True
        for profile in (("direct", "routed") if args.profile == "both" else (args.profile,)):
            row = {}; report["profiles"].append(row)
            journey(args, profile, output / profile, row)
        report["source_fingerprint_after"] = fingerprint()
        report["executed_package_after"] = package_probe(args.python)
        report["binary_after"] = artifact(args.cmqttd_bin)
        if args.wheel is not None:
            report["wheel_after"] = artifact(args.wheel)
            require(report["wheel_before"] == report["wheel_after"], "Wheel changed during acceptance")
        require(report["source_fingerprint_before"] == report["source_fingerprint_after"], "Source changed during acceptance")
        require(report["executed_package_before"] == report["executed_package_after"], "Executed package changed during acceptance")
        require(report["binary_before"] == report["binary_after"], "Backend binary changed during acceptance")
        report["result"] = "passed"
    except BaseException as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        (output / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
