"""Offline classic DLT ICON dialog routing, source binding and file safety."""
import argparse
from copy import deepcopy
import json
import os
from xml.dom import minidom

import pytest

from cbus_toolkit import dlt_icon_dialog_cli
from cbus_toolkit.dlt_project_labels import show_project_labels
from test_cli_dlt_controls import cli
from test_dlt_project_labels import ACTION, GROUP, project, tag


def source_file(tmp_path, text=None):
    if text is None:
        text = project(tag('202', '1', 'ICON', '7', 'first-icon') + tag(value='Other language'))
    source = tmp_path / 'source.xml'
    source.write_text(text.replace('<Languages>',
        '<Languages><Language><ID>202</ID><TagValue>Icons</TagValue></Language>', 1), encoding='utf-8')
    return source


def plan(source, *, variant=2, icon=91, language=202, target=GROUP, status=0):
    return cli('dlt', 'icon-dialog', 'plan', '--project-xml', source, '--target', target,
               '--language', language, '--variant', variant, '--icon', icon, status=status)


def apply(tmp_path, source, document, *, name='output.xml', status=0):
    saved_plan = tmp_path / (name + '.plan.json')
    saved_plan.write_text(json.dumps(document), encoding='utf-8')
    output = tmp_path / name
    result = cli('dlt', 'icon-dialog', 'apply', '--project-xml', source, '--plan', saved_plan,
                 '--output', output, status=status)
    return output, result


def selected_labels(path, *, target=GROUP):
    shown = show_project_labels(path.read_text(encoding='utf-8'), target)
    return {int(row['variant']): row for row in shown['labels'] if row['language_id'] == '202'}


def parse(*args):
    parser = argparse.ArgumentParser()
    dlt_icon_dialog_cli.options(parser.add_subparsers(dest='action', required=True))
    return parser.parse_args(['icon-dialog', *map(str, args)])


def test_parser_requires_explicit_language_and_has_no_execution_or_owner_context():
    common = ('plan', '--project-xml', 'source.xml', '--target', GROUP, '--variant', '1', '--icon', '7')
    assert parse(*common, '--language', '202').icon == 7
    for extra in ((), ('--language', '202', '--owner-default-representation', 'Owner'),
                  ('--language', '202', '--host', '127.0.0.1'), ('--language', '202', '--execute')):
        with pytest.raises(SystemExit) as error:
            parse(*common, *extra)
        assert error.value.code == 2


@pytest.mark.parametrize('payload', [
    '{"format":"a","format":"b"}', '{"nested":{"value":1,"value":2}}',
    '{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}',
    '{"value":1e9999}', '{"value":-1e9999}',
])
def test_duplicate_and_nonfinite_plan_json_are_refused(tmp_path, payload):
    path = tmp_path / 'invalid-plan.json'
    path.write_text(payload, encoding='utf-8')
    with pytest.raises(ValueError, match='Duplicate JSON key|Non-finite JSON number'):
        dlt_icon_dialog_cli._read_plan(path)


def test_plan_reader_requires_bounded_regular_file(tmp_path, monkeypatch):
    path = tmp_path / 'plan.json'
    path.write_text('{"value":"valid"}', encoding='utf-8')
    assert dlt_icon_dialog_cli._read_plan(path) == {'value': 'valid'}
    link = tmp_path / 'link.json'
    link.symlink_to(path)
    for invalid in (tmp_path, link):
        with pytest.raises((ValueError, OSError)):
            dlt_icon_dialog_cli._read_plan(invalid)
    if hasattr(os, 'mkfifo'):
        fifo = tmp_path / 'fifo.json'
        os.mkfifo(fifo)
        with pytest.raises(ValueError, match='regular file'):
            dlt_icon_dialog_cli._read_plan(fifo)
    monkeypatch.setattr(dlt_icon_dialog_cli, 'MAX_PLAN_BYTES', 4)
    with pytest.raises(ValueError, match='size limit'):
        dlt_icon_dialog_cli._read_plan(path)


def test_public_show_plan_apply_reload_preserves_oid_and_unowned_nodes(tmp_path):
    source = source_file(tmp_path)
    before = source.read_bytes()
    assert isinstance(cli('dlt', 'icon-dialog', 'show', '--project-xml', source,
                          '--target', GROUP, '--language', 202), dict)
    document = plan(source)
    assert document['requested'] == {'language': 202, 'variant': 2, 'icon_id': 91}
    assert [row['variant'] for row in document['effects']] == [1, 2, 3, 4]
    output, result = apply(tmp_path, source, document)
    assert result['file_saved'] is True and result['database_saved'] is False
    assert result['labels_transferred'] is False and result['device_verified'] is False
    assert result['candidate_sha256'] == document['candidate_sha256']
    labels = selected_labels(output)
    assert set(labels) == {1, 2}
    assert labels[1]['text'] == '7' and labels[1]['oid'] == 'first-icon'
    assert labels[2]['text'] == '91' and labels[2]['oid'] is None
    assert all(row['tag_type'] == 'ICON' for row in labels.values())
    assert source.read_bytes() == before
    before_dom, after_dom = minidom.parseString(before), minidom.parseString(output.read_bytes())
    for document_dom in (before_dom, after_dom):
        group = document_dom.getElementsByTagName('Group')[0]
        collection = [node for node in group.childNodes
                      if node.nodeType == node.ELEMENT_NODE and node.tagName == 'TagsDLT'][0]
        for label in list(collection.childNodes):
            if label.nodeType == label.ELEMENT_NODE and label.tagName == 'TagDLT' and \
                    label.getElementsByTagName('LanguageID')[0].firstChild.data == '202':
                collection.removeChild(label)
    assert before_dom.toxml() == after_dom.toxml()
    assert isinstance(cli('dlt', 'icon-dialog', 'show', '--project-xml', output,
                          '--target', GROUP, '--language', 202), dict)
    saved = output.read_bytes()
    _, refusal = apply(tmp_path, source, document, status=1)
    assert 'error' in refusal and output.read_bytes() == saved


def test_legacy_zero_identity_and_missing_first_require_no_owner_context(tmp_path):
    source = source_file(tmp_path, project(tag('202', '0', 'ICON', '2', 'legacy-icon')))
    output, _ = apply(tmp_path, source, plan(source, variant=1, icon=1))
    labels = selected_labels(output)
    assert set(labels) == {0} and labels[0]['text'] == '1' and labels[0]['oid'] == 'legacy-icon'
    source = source_file(tmp_path, project(''))
    missing, _ = apply(tmp_path, source, plan(source, variant=4, icon=7), name='missing.xml')
    assert set(selected_labels(missing)) == {4}


def test_trigger_action_address_and_value_remain_distinct(tmp_path):
    source = source_file(tmp_path)
    before_group = show_project_labels(source.read_text(encoding='utf-8'), '//DLTTEXT/254/202/7')['labels']
    output, _ = apply(tmp_path, source, plan(source, target=ACTION, variant=1, icon=1))
    assert selected_labels(output, target=ACTION)[1]['text'] == '1'
    assert '<Level Value="43">' in output.read_text(encoding='utf-8')
    assert show_project_labels(output.read_text(encoding='utf-8'), '//DLTTEXT/254/202/7')['labels'] == before_group


def test_invalid_language_and_icons_are_refused(tmp_path):
    source = source_file(tmp_path)
    for language in (0, 1, 14, 64, 116, 203, 255):
        assert 'error' in plan(source, language=language, status=1)
    for icon in (-1, 0, 92, 65535):
        assert 'error' in plan(source, icon=icon, status=1)


def test_ambiguous_selected_graph_is_refused(tmp_path):
    source = source_file(tmp_path)
    original = source.read_text(encoding='utf-8')
    variants = (
        original.replace('<ID>202</ID>', '<ID>0202</ID>'),
        original.replace('<LanguageID>202</LanguageID>', '<LanguageID>0202</LanguageID>'),
        original.replace('<LanguageID>202</LanguageID><FlavourID>1</FlavourID>',
                         '<LanguageID>202</LanguageID><FlavourID>01</FlavourID>', 1),
        original.replace('<Address>254</Address>', '<Address>0254</Address>', 1),
        original.replace('<TagsDLT x:keep="yes">', '<TagsDLT/><TagsDLT x:keep="yes">', 1),
        original.replace('</Languages>', '<Language><ID>202</ID><TagValue>Duplicate</TagValue></Language></Languages>', 1),
        original.replace('<TagsDLT x:keep="yes">', '<TagsDLT x:keep="yes">' + tag('202', '1', 'ICON', '2'), 1),
    )
    for malformed in variants:
        source.write_text(malformed, encoding='utf-8')
        assert 'error' in plan(source, status=1)


def test_stale_and_forged_plans_create_no_output(tmp_path):
    source = source_file(tmp_path)
    document = plan(source)
    forged_variants = [
        {**document, 'candidate_sha256': 'bad'}, {**document, 'labels_transferred': True},
        {**document, 'target_xml': '<Group/>'}, {**document, 'changed': int(document['changed'])},
    ]
    for field, value in (('language', 202.0), ('variant', True), ('icon_id', 91.0), ('icon_id', True)):
        changed = deepcopy(document)
        changed['requested'][field] = value
        forged_variants.append(changed)
    for position, forged in enumerate(forged_variants):
        output, refusal = apply(tmp_path, source, forged, name=f'forged-{position}.xml', status=1)
        assert 'error' in refusal and not output.exists()
    source.write_text(source.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    output, refusal = apply(tmp_path, source, document, name='stale.xml', status=1)
    assert 'error' in refusal and not output.exists()


def test_xml_and_output_file_boundaries(tmp_path, monkeypatch):
    source = source_file(tmp_path)
    link = tmp_path / 'source-link.xml'
    link.symlink_to(source)
    refusal = cli('dlt', 'icon-dialog', 'show', '--project-xml', link,
                  '--target', GROUP, '--language', 202, status=1)
    assert 'regular file' in refusal['error']
    document = plan(source)
    output = tmp_path / 'existing-link.xml'
    output.symlink_to(source)
    before = source.read_bytes()
    _, refusal = apply(tmp_path, source, document, name=output.name, status=1)
    assert 'error' in refusal and source.read_bytes() == before and output.is_symlink()
    monkeypatch.setattr(dlt_icon_dialog_cli, 'MAX_XML_BYTES', 8)
    with pytest.raises(ValueError, match='size limit'):
        dlt_icon_dialog_cli.offline(parse('show', '--project-xml', source, '--target', GROUP, '--language', '202'))
