"""Application and Reset/Add operator histories through owned public CLI."""
from contextlib import contextmanager
import json
import uuid
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

from test_cgate_barcode_database_interop import FaultGate, graph
from test_cgate_edlt_scene_add_dialog_interop import snapshot
import test_cgate_edlt_parent_add_dialog_interop as helpers
from test_edlt_application_add_dialog import operation, reset_spec
from test_edlt_parent_blank_reset import reset_operations
from cbus_toolkit.edlt_reset import _EXCLUDED
from cbus_toolkit.programming import Programmer

BACKENDS = helpers.BACKENDS
VECTOR = Path(__file__).resolve().parents[2] / 'rust/testdata/vectors/cgate_edlt_application_reset_add_wire.json'


def cases():
    result = json.loads(VECTOR.read_text())
    assert result['format'] == 'cbus-edlt-application-reset-add-cli-wire-v1'
    assert result['scope']['original_execution'] is False
    return result['cases']


@contextmanager
def journey(backend, variable, tmp_path, case):
    # Reuse the proven owned processes, startup-only fake PCI, zero-contact
    # configured CNI trap and framed relay; only synthetic schema/input differs.
    original_client = helpers.NamedClient
    def initial_client(spec):
        model = original_client(spec)
        if case.get('initial_primary') == 48:
            model.values['PrimaryApplication'] = '48'
            model.applications[48] = {'oid': helpers.oid(480), 'tag': 'Retained old primary',
                'groups': {0: {'oid': helpers.oid(4800), 'tag': 'Retained old Link', 'levels': ()},
                           42: {'oid': helpers.oid(4842), 'tag': 'Retained old group', 'levels': ()},
                           99: {'oid': helpers.oid(4899), 'tag': 'Retained old Office', 'levels': ()}}}
        return model
    with patch.object(helpers, 'fixture', reset_spec), patch.object(helpers, 'NamedClient', initial_client):
        with helpers.journey(backend, variable, tmp_path,
                             {'application_switch': True, 'initial_scene': case.get('initial_scene', False)}) as row:
            if case.get('reset'):
                # The old fixture primer uses Measurement12, outside Reset's
                # captured initial-model set. Supply a supported Blank0 input
                # in a temporary database PP session before the public journey.
                with Programmer(row[0]).load('//TEST/254','/db//TEST/254/p/20') as session:
                    session.set('Widget6WidgetType','0')
                    session.set('Widget6WidgetByteValue1','0')
                    session.save_to_source()
                assert row[0].command('PROJECT SAVE TEST').code == 200
            row[2]['format'] = 'cbus-application-reset-add-owned-v1'
            row[2]['vector_sha256'] = __import__('hashlib').sha256(VECTOR.read_bytes()).hexdigest()
            yield row


def pp(root):
    unit = root.find("./Project/Network/Unit[Address='20']")
    return {node.get('Name'): node.get('Value') for node in unit.findall('PP')}


def emitted_tree(text):
    return ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))


def assert_state(before, after, case, call):
    old, new = emitted_tree(before), emitted_tree(after)
    original, final = pp(old), pp(new)
    for name, value in case['pp'].items():
        assert [int(t, 0) for t in final[name].split()] == value, name
    assert [int(t, 0) for t in final['Widget6WidgetType'].split()] == [12]
    assert [int(t, 0) for t in final['Widget6WidgetByteValue1'].split()] == [42]
    assert [int(t, 0) for t in final['Widget6WidgetByteValue2'].split()] == [1]
    commands = call['commands']
    assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands) == 1
    assert commands.count('PROJECT SAVE TEST') == 2
    assert commands.count('PROJECT COPY TEST PABACKUP') == 1
    assert commands.count('PROJECT CLOSE TEST') == 1 and commands.count('PROJECT LOAD TEST') == 1
    assert commands.index('PROJECT SAVE TEST') < commands.index('PROJECT COPY TEST PABACKUP')
    assert commands.index('PROJECT COPY TEST PABACKUP') < next(i for i,c in enumerate(commands) if c.startswith('DBADDSAFE '))
    network = new.find('Project/Network')
    issued = []
    for app, name, description in case.get('applications', []):
        node = network.find(f"Application[Address='{app}']")
        assert node is not None and node.findtext('TagName') == name
        # The service XML omits Application Description; its independently
        # bound scalar property is verified below, separate from graph proof.
        assert node.find('Description') is None
        issued.append(node.findtext('OID'))
    for app, number, name in case.get('groups', []):
        node = network.find(f"Application[Address='{app}']/Group[Address='{number}']")
        assert node is not None and node.findtext('TagName') == name
        issued.append(node.findtext('OID'))
    for group, number, name in case.get('levels', []):
        node = network.find(f"Application[Address='202']/Group[Address='{group}']/Level[Address='{number}']")
        assert node is not None and node.findtext('TagName') == name and node.get('Value') == str(number)
        issued.append(node.findtext('OID'))
    assert len(issued) == len(set(issued)) and all(identity and identity not in before for identity in issued)
    assert all(str(uuid.UUID(identity)) == identity.lower() for identity in issued)
    issued_terminals = [terminal for c,terminal in zip(commands,call['terminals']) if c.startswith('DBADDSAFE ')]
    assert set(issued_terminals) == {'OID=' + identity for identity in issued}
    # Every creation binds one301 issued UUID; Level setters may follow ADD.
    assert sum(c.startswith('DBADDSAFE ') for c in commands) == len(issued)
    add_codes = [code for c,code in zip(commands,call['statuses']) if c.startswith('DBADDSAFE ')]
    assert add_codes == [301] * len(issued)
    for app, _name, description in case.get('applications', []):
        identity = network.find(f"Application[Address='{app}']").findtext('OID')
        assert commands.count('DBSETSAFE !' + identity + '/Description ' + description) == bool(description)
        indexes = [i for i,c in enumerate(commands) if c == 'DBGET !' + identity + '/Description']
        assert len(indexes) == (2 if description else 0)
        assert all(call['statuses'][i] == 342 and call['terminals'][i] == '!' + identity + '/Description=' + description for i in indexes)
    # Remove only exact requested creations at their addressed owner path.
    for group, number, _name in case.get('levels', []):
        owner = network.find(f"Application[Address='202']/Group[Address='{group}']")
        owner.remove(owner.find(f"Level[Address='{number}']"))
    for app, number, _name in case.get('groups', []):
        owner = network.find(f"Application[Address='{app}']")
        owner.remove(owner.find(f"Group[Address='{number}']"))
    for app, _name, _description in case.get('applications', []):
        network.remove(network.find(f"Application[Address='{app}']"))
    # Compare all original PP values, with explicit identity exclusions and
    # literal reset/default probes. No unknown/unrelated XML is normalized.
    if case.get('reset'):
        for name in _EXCLUDED: assert final[name] == original[name], name
        # Literal retained original Reset BeforeSave, followed by this
        # journey's separately established Measurement control. This is
        # distinct from the supplied raw schema defaults below.
        reset = json.loads(VECTOR.read_text())['reset_terminal']
        assert [int(final[f'Widget{slot}WidgetType'], 0) for slot in range(1, 22)] == reset['widget_types']
        assert [int(final[f'Scene{slot}StartAddress'], 0) for slot in range(1, 9)] == reset['scene_starts']
        assert int(final['SceneCount'], 0) == reset['scene_count']
        assert int(final['InvertDisplay'], 0) == reset['invert_display']
        assert all(int(final[f'Widget{slot}RestoreLevel'], 0) == 0 for slot in range(6, 22))
        # These are supplied schema defaults, never an expected plan emitted
        # by the producer. Every default outside the explicit native terminal
        # owners must survive Reset exactly.
        terminal = {'SceneBucket','SceneCount','WidgetGroups','OverallCRC','GlobalParameterCRC',
                    'WidgetsCRC','StaticTextCRC','ScenesCheckSum','Application','NavWidgetType',
                    'Widget10WidgetType','Widget10RestoreLevel','Widget10WidgetByteValue1'}
        terminal.update(f'Scene{i}StartAddress' for i in range(1,9))
        terminal.update(f'Widget{i}WidgetType' for i in range(1,22))
        terminal.add('InvertDisplay')
        terminal.update(['Widget6WidgetType','Widget6RestoreLevel',*[f'Widget6WidgetByteValue{i}' for i in range(1,32)]])
        for name, parameter in reset_spec().parameters.items():
            if name in _EXCLUDED or name in terminal or name in case['pp']: continue
            default = parameter.fields['DefaultValue']
            if parameter.type == 'string': assert final[name] == default, name
            else: assert [int(t,0) for t in final[name].split()] == [int(t.replace('$','0x'),0) for t in default.split()], name
        record = bytes.fromhex('0C2A0102010000000000FFFF8740000000000000000000000000000000000000')
        assert int(final['Widget6WidgetType'],0) == record[0]
        assert [int(final[f'Widget6WidgetByteValue{i}'],0) for i in range(1,32)] == list(record[1:])
        assert int(final['NavWidgetType'],0) == 0
        assert int(final['Widget10WidgetByteValue1'],0) == 2
        assert [int(t, 0) for t in final['Widget10WidgetType'].split()] == [10]
        assert [int(t, 0) for t in final['Widget6RestoreLevel'].split()] == [0]
    else:
        allowed = set(case['pp']) | {'SceneBucket','ScenesCheckSum','WidgetGroups','OverallCRC',
            'GlobalParameterCRC','WidgetsCRC','StaticTextCRC'}
        allowed.update({'Widget6WidgetType',*[f'Widget6WidgetByteValue{i}' for i in range(1,14)]})
        assert {name for name in final if final[name] != original[name]} <= allowed
    for node in network.find("Unit[Address='20']").findall('PP'):
        node.set('Value', original[node.get('Name')])
    assert graph(ET.tostring(new, encoding='unicode')) == graph(before)
    return final


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
@pytest.mark.parametrize('case',cases(),ids=lambda c:c['id'])
def test_public_application_reset_add_complete_history(backend,variable,case,tmp_path):
    with journey(backend,variable,tmp_path,case) as (owner,relay,evidence,specs,_endpoint):
        before = snapshot(owner)
        preview, call = helpers.invoke(relay,evidence,specs,tmp_path,case,dry_run=True)
        assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PROJECT COPY','PROJECT SAVE','PP SAVE')) for c in call['commands'])
        assert snapshot(owner) == before
        result, call = helpers.invoke(relay,evidence,specs,tmp_path,case)
        assert result['saved'] and result['pp_readback_verified'] and result['persistence_verified']
        after = snapshot(owner)
        assert_state(before,after,case,call)
        evidence['snapshots'] = {'before':before,'after':after}
        assert owner.command('PROJECT CLOSE TEST').code == 200
        assert owner.command('PROJECT LOAD TEST').code == 200
        assert graph(snapshot(owner)) == graph(after)


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
def test_public_application_reset_add_lost_save_is_not_replayed(backend,variable,tmp_path):
    case = cases()[2]
    with journey(backend,variable,tmp_path,case) as (owner,_relay,evidence,specs,endpoint):
        with FaultGate(endpoint,'PP SAVE_TO_SOURCE','drop') as fault:
            result,call = helpers.invoke(fault,evidence,specs,tmp_path,case,expected=1,complete=False)
            assert fault.matches == 1
            assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in call['commands']) == 1
            index = next(i for i,c in enumerate(call['commands']) if c.startswith('PP SAVE_TO_SOURCE '))
            assert not any(c.startswith(('PROJECT SAVE ','PROJECT CLOSE ','PROJECT LOAD ','DBDELETE ')) for c in call['commands'][index+1:])
            assert call['commands'].count('PROJECT SAVE TEST') == 1
            rows = [r for r in fault.evidence() if r.get('fault')]
            assert len(rows) == 1
            assert bytes.fromhex(rows[0]['lost_backend_terminal_hex']).decode() == '[' + rows[0]['fault']['tag'] + '] 200 OK\r\n'
            evidence['lost_save_wires'] = fault.evidence()
        current = emitted_tree(snapshot(owner)); current_pp = pp(current)
        assert int(current_pp['PrimaryApplication'],0) == 48
        assert current.find("Project/Network/Application[Address='48']/Group[Address='0']") is not None


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
def test_public_application_add_guards_refuse_without_persistent_send(backend,variable,tmp_path):
    case = cases()[0]
    with journey(backend,variable,tmp_path,case) as (owner,relay,evidence,specs,_endpoint):
        before = snapshot(owner)
        for op in (operation(address=100,name='Outside'), operation(name='TEST'),
                   operation(address=100,name='Reserved',creation_preferences={'allow_user_defined':True,'allow_legacy':False})):
            _result,call = helpers.invoke(relay,evidence,specs,tmp_path,{'ops':[op]},expected=1)
            assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PROJECT COPY','PROJECT SAVE','PP SAVE')) for c in call['commands'])
            assert snapshot(owner) == before
