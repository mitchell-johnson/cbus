"""Literal Toolkit wireless, gateway and remote-control report bodies."""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Sequence

from .project_documentation_devices import _classic_preset_cell, _group_link, _required_array
from .project_documentation_wireless_facts import COMMAND_DESCRIPTIONS, MACRO_DESCRIPTIONS, REMOTE_TYPES, WIRELESS_TYPES
from .project_documentation_wireless_loader import (
    GatewayKey, WirelessData, WirelessScene, gateway_profile, gateway_remote_data,
    input_remote_maps, remote_profile, wireless_channels, wireless_key_data,
)

if TYPE_CHECKING:
    from .project_documentation import Network, Unit, _Writer

CURVES = ('None (1:1 mapping)', 'Incandescent Lighting', 'Fan Control')
GATEWAY_FUNCTIONS = ('Group Dimmer', 'Scene Set', 'Scene Toggle')


def remote_key_display(unit: Unit, index: int) -> tuple[bool, str]:
    """TWTXU's original ten-key display mapping and page visibility."""
    remote_profile(unit)
    kind = unit.unit_type.replace(" ", "")
    number = 10 - index if index < 10 and kind in (
        'NEOI1FL', 'NEOI4FL', 'NEOIHHR', 'WTXU2FL', 'WTXU6FL') else index + 1
    per_page = {'NEOI1FL': 1, 'WTXU2FL': 2, 'NEOI4FL': 4}.get(kind, 5)
    visible = (number - 1) % 5 < per_page
    page, ordinal = ('Blue', number) if number <= 5 else ('Red', number - 5)
    if kind == 'NEOI1FL':
        text = f'{page} {ordinal}'
    elif kind == 'NEOI4FL':
        text = f'{page} {ordinal - 1}'
    elif kind == 'NEOIHHR':
        text = f'{"Scene" if number <= 5 else "Device"} {ordinal}'
    elif kind in ('WTXU2FL', 'WTXU6FL'):
        text = f'{page} {(2 if kind == "WTXU2FL" else 5) - (ordinal - 1)}'
    else:
        text = str(number) if number <= 5 else f'Shift {number - 5}'
    return visible, text


def wireless_key_html(network: Network, data: WirelessData, index: int) -> str:
    key = data.keys[index]
    prefix = f'<td>{index + 1}</td>'
    members = [data.groups[block] for block in key.blocks if data.groups[block][1] != 255]
    if key.kind == 22 or (not key.scene_key and not members):
        return prefix + '<td>Unused</td><td>&nbsp;</td>'
    description = MACRO_DESCRIPTIONS[key.kind]
    if key.scene_key:
        control = '&nbsp;' if key.scene is None else f'Scene {key.scene + 1}'
        return prefix + f'<td>{description}</td><td>{control}</td>'
    value = prefix + f'<td>{description}</td><td><table border="1"><tr><th>Group</th>'
    if key.kind in (20, 34):
        value += '<th>Preset 1</th>'
    if key.kind in (21, 34):
        value += '<th>Preset 2</th>'
    if key.kind in (13, 34):
        value += '<th>Timer</th><th>Expiry</th>'
    value += '</tr>'
    for application, group in members:
        # The original list keeps duplicate group references and then looks
        # up the first block in the unit's full collection for each reference.
        block = data.groups.index((application, group))
        value += '<tr><td>' + _group_link(network, application, group) + '</td>'
        if key.kind in (20, 34):
            value += _classic_preset_cell(network, application, group, data.memory1[block])
        if key.kind in (21, 34):
            value += _classic_preset_cell(network, application, group, data.memory2[block])
        if key.kind in (13, 34):
            hours, remainder = divmod(data.timers[block] & 65535, 3600)
            minutes, seconds = divmod(remainder, 60)
            value += f'<td>{hours}h{minutes}m{seconds}s</td><td>{COMMAND_DESCRIPTIONS[data.expiry[block]]}</td>'
        value += '</tr>'
    return value + '</table></td>'


def _trigger_link(network: Network, scene: WirelessScene) -> str:
    application = network.application(202)
    group = application.group(scene.trigger_group) if application is not None else None
    level = next((level for level in group.levels if level.address == scene.trigger_address), None) if group else None
    if level is None:
        raise ValueError(f'unresolved Application 202 Group {scene.trigger_group} Level Address {scene.trigger_address}')
    return f'<a href="#{network.address}_202_{group.address}_{level.address}">{level.name}</a>'


def _scene_lines(network: Network, scenes: tuple[WirelessScene, ...], referenced: set[int]) -> list[str]:
    result = ['<br />', 'Scenes<br />', '<table border="1">',
              '<tr><th>Scene</th><th>Trigger</th><th>Groups</th><th>Level</th></tr>']
    for index, scene in enumerate(scenes):
        trigger = _trigger_link(network, scene) if index in referenced and scene.has_trigger else '&nbsp;'
        links = '<br />'.join(_group_link(network, scene.application, address) for address, _ in scene.commands)
        levels = '<br />'.join(f'{(level + 2) * 100 // 255}%' for _, level in scene.commands)
        result.append(f'<tr><td>{index + 1}</td><td>{trigger}</td><td>{links}</td><td>{levels}</td></tr>')
    result.append('</table>')
    return result


def _wireless_lines(network: Network, unit: Unit) -> list[str]:
    data = wireless_key_data(unit)
    result = ['<table border="1">', '<tr><th>Key</th><th>Macro Function</th><th>Controls</th></tr>']
    for index in range(16):
        result.extend(('<tr>', wireless_key_html(network, data, index), '</tr>'))
    result.append('</table>')
    result.extend(_scene_lines(network, data.scenes, {key.scene for key in data.keys if key.scene is not None}))
    result.extend(('<br />', '<table border="1">',
                   '<tr><th>Channel</th><th>Group</th><th>Dimming Curve</th><th>Min</th><th>Max</th></tr>'))
    for index, (application, group, curve, minimum, maximum) in enumerate(wireless_channels(unit), start=1):
        row = f'<tr><td>{index}</td><td>{_group_link(network, application, group)}</td>'
        if group == 255:
            row += '<td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td>'
        else:
            # Agent LoadChannels stores percentages; the documentor applies
            # LevelToPercent a second time. Preserve the source's two calls.
            low = (((minimum + 2) * 100 // 255) + 2) * 100 // 255
            high = (((maximum + 2) * 100 // 255) + 2) * 100 // 255
            row += f'<td>{CURVES[curve]}</td><td>{low}%</td><td>{high}%</td>'
        result.append(row + '</tr>')
    result.append('</table>')
    return result


def _gateway_key_control(network: Network, key: GatewayKey) -> str:
    if key.function == 0:
        if key.group is None:
            raise ValueError('gateway key Group is undefined because primary Application is 255')
        return _group_link(network, key.application, key.group)
    if key.scene is None:
        raise ValueError('gateway scene key references a missing compacted scene')
    return f'Scene {key.scene + 1}'


def _gateway_advanced_lines(network: Network, unit: Unit) -> list[str]:
    from .project_documentation import html_unit
    scenes, remotes = gateway_remote_data(network, unit)
    result = []
    for index, (remote, keys) in enumerate(remotes, start=1):
        if remote is None:
            continue
        result.extend((f'<b>Remote {index}</b> - {html_unit(network, remote)}<br/>', '<table border="1">',
                       '<tr><th>Key</th><th>Function</th><th>Control</th></tr>'))
        for ordinal, key in enumerate(keys[:10]):
            visible, title = remote_key_display(remote, ordinal)
            if visible:
                result.append(f'<tr><td>{title}</td><td>{GATEWAY_FUNCTIONS[key.function]}</td>'
                              f'<td>{_gateway_key_control(network, key)}</td></tr>')
        result.append('</table><br/>')
    referenced = {key.scene for remote, keys in remotes if remote is not None
                  for key in keys if key.function and key.scene is not None}
    result.extend(_scene_lines(network, scenes, referenced))
    return result


def _gateway_lines(network: Network, unit: Unit, networks: Sequence[Network]) -> list[str]:
    from .project_documentation import html_application, html_network, network_by_number
    # Both adjacent and forwarding destinations use NetworkNumber, not the
    # archive object Address. Missing numbers cannot establish this lookup.
    adjacent = network_by_number(networks, unit.address)
    if adjacent is None:
        return ['WARNING: Wireless Gateway has no far side Network.']
    apps = _required_array(unit, 'Application', 2)
    connect = _required_array(unit, 'ApplicationConnectEnabled', 1, 1)[0]
    forward = _required_array(unit, 'ForwardingMode', 1, 1)[0]
    sync = _required_array(unit, 'SynchroniseToWired', 1, 1)[0]
    status = _required_array(unit, 'StatusMonitorApplication', 1)[0]
    result = [f'Adjacent Network: {html_network(adjacent)}<br/>']
    if connect:
        result.extend(f'Connect Application {index}: {html_application(network, application)}<br/>'
                      for index, application in enumerate(apps, start=1))
    else:
        result.append('Connect Applications: All Applications<br/>')
    result.append(f'Send Messages to Adjacent Network: {"Yes" if connect else "No"}<br/>')
    destination = None
    if forward:
        route = _required_array(unit, 'ForwardingRoute', 7)
        for number in route[1:]:
            if number == 255:
                break
            resolved = network_by_number(networks, number)
            if resolved is None:
                break
            destination = resolved
    result.append('Send Messages to a Remote Network: No<br/>' if destination is None else
                  f'Send Messages to Remote Network: {html_network(destination)}<br/>')
    result.append(f'Sync To Wired: {"Yes" if sync else "No"}<br/>')
    result.append(f'Status Monitor Application: {html_application(network, status)}<br/>')
    return result


def receiver_bindings(network: Network, remote: Unit) -> tuple:
    """Network order, then receiver remote-page order; retain duplicate bindings."""
    result = []
    for receiver in network.units:
        if receiver.unit_type in WIRELESS_TYPES:
            for page, (selected, mapping) in enumerate(input_remote_maps(network, receiver)):
                if selected is remote:
                    result.append(('input', receiver, page, mapping, wireless_key_data(receiver)))
        elif receiver.unit_type == 'WGATE5F' and gateway_profile(receiver):
            _, remotes = gateway_remote_data(network, receiver)
            for page, (selected, keys) in enumerate(remotes):
                if selected is remote:
                    result.append(('gateway', receiver, page, keys, None))
    return tuple(result)


def _remote_lines(network: Network, unit: Unit) -> list[str]:
    from .project_documentation import html_unit
    remote_profile(unit)
    bindings = receiver_bindings(network, unit)
    result = ['<br />', '<table border="1">', '<tr><th>Key</th><th>Controls</th></tr>']
    for index in range(10):
        visible, title = remote_key_display(unit, index)
        if not visible:
            continue
        result.append(f'<tr><td>{title}</td>')
        used = [(family, receiver, mapping[index], data) for family, receiver, _, mapping, data in bindings
                if (mapping[index] is not None if family == 'input'
                    else mapping[index].function != 0 or mapping[index].group != 255)]
        if not used:
            result.append('<td>&nbsp;</td></tr>')
            continue
        result.append('<td><table border="1"><tr><th>Unit</th><th>Key</th><th>Macro Function</th><th>Controls</th></tr>')
        for family, receiver, key, data in used:
            result.append(f'<tr><td>{html_unit(network, receiver)}</td>')
            if family == 'input':
                result.append(wireless_key_html(network, data, key))
            else:
                result.append('<td>&nbsp;</td>')
                result.append(f'<td>{GATEWAY_FUNCTIONS[key.function]}</td>')
                result.append(f'<td>{_gateway_key_control(network, key)}</td>')
            result.append('</tr>')
        result.append('</table></td></tr>')
    result.append('</table>')
    return result


def document_wireless(out: _Writer, network: Network, unit: Unit, networks: Sequence[Network]) -> str:
    """Dispatcher for all source-pinned wireless report families."""
    from .project_documentation import document_base
    try:
        if unit.unit_type in REMOTE_TYPES:
            remote_profile(unit)
            lines = _remote_lines(network, unit)
            base_unit = unit
        elif unit.unit_type in WIRELESS_TYPES:
            lines = _wireless_lines(network, unit)
            base_unit = unit
        else:
            advanced = gateway_profile(unit)
            mode = _required_array(unit, 'MapWirelessRemotes', 1, 1)[0] if advanced else 0
            lines = _gateway_advanced_lines(network, unit) if mode else _gateway_lines(network, unit, networks)
            # The advanced remote-switch override writes the same base prefix
            # through Notes but omits both clock and burden lines.
            base_unit = replace(unit, fields={**unit.fields, 'ClockGenEnable': '0', 'Burden': '0'}) if mode else unit
    except ValueError as error:
        document_base(out, network, unit)
        out.mark(network, unit, f'Wireless report: {error}')
        return 'partial'
    document_base(out, network, base_unit)
    for line in lines:
        out.add(line)
    return 'recovered'
