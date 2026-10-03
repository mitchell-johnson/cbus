"""A complete applied-but-unsynced reply prohibits automatic inverse writes."""
import json
from pathlib import Path

import pytest

from cbus_toolkit.cgate import CGateClient, CGateError, CGateResponse
from cbus_toolkit.edlt_scene_metadata import NativeSceneMetadataError, NativeSceneMetadataTransaction
from tests.test_cgate import peer
from tests import test_edlt_scene_metadata as existing

ROOT = Path(__file__).resolve().parents[2]
VECTOR = json.loads((ROOT / 'rust/testdata/vectors/cgate_repository_uncertainty.json').read_text())


def test_exact_repository_commit_error_closes_stream_and_sends_no_inverse():
    final = VECTOR['final']
    with peer([[('[1] ' + final + '\r\n').encode()], [b'[2] 200 OK.\r\n']]) as (address, sent):
        with CGateClient(*address) as client:
            with pytest.raises(CGateError) as caught:
                client.command('DBADDSAFE //TEST/254 Application 202 Trigger Control')
            assert caught.value.repository_commit_uncertain
            assert caught.value.response.final == final
            assert not client.connected
            with pytest.raises(RuntimeError, match='connect.*explicitly'):
                client.command('DBDELETE !created')
    assert sent == [b'[1] DBADDSAFE //TEST/254 Application 202 Trigger Control\r\n']


@pytest.mark.parametrize('status,final', [
    (500, '500 Database commit failed; change rolled back'),
    (500, '500 ordinary failure'),
    (500, VECTOR['final'] + ' extra'),
    (408, VECTOR['final']),
])
def test_other_errors_do_not_claim_commit_uncertainty(status, final):
    assert not CGateError(CGateResponse((final,), final, status)).repository_commit_uncertain


def test_ordinary500_keeps_synchronized_connection():
    with peer([[b'[1] 500 ordinary failure\r\n'], [b'[2] 200 OK.\r\n']]) as (address, sent):
        with CGateClient(*address) as client:
            with pytest.raises(CGateError) as caught:
                client.command('NOOP')
            assert not caught.value.repository_commit_uncertain
            assert client.connected
            assert client.command('NOOP').code == 200
    assert sent == [b'[1] NOOP\r\n', b'[2] NOOP\r\n']


@pytest.mark.parametrize('phase', ('source-save', 'copy', 'metadata'))
def test_scene_metadata_uncertainty_keeps_applied_graph_and_stops_without_inverse_even_connected(phase):
    fixture = existing.SceneMetadataTests()
    fixture.setUp()
    del fixture.client.applications[202]
    del fixture.client.saved_applications[202]
    session = existing.NativeSession(fixture.spec, fixture.client)
    programmer = existing.FakeProgrammer(session)
    manager = NativeSceneMetadataTransaction(fixture.client, fixture.editor, programmer=programmer)
    plan = manager.plan('/db//TEST/254/p/20', operations=existing.operations('sync'), exclusive_project=True)
    original = fixture.client.command
    failed_at = []

    def command(text):
        result = original(text)
        matches = (text == 'PROJECT SAVE TEST' if phase == 'source-save' else
                   text == 'PROJECT COPY TEST SCBACKUP' if phase == 'copy' else
                   text.startswith('DBADDSAFE '))
        if matches and not failed_at:
            failed_at.append(len(fixture.client.commands) - 1)
            raise CGateError(existing.response(500, VECTOR['final'][4:]))
        return result

    fixture.client.command = command
    with pytest.raises(NativeSceneMetadataError):
        manager.apply(plan, backup_project='SCBACKUP')
    evidence = manager.last_result.as_dict()
    assert fixture.client.connected  # The owner must recognize the boundary too.
    assert evidence['database_state_uncertain'] and evidence['state'] == 'uncertain'
    assert evidence['database_persistence'] == 'uncertain'
    assert not evidence['saved'] and evidence['partial_failure_possible']
    assert not evidence['rollback_attempted'] and not evidence['pp_save_attempted']
    assert failed_at and len(fixture.client.commands) == failed_at[0] + 1
    assert not any(row.startswith(('DBDELETE ', 'PROJECT CLOSE ', 'PROJECT LOAD '))
                   for row in fixture.client.commands)
