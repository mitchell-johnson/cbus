"""Public completion report journeys on owned Rust servers; no original or site I/O."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.file_transfer import prepare_upload, upload
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text
from test_cgate_barcode_database_interop import FaultGate, cli, graph
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)
from test_toolkit_database_csv_completion import COLUMNS, DATA, tree, unit, pp

BACKENDS=[('cgate-mock','CBUS_CGATE_MOCK_BIN'),('cmqttd','CBUS_CMQTTD_BIN')]


def selected_binary(variable):
    supplied=os.environ.get(variable)
    if not supplied:
        pytest.skip(f'Select {variable} for the owned CSV family journey')
    binary=Path(supplied).resolve()
    assert binary.is_file() and os.access(binary,os.X_OK)
    return binary


def seed(owner,work,trap):
    root=tree()
    for network in root.find('Project').findall('Network'):
        interface=ET.SubElement(network,'Interface')
        ET.SubElement(interface,'OID').text=str(uuid.uuid4())
        ET.SubElement(interface,'InterfaceType').text='cni'
        ET.SubElement(interface,'InterfaceAddress').text=trap
    source=work/'CMPLCSV-synthetic.xml';source.write_bytes(ET.tostring(root,encoding='utf-8'));source.chmod(0o600)
    for command in ('FILE MKDIR Projects','FILE MKDIR Projects/archived'):
        assert owner.command(command).code==200
    result=upload(prepare_upload('Projects/archived/CMPLCSV.xml',source),owner)
    assert result['upload_completed'] and not result['project_save_requested']
    for command in ('PROJECT RESTORE CMPLCSV CMPLCSV.xml','PROJECT USE CMPLCSV','PROJECT SAVE CMPLCSV'):
        assert owner.command(command).code==200
    return hashlib.sha256(source.read_bytes()).hexdigest()


def snapshot(owner):
    return xml_text(NativeDatabase(owner).get('//CMPLCSV',xml=True))


@contextmanager
def journey(backend,variable,tmp_path):
    binary=selected_binary(variable);work=associated_work(tmp_path,'owned')
    evidence={'format':'cbus-csv-completion-owned-v1','backend':backend,'original_execution':False,
              'physical_acceptance':False,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
              'fixture_sha256':hashlib.sha256(DATA['fixture']['xml'].encode()).hexdigest(),'calls':[],'processes':[]}
    relay=None
    try:
        with no_contact_trap() as trap,owned_backend(backend,binary,work) as (endpoint,record):
            evidence['processes'].append(record)
            with CGateClient(*endpoint,timeout=15) as owner,RecordedGate(endpoint) as relay:
                evidence['provisioned_xml_sha256']=seed(owner,work,trap)
                yield owner,relay,evidence,endpoint
        evidence['closed_graph_trap_contacts']=0
    finally:
        if relay is not None:evidence['wires']=relay.evidence()
        associated_evidence(tmp_path/'csv-completion-evidence.json',evidence)


def read_only(call):
    assert call['commands']==['DBGETXML //CMPLCSV']
    assert call['statuses']==[344]


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
def test_public_csv_completion_all_templates_and_ordered_selection(backend,variable,tmp_path):
    with journey(backend,variable,tmp_path) as (owner,relay,evidence,_endpoint):
        before=snapshot(owner)
        rows=DATA['fixture']['rows']
        units=DATA['fixture']['units']
        cases=[('project',['--project','//CMPLCSV'],rows),
               ('network',['--network','//CMPLCSV/254'],rows),
               ('ordered',['--units',units[-1]['path'],units[0]['path']],
                [rows[0],units[-1]['row'],units[0]['row']])]
        cases.extend(('unit-'+str(i),[row['path']],[rows[0],row['row']])
                     for i,row in enumerate(units))
        for name,flags,expected in cases:
            output=tmp_path/(name+'.csv')
            result,call=cli(relay,evidence['calls'],'database-csv',*flags,
                           '--columns',*COLUMNS,'--output',output)
            read_only(call)
            assert not result['native_database_mutated']
            assert result['report']['unit_count']==len(expected)-1
            assert output.read_bytes()==('\r\n'.join(expected)+'\r\n\r\n').encode()
            assert snapshot(owner)==before
        original=(tmp_path/'project.csv').read_bytes()
        _result,call=cli(relay,evidence['calls'],'database-csv','--project','//CMPLCSV',
                         '--output',tmp_path/'project.csv',expected=1,connections=0)
        assert not call['commands'] and (tmp_path/'project.csv').read_bytes()==original
        assert snapshot(owner)==before


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
@pytest.mark.parametrize('case',('bad-profile','missing-application'))
def test_public_csv_completion_late_refusal_is_atomic(backend,variable,case,tmp_path):
    with journey(backend,variable,tmp_path) as (owner,relay,evidence,_endpoint):
        root=ET.fromstring(snapshot(owner));row=DATA['fixture']['units'][-1]
        target=unit(root,row['path'])
        if case=='bad-profile':target.find('UnitType').text='UNRECOVERED_COMPLETION'
        else:pp(target,'Application').set('Value','56 58')
        response=owner.command_document('DBSETXML '+row['path'],ET.tostring(target,encoding='unicode'))
        assert response.code==301
        before=snapshot(owner);output=tmp_path/'never.csv'
        _result,call=cli(relay,evidence['calls'],'database-csv','--project','//CMPLCSV',
                         '--columns',*COLUMNS,'--output',output,expected=1)
        read_only(call)
        assert not output.exists() and snapshot(owner)==before


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
def test_public_csv_completion_lost_snapshot_is_not_retried(backend,variable,tmp_path):
    with journey(backend,variable,tmp_path) as (owner,_relay,evidence,endpoint):
        before=snapshot(owner)
        with FaultGate(endpoint,'DBGETXML','drop') as fault:
            output=tmp_path/'lost.csv'
            _result,call=cli(fault,evidence['calls'],'database-csv','--project','//CMPLCSV',
                             '--columns',*COLUMNS,'--output',output,expected=1,complete=False)
            assert call['commands']==['DBGETXML //CMPLCSV']
            assert fault.matches==1 and len(fault.rows)==1
            assert bytes.fromhex(fault.rows[0]['lost_backend_terminal_hex']).decode().endswith('344 End XML snippet\r\n')
            assert not output.exists()
        evidence['lost_snapshot_wires']=fault.evidence()
        assert graph(snapshot(owner))==graph(before)
