"""Image-source provenance, per-target graph checks and save uncertainty."""
from contextlib import contextmanager
from dataclasses import replace
import re
from unittest.mock import patch
from xml.dom import minidom

import pytest

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.edlt import EdltError
from cbus_toolkit.native_global_programming import NativeEdltGlobalProgramming, NativeGlobalProgrammingError
from tests.test_edlt_global_programming import fixture
from tests.test_edlt_global_image_context import vectors, provider


def reply(code=200, message='OK'):
    line = str(code) + ' ' + message
    return CGateResponse((line,), line, code)


class SourceProjectClient:
    """A stored XML/session boundary; source expectations come only from literals."""
    def __init__(self):
        self.document = minidom.parseString(vectors()['fixture']['project_xml'])
        self.commands = []
        self.session = None
        self.failure = None

    def unit(self, path):
        network, address = path.split('/')[3], path.split('/')[-1]
        n = next(n for n in self.document.getElementsByTagName('Network')
            if n.getElementsByTagName('Address')[0].firstChild.data == network)
        return next(u for u in n.getElementsByTagName('Unit')
            if u.getElementsByTagName('Address')[0].firstChild.data == address)

    def values(self, path):
        return {r.getAttribute('Name'): r.getAttribute('Value')
                for r in self.unit(path).getElementsByTagName('PP')}

    def command(self, command):
        self.commands.append(command)
        if self.failure:
            failure = self.failure(command)
            if isinstance(failure, BaseException): raise failure
            if failure is not None: return failure
        if command.startswith('DBGETXML '):
            path = command.split(' ', 1)[1]
            text = self.document.documentElement.toxml() if path == '//IMGLOBAL' else self.unit(path).toxml()
            lines = ('343-Begin XML snippet', '347-' + text, '344 End XML snippet')
            return CGateResponse(lines, lines[-1], 344)
        if command.startswith('PP SET '):
            match = re.fullmatch(r'PP SET OWNED (\w+) "([0-9a-fx ]+)"', command)
            assert match is not None and self.session is not None
            self.session.staged[match[1]] = match[2]
        return reply()


class BoundaryManager(NativeEdltGlobalProgramming):
    def __init__(self, client):
        super().__init__(client, fixture())
        self.engine.common._verify_session = lambda session: None
        self._network_guard._runtime = lambda path: (('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle'))

    @contextmanager
    def _session(self, path):
        assert self.client.session is None
        outer = self
        class Session:
            name = 'OWNED'
            def __init__(self): self.staged = outer.client.values(path)
            def values(self): return dict(self.staged)
            def save_to_source(self):
                outer.client.commands.append('PP SAVE_TO_SOURCE OWNED')
                for row in outer.client.unit(path).getElementsByTagName('PP'):
                    row.setAttribute('Value', self.staged[row.getAttribute('Name')])
                if outer.client.failure:
                    result = outer.client.failure('PP SAVE_TO_SOURCE OWNED')
                    if isinstance(result, BaseException): raise result
                    if result is not None: return result
                return reply()
        session = Session(); self.client.session = session
        try: yield session
        finally: self.client.session = None

    def _raw(self, session, start, count):
        # Session simulator reads its backing memory; expected target values and
        # save bytes remain the literal vector and the production mask check.
        raw = bytearray(count)
        for name, value in self.engine.snapshot(session.values()).items():
            for edit in self.engine.codec.encode(name, value).edits:
                if start <= edit.address < start + count:
                    i = edit.address - start
                    raw[i] = (raw[i] & ~edit.mask) | edit.value
        return bytes(raw)


def setup(mask=15):
    client = SourceProjectClient(); manager = BoundaryManager(client)
    source = manager.prepare_project_source(vectors()['fixture']['source_unit'], project_images=provider())
    payload = manager.engine.select(source, categories=vectors()['masks'][mask]['categories'])
    plan = manager.plan(payload, [t['path'] for t in vectors()['fixture']['targets']],
        source_database=vectors()['fixture']['source_unit'], exclusive_project=True)
    return client, manager, plan


def test_one_exact_project_snapshot_prepares_source_without_pp_or_target_loads():
    client = SourceProjectClient(); manager = BoundaryManager(client)
    with patch.object(manager.engine.lifecycle, 'load', wraps=manager.engine.lifecycle.load) as load:
        source = manager.prepare_project_source(vectors()['fixture']['source_unit'], project_images=provider())
    assert client.commands == ['DBGETXML //IMGLOBAL']
    assert load.call_count == 1
    assert dict(source.final) == manager.engine.snapshot(vectors()['expected_source']['final'])


@pytest.mark.parametrize('mask', range(16))
def test_native_all16_masks_save_two_divergent_targets_with_full_preservation(mask):
    client, manager, plan = setup(mask); f = vectors()['fixture']
    initial = client.document.toxml()
    assert len({r.preservation for r in plan.targets}) == 2
    with patch.object(manager.engine.lifecycle, 'load', side_effect=AssertionError('target/source reload')):
        result = manager.apply(plan, backup_project='IMBACK').as_dict()
    assert result['complete'] and all(t['verified_saved'] for t in result['targets'])
    assert client.commands.count('PP SAVE_TO_SOURCE OWNED') == 2
    assert result['project_preservation']['destination_lifecycle_loads'] == 0
    assert result['source_image_context']['source_language'] == 1
    expected_payload = dict(vectors()['masks'][mask]['ordered_payload'])
    for row in f['targets']:
        assert manager.engine.snapshot(client.values(row['path'])) == manager.engine.snapshot({**row['input'], **expected_payload})
        assert client.unit(row['path']).getAttribute('marker') == 'unit-' + row['path'].split('/')[-1]
    assert client.values(f['source_unit']) == f['source_pp']
    # Opaque group/label/Language facts and all unit identities are untouched.
    for tag in ('TagsDLT', 'Languages', 'OID', 'Opaque'):
        before = [n.toxml() for n in minidom.parseString(initial).getElementsByTagName(tag)]
        assert [n.toxml() for n in client.document.getElementsByTagName(tag)] == before


@pytest.mark.parametrize('fault', ['source-pp', 'source-language', 'target-label', 'opaque', 'provider'])
def test_stale_source_provider_or_independent_target_graph_rejects_before_mutation(fault):
    client, manager, plan = setup()
    if fault == 'source-pp':
        next(r for r in client.unit(vectors()['fixture']['source_unit']).getElementsByTagName('PP') if r.getAttribute('Name') == 'FontStyle').setAttribute('Value', '0x2')
    elif fault == 'source-language': client.document.getElementsByTagName('Language')[0].getElementsByTagName('TagValue')[0].firstChild.data = '2'
    elif fault == 'target-label': client.document.getElementsByTagName('Group')[1].getElementsByTagName('TagValue')[0].firstChild.data = 'changed'
    elif fault == 'opaque': client.document.getElementsByTagName('Opaque')[-1].firstChild.data = 'changed'
    else: object.__setattr__(plan.payload.source.image_context.project_images, 'entries', ())
    client.commands.clear()
    with pytest.raises(NativeGlobalProgrammingError) as caught: manager.apply(plan)
    assert caught.value.details['target_save_attempted'] is False
    assert not any(c.startswith(('PP SET ', 'PP SAVE_TO_SOURCE', 'PROJECT SAVE', 'PROJECT COPY')) for c in client.commands)


def test_source_context_is_mandatory_and_cannot_name_a_target_or_another_unit():
    client = SourceProjectClient(); manager = BoundaryManager(client)
    source = manager.prepare_project_source(vectors()['fixture']['source_unit'], project_images=provider())
    payload = manager.engine.select(source)
    for path in (None, vectors()['fixture']['targets'][0]['path'], '//IMGLOBAL/254/p/19'):
        client.commands.clear()
        with pytest.raises(NativeGlobalProgrammingError):
            manager.plan(payload, [r['path'] for r in vectors()['fixture']['targets']], source_database=path, exclusive_project=True)
        assert not any(c.startswith('PP SET ') for c in client.commands)


def test_complete_project_changed_between_source_and_plan_is_stale_even_for_selected_pp():
    client = SourceProjectClient(); manager = BoundaryManager(client)
    source = manager.prepare_project_source(vectors()['fixture']['source_unit'], project_images=provider())
    payload = manager.engine.select(source, categories=('key-settings',))
    unit = client.unit(vectors()['fixture']['targets'][0]['path'])
    next(r for r in unit.getElementsByTagName('PP') if r.getAttribute('Name') == 'FontStyle').setAttribute('Value', '0x1')
    with pytest.raises(NativeGlobalProgrammingError, match='project XML changed'):
        manager.plan(payload, [r['path'] for r in vectors()['fixture']['targets']], source_database=vectors()['fixture']['source_unit'], exclusive_project=True)


def test_known_set_rejection_discards_staging_without_destination_save():
    client, manager, plan = setup(); before = client.document.toxml()
    client.failure = lambda command: reply(400, 'Owned rejection') if command.startswith('PP SET OWNED FontStyle ') else None
    with pytest.raises(NativeGlobalProgrammingError) as caught: manager.apply(plan)
    assert client.document.toxml() == before
    assert caught.value.details['state'] == 'stopped'
    assert caught.value.details['target_save_attempted'] is False
    assert client.commands.count('PP SAVE_TO_SOURCE OWNED') == 0
    assert caught.value.details['targets'][0]['attempted_parameters'][-1] == 'FontStyle'


def test_save_applied_with_lost_terminal_is_uncertain_and_never_replayed():
    client, manager, plan = setup(); second = dict(client.values(plan.targets[1].path))
    client.failure = lambda command: TimeoutError('Owned lost successful terminal') if command == 'PP SAVE_TO_SOURCE OWNED' else None
    with pytest.raises(NativeGlobalProgrammingError) as caught: manager.apply(plan)
    assert caught.value.details['state'] == 'uncertain'
    assert caught.value.details['target_save_attempted'] is True
    assert client.commands.count('PP SAVE_TO_SOURCE OWNED') == 1
    assert client.values(plan.targets[1].path) == second
    assert manager.engine.snapshot(client.values(plan.targets[0].path)) == dict(plan.targets[0].merge.final)


def test_pre_save_graph_change_after_staging_stops_before_pp_save():
    client, manager, plan = setup(); changed = False
    def fault(command):
        nonlocal changed
        if command.startswith('PP SET ') and not changed:
            client.document.getElementsByTagName('Opaque')[0].firstChild.data = 'changed-while-staging'
            changed = True
    client.failure = fault
    with pytest.raises(NativeGlobalProgrammingError, match='project graph changed'): manager.apply(plan)
    assert client.commands.count('PP SAVE_TO_SOURCE OWNED') == 0


def test_plan_and_per_target_preservation_bind_issued_payload_context():
    client, manager, plan = setup()
    for forged in (replace(plan), replace(plan, preserved_project='changed')):
        with pytest.raises((EdltError, NativeGlobalProgrammingError)): manager.apply(forged)
    object.__setattr__(plan, 'preserved_project', 'changed')
    with pytest.raises(NativeGlobalProgrammingError, match='preservation baseline'): manager.apply(plan)
