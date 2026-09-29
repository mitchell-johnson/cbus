"""Offline Toolkit Document Project HTML from synthetic saved projects."""
from __future__ import annotations

from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit.cli import main
from cbus_toolkit.project import ProjectDocument

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/experiments/2026-09-30/project-documentor-static.json"
WHEN = datetime(2026, 9, 30, 7, 5)


def unit(address, unit_type, *, name=None, firmware="", pps=(), fields="", unit_name="", serial="",
         description=""):
    params = "".join(f'<PP Name="{key}" Value="{value}"/>' for key, value in pps)
    return (f"<Unit><TagName>{escape(name or f'U{address}')}</TagName><Address>{address}</Address>"
            f"<UnitType>{unit_type}</UnitType><UnitName>{unit_name}</UnitName>"
            f"<SerialNumber>{serial}</SerialNumber><FirmwareVersion>{firmware}</FirmwareVersion>"
            f"<Description>{escape(description)}</Description>{fields}{params}</Unit>")


def group(address, name, levels=(), description=""):
    body = "".join(f"<Level><TagName>{tag}</TagName><Address>{lvl}</Address></Level>" for lvl, tag in levels)
    return (f"<Group><TagName>{name}</TagName><Address>{address}</Address>"
            f"<Description>{escape(description)}</Description>{body}</Group>")


def application(address, name, groups=(), description=""):
    return (f"<Application><TagName>{name}</TagName><Address>{address}</Address>"
            f"<Description>{escape(description)}</Description>{''.join(groups)}</Application>")


def network(address, name, *, apps=(), units=(), interface=("CNI", "10.0.0.1:10001")):
    return (f"<Network><TagName>{name}</TagName><Address>{address}</Address>"
            f"<Interface><InterfaceType>{interface[0]}</InterfaceType>"
            f"<InterfaceAddress>{interface[1]}</InterfaceAddress></Interface>"
            f"{''.join(apps)}{''.join(units)}</Network>")


def xml(networks, name="HOUSE"):
    return f"<Installation><Project><TagName>{name}</TagName>{''.join(networks)}</Project></Installation>".encode()


def build(networks, **kwargs):
    return doc.build_model(ProjectDocument.from_bytes(xml(networks)))


def page(networks, **kwargs):
    text, summary = doc.render(build(networks), generated=WHEN, **kwargs)
    return text.split("\r\n"), summary


def section(lines, start, stop):
    first = lines.index(start)
    return lines[first:lines.index(stop, first + 1) if stop else None]


def cli(capsys, *argv):
    status = main(["project", "document", *map(str, argv)])
    captured = capsys.readouterr()
    return status, json.loads(captured.out or captured.err)


LIGHTING = application(56, "Lighting", (group(1, "Kitchen", ((0, "Off"), (255, "Full")), "A<B>"),
                                        group(255, "Spare")), "Main & lights")
TRIGGER = application(202, "Trigger Control", (group(3, "Scenes", ((1, "Movie"),)),))
UNUSED = application(255, "Unused")


def test_page_head_header_contents_and_section_order():
    lines, summary = page([network(254, "Local", apps=(TRIGGER, LIGHTING, UNUSED),
                                   units=(unit(30, "CLK2", name="Clock"), unit(12, "PC_GIM", name="Gim"))),
                           network(1, "Remote", interface=("Bridge", "254/p/1"))])
    assert lines[:16] == [
        "﻿<html>"[1:], "<head>", "<title>", "CBus Project HOUSE", "</title>", '<style type="text/css">',
        "h1 {text-align: center;}", "h2 {text-align: center;}", "div.header_info {text-align: center;}",
        "</style>", "</head>", "<body>", "<h1>Project: HOUSE</h1>", '<div class="header_info">',
        "Generated on: 30 Sep 2026 07:05<br />", "Number of Networks: 2<br />"]
    assert lines[16:19] == ["Number of Units: 2", "</div>", "<hr />"]
    # Contents: ascending networks, then applications except 255, groups except 255, units by address.
    assert section(lines, '<h2><a name="contents">Contents</a></h2>', "<hr />") == [
        '<h2><a name="contents">Contents</a></h2>', '<ul type="square">',
        '<li \\><a href="#1">Remote</a>', '<ul type="disc">', '<li /><a href="#1_Units">Units</a>',
        '<ul type="circle">', "</ul>", "</ul>",
        '<li \\><a href="#254">Local</a>', '<ul type="disc">',
        '<li \\><a href="#254_56">Lighting</a>', '<ul type="circle">', '<li \\><a href="#254_56_1">Kitchen</a>',
        "</ul>",
        '<li \\><a href="#254_202">Trigger Control</a>', '<ul type="circle">',
        '<li \\><a href="#254_202_3">Scenes</a>', "</ul>",
        '<li /><a href="#254_Units">Units</a>', '<ul type="circle">',
        '<li /><a href="#254_unit_12">Gim - PC_GIM</a>', '<li /><a href="#254_unit_30">Clock - CLK2</a>',
        "</ul>", "</ul>", "</ul>"]
    headings = [line for line in lines if line.startswith("<h3>")]
    assert headings == [
        '<h3><a name="1">Network - Remote</a> [ <a href="#contents">top</a> ]</h3>',
        '<h3><a name="1_Units">Units</a> [ <a href="#contents">top</a> ]</h3>',
        '<h3><a name="254">Network - Local</a> [ <a href="#contents">top</a> ]</h3>',
        '<h3><a name="254_56">Application - Lighting</a> [ <a href="#contents">top</a> ]</h3>',
        '<h3><a name="254_56_1">Group - Kitchen</a> [ <a href="#contents">top</a> ]</h3>',
        '<h3><a name="254_202">Application - Trigger Control</a> [ <a href="#contents">top</a> ]</h3>',
        '<h3><a name="254_202_3">Scenes</a> [ <a href="#contents">top</a> ]</h3>',
        '<h3><a name="254_Units">Units</a> [ <a href="#contents">top</a> ]</h3>',
        '<h3><a name="254_unit_12">Gim - PC_GIM</a> [ <a href="#contents">top</a> ]</h3>',
        '<h3><a name="254_unit_30">Clock - CLK2</a> [ <a href="#contents">top</a> ]</h3>']
    assert lines[-3:] == ["</body>", "</html>", ""]
    assert summary["networks"] == [1, 254]


def test_network_application_and_group_blocks():
    lines, _ = page([network(254, "Local", apps=(LIGHTING,))])
    assert section(lines, '<h3><a name="254">Network - Local</a> [ <a href="#contents">top</a> ]</h3>',
                   '<h3><a name="254_56">Application - Lighting</a> [ <a href="#contents">top</a> ]</h3>')[1:] == [
        "Network Number: 254</br>", "Interface Type: CNI</br>", "Interface Address: 10.0.0.1:10001</br>",
        "Current Consumption: not calculated mA</br>", "Current Supplied: not calculated mA</br>",
        "Impedance: not calculated ohms</br>", "Status Report Interval: not documented (unrecovered)<br/>",
        "<ul>"]
    block = section(lines, '<h3><a name="254_56">Application - Lighting</a> [ <a href="#contents">top</a> ]</h3>',
                    '<h3><a name="254_Units">Units</a> [ <a href="#contents">top</a> ]</h3>')
    assert block[1:] == [
        "Address: 56 ($38)</br>", "Description: Main & lights</br>", "<ul>",
        '<h3><a name="254_56_1">Group - Kitchen</a> [ <a href="#contents">top</a> ]</h3>',
        "Address: 1 ($01) <br />", "Description: A&#60;B&#62;<br />",
        "Inputs:", "<ul>", "<li />Unit usage: not documented (unrecovered)", "</ul>",
        "Outputs:", "<ul>", "<li />Unit usage: not documented (unrecovered)", "</ul>",
        "Other:", "<ul>", "<li />Unit usage: not documented (unrecovered)", "</ul>",
        "Levels: ", "<ul>", '<li /><a name="254_56_1_0">Off</a>', '<li /><a name="254_56_1_255">Full</a>', "</ul>",
        "</ul>", "</ul>"]


def test_trigger_group_events_use_action_selector_names_and_mark_unrecovered_units():
    lines, summary = page([network(254, "Local", apps=(TRIGGER,))])
    block = section(lines, '<h3><a name="254_202_3">Scenes</a> [ <a href="#contents">top</a> ]</h3>', "</ul>")
    assert lines[lines.index(block[0]):lines.index(block[0]) + 11] == [
        '<h3><a name="254_202_3">Scenes</a> [ <a href="#contents">top</a> ]</h3>', "Address: 3 ($03) <br />",
        "Description: <br /><br />", "Events:<br />", "Action Selectors: ", "<ul>",
        '<li /><a name="254_202_3_1">Movie</a>', "<ul>", "<li />Action Selector is not used", "</ul>", "</ul>"]
    lines, summary = page([network(254, "Local", apps=(TRIGGER,),
                                   units=(unit(20, "KEYE4", firmware="2.5.00", name="Key"),
                                          unit(21, "CLK2")))])
    start = lines.index('<li /><a name="254_202_3_1">Movie</a>')
    assert lines[start:start + 7] == [
        '<li /><a name="254_202_3_1">Movie</a>', "<ul>", '<a href="#254_unit_20">Key - KEYE4</a>', "<ul>",
        "<li />TNeoProInputDocumentor.ActionSelectorUse: not documented (unrecovered)", "</ul>", "</ul>"]
    assert "<li />Action Selector is not used" not in lines
    assert {"network": 254, "unit": 20, "item": "TNeoProInputDocumentor.ActionSelectorUse",
            "level": [202, 3, 1]} in summary["unrecovered"]


def test_enable_application_levels_are_values():
    enable = application(203, "Enable Control", (group(4, "Mode", ((7, "Seven"),)),))
    lines, _ = page([network(254, "Local", apps=(enable,))])
    assert "Values: " in lines and "Levels: " not in lines


def test_base_documentor_fields_flags_applications_and_escaping():
    units = (unit(5, "PC_GIM", name="In<1>", unit_name="5504GI", serial="1234.5", firmware="1.0",
                  description="x<y>", pps=(("Application", "0x38 0xca"), ("ClockGenEnable", "1"), ("Burden", "0"))),
             unit(6, "CLK2", fields="<Burden>true</Burden>", pps=(("Application", "$FF $FF"),)),
             unit(7, "KEYSCEN4", pps=(("Application", "0xe4 0xff"),)))
    lines, summary = page([network(254, "Local", apps=(LIGHTING,), units=units)])
    assert section(lines, '<h3><a name="254_unit_5">In<1> - PC_GIM</a> [ <a href="#contents">top</a> ]</h3>',
                   '<h3><a name="254_unit_6">U6 - CLK2</a> [ <a href="#contents">top</a> ]</h3>')[1:] == [
        "Unit Address: 5<br />", "Tagname: In<1><br />", "Part name: 5504GI<br />",
        'Application: <a href="#254_56">Lighting</a><br />',
        'Secondary Application: <a href="#254_202">Trigger Control</a><br />',
        "Serial Number: 000012340005<br />", "Firmware Version: 1.0<br />", "Notes: x&#60;y&#62;<br />",
        "Unit clock is enabled<br />", "<br />"]
    six = section(lines, '<h3><a name="254_unit_6">U6 - CLK2</a> [ <a href="#contents">top</a> ]</h3>',
                  '<h3><a name="254_unit_7">U7 - KEYSCEN4</a> [ <a href="#contents">top</a> ]</h3>')
    assert "Application: Unused<br />" in six and "Unit burden is enabled<br />" in six
    assert "Serial Number: No serial #<br />" in six
    assert 'Application: <a href="#254_228">Measurement</a><br />' in lines
    assert [row["status"] for row in summary["units"]] == ["recovered"] * 3
    assert [row["documentor"] for row in summary["units"]] == [
        "TGeneralInputDocumentor", "TClockDocumentor", "TCustomSceneKeyUnitDocumentor"]


def test_heading_only_units_and_unregistered_types_use_the_base():
    lines, summary = page([network(254, "Local", units=(unit(1, "BURDEN"), unit(2, "XC100B"),
                                                        unit(3, "PCI"), unit(4, "burden")))])
    units = section(lines, '<h3><a name="254_Units">Units</a> [ <a href="#contents">top</a> ]</h3>', "<hr />")
    assert units[1:4] == [
        '<h3><a name="254_unit_1">U1 - BURDEN</a> [ <a href="#contents">top</a> ]</h3>',
        '<h3><a name="254_unit_2">U2 - XC100B</a> [ <a href="#contents">top</a> ]</h3>',
        '<h3><a name="254_unit_3">U3 - PCI</a> [ <a href="#contents">top</a> ]</h3>']
    assert units[4] == "Unit Address: 3<br />"
    assert [row["status"] for row in summary["units"]] == ["heading_only", "heading_only", "recovered",
                                                           "recovered"]
    assert summary["units"][3]["documentor"] == "TUnitTypeDocumentor"


@pytest.mark.parametrize("unit_type, firmware, expected", [
    ("KEYA1", "1.3.01", "NeoInput"), ("KEYA1", "1.5.02", "NeoInput"), ("keya1", "1.5.03", "NeoProInput"),
    ("KEYA1", "2.9.99", "NeoProInput"), ("KEYA1", "3.0", "UnitType"), ("KEYA1", "", "UnitType"),
    ("SENLL", "2.0.00", "LightLevelSensor"), ("SENLL", "2.0.01", "ST7LightLevelSensor"),
    ("SENLL", "0.9", "UnitType"), ("SENPIRIB", "2.3.9", "ST7PIRSensor"), ("SENPIRIB", "2.4", "Multisensor"),
    ("SENPIRIB", "2.3.10", "UnitType"), ("WGATE5F", "2.2.89", "WirelessGateway"),
    ("WGATE5F", "2.2.90", "WirelessGatewayAdvanced"), ("WGATE5N", "2.4.99", "WirelessGateway"),
    ("RELDN8", "2.7.00", "Output"), ("DIMPR3A", "", "ErrorReportOutput"), ("NEOI 4FL", "", "RemoteControl"),
    ("KEYGL5", "5.5.00", "UnitType"), ("PC_TSB5", "", "Thermostat"),
])
def test_documentor_selection_by_upper_case_type_and_firmware_range(unit_type, firmware, expected):
    assert doc.select_documentor(unit_type, firmware) == expected


def test_registration_ranges_never_overlap_for_one_type():
    rows = {}
    for unit_type, _, low, high in doc.REGISTRATIONS:
        rows.setdefault(unit_type, []).append((low, high))
    for unit_type, ranges in rows.items():
        for index, (low, high) in enumerate(ranges):
            for other_low, other_high in ranges[index + 1:]:
                assert (doc.version_compare(high, other_low) < 0 or doc.version_compare(other_high, low) < 0
                        or (low, high) == (other_low, other_high)), unit_type


def din(unit_type, groups, *, assoc=None, functions=None, app="0x38 0xff"):
    pps = [("Application", app), ("GroupAddress", " ".join(map(str, groups)))]
    for k, values in (assoc or {}).items():
        pps.append((f"LogicGA{13 + k}Associations", " ".join(map(str, values))))
    if functions is not None:
        pps.append(("LogicFunction", " ".join(map(str, functions))))
    return unit(12, unit_type, firmware="2.7.00", pps=pps)


def table(lines):
    return section(lines, '<table border="1">', "</table>")[1:]


def test_din_output_channels_without_logic_groups():
    groups = [1, 255, 2, 255] + [255] * 12
    lines, summary = page([network(254, "Local", apps=(LIGHTING,), units=(din("RELDN4", groups),))])
    assert table(lines) == [
        "<tr><th>Channel</th><th>Groups</th></tr>",
        '<tr><td>1</td><td><a href="#254_56_1">Kitchen</a></td></tr>', "<tr><td>2</td><td>&nbsp;</td></tr>",
        '<tr><td>3</td><td><a href="#254_56_2">2</a></td></tr>', "<tr><td>4</td><td>&nbsp;</td></tr>"]
    assert lines[lines.index("</table>") + 1] == "<br />"
    assert summary["units"][0]["status"] == "recovered"


def test_din_output_logic_groups_function_column_and_relay_marshalling():
    # RELDN8 channels read PP indexes 1, 2, 3, 4, 7, 8, 9, 10; logic groups live at 12..15.
    groups = [9, 1, 255, 255, 255, 255, 255, 2, 255, 255, 255, 255, 40, 255, 41, 255]
    assoc = {0: [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 2: [0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0],
             1: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]}
    functions = [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    lines, _ = page([network(254, "Local", apps=(LIGHTING,),
                             units=(din("RELDN8", groups, assoc=assoc, functions=functions),))])
    rows = table(lines)
    assert rows[0] == "<tr><th>Channel</th><th>Groups</th><th>Logic Function</th></tr>"
    assert rows[1] == ('<tr><td>1</td><td><a href="#254_56_1">Kitchen</a>, <a href="#254_56_40">40</a>'
                       "</td><td>Max</td></tr>")
    assert rows[2] == '<tr><td>2</td><td><a href="#254_56_41">41</a></td><td>&nbsp;</td></tr>'
    assert rows[3] == "<tr><td>3</td><td>&nbsp;</td><td>&nbsp;</td></tr>"
    assert rows[5] == '<tr><td>5</td><td><a href="#254_56_2">2</a>, <a href="#254_56_41">41</a></td><td>Min</td></tr>'
    assert rows[6] == "<tr><td>6</td><td>&nbsp;</td><td>&nbsp;</td></tr>"
    assert len(rows) == 9


def test_other_output_classes_and_missing_programming_are_marked_partial():
    lines, summary = page([network(254, "Local", units=(unit(1, "DIMDH4"), unit(2, "DIMDN8", firmware="2.7.00")))])
    assert lines.count("Output channels: not documented (unrecovered)<br />") == 2
    assert [row["status"] for row in summary["units"]] == ["partial", "partial"]


def test_bridge_adjacent_network_and_missing_far_side_warning():
    lines, summary = page([network(254, "Local", units=(unit(1, "BRIDGE2N", name="B"), unit(9, "GATEWLS"))),
                           network(1, "Far", interface=("Bridge", "254/p/1"))])
    assert 'Adjacent Network: <a href="#1">Far</a><br/>' in lines
    assert "Bridge connection settings: not documented (unrecovered)<br />" in lines
    assert "WARNING: GATEWLS has no far side Network." in lines
    by_unit = {row["unit"]: row["status"] for row in summary["units"]}
    assert by_unit == {1: "partial", 9: "recovered"}


def test_unrecovered_documentors_are_marked_and_listed_last():
    lines, summary = page([network(254, "Local", units=(unit(3, "PC_TSB5", name="Stat"),
                                                        unit(4, "KEYA1", firmware="1.4.00")))])
    assert "TThermostatDocumentor.DocumentHTML: not documented (unrecovered)<br />" in lines
    assert "TNeoInputDocumentor.DocumentHTML: not documented (unrecovered)<br />" in lines
    tail = section(lines, '<h2><a name="unrecovered">Not documented (unrecovered)</a></h2>', "</ul>")
    assert tail[1:] == [
        "<ul>", "<li />Group Inputs/Outputs/Other unit usage: not documented (unrecovered)",
        '<li /><a href="#254">Local</a>: Network calculator (no --catalog supplied)',
        '<li /><a href="#254">Local</a>: Status Report Interval (status-report interface)',
        '<li /><a href="#254_unit_3">Stat - PC_TSB5</a>: TThermostatDocumentor.DocumentHTML',
        '<li /><a href="#254_unit_4">U4 - KEYA1</a>: TNeoInputDocumentor.DocumentHTML']
    assert lines[lines.index(tail[0]) - 1] == "<hr />"
    assert summary["unit_status"] == {"recovered": 0, "partial": 0, "unrecovered": 2, "heading_only": 0}


def test_calculator_lines_with_a_synthetic_catalogue(tmp_path):
    from cbus_toolkit.calculator import CalculatorCatalog
    catalogue = tmp_path / "cbusunits.xml"
    catalogue.write_text(
        "<CBusUnits><Calculator><MinImpedance>400</MinImpedance><MaxImpedance>1500</MaxImpedance>"
        "<MaxSupplyCurrent>2000</MaxSupplyCurrent></Calculator><Units>"
        "<Unit><CatalogNumber>KEY</CatalogNumber><CurrentDrawn>18</CurrentDrawn><CurrentSupplied>0"
        "</CurrentSupplied><Impedance>110000</Impedance></Unit>"
        "<Unit><CatalogNumber>PS</CatalogNumber><CurrentDrawn>0</CurrentDrawn><CurrentSupplied>350"
        "</CurrentSupplied><Impedance>20000</Impedance></Unit></Units></CBusUnits>")
    units = (unit(1, "KEY4", fields="<CatalogNumber>KEY</CatalogNumber>"),
             unit(2, "POWER", fields="<CatalogNumber>PS</CatalogNumber>", pps=(("Burden", "1"),)))
    text, summary = doc.render(build([network(254, "Local", units=units)]), generated=WHEN,
                               catalog=CalculatorCatalog.load(catalogue))
    lines = text.split("\r\n")
    assert lines[lines.index("Network Number: 254</br>") + 3:][:3] == [
        "Current Consumption: 18 mA</br>", "Current Supplied: 350 mA</br>", "Impedance: 944 ohms</br>"]
    assert not any("calculator" in item["item"].lower() for item in summary["unrecovered"])


def write(tmp_path, networks, filename="house.xml", raw=None):
    path = tmp_path / filename
    path.write_bytes(raw if raw is not None else xml(networks))
    return path


def test_cli_writes_utf8_bom_crlf_deterministically_and_never_overwrites(tmp_path, capsys):
    project = write(tmp_path, [network(254, "Local", apps=(LIGHTING,), units=(unit(5, "CLK2", name="Ü"),))])
    original = project.read_bytes()
    first, second = tmp_path / "a.html", tmp_path / "b.html"
    for target in (first, second):
        status, payload = cli(capsys, project, "--output", target, "--generated-at", "2026-09-30T07:05")
        assert status == 0 and payload["file"] == str(target)
        assert payload["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert first.read_bytes() == second.read_bytes()
    data = first.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf<html>\r\n<head>\r\n") and data.endswith(b"</html>\r\n")
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert "Tagname: Ü<br />".encode() in data
    assert payload["format"] == doc.FORMAT and payload["parity"]["byte_parity"] == "unassessed"
    first.write_bytes(b"keep")
    status, payload = cli(capsys, project, "--output", first)
    assert status == 1 and payload["type"] == "FileExistsError"
    assert first.read_bytes() == b"keep" and project.read_bytes() == original


def test_cli_default_name_network_filter_and_source_timestamp(tmp_path, capsys, monkeypatch):
    project = write(tmp_path, [network(254, "Local", units=(unit(1, "CLK2"),)),
                               network(1, "Other", units=(unit(2, "CLK2"), unit(3, "CLK2")))])
    os.utime(project, (0, 1_700_000_000))
    monkeypatch.chdir(tmp_path)
    status, payload = cli(capsys, project, "--network", "1")
    assert status == 0 and payload["file"] == "HOUSE.html" and payload["networks"] == [1]
    text = (tmp_path / "HOUSE.html").read_bytes().decode("utf-8-sig")
    assert "Generated on: 14 Nov 2023 22:13<br />\r\nNumber of Networks: 1<br />\r\nNumber of Units: 2" in text
    assert 'name="254"' not in text
    status, payload = cli(capsys, project, "--network", "7", "--output", tmp_path / "x.html")
    assert status == 1 and "Network 7 is absent" in payload["error"]
    assert not (tmp_path / "x.html").exists()


def test_cli_rejects_unsafe_default_name(tmp_path, capsys, monkeypatch):
    project = write(tmp_path, None, raw=xml([network(254, "Local")], name="a/b"))
    monkeypatch.chdir(tmp_path)
    status, payload = cli(capsys, project)
    assert status == 1 and "--output" in payload["error"]


def test_cbz_input_matches_xml(tmp_path):
    raw = xml([network(254, "Local", apps=(LIGHTING,), units=(unit(1, "CLK2"),))])
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("HOUSE.xml", raw)
    xml_model = doc.load_model(write(tmp_path, None, raw=raw))
    cbz_model = doc.load_model(write(tmp_path, None, filename="house.cbz", raw=buffer.getvalue()))
    assert cbz_model.format == "legacy-cbz"
    assert doc.render(xml_model, generated=WHEN) == doc.render(cbz_model, generated=WHEN)


def test_duplicate_addresses_are_rejected():
    with pytest.raises(doc.ProjectError, match="Duplicate Unit address 1"):
        build([network(254, "Local", units=(unit(1, "CLK2"), unit(1, "CLK2")))])


def test_committed_static_receipt_matches_the_model():
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["original_executed"] is False
    assert [tuple(row) for row in receipt["registrations"]] == list(doc.REGISTRATIONS)
    assert {short: (row["document_html"], row["action_selector_use"])
            for short, row in receipt["documentor_classes"].items()} == doc.DOCUMENTOR_METHODS
    assert receipt["levels_names"] == {str(key): value for key, value in doc.LEVELS_NAMES.items()}
    assert set(receipt["method_spans"]) == set(doc.ORIGINAL_LITERALS)
    assert all(receipt["checks"].values())
    assert receipt["model_module_sha256"] == hashlib.sha256(Path(doc.__file__).read_bytes()).hexdigest()
    statuses = {row["body_status"] for row in receipt["documentor_classes"].values()}
    assert statuses == {"recovered", "partial", "unrecovered"}


@pytest.mark.skipif(not os.environ.get("CBUS_TOOLKIT_EXE"),
                    reason="Set CBUS_TOOLKIT_EXE (and optionally CBUS_TOOLKIT_MAP) to regenerate the receipt")
def test_vendor_inputs_reproduce_the_committed_receipt():
    import sys
    sys.path.insert(0, str(ROOT / "research"))
    from project_documentor_static import inspect, render
    exe = Path(os.environ["CBUS_TOOLKIT_EXE"])
    map_file = Path(os.environ.get("CBUS_TOOLKIT_MAP", exe.with_suffix(".map")))
    assert render(inspect(exe, map_file)) == RECEIPT.read_text(encoding="utf-8")
