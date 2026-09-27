"""Automatic ordered ApplicationCache resolution for native parent edits."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.edlt import _render
from cbus_toolkit.edlt_application_cache import ApplicationCache
from cbus_toolkit.edlt_parent_metadata import (
    NativeEdltParentError,
    NativeEdltParentTransaction,
    plan_native_parent_metadata,
)
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from tests.test_edlt import Session
from tests.test_edlt_parent_blank_reset import (
    complete_spec,
    reset_operations,
    reset_source,
)
from tests.test_edlt_parent_cache_panels import (
    application_cache,
    fixture,
    operations,
)
from tests.test_edlt_parent_metadata import (
    FakeProgrammer,
    MetadataClient,
    NativeSession,
    oid,
)
from tests.test_edlt_reset import metadata as reset_cache
from tests.test_edlt_scene import prepared


def _native_applications(cache):
    if not isinstance(cache, ApplicationCache):
        cache = ApplicationCache.from_dict(cache)
    result = {}
    identity = 1000000
    for application in cache.applications:
        if application.address == 255:
            continue
        identity += 1
        groups = {}
        group_list = cache.find_group_list(application.address)
        for display in group_list.groups:
            if display.address == 255:
                continue
            identity += 1
            fact = cache.lifecycle.find(application.address, display.address)
            levels = () if fact is None or fact.levels is None else fact.levels
            level_oids = {}
            for level in levels:
                identity += 1
                level_oids[level] = oid(identity)
            groups[display.address] = {
                'oid': oid(identity + 1000000),
                'tag': display.name,
                'levels': levels,
                'level_oids': level_oids,
            }
        result[application.address] = {
            'oid': oid(identity + 2000000),
            'tag': application.name,
            'groups': groups,
        }
    return result


def _numeric_raw(values):
    return {name: _render(value) for name, value in values.items()}


class ParentAutomaticApplicationCacheTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.source = self.editor.snapshot(prepared(Session(self.spec).values()))
        self.manual_cache = application_cache(self.editor, self.source)
        self.client = MetadataClient(
            self.spec, applications=_native_applications(self.manual_cache))
        self.client.values = _numeric_raw(self.source)

    def offline(self, text=None):
        return plan_native_parent_metadata(
            self.client.xml() if text is None else text,
            '//TEST/254/p/20', self.source, self.editor, operations())

    def test_applications_and_corridor_use_complete_database_view_cache(self):
        plan = self.offline()
        document = plan.as_dict()
        self.assertIsInstance(plan.cache, ApplicationCache)
        self.assertEqual(plan.creations, ())
        self.assertTrue(plan.cache.applications_complete)
        self.assertTrue(all(row.complete for row in plan.cache.group_lists))
        self.assertEqual(
            [row['format'] for row in
             document['parent_transaction']['operation_results']],
            ['cbus-edlt-applications-plan-v1',
             'cbus-edlt-corridor-plan-v1',
             'cbus-edlt-lighting-plan-v1'])
        evidence = document['automatic_ordered_application_cache']
        self.assertEqual(evidence['operations'], ['applications', 'corridor'])
        self.assertEqual(evidence['display_projection'],
                         'exact TagName database view')
        self.assertFalse(evidence[
            'toolkit_registry_display_and_sort_preferences_observed'])
        self.assertFalse(evidence['projected_list_objects_admitted'])
        self.assertEqual(
            [row.formatted_display for row in plan.cache.applications],
            [row.name for row in plan.cache.applications])

    def test_xml_application_and_group_child_order_is_preserved(self):
        text = self.client.xml()
        applications = list(re.finditer(
            r'<Application>.*?</Application>', text, re.DOTALL))
        original = ''.join(match.group(0) for match in applications)
        reversed_apps = ''.join(
            match.group(0) for match in reversed(applications))
        text = text.replace(original, reversed_apps, 1)

        # Reverse the persisted groups in application56 as an independent
        # order fact.  The selected addresses remain identical.
        match = next(match for match in re.finditer(
            r'<Application>.*?</Application>', text, re.DOTALL)
                     if '<Address>56</Address>' in match.group(0))
        block = match.group(0)
        groups = list(re.finditer(
            r'<(Group|NetVar)>.*?</\1>', block, re.DOTALL))
        if len(groups) > 1:
            original_groups = ''.join(row.group(0) for row in groups)
            block = block.replace(
                original_groups,
                ''.join(row.group(0) for row in reversed(groups)), 1)
            text = text[:match.start()] + block + text[match.end():]

        plan = self.offline(text)
        self.assertEqual(
            [row.address for row in plan.cache.applications],
            list(reversed(sorted(self.client.applications))))
        expected_groups = list(reversed(sorted(
            self.client.applications[56]['groups'])))
        actual = [row.address for row in
                  plan.cache.find_group_list(56).groups if row.address != 255]
        self.assertEqual(actual, expected_groups)

    def test_native_apply_has_one_pp_save_and_final_project_reload(self):
        session = NativeSession(self.spec, self.client)
        programmer = FakeProgrammer(session)
        manager = NativeEdltParentTransaction(
            self.client, self.editor, programmer=programmer)
        plan = manager.plan(
            '//TEST/254/p/20', operations=operations(),
            exclusive_project=True)
        result = manager.apply(plan, backup_project='BACKUP').as_dict()
        self.assertTrue(result['complete'])
        self.assertTrue(result['persistence_verified'])
        self.assertEqual(plan.creations, ())
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)
        self.assertEqual(self.client.commands.count('PROJECT SAVE TEST'), 2)
        self.assertEqual(programmer.calls,
                         [('//TEST/254', '/db//TEST/254/p/20')])

    def test_missing_list_objects_are_not_projected(self):
        del self.client.applications[203]
        with self.assertRaisesRegex(
                ValueError, 'cannot project missing applications'):
            self.offline()

        self.client = MetadataClient(
            self.spec, applications=_native_applications(self.manual_cache))
        self.client.values = _numeric_raw(self.source)
        del self.client.applications[56]['groups'][12]
        with self.assertRaisesRegex(Exception, 'unavailable|existing group'):
            self.offline()

    def test_offline_cli_exposes_ordered_cache_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = root / 'values.json'
            project = root / 'project.xml'
            requested = root / 'operations.json'
            values.write_text(json.dumps(self.source))
            project.write_text(self.client.xml())
            requested.write_text(json.dumps(operations()))
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(cli, '_edlt_parent_transaction',
                              return_value=self.editor), patch(
                    'cbus_toolkit.cgate.CGateClient',
                    side_effect=AssertionError('offline plan connected')), \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                status = cli.main([
                    'edlt', 'parent-transaction-plan', str(values),
                    '--project-xml', str(project),
                    '--unit', '//TEST/254/p/20',
                    '--operations', str(requested),
                ])
            self.assertEqual(status, 0, stderr.getvalue())
            document = json.loads(stdout.getvalue())
            self.assertEqual(
                document['automatic_ordered_application_cache']['operations'],
                ['applications', 'corridor'])


class ParentAutomaticResetCacheTests(unittest.TestCase):
    def setUp(self):
        self.spec = complete_spec()
        self.editor = EdltParentTransaction(self.spec)
        self.raw = reset_source(self.spec)
        self.source = self.editor.snapshot(self.raw)
        self.client = MetadataClient(
            self.spec, applications=_native_applications(reset_cache()))
        self.client.values = dict(self.raw)

    def offline(self):
        return plan_native_parent_metadata(
            self.client.xml(), '//TEST/254/p/20', self.source,
            self.editor, reset_operations())

    def test_reset_uses_exact_xml_raw_strings_and_complete_lists(self):
        plan = self.offline()
        document = plan.as_dict()
        self.assertEqual(plan.creations, ())
        self.assertEqual(dict(plan.parent_plan.expected_raw), self.raw)
        self.assertEqual(plan.parent_plan.expected_raw['NavWidgetType'], '0x1')
        self.assertEqual(plan.parent_plan.expected_raw['Project'], 'OWNED   ')
        self.assertTrue(document['raw_parameters_sha256'])
        cache = document['automatic_ordered_application_cache']
        self.assertEqual(cache['operations'], ['reset'])
        self.assertEqual(cache['reset_raw_source'],
                         'exact selected Unit PP Value attributes')
        self.assertTrue(cache['applications_complete'])

    def test_reset_native_apply_preserves_single_save_boundary(self):
        session = NativeSession(self.spec, self.client)
        manager = NativeEdltParentTransaction(
            self.client, self.editor, programmer=FakeProgrammer(session))
        plan = manager.plan(
            '//TEST/254/p/20', operations=reset_operations(),
            exclusive_project=True)
        result = manager.apply(plan, backup_project='RSTBACK').as_dict()
        self.assertTrue(result['persistence_verified'])
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)
        self.assertEqual(self.client.commands.count('PROJECT SAVE TEST'), 2)
        self.assertEqual(plan.parent_plan.expected_raw['Project'], 'OWNED   ')

    def test_missing_positive_reset_control_group_is_refused(self):
        self.raw['QuickStatusGroup'] = '0x2a'
        self.source = self.editor.snapshot(self.raw)
        self.client.values = dict(self.raw)
        del self.client.applications[56]['groups'][42]
        with self.assertRaisesRegex(
                ValueError, 'does not infer a missing bound control group'):
            self.offline()

    def test_reset_raw_spelling_stale_guard_precedes_backup(self):
        manager = NativeEdltParentTransaction(
            self.client, self.editor,
            programmer=FakeProgrammer(NativeSession(self.spec, self.client)))
        plan = manager.plan(
            '//TEST/254/p/20', operations=reset_operations(),
            exclusive_project=True)
        self.client.values['NavWidgetType'] = '0x01'
        with self.assertRaises(NativeEdltParentError) as caught:
            manager.apply(plan, backup_project='RSTBACK')
        evidence = caught.exception.result.as_dict()
        self.assertFalse(evidence['backup_created'])
        self.assertFalse(evidence['pp_mutation_attempted'])
        self.assertFalse(any(command.startswith('PROJECT ')
                             for command in self.client.commands))

    def test_scene_manager_combination_remains_explicitly_refused(self):
        requested = (*reset_operations(), {
            'op': 'scene-manager',
            'operations': [{'op': 'get-trigger', 'scene': 1}],
        })
        with self.assertRaisesRegex(
                ValueError, 'does not admit.*reset'):
            plan_native_parent_metadata(
                self.client.xml(), '//TEST/254/p/20', self.source,
                self.editor, requested)


class ParentAutomaticCacheNativeAcceptance(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get('CBUS_EDLT_PARENT_CACHE_METADATA_ACCEPTANCE') == '1'
        and os.environ.get('CBUS_EDLT_PARENT_CACHE_METADATA_UNIT')
        and os.environ.get('CBUS_EDLT_PARENT_CACHE_METADATA_BACKUP')
        and os.environ.get('CBUS_EDLT_PARENT_CACHE_METADATA_OPERATIONS')
        and os.environ.get('CBUS_CGATE_TEST_HOST')
        and os.environ.get('CBUS_UNITSPEC_DIR'),
        'Set the explicit disposable closed-project ordered-cache acceptance environment')
    def test_optional_native_ordered_cache_parent_transaction(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.unitspec import UnitSpecStore

        editor = EdltParentTransaction(
            UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml'))
        requested = json.loads(Path(os.environ[
            'CBUS_EDLT_PARENT_CACHE_METADATA_OPERATIONS']).read_text())
        self.assertTrue(any(row.get('op') in (
            'applications', 'corridor', 'reset') for row in requested))
        host = os.environ['CBUS_CGATE_TEST_HOST']
        port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        with CGateClient(host, port, timeout=30) as client:
            manager = NativeEdltParentTransaction(client, editor)
            plan = manager.plan(
                os.environ['CBUS_EDLT_PARENT_CACHE_METADATA_UNIT'],
                operations=requested, exclusive_project=True)
            result = manager.apply(
                plan, backup_project=os.environ[
                    'CBUS_EDLT_PARENT_CACHE_METADATA_BACKUP']).as_dict()
        self.assertTrue(result['persistence_verified'])
        self.assertFalse(result['physical_device_programmed'])


if __name__ == '__main__':
    unittest.main()
