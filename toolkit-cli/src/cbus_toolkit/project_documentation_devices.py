"""Source-pinned device bodies for the offline project documentor.

The PP adapters require explicit, complete data for every consumed array.  They
never turn a missing parameter into an unused group or a disabled association.
These are static reconstructions; original generated-page acceptance is open.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .project_documentation import Network, Unit, _Writer

# Exact original unit registrations and virtual GetMaxChannels implementations.
CLASSIC_OUTPUT_CHANNELS = {"RELAY1": 1, "RELAY2": 2, "RELAY4": 4, "DIMMER4": 4, "AN_OUT4": 4}
DMX_CHANNELS = 12
DMX_MAPPING_BANKS = 16
DMX_BANK_SIZE = 32


def _required_array(unit: Unit, name: str, count: int, maximum: int = 255) -> list[int]:
    values = unit.array(name)
    if values is None or len(values) < count or any(not 0 <= value <= maximum for value in values):
        raise ValueError(f"{name} (requires {count} explicit values in 0..{maximum})")
    return values[:count]


def _primary_application(unit: Unit) -> int:
    return _required_array(unit, "Application", 1)[0]


def _group_link(network: Network, application: int, address: int) -> str:
    from .project_documentation import html_group
    app = network.application(application)
    group = app.group(address) if app is not None else None
    if group is None:
        raise ValueError(f"unresolved Application {application} Group {address}")
    return html_group(network, application, group)


def classic_output_data(unit: Unit) -> tuple[int, list[int], list[list[int]], list[int]]:
    """Decode only PP fields consumed by the classic relay documentor.

    The agent loads six group slots and one association bit-vector per slot.
    LogicFunctionAndPowerUpDelay bit zero is the Min/Max selector.
    """
    count = CLASSIC_OUTPUT_CHANNELS.get(unit.unit_type.upper())
    if count is None:
        raise ValueError("unrecovered classic output class")
    return (_primary_application(unit), _required_array(unit, "GroupAddress", 6),
            [_required_array(unit, f"LogicGA{slot}Associations", count) for slot in range(6)],
            _required_array(unit, "LogicFunctionAndPowerUpDelay", count))


def document_classic_output(out: _Writer, network: Network, unit: Unit) -> str:
    """TClassicOutputDocumentor.DocumentHTML, including its GA5 indexing quirk."""
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        application, groups, associations, functions = classic_output_data(unit)
    except ValueError as exc:
        out.mark(network, unit, f"Classic output channels: {exc}")
        return "partial"
    rows = []
    for channel, function in enumerate(functions):
        # 0x1018132 tests slot 5; 0x101815c then loads slot 0 for display.
        # Deliberately retain duplicate groups: the original uses TList.Add.
        members = [groups[slot if slot != 5 else 0] for slot in range(6)
                   if associations[slot][channel] and groups[slot] != 255]
        try:
            text = ", ".join(_group_link(network, application, group) for group in members) if members else "&nbsp;"
        except ValueError as exc:
            out.mark(network, unit, f"Classic output channels: {exc}")
            return "partial"
        logic = ("Max" if function & 1 else "Min") if len(members) > 1 else "&nbsp;"
        rows.append(f"<tr><td>{channel + 1}</td><td>{text}</td><td>{logic}</td></tr>")
    out.add('<table border="1">')
    out.add("<tr><th>Channel</th><th>Groups</th><th>Logic Function</th></tr>")
    for row in rows:
        out.add(row)
    out.add("</table>")
    out.add("<br />")
    return "recovered"


def dmx_gateway_data(unit: Unit) -> tuple[int, list[int], list[int]]:
    """Decode the 12 channel groups and 16 by 32 one-based channel slot map."""
    if unit.unit_type.upper() != "DMXDO12":
        raise ValueError("unrecovered DMX gateway class")
    application = _primary_application(unit)
    groups = _required_array(unit, "GroupAddress", DMX_CHANNELS)
    mappings = [value for bank in range(1, DMX_MAPPING_BANKS + 1)
                for value in _required_array(unit, f"DMXSlotMapping{bank}", DMX_BANK_SIZE, DMX_CHANNELS)]
    return application, groups, mappings


def document_dmx_gateway(out: _Writer, network: Network, unit: Unit) -> str:
    """TDMXGatewayDocumentor.DocumentHTML with its original string ordering.

    Channels sharing a group each produce a row listing *all* slots for that
    group.  Original 0x123f6b6 prepends the closing cells before the row text;
    preserve that malformed HTML until an original-page comparison supersedes
    the pinned instruction evidence.
    """
    from .project_documentation import document_base
    document_base(out, network, unit)
    try:
        application, groups, mappings = dmx_gateway_data(unit)
    except ValueError as exc:
        out.mark(network, unit, f"DMX gateway mappings: {exc}")
        return "partial"
    rows = []
    for group in groups:
        if group == 255:
            continue
        slots = [str(slot) for slot, channel in enumerate(mappings, start=1)
                 if channel and groups[channel - 1] == group]
        if slots:
            try:
                link = _group_link(network, application, group)
            except ValueError as exc:
                out.mark(network, unit, f"DMX gateway mappings: {exc}")
                return "partial"
            rows.append(f'</td></tr><tr><td>{link}</td><td>{", ".join(slots)}')
    out.add('<table border="1"><tr><th>Group</th><th>DMX Slots</th></tr>')
    for row in rows:
        out.add(row)
    out.add("</table>")
    return "recovered"


DOCUMENTORS = {"ClassicOutput": document_classic_output, "DMXGateway": document_dmx_gateway}
