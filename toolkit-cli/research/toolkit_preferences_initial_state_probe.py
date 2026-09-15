"""Bounded original Toolkit preference constructor/registration observation.

Requires the pinned original executable and research-only pefile/unicorn packages.
The original constructor/type bodies execute on preallocated fixture objects;
allocation and AfterConstruction branches are skipped. Original InitInstance is
independently executed over poisoned memory for each actual class. Heap, managed
strings, resources and collection insertion are explicit fixtures. Only selected
registration routines execute; no manager constructor, other module initializer,
registry call, UI startup or network operation is run.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys

EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
DISPLAY_FIELDS = (
    ('tag_hex', 0x144df1c), ('tag_override', 0x144df24),
    ('sort_applications', 0x144df25), ('sort_groups', 0x144df26),
    ('sort_levels', 0x144df27),
)
_ALLOWED = (
    (0x85211c, 0x8527c2), (0x136afb8, 0x136b178),
    (0x136b1bc, 0x136babb), (0x1379b18, 0x1379c4c),
    (0x6061d0, 0x6061f0), (0x60620c, 0x606262),
    (0x606488, 0x6064ce), (0x619800, 0x6198c9),
    (0x85b67c, 0x85b6a3),
)
_HOOKS = {0x85211c, 0x608924, 0x608978, 0x608914, 0x60891c,
          0x60890c, 0x608a50, 0x618f9c, 0x60c470, 0x76855c}


def probe_constructor_state(executable):
    data = Path(executable).read_bytes()
    if hashlib.sha256(data).hexdigest() != EXE_SHA256:
        raise ValueError('The exact Toolkit 1.18.0.2754 executable is required')
    import pefile
    import unicorn
    from unicorn.x86_const import (
        UC_X86_REG_EAX as EAX, UC_X86_REG_EDX as EDX,
        UC_X86_REG_ECX as ECX, UC_X86_REG_ESP as ESP, UC_X86_REG_EIP as EIP,
    )
    pe = pefile.PE(data=data)
    base = pe.OPTIONAL_HEADER.ImageBase
    image = pe.get_memory_mapped_image()
    def original_integer(address):
        return struct.unpack('<I', pe.get_data(address-base, 4))[0]
    classes = {original_integer(slot):kind for slot,kind in
               ((0x851804,'boolean'),(0x8518c4,'string'),(0x85198c,'integer'))}
    resources = {}
    for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if kind.id != 6: continue
        for block in kind.directory.entries:
            for language in block.directory.entries:
                entry=language.data.struct;raw=pe.get_data(entry.OffsetToData, entry.Size);pos=0
                for index in range(16):
                    count=struct.unpack_from('<H',raw,pos)[0];pos+=2
                    text=raw[pos:pos+count*2].decode('utf-16-le');pos+=count*2
                    resources.setdefault((block.id-1)*16+index,set()).add(text)
                assert pos==len(raw) or (len(raw)==((pos+3)&~3) and not any(raw[pos:]))

    class Machine:
        def __init__(self):
            self.u=unicorn.Uc(unicorn.UC_ARCH_X86,unicorn.UC_MODE_32)
            self.u.mem_map(base,(len(image)+4095)&~4095);self.u.mem_write(base,image)
            for address,size in ((0,4096),(0x10000000,0x400000),(0x20000000,0x40000),(0x30000000,4096)):
                self.u.mem_map(address,size)
            self.heap=0x10000000;self.items=[];self.created=[];self.constructors=[];self.registrations=[];self.type_initializers=[]
            self.manager=self.alloc(0x100);self.put(original_integer(0x13c36f8),self.manager)
            self.phase='';self.u.hook_add(unicorn.UC_HOOK_CODE,self.hook)
        def alloc(self,size):
            address=self.heap;self.heap=(address+size+7)&~7
            assert self.heap<=0x10400000
            return address
        def get(self,address): return struct.unpack('<I',self.u.mem_read(address,4))[0]
        def put(self,address,value): self.u.mem_write(address,struct.pack('<I',value&0xffffffff))
        def text(self,value):
            if not value: return 0
            raw=value.encode('utf-16-le');address=self.alloc(len(raw)+14)
            self.u.mem_write(address,struct.pack('<HHII',1200,2,0xffffffff,len(raw)//2)+raw+b'\0\0')
            return address+12
        def read(self,address):
            if not address:return ''
            size=self.get(address-4);assert size<=4096
            return bytes(self.u.mem_read(address,size*2)).decode('utf-16-le')
        def fields(self,obj):
            kind=classes[self.get(obj)]
            value=(bool(self.u.mem_read(obj+26,1)[0]) if kind=='boolean' else
                self.read(self.get(obj+24)) if kind=='string' else
                struct.unpack('<i',self.u.mem_read(obj+32,4))[0])
            return {'name':self.read(self.get(obj+12) or self.get(obj+4)), 'kind':kind,'value':value,
                'class_vmt':hex(self.get(obj)), 'boolean_default':bool(self.u.mem_read(obj+25,1)[0]) if kind=='boolean' else None,
                'machine_first':bool(self.u.mem_read(obj+20,1)[0]),'skip_save':bool(self.u.mem_read(obj+21,1)[0]),
                'alternate_key':bool(self.u.mem_read(obj+22,1)[0])}
        def hook(self,u,address,size,user):
            eax,edx,ecx,esp=(u.reg_read(reg) for reg in (EAX,EDX,ECX,ESP))
            if address==0x852174:self.constructors.append(self.fields(eax))
            if address in (0x85254c,0x852580,0x852664):self.type_initializers.append(hex(address))
            if address not in _HOOKS:
                assert any(start<=address<end for start,end in _ALLOWED),('unhandled original code',hex(address),self.phase)
                return
            if address==0x85211c:
                if edx&255:
                    assert eax in classes
                    obj=self.alloc(0x100);self.put(obj,eax);self.created.append(obj)
                    u.reg_write(EAX,obj);u.reg_write(EDX,edx&~255)
                return
            if address==0x76855c:
                assert eax==self.manager and edx in self.created
                self.registrations.append(self.fields(edx));self.items.append(edx)
            elif address==0x60c470:
                options=resources[self.get(eax+4)];assert len(options)==1
                self.put(edx,self.text(next(iter(options))))
            elif address in (0x608924,0x608978):self.put(eax,self.text(self.read(edx)))
            elif address==0x608914:self.put(eax,0)
            elif address==0x60891c:
                assert edx<=4096
                for index in range(edx):self.put(eax+4*index,0)
            elif address==0x60890c:pass
            elif address==0x618f9c:self.put(edx,self.text(self.read(eax).strip()))
            elif address==0x608a50:
                assert ecx<=4096
                self.put(eax,self.text(bytes(u.mem_read(edx,ecx)).decode('ascii')))
            else:raise AssertionError(hex(address))
            u.reg_write(EIP,self.get(esp));u.reg_write(ESP,esp+4)
        def call(self,address,phase,eax=0,edx=0,end=0x30000000):
            self.phase=phase;self.put(0,0);self.put(0x20030000,0x30000000)
            for reg,value in ((ESP,0x20030000),(EAX,eax),(EDX,edx),(ECX,0)):
                self.u.reg_write(reg,value)
            self.u.emu_start(address,end,timeout=3000000,count=300000)
            assert self.u.reg_read(EIP)==end,('incomplete original execution',hex(self.u.reg_read(EIP)))

    machine=Machine()
    table=original_integer(0x1342774);count=original_integer(0x1342770)
    assert count==2091 and table==0x1342788
    targets={0x1379b18:'kipper',0x136b1bc:'global',0x136afb8:'languages'}
    order=[{'ordinal':index,'address':hex(original_integer(table+8*index)),
            'phase':targets[original_integer(table+8*index)]}
           for index in range(count) if original_integer(table+8*index) in targets]
    assert [row['ordinal'] for row in order]==[388,614,682]
    for row in order:machine.call(int(row['address'],16),row['phase'])
    assert len(machine.items)==len(machine.created)==len(machine.constructors)==len(machine.type_initializers)==40
    preferences=[machine.fields(obj) for obj in machine.items]
    assert preferences==machine.registrations
    zero_proofs=[]
    for cls in classes:
        probe=Machine();size=probe.get(cls-0x34);assert 24<=size<=256
        obj=probe.alloc(size+16);probe.u.mem_write(obj,b'\xa5'*(size+16))
        probe.call(0x60620c,'original-InitInstance',eax=cls,edx=obj)
        raw=bytes(probe.u.mem_read(obj,size+16))
        assert probe.get(obj)==cls and raw[4:size]==bytes(size-4) and raw[size:]==b'\xa5'*16 and probe.u.reg_read(EAX)==obj
        zero_proofs.append({'kind':classes[cls],'class_vmt':hex(cls),'instance_size':size,'after_hex':raw.hex(),'guard_tail_unchanged':True})
    display=Machine();bss={}
    for name,address in DISPLAY_FIELDS:
        section=pe.get_section_by_rva(address-base)
        assert section.Name.rstrip(b'\0')==b'.bss' and section.SizeOfRawData==0
        bss[name]=display.u.mem_read(address,1)[0];display.u.mem_write(address,b'\x7f')
    display.call(0x85b67c,'display-reset-before-registry',end=0x85b6a3)
    fallback={name:bool(display.u.mem_read(address,1)[0]) for name,address in DISPLAY_FIELDS}
    assert set(bss.values())=={0} and set(fallback.values())=={False}
    return {'format':'cbus-original-preference-initial-state-probe-v1','passed':True,
        'state':{'format':'cbus-toolkit-preferences-state-v1','values':{row['name']:row['value'] for row in preferences},'display_values':fallback},
        'preferences':preferences,'constructor_returns':machine.constructors,'type_initializer_calls':machine.type_initializers,
        'registration_order':order,'zero_layout_proofs':zero_proofs,'display_initial_bss':bss,
        'display_reset_prefix_executed':True,'registry_calls':0,'network_calls':0,
        'constructor_preallocated_fixture':True,'constructor_allocation_branch_executed':False,
        'constructor_AfterConstruction_branch_executed':False,'manager_constructor_executed':False,
        'other_unit_initializers_executed':False,'whole_application_startup_verified':False,'installer_defaults_verified':False,
        'original_executable_sha256':EXE_SHA256,'probe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'python':sys.version,'pefile_version':pefile.__version__,'unicorn_version':unicorn.__version__}


if __name__=='__main__':
    result=probe_constructor_state(sys.argv[1])
    with Path(sys.argv[2]).open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'passed':result['passed'],'preferences':len(result['preferences']),'report':sys.argv[2]}))
