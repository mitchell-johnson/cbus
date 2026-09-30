"""Old DIMPR12 documentor from explicit, bounded saved programming fields."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .project_documentation_bytecraft_loader import decode_bytecraft_scenes
from .project_documentation_devices import _group_link, _required_array

if TYPE_CHECKING:
    from .project_documentation import Network, Unit, _Writer

CURVE_DESCRIPTIONS = ('Lite 1', 'Lite 2', 'Lite 3', 'Non Dim', 'Lin RMS', '1:1')
FADE_DESCRIPTIONS = ('Instantaneous', '4 s', '8 s', '12 s', '20 s', '30 s', '40 s',
                     '1 min', '1.5 min', '2 min', '3 min', '5 min', '7 min',
                     '10 min', '15 min', '17 min')


def _nibbles(unit: Unit, name: str) -> tuple[int, ...]:
    values = _required_array(unit, name, 6)
    return tuple((values[index // 2] >> (4 * (index % 2))) & 15 for index in range(12))


def _bits(unit: Unit, name: str) -> tuple[bool, ...]:
    # The original requires sixteen single-character text bits, then swaps the
    # two eight-bit halves before selecting a character. These are not bytes.
    raw = unit.parameters.get(name)
    values = unit.array(name)
    if (not isinstance(raw, str) or values is None or len(values) != 16
            or any(value not in (0, 1) for value in values)
            or raw.strip(' \t\r\n') != ' '.join(map(str, values))):
        raise ValueError(f'{name} (requires sixteen canonical text bits)')
    return tuple(bool(values[(index + 8) % 16]) for index in range(16))


def _percent(value: int) -> str:
    return f'{(value + 2) * 100 // 255}%'


def _level_link(network: Network, group_address: int, address: int) -> str:
    group = network.application(202).group(group_address) if network.application(202) else None
    level = next((level for level in group.levels if level.address == address), None) if group else None
    if level is None:
        raise ValueError(f'unresolved Application 202 Group {group_address} Level {address}')
    # The original common Level formatter preserves the tag literally.
    return f'<a href="#{network.address}_202_{group_address}_{address}">{level.name}</a>'


def bytecraft_body_lines(network: Network, unit: Unit) -> list[str]:
    """Project the old class only, retaining the original malformed table tags."""
    scenes = decode_bytecraft_scenes(unit)
    application = _required_array(unit, 'Application', 1)[0]
    groups = _required_array(unit, 'GroupAddress', 12)
    disable = _required_array(unit, 'CBusDisableGroupAddress', 1)[0]
    switch = _required_array(unit, 'DMXCBusSwitchAddress', 1)[0]
    switching = _bits(unit, 'DMXCbusSwitchOverActionAndRestoreMode')
    restore = switching[15]
    raw_patches = _required_array(unit, 'DMXPatchInfo', 24)
    patches = tuple((raw_patches[index * 2] << 8) + raw_patches[index * 2 + 1] for index in range(12))
    used = [index for index, group in enumerate(groups) if group != 255]
    if used:
        curves = _nibbles(unit, 'ChannelDimmerCurve')
        if any(curves[index] >= len(CURVE_DESCRIPTIONS) for index in used):
            raise ValueError('ChannelDimmerCurve (unrecovered curve ordinal)')
        minimum = _required_array(unit, 'ChannelMinLevel', 12)
        maximum = _required_array(unit, 'ChannelMaxLevel', 12)
        voltage = _required_array(unit, 'MaxChannelVoltage', 12)
        locks = _bits(unit, 'CBusDisable') if disable != 255 else None
    else:
        curves = minimum = maximum = voltage = locks = None
    if switch != 255 and any(patches):
        cbus_fade = _nibbles(unit, 'CbusDMXSwitchOverFadeTime')
        dmx_fade = _nibbles(unit, 'DMXCbusSwitchOverFadeTime')
    else:
        cbus_fade = dmx_fade = None
    lines = ['C-Bus Lock Enable Group: ' + _group_link(network, 203, disable) + '<br />',
             'DMX Enable Group: ' + _group_link(network, 203, switch) + '<br />']
    if restore:
        lines += ['Control Failure Scene: Enabled<br />',
                  'Control Failure Scene Ramp Rate: ' + FADE_DESCRIPTIONS[scenes[0].ramp_on] + '<br />']
    else:
        lines.append('Control Failure Scene: Disabled<br />')
    lines += ['<br />', '<table border="1">']
    header = '</tr><tr><th>Channel</th><th>Groups</th><th>Logic Function</th><th>Curve</th><th>Min</th><th>Max</th>'
    if disable != 255:
        header += '<th>C-Bus Lock</th>'
    header += '<th>Max RMS Voltage</th>'
    if switch != 255:
        header += '<th>DMX</th><th>Take|Update</th><th>C-Bus Fade</th><th>DMX Fade</th>'
    if restore:
        header += '<th>Restore Level</th>'
    lines.append(header)
    for index, group in enumerate(groups):
        if group == 255 and patches[index] == 0:
            continue
        row = f'</tr><tr><td>{index + 1}</td><td>' + _group_link(network, application, group) + '</td><td>&nbsp;</td>'
        if group != 255:
            row += f'<td>{CURVE_DESCRIPTIONS[curves[index]]}</td><td>{_percent(minimum[index])}</td><td>{_percent(maximum[index])}</td>'
            if disable != 255:
                row += '<td>' + ('Yes' if locks[index] else 'No') + '</td>'
            row += '<td>' + ('LINE' if voltage[index] in (0, 255) else str(voltage[index])) + '</td>'
        else:
            if disable != 255:
                row += '<td>&nbsp;</td>'
            row += '<td>&nbsp;</td>' * 4
        if switch != 255:
            if patches[index] == 0:
                row += '<td>&#60;Unused&#62;</td>' + '<td>&nbsp;</td>' * 3
            else:
                row += (f'<td>{patches[index]}</td><td>' + ('Update' if switching[index] else 'Take')
                        + f'</td><td>{FADE_DESCRIPTIONS[cbus_fade[index]]}</td><td>{FADE_DESCRIPTIONS[dmx_fade[index]]}</td>')
        if restore:
            row += '<td>' + (_percent(scenes[0].on_levels[index]) if scenes[0].on[index] else '&nbsp;') + '</td>'
        lines.append(row)
    lines += ['</table>', 'Scenes: <br />', '<table border="1"',
              '<tr><th>Scene</th><th>Scene Type</th><th>Trigger</th><th>Scene On</th><th>Scene Off</th></tr>']
    for scene in scenes[1:]:
        if scene.unused:
            continue
        lines.append(f'<tr><td>{scene.index}</td>')
        lines.append('<td>' + ('Advanced' if scene.advanced else 'Basic') + '</td>')
        trigger = (_group_link(network, 202, scene.recall_group) if scene.advanced
                   else _level_link(network, scene.recall_group, scene.selector_address))
        lines.append('<td>' + trigger + '</td>')
        for included, levels, ramp, show in (
            (scene.on, scene.on_levels, scene.ramp_on, not scene.on_unused),
            (scene.off, scene.off_levels, scene.ramp_off, scene.advanced and not scene.off_unused),
        ):
            if not show:
                lines.append('<td>&nbsp;</td>')
                continue
            lines += ['<td><table border="1">', '<tr><th>Group</th><th>Level</th><th>Ramp Rate</th></tr>']
            for index, group in enumerate(groups):
                if included[index] and group != 255:
                    lines.append('<tr><td>' + _group_link(network, application, group)
                                 + f'</td><td>{_percent(levels[index])}</td><td>{FADE_DESCRIPTIONS[ramp]}</td></tr>')
            lines += ['</table>', '</td>']
        lines.append('</tr>')
    lines.append('</table>')
    return lines


def document_bytecraft(out: _Writer, network: Network, unit: Unit) -> str:
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        lines = bytecraft_body_lines(network, unit)
    except ValueError as error:
        out.mark(network, unit, f'Bytecraft controls: {error}')
        return 'partial'
    for line in lines:
        out.add(line)
    return 'recovered'
