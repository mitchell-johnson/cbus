"""Bounded original classic ICON acceptance and language visibility evidence.

The original OK button, default-type predicates and Execute visibility/type
selection fragment run against synthetic controls, tags and finalizer hooks.
No GUI, image renderer, project store, C-Gate or physical labels are executed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX as EAX, UC_X86_REG_EBP as EBP,
                               UC_X86_REG_ECX as ECX, UC_X86_REG_EDX as EDX,
                               UC_X86_REG_EIP as EIP, UC_X86_REG_ESP as ESP)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classic_dlt_controls_original import (ClassicControlsProbe, EXE_SHA256,
                                            MAP_SHA256)  # noqa: E402

FORMAT = 'cbus-classic-dlt-icon-dialog-original-v1'
FORM_NAME = 'CIS_TfrmEditDLTLabel.TfrmEditDLTLabel.'
LANGUAGE_NAME = 'CIS_TGroupLanguage.TGroupLanguage.'
FLAVOUR_NAME = 'CIS_TGroupLanguage.TGroupLanguageFlavour.'
METHODS = {
    'icon_ok': FORM_NAME + 'btnOKClick',
    'execute': FORM_NAME + 'Execute',
    'prepare_tabs': FORM_NAME + 'PrepareTabs',
    'radio_click': FORM_NAME + 'rbTabLabelTextClick',
    'form_show': FORM_NAME + 'FormShow',
    'predefined_default': LANGUAGE_NAME + 'GetHasTagTypePredefined',
    'text_default': LANGUAGE_NAME + 'GetHasTagTypeText',
    'group_finalise': 'CIS_TCommonCBus.TCBusGroup.FinaliseLanguage',
    'level_finalise': 'CIS_TCommonCBus.TLevel.FinaliseLanguage',
}
VISIBILITY = (0xC125D0, 0xC12672)
FORM, PAGES, ICON_PAGE, FLAVOUR, TAG, LANGUAGE, LANGUAGE_TYPE, TARGET = (
    0x30001000, 0x30002000, 0x30003000, 0x30004000,
    0x30005000, 0x30006000, 0x30007000, 0x30007800)
COMBO, PROPERTIES, ITEMS, ITEM, VMT, GET_INDEX, SET_CHECKED = (
    0x30008000, 0x30008200, 0x30008400, 0x30008600,
    0x30008800, 0x30008E00, 0x30008F00)
RADIOS = {'TEXT': 0x3000A000, 'ICON': 0x3000A100,
          'DYNAMIC': 0x3000A200, 'FONT': 0x3000A300}
STACK, FRAME, RETURN = 0x20006000, 0x20008000, 0x3000F000


class IconDialogProbe(ClassicControlsProbe):
    def __init__(self, executable, symbols):
        super().__init__(executable, symbols)
        self.methods = {key: self.method(name) for key, name in METHODS.items()}

    def static_facts(self):
        def require(key, *markers):
            rows = [row[1:] for row in self.methods[key]['instructions']]
            assert all(marker in rows for marker in markers), key
        require('icon_ok', ('call', 'dword ptr [edx + 0x468]'),
                ('jl', '0xc13d52'), ('mov', 'dl, 1'),
                ('lea', 'edx, [eax + 0x18]'), ('call', '0x62ea8c'))
        require('predefined_default', ('cmp', 'eax, 0xca'))
        require('text_default', ('test', 'eax, eax'), ('cmp', 'eax, 0xca'))
        require('execute', ('cmp', 'eax, 0xca'), ('call', '0x6f68dc'),
                ('cmp', 'byte ptr [eax + 0x47a], 0'))
        require('prepare_tabs', ('call', '0xc1387c'))
        for address in (0xC13D8F, 0xC13DC2):
            assert next(row[1:] for row in self.methods['icon_ok']['instructions']
                        if row[0] == address) == ('xor', 'ecx, ecx')
        return {
            'source': {'executable_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256},
            'methods': {key: {'symbol': METHODS[key], **self.span(m['start'], m['end'])}
                        for key, m in self.methods.items()},
            'fragments': {'execute_visibility_and_existing_type': self.span(*VISIBILITY)},
            'rules': {
                'visible_icon_choice': 'Execute hides the ICON radio unless current language ID is202; this is the visible-choice gate, not the default-type predicate',
                'existing_type': 'Execute checks the radio for existing TEXT0, ICON1, DYNAMIC2 or FONT3, even if the ICON radio was hidden for a non202 language',
                'force_graphic': 'Later Execute form+0x47a can override selection to DYNAMIC and disable TEXT; excluded from this ordinary ICON transaction',
                'tab_activation': 'FormShow invokes shared radio-click handler, which activates its page, calls PrepareTabs and RefreshControls; checked ICON invokes PopulatePredefinedGraphicsList without another language gate',
                'default_predicates': 'Predefined default iff nonnil LanguageType ID202; text default iff nonnil ID neither0 nor202. These govern collection initialization and do not disable TEXT in Execute',
                'selection': 'Negative combo ItemIndex skips tag mutation; otherwise SetTagType(1), obtain Items[ItemIndex].Value and VarToUStr, then SetTagValue',
                'identifier': 'Combo item Value is the integer parsed from catalogue name; ImageIndex and selected ItemIndex are separate and are not the stored ICON identifier',
                'handler_validation': 'The OK branch itself does not check catalogue membership, language ID or decimal range; the portable API admits only explicitly selected pinned built-in IDs1..91 and ordinary language202',
                'accept': 'Both selected and unselected branches reach ModalResult1; ordinary acceptance clears selected flavour broadcast flag then finalizes the entire selected language for group or level with nil supplied-model override',
                'deferred': 'form+0x478 skips broadcast reset and FinaliseLanguage but still accepts the chosen tag value',
                'collection': 'Fresh selected202 language defaults missing flavour1 to ICON with constructor-empty value; existing TEXT/ICON retain type and take20 UTF16 units; false initialization deletes missing cached alternates; finalization visits all4 flavours and retains chosen legacy0 identity',
                'boundary': 'Collection behavior is independently pinned by the existing language-dialog collection receipt; this probe hooks finalizers and does not execute graph allocation or persistent storage',
            },
        }

    def _machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(self.base, (len(self.memory) + 4095) & ~4095)
        u.mem_write(self.base, self.memory)
        for base in (0, 0x20000000, 0x30000000):
            u.mem_map(base, 0x10000)
        put = lambda address, value: u.mem_write(address, struct.pack('<I', value & 0xFFFFFFFF))
        read = lambda address: struct.unpack('<I', u.mem_read(address, 4))[0]
        for address, value in ((FORM + 0x3AC, PAGES), (PAGES + 0x2D4, ICON_PAGE),
                               (FORM + 0x3EC, ICON_PAGE), (FORM + 0x458, FLAVOUR),
                               (FORM + 0x430, COMBO), (COMBO, VMT),
                               (VMT + 0x468, GET_INDEX), (PROPERTIES + 0x194, ITEMS),
                               (VMT + 0xF0, SET_CHECKED), (FRAME - 4, FORM)):
            put(address, value)
        for name, offset in (('TEXT', 0x3A0), ('ICON', 0x450),
                             ('DYNAMIC', 0x3A4), ('FONT', 0x3A8)):
            put(FORM + offset, RADIOS[name])
            put(RADIOS[name], VMT)

        def string(address):
            return (bytes(u.mem_read(address, read(address - 4) * 2)).decode('utf-16-le')
                    if address else '')

        def allocate(value):
            if not value:
                return 0
            raw, address = value.encode('utf-16-le'), self.next_string + 8
            assert address + len(raw) + 2 < 0x3000E000
            put(address - 4, len(raw) // 2)
            u.mem_write(address, raw + b'\0\0')
            self.next_string = (address + len(raw) + 5) & ~3
            return address

        def ret(value=None):
            stack = u.reg_read(ESP)
            if value is not None:
                u.reg_write(EAX, value & 0xFFFFFFFF)
            u.reg_write(EIP, read(stack))
            u.reg_write(ESP, stack + 4)

        getters = {self.by_name[FLAVOUR_NAME + 'GetDLTTag']: TAG,
                   self.by_name[FLAVOUR_NAME + 'GetGroupLanguage']: LANGUAGE}
        finalisers = {self.methods[key + '_finalise']['start']: key for key in ('group', 'level')}
        allowed = [(self.methods[key]['start'], self.methods[key]['end'])
                   for key in ('icon_ok', 'predefined_default', 'text_default')]
        allowed.append(VISIBILITY)

        def hook(_u, address, _size, _data):
            if address in (RETURN, VISIBILITY[1]):
                u.emu_stop()
            elif address in getters:
                ret(getters[address])
            elif address == self.by_name[LANGUAGE_NAME + 'GetLanguageType']:
                ret(0 if self.language_id is None else LANGUAGE_TYPE)
            elif address == self.by_name['CIS_TLanguageType.TLanguageType.GetIdentifier']:
                assert self.language_id is not None
                ret(self.language_id)
            elif address == self.by_name['CIS_TLanguageTag.TLanguageTag.GetTagType']:
                ret(self.tag_type)
            elif address == self.by_name['Controls.TControl.Hide']:
                assert u.reg_read(EAX) == RADIOS['ICON']
                self.icon_hidden = True
                ret()
            elif address == SET_CHECKED:
                self.checked = next(name for name, value in RADIOS.items() if value == u.reg_read(EAX))
                assert u.reg_read(EDX) & 255 == 1
                ret()
            elif address == GET_INDEX:
                assert u.reg_read(EAX) == COMBO
                self.index_reads += 1
                ret(self.index)
            elif address == self.by_name['cxImageComboBox.TcxImageComboBox.GetProperties']:
                assert u.reg_read(EAX) == COMBO
                ret(PROPERTIES)
            elif address == self.by_name['cxImageComboBox.TcxImageComboBoxItems.GetItems']:
                assert u.reg_read(EAX) == ITEMS and u.reg_read(EDX) == self.index
                self.item_reads.append(self.index)
                ret(ITEM)
            elif address == self.by_name['Variants.@VarToUStr']:
                assert u.reg_read(EDX) == ITEM + 0x18
                put(u.reg_read(EAX), allocate(str(self.icon_id)))
                ret()
            elif address == self.by_name['CIS_TLanguageTag.TLanguageTag.SetTagType']:
                assert u.reg_read(EAX) == TAG
                self.tag_type = u.reg_read(EDX) & 255
                self.calls.append({'operation': 'SetTagType', 'value': self.tag_type})
                ret()
            elif address == self.by_name['CIS_TLanguageTag.TLanguageTag.SetTagValue']:
                assert u.reg_read(EAX) == TAG
                self.tag_value = string(u.reg_read(EDX))
                self.calls.append({'operation': 'SetTagValue', 'value': self.tag_value})
                ret()
            elif address in finalisers:
                assert u.reg_read(EAX) == TARGET and u.reg_read(EDX) == LANGUAGE_TYPE
                assert u.reg_read(ECX) == 0
                self.calls.append({'operation': 'FinaliseLanguage', 'target': finalisers[address],
                                   'language': self.language_id, 'supplied_model': None})
                ret()
            elif address == self.by_name['System.@UStrArrayClr']:
                ret()
            elif not any(start <= address < stop for start, stop in allowed):
                raise AssertionError(f'Unexpected original execution at {address:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        self.put = put
        return u

    def machine(self):
        if not hasattr(self, '_cached_machine'):
            self._cached_machine = self._machine()
        return self._cached_machine

    def run(self, index, icon_id, *, target='group', deferred=False):
        u = self.machine()
        self.index, self.icon_id, self.language_id = index, icon_id, 202
        self.next_string, self.tag_type, self.tag_value = 0x3000C000, 0, 'before'
        self.index_reads, self.item_reads, self.calls = 0, [], []
        for offset, value in ((0x45C, TARGET if target == 'group' else 0),
                               (0x460, TARGET if target == 'level' else 0), (0x2B8, 0)):
            self.put(FORM + offset, value)
        u.mem_write(FORM + 0x478, bytes([int(deferred)]))
        u.mem_write(FLAVOUR + 0xC4, b'\1')
        self.put(STACK, RETURN)
        u.reg_write(EAX, FORM)
        u.reg_write(ESP, STACK)
        u.emu_start(self.methods['icon_ok']['start'], RETURN, count=3000)
        assert u.reg_read(EIP) == RETURN
        return {'selected_index': index, 'item_integer_value': icon_id,
                'target': target, 'deferred': deferred,
                'result': {'accepted': u.mem_read(FORM + 0x2B8, 4) == b'\1\0\0\0',
                           'tag_type': self.tag_type, 'tag_value': self.tag_value,
                           'index_reads': self.index_reads, 'item_reads': self.item_reads,
                           'broadcast_marked': bool(u.mem_read(FLAVOUR + 0xC4, 1)[0]),
                           'calls': self.calls}}

    def eligibility(self, language_id):
        u = self.machine()
        self.language_id = language_id
        result = {'language_id': language_id}
        for key in ('predefined_default', 'text_default'):
            self.put(STACK, RETURN)
            u.reg_write(EAX, LANGUAGE)
            u.reg_write(ESP, STACK)
            u.emu_start(self.methods[key]['start'], RETURN, count=300)
            assert u.reg_read(EIP) == RETURN
            result[key] = bool(u.reg_read(EAX) & 255)
        result['execute_fragment'] = []
        if language_id is not None:
            for self.tag_type in range(4):
                self.icon_hidden, self.checked = False, None
                u.reg_write(EBP, FRAME)
                u.reg_write(ESP, STACK)
                u.emu_start(VISIBILITY[0], VISIBILITY[1], count=300)
                assert u.reg_read(EIP) == VISIBILITY[1]
                result['execute_fragment'].append({'saved_tag_type': self.tag_type,
                                                   'icon_hidden': self.icon_hidden,
                                                   'checked': self.checked})
        return result

    def observations(self, catalogue):
        rows = [self.run(index, icon_id, target='group' if index % 2 == 0 else 'level')
                for index, icon_id in enumerate(catalogue['ordered_ids'])]
        rows.extend([self.run(42, 1), self.run(0, 92), self.run(-1, None),
                     self.run(-1, None, target='level'), self.run(90, 91, deferred=True)])
        for row in rows:
            result = row['result']
            assert result['accepted']
            assert result['tag_type'] == (1 if row['selected_index'] >= 0 else 0)
            assert result['tag_value'] == (str(row['item_integer_value'])
                                            if row['selected_index'] >= 0 else 'before')
            assert result['broadcast_marked'] == row['deferred']
        eligibility = [self.eligibility(value) for value in (None, 0, 1, 14, 64, 116, 202, 255)]
        for row in eligibility:
            assert row['predefined_default'] == (row['language_id'] == 202)
            assert row['text_default'] == (row['language_id'] not in (None, 0, 202))
            for visible in row['execute_fragment']:
                assert visible['icon_hidden'] == (row['language_id'] != 202)
                assert visible['checked'] == ('TEXT', 'ICON', 'DYNAMIC', 'FONT')[visible['saved_tag_type']]
        return {'icon_ok': rows, 'eligibility': eligibility}


def inspect(executable: Path, symbols: Path, catalogue_index: Path):
    from classic_dlt_icon_catalogue_original import catalogue_facts
    from classic_dlt_language_collection_original import collection_facts
    probe = IconDialogProbe(executable, symbols)
    catalogue = catalogue_facts(probe, catalogue_index)
    return {'format': FORMAT, **probe.static_facts(), 'catalogue': catalogue,
            'observations': probe.observations(catalogue), 'collection': collection_facts(probe),
            'boundary': 'Original ICON OK button, default predicates and visibility/type fragment only; synthetic VCL/Variant/tag/finalizer hooks. Catalogue and collection source extraction only. No full native or managed GUI, bitmap rendering, server persistence or physical labels.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--catalogue-index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.executable, args.map, args.catalogue_index)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'format': FORMAT, 'icon_ok_cases': len(report['observations']['icon_ok']),
                      'eligibility_cases': len(report['observations']['eligibility']),
                      'catalogue_rows': len(report['catalogue']['ordered_ids']), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
