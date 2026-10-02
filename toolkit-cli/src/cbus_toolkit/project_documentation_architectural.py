"""The complete architectural dimmer DocumentHTML body for admitted snapshots.

Original line boundaries and malformed table cells are intentional. Static
source reconstruction is separate from original generated-page acceptance.
"""
from __future__ import annotations

from .project_documentation_devices import _group_link
from .project_documentation_architectural_loader import (
    CURVES, RAMPS, architectural_data, cross_fade_parts, percent, rms_voltage,
)


def _level_link(network, group, address):
    application = network.application(202)
    obj = application.group(group) if application else None
    level = next((level for level in obj.levels if level.address == address), None) if obj else None
    if level is None:
        raise ValueError(f"unresolved Application 202 Group {group} Level {address}")
    return f'<a href="#{network.address}_202_{group}_{address}">{level.name}</a>'


def architectural_body_lines(network, unit):
    data = architectural_data(unit)
    app, count = data["application"], data["count"]
    group = lambda address: _group_link(network, app, address)
    lines = ["C-Bus Lock Enable Group: " + _group_link(network, 203, data["enable"]) + "<br />",
             '<table border="1">']
    header = '<tr><th>Channel</th><th>Groups</th><th>Logic Function</th><th>Curve</th><th>Fan Kickstart</th><th>Min</th><th>Max</th><th>Max RMS Voltage</th><th>Turn On Threshold</th>'
    if data["enable"] != 255:
        header += ''.join(f'<th>C-Bus Mask {mask}</th>' for mask in range(1, 5))
    lines.append(header + '</tr>')
    for index in range(count):
        members = ([data["groups"][index]] if data["groups"][index] != 255 else [])
        members += [address for slot, address in enumerate(data["logic"])
                    if address != 255 and data["associations"][slot][index]]
        groups = ', '.join(group(address) for address in members) if members else '&nbsp;'
        logic = ('Max' if data["functions"][index] else 'Min') if len(members) > 1 else '&nbsp;'
        # DocumentHTML starts the Curve cell without closing the Logic cell.
        row = f'<tr><td>{index + 1}</td><td>{groups}</td><td>{logic}<td>{CURVES[data["curves"][index]]}</td>'
        row += ('<td>' + str(data["kickstart"][index]) + ' s</td>'
                if data["curves"][index] == 0 else '<td>&nbsp;</td>')
        row += f'<td>{percent(data["minimum"][index])}%</td><td>{percent(data["maximum"][index])}%</td>'
        voltage = rms_voltage(data["max_voltage"][index], data["line_voltage"])
        row += '<td>' + (f'LINE({voltage})' if voltage == data["line_voltage"] else str(voltage)) + '</td>'
        row += f'<td>{percent(data["threshold"][index])}%</td>'
        if data["enable"] != 255:
            row += ''.join('<td>Yes</td>' if mask[index] else '<td>&nbsp;</td>' for mask in data["cbus_masks"])
        lines.append(row + '</tr>')
    lines += ['</table>', '<br />', 'DMX Enable Group: ' + _group_link(network, 203, data["dmx_enable"]) + '<br />',
              '<table border="1">']
    dmx = '<tr><th>Channel</th><th>DMX</th>'
    if data["dmx_enable"] != 255:
        dmx += '<th>Enable Fade Time</th><th>Set 1</th><th>Set 2</th><th>Set 3</th><th>Set 4</th><th>Disable Operation</th><th>Duration</th>'
    dmx += '</tr>'
    for index, patch in enumerate(data["dmx"]):
        dmx += f'<tr><td>{index + 1}</td><td>' + (str(patch) if patch else '&lt;DMX Disabled&gt;') + '</td>'
        # The original renders all extended columns even for a disabled patch.
        if data["dmx_enable"] != 255:
            dmx += f'<td>{data["dmx_on"][index]} s</td>'
            dmx += ''.join('<td>Yes</td>' if mask[index] else '<td>&nbsp;</td>' for mask in data["dmx_masks"])
            if data["dmx_take"][index]:
                dmx += f'<td>Take C-Bus</td><td>{data["dmx_off"][index]} s</td>'
            else:
                dmx += f'<td>Update C-Bus</td><td>{RAMPS[data["dmx_ramp"][index]]}</td>'
        dmx += '</tr>'
    lines += [dmx + '</table>', '<br />', '<b>Special Scenes</b><br />', '<table border="1">']
    special = '<tr><th>Scene</th><th>Parameters</th><th>Controls</th></tr>'
    labels = (('SceneDryContact1', 'Panic/Dry Contact 1 (aux1)'), ('SceneDryContact2', 'Panic/Dry Contact 2 (aux2)'),
              ('SceneDryContact3', 'Panic/Dry Contact 3 (aux3)'), ('SceneLoadShed', 'Backup Generator / Load Shed (aux4)'),
              ('SceneCBusLoss', 'C-Bus Loss'))
    for field, label in labels:
        if not data["special"][field]:
            continue
        special += '<tr><td>' + label + '</td><td>'
        special += (f'<table border="1"><tr><th>Fade Time</th></tr><tr><td>{data["loss_fade"]} s</td></tr></table>'
                    if field == 'SceneCBusLoss' else '&nbsp;')
        special += '</td><td><table border="1"><tr><th>Channel</th><th>Group</th><th>Level</th></tr>'
        for index, target in data["special"][field]:
            special += f'<tr><td>{index + 1}</td><td>{group(data["groups"][index])}</td><td>{target} ({percent(target)}%)</td></tr>'
        special += '</table></td></tr>'
    if data["halogen"] is not None and any(data["halogen_mask"]):
        special += '<tr><td>Halogen Clean</td><td><table border="1"><tr><th>Action Selector</th><th>Fade Time</th><th>Duration</th></tr><tr>'
        special += '<td>' + _level_link(network, *data["halogen"]) + '</td>'
        special += f'<td>{data["halogen_fade"]} s</td><td>{data["halogen_duration"]} m</td></tr></table></td><td>'
        special += '<table border="1"><tr><th>Channel</th><th>Group</th></tr>'
        special += ''.join(f'<tr><td>{index + 1}</td><td>{group(data["groups"][index])}</td></tr>'
                           for index, used in enumerate(data["halogen_mask"]) if used)
        special += '</table></td></tr>'
    lines += [special + '</table>', '<br />', '<b>Scenes</b><br />']
    ordinary = '<table border="1"><tr><th>Scene</th><th>Action Selector</th><th>Cross Fade Time</th><th>Controls</th></tr>'
    for scene in data["scenes"]:
        selector = '&nbsp;' if scene.selector is None else _level_link(network, scene.trigger, scene.selector)
        fade = '%dd %dh %dm %d s' % cross_fade_parts(scene.fade) if scene.cross_fade else '&nbsp;'
        ordinary += f'<tr><td>{scene.name}</td><td>{selector}</td><td>{fade}</td>'
        ordinary += '<td><table border="1"><tr><th>Group</th><th>Level</th>'
        if not scene.cross_fade:
            ordinary += '<th>Ramp Rate</th>' if scene.use_ramp else '<th>Fade Time</th>'
        ordinary += '</tr>'
        for channel in scene.groups:
            ordinary += f'<tr><td>{group(channel.group)}</td><td>{percent(channel.target)}%</td>'
            if not scene.cross_fade:
                ordinary += '<td>' + (RAMPS[channel.fade] if scene.use_ramp else str(channel.fade)) + '</td>'
            ordinary += '</tr>'
        ordinary += '</table></td></tr>'
    lines += [ordinary + '</table>', '<br />']
    return lines


def document_architectural(out, network, unit):
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        lines = architectural_body_lines(network, unit)
    except ValueError as error:
        out.mark(network, unit, f'Architectural dimmer controls: {error}')
        return 'partial'
    for line in lines:
        out.add(line)
    return 'recovered'
