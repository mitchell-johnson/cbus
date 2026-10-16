"""Literal prompt outcomes and full-graph Level preservation, without vendors."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit.thermostat_remote_references import (plan_remote_references, snapshot_project,
    validate_remote_plan, verify_project_preservation)
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
from cbus_toolkit.unitspec import UnitSpecStore
from test_thermostat_remote_references import RAW, PATH, apply_graph, node, oid, project
from test_thermostat_settings import _spec


ZONES = (
    'Zone:unsw', 'Zone:1', 'Zones:unsw,1', 'Zone:2', 'Zones:unsw,2', 'Zones:1,2',
    'Zones:unsw,1,2', 'Zone:3', 'Zones:unsw,3', 'Zones:1,3', 'Zones:unsw,1,3',
    'Zones:2,3', 'Zones:unsw,2,3', 'Zones:1,2,3', 'Zones:unsw,1,2,3', 'Zone:4',
    'Zones:unsw,4', 'Zones:1,4', 'Zones:unsw,1,4', 'Zones:2,4', 'Zones:unsw,2,4',
    'Zones:1,2,4', 'Zones:unsw,1,2,4', 'Zones:3,4', 'Zones:unsw,3,4', 'Zones:1,3,4',
    'Zones:unsw,1,3,4', 'Zones:2,3,4', 'Zones:unsw,2,3,4', 'Zones:1,2,3,4', 'Zones:unsw,1,2,3,4')
ENABLED = dict(RAW, RemoteSetbackControlSource='2', RemoteSetbackOnGroup='21', RemoteSetbackOffGroup='22',
               NonEvapProgramEnabled='1', RemoteScheduleEnable='1', RemoteScheduleOnGroup='12',
               RemoteScheduleOffGroup='13', RemoteScheduleOverrideGroup='14')
ROLES = ((21, 'setback_on', 'setback', 'Setbk Enable '),
         (22, 'setback_off', 'setback', 'Setbk Disable '),
         (12, 'schedule_on', 'schedule', 'Sched Enable '),
         (13, 'schedule_off', 'schedule', 'Sched Disable '),
         (14, 'schedule_override', 'schedule', 'Sched Overrd '))


def seed(kind='PC_TSA', raw=None, applications=None, complete=False):
    raw = ENABLED if raw is None else raw
    root = ET.fromstring(project(kind, {203: [21, 22, 12, 13, 14]} if applications is None else applications, raw))
    for app in root.findall('./Project/Network/Application'):
        for group in list(app):
            if group.tag not in ('Group', 'NetVar'):
                continue
            app_address, group_address = app.findtext('Address'), group.findtext('Address')
            group.find('Level').set('Value', '207')
            extra = node(group, 'Level', 200, 'Value one at other address', oid(f'extra:{app_address}:{group_address}'))
            extra.set('Value', '1')
            if complete:
                for address in range(1, 32):
                    if address == 7:
                        continue
                    level = node(group, 'Level', address, 'Retain unusual ' + str(address),
                                 oid(f'complete:{app_address}:{group_address}:{address}'))
                    level.set('Value', str(255 - address))
    return ET.tostring(root, encoding='unicode')


def apply_levels(plan):
    root, objects = apply_graph(plan)
    receipts = {}
    for c in plan.level_creations:
        app = next(row for row in root.findall('./Project/Network/Application')
                   if row.findtext('Address') == str(c.application))
        group = next(row for row in list(app) if row.tag in ('Group', 'NetVar')
                     and row.findtext('Address') == str(c.group))
        identity = oid('created-level:' + repr(c.key))
        level = node(group, 'Level', c.address, c.name, identity)
        level.set('Value', str(c.value))
        ET.SubElement(level, 'TagsDLT')
        receipts[c.key] = identity
    return root, objects, receipts


class RemoteLevelTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for kind in ('THERMOSTATA', 'THERMOSTATB'):
            (self.folder / (kind + '.xml')).write_text(_spec(kind, set(RAW)))
        self.store = UnitSpecStore(self.folder)

    def plan(self, *, kind='PC_TSA', raw=None, xml=None, edits=None, prompts=None):
        raw = ENABLED if raw is None else raw
        return plan_remote_references(self.store, kind, raw, edits or {}, project_xml=xml or seed(kind, raw),
                                      unit_path=PATH, level_prompts=prompts)

    def test_four_prompt_choices_exact_order_labels_and_address_reuse(self):
        for setback in ('accept', 'decline'):
            for schedule in ('accept', 'decline'):
                with self.subTest(setback=setback, schedule=schedule):
                    p = self.plan(prompts={'setback': setback, 'schedule': schedule})
                    actual = [(c.application, c.group, c.address, c.value, c.initial_name, c.name, c.role, c.phase)
                              for c in p.level_creations]
                    expected = [(203, group, address, address, 'Level ' + str(address), prefix + ZONES[address - 1], role, phase)
                                for group, role, phase, prefix in ROLES
                                if {'setback': setback, 'schedule': schedule}[phase] == 'accept'
                                for address in range(1, 32) if address != 7]
                    self.assertEqual(actual, expected)
                    self.assertFalse(p.pp_mutation_required)
                    self.assertEqual(p.graph_mutation_required, setback == 'accept' or schedule == 'accept')
                    self.assertEqual(p.creations, ())
                    for phase, count in (('setback', 60), ('schedule', 90)):
                        receipt = p.as_dict()['level_prompts'][phase]
                        self.assertTrue(receipt['required'] and receipt['offered'])
                        self.assertEqual(receipt['response_used'], {'setback': setback, 'schedule': schedule}[phase])
                        self.assertEqual(receipt['created_count'], count if receipt['response_used'] == 'accept' else 0)
                    self.assertEqual(p.graph.applications[0].groups[0].levels[0].value, '207')
                    self.assertEqual(p.graph.applications[0].groups[0].levels[1].address, 200)
                    self.assertIs(validate_remote_plan(self.store, p), p)

    def test_default_decline_and_unoffered_accept_are_noops(self):
        default = self.plan()
        self.assertEqual(default.level_creations, ())
        self.assertFalse(default.apply_would_mutate)
        for complete, raw in ((True, ENABLED), (False, RAW)):
            with self.subTest(complete=complete):
                p = self.plan(raw=raw, xml=seed(raw=raw, complete=complete),
                              prompts={'setback': 'accept', 'schedule': 'accept'})
                self.assertFalse(p.apply_would_mutate)
                self.assertEqual(p.level_creations, ())
                for receipt in p.as_dict()['level_prompts'].values():
                    self.assertFalse(receipt['required'] or receipt['offered'] or receipt['executed'])
                    self.assertIsNone(receipt['response_used'])

    def test_aliases_lighting_group_zero_unused_and_inherited_order(self):
        for kind in ('PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5'):
            for application in (56, 203):
                with self.subTest(kind=kind, application=application):
                    raw = dict(RAW, RemoteSetbackControlSource='1', ApplicationNumber=str(application),
                               RemoteSetbackOnGroup='0', RemoteSetbackOffGroup='255')
                    p = self.plan(kind=kind, raw=raw, xml=seed(kind, raw, {application: []}),
                                  prompts={'setback': 'accept'})
                    self.assertEqual([(c.kind, c.application, c.address) for c in p.creations][:2],
                                     [('Group', application, 0), ('Group', application, 255)])
                    self.assertEqual([(c.application, c.group, c.address, c.value, c.name) for c in p.level_creations],
                                     [(application, 0, n, n, 'Setbk Enable ' + ZONES[n - 1]) for n in range(1, 32)])
                    self.assertTrue(p.as_dict()['level_prompts']['setback']['roles'][1]['unused'])
                    self.assertFalse(p.as_dict()['level_prompts']['schedule']['offered'])
        p = self.plan(xml=seed(applications={}), prompts={'setback': 'accept', 'schedule': 'accept'})
        self.assertEqual([(c.kind, c.address) for c in p.creations],
                         [('Application', 203), ('Group', 21), ('Group', 22), ('Group', 12), ('Group', 13), ('Group', 14)])
        self.assertEqual([(c.group, c.address) for c in p.level_creations],
                         [(group, address) for group in (21, 22, 12, 13, 14) for address in range(1, 32)])
        raw = dict(ENABLED, RemoteSetbackControlSource='1', RemoteSetbackOnGroup='12', RemoteSetbackOffGroup='13')
        p = self.plan(raw=raw, xml=seed(raw=raw, applications={56: [12, 13], 203: [12, 13, 14]}),
                      prompts={'setback': 'accept', 'schedule': 'accept'})
        self.assertEqual([(c.application, c.group, c.address, c.name) for c in p.level_creations if c.address == 1],
                         [(56, 12, 1, 'Setbk Enable Zone:unsw'), (56, 13, 1, 'Setbk Disable Zone:unsw'),
                          (203, 12, 1, 'Sched Enable Zone:unsw'), (203, 13, 1, 'Sched Disable Zone:unsw'),
                          (203, 14, 1, 'Sched Overrd Zone:unsw')])

    def test_strict_choices_preflight_and_replay(self):
        for prompts in ([], True, {'other': 'accept'}, {'setback': True}, {'schedule': 'ACCEPT'},
                        {'setback': 1}, {1: 'accept'}):
            with self.subTest(prompts=prompts), self.assertRaises(ThermostatTemplateError):
                self.plan(prompts=prompts)
        with self.assertRaisesRegex(ThermostatTemplateError, 'Basic'):
            self.plan(kind='PC_TSB', prompts={'schedule': 'accept'})
        with self.assertRaisesRegex(ThermostatTemplateError, 'duplicate'):
            self.plan(edits={'RemoteScheduleOnGroup': 21}, prompts={'setback': 'accept', 'schedule': 'accept'})
        p = self.plan(prompts={'setback': 'accept'})
        bad_level = replace(p.level_creations[0], value=True)
        for broken in (replace(p, level_creations=()), replace(p, level_prompts=(('setback', 'decline'), ('schedule', 'decline'))),
                       replace(p, level_prompts_json='{}'), replace(p, level_creations=(bad_level,) + p.level_creations[1:]),
                       replace(p, level_creations=tuple(reversed(p.level_creations)))):
            with self.subTest(tamper=broken.level_prompts_json), self.assertRaises(ThermostatTemplateError):
                validate_remote_plan(self.store, broken)

    def test_full_graph_preservation_and_exact_creation_receipts(self):
        for applications in ({203: [21, 22, 12, 13, 14]}, {}):
            with self.subTest(applications=applications):
                p = self.plan(xml=seed(applications=applications), prompts={'setback': 'accept', 'schedule': 'accept'})
                root, objects, levels = apply_levels(p)
                after = ET.tostring(root, encoding='unicode')
                def verify(text=after, receipts=levels, planned=p.level_creations):
                    return verify_project_preservation(p.project_xml, text, PATH, changed_parameters=p.expected,
                        created_oids=objects, created_level_oids=receipts, level_creations=planned)
                report = verify()
                self.assertTrue(report['preserved'])
                self.assertEqual(len(report['created_levels']), len(p.level_creations))
                for mutation in ('value', 'missing-value', 'raw-value', 'noncanonical-value', 'out-of-range-value',
                                 'tag', 'oid', 'parent', 'unexpected-level', 'existing-metadata'):
                    changed = ET.fromstring(after)
                    groups = changed.findall('./Project/Network/Application/NetVar')
                    first = groups[0].find("Level[Address='1']")
                    if mutation == 'value':
                        first.set('Value', '17')
                    elif mutation == 'missing-value':
                        del first.attrib['Value']
                    elif mutation == 'raw-value':
                        first.set('Value', 'oops')
                    elif mutation == 'noncanonical-value':
                        first.set('Value', '01')
                    elif mutation == 'out-of-range-value':
                        first.set('Value', '256')
                    elif mutation == 'tag':
                        first.find('TagName').text = 'different'
                    elif mutation == 'oid':
                        first.find('OID').text = oid('wrong-created')
                    elif mutation == 'parent':
                        groups[0].remove(first); groups[1].append(first)
                    elif mutation == 'unexpected-level':
                        extra = node(groups[0], 'Level', 201, 'hidden unexpected', oid('unplanned'))
                        extra.set('Value', '201')
                    elif applications:
                        groups[0].find("Level[Address='7']/{urn:remote:fixture}Opaque").text = 'changed'
                    else:
                        changed.find('./Project/Network/Unit/{urn:remote:fixture}Opaque').text = 'changed'
                    with self.subTest(mutation=mutation), self.assertRaises(ThermostatTemplateError):
                        verify(ET.tostring(changed, encoding='unicode'))
                for receipts in ({}, {**levels, (203, 21, 31): oid('wrong-receipt')},
                                 {**levels, (203, 21, 1): oid('unit')}):
                    with self.assertRaises(ThermostatTemplateError):
                        verify(receipts=receipts)
                # A second baseline preserves the exact new Level metadata.
                verify_project_preservation(after, after, PATH, changed_parameters=(), created_oids={})
                changed = ET.fromstring(after)
                changed.find('./Project/Network/Application/NetVar/Level').set('Opaque', 'drift')
                with self.assertRaises(ThermostatTemplateError):
                    verify_project_preservation(after, ET.tostring(changed, encoding='unicode'), PATH,
                                                changed_parameters=(), created_oids={})

    def test_default_decline_preserves_unrelated_opaque_or_missing_values(self):
        for used_role in (False, True):
            for value in (None, 'oops', '256', '010'):
                with self.subTest(used_role=used_role, value=value):
                    raw = ENABLED if used_role else RAW
                    root = ET.fromstring(seed(raw=raw, applications={203: [21, 22, 12, 13, 14]}
                                              if used_role else {56: [7], 203: []}))
                    group = next(row for row in root.findall('./Project/Network/Application')[0]
                                 if row.tag in ('Group', 'NetVar'))
                    level = group.find('Level')
                    self.assertIsNotNone(level)
                    if value is None:
                        del level.attrib['Value']
                    else:
                        level.set('Value', value)
                    before = ET.tostring(root, encoding='unicode')
                    p = self.plan(raw=raw, xml=before)
                    self.assertFalse(p.apply_would_mutate)
                    self.assertEqual(p.level_creations, ())
                    self.assertEqual(p.graph.applications[0].groups[0].levels[0].value, value)
                    self.assertTrue(verify_project_preservation(before, before, PATH,
                        changed_parameters=(), created_oids={})['preserved'])

    def test_accept_used_role_reuses_address_without_consuming_existing_value(self):
        for value in (None, 'oops', '256', '010'):
            with self.subTest(value=value):
                root = ET.fromstring(seed())
                level = root.find('./Project/Network/Application/NetVar/Level')
                self.assertIsNotNone(level)
                if value is None:
                    del level.attrib['Value']
                else:
                    level.set('Value', value)
                before = ET.tostring(root, encoding='unicode')
                p = self.plan(xml=before, prompts={'setback': 'accept'})
                self.assertEqual(p.graph.applications[0].groups[0].levels[0].value, value)
                self.assertEqual([(c.group, c.address) for c in p.level_creations],
                    [(group, address) for group in (21, 22) for address in range(1, 32) if address != 7])
                after, objects, levels = apply_levels(p)
                report = verify_project_preservation(before, ET.tostring(after, encoding='unicode'), PATH,
                    changed_parameters=p.expected, created_oids=objects,
                    created_level_oids=levels, level_creations=p.level_creations)
                self.assertTrue(report['preserved'] and report['existing_metadata_preserved'])
                retained = after.find('./Project/Network/Application/NetVar/Level')
                self.assertEqual(retained.get('Value'), value)
                drift = ET.fromstring(ET.tostring(after, encoding='unicode'))
                drift.find('./Project/Network/Application/NetVar/Level').set('Value', 'different')
                with self.assertRaises(ThermostatTemplateError):
                    verify_project_preservation(before, ET.tostring(drift, encoding='unicode'), PATH,
                        changed_parameters=p.expected, created_oids=objects,
                        created_level_oids=levels, level_creations=p.level_creations)

    def test_typed_level_snapshot_rejects_ambiguous_addresses(self):
        root = ET.fromstring(seed())
        group = root.find('./Project/Network/Application/NetVar')
        extra = node(group, 'Level', 7, 'duplicate', oid('duplicate-level'))
        extra.set('Value', '7')
        with self.assertRaises(ThermostatTemplateError):
            snapshot_project(ET.tostring(root, encoding='unicode'), PATH)

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_TOOLKIT_MAP'),
                         'Explicit original EXE/MAP required for static source verification')
    def test_optional_static_source(self):
        research = Path(__file__).resolve().parents[1] / 'research'
        sys.path.insert(0, str(research))
        from thermostat_remote_levels_static import inspect
        result = inspect(Path(os.environ['CBUS_TOOLKIT_EXE']), Path(os.environ['CBUS_TOOLKIT_MAP']))
        self.assertEqual(result, json.loads((research / 'fixtures/thermostat-remote-levels-source-review.json').read_text()))
        self.assertFalse(result['original_executed'])
        self.assertTrue(all(result['checks'].values()))
