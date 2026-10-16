"""Public tweaker subprocesses on owned servers and public synthetic profiles.

The project, specs, broker, PCI and fault relays are owned by these tests. No
vendor encoder, original GUI, physical bus, delete/readdress or project save
is used by the workflow. Literal requests, replies and cleanup remain private.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from xml.sax.saxutils import quoteattr

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.file_transfer import prepare_upload, upload
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text
from test_cgate_barcode_database_interop import FaultGate, graph, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)
from test_toolkit_tweaker_workflow import profile_files


BACKENDS = [("cgate-mock", "CBUS_CGATE_MOCK_BIN"), ("cmqttd", "CBUS_CMQTTD_BIN")]
PAIRS = [("DIMDN8", "DIMDU4"), ("RELDN8", "RELDN12"), ("KEY4", "KEYC4"),
         ("KEYBC2", "BCN2B"), ("KEY1", "KEY2")]


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def plan_digest(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def document(owner, path="//WFTEST"):
    return xml_text(NativeDatabase(owner).get(path, xml=True))


def seed(owner, work, trap, source, profile):
    roles = {name: str(uuid.uuid4()) for name in ("project", "network", "interface", "source",
             "neighbor", "application", "group", "level", "other_project", "other_network", "other_interface")}
    pp = "".join(f"<PP Name={quoteattr(name)} Value={quoteattr(value)}/>"
                 for name, value in profile["source_values"].items())
    unit = (f"<Unit><OID>{roles['source']}</OID><TagName>Source &amp; exact</TagName><Address>20</Address>"
            f"<UnitType>{source}</UnitType><UnitName>SOURCE</UnitName><SerialNumber>123456.7</SerialNumber>"
            f"<FirmwareVersion>{profile['source_firmware']}</FirmwareVersion><CatalogNumber>SYNTHETIC</CatalogNumber>"
            "<!-- keep source comment -->" + pp + "</Unit>")
    sibling = (f"<Unit><OID>{roles['neighbor']}</OID><TagName>Unrelated</TagName><Address>22</Address>"
               "<UnitType>KEY1</UnitType><UnitName>NEIGHBOR</UnitName><FirmwareVersion>1.2.67</FirmwareVersion>"
               '<PP Name="OpaqueSetting" Value="multiword &amp; raw Ω"/></Unit>')
    raw = (f"<Application><OID>{roles['application']}</OID><Address>56</Address><TagName>Lighting</TagName>"
           f"<Group><OID>{roles['group']}</OID><Address>1</Address><TagName>Raw group</TagName>"
           f'<Level Value="77"><OID>{roles["level"]}</OID><Address>7</Address><TagName>Raw retained</TagName>'
           "<TagsDLT/></Level></Group></Application>")

    def network(key, contents):
        address = "11" if key == "network" else "12"
        interface = "interface" if key == "network" else "other_interface"
        return (f"<Network><OID>{roles[key]}</OID><Address>{address}</Address><NetworkNumber>{address}</NetworkNumber>"
                f"<TagName>Owned{address}</TagName><Interface><OID>{roles[interface]}</OID>"
                f"<InterfaceType>cni</InterfaceType><InterfaceAddress>{trap}</InterfaceAddress></Interface>"
                '<!-- keep network comment --><?owned keep?><s:Opaque xmlns:s="urn:cbus:synthetic:tweak"'
                ' key="&amp;&quot;">mixed Ω<s:Child/> tail</s:Opaque>' + contents + "</Network>")

    for command in ("FILE MKDIR Projects", "FILE MKDIR Projects/archived"):
        assert owner.command(command).code == 200
    for name, oid, contents in (("WFTEST", roles["project"], network("network", unit + sibling + raw)),
                               ("OTHER", roles["other_project"], network("other_network", ""))):
        path = work / (name + "-synthetic.xml")
        path.write_text("<Installation><DBVersion>2.3</DBVersion><Project>"
                        f"<OID>{oid}</OID><Address>{name}</Address><TagName>{name}</TagName>"
                        + contents + "</Project></Installation>", encoding="utf-8")
        path.chmod(0o600)
        result = upload(prepare_upload("Projects/archived/" + path.name, path), owner)
        assert result["upload_completed"] and not result["project_save_requested"]
        assert owner.command(f"PROJECT RESTORE {name} {path.name}").code == 200
    assert owner.command("PROJECT USE WFTEST").code == 200
    # External XML intentionally retains its byte Value admission. The public
    # scalar setter is the admitted way to construct the retained raw owner.
    assert owner.command("DBSET //WFTEST/11/56/1/7/Value oops").code == 200
    return roles


@contextmanager
def journey(backend, variable, tmp_path, source="DIMDN8", target="DIMDU4", *, auth_file=None):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, "backend")
    specs = tmp_path / "synthetic-specs"
    profile = profile_files(specs, source, target)
    # Launch the selected Rust binary directly; retain this public synthetic
    # specification profile and the actual argv in the v2 journal.
    flag = "--unitspec" if backend == "cgate-mock" else "--cgate-unitspec"
    evidence = {"format": "cbus-toolkit-tweaker-owned-v2", "backend": backend,
                "original_execution": False, "physical_acceptance": False,
                "binary_sha256": digest(binary.read_bytes()),
                "direct_launch_profile": {"kind": "selected-owned-rust",
                    "binary": {"resolved": str(binary), "sha256": digest(binary.read_bytes()),
                               "bytes": binary.stat().st_size},
                    "extra_args": [flag, str(specs)],
                    "specifications": {p.name: digest(p.read_bytes()) for p in specs.iterdir()},
                    "argv": None},
                "specifications": {p.name: digest(p.read_bytes()) for p in specs.iterdir()},
                "calls": [], "processes": [], "wires": []}
    relay = None
    try:
        with no_contact_trap() as trap:
            with owned_backend(backend, binary, work, auth_file=auth_file, extra_args=(flag, specs)) as (endpoint, process):
                evidence["direct_launch_profile"]["argv"] = list(process["argv"])
                evidence["processes"].append(process)
                with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                    if auth_file is not None:
                        assert owner.command("LOGIN " + auth_file.read_text().splitlines()[0]).code == 200
                    roles = seed(owner, work, trap, source, profile)
                    evidence["roles"] = roles
                    yield owner, relay, evidence, specs, profile, endpoint
            evidence["closed_graph_trap_contacts"] = 0
    finally:
        if relay is not None:
            evidence["wires"] = relay.evidence()
        associated_evidence(tmp_path / "toolkit-tweaker-evidence.json", evidence)


def cli(relay, evidence, specs, profile, source="DIMDN8", target="DIMDU4", *, expected=0, extra=()):
    before = len(relay.rows)
    argv = [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", relay.endpoint[0], "--port",
            str(relay.endpoint[1]), "--timeout", "15", "conversion", "tweak", "//WFTEST/11/p/20",
            "--source-type", source, "--target-type", target, "--source-spec", profile["source_spec"],
            "--target-spec", profile["target_spec"], "--spec-dir", str(specs), "--firmware", profile["firmware"],
            "--catalog-number", "SYNTHETIC", "--target-address", "21", "--tag-name", "Replacement & Ω", *extra]
    result = subprocess.run(argv, text=True, capture_output=True, timeout=45)
    call = {"argv": argv, "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    evidence["calls"].append(call)
    value = call["result"] = json.loads(result.stdout or result.stderr)
    assert result.returncode == expected, value
    assert len(relay.rows) == before + 1, "CLI opened or replayed a connection"
    row = relay.rows[before]
    assert row["done"].wait(5), "CLI connection did not close"
    tagged, documents, body, delimiter = [], [], [], None
    for line in bytes.fromhex(row["request_hex"]).decode().splitlines():
        if delimiter is not None:
            if line == delimiter:
                documents.append({"text": "\n".join(body), "sha256": digest("\n".join(body))})
                body, delimiter = [], None
            else:
                body.append(line)
            continue
        match = re.fullmatch(r"\[([^]]+)\] (.+)", line)
        tagged.append(match)
        if match and " << " in match[2]:
            delimiter = match[2].rsplit(" << ", 1)[1]
    assert delimiter is None
    assert tagged and all(tagged), row
    tags, commands = zip(*(match.groups() for match in tagged))
    assert len(set(tags)) == len(tags), "Request tag reused"
    assert sum(command == "PROJECT USE WFTEST" for command in commands) == int("PROJECT USE WFTEST" in commands)
    assert not any(command.startswith(("DBDELETE ", "DBCONVERT ", "PROJECT SAVE ", "PROJECT CLOSE ",
                "PROJECT LOAD ", "NET OPEN ", "PP PROGRAM ")) for command in commands), commands
    assert all("/db//WFTEST/11/p/" in command for command in commands if command.startswith("PP LOAD "))
    terminal = {}
    replies = {tag: [] for tag in tags}
    for line in bytes.fromhex(row["response_hex"]).decode().splitlines():
        match = re.fullmatch(r"\[([^]]+)\] (\d{3})([- ])(.*)", line)
        if match and match[1] in replies:
            replies[match[1]].append(match[2] + match[3] + match[4])
            if match[3] == " ":
                assert match[1] not in terminal
                terminal[match[1]] = (int(match[2]), match[4])
    # A controlled lost terminal leaves precisely the last request unanswered.
    lost = row.get("fault", {}).get("mode") == "drop"
    assert set(terminal) == set(tags[:-1] if lost else tags), row
    call.update(commands=list(commands), documents=documents,
                statuses=[terminal.get(tag, (None, None))[0] for tag in tags],
                terminals=[terminal.get(tag, (None, None))[1] for tag in tags],
                reply_lines=[replies[tag] for tag in tags])
    return value, call


def state(value):
    return value.get("toolkit_tweaker_evidence", value.get("details", {}).get("toolkit_tweaker_evidence", value))


def apply_flags(preview):
    assert preview["plan_sha256"] == plan_digest(preview["plan"])
    return ("--apply", "--exclusive-project", "--expect-plan-sha256", preview["plan_sha256"])


def unchanged_after_removing_new(before, after, oid):
    # This independent comparison includes every attribute, comment, PI,
    # namespace, non-whitespace text and source PP field, with only the issued
    # Unit fragment removed. The existing graph comparator omits whitespace-only
    # text around element children, including under xml:space="preserve".
    matches = [m for m in re.finditer(r"<Unit>.*?</Unit>", after, re.DOTALL)
               if f"<OID>{oid}</OID>" in m[0]]
    assert len(matches) == 1, after
    match = matches[0]
    assert graph(after[:match.start()] + after[match.end():]) == graph(before)


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
@pytest.mark.parametrize("source,target", PAIRS, ids=["dimmer", "relay", "classic-key", "coupler", "input"])
def test_public_toolkit_tweaker_preview_apply_family(backend, variable, source, target, tmp_path):
    with journey(backend, variable, tmp_path, source, target) as (owner, relay, evidence, specs, profile, _):
        before = document(owner)
        source_before = document(owner, "//WFTEST/11/p/20")
        assert owner.command("PROJECT USE OTHER").code == 200
        other_before = document(owner, "//OTHER")
        assert owner.command("PROJECT USE WFTEST").code == 200
        preview, call = cli(relay, evidence, specs, profile, source, target)
        assert preview["phase"] == "preview_complete" and not preview["created"]
        assert not preview["writes"] and not any(c.startswith(("DBADD", "DBSET", "PP SAVE")) for c in call["commands"])
        assert document(owner) == before and document(owner, "//WFTEST/11/p/20") == source_before
        final, call = cli(relay, evidence, specs, profile, source, target, extra=apply_flags(preview))
        assert final["phase"] == "complete" and final["created"] and final["applied"] and final["accepted"]
        assert final["planned_assignments_complete"] and not final["outcome_uncertain"]
        assert final["xml_comparison"] == {"formatting_only_container_indentation_compared": False,
                                           "xml_space_preserve_override_enforced": True,
                                           "mixed_content_text_whitespace_compared": True,
                                           "whitespace_only_leaf_values_compared": True}
        assert final["plan_sha256"] == preview["plan_sha256"] == plan_digest(final["plan"])
        assert final["verified_expected_parameters"] == final["plan"]["expected_parameters"]
        assert [{k: v for k, v in row.items() if k != "confirmed"} for row in final["assignments"]] == final["plan"]["assignments"]
        assert all(row["confirmed"] for row in final["assignments"])
        assert not any(final[k] for k in ("project_saved", "source_deleted", "readdressed", "hardware_programmed",
                                         "automatic_retries", "rollback_performed"))
        assert sum(c.startswith("DBADDSAFE ") for c in call["commands"]) == 1
        assert sum(c.startswith("PP SAVE_TO_SOURCE ") for c in call["commands"]) == 1
        assert len([c for c in call["commands"] if c.startswith("DBSETSAFE ")]) == 5
        assert not any(c.startswith(("DBSET ", "DBSETXML ")) for c in call["commands"])
        added = call["commands"].index("DBADDSAFE //WFTEST/11 Unit 21 Replacement & Ω")
        assert call["statuses"][added] == 301 and call["terminals"][added] == "OID=" + final["oid"]
        assert uuid.UUID(final["oid"]) and final["oid"] not in before
        assert document(owner, "//WFTEST/11/p/20") == source_before
        after = document(owner)
        unchanged_after_removing_new(before, after, final["oid"])
        assert f"<Address>21</Address>" in document(owner, "//WFTEST/11/p/21")
        expected = final["verified_expected_parameters"]
        assert expected["Application"] == [56, 255] and expected["UnitAddress"] == [20]
        assert expected["UnitName"] == "SOURCE  " and expected["Project"] == "WFTEST  "
        if source == "DIMDN8":
            assert expected["MaxDimmingLevel"] == [0] * 4 and expected["PowerUpDelay"] == [1, 2, 3, 4]
            assert expected["InterLockingChannel"] == [4]
        elif source == "RELDN8":
            assert expected["GroupAddress"] == [10, 255, 30, 40, 70, 80, 90, 100, 255, 255, 255, 255, 120, 130, 140, 254]
            assert expected["LogicGA13Associations"] == [0, 1, 0, 1, 1, 0, 1, 0, 0, 0, 0, 0]
        elif target in ("KEYC4", "BCN2B"):
            assert expected["GroupAddress"] == [0, 10, 254, 255, 255, 255, 255, 255, 173]
            assert expected["IndicatorFunction"] == [0, 2, 2, 1, 0, 0, 0, 0]
            assert expected["LearnedFlag"] == [0]
            if target == "BCN2B":
                assert expected["BistableSwitchBlock"] == expected["GroupAssertOnPowerup"] == [0]
        else:
            assert expected["IndicatorFunction"] == [0, 1, 2, 3] and expected["LearnedFlag"] == [0]
        assert owner.command("PROJECT USE OTHER").code == 200
        assert document(owner, "//OTHER") == other_before


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_toolkit_tweaker_stale_plan_and_alias_collision_refuse(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, specs, profile, _):
        preview, _ = cli(relay, evidence, specs, profile)
        assert owner.command("DBSET //WFTEST/11/p/20/TagName changed after review").code == 200
        before = document(owner)
        refused, call = cli(relay, evidence, specs, profile, expected=1, extra=apply_flags(preview))
        assert "Fresh plan differs" in refused["error"]
        assert not state(refused)["writes"] and not state(refused)["outcome_uncertain"]
        assert not any(c.startswith(("DBADD", "DBSET", "PP SAVE")) for c in call["commands"])
        assert document(owner) == before
        # Legacy generic XML preserves literal aliases; the frontend must
        # detect collision without asking ADD to resolve the ambiguity.
        assert owner.command("DBSET //WFTEST/11/p/22/Address 021").code == 200
        before = document(owner)
        refused, call = cli(relay, evidence, specs, profile, expected=1)
        assert "occupied" in refused["error"]
        assert not state(refused)["writes"] and not any(c.startswith("PP ") for c in call["commands"])
        assert document(owner) == before


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
@pytest.mark.parametrize("verb", ["DBADDSAFE", "PP SAVE_TO_SOURCE", "PP SET"], ids=["lost-add", "lost-save", "lost-set"])
def test_public_toolkit_tweaker_lost_receipt_retains_scaffold_without_replay(backend, variable, verb, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, _, evidence, specs, profile, endpoint):
        before = document(owner)
        with FaultGate(endpoint, verb, "drop") as relay:
            preview, _ = cli(relay, evidence, specs, profile)
            failed, call = cli(relay, evidence, specs, profile, expected=1, extra=apply_flags(preview))
            evidence["fault_wires"] = relay.evidence()
        result = state(failed)
        assert result["outcome_uncertain"] and not result["accepted"]
        assert result["plan_sha256"] == plan_digest(result["plan"])
        assert not result["automatic_retries"] and not result["rollback_performed"]
        assert sum(c.startswith(verb + " ") for c in call["commands"]) == 1
        assert call["commands"][-1].startswith(verb + " ")
        after = document(owner)
        issued = re.search(r"<Unit><OID>([^<]+)</OID><TagName>Replacement &amp; Ω</TagName><Address>21</Address>", after)
        assert issued is not None, after
        unchanged_after_removing_new(before, after, issued[1])
        last = evidence["fault_wires"][-1]
        backend_terminal = bytes.fromhex(last["lost_backend_terminal_hex"]).decode()
        assert ("301 OID=" if verb == "DBADDSAFE" else "200 ") in backend_terminal
        if verb == "DBADDSAFE":
            assert not result["created"] and not any(c.startswith(("DBSET ", "PP SAVE")) for c in call["commands"])
        elif verb == "PP SAVE_TO_SOURCE":
            assert result["created"] and not result["applied"] and result["oid"] == issued[1]
            assert '<PP Name="PowerUpDelay" Value="1 2 3 4"/>' in document(owner, "//WFTEST/11/p/21")
        else:
            assert result["created"] and not result["applied"] and result["staging_uncertain"]
            assert result["oid"] == issued[1]
            assert not any(c.startswith("PP SAVE") for c in call["commands"])
            assert result["staging_writes"][-1]["confirmed"] is False


@pytest.mark.parametrize("backend,variable", BACKENDS, ids=["mock", "daemon"])
def test_public_toolkit_tweaker_declared_assignment_failure_keeps_reviewed_plan(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, _, evidence, specs, profile, endpoint):
        before = document(owner)
        with FaultGate(endpoint, "PP SET", "refuse", occurrence=3) as relay:
            preview, _ = cli(relay, evidence, specs, profile)
            partial, call = cli(relay, evidence, specs, profile, expected=1, extra=apply_flags(preview))
            evidence["fault_wires"] = relay.evidence()
        assert partial["phase"] == "complete" and partial["applied"] and not partial["accepted"]
        assert not partial["planned_assignments_complete"] and not partial["outcome_uncertain"] and not partial["staging_uncertain"]
        assert set(partial["failed_writes"]) == {"Application"}
        assert partial["plan_sha256"] == preview["plan_sha256"] == plan_digest(partial["plan"])
        assert partial["plan"]["expected_parameters"]["Application"] == [56, 255]
        assert partial["verified_expected_parameters"]["Application"] == [0, 0]
        assert sum(c.startswith("PP SAVE_TO_SOURCE ") for c in call["commands"]) == 1
        unchanged_after_removing_new(before, document(owner), partial["oid"])


def test_public_toolkit_tweaker_authentication_refuses_before_planning_or_writes(tmp_path):
    token = tmp_path / "auth.txt"
    token.write_text("a" * 64 + "\n", encoding="utf-8")
    token.chmod(0o600)
    with journey("cmqttd", "CBUS_CMQTTD_BIN", tmp_path, auth_file=token) as (owner, relay, evidence, specs, profile, _):
        before = document(owner)
        failed, call = cli(relay, evidence, specs, profile, expected=1)
        assert call["commands"][:3] == ["PROJECT USE WFTEST", "DBGETXML //WFTEST", "GET //WFTEST/11 *"]
        assert len(call["commands"]) == 4 and call["commands"][-1].startswith("PP LOCK ")
        assert call["statuses"] == [200, 344, 300, 420]
        assert not state(failed)["writes"] and document(owner) == before
        wrong = tmp_path / "wrong.txt"
        wrong.write_text("b" * 64 + "\n", encoding="utf-8")
        wrong.chmod(0o600)
        failed, call = cli(relay, evidence, specs, profile, expected=1, extra=("--auth-token-file", str(wrong)))
        assert call["commands"] == ["LOGIN " + "b" * 64] and call["statuses"] == [420]
        assert "b" * 64 not in call["stdout"] + call["stderr"]
        assert state(failed)["commands"] == ["LOGIN <redacted>"] and not state(failed)["writes"]
        assert document(owner) == before
        preview, _ = cli(relay, evidence, specs, profile, extra=("--auth-token-file", str(token)))
        assert preview["phase"] == "preview_complete" and not preview["writes"]


def test_public_toolkit_tweaker_local_guards_never_connect(tmp_path):
    specs = tmp_path / "specs"
    profile = profile_files(specs, "DIMDN8", "DIMDU4")
    with no_contact_trap() as endpoint:
        host, port = endpoint.split(":")
        argv = [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", host, "--port", port,
                "conversion", "tweak", "//WFTEST/11/p/20", "--source-type", "DIMDN8", "--target-type", "DIMDU4",
                "--source-spec", profile["source_spec"], "--target-spec", profile["target_spec"], "--spec-dir", str(specs),
                "--firmware", profile["firmware"], "--catalog-number", "SYNTHETIC", "--target-address", "21", "--apply"]
        result = subprocess.run(argv, text=True, capture_output=True, timeout=15)
        value = json.loads(result.stdout or result.stderr)
        assert result.returncode == 1 and "requires --exclusive-project" in value["error"]
        associated_evidence(tmp_path / "toolkit-tweaker-local-evidence.json", {
            "argv": argv, "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
            "connections": 0, "original_execution": False, "physical_acceptance": False})
