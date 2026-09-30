"""Toolkit client-side conversion tweakers: registry receipt, model and native acceptance."""
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit import toolkit_conversion_tweakers as tweakers
from cbus_toolkit.toolkit_conversion_tweakers import (ASSIGNMENTS, NO_TWEAKER, REFUSALS, REGISTRY,
                                                      ToolkitTweakerConversion, TweakerRefused, admitted,
                                                      plan_writes, staged)


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'research/fixtures/toolkit-conversion-tweaker-registry.json'
ADMITTED = [('DIMDN8', 'DIMDU4'), ('DIMDN8F', 'DIMDU4'), ('DIMDN4', 'DIMDU4'), ('DIMDN4F', 'DIMDU4'),
            ('DIMDU4', 'DIMDN8'), ('DIMDU4', 'DIMDN8F'), ('DIMDU4', 'DIMDN4'), ('DIMDU4', 'DIMDN4F')]


def receipt():
    return json.loads(RECEIPT.read_text(encoding='utf-8'))


class Parameter:
    def __init__(self, kind, size):
        self.type, self.array_size = kind, size


class NoIO:
    def command(self, *_args, **_kwargs):
        raise AssertionError('refusal must happen before any C-Gate I/O')

    command_document = command


class ReceiptTests(unittest.TestCase):
    def test_receipt_is_consistent_and_sanitized(self):
        import sys
        sys.path.insert(0, str(ROOT / 'research'))
        from toolkit_conversion_tweaker_registry import validate
        data = receipt()
        self.assertEqual(validate(data), [])
        self.assertEqual(data['registration_count'], 292)
        self.assertFalse(data['original_code_executed'])
        self.assertFalse(data['toolkit_semantics']['uses_cgate_convertunit'])

    def test_module_registry_and_reasons_match_receipt(self):
        data = receipt()
        expected = {}
        for row in data['registrations']:
            expected.setdefault((row['source'].upper(), row['target'].upper()), row['tweaker_class'])
        self.assertEqual(dict(REGISTRY), expected)
        for name, spec in data['classes'].items():
            self.assertEqual(REFUSALS[name], spec['refusal'], name)
        self.assertEqual(set(REFUSALS), set(data['classes']))
        admitted_rows = {(row['source'], row['target']) for row in data['registrations'] if row['decision'] == 'admitted'}
        self.assertEqual(admitted_rows, set(ADMITTED))
        for name, rules in ASSIGNMENTS.items():
            recorded = [(rule['target'], 'literal' if 'literal' in rule else 'from', rule.get('literal', rule.get('from')))
                        for rule in data['classes'][name]['assignments']]
            self.assertEqual(list(rules), recorded)
        for agent in data['agents'].values():
            for unit_type in agent['unit_types']:
                self.assertEqual([list(item) for item in tweakers.AGENT_ATTRIBUTES[unit_type]], agent['attributes'])


class ModelTests(unittest.TestCase):
    def test_every_other_registered_class_and_unregistered_pair_is_refused_before_io(self):
        data = receipt()
        for row in data['registrations']:
            if row['decision'] == 'admitted':
                self.assertEqual(admitted(row['source'].lower(), row['target']), row['tweaker_class'])
                continue
            with self.subTest(pair=(row['source'], row['target'])):
                with self.assertRaises(TweakerRefused) as error:
                    ToolkitTweakerConversion(NoIO(), row['source'], None, row['target'], None)
                self.assertEqual(error.exception.reason, row['refusal_reason'])
                self.assertEqual(error.exception.tweaker_class, row['tweaker_class'])
        for source, target in (('DIMDN8', 'DIMDN4'), ('DIMDU4', 'DIMDU4'), ('KEYM4', 'KEY4')):
            with self.assertRaises(TweakerRefused) as error:
                ToolkitTweakerConversion(NoIO(), source, None, target, None)
            self.assertEqual(error.exception.reason, NO_TWEAKER)

    def test_dimdn_to_dimdu4_rules_and_pp_set_gate(self):
        source = {'Application': '0x38 0xff', 'UnitName': 'SRC', 'MaxDimmingLevel': '0x1 0x2 0x3 0x4 0x5',
                  'PowerUpDelay': '0x9 0x9', 'InterLockingChannel': '0x2', 'SerialNo': '0x1 0x2 0x3 0x4',
                  'UnitAddress': '0x14', 'Project': 'TEST'}
        native = {'Application', 'UnitName', 'MaxDimmingLevel', 'PowerUpDelay', 'InterLockingChannel', 'SerialNo',
                  'UnitAddress', 'Project', 'ErrorMode'}
        plan = plan_writes('DIMDN8', 'DIMDU4', source, native)
        writes = {name: (value, origin) for name, value, origin in plan.writes}
        self.assertEqual(writes['InterLockingChannel'], ('4', 'literal'))
        self.assertEqual(writes['PowerUpDelay'], ('0x1 0x2 0x3 0x4 0x5', 'moved from MaxDimmingLevel'))
        self.assertEqual(writes['MaxDimmingLevel'], ('0 0 0 0', 'literal'))
        self.assertEqual(writes['UnitAddress'], ('0x14', 'copied'))
        self.assertEqual([name for name, _, _ in plan.writes][:4], ['Application', 'Project', 'UnitAddress', 'UnitName'])
        self.assertEqual(plan.not_written['SerialNo'], 'initially immutable agent attribute')
        self.assertIn('no source agent attribute', plan.not_written['ErrorMode'])
        self.assertIn('empty source value', plan.not_written['GroupAddress'])
        reverse = {name: value for name, value, _ in plan_writes('DIMDU4', 'DIMDN4', source, native).writes}
        self.assertEqual((reverse['InterLockingChannel'], reverse['MaxDimmingLevel'], reverse['PowerUpDelay']),
                         ('0', '0x9 0x9', '0 0 0 0'))

    def test_empty_source_value_stays_immutable_after_an_assignment(self):
        plan = plan_writes('DIMDN4', 'DIMDU4', {'MaxDimmingLevel': '0x1', 'InterLockingChannel': ''},
                           {'MaxDimmingLevel', 'PowerUpDelay', 'InterLockingChannel'})
        self.assertNotIn('InterLockingChannel', [name for name, _, _ in plan.writes])

    def test_native_pp_set_array_rule(self):
        self.assertEqual(staged(Parameter('int', 4), '0xff 0xff 0xff 0xff', '1 2 3 4 5 6'), (1, 2, 3, 4))
        self.assertEqual(staged(Parameter('int', 4), '0xff 0xff 0xff 0xff', '9 8'), (9, 8, 255, 255))
        self.assertEqual(staged(Parameter('sixbit', 8), 'NEWUNIT ', 'abc'), 'ABC     ')


SPECS = os.environ.get('CBUS_UNITSPEC_DIR')
VENDOR = os.environ.get('CBUS_LOCAL_CGATE_VENDOR')


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA') and SPECS and VENDOR,
                     'set CBUS_CGATE_JAVA, CBUS_LOCAL_CGATE_VENDOR and CBUS_UNITSPEC_DIR for native tweaker acceptance')
class NativeToolkitTweakerTests(unittest.TestCase):
    def test_admitted_pairs_match_the_model_and_persist(self):
        from research.convertunit_pairs import Inputs, Runner, owned_backend
        specs, catalog = Path(SPECS), Path(VENDOR) / 'unitspec/cbusunits.xml'
        inputs = Inputs(specs, catalog, specs / 'ConvertUnitMappingTable.xml')
        report = {'format': 'cbus-toolkit-conversion-tweaker-native-v1', 'cases': []}
        with owned_backend('native', spec_dir=specs, catalog_path=catalog, table_path=None, vendor=VENDOR,
                           java=os.environ['CBUS_CGATE_JAVA']) as (client, backend):
            report['backend'] = backend
            runner = Runner(client, inputs)
            runner.open()
            try:
                # Pin the native PP SET array behaviour that the model relies on.
                probe, _ = runner.make_unit('DIMDU4', 1)
                with runner.programmer.load(runner.network, '/db' + probe) as session:
                    session.set('PowerUpDelay', '1 2 3 4 5 6 7 8')
                    session.set('MaxDimmingLevel', '9 8')
                    values = session.values()
                current = {name: tweakers._numbers(values[name]) for name in ('PowerUpDelay', 'MaxDimmingLevel')}
                self.assertEqual(current['PowerUpDelay'], (1, 2, 3, 4))
                self.assertEqual(current['MaxDimmingLevel'][:2], (9, 8))
                results = []
                for index, (source_type, target_type) in enumerate(ADMITTED):
                    with self.subTest(pair=(source_type, target_type)):
                        source, rejected = runner.make_unit(source_type, 1 + index % 2)
                        self.assertEqual(rejected, [])
                        with runner.programmer.load(runner.network, '/db' + source) as session:
                            before = session.values()
                        catalog_number, firmware, _ = inputs.revision(target_type)
                        converter = ToolkitTweakerConversion(client, source_type, inputs.spec(source_type),
                                                             target_type, inputs.spec(target_type))
                        result = converter.apply(source, 100 + index, target_firmware=firmware,
                                                 target_catalog=catalog_number)
                        self.assertEqual(result['failed_writes'], {})
                        with runner.programmer.load(runner.network, '/db' + result['target']) as session:
                            after = session.values()
                        # Independent spot checks of the recovered tweaker rules.
                        size = inputs.spec(target_type).parameters['PowerUpDelay'].array_size
                        if target_type == 'DIMDU4':
                            self.assertEqual(tweakers._numbers(after['InterLockingChannel']), (4,))
                            self.assertEqual(tweakers._numbers(after['MaxDimmingLevel']), (0,) * size)
                            self.assertEqual(tweakers._numbers(after['PowerUpDelay']),
                                             tweakers._numbers(before['MaxDimmingLevel'])[:size])
                        else:
                            self.assertEqual(tweakers._numbers(after['InterLockingChannel']), (0,))
                            self.assertEqual(tweakers._numbers(after['PowerUpDelay'])[:4], (0, 0, 0, 0))
                            self.assertEqual(tweakers._numbers(after['MaxDimmingLevel'])[:4],
                                             tweakers._numbers(before['PowerUpDelay'])[:4])
                        self.assertEqual(after['UnitName'].strip(), before['UnitName'].strip())
                        self.assertEqual(tweakers._numbers(after['GroupAddress'])[:8],
                                         tweakers._numbers(before['GroupAddress'])[:8])
                        with runner.programmer.load(runner.network, '/db' + source) as session:
                            self.assertEqual(session.values(), before)
                        results.append((result['target'], after))
                        report['cases'].append({'source_type': source_type, 'target_type': target_type,
                                                'tweaker_class': result['tweaker_class'],
                                                'writes': len(result['plan']['writes']),
                                                'verified_parameters': result['verified_parameters'],
                                                'passed': True})
                runner.projects.operation('save', runner.project)
                runner.projects.operation('close', runner.project)
                runner.projects.operation('load', runner.project)
                runner.projects.operation('use', runner.project)
                client.command('NET LOAD DB')
                for target, after in results:
                    with runner.programmer.load(runner.network, '/db' + target) as session:
                        self.assertEqual(session.values(), after)
                report['project_reload_cases'] = len(results)
                with self.assertRaises(TweakerRefused):
                    ToolkitTweakerConversion(client, 'RELDN8', None, 'RELDN4', None)
            finally:
                runner.close()
        report['passed'] = len(report['cases']) == len(ADMITTED)
        if os.environ.get('CBUS_TWEAKER_REPORT'):
            Path(os.environ['CBUS_TWEAKER_REPORT']).write_text(json.dumps(report, indent=2) + '\n')
        self.assertTrue(report['passed'])


if __name__ == '__main__':
    unittest.main()
