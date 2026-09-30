"""Offline thermostat Load Template rules with synthetic specifications."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.thermostat_templates import (FAMILIES, PROGRAMMABLE_ONLY, ThermostatTemplateCatalog,
                                               NativeThermostatTemplates, NativeThermostatTemplateError,
                                               ThermostatTemplateError, compare_overlay,
                                               family_for_unit_type, plan_overlay)


def _param(name, address, default, maximum='$FF', kind='int', extra=''):
    return (f'<Param><Name>{name}</Name><Type>{kind}</Type><ProgramMethod>sgiu</ProgramMethod>'
            f'<Address>{address}</Address><Protection>none</Protection><MinValue>$00</MinValue>'
            f'<MaxValue>{maximum}</MaxValue><DefaultValue>{default}</DefaultValue>{extra}</Param>')


def _spec(kind, params, include=None):
    includes = f'<Includes><Include>{include}</Include></Includes>' if include else ''
    return ('(C) CLIPSAL INTEGRATED SYSTEMS 2003 all rights reserved\n<?xml version="1.0"?>'
            f'<UnitSpecification><Type>{kind}</Type><MinVersion>0</MinVersion><MaxVersion>9</MaxVersion>'
            f'<Description>Synthetic {kind}</Description>{includes}<Parameters>{"".join(params)}'
            '</Parameters></UnitSpecification>')


class ThermostatTemplateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        common = [_param('ZoneA', '$105', '$01', '$1F'), _param('ZoneB', '$10B', '$01', '$1F'),
                  _param('Other', '$120', '5')]
        self.write('THERMOSTATB.xml', _spec('THERMOSTATB', common + [_param('TimerEnable', '$111', '1')]))
        self.write('THERMOSTATA.xml', _spec('THERMOSTATA', common + [_param('NonEvap', '$110', '0')]))
        for number in range(1, 10):
            basic = f'THERMOSTAT_TEMPLATE{number:02d}.xml'
            self.write(basic, _spec('THERMOSTAT', [_param('ZoneA', '$105', str(number), '$FF'),
                                                   _param('ZoneB', '$10B', '$03')]))
            self.write(f'THERMOSTATA_TEMPLATE{number:02d}.xml',
                       _spec('THERMOSTATA', [_param('ZoneB', '$10B', '$07'), _param('NonEvap', '$110', '1')],
                             include=basic))
        self.catalog = ThermostatTemplateCatalog(self.root)

    def write(self, name, text):
        (self.root / name).write_text(text, encoding='utf-8')

    def test_original_offer_table_and_family_mapping(self):
        self.assertEqual(FAMILIES['programmable']['offered'], tuple(range(1, 10)))
        self.assertEqual(FAMILIES['basic']['offered'], (1, 4, 5, 6, 8, 9))
        self.assertEqual(PROGRAMMABLE_ONLY, (2, 3, 7))
        rows = self.catalog.listing()
        self.assertEqual(sum(row['offered_by_original'] for row in rows), 15)
        for unit_type, family in (('PC_TSA', 'programmable'), ('PC_TSA5', 'programmable'),
                                  ('PC_TSB', 'basic'), ('PC_TSB5', 'basic')):
            self.assertEqual(family_for_unit_type(unit_type), family)
        for unit_type in ('THERMOSTAT', 'THERMOSTATA', 'KEY4', 'pc_tsa', None):
            with self.assertRaises(ThermostatTemplateError):
                family_for_unit_type(unit_type)
        for number in PROGRAMMABLE_ONLY:
            with self.assertRaisesRegex(ThermostatTemplateError, 'not offered'):
                self.catalog.load('basic', number)
        for number in (0, 10, True, '1'):
            with self.assertRaises(ThermostatTemplateError):
                self.catalog.load('programmable', number)

    def test_programmable_template_inherits_and_overrides_basic_template(self):
        template = self.catalog.load('programmable', 4)
        self.assertEqual(dict(template.values), {'ZoneA': 4, 'ZoneB': 7, 'NonEvap': 1})
        self.assertEqual(dict(self.catalog.load('basic', 4).values), {'ZoneA': 4, 'ZoneB': 3})

    def test_overlay_plan_changes_only_template_parameters(self):
        template = self.catalog.load('basic', 5)
        snapshot = {'ZoneA': '0x1', 'ZoneB': '3', 'Other': '0x9', 'TimerEnable': '0x1'}
        overlay = plan_overlay(template, 'PC_TSB5', '5.4.01', snapshot)
        self.assertEqual(overlay.changes, (('ZoneA', 1, 5),))
        document = overlay.as_dict()
        self.assertEqual(document['unchanged_template_parameters'], ['ZoneB'])
        self.assertEqual(document['preserved_parameter_count'], 2)
        self.assertFalse(document['reset_before_load'])
        self.assertFalse(document['original_post_load_adjustments_replayed'])
        good = dict(snapshot, ZoneA='0x5')
        self.assertEqual(compare_overlay(overlay, good), {'template_mismatches': [], 'unrelated_changes': []})
        self.assertEqual(compare_overlay(overlay, dict(good, Other='0x8', ZoneB='0x2')),
                         {'template_mismatches': ['ZoneB'], 'unrelated_changes': ['Other']})
        self.assertEqual(compare_overlay(overlay, {k: v for k, v in good.items() if k != 'Other'})
                         ['unrelated_changes'], ['Other'])

    def test_incompatible_type_firmware_and_snapshots_are_refused(self):
        programmable = self.catalog.load('programmable', 1)
        snapshot = {'ZoneA': '0x1', 'ZoneB': '0x1', 'Other': '0x5', 'NonEvap': '0x0'}
        for unit_type in ('PC_TSB', 'PC_TSB5', 'KEY4'):
            with self.assertRaises(ThermostatTemplateError):
                plan_overlay(programmable, unit_type, '5.4.01', snapshot)
        for firmware in ('10.0', '', 'x'):
            with self.assertRaises(ThermostatTemplateError):
                plan_overlay(programmable, 'PC_TSA', firmware, snapshot)
        for broken in ({'ZoneA': '0x1', 'ZoneB': '0x1'}, dict(snapshot, ZoneA='0x100'),
                       dict(snapshot, ZoneA='one'), dict(snapshot, ZoneA=1)):
            with self.assertRaises(ThermostatTemplateError):
                plan_overlay(programmable, 'PC_TSA', '5.4.01', broken)

    def test_malformed_template_specifications_are_refused(self):
        cases = (
            ('THERMOSTATB.xml', _spec('THERMOSTATB', [_param('ZoneA', '$105', '1'), _param('ZoneB', '$10B', '1'),
                                                      _param('Alias', '$105', '0', kind='bit',
                                                             extra='<BitAddress>2</BitAddress>')])),
            ('THERMOSTATB.xml', _spec('THERMOSTATB', [_param('ZoneA', '$106', '1'), _param('ZoneB', '$10B', '1')])),
            ('THERMOSTATB.xml', _spec('THERMOSTATB', [_param('ZoneA', '$105', '0', '$00'),
                                                      _param('ZoneB', '$10B', '1')])),
            ('THERMOSTAT_TEMPLATE01.xml', _spec('THERMOSTATB', [_param('ZoneA', '$105', '1')])),
        )
        for name, text in cases:
            with self.subTest(name=name, text=text[-160:]):
                self.setUp()
                self.write(name, text)
                with self.assertRaises(ThermostatTemplateError):
                    ThermostatTemplateCatalog(self.root).load('basic', 1)
        with self.assertRaises(ThermostatTemplateError):
            ThermostatTemplateCatalog(None)

    def test_cli_list_is_offline(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), \
                patch('socket.create_connection', side_effect=AssertionError('Unexpected network')):
            code = cli.main(['thermostat', 'template', 'list', '--unit-type', 'PC_TSB',
                             '--spec-dir', str(self.root)])
        self.assertEqual(code, 0, stderr.getvalue())
        result = json.loads(stdout.getvalue())
        self.assertEqual([row['number'] for row in result['templates'] if row['offered_by_original']],
                         [1, 4, 5, 6, 8, 9])
        self.assertIn('post-load', result['scope'])
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(['thermostat', 'template', 'preview', '//P/254/p/4', '--template', '2',
                             '--host', '127.0.0.1', '--spec-dir', str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn('--exclusive-project', json.loads(stderr.getvalue())['error'])

    def test_group_sort_requires_post_load_before_network_access(self):
        template = self.catalog.load('programmable', 1)
        with self.assertRaisesRegex(ThermostatTemplateError, 'requires post-load'):
            plan_overlay(template, 'PC_TSA', '5.4.01', {}, group_sort='address-ascending')
        for application in (172, 203):
            with self.assertRaisesRegex(ThermostatTemplateError, 'zone/remote applications'):
                plan_overlay(template, 'PC_TSA', '5.4.01', {}, groups={}, application=application,
                             group_sort='address-ascending')
        manager = NativeThermostatTemplates(object(), self.catalog)
        for options in ({'group_sort': True}, {'group_sort': 'tag'},
                        {'group_sort': 'address-ascending', 'post_load': False}):
            with self.assertRaises(NativeThermostatTemplateError) as caught:
                manager.plan('//P/254/p/4', 1, exclusive_project=True, **options)
            self.assertIsInstance(caught.exception.cause, ThermostatTemplateError)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), \
                patch('socket.create_connection', side_effect=AssertionError('Unexpected network')):
            code = cli.main(['thermostat', 'template', 'preview', '//P/254/p/4', '--template', '9',
                             '--host', '127.0.0.1', '--spec-dir', str(self.root), '--exclusive-project',
                             '--overlay-only', '--group-sort', 'address-ascending'])
        self.assertEqual(code, 1)
        self.assertIn('requires post-load', json.loads(stderr.getvalue())['error'])


if __name__ == '__main__':
    unittest.main()
