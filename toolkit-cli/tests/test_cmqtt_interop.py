"""Production CLI -> real Rust daemon -> independently implemented Python PCI.

Only ephemeral loopback sockets and synthetic configuration bytes are used.
"""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

import pytest
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.simulator import PCISimulator
from test_cmqtt import memory


ROOT = Path(__file__).resolve().parents[2]


def find_cmqttd():
    override = os.environ.get('CBUS_CMQTTD_BIN')
    candidate = Path(override) if override else ROOT / 'rust/target/debug/cmqttd'
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate.resolve()
    return None


BIN = find_cmqttd()


class InitializedPCI(PCISimulator):
    def _command(self, line, context):
        # Literal initialization profile from the existing Rust hardware tests.
        if line in (b'~', b'A32100FF', b'A32200FF', b'A342000E', b'A3300079'):
            return b'', None
        return super()._command(line, context)


@pytest.mark.skipif(BIN is None, reason='Build the Rust cmqttd binary to run cross-language hardware-service tests')
def test_real_cli_reads_all_edlt_labels_through_cmqttd(tmp_path):
    image = memory()
    sim = InitializedPCI(profile='captured', command_checksum=True,
                         physical_memory={5: dict(enumerate(image))})
    project = tmp_path / 'project.xml'
    project.write_text('<Installation><Project><TagName>TEST</TagName><Network><Address>254</Address>'
                       '<TagName>Fixture</TagName><Application><Address>56</Address>'
                       '<TagName>Lighting</TagName><Group><Address>27</Address>'
                       '<TagName>Sample Group</TagName><TagsDLT><TagDLT><LanguageID>1</LanguageID>'
                       '<FlavourID>1</FlavourID><TagType>TEXT</TagType>'
                       '<TagValue>Synthetic Label</TagValue></TagDLT></TagsDLT></Group>'
                       '</Application><Unit><Address>5</Address><TagName>Fixture eDLT</TagName>'
                       '<UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion>'
                       '</Unit></Network></Project></Installation>')
    # Hold a local broker socket without accepting/publishing anything.
    with socket.socket() as broker, sim.running() as pci:
        broker.bind(('127.0.0.1', 0)); broker.listen(1)
        with (tmp_path / 'daemon.log').open('w+') as log:
            process = subprocess.Popen([str(BIN), '--tcp', f'{pci[0]}:{pci[1]}',
                '--broker-address', '127.0.0.1', '--broker-port', str(broker.getsockname()[1]),
                '--broker-disable-tls', '--timesync', '0', '--status-resync', '0',
                '--project-file', str(project), '--cgate-bind', '127.0.0.1:0',
                '--cgate-state', str(tmp_path / 'state.json')], stdout=subprocess.DEVNULL, stderr=log)
            try:
                deadline = time.monotonic() + 10
                port = None
                while time.monotonic() < deadline:
                    log.seek(0); output = log.read()
                    match = re.search(r'C-Gate service listening on 127\.0\.0\.1:(\d+)', output)
                    if match:
                        port = match[1]; break
                    assert process.poll() is None, output
                    time.sleep(.02)
                assert port is not None, output
                with CGateClient('127.0.0.1', int(port), timeout=30) as client:
                    xml_response = client.command('DBGETXML //TEST/254')
                    assert xml_response.status == 344
                result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'cgate',
                    '--host', '127.0.0.1', '--port', port, '--timeout', '30',
                    'edlt-labels', '//TEST/254/p/5'], capture_output=True, text=True, timeout=120)
                assert result.returncode == 0, result.stderr
                value = json.loads(result.stdout)
                assert value['source'] == 'physical-via-cmqttd'
                assert [w['label'] for w in value['widgets']] == ['Kitchen', 'Goodnight']
                assert len(value['static_strings']) == 64
                assert value['static_text_crc_verified']
                assert value['project_group_labels_complete']
                assert value['project_group_labels']['cmqttd_import_capability_verified'] is True
                assert value['project_group_labels']['labels'][0]['tag_value'] == 'Synthetic Label'
                assert value['project_group_labels']['device_readback'] is False
                assert sim.physical_memory[5] == dict(enumerate(image))
                connections = {row['connection'] for row in sim.wire_log}
                assert len(connections) == 1
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


@pytest.mark.skipif(BIN is None, reason='Build the Rust cmqttd binary to run cross-language hardware-service tests')
def test_real_cli_programs_direct_physical_parameter_and_freshly_reloads_it(tmp_path):
    """Exercise the production typed workflow over the real shared PCI path.

    This synthetic direct-method case establishes Python/Rust framing, PP
    session behavior, one SAVE_TO_SOURCE, device write/readback and the fresh
    second PP LOAD.  The companion routed Python/daemon interop test covers
    the ten declared methods through one scripted bridge. Neither test is
    live-device or power-cycle acceptance.
    """
    specs = tmp_path / 'unitspec'
    specs.mkdir()
    (specs / 'KEYGL5.xml').write_text(
        '<UnitSpecification><Parameters><Param><Name>Value</Name><Type>int</Type>'
        '<Address>$21</Address><ArraySize>12</ArraySize><ProgramMethod>direct</ProgramMethod>'
        '<Protection>none</Protection></Param></Parameters></UnitSpecification>'
    )
    project = tmp_path / 'project.xml'
    project.write_text(
        '<Installation><Project><TagName>TEST</TagName><Network><Address>254</Address>'
        '<TagName>Fixture</TagName><Interface><InterfaceType>CNI</InterfaceType>'
        '<InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>'
        '<Unit><Address>5</Address><TagName>Fixture unit</TagName>'
        '<UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion></Unit>'
        '</Network></Project></Installation>'
    )
    new_value = bytes.fromhex('00112233445566778899AABB')
    value_text = ' '.join(f'0x{value:02X}' for value in new_value)
    initial = bytes.fromhex('FFFF9B192D8229E4FF923AF3')
    sim = InitializedPCI(
        profile='captured', command_checksum=True,
        legacy_memory={5: {0x21 + index: value for index, value in enumerate(initial)}},
        legacy_writable={5: set(range(0x21, 0x21 + len(initial)))},
    )
    with socket.socket() as broker, sim.running() as pci:
        broker.bind(('127.0.0.1', 0)); broker.listen(1)
        with (tmp_path / 'physical-pp-daemon.log').open('w+') as log:
            process = subprocess.Popen([
                str(BIN), '--tcp', f'{pci[0]}:{pci[1]}',
                '--broker-address', '127.0.0.1', '--broker-port', str(broker.getsockname()[1]),
                '--broker-disable-tls', '--timesync', '0', '--status-resync', '0',
                '--project-file', str(project), '--cgate-bind', '127.0.0.1:0',
                '--cgate-state', str(tmp_path / 'state.json'),
                '--cgate-unitspec', str(specs),
            ], stdout=subprocess.DEVNULL, stderr=log)
            try:
                deadline = time.monotonic() + 10
                port = None
                while time.monotonic() < deadline:
                    log.seek(0); output = log.read()
                    match = re.search(r'C-Gate service listening on 127\.0\.0\.1:(\d+)', output)
                    if match:
                        port = match[1]; break
                    assert process.poll() is None, output
                    time.sleep(.02)
                assert port is not None, output
                result = subprocess.run([
                    sys.executable, '-m', 'cbus_toolkit', 'cgate',
                    '--host', '127.0.0.1', '--port', port, '--timeout', '30',
                    'physical-pp', 'apply', '//TEST/254/p/5', '--method', 'direct',
                    '--journal', str(tmp_path / 'physical-pp-journal.json'),
                    '--set', 'Value', value_text,
                ], capture_output=True, text=True, timeout=120)
                assert result.returncode == 0, result.stderr
                value = json.loads(result.stdout)
                assert value['complete']
                assert value['native_save_operation'] == 'PP SAVE_TO_SOURCE'
                assert value['save_attempts'] == 1
                assert value['automatic_write_retries'] == 0
                assert value['staged_readback_verified']
                assert value['fresh_physical_readback_verified']
                assert not value['power_cycle_persistence_verified']
                assert bytes(sim.legacy_memory[5][address] for address in range(0x21, 0x2D)) == new_value
                assert len({row['connection'] for row in sim.wire_log}) == 1
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


def _diagnostics_fixture():
    import importlib.util
    path = ROOT / 'toolkit-cli/research/unit_diagnostics_fixture.py'
    spec = importlib.util.spec_from_file_location('unit_diagnostics_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(BIN is None, reason='Build the Rust cmqttd binary to run cross-language hardware-service tests')
def test_real_cli_network_diagnose_through_cmqttd(tmp_path):
    """Toolkit Diagnostics dialog: production CLI -> cmqttd -> Python PCI.

    The synthetic catalogue names KEYE1's native class (CBusNeoInputUnit), so
    Psync reads IDENTIFY4 only, as native C-Gate did against this fixture.
    The local PCI unit and the clock pass are outside this case (see
    docs/network-diagnostics.md). Voltages are the fixture's chosen IDENTIFY4
    bytes, not electrical measurements.
    """
    fixture = _diagnostics_fixture()
    sim = fixture.diagnostics_simulator(units=(4, 5, 16), command_checksum=True)
    command = sim._command

    def initialized(line, context):
        # Literal initialization profile from the existing Rust hardware tests.
        if line in (b'~', b'A32100FF', b'A32200FF', b'A342000E', b'A3300079'):
            return b'', None
        return command(line, context)

    sim._command = initialized
    specs = tmp_path / 'unitspec'
    specs.mkdir()
    (specs / 'cbusunits.xml').write_text(
        '<CBusUnits><Units><Unit><CatalogNumber>SYNTHETIC-KEYE1</CatalogNumber><FirmwareRevisions>'
        '<Revision><UnitType>KEYE1</UnitType><MinVersion>2.5.00</MinVersion><MaxVersion>9</MaxVersion>'
        '<ClassName>CBusNeoInputUnit</ClassName></Revision></FirmwareRevisions></Unit></Units></CBusUnits>')
    units = ''.join(
        f'<Unit><Address>{address}</Address><TagName>U{address}</TagName><UnitType>{unit_type}</UnitType>'
        f'<FirmwareVersion>{firmware}</FirmwareVersion></Unit>'
        for address, unit_type, firmware in fixture.DATABASE_UNITS if address != 17)
    project = tmp_path / 'project.xml'
    project.write_text(
        '<Installation><Project><TagName>DIAGNOSE</TagName><Network><Address>254</Address>'
        '<TagName>Fixture</TagName><Interface><InterfaceType>CNI</InterfaceType>'
        '<InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>' + units +
        '</Network></Project></Installation>')
    with socket.socket() as broker, sim.running() as pci:
        broker.bind(('127.0.0.1', 0)); broker.listen(1)
        with (tmp_path / 'diagnose-daemon.log').open('w+') as log:
            process = subprocess.Popen([
                str(BIN), '--tcp', f'{pci[0]}:{pci[1]}',
                '--broker-address', '127.0.0.1', '--broker-port', str(broker.getsockname()[1]),
                '--broker-disable-tls', '--timesync', '0', '--status-resync', '0',
                '--project-file', str(project), '--cgate-bind', '127.0.0.1:0',
                '--cgate-state', str(tmp_path / 'state.json'), '--cgate-unitspec', str(specs),
            ], stdout=subprocess.DEVNULL, stderr=log)
            try:
                deadline = time.monotonic() + 10
                port = None
                while time.monotonic() < deadline:
                    log.seek(0); output = log.read()
                    match = re.search(r'C-Gate service listening on 127\.0\.0\.1:(\d+)', output)
                    if match:
                        port = match[1]; break
                    assert process.poll() is None, output
                    time.sleep(.02)
                assert port is not None, output
                with CGateClient('127.0.0.1', int(port), timeout=30) as client:
                    assert client.command('NET SYNC //DIAGNOSE/254').code == 200
                result = subprocess.run([
                    sys.executable, '-m', 'cbus_toolkit', 'cgate',
                    '--host', '127.0.0.1', '--port', port, '--timeout', '30',
                    'network', 'diagnose', '//DIAGNOSE/254', '--project', 'DIAGNOSE',
                    '--unit', '4', '--unit', '5', '--unit', '99', '--no-clock',
                ], capture_output=True, text=True, timeout=120)
                # Unit 99 is database-only, so the run is incomplete (exit 1).
                assert result.returncode == 1, result.stderr
                value = json.loads(result.stdout)
                assert value['pingu_addresses'] == [4, 5, 16]
                units = {row['address']: row for row in value['units']}
                assert {key: units[4][key] for key in ('found', 'voltage', 'burden', 'burden_basis', 'errors')} == {
                    'found': 'present', 'voltage': 31.0, 'burden': 'not-enabled',
                    'burden_basis': 'native-burdenactive', 'errors': []}
                assert (units[5]['voltage'], units[5]['burden_basis']) == (31.5, 'toolkit-unit-type-rule')
                assert {key: units[99][key] for key in ('found', 'voltage', 'burden')} == {
                    'found': 'not-found', 'voltage': 'unknown', 'burden': 'unknown'}
                replies = {row['command']: row['lines'] for row in value['commands']}
                assert replies['DO //DIAGNOSE/254/p/4 Psync'] == ['202 Done: //DIAGNOSE/254/p/4']
                assert not any('/p/99' in command for command in replies)
                assert [row for row in sim.wire_log if row.get('reason')] == []
                assert len({row['connection'] for row in sim.wire_log}) == 1
                assert process.poll() is None
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
