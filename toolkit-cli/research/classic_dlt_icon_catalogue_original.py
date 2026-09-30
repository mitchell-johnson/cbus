"""Read-only pinned classic DLTP catalogue facts, without image/source exports.

The caller verifies EXE/MAP hashes before constructing _Toolkit.  This helper
rechecks the executable and exact consumed symbol addresses, then verifies the
separate index file.  Only ID/label facts and method receipts leave this helper;
vendor filenames, bitmap bytes and disassembled instruction bytes do not.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit


INDEX_SHA256 = 'c6cca64deaed7bb5ad814b2aaf4c37b580396bf38c057aae8bd616fadfd26310'
INDEX_BYTES = 2392
METHODS = {
    'CIS_TfrmEditDLTLabel.TfrmEditDLTLabel.PopulatePredefinedGraphicsList': 0xC1387C,
    'CIS_TClientGraphic.TClientGraphicFactory.GetPictogramList': 0xBCD33C,
    'CIS_TClientGraphic.TClientGraphicFactory.GenImageStrings': 0xBCCC5C,
    'CIS_TClientGraphic.TClientGraphicFactory.GenDirStr': 0xBCC778,
    'CIS_TClientGraphic.TClientGraphicFactory.GenContextStr': 0xBCC834,
    'CIS_TClientGraphic.TClientGraphicFactory.GenSetName': 0xBCC8C8,
    'CIS_TClientGraphic.ParseRecord': 0xBCC8EC,
    'CIS_TClientGraphic.TClientGraphicFactory.GeneratePictogramSet': 0xBCCABC,
    'CIS_TClientGraphic.Reg': 0xBCCA30,
    'CIS_TImageFactory.TImageFactory.RegisterImage': 0x7D5F8C,
    'CIS_TImageFactory.TImageFactory.CreateImageCache': 0x7D5D7C,
    'CIS_TImageFactory.TImageCacheList.AddImageCache': 0x7D58A0,
    'CIS_TImageFactory.TImageFactory.FindImageNames': 0x7D658C,
    'CIS_TImageFactory.TImageCacheList.ImageCacheByName': 0x7D5A44,
    'CIS_TClientGraphic.TClientGraphicFactory.FindPictogram': 0xBCD1FC,
    'CIS_TImageFactory.TImageFactory.FindGraphic': 0x7D6370,
    'Classes.TStrings.SetValue': 0x646D7C,
    'Classes.TStrings.IndexOfName': 0x646568,
}


def _has(method: dict, *pairs: tuple[str, str]) -> None:
    rows = [row[1:] for row in method['instructions']]
    assert all(pair in rows for pair in pairs), (hex(method['start']), pairs)


def _at(method: dict, address: int, mnemonic: str, operands: str) -> None:
    assert (address, mnemonic, operands) in method['instructions'], (hex(address), mnemonic, operands)


def _calls(image: _Toolkit, method: dict, *symbols: str) -> None:
    calls = iter(operands for _, mnemonic, operands in method['instructions'] if mnemonic == 'call')
    for symbol in symbols:
        addresses = {hex(address) for address, names in image.symbols.items() if symbol in names}
        assert addresses and any(operand in addresses for operand in calls), (hex(method['start']), symbol)


def catalogue_facts(image: _Toolkit, index_path: Path) -> dict:
    """Return a source-bound ordered ID/label table and bounded catalogue rules."""
    assert hashlib.sha256(image.raw).hexdigest() == EXE_SHA256, 'Unexpected Toolkit executable'
    raw = Path(index_path).read_bytes()
    assert len(raw) == INDEX_BYTES and hashlib.sha256(raw).hexdigest() == INDEX_SHA256, 'Unexpected classic DLTP index'
    methods = {}
    for symbol, start in METHODS.items():
        assert image.by_name.get(symbol) == start, ('Unexpected Toolkit MAP symbol', symbol)
        methods[symbol] = image.method(symbol)
    get = lambda suffix: next(method for name, method in methods.items() if name.endswith(suffix))
    populate = get('TfrmEditDLTLabel.PopulatePredefinedGraphicsList')
    _at(populate, 0xC138C4, 'mov', 'dl, 1')
    _calls(image, populate, 'CIS_TClientGraphic.TClientGraphicFactory.GetPictogramList',
           'Classes.TCollection.Clear', 'ImgList.TCustomImageList.Clear',
           'Classes.TStrings.GetName', 'SysUtils.StrToIntDef',
           'CIS_TClientGraphic.TClientGraphicFactory.FindPictogram',
           'cxImageComboBox.TcxImageComboBoxItems.Add',
           'cxImageComboBox.TcxImageComboBoxItem.SetImageIndex',
           'Classes.TStrings.GetName', 'SysUtils.StrToIntDef',
           'cxImageComboBox.TcxImageComboBoxItem.SetValue',
           'Classes.TStrings.GetName', 'Classes.TStrings.GetValue',
           'cxImageComboBox.TcxImageComboBoxItem.SetDescription')
    _at(populate, 0xC13922, 'mov', 'dword ptr [ebp - 0x14], 0')
    _at(populate, 0xC139C2, 'mov', 'edx, dword ptr [ebp - 0x14]')
    _at(populate, 0xC13A23, 'inc', 'dword ptr [ebp - 0x14]')
    pictograms = get('TClientGraphicFactory.GetPictogramList')
    _has(pictograms, ('call', 'dword ptr [edx + 0x44]'))
    _calls(image, pictograms, 'CIS_TClientGraphic.TClientGraphicFactory.GenImageStrings')
    _calls(image, get('TClientGraphicFactory.GenImageStrings'),
           'CIS_TClientGraphic.TClientGraphicFactory.GeneratePictogramSet',
           'CIS_TClientGraphic.TClientGraphicFactory.GenSetName',
           'CIS_TImageFactory.TImageFactory.FindImageNames')
    context = get('TClientGraphicFactory.GenContextStr')
    _at(context, 0xBCC846, 'sub', 'al, 1')
    _at(context, 0xBCC84A, 'je', '0xbcc85d')
    assert context['literal_at'][0xBCC860] == 'DLTP'
    assert {'Images\\', '\\'} <= set(get('TClientGraphicFactory.GenDirStr')['literals'])
    _calls(image, get('TClientGraphicFactory.GenSetName'), 'CIS_TClientGraphic.TClientGraphicFactory.GenContextStr')
    generate = get('TClientGraphicFactory.GeneratePictogramSet')
    assert 'index.txt' in generate['literals']
    _at(generate, 0xBCCB0D, 'jne', '0xbccc05')
    _at(generate, 0xBCCB6B, 'mov', 'dword ptr [ebp - 0x24], 0')
    _at(generate, 0xBCCBE0, 'inc', 'dword ptr [ebp - 0x24]')
    _calls(image, generate, 'CIS_TImageFactory.TImageFactory.RegisteredImageSet',
           'CIS_TClientGraphic.TClientGraphicFactory.GenDirStr', 'CIS_TClientGraphic.ParseRecord',
           'CIS_TClientGraphic.TClientGraphicFactory.GenDirStr', 'SysUtils.IntToStr', 'CIS_TClientGraphic.Reg')
    parse = get('CIS_TClientGraphic.ParseRecord')
    _has(parse, ('mov', 'word ptr [ebp - 0x1c], 0x2c'), ('xor', 'edx, edx'),
         ('cmp', 'dword ptr [eax], 0'), ('jg', '0xbcc989'))
    _calls(image, parse, 'CIS_Strings.StringToken', 'SysUtils.StrToIntDef', 'System.Pos',
           'CIS_Strings.StringToken', 'CIS_Strings.StringToken')
    assert '//' in parse['literals']
    _calls(image, get('CIS_TClientGraphic.Reg'), 'CIS_TImageFactory.TImageFactory.RegisterImage')
    _calls(image, get('TImageFactory.RegisterImage'), 'CIS_TImageFactory.TImageFactory.CreateImageSet',
           'CIS_TImageFactory.TImageFactory.CreateImageCache', 'CIS_TImageFactory.TImageCacheList.AddImageCache')
    _has(get('TImageFactory.CreateImageCache'), ('add', 'eax, 0x14'), ('call', 'dword ptr [eax]'))
    _calls(image, get('TImageCacheList.AddImageCache'), 'Classes.TList.Add')
    names = get('TImageFactory.FindImageNames')
    _at(names, 0x7D65E2, 'mov', 'dword ptr [ebp - 0x1c], 0')
    _at(names, 0x7D6611, 'inc', 'dword ptr [ebp - 0x1c]')
    _calls(image, names, 'CIS_TImageFactory.TImageCacheList.ImageCacheByIndex',
           'CIS_TImageFactory.TImageCacheList.ImageCacheByIndex', 'Classes.TStrings.SetValue')
    _has(names, ('mov', 'eax, dword ptr [eax + 0x18]'), ('mov', 'edx, dword ptr [eax + 0x14]'))
    value = get('Classes.TStrings.SetValue')
    _has(value, ('call', 'dword ptr [ecx + 0x58]'), ('call', 'dword ptr [ecx + 0x38]'),
         ('call', 'dword ptr [ebx + 0x20]'), ('call', 'dword ptr [ecx + 0x48]'))
    _at(value, 0x646DB3, 'je', '0x646df9')
    _at(value, 0x646DB7, 'jge', '0x646dc4')
    _has(get('Classes.TStrings.IndexOfName'), ('mov', 'dword ptr [ebp - 0xc], 0'),
         ('je', '0x646608'))
    lookup = get('TImageCacheList.ImageCacheByName')
    _at(lookup, 0x7D5A7D, 'mov', 'dword ptr [ebp - 0x10], 0')
    _at(lookup, 0x7D5ACD, 'jmp', '0x7d5ad7')
    _calls(image, lookup, 'System.@UStrEqual')
    _calls(image, get('TClientGraphicFactory.FindPictogram'),
           'CIS_TClientGraphic.TClientGraphicFactory.GeneratePictogramSet',
           'SysUtils.IntToStr', 'CIS_TImageFactory.TImageFactory.FindGraphic')
    _calls(image, get('TImageFactory.FindGraphic'), 'CIS_TImageFactory.TImageCacheList.ImageCacheByName')
    # The pinned input has exactly three simple comma-delimited ASCII fields per
    # line. Field3 is consumed only for a shape check and is never returned.
    rows = []
    for line in raw.decode('ascii').splitlines():
        fields = line.split(',')
        assert len(fields) == 3 and fields[0].isdigit() and str(int(fields[0])) == fields[0]
        assert fields[1] and '=' not in fields[1] and fields[2].endswith('.bmp')
        rows.append({'id': int(fields[0]), 'label': fields[1]})
    ordered_ids = [row['id'] for row in rows]
    assert len(rows) == 91 and len(set(ordered_ids)) == 91 and ordered_ids == list(range(1, 92))
    return {
        'source_sha256': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256,
                          'Images/DLTP/index.txt': INDEX_SHA256},
        'index': {'relative_name': 'Images/DLTP/index.txt', 'bytes': INDEX_BYTES,
                  'sha256': INDEX_SHA256, 'count': len(rows), 'encoding': 'ASCII',
                  'field_order': ['identifier', 'description', 'bitmap filename']},
        'rows': rows, 'ordered_ids': ordered_ids,
        'methods': [{'symbol': symbol, 'start': hex(method['start']), 'end': hex(method['end']),
                     'sha256': method['sha256']} for symbol, method in methods.items()],
        'findings': {
            'context': 'PopulatePredefinedGraphicsList passes pictogram type1; type1 resolves DLTP and executable-relative Images/DLTP/index.txt.',
            'load_gate': 'GeneratePictogramSet reads index only when the image set is not already registered. Existing process cache prevents reloading.',
            'parse': 'First token parses ID using StrToIntDef(token,0); require positive ID and nonempty remainder not beginning //. Next tokens are description then filename. Registration name is decimal IntToStr(ID).',
            'registration': 'Index records are processed forward; RegisterImage creates a new cache and AddImageCache appends to TList. Registration does not deduplicate names.',
            'name_list': 'FindImageNames walks cache forward and sets output string-list Values[name]=description. A new nonempty name appends; later nonempty descriptions replace the existing value in place; an empty description deletes that name, so a subsequent nonempty occurrence appends anew.',
            'bitmap_lookup': 'FindPictogram uses decimal ID as image name; ImageCacheByName scans forward and returns the first exact-name match. Duplicate registration can therefore pair a later label with the first bitmap.',
            'combo': 'PopulatePredefinedGraphicsList adds items in returned list order. ImageIndex is zero-based list index; Value is integer identifier from name; Description is the corresponding string-list value. Icon identity is not ImageIndex.',
            'pinned_catalogue': 'The pinned file has91 unique canonical IDs1..91 and nonempty labels, so fresh-load list/combobox order is exactly the returned ordered table.',
            'limitations': 'Source facts assume a fresh or unmodified DLTP image-set cache and ordinary new unsorted TStringList. No bitmap bytes, previews, full GUI execution, changed-installation discovery, C-Gate operation or device acceptance is included.',
        },
    }
