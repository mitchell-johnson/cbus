import argparse
import json
import os

import pytest

from cbus_toolkit import dlt_project_cli
from test_dlt_project_labels import GROUP, project


def parse(*args):
    parser = argparse.ArgumentParser()
    dlt_project_cli.options(parser.add_subparsers(dest='action', required=True))
    return parser.parse_args(['text', *args])


def test_show_plan_apply_new_file_and_reload(tmp_path):
    source, saved_plan, output = (tmp_path / name for name in ('source.xml', 'plan.json', 'result.xml'))
    source.write_text(project(), encoding='utf-8')
    shown, code = dlt_project_cli.offline(parse('show', '--project-xml', str(source), '--target', GROUP))
    assert code == 0 and shown['labels'][0]['text'] == 'Before'
    plan, code = dlt_project_cli.offline(parse('plan', '--project-xml', str(source), '--target', GROUP,
                                           '--edit', '1:1=New text', '--edit', '255:4='))
    assert code == 0
    saved_plan.write_text(json.dumps(plan), encoding='utf-8')
    args = parse('apply', '--project-xml', str(source), '--plan', str(saved_plan), '--output', str(output))
    result, code = dlt_project_cli.offline(args)
    assert code == 0 and result['file_saved'] and not result['database_saved']
    labels, code = dlt_project_cli.offline(parse('show', '--project-xml', str(output), '--target', GROUP))
    assert labels['labels'][0]['text'] == 'New text' and labels['labels'][-1]['text'] == ''
    assert source.read_text() == project()
    with pytest.raises(FileExistsError):
        dlt_project_cli.offline(args)


def test_stale_plan_creates_no_output(tmp_path):
    source, saved_plan, output = (tmp_path / name for name in ('source.xml', 'plan.json', 'result.xml'))
    source.write_text(project(), encoding='utf-8')
    plan, _ = dlt_project_cli.offline(parse('plan', '--project-xml', str(source), '--target', GROUP, '--edit', '1:1=new'))
    saved_plan.write_text(json.dumps(plan), encoding='utf-8')
    source.write_text(project() + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='changed since'):
        dlt_project_cli.offline(parse('apply', '--project-xml', str(source), '--plan', str(saved_plan), '--output', str(output)))
    assert not output.exists()


def test_reader_refuses_fifo_symlink_and_oversize(tmp_path):
    fifo, link, source = (tmp_path / name for name in ('fifo', 'link', 'file'))
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match='regular file'):
        dlt_project_cli._read(fifo, 100)
    source.write_text('data')
    link.symlink_to(source)
    with pytest.raises((OSError, ValueError)):
        dlt_project_cli._read(link, 100)
    with pytest.raises(ValueError, match='size limit'):
        dlt_project_cli._read(source, 1)


def test_reader_without_posix_flags(tmp_path, monkeypatch):
    source = tmp_path / 'source.xml'
    source.write_text('data')
    monkeypatch.delattr(os, 'O_NOFOLLOW', raising=False)
    monkeypatch.delattr(os, 'O_NONBLOCK', raising=False)
    assert dlt_project_cli._read(source, 100) == 'data'


@pytest.mark.parametrize('value', ['1=Text', '1:0=Text', '1:5=Text', '-1:1=Text', '01:1=Text'])
def test_edit_syntax(value):
    with pytest.raises(ValueError):
        dlt_project_cli._edit(value)


def test_public_cli_show_plan_apply_reload(tmp_path):
    import subprocess
    import sys
    source, plan_file, output = (tmp_path / name for name in ('source.xml', 'plan.json', 'output.xml'))
    source.write_text(project(), encoding='utf-8')
    def cli(*args, expected=0):
        reply = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'dlt', 'text', *map(str, args)],
                               capture_output=True, text=True, timeout=10)
        assert reply.returncode == expected, reply.stdout + reply.stderr
        return json.loads(reply.stdout or reply.stderr)
    assert cli('show', '--project-xml', source, '--target', GROUP)['labels'][0]['text'] == 'Before'
    plan = cli('plan', '--project-xml', source, '--target', GROUP, '--edit', '1:1=café 😀', '--edit', '2:4=')
    plan_file.write_text(json.dumps(plan), encoding='utf-8')
    assert cli('apply', '--project-xml', source, '--plan', plan_file, '--output', output)['file_saved']
    result = cli('show', '--project-xml', output, '--target', GROUP)
    assert result['labels'][0]['text'] == 'café 😀' and result['labels'][-1]['text'] == ''
    assert 'error' in cli('apply', '--project-xml', source, '--plan', plan_file, '--output', output, expected=1)


def test_generated_json_plan_larger_than_xml_limit_is_readable(tmp_path, monkeypatch):
    # Scale the limit down to exercise expansion without a 20 MiB fixture.
    from cbus_toolkit import dlt_project_labels
    from test_dlt_project_labels import edit, tag
    text = project(tag(value='α' * 1024))
    plan = dlt_project_labels.plan_project_labels(text, GROUP, [edit(text='new')]).as_dict()
    xml_limit = len(text.encode('utf-8')) + 1
    assert len(json.dumps(plan).encode('utf-8')) > xml_limit
    monkeypatch.setattr(dlt_project_cli, 'MAX_XML_BYTES', xml_limit)
    source, plan_file, output = (tmp_path / name for name in ('source.xml', 'plan.json', 'output.xml'))
    source.write_text(text, encoding='utf-8')
    plan_file.write_text(json.dumps(plan), encoding='utf-8')
    result, _ = dlt_project_cli.offline(parse('apply', '--project-xml', str(source), '--plan', str(plan_file), '--output', str(output)))
    assert result['file_saved']
