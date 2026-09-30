"""Public template dispatch and separate local parent staging boundaries."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest

from cbus_toolkit import cli
from cbus_toolkit.edlt_templates import EdltTemplateError
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction, normalize_operations
from cbus_toolkit.edlt_lifecycle import LifecycleCache
from cbus_toolkit.edlt_reset import _RawState
from cbus_toolkit.edlt_template_staging import TemplatePpSnapshot
from tests.test_edlt_templates_cli import export_arguments
from tests.test_edlt_reset import fixture, metadata
from tests.test_edlt_template_staging import template


def invoke(arguments):
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr), patch(
            'socket.socket', side_effect=AssertionError('local interface opened transport')):
        status = cli.main(list(map(str, arguments)))
    return status, json.loads(stdout.getvalue() or stderr.getvalue())


def test_public_export_inspect_preview_and_exclusive_output():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source, output, names = root/'source.json', root/'new.xml', root/'names.json'
        source.write_text(json.dumps(export_arguments()))
        names.write_text(json.dumps(['Application', 'ParamA', 'ParamB']))
        status, result = invoke(['edlt-templates', 'export', source, '--output', output])
        assert status == 0 and result['output_complete']
        saved = output.read_bytes()
        assert invoke(['edlt-templates', 'inspect', output])[0] == 0
        status, result = invoke(['edlt-templates', 'preview', output, '--pp-attribute-names', names])
        assert status == 0 and result['input_validated'] and not result['apply_allowed']
        assert invoke(['edlt-templates', 'export', source, '--output', output])[0] == 1
        assert output.read_bytes() == saved


def test_public_apply_refuses_before_input_read():
    with patch('cbus_toolkit.edlt_templates_cli._read_bytes', side_effect=AssertionError('read input')):
        status, result = invoke(['edlt-templates', 'apply', '/nonexistent/template.xml'])
    assert status == 1 and result['type'] == 'EdltTemplateApplyRefused'


def test_parent_adapter_stages_cancels_and_never_admits_apply():
    from tests.test_edlt_parent_form import fixture as parent_fixture
    spec = fixture()
    parameters = dict(spec.parameters)
    parameters.update(parent_fixture().parameters)
    spec = replace(spec, parameters=parameters)
    parent = EdltParentTransaction(spec)
    stager = parent.template_lifecycle_stager()
    other = parent.template_lifecycle_stager()
    assert stager is not other
    raw = _RawState(spec.defaults()).raw()
    source = TemplatePpSnapshot([(name, value.split(' '), False) for name, value in raw.items()])
    before = source.as_dict()
    cache = LifecycleCache.from_dict(metadata()['lifecycle'])
    candidate = stager.stage(template([('Widget6WidgetType', '0x2')]), source=source, metadata=cache)
    assert stager.validate(candidate, current_source=source, metadata=cache) is candidate
    assert source.as_dict() == before
    assert not candidate.as_dict()['apply_allowed'] and not candidate.as_dict()['saved']
    with pytest.raises(EdltTemplateError):
        stager.apply(object())
    stager.cancel()
    with pytest.raises(EdltTemplateError):
        stager.validate(candidate, current_source=source, metadata=cache)
    with pytest.raises(ValueError):
        normalize_operations([{'op': 'template'}])


def test_public_native_derivative_keeps_historical_scope_and_declares_only_path_changes():
    path = Path(__file__).resolve().parents[1] / 'research/edlt_template_terminal_native_attempt1.json'
    receipt = json.loads(path.read_bytes())
    provenance = receipt['public_derivative_provenance']
    assert provenance['original_sha256'] == '7926101e597d90ed2c9110a605e07db6b7d83d8fd0be62e709360eba201de549'
    assert set(provenance['normalized_json_pointer_fields']) == {
        '/service/java', '/service/argv/0', '/service/argv/6'}
    assert provenance['historical_execution_unchanged'] and not provenance['new_execution_performed']
    assert receipt['passed'] and receipt['fresh_pp_reload_verified']
    assert not receipt['template_apply_executed'] and not receipt['physical_devices_accessed']
    assert not receipt['original_save_validation_verified'] and not receipt['complete_parent_lifecycle_verified']
    assert receipt['source_hashes_before'] == receipt['source_hashes_after']
    assert '/Volumes/' not in path.read_text() and '/Users/' not in path.read_text()
