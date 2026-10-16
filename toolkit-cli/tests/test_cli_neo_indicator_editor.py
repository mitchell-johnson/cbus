"""Public per-unit Neo panel commands, distinct from Unit Magic bulk tools."""
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from test_input_options import DEFAULTS
from cbus_toolkit.neo_indicators import OPTION_LAYOUTS, STYLE_LAYOUTS
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


def write_spec(folder, unit_type="KEYM4", filename=None):
    # Authored schema fixture: the two per-LED fields share each packed byte.
    layouts = {**OPTION_LAYOUTS, **STYLE_LAYOUTS,
               "NightlightColour": ("bit", 0x34, 1, 1, 2, 0),
               "EnableNightlightControl": ("bit", 0x34, 1, 1, 7, 0)}
    defaults = {**DEFAULTS, "NightlightColour": "0", "EnableNightlightControl": "0"}
    parameters = {}
    for name, (kind, address, count, bits, offset, skip) in layouts.items():
        fields = {"Name": name, "Type": kind, "Address": str(address), "ArraySize": str(count),
                  "BitSize": str(bits), "BitAddress": str(offset), "ArraySkip": str(skip),
                  "DefaultValue": defaults[name]}
        parameters[name] = ParameterSpec(name, kind, "fixture.xml", fields)
    spec = UnitSpec(filename or unit_type + ".xml", {"Type": unit_type}, ("fixture.xml",), parameters)
    root = ET.Element("UnitSpecification")
    ET.SubElement(root, "Type").text = unit_type
    params = ET.SubElement(root, "Parameters")
    for param in spec.parameters.values():
        node = ET.SubElement(params, "Param")
        for key, value in param.fields.items():
            ET.SubElement(node, key).text = value
    ET.ElementTree(root).write(Path(folder) / spec.filename, encoding="utf-8", xml_declaration=True)
    return spec


def snapshot(folder, spec, *, firmware="2.5.00", catalog=None, **overrides):
    path = Path(folder) / "snapshot.json"
    path.write_text(json.dumps({"format": "cbus-cli-parameters-v1", "unit_type": spec.unit_type,
                               "firmware": firmware, "catalog_number": catalog,
                               "parameters": {**spec.defaults(), **overrides}}))
    return path


def cli(*args, status=0):
    result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == status, result.stdout + result.stderr
    return json.loads(result.stdout or result.stderr)


def controls(folder, operations):
    path = Path(folder) / "controls.json"
    path.write_text(json.dumps(operations))
    return path


def test_public_plan_keeps_physical_led_order_and_off_colour_read_only(tmp_path):
    spec = write_spec(tmp_path)
    path = snapshot(tmp_path, spec)
    before = path.read_bytes()
    args = ("keys", "--spec-dir", tmp_path)
    view = cli(*args, "neo-indicator-editor-show", spec.filename, path)
    assert view["unit_type"] == "KEYM4"
    ops = controls(tmp_path, [{"led": 2, "on_colour": "blue"}, {"led": 2, "style": "always_off"}])
    plan = cli(*args, "neo-indicator-editor-plan", spec.filename, path, "--controls", ops)
    assert plan["format"] == "cbus-neo-indicator-editor-plan-v1"
    assert plan["saved"] is False
    assert plan["changes"]["PrimaryColour"] == [1, 0, 1, 1, 1, 1, 1, 1]
    assert plan["changes"]["IndicatorFunction"] == [2, 0, 2, 2, 2, 2, 2, 2]
    ops = controls(tmp_path, [{"led": 2, "style": "always_off"}, {"led": 2, "on_colour": "blue"}])
    assert "error" in cli(*args, "neo-indicator-editor-plan", spec.filename, path, "--controls", ops, status=1)
    ops = controls(tmp_path, [{"led": 2, "off_colour": "orange"}])
    assert "error" in cli(*args, "neo-indicator-editor-plan", spec.filename, path, "--controls", ops, status=1)
    assert path.read_bytes() == before


@pytest.mark.parametrize("unit_type,styles,colours", [
    ("KEYA3", [2] * 8, [1] * 8), ("KEYC4", [2] * 8, [0] * 8),
])
def test_public_empty_history_normalizes_all_eight_entries(tmp_path, unit_type, styles, colours):
    spec = write_spec(tmp_path, unit_type)
    path = snapshot(tmp_path, spec, IndicatorFunction="3 3 3 3 3 3 3 3", PrimaryColour="0 0 0 0 0 0 0 0")
    plan = cli("keys", "--spec-dir", tmp_path, "neo-indicator-editor-plan", spec.filename, path,
               "--controls", controls(tmp_path, []))
    assert plan["changes"]["IndicatorFunction"] == styles
    assert plan["changes"].get("PrimaryColour", [0] * 8) == colours


def test_public_snapshot_identity_and_json_guards(tmp_path):
    spec = write_spec(tmp_path)
    args = ("keys", "--spec-dir", tmp_path, "neo-indicator-editor-show", spec.filename)
    path = snapshot(tmp_path, spec, firmware="2.4.99")
    assert "2.5.00" in cli(*args, path, status=1)["error"]
    path = snapshot(tmp_path, spec, catalog="5054NL")
    assert "identity" in cli(*args, path, "--catalog-number", "other", status=1)["error"]
    value = json.loads(path.read_text())
    value["unit_type"] = "KEYB4"
    path.write_text(json.dumps(value))
    assert "error" in cli(*args, path, status=1)
    path = snapshot(tmp_path, spec)
    ops = controls(tmp_path, [])
    for malformed in ('{"led":1}', '[{"led":1,"style":"always_on","style":"always_off"}]'):
        ops.write_text(malformed)
        assert "error" in cli("keys", "--spec-dir", tmp_path, "neo-indicator-editor-plan", spec.filename,
                              path, "--controls", ops, status=1)


def test_legacy_bulk_commands_remain_distinct(tmp_path):
    spec = write_spec(tmp_path)
    path = snapshot(tmp_path, spec)
    args = ("keys", "--spec-dir", tmp_path)
    plan = cli(*args, "neo-style-plan", spec.filename, path, "--colour", "blue", "--style", "always_on")
    assert plan["format"] == "cbus-neo-indicator-styles-plan-v1"
    assert plan["changes"] == {"PrimaryColour": [0] * 8, "IndicatorFunction": [1] * 8}
    plan = cli(*args, "neo-indicator-plan", spec.filename, path, "--brightness", "fixed", "--brightness-percent", 50)
    assert plan["changes"] == {"IndicatorBrightness": [127]}
