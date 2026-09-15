"""Selected-serial CLI over owned literal peers and independent persisted nodes."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.pci_selected_serial import SelectedSerialCoordinator, SelectedSerialPlan
from cbus_toolkit.pci_serial_address_transport import PCISerialAddressTransport
from cbus_toolkit.simulator_duplicate_addressing import SerialAddressFixture, SerialAddressFault
from tests.test_simulator_duplicate_addressing import fixture,A,B,CO_A,RECEIPT_A
from tests.test_pci_selected_serial import manager,LOCAL,OPTIONS,OPTIONS_REQUEST,LOCAL_REQUEST,MMI_REQUEST,after_responses
from tests.test_pci_full_inventory import conversation,successful_responses
from tests.test_pci_serials import BARE_PCI
from tests.test_pci_serial_address_transport import Clock,FakeSocket


FAST=['--timeout','5','--observation-timeout','.5','--confirmation-timeout','.1',
      '--mmi-response-timeout','.1','--quiet-period','.02','--options-response-timeout','.02',
      '--address-response-timeout','.02','--max-mmi-frames','7','--max-serial-frames','7',
      '--max-unrelated','64','--max-bytes','65536']


def plan_args(endpoint,path,*options):
    return ['serial-address','plan',A,'6','--host',endpoint[0],'--port',str(endpoint[1]),
            '--local-unit','16','--expected-local-serial',LOCAL,'--output',str(path),'--source','255',*FAST,*options]


def requests(sim):
    return [bytes.fromhex(item['hex']) for item in sim.wire_log if item['direction']=='rx']


class SelectedSerialCLITests(unittest.TestCase):
    def subprocess_cli(self,*args,status=0):
        process=subprocess.run([sys.executable,'-m','cbus_toolkit',*map(str,args)],
                               capture_output=True,text=True,timeout=15)
        self.assertEqual(process.returncode,status,process.stdout+process.stderr)
        return json.loads(process.stdout or process.stderr)

    def invoke(self,args,status=0):
        output,error=io.StringIO(),io.StringIO()
        with redirect_stdout(output),redirect_stderr(error):actual=cli.main(list(map(str,args)))
        self.assertEqual(actual,status,output.getvalue()+error.getvalue())
        self.assertFalse(output.getvalue() and error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def test_literal_subprocess_sequence_exports_exact_plan_and_verifies_without_replay(self):
        before=successful_responses()+[b'g.'+BARE_PCI,OPTIONS]
        with tempfile.TemporaryDirectory() as tmp,conversation(before*2+[RECEIPT_A]+after_responses()*2) as (endpoint,state):
            path=Path(tmp)/'plan.json';journal=Path(tmp)/'recovery.json'
            export=self.subprocess_cli(*plan_args(endpoint,path))
            self.assertEqual(export['format'],'cbus-selected-serial-plan-export-v1')
            self.assertEqual(export['plan_file'],str(path));self.assertFalse(export['address_command_sent'])
            self.assertFalse(export['database_updated']);self.assertEqual(json.loads(path.read_text()),export['plan'])
            self.assertEqual(SelectedSerialPlan.load(path).as_dict(),export['plan'])
            plan_bytes=path.read_bytes()
            result=self.subprocess_cli('serial-address','apply',path,'--recovery',journal)
            recovery_bytes=journal.read_bytes()
            verify=self.subprocess_cli('serial-address','verify','--recovery',journal)
            self.assertEqual(path.read_bytes(),plan_bytes);self.assertEqual(journal.read_bytes(),recovery_bytes)
        initial=[MMI_REQUEST,LOCAL_REQUEST,b'\\46FF002104g\r',MMI_REQUEST,LOCAL_REQUEST,OPTIONS_REQUEST]
        after=[MMI_REQUEST,b'\\4606002104g\r',LOCAL_REQUEST,b'\\46FF002104g\r',MMI_REQUEST]
        self.assertEqual(state['requests'],initial*2+[CO_A]+after*2)
        self.assertFalse(any(state['extra']));self.assertTrue(all(state['closed']))
        for value in (result,verify):
            self.assertEqual(value['outcome'],'observed_expected_change');self.assertTrue(value['expected_identity_change'])
            self.assertTrue(value['after_collection_complete']);self.assertFalse(value['firmware_persistence_verified'])
            self.assertFalse(value['physical_compatibility_verified']);self.assertFalse(value['atomic_observation'])
        self.assertTrue(result['receipt_matches_request']);self.assertTrue(result['send_attempted'])
        self.assertFalse(verify['send_attempted']);self.assertIsNone(verify['exchange'])

    def test_checksummed_fixture_restart_retains_selected_move_and_verification_uses_saved_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plan.json';journal=Path(tmp)/'recovery.json';state_path=Path(tmp)/'fixture.json'
            sim=fixture(state_path=state_path,command_checksum=True)
            with sim.running() as endpoint:
                export=self.subprocess_cli(*plan_args(endpoint,path,'--checksum'))
                self.assertTrue(export['plan']['settings']['command_checksum'])
                self.assertEqual(export['plan']['settings']['overall_timeout'],5.)
                unchanged=self.subprocess_cli('serial-address','verify','--plan',path,status=1)
                self.assertEqual(unchanged['outcome'],'observed_unchanged');self.assertEqual(sim.co_operations,[])
                moved=self.subprocess_cli('serial-address','apply',path,'--recovery',journal)
                self.assertEqual(moved['outcome'],'observed_expected_change');self.assertEqual(len(sim.co_operations),1)
                self.assertEqual(sim.nodes[A].address,6);self.assertEqual(sim.nodes[B].address,255)
                stale=self.subprocess_cli('serial-address','apply',path,'--recovery',Path(tmp)/'second.json',status=1)
                self.assertFalse(stale['selected_serial_evidence']['send_attempted'])
                self.assertFalse(Path(tmp,'second.json').exists());self.assertEqual(len(sim.co_operations),1)
                self.assertIn(b'\\05FF000F0018B106160615EDg\r',requests(sim))
                self.assertIn(b'\\4610001A42014Dg\r',requests(sim))
                self.assertNotIn(CO_A,requests(sim))
            restarted=SerialAddressFixture.from_state(state_path,command_checksum=True)
            with restarted.running(*endpoint):
                result=self.subprocess_cli('serial-address','verify','--recovery',journal)
                self.assertEqual(result['outcome'],'observed_expected_change');self.assertEqual(restarted.co_operations,[])
                self.assertEqual([item['serials'] for item in result['after']['serial_observations']],[[A],[LOCAL],[B]])
            self.assertEqual(restarted.nodes[A].address,6);self.assertEqual(restarted.nodes[B].address,255)

    def test_missing_receipt_and_forged_success_have_independently_correct_exit_status(self):
        report=[]
        for label,fault,status,outcome,matched in (
            ('move_without_reply',SerialAddressFault(reply=False),0,'observed_expected_change',False),
            ('forged_success_without_move',SerialAddressFault(move=False),1,'observed_unchanged',True)):
            with self.subTest(case=label),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'plan.json';journal=Path(tmp)/'recovery.json';sim=fixture(faults={A:fault})
                with sim.running() as endpoint:
                    self.subprocess_cli(*plan_args(endpoint,path))
                    result=self.subprocess_cli('serial-address','apply',path,'--recovery',journal,status=status)
                    verify=self.subprocess_cli('serial-address','verify','--plan',path,status=status)
                    self.assertEqual(result['outcome'],outcome);self.assertEqual(verify['outcome'],outcome)
                    self.assertEqual(result['receipt_matches_request'],matched);self.assertEqual(len(sim.co_operations),1)
                    self.assertEqual(sim.nodes[A].address,6 if fault.move else 255);self.assertEqual(sim.nodes[B].address,255)
                report.append({'case':label,'exit_status':status,'outcome':outcome,'receipt_matches_request':matched,
                    'actual_fixture_addresses':{A:sim.nodes[A].address,B:sim.nodes[B].address},'co_requests':1})
        if os.environ.get('CBUS_SELECTED_SERIAL_CLI_REPORT'):
            Path(os.environ['CBUS_SELECTED_SERIAL_CLI_REPORT']).write_text(json.dumps({'passed':True,'cases':report},indent=2)+'\n')

    def test_new_file_preflight_guards_existing_plan_journal_and_missing_parent_without_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plan.json';journal=Path(tmp)/'recovery.json';sim=fixture()
            with sim.running() as endpoint:
                plan=manager(endpoint).plan(A,6)
            path.write_text(json.dumps(plan.as_dict()));journal.write_text('KEEP')
            original=path.read_bytes()
            with patch('socket.socket',side_effect=AssertionError('File preflight must precede network I/O')):
                self.assertIn('error',self.invoke(plan_args(endpoint,path),status=1))
                self.assertIn('error',self.invoke(plan_args(endpoint,Path(tmp)/'missing'/'plan.json'),status=1))
                self.assertIn('error',self.invoke(['serial-address','apply',path,'--recovery',journal],status=1))
                self.assertIn('error',self.invoke(['serial-address','apply',path,'--recovery',Path(tmp)/'missing'/'journal.json'],status=1))
            self.assertEqual(path.read_bytes(),original);self.assertEqual(journal.read_text(),'KEEP')

    def test_corrupt_plan_and_recovery_are_rejected_before_any_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plan.json';journal=Path(tmp)/'journal.json';sim=fixture()
            with sim.running() as endpoint:valid=manager(endpoint).plan(A,6).as_dict()
            changed=deepcopy(valid);changed['expected_after']['identities'][0]['serials']=[B]
            invalid=('{}','{"format":1,"format":2}','{"value":NaN}',json.dumps(changed))
            with patch('socket.socket',side_effect=AssertionError('Invalid recovery must never connect')):
                for data in invalid:
                    with self.subTest(data=data[:50]):
                        path.write_text(data);journal.write_text(data)
                        self.assertIn('error',self.invoke(['serial-address','apply',path,'--recovery',Path(tmp)/'new.json'],status=1))
                        self.assertIn('error',self.invoke(['serial-address','verify','--plan',path],status=1))
                        self.assertIn('error',self.invoke(['serial-address','verify','--recovery',journal],status=1))
                        self.assertFalse(Path(tmp,'new.json').exists())

    def test_destination_endpoint_and_timing_guards_fail_before_output_or_connection(self):
        with tempfile.TemporaryDirectory() as tmp,patch('socket.socket',side_effect=AssertionError('Invalid settings must never connect')):
            path=Path(tmp)/'plan.json';base=plan_args(('127.0.0.1',10001),path)
            cases=[['--source','254'],['--host','localhost'],['--port','0'],['--local-unit','6'],
                   ['--expected-local-serial','0.0'],['--max-bytes','0'],['--max-serial-frames','0'],
                   ['--quiet-period','.5'],['--address-response-timeout','.5']]
            for options in cases:
                with self.subTest(options=options):self.assertIn('error',self.invoke(base+options,status=1))
            for destination in ('0','255'):
                args=list(base);args[3]=destination
                with self.subTest(destination=destination):self.assertIn('error',self.invoke(args,status=1))
            self.assertFalse(path.exists())

    def test_parser_requires_identity_and_prevents_saved_plan_endpoint_overrides(self):
        defaults=cli.build_parser().parse_args(['serial-address','plan',A,'6','--host','127.0.0.1',
            '--local-unit','16','--expected-local-serial',LOCAL,'--output','new.json'])
        self.assertEqual((defaults.timeout,defaults.observation_timeout,defaults.confirmation_timeout,
            defaults.mmi_response_timeout,defaults.quiet_period,defaults.options_response_timeout,
            defaults.address_response_timeout),(600,10,2,5.5,2,2,2))
        self.assertEqual((defaults.max_mmi_frames,defaults.max_serial_frames,defaults.max_unrelated,defaults.max_bytes),(7,7,64,65536))
        cases=[['plan',A,'6','--host','127.0.0.1','--output','unused.json'],
               ['apply','unused.json','--recovery','new.json','--host','10.0.0.1'],
               ['verify','--plan','unused.json','--recovery','new.json'],['verify']]
        with patch('socket.socket',side_effect=AssertionError('Parser rejection must not connect')):
            for args in cases:
                output=io.StringIO()
                with self.subTest(args=args),redirect_stderr(output),self.assertRaises(SystemExit) as caught:
                    cli.main(['serial-address',*args])
                self.assertEqual(caught.exception.code,2);self.assertIn('error:',output.getvalue())

    def test_actual_main_cancelled_send_preserves_evidence_journal_and_never_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plan.json';journal=Path(tmp)/'journal.json';sim=fixture()
            with sim.running() as endpoint:
                plan=manager(endpoint).plan(A,6);path.write_text(json.dumps(plan.as_dict()))
                previous=len(requests(sim));first=KeyboardInterrupt('send interrupted')
                sock=FakeSocket(Clock(),send=first,close=SystemExit('close also interrupted'))
                with patch.object(PCISerialAddressTransport,'_make_socket',return_value=sock):
                    result=self.invoke(['serial-address','apply',path,'--recovery',journal],status=130)
                self.assertEqual(result['error'],'Interrupted');evidence=result['selected_serial_evidence']
                self.assertEqual(evidence,first.selected_serial_evidence);self.assertEqual(evidence['outcome'],'uncertain')
                self.assertTrue(evidence['send_attempted']);self.assertTrue(evidence['attempt_durability_verified'])
                self.assertIsNone(evidence['after']);self.assertEqual(evidence['exchange']['termination'],'interrupted')
                self.assertEqual([call for call in sock.calls if call[0]=='sendall'],[('sendall',CO_A)])
                self.assertFalse(any(call[0]=='recv' for call in sock.calls));self.assertEqual(sim.co_operations,[])
                self.assertEqual(len(requests(sim))-previous,6)  # Fresh inventory, local identity and options only.
                self.assertEqual(SelectedSerialCoordinator.load_recovery(journal).as_dict(),plan.as_dict())

    def test_oversized_or_nonserializable_error_evidence_retains_original_error_and_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plan.json';journal=Path(tmp)/'journal.json';sim=fixture()
            with sim.running() as endpoint:plan=manager(endpoint).plan(A,6)
            path.write_text(json.dumps(plan.as_dict()))
            for label,kind in (('object',KeyboardInterrupt),('oversized',RuntimeError),('huge_integer',RuntimeError),
                               ('secondary_export_interrupt',KeyboardInterrupt)):
                first=kind('original failure')
                first.selected_serial_evidence={'operation':'apply','state':'write_attempted','outcome':'uncertain',
                    'attempt_recorded':True,'send_attempted':10**5000 if label=='huge_integer' else None,
                    'journal':{'path':str(journal)},'raw':('x'*(17*1024*1024) if label=='oversized' else object())}
                export=(patch.object(cli,'_json_default',side_effect=KeyboardInterrupt('secondary export'))
                        if label=='secondary_export_interrupt' else nullcontext())
                with self.subTest(case=label),patch.object(SelectedSerialCoordinator,'apply',side_effect=first),export, \
                        patch('socket.socket',side_effect=AssertionError('Fake failure must not access network')):
                    result=self.invoke(['serial-address','apply',path,'--recovery',journal],status=130 if kind is KeyboardInterrupt else 1)
                self.assertEqual(result['error'],'Interrupted' if kind is KeyboardInterrupt else 'original failure')
                evidence=result['selected_serial_evidence'];self.assertFalse(evidence['evidence_export_complete'])
                self.assertIn('evidence_export_error',evidence);self.assertEqual(evidence['journal']['path'],str(journal))
                self.assertEqual(evidence['outcome'],'uncertain');self.assertNotIn('raw',evidence)
                if label=='secondary_export_interrupt':
                    self.assertEqual(evidence['evidence_export_error']['type'],'KeyboardInterrupt')
                    self.assertEqual(evidence['evidence_export_error']['message'],'secondary export')


if __name__=='__main__':unittest.main()
