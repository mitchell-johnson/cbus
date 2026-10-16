"""Exact post-commit directory-sync uncertainty must not invoke parent recovery."""
import pytest
from cbus_toolkit.cgate import CGateError
from cbus_toolkit.edlt_parent_metadata import NativeEdltParentError
from tests import test_edlt_parent_metadata as existing
response=existing.response


@pytest.mark.parametrize('failure_phase', ('source-save','copy','metadata'))
def test_exact_applied_unconfirmed_error_stops_without_inverse_io_even_connected(failure_phase):
    fixture=existing.ParentMetadataTests();fixture.setUp()
    manager,session,programmer=fixture.manager()
    plan=manager.plan('//TEST/254/p/20',operations=fixture.operations,exclusive_project=True)
    ordinary=fixture.client.command
    failed_at=[]
    def command(text):
        value=ordinary(text)
        match=(text=='PROJECT SAVE TEST' if failure_phase=='source-save' else
               text=='PROJECT COPY TEST BACKUP' if failure_phase=='copy' else text.startswith('DBADDSAFE '))
        if match and not failed_at:
            failed_at.append(len(fixture.client.commands)-1)
            raise CGateError(response(500,'Database commit applied; durability unconfirmed; do not retry'))
        return value
    fixture.client.command=command
    with pytest.raises(NativeEdltParentError) as caught: manager.apply(plan,backup_project='BACKUP')
    data=caught.value.details['edlt_parent_metadata_evidence']
    assert fixture.client.connected is True  # Prove manager classification, not disconnect-only avoidance.
    assert data['repository_commit_uncertain'] is True
    assert data['database_state_uncertain'] is True and data['state']=='uncertain'
    assert data['saved'] is False and data['partial_failure_possible'] is True
    assert data['database_persistence']=='uncertain'
    assert data['rollback_attempted'] is False
    assert not data['pp_save_attempted'] and not programmer.calls
    assert failed_at and len(fixture.client.commands)==failed_at[0]+1
    assert not any(c.startswith(('DBDELETE ','PROJECT CLOSE ','PROJECT LOAD ')) for c in fixture.client.commands)


def test_generic500_before_pp_keeps_existing_verified_metadata_rollback():
    fixture=existing.ParentMetadataTests();fixture.setUp()
    manager,session,programmer=fixture.manager()
    plan=manager.plan('//TEST/254/p/20',operations=fixture.operations,exclusive_project=True)
    ordinary=fixture.client.command;failed=[]
    def command(text):
        value=ordinary(text)
        if text.startswith('DBADDSAFE ') and not failed:
            failed.append(True)
            raise CGateError(response(500,'Ordinary error'))
        return value
    fixture.client.command=command
    with pytest.raises(NativeEdltParentError) as caught: manager.apply(plan,backup_project='BACKUP')
    data=caught.value.details['edlt_parent_metadata_evidence']
    assert not data['repository_commit_uncertain']
    assert data['rollback_attempted'] is True
    assert any(c=='PROJECT CLOSE TEST' for c in fixture.client.commands)
    assert any(c=='PROJECT LOAD TEST' for c in fixture.client.commands)
