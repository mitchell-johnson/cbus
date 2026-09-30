"""Literal base-gateway cases, independent of Advanced remote/scene controls."""
from copy import deepcopy
import json
import unittest

from cbus_toolkit.unitspec import UnitSpec
from cbus_toolkit.wireless_connection import (
    FrozenTopology, WirelessConnectionEditor, WirelessConnectionError, WirelessConnectionPlan,
)
from cbus_toolkit.wireless_gateway import WirelessGatewayEditor, WirelessGatewayError
from test_wireless_connection import ConnectionSession, fixture, mapped_session, xml


BASE_FIELDS = ('Application', 'ApplicationConnectEnabled', 'SynchroniseToWired',
               'ForwardingMode', 'ForwardingRoute', 'StatusMonitorApplication')


def base_topology(firmware='2.4.00'):
    return FrozenTopology.from_xml(xml().replace(b'WGATE5F', b'WGATE5N').replace(b'2.4.00', firmware.encode()))


class BaseConnectionTest(unittest.TestCase):
    def setUp(self):
        self.editor = WirelessConnectionEditor(fixture())
        self.live = mapped_session(MapWirelessRemotes='1')
        self.live.unit_type = 'WGATE5N'
        self.topology = base_topology()

    def plan(self, **options):
        return self.editor.plan(self.live.values(), topology=self.topology, source_network=254,
                                unit_address=200, identity=('WGATE5N', '2.4.00', None), **options)

    def apply(self, plan, **options):
        return self.editor.apply(self.live, plan, topology=self.topology,
                                 exclusive_project=True, **options)

    def test_registered_profile_boundaries_and_outside_refusals(self):
        for firmware in ('2.2.90', '2.4.99'):
            with self.subTest(firmware=firmware):
                plan = self.editor.plan(self.live.values(), topology=base_topology(firmware),
                                        source_network=254, unit_address=200, application2=202)
                self.assertEqual(plan.identity, ('WGATE5N', firmware, None))
                self.assertEqual(set(plan.expected), set(BASE_FIELDS))
        for firmware in ('0', '1.4.91', '2.2.89', '2.5.00', '2.4.99\n', True):
            with self.subTest(firmware=firmware), self.assertRaises(WirelessConnectionError):
                self.editor.plan(self.live.values(), topology=self.topology, source_network=254,
                                 unit_address=200, identity=('WGATE5N', firmware, None))
        self.assertEqual(self.live.calls, [])

    def test_six_field_schema_and_snapshot_need_no_advanced_parameters(self):
        original = fixture()
        minimal = UnitSpec(original.filename, original.metadata, original.sources,
                           {k: v for k, v in original.parameters.items() if k in BASE_FIELDS})
        editor = WirelessConnectionEditor(minimal)
        current = {k: self.live.current[k] for k in BASE_FIELDS}
        plan = editor.plan(current, topology=self.topology, source_network=254, unit_address=200,
                           application1=57, application2=202, destination_network=99)
        self.assertEqual(plan.changes, {'Application': (57, 202), 'ForwardingMode': (1,),
                                       'ForwardingRoute': (27, 123, 99, 255, 255, 255, 255)})
        view = editor.show(current, topology=self.topology, source_network=254, unit_address=200)
        self.assertFalse(view['advanced_controls_available'])
        self.assertEqual(view['unit_type'], 'WGATE5N')
        # F continues to require its actual scene/mapping dependencies.
        with self.assertRaises(WirelessConnectionError):
            editor.plan(current, topology=FrozenTopology.from_xml(xml()), source_network=254, unit_address=200)

    def test_application_change_preserves_opaque_mode_remote_and_scene_state(self):
        before = self.live.values()
        plan = self.plan(application1=57, application2=202, destination_network=99,
                         adjacent_network=True, synchronise_to_wired=True, status_monitor_application=57)
        self.assertEqual(set(plan.expected), set(BASE_FIELDS))
        restored = WirelessConnectionPlan.from_dict(json.loads(json.dumps(plan.as_dict())))
        result = self.apply(restored)
        self.assertTrue(result['verified'])
        self.assertFalse(result['whole_dialog_save_executed'])
        after = self.live.values()
        self.assertEqual({k: v for k, v in before.items() if k not in BASE_FIELDS},
                         {k: v for k, v in after.items() if k not in BASE_FIELDS})
        self.assertEqual(after['MapWirelessRemotes'], '1')
        self.assertEqual(after['Application'], '57 202')
        self.assertEqual(after['ForwardingRoute'], '27 123 99 255 255 255 255')

    def test_explicit_all_applications_and_adjacent_off_dependencies(self):
        plan = self.plan(application1=255, adjacent_network=False)
        self.assertEqual(plan.changes['Application'], (255, 255))
        self.assertEqual(set(plan.expected), set(BASE_FIELDS))
        with self.assertRaises(WirelessConnectionError):
            self.plan(application1=255, application2=202)
        with self.assertRaises(WirelessConnectionError):
            self.plan(adjacent_network=False, synchronise_to_wired=True)

    def test_advanced_state_is_not_consumed_but_advanced_workflow_still_refuses_n(self):
        plan = self.plan(application2=202)
        self.live.current['RemoteIdentity8'] = 'opaque changed value'
        self.live.current['SceneVectorOffset'] = 'opaque changed value'
        self.assertTrue(self.apply(plan)['verified'])
        gateway = WirelessGatewayEditor(fixture())
        with self.assertRaises(WirelessGatewayError):
            gateway.plan(self.live.values(), identity=('WGATE5N', '2.4.00', None), mode='remote-switch')

    def test_forged_advanced_fields_and_profile_changes_refuse_without_io(self):
        document = self.plan(application2=202).as_dict()
        for section, field, value in (('expected', 'MapWirelessRemotes', [1]),
                                       ('changes', 'RemoteIdentity1', [1, 2, 3, 4]),
                                       ('changes', 'ForwardingRoute', [27, 80, 99, 255, 255, 255, 255])):
            forged = deepcopy(document)
            forged[section][field] = value
            self.live.reads.clear()
            with self.subTest(field=field), self.assertRaises(WirelessConnectionError):
                self.apply(WirelessConnectionPlan.from_dict(forged))
            self.assertEqual(self.live.reads, [])
            self.assertEqual(self.live.calls, [])
        for field, value in (('unit_type', 'WGATE5F'), ('firmware', '2.5.00')):
            with self.subTest(field=field), self.assertRaises(WirelessConnectionError):
                WirelessConnectionPlan.from_dict({**document, field: value})

    def test_stale_owned_fields_refuse_before_write(self):
        plan = self.plan(application2=202)
        for name, value in (('Application', '57 202'), ('StatusMonitorApplication', '57')):
            before = dict(self.live.current)
            self.live.current[name] = value
            with self.subTest(name=name), self.assertRaises(WirelessConnectionError):
                self.apply(plan)
            self.assertEqual(self.live.calls, [])
            self.live.current = before


if __name__ == '__main__':
    unittest.main()
