"""Independent byte/literal expectations for project and decoded DLTP images."""
from dataclasses import replace
import base64
import hashlib
import json
import struct
from xml.dom import minidom

import pytest

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.edlt_scene_label_images import (
    LabelImageError, decode_bmp, parse_project_images, load_project_images,
    check_project_images, export_project_images, load_decoded_dltp_index,
    check_dltp_images,
)
from cbus_toolkit.edlt_parent_metadata import _dynamic_labels
from cbus_toolkit.edlt_dltp_index import load_dltp_index


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bmp(bits=24, top_down=False, *, red=True):
    # Two independently specified samples: red then green, one per scanline.
    palette = b''
    if bits <= 8:
        palette = b'\x00\x00\xff\x00\x00\xff\x00\x00' + b'\0' * ((1 << bits) - 2) * 4
        rows = [bytes([0 if red else (1 << (8-bits)), 0, 0, 0]),
                bytes([1 << (8-bits), 0, 0, 0])]
    elif bits == 16:
        rows = [b'\x00\x7c\0\0' if red else b'\xe0\x03\0\0', b'\xe0\x03\0\0']
    else:
        rows = [b'\x00\x00\xff\x80' if red else b'\x00\xff\x00\x80', b'\x00\xff\x00\x40']
    pixels = b''.join(rows if top_down else reversed(rows))
    offset = 54 + len(palette)
    return (b'BM' + struct.pack('<IHHI', offset+len(pixels), 0, 0, offset)
        + struct.pack('<IiiHHIIiiII', 40, 1, -2 if top_down else 2, 1, bits, 0, len(pixels), 0, 0, 0, 0)
        + palette + pixels)


def export_bytes(project='SCENEINV', *, entries=None, directory_names=None):
    entries = entries if entries is not None else [
        (project+'-DLTD-Pic0001.bmp', bmp()),
        (project+'-DLTD-Pic0001.extra.bmp', bmp(red=False))]
    names = directory_names if directory_names is not None else ['notes.txt', *[name for name, _ in entries], 'folder/']
    return (json.dumps({'format':'cbus-edlt-project-images-v1', 'project':project,
        'complete':True, 'directory_names':names, 'files':[
            {'name':name,'sha256':sha(data),'data_base64':base64.b64encode(data).decode('ascii')}
            for name,data in entries]}, sort_keys=True)+'\n').encode('ascii')


def catalog(project='SCENEINV'):
    raw = export_bytes(project)
    return parse_project_images(raw, expected_sha256=sha(raw))


@pytest.mark.parametrize('bits',[1,4,8,16,24,32])
@pytest.mark.parametrize('top_down',[False,True],ids=['bottom-up','top-down'])
def test_actual_indexed_and_rgb_samples_decode_with_exact_orientation(bits,top_down):
    raw=bmp(bits,top_down); result=decode_bmp(raw)
    assert result['width']==1 and result['height']==2 and result['bits_per_pixel']==bits
    assert result['rgb_sha256']==sha(b'\xff\x00\x00\x00\xff\x00')
    assert result['file_sha256']==sha(raw)
    assert result['opacity_modeled'] is False


@pytest.mark.parametrize('offset,value',[(2,0),(6,1),(10,0),(14,108),(18,0),(22,0),(26,2),(28,2),(30,1),(34,9),(46,1)])
def test_malformed_or_unsupported_bmp_refuses(offset,value):
    raw=bytearray(bmp());struct.pack_into('<I' if offset not in (26,28) else '<H',raw,offset,value)
    with pytest.raises(LabelImageError):decode_bmp(bytes(raw))


def test_palette_reference_is_verified_not_merely_bm_header():
    raw=bytearray(bmp(8));struct.pack_into('<I',raw,46,2);raw[1078]=255
    with pytest.raises(LabelImageError,match='palette'):decode_bmp(bytes(raw))


def test_export_derives_keys_preserves_order_and_first_duplicate_match():
    value=catalog()
    assert [row.key for row in value.entries]==['0001','0001']
    assert value.match('0001') is value.entries[0]
    assert value.match('1') is None and value.match(' 0001') is None
    assert value.entries[0].rgb_sha256==sha(b'\xff\0\0\0\xff\0')
    assert value.entries[1].rgb_sha256==sha(b'\0\xff\0\0\xff\0')
    assert value.evidence()['server_directory_observed'] is False


@pytest.mark.parametrize('fault',['order','omitted','extra','roster','hash','bmp','boolean','project','complete','duplicate-json'])
def test_export_cannot_supply_unbacked_or_reordered_facts(fault):
    raw=export_bytes(); value=json.loads(raw)
    if fault=='order':value['files'].reverse()
    if fault=='omitted':value['files'].pop()
    if fault=='extra':value['files'].append(value['files'][0])
    if fault=='roster':value['directory_names'].append(value['directory_names'][1])
    if fault=='hash':value['files'][0]['sha256']='0'*64
    if fault=='bmp':
        bad=b'BM'+b'\0'*60;value['files'][0].update(sha256=sha(bad),data_base64=base64.b64encode(bad).decode())
    if fault=='boolean':value['files'][0]['image_present']=True
    if fault=='project':value['project']='OTHER'
    if fault=='complete':value['complete']=False
    raw=json.dumps(value).encode()
    if fault=='duplicate-json':raw=raw.replace(b'"complete": true',b'"complete": true, "complete": true')
    with pytest.raises(LabelImageError):parse_project_images(raw,expected_sha256=sha(raw))


def test_seal_project_and_raw_file_sha_bindings(tmp_path):
    raw=export_bytes(); path=tmp_path/'images.json';path.write_bytes(raw)
    value=load_project_images(path,expected_sha256=sha(raw))
    check_project_images(value,project='SCENEINV')
    for forged in [replace(value,project='OTHER'),replace(value,entries=value.entries[::-1]),replace(value,directory_files=99)]:
        with pytest.raises(LabelImageError):check_project_images(forged)
    with pytest.raises(LabelImageError):check_project_images(value.evidence())
    with pytest.raises(LabelImageError):check_project_images(value,project='OTHER')
    with pytest.raises(LabelImageError):load_project_images(path,expected_sha256='0'*64)
    alias=tmp_path/'alias';alias.symlink_to(path)
    with pytest.raises(LabelImageError):load_project_images(alias,expected_sha256=sha(raw))


@pytest.mark.parametrize('kind,value,present',[
    ('FONT','0001,Arial,12',True),('FONT','0001',True),('FONT',',0001',False),
    ('FONT',' 0001,Arial',False),('DYNAMIC','0001',True),('TEXT','0001',True),
    ('','0001',True),('DYNAMIC','0001,Arial',False),('FONT','0009,Arial',False)])
def test_exact_source_image_lookup_keeps_complete_tag_value(kind,value,present):
    node=minidom.parseString(f'<Level><TagsDLT><TagDLT><LanguageID>1</LanguageID><FlavourID>1</FlavourID><TagType>{kind}</TagType><TagValue>{value}</TagValue></TagDLT></TagsDLT></Level>').documentElement
    rows,known=_dynamic_labels(node,1,project_images=catalog())
    assert known and rows[0]==('0',value,present)
    assert rows[1:]==(('1','',False),('2','',False),('3','',False))


def test_optional_decoded_dltp_successor_retains_legacy_loader(tmp_path):
    path=tmp_path/'Images'/'DLTP';path.mkdir(parents=True)
    index=b'1,Owned,one.bmp\n';(path/'Index.txt').write_bytes(index);(path/'one.bmp').write_bytes(bmp(1))
    legacy=load_dltp_index(tmp_path,expected_sha256=sha(index))
    decoded=load_decoded_dltp_index(tmp_path,expected_sha256=sha(index))
    assert legacy.as_dict()['images_decoded'] is False
    assert decoded.evidence()['images_decoded'] is True
    assert decoded.image_present('1') and not decoded.image_present('01')
    assert decoded.entries==legacy.entries
    with pytest.raises(LabelImageError):check_dltp_images(replace(decoded,decoded_entries=()))
    (path/'one.bmp').write_bytes(b'BMnot-a-decoded-bitmap')
    assert load_dltp_index(tmp_path,expected_sha256=sha(index)).image_present('1')
    with pytest.raises(LabelImageError):load_decoded_dltp_index(tmp_path,expected_sha256=sha(index))


class FileClient:
    def __init__(self,*,fault=None):self.commands=[];self.fault=fault
    def command(self,command):
        self.commands.append(command);name='SCENEINV-DLTD-Pic0001.bmp';data=bmp()
        if command.startswith('FILE DIR'):
            rows=('304-directory="owned-directory" files=2','305-name="notes.txt" size=3 modified=20261003-000000',f'305 name="{name}" size={len(data)} modified=20261003-000000')
            if self.fault=='count':rows=(rows[0].replace('files=2','files=3'),*rows[1:])
            return CGateResponse(rows,rows[-1],305)
        encoded=base64.b64encode(data).decode();rows=(f'345-Start file download for file: %PROJ%/SCENEINV/{name}',*[f'347-{encoded[i:i+76]}' for i in range(0,len(encoded),76)],'346 End file download')
        if self.fault=='terminal':rows=(*rows[:-1],'200 OK')
        if self.fault=='wrong-file':rows=(rows[0].replace(name,'OTHER.bmp'),*rows[1:])
        if self.fault=='data':rows=(rows[0],'347-AAAA',rows[-1])
        return CGateResponse(rows,rows[-1],200 if self.fault=='terminal' else 346)


def test_exporter_reads_exact_source_roster_and_bytes_without_duplicate_pixels():
    client=FileClient(); result=export_project_images(client,'SCENEINV')
    assert client.commands==['FILE DIR %PROJ%/SCENEINV','FILE DOWNLOAD %PROJ%/SCENEINV/SCENEINV-DLTD-Pic0001.bmp']
    value=json.loads(result.raw);assert value['directory_names']==['notes.txt','SCENEINV-DLTD-Pic0001.bmp']
    assert base64.b64decode(value['files'][0]['data_base64'])==bmp()
    receipt=result.as_dict();assert receipt['automatic_retries']==0 and receipt['persistent_mutations']==0
    assert receipt['export_sha256']==sha(result.raw)
    assert 'data_base64' not in json.dumps(receipt) and '347-' not in json.dumps(receipt)
    assert [row['response_lines'] for row in receipt['commands']]==[3,4]


@pytest.mark.parametrize('fault',['count','terminal','wrong-file','data'])
def test_exporter_stops_on_malformed_read_without_retry(fault):
    client=FileClient(fault=fault)
    with pytest.raises(LabelImageError):export_project_images(client,'SCENEINV')
    assert len(client.commands)==(1 if fault=='count' else 2)


def test_sanitized_static_annex_and_independent_literal_oracles_match():
    from pathlib import Path
    fixtures=Path(__file__).resolve().parents[1]/'research/fixtures'
    proof=json.loads((fixtures/'edlt-scene-language-images-static.json').read_bytes())
    vectors=json.loads((fixtures/'edlt-scene-language-images-vectors.json').read_bytes())
    assert len(proof['managed_method_spans'])==19
    assert len(proof['decompiled_declarations'])==5
    assert len(proof['static_checks'])==12 and all(row['passed'] for row in proof['static_checks'])
    assert proof['lookup_contract']['project_duplicate_match']=='first'
    assert proof['lookup_contract']['dltp_reloaded_by_refresh'] is False
    assert proof['admission']['original_instructions_executed'] is False
    assert proof['admission']['GDI_equivalence_claimed'] is False
    assert proof['admission']['font_rendering_implemented'] is False
    samples=vectors['bmp_rgb_samples']
    for bits in samples['bits_per_pixel']:
        assert decode_bmp(bmp(bits))['rgb_sha256']==samples['rgb_sha256']
    for case in vectors['lookup_cases']:
        document=minidom.parseString('<Level><TagsDLT><TagDLT><LanguageID>1</LanguageID><FlavourID>1</FlavourID><TagType/>'+ '<TagValue/></TagDLT></TagsDLT></Level>')
        for field,text in [('TagType',case['kind']),('TagValue',case['tag_value'])]:
            document.getElementsByTagName(field)[0].appendChild(document.createTextNode(text))
        rows,known=_dynamic_labels(document.documentElement,1,project_images=catalog('TEST'))
        assert known and rows[0]==('0',case['tag_value'],case['image_present'])


@pytest.mark.parametrize('provider',['project','decoded-dltp'])
def test_copied_seal_cannot_reissue_modified_image_facts(tmp_path,provider):
    import copy
    if provider=='project':
        value=catalog();forged=replace(value,entries=(),_seal=copy.copy(value._seal))
        check=check_project_images
    else:
        directory=tmp_path/'Images'/'DLTP';directory.mkdir(parents=True)
        index=b'1,Owned,one.bmp\n';(directory/'Index.txt').write_bytes(index)
        (directory/'one.bmp').write_bytes(bmp(1))
        value=load_decoded_dltp_index(tmp_path,expected_sha256=sha(index))
        forged=replace(value,decoded_entries=(),_seal=copy.copy(value._seal));check=check_dltp_images
    with pytest.raises(AttributeError):forged._seal.fingerprint=forged.fingerprint
    with pytest.raises(LabelImageError):check(forged)
    check(value)


@pytest.mark.parametrize('provider',['project','decoded-dltp'])
def test_original_seal_cannot_be_mutated_to_admit_replaced_image_payload(tmp_path,provider):
    if provider=='project':
        value=catalog();forged=replace(value,entries=());check=check_project_images
    else:
        directory=tmp_path/'Images'/'DLTP';directory.mkdir(parents=True)
        index=b'1,Owned,one.bmp\n';(directory/'Index.txt').write_bytes(index)
        (directory/'one.bmp').write_bytes(bmp(1))
        value=load_decoded_dltp_index(tmp_path,expected_sha256=sha(index))
        forged=replace(value,decoded_entries=());check=check_dltp_images
    with pytest.raises(AttributeError):value._seal.fingerprint=forged.fingerprint
    with pytest.raises(LabelImageError):check(forged)
    check(value)
