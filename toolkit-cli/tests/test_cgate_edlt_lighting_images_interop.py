"""Byte-backed labels and explicit Lighting callbacks on both owned services."""
import hashlib
import json
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.file_transfer import prepare_upload, upload
from test_cgate_barcode_database_interop import FaultGate, graph, parse_wire
import test_cgate_edlt_parent_add_dialog_interop as parent
from test_cgate_edlt_scene_add_dialog_interop import snapshot
from test_cli_edlt_project_images import owned_bmp

BACKENDS = parent.BACKENDS
PROFILES = ('dynamic-text', 'project-font-image', 'text-image-collision',
            'decoded-dltp-icon', 'label-and-status', 'static-commit',
            'language-current-rows', 'pending-refusal')


def invoke(relay, evidence, args, *, expected=0, complete=True):
    start = len(relay.rows)
    argv = [sys.executable, '-m', 'cbus_toolkit', 'cgate', '--host', relay.endpoint[0],
            '--port', str(relay.endpoint[1]), '--timeout', '3', *map(str, args)]
    process = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    call = {'argv': argv, 'exit': process.returncode,
            'stdout': process.stdout, 'stderr': process.stderr}
    evidence['calls'].append(call)
    assert process.returncode == expected, call
    value = json.loads(process.stdout or process.stderr)
    call['result'] = value
    assert len(relay.rows) == start + 1, call
    wire = relay.rows[start]
    assert wire['done'].wait(5)
    call.update(parse_wire(wire, complete=complete))
    return value, call


def control(target, variant):
    return {'target': target, 'type': 10, 'events': [
        {'event': 'selected-row', 'index': variant,
         'identity': f'label:56/0/{variant}', 'value': variant}]}


def provision(owner, tmp_path, profile):
    root = ET.fromstring(snapshot(owner))
    network = root.find('Project/Network')
    group = network.find("Application[Address='56']/Group[Address='0']")
    old = group.find('TagsDLT')
    if old is not None:
        group.remove(old)
    tags = ET.SubElement(group, 'TagsDLT')
    for language in (1, 2):
        for variant, (kind, text) in enumerate((('DYNAMIC', '0001'), ('FONT', '0002,Owned font'),
                                               ('FONT', '0009,Missing image'), ('TEXT', '0002'))):
            if profile == 'decoded-dltp-icon' and variant == 1:
                kind, text = 'ICON', '1'
            if profile == 'language-current-rows' and language == 2:
                text = '0009,Old language'
            node = ET.SubElement(tags, 'TagDLT')
            for name, value in (('LanguageID', language), ('FlavourID', variant + 1),
                                ('TagType', kind), ('TagValue', text)):
                ET.SubElement(node, name).text = str(value)
    if profile == 'language-current-rows':
        old = network.find('Languages')
        if old is not None:
            network.remove(old)
        collection = ET.SubElement(network, 'Languages')
        ET.SubElement(collection, 'OID').text = str(uuid.uuid4())
        for identifier, name in ((0, '2'), (1, 'English'), (2, 'English (Australia)')):
            node = ET.SubElement(collection, 'Language')
            for field, value in (('OID', uuid.uuid4()), ('ID', identifier), ('TagValue', name)):
                ET.SubElement(node, field).text = str(value)
    assert owner.command_document('DBSETXML //TEST/254', ET.tostring(network, encoding='unicode')).code == 301
    assert owner.command('FILE MKDIR %TEST%/TEST').code == 200
    raw = owned_bmp()
    for name in ('TEST-DLTD-Pic0001.bmp', 'TEST-DLTD-Pic0002.bmp'):
        path = tmp_path / name
        path.write_bytes(raw)
        assert upload(prepare_upload('%TEST%/TEST/' + name, path), owner)['upload_completed']
    assert owner.command('PROJECT SAVE TEST').code == 200
    return snapshot(owner)


def assert_full_preservation(before, after, profile, byte1, index):
    """Literal control fields, opaque bytes, all PP and complete XML graph."""
    old, new = ET.fromstring(before), ET.fromstring(after)
    source, actual = parent.values(old), parent.values(new)
    assert len(source) == len(actual) == 844
    expected = {'Widget6WidgetByteValue1': [42], 'Widget6WidgetByteValue2': [1],
                'Widget7RestoreLevel': [9], 'Widget8WidgetType': [255]}
    # SetToDefault preserves bytes4/5/15..31; these are tested against the
    # original record, rather than synthesized from the editor under test.
    record = [source['Widget7WidgetType'][0],
              *(source[f'Widget7WidgetByteValue{i}'][0] for i in range(1, 32))]
    for offset, value in {0: 2, 1: byte1, 2: 2, 3: 1, 6: 0, 7: 10, 8: 9,
                          9: 1, 10: 255, 11: 255, 12: 25, 13: index, 14: 0}.items():
        record[offset] = value
    expected['Widget7WidgetType'] = [record[0]]
    expected.update({f'Widget7WidgetByteValue{i}': [record[i]] for i in range(1, 32)})
    if profile == 'static-commit':
        assert index == 63
        expected['StaticTextString63'] = list(b'Owned public control'.ljust(64, b'\0'))
    for name, literal in expected.items():
        assert actual[name] == literal, (name, actual[name], literal)
    assert actual['Widget6WidgetType'] == [12]
    crc_fields = {'OverallCRC', 'GlobalParameterCRC', 'WidgetsCRC',
                  'StaticTextCRC', 'ScenesCheckSum'}
    changed = {name for name in actual if actual[name] != source[name]}
    assert changed <= set(expected) | crc_fields, changed - set(expected) - crc_fields
    for name in crc_fields:
        assert len(actual[name]) == 2 and all(0 <= value <= 255 for value in actual[name])
    # Mask only the named parameter changes and terminal checksum family. All
    # unrelated PP, OIDs, object order, tags and interface data remain exact.
    for node in new.find("Project/Network/Unit[Address='20']").findall('PP'):
        if node.get('Name') in set(expected) | crc_fields:
            original = old.find("Project/Network/Unit[Address='20']/PP[@Name='" + node.get('Name') + "']")
            node.set('Value', original.get('Value'))
    if profile == 'language-current-rows':
        languages = new.find('Project/Network/Languages')
        assert [(n.findtext('ID'), n.findtext('TagValue')) for n in languages.findall('Language')] == [
            ('0', '1'), ('1', 'English')]
        languages.find("Language[ID='0']/TagValue").text = '2'
        # Restore only the requested removal; retained Language OIDs and every
        # TagsDLT row, including the old language's rows, compare unchanged.
        languages.append(old.find("Project/Network/Languages/Language[ID='2']"))
    assert graph(ET.tostring(new, encoding='unicode')) == graph(before)


def public_journey(backend, variable, profile, tmp_path, *, lost_save=False):
    with parent.journey(backend, variable, tmp_path, {}) as (owner, relay, evidence, specs, endpoint):
        before = provision(owner, tmp_path, profile)
        evidence.update(format='cbus-edlt-lighting-images-owned-v1', profile=profile,
                        snapshots={'before': before})
        export_path = tmp_path / 'project-images.json'
        exported, image_call = invoke(relay, evidence,
            ['edlt-project-images', 'TEST', '--output', export_path])
        assert image_call['commands'] == ['FILE DIR %PROJ%/TEST',
            'FILE DOWNLOAD %PROJ%/TEST/TEST-DLTD-Pic0001.bmp',
            'FILE DOWNLOAD %PROJ%/TEST/TEST-DLTD-Pic0002.bmp']
        assert image_call['statuses'] == [305, 346, 346]
        assert exported['sha256'] == hashlib.sha256(export_path.read_bytes()).hexdigest()
        assert graph(snapshot(owner)) == graph(before)
        histories = ([{'target': 'label', 'type': 3, 'events': [
                         {'event': 'input', 'text': 'Owned public control'},
                         *([] if profile == 'pending-refusal' else [{'event': 'enter'}])]}]
                     if profile in ('static-commit', 'pending-refusal') else
                     [control('label', 2 if profile == 'dynamic-text' else
                              3 if profile == 'text-image-collision' else 1)])
        if profile == 'label-and-status':
            histories.append(control('status', 0))
        operations = [{'op': 'lighting', 'page': 1, 'position': 2, 'group': 0,
                       'mode': 'off-on', 'restore_level': 9, 'label_controls': histories},
                      parent.widget()]
        if profile == 'language-current-rows':
            operations.insert(0, {'op': 'add-language-dialog', 'selected_ids': [1],
                                  'preferences': 'registered-defaults'})
        operations_path = tmp_path / 'operations.json'
        operations_path.write_text(json.dumps(operations))
        argv = ['unit', '--lock-address', '//TEST/254', '--source', '/db//TEST/254/p/20',
                'edlt-parent-transaction', '--spec-dir', specs, '--auto-metadata',
                '--exclusive-project', '--operations', operations_path,
                '--project-images-export', export_path, '--project-images-sha256', exported['sha256']]
        if profile == 'decoded-dltp-icon':
            directory = tmp_path / 'owned-toolkit' / 'Images' / 'DLTP'
            directory.mkdir(parents=True)
            index_bytes = b'1,Owned icon,one.bmp\n'
            (directory / 'Index.txt').write_bytes(index_bytes)
            (directory / 'one.bmp').write_bytes(owned_bmp())
            argv.extend(['--toolkit-dltp-dir', directory.parents[1], '--toolkit-dltp-sha256',
                         hashlib.sha256(index_bytes).hexdigest(), '--toolkit-dltp-decode'])
        if profile == 'pending-refusal':
            refused, call = invoke(relay, evidence, argv, expected=1)
            assert 'pending text' in refused['error']
            assert not any(c.startswith(('DBADD', 'DBSET', 'DBDELETE', 'DBCOPY', 'PP SET',
                                        'PPSET', 'PP SAVE', 'PPSAVE', 'PROJECT SAVE', 'PROJECT COPY',
                                        'PROJECT NEW', 'FILE UPLOAD', 'FILE MKDIR', 'FILE DELETE'))
                           for c in call['commands'])
            assert graph(snapshot(owner)) == graph(before)
            return
        if lost_save:
            with FaultGate(endpoint, 'PP SAVE_TO_SOURCE', 'drop') as fault:
                _result, call = invoke(fault, evidence, [*argv, '--backup-project', 'LBACKUP'],
                                       expected=1, complete=False)
                assert fault.matches == 1
                assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in call['commands']) == 1
                saved_index = next(i for i, c in enumerate(call['commands'])
                                   if c.startswith('PP SAVE_TO_SOURCE '))
                assert not any(c.startswith(('PROJECT SAVE ', 'PROJECT CLOSE ', 'PROJECT LOAD ',
                                             'DBDELETE ', 'DBSET ', 'PP SET ', 'PP SAVE'))
                               for c in call['commands'][saved_index + 1:])
                rows = [row for row in fault.evidence() if row.get('fault')]
                assert len(rows) == 1
                assert bytes.fromhex(rows[0]['lost_backend_terminal_hex']).decode() == (
                    '[' + rows[0]['fault']['tag'] + '] 200 OK\r\n')
                evidence['lost_save_wires'] = fault.evidence()
            after = snapshot(owner)
            assert_full_preservation(before, after, profile, 0x20, 1)
            evidence['snapshots']['after'] = after
            return
        result, call = invoke(relay, evidence, [*argv, '--backup-project', 'LBACKUP'])
        assert result['saved'] and result['persistence_verified']
        assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in call['commands']) == 1
        after = snapshot(owner)
        expected_byte = 0x30 if profile == 'static-commit' else 0x10 if profile == 'dynamic-text' else 0x27 if profile == 'label-and-status' else 0x20
        values = parent.values(ET.fromstring(after))
        assert values['Widget7WidgetByteValue1'] == [expected_byte]
        expected_index = (63 if profile == 'static-commit' else 2 if profile == 'dynamic-text'
                          else 3 if profile == 'text-image-collision' else 1)
        if profile == 'static-commit':
            index = values['Widget7WidgetByteValue13'][0]
            assert bytes(values[f'StaticTextString{index}']) == b'Owned public control'.ljust(64, b'\0')
        else:
            assert values['Widget7WidgetByteValue13'] == [expected_index]
        if profile == 'label-and-status':
            assert values['Widget7WidgetByteValue14'] == [0]
        result_receipt = next(row['label_controls'] for row in result['plan']['parent_transaction']['operation_results']
                              if 'label_controls' in row)
        assert result_receipt['binding']['dynamic_rows'][1]['name'] == (
            '1' if profile == 'decoded-dltp-icon' else '0002,Owned font')
        assert result_receipt['binding']['dynamic_rows'][1]['image_present']
        if profile == 'text-image-collision':
            assert result_receipt['binding']['dynamic_rows'][3] == {
                'identity': 'label:56/0/3', 'value': 3, 'name': '0002', 'image_present': True}
        assert not result_receipt['original_host_executed']
        assert_full_preservation(before, after, profile, expected_byte, expected_index)
        for command in ('PROJECT SAVE TEST', 'PROJECT CLOSE TEST', 'PROJECT LOAD TEST'):
            assert owner.command(command).code == 200
        assert graph(snapshot(owner)) == graph(after)
        evidence['snapshots']['after'] = after


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
@pytest.mark.parametrize('profile', PROFILES)
def test_public_byte_images_and_lighting_callbacks(backend, variable, profile, tmp_path):
    public_journey(backend, variable, profile, tmp_path)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
def test_public_byte_images_lost_successful_save_is_not_replayed(backend, variable, tmp_path):
    public_journey(backend, variable, 'project-font-image', tmp_path, lost_save=True)
