"""Independent ICON collection ordering, XML preservation and replay checks."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from xml.dom import Node, minidom

import pytest

from cbus_toolkit.dlt_icon_dialog import (apply_icon_dialog, catalogue, plan_icon_dialog,
                                         show_icon_dialog)
from cbus_toolkit.dlt_project_labels import show_project_labels
from test_dlt_project_labels import ACTION, GROUP, project, tag

ORIGINAL = json.loads((Path(__file__).resolve().parents[1] /
    'research/fixtures/classic-dlt-icon-dialog-original.json').read_text())
SELECTED_CASES = [row for row in ORIGINAL['observations']['icon_ok']
                  if not row['deferred'] and row['selected_index'] >= 0 and
                  row['item_integer_value'] in ORIGINAL['catalogue']['ordered_ids']]


def source(tags=''):
    return project(tags).replace('<Languages>',
        '<Languages><Language><ID>202</ID><TagValue>Icons</TagValue></Language>', 1)


def icon_tag(variant='1', kind='ICON', value='5', oid='icon-oid'):
    return tag('202', variant, kind, value, oid)


def labels(xml, target=GROUP):
    return show_project_labels(xml, target)['labels']


def selected(xml, target=GROUP):
    return [row for row in labels(xml, target) if row['language_id'] == '202']


@pytest.mark.parametrize('row', SELECTED_CASES)
def test_selected_action_matches_retained_original_button_receipt(row):
    # Only retained JSON is read: no original runtime or CPU probe is launched.
    target = GROUP if row['target'] == 'group' else ACTION
    variant = row['selected_index'] % 4 + 1
    original = source(icon_tag())
    plan = plan_icon_dialog(original, target, 202, variant, row['item_integer_value'])
    saved = apply_icon_dialog(original, plan)
    result = row['result']
    assert result['accepted'] is True and result['tag_type'] == 1
    assert result['tag_value'] == str(row['item_integer_value'])
    actual = next(label for label in selected(saved, target) if label['variant'] == str(variant))
    assert actual['tag_type'] == 'ICON' and actual['text'] == result['tag_value']
    assert result['calls'][-1] == {'operation': 'FinaliseLanguage', 'target': row['target'],
                                 'language': 202, 'supplied_model': None}
    assert plan.as_dict()['finalization']['selected_language'] == 202
    assert plan.as_dict()['finalization']['supplied_model'] is None
    assert plan.as_dict()['labels_transferred'] is False


def test_catalogue_is_bound_to_source_and_selection_uses_value_not_index():
    model = catalogue()
    assert model['icon_ids'] == ORIGINAL['catalogue']['ordered_ids']
    assert model['original_index_sha256'] == ORIGINAL['catalogue']['index']['sha256']
    assert model['images_included'] is False and model['rendering_verified'] is False
    skewed = next(row for row in SELECTED_CASES if row['selected_index'] == 42 and row['item_integer_value'] == 1)
    assert skewed['result']['tag_value'] == '1'
    synthetic = next(row for row in ORIGINAL['observations']['icon_ok'] if row['item_integer_value'] == 92)
    assert synthetic['result']['accepted'] is True
    assert 92 not in model['icon_ids']  # Button accepts a synthetic item the pinned palette never offers.
    with pytest.raises(ValueError):
        plan_icon_dialog(source(), GROUP, 202, 1, 92)


def test_fresh_202_missing_first_stays_empty_without_owner_display_dependency():
    original = source()
    shown = show_icon_dialog(original, GROUP, 202)
    first = shown['flavours'][0]
    assert first['present'] is True and first['tag_type'] == 'ICON' and first['text'] == ''
    plan = plan_icon_dialog(original, GROUP, 202, 3, 5)
    saved = apply_icon_dialog(original, plan)
    assert [(row['variant'], row['tag_type'], row['text']) for row in selected(saved)] == [('3', 'ICON', '5')]


def test_existing_text_202_converts_only_explicit_flavour_even_when_value_unchanged():
    original = source(icon_tag(kind='TEXT', value='5', oid='selected') +
                      icon_tag('2', kind='TEXT', value='258', oid='other'))
    plan = plan_icon_dialog(original, GROUP, 202, 1, 5)
    saved = apply_icon_dialog(original, plan)
    assert [(row['variant'], row['tag_type'], row['text'], row['oid']) for row in selected(saved)] == [
        ('1', 'ICON', '5', 'selected'), ('2', 'TEXT', '258', 'other')]
    assert plan.as_dict()['effects'][0]['operation'] == 'update'


def test_complete_selected_language_flush_retains_types_and_legacy_zero_identity():
    original = source(icon_tag('0', kind='TEXT', value='A' * 21, oid='legacy') +
                      icon_tag('2', value='', oid='empty') +
                      icon_tag('4', kind='TEXT', value='界' * 21, oid='fourth') +
                      tag('1', '1', 'FONT', 'opaque foreign language', 'foreign') +
                      icon_tag('5', kind='FONT', value='opaque out of range', oid='out-of-range'))
    plan = plan_icon_dialog(original, GROUP, 202, 3, 91)
    saved = apply_icon_dialog(original, plan)
    assert [(row['variant'], row['tag_type'], row['text'], row['oid']) for row in selected(saved)] == [
        ('0', 'TEXT', 'A' * 20, 'legacy'), ('4', 'TEXT', '界' * 20, 'fourth'),
        ('5', 'FONT', 'opaque out of range', 'out-of-range'), ('3', 'ICON', '91', None)]
    assert [row['operation'] for row in plan.as_dict()['effects']] == ['update', 'delete', 'create', 'update']
    assert next(row for row in labels(saved) if row['oid'] == 'foreign') == next(
        row for row in labels(original) if row['oid'] == 'foreign')


def test_exact_one_precedes_shadowed_legacy_and_deletion_exposes_it_only_on_reopen():
    original = source(icon_tag('0', value='258', oid='shadowed') + icon_tag(value='', oid='exact'))
    shown = show_icon_dialog(original, GROUP, 202)
    assert shown['flavours'][0]['stored']['oid'] == 'exact'
    saved = apply_icon_dialog(original, plan_icon_dialog(original, GROUP, 202, 2, 1))
    assert [(row['variant'], row['text'], row['oid']) for row in selected(saved)] == [
        ('0', '258', 'shadowed'), ('2', '1', None)]
    reopened = show_icon_dialog(saved, GROUP, 202)
    assert reopened['flavours'][0]['stored']['oid'] == 'shadowed'
    assert reopened['flavours'][0]['text'] == '258'


def test_shadowed_legacy_font_does_not_block_exact_first_icon_action():
    original = source(icon_tag('0', kind='FONT', value='opaque shadow', oid='shadowed') + icon_tag())
    saved = apply_icon_dialog(original, plan_icon_dialog(original, GROUP, 202, 1, 1))
    assert selected(saved)[0] == selected(original)[0]
    assert selected(saved)[1]['text'] == '1'


def test_icon_id_outside_palette_is_preserved_when_it_is_not_the_requested_choice():
    original = source(icon_tag(value='65535') + icon_tag('2', value='1', oid='second'))
    saved = apply_icon_dialog(original, plan_icon_dialog(original, GROUP, 202, 2, 2))
    assert selected(saved)[0] == selected(original)[0]


def test_noop_is_byte_identical_and_type_change_preserves_extension_dom():
    unchanged = source(icon_tag(value='5'))
    assert apply_icon_dialog(unchanged, plan_icon_dialog(unchanged, GROUP, 202, 1, 5)) == unchanged
    marked = icon_tag(kind='TEXT', value='old').replace('<TagDLT>', '<TagDLT x:a="A&#10;B&#9;C&#13;D">', 1)
    marked = marked.replace('<TagValue>old</TagValue>',
        '<TagValue x:a="A&#10;B"><![CDATA[old]]><!--inside--><?inside keep?></TagValue>')
    marked = marked.replace('<TagType>TEXT</TagType>', '<TagType x:t="keep">TEXT<!--type--></TagType>')
    marked = marked.replace('</TagDLT>', '<x:Opaque flag="yes"/></TagDLT>')
    original = source(marked)
    plan = plan_icon_dialog(original, GROUP, 202, 1, 5)
    saved = apply_icon_dialog(original, plan)
    documents = [minidom.parseString(xml) for xml in (original, saved)]
    for document in documents:
        chosen = next(node for node in document.getElementsByTagName('TagDLT')
                      if node.getElementsByTagName('OID')[0].firstChild.data == 'icon-oid')
        assert chosen.getAttribute('x:a') == 'A\nB\tC\rD'
        for name in ('TagType', 'TagValue'):
            field = chosen.getElementsByTagName(name)[0]
            for child in list(field.childNodes):
                if child.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
                    field.removeChild(child)
    assert documents[0].toxml() == documents[1].toxml()
    assert minidom.parseString(plan.target_xml).documentElement.getAttribute('xmlns:x') == 'urn:other'


def test_action_address_identity_retains_independent_value_attribute_and_group():
    original = source()
    plan = plan_icon_dialog(original, ACTION, 202, 1, 91)
    saved = apply_icon_dialog(original, plan)
    assert '<Level Value="43">' in saved
    assert [(row['tag_type'], row['text']) for row in selected(saved, ACTION)] == [('ICON', '91')]
    assert labels(saved, '//DLTTEXT/254/202/7') == labels(original, '//DLTTEXT/254/202/7')


@pytest.mark.parametrize('mutation', [
    lambda xml: xml.replace('<Language><ID>202</ID>', '<Language><ID>0202</ID>', 1),
    lambda xml: xml.replace('<Languages>', '<Languages><Language><ID>202</ID><TagValue>Duplicate</TagValue></Language>', 1),
    lambda xml: xml.replace('<LanguageID>202</LanguageID>', '<LanguageID>0202</LanguageID>'),
    lambda xml: xml.replace('<FlavourID>1</FlavourID>', '<FlavourID>01</FlavourID>'),
    lambda xml: xml.replace('</Project>', '<Network><Address>0254</Address></Network></Project>', 1),
    lambda xml: xml.replace('</Network>', '<Application><Address>056</Address></Application></Network>', 1),
    lambda xml: xml.replace('<Group data="keep">', '<Group><Address>01</Address></Group><Group data="keep">', 1),
])
def test_identity_aliases_and_duplicate_definitions_are_rejected(mutation):
    with pytest.raises(ValueError):
        plan_icon_dialog(mutation(source(icon_tag())), GROUP, 202, 1, 5)


@pytest.mark.parametrize('language', [0, 1, 64, 201, 203, True, '202'])
def test_only_explicit_existing_icon_language_is_admitted(language):
    with pytest.raises(ValueError):
        plan_icon_dialog(source(), GROUP, language, 1, 5)


def test_network_default_marker_alone_does_not_create_icon_language():
    original = project('').replace('<TagValue>2</TagValue>', '<TagValue>202</TagValue>', 1)
    with pytest.raises(ValueError):
        plan_icon_dialog(original, GROUP, 202, 1, 5)


@pytest.mark.parametrize('choice', [0, 92, 65535, -1, True, 5.0, '5', None])
def test_explicit_choice_requires_pinned_palette_integer(choice):
    with pytest.raises(ValueError):
        plan_icon_dialog(source(), GROUP, 202, 1, choice)


@pytest.mark.parametrize('kind', ['DYNAMIC', 'FONT', 'text', 'icon', 'UNKNOWN'])
def test_consumed_image_cache_or_ambiguous_types_refused(kind):
    with pytest.raises(ValueError):
        plan_icon_dialog(source(icon_tag('2', kind=kind)), GROUP, 202, 1, 5)


def test_invalid_xml_utf16_normalization_is_refused_even_for_other_flavour():
    original = source(icon_tag(kind='TEXT', value='x' * 19 + '😀'))
    with pytest.raises(ValueError, match='surrogate'):
        plan_icon_dialog(original, GROUP, 202, 2, 5)


@pytest.mark.parametrize('mutation', [
    lambda plan: plan.update(changed=1), lambda plan: plan.update(saved=0),
    lambda plan: plan.update(labels_transferred=0),
    lambda plan: plan['requested'].update(language=202.0),
    lambda plan: plan['requested'].update(variant=True),
    lambda plan: plan['requested'].update(icon_id=5.0),
    lambda plan: plan['effects'][0].update(variant=True),
    lambda plan: plan.update(extra='injected'),
])
def test_saved_plan_binds_exact_typed_request_and_complete_derived_metadata(mutation):
    original = source(icon_tag(value='1'))
    forged = deepcopy(plan_icon_dialog(original, GROUP, 202, 1, 5).as_dict())
    mutation(forged)
    with pytest.raises(ValueError):
        apply_icon_dialog(original, forged)


def test_candidate_payload_is_rederived_and_source_staleness_is_rejected():
    original = source(icon_tag(value='1'))
    plan = plan_icon_dialog(original, GROUP, 202, 1, 5)
    forged = replace(plan, candidate_xml='<Installation/>')
    assert apply_icon_dialog(original, forged) == plan.candidate_xml
    copied = plan.as_dict()
    copied['requested']['icon_id'] = 91
    assert selected(apply_icon_dialog(original, plan))[0]['text'] == '5'
    with pytest.raises(ValueError):
        apply_icon_dialog(original + '\n', plan)
