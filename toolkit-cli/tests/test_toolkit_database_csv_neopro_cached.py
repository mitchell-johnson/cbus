"""Literal cached-v2 NeoPro identity/provider contracts and offline public CLI.

Synthetic detached records only. These subprocess cases also run against a
fresh installed wheel and never provision original software or an endpoint.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.toolkit_database_csv import COLUMNS
from cbus_toolkit.toolkit_database_csv_native import project_native_xml_unit
from cbus_toolkit.toolkit_database_csv_projection import (
    CSVAreaObservation, IDENTITY_PROFILE, PROFILE, loads_cached_projection,
    parse_cached_projection, project_cached_csv_unit,
)
from tests.test_toolkit_database_csv_neopro import FIRST_PATH, invoke, one_family, xml
from tests.test_toolkit_database_csv_projection import projection_input


ROOT = Path(__file__).resolve().parents[2]
VECTOR = ROOT / 'rust/testdata/vectors/toolkit_database_csv_neopro_cached_v2.json'
DATA = json.loads(VECTOR.read_text(encoding='utf-8'))
TYPES = ('KEYB2', 'KEYB4', 'KEYB6')


def value(kind='KEYB2', mask=255):
    source = deepcopy(DATA['fixture'])
    source['unit']['unit_type'] = kind
    source['unit']['group_identities'] = DATA['mask_cases'][mask]['group_identities'][:]
    source['application_context']['secondary_mask'] = mask
    return source


def primary(source):
    return next(app for app in source['application_context']['applications']
                if app['identity'] == source['application_context']['primary_identity'])


def remove_group(source, identity):
    source['group_cache'] = [g for g in source['group_cache'] if g['identity'] != identity]
    for app in source['application_context']['applications']:
        app['group_identities'] = [i for i in app['group_identities'] if i != identity]


def provider_input(case, kind='KEYB2'):
    source = value(kind)
    source['area_observations'] = deepcopy(case['observations'])
    if case.get('remove_primary_255'):
        remove_group(source, 'primary-255')
    source['group_save'] = deepcopy(case.get('group_save'))
    return source


def expected_rows(case, kind):
    return tuple(row.replace(',KEYB2,', ',' + kind + ',') for row in case['rows_keyb2'])


class NeoProCachedIdentityMatrixTests(unittest.TestCase):
    def test_all_three_families_all_256_masks_match_literal_rows_and_membership(self):
        self.assertEqual(tuple(DATA['columns']), COLUMNS)
        self.assertEqual(len(DATA['mask_cases']), 256)
        for kind in TYPES:
            for case in DATA['mask_cases']:
                with self.subTest(kind=kind, mask=case['mask']):
                    source = value(kind, case['mask'])
                    before = deepcopy(source)
                    result = loads_cached_projection(json.dumps(source, ensure_ascii=False).encode(), columns=COLUMNS)
                    expected = case['csv_utf8_keyb2'].replace(',KEYB2,', ',' + kind + ',').encode()
                    self.assertTrue(result.complete)
                    self.assertEqual(result.selected_class, 'T' + kind)
                    self.assertEqual(result.report.utf8_bytes, expected)
                    self.assertEqual(result.unit.group_identities, tuple(case['group_identities']))
                    self.assertEqual(result.area_identity, 'primary-255')
                    self.assertEqual(result.raw_area, '255')
                    self.assertEqual([g.identity for g in result.groups], [g['identity'] for g in source['group_cache']])
                    tags = {group.identity: group.tag for group in result.groups}
                    self.assertEqual([tags[identity] for identity in result.unit.group_identities], case['group_tags'])
                    self.assertEqual([e.event for e in result.events], DATA['provider_cases'][0]['events'])
                    refs = {group.identity: group.references for group in result.groups}
                    self.assertEqual(refs['primary-255'], ('unrelated-unit', 'cached-neopro-unit'))
                    self.assertEqual(refs['secondary-255'], ('unrelated-unit',))
                    self.assertEqual(source, before)

    def test_all_provider_cases_have_literal_order_partial_state_and_primary_references(self):
        for kind in TYPES:
            for case in DATA['provider_cases']:
                with self.subTest(kind=kind, provider=case['id']):
                    source = provider_input(case, kind)
                    before = deepcopy(source)
                    result = parse_cached_projection(source, columns=COLUMNS)
                    self.assertEqual(result.complete, case['complete'])
                    self.assertEqual(result.area_identity, case['area_identity'])
                    self.assertEqual(result.raw_area, case['raw_area'])
                    self.assertEqual(result.stop_reason, case.get('stop_reason'))
                    self.assertEqual(result.rows, expected_rows(case, kind))
                    self.assertEqual([e.event for e in result.events], case['events'])
                    expected_events = deepcopy(case['event_records'])
                    expected_events[0]['selected_class'] = 'T' + kind
                    self.assertEqual([e.as_dict() for e in result.events], expected_events)
                    self.assertEqual(result.as_dict()['format'], IDENTITY_PROFILE)
                    self.assertEqual(result.as_dict()['native_mutation_performed'], False)
                    self.assertEqual(source, before)
                    groups = {group.identity: group for group in result.groups}
                    self.assertEqual(groups['secondary-255'].references, ('unrelated-unit',))
                    if case.get('remove_primary_255'):
                        created = groups['created-255']
                        self.assertEqual((created.address, created.tag, created.oid), (255, '<Unused>', 'OID-created-255'))
                        self.assertEqual(created.references, ('cached-neopro-unit',) if case['complete'] else ())
                        membership = next(app.group_identities for app in result.application_context.applications
                                          if app.identity == 'primary-app')
                        self.assertIn('created-255', membership)
                    if result.area_identity is not None:
                        self.assertIn('cached-neopro-unit', groups[result.area_identity].references)
                    if case['id'] == 'moves-12-to-13':
                        self.assertEqual(groups['primary-12'].references, ())
                        self.assertEqual([dict(e.fields)['previous'] for e in result.events if e.event == 'area_reference'], [None, 'primary-12'])


def test_cached_v2_vector_binds_retained_source_facts_without_new_original_execution():
    evidence = DATA['source_evidence']
    for path_key, digest_key in [('legacy_neopro_vector', 'legacy_neopro_vector_sha256'),
                                 ('cached_provider_review', 'cached_provider_review_sha256')]:
        assert hashlib.sha256((ROOT / evidence[path_key]).read_bytes()).hexdigest() == evidence[digest_key]
    assert evidence['original_instructions_executed'] is False
    assert evidence['fresh_original_execution'] is False
    assert any(name.endswith('TCBusInputUnit.GetAreaIfAvailable') for name in evidence['method_spans'])


@pytest.mark.parametrize('kind', TYPES)
def test_identity_not_cache_order_controls_area_even_when_column_is_omitted(kind):
    source = value(kind)
    source['group_cache'].reverse()
    source['application_context']['applications'].reverse()
    result = parse_cached_projection(source, columns=('address',))
    assert result.rows == ('Unit Address,', '21,')
    assert result.area_identity == 'primary-255'
    assert [event.event for event in result.events].count('area_load') == 2
    assert [g.identity for g in result.groups] == [g['identity'] for g in source['group_cache']]


@pytest.mark.parametrize('kind', TYPES)
@pytest.mark.parametrize('mode', ('unused', 'same'))
def test_unused_and_same_secondary_identity_are_explicit(kind, mode):
    source = value(kind, 0 if mode == 'unused' else 255)
    source['group_cache'] = [g for g in source['group_cache'] if g['identity'].startswith('primary-')]
    source['application_context']['applications'] = [primary(source)]
    source['application_context']['secondary_identity'] = None if mode == 'unused' else 'primary-app'
    source['unit']['secondary'] = '' if mode == 'unused' else 'Lighting'
    source['unit']['group_identities'] = DATA['mask_cases'][0]['group_identities'][:]
    result = parse_cached_projection(source, columns=COLUMNS)
    assert result.complete and result.area_identity == 'primary-255'
    assert result.csv_unit.secondary == source['unit']['secondary']


def damage(source, case):
    context = source['application_context']
    apps = context['applications']
    if case == 'missing-context': source.pop('application_context')
    elif case == 'missing-primary': context['primary_identity'] = 'absent'
    elif case == 'missing-secondary': context['secondary_identity'] = 'absent'
    elif case == 'tag-as-identity': context['primary_identity'] = 'Lighting'
    elif case == 'duplicate-identity': apps[0]['identity'] = apps[1]['identity']
    elif case == 'duplicate-address': apps[0]['address'] = apps[1]['address']
    elif case == 'wrong-primary-tag': source['unit']['primary'] = 'HVAC, west'
    elif case == 'wrong-secondary-tag': source['unit']['secondary'] = ''
    elif case == 'unbound-group': primary(source)['group_identities'].remove('primary-12')
    elif case == 'two-owners': primary(source)['group_identities'].append('secondary-12')
    elif case == 'missing-member': primary(source)['group_identities'].append('absent')
    elif case == 'duplicate-member': primary(source)['group_identities'].append('primary-12')
    elif case == 'ambiguous-area-address': next(g for g in source['group_cache'] if g['identity'] == 'primary-12')['address'] = 255
    elif case == 'wrong-block-owner': source['unit']['group_identities'][0] = 'primary-8'
    elif case == 'wrong-mask': context['secondary_mask'] = 0
    elif case == 'mask-overflow': context['secondary_mask'] = 256
    elif case == 'mask-bool': context['secondary_mask'] = True
    elif case == 'address-bool': apps[0]['address'] = True
    elif case == 'secondary-255': apps[0]['address'] = 255
    elif case == 'application-group-collision':
        app = primary(source)
        app['identity'] = context['primary_identity'] = 'primary-8'
    elif case == 'application-unit-collision':
        app = primary(source)
        app['identity'] = context['primary_identity'] = source['unit']['identity']
    elif case == 'unit-group-collision': source['unit']['identity'] = 'primary-8'
    elif case == 'own-reference': source['group_cache'][0]['references'].append(source['unit']['identity'])
    elif case == 'extra-context': context['extra'] = True
    elif case == 'extra-application': apps[0]['extra'] = True
    elif case == 'extra-root': source['extra'] = True
    elif case == 'missing-provider': source['area_observations'].pop()
    elif case == 'provider-raw-domain': source['area_observations'][0]['raw'] = '42'
    elif case == 'provider-completion-type': source['area_observations'][0]['completed'] = 1
    elif case == 'unconsumed-save': source['group_save'] = {'completed': True}
    elif case == 'missing-save': remove_group(source, 'primary-255')
    elif case == 'missing-non255': remove_group(source, 'primary-12');source['area_observations'][0]['raw'] = '12'
    elif case == 'creation-identity-collision':
        remove_group(source, 'primary-255')
        source['unit']['identity'] = 'created-255'
        source['group_save'] = {'completed': True}
    elif case in ('creation-oid-application-collision', 'creation-identity-application-collision'):
        app = primary(source)
        app['identity'] = context['primary_identity'] = (
            'OID-created-255' if case == 'creation-oid-application-collision' else 'created-255')
        remove_group(source, 'primary-255')
        source['group_save'] = {'completed': True}
    elif case == 'creation-oid-unit-collision':
        remove_group(source, 'primary-255')
        source['unit']['identity'] = 'OID-created-255'
        source['group_save'] = {'completed': True}
    elif case == 'creation-oid-group-identity-collision':
        group = source['group_cache'][0]
        old_identity = group['identity']
        group['identity'] = 'OID-created-255'
        for app in apps:
            app['group_identities'] = ['OID-created-255' if identity == old_identity else identity
                                       for identity in app['group_identities']]
        source['unit']['group_identities'] = ['OID-created-255' if identity == old_identity else identity
                                             for identity in source['unit']['group_identities']]
        remove_group(source, 'primary-255')
        source['group_save'] = {'completed': True}
    elif case == 'unsupported-firmware': source['unit']['firmware'] = '2.5.01'
    elif case == 'unsupported-family': source['unit']['unit_type'] = 'KEYH2'
    else: raise AssertionError(case)


REFUSALS = ('missing-context','missing-primary','missing-secondary','tag-as-identity',
    'duplicate-identity','duplicate-address','wrong-primary-tag','wrong-secondary-tag',
    'unbound-group','two-owners','missing-member','duplicate-member','ambiguous-area-address',
    'wrong-block-owner','wrong-mask','mask-overflow','mask-bool','address-bool','secondary-255',
    'application-group-collision','application-unit-collision','unit-group-collision','own-reference',
    'extra-context','extra-application','extra-root','missing-provider','provider-raw-domain',
    'provider-completion-type','unconsumed-save','missing-save','missing-non255',
    'creation-identity-collision','creation-oid-application-collision',
    'creation-identity-application-collision','creation-oid-unit-collision',
    'creation-oid-group-identity-collision','unsupported-firmware','unsupported-family')


@pytest.mark.parametrize('case', REFUSALS)
def test_missing_ambiguous_or_inconsistent_identity_is_refused_without_input_mutation(case):
    source = value()
    damage(source, case)
    before = deepcopy(source)
    with pytest.raises(ValueError):
        loads_cached_projection(json.dumps(source).encode(), columns=COLUMNS)
    assert source == before


@pytest.mark.parametrize('case', ('creation-oid-application-collision', 'creation-identity-application-collision',
                                'creation-oid-unit-collision', 'creation-oid-group-identity-collision'))
def test_created_area_cross_role_collision_has_no_partial_or_mutated_cache(case):
    source = value()
    damage(source, case)
    before = deepcopy(source)
    with pytest.raises(ValueError, match='created Area identity collides'):
        parse_cached_projection(source, columns=COLUMNS)
    assert source == before


def test_early_provider_stop_does_not_consume_later_group_save_outcome():
    source = value()
    source['area_observations'][0]['completed'] = False
    source['group_save'] = {'completed': True}
    before = deepcopy(source)
    result = parse_cached_projection(source, columns=COLUMNS)
    assert result.stop_reason == 'area_load_failed'
    assert [event.event for event in result.events] == ['factory_selected', 'area_load']
    assert result.group_save_required is False
    assert source == before


def test_cached_v2_json_duplicate_keys_and_depth_remain_bounded():
    raw = json.dumps(value())
    with pytest.raises(ValueError, match='duplicate'):
        loads_cached_projection(raw.replace('"primary_identity":', '"primary_identity": "primary-app", "primary_identity":', 1).encode(), columns=COLUMNS)
    with pytest.raises(ValueError, match='nesting'):
        loads_cached_projection(b'[[[[[[0]]]]]]', columns=COLUMNS)


def test_missing_primary_area_capacity_refuses_before_model_creation():
    source = value()
    remove_group(source, 'primary-255')
    occupied = {g['address'] for g in source['group_cache'] if g['identity'].startswith('primary-')}
    for address in range(255):
        if len(source['group_cache']) == 256: break
        if address in occupied: continue
        identity = 'extra-' + str(address)
        source['group_cache'].append({'identity':identity,'address':address,'tag':'Extra','oid':'OID-'+identity,'references':[]})
        primary(source)['group_identities'].append(identity)
    assert len(source['group_cache']) == 256
    source['group_save'] = {'completed': True}
    with pytest.raises(ValueError, match='capacity'):
        parse_cached_projection(source, columns=COLUMNS)


@pytest.mark.parametrize('kind', TYPES)
def test_native_derived_context_is_authoritative_and_typed_projection_requires_it(kind):
    native = project_native_xml_unit(xml(one_family(kind, mask=255)), FIRST_PATH, columns=COLUMNS)
    cached = native.cached
    context = cached.application_context
    assert context.primary_identity == '//NEOCSV/254/56'
    assert context.secondary_identity == '//NEOCSV/254/57'
    assert context.secondary_mask == 255
    groups = tuple(replace(g, references=()) for g in cached.groups)
    with pytest.raises(ValueError, match='explicit primary Application identity'):
        project_cached_csv_unit(cached.unit, group_cache=groups,
            area_observations=(CSVAreaObservation('255'),)*2, columns=COLUMNS)
    outcome = project_cached_csv_unit(cached.unit, group_cache=tuple(reversed(groups)),
        application_context=context, area_observations=(CSVAreaObservation('255'),)*2, columns=COLUMNS)
    assert outcome.report.utf8_bytes == cached.report.utf8_bytes
    assert outcome.area_identity == cached.area_identity


@pytest.mark.parametrize('kind', TYPES)
def test_native_emitted_application_oids_define_membership_instead_of_paths(kind):
    root = one_family(kind, mask=255)
    expected = DATA['native_application_oids']
    for app in root.find('Project/Network').findall('Application'):
        ET.SubElement(app, 'OID').text = expected[app.findtext('Address')]
    before = xml(root)
    result = project_native_xml_unit(before, FIRST_PATH, columns=COLUMNS)
    context = result.cached.application_context
    assert context.primary_identity == expected['56']
    assert context.secondary_identity == expected['57']
    primary_app = next(app for app in context.applications if app.identity == expected['56'])
    assert result.cached.area_identity in primary_app.group_identities
    assert result.cached.csv_unit.area == 'AreaPrimary'
    assert xml(root) == before


@pytest.mark.parametrize('case', ('duplicate', 'group-collision', 'unit-collision', 'malformed', 'extra-oid'))
def test_native_application_oid_identity_ambiguity_is_refused(case):
    root = one_family('KEYB2')
    apps = root.find('Project/Network').findall('Application')
    for app in apps:
        ET.SubElement(app, 'OID').text = DATA['native_application_oids'][app.findtext('Address')]
    primary_app = next(app for app in apps if app.findtext('Address') == '56')
    secondary_app = next(app for app in apps if app.findtext('Address') == '57')
    if case == 'duplicate': primary_app.find('OID').text = secondary_app.findtext('OID')
    elif case == 'group-collision': primary_app.find('OID').text = primary_app.find('Group/OID').text
    elif case == 'unit-collision': primary_app.find('OID').text = root.findtext('Project/Network/Unit/OID')
    elif case == 'malformed': primary_app.find('OID').text = 'not-an-oid'
    else: ET.SubElement(primary_app, 'OID').text = DATA['native_application_oids']['56']
    before = xml(root)
    with pytest.raises(ValueError):
        project_native_xml_unit(before, FIRST_PATH, columns=COLUMNS)
    assert xml(root) == before


def test_existing_v1_contract_and_output_remain_unchanged():
    source = projection_input()
    result = parse_cached_projection(source, columns=('address','area'))
    assert result.rows == ('Unit Address,Area,', '4,Area12,')
    assert result.as_dict()['format'] == PROFILE
    assert 'application_context' not in result.as_dict()


@pytest.mark.parametrize('kind', TYPES)
@pytest.mark.parametrize('mask', (0,1,85,170,255))
def test_public_cached_v2_cli_exports_exact_utf8_crlf_rows_without_side_effects(tmp_path, kind, mask):
    source = tmp_path / 'cached.json'
    source.write_text(json.dumps(value(kind,mask),ensure_ascii=False),encoding='utf-8')
    before = source.read_bytes()
    output = tmp_path / 'report.csv'
    code,result = invoke(['toolkit-database-csv',source,'--cached-projection','--output',output], artifact_dir=tmp_path)
    assert code == 0, result
    assert output.read_bytes() == DATA['mask_cases'][mask]['csv_utf8_keyb2'].replace(',KEYB2,',','+kind+',').encode()
    assert result['projection']['format'] == IDENTITY_PROFILE
    assert result['projection']['area_identity'] == 'primary-255'
    assert result['network_io_attempted'] is False
    assert result['source_modified'] is False
    assert source.read_bytes() == before


@pytest.mark.parametrize('case', DATA['provider_cases'], ids=lambda case: case['id'])
def test_public_cached_v2_cli_retains_provider_partial_evidence_and_never_creates_partial_output(tmp_path, case):
    source = tmp_path / 'cached.json'
    source.write_text(json.dumps(provider_input(case)),encoding='utf-8')
    before = source.read_bytes()
    output = tmp_path / 'report.csv'
    code,result = invoke(['toolkit-database-csv',source,'--cached-projection','--output',output], artifact_dir=tmp_path)
    assert code == (0 if case['complete'] else 1), result
    state = result if case['complete'] else result['toolkit_database_csv_evidence']
    projection = state['projection']
    assert projection['complete'] == case['complete']
    assert [e['event'] for e in projection['events']] == case['events']
    assert projection['area_identity'] == case['area_identity']
    assert state['network_io_attempted'] is False
    if case['complete']:
        assert output.read_bytes() == case['csv_utf8_keyb2'].encode()
    else:
        assert state['output_create_attempted'] is False
        assert not output.exists()
    assert source.read_bytes() == before


@pytest.mark.parametrize('case', ('missing-context','missing-primary','ambiguous-area-address','wrong-block-owner','wrong-mask','missing-save'))
def test_public_cached_v2_cli_identity_refusal_and_existing_output_are_atomic(tmp_path, case):
    source_value = value()
    damage(source_value,case)
    source = tmp_path / 'cached.json'
    source.write_text(json.dumps(source_value))
    before = source.read_bytes()
    output = tmp_path / 'never.csv'
    code,result = invoke(['toolkit-database-csv',source,'--cached-projection','--output',output], artifact_dir=tmp_path)
    assert code == 1
    assert result['toolkit_database_csv_evidence']['output_create_attempted'] is False
    assert result['toolkit_database_csv_evidence']['network_io_attempted'] is False
    assert not output.exists() and source.read_bytes() == before
    output.write_bytes(b'keep existing output\n')
    code,result = invoke(['toolkit-database-csv',source,'--cached-projection','--output',output], artifact_dir=tmp_path)
    assert code == 1
    assert output.read_bytes() == b'keep existing output\n'
    assert source.read_bytes() == before
