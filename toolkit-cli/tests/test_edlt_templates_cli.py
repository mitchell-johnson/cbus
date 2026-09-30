"""Local eDLT template file boundary and unconditional apply refusal."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import edlt_templates_cli as cli
from cbus_toolkit.edlt_templates import (
    EdltTemplate, EdltTemplateApplyRefused, export_edlt_template,
)


def export_arguments():
    return {
        'description': 'Local template', 'firmware': '5.5.00',
        'unit_name': 'TEST', 'primary_application': 56,
        'secondary_application': 255,
        'pp_attributes': [['ParamB', '0x01'], ['Application', 'discarded'],
                          ['UnitAddress', '20'], ['ParamA', '7']],
    }


class EdltTemplatesCLITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'source.json'
        self.output = self.root / 'new.xml'
        self.xml = self.root / 'input.xml'
        self.names = self.root / 'names.json'
        self.source.write_text(json.dumps(export_arguments()), encoding='utf-8')
        self.xml.write_bytes(export_edlt_template(**export_arguments()).to_xml().encode('utf-8'))
        self.names.write_text(json.dumps(['Application', 'ParamA', 'ParamB']), encoding='utf-8')

    def invoke(self, arguments, status=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), patch(
                'socket.socket', side_effect=AssertionError('Local templates must not connect')):
            actual = cli.main(list(map(str, arguments)))
        self.assertEqual(actual, status, stdout.getvalue() + stderr.getvalue())
        if status and not stdout.getvalue():
            return json.loads(stderr.getvalue())
        self.assertEqual(stderr.getvalue(), '')
        return json.loads(stdout.getvalue())

    def test_export_inspect_retains_order_and_excludes_identity_attributes(self):
        before = self.source.read_bytes()
        result = self.invoke(['export', self.source, '--output', self.output])
        raw = self.output.read_bytes()
        self.assertEqual(result['byte_count'], len(raw))
        self.assertTrue(result['output_created'])
        self.assertTrue(result['output_complete'])
        self.assertFalse(result['output_may_be_partial'])
        self.assertFalse(result['network_io_attempted'])
        self.assertFalse(result['unit_modified'])
        self.assertEqual(self.source.read_bytes(), before)
        template = EdltTemplate.from_xml(raw)
        self.assertEqual(template.payload, (
            ('Application', '56 255'), ('FirmwareVersion', '5.5.00'),
            ('UnitName', 'TEST'), ('UnitType', 'KEYGL5'),
            ('ParamB', '0x01'), ('ParamA', '7')))
        self.assertEqual(self.invoke(['inspect', self.output]), result['template'])

    def test_export_never_overwrites_existing_file_or_source(self):
        self.output.write_bytes(b'existing contents')
        for output in (self.output, self.source):
            with self.subTest(output=output):
                before = output.read_bytes()
                result = self.invoke(['export', self.source, '--output', output], 1)
                self.assertFalse(result['output_created'])
                self.assertFalse(result['output_complete'])
                self.assertFalse(result['output_may_be_partial'])
                self.assertEqual(output.read_bytes(), before)

    def test_export_never_follows_existing_output_symlink(self):
        target = self.root / 'protected.xml'
        target.write_bytes(b'protected')
        self.output.symlink_to(target)
        result = self.invoke(['export', self.source, '--output', self.output], 1)
        self.assertFalse(result['output_created'])
        self.assertEqual(target.read_bytes(), b'protected')
        self.assertTrue(self.output.is_symlink())

    def test_export_validates_entire_request_before_creating_output(self):
        cases = []
        for field, value in (
                ('primary_application', True), ('secondary_application', '255'),
                ('primary_application', 256), ('firmware', 5.5),
                ('description', None), ('unit_name', []),
                ('pp_attributes', {'ParamA': '7'}),
                ('pp_attributes', [['ParamA', 7]]),
                ('pp_attributes', [['ParamA']]),
                ('pp_attributes', [['ParamA', '7'], ['ParamA', '8']])):
            arguments = export_arguments()
            arguments[field] = value
            cases.append(arguments)
        missing = export_arguments()
        del missing['unit_name']
        cases.extend([missing, {**export_arguments(), 'host': 'localhost'}, []])
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.source.write_text(json.dumps(arguments), encoding='utf-8')
                self.invoke(['export', self.source, '--output', self.output], 1)
                self.assertFalse(self.output.exists())

    def test_json_duplicate_keys_nonfinite_and_malformed_fail_without_output(self):
        for raw in ('{"description":"one","description":"two"}',
                    '{"description": NaN}', '{"description": Infinity}',
                    '{"description": -Infinity}', '{broken', '\xff'):
            with self.subTest(raw=raw):
                self.source.write_bytes(raw.encode('latin-1'))
                self.invoke(['export', self.source, '--output', self.output], 1)
                self.assertFalse(self.output.exists())

    def test_partial_export_failure_retains_honest_output_evidence(self):
        class FailingOutput:
            def __enter__(self):
                return self

            def write(self, raw):
                return len(raw)

            def __exit__(self, *_args):
                raise OSError('simulated flush failure')

        with patch.object(Path, 'open', return_value=FailingOutput()):
            result = self.invoke(['export', self.source, '--output', self.output], 1)
        self.assertTrue(result['output_created'])
        self.assertFalse(result['output_complete'])
        self.assertTrue(result['output_may_be_partial'])
        self.assertFalse(result['unit_modified'])

    def test_preview_retains_assignment_order_and_has_no_mutation(self):
        before = self.xml.read_bytes(), self.names.read_bytes()
        result = self.invoke(['preview', self.xml, '--pp-attribute-names', self.names])
        self.assertTrue(result['input_validated'])
        self.assertFalse(result['schema_checked'])
        self.assertEqual([(row['name'], row['value']) for row in result['assignment_candidates']],
                         [('Application', '0x38 0xff'), ('ParamB', '0x01'), ('ParamA', '7')])
        for name in ('apply_allowed', 'mutation_attempted', 'saved',
                     'parent_lifecycle_executed', 'native_template_workflow_verified'):
            self.assertFalse(result[name])
        self.assertEqual((self.xml.read_bytes(), self.names.read_bytes()), before)

    def test_preview_rejects_invalid_pp_name_collections(self):
        for value in ({'ParamA': 7}, ['ParamA', 7], ['ParamA', 'ParamA'], ['']):
            with self.subTest(value=value):
                self.names.write_text(json.dumps(value), encoding='utf-8')
                self.invoke(['preview', self.xml, '--pp-attribute-names', self.names], 1)

    def test_preview_uses_explicit_keygl5_schema_and_returns_nonzero_validation(self):
        self.names.write_text('["ParamA"]', encoding='utf-8')
        (self.root / 'KEYGL5.xml').write_text(
            '<UnitSpecification><Type>"KEYGL5"</Type>'
            '<MinVersion>5.5.00</MinVersion><MaxVersion>5.5.00</MaxVersion>'
            '<Parameters><Param><Name>ParamA</Name><Type>int</Type>'
            '<Address>32</Address>'
            '<MinValue>0</MinValue><MaxValue>6</MaxValue></Param></Parameters>'
            '</UnitSpecification>', encoding='utf-8')
        result = self.invoke([
            'preview', self.xml, '--pp-attribute-names', self.names,
            '--spec-dir', self.root, '--firmware', '5.5.00'], 1)
        self.assertTrue(result['schema_checked'])
        self.assertFalse(result['input_validated'])
        self.assertTrue(result['validation_errors'])
        self.assertFalse(result['apply_allowed'])

    def test_preview_firmware_mismatch_is_an_explicit_warning(self):
        result = self.invoke(['preview', self.xml, '--pp-attribute-names', self.names,
                              '--firmware', '6.0.0'])
        self.assertTrue(any('firmware differ' in message for message in result['warnings']))
        self.assertFalse(result['apply_allowed'])

    def test_bad_crc_is_rejected_without_reading_target_names(self):
        raw = self.xml.read_bytes().replace(b'<ParamA>7</ParamA>', b'<ParamA>88</ParamA>')
        self.xml.write_bytes(raw)
        result = self.invoke(['preview', self.xml, '--pp-attribute-names', self.root / 'missing'], 1)
        self.assertIn('CRC mismatch', result['error'])

    def test_apply_refuses_before_any_file_or_spec_io(self):
        for arguments in (['apply'], ['apply', self.root / 'missing.xml']):
            with self.subTest(arguments=arguments), patch.object(
                    cli.os, 'open', side_effect=AssertionError('apply must not open')), patch.object(
                    Path, 'open', side_effect=AssertionError('apply must not open')), patch(
                    'cbus_toolkit.unitspec.UnitSpecStore',
                    side_effect=AssertionError('apply must not load specifications')):
                result = self.invoke(arguments, 1)
            self.assertEqual(result['type'], 'EdltTemplateApplyRefused')
            self.assertEqual(result['status'], 'refused')
            self.assertFalse(result['mutation_attempted'])
            self.assertFalse(result['saved'])
            self.assertTrue(result['blockers'])

    def test_adapter_registers_root_and_keeps_apply_exception(self):
        parser = argparse.ArgumentParser()
        cli.options(parser.add_subparsers(dest='area', required=True))
        args = parser.parse_args(['edlt-templates', 'inspect', str(self.xml)])
        result, status = cli.run(args)
        self.assertEqual(status, 0)
        self.assertEqual(result, EdltTemplate.from_xml(self.xml.read_bytes()).as_dict())
        args = parser.parse_args(['edlt-templates', 'apply', 'never-read.xml'])
        with self.assertRaises(EdltTemplateApplyRefused):
            cli.run(args)

    def test_oversized_regular_file_is_refused_before_parser(self):
        with patch.object(cli, 'MAX_INPUT_BYTES', 10):
            result = self.invoke(['inspect', self.xml], 1)
        self.assertIn('size limit', result['error'])

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'named pipe test requires POSIX')
    def test_fifo_is_refused_without_waiting_for_a_writer(self):
        fifo = self.root / 'pipe.xml'
        os.mkfifo(fifo)
        result = self.invoke(['inspect', fifo], 1)
        self.assertIn('regular local files', result['error'])

    def test_standalone_module_runs_with_compact_json(self):
        result = subprocess.run(
            [sys.executable, '-m', 'cbus_toolkit.edlt_templates_cli',
             '--compact', 'inspect', str(self.xml)],
            capture_output=True, text=True, check=False, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertTrue(json.loads(result.stdout)['crc_valid'])


if __name__ == '__main__':
    unittest.main()
