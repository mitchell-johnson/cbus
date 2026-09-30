"""One complete classic DLT edit/save/deliver/recover journey on scripted PCI.

The independent peer checks native wire correlation and owns synthetic memory.
Indicator layouts/controls come from the existing source-backed DLT editor;
literal expected bytes are derived here, independently of the delivery adapter.
No vendor files, physical endpoints, original GUI or home projects are used.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import pytest

from cbus_toolkit.memory import MemoryCodec, MemoryImage
from cbus_toolkit.dlt_indicators import FIELDS
from test_dlt_indicators import fixture
from test_cmqtt_programming_methods_interop import (
    ProgrammingPCI, _reply, needs_cmqttd, reply_frame, running_daemon, write_project,
)


TARGET = "//TEST/254/p/5"


class FirstEditPCI(ProgrammingPCI):
    """Literal direct unit-4 correlation, without changing the shared unit-5 peer."""

    def _parse(self, line):
        code = b""
        if line and ord("g") <= line[-1] <= ord("z"):
            code, line = line[-1:], line[:-1]
        assert line.startswith(b"\\"), line
        raw = bytes.fromhex(line[1:].decode("ascii"))
        assert raw[:3] == b"\x46\x04\x00", raw.hex()
        assert not sum(raw) & 0xFF, raw.hex()
        cal = raw[3:-1]
        with self._peer_lock:
            self.requests.append({"wire_hex": raw.hex().upper(), "cal_hex": cal.hex().upper(),
                                  "envelope": "direct", "confirmation": code.decode() or None,
                                  "time": time.monotonic()})
        return code, cal, "direct"

    def _frames(self, cals, stale, envelope):
        assert envelope == "direct"
        self.noise_frames += 3
        return (reply_frame((253,), cals[0], unit=4)
                + reply_frame((), cals[0], unit=5)
                + reply_frame((), stale, unit=4)
                + b"".join(reply_frame((), cal, unit=4) for cal in cals))

    def _command(self, line, context):
        if line.startswith(b"\\"):
            code, cal, envelope = self._parse(line)
            if cal[:1] == b"\x21":
                data = b"KEYML5" if cal[1] == 1 else b"2.1.00"
                return self._answer(code, [_reply(cal[1], data)],
                                    _reply(cal[1] ^ 3, data), envelope)
            self.requests.pop()
        return super()._command(line, context)


class IndicatorPCI(ProgrammingPCI):
    unit_type = b"KEYML5"
    firmware = b"2.1.00"

    def _command(self, line, context):
        # Preserve the independently checked protocol, replacing only the
        # scripted unit's literal profile responses.
        if line.startswith(b"\\"):
            code, cal, envelope = self._parse(line)
            if cal[:1] == b"\x21":
                data = self.unit_type if cal[1] == 1 else self.firmware
                return self._answer(code, [_reply(cal[1], data)],
                                    _reply(cal[1] ^ 3, data), envelope)
            self.requests.pop()  # Parent parses and records non-IDENTIFY once.
        return super()._command(line, context)


def invoke(port, *args, status=0):
    result = subprocess.run([
        sys.executable, "-m", "cbus_toolkit", "cgate", "--host", "127.0.0.1",
        "--port", str(port), "--timeout", "8", *map(str, args),
    ], capture_output=True, text=True, timeout=60)
    if result.returncode != status and "--plan" in args:
        plan_path = Path(args[args.index("--plan") + 1])
        (plan_path.parent / "unexpected-cli-result.json").write_text(json.dumps({
            "expected_exit": status, "actual_exit": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr,
        }, indent=2))
    assert result.returncode == status, result.stdout + result.stderr
    return json.loads(result.stdout if status == 0 else result.stderr)


def unit(port, *args, **kwargs):
    return invoke(port, "unit", "--lock-address", "//TEST/254",
                  "--source", "/db" + TARGET, *args, **kwargs)


def setup(tmp_path, **peer_options):
    specs = tmp_path / "specs"
    specs.mkdir()
    spec = fixture()
    root = ET.Element("UnitSpecification")
    ET.SubElement(root, "Type").text = "KEYL5"
    parameters = ET.SubElement(root, "Parameters")
    for parameter in spec.parameters.values():
        node = ET.SubElement(parameters, "Param")
        for key, value in parameter.fields.items():
            ET.SubElement(node, key).text = value
    for filename in ("KEYL5.xml", "KEYML5.xml", "KEYBL5.xml"):
        ET.ElementTree(root).write(specs / filename, encoding="utf-8")
    values = spec.defaults()
    values.update(IndicatorPressedLevel="10", DisableTimerFlash="1", EnableNightlightControl="1")
    image = MemoryCodec(spec).encode_many(values).apply(
        MemoryImage.from_bytes(bytes(range(128))))
    memory = {"standard": dict(enumerate(image.read(0, 128))),
              "paged": {}, "oem": {}, "goc": {}}
    project = tmp_path / "project.xml"
    write_project(project, ())
    document = ET.parse(project)
    target = document.find(".//Unit[@oid='target']")
    target.find("UnitType").text = "KEYML5"
    target.find("FirmwareVersion").text = "2.1.00"
    ET.SubElement(target, "CatalogNumber").text = "5055DL"
    ET.SubElement(target, "SerialNumber").text = "1.2.3.4"
    ET.SubElement(target, "TagName").text = "Indicator"
    ET.SubElement(target, "UnitName").text = "DLT"
    for name, value in values.items():
        ET.SubElement(target, "PP", Name=name, Value=value)
    document.write(project, encoding="utf-8")
    peer = IndicatorPCI((), [("direct", 0, 128)], memory, **peer_options)
    return specs, project, peer


def prepare(port, tmp_path, specs):
    before = tmp_path / "before.json"
    unit(port, "export", before)
    result = subprocess.run([
        sys.executable, "-m", "cbus_toolkit", "dlt", "--spec-dir", str(specs),
        "indicators", "plan", "--file", str(before),
        "--indicator-control", "page_fallback=yes",
        "--indicator-control", "duration_seconds=5",
        "--indicator-control", "pressed_level=12",
        "--indicator-control", "nightlight_keys=yes",
        "--indicator-control", "first_key_throwaway=yes",
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    plan = tmp_path / "plan.json"
    plan.write_text(result.stdout)
    edited = unit(port, "dlt-labels", "--spec-dir", specs, "--plan", plan)
    assert edited["saved"] and edited["verified"]
    after = unit(port, "show")
    for action in ("save", "close", "load"):
        invoke(port, "project", action, "TEST")
    assert unit(port, "show") == after
    return plan, json.loads(before.read_text())["parameters"], after


def deliver(port, plan, journal=None, *, status=0, dry_run=False):
    flags = ["--dry-run"] if dry_run else ["--journal", journal]
    return invoke(port, "physical-pp", "dlt-indicators", TARGET, "--plan", plan,
                  *flags, status=status)


@needs_cmqttd
def test_complete_typed_editor_saved_project_and_physical_delivery(tmp_path):
    specs, project, peer = setup(tmp_path)
    original_memory = deepcopy(peer.memory)
    journal = tmp_path / "attempt.json"
    with peer.running() as pci, running_daemon(tmp_path, pci, project, specs) as port:
        plan, before, after = prepare(port, tmp_path, specs)
        preview = deliver(port, plan, dry_run=True)
        assert preview["staged_readback_verified"] and not preview["saved"]
        assert peer.memory == original_memory and not peer.stores
        result = deliver(port, plan, journal)
        assert result["saved"] and result["fresh_physical_readback_verified"]
        assert result["save_attempts"] == 1
        evidence = result["dlt_indicators_evidence"]
        assert evidence["database_edited_state_verified"]
        assert evidence["physical_original_baseline_verified"]
        assert evidence["physical_loaded_identity_verified"]
        assert evidence["fresh_physical_identity_verified"]
        assert evidence["unchanged_indicator_fields_verified"]
        assert evidence["complete_indicator_bytes_verified"]
        assert result["typed_validation"]["loaded"]["raw_hex"] == "af8e"
        assert result["typed_validation"]["fresh"]["raw_hex"] == "c5be"
        assert result["typed_validation"]["loaded"]["loaded_identity"] == {
            "UnitType": "KEYML5", "FirmwareVersion": "2.1.00", "Source": TARGET}
        assert result["typed_validation"]["fresh"]["loaded_identity"] == (
            result["typed_validation"]["loaded"]["loaded_identity"])
        # A separate CLI process opens another physical session and reads every
        # control, beyond the adapter's own verification session.
        check = invoke(port, "physical-pp", "inspect", TARGET, "--method", "direct",
                       *[item for name in FIELDS for item in ("--parameter", name)])
        assert {k: int(v, 0) for k, v in check["values"].items()} == {
            k: int(after[k], 0) for k in FIELDS}
        assert unit(port, "show") == after
        assert before["TimerDuration"] != after["TimerDuration"]
        expected_memory = deepcopy(original_memory)
        expected_memory["standard"].update({0x33: 0xC5, 0x34: 0xBE})
        assert peer.memory == expected_memory
        assert peer.noise_frames > 0
        assert json.loads(journal.read_text())["complete"]
        (tmp_path / "journey-result.json").write_text(json.dumps({
            "project_save_close_load_verified": True,
            "meaningful_typed_control_change": True,
            "physical_raw_before": "af8e", "physical_raw_after": "c5be",
            "entire_peer_memory_preserved_except_two_indicator_bytes": True,
            "independent_fresh_cli_inspection_verified": True,
            "result": result,
        }, indent=2))


@needs_cmqttd
def test_missing_loaded_identity_contract_real_cli_refuses_before_first_set(tmp_path, monkeypatch):
    """Exercise unsupported metadata over real transport, with no STORE.

    Strip only the proposed physical INFO attributes at the client boundary so
    this negative stays valid after the centrally owned binary is upgraded.
    """
    from contextlib import redirect_stdout, redirect_stderr
    import io
    from cbus_toolkit import cli
    from cbus_toolkit.cgate import CGateClient, CGateResponse
    from cbus_toolkit.programming import xml_text
    specs, project, peer = setup(tmp_path)
    with peer.running() as pci, running_daemon(tmp_path, pci, project, specs) as port:
        plan, _, after = prepare(port, tmp_path, specs)
        original = CGateClient.command
        commands = []
        def unsupported(self, command, *args, **kwargs):
            commands.append(command)
            reply = original(self, command, *args, **kwargs)
            if command.startswith("PP INFO "):
                root = ET.fromstring(xml_text(reply))
                root.attrib.clear()
                lines = ("343-Begin XML snippet", "347-" + ET.tostring(root, encoding="unicode"),
                         "344 End XML snippet")
                return CGateResponse(lines, lines[-1], 344)
            return reply
        monkeypatch.setattr(CGateClient, "command", unsupported)
        output, error = io.StringIO(), io.StringIO()
        journal = tmp_path / "attempt.json"
        before = deepcopy(peer.memory)
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["cgate", "--host", "127.0.0.1", "--port", str(port),
                "physical-pp", "dlt-indicators", TARGET, "--plan", str(plan),
                "--journal", str(journal)])
        assert status == 1
        result = json.loads(error.getvalue())
        assert "identity contract is missing or unsupported" in result["error"]
        assert result["dlt_indicators_evidence"]["database_edited_state_verified"]
        assert not result["dlt_indicators_evidence"]["physical_loaded_identity_verified"]
        assert not any(row.startswith(("PP SET ", "PP SAVE")) for row in commands)
        assert peer.memory == before and not peer.stores and not journal.exists()
        assert unit(port, "show") == after


@needs_cmqttd
def test_lost_ack_no_replay_and_restart_read_only_recovery(tmp_path):
    journal = tmp_path / "attempt.json"
    specs, project, peer = setup(tmp_path, drop_on=("post-send", 0), journal_probe=journal)
    with peer.running() as pci:
        with running_daemon(tmp_path, pci, project, specs) as port:
            plan, _, _ = prepare(port, tmp_path, specs)
            failed = deliver(port, plan, journal, status=1)
            evidence = failed["physical_programming_evidence"]
            assert evidence["save_attempts"] == 1 and evidence["save_outcome_uncertain"]
            assert not evidence["saved"] and evidence["automatic_write_retries"] == 0
        assert peer.dropped and len(peer.stores) == 1
        assert peer.journal_at_first_store["phase"] == "save-sent"
        count = len(peer.requests)
        with running_daemon(tmp_path, pci, project, specs, log_name="restart.log") as port:
            refused = deliver(port, plan, tmp_path / "attempt2.json", status=1)
            assert "incomplete save" in refused["error"]
            assert len(peer.requests) == count
            recovered = invoke(port, "physical-pp", "recover", "--journal", journal)
            assert recovered["conclusive"] and recovered["resolved"]
            assert recovered["outcome"] == "observed_partial"
            assert len(peer.stores) == 1 and not peer.unlocks and not peer.nvm
            assert all(bytes.fromhex(row["cal_hex"])[0] in (0x21, 0x1A)
                       for row in peer.requests[count:])
            # A resolved partial observation is not completion and cannot bypass
            # the original physical baseline on a later newly named attempt.
            refused = deliver(port, plan, tmp_path / "attempt3.json", status=1)
            assert "loaded values differ" in refused["error"]
            assert len(peer.stores) == 1


@needs_cmqttd
@pytest.mark.parametrize("changed", ["physical-type", "physical-firmware", "shared-bit", "edited-bit"])
def test_stale_physical_identity_or_baseline_refused_before_store(tmp_path, changed):
    specs, project, peer = setup(tmp_path)
    with peer.running() as pci, running_daemon(tmp_path, pci, project, specs) as port:
        plan, _, after = prepare(port, tmp_path, specs)
        if changed == "physical-type":
            peer.unit_type = b"KEYBL5"
        elif changed == "physical-firmware":
            peer.firmware = b"2.1.01"
        else:
            peer.memory["standard"][0x34 if changed == "shared-bit" else 0x33] ^= 0x80 if changed == "shared-bit" else 1
        before = deepcopy(peer.memory)
        journal = tmp_path / "refused.json"
        result = deliver(port, plan, journal, status=1)
        if changed in ("physical-type", "physical-firmware"):
            # Missing metadata on an old binary must not masquerade as proof
            # that exact physical profile refusal has been integrated.
            assert "Loaded physical identity differs from the exact DLT indicator plan" in result["error"]
        else:
            assert "loaded values differ" in result["error"]
        assert not peer.stores and peer.memory == before and not journal.exists()
        assert result["dlt_indicators_evidence"]["database_edited_state_verified"]
        assert not result["dlt_indicators_evidence"]["physical_original_baseline_verified"]
        assert unit(port, "show") == after


@needs_cmqttd
def test_database_edit_and_plan_guards_before_physical_io(tmp_path):
    from cbus_toolkit.dlt_indicators import DltIndicatorPlan
    from dataclasses import replace
    specs, project, peer = setup(tmp_path)
    with peer.running() as pci, running_daemon(tmp_path, pci, project, specs) as port:
        plan, _, after = prepare(port, tmp_path, specs)
        original = DltIndicatorPlan.from_dict(json.loads(plan.read_text()))
        count = len(peer.requests)
        # Forge changes while retaining valid ranges/canonical serialization.
        forged = replace(original, changes={**original.changes, "TimerDuration": (6,)})
        plan.write_text(json.dumps(forged.as_dict()))
        assert "ordered controls" in deliver(port, plan, tmp_path / "forged.json", status=1)["error"]
        assert len(peer.requests) == count
        plan.write_text(json.dumps(original.as_dict()))
        # A saved database that has drifted is distinct from a physical baseline
        # that still matches; it must refuse instead of proceeding from either.
        unit(port, "set", "TimerDuration", "6")
        result = deliver(port, plan, tmp_path / "db-drift.json", status=1)
        assert "database indicator state differs" in result["error"]
        assert len(peer.requests) == count and not peer.stores
        unit(port, "set", "TimerDuration", "5")
        assert unit(port, "show") == after
        # A valid but different catalogue/profile is not silently repinned.
        drifted = replace(original, identity=("KEYBL5", "2.1.00", "5085DL"), unit_type="KEYBL5")
        plan.write_text(json.dumps(drifted.as_dict()))
        assert "KEYML5 2.1.00" in deliver(port, plan, tmp_path / "identity.json", status=1)["error"]
        assert len(peer.requests) == count and not peer.stores


@needs_cmqttd
@pytest.mark.parametrize("failure", [OSError("synthetic journal fsync failure"), KeyboardInterrupt()])
def test_pre_save_journal_failure_or_interruption_never_programs(tmp_path, monkeypatch, failure):
    from contextlib import redirect_stdout, redirect_stderr
    import io
    from cbus_toolkit import cli
    from cbus_toolkit.physical_pp_journal import PhysicalPPJournal
    specs, project, peer = setup(tmp_path)
    before = deepcopy(peer.memory)
    with peer.running() as pci, running_daemon(tmp_path, pci, project, specs) as port:
        plan, _, after = prepare(port, tmp_path, specs)
        def fail(*args, **kwargs):
            raise failure
        monkeypatch.setattr(PhysicalPPJournal, "create", fail)
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(["cgate", "--host", "127.0.0.1", "--port", str(port),
                "physical-pp", "dlt-indicators", TARGET, "--plan", str(plan),
                "--journal", str(tmp_path / "attempt.json")])
        assert status == (130 if isinstance(failure, KeyboardInterrupt) else 1)
        result = json.loads(error.getvalue())
        evidence = result["physical_programming_evidence"]
        assert evidence["staged_readback_verified"]
        assert not evidence["save_attempted"] and evidence["save_attempts"] == 0
        assert not evidence["saved"] and peer.memory == before and not peer.stores
        assert unit(port, "show") == after


@needs_cmqttd
def test_issue36_first_two_controls_wfdlt_unit4_complete_public_journey(tmp_path):
    """The issue's first edit, with retained public output and literal unit-4 wire."""
    target = "//WFDLT/254/p/4"
    specs, project, original_peer = setup(tmp_path)
    document = ET.parse(project)
    document.find(".//Project/TagName").text = "WFDLT"
    node = document.find(".//Unit[@oid='target']")
    node.find("Address").text = "4"
    next(row for row in node.findall("PP") if row.get("Name") == "EnablePageFallback").set("Value", "0")
    document.write(project, encoding="utf-8")
    original_memory = deepcopy(original_peer.memory)
    original_memory["standard"][0x34] = 0x8A
    assert bytes(original_memory["standard"][address] for address in (0x33, 0x34)) == b"\xaf\x8a"
    peer = FirstEditPCI((), [("direct", 0, 128)], original_memory)
    transcript = []
    journal = tmp_path / "first-edit-attempt.json"

    def public(*arguments, status=0):
        argv = [sys.executable, "-m", "cbus_toolkit", *map(str, arguments)]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        transcript.append({"argv": argv, "exit": result.returncode,
                           "stdout": result.stdout, "stderr": result.stderr})
        (tmp_path / "public-command-transcript.json").write_text(json.dumps(transcript, indent=2))
        assert result.returncode == status, result.stdout + result.stderr
        return json.loads(result.stdout if status == 0 else result.stderr)

    def unit_metadata(raw):
        root = ET.fromstring(raw)
        for child in list(root):
            if child.tag == "PP":
                root.remove(child)
        return ET.tostring(root, encoding="unicode")

    try:
        with peer.running() as pci, running_daemon(tmp_path, pci, project, specs) as port:
            def remote(*arguments, status=0):
                return public("cgate", "--host", "127.0.0.1", "--port", str(port),
                              "--timeout", "8", *arguments, status=status)

            def db_unit(*arguments):
                return remote("unit", "--lock-address", "//WFDLT/254",
                              "--source", "/db" + target, *arguments)

            def snapshot(name):
                remote("database", "get-xml", "//WFDLT", "--output", tmp_path / (name + "-project.xml"))
                remote("database", "get-xml", target, "--output", tmp_path / (name + "-unit.xml"))

            snapshot("before")
            before_file = tmp_path / "before-parameters.json"
            db_unit("export", before_file)
            before = json.loads(before_file.read_text())["parameters"]
            planned = public("dlt", "--spec-dir", specs, "indicators", "plan", "--file", before_file,
                             "--indicator-control", "page_fallback=yes",
                             "--indicator-control", "duration_seconds=5")
            assert [(row["control"], row["value"]) for row in planned["requested"]] == [
                ("page_fallback", True), ("duration_seconds", 5)]
            plan_path = tmp_path / "first-edit-plan.json"
            plan_path.write_text(json.dumps(planned, indent=2))
            edited = db_unit("dlt-labels", "--spec-dir", specs, "--plan", plan_path)
            assert edited["saved"] and edited["verified"]
            db_unit("export", tmp_path / "edited-parameters.json")
            after = json.loads((tmp_path / "edited-parameters.json").read_text())["parameters"]
            assert {key: value for key, value in before.items() if key not in FIELDS} == {
                key: value for key, value in after.items() if key not in FIELDS}
            assert {key for key in before if before[key] != after[key]} == {"EnablePageFallback", "TimerDuration"}
            snapshot("edited")
            def project_without_target_pp(filename):
                tree = ET.parse(filename)
                selected = [row for row in tree.findall(".//Network") if row.findtext("Address") == "254"]
                assert len(selected) == 1
                units = [row for row in selected[0].findall("Unit") if row.findtext("Address") == "4"]
                assert len(units) == 1
                for child in list(units[0]):
                    if child.tag == "PP":
                        units[0].remove(child)
                return ET.tostring(tree.getroot())

            assert project_without_target_pp(tmp_path / "before-project.xml") == project_without_target_pp(
                tmp_path / "edited-project.xml")
            for action in ("save", "close", "load"):
                remote("project", action, "WFDLT")
            snapshot("reopened")
            db_unit("export", tmp_path / "reopened-parameters.json")
            assert json.loads((tmp_path / "reopened-parameters.json").read_text())["parameters"] == after
            assert unit_metadata((tmp_path / "before-unit.xml").read_text()) == unit_metadata(
                (tmp_path / "reopened-unit.xml").read_text())
            assert ET.tostring(ET.parse(tmp_path / "edited-project.xml").getroot()) == ET.tostring(
                ET.parse(tmp_path / "reopened-project.xml").getroot())
            preview = remote("physical-pp", "dlt-indicators", target, "--plan", plan_path, "--dry-run")
            assert not preview["saved"] and peer.memory == original_memory and not peer.stores
            result = remote("physical-pp", "dlt-indicators", target, "--plan", plan_path, "--journal", journal)
            assert result["saved"] and result["fresh_physical_readback_verified"] and result["save_attempts"] == 1
            assert result["typed_validation"]["loaded"]["raw_hex"] == "af8a"
            assert result["typed_validation"]["fresh"]["raw_hex"] == "a58e"
            for phase in ("loaded", "staged", "fresh"):
                assert result["typed_validation"][phase]["loaded_identity"] == {
                    "UnitType": "KEYML5", "FirmwareVersion": "2.1.00", "Source": target}
            expected_memory = deepcopy(original_memory)
            expected_memory["standard"].update({0x33: 0xA5, 0x34: 0x8E})
            assert peer.memory == expected_memory
            check = remote("physical-pp", "inspect", target, "--method", "direct",
                           *[word for name in FIELDS for word in ("--parameter", name)])
            assert {key: int(value, 0) for key, value in check["values"].items()} == {
                key: int(after[key], 0) for key in FIELDS}
            assert json.loads(journal.read_text())["complete"]
            stores_before_recovery = len(peer.stores)
            request_boundary = len(peer.requests)
            recovery = remote("physical-pp", "recover", "--journal", journal)
            assert recovery["resolved"] and recovery["outcome"] == "observed_expected"
            assert len(peer.stores) == stores_before_recovery
            assert all(bytes.fromhex(row["cal_hex"])[0] in (0x21, 0x1A)
                       for row in peer.requests[request_boundary:])
            snapshot("after-physical")
            assert ET.tostring(ET.parse(tmp_path / "reopened-project.xml").getroot()) == ET.tostring(
                ET.parse(tmp_path / "after-physical-project.xml").getroot())
            assert peer.noise_frames > 0 and not peer.unlocks and not peer.nvm
            (tmp_path / "first-edit-result.json").write_text(json.dumps({
                "profile": {"project": "WFDLT", "network": 254, "unit": 4},
                "operations": planned["requested"], "literal_before": "af8a", "literal_after": "a58e",
                "all_other_parameters_and_metadata_preserved": True,
                "full_128_byte_memory_preserved_except_two_indicator_bytes": True,
                "project_save_close_load_verified": True, "result": result, "recovery": recovery,
            }, indent=2))
    finally:
        serializable = lambda value: value.hex() if isinstance(value, bytes) else str(value)
        (tmp_path / "peer-memory-before.json").write_text(json.dumps(original_memory, indent=2))
        (tmp_path / "peer-memory-after.json").write_text(json.dumps(peer.memory, indent=2))
        (tmp_path / "peer-wire-and-stores.json").write_text(json.dumps({
            "requests": peer.requests, "stores": peer.stores, "unlocks": peer.unlocks,
            "nvm": peer.nvm, "noise_frames": peer.noise_frames,
        }, indent=2, default=serializable))
