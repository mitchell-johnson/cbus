"""Wave-22 offline pins for shutter guards with zero prior test refs.

Covers only guards in cbus_toolkit/edlt_shutter.py that no existing test
references: unsupported navigation widget mode, invalid page_mode,
label-text/static-display coupling, and unknown plan settings on apply.
Offline: synthetic fixture + Session only, no Toolkit/C-Gate/hardware.
"""
import unittest
from dataclasses import replace

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_shutter import EdltShutterWidget
from tests.test_edlt import Session, fixture


class ShutterWave22Pins(unittest.TestCase):
    def setUp(self):
        self.editor = EdltShutterWidget(fixture())
        self.session = Session(fixture())

    def plan(self, current=None, **options):
        settings = dict(page=1, position=1, group=42)
        settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def test_unsupported_navigation_widget_mode_rejected(self):
        current = self.session.values()
        current['NavWidgetType'] = (2,)
        with self.assertRaisesRegex(EdltError, 'Unsupported navigation widget mode'):
            self.plan(current)

    def test_invalid_page_mode_rejected(self):
        with self.assertRaisesRegex(EdltError, 'page_mode must be single or multiple'):
            self.plan(page_mode='auto')

    def test_label_text_requires_static_display(self):
        with self.assertRaisesRegex(EdltError, 'label_text selects static display'):
            self.plan(label_type='blank', label_text='Hi')

    def test_bogus_plan_option_rejected_on_apply(self):
        plan = self.plan()
        forged = replace(plan, options={**dict(plan.options), 'bogus': 1})
        with self.assertRaisesRegex(EdltError, 'Invalid Shutter plan settings'):
            self.editor.apply(self.session, forged)


if __name__ == '__main__':
    unittest.main()
