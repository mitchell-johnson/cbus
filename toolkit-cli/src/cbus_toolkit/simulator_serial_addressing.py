"""Explicit serial broadcast fixture; unknown response-tail semantics stay data."""
from . import simulator_addressing
from .serials import parse_native_serial


def _serial(unit):
    attribute = unit.attributes.get(4, b"")
    if len(attribute) < 9: raise ValueError("Serial fixture needs captured IDENTIFY4 data")
    packed = int.from_bytes(attribute[5:9], "big")
    number = parse_native_serial(str(packed >> 12) + "." + str(packed & 4095))
    if not number.known: raise ValueError("Serial fixture requires a known serial")
    return number.canonical


def configure_empty(simulator, addresses):
    if not isinstance(addresses, (list, tuple, set, frozenset)):
        raise ValueError("Explicit empty readdress addresses must be a sequence")
    result = set()
    for address in addresses:
        if (simulator.profile != "synthetic" or type(address) is not int or not 1 <= address <= 255
                or address in result or address == simulator.local_unit
                or any(address in getattr(simulator, name) for name in simulator_addressing._MAPS)):
            raise ValueError("Empty readdress address must be a unique unoccupied synthetic slot")
        result.add(address)
    return result


def configure_tails(simulator, tails):
    if not isinstance(tails, dict): raise ValueError("Serial reply tails must be an explicit mapping")
    result = {}
    for serial, tail in tails.items():
        number = parse_native_serial(serial)
        if not number.known or serial != number.canonical or not isinstance(tail, bytes) or len(tail) != 2:
            raise ValueError("Provide a canonical known serial and exactly two opaque response bytes")
        units = [unit for unit in simulator.units.values() if len(unit.attributes.get(4, b"")) >= 9
                 and _serial(unit) == serial]
        if len(units) != 1: raise ValueError("Serial broadcast fixture requires exactly one matching unit")
        simulator_addressing.configure(simulator, {units[0].address: 0})
        result[serial] = tail
    return result


def handle(simulator, payload):
    if (len(payload) != 11 or payload[:5] != b"\x05\xff\x00\x0f\x00"
            or sum(payload[4:]) & 255):
        raise ValueError("Invalid serial readdress broadcast or inner checksum")
    if not simulator.serial_readdress_reply_tails:
        raise ValueError("Serial readdress broadcasts are not enabled in this fixture")
    packed = int.from_bytes(payload[5:9], "big")
    serial = str(packed >> 12) + "." + str(packed & 4095)
    if serial not in simulator.serial_readdress_reply_tails: return b""
    matches = [unit for unit in simulator.units.values() if len(unit.attributes.get(4, b"")) >= 9
               and _serial(unit) == serial]
    if len(matches) != 1: raise ValueError("Serial broadcast identity is missing or ambiguous")
    old, new = matches[0].address, payload[9]
    if not 2 <= new <= 254 or new not in simulator.readdress_empty_addresses:
        raise ValueError("Serial fixture requires an explicitly empty destination in 2..254")
    try: simulator_addressing._move(simulator, old, new)
    except OSError as error: raise ValueError("Serial readdress persistence failed") from error
    # co.java correlates the source plus 87/00/packed serial. Its two remaining
    # CAL bytes are opaque caller-supplied fixture data, not inferred fields.
    return bytes([0x86, new, simulator.local_unit, 0, 0x87, 0]) + payload[5:9] + simulator.serial_readdress_reply_tails[serial]
