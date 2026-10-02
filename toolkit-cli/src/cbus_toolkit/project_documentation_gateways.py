"""Saved-PP WHAA and DALI 2B/C documentors, without vendor or device I/O.

The native report consumes the loaded object graph. In particular DALI mapping
setters remove earlier duplicate destinations, and an explicitly short mapping
string supplies zero for its missing elements. An absent string is not a known
empty string. Original source pins are recorded separately from older receipts.
"""
from __future__ import annotations

from .project_documentation_devices import _group_link, _required_array
from .project_documentation_outputs import _registration
from .project_documentation_usage import Usage

WHA_TYPES = {"PC_WHAD": "TPC_WHAD", "PC_WHAR": "TPC_WHAR", "PC_WHARB": "TPC_WHARB"}
DALI_TYPES = {"PC_DAL2B": "TPC_DAL2B", "PC_DAL2C": "TPC_DAL2C"}
WHA_GROUPS = (
    ("AlternateVolumeControlGroup", "Volume Control"),
    ("AlternateBassControlGroup", "Bass Control"),
    ("AlternateTrebleControlGroup", "Treble Control"),
    ("AlternateNextSourceGroup", "Next Source"),
    ("AlternatePrevSourceGroup", "Prev Source"),
    ("AlternateButtonAGroup", "Button A"),
    ("AlternateButtonBGroup", "Button B"),
    ("AlternateLanguageGroup", "Language Group"),
    ("AlternateAbsoluteSourceGroup", "Absolute Source"),
)


def _profile(unit, family):
    row = _registration(unit)
    classes = WHA_TYPES if family == "WHAA" else DALI_TYPES
    agent = "TCBusPC_WHAACGateAgent" if family == "WHAA" else "TCBusPC_DAL2BCGateAgent"
    if row is None or row[3:5] != (classes.get(unit.unit_type.upper()), agent):
        raise ValueError(f"unrecovered {family} class or firmware")
    return unit.unit_type.upper()


def _byte(unit, name):
    return _required_array(unit, name, 1)[0]


def whaa_data(unit):
    _profile(unit, "WHAA")
    data = {"auto_zone": _byte(unit, "UsePnP") > 0,
            "application": _byte(unit, "AlternateApplication")}
    if not data["auto_zone"]:
        zone = _byte(unit, "ZoneNumber")
        matrix = 0 if zone < 8 else 1 if zone < 16 else 2
        data.update(matrix=matrix + 1, zone=min(7, zone - matrix * 8) + 1)
    if data["application"] != 255:
        data["groups"] = {name: _byte(unit, name) for name, _ in WHA_GROUPS
                          if name != "AlternateLanguageGroup"}
    return data


def whaa_lines(network, data):
    from .project_documentation import html_application
    lines = [f'Use Matrix Switcher Auto Assign Zone: {"Yes" if data["auto_zone"] else "No"}<br/>']
    if not data["auto_zone"]:
        lines += [f'Matrix Switcher Number: {data["matrix"]}<br/>', f'Zone Number: {data["zone"]}<br/>']
    lines.append("<br/>")
    app = data["application"]
    if app == 255:
        return lines + ["CBus Control Application: &#60;Unused&#62;<br/>"]
    lines.append(f"CBus Control Application: {html_application(network, app)}<br/>")
    for title, rows in (
        ("Audio Control", (("Volume", "AlternateVolumeControlGroup"),
                           ("Bass", "AlternateBassControlGroup"),
                           ("Treble", "AlternateTrebleControlGroup"))),
        ("Source/Dynamic Control Groups", (("Next Source", "AlternateNextSourceGroup"),
                                           ("Prev Source", "AlternatePrevSourceGroup"),
                                           ("Absolute", "AlternateAbsoluteSourceGroup"),
                                           ("Dynamic 1", "AlternateButtonAGroup"),
                                           ("Dynamic 2", "AlternateButtonBGroup"))),
    ):
        table = f'<table border="1"><tr><th colspan="2">{title}</th></tr>'
        table += "".join(f"<tr><th>{label}</th><td>{_group_link(network, app, data['groups'][name])}</td></tr>"
                         for label, name in rows)
        lines.append(table + "</table>")
    return lines


def _mapping(unit, name):
    values = unit.array(name)
    if values is None or any(not 0 <= value <= 255 for value in values):
        raise ValueError(f"{name} (explicit byte string required)")
    # IntArrayElementWithDefault(..., default=0), followed by ascending setter
    # calls. Each setter clears other entries with the same non-255 value.
    values = (values + [0] * 256)[:256]
    last = {value: index for index, value in enumerate(values) if value != 255}
    return tuple(value if value == 255 or last[value] == index else 255
                 for index, value in enumerate(values))


def dali_action_name(address):
    for network, start in (("A", 0), ("B", 128)):
        relative = address - start
        if 0 <= relative < 64:
            return f"DALI {network} Unit {relative}"
        if 64 <= relative < 80:
            return f"DALI {network} Group {relative - 63}"
        if 80 <= relative < 96:
            return f"DALI {network} Scene {relative - 79}"
        if relative in (96, 97):
            return f'DALI {network} {"Broadcast" if relative == 96 else "Off"}'
    if address == 255:
        return "Unused"
    raise ValueError(f"unregistered DALI action {address}")


def dali_data(unit):
    kind = _profile(unit, "DALI2B")
    applications = _required_array(unit, "Application", 2)
    data = {"application": applications[1], "c_to_d": _mapping(unit, "CBusToDali"),
            "d_to_c": _mapping(unit, "DaliToCBus"), "networks": []}
    for network in ("A", "B"):
        prefix = "Dali" + network
        report = _byte(unit, prefix + "ErrorReportingStatus") != 0
        ramp = _byte(unit, prefix + "RampMatching")
        row = {"network": network, "report": report, "ramp": bool(ramp & 1),
               "kind_c": kind == "PC_DAL2C"}
        if report:
            refresh = _byte(unit, prefix + "ErrorRefreshTime")
            row["refresh"] = 1 if refresh == 255 else min(refresh, 59) + 1
        for field, application, parameter in (("enable", 203, "EnableErrorGroup"),
                                               ("disable", 203, "DisableErrorGroup"),
                                               ("trigger", 202, "TriggerErrorGroup")):
            group = _byte(unit, prefix + parameter)
            row[field] = (application, group, None if group == 255 else
                          _byte(unit, prefix + ("TriggerErrorAcSel" if field == "trigger" else
                                               field.capitalize() + "ErrorLevel")))
        row["correction"] = kind == "PC_DAL2C" and bool(ramp & 2)
        if row["correction"]:
            row["restore"] = (_byte(unit, prefix + "RestoreLevel") + 2) * 100 // 255
        else:
            start = 0 if network == "A" else 128
            row["mapping"] = any(value != 255 for value in data["d_to_c"][start:start + 128])
        data["networks"].append(row)
    return data


def _level(network, application, group, address):
    app = network.application(application)
    record = app.group(group) if app else None
    level = next((row for row in record.levels if row.address == address), None) if record else None
    if level is None:
        raise ValueError(f"unresolved Application {application} Group {group} Level {address}")
    return f'<a href="#{network.address}_{application}_{group}_{address}">{level.name}</a>'


def dali_lines(network, data):
    def row(label, value):
        return f"<tr><th>{label}</th><td>{value}</td></tr>"

    lines = ['<table border="0">', '<tr><th>Dali Network A</th><th>Dali Network B</th></tr><tr>']
    for facts in data["networks"]:
        table = '<td><table border="1">'
        table += row("Live Error Reporting", "On" if facts["report"] else "Off")
        table += row("Refresh Error Time", str(facts["refresh"]) + " min" if facts["report"] else "&nbsp; min")
        for field, title, value_title in (("enable", "Enable Error Reporting", "Value"),
                                           ("disable", "Disable Error Reporting", "Value"),
                                           ("trigger", "Trigger Full Error Report", "Action Selector")):
            app, group, level = facts[field]
            table += row(title + " Group", "Unused" if group == 255 else _group_link(network, app, group))
            label = "Trigger Full Report Action Selector" if field == "trigger" else title + " " + value_title
            table += row(label, "&nbsp;" if group == 255 else _level(network, app, group, level))
        table += row("Match Ramp Rate", "Yes" if facts["ramp"] else "No")
        if facts["correction"]:
            table += row("Status Correction", "On")
            table += row("Dali " + facts["network"] + " Restore Level", str(facts["restore"]) + "%")
        else:
            if "correction" in facts and facts.get("kind_c"):
                table += row("Status Correction", "Off")
            table += row("Dali " + facts["network"] + " to C-Bus Mapping",
                         "1:1 Mapping" if facts["mapping"] else "Disabled")
        lines.append(table + "</table></td>")
    lines += ['</tr></table>', '<br/>', '<table border="1">',
              '<tr><th>C-Bus Group</th><th>Dali Action</th><th>Mapping</th></tr>']
    mappings = ""
    for group, action in enumerate(data["c_to_d"][:255]):
        if action == 255:
            continue
        link = _group_link(network, data["application"], group)
        mapping = "1:1 Mapping" if data["d_to_c"][action] == group else "Diabled"
        mappings += f"<tr><td>{link}</td><td>{dali_action_name(action)}</td><td>{mapping}</td></tr>"
    return lines + [mappings, '</table>']


def _document(out, network, unit, family, data_function, lines_function):
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        lines = lines_function(network, data_function(unit))
    except ValueError as error:
        out.mark(network, unit, f"{family} report: {error}")
        return "partial"
    for line in lines:
        out.add(line)
    return "recovered"


def document_whaa(out, network, unit):
    return _document(out, network, unit, "WHAA", whaa_data, whaa_lines)


def document_dali(out, network, unit):
    return _document(out, network, unit, "DALI2B", dali_data, dali_lines)


def gateway_group_usage(unit, application, group, kind):
    if kind not in {"input", "output", "other"}:
        raise ValueError("Group usage kind must be input, output or other")
    try:
        if unit.unit_type.upper() in WHA_TYPES:
            _profile(unit, "WHAA")
            if kind != "other":
                return Usage()
            if application != _byte(unit, "AlternateApplication"):
                return Usage()
            return Usage("<br/>".join(label for name, label in WHA_GROUPS if _byte(unit, name) == group))
        _profile(unit, "DALI2B")
        if kind == "other":
            if application != 203:
                return Usage()
            fields = (("DaliAEnableErrorGroup", "Dali A Enable Error Group"),
                      ("DaliBEnableErrorGroup", "Dali B Enable Error Group"),
                      ("DaliADisableErrorGroup", "Dali A Disable Error Group"),
                      ("DaliBDisableErrorGroup", "Dali B Disable Error Group"))
            return Usage("<br/>".join(label for name, label in fields if _byte(unit, name) == group))
        if application != _required_array(unit, "Application", 2)[1]:
            return Usage()
        forward = _mapping(unit, "CBusToDali")
        action = forward[group]
        if kind == "output":
            return Usage(dali_action_name(action) if action != 255 else "")
        reverse = _mapping(unit, "DaliToCBus")
        return Usage(dali_action_name(action) if reverse[action] == group else "")
    except (ValueError, IndexError) as error:
        return Usage(status="unrecovered", missing=(str(error),))


def dali_action_selector_usage(unit, application, group, address, value):
    del value  # The native comparison is Level object identity, not Level.Value.
    try:
        _profile(unit, "DALI2B")
        if application != 202:
            return Usage()
        labels = []
        for network in ("A", "B"):
            trigger = _byte(unit, "Dali" + network + "TriggerErrorGroup")
            if trigger != 255 and trigger == group and _byte(unit, "Dali" + network + "TriggerErrorAcSel") == address:
                labels.append("<li />Trigger Dali Network " + network + " Error Report")
        return Usage("".join(labels))
    except ValueError as error:
        return Usage(status="unrecovered", missing=(str(error),))
