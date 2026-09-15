"""Full inventory CLI over independent literal, sequential TCP exchanges."""
from contextlib import contextmanager
import json
import select
import socket
import subprocess
import sys
import threading
import unittest

from test_cli_pci_mmi import FIRST, MIDDLE, LAST
from test_cli_pci_serials import SERIAL_A, SERIAL_B

LOCAL = b'8D04FFFFFF000018A664A3B10005F7\r\n'
EMPTY_LAST = b'D6FFB0' + b'00'*20 + b'7B\r\n'
FULL = FIRST + MIDDLE + LAST
REQUESTS = [b'\\05FF00FAFF00g\r', b'\\4610002104g\r', b'\\46FF002104g\r', b'\\05FF00FAFF00g\r']
CHECKED = [b'\\05FF00FAFF0003g\r', b'\\461000210485g\r', b'\\46FF00210496g\r', b'\\05FF00FAFF0003g\r']


@contextmanager
def inventory_peer(responses):
    listener = socket.socket()
    listener.bind(('127.0.0.1',0)); listener.listen(1); listener.settimeout(6)
    state = {'requests':[], 'closed':0, 'errors':[]}
    def worker():
        try:
            for response in responses:
                with listener.accept()[0] as connection:
                    connection.settimeout(6)
                    request = b''
                    while not request.endswith(b'\r'):
                        chunk = connection.recv(1024)
                        if not chunk: raise AssertionError('Connection closed before its request')
                        request += chunk
                    state['requests'].append(request)
                    connection.sendall(b'g.' + response)
                    if connection.recv(1024): raise AssertionError('Observation reused a connection for another request')
                    state['closed'] += 1
        except Exception as error:
            state['errors'].append(str(error))
    thread = threading.Thread(target=worker,daemon=True); thread.start()
    try:
        yield listener.getsockname()[1], state
    finally:
        thread.join(7)
        extra = bool(select.select([listener],[],[],0)[0])
        listener.close()
        if thread.is_alive(): raise AssertionError('Inventory peer did not finish')
        if extra: raise AssertionError('Inventory opened an unplanned connection')


class PCIInventoryCLITests(unittest.TestCase):
    def cli(self, port, *args, status=0, fast=True, checked=False, local=True):
        global_args = ['--port',str(port)]
        if local: global_args += ['--local-unit','16']
        if checked: global_args += ['--checksum']
        if fast: global_args += ['--timeout','3']
        settings = ['--observation-timeout','.5','--confirmation-timeout','.2',
                    '--response-timeout','.2','--quiet-period','.05'] if fast else []
        process = subprocess.run([sys.executable,'-m','cbus_toolkit','pci',*global_args,
            'inventory',*settings,*map(str,args)],capture_output=True,text=True,timeout=12)
        self.assertEqual(process.returncode,status,process.stdout+process.stderr)
        return json.loads(process.stdout or process.stderr)

    def test_default_windows_and_complete_unique_inventory_use_four_fresh_connections(self):
        with inventory_peer([FULL,LOCAL,SERIAL_A,FULL]) as (port,state):
            result = self.cli(port,fast=False)
        self.assertEqual(state,{'requests':REQUESTS,'closed':4,'errors':[]})
        self.assertEqual(result['format'],'cbus-pci-inventory-observation-v1')
        self.assertEqual(result['status'],'complete')
        self.assertTrue(result['collection_complete'])
        self.assertTrue(result['membership_unchanged'])
        self.assertTrue(result['unique'])
        self.assertTrue(result['healthy'])
        self.assertEqual(result['request_count'],4)
        self.assertEqual(result['planned_addresses'],[16,255])
        self.assertEqual(result['unattempted_addresses'],[])
        self.assertEqual([r['serials'] for r in result['serial_observations']],[['100966.1187'],['101136.1558']])
        self.assertEqual(result['timing']['overall_timeout_seconds'],600)
        self.assertGreaterEqual(result['timing']['elapsed_seconds'],3.9)
        self.assertTrue(all(r['timing']['vendor_quiet_period'] for r in result['serial_observations']))
        self.assertFalse(result['atomic_snapshot'])
        self.assertFalse(result['authorizes_address_mutation'])
        self.assertFalse(result['physical_addresses_changed'])
        self.assertFalse(result['database_updated'])

    def test_duplicate_inventory_retains_all_serials_and_returns_nonzero(self):
        with inventory_peer([FULL,LOCAL,SERIAL_A+SERIAL_B,FULL]) as (port,state):
            result = self.cli(port,checked=True,status=1)
        self.assertEqual(state,{'requests':CHECKED,'closed':4,'errors':[]})
        self.assertEqual(result['status'],'duplicate_address')
        self.assertTrue(result['complete'])
        self.assertFalse(result['unique'])
        self.assertEqual(result['duplicate_addresses'],[255])
        self.assertEqual(result['serial_observations'][1]['serials'],['101136.1558','101136.1559'])
        self.assertEqual(result['timing']['overall_timeout_seconds'],3)
        self.assertEqual(result['automatic_retries'],0)

    def test_changed_membership_or_missing_final_range_preserves_completed_serials(self):
        for final, status in ((FIRST+MIDDLE+EMPTY_LAST,'inconsistent'),(FIRST+LAST,'incomplete')):
            with self.subTest(status=status), inventory_peer([FULL,LOCAL,SERIAL_A,final]) as (port,state):
                result = self.cli(port,status=1)
            self.assertEqual(state,{'requests':REQUESTS,'closed':4,'errors':[]})
            self.assertEqual(result['status'],status)
            self.assertFalse(result['complete'])
            self.assertEqual(len(result['serial_observations']),2)
            self.assertEqual(result['unattempted_addresses'],[])
            if status=='inconsistent':
                self.assertTrue(result['collection_complete'])
                self.assertFalse(result['membership_unchanged'])
                self.assertEqual(result['changed_states'],[{'address':255,'before':2,'after':0}])
            else:
                self.assertFalse(result['collection_complete'])
                self.assertIsNone(result['membership_unchanged'])
                self.assertEqual(result['final_mmi']['states'][88:],[None]*168)

    def test_incomplete_initial_scan_stops_and_invalid_limits_do_not_connect(self):
        with inventory_peer([FIRST+LAST]) as (port,state):
            result = self.cli(port,status=1)
        self.assertEqual(state,{'requests':REQUESTS[:1],'closed':1,'errors':[]})
        self.assertEqual(result['status'],'incomplete')
        self.assertEqual(result['serial_observations'],[])
        self.assertIsNone(result['final_mmi'])
        self.assertTrue(result['connection_closed'])
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); listener.listen(1)
            port=listener.getsockname()[1]
            self.assertIn('--local-unit',self.cli(port,local=False,status=1)['error'])
            self.assertIn('error',self.cli(port,'--max-serial-frames',0,status=1))
            self.assertIn('error',self.cli(port,'--max-mmi-frames',0,status=1))
            self.assertFalse(select.select([listener],[],[],0)[0])


if __name__=='__main__':
    unittest.main()
