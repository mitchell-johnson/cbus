"""Bounded original TEXT acceptance plus static collection/network receipts.

Original button and Unicode-predicate instructions execute with synthetic VCL,
strings, tag storage, confirmation and finalizer hooks. No full GUI or transport.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import struct
import sys

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX as EAX, UC_X86_REG_ECX as ECX,
                               UC_X86_REG_EDX as EDX, UC_X86_REG_EIP as EIP,
                               UC_X86_REG_ESP as ESP)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classic_dlt_controls_original import (EXE_SHA256, MAP_SHA256,
                                            ClassicControlsProbe)  # noqa: E402

FORMAT = 'cbus-classic-dlt-language-dialog-original-v1'
FORM, PAGES, TEXT_PAGE, FLAVOUR, TAG, LANGUAGE, LANGUAGE_TYPE, TARGET = (
    0x30001000, 0x30002000, 0x30003000, 0x30004000,
    0x30005000, 0x30006000, 0x30007000, 0x30007800)
STACK, RETURN = 0x20008000, 0x3000F000
FORM_NAME = 'CIS_TfrmEditDLTLabel.TfrmEditDLTLabel.'
FLAVOUR_NAME = 'CIS_TGroupLanguage.TGroupLanguageFlavour.'
METHODS = {'text_ok': FORM_NAME + 'btnOKClick',
           'unicode_predicate': FORM_NAME + 'ContainUnicode', 'execute': FORM_NAME + 'Execute',
           'group_dialog': 'CIS_TCBusGroupGUIAgent.TCBusGroupGUIAgent.DynamicLabelDialog',
           'group_editor': 'CIS_TCBusGroupGUIAgent.TCBusGroupGUIAgent.EditDLTTags',
           'group_initialise': 'CIS_TCommonCBus.TCBusGroup.InitialiseLanguages',
           'level_initialise': 'CIS_TCommonCBus.TLevel.InitialiseLanguages',
           'group_finalise': 'CIS_TCommonCBus.TCBusGroup.FinaliseLanguage',
           'level_finalise': 'CIS_TCommonCBus.TLevel.FinaliseLanguage'}


class TextDialogProbe(ClassicControlsProbe):
    def __init__(self, executable, symbols):
        super().__init__(executable, symbols)
        self.methods = {key: self.method(name) for key, name in METHODS.items()}

    def static_facts(self):
        button = [(m, op) for _, m, op in self.methods['text_ok']['instructions']]
        assert ('mov', 'ecx, 0x14') in button and ('mov', 'edx, 1') in button
        assert '<Default>' in self.methods['text_ok']['literals']
        assert ('cmp', 'word ptr [eax + edx*2 - 2], 0xff') in [
            (m, op) for _, m, op in self.methods['unicode_predicate']['instructions']]
        for address in (0xED8A1F, 0xED8A2B):
            assert next(row[1:] for row in self.methods['group_dialog']['instructions']
                        if row[0] == address) == ('xor', 'edx, edx')
        for address in (0xC13D8F, 0xC13DC2):
            assert next(row[1:] for row in self.methods['text_ok']['instructions']
                        if row[0] == address) == ('xor', 'ecx, ecx')
        return {
            'source': {'executable_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256},
            'methods': {key: {'symbol': METHODS[key], **self.span(m['start'], m['end'])}
                        for key, m in self.methods.items()},
            'rules': {
                'text_action': 'Set TagType TEXT; empty input becomes <Default>; otherwise copy first20 UTF16 code units',
                'unicode_guard': 'Scan entire original input for any UTF16 code unit greater than255 before truncating; a positive confirmation result1 is required',
                'accept': 'If not deferred, clear selected flavour broadcast flag and FinaliseLanguage for its language with no supplied language-model override',
                'finalise_scope': 'Whole selected language collection, not only edited flavour',
                'initialise_call': 'Native group/level callback invokes InitialiseLanguages(false)',
                'editor_entry': 'Group EditDLTTags initializes Network,Group(false),Network then creates managed label dialog; this receipt does not run that managed dialog',
                'prerequisites': 'Explicit current language cache and owner display string when default flavour1 is missing; XML alone does not prove user preferences or retained model cache',
            },
        }

    def _machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(self.base, (len(self.memory) + 4095) & ~4095)
        u.mem_write(self.base, self.memory)
        for address in (0, 0x20000000, 0x30000000):
            u.mem_map(address, 0x10000)
        put = lambda address, value: u.mem_write(address, struct.pack('<I', value))
        put(FORM + 0x3AC, PAGES)
        put(PAGES + 0x2D4, TEXT_PAGE)
        put(FORM + 0x3B0, TEXT_PAGE)
        put(FORM + 0x458, FLAVOUR)

        def read(address):
            return struct.unpack('<I', u.mem_read(address, 4))[0]

        def read_string(address):
            return (bytes(u.mem_read(address, read(address - 4) * 2)).decode('utf-16-le', 'surrogatepass')
                    if address else '')

        def write_string(value):
            if not value:
                return 0
            raw = value.encode('utf-16-le', 'surrogatepass')
            target = self.string_next + 8
            assert target + len(raw) + 2 < 0x3000E000
            put(target - 4, len(raw) // 2)
            u.mem_write(target, raw + b'\x00\x00')
            self.string_next = (target + len(raw) + 5) & ~3
            return target

        def ret(value=None, cleanup=0):
            stack = u.reg_read(ESP)
            if value is not None:
                u.reg_write(EAX, value)
            u.reg_write(EIP, read(stack))
            u.reg_write(ESP, stack + 4 + cleanup)

        noops = {self.by_name[name] for name in ('System.@UStrArrayClr',
                 'Forms.TApplication.NormalizeTopMosts', 'Forms.TApplication.RestoreTopMosts')}
        getters = {self.by_name[FLAVOUR_NAME + 'GetDLTTag']: TAG,
                   self.by_name[FLAVOUR_NAME + 'GetGroupLanguage']: LANGUAGE,
                   self.by_name['CIS_TGroupLanguage.TGroupLanguage.GetLanguageType']: LANGUAGE_TYPE}
        finalisers = {self.methods[name + '_finalise']['start']: name for name in ('group', 'level')}
        allowed = [(self.methods[key]['start'], self.methods[key]['end'])
                   for key in ('text_ok', 'unicode_predicate')]

        def hook(_u, address, _size, _data):
            if address == RETURN:
                u.emu_stop()
            elif address in getters:
                ret(getters[address])
            elif address in noops:
                ret()
            elif address == self.by_name['Controls.TControl.GetText']:
                put(u.reg_read(EDX), write_string(self.input_text))
                ret()
            elif address == self.by_name['Dialogs.MessageDlgPosHelp']:
                self.prompts += 1
                ret(1 if self.confirm else 2, cleanup=16)
            elif address == self.by_name['CIS_TLanguageTag.TLanguageTag.SetTagType']:
                assert u.reg_read(EAX) == TAG
                self.tag_type = u.reg_read(EDX)
                ret()
            elif address == self.by_name['CIS_TLanguageTag.TLanguageTag.SetTagValue']:
                assert u.reg_read(EAX) == TAG
                self.tag_value = read_string(u.reg_read(EDX))
                ret()
            elif address == self.by_name['System.@UStrCopy']:
                raw = read_string(u.reg_read(EAX)).encode('utf-16-le', 'surrogatepass')
                start, count = u.reg_read(EDX), u.reg_read(ECX)
                self.copies.append({'start': start, 'utf16_count': count})
                value = raw[(start - 1) * 2:(start - 1 + count) * 2].decode('utf-16-le', 'surrogatepass')
                put(read(u.reg_read(ESP) + 4), write_string(value))
                ret(cleanup=4)
            elif address in finalisers:
                assert u.reg_read(EAX) == TARGET and u.reg_read(EDX) == LANGUAGE_TYPE
                assert u.reg_read(ECX) == 0
                self.calls.append({'operation': 'FinaliseLanguage', 'target': finalisers[address],
                                   'language': 'selected flavour language', 'supplied_model': None})
                ret()
            elif not any(start <= address < stop for start, stop in allowed):
                raise AssertionError(f'Unexpected original execution at {address:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        return u

    def run(self, text, *, target='group', confirm=False, deferred=False):
        if not hasattr(self, 'machine'):
            self.machine = self._machine()
        u = self.machine
        self.input_text, self.confirm, self.string_next = text, confirm, 0x30008000
        self.tag_type, self.tag_value, self.prompts, self.calls, self.copies = 3, 'before', 0, [], []
        for offset, value in ((0x45C, TARGET if target == 'group' else 0),
                               (0x460, TARGET if target == 'level' else 0), (0x2B8, 0)):
            u.mem_write(FORM + offset, struct.pack('<I', value))
        u.mem_write(FORM + 0x478, bytes([int(deferred)]))
        u.mem_write(FLAVOUR + 0xC4, b'\x01')
        u.mem_write(STACK, struct.pack('<I', RETURN))
        u.reg_write(EAX, FORM)
        u.reg_write(ESP, STACK)
        u.emu_start(self.methods['text_ok']['start'], RETURN, count=3000)
        assert u.reg_read(EIP) == RETURN
        return {'input': text, 'target': target, 'confirm_non_latin1': confirm, 'deferred': deferred,
                'result': {'accepted': u.mem_read(FORM + 0x2B8, 4) == b'\x01\x00\x00\x00',
                           'tag_type': self.tag_type, 'tag_value': self.tag_value,
                           'unicode_prompts': self.prompts, 'copies': self.copies,
                           'broadcast_marked': bool(u.mem_read(FLAVOUR + 0xC4, 1)[0]), 'calls': self.calls}}

    def observations(self):
        rows = []
        for text in ('', 'Kitchen', '012345678901234567890123', 'Café', '漢字',
                     '12345678901234567890漢', '1234567890123456789😀'):
            for confirm in (False, True):
                row = self.run(text, confirm=confirm, target='group' if not confirm else 'level')
                expected_accept = all(ord(char) <= 255 for char in text) or confirm
                assert row['result']['accepted'] == expected_accept
                assert bool(row['result']['unicode_prompts']) == any(ord(char) > 255 for char in text)
                if expected_accept:
                    expected = text.encode('utf-16-le')[:40].decode('utf-16-le', 'surrogatepass') if text else '<Default>'
                    assert row['result']['tag_value'] == expected and row['result']['tag_type'] == 0
                    assert len(row['result']['calls']) == 1 and not row['result']['broadcast_marked']
                else:
                    assert row['result']['tag_value'] == 'before' and row['result']['tag_type'] == 3
                    assert not row['result']['calls'] and row['result']['broadcast_marked']
                rows.append(row)
        deferred = self.run('Deferred', deferred=True)
        assert deferred['result']['accepted'] and deferred['result']['broadcast_marked']
        assert not deferred['result']['calls']
        rows.append(deferred)
        return rows


def inspect(executable: Path, symbols: Path):
    from classic_dlt_language_collection_original import collection_facts
    from classic_dlt_language_network_original import network_facts
    probe = TextDialogProbe(executable, symbols)
    return {'format': FORMAT, **probe.static_facts(), 'observations': probe.observations(),
            'collection': collection_facts(probe), 'network': network_facts(probe),
            'boundary': 'Original TEXT button and Unicode predicate with synthetic VCL/string/tag/finalizer hooks; collection/network source extraction only. No full native or managed GUI, server persistence or physical labels.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.executable, args.map)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'format': FORMAT, 'observations': len(report['observations']), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
