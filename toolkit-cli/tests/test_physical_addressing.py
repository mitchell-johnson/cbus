"""Physical identity guards, one-write failures and isolated native acceptance."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

from cbus_toolkit.addressing import _network_canonical
from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.networks import NativeNetworks
from cbus_toolkit.physical_addressing import PhysicalAddressing, PhysicalAddressPlan, PhysicalAddressUncertain
from cbus_toolkit.programming import xml_text
from cbus_toolkit.serials import NativeSerials, SerialTransportError
from cbus_toolkit.simulator import PCISimulator, UnitState, synthetic_units
from tests.test_serials import FakeClient, NET, reply
from tests.test_simulator_addressing import fixture


class PhysicalClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.network.update(Retries="0", NetworkType="Wired", Name="254", Type="Cni", InterfaceAddress="fixture:10001")
        self.database = '<Network><Address>254</Address><Interface><InterfaceType>Cni</InterfaceType><InterfaceAddress>fixture:10001</InterfaceAddress></Interface></Network>'
        self.mode = None
        self.connected = True
        self.pingu_calls = 0
        self.pingu_fault_at = None
        self.pingu_reply = None

    def command(self, command):
        if command == "NET PINGU " + NET:
            self.commands.append(command)
            self.pingu_calls += 1
            if self.pingu_fault_at is None or self.pingu_fault_at == self.pingu_calls:
                if isinstance(self.pingu_reply, Exception): raise self.pingu_reply
                if self.pingu_reply is not None: return self.pingu_reply
            return reply("302-Units=" + ", ".join(map(str, sorted(self.units))), "200 OK.")
        if command.startswith("DBGETXML "):
            self.commands.append(command)
            return reply("343-Begin XML snippet", "347-" + self.database, "344 End XML snippet")
        if command.startswith("SET "):
            self.commands.append(command)
            _, source, field, value = command.split()
            if field != "Address": raise AssertionError("Unexpected runtime setting mutation")
            old, new = int(source.rsplit("/", 1)[1]), int(value)
            if self.mode != "unchanged":
                self.units[new] = self.units.pop(old); self.units[new]["Address"] = str(new)
                self.network["Units"] = ",".join(map(str, sorted(self.units)))
            if self.mode == "serial": self.units[new]["SerialNumber"] = "123.456"
            if self.mode == "database": self.database = self.database.replace("</Network>", "<Other>Changed</Other></Network>")
            if self.mode == "disconnect":
                self.connected = False
                raise OSError("Lost write response")
            return reply("200 OK: " + NET + "/p/" + str(new))
        return super().command(command)


class PhysicalAddressingTests(unittest.TestCase):
    def setUp(self):
        self.client = PhysicalClient(); self.manager = PhysicalAddressing(self.client)
        self.source = NET + "/p/4"

    def test_plan_apply_physical_identity_and_database_guards(self):
        plan = self.manager.plan(self.source, 6, expected_serial="00101136.1558")
        self.assertFalse(any(c.startswith("SET ") for c in self.client.commands))
        result = self.manager.apply(plan)
        self.assertEqual(result["outcome"], "confirmed_moved")
        self.assertTrue(result["verification"]["source_absent"])
        self.assertTrue(result["verification"]["serial_confirmed"])
        self.assertEqual([c for c in self.client.commands if c.startswith("SET ")], ["SET " + self.source + " Address 6"])
        write = self.client.commands.index("SET " + self.source + " Address 6")
        self.assertEqual(self.client.commands[write-1], "NET PINGU " + NET)
        self.assertEqual(result["pre_write_mmi"]["addresses"], [4, 5, 16])
        self.assertEqual(result["verification"]["mmi"]["addresses"], [5, 6, 16])
        json.dumps(result)

    def test_native_retries_busy_closed_and_wireless_reject_before_probe(self):
        for field, value in (("Retries", "2"), ("SyncState", "busy"), ("InterfaceState", "closed"),
                             ("AutoUnravel", "yes"), ("AutoUpdate", "yes"), ("NetworkType", "Wireless")):
            with self.subTest(field=field):
                client = PhysicalClient(); client.network[field] = value
                with self.assertRaisesRegex(ValueError, field):
                    PhysicalAddressing(client).plan(self.source, 6, expected_serial="101136.1558")
                self.assertFalse(any(c.startswith(("SET ", "NET SYNC")) for c in client.commands))

    def test_invalid_boundaries_expected_serial_occupied_type_and_endpoint(self):
        for new in (0, 255, 256, 4, True, "6"):
            with self.subTest(new=new), self.assertRaises(ValueError):
                self.manager.plan(self.source, new, expected_serial="101136.1558")
        for serial in ("0.0", "1048575.4095", "bad", "123.456"):
            with self.subTest(serial=serial), self.assertRaises(ValueError): self.manager.plan(self.source, 6, expected_serial=serial)
        with self.assertRaisesRegex(ValueError, "occupied"): self.manager.plan(self.source, 5, expected_serial="101136.1558")
        with self.assertRaisesRegex(ValueError, "verified only"): self.manager.plan(NET + "/p/5", 6, expected_serial="101183.1666")
        self.client.network["InterfaceAddress"] = "another:10001"
        with self.assertRaisesRegex(ValueError, "definitions differ"): self.manager.plan(self.source, 6, expected_serial="101136.1558")

    def test_stale_forged_plan_never_writes(self):
        plan = self.manager.plan(self.source, 6, expected_serial="101136.1558")
        with self.assertRaises(ValueError): self.manager.apply(replace(plan, database_hash="changed"))
        self.client.units[4]["SerialNumber"] = "123.456"
        with self.assertRaises(ValueError): self.manager.apply(plan)
        self.assertFalse(any(c.startswith("SET ") for c in self.client.commands))

    def test_lost_reply_is_uncertain_without_followup_or_replay(self):
        plan = self.manager.plan(self.source, 6, expected_serial="101136.1558")
        self.client.mode = "disconnect"
        with self.assertRaises(PhysicalAddressUncertain) as error: self.manager.apply(plan)
        self.assertEqual(error.exception.details["outcome"], "uncertain")
        self.assertTrue(error.exception.details["write_attempted"])
        self.assertEqual(self.client.commands[-1], "SET " + self.source + " Address 6")
        self.assertEqual(sum(c.startswith("SET ") for c in self.client.commands), 1)
        self.assertIn(6, self.client.units)
        self.assertEqual(error.exception.details["cause"], "Lost write response")
        self.assertNotIn("error", error.exception.details)

    def test_recovery_document_roundtrip_is_read_only_for_both_known_outcomes(self):
        plan = self.manager.plan(self.source, 6, expected_serial="101136.1558")
        recovered = PhysicalAddressPlan.from_dict(json.loads(json.dumps(plan.as_dict())))
        self.assertEqual(recovered, plan)
        self.assertEqual(self.manager.verify(recovered)["outcome"], "confirmed_not_moved")
        self.manager.apply(plan)
        start = len(self.client.commands)
        self.assertEqual(self.manager.verify(recovered)["outcome"], "confirmed_moved")
        self.assertFalse(any(c.startswith("SET ") for c in self.client.commands[start:]))
        self.client.network["InterfaceAddress"] = "changed:10001"
        with self.assertRaisesRegex(ValueError, "runtime settings"):
            self.manager.verify(recovered)

    def test_recovery_document_rejects_incomplete_malformed_or_inconsistent_baselines(self):
        plan = self.manager.plan(self.source, 6, expected_serial="101136.1558")
        source = plan.as_dict()
        mutations = (
            lambda d: d.pop("database_xml"),
            lambda d: d.update(unexpected=True),
            lambda d: d.update(format="unknown"),
            lambda d: d.update(native_retries=False),
            lambda d: d.update(database_hash="0" * 64),
            lambda d: d.update(database_xml='<!DOCTYPE Network [<!ENTITY e "x">]><Network>&e;</Network>'),
            lambda d: d.update(destination=d["source"]),
            lambda d: d.update(destination="//OTHER/254/p/6"),
            lambda d: d.update(serial="0.0"),
            lambda d: d.update(unit_type="KEYGL5"),
            lambda d: d.update(inventory=[]),
            lambda d: d["inventory"][0].__setitem__(0, True),
            lambda d: d["inventory"][0].__setitem__(3, "123.456"),
            lambda d: d["inventory"].append(d["inventory"][0]),
            lambda d: d["runtime"].update(Retries="2"),
            lambda d: d["runtime"].update(InterfaceAddress="different:10001"),
        )
        start = len(self.client.commands)
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                document = deepcopy(source); mutation(document)
                with self.assertRaises(ValueError): PhysicalAddressPlan.from_dict(document)
        self.assertEqual(self.client.commands[start:], [])

    def test_post_write_identity_absence_and_database_failures_are_uncertain(self):
        for mode in ("unchanged", "serial", "database"):
            with self.subTest(mode=mode):
                client = PhysicalClient(); client.mode = mode; manager = PhysicalAddressing(client)
                with self.assertRaises(PhysicalAddressUncertain) as error:
                    manager.readdress(self.source, 6, expected_serial="101136.1558")
                self.assertEqual(sum(c.startswith("SET ") for c in client.commands), 1)
                self.assertFalse(error.exception.details["verification"]["outcome"] == "confirmed_moved")

    def test_pingu_incomplete_empty_malformed_or_changed_inventory_blocks_before_write(self):
        failures = (reply("200 OK."), reply("302-Units=null", "200 OK."),
            reply("302-Units=", "200 OK."), reply("302-Units=4, 5, 16", "600 Busy"),
            reply("302-Units=4, 5, 16", "120-extra", "200 OK."),
            reply("302-Units=4, 4, 16", "200 OK."), reply("302-Units=4, 5, 256", "200 OK."),
            reply("302-Units=04, 5, 16", "200 OK."), reply("302-Units=16, 5, 4", "200 OK."),
            reply("302-Units=4,5,16", "200 OK."), reply("302-Units=4, 16", "200 OK."),
            reply("302-Units=5, 16", "200 OK."), reply("302-Units=4, 5, 6, 16", "200 OK."),
            CGateError(reply("408 Operation failed: net pingu failed: Unexpected block offset")),
            OSError("Dropped PINGU response"))
        for failure in failures:
            with self.subTest(failure=failure):
                client=PhysicalClient(); client.pingu_reply=failure
                with self.assertRaises((ValueError, CGateError, SerialTransportError)):
                    PhysicalAddressing(client).readdress(self.source, 6, expected_serial="101136.1558")
                self.assertFalse(any(c.startswith("SET ") for c in client.commands))
                self.assertEqual(client.commands[-1], "NET PINGU " + NET)

    def test_fresh_pingu_immediately_before_write_catches_changed_destination(self):
        plan=self.manager.plan(self.source, 6, expected_serial="101136.1558")
        self.client.pingu_fault_at=3  # initial plan, fresh plan, then immediate guard
        self.client.pingu_reply=reply("302-Units=4, 5, 6, 16", "200 OK.")
        with self.assertRaisesRegex(ValueError, "occupied"):
            self.manager.apply(plan)
        self.assertFalse(any(c.startswith("SET ") for c in self.client.commands))

    def test_post_write_pingu_failure_retains_uncertain_outcome_without_retry(self):
        for failure in (reply("302-Units=5, 6", "200 OK."), OSError("Lost verification PINGU"),
                        CGateError(reply("408 Operation failed: net pingu failed: Unexpected block offset"))):
            with self.subTest(failure=failure):
                client=PhysicalClient(); manager=PhysicalAddressing(client)
                client.pingu_fault_at=4; client.pingu_reply=failure
                with self.assertRaises(PhysicalAddressUncertain) as error:
                    manager.readdress(self.source, 6, expected_serial="101136.1558")
                self.assertEqual(error.exception.details["verification"]["outcome"], "uncertain")
                self.assertIsNone(error.exception.details["verification"]["mmi"])
                self.assertIn("verification_error", error.exception.details["verification"])
                self.assertEqual(sum(c.startswith("SET ") for c in client.commands), 1)
                self.assertEqual(client.commands[-1], "NET PINGU " + NET)

    def test_interruption_preserves_original_exception_and_recovery_without_followup(self):
        for kind in (KeyboardInterrupt, SystemExit):
            for phase in ("write", "verification"):
                with self.subTest(kind=kind, phase=phase):
                    interruption=kind("stop")
                    class InterruptingClient(PhysicalClient):
                        wrote=False
                        def command(self, command):
                            response=super().command(command)
                            if command.startswith("SET "):
                                self.wrote=True
                                if phase=="write":raise interruption
                            if phase=="verification" and self.wrote and command=="NET PINGU "+NET:
                                raise interruption
                            return response
                    client=InterruptingClient();manager=PhysicalAddressing(client)
                    with self.assertRaises(kind) as caught:
                        manager.readdress(self.source,6,expected_serial="101136.1558")
                    self.assertIs(caught.exception,interruption)
                    self.assertIs(manager.last_uncertain,interruption.physical_address_evidence)
                    evidence=manager.last_uncertain
                    self.assertTrue(evidence["write_attempted"])
                    self.assertEqual(evidence["outcome"],"uncertain")
                    self.assertEqual(evidence["interruption_type"],kind.__name__)
                    self.assertEqual(evidence["automatic_write_retries"],0)
                    PhysicalAddressPlan.from_dict(evidence["plan"])
                    json.dumps(evidence)
                    self.assertEqual(sum(command.startswith("SET ") for command in client.commands),1)
                    expected="SET "+self.source+" Address 6" if phase=="write" else "NET PINGU "+NET
                    self.assertEqual(client.commands[-1],expected)

    def test_preflight_interruption_never_marks_a_write_attempted(self):
        interruption=KeyboardInterrupt("preflight")
        class InterruptedPreflight(PhysicalClient):
            def command(self, command):
                response=super().command(command)
                if command=="NET PINGU "+NET:raise interruption
                return response
        client=InterruptedPreflight();manager=PhysicalAddressing(client)
        with self.assertRaises(KeyboardInterrupt) as caught:
            manager.readdress(self.source,6,expected_serial="101136.1558")
        self.assertIs(caught.exception,interruption)
        self.assertIsNone(manager.last_uncertain)
        self.assertFalse(hasattr(interruption,"physical_address_evidence"))
        self.assertFalse(any(command.startswith("SET ") for command in client.commands))


class LostPhysicalReply:
    def __init__(self, client): self.client, self.writes = client, 0
    @property
    def connected(self): return self.client.connected
    def command(self, command):
        result = self.client.command(command)
        if command.startswith("SET ") and " Address " in command:
            self.writes += 1; self.client.close()
            raise OSError("Injected transport loss after native physical mutation")
        return result


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for isolated native physical addressing")
class NativePhysicalAddressingTests(unittest.TestCase):
    def test_hidden_occupied_target_is_rejected_by_independent_pingu_without_address_write(self):
        class MissingMiddleMMI(PCISimulator):
            armed=False
            def _install_mmi(self, application=255):
                full=super()._install_mmi(application)
                if not self.armed or application != 255:return full
                # Valid checksums and three frames, but no88..175 coverage.
                # Original dw/dx treats that missing range as zero; dk/dn
                # rejects it before the scalar address operation is enabled.
                first=b"D8FF00000A00000100000000000000000000000000000000001E\r\n"
                last=b"D6FFB000000000000000000000000000000000000000007B\r\n"
                return first+first+last

        class RecordingClient:
            def __init__(self, client): self.client,self.commands=client,[]
            def command(self, command):
                self.commands.append(command)
                return self.client.command(command)

        units=synthetic_units();units[0].parameters[32]=b"\x04"
        hidden=UnitState(100,units[0].attributes,units[0].parameters,{},2)
        hidden.parameters[32]=b"\x64"
        hidden.attributes[4]=bytes.fromhex("38FFFFFFFF18B10617A20005")
        sim=MissingMiddleMMI(units,profile="synthetic",readdress_challenges={4:0x5A},response_delay=.01)
        project="MC"+uuid4().hex[:6].upper();network="//"+project+"/254"
        report={"passed":False,"scope":"MMI-hidden occupied target100; read-only native guard regression"}
        try:
            with sim.running("0.0.0.0",0) as (_,port), CGateClient(
                    os.environ["CBUS_CGATE_TEST_HOST"],int(os.environ.get("CBUS_CGATE_TEST_PORT","20023")),timeout=40) as raw:
                client=RecordingClient(raw);projects=NativeProjects(client);db=NativeDatabase(client);nets=NativeNetworks(client)
                created=False
                try:
                    projects.operation("new",project);created=True
                    db.create_network(project,254,"MMI_Guard","Cni",
                        os.environ.get("CBUS_CGATE_SIMULATOR_HOST","host.docker.internal")+":"+str(port))
                    projects.operation("save",project)
                    before_xml=xml_text(db.get(network,xml=True))
                    nets.open(network);nets.wait_ready(network,timeout=30)
                    self.assertEqual(client.command("SET "+network+" Retries 0").code,200)
                    self.assertEqual(client.command("GET "+network+" Retries").lines,("300 "+network+": Retries=0",))
                    # Explicit test-only topology addition after the initial
                    # healthy scan: target100 is physically present but has
                    # never entered the native cache. No fixture state changes
                    # occur from this baseline through the failed move attempt.
                    with sim._lock:
                        sim.units[100]=hidden
                        sim.armed=True
                    before=sim.snapshot()
                    start=len(sim.wire_log)
                    misleading=client.command("NET CHECKUNIT "+network+" 4,100")
                    self.assertEqual(misleading.lines,("120-Single unit detected at address: 4","120 No units detected at address: 100"))
                    misleading_wire=list(sim.wire_log[start:])
                    self.assertFalse(any(b"4664002104" in bytes.fromhex(row["hex"]).upper()
                                         for row in misleading_wire if row["direction"]=="rx"))
                    self.assertEqual(client.command("GET "+network+" Units").lines,("300 "+network+": Units=4,5,16",))
                    start=len(sim.wire_log);command_start=len(client.commands)
                    with self.assertRaisesRegex(CGateError,"net pingu failed: Unexpected block offset") as caught:
                        PhysicalAddressing(client).readdress(network+"/p/4",100,expected_serial="101136.1558")
                    commands=client.commands[command_start:]
                    self.assertEqual(commands[-1],"NET PINGU "+network)
                    self.assertFalse(any(command.startswith("SET ") for command in commands))
                    guard_wire=list(sim.wire_log[start:])
                    self.assertFalse(any(b"1120" in bytes.fromhex(row["hex"]).upper()
                        or b"A3204E" in bytes.fromhex(row["hex"]).upper()
                        for row in guard_wire if row["direction"]=="rx"))
                    self.assertEqual(sim.snapshot(),before)
                    self.assertEqual(xml_text(db.get(network,xml=True)),before_xml)
                    self.assertFalse([row for row in sim.wire_log if row.get("reason")])
                    report.update(passed=True,misleading_check_reply=list(misleading.lines),misleading_wire=misleading_wire,
                        guard_reply=list(caught.exception.response.lines),guard_commands=commands,guard_wire=guard_wire,
                        hidden_target={"address":100,"serial":"101136.1559"},
                        database_unchanged=True,fixture_unchanged=True,address_write_attempted=False)
                finally:
                    report["wire"]=list(sim.wire_log)
                    report["cleanup_errors"]=[]
                    if created:
                        for command in ("NET CLOSE "+network,"PROJECT CLOSE "+project,"PROJECT DELETE "+project):
                            try:client.command(command)
                            except Exception as error:report["cleanup_errors"].append(str(error))
                    if report["passed"]:self.assertEqual(report["cleanup_errors"],[])
        finally:
            if destination:=os.environ.get("CBUS_PHYSICAL_MMI_REPORT"):
                Path(destination).write_text(json.dumps(report,indent=2)+"\n")

    def test_native_move_then_lost_reply_observation_and_simulator_restart(self):
        project = "PH" + uuid4().hex[:6].upper(); network = f"//{project}/254"
        host, oracle = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        report = {"scope": "Real C-Gate against explicit synthetic KEYE1; no physical hardware claim", "passed": False}
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory) / "fixture.json"; sim = fixture(state_path=state, response_delay=0.01)
                with CGateClient(host, oracle, timeout=30) as client:
                    projects, database, networks = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
                    created = False
                    try:
                        with sim.running("0.0.0.0", 0) as (_, port):
                            projects.operation("new", project); created = True
                            database.create_network(project, 254, "Physical_Address", "Cni",
                                os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal") + ":" + str(port))
                            # The intended database unit is already at6. This
                            # workflow changes only the observed physical4.
                            database.create_unit(network, 6, "Matched_Target", "KEYE1", "2.5.00", catalog_number="5031NMML")
                            database.set(network + "/p/6/SerialNumber", "101136.1558")
                            projects.operation("save", project)
                            networks.open(network); networks.wait_ready(network, timeout=25)
                            client.command("SET " + network + " Retries 0")
                            manager = PhysicalAddressing(client)
                            before_xml = xml_text(database.get(network, xml=True)); before_state = sim.snapshot()
                            plan = manager.plan(network + "/p/4", 6, expected_serial="101136.1558")
                            start = len(sim.wire_log)
                            result = manager.apply(plan)
                            self.assertEqual(result["outcome"], "confirmed_moved")
                            expected = deepcopy(before_state)
                            unit = next(u for u in expected["units"] if u["address"] == 4)
                            unit["address"] = 6; unit["parameters"]["32"] = "06"
                            expected["units"].sort(key=lambda u: u["address"])
                            expected["readdress_challenges"] = {"6": 0x5A}
                            self.assertEqual(sim.snapshot(), expected)
                            self.assertEqual(_network_canonical(xml_text(database.get(network, xml=True))), _network_canonical(before_xml))
                            wire = [bytes.fromhex(row["hex"]) for row in sim.wire_log[start:] if row["direction"] == "rx"]
                            stores = [raw for raw in wire if b"A3204E06" in raw.upper()]
                            self.assertEqual(len(stores), 1, wire)
                            self.assertIn(b"A3204E065A", stores[0].upper())
                            self.assertFalse([r for r in sim.wire_log if r.get("reason")])
                            # An independently issued move back loses its native
                            # reply after mutation. No automatic replay follows.
                            back = manager.plan(network + "/p/6", 4, expected_serial="101136.1558")
                            lost = LostPhysicalReply(client)
                            with self.assertRaises(PhysicalAddressUncertain) as error: PhysicalAddressing(lost).apply(back)
                            self.assertEqual(lost.writes, 1)
                            self.assertFalse(client.connected)
                            self.assertEqual(error.exception.details["outcome"], "uncertain")
                            client.connect()  # Explicit recovery observation in the test.
                            recovery = PhysicalAddressPlan.from_dict(json.loads(json.dumps(error.exception.details["plan"])))
                            self.assertEqual(recovery, back)
                            verified = PhysicalAddressing(client).verify(recovery)
                            self.assertEqual(verified["outcome"], "confirmed_moved")
                            # Leave the fixture at6 for the independent restart.
                            manager.readdress(network + "/p/4", 6, expected_serial="101136.1558")
                            networks.close(network)
                            report.update(result=result, lost_reply=error.exception.details, recovery=verified)
                        restarted = PCISimulator(profile="synthetic", state_path=state, response_delay=0.01)
                        self.assertNotIn(4, restarted.units); self.assertIn(6, restarted.units)
                        with restarted.running("0.0.0.0", port):
                            networks.open(network)
                            deadline = time.monotonic() + 10
                            while NativeSerials(client)._get(network, "InterfaceState") != "running":
                                self.assertLess(time.monotonic(), deadline, "Restarted native interface did not open")
                                time.sleep(0.05)
                            # Reopening an existing model retains its next-sync
                            # schedule. Explicitly observe the restarted bus.
                            self.assertEqual(networks.synchronize(network, fast=True).code, 200)
                            networks.wait_ready(network, timeout=25)
                            inventory = NativeSerials(client).cached(network)
                            self.assertEqual([(u.address, u.serial) for u in inventory.identities if u.unit_type == "KEYE1"], [(6, "101136.1558")])
                            self.assertEqual(_network_canonical(xml_text(database.get(network, xml=True))), _network_canonical(before_xml))
                            report.update(passed=True, restart_inventory=inventory.as_dict(), wire=list(sim.wire_log))
                    finally:
                        if created:
                            errors = []
                            for command in ("NET CLOSE " + network, "PROJECT CLOSE " + project, "PROJECT DELETE " + project):
                                try:
                                    if not client.connected: client.connect()
                                    client.command(command)
                                except Exception as error: errors.append(str(error))
                            report["cleanup_errors"] = errors
                            if report["passed"]: self.assertEqual(errors, [])
        finally:
            if os.environ.get("CBUS_PHYSICAL_ADDRESS_REPORT"):
                Path(os.environ["CBUS_PHYSICAL_ADDRESS_REPORT"]).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__": unittest.main()
