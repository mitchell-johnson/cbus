"""Wave31 narrow offline pins for thermostat output-group guards (P5.05).

Offline only: no I/O, no native writes, no network. Pins model-level
guards in thermostat_output_groups.py whose distinctive messages have
zero prior message-level refs in tests/.
"""
import unittest

from cbus_toolkit.thermostat_output_groups import (
    OUTPUT_FIELDS,
    normalize_output_operations,
    normalize_output_selections,
)
from cbus_toolkit.thermostat_templates import ThermostatTemplateError

PARAM = OUTPUT_FIELDS[1]


def selection(address=1, parameter=PARAM):
    return {'parameter': parameter, 'address': address}


class OutputGroupsWave31Pins(unittest.TestCase):
    def test_selection_history_and_shape_guards(self):
        with self.assertRaisesRegex(ThermostatTemplateError, 'exceeds 256 operations'):
            normalize_output_selections([selection()] * 257)
        with self.assertRaisesRegex(ThermostatTemplateError, 'requires exactly parameter and address'):
            normalize_output_selections([{'parameter': PARAM}])
        with self.assertRaisesRegex(ThermostatTemplateError, 'requires exactly parameter and address'):
            normalize_output_selections([dict(selection(), extra=0)])

    def test_selection_parameter_and_address_guards(self):
        with self.assertRaisesRegex(ThermostatTemplateError, 'Unknown thermostat output selection'):
            normalize_output_selections([selection(parameter='Nope')])
        with self.assertRaisesRegex(ThermostatTemplateError, 'must be an integer byte'):
            normalize_output_selections([selection(address=True)])
        with self.assertRaisesRegex(ThermostatTemplateError, r'Output group address must be 0\.\.255'):
            normalize_output_selections([selection(address=256)])

    def test_operation_record_and_dispatch_guards(self):
        with self.assertRaisesRegex(ThermostatTemplateError, 'Each output operation must be a record'):
            normalize_output_operations([None])
        with self.assertRaisesRegex(ThermostatTemplateError, 'Unknown thermostat output operation'):
            normalize_output_operations([{'op': 'nope'}])
        bad_select = {'op': 'select-output-group', 'parameter': PARAM, 'address': 1, 'extra': 0}
        with self.assertRaisesRegex(ThermostatTemplateError, 'requires exactly op, parameter and address'):
            normalize_output_operations([bad_select])

    def test_add_dialog_field_guards(self):
        cancel_with_address = {'op': 'add-output-group', 'parameter': PARAM,
                               'outcome': 'cancel', 'address': 1}
        with self.assertRaisesRegex(ThermostatTemplateError, 'Direct-cancel output Add admits no'):
            normalize_output_operations([cancel_with_address])
        bad_address = {'op': 'add-output-group', 'parameter': PARAM,
                       'outcome': 'accept', 'address': 255}
        with self.assertRaisesRegex(ThermostatTemplateError, r'must be an integer in 0\.\.254'):
            normalize_output_operations([bad_address])
        long_name = {'op': 'add-output-group', 'parameter': PARAM,
                     'outcome': 'accept', 'name': 'A' * 33}
        with self.assertRaisesRegex(ThermostatTemplateError, 'exceeds 32 UTF-16 code units before trimming'):
            normalize_output_operations([long_name])


if __name__ == '__main__':
    unittest.main()
