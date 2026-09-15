"""Explicit PCI.xml fixture for native network clock and burden acceptance."""
import json
from pathlib import Path
from cbus_toolkit.memory import encode_sixbit
from cbus_toolkit.simulator import PCISimulator, UnitState, default_units


def clock_simulator(*, state_path=None, wire_log_path=None):
    fixture = json.loads((Path(__file__).parent / 'fixtures/pci-clock-synthetic.json').read_text())
    memory = {int(k): v for k, v in fixture['legacy_memory'].items()}
    units, memories = [], {}
    for address in (16, 17):
        original = default_units()[-1]
        attrs = dict(original.attributes)
        # Catalogue PCI.xml maps remote DIN CNI PC_CNICD to CBus2PCI;
        # PC_CNIED is the attached interface and maps to CBus2PCILocal.
        if address == 17:
            attrs[1] = b'PC_CNICD'
        # Explicit synthetic serial number, keeping the captured capability prefix.
        attrs[4] = attrs[4][:6] + bytes([0, 0, 0, address, 0, 5])
        units.append(UnitState(address, attrs, dict(original.parameters)))
        cells = dict(memory)
        cells[0x20] = address
        cells[0x3e] = 1 if address == 16 else 0
        # Native lP fetches 12 bytes from3E for the one-bit field. These
        # unmapped trailing bytes are explicitly chosen A5 fixture padding,
        # not schema fields, defaults or inferred hardware bytes.
        cells.update({int(i): value for i, value in fixture['read_ahead_padding'].items()})
        cells.update(enumerate(encode_sixbit('SIMPCI'+str(address)), 0x2a))
        memories[address] = cells
    return PCISimulator(units, profile='synthetic', physical_memory={},
                        legacy_memory=memories, legacy_writable={16: {0x3e}, 17: {0x3e}},
                        pci_settings_units=[16, 17], clock_generator=16,
                        # Native cl.a sends before setting its awaited tag and
                        # txEnabled=false. A zero-latency confirmation can be
                        # consumed first and lost. This explicit transport
                        # delay avoids that vendor race; it is not a retry or
                        # an assertion about physical PCI response timings.
                        response_delay=0.01,
                        state_path=state_path, wire_log_path=wire_log_path)
