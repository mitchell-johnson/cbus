"""DLT tweaker public subprocesses on owned mock/daemon and synthetic profiles."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import pytest
from cbus_toolkit.cgate import CGateClient
from test_cgate_named_database_interop import associated_work, owned_backend, no_contact_trap, RecordedGate, associated_evidence
from test_cgate_barcode_database_interop import FaultGate, selected_binary, graph
import test_cgate_toolkit_tweaker_interop as create
import test_cgate_toolkit_tweaker_lifecycle_interop as replace
from test_toolkit_conversion_dlt import profile_files, VECTOR as RULES

BACKENDS = create.BACKENDS
VECTOR = json.loads((Path(__file__).resolve().parents[2]/'rust/testdata/vectors/cgate_toolkit_tweaker_dlt_wire.json').read_text())
CASES = [row for row in RULES['cases'] if row['id'] != 'neo-classic-three-preserved']
# The literal KEYB2/Saturn model oracle also applies to the catalogue's KEYBIR2
# alias. Only the source identity and destination profile change; this is not
# derived from the implementation's reported expected values.
CASES.append({**next(row for row in RULES['cases'] if row['id'] == 'saturn-pcx'),
              'id': 'keybir2-literal-keyb2-catalogue-alias',
              'source': 'KEYBIR2', 'target': 'KEYDL4'})


@contextmanager
def journey(backend, variable, tmp_path, source, target, *, auth_file=None):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'backend')
    specs = tmp_path/'synthetic-specs'
    profile = profile_files(specs, source, target)
    flag = '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec'
    evidence = {'format':'cbus-toolkit-dlt-tweaker-owned-v1','backend':backend,'original_execution':False,
                'physical_acceptance':False,'binary_sha256':create.digest(binary.read_bytes()),
                'specifications':{p.name:create.digest(p.read_bytes()) for p in specs.iterdir()},
                'calls':[],'processes':[],'wires':[]}
    relay = None
    try:
        with no_contact_trap() as trap:
            with owned_backend(backend, binary, work, auth_file=auth_file, extra_args=(flag, specs)) as (endpoint, process):
                evidence['processes'].append(process)
                with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                    if auth_file is not None:
                        assert owner.command('LOGIN '+auth_file.read_text().splitlines()[0]).code == 200
                    evidence['roles'] = create.seed(owner, work, trap, source, profile)
                    yield owner, relay, evidence, specs, profile, endpoint
            evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None: evidence['wires'] = relay.evidence()
        associated_evidence(tmp_path/'toolkit-tweaker-dlt-evidence.json', evidence)


def check_expected(case, actual):
    for name,value in case['expected'].items():
        assert actual[name] == value, (name, actual)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
@pytest.mark.parametrize('operation', ['create','replace'])
@pytest.mark.parametrize('case', CASES, ids=lambda row:row['id'])
def test_public_dlt_tweaker_profile_create_and_replace(backend, variable, operation, case, tmp_path):
    source,target = case['source'],case['target']
    with journey(backend, variable, tmp_path, source, target) as (owner, relay, evidence, specs, profile, _):
        # The reflection vector's brightness3 model is distinct from the
        # default fixture2; restore that value through the ordinary PP source.
        if case.get('source_values'):
            from cbus_toolkit.programming import Programmer
            with Programmer(owner).load('//WFTEST/11','/db//WFTEST/11/p/20') as session:
                for name,value in case['source_values'].items(): session.set(name,value)
                session.save_to_source()
        assert owner.command('DBSET //WFTEST/11/p/20/Description copied & Ω description').code == 200
        before, original, other = create.document(owner), create.document(owner,'//WFTEST/11/p/20'), create.document(owner,'//OTHER')
        journal = tmp_path/'attempt.json'
        run = create.cli if operation == 'create' else replace.cli
        preview, call = run(relay,evidence,specs,profile,source,target)
        assert preview['phase'] == 'preview_complete' and create.document(owner) == before
        assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PP SAVE','PROJECT COPY','PROJECT SAVE')) for c in call['commands'])
        assert preview['plan_sha256'] == create.plan_digest(preview['plan'])
        assert preview['plan']['tweaker']['model_context']['inherited_conversion_hooks_called'] is False
        flags = create.apply_flags(preview) if operation == 'create' else replace.flags(preview,journal)
        final, call = run(relay,evidence,specs,profile,source,target,extra=flags)
        assert final['phase'] == 'complete' and final['accepted'] and not final['outcome_uncertain']
        assert final['plan_sha256'] == preview['plan_sha256'] == create.plan_digest(final['plan'])
        check_expected(case, final['verified_expected_parameters'] if operation == 'create' else final['creation']['verified_expected_parameters'])
        commands = call['commands']
        assert sum(c.startswith('DBADDSAFE ') for c in commands) == sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands) == 1
        set_rows = [c for c in commands if c.startswith('PP SET ')]
        for name in case.get('not_written',[]): assert not any(re.search(r' '+re.escape(name)+r' ',c) for c in set_rows)
        for name in ('LabelFlavourLSB','LabelFlavourMSB'):
            matches = [c for c in set_rows if ' '+name+' ' in c]
            assert len(matches) == 1 and matches[0].endswith(' '+name+' '+VECTOR['label_wire_tail'])
        oid = final['oid'] if operation == 'create' else final['destination_oid']
        assert oid not in before and oid != ET.fromstring(original).findtext('OID')
        unit = ET.fromstring(create.document(owner, '//WFTEST/11/p/'+('21' if operation == 'create' else '20')))
        assert unit.findtext('OID') == oid and unit.findtext('UnitType') == target and unit.findtext('FirmwareVersion') == '2.1.00'
        after = create.document(owner)
        if operation == 'create':
            assert create.document(owner,'//WFTEST/11/p/20') == original
            create.unchanged_after_removing_new(before,after,oid)
            assert not any(final[k] for k in ('source_deleted','project_saved','readdressed','automatic_retries'))
        else:
            assert final['source_deleted'] and final['readdressed'] and final['project_saved'] and final['reopened']
            assert not final['full_replacement_parity'] and not final['rollback_performed']
            assert graph(replace.remove_unit(before,ET.fromstring(original).findtext('OID'))) == graph(replace.remove_unit(after,oid))
            assert graph(replace.normalized_backup(create.document(owner,'//BACKUP'))) == graph(before)
            for name in ('TagName','UnitName','SerialNumber','Description'):
                assert unit.findtext(name) == ET.fromstring(original).findtext(name)
            assert unit.findtext('CatalogNumber') == 'TARGET'
            sequence = VECTOR['replace_ordered_once']
            assert [commands.index(c) for c in sequence] == sorted(commands.index(c) for c in sequence)
            assert [call['statuses'][commands.index(c)] for c in sequence] == VECTOR['replace_statuses']
            assert all(commands.count(c) == 1 for c in sequence)
            retained = journal.read_bytes()
            recovered, read = replace.cli(relay,evidence,recovery=True,extra=('--journal',str(journal)))
            assert recovered['disposition'] == 'observed_replaced' and recovered['persistence_verified']
            assert not recovered['replay_authorized'] and create.document(owner) == after and journal.read_bytes() == retained
            assert all(c.startswith(tuple(VECTOR['recovery_prefixes'])) for c in read['commands'])
        assert create.document(owner,'//OTHER') == other
        evidence['snapshots'] = dict(before=before,after=after,source_before=original,other=other)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
@pytest.mark.parametrize('operation,verb',[('create','PP SAVE_TO_SOURCE'),('replace','DBDELETE')],ids=['lost-create-save','lost-replace-delete'])
def test_public_dlt_tweaker_unknown_receipt_never_replays(backend,variable,operation,verb,tmp_path):
    with journey(backend,variable,tmp_path,'KEYML5','KEYDL4') as (owner,_,evidence,specs,profile,endpoint):
        before = create.document(owner)
        journal = tmp_path/'attempt.json'
        with FaultGate(endpoint,verb,'drop') as relay:
            run = create.cli if operation == 'create' else replace.cli
            preview,_ = run(relay,evidence,specs,profile,'KEYML5','KEYDL4')
            flags = create.apply_flags(preview) if operation == 'create' else replace.flags(preview,journal)
            failed,call = run(relay,evidence,specs,profile,'KEYML5','KEYDL4',extra=flags,expected=1)
            failed = create.state(failed) if operation == 'create' else replace.state(failed)
            assert failed['outcome_uncertain'] and not failed['accepted'] and not failed['automatic_retries']
            assert call['commands'][-1].startswith(verb+' ') and sum(c.startswith(verb+' ') for c in call['commands']) == 1
            assert not any(c.startswith(('PROJECT SAVE ','PROJECT CLOSE ','PROJECT LOAD ')) for c in call['commands'])
            faults = [r for r in relay.evidence() if r.get('fault')]
            assert len(faults) == 1
            row = faults[0]; fault = row['fault']
            assert re.fullmatch(r'\['+re.escape(fault['tag'])+r'\] 200 [^\r\n]*\r\n',bytes.fromhex(row['lost_backend_terminal_hex']).decode())
            assert bytes.fromhex(row['forwarded_request_hex']).decode().splitlines().count('['+fault['tag']+'] '+fault['command']) == 1
            if operation == 'replace':
                retained = journal.read_bytes()
                recovered,read = replace.cli(relay,evidence,recovery=True,extra=('--journal',str(journal)))
                assert not recovered['replay_authorized'] and not recovered['persistence_verified']
                assert all(c.startswith(tuple(VECTOR['recovery_prefixes'])) for c in read['commands'])
                assert journal.read_bytes() == retained
            evidence['fault_wires'] = relay.evidence()
        after = create.document(owner)
        if operation == 'create': create.unchanged_after_removing_new(before,after,failed['oid'])
        else:
            oid = failed['creation']['oid']
            assert graph(replace.remove_unit(before,evidence['roles']['source'])) == graph(replace.remove_unit(after,oid))
        evidence['snapshots'] = dict(before=before,after=after)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
def test_public_dlt_tweaker_stale_plan_and_source_firmware_refuse(backend,variable,tmp_path):
    with journey(backend,variable,tmp_path,'KEYM2','KEYBL5') as (owner,relay,evidence,specs,profile,_):
        preview,_ = create.cli(relay,evidence,specs,profile,'KEYM2','KEYBL5')
        assert owner.command('DBSET //WFTEST/11/p/20/Description changed').code == 200
        before = create.document(owner)
        failed,call = create.cli(relay,evidence,specs,profile,'KEYM2','KEYBL5',expected=1,extra=create.apply_flags(preview))
        assert 'Fresh plan differs' in failed['error'] and not create.state(failed)['writes']
        assert not any(c.startswith(('DBADD','DBSET','PP SAVE')) for c in call['commands']) and create.document(owner) == before
        assert owner.command('DBSET //WFTEST/11/p/20/FirmwareVersion 2.5.01').code == 200
        before = create.document(owner)
        failed,call = create.cli(relay,evidence,specs,profile,'KEYM2','KEYBL5',expected=1)
        assert 'firmware' in failed['error'] and not create.state(failed)['writes']
        assert not any(c.startswith('PP ') for c in call['commands']) and create.document(owner) == before


@pytest.mark.parametrize('backend,variable', [BACKENDS[1]], ids=['daemon'])
def test_public_dlt_tweaker_auth_stops_before_selection_or_write(backend,variable,tmp_path):
    auth = tmp_path/'auth.txt';auth.write_text('a'*64+'\n');auth.chmod(0o600)
    bad = tmp_path/'bad.txt';bad.write_text('b'*64+'\n');bad.chmod(0o600)
    with journey(backend,variable,tmp_path,'KEY4','KEYML5',auth_file=auth) as (owner,relay,evidence,specs,profile,_):
        before = create.document(owner)
        failed,call = create.cli(relay,evidence,specs,profile,'KEY4','KEYML5',expected=1,extra=('--auth-token-file',str(bad)))
        assert call['commands'] == ['LOGIN '+'b'*64] and call['statuses'] == [420]
        assert 'b'*64 not in call['stdout']+call['stderr']
        assert not create.state(failed)['writes'] and create.document(owner) == before
