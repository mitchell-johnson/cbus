"""Public replacement lifecycle on owned mock/daemon and synthetic profiles.

No original instructions, physical bus, vendor specification or automatic
rollback is executed. Source-established metadata/delete/readdress ordering is
combined with an explicit operator backup and save/close/load verification.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateError
from test_cgate_toolkit_tweaker_interop import BACKENDS, PAIRS, journey, document, plan_digest
from test_cgate_barcode_database_interop import FaultGate, graph
from test_cgate_named_database_interop import associated_evidence


VECTOR = json.loads((Path(__file__).resolve().parents[2] / "rust/testdata/vectors/cgate_toolkit_tweaker_lifecycle_wire.json").read_text())


@contextmanager
def owned(backend, variable, tmp_path, source="DIMDN8", target="DIMDU4", **options):
    try:
        with journey(backend, variable, tmp_path, source, target, **options) as values:
            values[2]["format"] = "cbus-toolkit-tweaker-lifecycle-owned-v1"
            yield values
    finally:
        old = tmp_path / "toolkit-tweaker-evidence.json"
        if old.exists():
            old.rename(tmp_path / "toolkit-tweaker-lifecycle-evidence.json")


def cli(relay, evidence, specs=None, profile=None, source="DIMDN8", target="DIMDU4", *, extra=(), expected=0, recovery=False):
    before = len(relay.rows)
    argv = [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", relay.endpoint[0], "--port",
            str(relay.endpoint[1]), "--timeout", "15", "conversion"]
    if recovery:
        argv += ["tweak-recover", *extra]
    else:
        argv += ["tweak-replace", "//WFTEST/11/p/20", "--source-type", source, "--target-type", target,
                 "--source-spec", profile["source_spec"], "--target-spec", profile["target_spec"],
                 "--spec-dir", str(specs), "--firmware", profile["firmware"], "--catalog-number", "TARGET",
                 "--backup-project", "BACKUP", *extra]
    process = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    call = dict(argv=argv, exit=process.returncode, stdout=process.stdout, stderr=process.stderr)
    evidence["calls"].append(call)
    result = call["result"] = json.loads(process.stdout or process.stderr)
    assert process.returncode == expected, result
    assert len(relay.rows) == before + 1, "CLI opened another connection or replayed"
    row = relay.rows[before]
    assert row["done"].wait(5), "CLI connection did not close"
    requests = [re.fullmatch(r"\[([^]]+)\] (.+)", line)
                for line in bytes.fromhex(row["request_hex"]).decode().splitlines()]
    assert requests and all(requests)
    tags, commands = zip(*(match.groups() for match in requests))
    assert len(set(tags)) == len(tags)
    assert sum(c == "PROJECT USE WFTEST" for c in commands) <= 1
    assert not any(c.startswith(("NET OPEN ", "PP PROGRAM ", "DBCONVERT ", "CONVERTUNIT ",
                                "PROJECT DELETE ")) for c in commands)
    replies = {tag: [] for tag in tags}
    terminal = {}
    for line in bytes.fromhex(row["response_hex"]).decode().splitlines():
        match = re.fullmatch(r"\[([^]]+)\] (\d{3})([- ])(.*)", line)
        if match and match[1] in replies:
            replies[match[1]].append(match[2] + match[3] + match[4])
            if match[3] == " ":
                assert match[1] not in terminal
                terminal[match[1]] = (int(match[2]), match[4])
    lost = row.get("fault", {}).get("mode") == "drop"
    assert set(terminal) == set(tags[:-1] if lost else tags), row
    call.update(commands=list(commands), statuses=[terminal.get(tag, (None, None))[0] for tag in tags],
                terminals=[terminal.get(tag, (None, None))[1] for tag in tags],
                reply_lines=[replies[tag] for tag in tags], documents=[])
    return result, call


def state(value):
    return value.get("toolkit_tweaker_lifecycle_evidence", value.get("details", {}).get("toolkit_tweaker_lifecycle_evidence", value))


def flags(preview, journal):
    assert preview["plan_sha256"] == plan_digest(preview["plan"])
    return ("--apply", "--exclusive-project", "--expect-plan-sha256", preview["plan_sha256"], "--journal", str(journal))


def remove_unit(text, oid):
    root = ET.fromstring(text, ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    matches = [(parent, child) for parent in root.iter() for child in parent
               if child.tag == "Unit" and child.findtext("OID") == oid]
    assert len(matches) == 1, (oid, text)
    parent, child = matches[0]
    parent.remove(child)
    return ET.tostring(root, encoding="unicode")


def normalized_backup(text):
    root = ET.fromstring(text, ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    project = root.find("Project") if root.tag == "Installation" else root
    project.find("Address").text = "WFTEST"
    if project.find("TagName") is not None:
        project.find("TagName").text = "WFTEST"
    return ET.tostring(root, encoding="unicode")


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
@pytest.mark.parametrize("source,target", PAIRS, ids=["dimmer", "relay", "classic-key", "coupler", "input"])
def test_public_tweaker_replace_full_family_lifecycle(backend, variable, source, target, tmp_path):
    with owned(backend, variable, tmp_path, source, target) as (owner, relay, evidence, specs, profile, _):
        assert owner.command("DBSET //WFTEST/11/p/20/Description copied & Ω description").code == 200
        before, other = document(owner), document(owner, "//OTHER")
        original = ET.fromstring(document(owner, "//WFTEST/11/p/20"))
        journal = tmp_path / "attempt.json"
        preview, call = cli(relay, evidence, specs, profile, source, target)
        assert preview["phase"] == "preview_complete" and not journal.exists()
        assert preview["plan"]["target"] == "//WFTEST/11/p/1"
        assert preview["plan"]["metadata"]["CatalogNumber"] == "TARGET"
        assert not any(c.startswith(("DBADD", "DBSET", "DBDELETE", "PP SAVE", "PROJECT COPY", "PROJECT SAVE")) for c in call["commands"])
        assert document(owner) == before
        final, call = cli(relay, evidence, specs, profile, source, target, extra=flags(preview, journal))
        assert final["phase"] == "complete" and final["accepted"]
        assert all(final[k] for k in ("created", "source_deleted", "readdressed", "project_saved", "reopened", "backup_verified"))
        assert not final["outcome_uncertain"] and not final["rollback_performed"] and not final["full_replacement_parity"]
        assert final["plan_sha256"] == preview["plan_sha256"] == plan_digest(final["plan"])
        commands = call["commands"]
        assert sum(c.startswith("DBADDSAFE ") for c in commands) == 1
        sequence = VECTOR["ordered_once"]
        assert [commands.index(c) for c in sequence] == sorted(commands.index(c) for c in sequence)
        assert all(commands.count(c) == 1 for c in sequence)
        assert [call["statuses"][commands.index(c)] for c in sequence] == VECTOR["ordered_statuses"]
        unit = ET.fromstring(document(owner, "//WFTEST/11/p/20"))
        assert unit.findtext("OID") == final["destination_oid"] != original.findtext("OID")
        assert unit.findtext("UnitType") == target and unit.findtext("Address") == "20"
        for key in ("TagName", "UnitName", "SerialNumber", "Description"):
            assert (unit.findtext(key) or "") == (original.findtext(key) or "")
        assert unit.findtext("CatalogNumber") == "TARGET"
        after = document(owner)
        assert graph(remove_unit(before, original.findtext("OID"))) == graph(remove_unit(after, final["destination_oid"]))
        assert graph(normalized_backup(document(owner, "//BACKUP"))) == graph(before)
        assert document(owner, "//OTHER") == other
        evidence["snapshots"] = dict(before=before, after=after, source_before=ET.tostring(original, encoding="unicode"),
                                     backup=document(owner, "//BACKUP"), other=other)
        saved = json.loads(journal.read_text())
        assert saved["phase"] == "complete" and saved["plan_sha256"] == preview["plan_sha256"]
        assert journal.stat().st_mode & 0o777 == 0o600
        assert all(row["confirmed"] for row in saved["mutation_journal"])
        recovered, read = cli(relay, evidence, extra=("--journal", str(journal)), recovery=True)
        assert recovered["disposition"] == "observed_replaced" and recovered["persistence_verified"]
        assert recovered["backup_verified_fresh"] and not recovered["replay_authorized"]
        assert all(c.startswith(("DBGETXML ", "PROJECT USE WFTEST", "PP LOCK ", "PP START ", "PP LOAD ", "DBGET ",
                                "PP GET ", "PP END ", "PP UNLOCK ")) for c in read["commands"])
        assert document(owner) == after


FAULTS = [("PROJECT COPY", "backup"), ("DBADDSAFE", "creation"), ("PP SET", "creation"),
          ("PP SAVE_TO_SOURCE", "creation"), ("DBDELETE", "delete"),
          ("DBSET //WFTEST/11/p/1/Address", "readdress"), ("PROJECT SAVE", "save"),
          ("PROJECT CLOSE", "close"), ("PROJECT LOAD", "load")]


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
@pytest.mark.parametrize("verb,phase", FAULTS, ids=["backup", "add", "set", "pp-save", "delete", "readdress", "project-save", "close", "load"])
def test_public_tweaker_lifecycle_lost_receipt_never_replays(backend, variable, verb, phase, tmp_path):
    assert [row[0] for row in FAULTS] == VECTOR["lost_receipt_verbs"]
    with owned(backend, variable, tmp_path) as (owner, relay, evidence, specs, profile, endpoint):
        journal = tmp_path / "attempt.json"
        with FaultGate(endpoint, verb, "drop") as fault:
            preview, _ = cli(fault, evidence, specs, profile)
            failed, call = cli(fault, evidence, specs, profile, expected=1, extra=flags(preview, journal))
            failed = state(failed)
            assert failed["outcome_uncertain"] and failed["failure_phase"] == phase
            assert failed["automatic_retries"] == 0 and not failed["rollback_performed"]
            assert call["commands"][-1].startswith(verb + " ")
            assert sum(c.startswith(verb + " ") for c in call["commands"]) == 1
            if phase not in ("close", "load"):
                assert not any(c.startswith("PROJECT CLOSE ") for c in call["commands"])
            retained = journal.read_bytes()
            value = json.loads(retained)
            assert value["phase"] == phase and value["outcome_uncertain"]
            assert not value["mutation_journal"][-1]["confirmed"]
            recovered, call = cli(fault, evidence, recovery=True, extra=("--journal", str(journal)))
            assert recovered["read_only_recovery_only"] and not recovered["replay_authorized"]
            assert recovered["project_saved"] is None and not recovered["persistence_verified"]
            assert all(c.startswith(("DBGETXML ", "PROJECT USE WFTEST", "PP LOCK ", "PP START ", "PP LOAD ", "DBGET ",
                                    "PP GET ", "PP END ", "PP UNLOCK ")) for c in call["commands"])
            assert journal.read_bytes() == retained
            evidence["fault_wires"] = fault.evidence()
            faults = [row for row in evidence["fault_wires"] if row.get("fault")]
            assert len(faults) == 1
            fault_row = faults[0]
            selected = fault_row["fault"]
            terminal = bytes.fromhex(fault_row["lost_backend_terminal_hex"]).decode()
            code = 301 if verb == "DBADDSAFE" else 200
            assert re.fullmatch(r"\[" + re.escape(selected["tag"]) + r"\] " + str(code) + r" [^\r\n]*\r\n", terminal)
            forwarded = bytes.fromhex(fault_row["forwarded_request_hex"]).decode().splitlines()
            assert forwarded.count("[" + selected["tag"] + "] " + selected["command"]) == 1


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_tweaker_lifecycle_stale_plan_and_occupied_backup_no_write(backend, variable, tmp_path):
    with owned(backend, variable, tmp_path) as (owner, relay, evidence, specs, profile, _):
        preview, _ = cli(relay, evidence, specs, profile)
        assert owner.command("DBSETSAFE //WFTEST/11/p/20/Description changed").code == 200
        before = document(owner)
        failed, call = cli(relay, evidence, specs, profile, expected=1, extra=flags(preview, tmp_path / "attempt.json"))
        assert not state(failed)["created"]
        assert not any(c.startswith(("DBADD", "DBSET", "DBDELETE", "PP SAVE", "PROJECT COPY", "PROJECT SAVE")) for c in call["commands"])
        assert document(owner) == before and not (tmp_path / "attempt.json").exists()
        assert owner.command("PROJECT COPY WFTEST BACKUP").code == 200
        _, call = cli(relay, evidence, specs, profile, expected=1)
        assert not any(c.startswith(("DBADD", "DBSET", "DBDELETE", "PP SAVE", "PROJECT COPY", "PROJECT SAVE")) for c in call["commands"])
        assert document(owner) == before


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_tweaker_lifecycle_declared_assignment_refusal_preserves_source(backend, variable, tmp_path):
    with owned(backend, variable, tmp_path) as (owner, relay, evidence, specs, profile, endpoint):
        before = document(owner)
        original = document(owner, "//WFTEST/11/p/20")
        journal = tmp_path / "attempt.json"
        with FaultGate(endpoint, "PP SET", "refuse", occurrence=3) as fault:
            preview, _ = cli(fault, evidence, specs, profile)
            partial, call = cli(fault, evidence, specs, profile, expected=1, extra=flags(preview, journal))
            assert partial["phase"] == "creation_incomplete" and not partial["accepted"]
            assert partial["creation"]["failed_writes"] == {"Application": "C-Gate error: 408 Controlled barcode refusal"}
            assert partial["plan_sha256"] == preview["plan_sha256"] == plan_digest(partial["plan"])
            assert not partial["source_deleted"] and not partial["project_saved"]
            assert not any(c.startswith(("DBDELETE ", "PROJECT SAVE ", "PROJECT CLOSE ", "PROJECT LOAD ")) for c in call["commands"])
            evidence["fault_wires"] = fault.evidence()
        assert document(owner, "//WFTEST/11/p/20") == original
        assert graph(remove_unit(document(owner), partial["creation"]["oid"])) == graph(before)
        assert graph(normalized_backup(document(owner, "//BACKUP"))) == graph(before)


def test_public_tweaker_lifecycle_authentication_redacts_and_stops_before_write(tmp_path):
    correct, wrong = tmp_path / "auth.txt", tmp_path / "wrong.txt"
    correct.write_text("a" * 64 + "\n")
    wrong.write_text("b" * 64 + "\n")
    correct.chmod(0o600)
    wrong.chmod(0o600)
    with owned("cmqttd", "CBUS_CMQTTD_BIN", tmp_path, auth_file=correct) as (owner, relay, evidence, specs, profile, _):
        before = document(owner)
        failed, call = cli(relay, evidence, specs, profile, expected=1, extra=("--auth-token-file", str(wrong)))
        assert call["commands"] == ["LOGIN " + "b" * 64] and call["statuses"] == [420]
        assert "b" * 64 not in call["stdout"] + call["stderr"]
        assert state(failed)["commands"] == ["LOGIN <redacted>"]
        assert not state(failed)["mutation_journal"] and document(owner) == before
        preview, call = cli(relay, evidence, specs, profile, extra=("--auth-token-file", str(correct)))
        assert preview["phase"] == "preview_complete" and not preview["created"]
        assert "a" * 64 not in call["stdout"] + call["stderr"]
        assert document(owner) == before


def test_public_tweaker_lifecycle_malformed_recovery_and_apply_guards_never_connect(tmp_path):
    from test_cgate_named_database_interop import no_contact_trap
    from test_toolkit_tweaker_workflow import profile_files
    specs = tmp_path / "specs"
    profile = profile_files(specs, "DIMDN8", "DIMDU4")
    bad = tmp_path / "bad.json"
    bad.write_text('{"format":"cbus-toolkit-tweaker-lifecycle-v1"}')
    with no_contact_trap() as endpoint:
        host, port = endpoint.split(":")
        prefix = [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", host, "--port", port, "conversion"]
        commands = [["tweak-recover", "--journal", str(bad)],
                    ["tweak-replace", "//WFTEST/11/p/20", "--source-type", "DIMDN8", "--target-type", "DIMDU4",
                     "--source-spec", profile["source_spec"], "--target-spec", profile["target_spec"],
                     "--spec-dir", str(specs), "--firmware", profile["firmware"], "--catalog-number", "TARGET",
                     "--backup-project", "BACKUP", "--apply"]]
        for tail in commands:
            result = subprocess.run(prefix + tail, text=True, capture_output=True, timeout=15)
            assert result.returncode == 1
            assert json.loads(result.stdout or result.stderr)["type"] == "ValueError"
