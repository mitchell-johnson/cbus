"""Literal eDLT control packets and independent per-unit fixture persistence."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.simulator_edlt_labels import EdltLabelClearFixture, LabelClearFault


CLEAR=b'\\46050900A4FF43C1EAg'
ACK=b'g.860510010032FF43F0\r\n'


def labels():
    return {'format':'cbus-synthetic-labels-v1','labels':[
        {'key':[56,42,None,0,0],'kind':'text','text':'Owned','data_hex':'4f776e6564'},
        {'key':[56,42,None,1,1],'kind':'unicode','text':'Māori','data_hex':'4dc4816f7269'},
        {'key':[202,7,11,0,2],'kind':'icon','icon':258,'data_hex':'010102'},
        {'key':[56,43,None,0,3],'kind':'dynamic','icon':300,'width':8,'height':1,'vertical_offset':0,'data_hex':'a5'}],
        'languages':[{'key':[56,42,None],'language':1}]}


def fixture(**options):
    return EdltLabelClearFixture({4:labels(),5:labels()},clearing_policy=EdltLabelClearFixture.POLICY,**options)


def command(sim,line=CLEAR,context=None):
    return sim._command(line,context or {'header':None})


class LabelFixtureTests(unittest.TestCase):
    def test_exact_control_clears_only_target_committed_records_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path);before=sim.snapshot();context={'header':None}
            self.assertEqual(command(sim,CLEAR,context),(ACK,None))
            after=sim.snapshot();self.assertEqual(after['base'],before['base']);self.assertEqual(after['unit_labels']['4'],before['unit_labels']['4'])
            self.assertEqual(after['unit_labels']['5']['labels'],[])
            self.assertEqual(after['unit_labels']['5']['languages'],before['unit_labels']['5']['languages'])
            self.assertEqual(after['revision'],1);self.assertFalse(after['firmware_erasure_verified'])
            self.assertEqual(EdltLabelClearFixture.from_state(path).snapshot(),after)
            self.assertEqual(command(sim,b'A4FF43C1EAh',context),(b'h.860510010032FF43F0\r\n',None))
            self.assertEqual(sim.revision,2);self.assertEqual(len(sim.clear_operations),2)
            detached=sim.unit_labels;detached[4]['labels'].clear();self.assertEqual(len(sim.unit_labels[4]['labels']),4)
    def test_literal_faults_keep_reply_independent_from_declared_state_policy(self):
        vectors={'ack':ACK,'missing':b'g.','negative':b'g.86051001003BFF43E7\r\n',
                 'extended':b'g.860510010032FF43DEADBEEFB8\r\n','wrong_tag':b'g.860510010032FF44EF\r\n',
                 'wrong_source':b'g.860410010032FF43F1\r\n','wrong_destination':b'g.860511010032FF43EF\r\n',
                 'bad_checksum':b'g.860510010032FF4300\r\n'}
        for clear in (False,True):
            for response,wire in vectors.items():
                with self.subTest(clear=clear,response=response),tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'state.json';sim=fixture(state_path=path,fault=LabelClearFault(clear,response))
                    self.assertEqual(command(sim)[0],wire)
                    self.assertEqual(len(sim.unit_labels[5]['labels']),0 if clear else 4)
                    self.assertEqual(EdltLabelClearFixture.from_state(path).unit_labels,sim.unit_labels)
                    self.assertEqual(len(sim.unit_labels[4]['labels']),4)
                    self.assertEqual(sim.clear_operations[-1]['fault'],{'clear':clear,'response':response})
    def test_strict_frame_and_profile_rejects_other_mutations_without_erasing(self):
        sim=fixture();before=sim.snapshot()
        for packet in (b'\\46050900A4FF43B2B2g',b'\\46040900A4FF43C1EAg',b'\\46050900A3FF43C1EAg',
                       b'\\460500A42100AABB g',b'\\46050900A40142AABB g',b'\\053800A80100004F574E4544g',
                       b'\\05FF000F0018B106160615g',b'\\46050900A4FF43C1EAgmore'):
            with self.subTest(packet=packet):
                wire,reason=command(sim,packet);self.assertIsNotNone(reason)
                self.assertTrue(wire.endswith((b'#',b'!')))
        self.assertEqual(sim.snapshot(),before);self.assertFalse(sim.clear_operations)
    def test_strict_whole_state_loader_rejects_tampering_duplicate_keys_and_oversize(self):
        sim=fixture();source=sim.snapshot()
        invalid=[]
        for change in (lambda d:d.update(extra=True),lambda d:d.update(revision=True),
                       lambda d:d['base'].update(schema=True),lambda d:d['base'].update(local_unit=16.0),
                       lambda d:d['unit_labels'].update({'6':labels()}),
                       lambda d:d['unit_labels']['5'].update(extra=1),
                       lambda d:d['unit_labels']['5']['languages'][0].update(extra=1),
                       lambda d:d['unit_labels']['5']['labels'][0].update(data_hex='4F776E6564'),
                       lambda d:d.update(clearing_policy='clear_everything')):
            d=deepcopy(source);change(d);invalid.append(json.dumps(d).encode())
        invalid += [b'{"format":"x","format":"y"}',b'{"revision":NaN}',b' '*(EdltLabelClearFixture.MAX_BYTES+1)]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json'
            for raw in invalid:
                path.write_bytes(raw)
                with self.subTest(raw=raw[:80]),self.assertRaises(ValueError):EdltLabelClearFixture.from_state(path)
            target=Path(directory)/'target';target.write_text('{}');path.unlink();path.symlink_to(target)
            with self.assertRaises(ValueError):EdltLabelClearFixture.from_state(path)
    def test_persistence_failure_restores_memory_and_keeps_external_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path);before=sim.snapshot();disk=path.read_bytes()
            with patch('cbus_toolkit.simulator_edlt_labels.os.replace',side_effect=OSError('replace refused')):
                self.assertEqual(command(sim)[0],b'g#')
            self.assertEqual(sim.snapshot(),before);self.assertEqual(path.read_bytes(),disk)
            self.assertTrue(sim.clear_operations[-1]['memory_restored']);self.assertFalse(sim.clear_operations[-1]['persisted'])
            self.assertFalse(list(Path(directory).glob('.edlt-label-state-*')))
            path.write_bytes(b'external');self.assertEqual(command(sim)[0],b'g#')
            self.assertEqual(path.read_bytes(),b'external');self.assertEqual(sim.snapshot(),before)
    def test_failure_after_replace_retains_new_file_and_explicit_durability_uncertainty(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path);real=os.replace
            def replace_then_fail(a,b):real(a,b);raise OSError('after replace')
            with patch('cbus_toolkit.simulator_edlt_labels.os.replace',side_effect=replace_then_fail):self.assertEqual(command(sim)[0],b'g#')
            self.assertFalse(sim.unit_labels[5]['labels']);self.assertEqual(EdltLabelClearFixture.from_state(path).snapshot(),sim.snapshot())
            record=sim.clear_operations[-1];self.assertEqual(record['disk_state'],'proposed_observed_durability_uncertain')
            self.assertFalse(record['persisted']);self.assertFalse(record['response_generated'])
    def test_interruption_before_persistence_and_secondary_probe_failures_keep_first_object(self):
        for before_persist in (False,True):
            with self.subTest(before=before_persist),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'state.json';sim=fixture(state_path=path);before=sim.snapshot();disk=path.read_bytes()
                first=KeyboardInterrupt('first');second=SystemExit('probe')
                with patch.object(sim,'_bytes' if before_persist else '_persist',side_effect=first),patch.object(sim,'_read',side_effect=second):
                    with self.assertRaises(KeyboardInterrupt) as caught:command(sim)
                self.assertIs(caught.exception,first);self.assertEqual(sim.snapshot(),before);self.assertEqual(path.read_bytes(),disk)
                record=first.edlt_label_fixture_evidence
                self.assertEqual(record['persistence_attempted'],not before_persist)
                if not before_persist:self.assertEqual(record['disk_probe_error']['type'],'SystemExit')
                self.assertFalse(record['response_generated'])
    def test_fsync_interruption_survives_close_interruption_and_stops_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path);before=sim.snapshot();first=KeyboardInterrupt('fsync');second=SystemExit('close');close=os.close
            def fail_close(fd):close(fd);raise second
            with patch('cbus_toolkit.simulator_edlt_labels.os.fsync',side_effect=first),patch('cbus_toolkit.simulator_edlt_labels.os.close',side_effect=fail_close):
                with self.assertRaises(KeyboardInterrupt) as caught:command(sim)
            self.assertIs(caught.exception,first);self.assertEqual(sim.snapshot(),before)
            self.assertEqual(first.edlt_label_fixture_evidence['cleanup_errors'][0]['type'],'SystemExit')
            self.assertFalse(first.edlt_label_fixture_evidence['response_generated'])
    def test_failed_error_formatting_keeps_first_interruption_and_restores_state(self):
        class UnprintableInterrupt(KeyboardInterrupt):
            def __str__(self):raise SystemExit('formatting')
        first=UnprintableInterrupt();second=UnprintableInterrupt()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';sim=fixture(state_path=path);before=sim.snapshot();disk=path.read_bytes()
            with patch.object(sim,'_persist',side_effect=first),patch.object(sim,'_read',side_effect=second):
                with self.assertRaises(UnprintableInterrupt) as caught:command(sim)
            self.assertIs(caught.exception,first);self.assertEqual(sim.snapshot(),before);self.assertEqual(path.read_bytes(),disk)
            evidence=first.edlt_label_fixture_evidence
            self.assertEqual(evidence['cause']['message_error_type'],'SystemExit')
            self.assertEqual(evidence['disk_probe_error']['message_error_type'],'SystemExit')
            self.assertTrue(evidence['memory_restored']);self.assertFalse(evidence['response_generated'])
        self.assertIs(EdltLabelClearFixture._secondary(first,second),first)
        self.assertEqual(first.fixture_cleanup_errors[0]['message_error_type'],'SystemExit')
    def test_literal_socket_fragmented_and_outgoing_checksum_frames(self):
        for checksum,request in ((False,b'\\46050900A4FF43C1EAg\r'),(True,b'\\46050900A4FF43C1EA1Bg\r')):
            sim=fixture(command_checksum=checksum,fragment_sizes=(1,2,1,3))
            with sim.running('127.0.0.1',0) as endpoint,socket.create_connection(endpoint,timeout=2) as sock:
                sock.sendall(request[:7]);sock.sendall(request[7:]);received=b''
                while not received.endswith(b'\r\n'):received+=sock.recv(100)
            self.assertEqual(received,ACK);self.assertFalse(sim.unit_labels[5]['labels']);self.assertEqual(len(sim.clear_operations),1)
