"""Exact source-loader counts, v4 Application state and atomic public reports."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.toolkit_database_csv_native import (
    project_native_xml_unit, project_native_xml_selection,
)
from cbus_toolkit.toolkit_database_csv_projection import (
    SOURCE_PROFILE, CSVAreaObservation, CSVGroupSaveObservation,
    family_profile, loads_cached_projection, project_cached_csv_unit,
)
from tests.test_cgate import peer
from tests.test_toolkit_database_csv_neopro import invoke, reply

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT/'rust/testdata/vectors/toolkit_database_csv_completion.json').read_text())
COLUMNS = tuple(DATA['columns'])


def tree():
    return ET.fromstring(DATA['fixture']['xml'])


def xml(root):
    return ET.tostring(root, encoding='unicode')


def unit(root, path):
    return next(node for node in root.find('Project/Network').findall('Unit')
                if node.findtext('Address') == path.rsplit('/',1)[1])


def pp(node, name):
    return next(p for p in node.findall('PP') if p.get('Name') == name)


def cached_input(native):
    cached = native.cached
    return {'format': SOURCE_PROFILE, 'unit': cached.unit.as_dict(),
            'group_cache': [replace(group, references=()).as_dict() for group in cached.groups],
            'application_context': cached.application_context.as_dict(),
            'area_observations': [] if cached.raw_area is None else
                [{'raw':cached.raw_area,'completed':True}]*2,
            'group_save':None}


def select_case(root, case):
    node = unit(root, case['template_path'])
    node.find('UnitType').text = case['kind']
    node.find('FirmwareVersion').text = case['firmware']
    profile = family_profile(case['kind'], case['firmware'])
    count = profile['blocks']
    parameter = profile['group_parameter']
    if parameter == 'channel_fields':
        for item in list(node.findall('PP')):
            if item.get('Name','').startswith('Ch'): node.remove(item)
        for index in range(count):
            ET.SubElement(node, 'PP', Name=f'Ch{index}GroupAddress', Value=str(count-index))
    elif parameter is not None:
        pp(node, 'GroupAddress' if parameter == 'relay_logic' else parameter).set(
            'Value', ' '.join(map(str,range(count,0,-1))))
    if profile['secondary_blocks']:
        pp(node, 'SecondApplicationBlocks').set('Value', str(case['mask']))
    return node


class SourceCompletionRangesTests(unittest.TestCase):
    def test_fresh_registry_static_facts_and_historical_receipts_are_preserved(self):
        current_path=ROOT/'toolkit-cli/research/fixtures/toolkit-database-csv-completion-registry.json'
        current=json.loads(current_path.read_text())
        historical=json.loads((ROOT/'toolkit-cli/research/fixtures/toolkit-database-csv-families-registry.json').read_text())
        omitted={'admitted','admitted_firmware','association_model','refusal_reason'}
        self.assertEqual([{k:v for k,v in row.items() if k not in omitted}
                          for row in current['registrations']],
                         [{k:v for k,v in row.items() if k not in omitted}
                          for row in historical['registrations']])
        self.assertEqual(hashlib.sha256(current_path.read_bytes()).hexdigest(),
                         DATA['source_evidence']['registry_sha256'])
        self.assertEqual((current['summary']['static_registrations'],current['summary']['unit_types']), (425,262))
        self.assertEqual(historical['summary']['admitted_types'],126)
        self.assertFalse(current['original_execution'])

    def test_every_range_endpoint_has_literal_native_cached_rows_and_retained_inputs(self):
        self.assertGreater(len(DATA['range_cases']),200)
        for case in DATA['range_cases']:
            with self.subTest(kind=case['kind'],firmware=case['firmware'],klass=case['class']):
                root=tree();select_case(root,case);before=xml(root)
                native=project_native_xml_unit(before,case['template_path'],columns=COLUMNS)
                self.assertEqual(native.cached.selected_class,case['class'])
                self.assertEqual(native.report.rows,(DATA['fixture']['rows'][0],case['row']))
                value=cached_input(native);frozen=deepcopy(value)
                result=loads_cached_projection(json.dumps(value).encode(),columns=COLUMNS)
                self.assertEqual(result.report.utf8_bytes,native.report.utf8_bytes)
                self.assertEqual(value,frozen)
                self.assertEqual(xml(root),before)


@pytest.mark.parametrize('path',[r['path'] for r in DATA['fixture']['units']])
def test_template_exact_literal_rows(path):
    native=project_native_xml_unit(DATA['fixture']['xml'],path,columns=COLUMNS)
    expected=next(r['row'] for r in DATA['fixture']['units'] if r['path']==path)
    assert native.report.rows==(DATA['fixture']['rows'][0],expected)
    assert native.cached.as_dict()['format']==SOURCE_PROFILE


@pytest.mark.parametrize('kind',('BCI4A','SENPILLA','KEYBL5','SENPIRSS'))
@pytest.mark.parametrize('mask',(0,1,85,255))
def test_input_masks_repeated_unused_and_primary_area_owner(kind,mask):
    root=tree()
    row=next(r for r in DATA['range_cases'] if r['kind']==kind)
    node=select_case(root,row);profile=family_profile(kind,row['firmware'])
    count=profile['blocks']
    pp(node,'GroupAddress').set('Value',' '.join(['255',*[str(x) for x in range(1,count)]]))
    if profile['secondary_blocks']:pp(node,'SecondApplicationBlocks').set('Value',str(mask))
    native=project_native_xml_unit(xml(root),row['template_path'],columns=COLUMNS)
    cache={g.identity:g for g in native.cached.groups}
    labels=[cache[g].tag for g in native.cached.unit.group_identities]
    actual_mask=mask if profile['secondary_blocks'] else 0
    assert labels==[('S' if actual_mask&(1<<x) else'P')+
        ('Unused' if x==0 else f'{x:02d}') for x in range(count)]
    assert cache[native.cached.area_identity].tag=='P42'


@pytest.mark.parametrize('agent',('TDIMDNUXCGateAgent','TDIMARXCGateAgent','TCBus1RelayCGateAgent'))
def test_short_nonempty_group_arrays_default_each_missing_tail_to_primary255(agent):
    row=next(r for r in DATA['fixture']['units'] if r['agent']==agent)
    root=tree();node=unit(root,row['path'])
    pp(node,'ChannelOutputGroup' if agent=='TDIMARXCGateAgent' else'GroupAddress').set('Value','3')
    result=project_native_xml_unit(xml(root),row['path'],columns=COLUMNS)
    cache={g.identity:g.tag for g in result.cached.groups}
    assert [cache[g] for g in result.cached.unit.group_identities]==[
        'P03',*['PUnused']*(row['groups']-1)]


@pytest.mark.parametrize('agent',('TCBusNonUnitCGateAgent','TCBusCouplerProInputCGateAgent','TDIMDD8CGateAgent'))
@pytest.mark.parametrize('raw',('', '56', '56 255'))
def test_base_formatter_defaults_require_real_primary_and_secondary255(agent,raw):
    root=tree();row=next(r for r in DATA['fixture']['units'] if r['agent']==agent)
    node=unit(root,row['path'])
    pp(node,'Application').set('Value',raw)
    if family_profile(row['kind'],row['firmware'])['secondary_blocks']:
        pp(node,'SecondApplicationBlocks').set('Value','0')
    before=xml(root)
    with pytest.raises(ValueError,match='Application at address 255'):
        project_native_xml_unit(before,row['path'],columns=COLUMNS)
    app=ET.SubElement(root.find('Project/Network'),'Application')
    ET.SubElement(app,'Address').text='255';ET.SubElement(app,'TagName').text='Real Application255'
    after=xml(root)
    result=project_native_xml_unit(after,row['path'],columns=COLUMNS)
    context=result.cached.application_context
    assert next(a for a in context.applications if a.identity==context.primary_identity).address==56
    assert next(a for a in context.applications if a.identity==context.secondary_identity).address==255
    assert result.cached.unit.secondary=='Real Application255'
    assert DATA['error_row']['text'] not in result.report.rows[1]
    value=cached_input(result)
    assert loads_cached_projection(json.dumps(value).encode(),columns=COLUMNS).report.utf8_bytes==result.report.utf8_bytes
    assert xml(root)==after


@pytest.mark.parametrize('columns',(COLUMNS,('primary',),('group_16',)))
def test_v4_cold_nil_secondary_refuses_before_events_even_if_column_omitted(columns):
    row=next(r for r in DATA['fixture']['units'] if r['agent']=='TCBusNonUnitCGateAgent')
    value=cached_input(project_native_xml_unit(DATA['fixture']['xml'],row['path'],columns=COLUMNS))
    context=value['application_context']
    context['applications']=[a for a in context['applications'] if a['identity']==context['primary_identity']]
    context['secondary_identity']=None;value['unit']['secondary']=''
    value['group_cache']=[g for g in value['group_cache'] if g['identity'] in context['applications'][0]['group_identities']]
    before=deepcopy(value)
    with pytest.raises(ValueError,match='resolved secondary Application identity'):
        loads_cached_projection(json.dumps(value).encode(),columns=columns)
    assert value==before


@pytest.mark.parametrize('unconsumed',('area','save'))
def test_generic_loader_rejects_unconsumed_provider_outcomes(unconsumed):
    row=next(r for r in DATA['fixture']['units'] if r['agent']=='TCBusNonUnitCGateAgent')
    value=cached_input(project_native_xml_unit(DATA['fixture']['xml'],row['path'],columns=COLUMNS))
    if unconsumed=='area':value['area_observations']=[{'raw':'255','completed':True}]*2
    else:value['group_save']={'completed':True}
    before=deepcopy(value)
    with pytest.raises(ValueError,match='no Area|cannot consume'):
        loads_cached_projection(json.dumps(value).encode(),columns=COLUMNS)
    assert value==before


@pytest.mark.parametrize('case',('first-load','second-load','save','create'))
def test_v4_provider_stop_order_and_primary_only_missing255_creation(case):
    row=next(r for r in DATA['fixture']['units'] if r['agent']=='TCBusCouplerProInputCGateAgent')
    native=project_native_xml_unit(DATA['fixture']['xml'],row['path'],columns=COLUMNS)
    c=native.cached;context=c.application_context
    primary=next(a for a in context.applications if a.identity==context.primary_identity)
    remove=next(g.identity for g in c.groups if g.address==255 and g.identity in primary.group_identities)
    groups=tuple(replace(g,references=()) for g in c.groups if g.identity!=remove)
    context=replace(context,applications=tuple(replace(a,group_identities=tuple(
        g for g in a.group_identities if g!=remove)) for a in context.applications))
    result=project_cached_csv_unit(c.unit,group_cache=groups,application_context=context,
        area_observations=(CSVAreaObservation('255',case!='first-load'),
                           CSVAreaObservation('255',case!='second-load')),
        group_save=CSVGroupSaveObservation(case!='save'),columns=COLUMNS)
    assert result.complete==(case=='create')
    if case=='first-load':assert [e.event for e in result.events]==['factory_selected','area_load']
    elif case=='save':assert result.events[-1].event=='group_save'
    elif case=='second-load':assert result.events[-1].event=='area_load'
    else:assert result.area_identity=='created-255' and result.csv_unit.area=='<Unused>'


@pytest.mark.parametrize('mutation',('format','missing-app','member','oid-collision','group-count','raw-area'))
def test_cached_v4_refuses_ambiguous_or_unbound_metadata_without_model_events(mutation):
    row=next(r for r in DATA['fixture']['units'] if r['agent']=='TCBusCouplerProInputCGateAgent')
    value=cached_input(project_native_xml_unit(DATA['fixture']['xml'],row['path'],columns=COLUMNS))
    if mutation=='format':value['format']='cbus-toolkit-database-cached-projection-v2'
    elif mutation=='missing-app':value['application_context']['primary_identity']='missing'
    elif mutation=='member':value['application_context']['applications'][1]['group_identities'].append(
        value['application_context']['applications'][0]['group_identities'][0])
    elif mutation=='oid-collision':value['unit']['identity']=value['group_cache'][0]['oid']
    elif mutation=='group-count':value['unit']['group_identities'].pop()
    else:value['area_observations'][0]['raw']='256'
    frozen=deepcopy(value)
    with pytest.raises(ValueError):loads_cached_projection(json.dumps(value).encode(),columns=COLUMNS)
    assert value==frozen


@pytest.mark.parametrize('live,selection',[(live,selection) for live in (False,True)
    for selection in ('project','network','ordered','cached') if not (live and selection=='cached')])
def test_public_source_contract_csv_and_stdout_metadata(live,selection,tmp_path):
    root=tree()
    source=tmp_path/'synthetic.xml';source.write_text(xml(root))
    if selection=='cached':
        row=DATA['fixture']['units'][0]
        source=tmp_path/'cached.json'
        source.write_text(json.dumps(cached_input(project_native_xml_unit(
            xml(root),row['path'],columns=COLUMNS))))
        argv=['toolkit-database-csv',source,'--cached-projection'];rows=DATA['fixture']['rows'][:2]
    elif selection=='ordered':
        selected=[DATA['fixture']['units'][-1],DATA['fixture']['units'][0]]
        paths=[r['path'] for r in selected];rows=[DATA['fixture']['rows'][0],*[r['row'] for r in selected]]
        argv=['--units' if live else'--native-xml-units',*paths]
    else:
        rows=DATA['fixture']['rows']
        argv=['--project' if live else'--native-xml-project','//CMPLCSV'] if selection=='project' else[
              '--network' if live else'--native-xml-network','//CMPLCSV/254']
    output=tmp_path/'report.csv'
    args=[*argv,'--columns',*COLUMNS,'--output',output]
    if live:
        with peer([[reply(xml(root))]]) as ((host,port),sent):
            code,result=invoke(['cgate','--host',host,'--port',port,'database-csv',*args],artifact_dir=tmp_path)
        assert sent==[b'[1] DBGETXML //CMPLCSV\r\n']
    else:
        code,result=invoke(args if selection=='cached' else[
            'toolkit-database-csv',source,*args],artifact_dir=tmp_path)
    assert code==0,result
    assert output.read_bytes()==('\r\n'.join(rows)+'\r\n\r\n').encode()
    assert result['report']['sha256']==hashlib.sha256(output.read_bytes()).hexdigest()


@pytest.mark.parametrize('live',(False,True),ids=('offline','owned-wire'))
@pytest.mark.parametrize('fault',('late-firmware','late-application','late-channel','late-logic','existing-output'))
def test_whole_project_late_failure_preserves_output_and_snapshot(live,fault,tmp_path):
    root=tree();last=DATA['fixture']['units'][-1]
    if fault=='late-firmware':unit(root,last['path']).find('FirmwareVersion').text='999'
    elif fault=='late-application':pp(unit(root,last['path']),'Application').set('Value','56 58')
    elif fault=='late-channel':
        row=next(r for r in DATA['fixture']['units'] if r['agent']=='TDIMDD8CGateAgent')
        pp(unit(root,row['path']),'Ch7GroupAddress').set('Value','200')
    elif fault=='late-logic':
        row=next(r for r in DATA['fixture']['units'] if r['agent']=='TCBus1RelayCGateAgent')
        pp(unit(root,row['path']),'LogicGA5Associations').set('Value','bad')
    source=tmp_path/'synthetic.xml';source.write_text(xml(root));before=source.read_bytes()
    output=tmp_path/'report.csv'
    if fault=='existing-output':output.write_bytes(b'previous artifact')
    args=['--project' if live else'--native-xml-project','//CMPLCSV','--columns',*COLUMNS,
          '--output',output]
    if live:
        with peer([[reply(xml(root))]]) as ((host,port),sent):
            code,result=invoke(['cgate','--host',host,'--port',port,'database-csv',*args],artifact_dir=tmp_path)
        assert len(sent)<=1
    else:code,result=invoke(['toolkit-database-csv',source,*args],artifact_dir=tmp_path)
    assert code==1,result
    if fault=='existing-output':assert output.read_bytes()==b'previous artifact'
    else:assert not output.exists()
    assert source.read_bytes()==before


def test_owned_lost_snapshot_reply_has_one_request_no_output_or_retry(tmp_path):
    output=tmp_path/'lost.csv'
    with peer([[]]) as ((host,port),sent):
        code,result=invoke(['cgate','--host',host,'--port',port,'database-csv',
            '--project','//CMPLCSV','--columns',*COLUMNS,'--output',output],artifact_dir=tmp_path)
    assert code==1,result
    assert sent==[b'[1] DBGETXML //CMPLCSV\r\n']
    assert not output.exists()


@pytest.mark.parametrize('raw',('56 57 255','56  57','0x38 57','+56 57','256 57'))
def test_source_application_grammar_refuses_unbound_forms_without_mutating(raw):
    root=tree();row=DATA['fixture']['units'][0]
    pp(unit(root,row['path']),'Application').set('Value',raw)
    before=xml(root)
    with pytest.raises(ValueError,match='Application'):
        project_native_xml_unit(before,row['path'],columns=COLUMNS)
    assert xml(root)==before
