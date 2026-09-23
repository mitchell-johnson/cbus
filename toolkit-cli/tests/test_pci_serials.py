"""Independent literal peers for bounded read-only serial collection."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from cbus_toolkit.pci_serials import PCISerialCollector
from tests.test_simulator_duplicates import SERIAL_A, SERIAL_B, fixture


BARE_PCI = b"8D04FFFFFF000018A664A3B10005F7\r\n"
OTHER_UNIT = b"860410008D0438FFFFFFFF18B10616A2000515\r\n"
WRONG_DESTINATION = b"86FF11008D0438FFFFFFFF18B10616A2000519\r\n"
WRONG_ROUTE = b"86FF1001008D0438FFFFFFFF18B10616A2000519\r\n"
BARE_REMOTE = b"8D0438FFFFFFFF18B10616A20005AF\r\n"
UNKNOWN_ZERO = b"86FF10008D0438FFFFFFFF00000000A20005FF\r\n"
UNKNOWN_ONES = b"86FF10008D0438FFFFFFFFFFFFFFFFA2000503\r\n"
SHORT = b"86FF10008C0438FFFFFFFF18B10616A20020\r\n"
CONFLICT = b"86FF10008D0439FFFFFFFF18B10616A2000519\r\n"


@contextmanager
def peer(handler):
    """A literal TCP peer independent of every production codec/simulator."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0)); listener.listen(1); listener.settimeout(2)
    state = {"request": b"", "extra": b"", "closed": False, "errors": []}
    def serve():
        try:
            with listener.accept()[0] as connection:
                connection.settimeout(2)
                while not state["request"].endswith(b"\r"):
                    chunk = connection.recv(512)
                    if not chunk: return
                    state["request"] += chunk
                handler(connection)
                while True:
                    chunk = connection.recv(512)
                    if not chunk: state["closed"] = True; break
                    state["extra"] += chunk
        except (BrokenPipeError, ConnectionResetError): state["closed"] = True
        except Exception as error: state["errors"].append(repr(error))
    thread = threading.Thread(target=serve, daemon=True); thread.start()
    try: yield listener.getsockname(), state
    finally:
        thread.join(3); listener.close()
        if thread.is_alive(): raise AssertionError("Literal peer failed to stop")
        if state["errors"]: raise AssertionError(state["errors"])


def collector(endpoint, **options):
    settings = dict(local_unit=16, quiet_period=.04, overall_timeout=.5, confirmation_timeout=.2)
    settings.update(options)
    return PCISerialCollector(*endpoint, **settings)


class PCISerialCollectorTests(unittest.TestCase):
    def observe(self, data, *, address=255, **settings):
        with peer(lambda connection: connection.sendall(data)) as (endpoint, state):
            result = collector(endpoint, **settings).collect_serials(address)
        self.assertTrue(state["closed"]); self.assertEqual(state["extra"], b"")
        return result, state

    def test_two_literals_complete_one_window_without_inventing_unique_identity(self):
        result, state = self.observe(b"g." + SERIAL_A + SERIAL_B)
        self.assertEqual(state["request"], b"\\46FF002104g\r")
        self.assertTrue(result.complete); self.assertEqual(result.status, "duplicate_address")
        self.assertEqual(result.serials, ("101136.1558", "101136.1559"))
        self.assertEqual(len(result.replies), 2); self.assertEqual(result.repeated_responses, 0)
        self.assertEqual(result.termination, "quiet"); self.assertGreaterEqual(result.elapsed, .04)
        document = json.loads(json.dumps(result.as_dict()))
        self.assertFalse(document["physical_addresses_changed"])
        self.assertFalse(document["timing"]["vendor_quiet_period"])
        self.assertEqual(document["received_hex"], (b"g." + SERIAL_A + SERIAL_B).hex())
        self.assertEqual(document["status"], "duplicate_address")

    def test_splitting_confirmation_and_frames_and_delaying_second_restarts_quiet(self):
        def send(connection):
            for chunk in (b"g", b".", SERIAL_A[:7], SERIAL_A[7:-1], SERIAL_A[-1:]):
                connection.sendall(chunk); time.sleep(.002)
            time.sleep(.06)
            for chunk in (SERIAL_B[:3], SERIAL_B[3:16], SERIAL_B[16:]): connection.sendall(chunk)
        with peer(send) as (endpoint, state):
            result = collector(endpoint, quiet_period=.12, overall_timeout=1).collect_serials(255)
        self.assertTrue(result.complete); self.assertEqual(result.status, "duplicate_address")
        self.assertGreaterEqual(result.elapsed, .17)
        self.assertEqual(result.replies[1].raw, SERIAL_B.rstrip(b"\r\n"))
        self.assertEqual(state["extra"], b"")

    def test_repeated_identical_serial_is_retained_and_deduplicated(self):
        result, _ = self.observe(b"g." + SERIAL_A + SERIAL_A + SERIAL_B)
        self.assertTrue(result.complete); self.assertEqual(len(result.replies), 3)
        self.assertEqual(result.repeated_responses, 1)
        self.assertEqual(result.serials, ("101136.1558", "101136.1559"))

    def test_unknown_malformed_or_conflicting_serials_are_incomplete_with_raw_evidence(self):
        for data, termination in ((UNKNOWN_ZERO, "unknown_serial"), (UNKNOWN_ONES, "unknown_serial"),
                                  (SHORT, "invalid_reply"), (CONFLICT, "conflicting_serial")):
            with self.subTest(data=data):
                result, _ = self.observe(b"g." + SERIAL_A + data)
                self.assertFalse(result.complete); self.assertEqual(result.termination, termination)
                self.assertEqual(result.status, "incomplete"); self.assertTrue(result.errors)
                self.assertEqual(result.replies[-1].raw, data.rstrip(b"\r\n"))
                self.assertIn("101136.1558", result.serials)

    def test_bad_later_checksum_preserves_earlier_reply_from_same_socket_read(self):
        result, _ = self.observe(b"g." + SERIAL_A + SERIAL_B.replace(b"0519", b"0518"))
        self.assertEqual(result.termination, "framing_error")
        self.assertEqual(result.serials, ("101136.1558",)); self.assertFalse(result.complete)
        self.assertIn("checksum", result.errors[0])

    def test_wrong_destination_route_or_bare_remote_cannot_satisfy_collection(self):
        for frame in (WRONG_DESTINATION, WRONG_ROUTE, BARE_REMOTE):
            with self.subTest(frame=frame):
                result, _ = self.observe(b"g." + frame)
                self.assertEqual(result.termination, "correlation_error")
                self.assertFalse(result.complete); self.assertEqual(result.serials, ())
                self.assertEqual(len(result.unrelated), 1)

    def test_only_explicit_local_address_can_use_bare_pci_serial(self):
        result, state = self.observe(b"g." + BARE_PCI, address=16)
        self.assertTrue(result.complete); self.assertEqual(result.status, "single")
        self.assertEqual(result.serials, ("100966.1187",))
        self.assertIsNone(result.replies[0].source); self.assertIsNone(result.replies[0].destination)
        self.assertEqual(state["request"], b"\\4610002104g\r")

    def test_other_source_is_retained_without_resetting_quiet_or_fabricating_identity(self):
        result, _ = self.observe(b"g.+" + OTHER_UNIT + SERIAL_A)
        self.assertTrue(result.complete); self.assertEqual(result.status, "single")
        self.assertEqual(result.serials, ("101136.1558",)); self.assertEqual(len(result.unrelated), 2)
        result, _ = self.observe(b"g." + OTHER_UNIT)
        self.assertTrue(result.complete); self.assertEqual(result.status, "absent")
        self.assertEqual(result.serials, ())

    def test_missing_rejected_foreign_duplicate_and_pre_reply_confirmations_are_incomplete(self):
        for data, termination in ((b"", "confirmation_timeout"), (b"g#", "rejected"), (b"g%", "rejected"),
                                  (b"!", "rejected"), (b"h.", "correlation_error"),
                                  (b"g.g.", "correlation_error"), (SERIAL_A + b"g.", "correlation_error")):
            with self.subTest(data=data):
                result, _ = self.observe(data, confirmation_timeout=.03)
                self.assertFalse(result.complete); self.assertEqual(result.termination, termination)
        result, _ = self.observe(b"g")
        self.assertEqual(result.termination, "truncated_frame")

    def test_saturation_and_byte_limits_never_claim_collection_complete(self):
        result, _ = self.observe(b"g." + SERIAL_A + SERIAL_A, max_frames=2)
        self.assertEqual(result.termination, "frame_limit"); self.assertEqual(result.repeated_responses, 1)
        self.assertFalse(result.complete)
        result, _ = self.observe(b"g.++", max_unrelated=2)
        self.assertEqual(result.termination, "unrelated_limit"); self.assertFalse(result.complete)
        result, _ = self.observe(b"g." + SERIAL_A + SERIAL_B, max_bytes=45)
        self.assertEqual(result.termination, "byte_limit")
        self.assertEqual(len(result.received), 45); self.assertEqual(result.bytes_received, 46)

    def test_continuing_matching_replies_hit_overall_limit_without_replay(self):
        def send(connection):
            connection.sendall(b"g.")
            for _ in range(9): connection.sendall(SERIAL_A); time.sleep(.04)
        with peer(send) as (endpoint, state):
            result = collector(endpoint, quiet_period=.1, overall_timeout=.24, max_frames=30).collect_serials(255)
        # A readable socket can wake at the deadline, before the timeout branch.
        # Both paths reject the unfinished window and must send no further request.
        self.assertIn(result.termination, ("overall_timeout", "late_data"))
        self.assertFalse(result.complete)
        self.assertGreaterEqual(result.elapsed, .24)
        self.assertGreater(len(result.replies), 1)
        self.assertEqual(state["request"], b"\\46FF002104g\r")
        self.assertEqual(state["extra"], b"")
        self.assertTrue(result.connection_closed)

    def test_fragment_before_deadline_and_late_tail_do_not_extend_quiet(self):
        def send(connection):
            connection.sendall(b"g." + SERIAL_A)
            time.sleep(.025); connection.sendall(SERIAL_B[:12])
            time.sleep(.1); connection.sendall(SERIAL_B[12:])
        with peer(send) as (endpoint, state):
            subject = collector(endpoint, quiet_period=.06)
            result = subject.collect_serials(255)
            with self.assertRaisesRegex(RuntimeError, "one-shot"): subject.collect_serials(255)
        self.assertEqual(result.termination, "truncated_frame")
        self.assertEqual(result.serials, ("101136.1558",)); self.assertFalse(result.complete)
        self.assertTrue(state["closed"]); self.assertEqual(state["extra"], b"")

    def test_reply_after_completed_window_cannot_be_reused_for_another_request(self):
        def send(connection):
            connection.sendall(b"g.")
            time.sleep(.1); connection.sendall(SERIAL_B)
        with peer(send) as (endpoint, state):
            subject = collector(endpoint, quiet_period=.03)
            result = subject.collect_serials(255)
            with self.assertRaises(RuntimeError): subject.collect_serials(255)
        self.assertTrue(result.complete); self.assertEqual(result.status, "absent")
        self.assertTrue(state["closed"]); self.assertEqual(state["extra"], b"")

    def test_eof_after_reply_or_partial_frame_is_incomplete(self):
        for data, termination in ((b"g." + SERIAL_A, "disconnected"), (b"g." + SERIAL_A[:8], "truncated_frame")):
            with self.subTest(data=data):
                def send(connection):
                    connection.sendall(data); connection.shutdown(socket.SHUT_WR)
                with peer(send) as (endpoint, _): result = collector(endpoint).collect_serials(255)
                self.assertEqual(result.termination, termination); self.assertFalse(result.complete)

    def test_command_checksum_is_independent_literal_and_simulator_accepts_it(self):
        result, state = self.observe(b"g." + SERIAL_A, command_checksum=True)
        self.assertTrue(result.complete); self.assertEqual(state["request"], b"\\46FF00210496g\r")
        sim = fixture(command_checksum=True, fragment_sizes=(1, 2, 5))
        before = sim.snapshot()
        with sim.running() as endpoint:
            result = collector(endpoint, command_checksum=True).collect_serials(255)
        self.assertTrue(result.complete); self.assertEqual(result.status, "duplicate_address")
        self.assertEqual(before, sim.snapshot()); self.assertFalse([r for r in sim.wire_log if r.get("reason")])

    def test_connection_failure_is_incomplete_and_invalid_inputs_never_connect(self):
        with patch.object(PCISerialCollector, "_make_socket", side_effect=OSError("offline")) as connect:
            subject = PCISerialCollector("127.0.0.1", local_unit=16)
            result = subject.collect_serials(255)
            self.assertEqual(result.termination, "connection_error"); self.assertEqual(result.request, b"")
            self.assertFalse(result.complete)
            with self.assertRaises(RuntimeError): subject.collect_serials(255)
            self.assertEqual(connect.call_count, 1)
        for settings in ({"quiet_period":0},{"quiet_period":True},{"overall_timeout":float("nan")},
                         {"overall_timeout":2},{"confirmation_timeout":11},{"max_frames":0},
                         {"max_unrelated":True},{"max_bytes":1048577},{"command_checksum":1},
                         {"local_unit":True},{"local_unit":256}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                PCISerialCollector("127.0.0.1", **(dict(local_unit=16) | settings))
        with patch.object(PCISerialCollector, "_make_socket") as connect:
            subject = PCISerialCollector("127.0.0.1", local_unit=16)
            for address in (-1,256,True,"255"):
                with self.assertRaises(ValueError): subject.collect_serials(address)
            connect.assert_not_called()
        self.assertFalse(any(hasattr(subject, name) for name in ("write","readdress","send_raw","command")))

    def test_hostnames_do_not_enter_unbounded_resolution_and_close_failure_preserves_evidence(self):
        with patch.object(PCISerialCollector, "_make_socket") as create:
            for host in ("localhost", "example.test", "127.0.0.1\n", "fe80::1%en0", ""):
                with self.subTest(host=host), self.assertRaises(ValueError): PCISerialCollector(host, local_unit=16)
            create.assert_not_called()

        class CloseFailure:
            def __init__(self, stream): self.stream = stream
            def __getattr__(self, name): return getattr(self.stream, name)
            def close(self):
                self.stream.close()
                raise OSError("Injected close failure")

        class Subject(PCISerialCollector):
            def _make_socket(self): return CloseFailure(super()._make_socket())

        for data, expected in ((b"g." + SERIAL_A, "close_error"), (b"g#", "rejected")):
            with self.subTest(data=data), peer(lambda stream: stream.sendall(data)) as (endpoint, _):
                result = Subject(*endpoint, local_unit=16, quiet_period=.03).collect_serials(255)
            self.assertEqual(result.termination, expected)
            self.assertFalse(result.complete); self.assertFalse(result.connection_closed)
            self.assertIn("Injected close failure", result.errors[-1])
            if expected == "close_error": self.assertEqual(result.serials, ("101136.1558",))


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "Set CBUS_CGATE_TEST_HOST for native collector comparison")
class NativePCISerialCollectorTests(unittest.TestCase):
    def test_native_ct_and_direct_collector_observe_same_two_fixture_serials_without_writes(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.networks import NativeNetworks
        from cbus_toolkit.programming import xml_text

        project = "SC" + uuid4().hex[:6].upper(); network = "//" + project + "/254"
        sim = fixture(response_delay=.01); before = sim.snapshot()
        report = {"passed":False,"scope":"Direct IDENTIFY4 collector and original native cT against explicit duplicate fixture"}
        with sim.running("0.0.0.0", 0) as (_, fixture_port):
            observation = PCISerialCollector("127.0.0.1", fixture_port, local_unit=16).collect_serials(255)
            self.assertTrue(observation.complete); self.assertEqual(observation.status, "duplicate_address")
            self.assertEqual(observation.serials, ("101136.1558","101136.1559"))
            self.assertGreaterEqual(observation.elapsed, 2.0)
            direct_wire = list(sim.wire_log)
            self.assertEqual([bytes.fromhex(r["hex"]) for r in direct_wire if r["direction"]=="rx"], [b"\\46FF002104g\r"])
            with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT","20023")), timeout=45) as client:
                projects, db, networks = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
                created=False
                try:
                    projects.operation("new",project); created=True
                    db.create_network(project,254,"Serial_Collector","Cni",
                        os.environ.get("CBUS_CGATE_SIMULATOR_HOST","host.docker.internal")+":"+str(fixture_port))
                    projects.operation("save",project)
                    xml_before=xml_text(db.get(network,xml=True))
                    for name,value in (("AutoUnravel","no"),("AutoUpdate","no"),("Retries","0")):
                        self.assertEqual(client.command("SET "+network+" "+name+" "+value).code,200)
                    networks.open(network)
                    deadline=time.monotonic()+25
                    while time.monotonic()<deadline:
                        if any("InterfaceState=running" in line for line in client.command("GET "+network+" InterfaceState").lines):break
                        time.sleep(.1)
                    else:self.fail("Native interface did not start")
                    self.assertEqual(networks.synchronize(network,fast=True).code,200)
                    networks.wait_ready(network, timeout=30)
                    # Startup reloads native settings; enforce and observe the
                    # requested value after the interface has become ready.
                    self.assertEqual(client.command("SET "+network+" Retries 0").code,200)
                    retries=client.command("GET "+network+" Retries")
                    self.assertEqual(retries.lines,("300 "+network+": Retries=0",))
                    start=len(sim.wire_log)
                    native=client.command("NET CHECKUNIT "+network+" 255")
                    self.assertEqual(native.lines,("120 Duplicate units detected at address: 255",))
                    native_wire=sim.wire_log[start:]
                    self.assertTrue(any(SERIAL_A in bytes.fromhex(r["hex"]) and SERIAL_B in bytes.fromhex(r["hex"])
                                        for r in native_wire if r["direction"]=="tx"))
                    self.assertEqual(xml_text(db.get(network,xml=True)),xml_before)
                    self.assertEqual(sim.snapshot(),before)
                    self.assertFalse([r for r in sim.wire_log if r.get("reason")])
                    report.update(passed=True,observation=observation.as_dict(),native_reply=list(native.lines),
                                  direct_wire=direct_wire,native_wire=native_wire,database_unchanged=True,fixture_unchanged=True,
                                  post_ready_retries_reply=list(retries.lines))
                finally:
                    errors=[]
                    if created:
                        for command in ("NET CLOSE "+network,"PROJECT CLOSE "+project,"PROJECT DELETE "+project):
                            try:client.command(command)
                            except Exception as error:errors.append(str(error))
                    report["cleanup_errors"]=errors
                    if path:=os.environ.get("CBUS_PCI_SERIAL_REPORT"):
                        destination=Path(path);destination.parent.mkdir(parents=True,exist_ok=True)
                        destination.write_text(json.dumps(report,indent=2)+"\n")
                    if report["passed"]:self.assertEqual(errors,[])


if __name__ == "__main__": unittest.main()
