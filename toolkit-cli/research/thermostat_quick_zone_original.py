"""Run one original quick-zone include in an owned, bounded core-model fixture.

This is not a constructed Toolkit form, PP load/save/reload or project fixture.
Original instructions execute against synthetic, source-shaped objects. GUI
publisher subscribers, workspace, parent enable callback, and unrelated model
attributes are absent. Owned no-contention critical sections and VT_EMPTY /
VT_BOOL stack-variant cleanup use explicit ABI adapters; no meaningful model
callback is replaced. Original OleAut32 implementation is not executed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import capstone
import unicorn
from unicorn.unicorn_py3 import unicorn as unicorn_core
from unicorn.x86_const import (UC_X86_REG_EAX as EAX, UC_X86_REG_EDX as EDX,
                              UC_X86_REG_ECX as ECX, UC_X86_REG_EBX as EBX,
                              UC_X86_REG_ESI as ESI, UC_X86_REG_EDI as EDI,
                              UC_X86_REG_EBP as EBP, UC_X86_REG_ESP as ESP,
                              UC_X86_REG_EIP as EIP)
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image
from thermostat_post_load_static import _Walker

GENERIC = {
    'CIS_TBaseObject.TBASEObject.': ('BeginUpdate', 'EndUpdate', 'Changed', 'GetUpdating'),
    'CIS_TManagedFlashObject.TManagedFlashObject.': ('Changed', 'ResolveChange', 'DoChangeNotification'),
    'CIS_TManagedFlashObject.TFlashElementStatePublisher.': ('Changed',),
    'CIS_TCustomFlashObject.TCISAttribute.': ('BeginUpdate', 'EndUpdate', 'Changed', 'ResolveChange'),
    'CIS_TCustomFlashObject.TFlashAttribute.': ('Changed',),
    'CIS_TCustomFlashObject.TAttributeManager.': ('BeginUpdate', 'EndUpdate'),
    'CIS_TCustomFlashObject.TFlashEntityManager.': ('Changed', 'ResolveChange'),
    'CIS_TCustomFlashObject.TCustomFlashObject.': ('Changed', 'DoChangeNotification'),
    'CIS_TCustomFlashObject.TFlashObjectReferenceList.': ('Changed', 'Count', 'Getitems'),
    'CIS_TCustomFlashObject.TThreadSafeList.': ('Count', 'Get', 'LockList', 'UnlockList'),
    'CIS_TCustomFlashObject.TFlashObjectReference.': ('ObjectChanged', 'GetFlashObject', 'ResolveReference'),
    'CIS_TCustomObjectAttribute.TCustomObjectAttribute.': ('GetFlashObject',),
    'CIS_TObjectAttribute.TObjectAttribute.': ('GetFlashObject', 'ObjectChanged'),
    'CIS_TBooleanAttribute.TBooleanAttribute.': ('AsBoolean', 'SetValue', 'SetAsBoolean'),
    'CIS_TEnumeratedTypeAttribute.TEnumeratedTypeAttribute.': ('AsInteger',),
    'CIS_TThermostatCommon.TZones.': ('IncludeZone',),
    'CIS_TThermostat.TThermostat.': ('GetUsedZones', 'GetUIService', 'GetPlantControlService',
        'GetTemperatureMeasurementService', 'GetZoneManagerService', 'GetCBusParameters', 'HandleZoneChange'),
    'CIS_TThermostat.TProgrammableThermostat.': ('GetScheduleService',),
    'CIS_TThermostat.TUIService.': ('GetUIAllocatedZones', 'HandleZoneAfterChange'),
    'CIS_TThermostat.TPlantControlService.': ('GetInternalPlantZones', 'HandleZoneAfterChange'),
    'CIS_TThermostat.TTemperatureMeasurementService.': ('GetMeasuredZones', 'HandleZoneAfterChange'),
    'CIS_TThermostat.TScheduleService.': ('GetControlledZones', 'HandleZoneAfterChange'),
    'CIS_TThermostat.TCBusParameters.': ('GetInstalledZones',),
    'CIS_TThermostat.TZoneManagerService.': ('GetControlledZones', 'GetZoneManagerMasterSlave',
        'GetHeatingPlantType', 'GetCoolingPlantType', 'GetVentingPlantType'),
    'CIS_TThermostat.TPlantTypeAttribute.': ('AsPlantTypeEnum',),
    'CIS_TcdThermostatTemplates.TcdThermostatTemplates.': ('HandleUnitZoneChange', 'UpdateQuickOptions'),
    'CIS_TcdThermostatTemplates.': ('IncludeZone',),
    'Variants.': ('@VarFromBool', '@VarToBool', '@VarToBoolean', '@VarClr', '@VarClear', 'VarClearDeep', 'VarResultCheck'),
    'System.': ('@IsClass', 'TObject.InheritsFrom', '@FinalizeArray', '@VarClr', '@IntfClear'),
    'Classes.TList.': ('Get',),
}
METHODS = tuple(p + n for p, names in GENERIC.items() for n in names)
OWNED = (0x10000000, 0x10080000)
STACK = (0x20000000, 0x20020000)
RETURN = 0x30000000
BUDGET = 200000
LIBRARIES = {
    '7a379c419496cdc98d098fa356a1e9b4fdb90f4c325b4d98e60042ab3d8216b0',
    '7207c8e3d7a63118fb0bca73e01816797fd51b1d8a39a4cbc7abfd562ee59c85',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def deny_external(event, _args):
    if event.startswith(('socket.', 'subprocess.', 'winreg.')) or event in ('os.system', 'os.exec', 'os.posix_spawn'):
        raise RuntimeError('External operation denied: ' + event)


class Probe:
    def __init__(self, executable, map_path):
        self.library_paths = [Path(unicorn_core.uclib._name).resolve(), Path(capstone._cs._name).resolve()]
        require({sha(p.read_bytes()) for p in self.library_paths} == LIBRARIES, 'Pinned actual instruction engine libraries')
        self.exe_raw, self.map_raw = executable.read_bytes(), map_path.read_bytes()
        require(sha(self.exe_raw) == EXE_SHA256 and sha(self.map_raw) == MAP_SHA256, 'Original source pin')
        self.image = _Image(self.exe_raw, self.map_raw)
        self.walk = _Walker(self.image)
        for name, address in (('VarUtils.VariantClear', 0x627b14),
                              ('Windows.EnterCriticalSection', 0x60e35c),
                              ('Windows.LeaveCriticalSection', 0x60e6c8)):
            require(self.addr(name) == address, 'Original ABI boundary symbol')
        self.u = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        self.base = self.image.base
        self.original_image = self.image.pe.get_memory_mapped_image()
        self.image_size = (len(self.original_image) + 4095) & ~4095
        self.u.mem_map(self.base, self.image_size)
        self.u.mem_write(self.base, self.original_image)
        # Original Variants unit initialization installs this specific manager entry.
        init = self.walk.listing('Variants.Variants')[0]
        for address, mnemonic, operands in ((0x13691f0, 'mov', 'eax, 0x629f1c'),
                                           (0x13691f5, 'mov', 'edx, dword ptr [0x13c2f58]'),
                                           (0x13691fb, 'mov', 'dword ptr [edx], eax')):
            require(any(a == address and m == mnemonic and o == operands for a, m, o, _ in init), 'Variant initialization source')
        require(self.walk.dword(0x13c2f58) == 0x13a1010, 'Variant slot indirection')
        self.put(0x13a1010, self.addr('Variants.@VarClr'))
        self.frozen_image = bytes(self.u.mem_read(self.base, self.image_size))
        self.u.mem_protect(self.base, self.image_size, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        for a, b in (OWNED, STACK, (0, 4096), (RETURN, RETURN + 4096)):
            self.u.mem_map(a, b - a, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        self.next_owned = OWNED[0]
        self.objects, self.managed, self.locks, self.ref_lists = {}, [], {}, {}
        self.ranges, self.by_entry = [], {}
        for name in METHODS:
            start = self.addr(name)
            end = next(a for a in self.image.starts if a > start)
            if name == 'Variants.VarResultCheck':
                # MAP repeats this name; VarClearDeep calls the HRESULT-only overload.
                start, end = 0x629b40, 0x629b4c
                require(name in self.image.symbols[start], 'Original HRESULT overload symbol')
            self.ranges.append((start, end, name))
            self.by_entry[start] = name
        self.instructions, self.entries, self.trace = {}, Counter(), []
        self.phase, self.total, self.adapter_calls, self.writes = 'setup', 0, Counter(), Counter()
        self.u.hook_add(unicorn.UC_HOOK_CODE, self.guard)
        self.u.hook_add(unicorn.UC_HOOK_MEM_WRITE, self.write_guard)
        self.seed()

    def addr(self, name):
        return self.image.by_name[name]

    def put(self, address, value):
        self.u.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def word(self, address):
        return struct.unpack('<I', self.u.mem_read(address, 4))[0]

    def byte(self, address, value):
        self.u.mem_write(address, bytes([value]))

    def alloc(self, name, size=0x100):
        address = self.next_owned
        self.next_owned += (size + 15) & ~15
        require(self.next_owned <= OWNED[1], 'Owned arena bound')
        self.objects[name] = (address, size)
        return address

    def list(self, name, members=()):
        pointer = self.alloc(name, 0x20)
        data = self.alloc(name + '.items', max(16, len(members) * 4))
        self.put(pointer + 4, data)
        self.put(pointer + 8, len(members))
        self.put(pointer + 12, len(members))
        for i, member in enumerate(members):
            self.put(data + 4 * i, member)
        return pointer

    def managed_object(self, name, cls, size=0x200):
        pointer = self.alloc(name, size)
        self.put(pointer, self.walk.dword(self.addr(cls)))
        self.byte(pointer + 0x1c, 1)
        self.byte(pointer + 0x1d, 1)  # Original Create default; reads resolve this latch.
        publisher = self.alloc(name + '.publisher', 0x20)
        self.put(pointer + 0x18, publisher)
        self.put(publisher + 8, pointer)
        self.put(publisher + 12, self.list(name + '.subscribers'))
        self.managed.append(pointer)
        return pointer

    def custom(self, name, cls):
        pointer = self.managed_object(name, cls)
        manager = self.alloc(name + '.manager', 0x40)
        self.put(manager, self.walk.dword(self.addr('CIS_TCustomFlashObject..TAttributeManager')))
        self.put(manager + 0x20, pointer)
        self.put(pointer + 0x30, manager)
        refs = self.alloc(name + '.references', 0x10)
        thread_list = self.alloc(name + '.reference_lock', 0x30)
        self.put(pointer + 0x50, refs)
        self.put(refs + 4, thread_list)
        self.locks[thread_list + 8] = 0
        self.ref_lists[pointer] = (thread_list, [])
        return pointer

    def attribute(self, name, owner, cls):
        pointer = self.managed_object(name, cls)
        self.put(pointer + 0x40, self.word(owner + 0x30))
        return pointer

    def link(self, name, owner, field, child, after=None):
        attribute = self.attribute(name, owner, 'CIS_TObjectAttribute..TObjectAttribute')
        self.put(owner + field, attribute)
        reference = self.alloc(name + '.reference', 0x70)
        self.put(attribute + 0x78, reference)
        self.put(reference + 0x18, child)
        self.byte(reference + 0x40, 3)
        self.put(reference + 0x20, self.addr('CIS_TObjectAttribute.TObjectAttribute.ObjectChanged'))
        self.put(reference + 0x24, attribute)
        self.ref_lists[child][1].append(reference)
        if after:
            self.put(attribute + 0x60, self.addr(after))
            self.put(attribute + 0x64, owner)
        return attribute

    def seed(self):
        self.thermostat = self.custom('thermostat', 'CIS_TThermostat..TProgrammableThermostat')
        self.templates = self.alloc('templates', 0x80)
        self.put(self.templates + 12, self.thermostat)
        self.byte(self.templates + 0x28, 1)  # Existing original click-action guard, not an executed click.
        self.put(self.thermostat + 0x1b8, self.addr('CIS_TcdThermostatTemplates.TcdThermostatTemplates.HandleUnitZoneChange'))
        self.put(self.thermostat + 0x1bc, self.templates)
        services = {}
        for name, cls, field, event in (
                ('ui', 'TUIService', 0x1e4, 0xb0), ('plant', 'TPlantControlService', 0x1a8, 0x150),
                ('measurement', 'TTemperatureMeasurementService', 0x1ac, 0x88),
                ('schedule', 'TScheduleService', 0x1ec, 0x80),
                ('cbus', 'TCBusParameters', 0x1a0, None), ('zone_manager', 'TZoneManagerService', 0x1a4, None)):
            pointer = self.custom(name, 'CIS_TThermostat..' + cls)
            self.link('thermostat.' + name, self.thermostat, field, pointer)
            services[name] = pointer
            if event is not None:
                self.put(pointer + event, self.addr('CIS_TThermostat.TThermostat.HandleZoneChange'))
                self.put(pointer + event + 4, self.thermostat)
        self.zones, self.boolean_attributes = {}, {}
        specs = (
            ('UsedZones', self.thermostat, 0x1d8, 1, None),
            ('UIAllocatedZones', services['ui'], 0x98, 1, 'TUIService.HandleZoneAfterChange'),
            ('InternalPlantZones', services['plant'], 0x90, 1, 'TPlantControlService.HandleZoneAfterChange'),
            ('MeasuredZones', services['measurement'], 0x7c, 1, 'TTemperatureMeasurementService.HandleZoneAfterChange'),
            ('ScheduleControlledZones', services['schedule'], 0x78, 1, 'TScheduleService.HandleZoneAfterChange'),
            ('InstalledZones', services['cbus'], 0x84, 3, 'TCBusParameters.HandleInstalledZonesAfterChange'),
            ('ControlledZones', services['zone_manager'], 0x78, 3, 'TZoneManagerService.HandleZoneAfterChange'),
            ('HeatingPlantInstalledZones', services['zone_manager'], 0x80, 1, 'TZoneManagerService.HandleZoneAfterChange'),
            ('CoolingPlantInstalledZones', services['zone_manager'], 0x88, 1, 'TZoneManagerService.HandleZoneAfterChange'),
            ('VentingPlantInstalledZones', services['zone_manager'], 0x94, 1, 'TZoneManagerService.HandleZoneAfterChange'))
        for name, owner, field, mask, callback in specs:
            zones = self.custom(name, 'CIS_TThermostatCommon..TZones')
            self.link(name + '.attribute', owner, field, zones, 'CIS_TThermostat.' + callback if callback else None)
            self.zones[name] = zones
            for bit in range(5):
                boolean = self.attribute(name + '.bit' + str(bit), zones, 'CIS_TBooleanAttribute..TBooleanAttribute')
                self.put(zones + 0x78 + 4 * bit, boolean)
                self.byte(boolean + 0x70, (mask >> bit) & 1)
                self.boolean_attributes[name, bit] = boolean
        for name, field in (('master_slave', 0xf8), ('heating_type', 0x7c), ('cooling_type', 0x84), ('venting_type', 0x90)):
            cls = ('CIS_TEnumeratedTypeAttribute..TEnumeratedTypeAttribute' if name == 'master_slave'
                   else 'CIS_TThermostat..TPlantTypeAttribute')
            attr = self.attribute(name, services['zone_manager'], cls)
            self.put(services['zone_manager'] + field, attr)
        for pointer, (thread_list, refs) in self.ref_lists.items():
            self.put(thread_list + 4, self.list('refs.' + hex(pointer), refs))
        self.parent_frame = self.alloc('nested_parent_frame', 0x20) + 4
        self.put(self.parent_frame - 4, self.templates)
        self.services = services

    def guard(self, machine, address, size, _):
        self.total += 1
        require(self.total <= BUDGET, 'Cumulative instruction budget')
        if address == 0x627b14:  # Original VarUtils.VariantClear import boundary.
            stack = machine.reg_read(ESP)
            pointer = self.word(stack + 4)
            require(STACK[0] <= pointer and pointer + 16 <= STACK[1], 'VariantClear requires owned stack variant')
            require(struct.unpack('<H', machine.mem_read(pointer, 2))[0] in (0, 11),
                    'VariantClear only admits VT_EMPTY or VT_BOOL')
            # No referenced allocation exists for these two admitted types.
            # Preserve the inactive payload; only the active type is cleared.
            machine.mem_write(pointer, b'\0\0')
            machine.reg_write(EAX, 0)  # S_OK
            machine.reg_write(EIP, self.word(stack))
            machine.reg_write(ESP, stack + 8)  # stdcall, one pointer argument
            self.adapter_calls['variant_clear_empty_or_bool'] += 1
            return
        if address in (0x60e35c, 0x60e6c8):
            stack = machine.reg_read(ESP)
            lock = self.word(stack + 4)
            require(lock in self.locks, 'Lock ABI adapter only admits owned list locks')
            delta = 1 if address == 0x60e35c else -1
            require(self.locks[lock] + delta >= 0, 'Balanced owned lock exit')
            self.locks[lock] += delta
            self.adapter_calls['enter' if delta == 1 else 'leave'] += 1
            machine.reg_write(EIP, self.word(stack))
            machine.reg_write(ESP, stack + 8)
            return
        spans = [(a, b, n) for a, b, n in self.ranges if a <= address and address + size <= b]
        require(len(spans) == 1, 'Unapproved original instruction at ' + hex(address))
        encoded = self.image.pe.get_data(address - self.base, size)
        decoded = list(self.image.decoder.disasm(encoded, address, count=1))
        require(len(decoded) == 1 and decoded[0].size == size, 'Instruction decoding')
        require(decoded[0].mnemonic not in ('int', 'int3', 'syscall', 'sysenter', 'in', 'out', 'insb', 'outsb'), 'External instruction denied')
        require(bytes(machine.mem_read(address, size)) == encoded, 'Original code altered')
        self.instructions[address] = size
        if address in self.by_entry:
            name = self.by_entry[address]
            self.entries[name] += 1
            if name.endswith(('HandleZoneAfterChange', 'HandleZoneChange', 'HandleUnitZoneChange', 'UpdateQuickOptions', 'SetAsBoolean')):
                obj = machine.reg_read(EAX)
                label = next((n for n, (a, _s) in self.objects.items() if a == obj), hex(obj))
                self.trace.append({'phase': self.phase, 'method': name, 'object': label})

    def write_guard(self, machine, _access, address, size, _value, _):
        require(any(a <= address and address + size <= b for a, b in (OWNED, STACK, (0, 4))),
                'Write outside owned state: ' + hex(address))
        self.writes['owned' if OWNED[0] <= address < OWNED[1] else 'stack' if address else 'seh'] += 1

    def call(self, name, eax=0, edx=0, args=()):
        stack = STACK[0] + 0x18000
        self.put(stack, RETURN)
        for i, arg in enumerate(args):
            self.put(stack + 4 + 4 * i, arg)
        saved = {EBX: 0x11223344, ESI: 0x55667788, EDI: 0x99aabbcc, EBP: 0x11221122}
        for reg, value in saved.items():
            self.u.reg_write(reg, value)
        for reg, value in ((EAX, eax), (EDX, edx), (ECX, 0), (ESP, stack)):
            self.u.reg_write(reg, value)
        self.u.emu_start(self.addr(name), RETURN, timeout=2000000, count=BUDGET)
        require(self.u.reg_read(EIP) == RETURN and self.u.reg_read(ESP) == stack + 4, 'Original return/stack')
        require(all(self.u.reg_read(reg) == value for reg, value in saved.items()), 'Original callee register preservation')
        require(self.word(0) == 0 and not any(self.locks.values()), 'SEH/owned lock restoration')
        return self.u.reg_read(EAX)

    def masks(self):
        return {name: sum((self.u.mem_read(attr + 0x70, 1)[0] << bit)
                          for (source, bit), attr in self.boolean_attributes.items() if source == name)
                for name in self.zones}

    def run(self):
        self.phase = 'original_boolean_reads'
        before = self.masks()
        for attr in self.boolean_attributes.values():
            self.call('CIS_TBooleanAttribute.TBooleanAttribute.AsBoolean', attr)
        self.phase = 'include_zone_1'
        self.call('CIS_TcdThermostatTemplates.IncludeZone', 1, args=(self.parent_frame,))
        after = self.masks()
        expected = dict(before)
        for name in ('UsedZones', 'UIAllocatedZones', 'InternalPlantZones', 'MeasuredZones', 'ScheduleControlledZones'):
            expected[name] = 3
        require(after == expected, 'Independent exact mask vector')
        require(all(self.word(p + 0x10) == 0 for p in self.managed), 'Balanced managed update counts')
        require(all(self.word(p + 0x10) == 0 for name, (p, _s) in self.objects.items()
                    if name.endswith('.manager')), 'Balanced attribute-manager update counts')
        require(all(self.word(self.objects[name][0] + 0x70) == 0
                    for name in ('master_slave', 'heating_type', 'cooling_type', 'venting_type')),
                'Retained master and zero plant types')
        require(self.u.mem_read(self.templates + 0x28, 1)[0] == 1, 'Outer action guard retained')
        require(self.u.mem_read(self.thermostat + 0x1c0, 1)[0] == 0, 'Thermostat guard restored')
        require(self.u.mem_read(self.services['plant'] + 0x15c, 1)[0] == 0, 'Plant guard restored')
        require(bytes(self.u.mem_read(self.base, self.image_size)) == self.frozen_image, 'Immutable original image')
        require({sha(p.read_bytes()) for p in self.library_paths} == LIBRARIES, 'Instruction engine libraries unchanged')
        callbacks = [e for e in self.trace if e['method'].endswith('HandleZoneAfterChange')]
        require([e['object'] for e in callbacks] == ['ui', 'plant', 'measurement', 'schedule'], 'Ordered four model callbacks')
        require(self.entries['CIS_TcdThermostatTemplates.TcdThermostatTemplates.UpdateQuickOptions'] == 4, 'Four actual guarded quick refreshes')
        setters = [e['object'] for e in self.trace if e['method'].endswith('SetAsBoolean')]
        require(setters == [name + '.bit1' for name in ('UsedZones', 'UIAllocatedZones', 'InternalPlantZones',
                                                       'MeasuredZones', 'ScheduleControlledZones', 'InstalledZones',
                                                       'ControlledZones')], 'Ordered seven original Boolean setters')
        methods = [{'name': name, 'start': hex(a), 'end': hex(b),
                    'sha256': sha(self.image.pe.get_data(a - self.base, b - a)), 'entries': self.entries[name]}
                   for a, b, name in self.ranges]
        return {'schema': 'cbus-thermostat-quick-zone-core-original-v1', 'passed': True,
                'scope': __doc__, 'source_exe_sha256': EXE_SHA256, 'source_map_sha256': MAP_SHA256,
                'probe_sha256': sha(Path(__file__).read_bytes()),
                'engine_versions': {'unicorn': unicorn.__version__, 'capstone': capstone.__version__},
                'actual_instruction_engine_sha256': sorted(LIBRARIES),
                'input': {'action': 'IncludeZone(1)', 'plant_types': [0, 0, 0], 'master_slave': 0,
                          'programmable': True, 'before_masks': before, 'templates_action_guard': True},
                'after_masks': after, 'expected_masks': expected, 'callback_trace': self.trace,
                'runtime_data_initialization': {'slot': '0x13a1010', 'target': '0x629f1c',
                    'source': 'Variants.Variants at 0x13691f0..0x13691fb; indirection 0x13c2f58'},
                'methods': methods, 'instruction_count': self.total, 'unique_instruction_count': len(self.instructions),
                'original_instruction_events': self.total - sum(self.adapter_calls.values()),
                'instruction_budget': BUDGET, 'abi_adapter_calls': dict(self.adapter_calls),
                'abi_adapter_semantics': {
                    '0x627b14 VarUtils.VariantClear': 'Owned stack VT_EMPTY/VT_BOOL only; clear type word, retain inactive payload, return S_OK; stdcall one argument. Original OleAut32 excluded.',
                    '0x60e35c Windows.EnterCriticalSection': 'Owned reference-list lock only; increment single-thread recursive depth; stdcall one argument.',
                    '0x60e6c8 Windows.LeaveCriticalSection': 'Owned reference-list lock only; require positive recursive depth then decrement; stdcall one argument.'},
                'writes': dict(self.writes), 'image_unchanged_after_runtime_data_seed': True,
                'adapter_stack_type_word_writes': self.adapter_calls['variant_clear_empty_or_bool'],
                'writes_outside_owned_state': 0, 'original_instruction_bytes_verified_at_every_execution': True,
                'balanced_update_counters_locks_and_seh': True, 'plant_types_and_master_preserved': True,
                'model_callbacks_executed': True, 'full_original_form_executed': False,
                'constructors_executed': False, 'pp_load_save_reload_executed': False,
                'project_group_allocation_proven': False, 'public_action_accepted': False,
                'omissions': ['GUI publisher subscribers/expression consumers', 'workspace',
                              'parent EnableDisableZone callback', 'unrelated model attributes',
                              'original constructor/AfterLoad graph', 'project/group metadata',
                              'BeforeSave/save/reload', 'outer click and confirmation workflow']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--confined-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.confined_child:
        require(sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').is_file(), 'macOS network confinement available')
        command = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)',
                   sys.executable, '-B', str(Path(__file__).resolve()), '--confined-child',
                   '--exe', str(args.exe.resolve(strict=True)), '--map', str(args.map.resolve(strict=True)),
                   '--output', str(args.output.resolve())]
        result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
        require(result.returncode == 0 and not result.stderr, 'Confined child failed: ' + result.stderr[-5000:])
        report = json.loads(result.stdout)
        report.update(network_denied_by_macos_sandbox=True, child_exit_code=0)
        with args.output.open('x') as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write('\n')
        print(json.dumps({'passed': True, 'instruction_count': report['instruction_count'], 'output': str(args.output)}))
        return
    sys.addaudithook(deny_external)
    probe = Probe(args.exe, args.map)
    report = probe.run()
    require(args.exe.read_bytes() == probe.exe_raw and args.map.read_bytes() == probe.map_raw, 'Source input changed')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
