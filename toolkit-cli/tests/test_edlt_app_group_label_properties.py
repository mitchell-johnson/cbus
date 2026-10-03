"""Complete records and distinct virtual setters, using literal source facts."""
import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_app_group_label_properties import (
    AppGroupLabelState, apply_app_group_label_type,
    set_app_group_label_index, update_app_group_label_types, PROFILES,
)

VECTOR = Path(__file__).resolve().parents[1] / 'research/fixtures/edlt-app-group-label-vectors.json'


class AppGroupPropertiesTests(unittest.TestCase):
    def test_whole_records_match_independent_literal_vectors(self):
        vectors = json.loads(VECTOR.read_text())
        for case in vectors['property_cases']:
            with self.subTest(case=case['name']):
                state = AppGroupLabelState(case['family'], bytes(case['before']))
                if case['operation']['kind'] == 'type':
                    result = apply_app_group_label_type(state, target=case['operation']['target'],
                        value=case['operation']['value'], image_flags=case['image_flags'])
                else:
                    result = set_app_group_label_index(state, target=case['operation']['target'],
                        index=case['operation']['value'], image_flags=case['image_flags'])
                self.assertEqual(result.state.record, bytes(case['after']))
                self.assertEqual(result.as_dict()['property_changed'], case['notifications'])

    def test_every_family_getter_clamps_source_dynamic_and_static_ranges(self):
        for family, selected in PROFILES.items():
            for byte, label, status, expected in (
                    (0x17, 4, 4, (0, 0)), (0x35, 64, 64, (0, 0)),
                    (0x35, 63, 63, (63, 63)), (0x00, 255, 255, (255, 255)),
                    (0x3d, 255, 255, (0, 0))):
                with self.subTest(family=family, byte=byte):
                    raw = bytearray(range(32)); raw[0]=selected.widget_type; raw[1]=byte
                    raw[selected.label_offset]=label; raw[selected.status_offset]=status
                    state=AppGroupLabelState(family,bytes(raw))
                    self.assertEqual((state.index('label'),state.index('status')),expected)
                    if byte==0x3d:
                        self.assertEqual(state.display_type('status'),13)

    def test_index_setter_suppresses_notifications_but_retains_bit7(self):
        for family, selected in PROFILES.items():
            raw=bytearray(range(32));raw[0]=selected.widget_type;raw[1]=0x96
            raw[selected.label_offset]=0;raw[selected.status_offset]=0
            with self.subTest(family=family):
                state=AppGroupLabelState(family,bytes(raw))
                label=set_app_group_label_index(state,target='label',index=1,image_flags=(False,True))
                status=set_app_group_label_index(label.state,target='status',index=1,image_flags=(False,True))
                self.assertEqual(status.state.record[1],0xa7)
                self.assertEqual(label.notifications+status.notifications,())
                self.assertEqual(label.state.record[selected.label_offset],1)
                self.assertEqual(status.state.record[selected.status_offset],1)

    def test_direct_property_alias_is_separate_from_actual_panel_choices(self):
        # Generic source properties can store the exact nibble; a panel's
        # omission is enforced by normalize_controls, not fabricated here.
        raw=bytearray(32);raw[0]=16;raw[1]=5
        result=apply_app_group_label_type(AppGroupLabelState('multilevel',bytes(raw)),
            target='status',value=3,image_flags=())
        self.assertEqual(result.state.record[1],3)
        self.assertEqual(result.notifications,('StatusDisplayType','StatusValueText'))

    def test_fan_and_multilevel_named_status_indices_never_change_type(self):
        for family in ('fan','multilevel'):
            raw=bytearray(range(32));raw[0]=PROFILES[family].widget_type;raw[1]=0xb5
            for target,offset in (('status-low',11),('status-medium',12),('status-high',13)):
                with self.subTest(family=family,target=target):
                    result=set_app_group_label_index(AppGroupLabelState(family,bytes(raw)),
                        target=target,index=255,image_flags=(True,))
                    expected=bytearray(raw);expected[offset]=255
                    self.assertEqual(result.state.record,bytes(expected))
                    self.assertEqual(result.notifications,())
                    with self.assertRaisesRegex(EdltError,'no type selector'):
                        apply_app_group_label_type(result.state,target=target,value=5,image_flags=())

    def test_update_types_is_status_then_label_with_recursive_index_reset(self):
        raw=bytearray(32);raw[0]=14;raw[1]=0xb5;raw[11]=1;raw[12]=1
        result, receipts=update_app_group_label_types(AppGroupLabelState('enable',bytes(raw)),
            image_flags=(False,True))
        self.assertEqual([row.target for row in receipts],['status','label'])
        self.assertEqual(result.record,bytes(raw))
        self.assertEqual([row.changed for row in receipts],[False,False])

    def test_type_same_semantic_dynamic_changes_only_subtype_without_reset(self):
        for family, selected in PROFILES.items():
            raw=bytearray(32);raw[0]=selected.widget_type;raw[1]=0x96
            raw[selected.label_offset]=1;raw[selected.status_offset]=1
            result=apply_app_group_label_type(AppGroupLabelState(family,bytes(raw)),
                target='label',value=10,image_flags=(False,True))
            with self.subTest(family=family):
                self.assertEqual(result.state.record[1],0xa6)
                self.assertEqual(result.state.record[selected.label_offset],1)
                self.assertEqual(result.notifications,('LabelDisplayType',))

    def test_invalid_record_family_types_and_unknown_images_refuse(self):
        for family, raw in (('lighting',bytes(32)),('enable',bytes(32)),('timer',b'\x05')):
            with self.subTest(family=family),self.assertRaises(EdltError):
                AppGroupLabelState(family,raw)
        raw=bytearray(32);raw[0]=14
        state=AppGroupLabelState('enable',bytes(raw))
        for images in ((None,),(1,),tuple([False]*5),'unknown'):
            with self.subTest(images=images),self.assertRaises(EdltError):
                apply_app_group_label_type(state,target='label',value=10,image_flags=images)
        for index in (-1,256,True):
            with self.subTest(index=index),self.assertRaises(EdltError):
                set_app_group_label_index(state,target='label',index=index,image_flags=())


if __name__ == '__main__': unittest.main()
