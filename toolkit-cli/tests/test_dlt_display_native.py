"""Owned original C-Gate database oracle for the three classic display controls."""
import hashlib
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.dlt_display import ClassicDltDisplay
from cbus_toolkit.dlt_profiles import PROFILES
from cbus_toolkit.unitspec import UnitSpecStore
from test_dlt_labels import NATIVE_TYPES
from test_macros import NATIVE, NATIVE_REASON, closed_network_project, native_endpoint


def raw_display(pp):
    return int(pp.get_raw_data(0x35, 1).lines[-1].split('RawData=', 1)[1], 16)


@unittest.skipUnless(NATIVE, NATIVE_REASON)
class NativeDisplayTests(unittest.TestCase):
    def test_explicit_controls_preserve_omitted_raw_three_neighbours_and_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        from research.local_cgate import JAR_SHA256
        store = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])
        report = {'format': 'cbus-classic-dlt-display-native-v1', 'passed': False,
                  'scope': 'Owned original C-Gate synthetic database units only',
                  'cgate_jar_sha256': JAR_SHA256,
                  'physical_hardware_verified': False, 'original_full_form_save_executed': False,
                  'specs': {name: hashlib.sha256((store.directory / name).read_bytes()).hexdigest()
                            for name in ('KEYL4.xml', 'KEYL5.xml', 'I_DLT.xml', 'I_NEOCORE.xml')}, 'cases': []}
        selections = (
            ({'invert_display': False}, 0xEF, {'InvertDisplay'}),
            ({'indicator_mode': 'on'}, 0xEE, {'IndicatorMode'}),
            ({'show_clock': True}, 0xCE, {'HideClock'}),
            ({'indicator_mode': 'off', 'invert_display': True, 'show_clock': False}, 0xFC,
             {'IndicatorMode', 'InvertDisplay', 'HideClock'}),
            ({'indicator_mode': 'normal', 'invert_display': False, 'show_clock': True}, 0xCD,
             {'IndicatorMode', 'InvertDisplay', 'HideClock'}),
            ({'indicator_mode': 'normal', 'invert_display': False, 'show_clock': True}, 0xCD,
             {'IndicatorMode', 'InvertDisplay', 'HideClock'}),
        )
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, 'DD') as project:
            database, programmer = NativeDatabase(client), Programmer(client)
            report['greeting'] = client.greeting
            network = f'//{project}/254'
            finals = {}
            for index, identity in enumerate(NATIVE_TYPES):
                kind, firmware, catalog = identity
                path = f'{network}/p/{20 + index}'
                database.create_unit(network, 20 + index, f'DltDisplay{index}', kind, firmware,
                                     catalog_number=catalog)
                editor = ClassicDltDisplay(store.load(PROFILES[kind].spec_filename), kind)
                case = {'unit_type': kind, 'firmware': firmware, 'catalog_number': catalog, 'steps': []}
                with programmer.load(network, '/db' + path) as pp:
                    # Both raw encodings 2 and 3 load as "on" in original Toolkit.
                    # All four non-owned bits are set, including unnamed bit7.
                    pp.set_raw_data(0x35, b'\xff')
                    self.assertEqual(int(pp.values()['IndicatorMode'], 0), 3)
                    for settings, expected_byte, owned in selections:
                        before, raw_before = pp.values(), raw_display(pp)
                        result = editor.configure(pp, settings=settings)
                        self.assertTrue(result['verified'] and result['raw_bytes_verified'])
                        self.assertFalse(result['saved'] or result['device_verified'])
                        self.assertEqual(raw_display(pp), expected_byte)
                        self.assertEqual(raw_display(pp) & 0xCC, 0xCC)
                        after = pp.values()
                        self.assertEqual({k: v for k, v in before.items() if k not in owned},
                                         {k: v for k, v in after.items() if k not in owned})
                        case['steps'].append({'settings': settings, 'raw_before': raw_before,
                                              'raw_after': expected_byte, 'all_other_pp_preserved': True})
                    pp.save_to_source()
                    finals[path] = (pp.values(), 0x4D)
                    case['staged_raw_byte'] = 0xCD
                    case['reloaded_raw_byte'] = 0x4D
                    case['unmodeled_bit7_persisted'] = False
                report['cases'].append(case)
            # Independent control: no display editor is involved. Original
            # C-Gate does not serialize the unnamed bit7 into database PP.
            raw_path = f'{network}/p/30'
            database.create_unit(network, 30, 'NativeRawControl', 'KEYML5', '2.1.00', catalog_number='5055DL')
            with programmer.load(network, '/db' + raw_path) as pp:
                pp.set_raw_data(0x35, b'\xff')
                self.assertEqual(raw_display(pp), 0xFF)
                pp.save_to_source()
                self.assertEqual(raw_display(pp), 0xFF)
                finals[raw_path] = (pp.values(), 0x7F)
            client.command('PROJECT SAVE ' + project)
            client.command('PROJECT CLOSE ' + project)
            client.command('PROJECT LOAD ' + project)
            client.command('PROJECT USE ' + project)
            for path, (expected, raw_expected) in finals.items():
                with programmer.load(network, '/db' + path) as pp:
                    self.assertEqual(pp.values(), expected)
                    self.assertEqual(raw_display(pp), raw_expected)
            report['all_named_pp_save_close_reload_passed'] = True
            report['native_no_editor_control'] = {'staged_raw_byte': 0xFF, 'reloaded_raw_byte': 0x7F,
                                                  'unmodeled_bit7_persisted': False}
            report['passed'] = True
        if os.environ.get('CBUS_DLT_DISPLAY_REPORT'):
            Path(os.environ['CBUS_DLT_DISPLAY_REPORT']).write_text(json.dumps(report, indent=2) + '\n')
