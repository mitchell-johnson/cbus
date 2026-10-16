"""Source-derived fresh SENLLA scalar literals; no original or device execution."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_light_level import SurfaceLightState
from cbus_toolkit.senlla_surface import SENLLASurface, SurfaceView
from cbus_toolkit.sensors import SensorError
from test_senlla_surface import IDENTITY, fixture


class SurfaceLightLevelTests(unittest.TestCase):
    def load(self, **changes):
        spec = fixture()
        view = SENLLASurface(spec).view(spec.defaults() | changes, identity=IDENTITY)
        return SurfaceLightState.from_surface_view(view)

    def test_source_target_and_margin_renderer_literals(self):
        source = json.loads((Path(__file__).parents[1] / 'research/fixtures/'
                             'senlla-fresh-light-level-source.json').read_text())
        self.assertEqual(len(source['method_pins']), 58)
        initial = self.load()
        for row in source['target_vectors']:
            with self.subTest(target=row['loaded_target']):
                state = replace(initial, target_byte=row['loaded_target'])
                result = state.fresh_initialize()
                self.assertEqual(result.target_byte, row['resulting_target'])
                self.assertEqual(result.margin_percent, state.margin_percent)
                self.assertEqual(result is state, not row['direct_setter'])
        for row in source['margin_vectors']:
            with self.subTest(margin=row['loaded_margin']):
                state = replace(initial, margin_percent=row['loaded_margin']).fresh_initialize()
                self.assertEqual(state.margin_percent, row['source_margin_after_synchronous_render'])
                self.assertEqual(state.as_dict()['margin_display_position'], row['control_position'])

    def test_raw_margin_is_captured_before_target_cap(self):
        loaded = self.load(PECTargetLux=[255], PECMarginLux=[25])
        self.assertEqual((loaded.target_byte, loaded.margin_percent), (255, 10))
        fresh = loaded.fresh_initialize()
        self.assertEqual((fresh.target_byte, fresh.margin_percent), (200, 10))
        self.assertEqual(fresh.parameters()['PECMarginLux'], [20])
        self.assertEqual(loaded.target_byte, 255)

    def test_display_clamp_retains_large_source_margin(self):
        state = self.load(PECTargetLux=[1], PECMarginLux=[255]).fresh_initialize()
        self.assertEqual(state.margin_percent, 25500)
        self.assertEqual(state.as_dict()['margin_display_position'], 100)
        self.assertEqual(state.parameters()['PECMarginLux'], [255])
        zero = self.load(PECTargetLux=[0], PECMarginLux=[255]).fresh_initialize()
        self.assertEqual(zero.as_dict()['margin_display_position'], 1)
        self.assertEqual(zero.parameters()['PECMarginLux'], [0])

    def test_target_group_load_and_copied_margin_power(self):
        state = self.load(LightLevelTargetGroup=[12], LightLevelMarginGroup=[34],
                          PECTargetLux=[80], PECMarginLux=[16],
                          LightLevelTargetGroupLevelStore=[1],
                          LightLevelMarginGroupLevelStore=[0]).fresh_initialize()
        self.assertEqual((state.target_byte, state.margin_percent, state.margin_group), (45, 20, 255))
        self.assertEqual(state.parameters(), {
            'LightLevelTargetGroup': [12], 'LightLevelMarginGroup': [12],
            'PECTargetLux': [200], 'PECMarginLux': [40],
            'LightLevelTargetGroupLevelStore': [1], 'LightLevelMarginGroupLevelStore': [1],
            'PowerUpTargetGroupLevel': [13], 'PowerUpMarginGroupLevel': [13]})

    def test_margin_group_save_uses_fresh_target_with_captured_power(self):
        state = self.load(LightLevelMarginGroup=[34], PECTargetLux=[255],
                          PECMarginLux=[25], LightLevelMarginGroupLevelStore=[1]).fresh_initialize()
        self.assertEqual((state.margin_percent, state.target_byte), (9, 200))
        result = state.parameters()
        self.assertEqual(result['PECMarginLux'], [200])
        self.assertEqual(result['LightLevelMarginGroupLevelStore'], [1])
        self.assertEqual(result['LightLevelTargetGroupLevelStore'], [0])
        self.assertEqual(result['PowerUpMarginGroupLevel'], [89])

    def test_detached_export_and_immutable_state(self):
        state = self.load().fresh_initialize()
        result = state.parameters()
        result['PECTargetLux'][0] = 1
        self.assertEqual(state.parameters()['PECTargetLux'], [40])
        with self.assertRaises(FrozenInstanceError):
            state.target_byte = 1
        view = state.as_dict()
        view['margin_percent'] = 1
        self.assertEqual(state.margin_percent, 20)

    def test_strict_domains_and_incomplete_view(self):
        state = self.load()
        for name in state.__dataclass_fields__:
            maximum = 25500 if name == 'margin_percent' else 1 if name.endswith('power_state') else 255
            for value in (True, -1, maximum + 1, '1', 1.0, None):
                with self.subTest(field=name, value=value), self.assertRaises(SensorError):
                    replace(state, **{name: value})
        with self.assertRaises(SensorError):
            replace(state, target_group=1, margin_group=2)
        with self.assertRaises(SensorError):
            replace(state, target_byte=200, margin_percent=25500).parameters()
        for view in (None, {}, SurfaceView(IDENTITY, {}, {}, {})):
            with self.subTest(view=view), self.assertRaises(SensorError):
                SurfaceLightState.from_surface_view(view)


if __name__ == '__main__':
    unittest.main()
