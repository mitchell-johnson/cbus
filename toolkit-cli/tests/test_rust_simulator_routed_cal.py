"""Python routed commissioning CLI against the real Rust PCI simulator process.

The simulator's opt-in fixture confirms transport composition and route
isolation. It is deliberately not accepted as a physical bridge or persistence
test. Set CBUS_SIMULATOR_BIN to an already-built binary for this focused gate.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

from cbus_toolkit.cli import main


class RustRoutedCalSimulatorTests(unittest.TestCase):
    def setUp(self):
        name = os.environ.get("CBUS_SIMULATOR_BIN", "")
        if not name or not Path(name).is_file():
            self.skipTest("set CBUS_SIMULATOR_BIN to the built Rust simulator")
        self.binary = name

    @staticmethod
    def invoke(args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:
                code = main(args)
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), error.getvalue()

    @staticmethod
    def project(path: Path, depth: int) -> tuple[Path, tuple[int, ...]]:
        bridges = tuple(253 - index for index in range(depth))
        nodes = ['<Installation><Project><TagName>HOUSE</TagName>']
        for index in range(depth + 1):
            address = 254 - index
            if index == 0:
                interface = '<InterfaceType>CNI</InterfaceType><InterfaceAddress>owned</InterfaceAddress>'
            else:
                parent = 255 - index
                interface = (f'<InterfaceType>Bridge</InterfaceType>'
                             f'<InterfaceAddress>{parent}/p/{address}</InterfaceAddress>')
            unit = (f'<Unit><Address>{address - 1}</Address><UnitType>BRIDGE2N</UnitType></Unit>'
                    if index < depth else '<Unit><Address>4</Address><UnitType>KEYGL5</UnitType></Unit>')
            if index == 0 and depth == 0:
                unit = '<Unit><Address>4</Address><UnitType>KEYGL5</UnitType></Unit>'
            nodes.append(f'<Network><TagName>Network{address}</TagName><Address>{address}</Address>'
                         f'<Interface>{interface}</Interface>{unit}</Network>')
        nodes.append('</Project></Installation>')
        path.write_text(''.join(nodes), encoding='utf-8')
        return path, bridges

    @contextlib.contextmanager
    def simulator(self, bridges, *, checksum=False):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        args = [self.binary, '127.0.0.1', str(port), '--cal-unit', '4',
                '--cal-local-unit', '16']
        if checksum:
            args.append('--cal-srchk')
        for bridge in bridges:
            args.extend(('--cal-bridge', str(bridge)))
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    self.fail(f'simulator exited before bind: {process.returncode}')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.01)
            else:
                self.fail('simulator did not bind its owned loopback port')
            yield port
        finally:
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=3)

    @staticmethod
    def common(port, *, checksum=False):
        return ['--compact', 'pci', '--host', '127.0.0.1', '--port', str(port),
                *(['--checksum'] if checksum else []), '--local-unit', '16']

    def test_project_bound_write_then_independent_recall_direct_through_six_bridges(self):
        for checksum, depth in ((False, d) for d in range(7)):
            with self.subTest(depth=depth, checksum=checksum), tempfile.TemporaryDirectory() as directory:
                project, bridges = self.project(Path(directory) / 'house.xml', depth)
                target = str(254 - depth)
                with self.simulator(bridges, checksum=checksum) as port:
                    base = self.common(port, checksum=checksum)
                    route = ['--project-file', str(project), '--project-name', 'HOUSE',
                             '--source-network', '254', '--target-network', target]
                    code, output, error = self.invoke([
                        *base, 'routed-write', '4', '7', '55AABB',
                        '--expected-ack-tag', '85', *route,
                    ])
                    self.assertEqual((code, error), (0, ''), f'depth={depth}')
                    write = json.loads(output)
                    self.assertEqual(write['requested']['bridges'], list(bridges))
                    self.assertEqual(write['route_plan']['route_depth'], depth)
                    self.assertTrue(write['confirmation_received'])
                    self.assertTrue(write['acknowledgement_received'])
                    self.assertFalse(write['nonvolatile_persistence_verified'])

                    code, output, error = self.invoke([
                        *base, 'routed-recall', '4', '7', '2', *route,
                    ])
                    self.assertEqual((code, error), (0, ''), f'depth={depth}')
                    recall = json.loads(output)
                    self.assertEqual(recall['data_hex'], 'AABB')
                    self.assertEqual(recall['requested']['bridges'], list(bridges))
                    self.assertFalse(recall['physical_delivery_verified'])

        # The full 0..6 route matrix above is unchecksummed; exercise the
        # negotiated SRCHK mode at direct, short and boundary route depths.
        for depth in (0, 1, 2, 6):
            with self.subTest(depth=depth, checksum=True), tempfile.TemporaryDirectory() as directory:
                project, bridges = self.project(Path(directory) / 'house.xml', depth)
                with self.simulator(bridges, checksum=True) as port:
                    base = self.common(port, checksum=True)
                    route = ['--project-file', str(project), '--source-network', '254',
                             '--target-network', str(254 - depth)]
                    code, _, error = self.invoke([
                        *base, 'routed-write', '4', '7', '55AABB',
                        '--expected-ack-tag', '85', *route,
                    ])
                    self.assertEqual((code, error), (0, ''))
                    code, output, error = self.invoke([
                        *base, 'routed-recall', '4', '7', '2', *route,
                    ])
                    self.assertEqual((code, error), (0, ''))
                    self.assertEqual(json.loads(output)['data_hex'], 'AABB')

    def test_wrong_outbound_route_never_mutates_the_simulated_parameter(self):
        with tempfile.TemporaryDirectory() as directory:
            project, bridges = self.project(Path(directory) / 'house.xml', 2)
            with self.simulator(bridges) as port:
                base = self.common(port)
                route = ['--project-file', str(project), '--source-network', '254',
                         '--target-network', '252']
                code, _, error = self.invoke([
                    *base, 'routed-write', '4', '7', '55AABB',
                    '--expected-ack-tag', '85', *route,
                ])
                self.assertEqual((code, error), (0, ''))

                # Raw mode permits an independent deliberately incorrect route.
                # The fixture must ignore it; the resulting write is uncertain
                # to the client, and a later right-route read proves isolation.
                code, output, error = self.invoke([
                    '--compact', 'pci', '--host', '127.0.0.1', '--port', str(port),
                    '--timeout', '0.2', 'routed-write', '4', '7', '55CCDD',
                    '--expected-ack-tag', '85', '--bridge', '253', '--bridge', '251',
                    '--expected-source', '253', '--expected-destination', '16',
                    '--expected-route', '251', '--expected-route', '4',
                ])
                self.assertEqual((code, output), (1, ''))
                self.assertTrue(json.loads(error)['pci_routed_write_evidence']['write_outcome_uncertain'])

                code, output, error = self.invoke([
                    *base, 'routed-recall', '4', '7', '2', *route,
                ])
                self.assertEqual((code, error), (0, ''))
                self.assertEqual(json.loads(output)['data_hex'], 'AABB')


if __name__ == '__main__':
    unittest.main()
