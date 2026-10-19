"""P5.05 wave-33 narrow offline pin for #42 (thermostat template guards).

Pins pure-offline guards in thermostat_templates.py via symbols with zero
prior test refs (template_filename, _number, _native_integer, _safe_int,
ThermostatTemplate/TemplateOverlay, ORIGINAL_POST_LOAD_ADJUSTMENTS,
default_spec_dir): filename zero-padding, integer-byte admission, synthetic
overlay projection, and the post-load catalogue/spec-dir shape. No server,
hardware, vendor EXE, decoded vendor spec, or PP session; #42 stays OPEN.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from cbus_toolkit import thermostat_templates as templates
from cbus_toolkit.thermostat_templates import (
    ORIGINAL_POST_LOAD_ADJUSTMENTS,
    TemplateOverlay,
    ThermostatTemplate,
    ThermostatTemplateError,
)


def _synthetic_template():
    return ThermostatTemplate(
        family='basic',
        number=4,
        filename='THERMOSTAT_TEMPLATE04.xml',
        sha256='synthetic',
        description='synthetic',
        min_version='',
        max_version='',
        values=(('ZoneA', 5), ('ZoneB', 3)),
    )


class TemplateFilenameAndNumberWave33Tests(unittest.TestCase):
    def test_filename_prefix_zero_pad_and_number_range(self):
        # Next: catalog load/include handshake stays open; naming/range only.
        self.assertEqual(templates.template_filename('basic', 1), 'THERMOSTAT_TEMPLATE01.xml')
        self.assertEqual(templates.template_filename('basic', 9), 'THERMOSTAT_TEMPLATE09.xml')
        self.assertEqual(
            templates.template_filename('programmable', 2), 'THERMOSTATA_TEMPLATE02.xml')
        self.assertEqual(
            templates.template_filename('programmable', 9), 'THERMOSTATA_TEMPLATE09.xml')
        for number in (1, 4, 9):
            self.assertEqual(templates._number(number), number)
        for bad in (0, 10, -1, True, False, '1', 1.0, None):
            with self.subTest(bad=repr(bad)):
                with self.assertRaisesRegex(ThermostatTemplateError, 'integer in 1\\.\\.9'):
                    templates._number(bad)


class NativeIntegerAndSafeWave33Tests(unittest.TestCase):
    def test_native_integer_byte_admission_and_safe_projection(self):
        # Next: snapshot/PP live comparison stays open; byte-text guards only.
        self.assertEqual(templates._native_integer('0', 'ZoneA'), 0)
        self.assertEqual(templates._native_integer('255', 'ZoneA'), 255)
        self.assertEqual(templates._native_integer('0xFF', 'ZoneA'), 255)
        self.assertEqual(templates._native_integer(' 10 ', 'ZoneA'), 10)
        with self.assertRaisesRegex(ThermostatTemplateError, 'exceeds one byte'):
            templates._native_integer('256', 'ZoneA')
        for bad in ('', 'one', '-1', '0x', '0x100', '1234', '0b1'):
            with self.subTest(bad=repr(bad)):
                with self.assertRaisesRegex(ThermostatTemplateError, 'not one byte integer'):
                    templates._native_integer(bad, 'ZoneA')
        for bad in (1, None, True, b'5'):
            with self.subTest(bad=repr(bad)):
                with self.assertRaisesRegex(ThermostatTemplateError, 'not one byte integer'):
                    templates._native_integer(bad, 'ZoneA')
        self.assertEqual(templates._safe_int('5'), 5)
        self.assertEqual(templates._safe_int('0xFF'), 255)
        self.assertIsNone(templates._safe_int('nope'))
        self.assertIsNone(templates._safe_int(None))
        self.assertIsNone(templates._safe_int('256'))


class TemplateOverlayProjectionWave33Tests(unittest.TestCase):
    def test_synthetic_overlay_projection_and_mutation_flag(self):
        # Next: catalog/PP overlay planning stays open; pure projection only.
        template = _synthetic_template()
        self.assertEqual(template.as_dict()['values'], {'ZoneA': 5, 'ZoneB': 3})
        overlay = TemplateOverlay(
            template, 'PC_TSB5', '5.4.01',
            before=(('Other', '0x9'), ('ZoneA', '0x1'), ('ZoneB', '3')),
            changes=(('ZoneA', 1, 5),),
        )
        self.assertEqual(overlay.overlay, {'ZoneA': 5, 'ZoneB': 3})
        self.assertEqual(overlay.expected, {'ZoneA': 5, 'ZoneB': 3})
        self.assertEqual(overlay.post_load_changes, {})
        self.assertTrue(overlay.would_mutate)
        document = overlay.as_dict()
        self.assertFalse(document['reset_before_load'])
        self.assertFalse(document['original_post_load_adjustments_replayed'])
        self.assertEqual(document['changed_parameters'],
                         [{'name': 'ZoneA', 'before': 1, 'after': 5}])
        self.assertEqual(document['unchanged_template_parameters'], ['ZoneB'])
        self.assertEqual(document['preserved_parameter_count'], 1)
        clean = TemplateOverlay(
            template, 'PC_TSB5', '5.4.01',
            before=(('ZoneA', '0x5'), ('ZoneB', '3')),
            changes=(),
        )
        self.assertFalse(clean.would_mutate)
        self.assertEqual(clean.as_dict()['changed_parameters'], [])


class PostLoadCatalogueAndSpecDirWave33Tests(unittest.TestCase):
    def test_adjustment_catalogue_shape_and_spec_dir_env(self):
        # Next: post-load replay/native staging stays open; catalogue/env only.
        self.assertIs(type(ORIGINAL_POST_LOAD_ADJUSTMENTS), tuple)
        self.assertGreaterEqual(len(ORIGINAL_POST_LOAD_ADJUSTMENTS), 5)
        for entry in ORIGINAL_POST_LOAD_ADJUSTMENTS:
            with self.subTest(entry=entry[:24]):
                self.assertIs(type(entry), str)
                self.assertTrue(entry)
        text = ' '.join(ORIGINAL_POST_LOAD_ADJUSTMENTS)
        self.assertIn('fan', text.lower())
        self.assertIn('damper', text.lower())
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(templates.default_spec_dir())
        with patch.dict(os.environ, {'CBUS_UNITSPEC_DIR': ''}):
            self.assertIsNone(templates.default_spec_dir())
        with patch.dict(os.environ, {'CBUS_UNITSPEC_DIR': '/tmp/specs'}):
            self.assertEqual(str(templates.default_spec_dir()), '/tmp/specs')


if __name__ == '__main__':
    unittest.main()
