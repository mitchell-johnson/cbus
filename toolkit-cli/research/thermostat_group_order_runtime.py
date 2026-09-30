"""Observe bounded original thermostat group ordering instructions offline.

The child runs with macOS network access denied. It maps the pinned PE as data,
then Unicorn executes only declared, byte-verified x86 instruction ranges.
Synthetic already-resolved group objects supply explicit inventory/order.
No Toolkit initialization, imports, GUI, object creation or C-Gate call runs.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys

import capstone
import unicorn
from unicorn.x86_const import (UC_X86_REG_EAX as EAX, UC_X86_REG_EBX as EBX,
                              UC_X86_REG_ECX as ECX, UC_X86_REG_EDX as EDX,
                              UC_X86_REG_EBP as EBP, UC_X86_REG_ESP as ESP,
                              UC_X86_REG_EIP as EIP)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402
from thermostat_post_load_static import _Walker  # noqa: E402

REF = 'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.'
GROUP = 'CIS_TCommonCBus.TCBusGroupManager.'
METHODS = (
    'CIS_TCustomFlashObject.QuickInsert', REF + 'GetSortedInsertLocation', REF + 'Compare',
    REF + 'GetCount', REF + 'GetItem', REF + 'ResolveChange', REF + 'ResolveAllReferences',
    'CIS_TManagedFlashObject.TManagedFlashObject.ResolveChange',
    'CIS_TCustomFlashObject.TFlashObjectReference.GetFlashObject',
    'CIS_TCustomFlashObject.TFlashObjectReference.ResolveReference',
    'CIS_TCBusObject.TCGateObjectManager.CustomSortAddressAsc',
    'CIS_TCBusObject.TCGateObject.GetAddressAsInteger',
    'CIS_TCBusObject.TCGateAddressAttribute.GetSimpleDecimalAddress',
    GROUP + 'GetItem', GROUP + 'GroupByAddress', GROUP + 'GroupByAddressExclude',
    GROUP + 'GetNextAvailableAddress', GROUP + 'GetMaximumPossibleAddress',
    GROUP + 'IndexOfGroupByAddress', GROUP + 'GetApplication',
    'CIS_TCommonCBus.TCBUSApplication.GetHasReservedGroupAddress255',
    'Classes.TList.Get', 'System.@IsClass', 'System.TObject.InheritsFrom',
    'System.@IntfClear', 'System.@UStrClr', 'System.@LStrClr',
    'Variants.@VarClr', 'Variants.@VarClear',
)
LIBRARIES = {
    '7a379c419496cdc98d098fa356a1e9b4fdb90f4c325b4d98e60042ab3d8216b0',
    '7207c8e3d7a63118fb0bca73e01816797fd51b1d8a39a4cbc7abfd562ee59c85',
}
DATA, STACK, CODE = 0x10000000, 0x20000000, 0x30000000
END = CODE + 0xff0


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Fixture:
    def __init__(self, exe, map_path):
        raw, map_raw = exe.read_bytes(), map_path.read_bytes()
        require((sha(raw), sha(map_raw)) == (EXE_SHA256, MAP_SHA256), 'Pinned original EXE/MAP')
        self.image = _Image(raw, map_raw)
        self.walker = _Walker(self.image)
        self.spans = []
        for name in METHODS:
            start = self.image.by_name[name]
            self.spans.append((name, start, next(a for a in self.image.starts if a > start)))
        # The MAP has overloaded System.Pos symbols. This call is the Unicode overload.
        self.spans += [('System.Pos (Unicode overload)', 0x6094d4, 0x609520),
                       ('TPlantControlService.GetNewGroup search region', 0xfe2f89, 0xfe3229)]
        self.u = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        mapped = self.image.pe.get_memory_mapped_image()
        self.u.mem_map(self.image.base, (len(mapped) + 4095) & ~4095)
        self.u.mem_write(self.image.base, mapped)
        self.u.mem_protect(self.image.base, (len(mapped) + 4095) & ~4095,
                           unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        for address, size in ((0, 4096), (DATA, 0x100000), (STACK, 0x20000), (CODE, 4096)):
            self.u.mem_map(address, size)
        self.cursor = DATA + 0x2000
        self.instructions, self.visited, self.adapters = {}, set(), {}
        self.writes = 0
        self.stop = None
        self.outcome = None
        self.u.hook_add(unicorn.UC_HOOK_CODE, self.guard)
        self.u.hook_add(unicorn.UC_HOOK_MEM_WRITE, self.write_guard)
        self.manager, self.application, self.thermostat, self.plant = (DATA + n for n in (0, 0x200, 0x400, 0x600))
        self.list_object, self.list_array = DATA + 0x800, DATA + 0x1000
        self.put(self.manager, self.walker.dword(self.image.by_name['CIS_TCommonCBus..TCBusGroupManager']))
        self.put(self.manager + 0x6c, self.list_object)
        self.put(self.manager + 0x30, self.application)
        self.put(self.list_object + 4, self.list_array)
        self.u.mem_write(self.manager + 0x59, b'\x03')
        self.put(self.manager + 0x60, 0xf4825c)
        self.put(self.manager + 0x64, self.manager)
        self.put(self.application + 0xb4, self.manager)
        self.put(self.plant + 0x158, self.thermostat)
        self.put(self.thermostat, DATA + 0xc00)
        self.put(DATA + 0xc00 + 0xb0, CODE + 0x100)
        self.put(self.thermostat + 0x10, self.application)
        self.adapter(CODE + 0x100, bytes.fromhex('8b4010c3'), 'declared output application pointer')
        self.adapter(CODE + 0x120, bytes.fromhex('8b40048902c3'), 'declared immutable tag pointer')
        self.groups = {}
        self.prefix = self.string('[CG01]')
        # Pure input adapter for the original AutogeneratedPrefix call: no tag
        # matching or allocation decision is made here.
        self.adapter(CODE + 0x140, b'\xb8' + self.prefix.to_bytes(4, 'little') + bytes.fromhex('8902c3'),
                     'declared thermostat prefix string')

    def put(self, address, value):
        self.u.mem_write(address, (value & 0xffffffff).to_bytes(4, 'little'))

    def get(self, address):
        return int.from_bytes(self.u.mem_read(address, 4), 'little')

    def alloc(self, length):
        result = self.cursor
        self.cursor += (length + 15) & ~15
        require(self.cursor < DATA + 0x100000, 'Synthetic fixture memory bound')
        return result

    def string(self, value):
        raw = value.encode('utf-16le')
        address = self.alloc(12 + len(raw) + 2)
        self.put(address + 4, 0xffffffff)
        self.put(address + 8, len(value))
        self.u.mem_write(address + 12, raw + b'\0\0')
        return address + 12

    def adapter(self, address, raw, meaning):
        self.u.mem_write(address, raw)
        for ins in self.image.decoder.disasm(raw, address):
            self.adapters[ins.address] = (bytes(ins.bytes), meaning)

    def group(self, address, prefixed=True):
        key = (address, prefixed)
        if key in self.groups:
            return self.groups[key]
        obj, attr, ref, tag = (self.alloc(n) for n in (0x200, 0x100, 0x80, 0x10))
        self.put(obj, self.walker.dword(self.image.by_name['CIS_TCommonCBus..TCBusGroup']))
        self.put(obj + 0x80, attr)
        self.put(attr + 0x88, address)
        self.put(ref + 0x18, obj)
        self.u.mem_write(ref + 0x40, b'\x03')  # Already resolved; no loading is claimed.
        self.put(tag, DATA + 0xe00)
        self.put(DATA + 0xe00 + 0x2c, CODE + 0x120)
        self.put(tag + 4, self.string(('[CG01] ' if prefixed else 'Other [CG01] ') + str(address)))
        self.put(obj + 0x9c, tag)
        self.groups[key] = (obj, ref)
        return obj, ref

    def inventory(self, addresses, prefixed=None):
        require(len(addresses) <= 256 and len(set(addresses)) == len(addresses), 'Unique byte-address inventory')
        prefixed = set(addresses) - {255} if prefixed is None else set(prefixed)
        for index, address in enumerate(addresses):
            require(type(address) is int and 0 <= address <= 255, 'Byte address')
            _obj, ref = self.group(address, address in prefixed)
            self.put(self.list_array + 4 * index, ref)
        self.put(self.list_object + 8, len(addresses))
        self.u.mem_write(self.manager + 0x1d, b'\0')

    def guard(self, machine, address, size, _):
        if address == END:
            machine.emu_stop()
            return
        if self.stop and address in (0xfe3050, 0xfe316a, 0xfe3229):
            frame = machine.reg_read(EBP)
            if address == 0xfe3050:
                self.outcome = ('above-prefix', self.get(frame - 0xc))
            elif address == 0xfe316a:
                self.outcome = ('lowest-free', self.get(frame - 0x10))
            else:
                require(self.get(frame - 0x18) == 0, 'No reused or created object in tag-miss fixture')
                self.outcome = ('full', None)
            machine.emu_stop()
            return
        # Supply the prefix as an explicit input through its original call.
        if self.stop and address == 0xfe2a74:
            machine.reg_write(EIP, CODE + 0x140)
            return
        expected = self.instructions.get(address)
        if expected is None:
            if address in self.adapters:
                expected = self.adapters[address][0]
            else:
                require(any(start <= address and address + size <= end for _n, start, end in self.spans),
                        'Instruction outside declared original methods: ' + hex(address))
                expected = self.image.pe.get_data(address - self.image.base, size)
                ins = list(self.image.decoder.disasm(expected, address, count=1))
                require(len(ins) == 1 and ins[0].size == size, 'Original instruction decoding')
                require(ins[0].mnemonic not in ('int', 'syscall', 'sysenter', 'in', 'out'), 'No external instructions')
            self.instructions[address] = expected
        require(len(expected) == size and bytes(machine.mem_read(address, size)) == expected,
                'Original or adapter instruction changed: ' + hex(address))
        self.visited.add(address)

    def write_guard(self, _machine, _access, address, size, _value, _):
        require((STACK <= address and address + size <= STACK + 0x20000)
                or (DATA <= address and address + size <= DATA + 0x100000)
                or (address == 0 and size == 4), 'Write outside synthetic fixture state')
        self.writes += 1

    def call(self, entry, eax=0, edx=0, ecx=0, stack_args=()):
        self.stop = None
        stack = STACK + 0x1f000
        for index, value in enumerate((END,) + tuple(stack_args)):
            self.put(stack + 4 * index, value)
        for register, value in ((ESP, stack), (EBP, 0), (EAX, eax), (EDX, edx), (ECX, ecx), (EBX, 0)):
            self.u.reg_write(register, value)
        try:
            self.u.emu_start(entry, END, count=100000)
        except unicorn.UcError as error:
            raise AssertionError('Original fixture fault at ' + hex(self.u.reg_read(EIP))
                                 + ', esp=' + hex(self.u.reg_read(ESP))) from error
        require(self.u.reg_read(EIP) == END, 'Original call completed within instruction bound')
        return self.u.reg_read(EAX)

    def compare(self, left, right):
        result = self.call(0x7e98f8, self.manager, self.group(left)[0], self.group(right)[0])
        return result - (1 << 32) if result >= (1 << 31) else result

    def insert(self, ordered, address):
        self.inventory(ordered)
        return self.call(0x7e9b30, self.manager, self.group(address)[0])

    def search(self, addresses, prefixed):
        self.inventory(addresses, prefixed)
        frame, outer = STACK + 0x1f000, STACK + 0x1f100
        self.u.mem_write(frame - 0x100, b'\0' * 0x100)
        self.put(frame + 8, outer)
        self.put(outer - 4, self.plant)
        self.u.reg_write(EBP, frame)
        self.u.reg_write(ESP, frame - 0x100)
        self.stop, self.outcome = True, None
        self.u.emu_start(0xfe2f89, 0xfe322a, count=1000000)
        require(self.outcome is not None, 'Original search reached an allocation boundary within instruction bound')
        return self.outcome


def observe(exe, map_path):
    from unicorn.unicorn_py3 import unicorn as core
    libs = {sha(Path(path).read_bytes()) for path in (core.uclib._name, capstone._cs._name)}
    require(libs == LIBRARIES, 'Pinned actual Unicorn/Capstone libraries')
    f = Fixture(exe, map_path)
    pairs = [(a, b) for a in (0, 1, 2, 127, 254, 255) for b in (0, 1, 2, 127, 254, 255)]
    comparisons = []
    for a, b in pairs:
        expected = 0 if a == b else (-1 if a == 255 else (1 if b == 255 else a - b))
        actual = f.compare(a, b)
        require(actual == expected, 'Original address comparator literal expectation')
        comparisons.append([a, b, actual])
    template_trace, ordered = [], []
    for address in (255, 5, 3, 6, 2):
        position = f.insert(ordered, address)
        ordered.insert(position, address)
        template_trace.append({'address': address, 'position': position, 'order': list(ordered)})
    require(ordered == [255, 2, 3, 5, 6], 'Template 9 literal insertion result')
    for permutation in itertools.permutations((255, 5, 3, 6, 2)):
        values = []
        for address in permutation:
            values.insert(f.insert(values, address), address)
        require(values == [255, 2, 3, 5, 6], 'Empty-address-sorted insertion permutation')
    unsorted = [5, 1, 7, 3]
    for address in (6, 4, 2):
        unsorted.insert(f.insert(unsorted, address), address)
    require(unsorted == [4, 5, 1, 2, 6, 7, 3], 'Unsorted initial list remains a counterexample')
    # Independently execute the original limit getter while 255 is not an
    # occupied group. The cap is not an artifact of the full-inventory case.
    f.inventory([])
    maximum = f.call(0xf28a58, f.manager)
    require(maximum == 254, 'Original application reserves free address 255')
    cases = [
        ('template9-address-order', [255, 2, 3, 5, 6], [2, 3, 5, 6], ('above-prefix', 7)),
        ('explicit-other-order', [255, 2, 5, 6, 3], [2, 3, 5, 6], ('above-prefix', 4)),
        ('skip-occupied-successor', [255, 2, 4, 3], [3], ('above-prefix', 5)),
        ('nonprefix-tail-ignored', [255, 3, 10], [3], ('above-prefix', 4)),
        ('prefix-not-at-start', [255, 3], [], ('lowest-free', 0)),
        ('prefix254-falls-back', [254, 255], [254], ('lowest-free', 0)),
        ('no-prefix-lowest-hole', [0, 1, 3, 255], [], ('lowest-free', 2)),
        ('empty-lowest-free', [], [], ('lowest-free', 0)),
        ('all256-present', list(range(256)), [], ('full', None)),
    ]
    observed = []
    for name, addresses, prefixed, expected in cases:
        actual = f.search(addresses, prefixed)
        require(actual == expected, name + ' literal allocation expectation')
        observed.append({'case': name, 'manager_order': addresses, 'prefixed_addresses': prefixed,
                         'boundary': actual[0], 'candidate_address': actual[1]})
    require((sha(exe.read_bytes()), sha(map_path.read_bytes())) == (EXE_SHA256, MAP_SHA256), 'Original inputs unchanged')
    return {'format': 'cbus-thermostat-group-order-original-instructions-v1', 'passed': True,
            'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
            'actual_instruction_engine_sha256': sorted(libs),
            'instruction_engine_versions': {'unicorn': unicorn.__version__, 'capstone': capstone.__version__},
            'original_gui_executed': False, 'original_initialization_executed': False,
            'original_imports_executed': False, 'hardware_access': False,
            'source_scope': 'Original comparator and binary insertion-position search with host-maintained inventory; '
                            'GetNewGroup tag-miss search only.',
            'original_method_spans': [{'name': n, 'start': hex(a), 'end': hex(b),
                                      'sha256': sha(f.image.pe.get_data(a - f.image.base, b - a))}
                                     for n, a, b in f.spans],
            'fixture_boundary': ['Explicit ordered, unique byte-address inventory with already-resolved references.',
                                 'Original cached-address getters read supplied address attributes.',
                                 'Application, tag, and prefix adapters supply declared inputs only.',
                                 'Search begins after FindExistingGroup returned nil; reuse/name construction excluded.',
                                 'Search stops before original object creation; no insertion or database save is implied.',
                                 'No preload sortedness, locale-dependent tag sorting, or whole-form claim.'],
            'adapters': sorted(set(meaning for _raw, meaning in f.adapters.values())),
            'comparisons': comparisons, 'empty_inventory_permutations': 120,
            'original_maximum_allocatable_address_with_empty_inventory': maximum,
            'template9_insertion_trace': template_trace, 'unsorted_initial_counterexample': unsorted,
            'search_cases': observed, 'unique_executed_instructions_including_adapters': len(f.visited),
            'unique_original_instructions': len(f.visited - f.adapters.keys()),
            'unique_adapter_instructions': len(f.visited & f.adapters.keys()),
            'original_bytes_verified_at_every_execution': True, 'writes_to_fixture_state': f.writes,
            'writes_outside_fixture_state': 0, 'production_admission_changed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', dest='map_path', type=Path, required=True)
    parser.add_argument('--confined-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.confined_child:
        print(json.dumps(observe(args.exe, args.map_path), sort_keys=True, indent=2))
        return
    require(sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').is_file(), 'macOS network confinement available')
    command = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)',
               sys.executable, '-B', str(Path(__file__).resolve()), '--confined-child',
               '--exe', str(args.exe.resolve(strict=True)), '--map', str(args.map_path.resolve(strict=True))]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    require(result.returncode == 0 and not result.stderr, 'Confined child failed: ' + result.stderr[-4000:])
    report = json.loads(result.stdout)
    report.update(network_denied_by_macos_sandbox=True, child_exit_code=result.returncode,
                  checker_sha256=sha(Path(__file__).read_bytes()))
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
