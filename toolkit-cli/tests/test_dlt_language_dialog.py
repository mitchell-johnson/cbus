"""Classic TEXT-button action, whole-language finalization and source replay."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from cbus_toolkit.dlt_language_dialog import (DltLanguageDialogPlan, apply_language_dialog,
                                             plan_language_dialog, show_language_dialog)
from cbus_toolkit.dlt_project_labels import show_project_labels
from test_dlt_project_labels import ACTION, GROUP, project, tag


ORIGINAL = json.loads((Path(__file__).resolve().parents[1] /
    'research/fixtures/classic-dlt-language-dialog-original.json').read_text())
ORIGINAL_TEXT_CASES = [row for row in ORIGINAL['observations'] if not row['deferred']]


def source(tags=None):
    return project(tags).replace('<Languages>', '<Languages><Language><ID>1</ID><TagValue>English</TagValue></Language>', 1)


def labels(xml, target=GROUP):
    return show_project_labels(xml, target)['labels']


def test_whole_selected_language_finalization_and_distinct_empty_action():
    original = source(tag(variant='0', value='legacy', oid='old-zero') +
                      tag(variant='2', value='', oid='empty-second') +
                      tag(variant='4', value='12345678901234567890tail', oid='long-fourth') +
                      tag(language='2', kind='FONT', value='unrelated image', oid='font-other'))
    plan = plan_language_dialog(original, GROUP, 1, 3, '')
    result = plan.as_dict()
    assert [row['operation'] for row in result['effects']] == ['preserve', 'delete', 'create', 'update']
    assert result['dialog_after'][2]['text'] == '<Default>'
    assert result['before']['flavours'][0]['initialization_provenance'] == 'saved-legacy-flavour-0'
    assert result['finalization']['supplied_model'] is None
    saved = apply_language_dialog(original, json.loads(json.dumps(result)))
    assert [(row['language_id'], row['variant'], row['text'], row['oid']) for row in labels(saved)] == [
        ('1', '0', 'legacy', 'old-zero'), ('1', '4', '12345678901234567890', 'long-fourth'),
        ('2', '1', 'unrelated image', 'font-other'), ('1', '3', '<Default>', None)]
    assert plan.target_xml.startswith('<Group')


def test_selected_legacy_zero_updates_in_place_and_exact_one_takes_precedence():
    original = source(tag(variant='0', value='old', oid='legacy'))
    saved = apply_language_dialog(original, plan_language_dialog(original, GROUP, 1, 1, 'new'))
    assert labels(saved) == [{'oid': 'legacy', 'language_id': '1', 'variant': '0', 'tag_type': 'TEXT', 'text': 'new'}]
    original = source(tag(variant='0', value='legacy untouched', oid='legacy') + tag(value='exact one', oid='one'))
    saved = apply_language_dialog(original, plan_language_dialog(original, GROUP, 1, 1, 'new one'))
    assert [row['text'] for row in labels(saved)] == ['legacy untouched', 'new one']
    assert [row['oid'] for row in labels(saved)] == ['legacy', 'one']


def test_deleted_exact_first_does_not_rewrite_shadowed_legacy_and_reopens_it():
    original = source(tag(variant='0', value='legacy restored on reload', oid='legacy') + tag(value='', oid='empty-one'))
    plan = plan_language_dialog(original, GROUP, 1, 2, 'second')
    assert plan.as_dict()['dialog_after'][0]['text'] == ''
    saved = apply_language_dialog(original, plan)
    assert labels(saved)[0]['variant'] == '0'
    reopened = show_language_dialog(saved, GROUP, 1)
    assert reopened['flavours'][0]['initialization_provenance'] == 'saved-legacy-flavour-0'
    assert reopened['flavours'][0]['text'] == 'legacy restored on r'


def test_missing_first_requires_explicit_owner_context_unless_overwritten():
    original = source('')
    shown = show_language_dialog(original, GROUP, 1)
    assert shown['default_representation_required'] is True
    assert shown['flavours'][0]['present'] is True and shown['flavours'][0]['text'] is None
    with pytest.raises(ValueError, match='owner_default_representation'):
        plan_language_dialog(original, GROUP, 1, 2, 'second')
    plan = plan_language_dialog(original, GROUP, 1, 1, 'first')
    assert plan.as_dict()['unobserved_default_overwritten'] is True
    assert plan.as_dict()['before']['flavours'][0]['text'] is None
    assert labels(apply_language_dialog(original, plan))[0]['text'] == 'first'
    plan = plan_language_dialog(original, GROUP, 1, 2, 'second',
                                owner_default_representation='1 - Owner display representation')
    assert [row['text'] for row in labels(plan.candidate_xml)] == ['1 - Owner display re', 'second']
    assert 'caller-supplied' in plan.as_dict()['default_representation_provenance']
    empty_default = plan_language_dialog(original, GROUP, 1, 2, 'second', owner_default_representation='')
    assert [row['variant'] for row in labels(empty_default.candidate_xml)] == ['2']


def test_empty_and_whitespace_inputs_follow_distinct_source_semantics():
    original = source(tag(value=''))
    assert labels(plan_language_dialog(original, GROUP, 1, 1, '').candidate_xml)[0]['text'] == '<Default>'
    assert labels(plan_language_dialog(original, GROUP, 1, 1, ' ').candidate_xml)[0]['text'] == ' '
    assert labels(plan_language_dialog(original, GROUP, 1, 1, '\t\n\r').candidate_xml)[0]['text'] == '\t\n\r'


@pytest.mark.parametrize('value,expected', [('café', 'café'), ('x' * 21, 'x' * 20),
                                          ('😀' * 11, '😀' * 10), ('x' * 18 + '😀z', 'x' * 18 + '😀')])
def test_original_prefix_uses_utf16_units(value, expected):
    plan = plan_language_dialog(source(), GROUP, 1, 1, value, confirm_non_latin1=True)
    assert labels(plan.candidate_xml)[0]['text'] == expected


def test_full_explicit_input_confirmation_precedes_truncation_only_for_user_input():
    original = source(tag(value='existing 漢字'))
    with pytest.raises(ValueError, match='confirmation'):
        plan_language_dialog(original, GROUP, 1, 2, 'x' * 20 + '漢')
    plan = plan_language_dialog(original, GROUP, 1, 2, 'x' * 20 + '漢', confirm_non_latin1=True)
    assert plan.as_dict()['input_confirmation'] == {'non_latin1_found_before_truncation': True, 'confirmed': True}
    assert [row['text'] for row in labels(plan.candidate_xml)] == ['existing 漢字', 'x' * 20]
    assert plan_language_dialog(original, GROUP, 1, 2, 'ASCII').as_dict()['input_confirmation'][
        'non_latin1_found_before_truncation'] is False


@pytest.mark.parametrize('where', ['input', 'existing', 'owner'])
def test_split_surrogate_prefix_refused_before_xml_output(where):
    bad_prefix = 'x' * 19 + '😀'
    with pytest.raises(ValueError, match='splits a surrogate pair'):
        if where == 'input':
            plan_language_dialog(source(), GROUP, 1, 1, bad_prefix, confirm_non_latin1=True)
        elif where == 'existing':
            plan_language_dialog(source(tag(value=bad_prefix)), GROUP, 1, 2, 'other')
        else:
            plan_language_dialog(source(''), GROUP, 1, 2, 'other', owner_default_representation=bad_prefix)


def test_trigger_level_is_independent_of_its_group_and_value_attribute():
    original = source()
    plan = plan_language_dialog(original, ACTION, 1, 1, 'Action')
    saved = apply_language_dialog(original, plan)
    assert labels(saved, ACTION)[0]['text'] == 'Action'
    assert labels(saved, '//DLTTEXT/254/202/7')[0]['text'] == 'trigger group'
    assert '<Level Value="43">' in saved


@pytest.mark.parametrize('language', [0, 15, 63, 117, 202, 255, True, '1'])
def test_language_scope_is_known_existing_and_text_capable(language):
    with pytest.raises(ValueError):
        plan_language_dialog(source(), GROUP, language, 1, 'value')


def test_missing_definition_and_involved_nontext_fail_closed():
    with pytest.raises(ValueError, match='existing selected network language'):
        plan_language_dialog(project(), GROUP, 1, 1, 'value')
    for kind in ('ICON', 'FONT', 'DYNAMIC', 'unknown', 'text'):
        with pytest.raises(ValueError, match='not TEXT'):
            plan_language_dialog(source(tag(variant='2', kind=kind)), GROUP, 1, 1, 'value')
    # A shadowed legacy0 and another language never enter this fresh model.
    original = source(tag(variant='0', kind='DYNAMIC', value='opaque') + tag(value='one', oid='one') +
                      tag(language='2', kind='FONT', value='opaque', oid='foreign'))
    saved = plan_language_dialog(original, GROUP, 1, 1, 'new').candidate_xml
    assert labels(saved)[0]['tag_type'] == 'DYNAMIC' and labels(saved)[2]['tag_type'] == 'FONT'


def test_plan_is_immutable_source_bound_type_strict_and_noop_byte_exact():
    original = source()
    plan = plan_language_dialog(original, GROUP, 1, 1, 'Before')
    assert plan.candidate_xml == original and plan.as_dict()['changed'] is False
    with pytest.raises(FrozenInstanceError):
        plan.candidate_xml = 'forged'
    copied = plan.as_dict()
    copied['requested']['text'] = 'forged'
    assert plan.as_dict()['requested']['text'] == 'Before'
    for key, value in (('changed', 0), ('saved', 0), ('target_xml', '<Group/>'), ('extra', True)):
        changed = plan.as_dict()
        changed[key] = value
        with pytest.raises(ValueError, match='canonical'):
            apply_language_dialog(original, changed)
    forged_candidate = replace(plan, candidate_xml='forged XML')
    assert apply_language_dialog(original, forged_candidate) == original
    with pytest.raises(ValueError, match='changed since'):
        apply_language_dialog(original + '\n', plan)
    with pytest.raises(ValueError, match='boolean'):
        plan_language_dialog(original, GROUP, 1, 1, 'value', confirm_non_latin1=1)
    assert isinstance(plan, DltLanguageDialogPlan)


@pytest.mark.parametrize('value', ['\x00', '\x01', '\uffff', '\ud800', 'x' * 1025, None])
def test_invalid_xml_and_local_input_bound(value):
    with pytest.raises(ValueError):
        plan_language_dialog(source(), GROUP, 1, 1, value)


@pytest.mark.parametrize('row', ORIGINAL_TEXT_CASES, ids=[
    f"{index}-{row['target']}-confirmed-{row['confirm_non_latin1']}"
    for index, row in enumerate(ORIGINAL_TEXT_CASES)])
def test_text_action_matches_independent_original_button_replay(row):
    assert len(ORIGINAL_TEXT_CASES) == 14
    target = GROUP if row['target'] == 'group' else ACTION
    kwargs = {'confirm_non_latin1': row['confirm_non_latin1']}
    if not row['result']['accepted']:
        with pytest.raises(ValueError, match='confirmation'):
            plan_language_dialog(source(), target, 1, 1, row['input'], **kwargs)
    elif any(0xD800 <= ord(character) <= 0xDFFF for character in row['result']['tag_value']):
        # Source's accepted UTF-16 string cannot be represented in XML. The
        # bounded editor intentionally refuses rather than inventing bytes.
        with pytest.raises(ValueError, match='splits a surrogate pair'):
            plan_language_dialog(source(), target, 1, 1, row['input'], **kwargs)
    else:
        plan = plan_language_dialog(source(), target, 1, 1, row['input'], **kwargs)
        assert labels(plan.candidate_xml, target)[0]['text'] == row['result']['tag_value']
        assert labels(plan.candidate_xml, target)[0]['tag_type'] == 'TEXT'
        assert row['result']['tag_type'] == 0
        assert plan.as_dict()['finalization']['supplied_model'] == row['result']['calls'][0]['supplied_model']
        assert plan.as_dict()['input_confirmation']['non_latin1_found_before_truncation'] == bool(
            row['result']['unicode_prompts'])
