#!/usr/bin/env python3
"""Original C-Gate closed-model NET SAVE DB materialization probe.

Uses only a newly owned LocalCGate child and synthetic disposable projects.
Raw captures stay private; the fixture records explicit OID/port normalization.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'toolkit-cli/research'))
from local_cgate import LocalCGate


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vendor', type=Path, required=True)
    parser.add_argument('--java', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    raw = {'format': 'cbus-native-net-save-db-materialization-v1', 'commands': [],
           'closed_model_only': True, 'physical_or_windows_acceptance': False,
           'source_pins': {str(Path(__file__).relative_to(ROOT)): sha(Path(__file__)),
                           'toolkit-cli/research/local_cgate.py': sha(ROOT/'toolkit-cli/research/local_cgate.py')}}
    report = args.output/'raw.json'
    report.touch(mode=0o600, exist_ok=False)
    server = LocalCGate(args.vendor, java=args.java)
    reserved = socket.socket()
    reserved.bind(('127.0.0.1', 0))
    port = reserved.getsockname()[1]
    address = f'127.0.0.1:{port}'
    reserved_second = socket.socket()
    reserved_second.bind(('127.0.0.1', 0))
    second_address = f'127.0.0.1:{reserved_second.getsockname()[1]}'
    serial = str(server.work/'tmp/absent-serial-interface')
    peer = stream = None
    def checkpoint():
        report.write_text(json.dumps(raw, indent=2)+'\n')
    def command(label, body):
        tag = f'probe{len(raw["commands"])}'
        stream.write(f'[{tag}] {body}\r\n'.encode())
        rows=[]
        while True:
            row=stream.readline().decode().rstrip('\r\n')
            if not row: raise EOFError(label)
            rows.append(row)
            if re.match(r'^\['+tag+r'\] \d{3} ',row): break
        raw['commands'].append({'label':label,'command':body,'response':rows})
        checkpoint()
        return rows
    try:
        server.start()
        peer=socket.create_connection(('127.0.0.1',server.port),timeout=10)
        peer.settimeout(10)
        stream=peer.makefile('rwb',buffering=0)
        raw['greeting']=stream.readline().decode().rstrip('\r\n')
        raw['synthetic_interfaces']={'cni_reserved_socket':address,'serial_absent_owned_path':serial,'second_cni_reserved_socket':second_address}
        def run(label, body): return command(label, body)
        def xml(label, addr):
            rows=run(label,'DBGETXML '+addr)
            return '\n'.join(r.split('347-',1)[1] for r in rows if '347-' in r) or None
        run('new','PROJECT NEW NSAVE');run('use','PROJECT USE NSAVE')
        run('tag254',f'DBCREATENET 254 OriginalTag Cni {address}')
        original=xml('tag254-before','//NSAVE/254')
        run('baseline-project-save','PROJECT SAVE NSAVE')
        run('runtime-conflict',f'NET CREATE 254 Serial {serial} flag duplicate=one duplicate=two')
        run('runtime42',f'NET CREATE 42 Cni {address}')
        run('runtime0254',f'NET CREATE 0254 Cni {address}')
        run('runtime256',f'NET CREATE 256 Cni {address}')
        run('runtime255',f'NET CREATE 255 Cni {address}')
        run('runtimehex',f'NET CREATE 0xff Cni {address}')
        run('runtime-flag-only',f'NET CREATE FlagOnly Cni {address} flag')
        run('runtime-duplicates',f'NET CREATE Duplicates Cni {address} duplicate=one duplicate=two')
        run('runtime-escaped-name',f'NET CREATE EscapedName Cni {address} a&b=x<y')
        run('runtime-escaped',f'NET CREATE Escaped Cni {address} escaped=hello\\world')
        run('runtimecustom',f'NET CREATE CustomA Cni {address} flag duplicate=one duplicate=two escaped=hello\\world')
        run('runtime-case-variant',f'NET CREATE Customa Cni {address}')
        run('save1','NET SAVE DB');first=xml('project-save1','//NSAVE')
        run('save2','NET SAVE DB');second=xml('project-save2','//NSAVE')
        raw['repeated_xml_identical']=first==second
        import xml.etree.ElementTree as ET
        tree=ET.fromstring(second)
        networks=tree.findall('.//Network')
        raw['network_summaries']=[{child.tag:child.text for child in n if len(child)==0} for n in networks]
        for n in networks:
            name=n.findtext('Address');oid=n.findtext('OID')
            xml('read-named-'+name,'//NSAVE/'+name)
            if oid:
                xml('read-oid-'+name,'!'+oid)
                run('get-oid-number-'+name,'GET !'+oid+' NetworkNumber')
            run('get-named-number-'+name,'GET //NSAVE/'+name+' NetworkNumber')
            run('get-options-'+name,'GET //NSAVE/'+name+' Options')
        run('close-unsaved','PROJECT CLOSE NSAVE');run('load-unsaved','PROJECT LOAD NSAVE');run('use-reloaded','PROJECT USE NSAVE')
        xml('project-after-unsaved-close','//NSAVE')
        run('list-after-unsaved-close','NET LIST')
        run('runtime-conflict-after-close',f'NET CREATE 254 Serial {serial} flag duplicate=one duplicate=two')
        for name in ['42','0254','256','255','0xff','CustomA']:run('runtime-recreate-'+name,f'NET CREATE {name} Cni {address}')
        run('save-after-close','NET SAVE DB');xml('project-after-second-materialization','//NSAVE')
        run('project-save','PROJECT SAVE NSAVE');run('project-close','PROJECT CLOSE NSAVE');run('project-load','PROJECT LOAD NSAVE');run('project-use','PROJECT USE NSAVE')
        persisted=xml('project-persisted','//NSAVE')
        persisted_tree=ET.fromstring(persisted)
        custom=next((n for n in persisted_tree.findall('.//Network') if n.findtext('Address')=='CustomA'),None)
        if custom is not None:
            oid=custom.findtext('OID')
            run('help-dbset','HELP DBSET')
            run('set-custom-name','DBSET //NSAVE/CustomA/TagName ChangedCustom')
            xml('custom-after-name','//NSAVE/CustomA')
            run('set-oid-name','DBSET !'+oid+'/TagName OidChanged')
            xml('custom-after-oid','!'+oid)
            updated=ET.tostring(custom,encoding='unicode').replace('<TagName>nCustomA</TagName>','<TagName>XmlChanged</TagName>')
            run('set-custom-xml','DBSETXML //NSAVE/CustomA << ENDPROBE\n'+updated+'\nENDPROBE')
            xml('custom-after-xml','//NSAVE/CustomA')
            run('delete-custom-oid','DBDELETE !'+oid);xml('custom-after-oid-delete','//NSAVE/CustomA');xml('whole-after-oid-delete','//NSAVE')
            run('delete-custom-named','DBDELETE //NSAVE/CustomA');xml('whole-after-named-delete','//NSAVE')
        run('delete-0254','DBDELETE //NSAVE/0254');xml('0254-after-delete','//NSAVE/0254')
        run('delete-hex','DBDELETE //NSAVE/0xff');xml('hex-after-delete','//NSAVE/0xff')
        run('get-number-field-before','DBGET //NSAVE/42/NetworkNumber')
        run('set-number-decimal255','DBSET //NSAVE/42/NetworkNumber 255');xml('number-decimal255-xml','//NSAVE/42')
        run('get-number-field-decimal','DBGET //NSAVE/42/NetworkNumber')
        run('set-number-hex','DBSET //NSAVE/42/NetworkNumber 0xff');xml('number-hex-xml','//NSAVE/42')
        run('get-number-field-hex','DBGET //NSAVE/42/NetworkNumber')
        run('save-after-number-edit','NET SAVE DB');xml('number-after-save','//NSAVE/42')
        run('project-final','PROJECT SAVE NSAVE')
    except BaseException as error:
        raw['failure']={'type':type(error).__name__,'message':str(error)}
        raise
    finally:
        if stream is not None: stream.close()
        if peer is not None: peer.close()
        reserved.close()
        reserved_second.close()
        server.close()
        raw['owned_process']=server.report
        checkpoint()
    assert server.report['cleanup_complete'] and server.report['listener_ownership_verified']
    # Normalize exact raw data using an explicit per-capture, equality-preserving
    # OID map. This fixture is a normalized original model capture, not live bytes.
    oids={}
    def oid(match):
        value=match[2]
        if value not in oids: oids[value]=f'%OID_{len(oids)+1}%'
        return match[1]+oids[value]
    def normalize(value):
        if isinstance(value,dict): return {k:normalize(v) for k,v in value.items()}
        if isinstance(value,list): return [normalize(v) for v in value]
        if not isinstance(value,str): return value
        value=value.replace(str(server.work.resolve()),'%OWNED_WORK%').replace(str(server.work),'%OWNED_WORK%')
        value=value.replace(address,'127.0.0.1:%FIXTURE_CNI_PORT%').replace(second_address,'127.0.0.1:%FIXTURE_SECOND_CNI_PORT%')
        def uuid_token(match):
            token=match[0]
            if token not in oids: oids[token]=f'%OID_{len(oids)+1}%'
            return oids[token]
        value=re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',uuid_token,value)
        value=re.sub(r'(<Modified>)[^<]*(</Modified>)',r'\1%MODIFIED%\2',value)
        value=re.sub(r'(<Hostname>)[^<]*(</Hostname>)',r'\1%HOSTNAME%\2',value)
        value=re.sub(r'(<OSVersion>)[^<]*(</OSVersion>)',r'\1%OS_VERSION%\2',value)
        return value
    fixture={'format':raw['format'],'oracle':{'version':'3.4.0.2001','jar_sha256':server.report['vendor_jar_sha256'],'java_sha256':server.report['java_sha256'],'java_version':server.report['java_version']},
             'source_pins':raw['source_pins'],'closed_model_only':True,'physical_or_windows_acceptance':False,
             'qualifications':['Fresh owned Program-role Java11 original process; raw boundary probe uses system Python, no Toolkit package imports.','All exact failed commands are retained; no hardware or Windows acceptance.'],
             'normalization':['Task-owned absent serial path/root becomes %OWNED_WORK%.','Reserved Cni port becomes %FIXTURE_CNI_PORT%.','Native generated OID elements/receipts become stable equality-preserving %OID_N% tokens; no OID allocator parity claimed.','Modified timestamps, Hostname and OSVersion are explicit tokens.','The second reserved Cni endpoint becomes %FIXTURE_SECOND_CNI_PORT%.','All UUID appearances including OID selectors/scalar summaries use the same equality-preserving OID map. Command tags are retained.'],
             'commands':normalize(raw['commands']),
             'network_summaries':normalize(raw.get('network_summaries',[])),
             'repeated_xml_identical':raw.get('repeated_xml_identical'),
             'cleanup':{k:server.report[k] for k in ['listener_ownership_verified','cleanup_complete','process_exit_confirmed','work_removed']},
             'raw_receipt_sha256':sha(report)}
    with args.fixture.open('x') as target: json.dump(fixture,target,indent=2);target.write('\n')
    print(json.dumps({'raw':str(report),'fixture':str(args.fixture),'raw_sha256':sha(report),'fixture_sha256':sha(args.fixture),'cleanup':fixture['cleanup']}))

if __name__=='__main__': main()
