"""Offline Toolkit "Document Project" HTML for saved XML/CBZ projects.

The page structure reproduces the statically recovered Toolkit 1.18.0.2754
``TProjectDocumentor`` / ``TDocumentorCommon`` routines (see
``research/experiments/2026-09-30/project-documentor-static.md``):

* ``OnDocumentHTMLnew`` writes the head, the centred header block, the
  contents, and then one section per network;
* ``InsertHTMLNetworkNEW`` writes the network facts, one nested list per
  assigned application (address 255 is skipped) and the Units section;
* applications list their used groups (address 255 is skipped); groups on the
  Trigger Control application (202) use the Trigger layout with Events;
* every unit gets a heading and, unless it is ``BURDEN``, ``XC100B`` or
  ``XC305B``, the body written by the documentor registered for its upper-case
  unit type and firmware range, or the base ``TUnitTypeDocumentor``.

The original writes each fragment as one ``TStringList`` line and saves the list
as UTF-8 with CRLF line breaks. Some per-type documentors and several data
sources were not recovered. Those places are marked in the output and listed in
a final "Not documented (unrecovered)" section. They are never guessed.

Nothing here opens an endpoint, executes vendor code or writes the project.
Byte/visual parity with an original page, printing and the progress dialog are
unassessed or not implemented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
from typing import Any
from xml.dom import Node, minidom

from .barcode_scanner import displayable_serial
from .commissioning_route import project_sha256, read_project_snapshot
from .project import ProjectDocument, ProjectError

FORMAT = "cbus-project-documentation-v1"
UNASSESSED = "unassessed"
UNRECOVERED = "not documented (unrecovered)"
NOT_CALCULATED = "not calculated"
LINE_BREAK = "\r\n"

# Units skipped by GetAllUnitProgramming and given only a heading by InsertHTMLUnit.
HEADING_ONLY_TYPES = ("BURDEN", "XC100B", "XC305B")
TRIGGER_APPLICATION = 202
UNASSIGNED = 255
# TStandardCBusApplications.GetLevelsName: resource 62334 unless registered.
LEVELS_NAME = "Levels"
LEVELS_NAMES = {202: "Action Selectors", 203: "Values"}
# TStandardCBusApplications registrations used when a unit references an
# application that the project does not contain.
STANDARD_APPLICATION_TITLES = {
    0x38: "Lighting", 0x88: "Heating (Legacy)", 0xCA: "Trigger Control", 0xCB: "Enable Control",
    0xCD: "Multi-room Audio", 0xE0: "Telephony", 0xFF: "<Unused>", 0xD0: "Security",
    0xDF: "Clock and Timekeeping", 0xAC: "Air Conditioning", 0xE4: "Measurement",
    0xCE: "Error Reporting",
}
# Resource 62345, DateTimeToString format for "Generated on:".
DATE_FORMAT_DELPHI = "dd mmm yyyy hh:mm"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
PROGRESS_TEXT = "Network %d of %d"          # resource 62346, TfrmProjectDocumentor
PROGRESS_TITLE = "Generating Documentation"  # resource 62347

# Ordered string literals of the reproduced original routines. The static
# receipt script requires each tuple to equal the original method's literals.
ORIGINAL_LITERALS = {
    "TProjectDocumentor.OnDocumentHTMLnew": (
        "<html>", "<head>", "<title>", "CBus Project ", "</title>", '<style type="text/css">',
        "h1 {text-align: center;}", "h2 {text-align: center;}", "div.header_info {text-align: center;}",
        "</style>", "</head>", "<body>", "<h1>Project: ", "</h1>", '<div class="header_info">',
        "Generated on: ", "<br />", "Number of Networks: ", "<br />", "Number of Units: ", "</div>",
        "<hr />", "<hr />", "</body>", "</html>", "WHITE"),
    "TProjectDocumentor.InsertHTMLContents": (
        '<h2><a name="contents">Contents</a></h2>', '<ul type="square">', "<li \\>", '<ul type="disc">',
        "<li \\>", '<ul type="circle">', "<li \\>", "</ul>", '<li /><a href="#', '_Units">Units</a>',
        '<ul type="circle">', "<li />", "</ul>", "</ul>", "</ul>"),
    "TProjectDocumentor.InsertHTMLNetworkNEW": (
        '<h3><a name="', '">Network - ', '</a> [ <a href="#contents">top</a> ]</h3>', "Network Number: ",
        "</br>", "Interface Type: ", "</br>", "Interface Address: ", "</br>", "Current Consumption: ",
        " mA</br>", "Current Supplied: ", " mA</br>", "Impedance: ", " ohms</br>",
        "Status Report Interval: ", "<br/>", "<ul>", "</ul>"),
    "TProjectDocumentor.InsertHTMLApplication": (
        '<h3><a name="', "_", '">Application - ', '</a> [ <a href="#contents">top</a> ]</h3>', "Address: ",
        " ($", ")</br>", "Description: ", "</br>", "<ul>", "</ul>"),
    "TProjectDocumentor.InsertHTMLGroup": (
        '<h3><a name="', "_", "_", '">Group - ', '</a> [ <a href="#contents">top</a> ]</h3>', "Address: ",
        " ($", ") <br />", "Description: ", "<br />", ": ", "<ul>", '<li /><a name="', "_", "_", "_", '">',
        "</a>", "</ul>"),
    "TProjectDocumentor.InsertHTMLGroupInput": (
        "Inputs:", "<ul>", "<br/>", "|", "<li />", "<ul>", "</ul>", "</ul>"),
    "TProjectDocumentor.InsertHTMLGroupOutput": (
        "Outputs:", "<ul>", "<br/>", "|", "<li />", "<ul>", "</ul>", "</ul>"),
    "TProjectDocumentor.InsertHTMLGroupOther": (
        "Other:", "<ul>", "<br/>", "|", "<li />", "<ul>", "</ul>", "</ul>"),
    "TProjectDocumentor.InsertHTMLTriggerGroup": (
        '<h3><a name="', "_", "_", '">', '</a> [ <a href="#contents">top</a> ]</h3>', "Address: ", " ($",
        ") <br />", "Description: ", "<br /><br />", "Events:<br />", ": ", "<ul>", '<li /><a name="', "_",
        "_", "_", '">', "</a>", "<ul>", "<ul>", "</ul>", "<li />Action Selector is not used", "</ul>",
        "</ul>"),
    "TProjectDocumentor.InsertHTMLUnits": (
        '<h3><a name="', '_Units">Units</a> [ <a href="#contents">top</a> ]</h3>'),
    "TProjectDocumentor.InsertHTMLUnit": (
        '<h3><a name="', "_unit_", '">', " - ", '</a> [ <a href="#contents">top</a> ]</h3>', "BURDEN",
        "XC100B", "XC305B",
        "<h4>An Error occurred while scanning this unit. The programming is unknown.</h4>"),
    "TProjectDocumentor.GetNetworkMinimumStatusReportInterval": ("None", "secs on Unit "),
    "TProjectDocumentor.GetAllUnitProgramming": HEADING_ONLY_TYPES,
    "TUnitTypeDocumentor.DocumentHTML": (
        "Unit Address: ", "<br />", "Tagname: ", "<br />", "Part name: ", "<br />", "Application: ",
        "<br />", "Secondary Application: ", "<br />", "Serial Number: ", "<br />", "Firmware Version: ",
        "<br />", "Notes: ", "<br />", "Unit clock is enabled<br />", "Unit burden is enabled<br />",
        "<br />"),
    "DisplayHTMLApplication": ('<a href="#', "_", '">', "</a>"),
    "DisplayHTMLGroup": ('<a href="#', "_", "_", '">', "</a>"),
    "DisplayHTMLLevel": ('<a href="#', "_", "_", "_", '">', "</a>"),
    "DisplayHTMLNetwork": ('<a href="#', '">', "</a>"),
    "DisplayHTMLUnit": ('<a href="#', "_unit_", '">', " - ", "</a>"),
    "FormatHTMLString": ("&#60;", "<", "&#62;", ">"),
    "TOutputDocumentor.DocumentHTML": (
        '<table border="1">', "<tr><th>Channel</th><th>Groups</th>", "<th>Logic Function</th>", "</tr>",
        "<tr><td>", "</td><td>", ", ", "&nbsp;", "</td>", "<td>", "Max", "Min", "&nbsp;", "</td>", "</tr>",
        "</table>", "<br />"),
    "TBridgeDocumentor.DocumentHTML": (
        "Adjacent Network: ", "<br/>", "Connect Application 1: ", "<br/>", "Connect Application 2: ",
        "<br/>", "Connect Applications: All Applications<br/>",
        "Send Messages to Adjacent Network: Yes<br/>", "Send Messages to Adjacent Network: No<br/>",
        "Send Messages to Remote Network: Unknown Network<br/>", "Send Messages to Remote Network: ",
        "<br/>", "Send Messages to a Remote Network: No<br/>", "WARNING: ", " has no far side Network."),
    "TProjectNodeHelper.DocumentProject": (".html", "\\", "WHITE"),
}

# TUnitTypeDocumentorFactory registrations in .itext initialization order:
# (upper-case unit type, documentor class without "T"/"Documentor", min, max firmware).
REGISTRATIONS = (
    ("SENPILLA", "Multisensor", "0", "9"), ("SENPILL", "Multisensor", "0", "9"),
    ("SENLL", "LightLevelSensor", "1.00", "2.0.00"), ("PE_CELL", "LightLevelSensor", "1.00", "2.0.00"),
    ("SENLL", "ST7LightLevelSensor", "2.0.01", "9"), ("KEYA1", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYA1", "NeoProInput", "1.5.03", "2.9.99"), ("KEYAV2", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYAV2", "NeoProInput", "1.5.03", "2.9.99"), ("KEYA3", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYA3", "NeoProInput", "1.5.03", "2.9.99"), ("KEYAV4", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYAV4", "NeoProInput", "1.5.03", "2.9.99"), ("KEYA6", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYA6", "NeoProInput", "1.5.03", "2.9.99"), ("KEYA8", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYA8", "NeoProInput", "1.5.03", "2.9.99"), ("KEYB2", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYB2", "NeoProInput", "1.5.03", "2.9.99"), ("KEYB4", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYB4", "NeoProInput", "1.5.03", "2.9.99"), ("KEYB6", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYB6", "NeoProInput", "1.5.03", "2.9.99"), ("KEYH1", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYH1", "NeoProInput", "1.5.03", "2.9.99"), ("KEYH2", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYH2", "NeoProInput", "1.5.03", "2.9.99"), ("KEYH3", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYH3", "NeoProInput", "1.5.03", "2.9.99"), ("KEYH4", "NeoInput", "1.3.01", "1.5.02"),
    ("KEYH4", "NeoProInput", "1.5.03", "2.9.99"), ("BCI4A", "NeoProInput", "0", "9"),
    ("KEYM2", "NeoInput", "1.3.01", "1.5.02"), ("KEYM2", "NeoProInput", "1.5.03", "2.9.99"),
    ("KEYM4", "NeoInput", "1.3.01", "1.5.02"), ("KEYM4", "NeoProInput", "1.5.03", "2.9.99"),
    ("KEYM8", "NeoInput", "1.3.01", "1.5.02"), ("KEYM8", "NeoProInput", "1.5.03", "2.9.99"),
    ("SENPIRIC", "Multisensor", "0", "9"), ("SENPIRSS", "PIR", "1.00", "2.0.00"),
    ("SENPIROA", "PIR", "1.2.60", "2.0.00"), ("SENPIRIA", "PIR", "1.2.60", "2.0.00"),
    ("SENPIRIB", "PIR", "1.2.60", "2.0.00"), ("SENPIROA", "ST7PIRSensor", "2.0.01", "9"),
    ("SENPIRIA", "ST7PIRSensor", "2.0.01", "9"), ("SENPIRIB", "ST7PIRSensor", "2.0.01", "2.3.9"),
    ("SENPIRIB", "Multisensor", "2.4", "9"), ("PC_GIM", "GeneralInput", "0", "9"),
    ("DIMDU4", "ErrorReportOutput", "0", "9"), ("DIMPR3A", "ErrorReportOutput", "0", "9"),
    ("DIMPR6A", "ErrorReportOutput", "0", "9"), ("DIMPR12A", "ErrorReportOutput", "0", "9"),
    ("BRIDGE1N", "Bridge", "0", "9"), ("BRIDGE1F", "Bridge", "0", "9"), ("BRIDGE2N", "Bridge", "0", "9"),
    ("BRIDGE2F", "Bridge", "0", "9"), ("GATEWLSN", "Bridge", "0", "9"), ("GATEWLSF", "Bridge", "0", "9"),
    ("GATEWLS", "Bridge", "0", "9"), ("WGATE5N", "WirelessGateway", "0", "2.2.89"),
    ("WGATE5F", "WirelessGateway", "0", "2.2.89"), ("WGATE5N", "WirelessGateway", "2.2.90", "2.4.99"),
    ("WGATE5F", "WirelessGatewayAdvanced", "2.2.90", "2.4.99"), ("WTXU", "RemoteControl", "0", "9"),
    ("WTXUP", "RemoteControl", "0", "9"), ("NEOI 1FL", "RemoteControl", "0", "9"),
    ("NEOI 4FL", "RemoteControl", "0", "9"), ("NEOI HHR", "RemoteControl", "0", "9"),
    ("WTXU 2FL", "RemoteControl", "0", "9"), ("WTXU 6FL", "RemoteControl", "0", "9"),
    ("DIMAR3", "ArchitecturalDimmer", "0", "9"), ("DIMAR6", "ArchitecturalDimmer", "0", "9"),
    ("DIMAR12", "ArchitecturalDimmer", "0", "9"), ("C12DIMAR", "ArchitecturalDimmer", "0", "9"),
    ("ANODN4", "Output", "0", "9"), ("RELDN16A", "Output", "0", "9"), ("RELDN8A", "Output", "0", "9"),
    ("RELDN4A", "Output", "0", "9"), ("DIMDH4", "Output", "0", "9"), ("KEYE1", "NeoProInput", "0", "9"),
    ("KEYE2", "NeoProInput", "0", "9"), ("KEYE3", "NeoProInput", "0", "9"), ("KEYE4", "NeoProInput", "0", "9"),
    ("KEYEIR1", "NeoProInput", "0", "9"), ("KEYEIR2", "NeoProInput", "0", "9"),
    ("KEYEIR3", "NeoProInput", "0", "9"), ("KEYEIR4", "NeoProInput", "0", "9"), ("ANOMB8", "Output", "0", "9"),
    ("DSIMB8", "Output", "0", "9"), ("RELMB8", "Output", "0", "9"), ("KEYCIR1", "ClassicKeyInput", "0", "9"),
    ("KEY1", "ClassicKeyInput", "0", "9"), ("KEY2", "ClassicKeyInput", "0", "9"),
    ("KEY4", "ClassicKeyInput", "0", "9"), ("KEYIR1", "ClassicKeyInput", "0", "9"),
    ("KEYIR4", "ClassicKeyInput", "0", "9"), ("KEYBC2", "ClassicKeyInput", "0", "9"),
    ("KEYBC4", "ClassicKeyInput", "0", "9"), ("KEYAUX4", "ClassicKeyInput", "0", "9"),
    ("DINAUX4", "ClassicKeyInput", "0", "9"), ("CLK2", "Clock", "0", "9"), ("KEYBIR2", "NeoProInput", "0", "9"),
    ("KEYBIR4", "NeoProInput", "0", "9"), ("KEYBIR6", "NeoProInput", "0", "9"),
    ("KEYDV1", "NeoProInput", "0", "9"), ("KEYDV2", "NeoProInput", "0", "9"),
    ("KEYDV3", "NeoProInput", "0", "9"), ("KEYDV4", "NeoProInput", "0", "9"),
    ("KEYP2", "NeoProInput", "0", "9"), ("KEYP4", "NeoProInput", "0", "9"), ("KEYP6", "NeoProInput", "0", "9"),
    ("KEYC1", "ClassicKeyInput", "0", "9"), ("KEYC2", "ClassicKeyInput", "0", "9"),
    ("KEYC4", "ClassicKeyInput", "0", "9"), ("KEYCIR4", "ClassicKeyInput", "0", "9"),
    ("KEYV1", "NeoProInput", "0", "9"), ("KEYV2", "NeoProInput", "0", "9"), ("KEYV3", "NeoProInput", "0", "9"),
    ("BCNC4A", "ClassicKeyInput", "0", "9"), ("BCNC4B", "ClassicKeyInput", "0", "9"),
    ("SENPIR", "PIR", "0", "9"), ("SENPOR", "PIR", "0", "9"), ("SENTEMP", "SENTEMP", "0", "9"),
    ("SENTEMPB", "SENTEMPPro", "0", "9"), ("PC_TSA", "Thermostat", "0", "9"),
    ("PC_TSA5", "Thermostat", "0", "9"), ("PC_TSB", "Thermostat", "0", "9"),
    ("PC_TSB5", "Thermostat", "0", "9"), ("KEYML5", "DLT", "0", "9"), ("KEYBL5", "DLT", "0", "9"),
    ("KEYDL4", "DLT", "0", "9"), ("KEYSCEN4", "CustomSceneKeyUnit", "0", "9"),
    ("SCNCTL5", "CustomSceneController", "0", "9"), ("DIMPR12", "BytecraftDimmer", "0", "9"),
    ("DIMMER4", "ClassicOutput", "0", "9"), ("AN_OUT4", "ClassicOutput", "0", "9"),
    ("RELAY4", "ClassicOutput", "0", "9"), ("PC_DAL2B", "DALI2B", "0", "9"), ("PC_DAL2C", "DALI2B", "0", "9"),
    ("PC_WHAD", "WHAA", "0", "9"), ("PC_WHAR", "WHAA", "0", "9"), ("PC_WHARB", "WHAA", "0", "9"),
    ("WRD0R1", "CBusWirelessInput", "0", "9"), ("WRD1R1", "CBusWirelessInput", "0", "9"),
    ("WRD2R1", "CBusWirelessInput", "0", "9"), ("WRD3R1", "CBusWirelessInput", "0", "9"),
    ("WRD4R1", "CBusWirelessInput", "0", "9"), ("WRD0D1", "CBusWirelessInput", "0", "9"),
    ("WRD1D1", "CBusWirelessInput", "0", "9"), ("WRD2D1", "CBusWirelessInput", "0", "9"),
    ("WRD3D1", "CBusWirelessInput", "0", "9"), ("WRD4D1", "CBusWirelessInput", "0", "9"),
    ("WRM1R1EZ", "CBusWirelessInput", "0", "9"), ("WRM2R2EZ", "CBusWirelessInput", "0", "9"),
    ("WPA2D1", "CBusWirelessInput", "0", "9"), ("WPA2R1", "CBusWirelessInput", "0", "9"),
    ("WPAD1D1", "CBusWirelessInput", "0", "9"), ("WPAD1R1", "CBusWirelessInput", "0", "9"),
    ("KEYV1SP", "NeoProInput", "0", "9"), ("KEYV2SP", "NeoProInput", "0", "9"),
    ("KEYV3SP", "NeoProInput", "0", "9"), ("BCN2B", "NeoProInput", "0", "9"),
    ("BCN4B", "NeoProInput", "0", "9"), ("SENLLA", "Multisensor", "0", "9"), ("DIMDN4", "Output", "0", "9"),
    ("DIMDN4F", "Output", "0", "9"), ("DIMDN8", "Output", "0", "9"), ("DIMDN8F", "Output", "0", "9"),
    ("DIMDS8", "Output", "0", "9"), ("DIMPR1", "Output", "0", "9"), ("DIMPR2", "Output", "0", "9"),
    ("DIMPR4", "Output", "0", "9"), ("RELDN12", "Output", "0", "9"), ("RELDN4", "Output", "0", "9"),
    ("RELDN8", "Output", "0", "9"), ("RELDN8B", "Output", "0", "9"), ("RELDN8SP", "Output", "0", "9"),
    ("RELDC4", "Output", "0", "9"), ("RELDB1", "Output", "0", "9"), ("RELSM8", "Output", "0", "9"),
    ("RELDF1", "FanController", "0", "9"), ("DMXDO12", "DMXGateway", "0", "9"),
    ("RELAY1", "ClassicOutput", "0", "9"), ("RELAY2", "ClassicOutput", "0", "9"),
    ("WRM2D1", "CBusWirelessInput", "0", "9"), ("WRM2R1", "CBusWirelessInput", "0", "9"),
    ("WRM4D1", "CBusWirelessInput", "0", "9"), ("WRM4D2", "CBusWirelessInput", "0", "9"),
    ("WRM4R1", "CBusWirelessInput", "0", "9"), ("WRM4R2", "CBusWirelessInput", "0", "9"),
    ("WRM8D1", "CBusWirelessInput", "0", "9"), ("WRM8D2", "CBusWirelessInput", "0", "9"),
    ("WRM8R1", "CBusWirelessInput", "0", "9"), ("WRM8R2", "CBusWirelessInput", "0", "9"),
    ("WRM2D1EZ", "CBusWirelessInput", "0", "9"), ("WRM4D2EZ", "CBusWirelessInput", "0", "9"),
    ("WRB2D1", "CBusWirelessInput", "0", "9"), ("WRB2R1", "CBusWirelessInput", "0", "9"),
    ("WRB4D1", "CBusWirelessInput", "0", "9"), ("WRB4D2", "CBusWirelessInput", "0", "9"),
    ("WRB4R1", "CBusWirelessInput", "0", "9"), ("WRB4R2", "CBusWirelessInput", "0", "9"),
    ("WRB6D1", "CBusWirelessInput", "0", "9"), ("WRB6D2", "CBusWirelessInput", "0", "9"),
    ("WRB6R1", "CBusWirelessInput", "0", "9"), ("WRB6R2", "CBusWirelessInput", "0", "9"),
    ("WRP2D1", "CBusWirelessInput", "0", "9"), ("WRP2R1", "CBusWirelessInput", "0", "9"),
    ("WRP4D1", "CBusWirelessInput", "0", "9"), ("WRP4D2", "CBusWirelessInput", "0", "9"),
    ("WRP4R1", "CBusWirelessInput", "0", "9"), ("WRP4R2", "CBusWirelessInput", "0", "9"),
    ("WRP6D1", "CBusWirelessInput", "0", "9"), ("WRP6D2", "CBusWirelessInput", "0", "9"),
    ("WRP6R1", "CBusWirelessInput", "0", "9"), ("WRP6R2", "CBusWirelessInput", "0", "9"),
    ("WPAP2D1", "CBusWirelessInput", "0", "9"), ("WPAP2R1", "CBusWirelessInput", "0", "9"),
    ("SENTEMP4", "DigitalTemperatureSensor", "0", "9"), ("DIMDD8", "Output", "0", "9"),
    ("DIMDD8F", "Output", "0", "9"), ("DIMDD4", "Output", "0", "9"), ("DIMDD4F", "Output", "0", "9"),
)

# Effective VMT slots +0x7C (DocumentHTML) and +0x80 (ActionSelectorUse) per
# documentor class, recovered from the class hierarchy.
DOCUMENTOR_METHODS = {
    "UnitType": ("UnitType", "UnitType"),
    "ArchitecturalDimmer": ("ArchitecturalDimmer", "ArchitecturalDimmer"),
    "Bridge": ("Bridge", "UnitType"),
    "BytecraftDimmer": ("BytecraftDimmer", "BytecraftDimmer"),
    "CBusWirelessInput": ("CBusWirelessInput", "CBusWirelessInput"),
    "ClassicKeyInput": ("ClassicKeyInput", "ClassicKeyInput"),
    "ClassicOutput": ("ClassicOutput", "UnitType"),
    "Clock": ("UnitType", "UnitType"),
    "CustomSceneController": ("CustomSceneController", "CustomSceneController"),
    "CustomSceneKeyUnit": ("CustomSceneKeyUnit", "UnitType"),
    "DALI2B": ("DALI2B", "DALI2B"),
    "DigitalTemperatureSensor": ("DigitalTemperatureSensor", "DigitalTemperatureSensor"),
    "DLT": ("DLT", "NeoProInput"),
    "DMXGateway": ("DMXGateway", "UnitType"),
    "ErrorReportOutput": ("Output", "ErrorReportOutput"),
    "FanController": ("FanController", "FanController"),
    "GeneralInput": ("UnitType", "UnitType"),
    "LightLevelSensor": ("LightLevelSensor", "UnitType"),
    "Multisensor": ("Multisensor", "NeoInput"),
    "NeoInput": ("NeoInput", "NeoInput"),
    "NeoProInput": ("NeoProInput", "NeoProInput"),
    "Output": ("Output", "UnitType"),
    "PIR": ("PIR", "ClassicKeyInput"),
    "RemoteControl": ("RemoteControl", "RemoteControl"),
    "SENTEMP": ("SENTEMP", "UnitType"),
    "SENTEMPPro": ("SENTEMPPro", "SENTEMPPro"),
    "ST7LightLevelSensor": ("ST7LightLevelSensor", "UnitType"),
    "ST7PIRSensor": ("ST7PIRSensor", "ClassicKeyInput"),
    "Thermostat": ("Thermostat", "UnitType"),
    "WHAA": ("WHAA", "UnitType"),
    "WirelessGatewayAdvanced": ("WirelessGatewayAdvanced", "WirelessGatewayAdvanced"),
    "WirelessGateway": ("WirelessGateway", "UnitType"),
}
# DocumentHTML bodies that are wrappers: CustomSceneKeyUnit only calls the base.
_BASE_ONLY_BODIES = frozenset({"UnitType", "CustomSceneKeyUnit"})
# Recovery status of each effective DocumentHTML body reproduced here.
RECOVERED_BODIES = {
    "UnitType": "recovered",
    "CustomSceneKeyUnit": "recovered",
    "Output": "partial",    # Known DIN PP mappings and NCC base-only; other agents remain open.
    "Bridge": "recovered",  # Requires the stored application/forwarding PP fields.
    "ClassicOutput": "recovered",
    "DMXGateway": "recovered",
    "ClassicKeyInput": "partial",  # Source-pinned classic families; other interfaces/PP state remain open.
    "NeoInput": "partial",  # Source-pinned families and fresh PP model only.
    "NeoProInput": "partial",
    "DLT": "partial",
    "CustomSceneController": "partial",  # Complete SCNCTL5 snapshots; loader failures remain open.
    "FanController": "partial",  # Exact RELDF1 profile, role and stored-label model.
    "SENTEMP": "partial",
    "SENTEMPPro": "partial",
    "DigitalTemperatureSensor": "partial",
    "PIR": "partial",
    "ST7PIRSensor": "partial",
    "BytecraftDimmer": "partial",  # Exact old/L1 DIMPR12 loaded records only.
    "LightLevelSensor": "recovered",  # Old SENLL/PE_CELL consumed PP and groups required.
    "ST7LightLevelSensor": "partial",  # Nonzero or explicitly idle zero broadcast timer.
    "WHAA": "recovered",
    "DALI2B": "recovered",
    "Multisensor": "partial",  # Exact source-pinned loaders; active joins remain explicit.
    "Thermostat": "partial",  # Resolved outputs/masters; implicit plant group creation remains open.
    "CBusWirelessInput": "partial",
    "WirelessGateway": "partial",
    "WirelessGatewayAdvanced": "partial",
    "RemoteControl": "partial",
    "ArchitecturalDimmer": "partial",  # Explicit loaded channels/logic/scenes only.
}
PARITY = {
    "model_basis": "static_disassembly_of_original_toolkit",
    "original_toolkit_executed": False,
    "byte_parity": UNASSESSED,
    "visual_parity": UNASSESSED,
    "print": "not_implemented",
    "progress_dialog": "not_implemented",
    "collection_order_basis": "explicit_offline_address_order; original application/group/level order depends on registry and Windows locale",
    "status_report_basis": "stored_pp_snapshot; original programming-load success/failure not observed",
    "scene_master_selector_format_basis": "DisplayAddressValue=false (original fresh default); saved preference not loaded",
    "temperature_format_basis": "celsius; period decimal separator; stored Toolkit preferences and Windows locale not loaded",
    "encoding": "utf-8-bom-crlf-per-TStringList.SaveToFile(TEncoding.UTF8)",
}


def documentor_class(short: str) -> str:
    return f"T{short}Documentor"


def _version_tokens(text: str) -> list[int]:
    # CIS_Strings.VersionStringCompare: numeric StrToIntDef per "." token.
    result = []
    for token in text.split("."):
        try:
            result.append(int(token.strip(), 10))
        except ValueError:
            result.append(0)
    return result


def version_compare(left: str, right: str) -> int:
    first, second = _version_tokens(left), _version_tokens(right)
    count = max(len(first), len(second))
    first += [0] * (count - len(first))
    second += [0] * (count - len(second))
    return (first > second) - (first < second)


def select_documentor(unit_type: str, firmware: str) -> str:
    """TUnitTypeDocumentorFactory.GetDocumentor: first matching registration, else the base."""
    key = unit_type.upper()
    for registered, short, minimum, maximum in REGISTRATIONS:
        # FirmwareWithinLimits: not (Min > fw) and (Max >= fw).
        if registered == key and version_compare(minimum, firmware) <= 0 \
                and version_compare(maximum, firmware) >= 0:
            return short
    return "UnitType"


def format_html_string(text: str) -> str:
    # StringReplace flags 3 = [rfReplaceAll, rfIgnoreCase].
    return text.replace("<", "&#60;").replace(">", "&#62;")


def delphi_date(moment: datetime) -> str:
    """DateTimeToString('dd mmm yyyy hh:mm') with English short month names."""
    return f"{moment.day:02d} {_MONTHS[moment.month - 1]} {moment.year:04d} {moment.hour:02d}:{moment.minute:02d}"


# -- project model -----------------------------------------------------------
def _local_name(node: Node) -> str:
    return node.localName or node.nodeName


def _children(node: Node, name: str) -> list[minidom.Element]:
    return [child for child in node.childNodes
            if child.nodeType == Node.ELEMENT_NODE and _local_name(child) == name
            and child.namespaceURI == node.namespaceURI]


def _scalar(node: Node, name: str) -> str:
    values = _children(node, name)
    if len(values) > 1:
        raise ProjectError(f"Ambiguous {name}: multiple matching fields")
    if not values:
        return ""
    return "".join(child.data for child in values[0].childNodes
                   if child.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE))


def _address(node: Node, label: str) -> int:
    value = _scalar(node, "Address").strip()
    if not re.fullmatch(r"[0-9]{1,3}", value) or int(value) > 255:
        raise ProjectError(f"{label} Address must be a decimal byte")
    return int(value)


def _numbers(value: str) -> list[int]:
    result = []
    for token in value.split():
        text = token.lower()
        try:
            result.append(int(text.replace("$", "0x"), 0) if text.startswith(("$", "0x")) else int(text, 10))
        except ValueError as exc:
            raise ProjectError(f"PP value {value!r} is not a numeric array") from exc
    return result


def _flag(value: str) -> bool:
    text = value.strip().lower()
    if text in ("true", "yes"):
        return True
    if text in ("", "false", "no"):
        return False
    try:
        return any(_numbers(text))
    except ProjectError:
        return False


@dataclass(frozen=True)
class Level:
    address: int
    name: str
    value: int | None = None

    @property
    def action_value(self) -> int:
        return self.address if self.value is None else self.value


@dataclass
class Group:
    address: int
    name: str
    description: str
    levels: list[Level]


@dataclass
class Application:
    address: int
    name: str
    description: str
    groups: list[Group]

    def group(self, address: int) -> Group | None:
        return next((group for group in self.groups if group.address == address), None)


@dataclass
class Unit:
    address: int
    name: str
    unit_type: str
    unit_name: str
    serial: str
    firmware: str
    description: str
    parameters: dict[str, str]
    fields: dict[str, str]

    def array(self, name: str) -> list[int] | None:
        value = self.parameters.get(name)
        return None if value is None else _numbers(value)

    def flag(self, name: str) -> bool:
        if name in self.fields:
            return _flag(self.fields[name])
        return _flag(self.parameters.get(name, ""))


@dataclass
class Network:
    address: int
    name: str
    interface_type: str
    interface_address: str
    applications: list[Application]
    units: list[Unit]
    # Physical NetworkNumber is independent of a database Address. Absence
    # stays unknown; report consumers must never substitute the Address.
    network_number: int | None = None

    def application(self, address: int) -> Application | None:
        return next((app for app in self.applications if app.address == address), None)


@dataclass
class ProjectModel:
    name: str
    networks: list[Network]
    digest: str = ""
    size: int = 0
    format: str = ""
    by_address: dict[int, Network] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_address = {network.address: network for network in self.networks}


def _unique(items, label: str):
    seen = set()
    for item in items:
        if item.address in seen:
            raise ProjectError(f"Ambiguous project: duplicate {label} address {item.address}")
        seen.add(item.address)
    # Original custom comparators place the unused object first for these
    # three classes; Unit and Level have ordinary numeric address order.
    if label in ("network", "application", "group"):
        return sorted(items, key=lambda item: (item.address != UNASSIGNED, item.address))
    return sorted(items, key=lambda item: item.address)


def _level_value(level: minidom.Element) -> int | None:
    if not level.hasAttribute("Value"):
        return None
    values = _numbers(level.getAttribute("Value"))
    if len(values) != 1 or not 0 <= values[0] <= 255:
        raise ProjectError("Level Value must be a byte")
    return values[0]


def build_model(project: ProjectDocument) -> ProjectModel:
    project.assert_valid()
    networks = []
    for net_node in _children(project.project, "Network"):
        net_address = _address(net_node, "Network")
        interfaces = _children(net_node, "Interface")
        interface = interfaces[0] if len(interfaces) == 1 else None
        applications = []
        for app_node in _children(net_node, "Application"):
            groups = []
            for group_node in _children(app_node, "Group"):
                levels = [Level(_address(level, "Level"), _scalar(level, "TagName"),
                                _level_value(level))
                          for level in _children(group_node, "Level")]
                groups.append(Group(_address(group_node, "Group"), _scalar(group_node, "TagName"),
                                    _scalar(group_node, "Description"), _unique(levels, "level")))
            applications.append(Application(_address(app_node, "Application"), _scalar(app_node, "TagName"),
                                             _scalar(app_node, "Description"), _unique(groups, "group")))
        units = []
        for unit_node in _children(net_node, "Unit"):
            parameters: dict[str, str] = {}
            for pp in _children(unit_node, "PP"):
                name = pp.getAttribute("Name")
                if name in parameters:
                    raise ProjectError("Unit has duplicate PP names")
                parameters[name] = pp.getAttribute("Value")
            fields = {name: _scalar(unit_node, name) for name in ("Burden", "ClockGenEnable", "CatalogNumber",
                                                                   "SwitchablePowerSupplyEnabled")
                      if _children(unit_node, name)}
            units.append(Unit(_address(unit_node, "Unit"), _scalar(unit_node, "TagName"),
                              _scalar(unit_node, "UnitType").strip(), _scalar(unit_node, "UnitName"),
                              _scalar(unit_node, "SerialNumber"), _scalar(unit_node, "FirmwareVersion").strip(),
                              _scalar(unit_node, "Description"), parameters, fields))
        network_number = None
        if _children(net_node, "NetworkNumber"):
            number = _scalar(net_node, "NetworkNumber").strip()
            if not re.fullmatch(r"[0-9]{1,3}", number) or int(number) > 255:
                raise ProjectError("NetworkNumber must be a decimal byte")
            network_number = int(number)
        networks.append(Network(
            net_address, _scalar(net_node, "TagName"),
            _scalar(interface, "InterfaceType") if interface is not None else "",
            _scalar(interface, "InterfaceAddress") if interface is not None else "",
            _unique(applications, "application"), _unique(units, "unit"), network_number))
    if not networks:
        raise ProjectError("Project contains no networks")
    return ProjectModel(_scalar(project.project, "TagName"), _unique(networks, "network"))


def load_model(path: Path, *, native_xml: bool = False) -> ProjectModel:
    snapshot = read_project_snapshot(Path(path))
    if native_xml:
        from .project_documentation_native import build_native_model
        return build_native_model(snapshot)
    project = ProjectDocument.from_snapshot(snapshot, source=Path(path))
    model = build_model(project)
    model.digest, model.size, model.format = project_sha256(snapshot), len(snapshot), project.format
    return model


# -- DocumentorCommon ----------------------------------------------------------
def html_network(network: Network) -> str:
    return f'<a href="#{network.address}">{network.name}</a>'


def html_application(network: Network, address: int) -> str:
    application = network.application(address)
    name = application.name if application is not None else STANDARD_APPLICATION_TITLES.get(address, str(address))
    if address == UNASSIGNED:
        return name
    return f'<a href="#{network.address}_{address}">{name}</a>'


def html_group(network: Network, application: int, group: Group) -> str:
    if group.address == UNASSIGNED:
        return format_html_string(group.name)
    return f'<a href="#{network.address}_{application}_{group.address}">{group.name}</a>'


def html_unit(network: Network, unit: Unit) -> str:
    return f'<a href="#{network.address}_unit_{unit.address}">{unit.name} - {unit.unit_type}</a>'


# -- documentors ----------------------------------------------------------------
class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.unrecovered: list[dict[str, Any]] = []
        self.unit_status: dict[str, int] = {"recovered": 0, "partial": 0, "unrecovered": 0, "heading_only": 0}
        self.status_reports: list[dict[str, Any]] = []

    def add(self, line: str) -> None:
        self.lines.append(line)

    def mark(self, network: Network, unit: Unit | None, what: str) -> None:
        line = f"{what}: {UNRECOVERED}<br />"
        self.add(line)
        self.unrecovered.append({"network": network.address, "unit": unit.address if unit else None,
                                 "item": what})


def _application_numbers(unit: Unit) -> tuple[int | None, int | None]:
    values = unit.array("Application")
    if not values:
        return None, None
    primary = values[0]
    secondary = values[1] if len(values) > 1 else None
    return primary, secondary


def document_base(out: _Writer, network: Network, unit: Unit) -> None:
    """TUnitTypeDocumentor.DocumentHTML."""
    out.add(f"Unit Address: {unit.address}<br />")
    out.add(f"Tagname: {unit.name}<br />")
    out.add(f"Part name: {unit.unit_name}<br />")
    primary, secondary = _application_numbers(unit)
    if primary is not None:
        out.add(f"Application: {html_application(network, primary)}<br />")
    if secondary is not None:
        out.add(f"Secondary Application: {html_application(network, secondary)}<br />")
    out.add(f"Serial Number: {displayable_serial(unit.serial)}<br />")
    out.add(f"Firmware Version: {unit.firmware}<br />")
    out.add(f"Notes: {format_html_string(unit.description)}<br />")
    if unit.flag("ClockGenEnable"):
        out.add("Unit clock is enabled<br />")
    if unit.flag("Burden"):
        out.add("Unit burden is enabled<br />")
    out.add("<br />")


def _din_profile(unit: Unit):
    from .project_documentation_outputs import output_profile
    return output_profile(unit)


def _group_link(network: Network, application: int | None, address: int) -> str:
    app = network.application(application) if application is not None else None
    group = app.group(address) if app is not None else None
    if group is None:
        group = Group(address, str(address), "", [])
    return html_group(network, application if application is not None else UNASSIGNED, group)


def document_output(out: _Writer, network: Network, unit: Unit) -> str:
    """TOutputDocumentor.DocumentHTML for recovered native class/PP mappings."""
    from .project_documentation_outputs import output_base_only
    document_base(out, network, unit)
    if output_base_only(unit):
        return "recovered"
    profile = _din_profile(unit)
    groups = unit.array("GroupAddress")
    if profile is None or groups is None:
        out.mark(network, unit, "Output channels")
        return "partial"
    application, _ = _application_numbers(unit)
    associations = [unit.array(f"LogicGA{13 + k}Associations") for k in range(4)]
    functions = unit.array("LogicFunction")
    last = max(profile.indices)
    if (application is None or not 0 <= application <= 255 or len(groups) < 16
            or any(not 0 <= value <= 255 for value in groups)
            or any(values is None or len(values) <= last or any(value not in (0, 1) for value in values)
                   for values in associations)
            or functions is None or len(functions) <= last or any(value not in (0, 1) for value in functions)):
        out.mark(network, unit, "Output channel programming (incomplete or invalid PP arrays)")
        return "partial"

    def at(values: list[int], index: int, default: int = 0) -> int:
        return values[index] if index < len(values) else default

    logic = [at(groups, 12 + k, UNASSIGNED) for k in range(4)]
    rows = []
    for index in profile.indices:
        members = []
        if at(groups, index, UNASSIGNED) != UNASSIGNED:
            members.append(at(groups, index))
        members += [logic[k] for k in range(4) if at(associations[k], index) and logic[k] != UNASSIGNED]
        rows.append((members, at(functions, index)))
    uses_logic = any(at(associations[k], index) and logic[k] != UNASSIGNED
                     for index in profile.indices for k in range(4))
    app = network.application(application)
    if any(app is None or app.group(member) is None for members, _ in rows for member in members):
        out.mark(network, unit, "Output channel group labels (missing project groups)")
        return "partial"
    out.add('<table border="1">')
    out.add("<tr><th>Channel</th><th>Groups</th>" + ("<th>Logic Function</th>" if uses_logic else "") + "</tr>")
    for channel, (members, function) in enumerate(rows, start=1):
        row = f"<tr><td>{channel}</td><td>"
        row += ", ".join(_group_link(network, application, member) for member in members) if members else "&nbsp;"
        row += "</td>"
        if uses_logic:
            row += "<td>" + (("Max" if function else "Min") if len(members) > 1 else "&nbsp;") + "</td>"
        out.add(row + "</tr>")
    out.add("</table>")
    out.add("<br />")
    return "recovered"


def document_bridge(out: _Writer, network: Network, unit: Unit, model: ProjectModel) -> str:
    """TBridgeDocumentor and TCBusBridgeCGateAgent.AfterLoadProgrammingInformation.

    The destination is the last known network in the first contiguous prefix
    of seven BridgeAddress entries, independently of BridgeCount. The latter
    only enables the remote-forwarding line. Missing programming is unknown.
    """
    document_base(out, network, unit)
    adjacent = model.by_address.get(unit.address)
    if adjacent is None:
        out.add(f"WARNING: {unit.unit_type} has no far side Network.")
        return "recovered"
    out.add(f"Adjacent Network: {html_network(adjacent)}<br/>")
    applications = unit.array("Application")
    adjacent_enabled = unit.array("ApplicationConnectEnabled")
    bridge_count = unit.array("BridgeCount")
    if (applications is None or len(applications) != 2
            or any(not 0 <= value <= 255 for value in applications)
            or adjacent_enabled is None or len(adjacent_enabled) != 1
            or adjacent_enabled[0] not in (0, 1)
            or bridge_count is None or len(bridge_count) != 1
            or not 0 <= bridge_count[0] <= 7):
        out.mark(network, unit, "Bridge connection settings")
        return "partial"
    # HasApplication1 is true for every original TBridge registration. The
    # bridge's private application lists rename address 255 independently.
    for index, address in enumerate(applications, start=1):
        title = ("All Applications" if index == 1 else "<Unused>") if address == UNASSIGNED \
            else html_application(network, address)
        out.add(f"Connect Application {index}: {title}<br/>")
    out.add("Send Messages to Adjacent Network: " + ("Yes" if adjacent_enabled[0] else "No") + "<br/>")
    if bridge_count[0] == 0:
        out.add("Send Messages to a Remote Network: No<br/>")
        return "recovered"
    route = unit.array("BridgeAddress")
    if route is None or any(not 0 <= value <= 255 for value in route):
        out.mark(network, unit, "Bridge destination network")
        return "partial"
    destination = UNASSIGNED
    for address in route[:7]:
        if address == UNASSIGNED or address not in model.by_address:
            break
        destination = address
    remote = model.by_address.get(destination)
    out.add("Send Messages to Remote Network: "
            + (html_network(remote) if remote is not None else "Unknown Network") + "<br/>")
    return "recovered"


def document_unit(out: _Writer, network: Network, unit: Unit, model: ProjectModel) -> dict[str, Any]:
    """TProjectDocumentor.InsertHTMLUnit."""
    from .project_documentation_devices import DOCUMENTORS as device_documentors
    from .project_documentation_classic_profiles import CLASSIC_PROFILE_COUNTS, document_classic_profile
    from .project_documentation_dlt import document_dlt
    from .project_documentation_neo import DOCUMENTORS as neo_documentors, neo_profile
    from .project_documentation_neoclassic import NEOCLASSIC_TYPES, document_neoclassic
    from .project_documentation_scene_controller import document_scene_controller
    from .project_documentation_special_outputs import document_fan
    from .project_documentation_temperature import document_temperature
    from .project_documentation_pir import document_pir
    from .project_documentation_bytecraft import document_bytecraft
    from .project_documentation_light_level import document_light_level
    from .project_documentation_gateways import document_dali, document_whaa
    from .project_documentation_multisensor import document_multisensor
    from .project_documentation_thermostat import document_thermostat
    from .project_documentation_wireless import document_wireless
    documentors = {**device_documentors, **neo_documentors, "DLT": document_dlt,
                   "CustomSceneController": document_scene_controller, "FanController": document_fan,
                   **{name: document_temperature for name in ("SENTEMP", "SENTEMPPro", "DigitalTemperatureSensor")},
                   "PIR": document_pir, "ST7PIRSensor": document_pir,
                   "BytecraftDimmer": document_bytecraft,
                   "LightLevelSensor": document_light_level, "ST7LightLevelSensor": document_light_level,
                   "DALI2B": document_dali, "WHAA": document_whaa,
                   "Multisensor": document_multisensor}
    out.add(f'<h3><a name="{network.address}_unit_{unit.address}">{unit.name} - {unit.unit_type}</a>'
            ' [ <a href="#contents">top</a> ]</h3>')
    record = {"network": network.address, "unit": unit.address, "unit_type": unit.unit_type}
    if unit.unit_type in HEADING_ONLY_TYPES:
        out.unit_status["heading_only"] += 1
        return {**record, "documentor": None, "status": "heading_only"}
    short = select_documentor(unit.unit_type, unit.firmware)
    body = DOCUMENTOR_METHODS[short][0]
    if body == "ClassicKeyInput" and unit.unit_type.upper() in CLASSIC_PROFILE_COUNTS:
        documentors[body] = document_classic_profile
    if body == "ClassicKeyInput" and unit.unit_type.upper() in NEOCLASSIC_TYPES:
        documentors[body] = document_neoclassic
    if body in neo_documentors:
        try:
            neo_profile(unit)
        except ValueError:
            # A shared documentor does not establish a device's PP loader.
            documentors.pop(body)
    if body in _BASE_ONLY_BODIES:
        document_base(out, network, unit)
        status = "recovered"
    elif body == "Output":
        status = document_output(out, network, unit)
    elif body == "Bridge":
        status = document_bridge(out, network, unit, model)
    elif body == "Thermostat":
        status = document_thermostat(out, network, unit, model)
    elif body == "ArchitecturalDimmer":
        from .project_documentation_architectural import document_architectural
        status = document_architectural(out, network, unit)
    elif body in {"CBusWirelessInput", "WirelessGateway", "WirelessGatewayAdvanced", "RemoteControl"}:
        status = document_wireless(out, network, unit, model.networks)
    elif body in documentors:
        status = documentors[body](out, network, unit)
    else:
        document_base(out, network, unit)
        out.mark(network, unit, f"{documentor_class(body)}.DocumentHTML")
        status = "unrecovered"
    out.unit_status[status] += 1
    return {**record, "documentor": documentor_class(short), "status": status}


# -- TProjectDocumentor ----------------------------------------------------------
def _contents(out: _Writer, networks: list[Network]) -> None:
    out.add('<h2><a name="contents">Contents</a></h2>')
    out.add('<ul type="square">')
    for network in networks:
        out.add("<li \\>" + html_network(network))
        out.add('<ul type="disc">')
        for application in network.applications:
            if application.address == UNASSIGNED:
                continue
            out.add("<li \\>" + html_application(network, application.address))
            out.add('<ul type="circle">')
            for group in application.groups:
                if group.address != UNASSIGNED:
                    out.add("<li \\>" + html_group(network, application.address, group))
            out.add("</ul>")
        out.add(f'<li /><a href="#{network.address}_Units">Units</a>')
        out.add('<ul type="circle">')
        for unit in network.units:
            out.add("<li />" + html_unit(network, unit))
        out.add("</ul>")
        out.add("</ul>")
    out.add("</ul>")


def _levels(out: _Writer, network: Network, application: Application, group: Group, trigger: bool,
            model: ProjectModel) -> None:
    from .project_documentation_usage import action_selector_usage
    title = LEVELS_NAMES.get(application.address, LEVELS_NAME)
    for index, level in enumerate(group.levels):
        if index == 0:
            out.add(title + ": ")
            out.add("<ul>")
        out.add(f'<li /><a name="{network.address}_{application.address}_{group.address}_{level.address}">'
                f"{level.name}</a>")
        if trigger:
            out.add("<ul>")
            reported = False
            for unit in network.units:
                short = select_documentor(unit.unit_type, unit.firmware)
                action = DOCUMENTOR_METHODS[short][1]
                usage = action_selector_usage(unit, action, application.address, group.address,
                                              level.address, level.action_value, network=network)
                if not usage.html and usage.status == "recovered":
                    continue
                reported = True
                out.add(html_unit(network, unit))
                out.add("<ul>")
                if usage.html:
                    out.add(usage.html)
                if usage.status != "recovered":
                    out.add(f"<li />{documentor_class(action)}.ActionSelectorUse: {UNRECOVERED}")
                    out.unrecovered.append({"network": network.address, "unit": unit.address,
                                            "item": f"{documentor_class(action)}.ActionSelectorUse",
                                            "level": [application.address, group.address, level.address]})
                out.add("</ul>")
            if not reported:
                out.add("<li />Action Selector is not used")
            out.add("</ul>")
        if index == len(group.levels) - 1:
            out.add("</ul>")


def _group_usage(out: _Writer, network: Network, application: Application, group: Group,
                 heading: str, kind: str) -> None:
    from .project_documentation_usage import group_usage
    out.add(heading)
    out.add("<ul>")
    for unit in network.units:
        usage = group_usage(unit, application.address, group.address, kind, network=network)
        if not usage.html and usage.status == "recovered":
            continue
        out.add("<li />" + html_unit(network, unit))
        if usage.html:
            out.add("<ul>" + usage.html + "</ul>")
        if usage.status != "recovered":
            out.add(f"<ul>Unit usage: {UNRECOVERED}</ul>")
            out.unrecovered.append({"network": network.address, "unit": unit.address,
                                    "item": f"Group {kind} usage ({application.address}/{group.address})",
                                    "missing": list(usage.missing)})
    out.add("</ul>")


def _group(out: _Writer, network: Network, application: Application, group: Group, model: ProjectModel) -> None:
    anchor = f"{network.address}_{application.address}_{group.address}"
    trigger = application.address == TRIGGER_APPLICATION
    label = "" if trigger else "Group - "
    out.add(f'<h3><a name="{anchor}">{label}{group.name}</a> [ <a href="#contents">top</a> ]</h3>')
    out.add(f"Address: {group.address} (${group.address:02X}) <br />")
    if trigger:
        out.add(f"Description: {format_html_string(group.description)}<br /><br />")
        out.add("Events:<br />")
    else:
        out.add(f"Description: {format_html_string(group.description)}<br />")
        for heading, kind in (("Inputs:", "input"), ("Outputs:", "output"), ("Other:", "other")):
            _group_usage(out, network, application, group, heading, kind)
    _levels(out, network, application, group, trigger, model)


def _application(out: _Writer, network: Network, application: Application, model: ProjectModel) -> None:
    out.add(f'<h3><a name="{network.address}_{application.address}">Application - {application.name}</a>'
            ' [ <a href="#contents">top</a> ]</h3>')
    out.add(f"Address: {application.address} (${application.address:02X})</br>")
    out.add(f"Description: {format_html_string(application.description)}</br>")
    for group in application.groups:
        if group.address == UNASSIGNED:
            continue
        out.add("<ul>")
        _group(out, network, application, group, model)
        out.add("</ul>")


def _calculator_lines(network: Network, catalog) -> tuple[str, str, str, str | None]:
    if catalog is None:
        return (NOT_CALCULATED,) * 3 + ("Network calculator (no --catalog supplied)",)
    from .calculator import CalculatorError, CalculatorUnit
    units = []
    for unit in network.units:
        # A Burden field wins; otherwise the calculator reads the Burden PP.
        burden = unit.fields.get("Burden")
        parameters = tuple((name, value) for name, value in unit.parameters.items()
                           if burden is None or name not in ("Burden", "HardwareBurdenMarker"))
        units.append(CalculatorUnit(unit.fields.get("CatalogNumber") or None, unit.unit_type or "?", burden,
                                    unit.fields.get("SwitchablePowerSupplyEnabled", "").lower() == "true",
                                    parameters))
    try:
        result = catalog.calculate(units)
    except CalculatorError:
        return (NOT_CALCULATED,) * 3 + ("Network calculator result (zero conductance)",)
    impedance = float(result.impedance_ohms)
    text = str(int(impedance)) if impedance.is_integer() else repr(impedance)
    return str(result.current_consumption_ma), str(result.current_supply_ma), text, None


def _network(out: _Writer, network: Network, model: ProjectModel, catalog, units: list) -> None:
    from .project_documentation_status import minimum_status_report
    out.add(f'<h3><a name="{network.address}">Network - {network.name}</a> [ <a href="#contents">top</a> ]</h3>')
    out.add(f"Network Number: {network.address}</br>")
    out.add(f"Interface Type: {network.interface_type}</br>")
    out.add(f"Interface Address: {network.interface_address}</br>")
    consumption, supplied, impedance, gap = _calculator_lines(network, catalog)
    out.add(f"Current Consumption: {consumption} mA</br>")
    out.add(f"Current Supplied: {supplied} mA</br>")
    out.add(f"Impedance: {impedance} ohms</br>")
    if gap:
        out.unrecovered.append({"network": network.address, "unit": None, "item": gap})
    status = minimum_status_report(network.units)
    if status.known:
        interval = "None" if status.seconds is None else f"{status.seconds}secs on Unit {html_unit(network, status.unit)}"
    else:
        interval = UNRECOVERED
        out.unrecovered.append({"network": network.address, "unit": None,
                                "item": "Status Report Interval (status-report interface)",
                                "missing": list(status.issues)})
    out.add(f"Status Report Interval: {interval}<br/>")
    out.status_reports.append({"network": network.address, "known": status.known, "seconds": status.seconds,
                               "unit": status.unit.address if status.unit else None,
                               "basis": status.basis, "issues": list(status.issues)})
    for application in network.applications:
        if application.address == UNASSIGNED:
            continue
        out.add("<ul>")
        _application(out, network, application, model)
        out.add("</ul>")
    out.add(f'<h3><a name="{network.address}_Units">Units</a> [ <a href="#contents">top</a> ]</h3>')
    for unit in network.units:
        units.append(document_unit(out, network, unit, model))


def _unrecovered_section(out: _Writer, networks: list[Network]) -> None:
    by_address = {network.address: network for network in networks}
    out.add("<hr />")
    out.add('<h2><a name="unrecovered">Not documented (unrecovered)</a></h2>')
    out.add("<ul>")
    for item in out.unrecovered:
        network = by_address[item["network"]]
        unit = next((u for u in network.units if u.address == item["unit"]), None)
        where = html_unit(network, unit) if unit is not None else html_network(network)
        out.add(f"<li />{where}: {format_html_string(item['item'])}")
    out.add("</ul>")


def render(model: ProjectModel, *, generated: datetime, networks: list[int] | None = None,
           catalog=None) -> tuple[str, dict[str, Any]]:
    """Return the document text (CRLF lines) and a summary."""
    selected = model.networks if networks is None else [model.by_address[n] for n in networks]
    out = _Writer()
    out.add("<html>")
    out.add("<head>")
    out.add("<title>")
    out.add("CBus Project " + model.name)
    out.add("</title>")
    out.add('<style type="text/css">')
    out.add("h1 {text-align: center;}")
    out.add("h2 {text-align: center;}")
    out.add("div.header_info {text-align: center;}")
    out.add("</style>")
    out.add("</head>")
    out.add("<body>")
    out.add(f"<h1>Project: {model.name}</h1>")
    out.add('<div class="header_info">')
    out.add(f"Generated on: {delphi_date(generated)}<br />")
    out.add(f"Number of Networks: {len(selected)}<br />")
    out.add(f"Number of Units: {sum(len(network.units) for network in selected)}")
    out.add("</div>")
    out.add("<hr />")
    _contents(out, selected)
    out.add("<hr />")
    units: list[dict[str, Any]] = []
    for network in selected:
        _network(out, network, model, catalog, units)
    _unrecovered_section(out, selected)
    out.add("</body>")
    out.add("</html>")
    text = LINE_BREAK.join(out.lines) + LINE_BREAK
    summary = {"networks": [network.address for network in selected], "units": units,
               "unit_status": dict(out.unit_status), "unrecovered": out.unrecovered,
               "status_reports": out.status_reports}
    return text, summary


def encode(text: str) -> bytes:
    """TStringList.SaveToFile(name, TEncoding.UTF8): UTF-8 preamble and CRLF lines."""
    return b"\xef\xbb\xbf" + text.encode("utf-8")


def default_output_name(project_name: str) -> Path:
    """TProjectNodeHelper.DocumentProject saves ``<AppPath>\\<project TagName>.html``."""
    if not project_name or any(char in project_name for char in '\\/:*?"<>|\0') or project_name in (".", ".."):
        raise ValueError("Project name is not a safe file name; pass --output")
    return Path(project_name + ".html")


def _write_new(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    handle = os.open(path, flags, 0o666)
    try:
        try:
            view = memoryview(payload)
            while view:
                written = os.write(handle, view)
                if written <= 0:
                    raise OSError("Document writer made no progress")
                view = view[written:]
            os.fsync(handle)
        finally:
            os.close(handle)
    except BaseException:
        # Created exclusively by this call, so a partial document is ours to remove.
        os.unlink(path)
        raise


def _generated_at(value: str | None, source: Path) -> datetime:
    if value is None:
        return datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc).replace(tzinfo=None)
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("--generated-at must be an ISO date and time") from exc


def run(args) -> tuple[dict[str, Any], int]:
    model = load_model(args.file, native_xml=getattr(args, "native_xml", False))
    networks = None
    if args.network is not None:
        if args.network not in model.by_address:
            raise ProjectError(f"Network {args.network} is absent from the project")
        networks = [args.network]
    catalog = None
    if args.catalog is not None:
        from .calculator import CalculatorCatalog
        catalog = CalculatorCatalog.load(args.catalog)
    output = args.output if args.output is not None else default_output_name(model.name)
    text, summary = render(model, generated=_generated_at(args.generated_at, Path(args.file)),
                           networks=networks, catalog=catalog)
    payload = encode(text)
    _write_new(Path(output), payload)
    return {
        "format": FORMAT,
        "project": {"name": model.name, "sha256": model.digest, "bytes": model.size, "format": model.format},
        "file": str(output), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
        **summary, "parity": dict(PARITY),
    }, 0


def options(commands) -> None:
    from .cli import _byte

    parser = commands.add_parser(
        "document",
        help="Write the Toolkit Document Project HTML for a saved XML/CBZ project; never overwrites",
    )
    parser.add_argument("file", type=Path)
    parser.add_argument("--native-xml", action="store_true",
                        help="Read an explicit saved native DBGETXML Installation snapshot (no server access)")
    parser.add_argument("--output", type=Path,
                        help="New HTML file (default: <project name>.html, as the Toolkit names it)")
    parser.add_argument("--network", type=_byte, metavar="N", help="Document only this network")
    parser.add_argument("--generated-at", metavar="ISO",
                        help="Timestamp for 'Generated on:' (default: the project file's modification time, UTC)")
    parser.add_argument("--catalog", type=Path, default=None,
                        help="cbusunits.xml for the network calculator lines; omitted lines are marked")
