"""Wave-26 offline pins for fan guards with zero prior test refs.

Covers only guards in cbus_toolkit/edlt_fan.py that no existing test
references by message text (verified via grep over tests/): unassigned
Lighting application, label index on an index-less display, invalid
existing label type/index, one-speed threshold rejection, and two-speed
high-threshold rejection. Distinct option shapes from test_edlt_fan.py's
range sweep, which asserts those branches only as bare EdltError.
Offline: synthetic fixture + Session only, no Toolkit/C-Gate/hardware.
"""
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_fan import EdltFanWidget
from test_edlt import Session, fixture


class FanWave26Pins(unittest.TestCase):
    def setUp(self):
        spec = fixture()
        self.editor = EdltFanWidget(spec)
        self.session = Session(spec)

    def plan(self, current=None, **options):
        settings = dict(page=1, position=1, group=42)
        settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def test_unassigned_lighting_application_rejected(self):
        current = self.session.values()
        current['SecondaryApplication'] = (255,)
        with self.assertRaisesRegex(EdltError, 'Fan requires an assigned Lighting application'):
            self.plan(current, application='secondary')

    def test_label_index_without_indexed_display_rejected(self):
        with self.assertRaisesRegex(EdltError, 'This label display does not use an index'):
            self.plan(label_type='blank', label_index=1)

    def test_invalid_existing_label_type_rejected(self):
        from test_edlt_fan import after
        current = after(self.plan())
        current['Widget6WidgetByteValue1'] = (0x75,)
        with self.assertRaisesRegex(EdltError, 'Invalid existing label type or index'):
            self.plan(current)

    def test_one_speed_threshold_rejected(self):
        with self.assertRaisesRegex(EdltError, 'One-speed Fan does not use thresholds'):
            self.plan(speeds=1, low_threshold=1)

    def test_two_speed_high_threshold_rejected(self):
        with self.assertRaisesRegex(EdltError, 'Two-speed Fan uses low_threshold for both stored thresholds'):
            self.plan(speeds=2, high_threshold=5)


if __name__ == '__main__':
    unittest.main()
