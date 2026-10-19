"""Wave-23 offline pins for timer layout guards with zero prior test refs.

Covers only guards in cbus_toolkit/edlt_timer.py that no existing test
references by message text (verified via grep over tests/): unsupported
navigation widget mode, active widget after terminator, AppGroup widget in
a standby position, and replacing another widget type. Distinct fixture
shapes from test_edlt_timer.py's range sweep ((1, 5), (6, 14), (7, 5)).
Offline: synthetic fixture + Session only, no Toolkit/C-Gate/hardware.
"""
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_timer import EdltTimerWidget
from test_edlt import Session, fixture


class TimerWave23Pins(unittest.TestCase):
    def setUp(self):
        spec = fixture()
        self.editor = EdltTimerWidget(spec)
        self.session = Session(spec)

    def plan(self, current=None, **options):
        settings = dict(page=1, position=1, group=42)
        settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def test_unsupported_navigation_widget_mode_rejected(self):
        current = self.session.values()
        current['NavWidgetType'] = (2,)
        with self.assertRaisesRegex(EdltError, 'Unsupported navigation widget mode'):
            self.plan(current)

    def test_active_widget_after_terminator_rejected(self):
        current = self.session.values()
        current['Widget6WidgetType'] = (255,)
        current['Widget7WidgetType'] = (5,)
        with self.assertRaisesRegex(EdltError, 'An active widget follows a terminator'):
            self.plan(current)

    def test_standby_app_group_widget_rejected(self):
        current = self.session.values()
        current['Widget2WidgetType'] = (3,)
        with self.assertRaisesRegex(EdltError, 'Unsupported AppGroup widget in a standby position'):
            self.plan(current)

    def test_replacing_another_widget_type_rejected(self):
        current = self.session.values()
        current['Widget6WidgetType'] = (2,)
        with self.assertRaisesRegex(EdltError, 'Selected widget is another type'):
            self.plan(current)


if __name__ == '__main__':
    unittest.main()
