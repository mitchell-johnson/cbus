"""Original classic DLT delivery decisions, without physical programming.

The pinned original AfterSaveProgrammingInformation fragments execute in
Unicorn. Model lookups, strings, callbacks and collection counts use synthetic
fixtures. No transport, vendor GUI or real project executes. Output contains
source hashes and symbolic observations only, never vendor instruction bytes.
The sequence is evidence for future work, not an exposed physical-save API.
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
                               UC_X86_REG_EFLAGS as EFLAGS, UC_X86_REG_EIP as EIP,
                               UC_X86_REG_ESP as ESP)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classic_dlt_controls_original import (AGENT_NAME, BASE_NAME, EXE_SHA256, MAP_SHA256,
                                            ClassicControlsProbe)  # noqa: E402
from classic_dlt_delivery_commands import delivery_command_facts  # noqa: E402

FORMAT = 'cbus-classic-dlt-delivery-original-v1'
FRAME, STACK = 0x20008000, 0x20006000
AGENT, UNIT, FLAVOUR, TAG, COLLECTION = (0x30001000, 0x30002000, 0x30003000,
                                       0x30004000, 0x30005000)
VMT, SAVE_ACTION, GET_COUNT = 0x30006000, 0x30007000, 0x30007100
GATE = (0x121C371, 0x121C3B9)
KEY = (0x121C7AA, 0x121C9F2)
SKIP = 0x121CE5F
METHODS = {
    'after_save': AGENT_NAME + 'AfterSaveProgrammingInformation',
    'agent_save': AGENT_NAME + 'AgentSave',
    'find_flavour': AGENT_NAME + 'FindFlavour',
    'save_flavours_only': AGENT_NAME + 'SaveLabelFlavoursOnly',
    'key_function_indicators': AGENT_NAME + 'SetKeyFunctionIndicators',
    'base_agent_save': BASE_NAME + 'AgentSave',
    'save_dialog': 'CIS_TddCBusUnit.TddCBusUnit.SaveProgramming',
    'keyl5_network_save': 'CIS_TddKEYL5.TddKEYL5.SaveProgramming_Network',
}


class DeliveryProbe(ClassicControlsProbe):
    def __init__(self, executable: Path, symbols: Path):
        super().__init__(executable, symbols)
        self.delivery_methods = {key: self.method(name) for key, name in METHODS.items()}

    def static_facts(self):
        after = self.delivery_methods['after_save']
        actual = [(m, op) for _, m, op in after['instructions']]
        for pair in [('cmp', 'byte ptr [eax + 0xc0], 0'),
                     ('cmp', 'byte ptr [eax + 0x16e], 0'),
                     ('cmp', 'byte ptr [eax + 0xda], 0'),
                     ('mov', 'byte ptr [eax + 0xc4], 0'),
                     ('mov', 'byte ptr [eax + 0xc4], 1')]:
            assert pair in actual
        assert {'DLTClearLabel', 'KeyNumber=', 'SaveDLTLabel', '<Default>'} <= set(after['literals'])
        base = self.delivery_methods['base_agent_save']
        assert {'TransferNetworkToDatabase', 'TransferDatabaseToNetwork', 'Database', 'ChangesOnly'} <= set(base['literals'])
        for offset, value in ((0xCB7316, 1), (0xCB7351, 1), (0xCB7389, 0), (0xCB73BC, 0)):
            assert next((m, op) for va, m, op in base['instructions'] if va == offset) == (
                'mov', f'byte ptr [eax + 0xda], {value}')
        return {
            'source': {'executable_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256},
            'methods': {key: {'symbol': METHODS[key], **self.span(m['start'], m['end'])}
                        for key, m in self.delivery_methods.items()},
            'fragments': {'save_gate': self.span(*GATE), 'key_decision': self.span(*KEY)},
            'rules': {
                'ordinary_physical_order': [
                    'Initial PP save sets EnableDynamicLabels=1',
                    'AfterSave: SetKeyFunctionIndicators if unit+0xdd',
                    'AfterSave: clear collected label errors and initialize network language if missing',
                    'AfterSave: labels in key collection order when SaveDLTLabels or transfer flag',
                    'AgentSave: reblock through SaveEnableDynamicLabelsOnly when BlockDynamicUpdates',
                ],
                'save_labels_flag': 'unit+0x16e; initialized from inverse BlockDynamicUpdates and writable by Save DLT Labels dialog checkbox',
                'transfer_flag': 'agent+0xda; true for TransferNetworkToDatabase/TransferDatabaseToNetwork, otherwise false',
                'key_resolution': [
                    'Scene-modify key: ControlAppGroup; absent/unused group skips key',
                    'Scene key: SceneTriggerLevel; absent level skips key',
                    'Other key: PrimaryDLTGroup; absent/unused group clears key label',
                    'Resolve network default language and selected LabelFlavour; first matching flavour wins',
                ],
                'dynamic_loading': 'For ordinary primary-group labels, DYNAMIC/FONT without cached dynamic data attempts LoadDLTBitmap before decision',
                'key_decision': 'Missing flavour, blank tag, <Default>, or DYNAMIC/FONT with no dynamic data => DLTClearLabel KeyNumber=zero_based_index+1; otherwise SaveDLTLabel',
                'errors': 'Retained-flavour dispatch exceptions are recorded and processing continues; fallback missing-flavour clear is outside that local handler; KEYL5 form limits displayed error list to ten',
                'save_flavours_only': 'Reuse existing session and stage two arrays without SAVE; otherwise Lock, Start, Load, Set LSB, Set MSB, Save, End, Unlock',
                'scope_limit': 'No complete physical executor: KFI state, image loading, original form lifecycle, failure cleanup and physical persistence remain separate evidence requirements',
            },
        }

    def _machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(self.base, (len(self.memory) + 4095) & ~4095)
        u.mem_write(self.base, self.memory)
        for address, size in ((0, 4096), (0x20000000, 0x10000), (0x30000000, 0x20000)):
            u.mem_map(address, size)
        put = lambda address, value: u.mem_write(address, struct.pack('<I', value))
        read = lambda address: struct.unpack('<I', u.mem_read(address, 4))[0]
        for obj in (UNIT, FLAVOUR, COLLECTION):
            put(obj, VMT)
        put(UNIT + 0x1E8, COLLECTION)
        put(VMT + 0x80, SAVE_ACTION)
        put(VMT + 0x58, GET_COUNT)

        def string(pointer):
            if not pointer:
                return ''
            return bytes(u.mem_read(pointer, 2 * read(pointer - 4))).decode('utf-16le')

        def allocate(value):
            if not value:
                return 0
            raw = value.encode('utf-16le')
            address = self.heap
            self.heap += (len(raw) + 19) & ~3
            u.mem_write(address, struct.pack('<III', 1200, 0xFFFFFFFF, len(raw) // 2) + raw + b'\0\0')
            return address + 12

        self.allocate = allocate

        def ret(value=None):
            stack = u.reg_read(ESP)
            if value is not None:
                u.reg_write(EAX, value)
            u.reg_write(EIP, read(stack))
            u.reg_write(ESP, stack + 4)

        def hook(_machine, address, _size, _data):
            if address in (GATE[1], SKIP):
                u.emu_stop()
            elif address == self.by_name[AGENT_NAME + 'GetDLTUnit']:
                ret(UNIT)
            elif address == self.by_name['CIS_TGroupLanguage.TGroupLanguageFlavour.GetDLTTag']:
                ret(TAG)
            elif address == self.by_name['CIS_TLanguageTag.TLanguageTag.GetTagValue']:
                put(u.reg_read(EDX), self.tag_value)
                ret()
            elif address == self.by_name['CIS_TLanguageTag.TLanguageTag.GetTagType']:
                ret(self.tag_type)
            elif address == self.by_name['CIS_TGroupLanguage.TGroupLanguageFlavour.GetDLTDynamicData']:
                put(u.reg_read(EDX), self.dynamic_data)
                ret()
            elif address == self.by_name['System.@UStrEqual']:
                equal = string(u.reg_read(EAX)) == string(u.reg_read(EDX))
                u.reg_write(EFLAGS, (u.reg_read(EFLAGS) & ~0x40) | (0x40 if equal else 0))
                ret()
            elif 'SysUtils.IntToStr' in self.symbols.get(address, set()):
                put(u.reg_read(EDX), allocate(str(u.reg_read(EAX))))
                ret()
            elif address == self.by_name['System.@UStrCat3']:
                put(u.reg_read(EAX), allocate(string(u.reg_read(EDX)) + string(u.reg_read(ECX))))
                ret()
            elif address == SAVE_ACTION:
                self.actions.append({'target': 'unit' if u.reg_read(EAX) == UNIT else 'flavour',
                                     'verbs': [string(read(u.reg_read(EDX) + 4 * i))
                                               for i in range(u.reg_read(ECX) + 1)]})
                ret()
            elif address == GET_COUNT:
                ret(self.key_count)
            elif not (GATE[0] <= address < GATE[1] or KEY[0] <= address < KEY[1]):
                raise AssertionError(f'Unexpected original execution at {address:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        return u

    def run(self, kind: str, *, save_labels=True, transfer=False, flavour=True,
            tag_value='Kitchen', tag_type=1, dynamic_data=False, key_index=0, key_count=8):
        if not hasattr(self, 'machine'):
            self.machine = self._machine()
        u = self.machine
        self.heap, self.actions, self.tag_type, self.key_count = 0x30008000, [], tag_type, key_count
        self.tag_value = self.allocate(tag_value)
        self.dynamic_data = self.allocate('bitmap' if dynamic_data else '')
        u.mem_write(FRAME - 0x100, bytes(0x100))
        u.mem_write(FRAME - 4, struct.pack('<I', AGENT))
        u.mem_write(FRAME - 0xC, struct.pack('<I', FLAVOUR if flavour else 0))
        u.mem_write(FRAME - 0x20, struct.pack('<I', key_index))
        u.mem_write(UNIT + 0x16E, bytes([int(save_labels)]))
        u.mem_write(AGENT + 0xDA, bytes([int(transfer)]))
        u.mem_write(FLAVOUR + 0xC4, b'\0')
        u.reg_write(EBP, FRAME)
        u.reg_write(ESP, STACK)
        start, stop = GATE if kind == 'gate' else KEY
        u.emu_start(start, stop, count=300)
        terminal = u.reg_read(EIP)
        assert terminal in ((stop, SKIP) if kind == 'gate' else (stop,)), hex(terminal)
        return {'eligible': terminal != SKIP, 'actions': self.actions,
                'flavour_marked': bool(u.mem_read(FLAVOUR + 0xC4, 1)[0])}

    def observations(self):
        gates = []
        for save_labels in (False, True):
            for transfer in (False, True):
                for key_count in (0, 8):
                    result = self.run('gate', save_labels=save_labels, transfer=transfer, key_count=key_count)
                    assert result['eligible'] == (bool(key_count) and (save_labels or transfer))
                    gates.append({'save_labels': save_labels, 'transfer': transfer,
                                  'key_count': key_count, 'result': result})
        decisions = []
        for key_index in (0, 7):
            for tag_type in (0, 1, 2, 3):
                for tag_value in ('', '<Default>', 'Kitchen'):
                    for dynamic_data in (False, True):
                        result = self.run('key', key_index=key_index, tag_type=tag_type,
                                          tag_value=tag_value, dynamic_data=dynamic_data)
                        clear = tag_value in ('', '<Default>') or (tag_type in (2, 3) and not dynamic_data)
                        expected = {'target': 'unit', 'verbs': ['DLTClearLabel', f'KeyNumber={key_index + 1}']} if clear else {
                            'target': 'flavour', 'verbs': ['SaveDLTLabel']}
                        assert result['actions'] == [expected]
                        assert result['flavour_marked'] == clear
                        decisions.append({'key_index': key_index, 'tag_type': tag_type, 'tag_value': tag_value,
                                          'dynamic_data': dynamic_data, 'result': result})
            result = self.run('key', key_index=key_index, flavour=False)
            assert result['actions'] == [{'target': 'unit', 'verbs': ['DLTClearLabel', f'KeyNumber={key_index + 1}']}]
            decisions.append({'key_index': key_index, 'flavour_present': False, 'result': result})
        return {'gates': gates, 'decisions': decisions}


def inspect(executable: Path, symbols: Path) -> dict:
    probe = DeliveryProbe(executable, symbols)
    return {'format': FORMAT, **probe.static_facts(), 'observations': probe.observations(),
            'command_builders': delivery_command_facts(probe),
            'boundary': 'Original x86 branch fragments with synthetic object/string fixtures. No physical executor, transport, GUI or persistence acceptance.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--map', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = inspect(args.executable, args.map)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'format': FORMAT, 'gate_cases': len(result['observations']['gates']),
                      'decision_cases': len(result['observations']['decisions'])}))


if __name__ == '__main__':
    main()
