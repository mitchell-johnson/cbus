"""Original C-Gate database save/reload for ordered classic DLT indicators."""
import hashlib
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.dlt_indicators import ClassicDltIndicators, OWNED
from cbus_toolkit.dlt_profiles import PROFILES
from cbus_toolkit.unitspec import UnitSpecStore
from test_dlt_labels import NATIVE_TYPES
from test_dlt_indicators import operations
from test_macros import NATIVE, NATIVE_REASON, closed_network_project, native_endpoint


@unittest.skipUnless(NATIVE, NATIVE_REASON)
class NativeIndicatorsTests(unittest.TestCase):
    def test_ordered_controls_preservation_and_complete_named_bytes_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        from research.local_cgate import JAR_SHA256
        store = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])
        report = {'format': 'cbus-classic-dlt-indicators-native-v1', 'passed': False,
                  'scope': 'Owned original C-Gate synthetic database units only',
                  'cgate_jar_sha256': JAR_SHA256, 'physical_hardware_verified': False,
                  'original_full_form_executed': False,
                  'specs': {name: hashlib.sha256((store.directory / name).read_bytes()).hexdigest()
                            for name in ('KEYL4.xml', 'KEYL5.xml', 'I_DLT.xml', 'I_NEOCORE.xml')}, 'cases': []}
        sequences = (
            (operations(('page_fallback', True)), 'ff86'),
            (operations(('pressed_enabled', True), ('pressed_level', 6), ('nightlight_keys', True),
                        ('first_key_throwaway', True), ('nightlight_toggle', True)), '6ffe'),
            (operations(('pressed_enabled', False), ('page_fallback', False)), '6f82'),
            (operations(('pressed_enabled', True), ('page_fallback', True),
                        ('page_fallback', False), ('pressed_enabled', False)), '6082'),
            (operations(('page_fallback', True), ('duration_seconds', 2), ('pressed_enabled', True),
                        ('pressed_level', 0), ('nightlight_toggle', True), ('first_key_throwaway', True)), '02de'),
        )
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, 'DN') as project:
            programmer, database = Programmer(client), NativeDatabase(client)
            report['greeting'] = client.greeting
            network = f'//{project}/254'
            finals = {}
            for index, (kind, firmware, catalog) in enumerate(NATIVE_TYPES):
                path = f'{network}/p/{20 + index}'
                database.create_unit(network, 20 + index, f'DltIndicators{index}', kind, firmware,
                                     catalog_number=catalog)
                editor = ClassicDltIndicators(store.load(PROFILES[kind].spec_filename), kind)
                case = {'unit_type': kind, 'firmware': firmware, 'catalog_number': catalog, 'steps': []}
                with programmer.load(network, '/db' + path) as pp:
                    pp.set_raw_data(0x33, bytes.fromhex('f0ff'))
                    baseline = pp.values()
                    for request, expected_hex in sequences:
                        result = editor.configure(pp, operations=request)
                        self.assertTrue(result['verified'] and result['raw_bytes_verified'])
                        self.assertEqual(result['raw_after_hex'], expected_hex)
                        self.assertEqual(bytes.fromhex(expected_hex)[1] & 0x82, 0x82)
                        self.assertEqual({k: v for k, v in pp.values().items() if k not in OWNED},
                                         {k: v for k, v in baseline.items() if k not in OWNED})
                        case['steps'].append({'operations': request, 'raw_before_hex': result['raw_before_hex'],
                                              'raw_after_hex': expected_hex, 'all_unowned_pp_preserved': True})
                    pp.save_to_source()
                    finals[path] = pp.values()
                report['cases'].append(case)
            client.command('PROJECT SAVE ' + project)
            client.command('PROJECT CLOSE ' + project)
            client.command('PROJECT LOAD ' + project)
            client.command('PROJECT USE ' + project)
            for path, expected in finals.items():
                with programmer.load(network, '/db' + path) as pp:
                    self.assertEqual(pp.values(), expected)
                    self.assertEqual(ClassicDltIndicators._raw_indicators(pp).hex(), '02de')
            report['all_pp_and_raw_bytes_save_close_reload_passed'] = True
            report['passed'] = True
        if os.environ.get('CBUS_DLT_INDICATORS_REPORT'):
            Path(os.environ['CBUS_DLT_INDICATORS_REPORT']).write_text(json.dumps(report, indent=2) + '\n')
