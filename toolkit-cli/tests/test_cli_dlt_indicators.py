"""Ordered classic DLT indicator controls through offline and database CLI routes."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cbus_toolkit import dlt_cli
from cbus_toolkit.cli import _programming, build_parser
from test_cli_dlt import snapshot
from test_cli_dlt_controls import cli
from test_dlt_indicators import fixture, session
from test_macros import NATIVE, NATIVE_REASON, closed_network_project, native_endpoint


def write_spec(folder):
    spec = fixture()
    root = ET.Element('UnitSpecification')
    ET.SubElement(root, 'Type').text = spec.unit_type
    parameters = ET.SubElement(root, 'Parameters')
    for parameter in spec.parameters.values():
        node = ET.SubElement(parameters, 'Param')
        for key, value in parameter.fields.items():
            ET.SubElement(node, key).text = value
    ET.ElementTree(root).write(Path(folder) / spec.filename, encoding='utf-8', xml_declaration=True)
    return spec


def native_args(*flags):
    parser = argparse.ArgumentParser()
    dlt_cli.native_options(parser.add_subparsers(dest='remote_action', required=True))
    return parser.parse_args(['dlt-labels', *map(str, flags)])


ORDERED_FLAGS = ('--indicator-control', 'page_fallback=yes', '--indicator-control', 'duration_seconds=5')
ORDERED_OPERATIONS = [{'control': 'page_fallback', 'value': True}, {'control': 'duration_seconds', 'value': 5}]


class IndicatorCliTests(unittest.TestCase):
    def test_argument_order_repeated_controls_and_explicit_types(self):
        args = native_args(*ORDERED_FLAGS, '--indicator-control', 'page_fallback=no',
                           '--indicator-control', 'pressed_level=0', '--indicator-control', 'nightlight_keys=yes')
        self.assertEqual(args.indicator_control, ORDERED_OPERATIONS + [
            {'control': 'page_fallback', 'value': False}, {'control': 'pressed_level', 'value': 0},
            {'control': 'nightlight_keys', 'value': True}])
        for name in ('pressed_enabled', 'nightlight_toggle', 'first_key_throwaway'):
            for text, value in (('yes', True), ('no', False)):
                self.assertIs(dlt_cli._indicator_control(name + '=' + text)['value'], value)
        for value in ('unknown=yes', 'page_fallback=1', 'pressed_enabled=true', 'nightlight_keys=YES',
                      'pressed_level=no', 'duration_seconds=-1', 'duration_seconds=1.0', 'page_fallback'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                dlt_cli._indicator_control(value)

    def test_offline_show_ordered_plan_bare_and_project_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            values = write_spec(folder).defaults()
            values.update(TimerDuration='0', EnablePageFallback='0')
            source = snapshot(folder, parameters=values)
            base = ('dlt', '--spec-dir', folder, 'indicators')
            shown = cli(*base, 'show', '--file', source)
            self.assertIn('page_fallback', shown['controls'])
            self.assertFalse(shown['controls']['page_fallback'])
            plan = cli(*base, 'plan', '--file', source, *ORDERED_FLAGS)
            self.assertEqual(plan['format'], 'cbus-classic-dlt-indicator-plan-v1')
            self.assertEqual(plan['requested'], ORDERED_OPERATIONS)
            self.assertEqual(plan['changes']['TimerDuration'], [5])
            self.assertEqual(plan['changes']['EnablePageFallback'], [1])
            self.assertFalse(plan['saved'] or plan['device_verified'])
            fallback = cli(*base, 'plan', '--file', source, '--indicator-control', 'page_fallback=yes')
            self.assertEqual(fallback['changes']['TimerDuration'], [15])
            refused = cli(*base, 'plan', '--file', source, '--indicator-control', 'duration_seconds=5',
                          '--indicator-control', 'page_fallback=yes', status=1)
            self.assertIn('disabled', refused['error'])
            bare = Path(folder) / 'bare.json'
            bare.write_text(json.dumps(values))
            self.assertEqual(cli(*base, 'show', '--file', bare, '--unit-type', 'KEYML5',
                                 '--firmware', '3.0.00')['controls'], shown['controls'])
            rows = ''.join(f'<PP Name="{key}" Value="{value}"/>' for key, value in values.items())
            project = Path(folder) / 'project.xml'
            project.write_text('<Installation><Project><Address>P1</Address><Network><Address>254</Address>'
                               '<Unit><Address>20</Address><UnitType>KEYBL5</UnitType>'
                               f'<FirmwareVersion>2.1.00</FirmwareVersion>{rows}</Unit></Network></Project></Installation>')
            self.assertEqual(cli(*base, 'show', '--project-xml', project, '--unit', '//P1/254/p/20')['controls'],
                             shown['controls'])
            self.assertIn('error', cli(*base, 'plan', '--file', source, status=1))
            for value in ('duration_seconds=1', 'duration_seconds=16', 'pressed_level=16'):
                with self.subTest(value=value):
                    self.assertIn('error', cli(*base, 'plan', '--file', source,
                                              '--indicator-control', 'page_fallback=yes',
                                              '--indicator-control', value, status=1))

    def test_native_mixed_options_refused_before_editor_and_physical_destinations_refused(self):
        for flags in (
                ('--show-indicators', '--show'), ('--show-indicators', '--show-display'),
                ('--show-indicators', '--plan', 'unused.json'), ('--show-indicators', *ORDERED_FLAGS),
                (*ORDERED_FLAGS, '--variant', '1=4'), (*ORDERED_FLAGS, '--block-dynamic-updates', 'yes'),
                (*ORDERED_FLAGS, '--indicator-mode', 'on'), (*ORDERED_FLAGS, '--show-clock', 'yes'),
                (*ORDERED_FLAGS, '--invert-display', 'yes'), (*ORDERED_FLAGS, '--show'),
                (*ORDERED_FLAGS, '--show-display'), (*ORDERED_FLAGS, '--plan', 'unused.json')):
            with self.subTest(flags=flags), patch.object(dlt_cli, '_editor') as editor:
                with self.assertRaisesRegex(ValueError, 'cannot be combined'):
                    dlt_cli.native(native_args(*flags), object())
                editor.assert_not_called()
        args = build_parser().parse_args([
            'cgate', 'unit', '--lock-address', '//P1/254', '--source', '/db//P1/254/p/20',
            '--destination', '//P1/254/p/20', 'dlt-labels', *ORDERED_FLAGS])
        with self.assertRaisesRegex(ValueError, 'database destinations'):
            _programming(args, object())

    def test_saved_plan_native_adapter_show_direct_apply_and_stale_refusal(self):
        from cbus_toolkit.dlt_indicators import ClassicDltIndicators
        with tempfile.TemporaryDirectory() as folder:
            spec = write_spec(folder)
            live = session()
            live.current.update(TimerDuration='0', EnablePageFallback='0')
            prefix = ('--spec-dir', folder)
            shown, edited = dlt_cli.native(native_args(*prefix, '--show-indicators'), live)
            self.assertFalse(edited)
            self.assertFalse(shown['controls']['page_fallback'])
            with self.assertRaisesRegex(ValueError, 'disabled'):
                dlt_cli.native(native_args(*prefix, '--indicator-control', 'duration_seconds=5'), live)
            self.assertEqual(live.calls, [])
            editor = ClassicDltIndicators(spec, live.unit_type)
            identity = (live.unit_type, live.firmware, live.catalog_number)
            plan = editor.plan(live.values(), operations=ORDERED_OPERATIONS, identity=identity).as_dict()
            path = Path(folder) / 'plan.json'
            path.write_text(json.dumps(plan))
            result, edited = dlt_cli.native(native_args(*prefix, '--plan', path), live)
            self.assertTrue(edited and result['verified'])
            self.assertFalse(result['saved'])
            self.assertEqual(live.current['TimerDuration'], '5')
            self.assertEqual(live.current['EnablePageFallback'], '1')
            with self.assertRaisesRegex(ValueError, 'changed since'):
                dlt_cli.native(native_args(*prefix, '--plan', path), live)
            direct, edited = dlt_cli.native(native_args(*prefix, '--indicator-control', 'duration_seconds=6'), live)
            self.assertTrue(edited and direct['verified'])
            self.assertEqual(live.current['TimerDuration'], '6')

    @unittest.skipUnless(NATIVE, NATIVE_REASON)
    def test_native_owned_database_dryrun_apply_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, 'DI') as project, tempfile.TemporaryDirectory() as folder:
            network = f'//{project}/254'
            path = network + '/p/20'
            NativeDatabase(client).create_unit(network, 20, 'DltIndicators', 'KEYML5', '2.1.00', catalog_number='5055DL')
            with Programmer(client).load(network, '/db' + path) as pp:
                pp.set('TimerDuration', '0')
                pp.set('EnablePageFallback', '0')
                pp.save_to_source()
            prefix = ('cgate', '--host', host, '--port', port, '--timeout', '30', 'unit',
                      '--lock-address', network, '--source', '/db' + path)
            source = Path(folder) / 'unit.json'
            cli(*prefix, 'export', source)
            before = cli(*prefix, 'dlt-labels', '--show-indicators')
            plan = cli('dlt', 'indicators', 'plan', '--file', source, *ORDERED_FLAGS)
            plan_file = Path(folder) / 'plan.json'
            plan_file.write_text(json.dumps(plan))
            preview = cli(*prefix, '--dry-run', 'dlt-labels', '--plan', plan_file)
            self.assertTrue(preview['verified'] and preview['raw_bytes_verified'])
            self.assertFalse(preview['saved'])
            self.assertEqual(cli(*prefix, 'dlt-labels', '--show-indicators'), before)
            applied = cli(*prefix, 'dlt-labels', '--plan', plan_file)
            self.assertTrue(applied['saved'])
            self.assertEqual(applied['changes']['TimerDuration'], [5])
            shown = cli(*prefix, 'dlt-labels', '--show-indicators')
            self.assertTrue(shown['controls']['page_fallback'])
            self.assertEqual(shown['controls']['duration_seconds'], 5)
            self.assertIn('changed since', cli(*prefix, 'dlt-labels', '--plan', plan_file, status=1)['error'])
            client.command('PROJECT SAVE ' + project)
            client.command('PROJECT CLOSE ' + project)
            client.command('PROJECT LOAD ' + project)
            client.command('PROJECT USE ' + project)
            self.assertEqual(cli(*prefix, 'dlt-labels', '--show-indicators')['controls'], shown['controls'])
            direct = cli(*prefix, 'dlt-labels', '--indicator-control', 'duration_seconds=6')
            self.assertTrue(direct['saved'])
            self.assertEqual(cli(*prefix, 'dlt-labels', '--show-indicators')['controls']['duration_seconds'], 6)
