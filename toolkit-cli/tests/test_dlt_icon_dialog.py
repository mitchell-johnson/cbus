"""Original built-in ICON selection with preserving selected-language flush."""
from dataclasses import FrozenInstanceError, replace
import json
from xml.dom import minidom

import pytest

from cbus_toolkit.dlt_icon_dialog import (apply_icon_dialog, catalogue, plan_icon_dialog,
                                         show_icon_dialog)
from cbus_toolkit.dlt_project_labels import show_project_labels
from test_dlt_project_labels import ACTION, GROUP, project, tag


def record(variant='1', kind='ICON', value='5', oid='icon-oid'):
    return tag(language='202', variant=variant, kind=kind, value=value, oid=oid)


def source(tags=None):
    if tags is None:
        tags = record() + tag(language='2', kind='FONT', value='other image', oid='foreign-font')
    return project(tags).replace('<Languages>', '<Languages><Language><ID>202</ID><TagValue>Chinese</TagValue></Language>', 1)


def labels(text, target=GROUP):
    return show_project_labels(text, target)['labels']


def test_builtin_metadata_has_pinned_ids_without_rendering_claims():
    value = catalogue()
    assert value['language_id'] == 202 and value['icon_ids'] == list(range(1, 92))
    assert value['original_index_sha256'] == 'c6cca64deaed7bb5ad814b2aaf4c37b580396bf38c057aae8bd616fadfd26310'
    assert value['images_included'] is value['rendering_verified'] is False
    value['icon_ids'][0] = 999
    assert catalogue()['icon_ids'][0] == 1


@pytest.mark.parametrize('icon', range(1, 92))
def test_selection_persists_catalogue_value_not_zero_based_combo_index(icon):
    original = source()
    plan = plan_icon_dialog(original, GROUP, 202, 1, icon)
    saved = apply_icon_dialog(original, json.loads(json.dumps(plan.as_dict())))
    assert labels(saved)[0] == {'oid': 'icon-oid', 'language_id': '202', 'variant': '1',
                                'tag_type': 'ICON', 'text': str(icon)}
    assert labels(saved)[1]['tag_type'] == 'FONT'
    assert plan.as_dict()['requested'] == {'language': 202, 'variant': 1, 'icon_id': icon}


def test_fresh_missing_first_is_icon_empty_without_owner_display_dependency():
    original = source('')
    shown = show_icon_dialog(original, GROUP, 202)
    assert shown['flavours'][0] == {
        'variant': 1, 'present': True, 'tag_type': 'ICON', 'text': '', 'stored': None,
        'initialization_provenance': 'fresh-language-202-first-flavour-ICON-empty'}
    assert shown['scope']['owner_default_representation_consumed'] is False
    assert all(not row['present'] for row in shown['flavours'][1:])
    plan = plan_icon_dialog(original, GROUP, 202, 3, 91)
    assert [(row['variant'], row['text']) for row in labels(plan.candidate_xml)] == [('3', '91')]
    assert [row['operation'] for row in plan.as_dict()['effects']] == ['preserve', 'preserve', 'create', 'preserve']


def test_whole_language_flush_preserves_each_type_and_legacy_identity():
    original = source(record('0', 'TEXT', 'legacy primary', 'legacy') +
                      record('2', 'ICON', '', 'empty-icon') +
                      record('4', 'TEXT', '12345678901234567890tail', 'long-text') +
                      tag(language='2', kind='DYNAMIC', value='opaque dynamic', oid='foreign'))
    plan = plan_icon_dialog(original, GROUP, 202, 3, 7)
    assert [row['operation'] for row in plan.as_dict()['effects']] == ['preserve', 'delete', 'create', 'update']
    assert [(row['language_id'], row['variant'], row['tag_type'], row['text'], row['oid'])
            for row in labels(plan.candidate_xml)] == [
        ('202', '0', 'TEXT', 'legacy primary', 'legacy'),
        ('202', '4', 'TEXT', '12345678901234567890', 'long-text'),
        ('2', '1', 'DYNAMIC', 'opaque dynamic', 'foreign'), ('202', '3', 'ICON', '7', None)]
    assert plan.as_dict()['finalization']['supplied_model'] is None


def test_type_only_transition_and_untouched_icon_outside_builtin_catalogue():
    original = source(record(kind='TEXT', value='5') + record('2', 'ICON', '258', 'non-builtin') +
                      record('3', 'TEXT', '258', 'text-number'))
    plan = plan_icon_dialog(original, GROUP, 202, 1, 5)
    assert plan.as_dict()['effects'][0]['operation'] == 'update'
    assert [(row['tag_type'], row['text']) for row in labels(plan.candidate_xml)] == [
        ('ICON', '5'), ('ICON', '258'), ('TEXT', '258')]


def test_legacy_zero_selected_in_place_and_exact_first_precedence():
    original = source(record('0', 'TEXT', 'before', 'legacy'))
    saved = plan_icon_dialog(original, GROUP, 202, 1, 2).candidate_xml
    assert labels(saved) == [{'oid': 'legacy', 'language_id': '202', 'variant': '0', 'tag_type': 'ICON', 'text': '2'}]
    original = source(record('0', 'FONT', 'shadowed opaque', 'legacy') + record('1', 'TEXT', 'before', 'exact'))
    saved = plan_icon_dialog(original, GROUP, 202, 1, 3).candidate_xml
    assert [(row['oid'], row['tag_type'], row['text']) for row in labels(saved)] == [
        ('legacy', 'FONT', 'shadowed opaque'), ('exact', 'ICON', '3')]


def test_deleting_empty_exact_first_leaves_legacy_for_a_later_reload():
    original = source(record('0', 'ICON', '91', 'legacy') + record('1', 'TEXT', '', 'empty-exact'))
    plan = plan_icon_dialog(original, GROUP, 202, 2, 5)
    assert plan.as_dict()['dialog_after'][0]['text'] == ''
    assert plan.as_dict()['effects'][0]['operation'] == 'delete'
    reopened = show_icon_dialog(plan.candidate_xml, GROUP, 202)
    assert reopened['flavours'][0]['text'] == '91'
    assert reopened['flavours'][0]['stored']['variant'] == '0'


def test_existing_text_and_icon_both_use_20_utf16_units_without_unicode_prompt():
    original = source(record('1', 'TEXT', '😀' * 11, 'text') + record('2', 'ICON', 'x' * 21, 'opaque-icon'))
    plan = plan_icon_dialog(original, GROUP, 202, 3, 1)
    assert [(row['tag_type'], row['text']) for row in labels(plan.candidate_xml)] == [
        ('TEXT', '😀' * 10), ('ICON', 'x' * 20), ('ICON', '1')]
    assert len(plan.as_dict()['before']['initialization_normalizations']) == 2
    for kind in ('TEXT', 'ICON'):
        with pytest.raises(ValueError, match='splits a surrogate pair'):
            plan_icon_dialog(source(record(kind=kind, value='x' * 19 + '😀')), GROUP, 202, 2, 1)


def test_trigger_level_mutation_preserves_parent_group_and_value_attribute():
    original = source().replace(tag(value='action before', oid='action-tag'), record(kind='TEXT', value='action before', oid='action-tag'))
    saved = plan_icon_dialog(original, ACTION, 202, 1, 91).candidate_xml
    assert labels(saved, ACTION)[0]['tag_type'] == 'ICON'
    assert labels(saved, ACTION)[0]['text'] == '91'
    assert labels(saved, '//DLTTEXT/254/202/7')[0]['text'] == 'trigger group'
    assert '<Level Value="43">' in saved


def test_nonselected_dom_namespace_comments_attributes_and_cdata_preserved():
    original = source(record(kind='TEXT', value='before').replace('<TagValue>before</TagValue>',
        '<TagValue x:keep="A&#10;B&#9;C&#13;D"><![CDATA[before]]><!--value comment--><?keep value?></TagValue>'))
    saved = plan_icon_dialog(original, GROUP, 202, 1, 91).candidate_xml
    before_dom, after_dom = minidom.parseString(original), minidom.parseString(saved)
    for document in (before_dom, after_dom):
        group = document.getElementsByTagName('Group')[0]
        collection = next(n for n in group.childNodes if n.nodeType == n.ELEMENT_NODE and n.tagName == 'TagsDLT')
        group.removeChild(collection)
    assert before_dom.toxml() == after_dom.toxml()
    assert '<!--value comment-->' in saved and '<?keep value?>' in saved
    value = next(row for row in minidom.parseString(saved).getElementsByTagName('TagValue')
                 if row.hasAttribute('x:keep'))
    assert value.getAttribute('x:keep') == 'A\nB\tC\rD'


@pytest.mark.parametrize('language', [0, 1, 14, 64, 116, 201, 203, 255, True, '202'])
def test_only_original_predefined_language_is_admitted(language):
    with pytest.raises(ValueError):
        plan_icon_dialog(source(), GROUP, language, 1, 5)


@pytest.mark.parametrize('icon', [0, 92, 258, -1, True, '1', None])
def test_explicit_choice_requires_pinned_builtin_id(icon):
    with pytest.raises(ValueError, match='Built-in icon ID'):
        plan_icon_dialog(source(), GROUP, 202, 1, icon)


def test_missing_language_definition_and_ambiguous_ids_refused():
    with pytest.raises(ValueError, match='existing language 202'):
        plan_icon_dialog(project(record()), GROUP, 202, 1, 5)
    for original in (source().replace('<ID>202</ID>', '<ID>0202</ID>', 1),
                     source().replace('<Languages>', '<Languages><Language><ID>202</ID><TagValue>duplicate</TagValue></Language>', 1),
                     source(record().replace('<LanguageID>202</LanguageID>', '<LanguageID>0202</LanguageID>')),
                     source(record().replace('<FlavourID>1</FlavourID>', '<FlavourID>01</FlavourID>')),
                     source(record() + record(oid='duplicate')),
                     source().replace('<Group data="keep">', '<Group><Address>01</Address></Group><Group data="keep">', 1)):
        with pytest.raises(ValueError):
            plan_icon_dialog(original, GROUP, 202, 1, 5)


@pytest.mark.parametrize('kind', ['DYNAMIC', 'FONT', 'unknown', 'text', 'icon'])
def test_involved_unsupported_types_refused_even_when_explicitly_edited(kind):
    with pytest.raises(ValueError, match='canonical TEXT or ICON'):
        plan_icon_dialog(source(record(kind=kind)), GROUP, 202, 1, 5)


def test_frozen_plan_strict_source_hash_and_type_sensitive_replay():
    original = source()
    plan = plan_icon_dialog(original, GROUP, 202, 1, 5)
    assert plan.candidate_xml == original and plan.as_dict()['changed'] is False
    with pytest.raises(FrozenInstanceError):
        plan.candidate_xml = 'forged'
    assert apply_icon_dialog(original, replace(plan, candidate_xml='forged')) == original
    changed = plan.as_dict()
    changed['requested']['icon_id'] = 91
    assert plan.as_dict()['requested']['icon_id'] == 5
    for field, value in [('saved', 0), ('changed', 0), ('target_xml', '<Group/>'), ('extra', 1)]:
        forged = plan.as_dict()
        forged[field] = value
        with pytest.raises(ValueError, match='canonical'):
            apply_icon_dialog(original, forged)
    forged = plan.as_dict()
    forged['catalogue']['icon_ids'][0] = True
    with pytest.raises(ValueError, match='canonical'):
        apply_icon_dialog(original, forged)
    with pytest.raises(ValueError, match='changed since'):
        apply_icon_dialog(original + '\n', plan)


def test_candidate_xml_growth_obeys_own_read_bound(monkeypatch):
    from cbus_toolkit import dlt_icon_dialog as module
    from cbus_toolkit.dlt_project_labels import _parse, _serialize
    original = _serialize(_parse(source()))
    monkeypatch.setattr(module, 'MAX_XML_BYTES', len(original.encode('utf-8')))
    with pytest.raises(ValueError, match='exceeds the 16 MiB'):
        plan_icon_dialog(original, GROUP, 202, 1, 91)
