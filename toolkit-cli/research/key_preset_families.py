"""Prove which key input types share the supported preset layout and save path.

Supply decoded unit specifications and the original Toolkit 1.18 EXE and MAP
explicitly. Nothing is executed or opened on C-Gate. The receipt contains
hashes, parameter names, class names, registration facts and decisions only;
no specification content or instruction bytes are copied.

Specification facts compare every parameter's structural layout (type, address,
array size, bit size, bit address and array skip) with a reference type that
already has native preset acceptance. Executable facts follow the RegisterUnitType
and TFlashAgentFactory.RegisterAgent call sites, Delphi VMT parent chains, the
virtual MacroFunctionSubsetName and MaximumKeyCount implementations, and the
macro-function subset registrations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

import capstone
import pefile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cbus_toolkit.unitspec import UnitCatalog, UnitSpecStore, _integer, version_matches  # noqa: E402


FORMAT = 'cbus-key-preset-family-equivalence-v1'
EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
MAP_SHA256 = 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
REGISTER_UNIT_TYPE = 'CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType'
REGISTER_AGENT = 'CIS_TCustomFlashObject.TFlashAgentFactory.RegisterAgent'
SUBSET_FACTORY = 'CIS_TKeyMacrofunctionSubset.InitialiseKeyMacroFunctionSubsetFactory'
REGISTER_SUBSET = 'CIS_TKeyMacrofunctionSubset.TKeyMacroFunctionSubsetFactory.RegisterKeyMacroFunctionSubset'
SUBSET_SLOT_OWNER = ('CIS_TCoreKeyInputUnit..TCoreKeyInputUnit',
                     'CIS_TCoreKeyInputUnit.TCoreKeyInputUnit.MacroFunctionSubsetName')
KEY_COUNT_SLOT_OWNER = ('CIS_TKey4..TKey4', 'CIS_TKey4.TKey4.MaximumKeyCount')
BCNC4_SAVE = 'CIS_TBCNC4CGateAgent.TBCNC4CGateAgent.BeforeSaveProgrammingInformation'
BCNC4_DEFAULTS = 'CIS_TBCNC.TBCNC4.ApplyMicroFunctionDefaults'
AUX_RECONCILE = 'CIS_TKeyMacroFunction.TKeyMacroFunction.ReconcileTemplateAndGroup'
MICRO_FACTORY = 'CIS_TKeyMicroFunction.InitialiseKeyMicroFunctionFactory'
REGISTER_MICRO = 'CIS_TKeyMicroFunction.TKeyMicroFunctionFactory.RegisterKeyMicroFunction'
GROUP_FACTORY = 'CIS_TKeyMicroFunctionGroup.InitialiseKeyMicroFunctionGroupFactory'
REGISTER_GROUP = 'CIS_TKeyMicroFunctionGroup.TKeyMicroFunctionGroupFactory.RegisterKeyMicroFunctionGroup'
GROUP_CLASS = 'CIS_TKeyMicroFunctionGroup.TKeyMicroFunctionGroup.'
TEMPLATE_FACTORY = 'CIS_TKeyMacroFunction.InitialiseKeyMacroFunctionFactory'
REGISTER_TEMPLATE = 'CIS_TKeyMacroFunction.TKeyMacroFunctionFactory.RegisterTemplate'
TEMPLATE_DEFAULT = 'CIS_TKeyMacroFunction.TKeyMacroFunctionTemplate.GetMicroFunctionGroupDefault'
ASSIGN_MICROFUNCTIONS = 'CIS_TKeyMacroFunction.TKeyMacroFunction.AssignTemplate_Microfunctions'
REFRESH_FROM_TYPE = 'CIS_TKeyMacroFunction.TKeyMacroFunction.RefreshFromFunctionType'
# Original help event tables (topics 965, 968, 969) that differ from the
# micro-function group Toolkit assigns when the template is selected.
HELP_TABLE_VECTORS = {'bellpress': [13, 15, 13, 15], 'soft_up': [14, 10, 5, 14],
                      'soft_down': [14, 9, 4, 14]}
# Delphi 32-bit VMT offsets relative to the class pointer.
VMT_SELF, VMT_CLASS_NAME, VMT_PARENT = -88, -56, -48

# Toolkit TKeyMacroFunctionTemplate function types for the 18 CLI presets.
# RegisterTemplate names 0-11 inline (On, Off, On/Off, Dimmer, On Up, Off Down,
# Timer, Bell Press, Dimmer Up, Dimmer Down, Soft Up, Soft Down) and 16 Unused;
# 12-15 use resource strings and the micro-function groups for Preset 1/2 and
# Trigger 1/2. Both dimmer variants are groups of the single Dimmer template.
PRESET_TEMPLATE_TYPES = {
    'unused': 16, 'on': 0, 'off': 1, 'toggle': 2, 'dimmer': 3, 'dimmer_memory': 3,
    'on_up': 4, 'off_down': 5, 'timer': 6, 'bellpress': 7, 'dimmer_up': 8,
    'dimmer_down': 9, 'soft_up': 10, 'soft_down': 11, 'preset1': 12, 'preset2': 13,
    'trigger1': 14, 'trigger2': 15,
}

CLASSIC_REFERENCE = 'KEY4.xml'
CLASSIC_WORKFLOW = ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand', 'BlockAllocation',
                    'GroupAddress', 'Application', 'TimerHighByte', 'TimerLowByte',
                    'TimerExpiryCommand', 'LightLevelStore1', 'LightLevelStore2')
CLASSIC_CANDIDATES = ('KEY1.xml', 'KEY2.xml', 'KEY4.xml', 'KEYIR1.xml', 'KEYIR4.xml',
                      'KEYAUX4.xml', 'DINAUX4.xml', 'KEYBC2.xml', 'KEYBC4.xml', 'BCNC4A.xml')
CLASSIC_ACCEPTED_AGENT = 'TCBusKeyInputCGateAgent'
CLASSIC_ALREADY = ('KEY1', 'KEY2', 'KEY4')

NEO_REFERENCE = 'KEYM4.xml'
NEO_WORKFLOW = ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand', 'BlockAllocation',
                'GroupAddress', 'Application', 'SecondApplicationBlocks', 'TimerHighByte',
                'TimerLowByte', 'TimerExpiryCommand', 'LightLevelStore1', 'LightLevelStore2',
                'SceneKeySelector', 'IndicatorBlockAssignment')
NEO_CANDIDATES = tuple(f'{name}.xml' for name in (
    'KEYA1', 'KEYA3', 'KEYA6', 'KEYA8', 'KEYAV2', 'KEYAV4', 'KEYB2', 'KEYB4', 'KEYB6',
    'KEYC1', 'KEYC2', 'KEYC4', 'KEYCIR1', 'KEYCIR4', 'KEYDV1', 'KEYDV2', 'KEYDV3', 'KEYDV4',
    'KEYE', 'KEYH1', 'KEYH2', 'KEYH3', 'KEYH4', 'KEYM2', 'KEYM4', 'KEYM6', 'KEYM8',
    'KEYP2', 'KEYP4', 'KEYP6', 'KEYV1', 'KEYV2', 'KEYV3', 'KEYV1SP',
    'KEYA1_A', 'KEYA3_A', 'KEYA6_A', 'KEYA8_A', 'KEYAV2_A', 'KEYAV4_A', 'KEYB2_A', 'KEYB4_A',
    'KEYB6_A', 'KEYH1_A', 'KEYH2_A', 'KEYH3_A', 'KEYH4_A', 'KEYM2_A', 'KEYM4_A', 'KEYM6_A',
    'KEYM8_A'))
# KEYE1's TKEYEx class and TCBusKEYExCGateAgent (a TCBusNeoProInputCGateAgent
# subclass) were accepted separately; its KeyMask difference is outside presets.
NEO_ACCEPTED_AGENTS = ('TCBusNeoProInputCGateAgent', 'TCBusKEYExCGateAgent')
NEO_ALREADY = ('KEYE1', 'KEYM4', 'KEYA3', 'KEYB4')
# Firmware used by the native acceptance for each family.
TESTED_FIRMWARE = {'classic': '1.2.67', 'neo': '2.5.00'}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _layout(parameter) -> list:
    fields = parameter.fields
    return [parameter.type, parameter.address, parameter.array_size, parameter.bit_size,
            _integer(fields.get('BitAddress') or '0'), _integer(fields.get('ArraySkip') or '0')]


def _digest(value) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


class Image:
    def __init__(self, exe: Path, map_file: Path):
        raw, map_raw = exe.read_bytes(), map_file.read_bytes()
        if _sha(raw) != EXE_SHA256 or _sha(map_raw) != MAP_SHA256:
            raise ValueError('Original Toolkit EXE/MAP hash mismatch')
        self.raw = raw
        self.pe = pefile.PE(data=raw, fast_load=True)
        if self.pe.FILE_HEADER.Machine != 0x14c:
            raise ValueError('Expected the pinned x86 Toolkit image')
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        sections = {index + 1: section for index, section in enumerate(self.pe.sections)}
        self.symbols: dict[int, list[str]] = {}
        self._by_name: dict[str, set[int]] = {}
        for line in map_raw.decode('ascii').splitlines():
            match = re.fullmatch(r'\s+000([1-4]):([0-9A-Fa-f]{8})\s+(\S+)\s*', line)
            if match:
                address = self.base + sections[int(match[1])].VirtualAddress + int(match[2], 16)
                names = self.symbols.setdefault(address, [])
                if match[3] not in names:
                    names.append(match[3])
                self._by_name.setdefault(match[3], set()).add(address)
        self.starts = sorted(self.symbols)
        self.decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        self.code = [section for section in self.pe.sections
                     if section.Name.rstrip(b'\0') in (b'.text', b'.itext')]

    def address(self, name: str) -> int:
        addresses = self._by_name.get(name, set())
        if len(addresses) != 1:
            raise ValueError('Missing or ambiguous MAP symbol: ' + name)
        return next(iter(addresses))

    def data(self, address: int, size: int) -> bytes:
        return self.pe.get_data(address - self.base, size)

    def u32(self, address: int) -> int:
        return struct.unpack('<I', self.data(address, 4))[0]

    def ustr(self, address: int) -> str:
        length = self.u32(address - 4)
        if not 0 < length < 256:
            raise ValueError(f'Unexpected UnicodeString literal at {address:#x}')
        return self.data(address, length * 2).decode('utf-16-le')

    def name(self, address: int) -> str:
        names = self.symbols.get(address)
        if not names:
            raise ValueError(f'No MAP symbol at {address:#x}')
        return names[0]

    def vmt(self, class_symbol: str) -> int:
        slot = self.address(class_symbol)
        vmt = self.u32(slot)
        if vmt + VMT_SELF != slot:
            raise ValueError('Class reference does not point at its VMT: ' + class_symbol)
        return vmt

    def class_name(self, vmt: int) -> str:
        pointer = self.u32(vmt + VMT_CLASS_NAME)
        return self.data(pointer + 1, self.data(pointer, 1)[0]).decode('ascii')

    def chain(self, class_symbol: str, stop: str) -> list[str]:
        vmt, names = self.vmt(class_symbol), []
        while True:
            names.append(self.class_name(vmt))
            if names[-1] == stop:
                return names
            parent = self.u32(vmt + VMT_PARENT)
            if not parent:
                raise ValueError('Class chain does not reach ' + stop)
            vmt = self.u32(parent)

    def slot(self, owner_class: str, method: str) -> int:
        vmt, target = self.vmt(owner_class), self.address(method)
        matches = [offset for offset in range(0, 0x800, 4) if self.u32(vmt + offset) == target]
        if len(matches) != 1:
            raise ValueError('Virtual slot is not unique for ' + method)
        return matches[0]

    def function(self, address: int, limit: int = 0x8000):
        end = next(start for start in self.starts if start > address)
        if not 0 < end - address <= limit:
            raise ValueError(f'Unbounded method at {address:#x}')
        raw = self.data(address, end - address)
        return raw, list(self.decoder.disasm(raw, address))

    def calls(self, target_name: str):
        target = self.address(target_name)
        for section in self.code:
            data, start = section.get_data(), self.base + section.VirtualAddress
            for match in re.finditer(rb'\xe8', data):
                offset = match.start()
                if offset + 5 <= len(data):
                    site = start + offset
                    if site + 5 + struct.unpack('<i', data[offset + 1:offset + 5])[0] == target:
                        yield site


def unit_registrations(image: Image) -> dict[str, dict]:
    # push min; push max; mov eax,[factory]; mov eax,[eax]; mov ecx,[class]; mov edx,name; call
    result: dict[str, dict] = {}
    for site in image.calls(REGISTER_UNIT_TYPE):
        prefix = image.data(site - 28, 28)
        match = re.fullmatch(rb'\x68(....)\x68(....)\xa1....\x8b\x00\x8b\x0d(....)\xba(....)', prefix, re.S)
        if match is None:
            continue
        low, high, class_ref, name = (struct.unpack('<I', group)[0] for group in match.groups())
        unit_type = image.ustr(name).upper()
        entry = {'class_symbol': image.name(class_ref), 'min_firmware': image.ustr(low),
                 'max_firmware': image.ustr(high), 'call_va': hex(site)}
        result.setdefault(unit_type, [])
        result[unit_type].append(entry)
    return result


def agent_registrations(image: Image) -> dict[str, list[str]]:
    # mov eax,[factory]; mov eax,[eax]; mov ecx,[agent]; mov edx,[unit class]; call
    result: dict[str, list[str]] = {}
    for site in image.calls(REGISTER_AGENT):
        match = re.fullmatch(rb'\xa1....\x8b\x00\x8b\x0d(....)\x8b\x15(....)', image.data(site - 19, 19), re.S)
        if match is None:
            continue
        agent, unit = (struct.unpack('<I', group)[0] for group in match.groups())
        result.setdefault(image.name(unit), []).append(image.name(agent))
    return result


def subset_name(image: Image, class_symbol: str, slot: int) -> tuple[str, str]:
    method = image.u32(image.vmt(class_symbol) + slot)
    _, instructions = image.function(method, 0x100)
    moves = [int(i.op_str.split(', ')[1], 16) for i in instructions
             if i.mnemonic == 'mov' and i.op_str.startswith('edx, 0x')]
    if len(moves) != 1:
        raise ValueError('Unexpected MacroFunctionSubsetName shape for ' + class_symbol)
    return image.name(method), image.ustr(moves[0])


def key_count(image: Image, class_symbol: str, slot: int) -> tuple[str, int]:
    method = image.u32(image.vmt(class_symbol) + slot)
    raw, _ = image.function(method, 0x40)
    constant = re.fullmatch(rb'\x55\x8b\xec\x83\xc4\xf8\x89\x45\xfc\xc7\x45\xf8(....)\x8b\x45\xf8\x59\x59\x5d\xc3.*', raw, re.S)
    zero = re.fullmatch(rb'\x55\x8b\xec\x83\xc4\xf8\x89\x45\xfc\x33\xc0\x89\x45\xf8\x8b\x45\xf8\x59\x59\x5d\xc3.*', raw, re.S)
    if constant:
        return image.name(method), struct.unpack('<I', constant[1])[0]
    if zero:
        return image.name(method), 0
    raise ValueError('Unexpected MaximumKeyCount shape for ' + class_symbol)


def subsets(image: Image) -> dict[str, dict[str, list[int]]]:
    start = image.address(SUBSET_FACTORY)
    _, instructions = image.function(start, 0x4000)
    register = image.address(REGISTER_SUBSET)
    stack: dict[int, int] = {}
    array = count = name = application = None
    result: dict[str, dict[str, list[int]]] = {}
    for instruction in instructions:
        mnemonic, operands = instruction.mnemonic, instruction.op_str
        byte = re.fullmatch(r'byte ptr \[ebp - (0x[0-9a-f]+|\d+)\], (0x[0-9a-f]+|\d+)', operands)
        if mnemonic == 'mov' and byte:
            stack[int(byte[1], 0)] = int(byte[2], 0)
        elif mnemonic == 'lea' and operands.startswith('eax, [ebp - '):
            array = int(operands.rsplit(' ', 1)[1].rstrip(']'), 0)
        elif mnemonic == 'push' and re.fullmatch(r'0x[0-9a-f]+|\d+', operands):
            count = int(operands, 0)
        elif mnemonic == 'mov' and operands.startswith('edx, 0x'):
            name = image.ustr(int(operands.split(', ')[1], 16))
        elif mnemonic == 'mov' and operands.startswith('ecx, '):
            application = int(operands.split(', ')[1], 0)
        elif mnemonic == 'xor' and operands == 'ecx, ecx':
            application = 0
        elif mnemonic == 'call' and operands == hex(register):
            values = [stack[array - index] for index in range(count + 1)]
            result.setdefault(name, {})[str(application)] = values
            array = count = application = None
    return result


def verify_bcnc4_forced_defaults(image: Image) -> dict:
    _, instructions = image.function(image.address(BCNC4_SAVE), 0x100)
    targets = [image.name(int(i.op_str, 16)) for i in instructions
               if i.mnemonic == 'call' and i.op_str.startswith('0x')]
    expected = ['CIS_TBCNC4CGateAgent.TBCNC4CGateAgent.CBusUnit', BCNC4_DEFAULTS,
                'CIS_TBCNC4CGateAgent.TBCNC4CGateAgent.CBusUnit', 'CIS_TBCNC.TBCNC4.ApplyLearnModeDefaults',
                'CIS_TKeyInputCGateAgent.TCBusKeyInputCGateAgent.BeforeSaveProgrammingInformation']
    if targets != expected:
        raise ValueError('TBCNC4CGateAgent save sequence changed')
    _, defaults = image.function(image.address(BCNC4_DEFAULTS), 0x400)
    writes = sum(1 for i in defaults if i.mnemonic == 'call' and i.op_str.startswith('0x')
                 and image.name(int(i.op_str, 16)) == 'CIS_TInputKey.TInputKey.SetMicroFunction')
    if writes != 16:
        raise ValueError('TBCNC4.ApplyMicroFunctionDefaults no longer writes all 16 stages')
    return {'method': BCNC4_SAVE, 'call_sequence': expected, 'forced_stage_writes': writes}


def verify_aux_override(image: Image) -> dict:
    # AUX keys set TKeyMacroFunction+0x8E; reconciliation then replaces template
    # types 0x1B and 7 (Bell Press) with 0x1C (Aux On/Off).
    _, instructions = image.function(image.address(AUX_RECONCILE), 0x400)
    text = [(i.mnemonic, i.op_str) for i in instructions]
    marker = ('cmp', 'byte ptr [eax + 0x8e], 0')
    if marker not in text:
        raise ValueError('AUX override check moved')
    tail = text[text.index(marker):]
    types = [int(operands.split(', ')[1], 0) for mnemonic, operands in tail[:20]
             if mnemonic == 'mov' and operands.startswith('dl, ')]
    if types[:3] != [0x1B, 7, 0x1C]:
        raise ValueError('AUX template reconciliation changed')
    return {'method': AUX_RECONCILE, 'override_field': '0x8e',
            'replaced_template_types': [0x1B, 7], 'replacement_template_type': 0x1C}


def _immediate(operand: str) -> int | None:
    return int(operand, 0) if re.fullmatch(r'0x[0-9a-f]+|\d+', operand) else None


def micro_function_types(image: Image) -> dict[int, int]:
    """Map micro-function FunctionType to the classic CBusValue it registers."""
    _, instructions = image.function(image.address(MICRO_FACTORY), 0x1000)
    register, pushes, edx, result = image.address(REGISTER_MICRO), [], None, {}
    for instruction in instructions:
        mnemonic, operands = instruction.mnemonic, instruction.op_str
        if mnemonic == 'push' and _immediate(operands) is not None:
            pushes.append(_immediate(operands))
        elif mnemonic == 'mov' and operands.startswith('edx, ') and _immediate(operands[5:]) is not None:
            edx = _immediate(operands[5:])
        elif mnemonic == 'xor' and operands == 'edx, edx':
            edx = 0
        elif mnemonic == 'call' and operands == hex(register):
            # push FunctionType; push new-device value; push family; EDX = CBusValue.
            result[pushes[-3]] = edx
            pushes, edx = [], None
    return result


def _stage_setters(image: Image) -> dict[str, int]:
    """Prove which group setter writes which JP/SR/LP/LR stage slot."""
    by_stage = {}
    _, instructions = image.function(image.address(GROUP_CLASS + 'GetMicroFunctionByStage'), 0x100)
    order = [int(i.op_str.split('+ ')[1].rstrip(']'), 0) for i in instructions
             if i.mnemonic == 'mov' and i.op_str.startswith('eax, dword ptr [eax + ')]
    # The switch tests stage 0, 1, 2, 3 and branches in that source order.
    for stage, offset in zip((0, 1, 2, 3), order):
        by_stage[offset] = stage
    # Sensor-command setters dispatch through a six-entry jump table.
    _, sensor = image.function(image.address(GROUP_CLASS + 'SetMicroFunctionBySensorCommand'), 0x200)
    table = next(int(i.op_str.split('+ ')[1].rstrip(']'), 0) for i in sensor
                 if i.mnemonic == 'jmp' and i.op_str.startswith('dword ptr [eax*4 + '))
    command_field = {}
    for command in range(6):
        target = image.u32(table + 4 * command)
        loads = [i for i in image.decoder.disasm(image.data(target, 0x20), target)]
        field_load = next(i for i in loads if i.op_str.startswith('eax, dword ptr [eax + '))
        command_field[command] = int(field_load.op_str.split('+ ')[1].rstrip(']'), 0)
    result = {}
    for name in ('SetJP', 'SetSR', 'SetLP', 'SetLR', 'SetMC', 'SetMT', 'SetOC', 'SetOT'):
        _, instructions = image.function(image.address(GROUP_CLASS + name), 0x40)
        selector = 0
        for i in instructions:
            if i.mnemonic == 'mov' and i.op_str.startswith('dl, '):
                selector = int(i.op_str[4:], 0)
        target = image.name(int(next(i.op_str for i in instructions if i.mnemonic == 'call'), 16))
        offset = command_field[selector] if target.endswith('BySensorCommand') else order[selector]
        result[name] = by_stage[offset]
    if [result[n] for n in ('SetJP', 'SetSR', 'SetLP', 'SetLR')] != [0, 1, 2, 3] or \
            [result[n] for n in ('SetMC', 'SetMT', 'SetOC', 'SetOT')] != [0, 1, 2, 3]:
        raise ValueError('Micro-function group stage setters changed')
    return result


def micro_function_groups(image: Image) -> dict[int, list[int]]:
    """Return the JP/SR/LP/LR FunctionTypes of every registered group."""
    _stage_setters(image)
    registers = image._by_name[REGISTER_GROUP]
    if len(registers) != 2:
        raise ValueError('Expected the two RegisterKeyMicroFunctionGroup overloads')
    _, instructions = image.function(image.address(GROUP_FACTORY), 0x4000)
    pushes, dl, result = [], None, {}
    for instruction in instructions:
        mnemonic, operands = instruction.mnemonic, instruction.op_str
        if mnemonic == 'push':
            pushes.append(_immediate(operands))
        elif mnemonic == 'mov' and operands.startswith('dl, '):
            dl = int(operands[4:], 0)
        elif mnemonic == 'call' and operands.startswith('0x') and int(operands, 16) in registers:
            # Arguments after the description are JP, SR, LP, LR (MC, MT, OC,
            # OT in the six-command overload), then VC and VT.
            stages = pushes[1:5]
            if dl in result or None in stages:
                raise ValueError('Unexpected micro-function group registration')
            result[dl] = stages
            pushes, dl = [], None
        elif mnemonic == 'call':
            pushes = []
    return result


def template_groups(image: Image) -> dict[int, list[int]]:
    """Return every template FunctionType's ordered micro-function groups."""
    _, instructions = image.function(image.address(TEMPLATE_FACTORY), 0x2000)
    register, stack, array, pushes, dl, result = image.address(REGISTER_TEMPLATE), {}, None, [], None, {}
    for instruction in instructions:
        mnemonic, operands = instruction.mnemonic, instruction.op_str
        byte = re.fullmatch(r'byte ptr \[ebp - (0x[0-9a-f]+|\d+)\], (0x[0-9a-f]+|\d+)', operands)
        if mnemonic == 'mov' and byte:
            stack[int(byte[1], 0)] = int(byte[2], 0)
        elif mnemonic == 'lea' and operands.startswith('eax, [ebp - '):
            array = int(operands.rsplit(' ', 1)[1].rstrip(']'), 0)
        elif mnemonic == 'push':
            pushes.append(_immediate(operands))
        elif mnemonic == 'mov' and operands.startswith('dl, '):
            dl = int(operands[4:], 0)
        elif mnemonic == 'xor' and operands == 'edx, edx':
            dl = 0
        elif mnemonic == 'call' and operands == hex(register):
            # push description; push open-array pointer; push high index.
            result[dl] = [stack[array - index] for index in range(pushes[-1] + 1)]
            pushes, dl = [], None
    return result


def verify_template_assignment(image: Image) -> dict:
    """Selecting a template assigns its first group (type 0x30 excepted)."""
    _, refresh = image.function(image.address(REFRESH_FROM_TYPE), 0x100)
    _, assign = image.function(image.address(ASSIGN_MICROFUNCTIONS), 0x100)
    _, default = image.function(image.address(TEMPLATE_DEFAULT), 0x100)
    called = lambda instructions: [image.name(int(i.op_str, 16)) for i in instructions
                                   if i.mnemonic == 'call' and i.op_str.startswith('0x')]
    if ASSIGN_MICROFUNCTIONS not in called(refresh) or TEMPLATE_DEFAULT not in called(assign):
        raise ValueError('Template selection no longer assigns the default group')
    text = [(i.mnemonic, i.op_str) for i in default]
    if ('cmp', 'al, 0x30') not in text or ('xor', 'edx, edx') not in text or \
            'CIS_TKeyMicroFunctionGroup.TKeyMicroFunctionGroupReferenceCollection.GetItem' not in called(default):
        raise ValueError('GetMicroFunctionGroupDefault changed')
    return {'selection_path': [REFRESH_FROM_TYPE, ASSIGN_MICROFUNCTIONS, TEMPLATE_DEFAULT],
            'default_group_index': 0, 'default_group_exception_template_type': 0x30}


def preset_micro_function_groups(image: Image) -> dict:
    types = micro_function_types(image)
    if any(types.get(value) != value for value in range(16)):
        raise ValueError('Classic FunctionTypes 0-15 no longer equal their CBusValues')
    groups, templates = micro_function_groups(image), template_groups(image)
    presets = {}
    for preset, template_type in PRESET_TEMPLATE_TYPES.items():
        choices = templates[template_type]
        # Dimmer's second group is the Memory variant, selectable in the dialog.
        index = 1 if preset == 'dimmer_memory' else 0
        group = choices[index]
        row = {'template_type': template_type, 'template_groups': choices,
               'group_index': index, 'group_type': group, 'stages': groups[group]}
        if preset in HELP_TABLE_VECTORS:
            row['help_table_stages'] = HELP_TABLE_VECTORS[preset]
        presets[preset] = row
    return {'stage_order': ['JPCommand', 'SRCommand', 'LPCommand', 'LRCommand'],
            'classic_function_types_equal_cbus_values': list(range(16)),
            'template_assignment': verify_template_assignment(image),
            'presets': presets}


def inspect(spec_dir: Path, exe: Path, map_file: Path, catalog_path: Path) -> dict:
    image = Image(exe, map_file)
    store = UnitSpecStore(spec_dir)
    catalog = UnitCatalog.load(catalog_path)
    registrations = unit_registrations(image)
    agents = agent_registrations(image)
    subset_slot = image.slot(*SUBSET_SLOT_OWNER)
    count_slot = image.slot(*KEY_COUNT_SLOT_OWNER)
    subset_table = subsets(image)
    lighting_types = sorted({value for value in PRESET_TEMPLATE_TYPES.values()})
    families = {}
    used_subsets: set[str] = set()
    hashes: dict[str, str] = {}
    for family, reference, workflow, candidates, accepted_agents, already in (
            ('classic', CLASSIC_REFERENCE, CLASSIC_WORKFLOW, CLASSIC_CANDIDATES,
             (CLASSIC_ACCEPTED_AGENT,), CLASSIC_ALREADY),
            ('neo', NEO_REFERENCE, NEO_WORKFLOW, NEO_CANDIDATES, NEO_ACCEPTED_AGENTS, NEO_ALREADY)):
        base = store.load(reference)
        base_layout = {name: _layout(parameter) for name, parameter in base.parameters.items()}
        rows = []
        for filename in candidates:
            spec = store.load(filename)
            for source in spec.sources:
                hashes[source] = _sha((spec_dir / source).read_bytes())
            layout = {name: _layout(parameter) for name, parameter in spec.parameters.items()}
            names = sorted(set(layout) | set(base_layout))
            differing = [name for name in names if layout.get(name) != base_layout.get(name)]
            defaults = sorted(name for name in names if name not in differing and
                              spec.parameters[name].fields.get('DefaultValue') != base.parameters[name].fields.get('DefaultValue'))
            unit_type = spec.unit_type
            generation = '_A' if filename.endswith('_A.xml') else ''
            matches = [entry for entry in registrations.get(unit_type.upper(), [])
                       if entry['class_symbol'].endswith('_A') == bool(generation)]
            row = {'spec_filename': filename, 'unit_type': unit_type,
                   'spec_sources': list(spec.sources),
                   'min_version': spec.metadata.get('MinVersion', ''),
                   'parameter_layout_sha256': _digest(layout),
                   'workflow_layout_sha256': _digest({name: layout.get(name) for name in workflow}),
                   'workflow_layout_matches_reference': all(layout.get(name) == base_layout.get(name) for name in workflow),
                   'differing_layout_parameters': differing,
                   'default_only_differences': defaults,
                   'guarded_parameters': [name for name in differing if name in layout],
                   'already_supported': unit_type in already and not generation}
            reasons = []
            if not row['workflow_layout_matches_reference']:
                reasons.append('preset parameter layout differs from ' + reference)
            if set(row['guarded_parameters']) & set(workflow):
                reasons.append('a differing parameter belongs to the preset workflow')
            if len(matches) != 1:
                reasons.append('no unique Toolkit RegisterUnitType registration')
            else:
                registration = matches[0]
                class_symbol = registration['class_symbol']
                agent_list = agents.get(class_symbol, [])
                agent_chain = image.chain(agent_list[0], 'TCBusUnitCGateAgent') if len(agent_list) == 1 else []
                subset_method, subset = subset_name(image, class_symbol, subset_slot)
                count_method, maximum = key_count(image, class_symbol, count_slot)
                allowed = subset_table.get(subset, {})
                row.update({
                    'toolkit_registration': registration,
                    'toolkit_class_chain': image.chain(class_symbol, 'TCBusInputUnit'),
                    'toolkit_agent_class': agent_chain[0] if agent_chain else None,
                    'toolkit_agent_chain': agent_chain,
                    'macro_function_subset': subset,
                    'macro_function_subset_method': subset_method,
                    'maximum_key_count': maximum,
                    'maximum_key_count_method': count_method,
                    'subset_preset_template_types': {
                        application: sorted(set(allowed.get(application, [])) & set(lighting_types))
                        for application in ('0', '202')},
                })
                if row['toolkit_agent_class'] == 'TBCNC4CGateAgent':
                    reasons.append('Toolkit TBCNC4CGateAgent forces ApplyMicroFunctionDefaults before every save')
                elif row['toolkit_agent_class'] not in accepted_agents:
                    reasons.append('Toolkit C-Gate agent differs from the accepted save path')
                if maximum < 1:
                    reasons.append('Toolkit MaximumKeyCount is zero')
                firmware = TESTED_FIRMWARE[family]
                records = catalog.match(unit_type=unit_type, firmware=firmware)
                selected = sorted({record['spec_filename'] for record in records})
                row['catalog_selection'] = {
                    'firmware': firmware, 'spec_filenames': selected,
                    'catalog_numbers': sorted({record['catalog_number'] for record in records})}
                if selected != [filename]:
                    reasons.append('catalogue does not select this specification at firmware ' + firmware)
                if not version_matches(firmware, registration['min_firmware'], registration['max_firmware']):
                    reasons.append('tested firmware is outside the Toolkit class registration')
                missing = sorted(preset for preset, kind in PRESET_TEMPLATE_TYPES.items()
                                 if kind not in allowed.get('0', []) and kind not in allowed.get('202', []))
                row['subset_excluded_presets'] = missing
            row['decision'] = 'refused' if reasons else 'admitted'
            row['refusal_reasons'] = reasons
            rows.append(row)
        used_subsets.update(row.get('macro_function_subset') for row in rows if row.get('macro_function_subset'))
        families[family] = {'reference_spec': reference, 'workflow_parameters': list(workflow),
                            'accepted_agents': list(accepted_agents), 'types': rows}
    return {
        'format': FORMAT,
        'original_exe_sha256': EXE_SHA256,
        'original_map_sha256': MAP_SHA256,
        'original_code_executed': False,
        'spec_sha256': dict(sorted(hashes.items())),
        'virtual_slots': {'MacroFunctionSubsetName': hex(subset_slot), 'MaximumKeyCount': hex(count_slot)},
        'preset_template_types': PRESET_TEMPLATE_TYPES,
        'preset_micro_function_groups': preset_micro_function_groups(image),
        'catalog_sha256': _sha(catalog_path.read_bytes()),
        'macro_function_subsets': {name: subset_table[name] for name in sorted(used_subsets)},
        'bcnc4_forced_defaults': verify_bcnc4_forced_defaults(image),
        'aux_template_override': verify_aux_override(image),
        'families': families,
        'limits': ('Static specification and executable evidence only. It does not execute Toolkit, '
                   'establish GUI rendering, physical key behavior or every firmware revision. '
                   'Native preset acceptance is recorded separately.'),
    }


def render(receipt: dict) -> str:
    text = json.dumps(receipt, indent=2) + '\n'
    # Keep scalar lists on one line so the receipt stays reviewable.
    return re.sub(r'\[\s*((?:(?:-?\d+|"[^"\n]*")\s*,\s*)*(?:-?\d+|"[^"\n]*"))\s*\]',
                  lambda match: '[' + re.sub(r'\s*,\s*', ', ', match[1]) + ']', text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unitspec-dir', type=Path, required=True)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, required=True, help='C-Gate unitspec/cbusunits.xml')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = render(inspect(args.unitspec_dir, args.exe, args.map, args.catalog))
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    else:
        sys.stdout.write(text)


if __name__ == '__main__':
    main()
