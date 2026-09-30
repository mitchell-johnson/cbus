"""Independent preservation and replay checks for the bounded TEXT dialog."""
from copy import deepcopy
from dataclasses import replace
import json
from xml.dom import Node, minidom

import pytest

from cbus_toolkit.dlt_language_dialog import (apply_language_dialog, plan_language_dialog,
                                              show_language_dialog)
from cbus_toolkit.dlt_project_labels import show_project_labels
from test_dlt_project_labels import ACTION, GROUP, project, tag


def source(tags=None):
    return project(tags).replace('<Languages>',
        '<Languages><Language><ID>1</ID><TagValue>English</TagValue></Language>', 1)


def group_rows(xml):
    return show_project_labels(xml, GROUP)['labels']


def stored_row(xml, variant, language='1'):
    return next(row for row in group_rows(xml)
                if row['language_id'] == language and row['variant'] == str(variant))


def test_selected_text_update_preserves_every_other_dom_node_and_scalar_attribute():
    selected = tag(value='Before').replace('<TagDLT>', '<TagDLT x:mark="A&#10;B&#9;C&#13;D">', 1)
    selected = selected.replace('<TagValue>Before</TagValue>',
        '<TagValue x:mark="V&#10;W&#9;X&#13;Y"><![CDATA[Before]]><!--inside--><?inside keep?></TagValue>')
    selected = selected.replace('</TagDLT>', '<x:VendorOpaque flag="yes"/></TagDLT>')
    original = source(selected + tag('2', '1', 'FONT', 'Unselected long text is not truncated', 'font-oid'))
    original = original.replace('<Project>', '<Project x:attr="A&#10;B&#9;C&#13;D">')
    value = '& < > ]]>\t\r\n'
    plan = plan_language_dialog(original, GROUP, 1, 1, value)
    saved = apply_language_dialog(original, json.loads(json.dumps(plan.as_dict())))
    assert stored_row(saved, 1)['text'] == value
    assert stored_row(saved, 1)['oid'] == 'label-oid'
    assert stored_row(saved, 1, '2') == stored_row(original, 1, '2')
    documents = [minidom.parseString(xml) for xml in (original, saved)]
    for document in documents:
        selected_node = next(node for node in document.getElementsByTagName('TagDLT')
                             if node.getElementsByTagName('OID')[0].firstChild.data == 'label-oid')
        field = selected_node.getElementsByTagName('TagValue')[0]
        for child in list(field.childNodes):
            if child.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
                field.removeChild(child)
        assert selected_node.getAttribute('x:mark') == 'A\nB\tC\rD'
        assert field.getAttribute('x:mark') == 'V\nW\tX\rY'
    assert documents[0].toxml() == documents[1].toxml()
    fragment = minidom.parseString(plan.target_xml)
    assert fragment.documentElement.getAttribute('xmlns:x') == 'urn:other'


def test_exact_one_precedes_legacy_zero_even_when_unused_zero_is_nontext():
    original = source(tag(variant='0', kind='FONT', value='opaque font', oid='legacy') + tag(oid='exact'))
    assert show_language_dialog(original, GROUP, 1)['flavours'][0]['stored']['oid'] == 'exact'
    saved = apply_language_dialog(original, plan_language_dialog(original, GROUP, 1, 1, 'Changed'))
    assert stored_row(saved, 0) == stored_row(original, 0)
    assert stored_row(saved, 1)['oid'] == 'exact'


def test_finalization_updates_legacy_zero_deletes_empty_and_normalizes_unedited_four():
    original = source(tag(variant='0', value='L' * 21, oid='legacy') +
                      tag(variant='2', value='', oid='empty') +
                      tag(variant='4', value='F' * 21, oid='fourth') +
                      tag('2', '2', 'ICON', 'opaque other language', 'icon'))
    plan = plan_language_dialog(original, GROUP, 1, 3, '')
    saved = apply_language_dialog(original, plan)
    assert [(r['variant'], r['text'], r['oid']) for r in group_rows(saved) if r['language_id'] == '1'] == [
        ('0', 'L' * 20, 'legacy'), ('4', 'F' * 20, 'fourth'), ('3', '<Default>', None)]
    assert [row['operation'] for row in plan.as_dict()['effects']] == ['update', 'delete', 'create', 'update']
    assert stored_row(saved, 2, '2') == stored_row(original, 2, '2')


def test_deleted_empty_exact_one_exposes_retained_legacy_zero_only_on_next_initialization():
    original = source(tag(variant='0', value='Legacy returns', oid='legacy') +
                      tag(variant='1', value='', oid='exact'))
    plan = plan_language_dialog(original, GROUP, 1, 2, 'Alternate')
    payload = plan.as_dict()
    assert payload['dialog_after'][0]['text'] == ''
    assert payload['effects'][0]['operation'] == 'delete'
    saved = apply_language_dialog(original, plan)
    assert stored_row(saved, 0) == stored_row(original, 0)
    fresh = show_language_dialog(saved, GROUP, 1)
    assert fresh['flavours'][0]['text'] == 'Legacy returns'
    assert fresh['flavours'][0]['initialization_provenance'] == 'saved-legacy-flavour-0'


@pytest.mark.parametrize('input_text', ['A' * 20 + '\u0100', 'A' * 20 + '😀'])
def test_confirmation_checks_full_input_even_when_nonlatin_suffix_is_discarded(input_text):
    original = source(tag())
    with pytest.raises(ValueError, match='confirmation'):
        plan_language_dialog(original, GROUP, 1, 1, input_text)
    plan = plan_language_dialog(original, GROUP, 1, 1, input_text, confirm_non_latin1=True)
    assert stored_row(plan.candidate_xml, 1)['text'] == 'A' * 20
    assert plan.as_dict()['input_confirmation'] == {
        'non_latin1_found_before_truncation': True, 'confirmed': True}


def test_utf16_prefix_counts_pairs_and_refuses_partial_pair_without_replacement():
    original = source(tag())
    retained = 'A' * 18 + '😀'
    plan = plan_language_dialog(original, GROUP, 1, 1, retained + 'suffix', confirm_non_latin1=True)
    assert stored_row(apply_language_dialog(original, plan), 1)['text'] == retained
    with pytest.raises(ValueError, match='splits a surrogate pair'):
        plan_language_dialog(original, GROUP, 1, 1, 'A' * 19 + '😀', confirm_non_latin1=True)
    with pytest.raises(ValueError, match='splits a surrogate pair'):
        show_language_dialog(source(tag(value='A' * 19 + '😀')), GROUP, 1)


def test_existing_unicode_is_not_mistaken_for_new_unconfirmed_text_input():
    original = source(tag(value='界' * 21) + tag(variant='2', value='Second', oid='second'))
    plan = plan_language_dialog(original, GROUP, 1, 2, 'ASCII')
    assert stored_row(plan.candidate_xml, 1)['text'] == '界' * 20
    assert plan.as_dict()['input_confirmation']['non_latin1_found_before_truncation'] is False


@pytest.mark.parametrize('mutation', [
    lambda text: text.replace('<Language><ID>1</ID>', '<Language><ID>01</ID>', 1),
    lambda text: text.replace('<Languages>', '<Languages><Language><ID>1</ID><TagValue>Duplicate</TagValue></Language>', 1),
    lambda text: text.replace('<LanguageID>1</LanguageID>', '<LanguageID>01</LanguageID>'),
    lambda text: text.replace('<FlavourID>1</FlavourID>', '<FlavourID>01</FlavourID>'),
    lambda text: text.replace('<TagsDLT x:keep="yes">', '<TagsDLT x:keep="yes">' + tag(oid='duplicate'), 1),
    lambda text: text.replace('</Project>', '<Network><Address>0254</Address></Network></Project>', 1),
    lambda text: text.replace('</Network>', '<Application><Address>056</Address></Application></Network>', 1),
    lambda text: text.replace('<Group data="keep">', '<Group><Address>01</Address></Group><Group data="keep">', 1),
])
def test_selected_identity_aliases_and_duplicates_refused(mutation):
    with pytest.raises(ValueError):
        plan_language_dialog(mutation(source(tag())), GROUP, 1, 1, 'After')


def test_level_address_alias_rejected_without_using_value_attribute_as_identity():
    original = source(tag())
    saved = plan_language_dialog(original, ACTION, 1, 1, 'Action label').candidate_xml
    assert '<Level Value="43">' in saved
    forged = original.replace('<Level Value="43">', '<Level><Address>042</Address></Level><Level Value="43">')
    with pytest.raises(ValueError, match='alias'):
        plan_language_dialog(forged, ACTION, 1, 1, 'Action label')


def test_default_marker_does_not_substitute_for_positive_language_definition():
    original = project(tag()).replace('<TagValue>2</TagValue>', '<TagValue>1</TagValue>', 1)
    with pytest.raises(ValueError, match='existing selected network language'):
        plan_language_dialog(original, GROUP, 1, 1, 'After')


@pytest.mark.parametrize('mutate', [
    lambda p: p.update(changed=1),
    lambda p: p.update(saved=0),
    lambda p: p.update(labels_transferred=0),
    lambda p: p['requested'].update(language=True),
    lambda p: p['requested'].update(variant=1.0),
    lambda p: p['requested'].update(confirm_non_latin1=0),
    lambda p: p['effects'][0].update(variant=True),
    lambda p: p['dialog_after'][0].update(present=1),
    lambda p: p['finalization'].update(selected_language=1.0),
    lambda p: p.update(extra='unrecognized'),
])
def test_saved_plan_metadata_requires_exact_json_types_and_shape(mutate):
    original = source(tag())
    forged = deepcopy(plan_language_dialog(original, GROUP, 1, 1, 'After').as_dict())
    mutate(forged)
    with pytest.raises(ValueError):
        apply_language_dialog(original, forged)


def test_candidate_field_is_not_trusted_and_plan_views_cannot_mutate_saved_action():
    original = source(tag())
    plan = plan_language_dialog(original, GROUP, 1, 1, 'After')
    altered_view = plan.as_dict()
    altered_view['requested']['text'] = 'Injected'
    forged_object = replace(plan, candidate_xml='<Installation/>')
    assert apply_language_dialog(original, forged_object) == plan.candidate_xml
    assert stored_row(apply_language_dialog(original, plan), 1)['text'] == 'After'
    with pytest.raises(ValueError, match='changed since'):
        apply_language_dialog(original + '\n', plan)
