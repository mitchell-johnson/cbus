"""Remaining conversion families through public CLI and owned Rust services.

The complete project, specifications, closed-network trap, inert PCI/MQTT
peers and any lost-reply relay belong to these tests. No original or physical
controller instructions are executed.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sys
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from test_cgate_barcode_database_interop import FaultGate, graph, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap,
    owned_backend,
)
import test_cgate_toolkit_tweaker_interop as create
import test_cgate_toolkit_tweaker_lifecycle_interop as replace
from test_toolkit_conversion_remaining import profile_files, VECTOR

BACKENDS = create.BACKENDS
WIRE = json.loads((Path(__file__).resolve().parents[2] /
    "rust/testdata/vectors/cgate_toolkit_tweaker_remaining_wire.json").read_text())


@contextmanager
def journey(backend, variable, tmp_path, case):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'backend')
    specs = tmp_path / 'synthetic-specs'
    profile = profile_files(specs, case['source'], case['target'])
    profile['source_values'].update(case.get('source_values', {}))
    launcher = work / 'owned-remaining-conversion-spec-backend'
    flag = '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec'
    launcher.write_text('#!' + sys.executable + '\nimport os,sys\nos.execv('
                        + repr(str(binary)) + ', [' + repr(str(binary))
                        + ', *sys.argv[1:], ' + repr(flag) + ', '
                        + repr(str(specs)) + '])\n', encoding='utf-8')
    launcher.chmod(0o700)
    evidence = {'format': 'cbus-remaining-conversion-owned-v1',
                'backend': backend, 'original_execution': False,
                'physical_acceptance': False,
                'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'case': case['id'], 'calls': [], 'processes': [],
                'specifications': {p.name: create.digest(p.read_bytes())
                                   for p in specs.iterdir()}}
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(backend, launcher, work) as (endpoint, record):
            evidence['processes'].append(record)
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                evidence['roles'] = create.seed(owner, work, trap, case['source'], profile)
                yield owner, relay, evidence, specs, profile, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'] = relay.evidence()
        associated_evidence(tmp_path / 'remaining-conversion-evidence.json', evidence)


def literal_parameters(case, result):
    # These expectations are fixed independently in the committed vector;
    # they are not derived from the workflow's reported expected dictionary.
    for name, values in case['expected'].items():
        assert result[name] == values, (name, result)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('operation', ['create', 'replace'])
@pytest.mark.parametrize('case', VECTOR['cases'], ids=lambda row: row['id'])
def test_public_remaining_conversion_literal_and_lifecycle(backend, variable, operation, case, tmp_path):
    with journey(backend, variable, tmp_path, case) as (owner, relay, evidence, specs, profile, _endpoint):
        source, target = case['source'], case['target']
        assert owner.command('DBSET //WFTEST/11/p/20/Description copied & Ω description').code == 200
        before = create.document(owner)
        original = create.document(owner, '//WFTEST/11/p/20')
        other = create.document(owner, '//OTHER')
        journal = tmp_path / 'attempt.json'
        run = create.cli if operation == 'create' else replace.cli
        preview, call = run(relay, evidence, specs, profile, source, target)
        assert preview['phase'] == 'preview_complete'
        assert create.document(owner) == before
        assert not any(c.startswith(('DBADD', 'DBSET', 'DBDELETE', 'PP SAVE', 'PROJECT COPY', 'PROJECT SAVE'))
                       for c in call['commands'])
        assert preview['plan_sha256'] == create.plan_digest(preview['plan'])
        flags = create.apply_flags(preview) if operation == 'create' else replace.flags(preview, journal)
        final, call = run(relay, evidence, specs, profile, source, target, extra=flags)
        assert final['phase'] == 'complete' and final['accepted'] and not final['outcome_uncertain']
        assert final['plan_sha256'] == preview['plan_sha256'] == create.plan_digest(final['plan'])
        conversion = final if operation == 'create' else final['creation']
        literal_parameters(case, conversion['verified_expected_parameters'])
        commands = call['commands']
        assert sum(c.startswith('DBADDSAFE ') for c in commands) == 1
        assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands) == 1
        assignments = [c for c in commands if c.startswith('PP SET ')]
        for name, tail in WIRE['cases'][case['id']].items():
            matches = [c for c in assignments if re.search(r' ' + re.escape(name) + r' ', c)]
            assert len(matches) == 1 and matches[0].endswith(tail), matches
        for name in case.get('not_written', []):
            assert not any(re.search(r' ' + re.escape(name) + r' ', c) for c in assignments)
        oid = final['oid'] if operation == 'create' else final['destination_oid']
        assert oid != ET.fromstring(original).findtext('OID') and oid not in before
        address = '21' if operation == 'create' else '20'
        unit = ET.fromstring(create.document(owner, '//WFTEST/11/p/' + address))
        assert unit.findtext('OID') == oid and unit.findtext('UnitType') == target
        assert unit.findtext('FirmwareVersion') == profile['firmware']
        after = create.document(owner)
        if operation == 'create':
            assert create.document(owner, '//WFTEST/11/p/20') == original
            create.unchanged_after_removing_new(before, after, oid)
            assert not any(final[k] for k in ('source_deleted', 'readdressed', 'project_saved', 'automatic_retries'))
        else:
            assert final['source_deleted'] and final['readdressed'] and final['project_saved'] and final['reopened']
            assert not final['full_replacement_parity'] and not final['rollback_performed']
            assert graph(replace.remove_unit(before, ET.fromstring(original).findtext('OID'))) == graph(replace.remove_unit(after, oid))
            assert graph(replace.normalized_backup(create.document(owner, '//BACKUP'))) == graph(before)
            for field in ('TagName', 'UnitName', 'SerialNumber', 'Description'):
                assert unit.findtext(field) == ET.fromstring(original).findtext(field)
            for verb in ('PROJECT COPY WFTEST BACKUP', 'DBDELETE //WFTEST/11/p/20', 'PROJECT SAVE WFTEST',
                         'PROJECT CLOSE WFTEST', 'PROJECT LOAD WFTEST'):
                assert commands.count(verb) == 1
            retained = journal.read_bytes()
            recovered, read = replace.cli(relay, evidence, recovery=True, extra=('--journal', str(journal)))
            assert recovered['disposition'] == 'observed_replaced' and recovered['persistence_verified']
            assert not recovered['replay_authorized'] and journal.read_bytes() == retained
            assert all(c.startswith(tuple(WIRE['recovery_prefixes']))
                       and not c.startswith(('PP SET ', 'PP SAVE')) for c in read['commands'])
            assert create.document(owner) == after
        assert create.document(owner, '//OTHER') == other
        evidence['snapshots'] = {'before': before, 'after': after, 'source_before': original, 'other': other}


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('operation,verb', [('create', 'PP SAVE_TO_SOURCE'), ('replace', 'DBDELETE')])
def test_public_remaining_conversion_lost_success_never_replays(backend, variable, operation, verb, tmp_path):
    case = VECTOR['cases'][0]
    with journey(backend, variable, tmp_path, case) as (owner, _relay, evidence, specs, profile, endpoint):
        before = create.document(owner)
        journal = tmp_path / 'attempt.json'
        with FaultGate(endpoint, verb, 'drop') as relay:
            run = create.cli if operation == 'create' else replace.cli
            preview, _call = run(relay, evidence, specs, profile, case['source'], case['target'])
            flags = create.apply_flags(preview) if operation == 'create' else replace.flags(preview, journal)
            failure, call = run(relay, evidence, specs, profile, case['source'], case['target'], expected=1, extra=flags)
            failure = create.state(failure) if operation == 'create' else replace.state(failure)
            assert failure['outcome_uncertain'] and not failure['accepted'] and not failure['automatic_retries']
            assert call['commands'][-1].startswith(verb + ' ')
            assert sum(c.startswith(verb + ' ') for c in call['commands']) == 1
            assert not any(c.startswith(('PROJECT SAVE ', 'PROJECT CLOSE ', 'PROJECT LOAD ')) for c in call['commands'])
            faults = [row for row in relay.evidence() if row.get('fault')]
            assert len(faults) == 1
            row = faults[0]; tag = row['fault']['tag']
            assert re.fullmatch(r'\[' + re.escape(tag) + r'\] 200 [^\r\n]*\r\n',
                                bytes.fromhex(row['lost_backend_terminal_hex']).decode())
            assert bytes.fromhex(row['forwarded_request_hex']).decode().splitlines().count('[' + tag + '] ' + row['fault']['command']) == 1
            if operation == 'replace':
                retained = journal.read_bytes()
                recovered, read = replace.cli(relay, evidence, recovery=True, extra=('--journal', str(journal)))
                assert not recovered['replay_authorized'] and not recovered['persistence_verified']
                assert journal.read_bytes() == retained
                assert all(c.startswith(tuple(WIRE['recovery_prefixes']))
                           and not c.startswith(('PP SET ', 'PP SAVE')) for c in read['commands'])
            evidence['fault_wires'] = relay.evidence()
        after = create.document(owner)
        if operation == 'create':
            create.unchanged_after_removing_new(before, after, failure['oid'])
        else:
            assert graph(replace.remove_unit(before, evidence['roles']['source'])) == graph(replace.remove_unit(after, failure['creation']['oid']))
        evidence['snapshots'] = {'before': before, 'after': after}
