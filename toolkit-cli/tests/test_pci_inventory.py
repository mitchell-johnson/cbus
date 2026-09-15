"""Literal direct install MMI framing, coverage, deadlines and native comparison."""
import json
import os
from pathlib import Path
import socket
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from cbus_toolkit.pci_inventory import PCIMMICollector
from tests.test_pci_serials import OTHER_UNIT, peer
from tests.test_simulator_duplicates import fixture


FIRST = b"D8FF00" + b"00" * 4 + b"01" + b"00" * 17 + b"28\r\n"
MIDDLE = b"D8FF58" + b"00" * 22 + b"D1\r\n"
LAST = b"D6FFB0" + b"00" * 19 + b"80FB\r\n"
FULL = FIRST + MIDDLE + LAST
ZERO_FIRST = b"D8FF00" + b"00" * 22 + b"29\r\n"
ZERO_LAST = b"D6FFB0" + b"00" * 20 + b"7B\r\n"
OTHER_MMI = b"D83858" + b"00" * 22 + b"98\r\n"


def collector(endpoint, **options):
    values = dict(local_unit=16, overall_timeout=.5, confirmation_timeout=.15, response_timeout=.05)
    values.update(options)
    return PCIMMICollector(*endpoint, **values)


class PCIMMICollectorTests(unittest.TestCase):
    def observe(self, data, **options):
        with peer(lambda connection: connection.sendall(data)) as (endpoint, state):
            result=collector(endpoint, **options).collect_mmi()
        self.assertTrue(state["closed"]);self.assertEqual(state["extra"],b"")
        return result,state

    def test_three_literal_blocks_establish_full_presence_without_serial_identity(self):
        result,state=self.observe(b"g."+FULL)
        self.assertEqual(state["request"],b"\\05FF00FAFF00g\r")
        self.assertTrue(result.complete);self.assertTrue(result.coverage_complete)
        self.assertEqual(result.status,"complete");self.assertEqual(result.addresses,(16,255))
        self.assertTrue(result.local_present);self.assertEqual(result.error_addresses,())
        self.assertEqual(len(result.states),256);self.assertEqual(result.states[16],1);self.assertEqual(result.states[255],2)
        self.assertEqual(result.missing_ranges,());self.assertEqual([b.start for b in result.blocks],[0,88,176])
        self.assertEqual([b.end for b in result.blocks],[88,176,256])
        document=result.as_dict();json.dumps(document)
        self.assertFalse(document["serials_observed"]);self.assertFalse(document["physical_addresses_changed"])
        self.assertEqual(document["automatic_retries"],0);self.assertTrue(document["connection_closed"])

    def test_fragmented_confirmation_and_blocks_preserve_literal_coverage(self):
        def send(connection):
            for chunk in (b"g",b".",FIRST[:9],FIRST[9:],MIDDLE[:20],MIDDLE[20:],LAST[:-3],LAST[-3:]):
                connection.sendall(chunk);time.sleep(.004)
        with peer(send) as (endpoint,state):result=collector(endpoint,response_timeout=.1).collect_mmi()
        self.assertTrue(result.complete);self.assertEqual(result.addresses,(16,255))
        self.assertEqual(state["request"],b"\\05FF00FAFF00g\r")

    def test_missing_repeated_overlapping_and_out_of_order_ranges_never_become_zero(self):
        for payload,known,block_count in ((FIRST+LAST,88,2),(FIRST+FIRST+LAST,88,2),
                                          (FIRST+MIDDLE+MIDDLE,176,3),(MIDDLE+FIRST+LAST,0,1)):
            with self.subTest(payload=payload):
                result,_=self.observe(b"g."+payload)
                self.assertFalse(result.complete);self.assertFalse(result.coverage_complete)
                self.assertEqual(result.termination,"coverage_error")
                self.assertEqual(sum(value is not None for value in result.states),known)
                self.assertEqual(len(result.blocks),block_count)
                self.assertEqual(result.missing_ranges,((known,256),))

    def test_missing_final_range_and_ack_only_timeout_retain_unknowns(self):
        for payload,known in ((FIRST+MIDDLE,176),(b"",0)):
            with self.subTest(payload=payload):
                result,_=self.observe(b"g."+payload)
                self.assertEqual(result.termination,"response_timeout")
                self.assertFalse(result.complete)
                self.assertEqual(sum(value is not None for value in result.states),known)
                self.assertIsNone(result.states[255]);self.assertEqual(result.missing_ranges,((known,256),))

    def test_zero_or_missing_local_is_complete_coverage_but_incomplete_observation(self):
        for payload,local in ((ZERO_FIRST+MIDDLE+ZERO_LAST,16),(FULL,17)):
            with self.subTest(local=local):
                result,_=self.observe(b"g."+payload,local_unit=local)
                self.assertTrue(result.coverage_complete);self.assertFalse(result.local_present)
                self.assertFalse(result.complete);self.assertEqual(result.status,"incomplete")
                self.assertEqual(result.termination,"local_absent");self.assertEqual(result.missing_ranges,())

    def test_state_error_flag_is_separate_from_protocol_completeness(self):
        error_last=b"D6FFB0"+b"00"*19+b"C0BB\r\n"
        result,_=self.observe(b"g."+FIRST+MIDDLE+error_last)
        self.assertTrue(result.complete);self.assertEqual(result.status,"mmi_errors")
        self.assertEqual(result.error_addresses,(255,));self.assertEqual(result.states[255],3)
        self.assertEqual(result.errors,())

    def test_literal_bit_order_covers_zero_and_all_segment_boundaries(self):
        first=b"D8FF00"+b"01"+b"00"*3+b"01"+b"00"*16+b"80A7\r\n"
        middle=b"D8FF58"+b"01"+b"00"*20+b"8050\r\n"
        last=b"D6FFB0"+b"01"+b"00"*18+b"80FA\r\n"
        result,_=self.observe(b"g."+first+middle+last,local_unit=0)
        self.assertTrue(result.complete)
        self.assertEqual({i:s for i,s in enumerate(result.states) if s},{0:1,16:1,87:2,88:1,175:2,176:1,255:2})

    def test_other_application_and_cal_are_retained_without_contributing_coverage(self):
        result,_=self.observe(b"g."+OTHER_MMI+OTHER_UNIT+FULL)
        self.assertTrue(result.complete);self.assertEqual(len(result.unrelated),2)
        self.assertEqual(result.unrelated[0]["reason"],"other_application")
        self.assertEqual(len(result.blocks),3)

    def test_correlation_rejection_and_data_before_confirmation_stop_without_retry(self):
        cases=((b"h.","correlation_error"),(b"g.g.","correlation_error"),
               (b"g#","rejected"),(b"g$","rejected"),(b"g!","rejected"),(b"!","rejected"),
               (FIRST+b"g.","correlation_error"),(b"g.","response_timeout"))
        for payload,reason in cases:
            with self.subTest(payload=payload):
                result,state=self.observe(payload)
                self.assertEqual(result.termination,reason);self.assertFalse(result.complete)
                self.assertTrue(all(value is None for value in result.states))
                self.assertEqual(state["request"],b"\\05FF00FAFF00g\r")

    def test_bad_later_checksum_length_range_or_unsupported_route_preserves_prefix(self):
        routed=b"86FF1000D8FF00"+b"00"*4+b"01"+b"00"*17+b"93\r\n"
        extended=b"F900FF00"+b"00"*4+b"01"+b"00"*17+b"07\r\n"
        failures=(MIDDLE[:-4]+b"D0\r\n",b"D8FFB0"+b"00"*22+b"79\r\n",
                  b"D8FF00"+b"00"*21+b"29\r\n",b"C2FF003F\r\n",b"XYZ\r\n",routed,extended)
        for bad in failures:
            with self.subTest(bad=bad):
                result,_=self.observe(b"g."+FIRST+bad)
                self.assertEqual(result.termination,"framing_error");self.assertFalse(result.complete)
                self.assertEqual(result.states[:88],tuple([0]*16+[1]+[0]*71))
                self.assertTrue(all(value is None for value in result.states[88:]))

    def test_extra_duplicate_confirmation_block_or_partial_data_in_completing_read_is_incomplete(self):
        for tail,reason in ((b"g.","correlation_error"),(FIRST,"coverage_error"),(b"D8FF","truncated_frame")):
            with self.subTest(tail=tail):
                result,_=self.observe(b"g."+FULL+tail)
                self.assertFalse(result.complete);self.assertTrue(result.coverage_complete)
                self.assertEqual(result.termination,reason)

    def test_finite_frame_byte_and_unrelated_limits_do_not_claim_completion(self):
        result,_=self.observe(b"g."+FULL,max_frames=1)
        self.assertEqual(result.termination,"frame_limit");self.assertEqual(result.missing_ranges,((88,256),))
        result,_=self.observe(b"g."+FULL,max_frames=3);self.assertTrue(result.complete)
        result,_=self.observe(b"g."+FULL,max_bytes=60)
        self.assertEqual(result.termination,"byte_limit");self.assertEqual(len(result.received),60)
        self.assertEqual(result.bytes_received,61);self.assertFalse(result.complete)
        result,_=self.observe(b"g.+"+FULL,max_unrelated=1)
        self.assertEqual(result.termination,"unrelated_limit");self.assertFalse(result.complete)

    def test_overall_deadline_bounds_late_final_segment(self):
        def send(connection):
            connection.sendall(b"g."+FIRST);time.sleep(.07)
            connection.sendall(MIDDLE);time.sleep(.07);connection.sendall(LAST)
        with peer(send) as (endpoint,state):
            result=collector(endpoint,overall_timeout=.12,confirmation_timeout=.1,response_timeout=.1).collect_mmi()
        # A receive can wake just after the deadline rather than timing out;
        # both outcomes retain the same bounded incomplete observation.
        self.assertIn(result.termination,("overall_timeout","late_data"));self.assertFalse(result.complete)
        self.assertEqual(result.missing_ranges,((176,256),));self.assertEqual(state["extra"],b"")

    def test_unrelated_traffic_does_not_extend_response_deadline(self):
        def send(connection):
            connection.sendall(b"g."+FIRST);time.sleep(.03);connection.sendall(OTHER_MMI)
            time.sleep(.03);connection.sendall(OTHER_UNIT)
        with peer(send) as (endpoint,_):result=collector(endpoint,response_timeout=.05).collect_mmi()
        self.assertEqual(result.termination,"response_timeout");self.assertFalse(result.complete)
        self.assertEqual(len(result.unrelated),1);self.assertLess(result.elapsed,.1)

    def test_partial_frame_or_confirmation_and_disconnect_remain_incomplete(self):
        for payload in (b"g",b"g."+FIRST+MIDDLE[:10]):
            with self.subTest(payload=payload):
                result,_=self.observe(payload,confirmation_timeout=.03)
                self.assertEqual(result.termination,"truncated_frame");self.assertFalse(result.complete)
        result,_=self.observe(b"+",confirmation_timeout=.03)
        self.assertEqual(result.termination,"confirmation_timeout")
        def close(connection):connection.sendall(b"g."+FIRST);connection.shutdown(socket.SHUT_WR)
        with peer(close) as (endpoint,_):result=collector(endpoint).collect_mmi()
        self.assertEqual(result.termination,"disconnected");self.assertFalse(result.complete)
        self.assertEqual(result.missing_ranges,((88,256),))

    def test_late_fragment_cannot_finish_a_timed_out_one_shot_observation(self):
        def send(connection):
            connection.sendall(b"g."+FIRST+MIDDLE[:10])
            time.sleep(.08);connection.sendall(MIDDLE[10:]+LAST)
        with peer(send) as (endpoint,state):
            subject=collector(endpoint,response_timeout=.04)
            result=subject.collect_mmi()
            with self.assertRaises(RuntimeError):subject.collect_mmi()
        self.assertEqual(result.termination,"truncated_frame");self.assertFalse(result.complete)
        self.assertEqual(result.missing_ranges,((88,256),));self.assertEqual(state["extra"],b"")

    def test_flow_control_bytes_and_lowercase_hex_keep_exact_received_evidence(self):
        wire=b"\x11g\x13."+FULL.lower().replace(b"d8",b"d\x118")
        result,_=self.observe(wire)
        self.assertTrue(result.complete);self.assertEqual(result.addresses,(16,255))
        self.assertEqual(result.received,wire)

    def test_srchk_literal_and_fragmented_duplicate_fixture_are_read_only(self):
        result,state=self.observe(b"g."+FULL,command_checksum=True)
        self.assertEqual(state["request"],b"\\05FF00FAFF0003g\r");self.assertTrue(result.complete)
        sim=fixture(command_checksum=True,fragment_sizes=(1,3,2));before=sim.snapshot()
        with sim.running() as endpoint:result=collector(endpoint,command_checksum=True).collect_mmi()
        self.assertTrue(result.complete);self.assertEqual(result.addresses,(16,255))
        self.assertEqual(sim.snapshot(),before);self.assertFalse([row for row in sim.wire_log if row.get("reason")])

    def test_invalid_inputs_never_connect_and_each_collector_is_one_shot(self):
        invalid=({"local_unit":True},{"local_unit":256},{"response_timeout":0},{"confirmation_timeout":float("inf")},
                 {"overall_timeout":True},{"overall_timeout":1},{"max_frames":0},{"max_bytes":1048577},
                 {"max_unrelated":False},{"command_checksum":1},{"port":0})
        with patch.object(PCIMMICollector,"_make_socket") as connect:
            for options in invalid:
                with self.subTest(options=options),self.assertRaises(ValueError):
                    PCIMMICollector("127.0.0.1",**(dict(local_unit=16)|options))
            for host in ("localhost","example.test","fe80::1%en0","",None):
                with self.subTest(host=host),self.assertRaises(ValueError):PCIMMICollector(host,local_unit=16)
            connect.assert_not_called()
        with peer(lambda connection:connection.sendall(b"g."+FULL)) as (endpoint,state):
            subject=collector(endpoint);self.assertTrue(subject.collect_mmi().complete)
            with self.assertRaises(RuntimeError):subject.collect_mmi()
        self.assertEqual(state["extra"],b"")
        self.assertFalse(any(hasattr(subject,name) for name in ("write","readdress","send_raw","command","collect_serials")))

    def test_connection_close_failure_and_interruption_preserve_partial_evidence(self):
        with patch.object(PCIMMICollector,"_make_socket",side_effect=OSError("offline")):
            result=PCIMMICollector("127.0.0.1",local_unit=16).collect_mmi()
        self.assertEqual(result.termination,"connection_error");self.assertEqual(result.request,b"")
        self.assertTrue(result.connection_closed)

        class Stream:
            def __init__(self, replies, close_error=None):self.replies,self.close_error=replies,close_error;self.closed=False
            def settimeout(self,value):pass
            def connect(self,endpoint):self.endpoint=endpoint
            def sendall(self,data):self.request=data
            def recv(self,count):
                event=self.replies.pop(0)
                if isinstance(event,BaseException):raise event
                return event
            def close(self):
                self.closed=True
                if self.close_error:raise self.close_error

        for error in (KeyboardInterrupt("stop"),SystemExit("stop")):
            stream=Stream([b"g."+FIRST,error]);subject=PCIMMICollector("::1",local_unit=16)
            with self.subTest(error=error),patch.object(subject,"_make_socket",return_value=stream):
                with self.assertRaises(type(error)) as caught:subject.collect_mmi()
                self.assertIs(caught.exception,error);self.assertTrue(stream.closed)
                self.assertEqual(stream.endpoint,("::1",10001,0,0))
                self.assertEqual(subject.last_observation.missing_ranges,((88,256),))
                self.assertEqual(error.pci_mmi_observation["termination"],"interrupted")
                self.assertTrue(error.pci_mmi_observation["connection_closed"])
        stream=Stream([b"g."+FULL],OSError("close failed"));subject=PCIMMICollector("127.0.0.1",local_unit=16)
        with patch.object(subject,"_make_socket",return_value=stream):result=subject.collect_mmi()
        self.assertFalse(result.complete);self.assertTrue(result.coverage_complete)
        self.assertEqual(result.termination,"close_error");self.assertFalse(result.connection_closed)
        self.assertIn("close failed",result.errors[-1])


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"),"Set CBUS_CGATE_TEST_HOST for native direct MMI comparison")
class NativePCIMMICollectorTests(unittest.TestCase):
    def test_direct_collector_and_native_pingu_agree_on_full_duplicate_fixture_presence(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.networks import NativeNetworks
        from cbus_toolkit.programming import xml_text

        sim=fixture(response_delay=.01);before=sim.snapshot()
        project="MM"+uuid4().hex[:6].upper();network="//"+project+"/254"
        report={"passed":False,"scope":"Direct standard install MMI and exact native PINGU; no serial or hardware claim"}
        try:
            with sim.running("0.0.0.0",0) as (_,port):
                result=PCIMMICollector("127.0.0.1",port,local_unit=16).collect_mmi()
                self.assertTrue(result.complete);self.assertEqual(result.addresses,(16,255))
                direct=list(sim.wire_log)
                self.assertEqual([bytes.fromhex(row["hex"]) for row in direct if row["direction"]=="rx"],[b"\\05FF00FAFF00g\r"])
                self.assertTrue(any(bytes.fromhex(row["hex"])==b"g."+FULL for row in direct if row["direction"]=="tx"))
                with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"],int(os.environ.get("CBUS_CGATE_TEST_PORT","20023")),timeout=40) as client:
                    projects,db,nets=NativeProjects(client),NativeDatabase(client),NativeNetworks(client);created=False
                    try:
                        projects.operation("new",project);created=True
                        db.create_network(project,254,"Direct_MMI","Cni",
                            os.environ.get("CBUS_CGATE_SIMULATOR_HOST","host.docker.internal")+":"+str(port))
                        projects.operation("save",project);xml_before=xml_text(db.get(network,xml=True))
                        nets.open(network);nets.wait_ready(network,timeout=30)
                        client.command("SET "+network+" Retries 0")
                        self.assertEqual(client.command("GET "+network+" Retries").lines,("300 "+network+": Retries=0",))
                        start=len(sim.wire_log);native=client.command("NET PINGU "+network)
                        self.assertEqual(native.lines,("302-Units=16, 255","200 OK."))
                        native_wire=list(sim.wire_log[start:])
                        self.assertTrue(any(bytes.fromhex(row["hex"])[2:]==FULL for row in native_wire if row["direction"]=="tx"))
                        self.assertEqual(sim.snapshot(),before);self.assertEqual(xml_text(db.get(network,xml=True)),xml_before)
                        self.assertFalse([row for row in sim.wire_log if row.get("reason")])
                        report.update(passed=True,observation=result.as_dict(),direct_wire=direct,native_reply=list(native.lines),
                                      native_wire=native_wire,database_unchanged=True,fixture_unchanged=True)
                    finally:
                        report["cleanup_errors"]=[]
                        if created:
                            for command in ("NET CLOSE "+network,"PROJECT CLOSE "+project,"PROJECT DELETE "+project):
                                try:client.command(command)
                                except Exception as error:report["cleanup_errors"].append(str(error))
                        if report["passed"]:self.assertEqual(report["cleanup_errors"],[])
        finally:
            if output:=os.environ.get("CBUS_PCI_MMI_REPORT"):
                Path(output).write_text(json.dumps(report,indent=2)+"\n")


if __name__=="__main__":unittest.main()
