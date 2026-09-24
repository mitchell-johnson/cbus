"""Production CLI -> real Rust daemon -> independently implemented Python PCI.

Only ephemeral loopback sockets and synthetic configuration bytes are used.
"""
import json
from pathlib import Path
import re
import socket
import subprocess
import time

import pytest
from cbus_toolkit.simulator import PCISimulator
from test_cmqtt import memory


ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / 'rust/target/debug/cmqttd'


class InitializedPCI(PCISimulator):
    def _command(self, line, context):
        # Literal initialization profile from the existing Rust hardware tests.
        if line in (b'~', b'A32100FF', b'A32200FF', b'A342000E', b'A3300079'):
            return b'', None
        return super()._command(line, context)


@pytest.mark.skipif(not BIN.exists(), reason='Build the Rust cmqttd binary to run cross-language hardware-service tests')
def test_real_cli_reads_all_edlt_labels_through_cmqttd(tmp_path):
    image = memory()
    sim = InitializedPCI(profile='captured', command_checksum=True,
                         physical_memory={5: dict(enumerate(image))})
    project = tmp_path / 'project.xml'
    project.write_text('<Installation><Project><TagName>TEST</TagName><Network><Address>254</Address>'
                       '<TagName>Fixture</TagName><Unit><Address>5</Address><TagName>Fixture eDLT</TagName>'
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
                result = subprocess.run([str(ROOT/'toolkit-cli/.venv/bin/cbus-toolkit'), 'cgate',
                    '--host', '127.0.0.1', '--port', port, '--timeout', '30',
                    'edlt-labels', '//TEST/254/p/5'], capture_output=True, text=True, timeout=120)
                assert result.returncode == 0, result.stderr
                value = json.loads(result.stdout)
                assert value['source'] == 'physical-via-cmqttd'
                assert [w['label'] for w in value['widgets']] == ['Kitchen', 'Goodnight']
                assert len(value['static_strings']) == 64
                assert value['static_text_crc_verified']
                assert sim.physical_memory[5] == dict(enumerate(image))
                connections = {row['connection'] for row in sim.wire_log}
                assert len(connections) == 1
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
