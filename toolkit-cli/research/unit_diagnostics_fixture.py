"""Synthetic PCI fixture for the Toolkit Diagnostics dialog (P8.05).

Units 4 (KEYE1) and 5 (KEYGL5) reuse the synthetic discovery identities;
16 (attached PC_CNIED) and 17 (remote PC_CNICD) reuse the explicit PCI.xml
clock fixture. Each unit's IDENTIFY4 byte 9 is set to a chosen raw network
voltage count, decoded by native C-Gate as ``raw * 0.15904 + 0.55`` volts.
Unit 17 has its burden enabled (EEPROM 3E bit 6); unit 16 is the only
enabled clock. These are explicit test values, not device observations or
an electrical model.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from cbus_toolkit.simulator import PCISimulator, synthetic_units, with_net_voltage

_spec = importlib.util.spec_from_file_location('clock_fixture', Path(__file__).with_name('clock_fixture.py'))
clock_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clock_fixture)

# Raw IDENTIFY4 byte 9 values and the text native C-Gate derives from them.
NET_VOLTAGE_RAW = {4: 0xC0, 5: 0xC3, 16: 0xC5, 17: 0xBE}
NET_VOLTAGE_TEXT = {4: '31.0', 5: '31.5', 16: '31.8', 17: '30.7'}
DATABASE_UNITS = ((4, 'KEYE1', '2.5.00'), (5, 'KEYGL5', '5.5.00'), (16, 'PC_CNIED', '5.5.00'),
                  (17, 'PC_CNICD', '5.5.00'), (99, 'KEYE1', '2.5.00'))


def diagnostics_simulator(*, units=(4, 5, 16, 17), **options):
    base = clock_fixture.clock_simulator()
    chosen = [unit for unit in synthetic_units() if unit.address in units and unit.address in (4, 5)]
    chosen += [base.units[address] for address in (16, 17) if address in units]
    for unit in chosen:
        unit.attributes[4] = with_net_voltage(unit.attributes[4], NET_VOLTAGE_RAW[unit.address])
    memory = {address: dict(cells) for address, cells in base.legacy_memory.items() if address in units}
    pci = [address for address in (16, 17) if address in units]
    if 17 in memory:
        memory[17][0x3E] = 0x40
    return PCISimulator(chosen, profile='synthetic', legacy_memory=memory,
                        legacy_writable={address: {0x3E} for address in pci},
                        pci_settings_units=pci, clock_generator=16,
                        # See clock_fixture: avoids a native confirmation race.
                        response_delay=0.01, **options)
