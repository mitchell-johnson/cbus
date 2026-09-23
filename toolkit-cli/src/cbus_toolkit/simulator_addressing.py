"""Explicit KEYE1 fixture unlock and protected-address STORE behavior.

Request/response layouts follow exact C-Gate dd/cu/ct classes. Challenge values
and their one-use lifetime are deliberate fixture state, not hardware secrets.
"""
from copy import deepcopy


_MAPS = ("units", "physical_memory", "legacy_memory", "legacy_writable", "status_blocks",
         "_physical_pointers", "_programming_registers", "readdress_challenges")


def configure(simulator, challenges):
    result = {}
    if not isinstance(challenges, dict): raise ValueError("Readdress challenges must be an address-to-byte mapping")
    for address, challenge in challenges.items():
        if type(address) is not int or not 1 <= address <= 255 or address == simulator.local_unit:
            raise ValueError("Readdress fixture requires a nonlocal address in 1..255")
        if type(challenge) is not int or not 0 <= challenge <= 255:
            raise ValueError("Explicit fixture challenge must fit one byte")
        unit = simulator.units.get(address)
        if (simulator.profile != "synthetic" or unit is None or unit.attributes.get(1, b"").rstrip() != b"KEYE1"
                or unit.attributes.get(2, b"").rstrip() != b"2.5.00"):
            raise ValueError("Readdress fixture supports only synthetic KEYE1 firmware 2.5.00")
        memory = simulator.legacy_memory.get(address)
        actual = memory.get(0x20) if memory is not None else (unit.parameters.get(0x20) or b"")[0:1]
        if actual != (address if memory is not None else bytes([address])):
            raise ValueError("Readdress fixture needs an explicit matching UnitAddress byte at 0x20")
        if 0x20 in simulator.legacy_writable.get(address, ()) or 0x20 in unit.write_tags:
            raise ValueError("UnitAddress must remain protected from generic STORE")
        result[address] = challenge
    return result


def _move(simulator, old, new):
    previous = {name: deepcopy(getattr(simulator, name)) for name in _MAPS}
    previous_settings = simulator.pci_settings_units.copy()
    previous_clock = simulator.clock_generator
    previous_empty = simulator.readdress_empty_addresses.copy()
    try:
        for name in _MAPS:
            values = getattr(simulator, name)
            if old in values: values[new] = values.pop(old)
        unit = simulator.units[new]
        unit.address = new
        if new in simulator.legacy_memory: simulator.legacy_memory[new][0x20] = new
        if 0x20 in unit.parameters:
            unit.parameters[0x20] = bytes([new]) + unit.parameters[0x20][1:]
        if old in simulator.pci_settings_units:
            simulator.pci_settings_units.remove(old); simulator.pci_settings_units.add(new)
        if simulator.clock_generator == old: simulator.clock_generator = new
        if new in simulator.readdress_empty_addresses:
            simulator.readdress_empty_addresses.remove(new)
            simulator.readdress_empty_addresses.add(old)
        simulator._persist()
    except Exception:
        for name, value in previous.items(): setattr(simulator, name, value)
        simulator.pci_settings_units = previous_settings
        simulator.clock_generator = previous_clock
        simulator.readdress_empty_addresses = previous_empty
        raise


def handle(simulator, address, payload):
    """Return (response source, CAL payload), or None for unrelated commands."""
    unlock = payload[:1] == b"\x11"
    store = payload[:3] == b"\xa3\x20\x4e"
    if not unlock and not store: return None
    if unlock and payload == b"\x11\x20" and address in simulator.readdress_empty_addresses:
        return address, b""  # PCI link confirmation; explicitly empty bus slot.
    if address not in simulator.readdress_challenges:
        raise ValueError("Physical address programming is not enabled for this fixture unit")
    if unlock:
        if payload != b"\x11\x20": raise ValueError("Unsupported unlock request")
        token = simulator.readdress_challenges[address]
        simulator._pending_readdress[address] = token
        return address, bytes([0x82, 0x20, token])
    if len(payload) != 5: raise ValueError("Protected address STORE needs a destination and unlock byte")
    new, token = payload[3:]
    expected = simulator._pending_readdress.pop(address, None)
    occupied = any(new in getattr(simulator, name) for name in _MAPS)
    if expected is None or token != expected or not 1 <= new <= 254 or occupied or new == simulator.local_unit:
        return address, b"\x3b\x20\x4e"
    try: _move(simulator, address, new)
    except OSError as error: raise ValueError("Physical address persistence failed") from error
    return new, b"\x32\x20\x4e"
