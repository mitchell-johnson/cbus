"""Public synthetic profiles and admission guards; no vendor specifications."""
from argparse import Namespace
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from cbus_toolkit import toolkit_conversion_tweakers as tweakers
from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.toolkit_tweaker_workflow import prepare, _Client, _initial, _digest, _closed
from cbus_toolkit.project import ProjectDocument


def profile_files(directory, source, target):
    """Independent public PP shapes, not a vendor encoder/fixture substitute."""
    directory.mkdir(parents=True, exist_ok=True)
    aliases = {"RELDN8B": "RELDN8", "BCI4A": "BCN4B", "BCNC4B": "BCNC4A"}
    kind = tweakers.admitted(source, target)
    firmware = "2.2.00" if source in tweakers.coupler.COUPLER_SOURCE_TYPES and kind == tweakers.KEY_TWEAKER else (
        "2.5.00" if kind == tweakers.KEY_TWEAKER else "1.2.67" if kind == tweakers.input_unit.INPUT_TWEAKER else "2.7.00")
    source_firmware = "1.2.67" if kind in (tweakers.KEY_TWEAKER, tweakers.input_unit.INPUT_TWEAKER) else "2.7.00"
    values = {}
    for unit_type, is_source in ((source, True), (target, False)):
        actual = aliases.get(unit_type, unit_type)
        name = actual + ".xml"
        shapes = {"Application": ("int", 2, 8), "UnitAddress": ("int", 1, 8),
                  "UnitName": ("sixbit", 8, 6), "Project": ("sixbit", 8, 6)}
        if kind in tweakers.RELAY_TWEAKERS:
            shapes["GroupAddress"] = ("int", 16, 8)
            shapes.update({n: ("int", 4 if unit_type == "RELDN4" else 12, 1)
                           for n in tweakers.RELAY_FIELDS if n != "GroupAddress"})
        elif kind in (tweakers.KEY_TWEAKER, tweakers.input_unit.INPUT_TWEAKER):
            shapes.update({"GroupAddress": ("int", 8 if is_source or kind == tweakers.input_unit.INPUT_TWEAKER else 9, 8),
                           "IndicatorFunction": ("int", 4 if is_source or kind == tweakers.input_unit.INPUT_TWEAKER else 8, 2),
                           "LearnAnyApp": ("bit", 1, 8), "LearnMode": ("bit", 1, 8), "LearnedFlag": ("bit", 1, 8)})
            if kind == tweakers.KEY_TWEAKER or unit_type in ("KEY1", "KEY2", "KEY4"):
                shapes["IndicatorBrightness"] = ("int", 1, 8)
            else:
                shapes["GAVBroadcastFlag"] = ("int", 1, 8)
            if not is_source and source in tweakers.coupler.COUPLER_SOURCE_TYPES:
                shapes.update({n: ("int", 1, 8) for n in ("BistableSwitchBlock", "GroupAssertOnPowerup")})
        else:
            size = 4 if unit_type == "DIMDU4" or unit_type in ("DIMDN4", "DIMDN4F") else 8
            shapes.update({"GroupAddress": ("int", 16, 8), "MaxDimmingLevel": ("int", size, 8),
                           "PowerUpDelay": ("int", size, 8), "InterLockingChannel": ("int", 1, 8)})
        xml = ET.Element("UnitSpecification")
        for key, value in (("Type", actual), ("MinVersion", source_firmware if is_source else firmware),
                           ("MaxVersion", source_firmware if is_source else firmware), ("MemorySize", "2048")):
            ET.SubElement(xml, key).text = value
        params = ET.SubElement(xml, "Parameters")
        offset = 0
        for key, (param_type, count, bits) in shapes.items():
            default = "TARGET" if key == "UnitName" else "WFTEST" if key == "Project" else " ".join(["0"] * count)
            param = ET.SubElement(params, "Param")
            for field, value in (("Name", key), ("Type", param_type), ("Address", str(offset)),
                                 ("ArraySize", str(count)), ("BitSize", str(bits)), ("DefaultValue", default)):
                ET.SubElement(param, field).text = value
            offset += max(8, count)
            if is_source:
                values[key] = default
        (directory / name).write_bytes(ET.tostring(xml))
    values.update(UnitAddress="20", UnitName="SOURCE", Application="56 255")
    if kind in tweakers.RELAY_TWEAKERS:
        values["GroupAddress"] = "0 10 255 30 40 50 60 70 80 90 100 110 120 130 140 254"
        for name in tweakers.RELAY_FIELDS:
            if name != "GroupAddress":
                values[name] = "1 0 1 0 1 1 0 1 0 1 0 1"
    elif kind in (tweakers.KEY_TWEAKER, tweakers.input_unit.INPUT_TWEAKER):
        values.update(GroupAddress="0 10 254 255 173 81 82 83", IndicatorFunction="0 1 2 3", LearnAnyApp="1", LearnMode="1", LearnedFlag="1")
    else:
        size = 4 if source == "DIMDU4" or source in ("DIMDN4", "DIMDN4F") else 8
        values.update(MaxDimmingLevel=" ".join(map(str, range(1, size + 1))),
                      PowerUpDelay=" ".join(["9"] * size), InterLockingChannel="2")
    return {"source_spec": aliases.get(source, source) + ".xml", "target_spec": aliases.get(target, target) + ".xml",
            "firmware": firmware, "source_firmware": source_firmware, "source_values": values}


def arguments(directory, source="DIMDN8", target="DIMDU4", **overrides):
    profile = profile_files(directory, source, target)
    values = dict(source="//WFTEST/11/p/20", target_address=21, source_type=source, target_type=target,
                     source_spec=profile["source_spec"], target_spec=profile["target_spec"], spec_dir=directory,
                     firmware=profile["firmware"], catalog_number="SYNTHETIC", tag_name="Replacement",
                     apply=False, exclusive_project=False, expect_plan_sha256=None, auth_token_file=None)
    return Namespace(**(values | overrides))


def test_frontend_admits_every_existing_pair_and_preserves_profile_rules(tmp_path):
    pairs = [pair for pair in tweakers.REGISTRY if pair not in tweakers.PAIR_REFUSALS
             and tweakers.REFUSALS[tweakers.REGISTRY[pair]] is None
             and tweakers.REGISTRY[pair] not in tweakers.dlt.TWEAKERS]
    assert len(pairs) == 123
    for source, target in pairs:
        directory = tmp_path / (source + "-" + target)
        args = arguments(directory, source, target)
        prepared = prepare(args)
        profile = profile_files(directory, source, target)
        plan = tweakers.plan_writes(source, target, profile["source_values"], set(prepared.target_spec.parameters),
                                   target_firmware=prepared.firmware)
        assert plan.tweaker_class == tweakers.admitted(source, target)
        assert prepared.source_type == source and prepared.target_type == target
        assert prepared.spec_pins and all(len(v) == 64 for v in prepared.spec_pins.values())


@pytest.mark.parametrize("change", [{"apply": True}, {"source": "//WFTEST/011/p/20"},
                                  {"source": "//WFTEST/11/p/020"}, {"target_address": 20},
                                  {"catalog_number": "two words"}])
def test_local_guards_before_connection(tmp_path, change):
    args = arguments(tmp_path)
    for name, value in change.items():
        setattr(args, name, value)
    with pytest.raises(ValueError):
        prepare(args)


def test_unsupported_pair_refuses_before_reading_specs(tmp_path):
    args = arguments(tmp_path)
    args.source_type, args.target_type = "RELDN4", "RELDN8"
    args.spec_dir = tmp_path / "missing"
    with pytest.raises(tweakers.TweakerRefused, match="eight"):
        prepare(args)


def test_private_include_snapshot_hashes_cover_actual_parsed_bytes(tmp_path):
    args = arguments(tmp_path)
    first = prepare(args)
    path = tmp_path / args.target_spec
    xml = ET.fromstring(path.read_bytes())
    xml.find("Parameters/Param/DefaultValue").text = "1 2"
    path.write_bytes(ET.tostring(xml))
    second = prepare(args)
    assert first.target_spec.parameters["Application"].default == "0 0"
    assert second.target_spec.parameters["Application"].default == "1 2"
    assert first.spec_pins[args.target_spec] != second.spec_pins[args.target_spec]
    assert second.spec_pins[args.target_spec] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("command,code,uncertain", [("PP SAVE_TO_SOURCE session", 500, True),
                                                  ("PP SAVE_TO_SOURCE session", 408, True),
                                                  ("DBADDSAFE //WFTEST/11 Unit 21 Test", 401, False)])
def test_persistent_error_keeps_conservative_possible_send(command, code, uncertain):
    class Refusal:
        def command(self, _command):
            raise CGateError(CGateResponse((f"{code} refusal",), f"{code} refusal", code))
    state = _initial()
    with pytest.raises(CGateError):
        _Client(Refusal(), state, "WFTEST").command(command)
    assert state["writes"] == [{"command": command, "attempted": True, "confirmed": False}]
    assert state["outcome_uncertain"] is uncertain


def test_deterministic_digest_normalizes_json_array_representation():
    assert _digest({"values": (1, 2), "before": "x"}) == _digest(json.loads('{"before":"x","values":[1,2]}'))


@pytest.mark.parametrize("command", ["PP SET session Application value", "PP RESET_TO_DEFAULTS session", "PP NEW session KEY1 1.2.67"])
def test_unknown_staging_send_is_uncertain_and_not_replayed(command):
    calls = []
    class LostReply:
        def command(self, value):
            calls.append(value)
            raise RuntimeError("connection ended after possible send")
    state = _initial()
    with pytest.raises(RuntimeError, match="possible send"):
        _Client(LostReply(), state, "WFTEST").command(command)
    assert calls == [command] and not state["writes"]
    assert state["staging_writes"] == [{"command": command, "attempted": True, "confirmed": False}]
    assert state["staging_uncertain"] and state["outcome_uncertain"] and not state["automatic_retries"]


@pytest.mark.parametrize("state", ["open", "opening", "syncing", "malformed"])
def test_every_network_closed_idle_is_required_including_unrelated(state):
    document = ProjectDocument.from_bytes(b"<Project><Address>WFTEST</Address><Network><Address>11</Address>"
        b"</Network><Network><Address>12</Address></Network></Project>")
    calls = []
    class Client:
        def command(self, command):
            calls.append(command)
            path = command.split()[1]
            values = ["InterfaceState=closed", "TargetInterfaceState=closed", "SyncState=idle"]
            if path.endswith("12"):
                values[0 if state in ("open", "opening", "malformed") else 2] = (
                    "InterfaceState=" + state if state != "syncing" else "SyncState=syncing")
            lines = tuple(f"300-{'wrong' if state == 'malformed' and path.endswith('12') else path}: {v}" for v in values)
            return CGateResponse(lines[:-1] + (lines[-1].replace("300-", "300 "),), lines[-1], 300)
    with pytest.raises(ValueError, match="closed and idle|Malformed"):
        _closed(Client(), document, "WFTEST")
    assert calls == ["GET //WFTEST/11 *", "GET //WFTEST/12 *"]


def test_dimmer_catalogue_f_variant_can_use_its_base_specification(tmp_path):
    args = arguments(tmp_path, "DIMDN8F", "DIMDU4")
    path = tmp_path / args.source_spec
    xml = ET.fromstring(path.read_bytes())
    xml.find("Type").text = "DIMDN8"
    path.write_bytes(ET.tostring(xml))
    assert prepare(args).source_spec.unit_type == "DIMDN8"
    xml.find("Type").text = "DIMDN4"
    path.write_bytes(ET.tostring(xml))
    with pytest.raises(ValueError, match="Dimmer specifications"):
        prepare(args)
