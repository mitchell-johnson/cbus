"""Literal source-backed family ranges, associations and atomic public CSV."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.toolkit_database_csv_native import project_native_xml_selection, project_native_xml_unit
from cbus_toolkit.toolkit_database_csv_projection import (
    CSVAreaObservation, CSVGroupSaveObservation, WIRELESS_PROFILE,
    loads_cached_projection, project_cached_csv_unit,
)
from cbus_toolkit import toolkit_database_csv_registry as registry
from tests.test_cgate import peer
from tests.test_toolkit_database_csv_neopro import invoke, reply

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT/'rust/testdata/vectors/toolkit_database_csv_families.json').read_text())
COLUMNS = tuple(DATA['columns'])
REGISTRY = ROOT/'toolkit-cli/research/fixtures/toolkit-database-csv-families-registry.json'


def tree():
    return ET.fromstring(DATA['fixture']['xml'])


def xml(root):
    return ET.tostring(root, encoding='unicode')


def unit(root, path):
    _, _, project, network, _, address = path.split('/')
    assert project == 'FAMCSV'
    n = next(n for n in root.find('Project').findall('Network') if n.findtext('Address') == network)
    return next(u for u in n.findall('Unit') if u.findtext('Address') == address)


def pp(node, name):
    return next(p for p in node.findall('PP') if p.get('Name') == name)


def cached_input(result):
    c = result.cached
    value = {'format':c.as_dict()['format'], 'unit':c.unit.as_dict(),
             'group_cache':[replace(g,references=()).as_dict() for g in c.groups],
             'area_observations':[] if c.raw_area is None else [{'raw':c.raw_area,'completed':True}]*2,
             'group_save':None, 'application_context':c.application_context.as_dict()}
    if c.wireless_loader is not None:
        value['wireless_loader'] = c.wireless_loader.as_dict()
    return value


class FamilyRangeRowsTests(unittest.TestCase):
    def test_new_registry_preserves_all_original_static_facts_and_historical_receipts(self):
        current=json.loads(REGISTRY.read_text())
        historical=json.loads((ROOT/'toolkit-cli/research/experiments/2026-09-30/csv-factory-registry-static.json').read_text())
        admission={'admitted','admitted_firmware','association_model','refusal_reason'}
        self.assertEqual([{k:v for k,v in row.items() if k not in admission} for row in current['registrations']],
                         [{k:v for k,v in row.items() if k not in admission} for row in historical['registrations']])
        self.assertFalse(current['original_execution'])
        self.assertEqual({name.split('.')[-1]:digest for name,digest in current['original_inputs'].items()},
                         DATA['source_evidence']['original_inputs'])
        self.assertEqual((current['summary']['static_registrations'],current['summary']['unit_types']), (425,262))
        prior=json.loads((ROOT/'toolkit-cli/research/fixtures/toolkit-database-csv-neopro-registry.json').read_text())
        self.assertEqual(prior['summary']['admitted_types'],35)
        self.assertEqual(current['summary']['admitted_types']-prior['summary']['admitted_types'],91)

    def test_every_selected_range_endpoint_matches_literal_native_and_cached_row(self):
        self.assertEqual(hashlib.sha256(REGISTRY.read_bytes()).hexdigest(), DATA['source_evidence']['registry_sha256'])
        receipt = json.loads(REGISTRY.read_text())
        self.assertEqual(receipt['summary']['admitted_types'], 126)
        self.assertEqual(receipt['summary']['unadmitted_types'], 136)
        self.assertEqual(len(DATA['range_cases']), 466)
        for case in DATA['range_cases']:
            with self.subTest(kind=case['kind'], firmware=case['firmware'], klass=case['class']):
                root = tree()
                target = unit(root, case['template_path'])
                target.find('UnitType').text = case['kind']
                target.find('FirmwareVersion').text = case['firmware']
                before = xml(root)
                result = project_native_xml_unit(before, case['template_path'], columns=COLUMNS)
                self.assertEqual(result.cached.selected_class, case['class'])
                self.assertEqual(result.report.rows, (DATA['fixture']['rows'][0], case['row']))
                cached = loads_cached_projection(json.dumps(cached_input(result)).encode(), columns=COLUMNS)
                self.assertEqual(cached.report.utf8_bytes, result.report.utf8_bytes)
                self.assertEqual(xml(root), before)

    def test_all_neopro_registered_types_all_masks_match_literal_rows(self):
        native=project_native_xml_unit(DATA['fixture']['xml'],'//FAMCSV/254/p/3',columns=COLUMNS)
        original=cached_input(native)
        kinds=sorted({r['kind'] for r in DATA['range_cases'] if r['family']=='neopro'})
        self.assertEqual(len(kinds),34)
        primary=next(a for a in original['application_context']['applications']
                     if a['identity']==original['application_context']['primary_identity'])
        secondary=next(a for a in original['application_context']['applications']
                       if a['identity']==original['application_context']['secondary_identity'])
        cache={g['identity']:g for g in original['group_cache']}
        for kind in kinds:
            for case in DATA['neopro_mask_cases']:
                with self.subTest(kind=kind,mask=case['mask']):
                    value=deepcopy(original);value['unit']['unit_type']=kind
                    value['unit']['firmware']='2.5.00'
                    value['application_context']['secondary_mask']=case['mask']
                    value['unit']['group_identities']=[next(identity for identity in
                        (secondary if case['mask']&(1<<x) else primary)['group_identities']
                        if cache[identity]['address']==n) for x,n in enumerate(range(8,0,-1))]
                    result=loads_cached_projection(json.dumps(value).encode(),columns=COLUMNS)
                    expected=case['row_keycir4'].replace(',KEYCIR4,',','+kind+',').replace(',1.8.01,',',2.5.00,')
                    self.assertEqual(result.report.rows,(DATA['fixture']['rows'][0],expected))
                    self.assertEqual({g.identity:g.tag for g in result.groups}[result.area_identity],'PUnused')

    def test_every_wireless_bit_routes_blocks_and_nonserialized_channel_tail(self):
        root=tree();target=unit(root,'//FAMCSV/254/p/42')
        pp(target,'InstalledChannels').set('Value','16')
        pp(target,'BlockGroup').set('Value',' '.join(map(str,range(1,17))))
        pp(target,'OutputGroup').set('Value',' '.join(map(str,range(1,17))))
        for bit in (*range(32),None,'all'):
            with self.subTest(bit=bit):
                mask=0 if bit is None else 0xffffffff if bit=='all' else 1<<bit
                pp(target,'BlockGroupSecondary').set('Value',' '.join(str(int(bool(mask&(1<<x)))) for x in range(16)))
                pp(target,'OutputGroupSecondary').set('Value',' '.join(str(int(bool(mask&(1<<(16+x))))) for x in range(16)))
                result=project_native_xml_unit(xml(root),'//FAMCSV/254/p/42',columns=COLUMNS)
                cache={g.identity:g.tag for g in result.cached.groups}
                self.assertEqual([cache[g] for g in result.cached.unit.group_identities],
                    [('S' if mask&(1<<x) else 'P')+f'{x%16+1:02d}' for x in range(32)])
                self.assertEqual(result.cached.application_context.secondary_mask,mask)
                self.assertEqual(len(result.cached.csv_unit.groups),16)


@pytest.mark.parametrize('mask', (0, 1, 85, 170, 255))
@pytest.mark.parametrize('secondary', (56, 57))
def test_neopro_ranges_keep_primary_area_and_repeated_order(mask, secondary):
    root = tree()
    target = unit(root, '//FAMCSV/254/p/3')
    pp(target, 'Application').set('Value', f'56 {secondary}')
    pp(target, 'SecondApplicationBlocks').set('Value', str(mask))
    pp(target, 'GroupAddress').set('Value', '8 8 255 4 3 2 1 16')
    result = project_native_xml_unit(xml(root), '//FAMCSV/254/p/3', columns=COLUMNS)
    cache = {g.identity:g for g in result.cached.groups}
    labels = [cache[g].tag for g in result.cached.unit.group_identities]
    expected = [('S' if secondary == 57 and mask & (1 << x) else 'P')
                + ('Unused' if n == 255 else f'{n:02d}') for x,n in enumerate((8,8,255,4,3,2,1,16))]
    assert labels == expected
    assert cache[result.cached.area_identity].tag == 'PUnused'


@pytest.mark.parametrize('channels', (0, 1, 2, 16))
@pytest.mark.parametrize('secondary', (False, True))
def test_wireless_sixteen_blocks_then_every_channel_is_validated(channels, secondary):
    root = tree()
    target = unit(root, '//FAMCSV/254/p/42')
    pp(target, 'InstalledChannels').set('Value', str(channels))
    pp(target, 'OutputGroup').set('Value', ' '.join(map(str, range(1, channels+1))))
    pp(target, 'OutputGroupSecondary').set('Value', ' '.join(['1' if secondary else '0']*channels))
    native = project_native_xml_unit(xml(root), '//FAMCSV/254/p/42', columns=COLUMNS)
    assert native.cached.as_dict()['format'] == WIRELESS_PROFILE
    assert len(native.cached.unit.group_identities) == 16 + channels
    assert native.cached.area_identity is None
    assert [e.event for e in native.cached.events] == ['factory_selected','wireless_groups_replaced','row_projected']
    cache = {g.identity:g for g in native.cached.groups}
    assert [cache[g].tag for g in native.cached.unit.group_identities[16:]] == [
        ('S' if secondary else 'P')+f'{n:02d}' for n in range(1, channels+1)]
    literal = next(r['row'] for r in DATA['fixture']['units'] if r['path'].endswith('/42'))
    assert native.report.rows[1] == literal
    cached = cached_input(native)
    assert loads_cached_projection(json.dumps(cached).encode(), columns=COLUMNS).report.utf8_bytes == native.report.utf8_bytes
    if channels:
        cached['unit']['group_identities'][-1] = cached['unit']['group_identities'][0]
        if secondary:
            with pytest.raises(ValueError, match='mask'):
                loads_cached_projection(json.dumps(cached).encode(), columns=COLUMNS)


@pytest.mark.parametrize('family_path', ('//FAMCSV/254/p/18','//FAMCSV/254/p/21','//FAMCSV/254/p/3'))
@pytest.mark.parametrize('case', ('first-fail','second-fail','save-fail','create'))
def test_new_area_families_replay_provider_stop_order(family_path, case):
    native = project_native_xml_unit(DATA['fixture']['xml'], family_path, columns=COLUMNS)
    c = native.cached
    current = tuple(replace(g,references=()) for g in c.groups)
    # Force primary255 absence, retaining secondary255 to disambiguate owner.
    primary = next(a for a in c.application_context.applications if a.identity == c.application_context.primary_identity)
    remove = next(g.identity for g in current if g.address == 255 and g.identity in primary.group_identities)
    if remove in c.unit.group_identities:
        # Fixtures for these three profiles do not consume255 as a block.
        raise AssertionError('Provider fixture unexpectedly depends on removed block')
    current = tuple(g for g in current if g.identity != remove)
    context = replace(c.application_context, applications=tuple(replace(a,group_identities=tuple(
        g for g in a.group_identities if g != remove)) for a in c.application_context.applications))
    observations = (CSVAreaObservation('255',case!='first-fail'),CSVAreaObservation('255',case!='second-fail'))
    result = project_cached_csv_unit(c.unit,group_cache=current,application_context=context,
        area_observations=observations,group_save=CSVGroupSaveObservation(case!='save-fail'),columns=COLUMNS)
    assert result.complete == (case=='create')
    if case=='first-fail':
        assert [e.event for e in result.events] == ['factory_selected','area_load']
    elif case=='save-fail':
        assert [e.event for e in result.events] == ['factory_selected','area_load','group_lookup','group_created','group_save']
    elif case=='second-fail':
        assert result.events[-1].event == 'area_load'
    else:
        assert result.csv_unit.area == '<Unused>'
        assert result.area_identity == 'created-255'


@pytest.mark.parametrize('case', ('firmware','missing-tail','wrong-tail-owner','missing-identity',
                                  'duplicate-membership','bad-count','bad-bool','bad-mask','area-observation'))
def test_wireless_cached_metadata_and_late_association_refusals(case):
    native = project_native_xml_unit(DATA['fixture']['xml'], '//FAMCSV/254/p/42', columns=COLUMNS)
    value = cached_input(native)
    if case=='firmware': value['unit']['firmware']='1.12.0'
    elif case=='missing-tail': value['unit']['group_identities'][-1]='absent'
    elif case=='wrong-tail-owner': value['unit']['group_identities'][-1]=value['unit']['group_identities'][1]
    elif case=='missing-identity': value['application_context']['primary_identity']='absent'
    elif case=='duplicate-membership': value['application_context']['applications'][1]['group_identities'].append(value['application_context']['applications'][0]['group_identities'][0])
    elif case=='bad-count': value['wireless_loader']['installed_channels']=3
    elif case=='bad-bool': value['wireless_loader']['block_secondary'][0]=1
    elif case=='bad-mask': value['application_context']['secondary_mask'] ^= 1
    else: value['area_observations']=[{'raw':'255','completed':True}]*2
    before=deepcopy(value)
    with pytest.raises(ValueError): loads_cached_projection(json.dumps(value).encode(),columns=COLUMNS)
    assert value == before


@pytest.mark.parametrize('live', (False,True), ids=('offline','owned-wire'))
def test_public_family_project_network_and_ordered_selection_exact_atomic_csv(live,tmp_path):
    selections=[('project',['--native-xml-project','//FAMCSV'],['--project','//FAMCSV'],DATA['fixture']['rows']),
                ('network',['--native-xml-network','//FAMCSV/254'],['--network','//FAMCSV/254'],DATA['fixture']['rows'][:-2]),
                ('selection',['--native-xml-units','//FAMCSV/11/p/9','//FAMCSV/254/p/3'],['--units','//FAMCSV/11/p/9','//FAMCSV/254/p/3'],
                 [DATA['fixture']['rows'][0],DATA['fixture']['units'][5]['row'],DATA['fixture']['units'][1]['row']])]
    source=tmp_path/'synthetic.xml';source.write_text(DATA['fixture']['xml'])
    for name,offline,online,rows in selections:
        output=tmp_path/(name+'.csv')
        if live:
            with peer([[reply(DATA['fixture']['xml'])]]) as ((host,port),sent):
                code,result=invoke(['cgate','--host',host,'--port',port,'database-csv',*online,
                                    '--columns',*COLUMNS,'--output',output],artifact_dir=tmp_path)
            assert sent == [b'[1] DBGETXML //FAMCSV\r\n']
        else:
            code,result=invoke(['toolkit-database-csv',source,*offline,'--columns',*COLUMNS,'--output',output],artifact_dir=tmp_path)
        assert code==0,result
        assert output.read_bytes()==('\r\n'.join(rows)+'\r\n\r\n').encode()
    assert source.read_text()==DATA['fixture']['xml']


@pytest.mark.parametrize('live',(False,True),ids=('offline','owned-wire'))
@pytest.mark.parametrize('case',('bad-profile','channel-tail','secondary-owner'))
def test_public_family_late_failure_leaves_no_outputs_or_partial_report(live,case,tmp_path):
    root=tree();last=unit(root,'//FAMCSV/11/p/9')
    if case=='bad-profile':last.find('FirmwareVersion').text='1.12.0'
    elif case=='channel-tail':pp(last,'OutputGroup').set('Value','11 99')
    else:pp(last,'Application').set('Value','56 58')
    raw=xml(root);source=tmp_path/'bad.xml';source.write_text(raw);output=tmp_path/'never.csv'
    if live:
        with peer([[reply(raw)]]) as ((host,port),sent):
            code,result=invoke(['cgate','--host',host,'--port',port,'database-csv','--project','//FAMCSV','--output',output],artifact_dir=tmp_path)
        assert sent == [b'[1] DBGETXML //FAMCSV\r\n']
    else:
        code,result=invoke(['toolkit-database-csv',source,'--native-xml-project','//FAMCSV','--output',output],artifact_dir=tmp_path)
    assert code==1,result
    assert not output.exists()
    assert source.read_text()==raw


@pytest.mark.parametrize('path',tuple(case['path'] for case in DATA['fixture']['units']))
def test_public_family_cached_contract_serializes_exact_literal_rows(path,tmp_path):
    native=project_native_xml_unit(DATA['fixture']['xml'],path,columns=COLUMNS)
    source=tmp_path/'cached.json';value=cached_input(native);source.write_text(json.dumps(value))
    output=tmp_path/'cached.csv'
    code,result=invoke(['toolkit-database-csv',source,'--cached-projection','--columns',*COLUMNS,
                        '--output',output],artifact_dir=tmp_path)
    assert code==0,result
    literal=next(row['row'] for row in DATA['fixture']['units'] if row['path']==path)
    assert output.read_bytes()==('\r\n'.join((DATA['fixture']['rows'][0],literal))+'\r\n\r\n').encode()
    assert json.loads(source.read_text())==value


@pytest.mark.parametrize('version',('v1','v2'))
def test_public_wireless_cached_versions_cannot_omit_consumed_loader_metadata(version,tmp_path):
    native=project_native_xml_unit(DATA['fixture']['xml'],'//FAMCSV/254/p/42',columns=COLUMNS)
    value=cached_input(native);value['format']='cbus-toolkit-database-cached-projection-'+version
    del value['wireless_loader']
    if version=='v1':del value['application_context']
    source=tmp_path/'invalid-cache.json';source.write_text(json.dumps(value));output=tmp_path/'never.csv'
    code,result=invoke(['toolkit-database-csv',source,'--cached-projection','--output',output],artifact_dir=tmp_path)
    assert code==1,result
    assert not output.exists()


@pytest.mark.parametrize('path',('//FAMCSV/254/p/3','//FAMCSV/254/p/42'),ids=('cached-v2','cached-v3'))
def test_cached_unit_identity_cannot_alias_distinct_group_oid(path):
    native=project_native_xml_unit(DATA['fixture']['xml'],path,columns=COLUMNS)
    value=cached_input(native)
    value['group_cache'][0]['oid']='aliased-unit-oid'
    value['unit']['identity']='aliased-unit-oid'
    assert value['group_cache'][0]['identity'] != value['group_cache'][0]['oid']
    before=deepcopy(value)
    with pytest.raises(ValueError,match='identities must not collide'):
        loads_cached_projection(json.dumps(value).encode(),columns=COLUMNS)
    assert value==before


@pytest.mark.parametrize('case',('ambiguous-firmware','malformed-firmware'))
def test_factory_selection_never_guesses_ambiguous_or_malformed_registration(case,monkeypatch):
    import cbus_toolkit.toolkit_database_csv_projection as projection
    root=tree();target=unit(root,'//FAMCSV/254/p/42')
    if case=='ambiguous-firmware':
        original=projection.registrations_for
        monkeypatch.setattr(projection,'registrations_for',lambda k,f:original(k,f)*2)
    else:target.find('FirmwareVersion').text='2.0.0x'
    with pytest.raises(ValueError,match='exactly one'):
        project_native_xml_unit(xml(root),'//FAMCSV/254/p/42',columns=COLUMNS)


@pytest.mark.parametrize('case',('keys-missing','keys-duplicate','channels-over-bound','channels-malformed',
                                  'relay-over-bound','relay-malformed','blocks-short','block-bool',
                                  'outputs-short','output-bool','secondary-missing'))
def test_native_wireless_consumed_metadata_refusals_preserve_snapshot(case):
    root=tree();target=unit(root,'//FAMCSV/254/p/42')
    if case=='keys-missing':target.remove(pp(target,'InstalledKeys'))
    elif case=='keys-duplicate':target.append(deepcopy(pp(target,'InstalledKeys')))
    elif case=='channels-over-bound':pp(target,'InstalledChannels').set('Value','17')
    elif case=='channels-malformed':pp(target,'InstalledChannels').set('Value','oops')
    elif case=='relay-over-bound':pp(target,'ChannelRelayMask').set('Value','65536')
    elif case=='relay-malformed':pp(target,'ChannelRelayMask').set('Value','oops')
    elif case=='blocks-short':pp(target,'BlockGroup').set('Value','1 2 3')
    elif case=='block-bool':pp(target,'BlockGroupSecondary').set('Value','2 '+'0 '*14+'0')
    elif case=='outputs-short':pp(target,'OutputGroup').set('Value','1')
    elif case=='output-bool':pp(target,'OutputGroupSecondary').set('Value','1 2')
    else:target.remove(pp(target,'OutputGroupSecondary'))
    before=xml(root)
    with pytest.raises(ValueError):project_native_xml_unit(before,'//FAMCSV/254/p/42',columns=COLUMNS)
    assert xml(root)==before
