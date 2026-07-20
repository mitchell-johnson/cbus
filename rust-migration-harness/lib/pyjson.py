"""Canonical JSON representation of C-Bus packets (Python side).

This module defines THE schema used by the golden vector files. The Rust
implementation must produce/consume exactly this JSON structure (see
rust-migration-harness/README.md for the field-by-field contract).

Only used at vector *generation* and *self-check* time -- it imports the
existing Python `cbus` package. The Rust-facing harness never needs it.
"""
from typing import Optional, Union

from cbus.common import GroupState, PriorityClass
from cbus.protocol.base_packet import BasePacket, InvalidPacket
from cbus.protocol.confirm_packet import ConfirmationPacket
from cbus.protocol.dm_packet import DeviceManagementPacket
from cbus.protocol.error_packet import PCIErrorPacket
from cbus.protocol.pm_packet import PointToMultipointPacket
from cbus.protocol.po_packet import PowerOnPacket
from cbus.protocol.pp_packet import PointToPointPacket
from cbus.protocol.reset_packet import ResetPacket
from cbus.protocol.scs_packet import SmartConnectShortcutPacket
from cbus.protocol.cal.extended import ExtendedCAL
from cbus.protocol.cal.identify import IdentifyCAL
from cbus.protocol.cal.recall import RecallCAL
from cbus.protocol.cal.reply import ReplyCAL
from cbus.protocol.cal.report import BinaryStatusReport, LevelStatusReport
from cbus.protocol.application.clock import (
    ClockRequestSAL, ClockUpdateSAL)
from cbus.protocol.application.enable import EnableSetNetworkVariableSAL
from cbus.protocol.application.lighting import (
    LightingOffSAL, LightingOnSAL, LightingRampSAL, LightingTerminateRampSAL)
from cbus.protocol.application.status_request import StatusRequestSAL
from cbus.protocol.application.temperature import TemperatureBroadcastSAL
from datetime import date, time


# ---------------------------------------------------------------------------
# SALs
# ---------------------------------------------------------------------------

def sal_to_json(s) -> dict:
    if isinstance(s, LightingRampSAL):
        return {'sal': 'lighting_ramp', 'application': int(s.application),
                'group_address': s.group_address,
                'duration': s.duration, 'level': s.level}
    if isinstance(s, LightingOnSAL):
        return {'sal': 'lighting_on', 'application': int(s.application),
                'group_address': s.group_address}
    if isinstance(s, LightingOffSAL):
        return {'sal': 'lighting_off', 'application': int(s.application),
                'group_address': s.group_address}
    if isinstance(s, LightingTerminateRampSAL):
        return {'sal': 'lighting_terminate_ramp',
                'application': int(s.application),
                'group_address': s.group_address}
    if isinstance(s, ClockRequestSAL):
        return {'sal': 'clock_request'}
    if isinstance(s, ClockUpdateSAL):
        if s.is_date:
            return {'sal': 'clock_update_date', 'year': s.val.year,
                    'month': s.val.month, 'day': s.val.day}
        return {'sal': 'clock_update_time', 'hour': s.val.hour,
                'minute': s.val.minute, 'second': s.val.second}
    if isinstance(s, TemperatureBroadcastSAL):
        return {'sal': 'temperature_broadcast',
                'group_address': s.group_address,
                'temperature': s.temperature}
    if isinstance(s, EnableSetNetworkVariableSAL):
        return {'sal': 'enable_set_network_variable',
                'variable': s.variable, 'value': s.value}
    if isinstance(s, StatusRequestSAL):
        return {'sal': 'status_request',
                'level_request': bool(s.level_request),
                'group_address': s.group_address,
                'child_application': int(s.child_application)}
    raise TypeError(f'unhandled SAL: {s!r}')


def sal_from_json(d: dict):
    k = d['sal']
    if k == 'lighting_on':
        return LightingOnSAL(d['group_address'], d['application'])
    if k == 'lighting_off':
        return LightingOffSAL(d['group_address'], d['application'])
    if k == 'lighting_terminate_ramp':
        return LightingTerminateRampSAL(d['group_address'], d['application'])
    if k == 'lighting_ramp':
        return LightingRampSAL(d['group_address'], d['application'],
                               d['duration'], d['level'])
    if k == 'clock_request':
        return ClockRequestSAL()
    if k == 'clock_update_date':
        return ClockUpdateSAL(date(d['year'], d['month'], d['day']))
    if k == 'clock_update_time':
        return ClockUpdateSAL(time(d['hour'], d['minute'], d['second']))
    if k == 'temperature_broadcast':
        return TemperatureBroadcastSAL(d['group_address'], d['temperature'])
    if k == 'enable_set_network_variable':
        return EnableSetNetworkVariableSAL(d['variable'], d['value'])
    if k == 'status_request':
        return StatusRequestSAL(d['level_request'], d['group_address'],
                                d['child_application'])
    raise ValueError(f'unhandled SAL json: {d!r}')


# ---------------------------------------------------------------------------
# CALs and status reports
# ---------------------------------------------------------------------------

def report_to_json(r) -> dict:
    if isinstance(r, BinaryStatusReport):
        return {'report': 'binary', 'group_states': [int(g) for g in r]}
    if isinstance(r, LevelStatusReport):
        return {'report': 'level', 'levels': list(r)}
    raise TypeError(f'unhandled report: {r!r}')


def report_from_json(d: dict):
    if d['report'] == 'binary':
        return BinaryStatusReport([GroupState(g) for g in d['group_states']])
    if d['report'] == 'level':
        return LevelStatusReport(d['levels'])
    raise ValueError(f'unhandled report json: {d!r}')


def cal_to_json(c) -> dict:
    if isinstance(c, IdentifyCAL):
        return {'cal': 'identify', 'attribute': int(c.attribute)}
    if isinstance(c, RecallCAL):
        return {'cal': 'recall', 'param': int(c.param), 'count': int(c.count)}
    if isinstance(c, ReplyCAL):
        return {'cal': 'reply', 'parameter': int(c.parameter),
                'data_hex': c.data.hex()}
    if isinstance(c, ExtendedCAL):
        # NB: the Python dataclass field is (typo) `externally_initated`;
        # the JSON name is spelled correctly.
        return {'cal': 'extended_status',
                'externally_initiated': bool(c.externally_initated),
                'child_application': int(c.child_application),
                'block_start': int(c.block_start),
                'report': report_to_json(c.report)}
    raise TypeError(f'unhandled CAL: {c!r}')


def cal_from_json(d: dict):
    k = d['cal']
    if k == 'identify':
        return IdentifyCAL(d['attribute'])
    if k == 'recall':
        return RecallCAL(d['param'], d['count'])
    if k == 'reply':
        return ReplyCAL(d['parameter'], bytes.fromhex(d['data_hex']))
    if k == 'extended_status':
        return ExtendedCAL(d['externally_initiated'], d['child_application'],
                           d['block_start'], report_from_json(d['report']))
    raise ValueError(f'unhandled CAL json: {d!r}')


# ---------------------------------------------------------------------------
# Packets
# ---------------------------------------------------------------------------

def _conf_to_json(confirmation) -> Optional[str]:
    if confirmation is None:
        return None
    if isinstance(confirmation, bytes):
        return confirmation.decode('ascii')
    return str(confirmation)


def packet_to_json(p) -> Optional[dict]:
    """Canonical JSON for anything decode_packet() may return."""
    if p is None:
        return None
    if isinstance(p, InvalidPacket):
        return {'type': 'invalid'}
    if isinstance(p, PowerOnPacket):
        return {'type': 'power_on'}
    if isinstance(p, PCIErrorPacket):
        return {'type': 'pci_error'}
    if isinstance(p, ConfirmationPacket):
        return {'type': 'confirmation', 'code': p.code.decode('ascii'),
                'success': p.success}
    if isinstance(p, ResetPacket):
        return {'type': 'reset'}
    if isinstance(p, SmartConnectShortcutPacket):
        return {'type': 'smart_connect'}
    if isinstance(p, DeviceManagementPacket):
        return {'type': 'device_management',
                'checksum': p.checksum,
                'priority_class': int(p.priority_class),
                'source_address': p.source_address,
                'confirmation': _conf_to_json(p.confirmation),
                'parameter': p.parameter, 'value': p.value}
    if isinstance(p, PointToMultipointPacket):
        return {'type': 'point_to_multipoint',
                'checksum': p.checksum,
                'priority_class': int(p.priority_class),
                'source_address': p.source_address,
                'confirmation': _conf_to_json(p.confirmation),
                'application': (None if p.application is None
                                else int(p.application)),
                'sals': [sal_to_json(s) for s in p]}
    if isinstance(p, PointToPointPacket):
        return {'type': 'point_to_point',
                'checksum': p.checksum,
                'priority_class': int(p.priority_class),
                'source_address': p.source_address,
                'confirmation': _conf_to_json(p.confirmation),
                'unit_address': p.unit_address,
                'bridged': p.pm_bridged,
                'hops': list(p.hops),
                'cals': [cal_to_json(c) for c in p]}
    # decode_packet can return a bare CAL (Serial Interface Guide s4.2.7
    # "device management CAL" path, client->PCI without '\\' prefix).
    if isinstance(p, (IdentifyCAL, RecallCAL, ReplyCAL, ExtendedCAL)):
        return {'type': 'cal', **cal_to_json(p)}
    raise TypeError(f'unhandled packet: {p!r}')


def packet_from_json(d: dict):
    """Constructs a Python packet object from canonical JSON.

    Used to verify `encode` vectors. Only encodable packet types are
    supported (no invalid/bridged variants).
    """
    t = d['type']
    if t == 'reset':
        return ResetPacket()
    if t == 'smart_connect':
        return SmartConnectShortcutPacket()
    if t == 'power_on':
        return PowerOnPacket()
    if t == 'pci_error':
        return PCIErrorPacket()
    if t == 'confirmation':
        return ConfirmationPacket(d['code'].encode('ascii'), d['success'])
    if t == 'device_management':
        p = DeviceManagementPacket(
            checksum=d['checksum'],
            priority_class=PriorityClass(d['priority_class']),
            parameter=d['parameter'], value=d['value'])
    elif t == 'point_to_multipoint':
        p = PointToMultipointPacket(
            checksum=d['checksum'],
            priority_class=PriorityClass(d['priority_class']),
            sals=[sal_from_json(s) for s in d['sals']])
    elif t == 'point_to_point':
        p = PointToPointPacket(
            checksum=d['checksum'],
            priority_class=PriorityClass(d['priority_class']),
            unit_address=d['unit_address'],
            cals=[cal_from_json(c) for c in d['cals']])
    elif t == 'cal':
        return cal_from_json(d)
    elif t == 'sal':
        return sal_from_json(d)
    elif t == 'binary_report':
        return report_from_json({'report': 'binary',
                                 'group_states': d['group_states']})
    elif t == 'level_report':
        return report_from_json({'report': 'level', 'levels': d['levels']})
    else:
        raise ValueError(f'unhandled packet json: {d!r}')

    p.source_address = d.get('source_address')
    conf = d.get('confirmation')
    p.confirmation = conf.encode('ascii') if conf else None
    return p
