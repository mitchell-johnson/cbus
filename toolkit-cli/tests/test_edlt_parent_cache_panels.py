"""Applications and Corridor dialogs inside one retained parent transaction."""
from dataclasses import replace
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.edlt import EdltError, _field
from cbus_toolkit.edlt_application_cache import (
    ApplicationCache, CachedDisplay, CachedGroupList,
)
from cbus_toolkit.edlt_lifecycle import LifecycleCache, LifecycleGroup
from cbus_toolkit.edlt_parent_transaction import (
    CRC_FIELDS, EdltParentTransaction,
)
from cbus_toolkit.edlt_parent_transaction_cli import metadata as read_metadata
from tests.test_edlt import Session
from tests.test_edlt_corridor import fixture as corridor_fixture
from tests.test_edlt_parent_panels import extended_fixture, panel_cache
from tests.test_edlt_scene import prepared


def fixture():
    """Merge the accepted Corridor fields into the extended parent profile."""
    base = extended_fixture()
    parameters = dict(base.parameters)
    for name, parameter in corridor_fixture().parameters.items():
        parameters.setdefault(name, parameter)
    return replace(base, parameters=parameters)


def application_cache(editor, source):
    """Turn the complete parent facts into ordered application/group lists."""
    lifecycle = LifecycleCache.from_dict(panel_cache(editor, source))
    # Supply the secondary binding used by the ownership-conflict regression.
    # This remains an explicit caller fact rather than an inferred group.
    facts = list(lifecycle.groups)
    if not any(row.application == 57 and row.group == 12 for row in facts):
        facts.append(LifecycleGroup(
            57, 12, True, (False,) * 4, True, (0, 1, 2, 255)))
    lifecycle = LifecycleCache(lifecycle.applications, tuple(facts))
    applications = tuple(
        CachedDisplay(address, f'Application {address}', f'Application {address}')
        for address in lifecycle.applications
    )
    group_lists = []
    for application in lifecycle.applications:
        seen = set()
        groups = []
        for fact in lifecycle.groups:
            if (fact.application != application or not fact.exists or
                    fact.group in seen):
                continue
            seen.add(fact.group)
            groups.append(CachedDisplay(
                fact.group, f'Group {fact.group}', f'Group {fact.group}'))
        group_lists.append(CachedGroupList(application, True, tuple(groups)))
    return ApplicationCache(
        lifecycle, True, applications, tuple(group_lists))


def operations():
    return (
        {'op': 'applications',
         'edits': [{'field': 'secondary', 'address': 255}]},
        {'op': 'corridor', 'edits': [
            {'field': 'link_group', 'value': 12},
            {'field': 'office_group', 'value': 14},
            {'field': 'corridor_group', 'value': 15},
            {'field': 'seconds', 'value': 600},
        ]},
        {'op': 'lighting', 'page': 1, 'position': 1, 'group': 12,
         'mode': 'dimmer', 'label_text': 'Hall'},
    )


class ParentCachePanelTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.session = Session(self.spec)
        self.source = self.editor.snapshot(prepared(self.session.values()))
        self.cache = application_cache(self.editor, self.source)

    def plan(self, requested=None, *, metadata=None, source=None):
        return self.editor.plan(
            self.source if source is None else source,
            metadata=self.cache if metadata is None else metadata,
            operations=operations() if requested is None else requested)

    def test_both_cache_dialogs_share_one_terminal_parent_projection(self):
        with patch.object(
                self.editor.lifecycle, 'crcs',
                wraps=self.editor.lifecycle.crcs) as crcs, patch.object(
                    self.editor.lifecycle, '_prepare_composed_save',
                    wraps=self.editor.lifecycle._prepare_composed_save) as terminal:
            plan = self.plan()
        document = plan.as_dict()
        self.assertEqual(
            [row['format'] for row in document['operation_results']],
            ['cbus-edlt-applications-plan-v1',
             'cbus-edlt-corridor-plan-v1',
             'cbus-edlt-lighting-plan-v1'])
        self.assertEqual(plan.after_controls['SecondaryApplication'], (255,))
        self.assertEqual(plan.after_controls['CorridorLinkingLinkGroup'], (12,))
        self.assertEqual(plan.after_controls['CorridorLinkingOfficeGroup'], (14,))
        self.assertEqual(plan.after_controls['CorridorLinkingCorridorGroup'], (15,))
        # Toolkit's retained OnValidation path clamps an edited value above
        # one byte even though the visible timer accepts a larger duration.
        self.assertEqual(plan.after_controls['CorridorLinkingCorridorTime'], (255,))
        self.assertEqual(plan.after_controls[_field(6)], (2,))
        self.assertEqual(crcs.call_count, 1)
        self.assertEqual(terminal.call_count, 1)
        self.assertEqual(set(document['lifecycle']['crc_fields_calculated']),
                         set(CRC_FIELDS))
        self.assertEqual(document['execution_counts'][
            'terminal_normalization_passes'], 1)
        self.assertEqual(document['execution_counts']['terminal_crc_passes'], 1)
        self.assertEqual(document['transaction_guards']['settings_panels'],
                         ['applications', 'corridor'])
        self.assertIsNotNone(document['application_cache'])
        for row in document['operation_results'][:2]:
            self.assertEqual(
                row['composition_role'],
                'validated parent cache-dialog projection')
            self.assertFalse(row['standalone_changes_applied_directly'])

    def test_apply_replans_canonically_writes_once_and_verifies_readback(self):
        plan = self.plan()
        self.session.current = dict(self.source)
        result = self.editor.apply(self.session, plan)
        self.assertTrue(result['verified'])
        self.assertEqual(len(self.session.calls), len(plan.changes))
        self.assertEqual(len({name for name, _ in self.session.calls}),
                         len(self.session.calls))
        self.assertEqual(
            self.editor.snapshot(self.session.values()),
            {**plan.expected, **plan.changes})

    def test_complete_application_cache_and_single_panel_ownership_are_required(self):
        lifecycle_only = self.cache.lifecycle
        with self.assertRaisesRegex(EdltError, 'complete.*application-cache'):
            self.plan(metadata=lifecycle_only)
        for kind in ('applications', 'corridor'):
            selected = next(row for row in operations() if row['op'] == kind)
            with self.subTest(kind=kind), self.assertRaisesRegex(
                    EdltError, 'only one ' + kind):
                self.plan((selected, selected, operations()[-1]))

    def test_application_callback_selector_conflicts_with_widget_owner(self):
        source = self.source
        cache = application_cache(self.editor, source)
        lighting = {**operations()[-1], 'application': 'secondary'}
        requested = (lighting, operations()[0])
        with self.assertRaisesRegex(
                EdltError, 'Duplicate or conflicting byte ownership'):
            self.editor.plan(source, metadata=cache, operations=requested)

    def test_metadata_reader_accepts_cache_and_rejects_ambiguous_or_unbounded_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / 'good.json'
            good.write_text(json.dumps(self.cache.as_dict()), encoding='utf-8')
            self.assertEqual(read_metadata(good), self.cache)
            for name, content, message in (
                    ('duplicate.json', '{"format":"x","format":"y"}',
                     'Duplicate key'),
                    ('nonfinite.json', '{"value":NaN}', 'Non-finite'),
                    ('large.json', ' ' * (16 * 1024 * 1024 + 1),
                     'exceeds 16 MiB')):
                path = root / name
                path.write_text(content, encoding='utf-8')
                with self.subTest(name=name), self.assertRaisesRegex(
                        ValueError, message):
                    read_metadata(path)

    def test_offline_cli_accepts_the_complete_application_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.json'
            metadata = root / 'metadata.json'
            requested = root / 'operations.json'
            source.write_text(json.dumps(self.source), encoding='utf-8')
            metadata.write_text(json.dumps(self.cache.as_dict()), encoding='utf-8')
            requested.write_text(json.dumps(operations()), encoding='utf-8')
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(
                    cli, '_edlt_parent_transaction',
                    return_value=self.editor), redirect_stdout(stdout), \
                    redirect_stderr(stderr):
                status = cli.main([
                    'edlt', 'parent-transaction-plan', str(source),
                    '--metadata', str(metadata), '--operations', str(requested)])
            self.assertEqual(status, 0, stderr.getvalue())
            document = json.loads(stdout.getvalue())
            self.assertEqual(
                [row['format'] for row in document['operation_results'][:2]],
                ['cbus-edlt-applications-plan-v1',
                 'cbus-edlt-corridor-plan-v1'])
            self.assertIsNotNone(document['application_cache'])


if __name__ == '__main__':
    unittest.main()
