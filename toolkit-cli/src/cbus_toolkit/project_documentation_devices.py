"""Source-pinned device bodies for the offline project documentor.

The PP adapters require explicit, complete data for every consumed array.  They
never turn a missing parameter into an unused group or a disabled association.
These are static reconstructions; original generated-page acceptance is open.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .macros import MICRO_FUNCTION_LABELS, PRESETS, STAGES

if TYPE_CHECKING:
    from .project_documentation import Network, Unit, _Writer

# Exact original unit registrations and virtual GetMaxChannels implementations.
CLASSIC_OUTPUT_CHANNELS = {"RELAY1": 1, "RELAY2": 2, "RELAY4": 4, "DIMMER4": 4, "AN_OUT4": 4}
DMX_CHANNELS = 12
DMX_MAPPING_BANKS = 16
DMX_BANK_SIZE = 32
CLASSIC_KEY_COUNTS = {"KEY1": 1, "KEY2": 2, "KEY4": 4}
KEY_TIMING_DESCRIPTIONS = tuple(f"{16 * value} ms" for value in range(64))
KEY_RAMP_DESCRIPTIONS = ("Instant", "4 secs", "8 secs", "12 secs", "20 secs", "30 secs",
                         "40 secs", "60 secs", "90 secs", "120 secs", "180 secs",
                         "300 secs", "420 secs", "600 secs", "900 secs", "1020 secs")
KEY_MACRO_DESCRIPTIONS = {
    0: "On", 1: "Off", 2: "On/Off", 3: "Dimmer", 4: "On Up", 5: "Off Down", 6: "Timer",
    7: "Bell Press", 8: "Dimmer Up", 9: "Dimmer Down", 10: "Soft Up", 11: "Soft Down",
    12: "Preset 1", 13: "Preset 2", 14: "Trigger 1", 15: "Trigger 2", 16: "Unused",
    17: "Shutter Toggle", 18: "Shutter Open Toggle", 19: "Shutter Close Toggle",
    20: "Shutter Open", 21: "Shutter Close", 22: "Shutter Stop", 26: "<Custom>",
}
_KEY_PRESET_TYPES = {"on": 0, "off": 1, "toggle": 2, "dimmer": 3, "dimmer_memory": 3,
                     "on_up": 4, "off_down": 5, "timer": 6, "bellpress": 7, "dimmer_up": 8,
                     "dimmer_down": 9, "soft_up": 10, "soft_down": 11, "preset1": 12,
                     "preset2": 13, "trigger1": 14, "trigger2": 15, "unused": 16}
_KEY_MACRO_TYPES = {PRESETS[name].codes: kind for name, kind in _KEY_PRESET_TYPES.items()}
# Global reverse lookup accepts these additional registered Timer groups. They
# are not the first template group used when assigning the editor's preset.
_KEY_MACRO_TYPES.update({(13, 7, 15, 0): 6, (13, 8, 13, 8): 6, (0, 7, 0, 7): 6,
                         (0, 7, 15, 0): 6, (9, 0, 0, 0): 21})
_KEY_TIMER_EXPIRY = frozenset((0, 15, 4, 9, 12, 6, 10))


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


@dataclass(frozen=True)
class ClassicKeyData:
    application: int
    timings: tuple[str, str, str, str]
    groups: list[int]
    masks: list[int]
    commands: list[tuple[int, ...]]
    stored1: list[int]
    stored2: list[int]
    timers: list[int]
    expiry: list[int]


def classic_key_data(unit: Unit) -> ClassicKeyData:
    """Bounded native PP loader projection for KEY1/KEY2/KEY4.

    These classes have four blocks and no IBistable interface. IR, auxiliary,
    bus-coupler and Neo model state is deliberately outside this adapter.
    """
    count = CLASSIC_KEY_COUNTS.get(unit.unit_type.upper())
    if count is None:
        raise ValueError("unrecovered classic key class")
    application = _primary_application(unit)
    debounce = _required_array(unit, "DebounceTime", 1, 63)[0]
    long_press = _required_array(unit, "LongPressTime", 1, 63)[0]
    ramps = _required_array(unit, "RampRate", 2)
    ramp_ordinals = [value if value <= 15 else 1 if value == 255 else 15 for value in ramps]
    groups = _required_array(unit, "GroupAddress", 4)
    masks = _required_array(unit, "BlockAllocation", count)
    stages = [_required_array(unit, stage, count, 15) for stage in STAGES]
    stored1 = _required_array(unit, "LightLevelStore1", 4)
    stored2 = _required_array(unit, "LightLevelStore2", 4)
    high = _required_array(unit, "TimerHighByte", 4)
    low = _required_array(unit, "TimerLowByte", 4)
    expiry = _required_array(unit, "TimerExpiryCommand", 4, 15)
    return ClassicKeyData(application, (KEY_TIMING_DESCRIPTIONS[debounce], KEY_TIMING_DESCRIPTIONS[long_press],
                                        *(KEY_RAMP_DESCRIPTIONS[value] for value in ramp_ordinals)),
                          groups, masks, list(zip(*stages)), stored1, stored2,
                          [(h << 8) | l for h, l in zip(high, low)],
                          [value if value in _KEY_TIMER_EXPIRY else 15 for value in expiry])


def classic_key_macro(commands: tuple[int, ...], application: int,
                      primary_stored1: int | None, primary_stored2: int | None) -> tuple[int, str]:
    """Match native global groups, shutter aliases, then the KEY app subset."""
    kind = _KEY_MACRO_TYPES.get(tuple(commands), 26)
    if application != 202:
        if kind == 14 and primary_stored1 is not None:
            kind = {249: 17, 252: 18, 255: 20}.get(primary_stored1, kind)
        elif kind == 15 and primary_stored2 is not None:
            kind = {2: 19, 5: 22}.get(primary_stored2, kind)
    if (application == 255 and kind != 16) or (application != 202 and kind in (14, 15)):
        kind = 26
    return kind, KEY_MACRO_DESCRIPTIONS[kind]


def _classic_preset_cell(network: Network, application: int, group_address: int, value: int) -> str:
    # The original searches Level.Address, never Level.Value, and its common
    # level formatter preserves the name literally (including level 255).
    group = network.application(application).group(group_address)
    level = next((level for level in group.levels if level.address == value), None)
    percentage = (value + 2) * 100 // 255
    if level is None:
        return f"<td>{percentage}%</td>"
    link = f'<a href="#{network.address}_{application}_{group_address}_{level.address}">{level.name}</a>'
    return f"<td>{link} ({percentage}%)</td>"


def _classic_key_controls(network: Network, data: ClassicKeyData, commands: tuple[int, ...],
                          blocks: list[int], kind: int) -> str:
    groups = [data.groups[block] for block in blocks if data.groups[block] != 255]
    if kind == 16 or not groups:
        return "&nbsp;"
    result = '<table border="1"><tr><th>Group</th>'
    if 12 in commands:
        result += "<th>Preset 1</th>"
    if 6 in commands:
        result += "<th>Preset 2</th>"
    if 7 in commands:
        result += "<th>Timer</th><th>Expiry</th>"
    result += "</tr>"
    for group in groups:
        # ItemByGroup searches all unit blocks and returns the first match;
        # that block need not belong to this key. Duplicate rows are retained.
        block = data.groups.index(group)
        result += f"<tr><td>{_group_link(network, data.application, group)}</td>"
        if 12 in commands:
            result += _classic_preset_cell(network, data.application, group, data.stored1[block])
        if 6 in commands:
            result += _classic_preset_cell(network, data.application, group, data.stored2[block])
        if 7 in commands:
            hours, remaining = divmod(data.timers[block], 3600)
            minutes, seconds = divmod(remaining, 60)
            result += f"<td>{hours}h{minutes}m{seconds}s</td><td>{MICRO_FUNCTION_LABELS[data.expiry[block]]}</td>"
        result += "</tr>"
    return result + "</table>"


def document_classic_key(out: _Writer, network: Network, unit: Unit) -> str:
    """TClassicKeyInputDocumentor body for the source-pinned KEY1/2/4 model."""
    from .project_documentation import document_base, format_html_string
    document_base(out, network, unit)
    try:
        data = classic_key_data(unit)
        rows = []
        for key, commands in enumerate(data.commands):
            blocks = [block for block in range(4) if data.masks[key] & (1 << block)]
            primary = blocks[0] if blocks else None
            kind, label = classic_key_macro(commands, data.application,
                                            data.stored1[primary] if primary is not None else None,
                                            data.stored2[primary] if primary is not None else None)
            if kind == 26:
                micro = ('<table border="1"><tr><th>SP</th><th>SR</th><th>LP</th><th>LR</th></tr><tr>'
                         + "".join(f"<td>{MICRO_FUNCTION_LABELS[command]}</td>" for command in commands)
                         + "</tr></table>")
            else:
                micro = "&nbsp;"
            controls = _classic_key_controls(network, data, commands, blocks, kind)
            rows.append(f"<tr><td>{key + 1}</td><td>{format_html_string(label)}</td><td>{micro}</td><td>{controls}</td></tr>")
    except ValueError as exc:
        out.mark(network, unit, f"Classic key controls: {exc}")
        return "partial"
    out.add('<table border="1">')
    for label, value in zip(("Debounce", "Long Press", "Ramp 1", "Ramp 2"), data.timings):
        out.add(f"<tr><th>{label}</th><td>{value}</td></tr>")
    out.add("</table>")
    out.add("<br/>")
    out.add('<table border="1">')
    out.add("<tr><th>Key</th><th>Macro Function</th><th>Micro Functions</th><th>Controls</th></tr>")
    for row in rows:
        out.add(row)
    out.add("</table>")
    return "recovered"


DOCUMENTORS = {"ClassicOutput": document_classic_output, "DMXGateway": document_dmx_gateway,
               "ClassicKeyInput": document_classic_key}
