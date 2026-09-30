"""Original first-open initialization for the direct eDLT database helpers."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit import cli
from cbus_toolkit.edlt_first_open import DIRECT_ACTIONS, FirstOpenRequired, database_cache, detect, network_path
from cbus_toolkit.edlt_general import EdltGeneralSettings
from cbus_toolkit.edlt_lifecycle import EdltLifecycle
from cbus_toolkit.edlt_page_control import EdltPageControl
from cbus_toolkit.edlt_standby import EdltStandby
from tests.test_edlt import Session
from tests.test_edlt_general import fixture as general_fixture
from tests.test_edlt_lifecycle import fixture as lifecycle_fixture
from tests.test_edlt_page_control import fixture as page_control_fixture
from tests.test_edlt_standby import fixture as standby_fixture

NETWORK_XML = ('<Network><Application><Address>56</Address><Group><Address>1</Address></Group></Application>'
               '<Application><Address>202</Address></Application>'
               '<Application><Address>203</Address><Group><Address>42</Address></Group></Application></Network>')


def fixture():
    parameters = {}
    for spec in (lifecycle_fixture(), page_control_fixture(), general_fixture(), standby_fixture()):
        parameters.update(spec.parameters)
    return replace(lifecycle_fixture(), parameters=parameters)


class DatabaseSession(Session):
    """A never-opened database unit (spec defaults) that also answers DBGETXML."""
    def __init__(self, spec, xml=NETWORK_XML):
        super().__init__(spec)
        # Eight default empty scenes in the layout the lifecycle can load.
        self.current.update({f'Scene{index}StartAddress': (0,) for index in range(1, 9)})
        self.current['SceneBucket'] = tuple(bytes((2, 0, 255, 255, 255)).ljust(232, b'\xff'))
        self.xml, self.commands, self.saves = xml, [], 0

    def command(self, command):
        self.commands.append(command)
        if command.startswith('DBGETXML '):
            return SimpleNamespace(code=344, lines=('343-Begin XML snippet', '347-' + self.xml, '344 End XML snippet'))
        return super().command(command)

    def save_to_source(self):
        self.saves += 1
        return SimpleNamespace(code=200)


class FirstOpenUnitTests(unittest.TestCase):
    def test_detects_the_original_after_load_configuration_version_condition(self):
        for major, minor, never in ((255, 255, True), (1, 0, False), (255, 0, True), (1, 255, True), (5, 5, False)):
            self.assertEqual(detect({'ConfigVersionMajor': (major,), 'ConfigVersionMinor': (minor,)}),
                             {'config_version': [[major], [minor]], 'never_initialized': never})
        self.assertTrue(detect({'ConfigVersionMajor': '0xFF', 'ConfigVersionMinor': '0'})['never_initialized'])

    def test_network_path_requires_a_database_unit(self):
        self.assertEqual(network_path('/db//PROJ/254/p/20'), '//PROJ/254')
        self.assertEqual(network_path('/DB//PROJ/254/P/20'), '//PROJ/254')
        for invalid in ('//PROJ/254/p/20', '/db//PROJ/254', '/db//PROJ/x/p/20', None):
            with self.assertRaises(ValueError):
                network_path(invalid)

    def test_database_cache_reads_existence_only_and_fails_closed(self):
        requirements = {'applications': [{'application': 203}, {'application': 56}, {'application': 202}],
                        'groups': [{'application': 202, 'group': 255, 'facts': {'exists': ['s']}},
                                   {'application': 56, 'group': 7, 'facts': {'exists': ['w']}},
                                   {'application': 203, 'group': 42, 'facts': {'exists': ['w']}}]}
        self.assertEqual(database_cache(requirements, NETWORK_XML), {
            'format': 'cbus-edlt-lifecycle-cache-v1', 'applications': [56, 202, 203],
            'groups': [{'application': 202, 'group': 255, 'exists': True},
                       {'application': 56, 'group': 7, 'exists': False},
                       {'application': 203, 'group': 42, 'exists': True}]})
        with self.assertRaisesRegex(FirstOpenRequired, 'absent: 57') as caught:
            database_cache({'applications': [{'application': 57}], 'groups': []}, NETWORK_XML)
        self.assertIn('edlt-lifecycle', str(caught.exception))
        self.assertEqual(caught.exception.details['first_open']['missing_applications'], [57])
        for facts in ({'exists': [], 'complete_levels_if_present': ['s']}, {'exists': [], 'dynamic_images_if_present': []}):
            with self.assertRaisesRegex(FirstOpenRequired, 'does not establish'):
                database_cache({'applications': [{'application': 56}],
                                'groups': [{'application': 56, 'group': 1, 'facts': facts}]}, NETWORK_XML)
        for xml in ('<Network>', '<Project/>', NETWORK_XML.replace('<Address>202', '<Address>56')):
            with self.assertRaises(ValueError):
                database_cache({'applications': [], 'groups': []}, xml)

    def test_every_direct_unit_workflow_has_the_first_open_options(self):
        import argparse

        def choices(parser, *path):
            for name in path:
                action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
                parser = action.choices[name]
            return parser
        unit = next(a for a in choices(cli.build_parser(), 'cgate', 'unit')._actions
                    if isinstance(a, argparse._SubParsersAction)).choices
        for action, parser in unit.items():
            options = {option for item in parser._actions for option in item.option_strings}
            has = {'--no-first-open', '--first-open-metadata'} <= options
            self.assertEqual(has, action in DIRECT_ACTIONS, action)
        parser = unit['edlt-page-control']
        self.assertTrue(parser.parse_args(['--no-first-open']).no_first_open)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(['--no-first-open', '--first-open-metadata', 'cache.json'])


class FirstOpenCLITests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()

    def run_cli(self, session, action, editor, *options, status=0):
        output, error = io.StringIO(), io.StringIO()
        name = {'edlt-page-control': '_edlt_page_control', 'edlt-general': '_edlt_general',
                'edlt-standby': '_edlt_standby'}[action]
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(session)), \
                patch('cbus_toolkit.programming.Programmer',
                      return_value=SimpleNamespace(load=Mock(return_value=nullcontext(session)))), \
                patch.object(cli, name, return_value=editor), redirect_stdout(output), redirect_stderr(error):
            code = cli.main(['cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                             action, *map(str, options)])
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def expected(self, session, plan):
        """Offline composition: the original load/save cycle, then the helper's own edit."""
        lifecycle = EdltLifecycle(self.spec)
        source = lifecycle.snapshot(session.values())
        cache = database_cache(lifecycle.requirements(source).as_dict(), NETWORK_XML)
        opened = lifecycle.plan(source, metadata=cache)
        loaded = {**opened.expected, **opened.changes}
        edited = plan(loaded)
        return opened, {**edited.expected, **edited.changes}

    def helpers(self):
        return (('edlt-page-control', EdltPageControl(self.spec), ('--group', 42),
                 lambda editor, values: editor.plan(values, group=42)),
                ('edlt-general', EdltGeneralSettings(self.spec), ('--long-press-ms', 1000),
                 lambda editor, values: editor.plan(values, long_press_ms=1000)),
                ('edlt-standby', EdltStandby(self.spec), ('--no-enabled',),
                 lambda editor, values: editor.plan(values, enabled=False)))

    def test_never_opened_unit_applies_first_open_then_the_edit_in_one_save(self):
        for action, editor, options, plan in self.helpers():
            with self.subTest(action=action):
                session = DatabaseSession(self.spec)
                opened, final = self.expected(session, lambda values: plan(editor, values))
                result = self.run_cli(session, action, editor, *options)
                self.assertEqual(editor.snapshot(session.values()), final)
                self.assertEqual(session.saves, 1)
                self.assertEqual([c for c in session.commands if c.startswith('DBGETXML')], ['DBGETXML //EDLTTEST/254'])
                first_open = result['first_open']
                self.assertTrue(first_open['applied']); self.assertTrue(first_open['never_initialized'])
                self.assertEqual(first_open['metadata_provenance'], 'native-database-network-xml')
                self.assertEqual(sorted(first_open['lifecycle_changes']), sorted(opened.changes))
                for name in ('ConfigVersionMajor', 'SceneCount', 'Widget1WidgetType'):
                    self.assertIn(name, first_open['lifecycle_changes'])
                self.assertTrue(result['saved'])

    def test_initialized_unit_is_unchanged_and_issues_no_first_open_io(self):
        for action, editor, options, plan in self.helpers():
            with self.subTest(action=action):
                session = DatabaseSession(self.spec)
                session.current.update(ConfigVersionMajor=(1,), ConfigVersionMinor=(0,))
                direct = plan(editor, session.values())
                result = self.run_cli(session, action, editor, *options)
                self.assertEqual(editor.snapshot(session.values()), {**direct.expected, **direct.changes})
                self.assertEqual([name for name, _ in session.calls], list(direct.changes))
                self.assertNotIn('first_open', result)
                self.assertFalse(any(c.startswith('DBGETXML') for c in session.commands))
                # --no-first-open is inert for an initialized unit.
                again = DatabaseSession(self.spec)
                again.current.update(ConfigVersionMajor=(1,), ConfigVersionMinor=(0,))
                self.run_cli(again, action, editor, '--no-first-open', *options)
                self.assertEqual(again.calls, session.calls)

    def test_no_first_open_keeps_the_direct_edit_and_reports_the_skip(self):
        session = DatabaseSession(self.spec); editor = EdltPageControl(self.spec)
        direct = editor.plan(session.values(), group=42)
        result = self.run_cli(session, 'edlt-page-control', editor, '--no-first-open', '--group', 42)
        self.assertEqual(editor.snapshot(session.values()), {**direct.expected, **direct.changes})
        self.assertEqual(result['first_open'], {'format': 'cbus-edlt-first-open-v1', 'config_version': [[255], [255]],
                                                'never_initialized': True, 'required': True, 'applied': False,
                                                'skipped_by_request': True})
        self.assertFalse(any(c.startswith('DBGETXML') for c in session.commands))

    def test_missing_database_application_refuses_before_any_write_or_save(self):
        session = DatabaseSession(self.spec, xml=NETWORK_XML.replace('<Address>203</Address>', '<Address>204</Address>'))
        result = self.run_cli(session, 'edlt-page-control', EdltPageControl(self.spec), '--group', 42, status=1)
        self.assertIn('absent: 203', result['error']); self.assertIn('edlt-lifecycle', result['error'])
        self.assertIn('--first-open-metadata', result['error'])
        self.assertEqual(result['first_open'], {'missing_applications': [203]})
        self.assertEqual((session.calls, session.saves), ([], 0))

    def test_caller_metadata_replaces_the_database_read(self):
        session = DatabaseSession(self.spec, xml='<unused/>'); editor = EdltPageControl(self.spec)
        opened, final = self.expected(DatabaseSession(self.spec), lambda values: editor.plan(values, group=42))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'; path.write_text(json.dumps(opened.metadata.as_dict()))
            result = self.run_cli(session, 'edlt-page-control', editor, '--first-open-metadata', path, '--group', 42)
        self.assertEqual(editor.snapshot(session.values()), final)
        self.assertEqual(result['first_open']['metadata_provenance'], 'caller-supplied-cache')
        self.assertFalse(any(c.startswith('DBGETXML') for c in session.commands))

    def test_dry_run_stages_first_open_without_saving(self):
        session = DatabaseSession(self.spec); editor = EdltPageControl(self.spec)
        _opened, final = self.expected(DatabaseSession(self.spec), lambda values: editor.plan(values, group=42))
        output, error = io.StringIO(), io.StringIO()
        with patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(session)), \
                patch('cbus_toolkit.programming.Programmer',
                      return_value=SimpleNamespace(load=Mock(return_value=nullcontext(session)))), \
                patch.object(cli, '_edlt_page_control', return_value=editor), redirect_stdout(output), redirect_stderr(error):
            code = cli.main(['cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                             '--dry-run', 'edlt-page-control', '--group', '42'])
        self.assertEqual(code, 0, error.getvalue())
        result = json.loads(output.getvalue())
        self.assertFalse(result['saved']); self.assertEqual(session.saves, 0)
        self.assertEqual(editor.snapshot(result['parameters']), final)


if __name__ == '__main__':
    unittest.main()
