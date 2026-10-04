"""Fresh cmqttd restart evidence for conversion XML lifecycle journals.

Owned JSON-state durability only. The stable test-local relay keeps the exact
journal endpoint while two separately reaped daemons use one explicit state
file. No mock durability, native repository, GUI, hardware or power-cycle claim.
The existing literal DOM/PP oracle is reused without importing the production
XML comparator. No data is seeded or restored after restart.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import re

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.programming import Programmer
from test_cgate_barcode_database_interop import FaultGate, selected_binary
from test_cgate_named_database_interop import (
    STARTUP, associated_evidence, associated_work, no_contact_trap,
    owned_backend, port_closed,
)
from test_cgate_toolkit_tweaker_interop import document
from test_cgate_toolkit_tweaker_lifecycle_interop import (
    cli as replace_cli, flags as replace_flags, state as replace_state,
)
from test_conversion_xml_preservation_backends import (
    EXPECTED_PP, FIXTURE, assert_graph, assert_read_only, backup,
    completed_replace, digest, seed_space,
)
from test_toolkit_tweaker_workflow import profile_files


EVIDENCE_NAME = "conversion-xml-restart-evidence.json"


class RestartGate(FaultGate):
    """Stable owned client endpoint; attach only between closed contexts."""

    def __init__(self, *, drop_save):
        # The completed case cannot match this deliberately unused verb.
        super().__init__(None, "PROJECT SAVE" if drop_save else
                         "UNUSED_CONVERSION_RESTART_FAULT", "drop")
        self.context_index = None
        self.attachments = []

    def _relay(self, peer, row):
        assert self.target is not None and self.context_index is not None
        row["process_context"] = self.context_index
        row["upstream_endpoint"] = list(self.target)
        super()._relay(peer, row)

    def quiesce(self):
        for row in self.rows:
            assert row["done"].wait(5), "Owned client did not close before restart"
        for worker in self.workers:
            worker.join(5)
        assert all(row["closed"] for row in self.rows)
        assert all(not worker.is_alive() for worker in self.workers)
        assert not self.errors, self.errors

    def attach(self, endpoint, index, previous=None):
        self.quiesce()
        if previous is not None:
            assert previous["process_cleanup"] and previous["process_exit"] == 0
            assert previous["listener_closed"] and previous["pci_closed"] and previous["broker_closed"]
        assert index == len(self.attachments)
        self.target = endpoint
        self.context_index = index
        self.attachments.append({"process_context": index,
                                 "upstream_endpoint": list(endpoint),
                                 "stable_client_endpoint": list(self.endpoint)})


def assert_closed(record):
    assert record["process_exit"] == 0
    assert all(record[key] for key in (
        "listener_owned", "process_cleanup", "listener_closed", "pci_closed", "broker_closed",
    ))
    rows = record["pci_wire"]
    assert [(row["direction"], bytes.fromhex(row["hex"])) for row in rows] == [
        ("rx", frame) for frame in STARTUP
    ], rows
    assert [row["sequence"] for row in rows] == list(range(8))
    assert all(row["connection"] == 0 for row in rows)


class RestartContext:
    def __init__(self, binary, tmp_path, specs, profile, trap, relay, evidence):
        self.binary, self.tmp_path = binary, tmp_path
        self.specs, self.profile, self.trap = specs, profile, trap
        self.relay, self.evidence = relay, evidence
        self.state_path = tmp_path / "durable-cgate-state.json"
        self.state_path = self.state_path.resolve()
        evidence["state_file"] = {"logical_name": self.state_path.name,
                                  "actual_argument": str(self.state_path)}
        evidence["stable_client_endpoint"] = {
            "host": relay.endpoint[0], "port": relay.endpoint[1],
        }

    @contextmanager
    def process(self, label):
        index = len(self.evidence["processes"])
        assert index < 2
        if index:
            assert_closed(self.evidence["processes"][-1])
            assert self.state_path.is_file() and not self.state_path.is_symlink()
        work = associated_work(self.tmp_path, label)
        first_call, first_wire = len(self.evidence["calls"]), len(self.relay.rows)
        with owned_backend(
            "cmqttd", self.binary, work, state_path=self.state_path,
            extra_args=("--cgate-unitspec", self.specs),
        ) as (endpoint, record):
            record["process_context"] = index
            record["work_directory"] = str(work)
            self.evidence["processes"].append(record)
            self.relay.attach(endpoint, index,
                              self.evidence["processes"][index - 1] if index else None)
            assert record["argv"][record["argv"].index("--cgate-state") + 1] == str(self.state_path)
            self.evidence["direct_launch_profile"]["argv"].append(list(record["argv"]))
            with CGateClient(*self.relay.endpoint, timeout=15) as owner:
                yield owner, work
            self.relay.quiesce()
        assert_closed(record)
        self.evidence.setdefault("context_ranges", []).append({
            "process_context": index,
            "cli_call_range": [first_call, len(self.evidence["calls"])],
            "wire_range": [first_wire, len(self.relay.rows)],
            "ranges_are_zero_based_half_open": True,
        })

    def state_pin(self, label):
        assert self.state_path.is_file() and not self.state_path.is_symlink()
        raw = self.state_path.read_bytes()
        # The schema/content are not used as the expected project oracle.
        assert isinstance(json.loads(raw), dict)
        row = {"label": label, "sha256": digest(raw), "bytes": len(raw),
               "logical_name": self.state_path.name}
        self.evidence.setdefault("state_file_checkpoints", []).append(row)
        return row


@contextmanager
def restart_journey(tmp_path, request, *, drop_save):
    binary = selected_binary("CBUS_CMQTTD_BIN")
    specs = tmp_path / "synthetic-specs"
    profile = profile_files(specs, "DIMDN8", "DIMDU4")
    evidence = {
        "format": "cbus-conversion-xml-restart-owned-v1", "backend": "cmqttd",
        "nodeid": request.node.nodeid, "original_execution": False,
        "physical_acceptance": False, "mock_persistence_acceptance": False,
        "native_repository_acceptance": False,
        "proposed_test_module": {"sha256": digest(Path(__file__).read_bytes()),
                                 "bytes": Path(__file__).stat().st_size},
        "borrowed_xml_test_module": {
            "sha256": digest(Path(__file__).with_name(
                "test_conversion_xml_preservation_backends.py").read_bytes()),
        },
        "literal_xml_fixture": {"sha256": digest(FIXTURE.read_bytes()),
                                "bytes": FIXTURE.stat().st_size},
        "direct_launch_profile": {"kind": "selected-owned-rust", "binary": {
            "resolved": str(binary), "sha256": digest(binary.read_bytes()),
            "bytes": binary.stat().st_size}, "argv": [],
            "extra_args": ["--cgate-unitspec", str(specs)],
            "specifications": {p.name: digest(p.read_bytes()) for p in specs.iterdir()}},
        "oracle": "Retained literal XML character nodes, complete source/target PP and whole graph/OID deltas",
        "calls": [], "processes": [], "wires": [],
    }
    path = tmp_path / EVIDENCE_NAME
    request.node.user_properties.append(("conversion_xml_restart_evidence", str(path)))
    relay = None
    try:
        with no_contact_trap() as trap:
            with RestartGate(drop_save=drop_save) as relay:
                context = RestartContext(binary, tmp_path, specs, profile, trap, relay, evidence)
                yield context
                assert len(evidence["processes"]) == 2
                assert evidence["processes"][0]["pid"] != evidence["processes"][1]["pid"]
                assert evidence["processes"][0]["work_directory"] != evidence["processes"][1]["work_directory"]
                assert len(relay.attachments) == 2
                assert all(row["stable_client_endpoint"] == list(relay.endpoint)
                           for row in relay.attachments)
                assert all(row["process_context"] in (0, 1) for row in relay.rows)
                relay.quiesce()
            assert port_closed(relay.endpoint)
        for record in evidence["processes"]:
            assert_closed(record)
        evidence.update(every_owned_process_reaped=True, no_later_pci=True,
                        explicit_closed_graph_trap_zero=True, closed_graph_trap_contacts=0,
                        stable_relay_listener_closed=True,
                        journal_endpoint_unchanged=True, restart_reseed_or_import_count=0)
    finally:
        if relay is not None:
            evidence["wires"] = relay.evidence()
            evidence["relay_attachments"] = relay.attachments
        associated_evidence(path, evidence)


def retain_journal(journal, evidence, relay):
    raw = journal.read_bytes()
    value = json.loads(raw)
    marker = journal.with_name(journal.name + ".toolkit-tweaker.json")
    marked = marker.read_bytes()
    assert journal.stat().st_mode & 0o777 == 0o600
    assert marker.stat().st_mode & 0o777 == 0o600
    assert value["plan"]["endpoint"] == {"host": relay.endpoint[0], "port": relay.endpoint[1]}
    assert value["plan"]["lifecycle"]["endpoint_tls"] is False
    evidence["original_lifecycle_journal"] = value
    evidence["journal_original"] = {"logical_name": journal.name, "sha256": digest(raw),
                                    "bytes": len(raw), "raw_hex": raw.hex()}
    evidence["attempt_marker_original"] = {
        "logical_name": marker.name, "sha256": digest(marked), "bytes": len(marked),
        "raw_hex": marked.hex(),
    }
    return raw, marker, marked


def assert_journal_retained(journal, retained, evidence, relay):
    raw, marker, marked = retained
    assert journal.read_bytes() == raw
    assert marker.read_bytes() == marked
    assert json.loads(raw)["plan"]["endpoint"] == {
        "host": relay.endpoint[0], "port": relay.endpoint[1],
    }
    evidence["journal_after_restart"] = {"sha256": digest(journal.read_bytes()),
                                         "bytes": journal.stat().st_size}
    evidence["attempt_marker_after_restart"] = {
        "sha256": digest(marker.read_bytes()), "bytes": marker.stat().st_size,
    }


def assert_literal_pp_read(call):
    groups = [rows for command, rows in zip(call["commands"], call["reply_lines"], strict=True)
              if re.fullmatch(r"PP GET \S+ \*", command)]
    assert len(groups) == 1
    pairs = []
    for line in groups[0]:
        assert line.startswith(("315-", "315 ")), line
        name, value = line[4:].split("=", 1)
        pairs.append((name, value))
    assert len(pairs) == len(EXPECTED_PP) and len(dict(pairs)) == len(pairs)
    assert dict(pairs) == EXPECTED_PP


def assert_restart_reads(context, start_call, start_wire):
    evidence, relay = context.evidence, context.relay
    assert len(evidence["calls"]) == start_call + 1
    call = evidence["calls"][-1]
    assert_read_only(call)
    assert_literal_pp_read(call)
    assert call["exit"] == 0
    rows = relay.rows[start_wire:]
    assert rows and all(row["process_context"] == 1 for row in rows)
    requests = [line for row in rows
                for line in bytes.fromhex(row["request_hex"]).decode().splitlines()]
    assert requests and all(re.fullmatch(r"\[[^]]+\] .+", line) for line in requests)
    commands = [line.split("] ", 1)[1] for line in requests]
    # Recovery itself is read-only. The separately requested owner CLOSE/LOAD
    # observations distinguish the retained saved image from the current tree;
    # neither is an automatic recovery step or a replay of the dropped SAVE.
    allowed_lifecycle = ("PROJECT CLOSE WFTEST", "PROJECT LOAD WFTEST")
    assert all(command in allowed_lifecycle or command.startswith((
        "DBGETXML ", "PROJECT USE WFTEST", "PROJECT USE BACKUP",
        "PP LOCK ", "PP START ", "PP LOAD ", "DBGET ", "PP GET ",
        "PP END ", "PP UNLOCK ",
    )) for command in commands), commands
    assert [command for command in commands if command in allowed_lifecycle] == list(allowed_lifecycle)
    assert not any(command.startswith((
        "FILE ", "PROJECT RESTORE ", "PROJECT SAVE ", "PROJECT COPY ",
        "DBADD", "DBSET", "DBDELETE ", "PP SET ", "PP NEW ", "PP SAVE",
    )) for command in commands)
    evidence["restart_recovery_read_only_commands"] = list(call["commands"])
    evidence["restart_all_commands"] = commands
    evidence["restart_database_write_or_save_count"] = 0
    evidence["restart_explicit_close_load_count"] = 2


def fresh_target_and_backup_pp(owner, context, label):
    """Two fresh database-only PP sessions, with literal complete values."""
    records = context.evidence.setdefault("fresh_restart_pp_readbacks", [])
    for project, expected_identity, expected_values in (
        ("WFTEST", ("DIMDU4", context.profile["firmware"], "TARGET"), EXPECTED_PP),
        ("BACKUP", ("DIMDN8", context.profile["source_firmware"], "SYNTHETIC"),
         context.profile["source_values"]),
    ):
        source = "/db//" + project + "/11/p/20"
        with Programmer(owner).load("//" + project + "/11", source) as session:
            identity = (session.unit_type, session.firmware, session.catalog_number)
            values = session.values()
            assert identity == expected_identity
            assert values == expected_values
            assert len(values) == 8
            records.append({"label": label, "project": project, "source": source,
                            "session": session.name, "identity": list(identity),
                            "values": values})
    # Return the owner connection's selection to the edited project explicitly.
    response = owner.command("PROJECT USE WFTEST")
    assert response.code == 200


def observe_current_then_saved_image(owner, context, before, other, oid, after):
    ev = context.evidence
    current = assert_graph(owner, ev, before, other, oid, replacement=True)
    assert current == after
    backup(owner, ev, before)
    fresh_target_and_backup_pp(owner, context, "fresh_current_before_close_load")
    ev["fresh_restart_current_project_xml"] = current
    # These operator-requested observations occur AFTER fresh current-tree
    # reads and are separate from the recovery CLI's read-only command list.
    observed = ev["explicit_saved_image_observation"] = []
    for command in ("PROJECT CLOSE WFTEST", "PROJECT LOAD WFTEST"):
        response = owner.command(command)
        observed.append({"command": command, "status": response.code,
                         "final": response.final})
        assert response.code == 200
    saved = assert_graph(owner, ev, before, other, oid, replacement=True)
    assert saved == after
    backup(owner, ev, before)
    fresh_target_and_backup_pp(owner, context, "saved_image_after_explicit_close_load")
    ev["fresh_restart_saved_image_project_xml"] = saved
    ev["current_and_saved_images_independently_read"] = True


def test_public_conversion_completed_journal_daemon_restart_preserves_xml(tmp_path, request):
    with restart_journey(tmp_path, request, drop_save=False) as context:
        ev, relay = context.evidence, context.relay
        journal = tmp_path / "attempt.json"
        with context.process("initial") as (owner, work):
            before, other = seed_space(owner, work, context.trap, context.profile, ev)
            final, after = completed_replace(
                owner, relay, ev, context.specs, context.profile, before, other, journal,
            )
            oid = final["destination_oid"]
            retained = retain_journal(journal, ev, relay)
            assert relay.matches == 0
        context.state_pin("after_first_process_reaped_before_restart")
        start_call, start_wire = len(ev["calls"]), len(relay.rows)
        with context.process("restarted") as (owner, _):
            # Fresh process only; no restore, reseed, save or inverse cleanup.
            # Explicit CLOSE/LOAD is separately recorded saved-image observation.
            observe_current_then_saved_image(owner, context, before, other, oid, after)
            recovered, call = replace_cli(relay, ev, recovery=True,
                                          extra=("--journal", str(journal)))
            assert recovered["disposition"] == "observed_replaced"
            assert recovered["fresh_pp_verified"] and recovered["backup_verified_fresh"]
            assert recovered["journal_xml_preservation_verified"]
            assert recovered["project_saved"] is True and recovered["persistence_verified"] is True
            assert not recovered["outcome_uncertain"] and not recovered["replay_authorized"]
            assert not recovered["automatic_retries"] and not recovered["rollback_performed"]
            assert_journal_retained(journal, retained, ev, relay)
            assert document(owner) == after and document(owner, "//OTHER") == other
            backup(owner, ev, before)
            assert_restart_reads(context, start_call, start_wire)
            ev["after_restart_read_only_recovery"] = recovered
        context.state_pin("after_second_process_reaped")
        ev["disk_restart_complete_journal_persistence_verified"] = True


def test_public_conversion_lost_save_daemon_restart_keeps_uncertainty(tmp_path, request):
    with restart_journey(tmp_path, request, drop_save=True) as context:
        ev, relay = context.evidence, context.relay
        journal = tmp_path / "attempt.json"
        with context.process("initial") as (owner, work):
            before, other = seed_space(owner, work, context.trap, context.profile, ev)
            preview, _ = replace_cli(relay, ev, context.specs, context.profile)
            failed, call = replace_cli(
                relay, ev, context.specs, context.profile, expected=1,
                extra=replace_flags(preview, journal),
            )
            failed = replace_state(failed)
            assert failed["failure_phase"] == "save" and failed["project_saved"] is None
            assert failed["outcome_uncertain"] and not failed["accepted"]
            assert failed["created"] and failed["source_deleted"] and failed["readdressed"]
            assert not failed["reopened"] and not failed["automatic_retries"]
            assert not failed["rollback_performed"]
            faults = [row for row in relay.evidence() if row.get("fault")]
            assert len(faults) == relay.matches == 1
            row, selected = faults[0], faults[0]["fault"]
            assert selected["command"] == "PROJECT SAVE WFTEST"
            assert selected["mode"] == "drop" and selected["occurrence"] == 1
            target = "[" + selected["tag"] + "] PROJECT SAVE WFTEST"
            assert bytes.fromhex(row["request_hex"]).decode().splitlines().count(target) == 1
            assert bytes.fromhex(row["forwarded_request_hex"]).decode().splitlines().count(target) == 1
            lost = bytes.fromhex(row["lost_backend_terminal_hex"])
            assert lost == ("[" + selected["tag"] + "] 200 OK\r\n").encode()
            assert lost.hex() in row["backend_response_hex"]
            assert lost.hex() not in row["response_hex"]
            assert call["statuses"][-1] is None and call["commands"][-1] == "PROJECT SAVE WFTEST"
            assert call["commands"].count("PROJECT SAVE WFTEST") == 1
            assert not any(c.startswith(("PROJECT CLOSE ", "PROJECT LOAD ")) for c in call["commands"])
            oid = failed["creation"]["oid"]
            after = assert_graph(owner, ev, before, other, oid, replacement=True)
            backup(owner, ev, before)
            retained = retain_journal(journal, ev, relay)
            saved = json.loads(retained[0])
            assert saved["phase"] == "save" and saved["outcome_uncertain"]
            assert saved["mutation_journal"][-1]["command"] == "PROJECT SAVE WFTEST"
            assert saved["mutation_journal"][-1]["attempted"]
            assert not saved["mutation_journal"][-1]["confirmed"]
            assert "status" not in saved["mutation_journal"][-1]
        context.state_pin("after_lost_success_first_process_reaped_before_restart")
        start_call, start_wire = len(ev["calls"]), len(relay.rows)
        with context.process("restarted") as (owner, _):
            observe_current_then_saved_image(owner, context, before, other, oid, after)
            recovered, call = replace_cli(relay, ev, recovery=True,
                                          extra=("--journal", str(journal)))
            assert recovered["disposition"] == "observed_replaced"
            assert recovered["fresh_pp_verified"] and recovered["backup_verified_fresh"]
            assert recovered["project_saved"] is None and recovered["outcome_uncertain"]
            assert recovered["persistence_verified"] is False
            assert recovered["journal_xml_preservation_verified"] is False
            assert recovered["replay_authorized"] is False
            assert not recovered["automatic_retries"] and not recovered["rollback_performed"]
            assert_journal_retained(journal, retained, ev, relay)
            assert document(owner) == after and document(owner, "//OTHER") == other
            backup(owner, ev, before)
            assert_restart_reads(context, start_call, start_wire)
            assert relay.matches == 1
            assert sum(bytes.fromhex(row["forwarded_request_hex"]).decode().splitlines().count(target)
                       for row in relay.rows) == 1
            ev["after_restart_read_only_recovery"] = recovered
        context.state_pin("after_uncertain_second_process_reaped")
        ev["actual_save200_dropped_once_no_replay"] = True
        ev["disk_restart_does_not_upgrade_unconfirmed_journal"] = True
