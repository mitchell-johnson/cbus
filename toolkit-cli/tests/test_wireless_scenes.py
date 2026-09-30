"""Independent synthetic WGATE5F Scene packing and fail-closed editor tests."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import unittest

from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from cbus_toolkit.wireless_scenes import (
    FrozenSceneProject, WirelessScenesApplyError, WirelessScenesEditor,
    WirelessScenesError, WirelessScenesPlan,
)
from test_wireless_connection import ConnectionSession, fixture as connection_fixture


def fixture():
    """Use literal schema coordinates, never the editor's layout constants."""
    base = connection_fixture()
    parameters = dict(base.parameters)
    for name, address, count in (('SceneTriggerLevel', 0x138, 8),
                                  ('SceneTriggerRate', 0x140, 8), ('SceneVector', 0x158, 100)):
        fields = {'Name': name, 'Type': 'int', 'Address': str(address), 'ArraySize': str(count),
                  'BitSize': '8', 'BitAddress': '0', 'ArraySkip': '0', 'MinValue': '0', 'MaxValue': '255',
                  'DefaultValue': ' '.join(['255'] * count)}
        parameters[name] = ParameterSpec(name, 'int', 'literal-scenes.xml', fields)
    return UnitSpec('WGATE5X_2.xml', base.metadata, base.sources, parameters)


def group(address, levels=()):
    children = ''.join(f'<Level Value="{number}"><Address>{number}</Address>'
                       f'<TagName>Action {number}</TagName></Level>' for number in levels)
    return f'<Group><Address>{address}</Address><TagName>Group {address}</TagName>{children}</Group>'


def application(address, groups):
    return (f'<Application><Address>{address}</Address><TagName>App {address}</TagName>'
            + ''.join(groups) + '</Application>')


def project_xml(apps=None, *, kind='WGATE5F', firmware='2.4.00'):
    if apps is None:
        apps = [application(56, [group(i) for i in (*range(61), 254)]),
                application(57, [group(i) for i in (*range(61), 254)]),
                application(202, [group(10, (20, 21)), group(11, (20, 21)), group(255)])]
    return (f'<Installation><Project><Address>P</Address><Network><Address>254</Address>'
            '<Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>'
            f'<Unit><Address>200</Address><UnitType>{kind}</UnitType><FirmwareVersion>{firmware}</FirmwareVersion></Unit>'
            + ''.join(apps) + '</Network></Project></Installation>').encode()


def scene(entries=((7, 0), (9, 255)), *, application='primary', trigger=10, action=20, rate=5):
    return {'application': application, 'trigger_group': trigger, 'trigger_level': action, 'rate': rate,
            'entries': [{'group': group, 'level': level} for group, level in entries]}


def two_scenes():
    return [scene(), scene(((3, 128),), application='secondary', trigger=11, action=21, rate=15)]


def text(values):
    return ' '.join(map(str, values))


class SceneSession(ConnectionSession):
    def __init__(self, **current):
        super().__init__()
        self.spec = fixture()
        self.current = self.spec.defaults()
        self.current.update({'MapWirelessRemotes': '1', 'Application': '56 57',
                             'SceneVector': text(range(100)), **current})


def loaded_session(**current):
    """Two valid loaded scenes before any preserved remote ordinal references."""
    return SceneSession(**{
        'SceneTriggerGroup': '10 10 255 255 255 255 255 255',
        'SceneTriggerLevel': '20 20 255 255 255 255 255 255',
        'SceneTriggerRate': '0 0 255 255 255 255 255 255',
        'SceneVectorOffset': '0 131 255 255 255 255 255 255',
        'SceneVector': text((8, 1, 255, 4, 254, 255) + tuple(range(6, 100))),
        **current,
    })


class WirelessScenesTest(unittest.TestCase):
    def setUp(self):
        self.editor = WirelessScenesEditor(fixture())
        self.live = SceneSession()
        self.project = FrozenSceneProject.from_xml(project_xml())

    def plan(self, scenes=None, *, live=None, project=None, identity=('WGATE5F', '2.4.00', None)):
        return self.editor.plan((live or self.live).values(), project=project or self.project,
                                source_network=254, unit_address=200, identity=identity,
                                scenes=two_scenes() if scenes is None else scenes)

    def apply(self, plan, *, live=None, project=None, exclusive_project=True):
        return self.editor.apply(live or self.live, plan, project=project or self.project,
                                 exclusive_project=exclusive_project)

    def test_literal_primary_secondary_arrays_level255_and_exact_vector_suffix(self):
        plan = self.plan()
        self.assertEqual(dict(plan.changes), {
            'SceneTriggerGroup': (10, 11, 255, 255, 255, 255, 255, 255),
            'SceneTriggerLevel': (20, 21, 255, 255, 255, 255, 255, 255),
            'SceneTriggerRate': (5, 15, 0, 0, 0, 0, 0, 0),
            'SceneVectorOffset': (0, 133, 255, 255, 255, 255, 255, 255),
            'SceneVector': (7, 0, 9, 255, 255, 3, 128, 255) + tuple(range(8, 100)),
        })
        image = self.editor.codec.encode_many(plan.changes).apply(MemoryImage.from_bytes(b'\xA5' * 0x200))
        self.assertEqual(image.read(0x130, 24), bytes((10, 11, 255, 255, 255, 255, 255, 255,
                                                    20, 21, 255, 255, 255, 255, 255, 255,
                                                    5, 15, 0, 0, 0, 0, 0, 0)))
        self.assertEqual(image.read(0x148, 8), b'\xA5' * 8)
        self.assertEqual(image.read(0x150, 16), bytes((0, 133, 255, 255, 255, 255, 255, 255,
                                                    7, 0, 9, 255, 255, 3, 128, 255)))
        self.assertEqual(image.read(0x160, 92), bytes(range(8, 100)))

    def test_empty_scene_costs_one_byte_and_eight_scenes_keep_literal_offsets(self):
        empty = scene((), trigger=255, action=255, rate=0)
        single = self.plan([empty])
        self.assertEqual(single.changes['SceneVectorOffset'], (0, 255, 255, 255, 255, 255, 255, 255))
        self.assertEqual(single.changes['SceneVector'], (255,) + tuple(range(1, 100)))
        rows = [dict(empty, application='secondary' if i % 2 else 'primary') for i in range(8)]
        eight = self.plan(rows)
        self.assertEqual(eight.changes['SceneVectorOffset'], (0, 129, 2, 131, 4, 133, 6, 135))
        self.assertEqual(eight.changes['SceneVector'], (255,) * 8 + tuple(range(8, 100)))
        with self.assertRaises(WirelessScenesError):
            self.plan(rows + [empty])

    def test_complete_scene_states_at_99_100_and_101_bytes(self):
        # Final layout validity is distinct from the original GUI's Add button sequence.
        forty_nine = scene(tuple((i, 255 if i == 48 else i) for i in range(49)))
        expected_pairs = tuple(value for i in range(49) for value in (i, 255 if i == 48 else i))
        at_99 = self.plan([forty_nine])
        self.assertEqual(at_99.changes['SceneVector'], expected_pairs + (255, 99))
        self.assertEqual(at_99.changes['SceneVectorOffset'], (0, 255, 255, 255, 255, 255, 255, 255))
        at_100 = self.plan([forty_nine, scene((), trigger=255, action=255, rate=0)])
        self.assertEqual(at_100.changes['SceneVector'], expected_pairs + (255, 255))
        self.assertEqual(at_100.changes['SceneVectorOffset'], (0, 99, 255, 255, 255, 255, 255, 255))
        with self.assertRaisesRegex(WirelessScenesError, '100-byte'):
            self.plan([scene(tuple((i, i) for i in range(50)))])

    def test_identical_scene_bodies_are_serialized_separately(self):
        plan = self.plan([scene(((7, 255),), rate=0), scene(((7, 255),), rate=15)])
        self.assertEqual(plan.changes['SceneVectorOffset'], (0, 3, 255, 255, 255, 255, 255, 255))
        self.assertEqual(plan.changes['SceneVector'], (7, 255, 255, 7, 255, 255) + tuple(range(6, 100)))
        self.assertEqual(plan.changes['SceneTriggerRate'], (0, 15, 0, 0, 0, 0, 0, 0))

    def test_clear_all_scenes_preserves_entire_loaded_vector(self):
        self.apply(self.plan())
        before = self.live.values()
        plan = self.plan([])
        self.assertEqual(dict(plan.changes), {'SceneTriggerGroup': (255,) * 8, 'SceneTriggerLevel': (255,) * 8,
                                             'SceneTriggerRate': (0,) * 8, 'SceneVectorOffset': (255,) * 8})
        self.apply(plan)
        self.assertEqual(self.live.current['SceneVector'], before['SceneVector'])

    def test_shorter_replacement_retains_old_long_scene_bytes_after_new_terminator(self):
        self.apply(self.plan([scene(((7, 1), (8, 2), (9, 3), (10, 4)))]))
        plan = self.plan([scene(((0, 255),), rate=0)])
        self.assertEqual(plan.changes['SceneVector'], (0, 255, 255, 2, 9, 3, 10, 4, 255) + tuple(range(9, 100)))

    def test_show_decodes_secondary_empty_and_level255_without_physical_claim(self):
        self.apply(self.plan([*two_scenes(), scene((), trigger=255, action=255, rate=0)]))
        view = self.editor.show(self.live.values())
        self.assertEqual(view['scenes'], [*two_scenes(), scene((), trigger=255, action=255, rate=0)])
        self.assertTrue(view['scene_controls_visible'])
        self.assertFalse(view['metadata_created'])
        self.assertFalse(view['device_verified'])

    def test_duplicate_loaded_offsets_form_separate_scene_objects_and_repack(self):
        live = SceneSession(SceneVectorOffset='0 128 255 255 255 255 255 255',
                            SceneVector=text((7, 255, 255) + tuple(range(3, 100))),
                            SceneTriggerGroup='10 11 255 255 255 255 255 255',
                            SceneTriggerLevel='20 21 255 255 255 255 255 255',
                            SceneTriggerRate='0 15 255 255 255 255 255 255')
        view = self.editor.show(live.values())
        self.assertEqual(view['scenes'], [scene(((7, 255),), rate=0),
                                          scene(((7, 255),), application='secondary', trigger=11, action=21, rate=15)])
        self.assertEqual(self.plan(view['scenes'], live=live).changes['SceneVectorOffset'],
                         (0, 131, 255, 255, 255, 255, 255, 255))

    def test_domains_and_unique_group_membership_fail_closed(self):
        bad = [dict(scene(), application='all'), dict(scene(), rate=16), dict(scene(), rate=True),
               dict(scene(), trigger_group=256), dict(scene(), trigger_level=-1),
               dict(scene(), trigger_group=255, trigger_level=20), scene(((255, 0),)),
               scene(((7, 256),)), scene(((7, True),)), scene(((7, 0), (7, 255))),
               dict(scene(), entries='7 0'), {**scene(), 'extra': 1}]
        for row in bad:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.plan([row])
        with self.assertRaises(WirelessScenesError):
            self.plan({'scene': scene()})
        self.assertEqual(self.live.calls, [])

    def test_boundary_group_addresses_and_levels_are_literal_bytes(self):
        plan = self.plan([scene(((0, 0), (254, 255)), rate=15)])
        self.assertEqual(plan.changes['SceneVector'][:5], (0, 0, 254, 255, 255))
        self.assertEqual(plan.changes['SceneTriggerRate'], (15, 0, 0, 0, 0, 0, 0, 0))

    def test_current_active_rate_outside_original_enum_is_refused(self):
        for rate in (16, 127, 128, 255):
            live = SceneSession(SceneVectorOffset='0 255 255 255 255 255 255 255',
                                SceneVector=text((255,) + tuple(range(1, 100))),
                                SceneTriggerRate=text((rate,) + (255,) * 7))
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                self.plan([], live=live)
            self.assertEqual(live.calls, [])
        # Unused raw rate255 is never loaded as an active enum and saves as zero.
        self.assertEqual(self.plan([]).changes['SceneTriggerRate'], (0,) * 8)

    def test_sparse_invalid_and_unterminated_loaded_vectors_refuse_before_replacement(self):
        cases = [
            {'SceneVectorOffset': '255 0 255 255 255 255 255 255'},
            {'SceneVectorOffset': '100 255 255 255 255 255 255 255'},
            {'SceneVectorOffset': '228 255 255 255 255 255 255 255'},
            {'SceneVectorOffset': '99 255 255 255 255 255 255 255', 'SceneVector': text((255,) * 99 + (7,))},
            {'SceneVectorOffset': '0 255 255 255 255 255 255 255', 'SceneVector': text((7,) * 100)},
        ]
        for values in cases:
            values['SceneTriggerRate'] = '0 0 0 0 0 0 0 0'
            live = SceneSession(**values)
            with self.subTest(values=values), self.assertRaises(WirelessScenesError):
                self.plan([], live=live)
            self.assertEqual(live.calls, [])

    def test_existing_application_group_and_action_metadata_required(self):
        cases = [
            [application(56, [group(7), group(9)]), application(57, [group(3)])],
            [application(57, [group(3)]), application(202, [group(10, (20,)), group(11, (21,))])],
            [application(56, [group(7)]), application(57, [group(3)]),
             application(202, [group(10, (20,)), group(11, (21,))])],
            [application(56, [group(7), group(9)]), application(57, [group(3)]),
             application(202, [group(10, (20,))])],
            [application(56, [group(7), group(9)]), application(57, [group(3)]),
             application(202, [group(10, (20,)), group(11)])],
        ]
        for apps in cases:
            with self.subTest(apps=apps), self.assertRaises(WirelessScenesError):
                self.plan(project=FrozenSceneProject.from_xml(project_xml(apps)))
        mismatch = project_xml().replace(b'Value="21"', b'Value="22"')
        with self.assertRaises(WirelessScenesError):
            self.plan(project=FrozenSceneProject.from_xml(mismatch))
        for values, rows in (({'Application': '255 57'}, [scene()]),
                              ({'Application': '56 255'}, [scene((), application='secondary')])):
            with self.subTest(values=values), self.assertRaises(WirelessScenesError):
                self.plan(rows, live=SceneSession(**values))
        self.assertEqual(self.live.calls, [])

    def test_missing_loaded_scene_metadata_cannot_be_bypassed_by_clear_replacement(self):
        payload = project_xml()
        cases = [
            project_xml([application(57, [group(4)]), application(202, [group(10, (20,)), group(255)])]),
            payload.replace(group(8).encode(), b''),
            payload.replace(group(10, (20, 21)).encode(), b''),
            payload.replace(b'<Level Value="20"><Address>20</Address><TagName>Action 20</TagName></Level>', b''),
            payload.replace(b'Value="20"', b'Value="19"'),
        ]
        for source in cases:
            live = loaded_session()
            with self.subTest(source=source[:100]), self.assertRaises(WirelessScenesError):
                self.plan([], live=live, project=FrozenSceneProject.from_xml(source))
            self.assertEqual(live.calls, [])

    def test_missing_trigger_application_refused_even_when_clearing_all_scenes(self):
        project = FrozenSceneProject.from_xml(project_xml([application(56, []), application(57, [])]))
        with self.assertRaises(WirelessScenesError):
            self.plan([], project=project)

    def test_remote_scene_references_are_preserved_and_cannot_be_invalidated(self):
        mask = text((0,) * 15 + (1,))
        groups = text((255,) * 15 + (22,))  # Scene2 Toggle, literal 0x16
        live = loaded_session(RemoteIdentity8='1 2 3 4', KeySceneMask8=mask, GroupAddress8=groups)
        self.assertTrue(self.apply(self.plan(live=live), live=live)['verified'])
        for rows in ([scene()], [scene(), scene((), trigger=11, action=21)],
                     [scene(), scene(((3, 1),), trigger=255, action=255)],
                     [scene(), scene(((3, 1),), trigger=11, action=255)]):
            with self.subTest(rows=rows), self.assertRaises(WirelessScenesError):
                self.plan(rows, live=live)
        live.current['GroupAddress8'] = text((255,) * 15 + (19,))  # Unsupported command3, no normalization.
        with self.assertRaises(WirelessScenesError):
            self.plan(live=live)

    def test_scene_set_may_reference_empty_scene_with_existing_trigger_and_action(self):
        live = loaded_session(RemoteIdentity1='1 2 3 4', KeySceneMask1=text((1,) + (0,) * 15),
                              GroupAddress1=text((1,) + (255,) * 15))
        plan = self.plan([scene((), rate=0)], live=live)
        self.apply(plan, live=live)
        self.assertEqual(live.current['KeySceneMask1'], text((1,) + (0,) * 15))
        self.assertEqual(live.current['GroupAddress1'], text((1,) + (255,) * 15))

    def test_invalid_loaded_remote_reference_cannot_be_repaired_by_new_scene(self):
        live = SceneSession(RemoteIdentity1='1 2 3 4', KeySceneMask1=text((1,) + (0,) * 15),
                            GroupAddress1=text((1,) + (255,) * 15))
        with self.assertRaises(WirelessScenesError):
            self.plan(live=live)
        self.assertEqual(live.calls, [])

    def test_apply_preserves_all_eight_remote_tables_and_unrelated_connection_parameters(self):
        self.live = loaded_session()
        for remote in range(1, 9):
            self.live.current.update({f'RemoteIdentity{remote}': text((remote, 33, 66, 99)),
                                      f'KeySceneMask{remote}': text((1,) + (0,) * 14 + (1,)),
                                      f'ApplicationSeconday{remote}': '1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 1',
                                      f'GroupAddress{remote}': text((1,) + tuple(range(remote, remote + 14)) + (22,))})
        self.live.current.update(ApplicationConnectEnabled='1', ForwardingMode='1', SynchroniseToWired='1',
                                 ForwardingRoute='27 123 99 255 255 255 255', StatusMonitorApplication='57')
        before = self.live.values()
        plan = self.plan()
        image = self.editor.codec.encode_many(before).apply(MemoryImage.from_bytes(b'\xA5' * 0x200))
        edited = self.editor.codec.encode_many(plan.changes).apply(image)
        self.assertEqual(edited.read(0x70, 0xC0), image.read(0x70, 0xC0))
        self.assertEqual(edited.read(0x20, 0x30), image.read(0x20, 0x30))
        result = self.apply(plan)
        expected = {**before, **{name: text(values) for name, values in plan.changes.items()}}
        self.assertEqual(self.live.values(), expected)
        self.assertEqual([name for name, _ in self.live.calls],
                         ['SceneTriggerGroup', 'SceneTriggerLevel', 'SceneTriggerRate', 'SceneVectorOffset', 'SceneVector'])
        self.assertTrue(result['remote_mappings_preserved'])
        self.assertTrue(result['unrelated_parameters_preserved'])
        for field in ('saved', 'metadata_created', 'original_toolkit_executed', 'whole_dialog_save_executed', 'device_verified'):
            self.assertFalse(result[field])

    def test_profile_and_mode_guards_do_not_infer_support_from_shared_spec(self):
        with self.assertRaises(WirelessScenesError):
            self.plan(live=SceneSession(MapWirelessRemotes='0'))
        for kind, firmware in (('WGATE5N', '2.4.00'), ('WGATE5F', '2.2.89'), ('WGATE5F', '2.5.00')):
            project = FrozenSceneProject.from_xml(project_xml(kind=kind, firmware=firmware))
            with self.subTest(kind=kind, firmware=firmware), self.assertRaises(ValueError):
                self.plan(project=project, identity=(kind, firmware, None))
        for firmware in ('2.2.90', '2.4.99'):
            project = FrozenSceneProject.from_xml(project_xml(firmware=firmware))
            self.assertTrue(self.plan(project=project, identity=('WGATE5F', firmware, None)).changes)
        with self.assertRaises(WirelessScenesError):
            self.plan(identity=('WGATE5F', '2.3.00', None))

    def test_constructor_and_current_snapshot_require_exact_schema_and_shapes(self):
        base = fixture()
        with self.assertRaises(WirelessScenesError):
            WirelessScenesEditor(UnitSpec('WGATE5X.xml', base.metadata, base.sources, base.parameters))
        for replacement in (None, {'Address': '345'}, {'BitSize': '16'}, {'ArraySize': '99'}):
            params = dict(base.parameters)
            prior = params.pop('SceneVector')
            if replacement:
                params['SceneVector'] = ParameterSpec(prior.name, prior.type, prior.source, {**prior.fields, **replacement})
            with self.subTest(replacement=replacement), self.assertRaises(WirelessScenesError):
                WirelessScenesEditor(UnitSpec(base.filename, base.metadata, base.sources, params))
        for values in ({'SceneVector': '255'}, {'SceneTriggerRate': '0 0 0 0 0 0 0 256'},
                       {'KeySceneMask1': text((2,) + (0,) * 15)}):
            with self.subTest(values=values), self.assertRaises(WirelessScenesError):
                self.plan(live=SceneSession(**values))

    def test_frozen_metadata_roundtrip_and_nested_mutations_are_isolated(self):
        serialized = self.project.as_dict()
        self.assertEqual(FrozenSceneProject.from_dict(json.loads(json.dumps(serialized))), self.project)
        exposed = self.project.applications(254)
        exposed[56]['groups'].clear()
        serialized['metadata'][0]['applications'].clear()
        self.assertTrue(self.project.applications(254)[56]['groups'])
        self.assertTrue(self.plan().changes)
        with self.assertRaises(ValueError):
            FrozenSceneProject.from_dict(serialized)
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            self.project.metadata = '[]'

    def test_duplicate_group_action_and_unsafe_xml_metadata_fail_closed(self):
        cases = [project_xml([application(56, [group(7), group(7)])]),
                 project_xml([application(202, [group(10, (20, 20))])]),
                 project_xml().replace(b'Value="20"', b'Value="256"'),
                 project_xml().replace(b'Value="20"', b'Value="x"'),
                 project_xml().replace(b'<Level Value="20"><Address>20</Address>',
                                       b'<Level Value="20"><Address>20</Address><Value>20</Value>'),
                 b'<!DOCTYPE Installation [<!ENTITY a "P">]>' + project_xml()]
        for payload in cases:
            with self.subTest(payload=payload[:80]), self.assertRaises(ValueError):
                FrozenSceneProject.from_xml(payload)

    def test_xml_utf16_dtd_and_non_utf8_payloads_are_rejected_before_parse(self):
        dtd = '<!DOCTYPE Installation [<!ENTITY a "P">]>' + project_xml().decode()
        for payload in (dtd.encode('utf-16'), dtd.encode('utf-16-be'),
                        project_xml().decode().encode('utf-16-le'),
                        project_xml().replace(b'App 56', b'App \xff')):
            with self.subTest(prefix=payload[:30]), self.assertRaises(ValueError):
                FrozenSceneProject.from_xml(payload)

    def test_native_level_value_attribute_and_legacy_child_have_identical_facts(self):
        payload = project_xml()
        for value in (20, 21):
            payload = payload.replace(f'<Level Value="{value}">'.encode(),
                                      f'<Level><Value>{value}</Value>'.encode())
        legacy = FrozenSceneProject.from_xml(payload)
        self.assertEqual(legacy.fingerprint, self.project.fingerprint)
        self.assertEqual(self.plan(project=legacy).changes['SceneVector'][:8], (7, 0, 9, 255, 255, 3, 128, 255))

    def test_plan_is_immutable_and_copies_input_scenes_and_snapshots(self):
        rows = two_scenes()
        plan = self.plan(rows)
        rows[0]['entries'][0]['group'] = 44
        exposed = plan.scenes
        exposed[0]['entries'].clear()
        self.assertEqual(plan.scenes, two_scenes())
        for values in (plan.expected, plan.changes):
            with self.assertRaises(TypeError):
                values['SceneVector'] = (0,) * 100
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            plan.scene_document = '[]'
        self.assertEqual(WirelessScenesPlan.from_dict(json.loads(json.dumps(plan.as_dict()))), plan)

    def test_forged_scene_changes_vector_suffix_metadata_and_ownership_fail_before_io(self):
        document = self.plan().as_dict()
        cases = []
        wrong_prefix = deepcopy(document)
        wrong_prefix['changes']['SceneVector'][0] = 9
        cases.append(wrong_prefix)
        wrong_tail = deepcopy(document)
        wrong_tail['changes']['SceneVector'][99] = 55
        cases.append(wrong_tail)
        unauthorized = deepcopy(document)
        unauthorized['changes']['GroupAddress1'] = [0] * 16
        cases.append(unauthorized)
        scenes = deepcopy(document)
        scenes['scenes'][0]['entries'][0]['level'] = 255
        cases.append(scenes)
        metadata = deepcopy(document)
        metadata['project']['facts_sha256'] = '0' * 64
        cases.append(metadata)
        self.live.reads.clear()
        for data in cases:
            with self.subTest(data=data['changes']), self.assertRaises(ValueError):
                self.apply(WirelessScenesPlan.from_dict(data))
            self.assertEqual(self.live.reads, [])
            self.assertEqual(self.live.calls, [])
        for data in (None, [], {}, {'format': 'other'}, dict(document, expected=1)):
            with self.subTest(data=data), self.assertRaises(ValueError):
                WirelessScenesPlan.from_dict(data)

    def test_source_lock_identity_and_exclusivity_fail_before_any_session_io(self):
        plan = self.plan()
        for field, value in (('source', '//P/254/p/200'), ('source', '/db//P/254/p/201'),
                              ('source', '/db//Q/254/p/200'), ('lock_address', '//P/123'),
                              ('unit_type', 'WGATE5N'), ('firmware', '2.3.00')):
            live = SceneSession()
            setattr(live, field, value)
            with self.subTest(field=field, value=value), self.assertRaises(WirelessScenesError):
                self.apply(plan, live=live)
            self.assertEqual(live.reads, [])
            self.assertEqual(live.calls, [])
        self.live.reads.clear()
        with self.assertRaises(WirelessScenesError):
            self.apply(plan, exclusive_project=False)
        self.assertEqual(self.live.reads, [])

    def test_stale_metadata_and_all_scene_and_remote_dependencies_refuse_before_writes(self):
        plan = self.plan()
        changed_project = FrozenSceneProject.from_xml(project_xml().replace(b'Group 7', b'Renamed 7'))
        self.live.reads.clear()
        with self.assertRaises(WirelessScenesError):
            self.apply(plan, project=changed_project)
        self.assertEqual(self.live.reads, [])
        changes = {'SceneVector': text((44,) + tuple(range(1, 100))),
                   'SceneTriggerGroup': '1 255 255 255 255 255 255 255',
                   'Application': '57 56', 'MapWirelessRemotes': '0', 'RemoteIdentity8': '1 2 3 4',
                   'ApplicationSeconday1': text((1,) + (0,) * 15), 'GroupAddress5': text((42,) + (255,) * 15)}
        for name, value in changes.items():
            live = SceneSession(**{name: value})
            with self.subTest(name=name), self.assertRaises(WirelessScenesError):
                self.apply(plan, live=live)
            self.assertEqual(live.calls, [])

    def test_native_schema_bitsize_drift_refuses_before_writes(self):
        plan = self.plan()
        params = dict(self.live.spec.parameters)
        prior = params['SceneVector']
        params['SceneVector'] = ParameterSpec(prior.name, prior.type, prior.source, dict(prior.fields, BitSize='16'))
        self.live.spec = UnitSpec(self.live.spec.filename, self.live.spec.metadata, self.live.spec.sources, params)
        with self.assertRaises(WirelessScenesError):
            self.apply(plan)
        self.assertEqual(self.live.calls, [])

    def test_partial_set_failure_never_retries_rolls_back_or_claims_save(self):
        plan = self.plan()
        self.live.failure = 'SceneVectorOffset'
        with self.assertRaises(WirelessScenesApplyError) as failed:
            self.apply(plan)
        expected = ['SceneTriggerGroup', 'SceneTriggerLevel', 'SceneTriggerRate', 'SceneVectorOffset']
        self.assertEqual([name for name, _ in self.live.calls], expected)
        self.assertEqual(failed.exception.details['attempted_parameters'], expected)
        self.assertEqual(self.live.current['SceneVector'], text(range(100)))
        for flag in ('saved', 'device_verified', 'retry_performed'):
            self.assertFalse(failed.exception.details[flag])

    def test_wrong_readback_or_unrelated_mutation_fails_without_retry(self):
        for corrupted, replacement in (('SceneVector', text((255,) * 100)), ('UnitAddress', '199')):
            class CorruptingSession(SceneSession):
                def set(self, name, value):
                    super().set(name, value)
                    if name == 'SceneVector':
                        self.current[corrupted] = replacement

            live = CorruptingSession()
            plan = self.plan(live=live)
            with self.subTest(corrupted=corrupted), self.assertRaises(WirelessScenesApplyError) as failure:
                self.apply(plan, live=live)
            self.assertEqual([name for name, _ in live.calls],
                             ['SceneTriggerGroup', 'SceneTriggerLevel', 'SceneTriggerRate', 'SceneVectorOffset', 'SceneVector'])
            self.assertFalse(failure.exception.details['saved'])
            self.assertFalse(failure.exception.details['retry_performed'])


if __name__ == '__main__':
    unittest.main()
