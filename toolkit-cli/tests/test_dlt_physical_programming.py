"""Fail-closed typed admission, independent of a new cmqttd binary."""
from copy import deepcopy
import json
import re
import xml.etree.ElementTree as ET

import pytest

from cbus_toolkit.dlt_indicators import ClassicDltIndicators, FIELDS
from cbus_toolkit.dlt_labels import DltLabelError
from cbus_toolkit.dlt_physical_programming import (
    DltPhysicalProgramming, _connected_generation, _loaded_identity,
)
from cbus_toolkit.physical_programming import PhysicalProgramming
from test_dlt_indicators import fixture
from test_physical_programming import PhysicalService, response


TARGET = "//TEST/254/p/5"
IDENTITY = ("KEYML5", "2.1.00", "5055DL")
ATTRIBUTES = 'UnitType="KEYML5" FirmwareVersion="2.1.00" Source="//TEST/254/p/5"'


def xml_reply(document):
    return response("343-Begin XML snippet", "347-" + document,
                    "344 End XML snippet", status=344)


def test_loaded_identity_contract_exact_values():
    assert _loaded_identity(xml_reply("<Parameters " + ATTRIBUTES + "/>"), TARGET, IDENTITY) == {
        "UnitType": "KEYML5", "FirmwareVersion": "2.1.00", "Source": TARGET}


@pytest.mark.parametrize("document", [
    "<Parameters/>",
    '<Parameters UnitType="KEYML5" Source="//TEST/254/p/5"/>',
    "<Parameters " + ATTRIBUTES + ' UnitType="KEYML5"/>',
    "<Parameters " + ATTRIBUTES + ' Contract="v1"/>',
    "<Parameters " + ATTRIBUTES + ' xmlns="unknown"/>',
    "<Wrong " + ATTRIBUTES + "/>",
    "<Parameters " + ATTRIBUTES + ">",
    "<!DOCTYPE Parameters><Parameters " + ATTRIBUTES + "/>",
    ATTRIBUTES.join(("<!ENTITY x 'x'><Parameters ", "/>")),
    "<Parameters " + ATTRIBUTES.replace("KEYML5", "KEYBL5") + "/>",
    "<Parameters " + ATTRIBUTES.replace("KEYML5", "keyml5") + "/>",
    "<Parameters " + ATTRIBUTES.replace("2.1.00", "2.1.01") + "/>",
    "<Parameters " + ATTRIBUTES.replace("2.1.00", "2.1.0") + "/>",
    "<Parameters " + ATTRIBUTES.replace("2.1.00", "2.1.00 ") + "/>",
    "<Parameters " + ATTRIBUTES.replace(TARGET, "/db" + TARGET) + "/>",
    "<Parameters " + ATTRIBUTES.replace(TARGET, "//TEST/254/p/005") + "/>",
    "<Parameters " + ATTRIBUTES.replace(TARGET, "//TEST/254/p/6") + "/>",
    "<Parameters " + ATTRIBUTES.replace(TARGET, "//OTHER/254/p/5") + "/>",
    "<Parameters " + ATTRIBUTES.replace(TARGET, "//TEST/254/p/0") + "/>",
])
def test_missing_duplicate_malformed_or_wrong_loaded_identity_refused(document):
    with pytest.raises(DltLabelError, match="identity"):
        _loaded_identity(xml_reply(document), TARGET, IDENTITY)


@pytest.mark.parametrize("capabilities", [
    {}, {"pci_connected": False, "pci_generation": 7},
    {"pci_connected": True, "pci_generation": True},
    {"pci_connected": True, "pci_generation": "7"},
    {"pci_connected": True, "pci_generation": -1},
])
def test_disconnected_or_malformed_generation_refused(capabilities):
    with pytest.raises(DltLabelError, match="generation"):
        _connected_generation(capabilities)


class IndicatorService(PhysicalService):
    """Owned in-memory PP service; no transport or physical endpoints."""
    def __init__(self):
        super().__init__()
        self.physical_loads = 0
        self.identity_fault = None
        self.generation_fault = None
        self.schema_fault = False
        self.raw_fault = False
        self.database_identity = IDENTITY
        self.before = {
            "TimerDuration": "15", "IndicatorPressedLevel": "10",
            "EnableNightlight": "0", "DisableTimerFlash": "1",
            "EnablePageFallback": "1", "EnableIndicatorPressedLevel": "1",
            "FirstKeyThrowAway": "0", "EnableNightlightOnUserKeys": "0",
            "EnableNightlightOnToggleKey": "0", "EnableNightlightControl": "1",
        }
        self.plan = ClassicDltIndicators(fixture(), "KEYML5").plan(
            self.before, identity=IDENTITY, operations=[
                {"control": "duration_seconds", "value": 5},
                {"control": "pressed_level", "value": 12},
                {"control": "nightlight_keys", "value": True},
                {"control": "first_key_throwaway", "value": True},
            ])
        self.after = {**self.before, **{k: str(v[0]) for k, v in self.plan.changes.items()}}
        self.devices = {TARGET: dict(self.before), "/db" + TARGET: dict(self.after)}

    def _phase(self, session):
        if self.physical_loads > 1:
            return "fresh"
        return "staged" if session["changed"] else "loaded"

    def command(self, command):
        if command.startswith("DBGET "):
            self.commands.append(command)
            return response(*[f"342 {key}={value}" for key, value in zip(
                ("UnitType", "FirmwareVersion", "CatalogNumber"), self.database_identity)], status=342)
        match = re.fullmatch(r"PP INFO (\S+) \*", command)
        if match:
            self.commands.append(command)
            session = self.sessions[match[1]]
            root = ET.Element("Parameters")
            if session["source"] == TARGET:
                phase = self._phase(session)
                root.attrib.update(UnitType="KEYML5", FirmwareVersion="2.1.00", Source=TARGET)
                if self.identity_fault == phase:
                    root.attrib["FirmwareVersion"] = "2.1.01"
                elif self.identity_fault == "missing":
                    root.attrib.clear()
                if self.generation_fault == phase:
                    self.capabilities["pci_generation"] = 8
                elif self.generation_fault == "disconnect-" + phase:
                    self.capabilities["pci_connected"] = False
            for name in FIELDS:
                parameter = fixture().parameters[name]
                node = ET.SubElement(root, "Param")
                for key, value in parameter.fields.items():
                    ET.SubElement(node, key).text = value
                if self.schema_fault and session["source"] == TARGET and name == "TimerDuration":
                    node.find("BitSize").text = "8"
            return xml_reply(ET.tostring(root, encoding="unicode"))
        result = super().command(command)
        if command.startswith("PP LOAD ") and command.endswith(" " + TARGET):
            self.physical_loads += 1
        return result

    def _debug(self, session, start):
        def raw(values):
            flags = ("EnableNightlight", "DisableTimerFlash", "EnablePageFallback",
                     "EnableIndicatorPressedLevel", "FirstKeyThrowAway",
                     "EnableNightlightOnUserKeys", "EnableNightlightOnToggleKey",
                     "EnableNightlightControl")
            return [int(values["TimerDuration"]) | int(values["IndicatorPressedLevel"]) << 4,
                    sum(int(values[name]) << bit for bit, name in enumerate(flags))]
        unit, current = raw(session["loaded"]), raw(session["values"])
        if self.raw_fault:
            unit[1] ^= 0x80
        changed = [0, 0]
        for name in session["changed"]:
            changed[0 if name in ("TimerDuration", "IndicatorPressedLevel") else 1] = 255
        offset = start - 0x33
        unit, current, changed = unit[offset:], current[offset:], changed[offset:]
        cells = lambda values: "|".join(f"{v:02x}" for v in values) + "|"
        return response("199---------|" + cells(range(start, 0x35)), "199-    unit>" + cells(unit),
                        "199- current>" + cells(current), "199-  change>" + cells(changed),
                        "199 endparam>" + "nn|" * len(unit), status=199)


@pytest.mark.parametrize("fault", ["missing", "loaded"])
def test_unsupported_server_or_wrong_identity_refused_before_first_set(tmp_path, fault):
    service = IndicatorService()
    service.identity_fault = fault
    with pytest.raises(DltLabelError, match="identity"):
        DltPhysicalProgramming(service).apply(TARGET, service.plan.as_dict(), journal=tmp_path / "attempt.json")
    assert not any(command.startswith(("PP SET ", "PP SAVE")) for command in service.commands)
    assert service.devices[TARGET] == service.before
    assert not list(tmp_path.iterdir())


def test_identity_is_rechecked_after_staging_before_journal_or_save(tmp_path):
    service = IndicatorService()
    service.identity_fault = "staged"
    with pytest.raises(DltLabelError, match="identity"):
        DltPhysicalProgramming(service).apply(TARGET, service.plan.as_dict(), journal=tmp_path / "attempt.json")
    assert any(command.startswith("PP SET ") for command in service.commands)
    assert not any(command.startswith("PP SAVE") for command in service.commands)
    assert service.devices[TARGET] == service.before and not list(tmp_path.iterdir())


@pytest.mark.parametrize("fault", ["staged", "disconnect-staged", "loaded", "disconnect-loaded"])
def test_generation_change_or_disconnect_refused_before_save(tmp_path, fault):
    service = IndicatorService()
    service.generation_fault = fault
    with pytest.raises(DltLabelError, match="generation"):
        DltPhysicalProgramming(service).apply(TARGET, service.plan.as_dict(), journal=tmp_path / "attempt.json")
    assert not any(command.startswith("PP SAVE") for command in service.commands)
    assert service.devices[TARGET] == service.before
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("fault", ["fresh-identity", "fresh-generation"])
def test_fresh_session_rechecks_identity_and_generation_without_replay(tmp_path, fault):
    service = IndicatorService()
    if fault == "fresh-identity":
        service.identity_fault = "fresh"
    else:
        service.generation_fault = "fresh"
    journal = tmp_path / "attempt.json"
    with pytest.raises(DltLabelError):
        DltPhysicalProgramming(service).apply(TARGET, service.plan.as_dict(), journal=journal)
    assert sum(command.startswith("PP SAVE") for command in service.commands) == 1
    assert service.devices[TARGET] == service.after
    assert json.loads(journal.read_text())["phase"] == "readback-unavailable"
    # Recovery is observation on a new generation; it never repeats SET/SAVE.
    service.identity_fault = service.generation_fault = None
    count = len(service.commands)
    recovered = PhysicalProgramming(service).recover(journal)
    assert recovered["outcome"] == "observed_expected" and recovered["resolved"]
    assert not any(command.startswith(("PP SET ", "PP SAVE")) for command in service.commands[count:])


@pytest.mark.parametrize("fault", ["schema", "raw"])
def test_schema_or_complete_raw_byte_mismatch_refused_before_set(tmp_path, fault):
    service = IndicatorService()
    service.schema_fault, service.raw_fault = fault == "schema", fault == "raw"
    original = deepcopy(service.devices)
    with pytest.raises(DltLabelError):
        DltPhysicalProgramming(service).apply(TARGET, service.plan.as_dict(), journal=tmp_path / "attempt.json")
    assert service.devices == original
    assert not any(command.startswith(("PP SET ", "PP SAVE")) for command in service.commands)


@pytest.mark.parametrize("fault", ["edited-state", "catalogue"])
def test_database_edit_or_catalogue_drift_refused_before_physical_load(tmp_path, fault):
    service = IndicatorService()
    if fault == "edited-state":
        service.devices["/db" + TARGET]["TimerDuration"] = "6"
    else:
        service.database_identity = ("KEYML5", "2.1.00", "5085DL")
    with pytest.raises(DltLabelError, match="database"):
        DltPhysicalProgramming(service).apply(TARGET, service.plan.as_dict(), journal=tmp_path / "attempt.json")
    assert service.physical_loads == 0
    assert not any(command.startswith(("PP SET ", "PP SAVE")) for command in service.commands)


def test_unchanged_shared_field_is_rechecked_on_fresh_load(tmp_path):
    service = IndicatorService()
    original = service._save
    def corrupt(session, destination):
        reply = original(session, destination)
        service.devices[destination]["DisableTimerFlash"] = "0"
        return reply
    service._save = corrupt
    with pytest.raises(DltLabelError, match="fresh values differ"):
        DltPhysicalProgramming(service).apply(TARGET, service.plan.as_dict(), journal=tmp_path / "attempt.json")
    assert sum(command.startswith("PP SAVE") for command in service.commands) == 1
    assert json.loads((tmp_path / "attempt.json").read_text())["phase"] == "readback-unavailable"


def test_single_byte_change_still_journals_both_complete_indicator_bytes(tmp_path):
    service = IndicatorService()
    service.plan = ClassicDltIndicators(fixture(), "KEYML5").plan(
        service.before, identity=IDENTITY,
        operations=[{"control": "duration_seconds", "value": 5}])
    service.after = {**service.before, "TimerDuration": "5"}
    service.devices["/db" + TARGET] = dict(service.after)
    journal = tmp_path / "attempt.json"
    result = DltPhysicalProgramming(service).apply(TARGET, service.plan.as_dict(), journal=journal)
    assert result["complete"] and result["typed_validation"]["fresh"]["raw_hex"] == "a58e"
    ranges = json.loads(journal.read_text())["plan"]["ranges"]
    assert {row["logical_address"] for row in ranges} == {0x33, 0x34}
    assert all(not row["write_planned"] and row["new_sha256"] == row["old_sha256"]
               for row in ranges if row["logical_address"] == 0x34)


def test_owned_mock_contract_success_binds_distinct_states_and_all_ten_fields(tmp_path):
    service = IndicatorService()
    result = DltPhysicalProgramming(service).apply(
        TARGET, service.plan.as_dict(), journal=tmp_path / "attempt.json")
    assert result["complete"] and result["save_attempts"] == 1
    assert result["typed_validation"]["loaded"]["raw_hex"] == "af8e"
    assert result["typed_validation"]["fresh"]["raw_hex"] == "c5be"
    assert service.devices["/db" + TARGET] == service.after
    assert result["dlt_indicators_evidence"]["physical_loaded_identity_verified"]
    assert result["dlt_indicators_evidence"]["fresh_physical_identity_verified"]
    assert not result["dlt_indicators_evidence"]["physical_serial_verified"]


@pytest.mark.parametrize("phase", ["create", "save-sent"])
@pytest.mark.parametrize("failure", [OSError("owned journal durability failure"), KeyboardInterrupt()])
def test_journal_durability_failure_or_interruption_before_save(tmp_path, monkeypatch, phase, failure):
    from cbus_toolkit.physical_pp_journal import PhysicalPPJournal
    service = IndicatorService()
    journal = tmp_path / "attempt.json"
    if phase == "create":
        def fail(*args, **kwargs):
            raise failure
        monkeypatch.setattr(PhysicalPPJournal, "create", fail)
    else:
        original = PhysicalPPJournal.advance
        def fail(self, next_phase, *args, **kwargs):
            if next_phase == "save-sent":
                raise failure
            return original(self, next_phase, *args, **kwargs)
        monkeypatch.setattr(PhysicalPPJournal, "advance", fail)
    with pytest.raises(type(failure)) as caught:
        DltPhysicalProgramming(service).apply(TARGET, service.plan.as_dict(), journal=journal)
    assert caught.value.physical_programming_evidence["staged_readback_verified"]
    assert caught.value.physical_programming_evidence["save_attempts"] == 0
    assert not any(command.startswith("PP SAVE") for command in service.commands)
    assert service.devices[TARGET] == service.before
    if phase == "save-sent":
        assert json.loads(journal.read_text())["phase"] == "planned"


def test_lost_ack_restart_read_only_partial_recovery_never_replays(tmp_path):
    service = IndicatorService()
    journal = tmp_path / "attempt.json"
    def lose_ack(session, destination):
        # The independent failure model applies only the first byte before the
        # connection loses its SAVE reply. No subsequent field is committed.
        service.devices[destination].update(TimerDuration="5", IndicatorPressedLevel="12")
        raise RuntimeError("owned disconnect after first STORE; acknowledgement lost")
    service._save = lose_ack
    with pytest.raises(RuntimeError) as caught:
        DltPhysicalProgramming(service).apply(TARGET, service.plan.as_dict(), journal=journal)
    evidence = caught.value.physical_programming_evidence
    assert evidence["save_attempts"] == 1 and evidence["save_outcome_uncertain"]
    assert evidence["automatic_write_retries"] == 0 and not evidence["saved"]
    assert json.loads(journal.read_text())["phase"] == "save-uncertain"
    restarted = IndicatorService()
    restarted.devices = deepcopy(service.devices)
    restarted.capabilities["pci_generation"] = 1
    with pytest.raises(Exception, match="incomplete save"):
        DltPhysicalProgramming(restarted).apply(
            TARGET, restarted.plan.as_dict(), journal=tmp_path / "second.json")
    assert not restarted.commands
    result = PhysicalProgramming(restarted).recover(journal)
    assert result["resolved"] and result["outcome"] == "observed_partial"
    assert result["recorded_pci_generation"] == 7 and result["fresh_pci_generation"] == 1
    assert not any(command.startswith(("PP SET ", "PP SAVE")) for command in restarted.commands)
    with pytest.raises(DltLabelError, match="loaded values differ"):
        DltPhysicalProgramming(restarted).apply(
            TARGET, restarted.plan.as_dict(), journal=tmp_path / "third.json")
    assert not any(command.startswith("PP SAVE") for command in restarted.commands)
