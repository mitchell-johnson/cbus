"""Offline routing CLI literals, ambiguity, and rejection without connection."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from cbus_toolkit import cli


class RoutingCLITests(unittest.TestCase):
    def execute(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('cbus_toolkit.pci.PCIClient', side_effect=AssertionError('Unexpected PCI connection')) as client, \
                patch('socket.create_connection', side_effect=AssertionError('Unexpected network connection')) as connect, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = cli.main(arguments)
        client.assert_not_called()
        connect.assert_not_called()
        return status, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_original_route_literals_and_explicit_requested_intent(self):
        status, result = self.execute(['pci-route', 'encode', '--unit', '4', '--cal', '2104',
            '--bridge', '0x1E', '--bridge', '20', '--confirmation', 'g', '--checksum'])
        self.assertEqual(status, 0)
        self.assertEqual(result['wire_text'], '\\461E12140421044Dg\r')
        self.assertEqual(result['raw_hex'], '5C34363145313231343034323130343444670D')
        self.assertEqual(result['address_path'], [30,20,4])
        self.assertEqual(result['requested'], {'unit':4, 'bridges':[30,20], 'addressing':'direct'})
        self.assertFalse(result['io_performed'])
        self.assertFalse(result['command_sent'])
        self.assertFalse(result['logical_network_resolved'])
        self.assertFalse(result['programming_mode_inferred'])
        _, programmed = self.execute(['pci-route', 'encode', '--unit', '4', '--cal', '2104',
                                      '--bridge', '20', '--addressing', 'programming'])
        self.assertEqual(programmed['wire_text'], '\\46141204002104\r')
        self.assertEqual(programmed['requested']['addressing'], 'programming')

    def test_inspection_retains_zero_ambiguity_and_has_no_invented_intent(self):
        status, result = self.execute(['pci-route', 'inspect', '5C3436303430393030323130340D'])
        self.assertEqual(status, 0)
        self.assertEqual(result['wire_text'], '\\460409002104\r')
        self.assertEqual(result['address_path'], [4,0])
        self.assertEqual(result['route_count'], 1)
        for field in ('unit', 'source', 'requested'):
            self.assertNotIn(field, result)
        self.assertFalse(result['programming_mode_inferred'])
        self.assertFalse(result['io_performed'])

    def test_malformed_hex_cal_addresses_and_arguments_reject_before_run(self):
        valid = ['pci-route', 'encode', '--unit', '4', '--cal', '2104']
        cases = [valid+['--confirmation','f'], valid+['--bridge','256'], valid+['--bridge','9'*10000],
                 valid+['--bridge','1_0'],valid+['--bridge',' 1'],valid+['--bridge','\u0661'],
                 valid+['--addressing','guessed'], valid+['--host','127.0.0.1']]
        cases += [['pci-route','encode','--unit','4','--cal',value]
                  for value in ('', '210', '21 04', '21042104', 'FFFF', '1A0400', 'A'*66)]
        cases += [['pci-route','inspect',value] for value in ('', '5C0', '5C 0D', 'g0', '00'*88)]
        for arguments in cases:
            with self.subTest(arguments=arguments[:8]), patch.object(cli,'run') as run, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    cli.main(arguments)
                self.assertEqual(stopped.exception.code, 2)
                run.assert_not_called()

    def test_semantic_route_checksum_and_incoming_rejections_do_not_connect(self):
        cases = [['pci-route','encode','--unit','4','--cal','2104']+['--bridge','1']*7,
                 ['pci-route','encode','--unit','4','--cal','2104','--addressing','programming']+['--bridge','1']*6,
                 ['pci-route','inspect','5C3436313430393034323130343735670D','--checksum'],
                 ['pci-route','inspect','5C343630343031323130340D'],
                 ['pci-route','inspect','38363034313030303831303430300D']]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                status,result=self.execute(arguments)
                self.assertEqual(status,1)
                self.assertIn('error',result)
                self.assertNotIn('wire_text',result)

    def test_maximum_supported_command_is_inspectable_in_compact_json(self):
        arguments=['--compact','pci-route','encode','--unit','255','--cal','BFFF'+bytes(range(30)).hex(),
                   '--checksum','--confirmation','z']
        for bridge in range(6):arguments.extend(['--bridge',str(bridge)])
        status,result=self.execute(arguments)
        self.assertEqual(status,0)
        self.assertEqual(len(result['wire_text']),87)
        status,observed=self.execute(['pci-route','inspect',result['raw_hex'],'--checksum'])
        self.assertEqual(status,0)
        self.assertEqual(observed['cal_hex'],'BFFF'+bytes(range(30)).hex().upper())
        self.assertEqual(observed['address_path'],[0,1,2,3,4,5,255])
        self.assertFalse(observed['io_performed'])
