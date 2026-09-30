"""Public offline DLT language TEXT dialog routing, confirmation and file safety."""
import json

import pytest

from cbus_toolkit import dlt_language_dialog_cli
from cbus_toolkit.dlt_project_labels import show_project_labels
from test_cli_dlt_controls import cli
from test_dlt_project_labels import GROUP, project, tag


def source_file(tmp_path, text=None):
    source = tmp_path / 'source.xml'
    source.write_text(with_language(project() if text is None else text), encoding='utf-8')
    return source


def with_language(text):
    return text.replace('<Languages>', '<Languages><Language><ID>1</ID><TagValue>English</TagValue></Language>', 1)


def plan(source, *, variant=2, text='New text', language=1, extra=(), status=0):
    return cli('dlt', 'text-dialog', 'plan', '--project-xml', source, '--target', GROUP,
               '--language', language, '--variant', variant, '--text', text, *extra, status=status)


def apply(tmp_path, source, document, *, name='output.xml', status=0):
    saved_plan = tmp_path / (name + '.plan.json')
    saved_plan.write_text(json.dumps(document), encoding='utf-8')
    output = tmp_path / name
    result = cli('dlt', 'text-dialog', 'apply', '--project-xml', source, '--plan', saved_plan,
                 '--output', output, status=status)
    return output, result


def selected_labels(path, language=1):
    shown = show_project_labels(path.read_text(encoding='utf-8'), GROUP)
    return {int(row['variant']): row for row in shown['labels'] if row['language_id'] == str(language)}


def test_public_show_plan_apply_reload_finalizes_variants_and_refuses_overwrite(tmp_path):
    source = source_file(tmp_path)
    before = source.read_bytes()
    shown = cli('dlt', 'text-dialog', 'show', '--project-xml', source, '--target', GROUP, '--language', 1)
    assert isinstance(shown, dict)
    document = plan(source, text='ABCDEFGHIJKLMNOPQRSTUVWXYZ')
    output, result = apply(tmp_path, source, document)
    assert result['file_saved'] and not result['database_saved']
    assert not result['labels_transferred'] and not result['device_verified']
    assert result['candidate_sha256'] == document['candidate_sha256']
    labels = selected_labels(output)
    assert set(labels) == {1, 2}
    assert [row['variant'] for row in document['effects']] == [1, 2, 3, 4]
    assert labels[1]['text'] == 'Before' and labels[2]['text'] == 'ABCDEFGHIJKLMNOPQRST'
    assert all(row['tag_type'] == 'TEXT' for row in labels.values())
    assert source.read_bytes() == before
    assert isinstance(cli('dlt', 'text-dialog', 'show', '--project-xml', output,
                          '--target', GROUP, '--language', 1), dict)
    saved = output.read_bytes()
    _, refusal = apply(tmp_path, source, document, status=1)
    assert 'error' in refusal and output.read_bytes() == saved


def test_empty_dialog_text_is_default_while_raw_text_stays_empty(tmp_path):
    source = source_file(tmp_path)
    output, _ = apply(tmp_path, source, plan(source, variant=3, text=''))
    assert selected_labels(output)[3]['text'] == '<Default>'
    raw_plan = cli('dlt', 'text', 'plan', '--project-xml', source, '--target', GROUP, '--edit', '1:3=')
    raw_file = tmp_path / 'raw-plan.json'
    raw_file.write_text(json.dumps(raw_plan), encoding='utf-8')
    raw_output = tmp_path / 'raw-output.xml'
    cli('dlt', 'text', 'apply', '--project-xml', source, '--plan', raw_file, '--output', raw_output)
    assert selected_labels(raw_output)[3]['text'] == ''


def test_unicode_confirmation_checks_whole_input_and_uses_utf16_prefix(tmp_path):
    source = source_file(tmp_path)
    value = 'A' * 20 + '\u0100'
    assert 'error' in plan(source, text=value, status=1)
    output, _ = apply(tmp_path, source, plan(source, text=value, extra=('--confirm-non-latin1',)))
    assert selected_labels(output)[2]['text'] == 'A' * 20
    emojis, _ = apply(tmp_path, source, plan(source, text='😀' * 11, extra=('--confirm-non-latin1',)),
                      name='emoji.xml')
    assert selected_labels(emojis)[2]['text'] == '😀' * 10
    latin, _ = apply(tmp_path, source, plan(source, text='café'), name='latin.xml')
    assert selected_labels(latin)[2]['text'] == 'café'


def test_legacy_zero_fallback_and_explicit_owner_default(tmp_path):
    source = source_file(tmp_path, project(tag(variant='0', value='Legacy first')))
    output, _ = apply(tmp_path, source, plan(source, variant=3, text='Third'))
    labels = selected_labels(output)
    assert labels[0]['text'] == 'Legacy first' and labels[3]['text'] == 'Third'
    assert 1 not in labels  # The legacy record keeps its stored identity.
    source.write_text(with_language(project('')), encoding='utf-8')
    assert 'error' in plan(source, text='Second', status=1)
    owner, _ = apply(tmp_path, source, plan(source, text='Second',
                     extra=('--owner-default-representation', 'Owner default')), name='owner.xml')
    assert selected_labels(owner)[1]['text'] == 'Owner default'
    assert selected_labels(owner)[2]['text'] == 'Second'
    direct, _ = apply(tmp_path, source, plan(source, variant=1, text='Explicit first'), name='first.xml')
    assert selected_labels(direct)[1]['text'] == 'Explicit first'


@pytest.mark.parametrize('payload', [
    '{"format":"a","format":"b"}', '{"nested":{"value":1,"value":2}}',
    '{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}',
    '{"value":1e9999}', '{"value":-1e9999}',
])
def test_duplicate_and_nonfinite_json_are_refused(tmp_path, payload):
    path = tmp_path / 'invalid-plan.json'
    path.write_text(payload, encoding='utf-8')
    with pytest.raises(ValueError, match='Duplicate JSON key|Non-finite JSON number'):
        dlt_language_dialog_cli._read_plan(path)


def test_invalid_stale_or_forged_plan_creates_no_output(tmp_path):
    source = source_file(tmp_path)
    document = plan(source)
    forged, refusal = apply(tmp_path, source, {**document, 'candidate_sha256': 'bad'}, status=1)
    assert 'error' in refusal and not forged.exists()
    source.write_text(source.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    stale, refusal = apply(tmp_path, source, document, name='stale.xml', status=1)
    assert 'error' in refusal and not stale.exists()
    invalid = tmp_path / 'invalid-plan.json'
    invalid.write_text('{"value":1,"value":2}', encoding='utf-8')
    output = tmp_path / 'invalid.xml'
    refusal = cli('dlt', 'text-dialog', 'apply', '--project-xml', source, '--plan', invalid,
                  '--output', output, status=1)
    assert 'Duplicate JSON key' in refusal['error'] and not output.exists()


def test_reader_uses_bounds_and_refuses_symlinks(tmp_path, monkeypatch):
    source = source_file(tmp_path)
    link = tmp_path / 'link.xml'
    link.symlink_to(source)
    refusal = cli('dlt', 'text-dialog', 'show', '--project-xml', link, '--target', GROUP, '--language', 1, status=1)
    assert 'regular file' in refusal['error']
    plan_file = tmp_path / 'large-plan.json'
    plan_file.write_text('{"padding":"oversized"}', encoding='utf-8')
    monkeypatch.setattr(dlt_language_dialog_cli, 'MAX_PLAN_BYTES', 8)
    with pytest.raises(ValueError, match='size limit'):
        dlt_language_dialog_cli._read_plan(plan_file)
