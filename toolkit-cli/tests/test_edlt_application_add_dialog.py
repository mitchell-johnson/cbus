"""Recovered eDLT overload policy and ordered native parent projections."""
from dataclasses import replace
import json
from pathlib import Path
import unittest
from copy import deepcopy
from unittest.mock import patch
from xml.dom import minidom

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_application_add_dialog import candidates, normalize, resolve
from cbus_toolkit.edlt_display_model import EdltDisplayPreferences
from cbus_toolkit.edlt_parent_metadata import (plan_native_parent_metadata, NativeEdltParentTransaction, NativeEdltParentError)
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from tests import test_edlt_parent_add_dialog as parent_helpers
NamedClient, UNIT, widget = parent_helpers.NamedClient, parent_helpers.UNIT, parent_helpers.widget
from tests.test_edlt_parent_blank_reset import complete_spec, reset_source, reset_operations
from tests.test_edlt_parent_cache_panels import fixture as panels_fixture
from tests.test_edlt_parent_metadata import oid, NativeSession, FakeProgrammer, response

PREFS = dict(allow_user_defined=False, allow_legacy=False)


def operation(field='primary', **options):
    return {'op': 'add-application-dialog', 'field': field,
            'creation_preferences': dict(PREFS), **options}


def reset_spec():
    base = complete_spec(); parameters = dict(base.parameters)
    additions = [n for n in panels_fixture().parameters if n not in parameters]
    for name in [n for n in parameters if n.startswith('OwnedPadding')][:len(additions)]:
        del parameters[name]
    for name, parameter in panels_fixture().parameters.items():
        if name != 'NavWidgetType' and not name.endswith('WidgetType'):
            parameters[name] = parameter
    assert len(parameters) == 874
    return replace(base, parameters=parameters)


class ApplicationDialogPolicyTests(unittest.TestCase):
    def test_normal_and_widened_candidates_exact_endpoints(self):
        self.assertEqual(candidates({}, PREFS), tuple(range(48, 96)) + (112, 113, 114, 136))
        for flag in PREFS:
            with self.subTest(flag):
                settings = {**PREFS, flag: True}
                self.assertEqual(candidates({48: 'Used', 127: 'Used'}, settings),
                                 tuple(range(49, 127)) + (136,))

    def test_first_free_native_name_editability_and_description(self):
        row = resolve(operation(name=' New application ', description=' Details '),
                      {48: 'Existing'}, 'Site')
        self.assertEqual((row['address'], row['name'], row['description']), (49, 'New application', 'Details'))
        self.assertTrue(row['name_editable'])
        for address, name in ((56, 'Lighting'), (95, 'DALI'), (113, 'Irrigation Control'),
                              (114, 'Pool, Spa, Pond Control'), (136, 'Heating (Legacy)')):
            with self.subTest(address):
                row = resolve(operation(address=address), {}, 'Site')
                self.assertEqual(row['name'], name)
                self.assertFalse(row['name_editable'])
                with self.assertRaisesRegex(EdltError, 'not editable'):
                    resolve(operation(address=address, name='Override'), {}, 'Site')

    def test_native_warning_order_and_reserved_confirmation(self):
        cases = [({'name': ''}, '2241'), ({'name': ' Site '}, '2247'),
                 ({'name': ' EXISTING '}, '2242')]
        for options, code in cases:
            with self.subTest(code), self.assertRaisesRegex(EdltError, code):
                resolve(operation(address=97, creation_preferences={**PREFS, 'allow_user_defined': True},
                                  **options), {48: 'Existing'}, 'Site')
        op = operation(address=97, name='New', creation_preferences={**PREFS, 'allow_user_defined': True})
        with self.assertRaisesRegex(EdltError, '3171'):
            resolve(op, {}, 'Site', ((2, {98: 'New'}),))
        with self.assertRaisesRegex(EdltError, '2244'):
            resolve({**op, 'confirm_reserved': True}, {}, 'Site', ((2, {98: 'NEW'}),))
        row = resolve({**op, 'confirm_reserved': True}, {}, 'Site')
        self.assertTrue(row['reserved_confirmation'])

    def test_project_cross_network_same_address_uses_exact_name(self):
        with self.assertRaisesRegex(EdltError, '2245'):
            resolve(operation(address=49, name='New'), {}, 'Site', ((2, {49: 'NEW'}),))
        self.assertEqual(resolve(operation(address=49, name='New'), {}, 'Site',
                                 ((2, {49: 'New'}),))['outcome'], 'accepted')

    def test_cancel_does_not_validate_disabled_operator_edits(self):
        row = resolve(
            operation(cancel=True, address=202, name='', confirm_reserved=False), {}, 'Site')
        self.assertEqual(row['outcome'], 'cancelled')
        self.assertEqual(row['first_free_address'], 48)
        self.assertNotIn('name', row)
        with self.assertRaisesRegex(EdltError, 'no listed'):
            resolve(operation(cancel=True), {a: str(a) for a in candidates({}, PREFS)}, 'Site')

    def test_profile_and_option_shapes_do_not_accept_caller_bounds(self):
        for op in ({'op': 'add-application-dialog', 'field': 'primary'},
                   {**operation(), 'maximum_address': 100},
                   {**operation(), 'creation_preferences': {**PREFS, 'unknown': False}},
                   {**operation(), 'cancel': 1}, {**operation(), 'field': 'primary_application'}):
            with self.subTest(op), self.assertRaises(EdltError): normalize(op)

    def test_literal_application_policy_vector(self):
        path = Path(__file__).resolve().parents[2] / 'rust/testdata/vectors/edlt_application_add_dialog.json'
        vector = json.loads(path.read_text())
        for row in vector['cases']:
            with self.subTest(row['name']):
                call = lambda: resolve(row['operation'], {int(a): n for a, n in row['applications'].items()},
                    vector['project_tag_name'], tuple((n, {int(a): v for a, v in apps.items()})
                        for n, apps in row.get('other_networks', [])))
                if 'error' in row:
                    with self.assertRaisesRegex(EdltError, row['error']): call()
                else:
                    result = call()
                    for key, expected in row['expected'].items(): self.assertEqual(result[key], expected)


class ApplicationClient(NamedClient):
    description_reads = 0
    description_fault = None
    description_fault_after = 1

    def xml(self):
        doc = minidom.parseString(super().xml())
        for node in doc.getElementsByTagName('Application'):
            addresses = [n for n in node.childNodes if n.nodeType == n.ELEMENT_NODE and n.tagName == 'Address']
            if not addresses: continue
            address = int(addresses[0].firstChild.data)
            if 'description' not in self.applications[address]: continue
            description = [n for n in node.childNodes if n.nodeType == n.ELEMENT_NODE and n.tagName == 'Description'][0]
            for child in tuple(description.childNodes): description.removeChild(child)
            description.appendChild(doc.createTextNode(self.applications[address]['description']))
        return doc.toxml()

    def command(self, command):
        if command.startswith('DBGET !') and command.endswith('/Description'):
            self.commands.append(command); self.description_reads += 1
            if self.description_fault and self.description_reads >= self.description_fault_after:
                if self.description_fault == 'missing': return response(401, 'Bad object or device ID: Object is null')
                if self.description_fault == 'wrong': return response(342, command[6:] + '=Wrong description')
                if self.description_fault == 'other-path': return response(342, '!'+oid(999)+'/Description=New description')
                if self.description_fault == 'extra':
                    from cbus_toolkit.cgate import CGateResponse
                    line = '342 ' + command[6:] + '=New description'
                    return CGateResponse((line, '200 OK'), '200 OK', 200)
            identity = command[7:].split('/', 1)[0]
            for app in self.applications.values():
                if app['oid'] == identity and app.get('description'):
                    return response(342, command[6:] + '=' + app['description'])
            return response(401, 'Bad object or device ID: Object is null')
        if command.startswith('DBSETSAFE !') and '/Description ' in command:
            self.commands.append(command)
            identity, value = command[11:].split('/Description ', 1)
            for app in self.applications.values():
                if app['oid'] == identity:
                    app['description'] = value
                    return response()
            return response(401, 'Unknown OID')
        result = super().command(command)
        if command.startswith('DBADDSAFE ') and ' Application ' in command and result.code == 301:
            self.applications[int(command.split()[3])]['description'] = ''
        return result


class ApplicationParentTests(unittest.TestCase):
    def setUp(self):
        helper = parent_helpers.ParentAddTests(); helper.setUp()
        self.helper = helper; self.client = ApplicationClient(helper.spec)
        self.client.values = deepcopy(helper.client.values)
        self.client.applications = deepcopy(helper.client.applications)
        helper.client = self.client; self.editor = helper.editor
        self.client.applications[57] = dict(oid=oid(57), tag='Existing secondary', groups={})
        self.client.applications[203] = dict(oid=oid(203), tag='Enable Control', groups={})

    def plan(self, rows): return self.helper.plan(rows)

    def test_accepted_primary_then_group_add_uses_new_application(self):
        p = self.plan((operation(name='New primary'), dict(op='add-dialog', field='QuickStatusGroup', name='Status')))
        self.assertEqual([(c.kind, c.application, c.address, c.name) for c in p.creations],
                         [('Application', 48, 48, 'New primary'), ('Group', 48, 0, 'Status')])
        final = {**p.parent_plan.expected, **p.parent_plan.changes}
        self.assertEqual((final['PrimaryApplication'], final['QuickStatusGroup']), ((48,), (0,)))
        self.assertEqual(p.cache.find_application(48).name, 'New primary')

    def test_earlier_group_remains_in_old_application_and_future_group_new(self):
        p = self.plan((dict(op='add-dialog', field='QuickStatusGroup', name='Old status'),
                       operation(name='New primary'),
                       dict(op='add-corridor-dialog', field='link_group', name='Link')))
        self.assertEqual([(r.as_dict()['kind'], r.as_dict()['address']) for r in p.add_dialogs],
                         [('Group', 1), ('Application', 48), ('Group', 0)])
        self.assertEqual([(c.application, c.name) for c in p.creations if c.kind == 'Group'],
                         [(48, 'Link'), (56, 'Old status')])

    def test_cancelled_application_add_leaves_later_group_in_old_application(self):
        p = self.plan((operation(cancel=True), dict(op='add-dialog', field='QuickStatusGroup', name='Status')))
        self.assertEqual(p.add_dialogs[0].as_dict()['outcome'], 'cancelled')
        self.assertFalse(any(c.kind == 'Application' for c in p.creations))
        self.assertEqual(p.creations[0].application, 56)

    def test_repeated_primary_secondary_dialogs_allocate_sequentially(self):
        p = self.plan((operation(name='Primary'), operation('secondary', name='Secondary')))
        self.assertEqual([r.as_dict()['address'] for r in p.add_dialogs], [48, 49])
        self.assertEqual(p.parent_plan.changes['PrimaryApplication'], (48,))
        self.assertEqual(p.parent_plan.changes['SecondaryApplication'], (49,))

    def test_project_wide_inventory_is_consumed_from_xml(self):
        text = self.client.xml().replace('</Project>', '<Network><OID>' + oid(1000) +
            '</OID><Address>3</Address><Application><OID>' + oid(1001) +
            '</OID><Address>49</Address><TagName>NEW</TagName></Application></Network></Project>')
        with self.assertRaisesRegex(EdltError, '2244'):
            plan_native_parent_metadata(text, UNIT, self.editor.snapshot(self.client.values), self.editor,
                (operation(name='New'), widget()), display_preferences=EdltDisplayPreferences())
        self.assertEqual(self.client.commands, [])

    def test_primary_switch_corridor_missing_office_cannot_borrow_future_group(self):
        self.client.values['CorridorLinkingOfficeGroup'] = '99'
        p = self.plan((operation(name='New primary'),
                       dict(op='add-corridor-dialog', field='link_group', address=99, name='New link')))
        final = {**p.parent_plan.expected, **p.parent_plan.changes}
        self.assertEqual((final['CorridorLinkingLinkGroup'], final['CorridorLinkingOfficeGroup']), ((99,), (255,)))


    def manager(self):
        session = NativeSession(self.helper.spec, self.client)
        return NativeEdltParentTransaction(self.client, self.editor,
            programmer=FakeProgrammer(session), display_preferences=EdltDisplayPreferences()), session

    def test_native_apply_binds_name_description_oid_and_one_parent_save(self):
        manager, _ = self.manager()
        p = manager.plan(UNIT, operations=(operation(name='New primary', description='New description'),
            dict(op='add-dialog', field='QuickStatusGroup', name='Status'), widget()), exclusive_project=True)
        before = deepcopy(self.client.applications[56])
        result = manager.apply(p, backup_project='BACKUP').as_dict()
        self.assertTrue(result['saved'] and result['persistence_verified'])
        self.assertEqual([r['phase'] for r in result['application_description_readbacks']],
                         ['before_pp', 'after_project_reload'])
        self.assertTrue(p.as_dict()['add_dialog_boundary']['application_add_dialog_supported'])
        only_app = self.plan((operation(name='Preview only'),))
        self.assertFalse(only_app.as_dict()['add_dialog_boundary']['blank_address_group_dialog_modeled'])
        self.assertEqual(self.client.applications[48]['description'], 'New description')
        self.assertEqual(self.client.applications[56], before)
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)
        self.assertEqual(sum(c.startswith('PROJECT COPY ') for c in self.client.commands), 1)
        self.assertEqual(sum(c.startswith('DBADDSAFE ') and ' Application 48 ' in c for c in self.client.commands), 1)
        self.assertEqual(sum('/Description New description' in c for c in self.client.commands), 1)
        with self.assertRaisesRegex(NativeEdltParentError, 'already had an apply attempt'):
            manager.apply(p, backup_project='OTHER')

    def test_description_wrong_missing_or_unbound_scalar_refuses_before_pp(self):
        for fault in ('wrong', 'missing', 'other-path', 'extra'):
            with self.subTest(fault):
                self.setUp(); manager, _ = self.manager()
                p = manager.plan(UNIT, operations=(operation(name='New primary', description='New description'), widget()), exclusive_project=True)
                self.client.description_fault = fault
                with self.assertRaises(NativeEdltParentError) as error: manager.apply(p, backup_project='BACKUP')
                result = error.exception.result.as_dict()
                self.assertFalse(result['pp_save_attempted'] or result['persistence_verified'])
                self.assertEqual(self.client.commands.count('PP SAVE'), 0)
                self.assertFalse(any(c.startswith('PP SET') for c in self.client.commands))
                before = list(self.client.commands)
                with self.assertRaises(NativeEdltParentError): manager.apply(p, backup_project='OTHER')
                self.assertEqual(self.client.commands, before)

    def test_description_wrong_or_missing_after_reload_cannot_claim_persistence_or_replay(self):
        for fault in ('wrong', 'missing', 'other-path', 'extra'):
            with self.subTest(fault):
                self.setUp(); manager, _ = self.manager()
                p = manager.plan(UNIT, operations=(operation(name='New primary', description='New description'), widget()), exclusive_project=True)
                self.client.description_fault = fault; self.client.description_fault_after = 2
                with self.assertRaises(NativeEdltParentError) as error: manager.apply(p, backup_project='BACKUP')
                result = error.exception.result.as_dict()
                self.assertTrue(result['pp_save_confirmed'] and result['target_project_save_confirmed'])
                self.assertFalse(result['persistence_verified'] or result['rollback_attempted'])
                self.assertEqual(result['database_persistence'], 'save-confirmed-verification-incomplete')
                self.assertEqual(self.client.commands.count('PP SAVE'), 1)
                self.assertEqual([r['phase'] for r in result['application_description_readbacks']], ['before_pp'])
                before = list(self.client.commands)
                with self.assertRaises(NativeEdltParentError): manager.apply(p, backup_project='OTHER')
                self.assertEqual(self.client.commands, before)

    def test_full_observed_project_oid_reuse_stops_before_initializer_or_inverse_delete(self):
        from cbus_toolkit.edlt_parent_metadata import _observed_oids
        identity = oid(88000)
        for kind in ('Project', 'Network', 'Interface', 'other Unit', 'other Network', 'nested metadata', 'fresh Config'):
            with self.subTest(kind):
                self.setUp(); base_xml = self.client.xml
                def augmented():
                    text = base_xml()
                    if kind == 'Project': return text.replace('<Project>', '<Project><OID>'+identity.upper()+'</OID>')
                    if kind == 'Network': return text.replace('<Network>', '<Network><OID>'+identity+'</OID>')
                    if kind == 'Interface': return text.replace('</Network>', '<Interface><OID>'+identity+'</OID></Interface></Network>')
                    if kind == 'other Unit': return text.replace('</Network>', '<Unit><OID>'+identity+'</OID><Address>21</Address></Unit></Network>')
                    if kind == 'other Network': return text.replace('</Project>', '<Network><Address>3</Address><OID>'+identity+'</OID></Network></Project>')
                    if kind == 'nested metadata': return text.replace('</Project>', '<Opaque><Item><OID>'+identity+'</OID></Item><OID>retained arbitrary data</OID></Opaque></Project>')
                    return text
                command = self.client.command
                def fixture_command(value):
                    if value == 'GET //TEST/3 *':
                        from cbus_toolkit.cgate import CGateResponse
                        answer = command('GET //TEST/254 *')
                        lines = tuple(line.replace('//TEST/254:', '//TEST/3:') for line in answer.lines)
                        return CGateResponse(lines, lines[-1], answer.code)
                    return command(value)
                self.client.xml = augmented; self.client.command = fixture_command
                manager, _ = self.manager()
                p = manager.plan(UNIT, operations=(operation(name='New primary', description='New description'), widget()), exclusive_project=True)
                issued = oid(30020) if kind == 'fresh Config' else identity
                with patch.object(self.client, '_new_oid', return_value=issued):
                    with self.assertRaisesRegex(NativeEdltParentError, 'existing OID') as error:
                        manager.apply(p, backup_project='BACKUP')
                result = error.exception.result.as_dict()
                self.assertTrue(result['unidentified_metadata_mutation'])
                self.assertFalse(result['pp_mutation_attempted'] or result['pp_save_attempted'])
                self.assertEqual(result['objects'], [])
                self.assertFalse(any(c.startswith(('DBSET', 'DBDELETE')) for c in self.client.commands))
                self.assertEqual(self.client.commands.count('PROJECT SAVE TEST'), 1)
                self.assertTrue(result['rollback_verified'])
                self.assertNotIn(48, self.client.applications)
        self.assertEqual(_observed_oids('<Installation><Opaque><OID>unchanged arbitrary data</OID></Opaque></Installation>'), {'unchanged arbitrary data'})

    def test_native_lost_save_remains_uncertain_and_does_not_replay(self):
        manager, session = self.manager()
        p = manager.plan(UNIT, operations=(operation(name='New primary'), widget()), exclusive_project=True)
        session.save_error = OSError('lost PP SAVE receipt')
        with self.assertRaises(NativeEdltParentError) as error:
            manager.apply(p, backup_project='BACKUP')
        self.assertTrue(error.exception.result.as_dict()['pp_save_outcome_uncertain'])
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)
        before = list(self.client.commands)
        with self.assertRaisesRegex(NativeEdltParentError, 'already had an apply attempt'): manager.apply(p, backup_project='OTHER')
        self.assertEqual(self.client.commands, before)

    def test_level_oid_collision_refuses_before_identity_read_value_or_cleanup(self):
        for kind in ('existing Level', 'foreign Unit'):
            with self.subTest(kind):
                self.setUp()
                identity = oid(20000 + 202 * 256 + 7 * 16) if kind == 'existing Level' else oid(88000)
                if kind == 'foreign Unit':
                    base_xml = self.client.xml
                    self.client.xml = lambda: base_xml().replace('</Network>',
                        '<Unit><OID>' + identity + '</OID><Address>21</Address></Unit></Network>')
                before = deepcopy(self.client.applications)
                manager, _ = self.manager()
                p = manager.plan(UNIT, operations=(
                    dict(op='add-activation-action-dialog', name='New action'), widget()),
                    exclusive_project=True)
                self.assertEqual([(c.kind, c.address) for c in p.creations], [('Level', 1)])
                with patch.object(self.client, '_new_oid', return_value=identity):
                    with self.assertRaisesRegex(NativeEdltParentError, 'existing OID') as error:
                        manager.apply(p, backup_project='BACKUP')
                result = error.exception.result.as_dict()
                self.assertTrue(result['unidentified_metadata_mutation'] and result['rollback_verified'])
                self.assertEqual(result['objects'], [])
                self.assertFalse(result['pp_mutation_attempted'] or result['pp_save_attempted'])
                self.assertFalse(any(c.startswith(('DBSET', 'DBDELETE', 'PP ')) for c in self.client.commands))
                self.assertFalse(any(c.startswith('DBGET !') and c.endswith('/OID') for c in self.client.commands))
                self.assertEqual(self.client.commands.count('PROJECT SAVE TEST'), 1)
                self.assertEqual(self.client.applications, before)
                commands = list(self.client.commands)
                with self.assertRaises(NativeEdltParentError): manager.apply(p, backup_project='OTHER')
                self.assertEqual(self.client.commands, commands)

    def test_scene_manager_after_application_add_uses_actual_named_projected_owner(self):
        p = self.plan((operation(name='New primary'),
            dict(op='scene-manager', operations=[dict(op='add-trigger-dialog', scene=1, name='Trigger'),
                                                dict(op='add-action-dialog', scene=1, name='Action')]),
            dict(op='add-dialog', field='QuickStatusGroup', name='Status')))
        self.assertIsNotNone(p.scene_metadata)
        self.assertEqual(p.cache.application_cache.find_application(48).name, 'New primary')
        self.assertEqual(next(c for c in p.creations if c.name == 'Status').application, 48)
        self.assertEqual([(c.kind, c.name) for c in p.creations if c.kind == 'Level'], [('Level', 'Action')])

    def test_description_transport_refusals_are_local_before_database_creation(self):
        for description in ('bad#description', 'bad  description', 'bad\uffffdescription', 'bad\nline'):
            with self.subTest(description), self.assertRaises(ValueError):
                self.plan((operation(name='New primary', description=description),))
        self.assertEqual(self.client.commands, [])

    def test_initial_application_getter_is_occupied_before_dialog(self):
        del self.client.applications[56]
        with self.assertRaisesRegex(EdltError, 'permitted free'):
            self.plan((operation(address=56),))


class ResetApplicationParentTests(unittest.TestCase):
    def setUp(self):
        self.spec = reset_spec(); self.editor = EdltParentTransaction(self.spec)
        self.client = NamedClient(self.spec); self.client.values = reset_source(self.spec)
        self.client.applications[56]['groups'][42] = dict(oid=oid(1042), tag='Old lighting', levels=())
        # Reset's required Application203 full list and initial binding group.
        self.client.applications[203] = dict(oid=oid(203), tag='Enable', groups={})
        self.client.applications[57] = dict(oid=oid(57), tag='Secondary', groups={})

    def plan(self, rows):
        return plan_native_parent_metadata(self.client.xml(), UNIT, self.editor.snapshot(self.client.values),
            self.editor, rows, display_preferences=EdltDisplayPreferences())

    def test_reset_application_group_and_one_terminal_crc(self):
        rows = (reset_operations()[0], operation(name='Fresh primary'),
                dict(op='add-dialog', field='QuickStatusGroup', name='Fresh status'))
        p = self.plan(rows); final = {**p.parent_plan.expected, **p.parent_plan.changes}
        self.assertEqual((final['PrimaryApplication'], final['QuickStatusGroup']), ((48,), (0,)))
        self.assertEqual(p.parent_plan.as_dict()['execution_counts']['reset_fresh_model_loads'], 1)
        self.assertEqual(p.parent_plan.as_dict()['execution_counts']['terminal_crc_passes'], 1)
        self.assertEqual(final['Widget10WidgetType'], (10,))
        self.assertEqual(final['SerialNumber'], p.parent_plan.expected['SerialNumber'])

    def test_reset_cancelled_application_then_group_retains_default_primary(self):
        p = self.plan((reset_operations()[0], operation(cancel=True),
                       dict(op='add-dialog', field='QuickStatusGroup', name='Status')))
        self.assertFalse(any(c.kind == 'Application' for c in p.creations))
        self.assertEqual(next(c for c in p.creations if c.name == 'Status').application, 56)

    def test_initial_reset_bound_groups_survive_canonical_cache_replay(self):
        self.client.applications[56]['groups'][99] = dict(oid=oid(5699), tag='Old Office', levels=())
        self.client.values['CorridorLinkingOfficeGroup'] = '99'
        p = self.plan((reset_operations()[0], operation(name='New primary'),
                       dict(op='add-dialog', field='QuickStatusGroup', name='Fresh status')))
        self.assertTrue(p.cache.lifecycle.find(56, 99).exists)
        self.assertEqual(p.parent_plan.changes['PrimaryApplication'], (48,))
        self.assertEqual(p.parent_plan.after_controls['CorridorLinkingOfficeGroup'], (255,))

    def test_reset_then_blank_and_add_uses_fresh_graph(self):
        p = self.plan((reset_operations()[0], dict(op='blank', page=1, position=5),
                       operation(name='New primary')))
        self.assertEqual(p.parent_plan.after_controls['Widget10WidgetType'], (0,))
        self.assertEqual(p.parent_plan.as_dict()['execution_counts']['fresh_reset_blank_transitions'], 1)

    def test_reset_uses_default_primary_for_earlier_widget_getter_and_later_add(self):
        self.client.applications[48] = dict(oid=oid(48), tag='Old primary', groups={
            42: dict(oid=oid(4842), tag='Old group', levels=())})
        self.client.values['PrimaryApplication'] = '48'
        p = self.plan((reset_operations()[0],
                       dict(op='lighting', page=1, position=1, group=12, mode='dimmer'),
                       dict(op='add-dialog', field='QuickStatusGroup', name='After widget')))
        self.assertTrue(any(c.kind == 'Group' and c.application == 56 and c.address == 12 for c in p.creations))
        self.assertFalse(any(c.kind == 'Group' and c.application == 48 and c.address == 12 for c in p.creations))
        self.assertEqual(next(c for c in p.creations if c.name == 'After widget').application, 56)

    def test_initial_scene_getter_survives_reset_without_retaining_old_scene_model(self):
        bucket = [255] * 232; bucket[:5] = [2, 0, 7, 1, 255]
        self.client.values.update(SceneBucket=' '.join(map(str, bucket)), Scene1StartAddress='0', SceneCount='1')
        self.client.applications[202]['groups'][7] = dict(oid=oid(207), tag='Old trigger', levels=(0, 2))
        p = self.plan((reset_operations()[0],
                       dict(op='standby', enabled=True, after_seconds=60),
                       dict(op='activation', wake_mode='trigger-event', group=7),
                       dict(op='add-activation-action-dialog', name='After old getter')))
        self.assertEqual([(c.address, c.name) for c in p.creations if c.kind == 'Level'],
                         [(1, 'Action Selector 1'), (3, 'After old getter')])
        self.assertEqual(p.parent_plan.after_controls['Scene1StartAddress'], (65535,))
        self.assertEqual(p.parent_plan.as_dict()['execution_counts']['reset_graph_replacements'], 1)

    def test_reset_application_add_and_scene_manager_use_fresh_scene_graph(self):
        p = self.plan((reset_operations()[0], operation(name='New primary'),
                       dict(op='scene-manager', operations=[dict(op='add-trigger-dialog', scene=1, name='Trigger'),
                                                           dict(op='add-action-dialog', scene=1, name='Action')]),
                       dict(op='add-corridor-dialog', field='link_group', name='Link')))
        self.assertEqual(next(c for c in p.creations if c.name == 'Link').application, 48)
        self.assertEqual([(c.kind, c.name) for c in p.creations if c.kind == 'Level'], [('Level', 'Action')])
        self.assertEqual(p.parent_plan.as_dict()['execution_counts']['reset_fresh_model_loads'], 1)

    def test_reset_then_activation_before_add_does_not_borrow_old_mode(self):
        self.client.values.update(ProximityMode='3', ProximityGroup='7')
        with self.assertRaisesRegex(EdltError, 'enabled standby'):
            self.plan((reset_operations()[0], dict(op='add-activation-group-dialog')))
        p = self.plan((reset_operations()[0], dict(op='standby', enabled=True, after_seconds=60),
                       dict(op='activation', wake_mode='trigger-event'),
                       dict(op='add-activation-group-dialog', name='Fresh trigger')))
        self.assertEqual(next(c for c in p.creations if c.name == 'Fresh trigger').application, 202)
