"""Scalar address255 commissioning and raw MATCHDB fallback regression."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.networks import NativeNetworks
from cbus_toolkit.physical_addressing import PhysicalAddressUncertain
from cbus_toolkit.programming import xml_text
from cbus_toolkit.serial_commissioning import SerialCommissioning, SerialCommissionPlan
from cbus_toolkit.serials import NativeSerials
from cbus_toolkit.simulator import PCISimulator
from tests.test_physical_addressing import PhysicalClient
from tests.test_serials import NET, reply
from tests.test_simulator_serial_addressing import commissioning_fixture


class CommissionClient(PhysicalClient):
    def __init__(self):
        super().__init__()
        self.units[255] = self.units.pop(4); self.units[255]["Address"] = "255"
        self.network["Units"] = "5,16,255"
        self.database = self.database.replace("</Network>", '<Unit><Address>6</Address><UnitType>KEYE1</UnitType><FirmwareVersion>2.5.00</FirmwareVersion><SerialNumber>101136.1558</SerialNumber><Unknown>keep</Unknown></Unit></Network>')



class SerialCommissioningTests(unittest.TestCase):
    def setUp(self): self.client = CommissionClient(); self.manager = SerialCommissioning(self.client)

    def test_matching_database_target_and_imported_plan_confirm_only_actual_move(self):
        plan = self.manager.plan(NET + "/p/255", 6, expected_serial="101136.1558")
        recovered = SerialCommissionPlan.from_dict(json.loads(json.dumps(plan.as_dict())))
        self.assertEqual(recovered, plan)
        self.assertEqual(self.manager.verify(recovered)["outcome"], "confirmed_not_moved")
        result = self.manager.apply(plan)
        self.assertEqual(result["outcome"], "confirmed_moved")
        self.assertEqual(result["command"], "SET " + NET + "/p/255 Address 6")
        self.assertEqual(result["method"], "database_serial_match_then_scalar_address")
        self.assertFalse(any(c.startswith("NET UNRAVEL") for c in self.client.commands))
        start = len(self.client.commands)
        self.assertEqual(self.manager.verify(recovered)["outcome"], "confirmed_moved")
        self.assertFalse(any(c.startswith(("SET ", "NET UNRAVEL")) for c in self.client.commands[start:]))

    def test_recovery_method_guard_and_legacy_baseline_compatibility(self):
        plan = self.manager.plan(NET + "/p/255", 6, expected_serial="101136.1558")
        old = plan.as_dict(); old.pop("method")
        self.assertEqual(SerialCommissionPlan.from_dict(old), plan)
        old["method"] = "unravel_with_fallback"
        with self.assertRaises(ValueError): SerialCommissionPlan.from_dict(old)

    def test_regular_address_reserved_destinations_and_unmatched_or_duplicate_database_serial_reject(self):
        for source, destination in ((4, 6), (255, 0), (255, 1), (255, 255), (255, True)):
            with self.subTest(source=source, destination=destination), self.assertRaises(ValueError):
                self.manager.plan(NET + "/p/" + str(source), destination, expected_serial="101136.1558")
        for change in (lambda s: s.replace("101136.1558", "123.456"),
                       lambda s: s.replace("<UnitType>KEYE1", "<UnitType>KEYGL5"),
                       lambda s: s.replace("</Network>", '<Unit><Address>7</Address><SerialNumber>101136.1558</SerialNumber></Unit></Network>')):
            with self.subTest(change=change):
                client = CommissionClient(); client.database = change(client.database)
                with self.assertRaises(ValueError): SerialCommissioning(client).plan(NET + "/p/255", 6, expected_serial="101136.1558")
                self.assertFalse(any(c.startswith("NET UNRAVEL") for c in client.commands))

    def test_stale_metadata_fails_before_native_operation(self):
        plan = self.manager.plan(NET + "/p/255", 6, expected_serial="101136.1558")
        self.client.database = self.client.database.replace("keep", "changed")
        with self.assertRaisesRegex(ValueError, "stale"): self.manager.apply(plan)
        self.assertFalse(any(c.startswith("NET UNRAVEL") for c in self.client.commands))

    def test_success_status_without_move_and_wrong_identity_are_uncertain(self):
        for mode in ("unchanged", "serial"):
            with self.subTest(mode=mode):
                client = CommissionClient(); client.mode = mode
                with self.assertRaises(PhysicalAddressUncertain) as error:
                    SerialCommissioning(client).commission(NET + "/p/255", 6, expected_serial="101136.1558")
                self.assertEqual(error.exception.details["outcome"], "uncertain")
                self.assertEqual(sum(c.startswith("SET ") for c in client.commands), 1)

    def test_lost_reply_stops_and_recovery_is_observation_only(self):
        plan = self.manager.plan(NET + "/p/255", 6, expected_serial="101136.1558")
        self.client.mode = "disconnect"
        with self.assertRaises(PhysicalAddressUncertain) as error: self.manager.apply(plan)
        self.assertEqual(self.client.commands[-1], "SET " + NET + "/p/255 Address 6")
        self.assertIn("not replayed", str(error.exception))
        recovery = SerialCommissionPlan.from_dict(error.exception.details["plan"])
        self.client.connected = True
        self.assertEqual(self.manager.verify(recovery)["outcome"], "confirmed_moved")
        self.assertEqual(sum(c.startswith("SET ") for c in self.client.commands), 1)

    def test_serial_commissioning_requires_fresh_full_coverage_before_scalar_write(self):
        plan=self.manager.plan(NET+"/p/255",6,expected_serial="101136.1558")
        self.client.pingu_fault_at=3
        self.client.pingu_reply=reply("302-Units=5, 6, 16, 255","200 OK.")
        with self.assertRaisesRegex(ValueError,"occupied"):
            self.manager.apply(plan)
        self.assertEqual(self.client.commands[-1],"NET PINGU "+NET)
        self.assertFalse(any(command.startswith(("SET ","NET UNRAVEL")) for command in self.client.commands))


class LostCommissionReply:
    def __init__(self, client): self.client, self.calls = client, 0
    @property
    def connected(self): return self.client.connected
    def command(self, command):
        result = self.client.command(command)
        if command.startswith("SET ") and " Address " in command:
            self.calls += 1; self.client.close()
            raise OSError("Injected lost response after native commissioning")
        return result


class InternalSerialFault:
    """One valid all-ones IDENTIFY4 response, armed after helper preflight."""
    def __init__(self, simulator):
        self.sim, self.original = simulator, simulator._command
        self.armed, self.triggered, self.operations = False, 0, []
        simulator._command = self.handle

    def handle(self, line, context):
        if self.armed and b"46FF002104" in line.upper():
            self.original(line, context)  # Maintain explicit-header compression state.
            self.armed = False; self.triggered += 1
            data = bytearray(self.sim.units[255].attributes[4]); data[5:9] = b"\xff" * 4
            return line[-1:] + b"." + self.sim._reply(bytes([0x86, 255, 16, 0, 0x8D, 4]) + data), None
        return self.original(line, context)


class ArmSerialFault:
    def __init__(self, client, fault): self.client, self.fault = client, fault
    @property
    def connected(self): return self.client.connected
    def close(self): self.client.close()
    def command(self, command):
        if command.startswith("NET UNRAVELUNIT ") or command.startswith("SET ") and " Address " in command:
            self.fault.armed = True; self.fault.operations.append(command)
        return self.client.command(command)


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for native commissioning")
class NativeSerialCommissioningTests(unittest.TestCase):
    def _lifecycle(self, lost=False, raw_scan_fault=False):
        project = "CM" + uuid4().hex[:6].upper(); network = f"//{project}/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        report = {"scope": "Native single KEYE1 scalar commissioning from255 and raw MATCHDB fallback comparison; no hardware claim",
                  "passed": False, "lost_reply": lost, "raw_unravel_scan_fault": raw_scan_fault}
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            sim = commissioning_fixture(state_path=state, response_delay=.01, empty_addresses=(2, 6) if raw_scan_fault else (6,))
            fault = InternalSerialFault(sim)
            with sim.running("0.0.0.0", 0) as (_, fixture_port), CGateClient(host, port, timeout=45) as client:
                projects, db, networks = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
                created = False
                try:
                    projects.operation("new", project); created = True
                    db.create_network(project, 254, "Serial_Commission", "Cni",
                        os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal") + ":" + str(fixture_port))
                    db.create_unit(network, 6, "Target_Serial", "KEYE1", "2.5.00", catalog_number="5031NMML")
                    db.set(network + "/p/6/SerialNumber", "101136.1558")
                    projects.operation("save", project)
                    networks.open(network); networks.wait_ready(network, timeout=25)
                    client.command("SET " + network + " Retries 0")
                    armed = ArmSerialFault(client, fault)
                    manager = SerialCommissioning(armed)
                    before_xml = xml_text(db.get(network, xml=True)); before_state = sim.snapshot()
                    plan = manager.plan(network + "/p/255", 6, expected_serial="101136.1558")
                    start = len(sim.wire_log)
                    if raw_scan_fault:
                        raw = armed.command("NET UNRAVELUNIT " + network + " 255 MATCHDB")
                        self.assertEqual(raw.code, 200)
                        result = manager.verify(plan)
                        self.assertEqual(result["outcome"], "uncertain")
                        self.assertEqual(result["serial_observed_addresses"], [2])
                        self.assertEqual(fault.triggered, 1)
                        report["raw_reply"] = list(raw.lines)
                    elif lost:
                        wrapper = LostCommissionReply(armed)
                        with self.assertRaises(PhysicalAddressUncertain) as error: SerialCommissioning(wrapper).apply(plan)
                        self.assertEqual(wrapper.calls, 1); self.assertFalse(client.connected)
                        client.connect()
                        recovery = SerialCommissionPlan.from_dict(json.loads(json.dumps(error.exception.details["plan"])))
                        result = manager.verify(recovery)
                        report["uncertainty"] = error.exception.details
                    else: result = manager.apply(plan)
                    if not raw_scan_fault:
                        self.assertEqual(result["outcome"], "confirmed_moved")
                        self.assertEqual(fault.triggered, 0, "Scalar SET must avoid the native UNRAVEL serial-scan fallback")
                    destination = 2 if raw_scan_fault else 6
                    expected_command = "NET UNRAVELUNIT " + network + " 255 MATCHDB" if raw_scan_fault else "SET " + network + "/p/255 Address 6"
                    self.assertEqual(fault.operations, [expected_command])
                    self.assertEqual(xml_text(db.get(network, xml=True)), before_xml)
                    expected = deepcopy(before_state)
                    unit = next(u for u in expected["units"] if u["address"] == 255)
                    unit["address"] = destination; unit["parameters"]["32"] = f"{destination:02x}"; expected["units"].sort(key=lambda u: u["address"])
                    expected["readdress_challenges"] = {str(destination): 90}; expected["readdress_empty_addresses"] = [6, 255] if raw_scan_fault else [255]
                    self.assertEqual(sim.snapshot(), expected)
                    self.assertEqual(PCISimulator(profile="synthetic", state_path=state).snapshot(), expected)
                    receives = [bytes.fromhex(r["hex"]) for r in sim.wire_log[start:] if r["direction"] == "rx"]
                    stores = [r for r in receives if b"A3204E" in r.upper()]
                    self.assertEqual(len(stores), 1)
                    self.assertIn(f"A3204E{destination:02X}5A".encode(), stores[0].upper())
                    self.assertFalse(any(b"0F0018B10616" in r.upper() for r in receives))
                    self.assertFalse([r for r in sim.wire_log if r.get("reason")])
                    report.update(passed=True, result=result, plan=plan.as_dict(), mutation_commands=fault.operations,
                                  internal_serial_fault_count=fault.triggered, before_database_xml=before_xml,
                                  after_database_xml=xml_text(db.get(network, xml=True)), wire=list(sim.wire_log))
                finally:
                    errors = []
                    if created:
                        for command in ("NET CLOSE " + network, "PROJECT CLOSE " + project, "PROJECT DELETE " + project):
                            try:
                                if not client.connected: client.connect()
                                client.command(command)
                            except Exception as error: errors.append(str(error))
                    report["cleanup_errors"] = errors
                    if report["passed"]: self.assertEqual(errors, [])
        if path := os.environ.get("CBUS_SERIAL_COMMISSION_REPORT"):
            destination = Path(path); destination.parent.mkdir(parents=True, exist_ok=True)
            if lost: destination = destination.with_name(destination.stem + "-lost" + destination.suffix)
            if raw_scan_fault: destination = destination.with_name(destination.stem + "-raw-scan" + destination.suffix)
            destination.write_text(json.dumps(report, indent=2) + "\n")

    def test_native_commissioning_preserves_database_and_persists_fixture(self): self._lifecycle()
    def test_native_lost_reply_recovery_does_not_replay(self): self._lifecycle(lost=True)
    def test_raw_unravel_internal_scan_fault_can_choose_another_address(self): self._lifecycle(raw_scan_fault=True)


if __name__ == "__main__": unittest.main()
