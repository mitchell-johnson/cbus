"""Direct-child ownership and cleanup faults, plus an isolated native process."""
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from research.local_cgate import LocalCGate
from cbus_toolkit.cgate import CGateClient


class Peer:
    def __init__(self,port,error=None):self.port=port;self.error=error;self.calls=0
    def getsockname(self):return ('127.0.0.1',self.port)
    def close(self):
        self.calls+=1
        if self.error:raise self.error


class Child:
    pid=84242
    def __init__(self):self.returncode=None;self.alive=True;self.calls=[]
    def poll(self):self.calls.append('poll');return None if self.alive else self.returncode
    def terminate(self):self.calls.append('terminate');self.alive=False;self.returncode=-15
    def kill(self):self.calls.append('kill');self.alive=False;self.returncode=-9
    def wait(self,timeout):
        self.calls.append(('wait',timeout))
        if self.alive:raise subprocess.TimeoutExpired('owned-java',timeout)
        return self.returncode


class LocalCGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.vendor=self.base/'vendor';self.vendor.mkdir()
        (self.vendor/'key').mkdir();(self.vendor/'key/cis.ks').write_bytes(b'owned dummy key')
        (self.vendor/'cgate.jar').write_bytes(b'owned fake jar');(self.vendor/'Projects').mkdir()
        (self.vendor/'Projects/EXISTING.xml').write_text('must remain unchanged')
        self.java=self.base/'bin/java';self.java.parent.mkdir();self.java.write_bytes(b'java fixture');self.java.chmod(0o700)
        (self.java.parent/'keytool').write_bytes(b'keytool');(self.java.parent/'keytool').chmod(0o700)
        self.pins=patch('research.local_cgate.JAR_SHA256',hashlib.sha256(b'owned fake jar').hexdigest());self.pins.start();self.addCleanup(self.pins.stop)
        self.version=patch('research.local_cgate.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','openjdk version "11.0.32.1"\n'))
        self.version.start();self.addCleanup(self.version.stop)
        self.which=patch('research.local_cgate.shutil.which',return_value='/owned/lsof');self.which.start();self.addCleanup(self.which.stop)

    def service(self,**kwargs):
        value=LocalCGate(self.vendor,java=self.java,**kwargs)
        self.addCleanup(lambda:shutil.rmtree(value.work,ignore_errors=True))
        self.addCleanup(value.close)
        return value

    def listing(self,value,**kwargs):
        output='p84242\n'+''.join('n127.0.0.1:'+str(port)+'\n' for port in value.ports)
        return subprocess.CompletedProcess([],kwargs.get('code',0),kwargs.get('stdout',output),kwargs.get('stderr',''))

    def test_new_directory_does_not_adopt_vendor_projects_and_closes_reservations(self):
        service=self.service(settings={'use-scenes':'yes','scene-base':'scene'})
        self.assertEqual(list((service.work/'tag').iterdir()),[]);self.assertFalse((service.work/'Projects').exists())
        self.assertIn('use-scenes=yes\n',(service.work/'config/C-GateConfig.txt').read_text())
        ports=service.ports.copy();report=service.close();self.assertTrue(report['cleanup_complete']);self.assertFalse(service.work.exists())
        for port in ports:
            with socket.socket() as peer:peer.bind(('127.0.0.1',port))
        self.assertEqual((self.vendor/'Projects/EXISTING.xml').read_text(),'must remain unchanged')
        with self.assertRaisesRegex(RuntimeError,'cannot be started'):service.start()

    def test_second_plain_bind_failure_releases_first_and_secure_sockets(self):
        peers=[Peer(port) for port in (40000,40001,40002,40003,41000)];error=OSError('second plain bind')
        with patch.object(LocalCGate,'_bind',side_effect=[*peers,error]):
            with self.assertRaises(OSError) as caught:LocalCGate(self.vendor,java=self.java)
        self.assertIs(caught.exception,error);self.assertEqual([peer.calls for peer in peers],[1]*5)
        self.assertTrue(error.local_cgate_report['cleanup_complete']);self.assertFalse(Path(error.local_cgate_report['work_directory']).exists())

    def test_bind_preserves_first_interrupt_when_socket_close_fails(self):
        first=KeyboardInterrupt('first');second=SystemExit('second');peer=Mock();peer.bind.side_effect=first;peer.close.side_effect=second
        with patch('research.local_cgate.socket.socket',return_value=peer):
            with self.assertRaises(KeyboardInterrupt) as caught:LocalCGate._bind(0)
        self.assertIs(caught.exception,first);self.assertEqual(first.local_cgate_cleanup_errors,(second,))

    def test_secure_reservation_collision_closes_only_attempt_then_reserves_fresh(self):
        failed=Peer(42000);group=[Peer(port) for port in (43000,43001,43002,43003,44000,44001)]
        with patch.object(LocalCGate,'_bind',side_effect=[failed,OSError('collision'),*group]):service=self.service()
        self.assertEqual(failed.calls,1);self.assertEqual(service.tls_port,43000);service.close()
        self.assertEqual([peer.calls for peer in group],[1]*6)

    def test_start_verifies_exact_direct_child_and_numeric_loopback(self):
        service=self.service();child=Child()
        with patch('research.local_cgate.subprocess.Popen',return_value=child),patch('research.local_cgate.subprocess.run',return_value=self.listing(service)) as lookup:
            self.assertIs(service.start(),service)
        self.assertTrue(service.report['listener_ownership_verified']);self.assertIn('-nP',lookup.call_args.args[0])
        self.assertIn('-Fpn',lookup.call_args.args[0]);self.assertTrue(service.close()['cleanup_complete'])
        before=child.calls.copy();self.assertIs(service.close(),service.report);self.assertEqual(child.calls,before)

    def test_start_rejects_foreign_pid_external_listener_and_inspection_failure(self):
        for variant in ('foreign','external','stderr'):
            with self.subTest(variant=variant):
                service=self.service();child=Child();listing=self.listing(service)
                if variant=='foreign':listing.stdout=listing.stdout.replace('p84242','p1')
                elif variant=='external':listing.stdout=listing.stdout.replace('127.0.0.1:','*:')
                else:listing.stderr='inspection failed'
                with patch('research.local_cgate.subprocess.Popen',return_value=child),patch('research.local_cgate.subprocess.run',return_value=listing):
                    with self.assertRaises(RuntimeError):service.start()
                self.assertFalse(service.report['listener_ownership_verified']);self.assertTrue(service.report['cleanup_complete'])

    def test_duplicate_or_incomplete_listener_inventory_times_out_and_cleans(self):
        service=self.service();child=Child();listing=self.listing(service);listing.stdout+='n127.0.0.1:'+str(service.port)+'\n'
        with patch('research.local_cgate.subprocess.Popen',return_value=child),patch('research.local_cgate.subprocess.run',return_value=listing),patch('research.local_cgate.time.monotonic',side_effect=[0,31]):
            with self.assertRaisesRegex(RuntimeError,'six reserved'):service.start()
        self.assertTrue(service.report['cleanup_complete'])

    def test_start_failure_preserves_original_despite_cleanup_interruption(self):
        service=self.service();first=KeyboardInterrupt('startup');second=SystemExit('cleanup')
        with patch('research.local_cgate.subprocess.Popen',side_effect=first),patch('research.local_cgate.shutil.rmtree',side_effect=second):
            with self.assertRaises(KeyboardInterrupt) as caught:service.start()
        self.assertIs(caught.exception,first);self.assertIn(second,first.local_cgate_cleanup_errors)
        self.assertFalse(service.report['cleanup_complete']);self.assertTrue(service.work.exists());self.assertTrue(service.closed)

    def test_log_open_and_clock_interruptions_are_inside_start_cleanup(self):
        for stage in ('log','clock'):
            service=self.service();first=KeyboardInterrupt(stage);child=Child()
            if stage=='log':
                with patch.object(Path,'open',side_effect=first):
                    with self.assertRaises(KeyboardInterrupt) as caught:service.start()
            else:
                with patch('research.local_cgate.subprocess.Popen',return_value=child),patch('research.local_cgate.time.monotonic',side_effect=first):
                    with self.assertRaises(KeyboardInterrupt) as caught:service.start()
            self.assertIs(caught.exception,first);self.assertTrue(service.report['cleanup_complete'])

    def test_unconfirmed_exit_retains_work_and_never_finalizes_it_on_gc(self):
        service=self.service();work=service.work;child=Child();service.process=child
        first=OSError('terminate');second=SystemExit('kill');child.terminate=Mock(side_effect=first);child.kill=Mock(side_effect=second)
        with self.assertRaises(OSError) as caught:service.close()
        self.assertIs(caught.exception,first);self.assertIn(second,first.local_cgate_cleanup_errors)
        self.assertFalse(service.report['cleanup_complete']);self.assertFalse(service.report['process_exit_confirmed']);self.assertTrue(work.exists())
        self.assertEqual(service.report['server_log_capture'],'deferred_process_alive')
        del service;gc.collect();self.assertTrue(work.exists())

    def test_cleanup_interruption_still_kills_child_and_preserves_first(self):
        service=self.service();child=Child();service.process=child;first=KeyboardInterrupt('wait')
        child.terminate=Mock();original_wait=child.wait;child.wait=Mock(side_effect=[first,-9])
        with self.assertRaises(KeyboardInterrupt) as caught:service.close()
        self.assertIs(caught.exception,first);self.assertIn('kill',child.calls);self.assertTrue(service.report['cleanup_complete'])

    def test_wait_timeout_uses_one_kill_and_confirms_exit(self):
        service=self.service();child=Child();service.process=child;child.terminate=Mock()
        self.assertTrue(service.close()['cleanup_complete']);self.assertEqual(child.calls.count('kill'),1)
        self.assertEqual([call for call in child.calls if isinstance(call,tuple)],[('wait',10),('wait',5)])

    def test_work_cleanup_failure_cannot_claim_complete(self):
        service=self.service();error=OSError('work cleanup')
        with patch('research.local_cgate.shutil.rmtree',side_effect=error):
            with self.assertRaises(OSError) as caught:service.close()
        self.assertIs(caught.exception,error);self.assertFalse(service.report['cleanup_complete']);self.assertTrue(service.report['process_exit_confirmed'])
        self.assertTrue(service.work.exists())

    def test_context_primary_survives_cleanup_failure_and_keys_are_not_exported(self):
        service=self.service();secret='GENERATED_PRIVATE_KEY_DATA';(service.work/'process.log').write_text('C-Gate is running.\n-----BEGIN PRIVATE KEY-----\n'+secret+'\n-----END PRIVATE KEY-----\n')
        first=ValueError('body');second=SystemExit('cleanup')
        with patch('research.local_cgate.shutil.rmtree',side_effect=second):service.__exit__(ValueError,first,None)
        self.assertEqual(first.local_cgate_cleanup_errors,(second,));self.assertNotIn(secret,json.dumps(service.report))
        self.assertEqual(service.report['server_log_tail'],['C-Gate is running.'])

    def test_preflight_rejects_runtime_jar_keytool_and_settings_before_temp_creation(self):
        for settings in ({'command-port':123},{'scene-base':'../external'},{'use-scenes':True}):
            with patch('research.local_cgate.tempfile.mkdtemp') as temporary:
                with self.assertRaises(ValueError):LocalCGate(self.vendor,java=self.java,settings=settings)
                temporary.assert_not_called()
        (self.java.parent/'keytool').chmod(0o600)
        with self.assertRaisesRegex(ValueError,'executable'):LocalCGate(self.vendor,java=self.java)


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA') and os.environ.get('CBUS_LOCAL_CGATE_VENDOR'),
                     'Select native Java and vendor for owned process acceptance')
class NativeLocalCGateTests(unittest.TestCase):
    def test_six_loopback_listeners_empty_projects_native_commands_and_cleanup(self):
        service=LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        with service:
            self.assertEqual(len(service.report['listeners']),6)
            self.assertTrue(all(value.startswith('127.0.0.1:') for value in service.report['listeners']))
            with CGateClient('127.0.0.1',service.port,timeout=10) as client:
                self.assertEqual(client.command('PROJECT LIST').lines,('124 no projects found',))
                client.command('PROJECT NEW OWNEDCHK');client.command('PROJECT SAVE OWNEDCHK')
                client.command('PROJECT CLOSE OWNEDCHK');client.command('PROJECT DELETE OWNEDCHK')
                self.assertEqual(client.command('PROJECT LIST').lines,('124 no projects found',))
        self.assertTrue(service.report['cleanup_complete']);self.assertFalse(service.work.exists())
        self.assertIsNotNone(service.process.returncode)
        output=os.environ.get('CBUS_LOCAL_CGATE_REPORT')
        if output:Path(output).write_text(json.dumps({'passed':True,'physical_networks_opened':False,**service.report},indent=2)+'\n')
