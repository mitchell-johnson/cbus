#!/usr/bin/env python3
"""Original C-Gate closed-model NET DB/FILE reconciliation probe.

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
    raw = {'format': 'cbus-native-net-db-reconciliation-v1', 'commands': [],
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
        rows=[
            ('no_project_db','NET LOAD DB'), ('no_project_file','NET LOAD FILE'),
            ('new_a','PROJECT NEW NDBPROBE'),('use_a','PROJECT USE NDBPROBE'),
            ('empty_db','NET LOAD DB'),('empty_list','NET LIST'),('missing_file','NET LOAD FILE'),
            ('create_cni',f'DBCREATENET 254 CniSeed Cni {address}'),
            ('fresh_db','NET LOAD DB'),('fresh_list','NET LIST'),
            ('cni_name','GET //NDBPROBE/254 Name'),('cni_type','GET //NDBPROBE/254 Type'),('cni_options','GET //NDBPROBE/254 Options'),('cni_get','GET //NDBPROBE/254 InterfaceAddress'),('cni_interface','GET //NDBPROBE/254 Interface'),('cni_state','GET //NDBPROBE/254 State'),('nonempty_missing_file','NET LOAD FILE'),('nonempty_missing_file_list','NET LIST'),('cni_xml','DBGETXML //NDBPROBE/254'),
            ('repeat_db','NET LOAD DB'),('repeat_list','NET LIST'),
            ('edit_cni_db',None),('edited_db_xml','DBGETXML //NDBPROBE/254'),
            ('edited_load_db','NET LOAD DB'),('edited_runtime_address','GET //NDBPROBE/254 InterfaceAddress'),
            ('edited_runtime_interface','GET //NDBPROBE/254 Interface'),('edited_runtime_name','GET //NDBPROBE/254 Name'),('edited_runtime_type','GET //NDBPROBE/254 Type'),('edited_runtime_options','GET //NDBPROBE/254 Options'),
            ('restore_cni_db',None),('restored_load_db','NET LOAD DB'),
            ('restored_runtime_address','GET //NDBPROBE/254 InterfaceAddress'),
            ('delete_numeric_runtime','NET DELETE //NDBPROBE/254'),
            ('create_conflicting_runtime',f'NET CREATE 254 Serial {serial} owned=yes'),('conflict_before_load_type','GET //NDBPROBE/254 Type'),('conflict_before_load_options','GET //NDBPROBE/254 Options'),
            ('conflict_load_db','NET LOAD DB'),('conflict_runtime_interface','GET //NDBPROBE/254 Interface'),
            ('conflict_runtime_address','GET //NDBPROBE/254 InterfaceAddress'),('conflict_runtime_type','GET //NDBPROBE/254 Type'),('conflict_runtime_options','GET //NDBPROBE/254 Options'),
            ('create_serial',f'DBCREATENET 253 SerialSeed Serial {serial}'),
            ('create_bridge','DBCREATENET 252 BridgeSeed Bridge 254/p/252'),
            ('sequential_db','NET LOAD DB'),('sequential_list','NET LIST'),
            ('serial_get','GET //NDBPROBE/253 InterfaceAddress'),('serial_interface','GET //NDBPROBE/253 Interface'),('bridge_get','GET //NDBPROBE/252 InterfaceAddress'),('bridge_interface','GET //NDBPROBE/252 Interface'),('bridge_name','GET //NDBPROBE/252 Name'),('bridge_type','GET //NDBPROBE/252 Type'),('bridge_options','GET //NDBPROBE/252 Options'),
            ('all_xml','DBGETXML //NDBPROBE'),
            ('rename_runtime','NET RENAME //NDBPROBE/254 CustomA'),('renamed_list','NET LIST'),('renamed_name','GET //NDBPROBE/CustomA Name'),('renamed_type','GET //NDBPROBE/CustomA Type'),('renamed_address','GET //NDBPROBE/CustomA InterfaceAddress'),('renamed_interface','GET //NDBPROBE/CustomA Interface'),('renamed_options','GET //NDBPROBE/CustomA Options'),
            ('renamed_db','NET LOAD DB'),('renamed_db_list','NET LIST'),
            ('file_save','NET SAVE FILE'),('file_collision','NET LOAD FILE'),('file_collision_list','NET LIST'),('file_remove_first','NET DELETE CustomA'),('file_later_collision','NET LOAD FILE'),('file_later_collision_list','NET LIST'),
            ('extra_runtime',f'NET CREATE Extra Cni {address} owned=yes second=two'),('extra_list','NET LIST'),('extra_name','GET //NDBPROBE/Extra Name'),('extra_type','GET //NDBPROBE/Extra Type'),('extra_address','GET //NDBPROBE/Extra InterfaceAddress'),('extra_interface','GET //NDBPROBE/Extra Interface'),('extra_options','GET //NDBPROBE/Extra Options'),
            ('extra_repeat',f'NET CREATE Extra Cni {address}'),
            ('extra_db_refresh','NET LOAD DB'),('extra_db_list','NET LIST'),('extra_refreshed_options','GET //NDBPROBE/Extra Options'),
            ('save_db','NET SAVE DB'),('saved_xml','DBGETXML //NDBPROBE'),
            ('new_b','PROJECT NEW NDBOTHER'),('use_b','PROJECT USE NDBOTHER'),
            ('create_other','DBCREATENET 10 OtherBridge Bridge 254/p/10'),
            ('use_a_again','PROJECT USE NDBPROBE'),('load_other_explicit','NET LOAD DB NDBOTHER'),
            ('other_list','NET LIST'),('use_loaded_b','PROJECT USE NDBOTHER'),('explicit_b_list','NET LIST'),('explicit_a_while_b','NET LOAD DB NDBPROBE'),('b_list_after_a','NET LIST'),('return_selected_a','PROJECT USE NDBPROBE'),('a_xml_after_other','DBGETXML //NDBPROBE'),
            ('b_xml','DBGETXML //NDBOTHER'),('missing_explicit_db','NET LOAD DB NDBMISS'),
            ('missing_explicit_file','NET LOAD FILE NDBMISS'),
            ('save_a','PROJECT SAVE NDBPROBE'),('close_a','PROJECT CLOSE NDBPROBE'),
            ('closed_a_list','NET LIST'),('load_a','PROJECT LOAD NDBPROBE'),
            ('use_reloaded_a','PROJECT USE NDBPROBE'),('reloaded_db','NET LOAD DB'),
            ('reloaded_list','NET LIST'),('reloaded_xml','DBGETXML //NDBPROBE'),
            ('delete_tag_network','DBDELETE //NDBPROBE/253'),('deleted_db_load','NET LOAD DB'),
            ('deleted_runtime_list','NET LIST'),('deleted_tag_xml','DBGETXML //NDBPROBE'),
            ('help_dbnew','HELP DBNEW'),('clear_database','DBNEW'),('after_dbnew_list','NET LIST'),('after_dbnew_load','NET LOAD DB'),
            ('after_dbnew_load_list','NET LIST'),('after_dbnew_xml','DBGETXML //NDBPROBE'),
            ('new_collision_project','PROJECT NEW NDBCOLL'),('use_collision_project','PROJECT USE NDBCOLL'),
            ('runtime_before_tag',f'NET CREATE 42 Serial {serial}'),
            ('runtime_before_tag_address','GET //NDBCOLL/42 InterfaceAddress'),
            ('tag_after_runtime',f'DBCREATENET 42 CollisionSeed Cni {second_address}'),
            ('tag_after_runtime_load','NET LOAD DB'),('tag_after_runtime_address','GET //NDBCOLL/42 InterfaceAddress'),
            ('remove_collision_tag','DBDELETE //NDBCOLL/42'),('save_refreshed_runtime','NET SAVE DB'),
            ('refreshed_runtime_type_xml','DBGETXML //NDBCOLL/42'),('refreshed_runtime_list','NET LIST'),
            ('final_save_collision','PROJECT SAVE NDBCOLL'),('final_close_collision','PROJECT CLOSE NDBCOLL'),
            ('final_reload_collision','PROJECT LOAD NDBCOLL'),('final_use_collision','PROJECT USE NDBCOLL'),
            ('final_refreshed_type_xml','DBGETXML //NDBCOLL/42'),
            ('clean_dbnew','DBNEW'),('clean_dbnew_xml','DBGETXML //NDBCOLL'),
            ('clean_dbnew_runtime','NET LIST'),('clean_dbnew_load_db','NET LOAD DB'),('clean_dbnew_runtime_after_load','NET LIST'),
        ]
        for label,body in rows:
            if body is None:
                base = next(item for item in raw['commands'] if item['label']=='cni_xml')
                xml = next(line.split('347-',1)[1] for line in base['response'] if '347-<Network>' in line)
                if label=='edit_cni_db': xml=xml.replace('<InterfaceType>Cni</InterfaceType>','<InterfaceType>Serial</InterfaceType>').replace(address,serial)
                else: xml=xml.replace(address,second_address)
                body='DBSETXML //NDBPROBE/254 << ENDPROBE\n'+xml+'\nENDPROBE'
            command(label,body)
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
        value=re.sub(r'(OID=|<OID>)([0-9a-f-]+)(?=$|\s|<)',oid,value)
        value=re.sub(r'(<Modified>)[^<]*(</Modified>)',r'\1%MODIFIED%\2',value)
        value=re.sub(r'(<Hostname>)[^<]*(</Hostname>)',r'\1%HOSTNAME%\2',value)
        value=re.sub(r'(<OSVersion>)[^<]*(</OSVersion>)',r'\1%OS_VERSION%\2',value)
        return value
    fixture={'format':raw['format'],'oracle':{'version':'3.4.0.2001','jar_sha256':server.report['vendor_jar_sha256'],'java_sha256':server.report['java_sha256'],'java_version':server.report['java_version']},
             'source_pins':raw['source_pins'],'closed_model_only':True,'physical_or_windows_acceptance':False,
             'qualifications':['Admin role v2 denies NET operations with420; accepted NET semantics use the fresh Program-role process.','Original DBNEW returned500 and left selected XML unchanged in this closed model; no successful DBNEW clearing claim.','NETGET is not a valid family leaf; GET network properties are captured instead.'],
             'normalization':['Task-owned absent serial path/root becomes %OWNED_WORK%.','Reserved Cni port becomes %FIXTURE_CNI_PORT%.','Native generated OID elements/receipts become stable equality-preserving %OID_N% tokens; no OID allocator parity claimed.','Modified timestamps, Hostname and OSVersion are explicit tokens.','The second reserved Cni endpoint becomes %FIXTURE_SECOND_CNI_PORT%.','Command tags are retained.'],
             'commands':normalize(raw['commands']),
             'cleanup':{k:server.report[k] for k in ['listener_ownership_verified','cleanup_complete','process_exit_confirmed','work_removed']},
             'raw_receipt_sha256':sha(report)}
    with args.fixture.open('x') as target: json.dump(fixture,target,indent=2);target.write('\n')
    print(json.dumps({'raw':str(report),'fixture':str(args.fixture),'raw_sha256':sha(report),'fixture_sha256':sha(args.fixture),'cleanup':fixture['cleanup']}))

if __name__=='__main__': main()
