"""Literal duplicate-node reads and native read-only serial-seeker acceptance."""
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.networks import NativeNetworks
from cbus_toolkit.programming import xml_text
from cbus_toolkit.serials import NativeSerials
from cbus_toolkit.simulator import PCISimulator, UnitState, synthetic_units
from cbus_toolkit.simulator_duplicates import DuplicateAddressSimulator


SERIAL_A = b"86FF10008D0438FFFFFFFF18B10616A200051A\r\n"
SERIAL_B = b"86FF10008D0438FFFFFFFF18B10617A2000519\r\n"


def fixture_units():
    first, _, pci = synthetic_units()
    first.address = 255; first.parameters[32] = b"\xff"
    second = UnitState(255, first.attributes, first.parameters, {}, first.mmi_state)
    # Explicit generated second identity: packed serial101136.1559. Other
    # attribute bytes remain the captured KEYE1 block; no hardware provenance.
    second.attributes[4] = bytes.fromhex("38FFFFFFFF18B10617A20005")
    return [first, second], pci


def fixture(**kwargs):
    nodes, pci = fixture_units()
    return DuplicateAddressSimulator(nodes, pci, **kwargs)


class DuplicateSimulatorTests(unittest.TestCase):
    def test_independent_literal_serial_frames_have_one_pci_confirmation(self):
        sim = fixture(); before = sim.snapshot(); context = {"header": None}
        self.assertEqual(sim._command(b"\\46FF002104g", context), (b"g." + SERIAL_A + SERIAL_B, None))
        self.assertEqual(sim._command(b"2104h", context), (b"h." + SERIAL_A + SERIAL_B, None))
        self.assertEqual(sim._command(b"2104i", {"header": None}),
                         (b"i.8D04FFFFFF000018A664A3B10005F7\r\n", None))
        self.assertEqual(before, sim.snapshot())
        for frame in (SERIAL_A, SERIAL_B):
            decoded = bytes.fromhex(frame.decode())
            self.assertEqual(sum(decoded) % 256, 0)
        self.assertEqual(int.from_bytes(bytes.fromhex(SERIAL_A.decode())[11:15], "big"), 0x18B10616)

    def test_socket_reads_fragmentation_and_connection_headers(self):
        sim = fixture(fragment_sizes=(1, 3, 7))
        with sim.running() as endpoint, socket.create_connection(endpoint, timeout=2) as stream:
            stream.sendall(b"\\46FF002104g\r")
            received = b""
            while len(received) < len(b"g." + SERIAL_A + SERIAL_B): received += stream.recv(4096)
            self.assertEqual(received, b"g." + SERIAL_A + SERIAL_B)
            stream.sendall(b"2104h\r")
            received = b""
            while len(received) < len(b"h." + SERIAL_A + SERIAL_B): received += stream.recv(4096)
            self.assertEqual(received, b"h." + SERIAL_A + SERIAL_B)
        self.assertFalse([r for r in sim.wire_log if r.get("reason")])

    def test_read_chains_checksum_mode_and_basic_pci_are_bounded(self):
        sim = fixture(); context = {"header": None}
        self.assertEqual(sim._command(b"@1A2001", context), (b"8220104E\r\n", None))
        response, reason = sim._command(b"\\46FF0021012102g", context)
        self.assertIsNone(reason); self.assertEqual(len(response.split(b"\r\n")), 3)
        self.assertEqual(response[2:].split(b"\r\n")[0], response.split(b"\r\n")[1])
        sim = fixture(command_checksum=True)
        self.assertEqual(sim._command(b"\\46FF00210496g", {"header": None}), (b"g." + SERIAL_A + SERIAL_B, None))
        response, reason = sim._command(b"\\46FF00210495g", {"header": None})
        self.assertEqual(response, b"g$"); self.assertIn("checksum", reason)

    def test_install_mmi_reports_shared_presence_without_inventing_a_second_address(self):
        sim = fixture(); before = sim.snapshot()
        expected = (b"g.D8FF00" + b"00" * 4 + b"01" + b"00" * 17 + b"28\r\n"
                    + b"D8FF58" + b"00" * 22 + b"D1\r\n"
                    + b"D6FFB0" + b"00" * 19 + b"80FB\r\n")
        self.assertEqual(sim._command(b"\\05FF00FAFF00g", {"header": None}), (expected, None))
        self.assertEqual(sim.snapshot(), before)

    def test_every_mutating_route_is_rejected_before_state_or_context_changes(self):
        sim = fixture(); before = sim.snapshot()
        commands = (b"\\46FF001120g", b"\\46FF00A3204E065Ag", b"\\461000A3420701g",
                    b"\\46FF0900A3004100g", b"\\05FF000F0018B1061606B5g",
                    b"\\053800790101g", b"\\05CA00090101g", b"\\05CB000201FFg",
                    b"\\46FF002104A3204E065Ag", b"@A22006g", b"\\05FF00FA3800g")
        for command in commands:
            with self.subTest(command=command):
                context = {"header": None}; response, reason = sim._command(command, context)
                self.assertEqual(response, b"g#"); self.assertIsNotNone(reason)
                self.assertEqual(context, {"header": None}); self.assertEqual(before, sim.snapshot())
        context = {"header": b"\x46\xff\x00"}
        self.assertIsNotNone(sim._command(b"A3204E065Ah", context)[1])
        self.assertEqual(before, sim.snapshot())

    def test_nodes_are_independent_detached_and_snapshot_retains_both(self):
        nodes, pci = fixture_units(); sim = DuplicateAddressSimulator(nodes, pci)
        before = sim.snapshot()
        nodes[0].parameters[32] = b"\x06"; nodes[1].attributes[4] = bytes(12)
        detached = sim.nodes; detached["101136.1558"].parameters[32] = b"\x07"
        detached["101136.1559"].address = 7
        snapshot = sim.snapshot(); snapshot["physical_nodes"][0]["address"] = 1
        self.assertEqual(sim.snapshot(), before)
        self.assertEqual([n["address"] for n in before["physical_nodes"]], [255, 255])
        self.assertEqual([n["serial"] for n in before["physical_nodes"]], ["101136.1558", "101136.1559"])

    def test_invalid_ambiguous_and_unmodeled_fixture_profiles_reject(self):
        mutations = (
            lambda n, p: setattr(n[1], "address", 4),
            lambda n, p: n[1].attributes.__setitem__(1, b"KEYGL5  "),
            lambda n, p: n[1].attributes.__setitem__(2, b"2.4.00  "),
            lambda n, p: n[1].parameters.__setitem__(32, b"\x04"),
            lambda n, p: n[1].attributes.__setitem__(4, n[0].attributes[4]),
            lambda n, p: n[1].attributes.__setitem__(4, bytes(12)),
            lambda n, p: n[1].attributes.__setitem__(4, bytes(11)),
            lambda n, p: n[1].parameters.__setitem__(0xF2, b"\x01"),
            lambda n, p: n[1].write_tags.__setitem__(32, 78),
            lambda n, p: setattr(p, "address", 255),
            lambda n, p: p.attributes.__setitem__(4, n[0].attributes[4]),
        )
        for mutation in mutations:
            nodes, pci = fixture_units(); mutation(nodes, pci)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): DuplicateAddressSimulator(nodes, pci)
        nodes, pci = fixture_units()
        for value in ([], nodes[:1], nodes + nodes[:1], [None, nodes[1]]):
            with self.subTest(value=value), self.assertRaises(ValueError): DuplicateAddressSimulator(value, pci)

    def test_state_loading_and_unknown_reads_fail_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with self.assertRaisesRegex(ValueError, "state-file"): fixture(state_path=path)
            self.assertFalse(path.exists())
            path.write_text(json.dumps(fixture().snapshot()))
            with self.assertRaises(ValueError): PCISimulator(state_path=path)
        sim = fixture(); before = sim.snapshot()
        for command in (b"\\46FF002199g", b"\\46FF001A2201g", b"\\46FE002104g", b"\\46FF0021g", b"gg"):
            with self.subTest(command=command): self.assertIsNotNone(sim._command(command, {"header": None})[1])
        self.assertEqual(before, sim.snapshot())


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for native duplicate discovery")
class NativeDuplicateDiscoveryTests(unittest.TestCase):
    def test_serial_seeker_detects_both_at255_without_fixture_or_database_mutation(self):
        sim = fixture(response_delay=.01); before = sim.snapshot()
        project = "DD" + uuid4().hex[:6].upper(); network = "//" + project + "/254"
        report = {"passed": False, "scope": "Read-only two-node KEYE1 discovery at255; synthetic delivery timing",
                  "native_serial_list_exposed": False, "fixture_serials": list(sim.nodes)}
        host = os.environ["CBUS_CGATE_TEST_HOST"]
        port = int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        with sim.running("0.0.0.0", 0) as (_, fixture_port), CGateClient(host, port, timeout=45) as client:
            projects, db, networks = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
            created = False
            try:
                projects.operation("new", project); created = True
                db.create_network(project, 254, "Duplicate_Reads", "Cni",
                    os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal") + ":" + str(fixture_port))
                for address, serial in ((6, "101136.1558"), (7, "101136.1559")):
                    db.create_unit(network, address, "Known_" + str(address), "KEYE1", "2.5.00", catalog_number="5031NMML")
                    db.set(network + "/p/" + str(address) + "/SerialNumber", serial)
                projects.operation("save", project)
                xml_before = xml_text(db.get(network, xml=True))
                for name, value in (("AutoUnravel", "no"), ("AutoUpdate", "no"), ("Retries", "0")):
                    self.assertEqual(client.command("SET " + network + " " + name + " " + value).code, 200)
                networks.open(network)
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if any("InterfaceState=running" in line for line in client.command("GET " + network + " InterfaceState").lines): break
                    time.sleep(.1)
                else: self.fail("Native interface did not start")
                self.assertEqual(networks.synchronize(network, fast=True).code, 200)
                wire_start = len(sim.wire_log)
                check = client.command("NET CHECKUNIT " + network + " 255")
                self.assertEqual(check.lines, ("120 Duplicate units detected at address: 255",))
                seeker_wire = deepcopy(sim.wire_log[wire_start:])
                replies = [bytes.fromhex(r["hex"]) for r in seeker_wire if r["direction"] == "tx"]
                self.assertEqual(sum(SERIAL_A in r and SERIAL_B in r for r in replies), 1)
                inventory = NativeSerials(client).refresh(network, units=[255])
                self.assertFalse(inventory.complete); self.assertEqual(inventory.identities, ())
                self.assertEqual(inventory.records[0].status, "duplicate_address")
                self.assertIsNone(inventory.records[0].serial)
                cached_units = client.command("GET " + network + " Units")
                self.assertEqual(cached_units.lines, ("300 " + network + ": Units=16",))
                full_refresh_commands = []

                class RecordingClient:
                    @property
                    def connected(self): return client.connected
                    def command(self, command):
                        response = client.command(command)
                        full_refresh_commands.append({"command": command, "reply": list(response.lines)})
                        return response

                full_inventory = NativeSerials(RecordingClient()).refresh(network)
                self.assertIsNone(full_inventory.requested)
                self.assertFalse(full_inventory.complete); self.assertEqual(full_inventory.errors, ())
                self.assertTrue(full_inventory.refresh_completed)
                records = {record.address: record for record in full_inventory.records}
                self.assertEqual(set(records), {16, 255})
                self.assertEqual(records[16].status, "ok")
                self.assertEqual(records[16].serial, "100966.1187")
                self.assertEqual(records[255].status, "duplicate_address")
                self.assertIsNone(records[255].identity)
                default_check = next(item for item in full_refresh_commands
                                     if item["command"] == "NET CHECKUNIT " + network + " *")
                self.assertEqual(default_check["reply"], ["120-Single unit detected at address: 16",
                                                          "120 Duplicate units detected at address: 255"])
                self.assertEqual(xml_text(db.get(network, xml=True)), xml_before)
                self.assertEqual(sim.snapshot(), before)
                self.assertFalse([r for r in sim.wire_log if r.get("reason")])
                receives = [bytes.fromhex(r["hex"]).upper() for r in sim.wire_log if r["direction"] == "rx"]
                self.assertFalse(any(b"A3204E" in r or b"1120" in r or b"05FF000F" in r for r in receives))
                report.update(passed=True, check_reply=list(check.lines), inventory=inventory.as_dict(),
                              cached_units_before_full_refresh=list(cached_units.lines),
                              full_refresh_inventory=full_inventory.as_dict(), full_refresh_commands=full_refresh_commands,
                              before_database_xml=xml_before, after_database_xml=xml_text(db.get(network, xml=True)),
                              before_fixture=before, after_fixture=sim.snapshot(), seeker_wire=seeker_wire)
            finally:
                errors = []
                if created:
                    for command in ("NET CLOSE " + network, "PROJECT CLOSE " + project, "PROJECT DELETE " + project):
                        try: client.command(command)
                        except Exception as error: errors.append(str(error))
                report["cleanup_errors"] = errors; report["wire"] = list(sim.wire_log)
                if path := os.environ.get("CBUS_DUPLICATE_DISCOVERY_REPORT"):
                    destination = Path(path); destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(json.dumps(report, indent=2) + "\n")
                if report["passed"]: self.assertEqual(errors, [])


if __name__ == "__main__": unittest.main()
