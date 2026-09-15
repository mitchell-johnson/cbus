"""Held original predicate pilot; fixtures supply stable group and level facts."""
from pathlib import Path
import hashlib
import json
import os
import stat
import struct
import sys
import time
import capstone
import pefile
import unicorn
import unicorn.unicorn_py3.arch.intel
from unicorn.x86_const import UC_X86_REG_EAX as EAX, UC_X86_REG_EDX as EDX, UC_X86_REG_ECX as ECX, UC_X86_REG_ESP as ESP, UC_X86_REG_EIP as EIP

TOKEN = 'root-reviewed-thermostat-selection12-v1'
EXE_SHA = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
SPANS = (
    ('GroupsSelected', 0x11301ec, 0x113028c),
    ('LevelsRequired', 0xfed2d4, 0xfed3c3),
    ('ZoneLevelsExist', 0xfda7a4, 0xfda7ff),
    ('IsUnused', 0xf27e14, 0xf27e35),
)
PROVIDERS = {0xfea78c: 'service', 0xfdffd4: 'enabled', 0xfe0040: 'on',
             0xfe001c: 'off', 0xfdfff8: 'override', 0xf47a10: 'address', 0xf2742c: 'find'}
sha = lambda raw: hashlib.sha256(raw).hexdigest()

def check(condition, message):
    if not condition: raise RuntimeError(message)

def read(path, limit):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    first = None
    try:
        info = os.fstat(descriptor)
        check(stat.S_ISREG(info.st_mode) and info.st_size <= limit, 'Bounded regular input required')
        chunks = []; size = 0
        while True:
            chunk = os.read(descriptor, min(65536, limit + 1 - size))
            if not chunk: break
            size += len(chunk); check(size <= limit, 'Input grew beyond bound'); chunks.append(chunk)
        return b''.join(chunks)
    except BaseException as error: first = error; raise
    finally:
        try: os.close(descriptor)
        except BaseException:
            if first is None: raise

def error_data(error):
    try: message = str(error)
    except BaseException: message = '<unprintable>'
    return {'type': type(error).__name__, 'message': message[:2048]}

def runtime_evidence():
    from unicorn.unicorn_py3 import unicorn as uc_core
    libraries = {str(Path(p).resolve()): sha(read(Path(p).resolve(), 64 * 1024 * 1024))
                 for p in (capstone._cs._name, uc_core.uclib._name)}
    modules = {}
    for name, module in tuple(sys.modules.items()):
        if name == 'pefile' or name == 'capstone' or name.startswith('capstone.') or name == 'unicorn' or name.startswith('unicorn.'):
            path = Path(module.__file__).resolve()
            modules[name] = {'path': str(path), 'sha256': sha(read(path, 4 * 1024 * 1024))}
    executable = Path(sys.executable).resolve()
    return {'python': sys.version, 'executable': str(executable), 'executable_sha256': sha(read(executable, 64 * 1024 * 1024)), 'libraries': libraries, 'loaded_python_modules': modules}

class Image:
    def __init__(self, raw):
        check(sha(raw) == EXE_SHA, 'Original executable hash')
        pe = pefile.PE(data=raw); self.base = pe.OPTIONAL_HEADER.ImageBase
        check(self.base == 0x600000 and pe.FILE_HEADER.Machine == 0x14c, 'Original image architecture')
        self.mapped = pe.get_memory_mapped_image(); self.instructions = {}; self.callsites = {}; self.spans = []
        decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        for name, begin, end in SPANS:
            code = pe.get_data(begin - self.base, end - begin)
            decoded = list(decoder.disasm(code, begin))
            check(decoded and decoded[-1].address + decoded[-1].size == end and decoded[-1].mnemonic == 'ret', 'Whole original method extent')
            for item in decoded:
                check(item.mnemonic not in ('int', 'syscall', 'sysenter', 'in', 'out'), 'Privileged instruction')
                self.instructions[item.address] = (name, bytes(item.bytes))
                if item.mnemonic == 'call' and item.op_str.startswith('0x'):
                    target = int(item.op_str, 16)
                    self.callsites.setdefault(target, set()).add(item.address + item.size)
            self.spans.append({'name': name, 'begin': hex(begin), 'end': hex(end), 'sha256': sha(code)})

class Machine:
    def __init__(self, image, case):
        self.image = image; self.case = case
        self.u = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        size = (len(image.mapped) + 4095) & ~4095
        self.u.mem_map(image.base, size); self.u.mem_write(image.base, image.mapped)
        self.u.mem_protect(image.base, size, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        self.u.mem_map(0x10000000, 0x40000); self.u.mem_map(0x20000000, 0x10000)
        self.u.mem_map(0x30000000, 0x1000, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        self.form = 0x10000000; self.unit = 0x10001000; self.service = 0x10002000
        self.put(self.form + 0xc, self.unit)
        self.objects = {}; self.managers = {}; self.roles = {}; self.events = []; self.executed = {}; self.count = 0
        for i, (role, group) in enumerate(case['groups'].items()):
            obj = 0x10010000 + i * 0x1000; manager = obj + 0x200
            self.roles[role] = obj if group is not None else 0
            if group is not None:
                self.objects[obj] = role; self.managers[manager] = role; self.put(obj + 0xd0, manager)
        self.u.hook_add(unicorn.UC_HOOK_CODE, self.hook)
        self.u.hook_add(unicorn.UC_HOOK_MEM_WRITE, self.write_guard)

    def get(self, address): return struct.unpack('<I', self.u.mem_read(address, 4))[0]
    def put(self, address, value): self.u.mem_write(address, struct.pack('<I', value))
    def event(self, **data):
        check(len(self.events) < 2000, 'Provider event bound'); self.events.append(data)

    def write_guard(self, uc, access, address, size, value, data):
        check(0x20000000 <= address and address + size <= 0x20010000, 'Original writes limited to owned stack')

    def hook(self, uc, address, size, data):
        self.count += 1; check(self.count <= 100000, 'Original instruction bound')
        if address not in PROVIDERS:
            item = self.image.instructions.get(address); check(item is not None, 'Unapproved instruction ' + hex(address))
            name, raw = item; check(bytes(uc.mem_read(address, len(raw))) == raw, 'Original code changed')
            self.executed[name] = self.executed.get(name, 0) + 1
            return
        eax, edx, ecx, esp = (uc.reg_read(r) for r in (EAX, EDX, ECX, ESP))
        check(self.get(esp) in self.image.callsites[address], 'Provider callsite identity')
        name = PROVIDERS[address]; pop = 0
        if name == 'service':
            check(eax == self.unit, 'Service owner'); result = self.service
        elif name == 'enabled':
            check(eax == self.service, 'Enable owner'); result = int(self.case['enabled'])
            self.event(event='enabled', value=self.case['enabled'])
        elif name in self.roles:
            check(eax == self.service, 'Group getter owner'); result = self.roles[name]
            self.event(event='group', role=name, present=result != 0)
        elif name == 'address':
            check(eax in self.objects, 'Address owner'); role = self.objects[eax]
            result = self.case['groups'][role]['address']; self.event(event='address', role=role, value=result)
        elif name == 'find':
            check(eax in self.managers and 1 <= edx <= 31 and ecx & 255 == 0 and self.get(esp + 4) == 0, 'Find argument domain')
            role = self.managers[eax]; found = edx in self.case['groups'][role]['level_addresses']
            result = 0x10030000 + edx * 16 if found else 0; pop = 4
            self.event(event='find', role=role, address=edx, create=False, found=found)
        else: raise RuntimeError('Unknown provider')
        uc.reg_write(EAX, result); uc.reg_write(EIP, self.get(esp)); uc.reg_write(ESP, esp + 4 + pop)

    def call(self, required):
        self.put(0x20008000, 0x30000000)
        self.u.reg_write(ESP, 0x20008000); self.u.reg_write(EAX, self.unit if required else self.form)
        self.u.emu_start(0xfed2d4 if required else 0x11301ec, 0x30000000, timeout=2000000, count=100000)
        check(self.u.reg_read(EIP) == 0x30000000 and self.u.reg_read(ESP) == 0x20008004, 'Original return/stack balance')
        value = self.u.reg_read(EAX) & 255; check(value in (0, 1), 'Boolean return domain')
        return {'value': bool(value), 'semantic_events': self.events}

def main():
    check(len(sys.argv) == 6 and sys.argv[1] in ('prepare', TOKEN), 'Held explicit mode')
    check(sys.platform == 'darwin' and sys.version_info[:2] in ((3, 10), (3, 13)), 'Supported research runtime')
    mode, case_path, output, exe_path, expected_case_sha = sys.argv[1:]
    out = Path(output); check(out.parent.resolve(strict=True) == Path(__file__).resolve().parent and not out.exists() and not out.is_symlink(), 'Fresh direct output')
    paths = (Path(__file__).resolve(), Path(case_path), Path(exe_path))
    raw = {str(p): read(p, 64 * 1024 * 1024 if p == paths[2] else 256 * 1024) for p in paths}
    check(sha(raw[str(paths[1])]) == expected_case_sha, 'Prewritten case input hash')
    cases = json.loads(raw[str(paths[1])]); check(type(cases) is list and len(cases) == 12, 'Exactly twelve cases')
    image = Image(raw[str(paths[2])]); out.mkdir()
    report = {'format': 'thermostat-original-selection-v1', 'passed': False, 'invocation_requested': mode != 'prepare', 'original_executed': False, 'inputs_before': {p: sha(v) for p, v in raw.items()}, 'spans': image.spans, 'results': [], 'scope': 'Original predicates with supplied stable group/address/level providers; no UI or original constructors/database'}
    first = None; started = time.monotonic()
    try:
        report['runtime_before'] = runtime_evidence()
        if mode != 'prepare':
            for case in cases:
                check(time.monotonic() - started < 20, 'Whole probe time bound')
                row = {'id': case['id'], 'arms': {}}; report['results'].append(row)
                for label in ('selected', 'required'):
                    machine = Machine(image, case); arm = {'completed': False}; row['arms'][label] = arm
                    try:
                        result = machine.call(label == 'required'); arm['result'] = result
                        check(result == case['expected'][label], 'Prewritten predicate/result order mismatch')
                        arm['completed'] = True
                    finally:
                        arm['events'] = machine.events; arm['executed_original'] = machine.executed; arm['instructions'] = machine.count
        report['passed'] = True
    except BaseException as error: first = error; report['error'] = error_data(error)
    finally:
        report['original_executed'] = any(sum(arm.get('executed_original', {}).values()) > 0 for row in report['results'] for arm in row['arms'].values())
        report['inputs_after'] = {}; report['secondary_errors'] = []
        for path, value in raw.items():
            try:
                observed = sha(read(path, 64 * 1024 * 1024)); report['inputs_after'][path] = observed
                check(observed == sha(value), 'Source changed')
            except BaseException as error:
                if first is None: first = error
                else: report['secondary_errors'].append(error_data(error))
        try:
            report['runtime_after'] = runtime_evidence()
            check(report['runtime_before'] == report['runtime_after'], 'Actual runtime changed')
        except BaseException as error:
            if first is None: first = error
            else: report['secondary_errors'].append(error_data(error))
        report['passed'] = report['passed'] and first is None
        stream = None
        try:
            data = (json.dumps(report, indent=2) + '\n').encode(); check(len(data) <= 4 * 1024 * 1024, 'Report bound')
            stream = (out / 'report.json').open('xb'); stream.write(data)
        except BaseException as error:
            if first is None: first = error
        finally:
            if stream is not None:
                try: stream.close()
                except BaseException as error:
                    if first is None: first = error
    if first is not None: raise first
    print(json.dumps({'passed': True, 'original_executed': report['original_executed'], 'report': str(out / 'report.json')}))

if __name__ == '__main__': main()
