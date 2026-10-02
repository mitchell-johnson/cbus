"""Pure lifecycle policy and transport/journal safety; public synthetic inputs."""
from argparse import Namespace
from copy import deepcopy
import json
from pathlib import Path

import pytest

from cbus_toolkit import toolkit_conversion_tweakers as tweakers
from cbus_toolkit import toolkit_tweaker_lifecycle as life
from cbus_toolkit.cgate import CGateResponse, CGateError
from cbus_toolkit.project import ProjectDocument
from test_toolkit_tweaker_workflow import arguments


def args(directory, **overrides):
    value = vars(arguments(directory)) | dict(backup_project="BACKUP", journal=None)
    value.pop("target_address")
    value.pop("tag_name")
    return Namespace(**(value | overrides))


def unit(fields):
    from xml.sax.saxutils import escape
    text = "<Project><Address>WFTEST</Address><Network><Address>11</Address><Unit>" + "".join(
        f"<{k}>{escape(v)}</{k}>" for k, v in fields.items()) + "</Unit></Network></Project>"
    return ProjectDocument.from_bytes(text.encode()).resolve("/network/11/unit/20")


def test_all_123_pairs_have_the_same_guarded_lifecycle_admission(tmp_path):
    pairs = [p for p in tweakers.REGISTRY if p not in tweakers.PAIR_REFUSALS
             and tweakers.REFUSALS[tweakers.REGISTRY[p]] is None
             and tweakers.REGISTRY[p] not in tweakers.dlt.TWEAKERS]
    assert len(pairs) == 123
    for source, target in pairs:
        # Reuse complete profile synthesis, including the retained aliases.
        from test_toolkit_tweaker_workflow import arguments as profile
        v = vars(profile(tmp_path / (source + target), source, target))
        v.update(backup_project="BACKUP", journal=None)
        p = life.prepare(Namespace(**v))
        assert tweakers.admitted(p.creation.source_type, p.creation.target_type)


def test_metadata_copies_source_and_separates_target_catalogue():
    node = unit(dict(Address="20", TagName="Exact & Ω", UnitName="SOURCE", Description="multiword Ω",
                     SerialNumber="123456.7", CatalogNumber="OLD"))
    assert life.metadata(node, "TARGET") == dict(TagName="Exact & Ω", UnitName="SOURCE",
        Description="multiword Ω", SerialNumber="123456.7", CatalogNumber="TARGET")


def test_blank_metadata_uses_recovered_newunit_and_legal_name():
    node = unit(dict(Address="20", TagName="", UnitName="", SerialNumber=""))
    assert life.metadata(node, "TARGET") == dict(TagName="NEWUNIT", UnitName="NEWUNIT",
        Description="", SerialNumber="", CatalogNumber="TARGET")
    assert life.legal_part_name("Ab c<d> ef_ghi") == "ABCDEF_G"


@pytest.mark.parametrize("fields", [dict(TagName="Unicode Ω", UnitName=""),
    dict(TagName="Two  spaces", UnitName="SOURCE"), dict(TagName="Exact", UnitName="a#b"),
    dict(TagName="Exact", UnitName="SOURCE", Description="\tbad")])
def test_unrepresentable_metadata_refuses_before_creation(fields):
    with pytest.raises(ValueError):
        life.metadata(unit(dict(Address="20") | fields), "TARGET")


def network(addresses):
    text = "<Project><Address>WFTEST</Address><Network><Address>11</Address>" + "".join(
        f"<Unit><Address>{a}</Address></Unit>" for a in addresses) + "</Network></Project>"
    return ProjectDocument.from_bytes(text.encode()).resolve("/network/11")


def test_first_free_matches_recovered_1_through_255_including_aliases():
    assert life.stage_address(network([0, "01", "+2", 4])) == 3
    assert life.stage_address(network(range(1, 255))) == 255
    with pytest.raises(ValueError, match="No free"):
        life.stage_address(network(range(1, 256)))
    with pytest.raises(ValueError, match="aliases"):
        life.stage_address(network([1, "01"]))


def test_apply_requires_digest_exclusive_and_new_journal(tmp_path):
    with pytest.raises(ValueError, match="requires"):
        life.prepare(args(tmp_path / "spec", apply=True))
    with pytest.raises(ValueError, match="journal"):
        life.prepare(args(tmp_path / "spec", apply=True, exclusive_project=True, expect_plan_sha256="a" * 64))
    old = tmp_path / "old.json"
    old.write_text("{}")
    with pytest.raises(ValueError, match="Existing"):
        life.prepare(args(tmp_path / "spec", journal=old))
    with pytest.raises(ValueError, match="distinct"):
        life.prepare(args(tmp_path / "spec", backup_project="wftest"))


def test_unknown_persistent_and_staging_sends_remain_uncertain():
    class Lost:
        def command(self, command):
            raise RuntimeError("controlled lost terminal")
    for command in ("DBDELETE //WFTEST/11/p/20", "PROJECT SAVE WFTEST", "PP SET session X 1"):
        state = life._initial()
        with pytest.raises(RuntimeError):
            life._Client(Lost(), state).command(command)
        assert state["outcome_uncertain"]
        assert state["mutation_journal"] == [dict(command=command, attempted=True, confirmed=False,
                                                   persistent=not command.startswith("PP SET"))]


def test_complete_error_does_not_fabricate_atomic_refusal():
    class Refuse:
        def command(self, command):
            raise CGateError(CGateResponse(("500 Save error",), "500 Save error", 500))
    state = life._initial()
    with pytest.raises(CGateError):
        life._Client(Refuse(), state).command("PROJECT SAVE WFTEST")
    assert state["outcome_uncertain"] and not state["mutation_journal"][0]["confirmed"]


def valid_journal():
    state = life._initial()
    before = '<Project><Address>WFTEST</Address><Network><Address>11</Address><Unit><Address>20</Address><OID>source</OID></Unit></Network></Project>'
    import hashlib
    plan = dict(source="//WFTEST/11/p/20", target="//WFTEST/11/p/1", endpoint=dict(host="127.0.0.1", port=1234),
                project_sha256=hashlib.sha256(before.encode()).hexdigest(), lifecycle=dict(format=life.FORMAT,
                    backup_project="BACKUP", before_project_xml=before, source_oid="source",
                    source_xml='<Unit><Address>20</Address><OID>source</OID></Unit>', source_rules=life.SOURCE_RULES,
                    catalogue_boundary="explicit", backup_reopen_boundary="operator", exception_cleanup_boundary="open", endpoint_tls=False),
                source_type="DIMDN8", target_type="DIMDU4", target_firmware="2.7.00", target_catalog="TARGET",
                tag_name="SOURCE", specifications={}, source_pp={}, target_defaults={}, tweaker={},
                assignments=[], expected_parameters={}, metadata={})
    state.update(phase="prepared", plan=plan, plan_sha256=life.creation._digest(plan))
    return state


def test_recovery_preflight_binds_exact_journal_endpoint_and_digest(tmp_path):
    path = tmp_path / "journal.json"
    path.write_text(json.dumps(valid_journal()))
    a = Namespace(journal=path, host="127.0.0.1", port=1234, auth_token_file=None)
    assert life.prepare_recovery(a)["phase"] == "prepared"
    a.port = 4321
    with pytest.raises(ValueError, match="endpoint"):
        life.prepare_recovery(a)
    value = valid_journal()
    value["plan"]["target"] = "//OTHER/11/p/1"
    path.write_text(json.dumps(value))
    a.port = 1234
    with pytest.raises(ValueError, match="digest"):
        life.prepare_recovery(a)
    path.write_text('{"format":"x","format":"y"}')
    with pytest.raises(ValueError):
        life.prepare_recovery(a)


@pytest.mark.parametrize("command", ["PROJECT COPY WFTEST BACKUP", "DBDELETE //WFTEST/11/p/20",
    "DBSET //WFTEST/11/p/1/Address 20", "PROJECT SAVE WFTEST", "PROJECT CLOSE WFTEST", "PROJECT LOAD WFTEST"])
def test_success_shaped_unexpected_receipts_keep_possible_send_uncertainty(command):
    class Unexpected:
        def command(self, value):
            return CGateResponse(("201 Unexpected receipt",), "201 Unexpected receipt", 201)
    state = life._initial()
    client = life._Client(Unexpected(), state)
    with pytest.raises(RuntimeError, match="required 200"):
        client.command(command)
    assert state["outcome_uncertain"]
    assert state["mutation_journal"][-1] == dict(command=command, attempted=True, confirmed=True, persistent=True, status=201)


def test_login_requires_exact_200_before_any_other_request(tmp_path):
    token = tmp_path / "token.txt"
    token.write_text("secret-token\n")
    p = life.prepare(args(tmp_path / "spec", auth_token_file=token))
    class Unexpected:
        commands = []
        def command(self, value):
            self.commands.append(value)
            return CGateResponse(("101 Unexpected login",), "101 Unexpected login", 101)
    client, state = Unexpected(), life._initial()
    with pytest.raises(RuntimeError, match="200 receipt"):
        life.execute(p, client, state)
    assert client.commands == ["LOGIN secret-token"] and state["commands"] == ["LOGIN <redacted>"]
    assert not state["mutation_journal"]
    path = tmp_path / "journal.json"
    path.write_text(json.dumps(valid_journal()))
    a = Namespace(journal=path, host="127.0.0.1", port=1234, auth_token_file=token, tls=False)
    life.prepare_recovery(a)
    client.commands = []
    with pytest.raises(RuntimeError, match="200 receipt"):
        life.recover(a, client)
    assert client.commands == ["LOGIN secret-token"]


def completed_journal():
    state = valid_journal()
    plan = state["plan"]
    oid = "00000000-0000-0000-0000-000000000005"
    before = plan["lifecycle"]["before_project_xml"]
    state.update(phase="complete", created=True, source_deleted=True, readdressed=True, reopened=True,
        accepted=True, backup_verified=True, project_saved=True, fresh_project_verified=True,
        fresh_pp_verified=True, verified_final_pp={"X": "1"}, destination_oid=oid,
        expected_final_project_xml=before.replace("<OID>source</OID>", "<OID>" + oid + "</OID>"),
        backup_xml=before.replace("<Address>WFTEST</Address>", "<Address>BACKUP</Address>"))
    state["creation"].update(plan=deepcopy(plan), accepted=True, oid=oid)
    commands = ["PROJECT COPY WFTEST BACKUP", "DBADDSAFE //WFTEST/11 Unit 1 SOURCE",
                "DBDELETE //WFTEST/11/p/20", "DBSET //WFTEST/11/p/1/Address 20",
                "PROJECT SAVE WFTEST", "PROJECT CLOSE WFTEST", "PROJECT LOAD WFTEST"]
    state["mutation_journal"] = [dict(command=c, attempted=True, confirmed=True, persistent=True,
                                       status=301 if c.startswith("DBADD") else 200) for c in commands]
    return state


@pytest.mark.parametrize("cleanup", ["PP END", "PP UNLOCK"])
def test_completed_recovery_cleanup_failure_cannot_claim_persistence(tmp_path, monkeypatch, cleanup):
    value = completed_journal()
    path = tmp_path / "journal.json"
    path.write_text(json.dumps(value))
    a = Namespace(journal=path, host="127.0.0.1", port=1234, auth_token_file=None, tls=False)
    life.prepare_recovery(a)
    retained = path.read_bytes()
    class Client:
        host, port = "127.0.0.1", 1234
    class Session:
        unit_type, firmware, catalog_number = "DIMDU4", "2.7.00", "TARGET"
        def __enter__(self): return self
        def values(self): return {"X": "1"}
        def __exit__(self, *unused): raise RuntimeError("controlled " + cleanup + " cleanup error")
    class Programmer:
        def __init__(self, client): pass
        def load(self, *unused): return Session()
    def document(client, project):
        raw = value["expected_final_project_xml"] if project == "WFTEST" else value["backup_xml"]
        return raw.encode(), ProjectDocument.from_bytes(raw.encode())
    monkeypatch.setattr(life, "Programmer", Programmer)
    monkeypatch.setattr(life.creation, "_document", document)
    result = life.recover(a, Client())
    assert result["disposition"] == "read_unavailable" and result["backup_verified_fresh"]
    assert not result["fresh_pp_verified"] and not result["persistence_verified"]
    assert result["project_saved"] is None and not result["replay_authorized"]
    assert cleanup in result["read_error"]["message"] and path.read_bytes() == retained


def test_completed_journal_requires_exact_receipts_and_nested_creation():
    assert life._validate_journal(completed_journal())["phase"] == "complete"
    for change in (lambda v: v["mutation_journal"][0].update(status=201),
                   lambda v: v.pop("creation"), lambda v: v["creation"].pop("oid"),
                   lambda v: v["creation"]["plan"].update(source="bad")):
        value = completed_journal()
        change(value)
        with pytest.raises(ValueError):
            life._validate_journal(value)


def test_default_port_and_tls_are_bound_in_recovery_preflight(tmp_path):
    value = valid_journal()
    value["plan"]["endpoint"]["port"] = 20123
    value["plan"]["lifecycle"]["endpoint_tls"] = True
    value["plan_sha256"] = life.creation._digest(value["plan"])
    path = tmp_path / "journal.json"
    path.write_text(json.dumps(value))
    a = Namespace(journal=path, host="127.0.0.1", port=None, auth_token_file=None, tls=True)
    assert life.prepare_recovery(a)["phase"] == "prepared"
    a.tls = False
    with pytest.raises(ValueError, match="endpoint"):
        life.prepare_recovery(a)


def test_dedicated_marker_scan_does_not_read_unrelated_files(tmp_path, monkeypatch):
    secret = tmp_path / "unrelated.bin"
    secret.write_bytes(b"x")
    state = valid_journal()
    class Client:
        writer = marker = None
        def checkpoint(self):
            self.writer.write(state)
            self.marker.write(state)
    read = life._Journal._read_current
    def guarded_read(self):
        assert self.path != secret, "Unrelated sibling file was read"
        return read(self)
    monkeypatch.setattr(life._Journal, "_read_current", guarded_read)
    life._new_attempt(Client(), tmp_path / "attempt.json", state)
    assert (tmp_path / "attempt.json.toolkit-tweaker.json").exists()
    assert secret.read_bytes() == b"x"


def test_sanitized_static_fixture_matches_bound_source_rules():
    path = Path(__file__).resolve().parents[1] / "research/fixtures/toolkit-tweaker-lifecycle-source.json"
    value = json.loads(path.read_text())
    assert value["inputs"]["exe_sha256"] == life.SOURCE_RULES["exe_sha256"]
    assert value["inputs"]["map_sha256"] == life.SOURCE_RULES["map_sha256"]
    assert value["methods"][0]["bytes_sha256"] == life.SOURCE_RULES["method_bytes_sha256"]
    assert value["original_instruction_execution"] == 0 and not value["vendor_bytes_included"]


@pytest.mark.parametrize("field,value", [("unit_type", "DIMDN8"), ("firmware", "9.9.99"), ("catalog_number", "OLD")])
def test_recovery_fresh_pp_requires_planned_identity(tmp_path, monkeypatch, field, value):
    state = completed_journal()
    path = tmp_path / "attempt.json"
    path.write_text(json.dumps(state))
    a = Namespace(journal=path, host="127.0.0.1", port=1234, auth_token_file=None, tls=False)
    life.prepare_recovery(a)
    class Client:
        host, port = "127.0.0.1", 1234
    class Session:
        unit_type, firmware, catalog_number = "DIMDU4", "2.7.00", "TARGET"
        def __enter__(self): return self
        def __exit__(self, *unused): pass
        def values(self): return {"X": "1"}
    setattr(Session, field, value)
    class Programmer:
        def __init__(self, client): pass
        def load(self, *unused): return Session()
    def document(client, project):
        raw = state["expected_final_project_xml"] if project == "WFTEST" else state["backup_xml"]
        return raw.encode(), ProjectDocument.from_bytes(raw.encode())
    monkeypatch.setattr(life, "Programmer", Programmer)
    monkeypatch.setattr(life.creation, "_document", document)
    result = life.recover(a, Client())
    assert result["disposition"] == "read_unavailable" and not result["fresh_pp_verified"]
    assert not result["persistence_verified"] and result["project_saved"] is None
    assert result["backup_verified_fresh"] and not result["replay_authorized"]


def test_apply_fresh_pp_refuses_contradictory_identity(tmp_path, monkeypatch):
    p = life.prepare(args(tmp_path / "spec")).creation
    class Session:
        unit_type, firmware, catalog_number = "DIMDN8", "2.7.00", "SYNTHETIC"
        def __enter__(self): return self
        def __exit__(self, *unused): pass
        def values(self): raise AssertionError("Parameters read despite contradictory identity")
    class Programmer:
        def __init__(self, client): pass
        def load(self, *unused): return Session()
    monkeypatch.setattr(life, "Programmer", Programmer)
    with pytest.raises(RuntimeError, match="identity"):
        life._pp(object(), p, p.source)
