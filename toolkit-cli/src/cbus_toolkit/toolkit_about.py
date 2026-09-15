"""Offline Toolkit About text and bounded explicit-EXE version-resource reading."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import struct

MAX_EXE_BYTES = 64 * 1024 * 1024
MAX_VERSION_BYTES = 65536
TOOLKIT_NAME = 'C-Bus Toolkit'
COPYRIGHT_COMPANY = 'Schneider Electric (Australia) Pty Ltd'
PINNED_TOOLKIT_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(name + ' must be an integer in the supported range')
    return value


def _text(value, name):
    if type(value) is not str or len(value) > 4096 or '\0' in value:
        raise ValueError(name + ' must be bounded text without NUL')
    try:
        value.encode('utf-8')
    except UnicodeError as error:
        raise ValueError(name + ' must be valid Unicode') from error
    return value


def validate_year(year):
    return _integer(year, 'year', 1, 9999)


def validate_context(context):
    if context is None:
        return None
    names = {'version', 'build', 'max_memory_mb', 'used_memory_mb', 'java_version'}
    if type(context) is not dict or set(context) != names:
        raise ValueError('Captured C-Gate context requires exactly version, build, max_memory_mb, used_memory_mb and java_version')
    return {key: (_integer(context[key], key, -(1 << 63), (1 << 63) - 1)
                  if key.endswith('_memory_mb') else _text(context[key], key)) for key in sorted(names)}


@dataclass(frozen=True)
class AboutReport:
    _document: str

    def as_dict(self):
        return json.loads(self._document)


def format_about(version, *, flags=0, year, product_name=TOOLKIT_NAME, context=None):
    """Run the proved pure text formula; every input here is caller-supplied."""
    validate_year(year); _text(product_name, 'product_name'); context = validate_context(context)
    _integer(flags, 'flags', 0, 0xffffffff)
    if version is not None:
        if type(version) not in (tuple, list) or len(version) != 4:
            raise ValueError('version must be four unsigned16-bit words or None')
        version = tuple(_integer(item, 'version word', 0, 65535) for item in version)
    if version is None:
        number, build, beta, special = '(unknown)', 'unknown', '', ''
    else:
        number = '.'.join(str(item) for item in version[:3]); build = str(version[3])
        beta = (' Beta' if flags & 8 else ' Public Beta') if flags & 2 else ''
        special = ' Special Build' if flags & 32 else ''
    captions = {'product': product_name, 'version': 'Version ' + number + beta + ' (build ' + build + ') ' + special,
        'copyright': 'Copyright © ' + str(year) + ' ' + COPYRIGHT_COMPANY,
        'cgate': 'C-Gate (Installation not selected)', 'maximum_memory': '', 'used_memory': '', 'java': ''}
    if context is not None:
        captions['cgate'] = 'C-Gate v' + context['version'] + ' (build ' + context['build'] + ')'
        captions['maximum_memory'] = 'C-Gate Max Memory: ' + str(context['max_memory_mb']) + ' MB'
        captions['used_memory'] = 'C-Gate Used Memory: ' + str(context['used_memory_mb']) + ' MB'
        if context['java_version']:
            captions['java'] = 'Java Version: ' + context['java_version']
    return AboutReport(json.dumps({'scope': 'Offline Toolkit1.18 About text formula',
        'window_caption': 'About ' + product_name, 'captions': captions, 'year': year,
        'version': list(version) if version is not None else None, 'flags': flags,
        'captured_context': context, 'context_source': 'caller-supplied' if context is not None else 'not supplied',
        'context_verified_live': False, 'original_live_application_name_provider_observed': False,
        'network_accessed': False, 'registry_accessed': False, 'clock_read': False, 'ui_created': False,
        'provenance': {'version': 'caller-supplied', 'flags': 'caller-supplied', 'display_name': 'caller-supplied formatter input',
                       'year': 'explicit caller input', 'copyright_company': 'original Toolkit1.18 menu literal'}}, ensure_ascii=True))


def _version_tree(blob):
    """Validate bounded VERSIONINFO blocks before any string-table interpretation."""
    count = [0]
    def block(start, boundary, depth):
        count[0] += 1
        if count[0] > 256 or depth > 4 or start + 6 > boundary:
            raise ValueError('Version resource structure exceeds its supported bounds')
        length, value_length, kind = struct.unpack_from('<HHH', blob, start)
        end = start + length
        if length < 8 or end > boundary or kind not in (0, 1):
            raise ValueError('Malformed version resource block')
        pos = start + 6
        while pos + 2 <= end and blob[pos:pos + 2] != b'\0\0':
            pos += 2
        if pos + 2 > end or pos - start > 1030:
            raise ValueError('Version resource key is unterminated or too long')
        key = blob[start + 6:pos].decode('utf-16le'); _text(key, 'version resource key')
        value_start = (pos + 5) & ~3
        size = value_length * (2 if kind else 1)
        if value_start + size > end:
            raise ValueError('Version resource value exceeds its block')
        value = blob[value_start:value_start + size]
        child = (value_start + size + 3) & ~3
        children = {}
        while child < end:
            if end - child <= 3 and not any(blob[child:end]):
                break
            item, next_child = block(child, end, depth + 1)
            if item['key'] in children:
                raise ValueError('Duplicate version resource block name')
            children[item['key']] = item
            child = (next_child + 3) & ~3
        return {'key': key, 'kind': kind, 'value': value, 'children': children}, end
    root, end = block(0, len(blob), 0)
    if len(blob) - end > 3 or any(blob[end:]) or root['key'] != 'VS_VERSION_INFO' or root['kind'] != 0 or len(root['value']) != 52:
        raise ValueError('Unsupported root version resource shape')
    if set(root['children']) - {'StringFileInfo', 'VarFileInfo'}:
        raise ValueError('Unknown version resource container')
    return root


def _resource(pe, data):
    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[2]
    if not directory.VirtualAddress and not directory.Size:
        return None
    if not directory.VirtualAddress or not 16 <= directory.Size <= len(data):
        raise ValueError('Invalid PE resource directory bounds')
    root = pe.get_offset_from_rva(directory.VirtualAddress)
    if pe.get_offset_from_rva(directory.VirtualAddress + directory.Size - 1) != root + directory.Size - 1:
        raise ValueError('PE resource directory must have a contiguous file mapping')
    def chunk(offset, size):
        if not 0 <= offset <= directory.Size - size or root + offset + size > len(data):
            raise ValueError('PE resource directory points outside its file bounds')
        return data[root + offset:root + offset + size]
    def entries(offset):
        raw = chunk(offset, 16); named, numbered = struct.unpack_from('<HH', raw, 12)
        if named + numbered > 1024:
            raise ValueError('PE resource directory has too many entries')
        raw = chunk(offset + 16, 8 * (named + numbered))
        pairs = [struct.unpack_from('<II', raw, i * 8) for i in range(named + numbered)]
        if len({name for name, _ in pairs}) != len(pairs):
            raise ValueError('Duplicate PE resource directory entry')
        return pairs
    roots = [item for item in entries(0) if item[0] == 16]
    if not roots:
        return None
    if not roots[0][1] & 0x80000000:
        raise ValueError('VERSION resource must have a name directory')
    names = entries(roots[0][1] & 0x7fffffff)
    if len(names) != 1 or names[0][0] != 1 or not names[0][1] & 0x80000000:
        raise ValueError('Exactly one VERSION resource with numeric name1 is supported')
    languages = entries(names[0][1] & 0x7fffffff)
    if len(languages) != 1 or languages[0][0] > 65535 or languages[0][1] & 0x80000000:
        raise ValueError('Exactly one numeric VERSION resource language is supported')
    rva, size, codepage, reserved = struct.unpack('<IIII', chunk(languages[0][1], 16))
    if reserved or not 92 <= size <= MAX_VERSION_BYTES:
        raise ValueError('VERSION resource size or reserved field is unsupported')
    offset = pe.get_offset_from_rva(rva)
    if offset < 0 or offset + size > len(data) or pe.get_offset_from_rva(rva + size - 1) != offset + size - 1:
        raise ValueError('VERSION resource data points outside the input file')
    return data[offset:offset + size], languages[0][0], codepage


def inspect_executable(raw_exe, *, year, context=None):
    """Read an explicit PE without loading/executing it or selecting an installation."""
    validate_year(year); context = validate_context(context)
    if type(raw_exe) is not bytes or not 64 <= len(raw_exe) <= MAX_EXE_BYTES:
        raise ValueError('EXE must be bounded PE bytes, from64 bytes through64MiB')
    try:
        import pefile
    except ImportError as error:
        raise RuntimeError('Install cbus-toolkit-cli[research] to read PE resources') from error
    try:
        pe = pefile.PE(data=raw_exe, fast_load=True)
        if len(pe.sections) > 96 or len(pe.OPTIONAL_HEADER.DATA_DIRECTORY) < 3 or pe.OPTIONAL_HEADER.Magic not in (0x10b, 0x20b):
            raise ValueError('Unsupported PE header bounds')
        resource = _resource(pe, raw_exe)
        machine = pe.FILE_HEADER.Machine
    except pefile.PEFormatError as error:
        raise ValueError('Cannot read the supplied PE headers or resource addresses') from error
    resource_name = None; strings = {}; fixed = None; language = codepage = None
    version = None; flags = 0
    if resource is not None:
        blob, language, codepage = resource
        try:
            tree = _version_tree(blob)
            words = struct.unpack('<13I', tree['value'])
            if words[0] != 0xfeef04bd or words[1] != 0x10000:
                raise ValueError('Unsupported fixed version signature or structure version')
            fixed = dict(zip(('signature', 'structure_version', 'file_version_ms', 'file_version_ls',
                'product_version_ms', 'product_version_ls', 'file_flags_mask', 'file_flags', 'file_os', 'file_type',
                'file_subtype', 'file_date_ms', 'file_date_ls'), words))
            version = (words[2] >> 16, words[2] & 65535, words[3] >> 16, words[3] & 65535); flags = words[7]
            container = tree['children'].get('StringFileInfo')
            if container is not None:
                if container['value'] or len(container['children']) != 1:
                    raise ValueError('Exactly one empty-value StringFileInfo table is supported')
                table = next(iter(container['children'].values()))
                if not re.fullmatch('[0-9a-fA-F]{8}', table['key']) or table['value']:
                    raise ValueError('Unsupported version string-table identity')
                for name, child in table['children'].items():
                    if child['kind'] != 1 or child['children']:
                        raise ValueError('Version strings must be text leaves')
                    value = child['value'].decode('utf-16le')
                    if value and not value.endswith('\0'):
                        raise ValueError('Version string value must be terminated')
                    strings[name] = _text(value[:-1] if value else '', 'version string')
                resource_name = strings.get('ProductName')
        except UnicodeError as error:
            raise ValueError('Version resource contains unsupported Unicode') from error
    name = resource_name if resource_name is not None else TOOLKIT_NAME
    result = format_about(version, flags=flags, year=year, product_name=name, context=context).as_dict()
    result.update(executable_sha256=hashlib.sha256(raw_exe).hexdigest(), executable_size=len(raw_exe),
        executable_executed=False, executable_authenticity_verified=False,
        matches_pinned_toolkit_1_18=hashlib.sha256(raw_exe).hexdigest() == PINNED_TOOLKIT_SHA256,
        resource_product_name=resource_name,
        executable_resource={'status':'available' if resource else 'missing', 'machine':machine,
            'language':language, 'codepage':codepage, 'fixed_file_info':fixed, 'strings':strings,
            'sha256':hashlib.sha256(resource[0]).hexdigest() if resource else None,
            'file_flags_mask_applied':False})
    result['provenance'].update(version='explicit EXE fixed file-version words' if resource else 'missing EXE VERSION resource',
        flags='explicit EXE fixed FileFlags; mask ignored by original reader' if resource else 'no VERSION resource',
        display_name='explicit EXE ProductName string substituted for original live application-name provider'
            if resource_name is not None else 'Toolkit profile fallback; EXE ProductName absent')
    return AboutReport(json.dumps(result, ensure_ascii=True))
