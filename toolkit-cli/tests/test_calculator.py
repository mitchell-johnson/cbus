"""Independent arithmetic fixtures and opt-in native database differential tests."""
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.calculator import CalculatorCatalog, CalculatorError, CalculatorUnit


LIMITS = '<Calculator><MinImpedance>400</MinImpedance><MaxImpedance>1500</MaxImpedance><MaxSupplyCurrent>2000</MaxSupplyCurrent></Calculator>'


def row(catalog, drawn=0, supplied=0, impedance=100000, extra=''):
    return (f'<Unit><CatalogNumber>{catalog}</CatalogNumber><CurrentDrawn>{drawn}</CurrentDrawn>'
            f'<CurrentSupplied>{supplied}</CurrentSupplied><Impedance>{impedance}</Impedance>{extra}</Unit>')


class CalculatorTests(unittest.TestCase):
    def catalog(self, rows, limits=LIMITS):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'cbusunits.xml'
        path.write_text('<CBusUnits>' + limits + '<Units>' + rows + '</Units></CBusUnits>')
        return CalculatorCatalog.load(path)

    def test_parallel_impedance_currents_and_catalog_identity(self):
        catalog = self.catalog(row('KEY', 18, impedance=110000) + row('BURDEN', impedance=1000) + row('PS', supplied=350, impedance=20000))
        result = catalog.calculate([CalculatorUnit('KEY', 'KEY4'), CalculatorUnit('BURDEN', 'BURDEN'), CalculatorUnit('PS', 'POWER')])
        self.assertEqual(result.native_values(), {'result': 'OK', 'current_supply(mA)': 350, 'current_consumption(mA)': 18,
                         'impedance(ohms)': 944.0, 'units_calculated': 3, 'units_not_calculated': 0})
        self.assertAlmostEqual(result.exact_impedance_ohms, 1 / (1/110000 + 1/1000 + 1/20000))
        self.assertTrue(result.passed)
        self.assertEqual(len(result.catalog_sha256), 64)

    def test_lookup_last_duplicate_alias_longest_prefix_and_case(self):
        catalog = self.catalog(row('AB*', 1) + row('ABC*', 2) + row('ABC', 3) + row('OTHER', 4, extra='<AlternativeCatalogNumbers>ABC; ALIAS</AlternativeCatalogNumbers>') + row('*', 99))
        result = catalog.calculate([CalculatorUnit(number, 'ANY') for number in ('ABZ', 'ABCD', 'ABC', ' ALIAS', 'ALIAS', 'abc', 'XYZ')])
        self.assertEqual((result.current_consumption_ma, result.units_calculated, result.units_not_calculated), (11, 4, 3))
        self.assertFalse(result.passed)
        self.assertEqual(catalog.calculate([CalculatorUnit('*', 'ANY')]).current_consumption_ma, 99)

    def test_subunits_replace_parent(self):
        catalog = self.catalog(row('PARENT', 99, extra='<SubUnits>' + row('CHILD', 7) + '</SubUnits>'))
        result = catalog.calculate([CalculatorUnit('PARENT', 'ANY'), CalculatorUnit('CHILD', 'ANY')])
        self.assertEqual((result.current_consumption_ma, result.units_calculated, result.units_not_calculated), (7, 1, 1))

    def test_switchable_uses_type_set_and_only_one_current(self):
        switchable = '<CurrentDrawnSwitchablePowerSupply>20</CurrentDrawnSwitchablePowerSupply><CurrentSuppliedSwitchablePowerSupply>200</CurrentSuppliedSwitchablePowerSupply><FirmwareRevisions><Revision><UnitType>SWITCH</UnitType></Revision></FirmwareRevisions>'
        catalog = self.catalog(row('SW', 88, 99, extra=switchable) + row('NORMAL', 7, 8))
        inputs = [CalculatorUnit('SW', 'SWITCH', switchable_supply_enabled=True), CalculatorUnit('SW', 'SWITCH'), CalculatorUnit('SW', 'switch'), CalculatorUnit('NORMAL', 'SWITCH')]
        result = catalog.calculate(inputs)
        self.assertEqual((result.current_supply_ma, result.current_consumption_ma), (299, 108))

    def test_overwritten_switchable_records_do_not_leave_type_in_set(self):
        switchable = '<CurrentDrawnSwitchablePowerSupply>20</CurrentDrawnSwitchablePowerSupply><CurrentSuppliedSwitchablePowerSupply>200</CurrentSuppliedSwitchablePowerSupply><FirmwareRevisions><Revision><UnitType>OLD</UnitType></Revision></FirmwareRevisions>'
        catalog = self.catalog(row('SW', extra=switchable) + row('SW', 7, 8))
        self.assertNotIn('OLD', catalog.switchable_unit_types)
        result = catalog.calculate([CalculatorUnit('SW', 'OLD', switchable_supply_enabled=True)])
        self.assertEqual((result.current_supply_ma, result.current_consumption_ma), (8, 7))

    def test_burden_literal_zero_and_first_matching_parameter(self):
        catalog = self.catalog(row('KEY', impedance=100000))
        for value in ('0x0', '00', '', 'false', '1'):
            with self.subTest(value=value):
                self.assertEqual(catalog.calculate([CalculatorUnit('KEY', 'KEY4', burden=value)]).impedance_ohms, 990)
        self.assertEqual(catalog.calculate([CalculatorUnit('KEY', 'KEY4', burden='0')]).impedance_ohms, 100000)
        for unit_type in ('KEYGL5', 'keygl5', 'SENTEMP4', 'sentemp4'):
            self.assertEqual(catalog.calculate([CalculatorUnit('KEY', unit_type, burden='1')]).impedance_ohms, 100000)
        unit = CalculatorUnit('KEY', 'KEY4', parameters=(('other', '1'), ('HardwareBurdenMarker', '0'), ('Burden', '1')))
        self.assertEqual(catalog.calculate([unit]).impedance_ohms, 100000)

    def test_impedance_below_ten_and_unknown_units_do_not_contribute(self):
        catalog = self.catalog(row('SHORT', impedance=9) + row('KEY', impedance=1000))
        result = catalog.calculate([CalculatorUnit('SHORT', 'ANY'), CalculatorUnit(None, 'ANY', burden='1'), CalculatorUnit('KEY', 'ANY')])
        self.assertEqual((result.impedance_ohms, result.units_calculated, result.units_not_calculated), (1000, 2, 1))
        with self.assertRaisesRegex(CalculatorError, 'cannot be zero') as captured:
            catalog.calculate([CalculatorUnit('SHORT', 'ANY'), CalculatorUnit('MISSING', 'ANY')])
        self.assertEqual((captured.exception.units_calculated, captured.exception.units_not_calculated), (1, 1))
        self.assertEqual(catalog.calculate([CalculatorUnit('SHORT', 'ANY', burden='1')]).impedance_ohms, 1000)

    def test_native_rounding_is_separate_from_limit_comparison(self):
        catalog = self.catalog(row('A', impedance=800) + row('B', impedance=799))
        result = catalog.calculate([CalculatorUnit('A', 'ANY'), CalculatorUnit('B', 'ANY')])
        self.assertEqual(result.impedance_ohms, 400)
        self.assertLess(result.exact_impedance_ohms, 400)
        self.assertFalse(result.passed)
        self.assertEqual(result.reasons, ('Impedance is below the catalogue minimum',))

    def test_all_failure_conditions_and_incomplete_limits(self):
        catalog = self.catalog(row('A', drawn=2500, supplied=2100, impedance=300))
        result = catalog.calculate([CalculatorUnit('A', 'ANY')])
        self.assertEqual(len(result.reasons), 3)
        missing = self.catalog(row('A', impedance=1000), '<Calculator><MinImpedance>400</MinImpedance></Calculator>')
        result = missing.calculate([CalculatorUnit('A', 'ANY')])
        self.assertFalse(result.passed)
        self.assertIsNone(result.limits)
        self.assertIn('incomplete', result.reasons[0])

    def test_java_signed_integer_totals_and_input_bound(self):
        catalog = self.catalog(row('A', drawn=2147483647, impedance=1000))
        self.assertEqual(catalog.calculate([CalculatorUnit('A', 'ANY')] * 2).current_consumption_ma, -2)
        with self.assertRaisesRegex(CalculatorError, '10000-unit limit'):
            catalog.calculate(CalculatorUnit('A', 'ANY') for _ in range(10001))

    def test_input_validation_and_mapping_form(self):
        catalog = self.catalog(row('A', impedance=1000))
        self.assertTrue(catalog.calculate([{'catalog_number': 'A', 'unit_type': 'ANY'}]).passed)
        for fields in ({'catalog_number': 'A'}, {'catalog_number': 'A', 'unit_type': 'ANY', 'extra': 1}, {'catalog_number': 1, 'unit_type': 'ANY'}, {'catalog_number': 'A', 'unit_type': 'ANY', 'switchable_supply_enabled': 'true'}, {'catalog_number': 'A', 'unit_type': 'ANY', 'parameters': None}, {'catalog_number': 'A', 'unit_type': 'ANY', 'burden': '0', 'parameters': [('Burden', '1')]}):
            with self.subTest(fields=fields), self.assertRaises(CalculatorError):
                catalog.calculate([fields])
        with self.assertRaises(CalculatorError):
            catalog.calculate([object()])

    def test_bad_catalogue_metadata_rejected(self):
        for value in ('NaN', '2147483648'):
            with self.subTest(value=value), self.assertRaises(CalculatorError):
                self.catalog(row('A', drawn=value))


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'), 'Set CBUS_CGATE_TEST_HOST for a disposable native oracle')
class NativeCalculatorTests(unittest.TestCase):
    def test_native_differential_database_networks(self):
        from cbus_toolkit.cgate import CGateClient, CGateError
        from cbus_toolkit.networks import NativeNetworks
        catalog_path = Path(os.environ.get('CBUS_CATALOG_PATH', Path(__file__).resolve().parents[1] / 'research/vendor/cgate/app/unitspec/cbusunits.xml'))
        if not catalog_path.is_file():
            self.skipTest('Supply the matching native server catalogue with CBUS_CATALOG_PATH')
        catalog = CalculatorCatalog.load(catalog_path)
        project = 'CALC' + uuid4().hex[:4].upper()
        network = f'//{project}/254'
        cases = [
            [CalculatorUnit('5034N', 'KEY4'), CalculatorUnit('5500BUR', 'BURDEN'), CalculatorUnit('5500PS', 'POWER')],
            [CalculatorUnit('5508D1D', 'DIMDD8', switchable_supply_enabled=True), CalculatorUnit('5034N', 'KEY4', burden='1')],
            [CalculatorUnit('5508D1D', 'DIMDD8'), CalculatorUnit('5034N', 'KEY4', burden='0')],
            [CalculatorUnit('5508D1D', 'dimdd8', switchable_supply_enabled=True)],
            [CalculatorUnit('5034N', 'KEY4', burden='0x0')],
            [CalculatorUnit('5034N', 'KEY4', burden='00')],
            [CalculatorUnit('5034N', 'keygl5', burden='1')],
            [CalculatorUnit('5034N', 'SENTEMP4', burden='1')],
            [CalculatorUnit('5034N', 'KEY4', parameters=(('HardwareBurdenMarker', '0'), ('Burden', '1')))],
            [CalculatorUnit('5034N', 'KEY4'), CalculatorUnit('unknown', 'ANY', burden='1')],
            [CalculatorUnit('5500BUR', 'BURDEN')] * 3,
            [CalculatorUnit('5500BUR', 'BURDEN')] + [CalculatorUnit('5500PS', 'POWER')] * 6,
            [],
            [CalculatorUnit('unknown', 'ANY')],
        ]
        with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], port=int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=20) as client:
            client.command('PROJECT NEW ' + project)
            client.command('PROJECT SAVE ' + project)
            try:
                client.command('PROJECT USE ' + project)
                client.command('DBCREATENET 254 Calculator Cni 127.0.0.1:29999')
                client.command('NET LOAD DB ' + project)
                for index, units in enumerate(cases):
                    with self.subTest(case=index):
                        created = []
                        try:
                            for address, unit in enumerate(units, 1):
                                path = f'{network}/p/{address}'
                                client.command(f'DBADDSAFE {network} Unit {address} U{address}')
                                created.append(path)
                                fields = [('UnitType', unit.unit_type), ('UnitName', unit.unit_type), ('FirmwareVersion', '1.0.0'), ('CatalogNumber', unit.catalog_number), ('SwitchablePowerSupplyEnabled', str(unit.switchable_supply_enabled).lower())]
                                for field, value in fields:
                                    if value is not None:
                                        client.command(f'DBSET {path}/{field} {value}')
                                parameters = unit.parameters + (() if unit.burden is None else (('Burden', unit.burden),))
                                for number, (name, value) in enumerate(parameters, 1):
                                    client.command(f'DBADD {path} PP')
                                    client.command(f'DBSET {path}/PP[{number}]/Name {name}')
                                    client.command(f'DBSET {path}/PP[{number}]/Value {value}')
                            try:
                                expected = catalog.calculate(units)
                            except CalculatorError:
                                with self.assertRaises(CGateError) as captured:
                                    NativeNetworks(client).calculate(network)
                                # Native A.java throws its uncaught invalid-data
                                # exception here; the transport exposes only500.
                                self.assertEqual(captured.exception.response.code, 500)
                            else:
                                actual = NativeNetworks(client).calculate(network)
                                self.assertEqual({field: actual[field] for field in ('passed', 'current_supply_ma', 'current_consumption_ma', 'impedance_ohms', 'units_calculated', 'units_not_calculated')},
                                                 {field: getattr(expected, field) for field in ('passed', 'current_supply_ma', 'current_consumption_ma', 'impedance_ohms', 'units_calculated', 'units_not_calculated')})
                        finally:
                            for path in reversed(created):
                                client.command('DBDELETE ' + path)
            finally:
                client.command('PROJECT CLOSE ' + project)
                client.command('PROJECT DELETE ' + project)


if __name__ == '__main__':
    unittest.main()
