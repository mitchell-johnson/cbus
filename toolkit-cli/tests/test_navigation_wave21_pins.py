"""Wave-21 offline pins for eDLT navigation guards with zero prior test refs.

Covers only guards in cbus_toolkit/edlt_navigation.py that no existing test
references: dynamic-group variant coupling, static-name variant coupling,
page-index variant coupling, and malformed metadata group records.
Offline: synthetic fixture + Session only, no Toolkit/C-Gate/hardware.
"""
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_navigation import EdltNavigation, NavigationMetadata
from tests.test_edlt import Session
from tests.test_edlt_navigation import fixture


class NavigationWave21Pins(unittest.TestCase):
    def setUp(self):
        self.editor = EdltNavigation(fixture())
        self.values = Session(fixture()).values()

    def test_dynamic_group_requires_logo_or_dynamic_labels(self):
        with self.assertRaisesRegex(EdltError, 'Dynamic group requires logo or dynamic-labels'):
            self.editor.plan(self.values, page_mode='multiple', variant='time', dynamic_group=42)

    def test_static_page_names_require_page_names_variant(self):
        with self.assertRaisesRegex(EdltError, 'Static page names require page-names variant'):
            self.editor.plan(self.values, page_mode='multiple', variant='time', page_names={1: 'Kitchen'})

    def test_page_indices_require_page_names_or_dynamic_labels(self):
        with self.assertRaisesRegex(EdltError, 'Page indices require page-names or dynamic-labels variant'):
            self.editor.plan(self.values, page_mode='multiple', variant='time', page_name_indices={1: 0})

    def test_malformed_metadata_group_record_rejected(self):
        document = {'format': 'cbus-edlt-navigation-metadata-v1',
                    'groups': [{'application': 56, 'group': 42}]}
        with self.assertRaisesRegex(EdltError, 'Invalid metadata group record'):
            NavigationMetadata.from_dict(document)


if __name__ == '__main__':
    unittest.main()
