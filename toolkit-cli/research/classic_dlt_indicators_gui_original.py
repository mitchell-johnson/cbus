"""Replay pinned classic DLT indicator component events in original x86 code.

The original duration-population fragment and complete event/helper methods run
in Unicorn with synthetic GUI controls. Primitive control storage, immediate
Flash checkbox binding, string conversion and model duration access are hooks.
No complete GUI, native C-Gate, project, network or physical device is executed.
Private original bytes are never included in the retained synthetic receipt.
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
from classic_dlt_controls_original import ClassicControlsProbe, sha  # noqa: E402
from classic_dlt_indicator_gui_bindings import gui_binding_facts  # noqa: E402

FORMAT = 'cbus-classic-dlt-indicators-gui-original-v1'
PREFIX = 'CIS_TcdDLTInputIndicators8.TcdDLTInputIndicators8.'
METHODS = {
    'setup': ('SetupNonFlashComponents', 0xFFB214),
    'populate': ('PopulateNonFlashComponents_Other', 0xFFB3E8),
    'page_change': ('HandlePageFallbackCheckboxChange', 0xFFB5CC),
    'pressed_change': ('HandleKeyPressBrightnessCheckboxChange', 0xFFB640),
    'duration_change': ('HandleKeyPressBrightnessComboChange', 0xFFB6B0),
    'store_duration': ('StoreKeyPressBrightness', 0xFFB6C8),
    'fallback': ('UpdateFallbackEnabled', 0xFFB888),
    'nightlight_change': ('HandleNightlightEnableCheckboxChange', 0xFFBA5C),
    'nightlight': ('UpdateNightlightEnabled', 0xFFBA74),
}
POPULATE = (0xFFB4CF, 0xFFB589)
CHECKBOXES = {
    'page_fallback': (0x2D4, 'page_change'),
    'pressed_enabled': (0x2CC, 'pressed_change'),
    'nightlight_keys': (0x2E0, 'nightlight_change'),
    'nightlight_toggle': (0x2E8, 'nightlight_change'),
    'first_key_throwaway': (0x2E4, None),
}
OTHER_CONTROLS = {'duration_seconds': 0x308, 'pressed_level': 0x300,
                  'duration_label': 0x2C4, 'duration_units': 0x2C8,
                  'pressed_label': 0x2D0, 'nightlight_label': 0x2F0,
                  'nightlight_note': 0x30C}
FRAME, STACK = 0x20008000, 0x20006000
CONTROLLER, FORM, UNIT = 0x30001000, 0x30002000, 0x30003000
VMT, ITEMS, ITEMS_VMT, CONTROL_BASE = 0x30004000, 0x30005000, 0x30006000, 0x30010000
GET_VALUE, SET_VALUE, GET_ENABLED, SET_ENABLED = (0x30007000, 0x30007100,
                                                0x30007200, 0x30007300)
GET_COUNT, GET_STRING, RETURN = 0x30007400, 0x30007500, 0x3000F000


class ClassicIndicatorsGuiProbe(ClassicControlsProbe):
    def __init__(self, executable: Path, symbols: Path):
        super().__init__(executable, symbols)
        self.gui_methods = {}
        for key, (name, address) in METHODS.items():
            assert self.by_name[PREFIX + name] == address
            self.gui_methods[key] = self.method(PREFIX + name)
        self.bindings_facts = gui_binding_facts(self)
        self.machine = self._gui_machine()

    def facts(self):
        setup = self.gui_methods['setup']['instructions']
        pairs = [row[1:] for row in setup]
        assert ('mov', 'byte ptr [ebp - 5], 2') in pairs
        assert ('cmp', 'byte ptr [ebp - 5], 0x10') in pairs
        assert ('inc', 'byte ptr [ebp - 5]') in pairs
        assert 'SysUtils.IntToStr' in self.symbols[0x6198AC]
        assert ('call', '0x6198ac') in pairs
        return {
            'source': self.bindings_facts['source_sha256'],
            'gui_bindings': self.bindings_facts,
            'methods': {key: {'symbol': PREFIX + METHODS[key][0],
                              **self.span(method['start'], method['end'])}
                        for key, method in self.gui_methods.items()},
            'fragments': {'populate_duration': self.span(*POPULATE)},
            'duration_items': list(range(2, 16)),
            'duration_index_to_seconds': 'index + 2 (indices 0..13)',
            'initialization': 'Populate duration selection, pressed checkbox handler, UpdateFallbackEnabled',
            'original_load_prelude': 'Page fallback and pressed-enabled model values each equal raw flag AND raw duration > 0',
            'save_boundary': 'Observations end after original component event dispatch; agent save is a separate source probe',
        }

    def _gui_machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(self.base, (len(self.memory) + 4095) & ~4095)
        u.mem_write(self.base, self.memory)
        for address, size in ((0, 4096), (0x20000000, 0x10000), (0x30000000, 0x30000)):
            u.mem_map(address, size)

        def put(address, value):
            u.mem_write(address, struct.pack('<I', value & 0xFFFFFFFF))

        def read(address):
            return struct.unpack('<I', u.mem_read(address, 4))[0]

        def ret(value=None):
            stack = u.reg_read(ESP)
            if value is not None:
                u.reg_write(EAX, value & 0xFFFFFFFF)
            u.reg_write(EIP, read(stack))
            u.reg_write(ESP, stack + 4)

        self.put, self.read = put, read
        self.controls, self.names = {}, {}
        for index, (name, offset) in enumerate([
                *((name, entry[0]) for name, entry in CHECKBOXES.items()),
                *OTHER_CONTROLS.items()]):
            address = CONTROL_BASE + index * 0x400
            self.controls[name] = address
            self.names[address] = name
            put(FORM + offset, address)
            put(address, VMT)
            u.mem_write(address + 0x59, b'\x01')  # Available classic controls are visible.
        put(CONTROLLER + 8, FORM)
        put(CONTROLLER + 0x10, UNIT)
        put(UNIT, VMT)
        put(self.controls['duration_seconds'] + 0x2AC, ITEMS)
        put(ITEMS, ITEMS_VMT)
        for offset, target in ((0xEC, GET_VALUE), (0xF0, SET_VALUE),
                               (0x5C, GET_ENABLED), (0x74, SET_ENABLED)):
            put(VMT + offset, target)
        put(VMT + 0x1EC, self.by_name['CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.NightlightPropertyEnabled'])
        put(ITEMS_VMT + 0x14, GET_COUNT)
        put(ITEMS_VMT + 0xC, GET_STRING)
        allowed = [POPULATE] + [(method['start'], method['end'])
                                for key, method in self.gui_methods.items()
                                if key not in ('setup', 'populate')]
        gate = self.method('CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.NightlightPropertyEnabled')
        allowed.append((gate['start'], gate['end']))
        getter = self.by_name['CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.GetKeyPressBrightnessDuration']
        setter = self.by_name['CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.SetKeyPressBrightnessDuration']

        def enabled(name, value):
            self.enabled[name] = bool(value)
            u.mem_write(self.controls[name] + 0x5A, bytes([bool(value)]))

        self.set_enabled = enabled

        def hook(_machine, address, _size, _data):
            if address == RETURN:
                u.emu_stop()
            elif address == GET_VALUE:
                name = self.names[u.reg_read(EAX)]
                ret(self.index if name == 'duration_seconds' else int(self.state[name]))
            elif address == SET_VALUE:
                name, value = self.names[u.reg_read(EAX)], u.reg_read(EDX)
                if name == 'duration_seconds':
                    assert 0 <= value <= 13
                    self.index = value  # Programmatic ItemIndex assignment has no OnChange.
                    ret()
                else:
                    value = bool(value & 255)
                    if self.state[name] == value:
                        ret()
                    else:
                        self.state[name] = value
                        self.writes.append({'control': name, 'value': value})
                        handler = CHECKBOXES[name][1]
                        if handler:
                            # Immediate Flash binding writes the model before OnClick.
                            u.reg_write(EDX, self.controls[name])
                            u.reg_write(EAX, CONTROLLER)
                            u.reg_write(EIP, METHODS[handler][1])
                        else:
                            ret()
            elif address == GET_ENABLED:
                ret(int(self.enabled[self.names[u.reg_read(EAX)]]))
            elif address in (SET_ENABLED, self.by_name['CIS_GUI.ComponentEnabled']):
                enabled(self.names[u.reg_read(EAX)], u.reg_read(EDX) & 255)
                ret()
            elif address == GET_COUNT:
                assert u.reg_read(EAX) == ITEMS
                ret(14)
            elif address == GET_STRING:
                assert u.reg_read(EAX) == ITEMS and u.reg_read(EDX) < 14
                # Synthetic Unicode string handle identifies its decimal value.
                put(u.reg_read(ECX), 0x30020000 + u.reg_read(EDX) + 2)
                ret()
            elif address in (self.by_name['SysUtils.StrToInt'], self.by_name['SysUtils.StrToIntDef']):
                value = u.reg_read(EAX) - 0x30020000
                assert 2 <= value <= 15
                ret(value)
            elif address == self.by_name['System.@UStrClr']:
                put(u.reg_read(EAX), 0)
                ret()
            elif address == getter:
                assert u.reg_read(EAX) == UNIT
                ret(self.state['duration_seconds'])
            elif address == setter:
                assert u.reg_read(EAX) == UNIT
                value = u.reg_read(EDX)
                assert 0 <= value <= 15
                self.state['duration_seconds'] = value
                self.writes.append({'control': 'duration_seconds', 'value': value})
                ret()
            elif any(start <= address < stop for start, stop in allowed):
                self.count += 1
            else:
                raise AssertionError(f'Unexpected original indicator GUI execution at {address:#x}')

        u.hook_add(UC_HOOK_CODE, hook)
        return u

    def execute(self, start, stop=RETURN, value=CONTROLLER, argument=0):
        u = self.machine
        for register, initial in ((EBP, FRAME), (ESP, STACK), (EAX, value), (EDX, argument), (ECX, 0)):
            u.reg_write(register, initial)
        self.put(STACK, RETURN)
        self.put(FRAME - 4, CONTROLLER)
        u.emu_start(start, stop, count=10000)
        assert u.reg_read(EIP) == stop, 'Original event did not complete'

    def snapshot(self):
        return {'controls': dict(self.state), 'duration_item_index': self.index,
                'duration_item_seconds': self.index + 2,
                'enabled': {name: self.enabled[name] for name in self.state}}

    def replay(self, name, initial, operations):
        self.state = dict(initial)
        # Agent load derives these flags before their immediate GUI binding.
        for flag in ('page_fallback', 'pressed_enabled'):
            self.state[flag] = self.state[flag] and self.state['duration_seconds'] > 0
        self.enabled, self.index, self.count, self.writes = {}, 0, 0, []
        for control in self.controls:
            self.set_enabled(control, True)
        loaded = self.snapshot()
        self.execute(*POPULATE)
        initialized = self.snapshot()
        initialization_writes = list(self.writes)
        transitions = []
        for operation in operations:
            control, value = operation['control'], operation['value']
            before, count_before = self.snapshot(), self.count
            self.writes = []
            if not self.enabled[control]:
                transitions.append({'operation': operation, 'before': before, 'after': before,
                                    'refused': 'original GUI control disabled',
                                    'original_instruction_count': 0, 'writes': []})
                break
            if control in CHECKBOXES:
                assert type(value) is bool
                self.execute(SET_VALUE, value=self.controls[control], argument=int(value))
            elif control == 'duration_seconds':
                assert type(value) is int and 2 <= value <= 15
                self.index = value - 2
                self.execute(METHODS['duration_change'][1])
            elif control == 'pressed_level':
                assert type(value) is int and 0 <= value <= 15
                self.state[control] = value  # Immediate numeric Flash model binding.
                self.writes.append({'control': control, 'value': value})
            else:
                raise AssertionError(control)
            transitions.append({'operation': operation, 'before': before, 'after': self.snapshot(),
                                'refused': None, 'original_instruction_count': self.count - count_before,
                                'writes': list(self.writes)})
        return {'name': name, 'input': initial, 'operations': operations, 'loaded': loaded,
                'initialized': initialized, 'initialization_writes': initialization_writes,
                'transitions': transitions, 'output': self.snapshot(),
                'original_instruction_count': self.count}

    def observations(self):
        baseline = {'page_fallback': True, 'pressed_enabled': True, 'duration_seconds': 15,
                    'pressed_level': 15, 'nightlight_keys': True, 'nightlight_toggle': True,
                    'first_key_throwaway': True}
        rows = []
        for duration in (0, 1, 2, 15):
            for page in (False, True):
                for pressed in (False, True):
                    rows.append(self.replay(f'initialize-{duration}-{int(page)}-{int(pressed)}',
                        {**baseline, 'duration_seconds': duration, 'page_fallback': page,
                         'pressed_enabled': pressed}, []))
        def actions(*pairs):
            return [{'control': key, 'value': value} for key, value in pairs]
        cases = [
            ('disable-pressed-then-page', {}, actions(('pressed_enabled', False), ('page_fallback', False))),
            ('disable-page-then-pressed', {}, actions(('page_fallback', False), ('pressed_enabled', False))),
            ('page-enable-from-zero', {'duration_seconds': 0}, actions(('page_fallback', True))),
            ('pressed-enable-from-zero', {'duration_seconds': 0}, actions(('pressed_enabled', True))),
            ('page-enable-after-pressed', {'duration_seconds': 0}, actions(('pressed_enabled', True), ('page_fallback', True))),
            ('duration-min-max', {}, actions(('duration_seconds', 2), ('duration_seconds', 15))),
            ('nightlight-disable-keys-then-toggle', {}, actions(('nightlight_keys', False), ('nightlight_toggle', False))),
            ('nightlight-disable-toggle-then-keys', {}, actions(('nightlight_toggle', False), ('nightlight_keys', False))),
            ('nightlight-enable-then-first', {'nightlight_keys': False, 'nightlight_toggle': False},
                actions(('nightlight_keys', True), ('first_key_throwaway', True))),
            ('pressed-level-min-max', {}, actions(('pressed_level', 0), ('pressed_level', 15))),
            ('unchanged-checkbox-no-callback', {}, actions(('page_fallback', True), ('pressed_enabled', True))),
        ]
        for control in ('duration_seconds', 'pressed_level', 'nightlight_keys', 'nightlight_toggle', 'first_key_throwaway'):
            cases.append(('disabled-' + control, {'duration_seconds': 0}, actions((control, 2 if control in (
                'duration_seconds', 'pressed_level') else True))))
        for name, overrides, operations in cases:
            rows.append(self.replay(name, {**baseline, **overrides}, operations))
        return rows


def inspect(executable: Path, symbols: Path):
    probe = ClassicIndicatorsGuiProbe(executable, symbols)
    return {'format': FORMAT, **probe.facts(), 'observations': probe.observations(),
            'script_sha256': sha(Path(__file__).read_bytes()),
            'bindings_script_sha256': sha(Path(__file__).with_name('classic_dlt_indicator_gui_bindings.py').read_bytes()),
            'passed': True, 'original_full_form_executed': False, 'physical_hardware_verified': False,
            'boundary': 'Original x86 component population fragment and complete event/helper methods; synthetic GUI/storage/string primitives and source-checked immediate Flash binding; no full dialog, database save, display rendering, or hardware acceptance.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--map', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = inspect(args.executable, args.map)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'format': FORMAT, 'observations': len(report['observations']),
                      'original_instruction_count': sum(row['original_instruction_count'] for row in report['observations']),
                      'script_sha256': report['script_sha256'], 'output': str(args.output)}))


if __name__ == '__main__':
    main()
