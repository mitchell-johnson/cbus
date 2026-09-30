"""C-Gate 3.4 wireless learn and unit-action boundary, recovered from source.

Radio learn/join and the explicit wireless DO actions are live-network operations:
C-Gate composes a C-Bus command, sends it through the network's interface
and, for the read actions, waits for the unit's reply. This module reproduces
the command strings C-Gate composes (``aW.e``), so the boundary can be
inspected and compared without a network. Status GETs read cached strings;
the IDENTIFY commands belong to the separate Psync refresh path. It never opens an endpoint.

Recovered from ``cgate.jar`` 3.4.0.2001 (research/fixtures/wireless-cgate-boundary.json):

* ``NET LEARN <net> <app> <grade> <group>`` (class ``kI`` -> ``bC``);
* ``DO <unit> MAISync`` IDENTIFY attribute 0xFE, eight bytes cached;
* ``DO <unit> ResetOpStats`` CAL 0x08 with no reply;
* ``DO <unit> RecallOpStats`` four 12-byte NG memory reads from address 0;
* the ``UnitTemperature``/``UnitSupplyVoltage``/``BackgroundSignalPower``/
  ``LastPacketReceivedPower`` cached properties; Psync internally refreshes
  them with IDENTIFY attributes 0x50..0x53.

Offline wireless editing lives in :mod:`cbus_toolkit.wireless_gateway` and
:mod:`cbus_toolkit.wireless_unit_globals`. See docs/wireless.md.
"""
from types import MappingProxyType

# kI help text; runCommand rejects every other grade as a syntax error.
LEARN_GRADES = MappingProxyType({1: 'init relay', 2: 'init dim', 0x80: 'cancel', 0x81: 'exit relay',
                                 0x82: 'exit dim', 0x83: 'exit area'})
# CBusWirelessUnit.n()->u(): Psync refreshes these cached properties via bB.
# Their GET accessors have no read callback and issue no bus command.
STATUS_ATTRIBUTES = MappingProxyType({'UnitTemperature': 0x50, 'UnitSupplyVoltage': 0x51,
                                      'BackgroundSignalPower': 0x52, 'LastPacketReceivedPower': 0x53})
# CBusWirelessUnit.au: OpStats counter order, each little-endian 32-bit.
OP_STATS_COUNTERS = ('PacketsReceived', 'PacketsReceivedWithError', 'PacketsNAKd', 'PacketsNCAd',
                     'CollisionsDetected', 'TransmitAttempts', 'TransmitCancellations', 'CollisionsDetectedinTAP',
                     'CollisionsNotifiedDetected', 'TransmissionsDropped', 'SuccessfulTransmissions',
                     'TransmissionsNAKd')
LIVE_NETWORK_REASON = ('C-Gate sends the command through the network interface and needs the physical '
                       'unit (and, for learn, the wireless units in learn range) to act or reply')


def _hex(value):
    """aW.c(int): two uppercase hex digits; values above 0xFF render as FF."""
    text = format(value, 'x')
    return ('0' + text if len(text) < 2 else 'ff' if len(text) > 2 else text).upper()


def _byte(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError(f'{label} must be an integer in 0..255')
    return value


def net_learn_command(application, grade, group):
    """The bC command body for ``NET LEARN``: ``\\05 <app> 00 03 <grade> <group> <check>``."""
    application, grade, group = (_byte(application, 'Application'), _byte(grade, 'Grade'),
                                 _byte(group, 'Group'))
    if grade not in LEARN_GRADES:
        raise ValueError('Learn grade must be one of ' + ', '.join(f'0x{g:02X}' for g in LEARN_GRADES))
    check = (((grade + group) & 0xFF) ^ 0xFF) + 1 & 0xFF
    return {'cgate': f'NET LEARN <network> {application} {grade} {group}', 'grade': LEARN_GRADES[grade],
            'command': '\\05' + _hex(application) + '00' + '03' + _hex(grade) + _hex(group) + _hex(check),
            'reply_expected': False, 'requires_live_network': True}


def unit_action_commands(unit):
    """Command bodies for the CBusWirelessUnit actions and status reads of one unit."""
    unit = _byte(unit, 'Unit address')
    identify = lambda attribute: '\\46' + _hex(unit) + '0021' + _hex(attribute)  # noqa: E731 - bB.a(int, int)
    return {
        'MAISync': {'cgate': 'DO <unit> MAISync', 'commands': [identify(0xFE)], 'reply_expected': True,
                    'reply_bytes': 8, 'requires_live_network': True},
        'ResetOpStats': {'cgate': 'DO <unit> ResetOpStats', 'commands': ['\\46' + _hex(unit) + '0008'],
                         'reply_expected': False, 'requires_live_network': True},
        # CBusNGUnit.a(aX, 0, 48, false): bp reads of at most 12 bytes.
        'RecallOpStats': {'cgate': 'DO <unit> RecallOpStats',
                          'commands': ['\\46' + _hex(unit) + '002A' + _hex(start) + _hex(12)
                                       for start in range(0, 48, 12)],
                          'reply_expected': True, 'reply_bytes': 48, 'counters': list(OP_STATS_COUNTERS),
                          'requires_live_network': True},
        'status': {name: {'cgate': 'GET <unit> ' + name, 'commands': [], 'reply_expected': True,
                          'requires_live_network': False, 'cached_only': True,
                          'refresh_commands': [identify(attribute)], 'refresh_requires_live_network': True}
                   for name, attribute in STATUS_ATTRIBUTES.items()},
    }


def decode_op_stats(data):
    """RecallOpStats: 48 reply bytes to the twelve little-endian 32-bit OpStats counters."""
    data = bytes(data)
    if len(data) != 48:
        raise ValueError('Op stats recall failed')
    return {name: int.from_bytes(data[4 * i:4 * i + 4], 'little') for i, name in enumerate(OP_STATS_COUNTERS)}
