"""Execute original SCNCTL5 report methods over synthetic scene getters.

DocumentHTML, ActionSelectorUse, IsSceneUnused, the input dependency method and
the master-selector AsString/extended-tag chain execute. All loaders, remaining
object accessors, string routines and common HTML formatters are synthetic leaves.
No GUI, project, network or hardware.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESP

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256

PREFIX = 'CIS_TCustomSceneControllerDocumentor.TCustomSceneControllerDocumentor.'
METHODS = {'body': PREFIX + 'DocumentHTML', 'action': PREFIX + 'ActionSelectorUse',
           'unused': PREFIX + 'IsSceneUnused',
           'input': 'CIS_TCustomSceneUnit.TCustomSceneUnit.DescribeInputGroupDependencyAdvanced',
           'as_string': 'CIS_TCustomFlashObject.TCustomFlashObject.GetAsString',
           'internal_representation': 'CIS_TCustomFlashObject.TCustomFlashObject.InternalGetDefaultRepresentation',
           'level_representation': 'CIS_TCommonCBus.TLevel.GetDefaultRepresentation',
           'extended_tag': 'CIS_TCommonCBus.TLevel.GetExtendedTagName'}
RETURN = 0x30000000
DOC, UNIT, STRINGS, SCENES, RESULT = (0x20000100 + n * 0x400 for n in range(5))
LIST_VMT, STRING_VMT, LEVEL_VMT = 0x20002000, 0x20002400, 0x20002800
COUNT, ADD, INDEX, NAME = (0x20004000 + n * 0x10 for n in range(4))
RAMP_LABELS = ('Instant', '4 secs', '8 secs', '12 secs', '20 secs', '30 secs', '40 secs', '60 secs',
               '90 secs', '120 secs', '180 secs', '300 secs', '420 secs', '600 secs', '900 secs', '1020 secs')


class OriginalSceneControllerProbe:
    def __init__(self, exe, map_file):
        raw, symbols = exe.read_bytes(), map_file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
            raise ValueError('Original Toolkit EXE/MAP hash mismatch')
        self.t = _Toolkit(raw, symbols)
        self.methods = {key: self.t.method(value) for key, value in METHODS.items()}
        self.image = self.t.pe.get_memory_mapped_image()

    def run(self, case, kind, query=None):
        t = self.t
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 4096)
        u.mem_map(t.base, (len(self.image) + 4095) & ~4095)
        u.mem_write(t.base, self.image)
        u.mem_map(0x20000000, 0x100000)
        u.mem_map(0x21000000, 0x10000)
        u.mem_map(RETURN, 4096)
        next_string = 0x20080000
        lines, lists, commands, scene_selectors = [], {}, {}, {}

        def put(address, value):
            u.mem_write(address, struct.pack('<I', value))

        def get(address):
            return struct.unpack('<I', u.mem_read(address, 4))[0]

        def text(pointer):
            return '' if not pointer else bytes(u.mem_read(pointer, get(pointer - 4) * 2)).decode('utf-16le')

        def write(destination, value):
            nonlocal next_string
            if not value:
                put(destination, 0)
                return
            encoded = value.encode('utf-16le')
            pointer = next_string + 12
            next_string += (len(encoded) + 31) & ~15
            u.mem_write(pointer - 12, struct.pack('<HHiI', 1200, 2, -1, len(encoded) // 2) + encoded + b'\0\0')
            put(destination, pointer)

        def finish(value=None, pop=0):
            if value is not None:
                u.reg_write(UC_X86_REG_EAX, value)
            stack = u.reg_read(UC_X86_REG_ESP)
            u.reg_write(UC_X86_REG_EIP, get(stack))
            u.reg_write(UC_X86_REG_ESP, stack + 4 + pop)

        groups = {(case['application'], command[0]) for scene in case['scenes'] for command in scene}
        groups.add((202, case['control_group']))
        if kind == 'input':
            groups.add(tuple(query))
        group_pointers = {key: 0x20010000 + n * 0x100 for n, key in enumerate(sorted(groups))}
        group_keys = {value: key for key, value in group_pointers.items()}
        selectors = set(case['selectors']) | {case['master_selector']}
        level_keys = {(202, case['control_group'], address) for address in selectors}
        if kind == 'action':
            level_keys.add(tuple(query))
        level_pointers = {key: 0x20020000 + n * 0x100 for n, key in enumerate(sorted(level_keys))}
        levels = {value: key for key, value in level_pointers.items()}
        tags = {}
        for index, pointer in enumerate(levels):
            put(pointer, LEVEL_VMT)
            attr = 0x20070000 + index * 0x100
            put(pointer + 0x9c, attr)
            u.mem_write(pointer + 0xbc, b'\x01')
            put(attr, 0x20002c00)
            tags[attr] = f'Action <{levels[pointer][2]}>'
        put(0x20002c00 + 0x2c, NAME)
        put(LEVEL_VMT + 0x2c, self.methods['as_string']['start'])
        put(LEVEL_VMT + 0x58, self.methods['level_representation']['start'])
        put(LEVEL_VMT + 0x94, self.methods['extended_tag']['start'])
        put(LEVEL_VMT + 0x24, t.by_name['CIS_TManagedFlashObject.TManagedFlashObject.ResolveChange'])
        scene_pointers = [0x20030000 + i * 0x200 for i in range(len(case['scenes']))]
        lists[SCENES] = scene_pointers
        for index, (pointer, scene) in enumerate(zip(scene_pointers, case['scenes'])):
            collection = 0x20040000 + index * 0x200
            put(pointer + 0x80, collection)
            command_pointers = [0x20050000 + (index * 16 + k) * 0x100 for k in range(len(scene))]
            lists[collection] = command_pointers
            commands.update(zip(command_pointers, scene))
            scene_selectors[pointer] = level_pointers[202, case['control_group'], case['selectors'][index]]
        for pointer in lists:
            put(pointer, LIST_VMT)
        put(UNIT + 0x1c8, SCENES)
        put(LIST_VMT + 0x58, COUNT)
        put(LIST_VMT + 0x78, INDEX)
        put(STRINGS, STRING_VMT)
        put(STRING_VMT + 0x38, ADD)
        hooks = {}

        def bind(suffix, callback):
            matches = [address for address, names in t.symbols.items() if any(name.endswith(suffix) for name in names)]
            if not matches:
                raise ValueError('Missing original symbol: ' + suffix)
            for address in matches:
                hooks[address] = callback

        bind('TUnitTypeDocumentor.DocumentHTML', lambda a, d, c: finish())
        bind('TUnitTypeDocumentor.ActionSelectorUse', lambda a, d, c: (write(RESULT, ''), finish(pop=4)))
        bind('TCBUSUnit.DescribeInputGroupDependencyAdvanced', lambda a, d, c: (write(c, ''), finish()))
        bind('System.@IsClass', lambda a, d, c: finish(1))
        bind('CIS_GlobalSoftwareParameters.UseAddressValueFormat', lambda a, d, c: finish(0))
        bind('TManagedFlashObject.ResolveChange', lambda a, d, c: finish())
        bind('TCustomSceneControllerUnit.GetControlAppGroup', lambda a, d, c: finish(group_pointers[202, case['control_group']]))
        bind('TCustomSceneControllerUnit.GetMasterOffTriggerLevel', lambda a, d, c: finish(level_pointers[202, case['control_group'], case['master_selector']]))
        bind('TCustomSceneControllerUnit.GetMasterOffRampRate', lambda a, d, c: finish(case['master_ramp']))
        bind('TSceneCollection.GetItem', lambda a, d, c: finish(lists[a][d]))
        bind('TSceneCommandCollection.GetItem', lambda a, d, c: finish(lists[a][d]))
        bind('TScene.GetTriggerLevel', lambda a, d, c: finish(scene_selectors[a]))
        bind('TSceneCommand.GetGroup', lambda a, d, c: finish(group_pointers[case['application'], commands[a][0]]))
        bind('TSceneCommand.GetLevelAsPercent', lambda a, d, c: finish((commands[a][1] + 2) * 100 // 255))
        bind('TSceneCommand.GetRampRate', lambda a, d, c: finish(commands[a][2]))
        bind('TSceneCommand.GetMasterOffAllowed', lambda a, d, c: finish(int(commands[a][3])))
        bind('TCBusGroup.IsUnused', lambda a, d, c: finish(int(group_keys[a][1] == 255)))
        bind('GetDescriptionFromEnumeratedValueOrdinalValue', lambda a, d, c: (write(c, RAMP_LABELS[d]), finish()))

        def group_html(a, d, c):
            application, address = group_keys[a]
            value = ('&#60;Unused&#62;' if address == 255 else
                     f'<a href="#{case["network"]}_{application}_{address}">Group <{address}></a>')
            write(d, value)
            finish()
        bind('TDocumentorCommon.DisplayHTMLGroup', group_html)

        def level_html(a, d, c):
            application, group, address = levels[a]
            write(d, f'<a href="#{case["network"]}_{application}_{group}_{address}">Action <{address}></a>')
            finish()
        bind('TDocumentorCommon.DisplayHTMLLevel', level_html)
        bind('SysUtils.IntToStr', lambda a, d, c: (write(d, str(a)), finish()))
        bind('System.LoadResString', lambda a, d, c: (write(d, t.resource(a)), finish()))
        bind('SysUtils.Format', lambda a, d, c: (write(get(u.reg_read(UC_X86_REG_ESP) + 4), text(a) % get(d)), finish(pop=4)))
        bind('System.@UStrAsg', lambda a, d, c: (write(a, text(d)), finish()))
        bind('System.@UStrLAsg', lambda a, d, c: (write(a, text(d)), finish()))
        bind('System.@UStrCat', lambda a, d, c: (write(a, text(get(a)) + text(d)), finish()))
        bind('System.@UStrClr', lambda a, d, c: finish())
        bind('System.@UStrArrayClr', lambda a, d, c: finish())

        def concatenate(a, count, c):
            stack = u.reg_read(UC_X86_REG_ESP)
            write(a, ''.join(reversed([text(get(stack + 4 + n * 4)) for n in range(count)])))
            finish(pop=count * 4)
        bind('System.@UStrCatN', concatenate)

        def intercept(_u, pc, _size, _data):
            a, d, c = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
            if pc in hooks:
                hooks[pc](a, d, c)
            elif pc == COUNT:
                finish(len(lists[a]))
            elif pc == INDEX:
                finish(lists[a].index(d))
            elif pc == ADD:
                lines.append(text(d))
                finish(len(lines) - 1)
            elif pc == NAME:
                write(d, tags[a])
                finish()
            elif not any(method['start'] <= pc < method['end'] for method in self.methods.values()):
                raise AssertionError(f'Unexpected original execution at {pc:#x}')
        u.hook_add(UC_HOOK_CODE, intercept)
        stack = 0x21008000
        put(stack, RETURN)
        put(stack + 4, RESULT)
        u.reg_write(UC_X86_REG_ESP, stack)
        u.reg_write(UC_X86_REG_EAX, UNIT if kind == 'input' else DOC)
        u.reg_write(UC_X86_REG_EDX, STRINGS if kind == 'body' else level_pointers[tuple(query)] if kind == 'action' else group_pointers[tuple(query)])
        u.reg_write(UC_X86_REG_ECX, RESULT if kind == 'input' else UNIT)
        u.emu_start(self.methods[kind]['start'], RETURN, count=200000)
        if u.reg_read(UC_X86_REG_EIP) != RETURN:
            raise AssertionError('Original scene-controller method did not return')
        return lines if kind == 'body' else text(get(RESULT))


def cases():
    empty = [[255, 255, 0, True]] * 9
    base = {'network': 254, 'application': 56, 'control_group': 8, 'master_selector': 11,
            'master_ramp': 7, 'selectors': [11, 22, 11, 44, 255],
            'scenes': [empty, [[1, 0, 1, True], [1, 255, 13, True], [2, 128, 15, False]] + empty[:6],
                       [[2, 1, 0, False]] + empty[:8], empty, [[1, 129, 3, True]] + empty[:8]]}
    return [{**base, 'name': 'sparse-duplicate-boundaries'},
            {**base, 'name': 'unused-control', 'control_group': 255},
            {**base, 'name': 'all-unused', 'scenes': [empty] * 5},
            {**base, 'name': 'all-master-and-scene-matches', 'selectors': [11] * 5,
             'scenes': [[[1, index, index, bool(index % 2)]] + empty[:8] for index in range(5)]}]


def capture(exe, map_file):
    probe = OriginalSceneControllerProbe(exe, map_file)
    rows = []
    for case in cases():
        actions = [[202, case['control_group'], address] for address in (11, 22, 255, 99)] + [[56, case['control_group'], 11], [202, 9, 11]]
        groups = [[56, address] for address in (1, 2, 255, 99)] + [[202, 1]]
        rows.append({**case, 'lines': probe.run(case, 'body'),
                     'actions': [{'query': query, 'html': probe.run(case, 'action', query)} for query in actions],
                     'inputs': [{'query': query, 'native': probe.run(case, 'input', query)} for query in groups]})
    return {'format': 'cbus-project-documentor-scene-controller-original-v1',
            'exe_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256,
            'original_methods_executed': True, 'original_loader_executed': False,
            'original_generated_page_compared': False,
            'master_selector_format_basis': 'standard tag-name profile; DisplayAddressValue=false (original fresh default)',
            'boundary': 'Original body/action/input-dependency/IsSceneUnused plus Level.AsString/default-representation/extended-tag instructions, with explicit standard-format preference, synthetic getters, collections, common HTML formatters and Delphi string leaves. No original loader, project, GUI, network or hardware.',
            'methods': {key: {'symbol': METHODS[key], 'start': hex(row['start']), 'end': hex(row['end']), 'sha256': row['sha256']}
                        for key, row in probe.methods.items()}, 'cases': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = capture(args.exe, args.map)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'cases': len(report['cases']), 'calls': sum(1 + len(c['actions']) + len(c['inputs']) for c in report['cases'])}))
