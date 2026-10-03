"""Literal image-aware source phases and all category destination boundaries."""
from dataclasses import replace
import copy
import hashlib
import json
import os
import weakref
from pathlib import Path
from unittest.mock import patch
from xml.dom import minidom

import pytest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_global_programming import EdltGlobalProgramming, CATEGORIES
from cbus_toolkit.edlt_global_image_context import (
    check_global_image_context, resolve_global_image_context, project_graph,
    target_preservation_baseline)
from cbus_toolkit.edlt_scene_label_images import parse_project_images, load_decoded_dltp_index
from tests.test_edlt_global_programming import fixture
from tests.test_edlt_scene_label_images import bmp

ROOT = Path(__file__).resolve().parents[1]
VECTOR_PATH = ROOT / 'research/fixtures/edlt-global-image-vectors.json'
VECTOR_HASH = 'dff2e94a56707a2c2a27c4396a3427209d14788e493485ba879a46c5d4b74dd6'


def vectors():
    raw = VECTOR_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == VECTOR_HASH
    return json.loads(raw)


def provider(*, empty=False):
    f = vectors()['fixture']; prefix = 'empty_' if empty else ''
    return parse_project_images(f[prefix + 'project_images_raw'].encode(),
        expected_sha256=f[prefix + 'project_images_sha256'])


def prepared(*, xml=None, images=True, empty=False):
    e = EdltGlobalProgramming(fixture()); f = vectors()['fixture']
    return e, e.prepare_project_source(f['project_xml'] if xml is None else xml,
        f['source_unit'], project_images=provider(empty=empty) if images else None)


def changed_xml(transform):
    doc = minidom.parseString(vectors()['fixture']['project_xml'])
    transform(doc)
    return doc.toxml()


def source_unit(doc):
    return doc.getElementsByTagName('Unit')[0]


def source_group(doc):
    return doc.getElementsByTagName('Group')[0]


def set_pp(doc, name, value):
    row = next(r for r in source_unit(doc).getElementsByTagName('PP')
               if r.getAttribute('Name') == name)
    row.setAttribute('Value', value)


def test_complete_literal_source_phases_default_language_and_first_match():
    e, source = prepared(); v = vectors()
    assert dict(source.expected) == e.snapshot(v['fixture']['source_pp'])
    assert dict(source.after_load) == e.snapshot(v['expected_source']['after_load'])
    assert dict(source.final) == e.snapshot(v['expected_source']['final'])
    context = source.image_context
    assert context.source_language == 1
    assert context.metadata.find(56, 12).dynamic_images == (True, True, False, False)
    assert context.project_images.match('0001').rgb_sha256 == v['expected_source']['first_image_rgb_sha256']
    assert context.parameter_order == tuple(v['fixture']['parameter_order'])
    assert source.as_dict()['image_context']['project_images']['complete_directory_declared'] is True
    assert source.as_dict()['image_context']['original_execution_verified'] is False


@pytest.mark.parametrize('mask', range(16))
def test_all16_literal_masks_preserve_two_independent_complete_targets(mask):
    e, source = prepared(); case = vectors()['masks'][mask]
    payload = e.select(source, categories=case['categories'])
    assert [(name, ' '.join(hex(n) for n in value)) for name, value in payload.ordered_payload] == [tuple(r) for r in case['ordered_payload']]
    expected_payload = {name: tuple(int(n, 0) for n in value.split()) for name, value in case['ordered_payload']}
    with patch.object(e.lifecycle, 'load', side_effect=AssertionError('destination lifecycle')):
        for row in vectors()['fixture']['targets']:
            before = e.snapshot(row['input']); merge = e.merge(payload, before)
            assert dict(merge.final) == {**before, **expected_payload}
            assert len(merge.final) == 874
            for name in before:
                if name not in expected_payload:
                    assert merge.final[name] == before[name]
            for name in ('WidgetsCRC', 'StaticTextCRC', 'ScenesCheckSum'):
                assert merge.final[name] == before[name]
            assert [merge.final['StaticTextString' + str(i)] for i in range(64)] == [before['StaticTextString' + str(i)] for i in range(64)]
            receipt = target_preservation_baseline(source.image_context, row['path'], before, payload.values)
            assert receipt['destination_lifecycle_loads'] == 0
            assert receipt['preserved_pp_sha256'] != source.as_dict()['image_context']['source_pp_sha256']


def test_text_collision_requires_provider_and_complete_empty_export_proves_absence():
    with pytest.raises(EdltError, match='SHA-bound ProjectImages'):
        prepared(images=False)
    _, source = prepared(empty=True)
    assert source.after_load['Widget6WidgetByteValue1'] == (16,)
    assert source.image_context.metadata.find(56, 12).dynamic_images == (False,) * 4


def test_text_only_is_not_implicitly_image_free():
    xml = changed_xml(lambda d: [setattr(n.firstChild, 'data', 'TEXT')
        for n in source_group(d).getElementsByTagName('TagType')])
    with pytest.raises(EdltError, match='SHA-bound ProjectImages'):
        prepared(xml=xml, images=False)
    _, source = prepared(xml=xml)
    assert source.image_context.metadata.find(56, 12).dynamic_images == (False, True, False, False)


def test_explicit_absence_of_tags_has_four_blank_rows_without_image_boolean():
    xml = changed_xml(lambda d: source_group(d).removeChild(source_group(d).getElementsByTagName('TagsDLT')[0]))
    _, source = prepared(xml=xml, images=False)
    assert source.image_context.metadata.find(56, 12).dynamic_images == (False,) * 4


def test_current_source_language_never_borrows_target_language_or_images():
    def edit(doc):
        source = doc.getElementsByTagName('Network')[0]
        langs = source.getElementsByTagName('Language')
        langs[0].getElementsByTagName('TagValue')[0].firstChild.data = '9'
        langs[1].getElementsByTagName('ID')[0].firstChild.data = '9'
    _, source = prepared(xml=changed_xml(edit))
    assert source.image_context.source_language == 9
    assert source.image_context.metadata.find(56, 12).dynamic_images == (False,) * 4
    assert source.after_load['Widget6WidgetByteValue1'] == (16,)


def test_consumed_icon_requires_decoded_sha_provider(tmp_path):
    def edit(doc):
        first = source_group(doc).getElementsByTagName('TagDLT')[0]
        first.getElementsByTagName('TagType')[0].firstChild.data = 'ICON'
        first.getElementsByTagName('TagValue')[0].firstChild.data = '1'
    xml = changed_xml(edit)
    with pytest.raises(EdltError, match='decoded DLTP'):
        prepared(xml=xml)
    directory = tmp_path / 'Images' / 'DLTP'; directory.mkdir(parents=True)
    index = b'1,Owned,one.bmp\n'
    (directory / 'Index.txt').write_bytes(index); (directory / 'one.bmp').write_bytes(bmp(1))
    decoded = load_decoded_dltp_index(tmp_path, expected_sha256=hashlib.sha256(index).hexdigest())
    e = EdltGlobalProgramming(fixture())
    source = e.prepare_project_source(xml, vectors()['fixture']['source_unit'],
        project_images=provider(), dltp_index=decoded)
    assert source.image_context.metadata.find(56, 12).dynamic_images == (True, True, False, False)
    assert source.as_dict()['image_context']['dltp_images']['images_decoded'] is True


@pytest.mark.parametrize('fault', ['project', 'oid', 'missing-pp', 'missing-app', 'ambiguous-language', 'duplicate-variant'])
def test_incomplete_or_conflicting_native_source_refuses(fault):
    def edit(doc):
        if fault == 'project': doc.getElementsByTagName('Project')[0].getElementsByTagName('Address')[0].firstChild.data = 'OTHER'
        elif fault == 'oid': source_unit(doc).getElementsByTagName('OID')[0].firstChild.data = 'invalid'
        elif fault == 'missing-pp': source_unit(doc).removeChild(source_unit(doc).getElementsByTagName('PP')[0])
        elif fault == 'missing-app':
            app = doc.getElementsByTagName('Network')[0].getElementsByTagName('Application')[2];app.parentNode.removeChild(app)
        elif fault == 'ambiguous-language':
            lang = doc.getElementsByTagName('Network')[0].getElementsByTagName('Language')[0];lang.parentNode.removeChild(lang)
        else:
            tag = source_group(doc).getElementsByTagName('TagDLT')[0];tag.parentNode.appendChild(tag.cloneNode(True))
    with pytest.raises((EdltError, ValueError)):
        prepared(xml=changed_xml(edit))


def test_source_order_is_xml_pp_order_and_reordering_does_not_borrow_spec_order():
    def edit(doc):
        unit = source_unit(doc)
        for node in list(unit.getElementsByTagName('PP'))[::-1]: unit.appendChild(node)
    e, source = prepared(xml=changed_xml(edit))
    assert source.parameter_order == tuple(vectors()['fixture']['parameter_order'][::-1])
    payload = e.select(source, categories=tuple(CATEGORIES))
    wanted = set(name for row in CATEGORIES.values() for name in row) | {'OverallCRC'}
    assert [name for name, _ in payload.ordered_payload] == [n for n in source.parameter_order if n in wanted] + ['GlobalParameterCRC']


def test_consumed_scene_level_requires_source_address_value_alias():
    def edit(doc):
        set_pp(doc, 'Scene1StartAddress', '0x0')
        set_pp(doc, 'SceneBucket', '0x2 0x0 0x2a 0x7 0xff ' + ' '.join(['0xff'] * 227))
        app = doc.getElementsByTagName('Network')[0].getElementsByTagName('Application')[1]
        group = minidom.parseString('<Group><OID>aaaaaaaa-bbbb-4ccc-8ddd-000000000042</OID>'
            '<Address>42</Address><TagName>Trigger</TagName><Level Value="8">'
            '<OID>aaaaaaaa-bbbb-4ccc-8ddd-000000000007</OID><Address>7</Address>'
            '<TagName>Action</TagName></Level></Group>').documentElement
        app.appendChild(doc.importNode(group, True))
    with pytest.raises(EdltError, match='Address/Value'):
        prepared(xml=changed_xml(edit))


def test_exact_context_owner_provider_and_source_binding_cannot_be_detached():
    e, source = prepared(); c = source.image_context
    for forged in (replace(c), replace(c, source_language=9), replace(c, project_xml=c.project_xml+' '), replace(c, _seal=copy.copy(c._seal))):
        with pytest.raises(EdltError): check_global_image_context(forged, e)
    with pytest.raises(EdltError): check_global_image_context(c, EdltGlobalProgramming(fixture()))
    with pytest.raises(EdltError): check_global_image_context(c.as_dict(), e)
    with pytest.raises(EdltError): e.select(replace(source, image_context=None))
    object.__setattr__(c.project_images, 'entries', c.project_images.entries[::-1])
    with pytest.raises((EdltError, ValueError)): e.select(source)


@pytest.mark.parametrize('fault', ['clear-both', 'new-origin', 'same-owner-other-context'])
def test_automatic_source_association_cannot_be_downgraded_or_reissued_in_place(fault):
    e, source = prepared()
    if fault == 'same-owner-other-context':
        f = vectors()['fixture']
        other = resolve_global_image_context(f['project_xml'], f['source_unit'], e,
            project_images=provider())
        object.__setattr__(source, 'image_context', other)
        source._origin.image_context = other
    else:
        object.__setattr__(source, 'image_context', None)
        if fault == 'clear-both': source._origin.image_context = None
        else:
            origin = type(source._origin)(e._owner)
            origin.reference = weakref.ref(source)
            object.__setattr__(source, '_origin', origin)
    with pytest.raises(EdltError, match='association'):
        e.select(source)


@pytest.mark.parametrize('kind', ['project', 'decoded-dltp'])
def test_context_retains_exact_original_provider_identity_even_for_equal_bytes(kind, tmp_path):
    if kind == 'project':
        e, source = prepared(); context = source.image_context
        equal_provider = provider()
        assert equal_provider.evidence() == context.project_images.evidence()
        object.__setattr__(context, 'project_images', equal_provider)
    else:
        directory = tmp_path / 'Images' / 'DLTP'; directory.mkdir(parents=True)
        index = b'1,Owned,one.bmp\n'
        (directory / 'Index.txt').write_bytes(index); (directory / 'one.bmp').write_bytes(bmp(1))
        decoded = load_decoded_dltp_index(tmp_path, expected_sha256=hashlib.sha256(index).hexdigest())
        e = EdltGlobalProgramming(fixture()); f = vectors()['fixture']
        source = e.prepare_project_source(f['project_xml'], f['source_unit'],
            project_images=provider(), dltp_index=decoded)
        context = source.image_context
        object.__setattr__(context, 'dltp_index', replace(decoded))
    with pytest.raises(EdltError, match='provider differs'):
        e.select(source)


def test_preservation_shape_exempts_only_selected_destination_values():
    _, source = prepared(); f = vectors()['fixture']; path = f['targets'][0]['path']
    baseline = project_graph(f['project_xml'], f['project'], mutable_parameters=((path, ('FontStyle',)),))
    def edit(doc):
        unit = doc.getElementsByTagName('Unit')[1]
        next(r for r in unit.getElementsByTagName('PP') if r.getAttribute('Name') == 'FontStyle').setAttribute('Value', '0x1')
    allowed = changed_xml(edit)
    assert project_graph(allowed, f['project'], mutable_parameters=((path, ('FontStyle',)),)) == baseline
    assert project_graph(allowed, f['project']) != project_graph(f['project_xml'], f['project'])
    changed = allowed.replace('keep-2', 'changed-target-label')
    assert project_graph(changed, f['project'], mutable_parameters=((path, ('FontStyle',)),)) != baseline
    assert source.image_context.project_xml == f['project_xml']


def test_static_annex_retains_exact_source_spans_categories_and_limits():
    path = ROOT / 'research/fixtures/edlt-global-image-source-annex.json'
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '569cc52afc79a5d57765afa23a877f330c7e4b3bafae6af0d66749e7fb7e1431'
    annex = json.loads(raw)
    assert len(annex['managed_method_spans']) == 19
    assert len(annex['decompiled_source_symbols']) == 13
    assert len(annex['static_checks']) == 16
    assert all(row['passed'] is True for row in annex['static_checks'])
    assert annex['limits']['original_instructions_executed'] == 0
    assert annex['limits']['factory_admission_expanded'] is False
    assert annex['limits']['target_lifecycle_loads'] == 0


def test_read_only_static_regeneration_when_exact_inputs_explicitly_provisioned():
    root = os.environ.get('CBUS_GLOBAL_IMAGE_STATIC_ROOT')
    if root is None:
        pytest.skip('Exact private managed static inputs are not explicitly provisioned')
    from research.edlt_global_image_static import recover
    expected = (ROOT / 'research/fixtures/edlt-global-image-source-annex.json').read_bytes()
    assert (json.dumps(recover(Path(root)), indent=2) + '\n').encode() == expected
