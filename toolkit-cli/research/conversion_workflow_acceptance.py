"""Owned-loopback public CLI database conversion acceptance (private inputs in place).

This research driver never uses hardware and keeps failed receipts. Run from
repository root with the selected source or installed Python interpreter.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.conversion_mapping import convert_parameters, session_default, render_parameters
from cbus_toolkit.programming import xml_text
from cbus_toolkit.simulator import PCISimulator
from research.convertunit_pairs import Inputs, _equivalent
import shutil
import select

PROJECT = 'WFCONV'
NETWORK = '//WFCONV/254'
SOURCE = NETWORK + '/p/20'
DESTINATION = NETWORK + '/p/21'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def projection(text):
    root = ET.fromstring(text)
    return {'scalars': {c.tag: c.text or '' for c in root if not len(c) and c.tag != 'PP'},
            'pp': [(c.get('Name'), c.get('Value')) for c in root if c.tag == 'PP'],
            'channels': [{x.tag: x.text or '' for x in c if x.tag != 'OID'} for c in root if c.tag == 'OutputChannel']}


class IdleCNI:
    def __init__(self, receipt): self.receipt = receipt
    def __enter__(self):
        self.socket = socket.socket(); self.socket.bind(('127.0.0.1', 0)); self.socket.listen()
        self.socket.settimeout(.1); self.port = self.socket.getsockname()[1]
        self.count = 0; self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()
        return self
    def run(self):
        while not self.stop.is_set():
            try: peer, _ = self.socket.accept()
            except socket.timeout: continue
            except OSError: return
            self.count += 1; peer.close()
    def __exit__(self, *args):
        self.stop.set(); self.socket.close(); self.thread.join(2)
        self.receipt.update(cni_connections=self.count, cni_terminal=not self.thread.is_alive())
        if self.thread.is_alive() or self.count: raise RuntimeError('conversion CNI ownership failed')


@contextmanager
def daemon(binary, specs, scratch, receipt):
    simulator = PCISimulator(profile='captured', command_checksum=True)
    broker = socket.socket(); broker.bind(('127.0.0.1', 0)); broker.listen()
    process = None
    log = (scratch / 'cmqttd.log').open('w+')
    try:
        with simulator.running() as pci:
            project = scratch / 'bridge.xml'
            project.write_text('<Installation><Project><TagName>BRIDGE</TagName><Network><Address>254</Address><TagName>Loopback</TagName></Network></Project></Installation>')
            process = subprocess.Popen([str(binary), '--tcp', f'{pci[0]}:{pci[1]}', '--broker-address', '127.0.0.1', '--broker-port', str(broker.getsockname()[1]), '--broker-disable-tls', '--timesync', '0', '--status-resync', '0', '--project-file', str(project), '--cgate-bind', '127.0.0.1:0', '--cgate-state', str(scratch/'state.json'), '--cgate-unitspec', str(specs)], stdout=subprocess.DEVNULL, stderr=log)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                log.seek(0); match = re.search(r'C-Gate service listening on 127\.0\.0\.1:([0-9]+)', log.read())
                if match: break
                if process.poll() is not None: raise RuntimeError('daemon startup failed')
                time.sleep(.05)
            else: raise TimeoutError('daemon startup')
            port = int(match[1]); receipt['daemon'] = {'pid': process.pid, 'port': port}
            yield port
    finally:
        if process is not None:
            process.terminate()
            try: process.wait(8)
            except subprocess.TimeoutExpired: process.kill(); process.wait(5)
            receipt.setdefault('daemon', {}).update(terminal=True, exit_code=process.returncode)
            if receipt['daemon'].get('port'):
                with socket.socket() as check:
                    check.settimeout(.5)
                    receipt['daemon']['listener_closed'] = check.connect_ex(('127.0.0.1',receipt['daemon']['port'])) != 0
        broker.close(); log.close()
        receipt['pci_wire_chunks'] = len(simulator.wire_log)


class DropReplyProxy:
    """Forward only to owned loopback, then lose one selected command reply."""
    def __init__(self, upstream, trigger, receipt):
        self.upstream=upstream; self.trigger=trigger; self.receipt=receipt
    def __enter__(self):
        self.socket=socket.socket(); self.socket.bind(('127.0.0.1',0)); self.socket.listen(); self.socket.settimeout(.1)
        self.port=self.socket.getsockname()[1]; self.stop=threading.Event(); self.threads=[]
        self.thread=threading.Thread(target=self.run,daemon=True); self.thread.start(); return self
    def run(self):
        while not self.stop.is_set():
            try: downstream,_=self.socket.accept()
            except socket.timeout: continue
            except OSError: return
            thread=threading.Thread(target=self.forward,args=(downstream,),daemon=True); self.threads.append(thread); thread.start()
    def forward(self, downstream):
        with downstream, socket.create_connection(('127.0.0.1',self.upstream),timeout=5) as upstream:
            pending=b''
            while not self.stop.is_set():
                ready,_,_=select.select([downstream,upstream],[],[],.1)
                for peer in ready:
                    data=peer.recv(65536)
                    if not data: return
                    if peer is upstream: downstream.sendall(data); continue
                    pending+=data
                    while b'\n' in pending:
                        line,pending=pending.split(b'\n',1)
                        command=re.sub(rb'^\[[0-9]+\] ',b'',line).strip().decode()
                        self.receipt.setdefault('proxy_commands',[]).append(command)
                        upstream.sendall(line+b'\n')
                        if command==self.trigger and not self.receipt.get('dropped_reply'):
                            # Execute once and consume the response privately, without delivery.
                            answer=b''
                            while not re.search(rb'\[[0-9]+\] 200 [^\r\n]*\r?\n',answer):
                                chunk=upstream.recv(65536)
                                if not chunk: raise RuntimeError('selected command did not finish successfully')
                                answer+=chunk
                            self.receipt.update(dropped_reply=True,dropped_command=command,dropped_reply_bytes=len(answer),dropped_successful_terminal=True)
                            return
    def __exit__(self,*args):
        self.stop.set(); self.socket.close(); self.thread.join(2)
        for thread in self.threads: thread.join(2)
        self.receipt['proxy_terminal']=not self.thread.is_alive() and not any(t.is_alive() for t in self.threads)
        if not self.receipt['proxy_terminal']: raise RuntimeError('fault proxy cleanup failed')


def native_case(directory):
    receipt = json.loads((directory/'raw-receipt.json').read_text())
    wire = json.loads((directory/'raw-wire.json').read_text())
    if receipt['outcome'] != 'passed' or not receipt['bindings_stable'] or receipt['cni_connections']:
        raise ValueError('native capture not admitted')
    row = next(r for r in receipt['cases'] if r['id'] == 'RELDN4->RELDN4A/mode2')
    span = wire[slice(*row['raw_event_span'])]
    conversion = next(i for i,r in enumerate(span) if r['command'].startswith('CONVERTUNIT CONVERT 2 '))
    paths = span[conversion]['command'].split()[3:]
    seeds = [xml_text(type('Reply', (), r)) for path in paths for r in [next(r for r in reversed(span[:conversion]) if r['command']=='DBGETXML '+path)]]
    after = xml_text(type('Reply', (), next(r for r in span[conversion+1:] if r['command']=='DBGETXML '+paths[1])))
    return seeds, after, row


def tree(element):
    return [element.tag,sorted(element.attrib.items()),(element.text or '').strip(),[tree(c) for c in element]]


def run(args, receipt):
    inputs = Inputs(args.specs, args.catalog, args.specs/'ConvertUnitMappingTable.xml')
    source_spec, target_spec = inputs.spec('RELDN4'), inputs.spec('RELDN4A')
    seeds, native_after, native_row = native_case(args.native)
    # Complete source defaults supply fields absent from the old native generator.
    source_values = {name: session_default(p) for name,p in source_spec.parameters.items() if session_default(p)}
    source_values.update(dict(projection(seeds[0])['pp']))
    source_values['UnitAddress']='0x14'
    source_values['Project']='WFCONV00'
    source_values['InterLockingChannel'] = '0x2'
    source_values['RestrikeChannel'] = ' '.join('0x0' for _ in range(source_spec.parameters['RestrikeChannel'].array_size))
    predicted = convert_parameters(inputs.table, 'RELDN4', list(source_values.items()), target_spec, 'RELDN4A')
    malformed = [name for name,value in predicted if not target_spec.parameters[name].validate_value(value)['valid']]
    receipt['profile'] = {'source': inputs.revision('RELDN4'), 'target': inputs.revision('RELDN4A'), 'malformed_mapped': malformed, 'native_get_failures': [r['parameter'] for r in native_row['readback']['get_checks'] if r['code'] != 315]}
    receipt['native_original_model_matches']=convert_parameters(inputs.table,'RELDN4',projection(seeds[0])['pp'],target_spec,'RELDN4A')==projection(native_after)['pp']
    if not receipt['native_original_model_matches']: raise ValueError('raw native model differs')
    if malformed: raise ValueError('profile requires reviewed valid mapped source values: '+','.join(malformed))
    bound = [Path(__file__), Path(sys.modules['research.convertunit_pairs'].__file__), args.cmqttd, args.catalog, args.native/'raw-wire.json', args.native/'raw-receipt.json', *[args.specs/name for name in inputs.hashes if name != 'cbusunits.xml']]
    import cbus_toolkit
    package = Path(cbus_toolkit.__file__).resolve().parent
    package_files=sorted(p for p in package.rglob('*') if p.is_file() and p.suffix in ('.py','.json'))
    bound += package_files
    receipt['package_roster_before']={str(p.relative_to(package)):sha(p) for p in package_files}
    repo=Path(__file__).resolve().parents[2]
    rust_files=[p for p in (repo/'rust').rglob('*') if p.is_file() and 'target' not in p.parts and (p.suffix=='.rs' or p.name in ('Cargo.toml','Cargo.lock'))]
    bound+=rust_files
    receipt['rust_source_qualification']='Source closure fingerprint plus supplied binary hash; this alone does not establish binary build provenance.'
    receipt['bindings_before'] = {str(p.resolve()): sha(p) for p in bound}
    receipt['subprocess_python'] = sys.executable
    receipt['profile']['source_control_changes']={'InterLockingChannel':'0x2','RestrikeChannel':source_values['RestrikeChannel'],'UnitAddress':'0x14','Project':'WFCONV00'}
    receipt['private_copy_scope']='Hash-bound selected specs/includes, mapping and catalogue only, deleted with temporary daemon scratch'
    receipt['fixture_qualification']='Real indexed imported Network/Application58/Group114 via complete DBSETXML; shallow DBADDSAFE Application/Group server gap remains outside this workflow.'
    receipt['native_qualification']='Old captured seed model checked against raw native XML; clean synthetic profile has no new native run. Unchanged dependency-defined subset only.'
    receipt['product_origin'] = str(package)
    with tempfile.TemporaryDirectory(prefix='cbus-public-conversion-', dir='/private/tmp') as temporary, IdleCNI(receipt) as cni:
        specdir = Path(temporary)/'specs'; specdir.mkdir()
        # Rust confines each include/catalogue to its configured directory.
        for name in inputs.hashes:
            shutil.copyfile(args.catalog if name=='cbusunits.xml' else args.specs/name, specdir/name)
        with daemon(args.cmqttd, specdir, Path(temporary), receipt) as port:
            client = CGateClient('127.0.0.1', port, timeout=30).connect()
            def command(text, document=None, codes=(200,301)):
                if cni.count: raise RuntimeError('CNI opened')
                try: reply = client.command(text) if document is None else client.command_document(text, document)
                except CGateError as error: reply = error.response
                receipt.setdefault('provisioning', []).append({'command': text, 'code':reply.code, 'final':reply.final})
                if reply.code not in codes: raise RuntimeError(reply.final)
                return reply
            def cli(*words, selected_port=None, expect_failure=False):
                origin_path=args.output/f'loaded-origins-{len(receipt.get("commands",[]))+1}.json'
                wrapper="import runpy,sys,json,hashlib\ntry:\n runpy.run_module('cbus_toolkit',run_name='__main__',alter_sys=True)\nfinally:\n origins={n:{'origin':m.__file__,'sha256':hashlib.sha256(open(m.__file__,'rb').read()).hexdigest()} for n,m in sys.modules.items() if n.startswith('cbus_toolkit') and getattr(m,'__file__',None)}\n open("+repr(str(origin_path))+",'x').write(json.dumps(origins,indent=2)+'\\n')\n"
                public_argv=[sys.executable,'-m','cbus_toolkit','cgate','--host','127.0.0.1','--port',str(selected_port or port),*words]
                argv = [sys.executable, '-c', wrapper, *public_argv[3:]]
                result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
                receipt.setdefault('commands', []).append({'argv':argv, 'public_argv':public_argv, 'loaded_module_origins':json.loads(origin_path.read_text()), 'exit':result.returncode, 'stdout':result.stdout, 'stderr':result.stderr})
                if bool(result.returncode) != expect_failure: raise RuntimeError('unexpected public CLI status: '+' '.join(words))
                return result
            try:
                command('PROJECT NEW WFCONV'); command('PROJECT USE WFCONV')
                command(f'DBCREATENET 254 Conversion Cni 127.0.0.1:{cni.port}')
                for index, seed in enumerate([*seeds,seeds[0]]):
                    address = 20+index; root = ET.fromstring(seed)
                    for c in list(root):
                        if c.tag in ('OID','PP','OutputChannel'): root.remove(c)
                    fields = {'Address':str(address), 'TagName':f'Fixture{address}', 'Description':f'Owned conversion fixture {address}', 'SerialNumber':f'000000{address:02d}.0000'}
                    for name,value in fields.items():
                        c = root.find(name)
                        if c is None: c = ET.SubElement(root,name)
                        c.text=value
                    values = source_values if index!=1 else {name:session_default(p) for name,p in target_spec.parameters.items() if session_default(p)}
                    values=dict(values)
                    values['UnitAddress']=hex(address); values['Project']='WFCONV00'
                    for name,value in values.items(): ET.SubElement(root,'PP',Name=name,Value=value)
                    command(f'DBADDSAFE {NETWORK} Unit {address} Fixture{address}')
                    current=ET.fromstring(xml_text(command(f'DBGETXML {NETWORK}/p/{address}',codes=(344,))))
                    ET.SubElement(root,'OID').text=current.findtext('OID')
                    command(f'DBSETXML {NETWORK}/p/{address}', ET.tostring(root,encoding='unicode'))
                network_root=ET.fromstring(xml_text(command('DBGETXML '+NETWORK,codes=(344,))))
                application=ET.SubElement(network_root,'Application')
                for name,value in [('OID','11111111-1111-4111-8111-111111111158'),('TagName','Lighting'),('Address','58')]: ET.SubElement(application,name).text=value
                group=ET.SubElement(application,'Group')
                for name,value in [('OID','11111111-1111-4111-8111-111111111114'),('TagName','UnrelatedGroup'),('Address','114')]: ET.SubElement(group,name).text=value
                command('DBSETXML '+NETWORK,ET.tostring(network_root,encoding='unicode'))
                command('PROJECT SAVE WFCONV')
                def closed():
                    state=command('GET '+NETWORK+' InterfaceState', codes=(300,))
                    if state.final != '300 '+NETWORK+': InterfaceState=closed': raise RuntimeError('conversion network open')
                    command('NET LIST WFCONV',codes=(131,200))
                closed()
                cli('database','get-xml','//WFCONV','--output',str(args.output/'before.xml'))
                cli('conversion','check-move',SOURCE,DESTINATION)
                if args.workflow:
                    for number in (20,21): cli('unit','--lock-address',NETWORK,'--source','/db'+NETWORK+'/p/'+str(number),'export',str(args.output/f'before-{number}-pp.json'))
                    cli('conversion','plan-move',SOURCE,DESTINATION,'--backup-project','WFCONVB1','--spec-dir',str(specdir),'--exclusive-project','--output',str(args.output/'plan.json'))
                    apply=('conversion','apply-move','--plan',str(args.output/'plan.json'),'--journal',str(args.output/'journal.json'),'--spec-dir',str(specdir),'--exclusive-project')
                    if args.stale_group:
                        with DropReplyProxy(port,'NEVER_MATCH_OWNED_STALE_TEST',receipt) as proxy:
                            (args.output/'plan.json').unlink()
                            cli('conversion','plan-move',SOURCE,DESTINATION,'--backup-project','WFCONVB1','--spec-dir',str(specdir),'--exclusive-project','--output',str(args.output/'plan.json'),selected_port=proxy.port)
                            network=ET.fromstring(xml_text(command('DBGETXML '+NETWORK,codes=(344,))))
                            network.find('Application/Group/TagName').text='ReviewedGroupChanged'
                            command('DBSETXML '+NETWORK,ET.tostring(network,encoding='unicode'))
                            observed=ET.fromstring(xml_text(command('DBGETXML '+NETWORK,codes=(344,))))
                            failed=cli(*apply,selected_port=proxy.port,expect_failure=True)
                            backup=command('DBGETXML //WFCONVB1',codes=(401,))
                            receipt['stale_checks']={'candidate_visible':tree(network)==tree(observed),'literal_change':observed.findtext('Application/Group/TagName')=='ReviewedGroupChanged','changed_error':'changed' in failed.stderr.lower(),'no_journal':not (args.output/'journal.json').exists(),'backup_absent':backup.code==401,'no_mutation':all(not c.startswith(('CONVERTUNIT CONVERT','PROJECT SAVE','PROJECT COPY')) for c in receipt['proxy_commands'])}
                            if not all(receipt['stale_checks'].values()): raise RuntimeError('stale-group rejection evidence differs')
                            closed(); receipt['outcome']='passed'; return
                    if args.fault:
                        trigger='CONVERTUNIT CONVERT 2 '+SOURCE+' '+DESTINATION if args.fault=='convert' else 'PROJECT SAVE WFCONV'
                        with DropReplyProxy(port,trigger,receipt) as proxy:
                            # Plan must bind the proxy endpoint used for apply/recovery.
                            (args.output/'plan.json').unlink()
                            cli('conversion','plan-move',SOURCE,DESTINATION,'--backup-project','WFCONVB1','--spec-dir',str(specdir),'--exclusive-project','--output',str(args.output/'plan.json'),selected_port=proxy.port)
                            cli(*apply,selected_port=proxy.port,expect_failure=True)
                            prior=len(receipt['proxy_commands'])
                            recovered=cli('conversion','recover','--journal',str(args.output/'journal.json'),selected_port=proxy.port)
                            recovery=json.loads(recovered.stdout); journal=json.loads((args.output/'journal.json').read_text())
                            expected_phase='convert-possible' if args.fault=='convert' else 'save-possible'
                            recovery_commands=receipt['proxy_commands'][prior:]
                            receipt['fault_checks']={'drop':receipt.get('dropped_reply') is True and receipt.get('dropped_command')==trigger and receipt.get('dropped_successful_terminal') is True,'phase':journal['phase']==expected_phase,'observed_converted':recovery['disposition']=='observed-converted','uncertain_save':recovery['project_saved'] is None and recovery['persistence_verified'] is False,'no_replay':recovery['replay_authorized'] is False and all(not c.startswith(('CONVERTUNIT CONVERT','PROJECT SAVE','PROJECT COPY','PROJECT LOAD','PROJECT CLOSE')) for c in recovery_commands),'one_convert':sum(c.startswith('CONVERTUNIT CONVERT') for c in receipt['proxy_commands'])==1}
                            mutations=lambda: [c for c in receipt['proxy_commands'] if c.startswith(('CONVERTUNIT CONVERT','PROJECT SAVE','PROJECT COPY'))]
                            prior_mutations=list(mutations())
                            cli(*apply,selected_port=proxy.port,expect_failure=True)
                            alternate=list(apply); alternate[alternate.index('--journal')+1]=str(args.output/'alternate-journal.json')
                            cli(*alternate,selected_port=proxy.port,expect_failure=True)
                            receipt['fault_checks']['repeat_no_mutation']=mutations()==prior_mutations
                            receipt['fault_checks']['backup_verified_fresh']=recovery.get('backup_verified_fresh') is True
                            receipt['fault_checks']['source_removed']=recovery.get('source_removed') is True
                            live=projection(xml_text(command('DBGETXML '+DESTINATION,codes=(344,))))
                            receipt['fault_checks']['independent_ordered_pp']=live['pp']==predicted
                            receipt['fault_checks']['native_channels']=live['channels']==projection(native_after)['channels']
                            fresh=recovery['observation']['fresh_pp']['parameters']
                            receipt['fault_checks']['independent_full_get']=all(_equivalent(p,dict(predicted).get(n,session_default(p)),fresh.get(n)) for n,p in target_spec.parameters.items())
                            backup=ET.fromstring(xml_text(command('DBGETXML //WFCONVB1',codes=(344,))))
                            backup.find('Project/Address').text='WFCONV'
                            receipt['fault_checks']['independent_backup']=tree(backup)==tree(ET.parse(args.output/'before.xml').getroot())
                            closed()
                            if not all(receipt['fault_checks'].values()): raise RuntimeError('injected failure evidence differs')
                            receipt['fault_acceptance']=True
                            receipt['outcome']='passed'
                            return
                    else:
                        applied=cli(*apply)
                        successful=json.loads(applied.stdout); journal=json.loads((args.output/'journal.json').read_text())
                        if journal['phase']!='complete' or successful['project_saved'] is not True or successful['fresh_database_verified'] is not True or len(journal['observations'])!=2 or not all(o['matched'] for o in journal['observations']): raise RuntimeError('apply persistence unverified')
                    cli('conversion','recover','--journal',str(args.output/'journal.json'))
                else:
                    cli('conversion','move',SOURCE,DESTINATION,'--backup-project','WFCONVB1')
                if not args.workflow:
                    for action in ('save','close','load'): cli('project',action,'WFCONV')
                cli('database','get-xml','//WFCONV','--output',str(args.output/'reopened.xml'))
                cli('database','get-xml','//WFCONVB1','--output',str(args.output/'backup.xml'))
                cli('unit','--lock-address',NETWORK,'--source','/db'+DESTINATION,'export',str(args.output/'reopened-pp.json'))
                actual = projection(xml_text(command('DBGETXML '+DESTINATION,codes=(344,))))
                receipt['ordered_pp_matches_model'] = actual['pp']==predicted
                before=ET.parse(args.output/'before.xml').getroot()
                backup=ET.parse(args.output/'backup.xml').getroot()
                backup.find('Project/Address').text='WFCONV'
                receipt['backup_matches_original']=tree(before)==tree(backup)
                after=ET.parse(args.output/'reopened.xml').getroot()
                bn=before.find('Project/Network'); an=after.find('Project/Network')
                receipt['source_removed']=not any(u.findtext('Address')=='20' for u in an.findall('Unit'))
                untouched=lambda n:[tree(c) for c in n if c.tag!='Unit' or c.findtext('Address') not in ('20','21')]
                receipt['unrelated_tree_preserved']=untouched(bn)==untouched(an)
                unrelated=next(u for u in an.findall('Unit') if u.findtext('Address')=='22')
                reference={p.get('Name'):p.get('Value') for p in unrelated.findall('PP')}
                receipt['unrelated_reference_present']=reference['Application'].split()[0]=='0x3a' and reference['GroupAddress'].split()[0]=='0x72'
                app=an.find('Application')
                receipt['unrelated_reference_present']=receipt['unrelated_reference_present'] and app.findtext('Address')=='58' and any(g.findtext('Address')=='114' for g in app.findall('Group'))
                receipt['unrelated_application_preserved']=tree(app)==tree(bn.find('Application'))
                original_destination=next(u for u in bn.findall('Unit') if u.findtext('Address')=='21')
                expected_identity={k:original_destination.findtext(k) for k in ('TagName','Address','Description','UnitType','UnitName','SerialNumber','FirmwareVersion','CatalogNumber')}
                receipt['destination_identity_preserved']=all(actual['scalars'].get(k)==v for k,v in expected_identity.items() if v is not None)
                receipt['channels_match_native']=actual['channels']==projection(native_after)['channels']
                fresh=json.loads((args.output/'reopened-pp.json').read_text())['parameters']
                receipt['full_get_matches_model'] = all(_equivalent(p,dict(predicted).get(n,session_default(p)),fresh.get(n)) for n,p in target_spec.parameters.items())
                closed()
                native = projection(native_after)
                changed={'InterLockingChannel','RestrikeChannel','UnitAddress','Project'}
                rules={p.new:p for p in inputs.table.find('RELDN4','RELDN4A').pairs}
                unchanged=[n for n,_ in native['pp'] if n not in changed and not (n in rules and (set(rules[n].old)&changed or any(r.param2 in changed for r in rules[n].rules)))]
                receipt['native_unchanged_fields']=unchanged
                receipt['native_unchanged_matches']=all(dict(actual['pp']).get(n)==dict(native['pp'])[n] for n in unchanged)
                required=('ordered_pp_matches_model','full_get_matches_model','backup_matches_original','source_removed','unrelated_tree_preserved','destination_identity_preserved','channels_match_native','unrelated_reference_present','unrelated_application_preserved')
                if not all(receipt[k] for k in required): raise RuntimeError('independent acceptance failed: '+','.join(k for k in required if not receipt[k]))
                receipt['outcome']='passed'
                receipt['native_original_model_matches']=convert_parameters(inputs.table,'RELDN4',projection(seeds[0])['pp'],target_spec,'RELDN4A')==native['pp']
                if not receipt['native_original_model_matches'] or not receipt['native_unchanged_matches']: raise RuntimeError('independent native binding differs')
            finally:
                for project in ('WFCONV','WFCONVB1'):
                    for action in ('CLOSE','DELETE'):
                        try: command(f'PROJECT {action} {project}', codes=(200,401,408))
                        except Exception as error: receipt.setdefault('cleanup_errors',[]).append(str(error))
                client.close()
        receipt['cni_connections']=cni.count
    receipt['cni_terminal']=not cni.thread.is_alive()
    receipt['bindings_after']={str(p.resolve()):sha(p) for p in bound}
    receipt['bindings_stable']=receipt['bindings_before']==receipt['bindings_after']
    if not receipt['bindings_stable']: raise RuntimeError('input/source binding changed')


def main():
    p=argparse.ArgumentParser(); p.add_argument('--workflow',action='store_true'); p.add_argument('--stale-group',action='store_true'); p.add_argument('--fault',choices=('convert','save'));  p.add_argument('--cmqttd',type=Path,required=True); p.add_argument('--specs',type=Path,required=True); p.add_argument('--catalog',type=Path,required=True); p.add_argument('--native',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); args.output.mkdir(mode=0o700)
    receipt={'format':'cbus-public-conversion-acceptance-v1','outcome':'failed'}
    try: run(args,receipt)
    except BaseException as error: receipt.update(outcome='failed',error_type=type(error).__name__,error=str(error)); raise
    finally:
        if 'bindings_before' in receipt:
            receipt['bindings_after']={p:sha(p) for p in receipt['bindings_before']}
            package=Path(receipt['product_origin'])
            receipt['package_roster_after']={str(p.relative_to(package)):sha(p) for p in sorted(package.rglob('*')) if p.is_file() and p.suffix in ('.py','.json')}
            receipt['bindings_stable']=receipt['bindings_before']==receipt['bindings_after'] and receipt['package_roster_before']==receipt['package_roster_after']
            if not receipt['bindings_stable'] or receipt.get('cleanup_errors') or receipt.get('cni_connections')!=0 or receipt.get('cni_terminal') is not True or receipt.get('daemon',{}).get('listener_closed') is not True or receipt.get('daemon',{}).get('terminal') is not True: receipt['outcome']='failed'
        (args.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    if receipt['outcome']!='passed': raise RuntimeError('acceptance finalization failed')

if __name__=='__main__': main()
