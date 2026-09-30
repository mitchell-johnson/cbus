"""Independent, no-hardware vectors for the wireless gateway Connection tab.

The synthetic schema, topology and route bytes below are intentionally literal:
none is generated from the production editor's layout or routing constants.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import unittest

from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from cbus_toolkit.wireless_connection import (
    FrozenTopology, WirelessConnectionApplyError, WirelessConnectionEditor, WirelessConnectionError,
    WirelessConnectionPlan,
)
from test_macros import Session


def fixture():
    rows = [
        ('Application', 0x21, 2, 8, 0, 'int', '56 255'),
        ('StatusMonitorApplication', 0x37, 1, 8, 0, 'int', '56'),
        ('ApplicationConnectEnabled', 0x41, 1, 1, 0, 'bit', '0'),
        ('ForwardingMode', 0x41, 1, 1, 1, 'bit', '0'),
        ('SynchroniseToWired', 0x41, 1, 1, 2, 'bit', '0'),
        ('MapWirelessRemotes', 0x41, 1, 1, 3, 'bit', '0'),
        ('ForwardingRoute', 0x42, 7, 8, 0, 'int', '255 255 255 255 255 255 255'),
        ('UnitAddress', 0x20, 1, 8, 0, 'int', '200'),
        ('SceneTriggerGroup', 0x130, 8, 8, 0, 'int', '255 255 255 255 255 255 255 255'),
        ('SceneVectorOffset', 0x150, 8, 8, 0, 'int', '255 255 255 255 255 255 255 255'),
    ]
    for remote in range(8):
        rows.extend([
            (f'RemoteIdentity{remote + 1}', 0x70 + remote * 4, 4, 8, 0, 'int', '255 255 255 255'),
            (f'KeySceneMask{remote + 1}', 0x90 + remote * 2, 16, 1, 0, 'bit',
             '0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0'),
            (f'ApplicationSeconday{remote + 1}', 0xA0 + remote * 2, 16, 1, 0, 'bit',
             '0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0'),
            (f'GroupAddress{remote + 1}', 0xB0 + remote * 16, 16, 8, 0, 'int',
             '255 255 255 255 255 255 255 255 255 255 255 255 255 255 255 255'),
        ])
    parameters = {}
    for name, address, size, bits, bit, kind, default in rows:
        fields = {'Name': name, 'Type': kind, 'Address': str(address),
                  'ArraySize': str(size), 'BitAddress': str(bit), 'ArraySkip': '0',
                  'DefaultValue': default}
        if kind == 'int':
            fields.update(BitSize=str(bits), MinValue='0', MaxValue='255')
        parameters[name] = ParameterSpec(name, kind, 'literal-connection.xml', fields)
    return UnitSpec('WGATE5X_2.xml', {'Type': 'WGATE5N'},
                    ('literal-connection.xml',), parameters)


def unit(address, kind='BRIDGE2N', firmware=None):
    version = '' if firmware is None else f'<FirmwareVersion>{firmware}</FirmwareVersion>'
    return f'<Unit><Address>{address}</Address><UnitType>{kind}</UnitType>{version}</Unit>'


def network(address, units=(), *, applications=(), interface='Bridge', parent=''):
    apps = ''.join(f'<Application><Address>{value}</Address><TagName>A{value}</TagName>'
                   '</Application>' for value in applications)
    return (f'<Network><Address>{address}</Address><TagName>N{address}</TagName>'
            f'<Interface><InterfaceType>{interface}</InterfaceType>'
            f'<InterfaceAddress>{parent}</InterfaceAddress></Interface>'
            f'{"".join(units)}{apps}</Network>')


def xml(networks=None):
    if networks is None:
        networks = [
            network(254, [unit(200, 'WGATE5F', '2.4.00')],
                    applications=(56, 57, 202, 203), interface='CNI', parent='127.0.0.1:1'),
            network(200, [unit(123)], parent='254/p/200'),
            network(123, [unit(99)], parent='200/p/123'),
            network(99, parent='123/p/99'),
        ]
    return ('<Installation><Project><Address>P</Address><TagName>Project P</TagName>'
            + ''.join(networks) + '</Project></Installation>').encode()


def topology(networks=None):
    return FrozenTopology.from_xml(xml(networks))


def source(*units):
    return network(254, [unit(200, 'WGATE5F', '2.4.00'), *units],
                   applications=(56, 57, 202, 203), interface='CNI', parent='127.0.0.1:1')


class ConnectionSession(Session):
    def __init__(self, **current):
        super().__init__(fixture())
        self.unit_type, self.firmware, self.catalog_number = 'WGATE5F', '2.4.00', None
        self.source, self.lock_address = '/db//P/254/p/200', '//P/254'
        self.current.update(current)
        self.reads = []

    def values(self):
        self.reads.append('values')
        return super().values()

    def info(self, name):
        self.reads.append('info')
        return super().info(name)


def mapped_session(**current):
    values = {'SceneTriggerGroup': '20 255 22 255 24 255 26 255',
              'SceneVectorOffset': '0 255 10 255 20 255 30 255'}
    for remote in range(1, 9):
        values.update({f'RemoteIdentity{remote}': '1 2 3 4',
                       f'KeySceneMask{remote}': '1 0 0 1 0 0 1 0 0 1 0 0 1 0 0 1',
                       f'ApplicationSeconday{remote}': '0 1 0 0 1 0 0 1 0 0 1 0 0 1 0 0',
                       f'GroupAddress{remote}': '35 12 254 1 255 3 4 5 6 7 8 9 10 11 12 13'})
    return ConnectionSession(**{**values, **current})


class ConnectionTest(unittest.TestCase):
    def setUp(self):
        self.editor = WirelessConnectionEditor(fixture())
        self.live = ConnectionSession()
        self.topology = topology()

    def plan(self, *, live=None, frozen=None, **options):
        return self.editor.plan((live or self.live).values(),
                                topology=frozen or self.topology,
                                source_network=254, unit_address=200,
                                identity=('WGATE5F', '2.4.00', None), **options)

    def apply(self, plan, *, live=None, frozen=None, exclusive_project=True):
        return self.editor.apply(live or self.live, plan,
                                 topology=frozen or self.topology,
                                 exclusive_project=exclusive_project)

    def test_literal_directional_route_excludes_selected_gateway(self):
        plan = self.plan(application1=56, application2=202,
                         adjacent_network=True, synchronise_to_wired=True,
                         destination_network=99, status_monitor_application=57)
        self.assertEqual(dict(plan.changes), {
            'Application': (56, 202),
            'ApplicationConnectEnabled': (1,),
            'SynchroniseToWired': (1,),
            'ForwardingMode': (1,),
            'ForwardingRoute': (27, 123, 99, 255, 255, 255, 255),
            'StatusMonitorApplication': (57,),
        })
        # 0x41's upper nibble and independent Remote Switch bit stay intact.
        image = self.editor.codec.encode_many(plan.changes).apply(MemoryImage.from_bytes(b'\xf0' * 0x200))
        self.assertEqual(image.read(0x21, 2), bytes([56, 202]))
        self.assertEqual(image.read(0x37, 1), bytes([57]))
        self.assertEqual(image.read(0x41, 8), bytes([247, 27, 123, 99, 255, 255, 255, 255]))

    def test_branch_sibling_uses_actual_directed_far_side_bridge(self):
        frozen = topology([
            source(),
            network(200, [unit(123), unit(80)]),
            network(123, [unit(200, 'BRIDGE2F'), unit(99)]),
            network(80, [unit(200, 'BRIDGE2F')]),
            network(99, [unit(123, 'BRIDGE2F')]),
        ])
        self.assertEqual(self.plan(frozen=frozen, destination_network=80).changes['ForwardingRoute'],
                         (18, 80, 255, 255, 255, 255, 255))
        self.assertEqual(self.plan(frozen=frozen, destination_network=99).changes['ForwardingRoute'],
                         (27, 123, 99, 255, 255, 255, 255))

    def test_missing_reverse_bridge_is_not_fabricated_from_interface(self):
        frozen = topology([
            source(), network(200, parent='123/p/200'),
            network(123, [unit(200)], parent='254/p/123'),
            network(99, [unit(123)], parent='123/p/99'),
        ])
        with self.assertRaises(WirelessConnectionError):
            self.plan(frozen=frozen, destination_network=99)
        self.assertEqual(self.live.calls, [])

    def test_missing_cyclic_ambiguous_and_unsupported_bridge_paths_fail_closed(self):
        cases = {
            'missing adjacent': [source(), network(99)],
            'missing destination': [source(), network(200)],
            'missing bridge target': [source(), network(200, [unit(123)]), network(99)],
            'long cycle': [source(), network(200, [unit(123)]),
                           network(123, [unit(80)]), network(80, [unit(200), unit(99)]), network(99)],
            'ambiguous': [source(), network(200, [unit(123), unit(80)]),
                          network(123, [unit(99)]), network(80, [unit(99)]), network(99)],
            'unsupported': [source(), network(200, [unit(99, 'BRIDGE1N')]), network(99)],
        }
        for label, networks in cases.items():
            with self.subTest(case=label), self.assertRaises(WirelessConnectionError):
                self.plan(frozen=topology(networks), destination_network=99)
        self.assertEqual(self.live.calls, [])

    def test_five_route_entries_admitted_six_without_sentinel_refused(self):
        networks = [source(), network(200, [unit(190)]), network(190, [unit(180)]),
                    network(180, [unit(170)]), network(170, [unit(160)]),
                    network(160, [unit(150)]), network(150, [unit(140)]), network(140)]
        frozen = topology(networks)
        self.assertEqual(self.plan(frozen=frozen, destination_network=150).changes['ForwardingRoute'],
                         (54, 190, 180, 170, 160, 150, 255))
        with self.assertRaises(WirelessConnectionError):
            self.plan(frozen=frozen, destination_network=140)

    def test_omission_preserves_route_and_remote_mapping_values(self):
        live = mapped_session(ForwardingMode='1', ForwardingRoute='18 123 255 99 255 255 255',
                              Application='56 202', ApplicationConnectEnabled='1', SynchroniseToWired='1')
        before = live.values()
        plan = self.plan(live=live, status_monitor_application=57)
        self.assertEqual(dict(plan.changes), {'StatusMonitorApplication': (57,)})
        self.assertTrue(self.apply(plan, live=live)['verified'])
        expected = dict(before, StatusMonitorApplication='57')
        self.assertEqual(live.values(), expected)
        self.assertEqual(live.calls, [('StatusMonitorApplication', '57')])

    def test_destination_none_clears_route_but_omitted_flags_stay_set(self):
        live = ConnectionSession(ForwardingMode='1', ForwardingRoute='27 123 99 255 255 255 255',
                                 ApplicationConnectEnabled='1', SynchroniseToWired='1')
        plan = self.plan(live=live, destination_network=None)
        self.assertEqual(dict(plan.changes), {'ForwardingMode': (0,), 'ForwardingRoute': (255,) * 7})

    def test_route_edit_preserves_seeded_remote_tables_and_shared_mode_bit(self):
        live = mapped_session()
        before = live.values()
        plan = self.plan(live=live, destination_network=99, adjacent_network=True,
                         synchronise_to_wired=True)
        self.assertTrue(self.apply(plan, live=live)['verified'])
        expected = dict(before, ForwardingRoute='27 123 99 255 255 255 255', ForwardingMode='1',
                        ApplicationConnectEnabled='1', SynchroniseToWired='1')
        self.assertEqual(live.values(), expected)

    def test_loaded_route_checks_each_entry_and_retains_valid_tail_after_gap(self):
        live = ConnectionSession(ForwardingMode='1', ForwardingRoute='18 123 111 99 255 255 255')
        before = live.values()
        view = self.editor.show(before, topology=self.topology, source_network=254,
                                unit_address=200, identity=('WGATE5F', '2.4.00', None))
        self.assertEqual(view['loaded_route'], {
            'bridge_addresses': [123, 255, 99, 255, 255, 255],
            'destination_network': 123,
            'stored_route_preserved': True,
        })
        self.assertEqual(live.values(), before)
        self.assertEqual(live.calls, [])

    def test_disabled_forwarding_does_not_load_a_retained_route(self):
        live = ConnectionSession(ForwardingMode='0', ForwardingRoute='27 123 99 255 255 255 255')
        before = live.values()
        view = self.editor.show(before, topology=self.topology, source_network=254,
                                unit_address=200, identity=('WGATE5F', '2.4.00', None))
        self.assertEqual(view['loaded_route']['bridge_addresses'], [255] * 6)
        self.assertIsNone(view['loaded_route']['destination_network'])
        self.assertEqual(view['parameters']['ForwardingRoute'], [27, 123, 99, 255, 255, 255, 255])
        self.assertEqual(live.values(), before)
        self.assertEqual(live.calls, [])

    def test_primary_unassigned_cascades_secondary_and_disconnect_clears_sync(self):
        live = ConnectionSession(Application='56 202', ApplicationConnectEnabled='1', SynchroniseToWired='1')
        plan = self.plan(live=live, application1=255, adjacent_network=False)
        self.assertEqual(dict(plan.changes), {'Application': (255, 255),
                                             'ApplicationConnectEnabled': (0,), 'SynchroniseToWired': (0,)})
        with self.assertRaises(WirelessConnectionError):
            self.plan(adjacent_network=False, synchronise_to_wired=True)

    def test_application_ids_require_existing_source_objects(self):
        for options in ({'application1': 88}, {'application2': 88}, {'status_monitor_application': 88}):
            with self.subTest(options=options), self.assertRaises(WirelessConnectionError):
                self.plan(**options)
        # The original permits both selectors to point at the same application.
        self.assertEqual(self.plan(application2=56).changes['Application'], (56, 56))

    def test_application_selector_excludes_literal_original_set_but_allows_unknown_group_app(self):
        frozen = topology([
            network(254, [unit(200, 'WGATE5F', '2.4.00')],
                    applications=(15, 56, 192, 205, 206, 208, 223, 224, 228, 255),
                    interface='CNI', parent='127.0.0.1:1'),
            network(200, [unit(123)]), network(123, [unit(99)]), network(99),
        ])
        for address in (192, 205, 206, 208, 223, 224, 228):
            for selector in ('application1', 'application2', 'status_monitor_application'):
                with self.subTest(address=address, selector=selector), self.assertRaises(WirelessConnectionError):
                    self.plan(frozen=frozen, **{selector: address})
        self.assertEqual(dict(self.plan(frozen=frozen, application1=15, application2=15,
                                        status_monitor_application=15).changes),
                         {'Application': (15, 15), 'StatusMonitorApplication': (15,)})
        self.assertEqual(dict(self.plan(frozen=frozen, application1=255,
                                        status_monitor_application=255).changes),
                         {'Application': (255, 255), 'StatusMonitorApplication': (255,)})

    def test_connection_hidden_in_remote_switch_mode(self):
        with self.assertRaises(WirelessConnectionError):
            self.plan(live=ConnectionSession(MapWirelessRemotes='1'), application2=202)

    def test_application_changes_with_existing_remotes_or_scenes_are_refused(self):
        for state in ({'RemoteIdentity1': '1 2 3 4'},
                      {'KeySceneMask8': '0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1'},
                      {'ApplicationSeconday4': '1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0'},
                      {'GroupAddress2': '255 255 255 255 255 255 255 255 255 255 255 255 255 255 255 7'},
                      {'SceneVectorOffset': '255 255 0 255 255 255 255 255'}):
            live = ConnectionSession(**state)
            with self.subTest(state=state), self.assertRaises(WirelessConnectionError):
                self.plan(live=live, application2=202)
            self.assertEqual(live.calls, [])

    def test_profile_identity_is_not_inferred_from_shared_unitspec(self):
        for kind, firmware in (('WGATE5N', '2.4.00'), ('WGATE5F', '2.2.89'),
                               ('WGATE5F', '2.5.00'), ('WRM2D1', '2.4.00')):
            with self.subTest(kind=kind, firmware=firmware), self.assertRaises(WirelessConnectionError):
                self.editor.plan(self.live.values(), topology=self.topology, source_network=254,
                                 unit_address=200, identity=(kind, firmware, None), application2=202)

    def test_admitted_firmware_boundaries_bind_exact_topology_identity(self):
        for firmware in ('2.2.90', '2.4.99'):
            frozen = FrozenTopology.from_xml(xml().replace(b'2.4.00', firmware.encode()))
            plan = self.editor.plan(self.live.values(), topology=frozen, source_network=254,
                                    unit_address=200, identity=('WGATE5F', firmware, None),
                                    application2=202)
            self.assertEqual(plan.changes['Application'], (56, 202))
        for original, replacement in ((b'WGATE5F', b'WGATE5N'), (b'2.4.00', b'2.3.00')):
            with self.subTest(replacement=replacement), self.assertRaises(WirelessConnectionError):
                self.plan(frozen=FrozenTopology.from_xml(xml().replace(original, replacement)),
                          application2=202)

    def test_invalid_parameter_domains_and_missing_snapshot_fail_closed(self):
        for options in ({'application1': -1}, {'application2': 256}, {'application1': True},
                         {'status_monitor_application': '56'}, {'destination_network': True},
                         {'adjacent_network': 1}, {'synchronise_to_wired': 'yes'}):
            with self.subTest(options=options), self.assertRaises(WirelessConnectionError):
                self.plan(**options)
        del self.live.current['ApplicationConnectEnabled']
        with self.assertRaises(WirelessConnectionError):
            self.plan(application2=202)

    def test_missing_duplicate_or_unsafe_xml_is_refused(self):
        cases = [
            b'<Installation><Project><Address>P</Address></Project></Installation>',
            xml([source(), source(), network(200)]),
            xml([source(unit(200, 'WGATE5F', '2.4.00')), network(200)]),
            xml().replace(b'<Application><Address>56</Address><TagName>A56</TagName></Application>', b''),
            b'<!DOCTYPE Installation [<!ENTITY a "P">]>' + xml(),
            b'<Installation>',
        ]
        for value in cases:
            with self.subTest(xml=value[:80]), self.assertRaises(WirelessConnectionError):
                self.plan(frozen=FrozenTopology.from_xml(value), application2=202)

    def test_native_apply_requires_database_source_exact_lock_and_exclusivity(self):
        plan = self.plan(application2=202)
        for attribute, value in (('source', '//P/254/p/200'), ('source', '/db//P/123/p/200'),
                                  ('source', '/db//OTHER/254/p/200'), ('source', '/db//P/254/p/199'),
                                  ('lock_address', '//P/123'), ('lock_address', '//P'),
                                  ('unit_type', 'WGATE5N'), ('firmware', '2.3.00')):
            live = ConnectionSession()
            setattr(live, attribute, value)
            with self.subTest(attribute=attribute, value=value), self.assertRaises(WirelessConnectionError):
                self.apply(plan, live=live)
            self.assertEqual(live.calls, [])
        with self.assertRaises(WirelessConnectionError):
            self.apply(plan, exclusive_project=False)
        self.assertEqual(self.live.calls, [])

    def test_current_parameters_and_topology_are_stale_checked_before_writes(self):
        plan = self.plan(application2=202)
        for name, value in (('Application', '57 255'), ('MapWirelessRemotes', '1'),
                             ('ForwardingRoute', '18 123 255 255 255 255 255'),
                             ('RemoteIdentity8', '1 2 3 4'),
                             ('SceneVectorOffset', '0 255 255 255 255 255 255 255')):
            live = ConnectionSession(**{name: value})
            with self.subTest(name=name), self.assertRaises(WirelessConnectionError):
                self.apply(plan, live=live)
            self.assertEqual(live.calls, [])
        altered = FrozenTopology.from_xml(xml().replace(b'<Address>99</Address>', b'<Address>98</Address>'))
        with self.assertRaises(WirelessConnectionError):
            self.apply(plan, frozen=altered)
        self.assertEqual(self.live.calls, [])

    def test_serialized_plan_roundtrip_rederives_changes_and_rejects_forgery(self):
        plan = self.plan(application2=202, destination_network=99)
        document = json.loads(json.dumps(plan.as_dict()))
        self.assertEqual(WirelessConnectionPlan.from_dict(document), plan)
        self.live.reads.clear()
        for name, value in (('ForwardingRoute', [27, 80, 99, 255, 255, 255, 255]),
                             ('GroupAddress1', [0] * 16), ('Application', [56, 88])):
            forged = deepcopy(document)
            forged['changes'][name] = value
            with self.subTest(name=name), self.assertRaises(WirelessConnectionError):
                self.apply(WirelessConnectionPlan.from_dict(forged))
            self.assertEqual(self.live.calls, [])
            self.assertEqual(self.live.reads, [])
        for bad in ({'format': 'other'}, dict(document, expected=1)):
            with self.assertRaises(WirelessConnectionError):
                WirelessConnectionPlan.from_dict(bad)

    def test_frozen_topology_does_not_expose_mutable_nested_state(self):
        original = self.topology.as_dict()
        restored = FrozenTopology.from_dict(json.loads(json.dumps(original)))
        self.assertEqual(restored, self.topology)
        exposed = self.topology.facts
        exposed['networks'].clear()
        original['facts']['networks'].clear()
        self.assertEqual(len(self.topology.facts['networks']), 4)
        self.assertEqual(self.plan(destination_network=99).changes['ForwardingRoute'],
                         (27, 123, 99, 255, 255, 255, 255))
        with self.assertRaises(WirelessConnectionError):
            FrozenTopology.from_dict(original)
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            self.topology.document = '{}'

    def test_native_schema_address_or_bit_size_change_fails_before_parameter_writes(self):
        plan = self.plan(application2=202)
        for field, value in (('Address', '67'), ('BitSize', '16')):
            live = ConnectionSession()
            changed = dict(live.spec.parameters)
            prior = changed['ForwardingRoute']
            changed['ForwardingRoute'] = ParameterSpec(prior.name, prior.type, prior.source,
                                                       {**prior.fields, field: value})
            live.spec = UnitSpec('WGATE5X_2.xml', live.spec.metadata, live.spec.sources, changed)
            with self.subTest(field=field), self.assertRaises(WirelessConnectionError):
                self.apply(plan, live=live)
            self.assertEqual(live.calls, [])

    def test_failed_set_is_not_retried_or_rolled_back(self):
        plan = self.plan(application2=202, destination_network=99, status_monitor_application=57)
        self.live.failure = 'ForwardingRoute'
        with self.assertRaises(WirelessConnectionApplyError) as failure:
            self.apply(plan)
        self.assertEqual([name for name, _ in self.live.calls],
                         ['Application', 'ForwardingMode', 'ForwardingRoute'])
        self.assertFalse(failure.exception.details['saved'])
        self.assertFalse(failure.exception.details['retry_performed'])
        self.assertFalse(failure.exception.details['device_verified'])
        self.assertEqual(self.live.current['StatusMonitorApplication'], '56')

    def test_plan_snapshots_are_immutable_and_apply_preserves_all_other_values(self):
        current = self.live.values()
        plan = self.plan(application2=202, destination_network=99)
        with self.assertRaises(TypeError):
            plan.changes['Application'] = (56, 88)
        with self.assertRaises(TypeError):
            plan.expected['Application'] = (57, 255)
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            plan.changes = {}
        document = plan.as_dict()
        document['changes']['Application'][1] = 88
        self.assertEqual(plan.changes['Application'], (56, 202))
        result = self.apply(plan)
        self.assertTrue(result['verified'])
        expected = dict(current, Application='56 202', ForwardingMode='1',
                        ForwardingRoute='27 123 99 255 255 255 255')
        self.assertEqual(self.live.values(), expected)
        self.assertEqual({name for name, _ in self.live.calls},
                         {'Application', 'ForwardingMode', 'ForwardingRoute'})


if __name__ == '__main__':
    unittest.main()
