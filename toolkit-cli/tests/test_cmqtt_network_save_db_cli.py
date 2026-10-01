"""Complete materialized Network integrity and owned public CLI acceptance."""
from pathlib import Path
import copy
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from research.network_save_db_cli_acceptance import materialized_rows, repeated_save_identity, require_initial_projection


class MaterializedNetworkReceiptTests(unittest.TestCase):
    def document(self):
        def oid(n):
            return f'71000000-0000-4000-8000-{n:012d}'
        return ('<Installation><Project><TagName>LAB</TagName><Address>LAB</Address><Network>'
                f'<OID>{oid(1)}</OID><TagName>nCustomA</TagName><Address>CustomA</Address><NetworkNumber>0xff</NetworkNumber>'
                f'<Interface><OID>{oid(2)}</OID><InterfaceType>cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress>'
                f'<Property><OID>{oid(3)}</OID><Name>owned</Name><Value>yes</Value></Property></Interface>'
                '<Opaque><Original>retained</Original></Opaque></Network></Project></Installation>')

    def test_receipt_requires_complete_independent_address_and_ordered_property_identity(self):
        expected = {'CustomA': dict(type='cni', address='127.0.0.1:1', properties=[('owned', 'yes')])}
        source = self.document()
        first = materialized_rows(source, expected)
        self.assertIn('Opaque', first['CustomA']['xml'])
        bad = (source.replace('<NetworkNumber>0xff</NetworkNumber>', '<NetworkNumber>42</NetworkNumber>'),
               source.replace('<OID>71000000-0000-4000-8000-000000000002</OID>', ''),
               source.replace('8000-000000000003', '8000-000000000001'),
               source.replace('<InterfaceType>cni</InterfaceType>', '<InterfaceType>Cni</InterfaceType>'),
               source.replace('<Project>', '<Project><OID>71000000-0000-4000-8000-000000000001</OID>'),
               source.replace('</Network>', '</Network>' + ET.tostring(ET.fromstring(source).find('Project/Network'), encoding='unicode')),
               source.replace('<Value>yes</Value>', '<Value>no</Value>'))
        for text in bad:
            with self.subTest(text=text), self.assertRaises(AssertionError):
                materialized_rows(text, expected)

    def test_repeated_save_requires_stable_network_interface_and_rebuilt_property_oids(self):
        first = materialized_rows(self.document(), {'CustomA': dict(type='cni', address='127.0.0.1:1', properties=[('owned', 'yes')])})
        second = materialized_rows(self.document().replace('8000-000000000003', '8000-000000000004'),
                                   {'CustomA': dict(type='cni', address='127.0.0.1:1', properties=[('owned', 'yes')])})
        repeated_save_identity(first, second)
        for field in ('network_oid', 'interface_oid', 'property_oids'):
            wrong = copy.deepcopy(second)
            wrong['CustomA'][field] = first['CustomA'][field] if field == 'property_oids' else '71000000-0000-4000-8000-000000000099'
            with self.subTest(field=field), self.assertRaises(AssertionError):
                repeated_save_identity(first, wrong)
        changed = materialized_rows(self.document().replace('8000-000000000003', '8000-000000000004')
                                     .replace('<Original>retained</Original>', '<Original>lost</Original>'),
                                     {'CustomA': dict(type='cni', address='127.0.0.1:1', properties=[('owned', 'yes')])})
        with self.assertRaisesRegex(AssertionError, 'metadata'):
            repeated_save_identity(first, changed)

    def test_initial_projection_preserves_complete_baseline_metadata(self):
        baseline = ('<Installation><Project><TagName>LAB</TagName><Address>LAB</Address><Opaque>keep</Opaque>'
                    '</Project><Tail><Data>preserve</Data></Tail></Installation>')
        expected = ET.fromstring(baseline)
        schema = ET.Element('DBVersion'); schema.text = '2.3'; expected.insert(0, schema)
        network = ET.fromstring(self.document()).find('Project/Network')
        network.remove(network.find('Opaque'))
        expected.find('Project').append(network)
        after = ET.tostring(expected, encoding='unicode')
        facts = {'CustomA': dict(type='cni', address='127.0.0.1:1', properties=[('owned', 'yes')])}
        require_initial_projection(baseline, after, facts)
        for bad in (after.replace('<Opaque>keep</Opaque>', ''), after.replace('<Data>preserve</Data>', '<Data>lost</Data>')):
            with self.subTest(bad=bad), self.assertRaisesRegex(AssertionError, 'whole-project'):
                require_initial_projection(baseline, bad, facts)


@unittest.skipUnless(os.environ.get('CBUS_CMQTTD_BIN'), 'Select CBUS_CMQTTD_BIN for owned public SAVE DB materialization')
class OwnedNetworkSaveDBCLITests(unittest.TestCase):
    def test_public_cli_materializes_complete_rows_and_preserves_explicit_persistence_boundaries(self):
        from research.network_save_db_cli_acceptance import main
        with tempfile.TemporaryDirectory(prefix='owned-net-save-db-') as directory:
            output = Path(directory) / 'raw'
            arguments = ['--cmqttd-bin', os.environ['CBUS_CMQTTD_BIN'], '--python', sys.executable, '--output-dir', str(output)]
            if os.environ.get('CBUS_TOOLKIT_ACCEPTANCE_WHEEL'):
                arguments += ['--wheel', os.environ['CBUS_TOOLKIT_ACCEPTANCE_WHEEL']]
            self.assertEqual(main(arguments), 0)
            value = json.loads((output / 'acceptance.json').read_text())
            self.assertEqual(value['result'], 'passed')
            self.assertTrue(value['inputs_unchanged'])
            self.assertTrue(value['completed'])
            for flag in ('complete_runtime_rows_materialized', 'repeated_save_stable_roots_fresh_properties',
                         'explicit_project_save_boundary', 'project_save_close_load_preserves_complete_rows',
                         'direct_and_oid_network_reads_equal', 'offline_cli_preserves_native_rows',
                         'daemon_restart_preserves_complete_rows', 'named_oid_and_complete_xml_mutations_preserved',
                         'unselected_named_mutation_refused_without_change',
                         'oid_delete_and_fresh_rematerialization', 'explicit_project_isolation',
                         'copy_archive_repository_portable_transform_preserves_rows', 'mqtt_one_connection_per_owned_daemon',
                         'literal_pci_after_cleanup_verified'):
                self.assertTrue(value['flags'][flag], flag)
            self.assertEqual(value['cni_trap_connections'], 0)
            self.assertTrue(value['serial_path_absent'])
            self.assertFalse(value['serial_open_syscalls_assessed'])
            self.assertTrue(all(value['pci_unchanged_per_session']))
            self.assertTrue(all(row['process_cleanup_verified'] for row in value['backend']['processes']))
            self.assertTrue(value['backend']['broker']['cleanup_verified'])


if __name__ == '__main__':
    unittest.main()
