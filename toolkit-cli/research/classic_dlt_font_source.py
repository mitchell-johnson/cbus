"""Static-only classic FONT descriptor, graphics persistence and renderer facts.

Reads a hash-pinned PE/MAP and one embedded form. Capstone decodes bounded
methods; no vendor instructions, CPU emulator, GUI, renderer or transport run.
The report retains hashes, identifiers and derived rules, not vendor bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit  # noqa: E402
from extract_toolkit_executable_surface import (Cursor, _read_component_header,
                                                _read_value, _text)  # noqa: E402

FORMAT = 'cbus-classic-dlt-font-source-v1'
GRAPHIC = 'CIS_TDLTGraphic.'
FORM = 'CIS_TfrmEditDLTLabel.TfrmEditDLTLabel.'
BITMAP = 'CIS_TDLTGraphicCGateFileAgent.TDLTGraphicCGateFileAgent.'
INDEX = 'CIS_TProjectGraphicsCGateFileAgent.TProjectGraphicsCGateFileAgent.'
METHODS = {
    'predicate': (GRAPHIC + 'IsDLTFontTagValue', 0x856FBC),
    'image_id': (GRAPHIC + 'GetImageIDFromFontTagValue', 0x856FE0),
    'label_text': (GRAPHIC + 'GetLabelTextFromFontTagValue', 0x857024),
    'parse': (GRAPHIC + 'LoadFontFromTagValue', 0x8571A8),
    'serialize': (GRAPHIC + 'MakeCustomFontTagValue', 0x85751C),
    'save_font': (FORM + 'SaveFontGraphic', 0xC14B40),
    'save_project': ('CIS_TCommonCBus.SaveCustomFontGraphicsToProject', 0xF25240),
    'allocate_id': (GRAPHIC + 'TDLTGraphicReferenceCollection.GenerateNewIdentifier', 0x857960),
    'base64': (GRAPHIC + 'IdBase64Encode', 0x857644),
    'ansi_stream': ('Classes.TStringStream.Create', 0x64867C),
    'ansi_bytes': ('SysUtils.BytesOf', 0x6264C0),
    'base64_encode': ('IdCoder3to4.TIdEncoder3to4.InternalEncode', 0x855D08),
    'base64_init': ('IdCoderMIME.TIdEncoderMIME.InitComponent', 0x85697C),
    'unicode_to_ansi': ('System.@LStrFromUStr', 0x608B78),
    'ansi_codepage': ('System.@LStrFromPWCharLen', 0x60781C),
    'windows_conversion': ('System.CharFromWChar', 0x60773C),
    'integer_parser': ('System.@ValLong', 0x605938),
    'preview': (FORM + 'RefreshImageLabelFont', 0xC12BEC),
    'installed_fonts': (FORM + 'LoadSystemFonts', 0xC1296C),
    'font_change': (FORM + 'cmbFontsPropertiesChange', 0xC118C0),
    'save_option': (FORM + 'UpdateSaveFontLabelOption', 0xC11AA0),
    'text_to_bitmap': ('CIS_Graphics.DLTLabelToBitmapCustomFont', 0x7D6B98),
    'measure': ('CIS_Graphics.GetWidthOfCustomFontDLTLabel', 0x7D6BDC),
    'charset': ('CIS_Graphics.CharSetNameToIndex', 0x7D6C4C),
    'y_correction': ('CIS_Graphics.AdjustCustomFontImagePositionY', 0x7D7054),
    'invert': ('CIS_Graphics.InvertBlackAndWhiteBitmap', 0x7D6F64),
    'font_create': ('Graphics.TFont.Create', 0x66A19C),
    'font_size': ('Graphics.TFont.SetSize', 0x66A724),
    'font_name': ('Graphics.TFont.SetName', 0x66A6AC),
    'text_out': ('Graphics.TCanvas.TextOut', 0x66BC60),
    'text_extent': ('Graphics.TCanvas.TextExtent', 0x66BEEC),
    'bitmap_directory': (BITMAP + 'GetFileDir', 0x1214B50),
    'bitmap_filename': (BITMAP + 'GetFileName', 0x1214C04),
    'bitmap_save': (BITMAP + 'PerformSave', 0x1214D50),
    'bitmap_load': (BITMAP + 'PerformLoad', 0x1214E4C),
    'index_directory': (INDEX + 'GetFileDir', 0x12151B4),
    'index_filename': (INDEX + 'GetFileName', 0x1215254),
    'index_serialize': (INDEX + 'BeforeSave', 0x12152EC),
    'index_parse': ('CIS_TProjectGraphicsCGateFileAgent.ParseRecord', 0x121541C),
    'index_load': (INDEX + 'AfterLoad', 0x1215560),
    'load_items': (INDEX + 'LoadItems', 0x12156B4),
}
DFM_SHA256 = 'd55ee037540cebd52dfa04c42efaa5ed27ef0da627511bc31a38f0d0a0aa15be'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _form_facts(image):
    raw = next(image.pe.get_data(entry.directory.entries[0].data.struct.OffsetToData,
                                 entry.directory.entries[0].data.struct.Size)
               for kind in image.pe.DIRECTORY_ENTRY_RESOURCE.entries if kind.id == 10
               for entry in kind.directory.entries if str(entry.name) == 'TFRMEDITDLTLABEL')
    assert sha(raw) == DFM_SHA256
    cursor, result = Cursor(raw, 4), {}
    names = {'frmEditDLTLabel', 'edtLabelFont', 'cmbFontSize', 'cmbCharSet', 'rgSaveFontOption'}
    keys = {'PixelsPerInch', 'Properties.MaxLength', 'Properties.Items.Strings',
            'Properties.OnChange', 'ItemIndex', 'Items.Strings'}

    def visit(depth=0):
        _class, name = _read_component_header(cursor, version=raw[3] - ord('0'))
        properties = {}
        while cursor.peek_u8():
            key = _text(cursor.short_bytes())
            value = _read_value(cursor, depth=depth + 1)
            if key in keys:
                properties[key] = value
        cursor.u8()
        if name in names:
            result[name] = properties
        while cursor.peek_u8():
            visit(depth + 1)
        cursor.u8()
    visit()
    assert cursor.remaining == 0
    assert result['edtLabelFont']['Properties.MaxLength'] == 20
    assert result['cmbFontSize']['Properties.Items.Strings'] == [str(n) for n in range(6, 19)] + ['20']
    assert result['rgSaveFontOption']['Items.Strings'] == ['Update Existing', 'Create New']
    # Confirm the radio control consumed by SaveFontGraphic, not just its caption.
    address = image.dword(image.vmt('CIS_TfrmEditDLTLabel..TfrmEditDLTLabel') - 0x44)
    fields, offset, data = {}, 6, image.pe.get_data(address - image.base, 4096)
    for _ in range(struct.unpack_from('<H', data)[0]):
        field_offset, length = struct.unpack_from('<I', data, offset)[0], data[offset + 6]
        fields[field_offset] = data[offset + 7:offset + 7 + length].decode('ascii')
        offset += 7 + length
    assert fields[0x428] == 'rgSaveFontOption'
    return {'resource': 'TFRMEDITDLTLABEL', 'sha256': sha(raw), 'controls': result,
            'save_radio_field': 'form+0x428',
            'dpi_boundary': 'Embedded form PixelsPerInch96 is a design value, not proof of the runtime TFont pixels-per-inch or Windows font metrics'}


def inspect(executable: Path, symbols: Path):
    exe, mapping = executable.read_bytes(), symbols.read_bytes()
    if sha(exe) != EXE_SHA256 or sha(mapping) != MAP_SHA256:
        raise ValueError('Expected pinned Toolkit 1.18.0.2754 executable and MAP')
    image, methods = _Toolkit(exe, mapping), {}
    for key, (symbol, address) in METHODS.items():
        assert symbol in image.symbols.get(address, set()), (key, symbol, hex(address))
        # MAP has overloaded names; resolve the exact called address explicitly.
        alias = f'{symbol}@{address:x}'
        image.by_name[alias] = address
        methods[key] = image.method(alias)

    def has(key, *pairs):
        actual = [row[1:] for row in methods[key]['instructions']]
        assert all(pair in actual for pair in pairs), (key, pairs)

    has('predicate', ('cmp', 'eax, 9'))
    has('serialize', ('mov', 'edx, 0x12'), ('mov', 'al, byte ptr [ebp + 0x10]'))
    assert {'1,', ','} <= set(methods['serialize']['literals'])
    has('parse', ('mov', 'ecx, 0x400'), ('mov', 'edx, 8'), ('setne', 'byte ptr [eax]'))
    has('label_text', ('mov', 'ecx, 0x400'))
    has('save_font', ('cmp', 'dword ptr [eax + 0x280], 1'), ('mov', 'edx, 0x7d0'),
        ('mov', 'ecx, 0x14'), ('mov', 'dl, 3'))
    has('allocate_id', ('inc', 'dword ptr [ebp - 0xc]'), ('mov', 'dword ptr [ebp - 0x10], eax'))
    has('save_project', ('mov', 'ecx, 0'), ('call', '0x608b78'), ('call', '0x857644'))
    assert {'Font=', 'Pic', '.bmp'} <= set(methods['save_project']['literals'])
    has('ansi_stream', ('call', '0x6264c0'))
    has('ansi_codepage', ('movzx', 'ebx, word ptr [0x13c58d0]'), ('call', '0x60773c'))
    has('windows_conversion', ('call', '0x602a0c'))
    assert image.literal(0x85657C) == 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    assert image.slot('IdCoderMIME..TIdEncoderMIME', 0x38) == 'IdCoder3to4.TIdEncoder3to4.Encode'
    has('preview', ('mov', 'edx, 0x52'), ('mov', 'edx, 0x28'), ('mov', 'edx, 0x3e'),
        ('mov', 'edx, 0x10'), ('call', '0x7d6b98'), ('call', '0x7d6f64'))
    has('font_size', ('push', '0x48'), ('mov', 'eax, dword ptr [ebx + 0x1c]'),
        ('call', '0x60e708'), ('neg', 'edx'))
    has('font_name', ('test', 'esi, esi'), ('je', '0x66a6fe'), ('mov', 'cl, 0x7c'))
    has('text_out', ('call', '0x60ea60'))
    has('text_extent', ('call', '0x60eb90'))
    assert image.slot('Graphics..TCanvas', 0x88) == 'Graphics.TCanvas.TextOut'
    assert image.slot('Graphics..TCanvas', 0x84) == 'Graphics.TCanvas.TextExtent'
    assert '%%PROJ%%/%s/' in methods['bitmap_directory']['literals']
    assert '-DLTD-' in methods['bitmap_filename']['literals']
    assert '-DLTD-index.txt' in methods['index_filename']['literals']
    has('index_parse', ('jg', '0x12154b9'))

    charsets, pending = {}, None
    for address, mnemonic, operands in methods['charset']['instructions']:
        if address in methods['charset']['literal_at']:
            pending = methods['charset']['literal_at'][address]
        if mnemonic == 'mov' and operands.startswith('dword ptr [ebp - 8], '):
            value = int(operands.rsplit(', ', 1)[1], 0)
            if pending is None:
                assert value == 1
            else:
                charsets[pending], pending = value, None
    assert len(charsets) == 14 and charsets['SHIFTJIS'] == 128
    correction = []
    for size in range(21):
        target = image.dword(0x7D7070 + size * 4)
        code = list(image.decoder.disasm(image.pe.get_data(target - image.base, 8), target))
        if code[0].mnemonic == 'xor':
            assert code[0].op_str == 'eax, eax'
            value = 0
        else:
            assert code[0].mnemonic == 'mov' and code[0].op_str.startswith('dword ptr [ebp - 8], ')
            value = int(code[0].op_str.rsplit(', ', 1)[1], 0)
            value = value if value < 2**31 else value - 2**32
        correction.append(value)
    assert correction == [0, 5, 5, 5, 5, 5, 5, 4, 2, 1, 0, -1, -2, -2, -3, -4, -4, -5, -5, -8, -8]
    return {
        'format': FORMAT,
        'source': {'executable_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256},
        'methods': {key: {'symbol': METHODS[key][0], 'start': hex(method['start']),
                          'end': hex(method['end']), 'sha256': method['sha256']}
                    for key, method in methods.items()},
        'form': _form_facts(image),
        'descriptor': {
            'fields': ['image_id', 'version', 'font_name', 'size_text', 'charset_name',
                       'style', 'x', 'y', 'invert', 'text'],
            'version_written': '1', 'delimiter': ',', 'escaping': None,
            'serializer': 'Unicode concatenation; signed32 decimal image ID/x/y, unsigned low-byte invert; no validation, escaping, clipping or normalization inside serializer',
            'gui_input': 'Ordinary GUI supplies style empty/B/I/BI, checkbox invert0/1 and first20 UTF16 text units; editor MaxLength is also20',
            'predicate': 'Exactly9 commas only; field contents and version are not validated',
            'parser': 'head(s)=Copy(s,1,Pos(comma,s)-1); tail(s)=Copy(s,Pos(comma,s)+1,1024). Skip2 tails, then read name,size,charset,style,x,y,invert. GetLabelText applies9 tails. Missing comma gives empty head and first1024 units of the same tail',
            'size_default': 8, 'position_default': 0,
            'invert': 'False only for exact string0; empty,00,false and any other text become true',
            'style': 'Case-sensitive substring B/I selects flags1/2/3; neither retains existing TFont style',
            'name': 'Empty font name retains the caller font name; allocated prior TFont state is required',
            'integer_grammar': 'Pinned Delphi ValLong: leading ASCII spaces; optional sign; decimal or $,x/X,0x/0X hexadecimal; no trailing spaces/junk; embedded NUL terminates. Signed32 decimal and32-bit hex patterns; no decimal-separator locale',
            'charset_values': charsets, 'charset_fallback': 1,
        },
        'allocation': {
            'create_new': 'Save radio index1 allocates first unused identifier at or above2000 from the project graphics references',
            'update_existing': 'Other radio state parses original form+0x470 descriptor ID via StrToIntDef(-1); any nonnegative result is reused, otherwise allocate. No existence check at this point',
            'collision': 'Scan collection forward; on equal identifier increment candidate and restart index0; no explicit local upper bound',
            'zero_id_mismatch': 'Save permits reuse0 but graphics index parser rejects IDs<=0; a portable save/reload contract should explicitly require positive IDs',
        },
        'persistence': {
            'description': 'Font= plus standard padded unwrapped Base64 of runtime-ANSI converted descriptor bytes; no BOM',
            'ansi': {'codepage_argument': 0, 'runtime_codepage_global': '0x13c58d0',
                     'api': 'WideCharToMultiByte', 'flags': 0,
                     'default_character_pointer': None, 'used_default_character_pointer': None,
                     'boundary': 'Actual Windows ANSI codepage and substitution behavior are external runtime prerequisites; do not infer from host locale'},
            'base64': 'ANSI TStringStream overload uses BytesOf/System.Move; TIdEncoderMIME uses standard A-Z,a-z,0-9,+,/ alphabet and equals padding with no line wrapping',
            'upsert': 'Find project graphic by ID; create if absent, otherwise reuse. Both branches overwrite identifier, Font= description, bitmap and Pic<ID>.bmp filename',
            'save_order': ['save graphic bitmap', 'save project graphic index'],
            'bitmap_path': '%PROJ%/UPPERPROJECT/UPPERPROJECT-DLTD-Pic<ID>.bmp',
            'index_path': '%PROJ%/UPPERPROJECT/UPPERPROJECT-DLTD-index.txt',
            'index': 'Forward id,description,filename plus CRLF rows without CSV quoting/escaping',
            'reload': 'Parse positive IDs and upsert descriptor/filename forward without clearing existing items; bitmap loading is deferred to LoadItems',
            'coupling': 'A metadata-only update is not the original FONT save: bitmap bytes and index are persisted separately, with no atomicity established',
        },
        'rendering': {
            'intermediate_size': [82, 40], 'final_size': [62, 16], 'monochrome': True,
            'installed_fonts': 'LoadSystemFonts copies Windows TScreen.GetFonts and selects Arial by list lookup; presence, substitution and actual face are runtime facts',
            'center_x': 'When centering is checked, truncate (current preview bitmap width - measured text width)/2 toward zero, then disable manual X; final recreated bitmap width is62',
            'font_height': '-Windows.MulDiv(point_size,TFont.PixelsPerInch,72)',
            'y_correction_by_size_0_to_20': correction, 'y_correction_other_sizes': 0,
            'drawing': 'Assign TFont to intermediate canvas, draw text at x0 and size-dependent Y; draw intermediate into62x16 preview at manual/centered X and manual Y; optionally invert',
            'windows_apis': ['GetTextExtentPoint32', 'ExtTextOut'],
            'pixel_boundary': 'Windows GDI/VCL metrics, font face/file/version, DPI/PixelsPerInch, charset/style and renderer state determine pixels; an arbitrary cross-platform font renderer is not equivalent',
            'wire_boundary': 'The62x16 final preview is not proof of transmitted bitmap width. The separately observed flavour default width64 requires its own LoadDLTBitmap width/padding/packing contract. The broadcast compiler accepts caller-prepared width1..240 as a native encoding bound, not original renderer evidence',
        },
        'future_preconditions': [
            'Fresh authoritative project identity, graphic IDs, index and referenced bitmap snapshot; exclusive update ownership and explicit create-new/update-existing intent',
            'Explicit selected target/language/flavour and complete admitted collection lifecycle; positive image IDs and comma-free fields for a bounded ordinary descriptor',
            'Explicit Windows font file/version/resolved face, DPI/TFont.PixelsPerInch, point size, charset/style, measured metrics and GDI/VCL rendering context',
            'Explicit Windows ANSI codepage/conversion facts or a separately declared ASCII-only metadata boundary; never infer host locale',
            'Prepared bitmap bound to descriptor and renderer evidence before any coupled graphic/index save; separate persistence receipts and failure handling',
        ],
        'boundary': {'static_only': True, 'original_instructions_executed': False,
                     'cpu_emulator_imported': False, 'renderer_executed': False,
                     'native_gui_executed': False, 'project_written': False,
                     'network_io': False, 'physical_io': False,
                     'production_font_writer_implemented': False},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.executable, args.map)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'format': FORMAT, 'methods': len(report['methods']),
                      'static_only': True, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
