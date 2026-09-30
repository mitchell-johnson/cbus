"""Project-only DLT text ownership, replay, encoding and preservation checks."""
import json
from xml.dom import minidom

import pytest

from cbus_toolkit.dlt_project_labels import (apply_project_labels,
                                            plan_project_labels, show_project_labels)

GROUP = '//DLTTEXT/254/56/1'
ACTION = '//DLTTEXT/254/202/7/42'


def tag(language='1', variant='1', kind='TEXT', value='Before', oid='label-oid'):
    return (f'<TagDLT><OID>{oid}</OID><LanguageID>{language}</LanguageID>'
            f'<FlavourID>{variant}</FlavourID><TagType>{kind}</TagType>'
            f'<TagValue>{value}</TagValue></TagDLT>')


def project(tags=None):
    if tags is None:
        tags = tag() + tag('2', '1', 'FONT', 'other font', 'other-label')
    return ('<?xml version="1.0" encoding="utf-8"?><?keep processing?>'
            '<Installation xmlns:x="urn:other"><Project><Address>DLTTEXT</Address>'
            '<Network><Address>254</Address><Languages>'
            '<Language><ID>0</ID><TagValue>2</TagValue></Language>'
            '<Language><ID>2</ID><TagValue>Second language</TagValue></Language></Languages>'
            '<Unit><Address>20</Address><UnitType>KEYML5</UnitType>'
            '<PP Name="EnableDynamicLabels" Value="1"/></Unit>'
            '<Application><Address>56</Address><Group data="keep"><OID>group-oid</OID>'
            '<Address>1</Address><TagName>Group</TagName><!--keep group comment-->'
            '<Level Value="23"><Address>99</Address><TagsDLT>' + tag(value='level untouched', oid='level-tag') + '</TagsDLT></Level>'
            '<TagsDLT x:keep="yes">' + tags + '</TagsDLT><x:TagsDLT><x:Opaque/></x:TagsDLT>'
            '</Group><Group><Address>2</Address><TagsDLT>' + tag(value='neighbor', oid='neighbor') + '</TagsDLT></Group>'
            '</Application><Application><Address>202</Address><Group><Address>7</Address>'
            '<TagsDLT>' + tag(value='trigger group', oid='trigger-group-tag') + '</TagsDLT>'
            '<Level Value="43"><OID>action-oid</OID><Address>42</Address><TagName>Action</TagName>'
            '<TagsDLT>' + tag(value='action before', oid='action-tag') + '</TagsDLT>'
            '</Level></Group></Application></Network></Project></Installation>')


def edit(language=1, variant=1, text='After'):
    return {'language_id': language, 'variant': variant, 'text': text}


def test_group_multi_language_all_variants_and_preservation():
    original = project()
    changes = [edit(1, variant, f'Variant {variant}') for variant in range(1, 5)] + [edit(255, 4, '语言 😀 & < >')]
    plan = plan_project_labels(original, GROUP, changes)
    saved = apply_project_labels(original, json.loads(json.dumps(plan.as_dict())))
    after = show_project_labels(saved, GROUP)
    assert [(row['language_id'], row['variant'], row['text']) for row in after['labels']] == [
        ('1', '1', 'Variant 1'), ('2', '1', 'other font'), ('1', '2', 'Variant 2'),
        ('1', '3', 'Variant 3'), ('1', '4', 'Variant 4'), ('255', '4', '语言 😀 & < >')]
    assert after['labels'][0]['oid'] == 'label-oid'
    assert all(row['oid'] is None for row in after['labels'][2:])
    assert after['network_languages'] == show_project_labels(original, GROUP)['network_languages']
    before_dom, after_dom = minidom.parseString(original), minidom.parseString(saved)
    for document in (before_dom, after_dom):
        group = document.getElementsByTagName('Group')[0]
        collection = [n for n in group.childNodes if n.nodeType == n.ELEMENT_NODE and n.tagName == 'TagsDLT'][0]
        group.removeChild(collection)
    assert before_dom.toxml() == after_dom.toxml()
    assert '<TagsDLT x:keep="yes">' in saved
    assert minidom.parseString(plan.target_xml).documentElement.tagName == 'Group'
    assert plan.as_dict()['labels_transferred'] is False
    assert plan.as_dict()['language_definitions_changed'] is False


def test_action_selection_uses_address_preserves_value_and_group_label():
    original = project()
    saved = apply_project_labels(original, plan_project_labels(original, ACTION, [edit(text='Scene café')]))
    assert show_project_labels(saved, ACTION)['labels'][0]['text'] == 'Scene café'
    assert show_project_labels(saved, '//DLTTEXT/254/202/7')['labels'][0]['text'] == 'trigger group'
    assert '<Level Value="43">' in saved


@pytest.mark.parametrize('value', ['', 'ASCII = a:b', 'café', '语言', '😀', '\t\n\r', 'x' * 1024])
def test_text_and_new_language_roundtrip(value):
    original = project()
    plan = plan_project_labels(original, GROUP, [edit(0, 4, value)])
    saved = apply_project_labels(original, plan)
    assert show_project_labels(saved, GROUP)['labels'][-1]['text'] == value
    assert plan_project_labels(saved, GROUP, [edit(0, 4, value)]).candidate_xml == saved


def test_cdata_comments_attributes_extensions_preserved():
    original = project(tag(value='<x:keep/>'))
    with pytest.raises(ValueError, match='nested XML'):
        plan_project_labels(original, GROUP, [edit()])
    original = project(tag(value='Before').replace('<TagValue>Before</TagValue>',
        '<TagValue x:attr="A&#10;B&#9;C&#13;D"><![CDATA[Before]]><!--keep--><?keep value?></TagValue>'))
    original = original.replace('<Project>', '<Project ext="A&#10;B&#9;C&#13;D">')
    saved = plan_project_labels(original, GROUP, [edit(text=']]>')]).candidate_xml
    assert show_project_labels(saved, GROUP)['labels'][0]['text'] == ']]>'
    assert '<!--keep-->' in saved and '<?keep value?>' in saved
    parsed = minidom.parseString(saved)
    assert parsed.getElementsByTagName('Project')[0].getAttribute('ext') == 'A\nB\tC\rD'
    assert parsed.getElementsByTagName('TagValue')[3].getAttribute('x:attr') == 'A\nB\tC\rD'


def test_noop_byte_exact_missing_collection_created():
    original = project()
    plan = plan_project_labels(original, GROUP, [edit(text='Before')])
    assert plan.candidate_xml == original and plan.as_dict()['changed'] is False
    original = project('').replace('<TagsDLT x:keep="yes"></TagsDLT>', '')
    saved = plan_project_labels(original, GROUP, [edit()]).candidate_xml
    assert show_project_labels(saved, GROUP)['labels'][0]['text'] == 'After'


@pytest.mark.parametrize('value', ['\x00', '\x01', '\x0b', '\ufffe', '\uffff', '\ud800', 'x' * 1025, 1, None])
def test_invalid_text_refused(value):
    with pytest.raises(ValueError, match='text'):
        plan_project_labels(project(), GROUP, [edit(text=value)])


@pytest.mark.parametrize('language,variant', [(True, 1), (-1, 1), (256, 1), ('1', 1), (1, False), (1, 0), (1, 5)])
def test_invalid_language_variant_refused(language, variant):
    with pytest.raises(ValueError):
        plan_project_labels(project(), GROUP, [edit(language, variant)])


def test_ambiguous_and_nontext_selected_variants_refused():
    for original, changes, match in (
        (project(tag() + tag()), [edit()], 'duplicate TagDLT'),
        (project(tag('01')), [edit()], 'noncanonical'),
        (project(), [edit(2, 1)], 'not TEXT'),
        (project(), [edit(), edit()], 'more than once'),
    ):
        with pytest.raises(ValueError, match=match):
            plan_project_labels(original, GROUP, changes)


def test_unrelated_raw_variants_retained_without_interpretation():
    original = project(tag() + tag('English', 'Primary', 'UNKNOWN', 'opaque', 'opaque'))
    saved = plan_project_labels(original, GROUP, [edit()]).candidate_xml
    assert tag('English', 'Primary', 'UNKNOWN', 'opaque', 'opaque') in saved


@pytest.mark.parametrize('target', ['//OTHER/254/56/1', '//DLTTEXT/254/56/1/99', '//DLTTEXT/254/1/1',
                                   '//DLTTEXT/254/56/99', '//DLTTEXT/0254/56/1', '//DLTTEXT/254/p/20'])
def test_target_scope_refused(target):
    with pytest.raises(ValueError):
        plan_project_labels(project(), target, [edit()])


def test_source_and_plan_tampering_refused():
    original = project()
    plan = plan_project_labels(original, GROUP, [edit()]).as_dict()
    with pytest.raises(ValueError, match='changed since'):
        apply_project_labels(original + '\n', plan)
    for key, value in [('target_xml', '<Group/>'), ('candidate_sha256', 'bad'), ('labels_transferred', True),
                       ('edits', [edit(text='injected')])]:
        with pytest.raises(ValueError, match='differs from'):
            apply_project_labels(original, {**plan, key: value})


def test_xml_guards():
    variants = [project().replace('<Installation', '<!DOCTYPE Installation [<!ENTITY x "bad">]><Installation', 1),
                project().replace('<TagsDLT x:keep="yes">', '<TagsDLT/><TagsDLT x:keep="yes">'),
                project().replace('<Project><Address>DLTTEXT</Address>', '<Project><Address>DLTTEXT</Address><Address>DLTTEXT</Address>'),
                '<Installation>']
    for value in variants:
        with pytest.raises(ValueError):
            plan_project_labels(value, GROUP, [edit()])


def test_candidate_size_limit_before_output(monkeypatch):
    from cbus_toolkit import dlt_project_labels
    original = project()
    monkeypatch.setattr(dlt_project_labels, 'MAX_XML_BYTES', len(original.encode('utf-8')) + 30)
    with pytest.raises(ValueError, match='Edited native project XML exceeds'):
        plan_project_labels(original, GROUP, [edit(text='X' * 1024)])
