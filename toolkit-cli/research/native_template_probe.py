"""Execute the original Toolkit checksum routine using an x86 CPU emulator.

The unmodified routine at CIS_Maths.CalculateCRC has no external calls. The
harness supplies only input memory, registers and a return address. Requires
local original Toolkit EXE plus developer-only pefile/unicorn packages.
"""
import argparse
import json
import struct
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=2)
def _image(executable):
    import pefile
    pe = pefile.PE(str(executable))
    return pe.OPTIONAL_HEADER.ImageBase, pe.get_memory_mapped_image()


def native_crc(executable, payload, *, high_argument=None):
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ESP, UC_X86_REG_EIP
    if len(payload) > 65536:
        raise ValueError('Toolkit checksum buffer is bounded at 65536 bytes')
    base, image = _image(str(executable))
    emulator = Uc(UC_ARCH_X86, UC_MODE_32)
    emulator.mem_map(base, (len(image)+4095)&~4095)
    emulator.mem_write(base, image)
    emulator.mem_map(0x10000000,0x20000)
    emulator.mem_map(0x20000000,0x40000)
    emulator.mem_map(0x30000000,4096)
    emulator.mem_write(0x10000000,payload+b'\0'*4)
    stack=0x20030000
    emulator.mem_write(stack,struct.pack('<I',0x30000000))
    emulator.reg_write(UC_X86_REG_EAX,0x10000000)
    emulator.reg_write(UC_X86_REG_EDX,(len(payload)-1 if high_argument is None else high_argument)&0xffffffff)
    emulator.reg_write(UC_X86_REG_ESP,stack)
    emulator.emu_start(0x7F1FDC,0x30000000,timeout=3000000,count=20000000)
    if emulator.reg_read(UC_X86_REG_EIP) != 0x30000000:
        raise RuntimeError('Original checksum routine did not return within its execution budget')
    return emulator.reg_read(UC_X86_REG_EAX)&65535


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps({'function':'CIS_Maths.CalculateCRC','virtual_address':'0x7F1FDC',
                      'argument':'DynArrayHigh(payload), exactly as CalcTemplateCRC calls it',
                      'vectors':[{'hex':value.hex(),'crc':native_crc(args.exe,value)}
                                 for value in (b'',b'a',b'ab',b'123456789',bytes(range(256)))]},indent=2))


def native_read_attribute(executable, document, name):
    """Run original LoadTemplate's line parser with isolated text-I/O services.

    Runtime hooks implement Delphi string primitives and in-memory text-file
    reads. The unmodified GetAttributeValue controls tag search, positions,
    termination and extraction. No Toolkit GUI or operating-system I/O runs.
    """
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_ESP, UC_X86_REG_EIP
    base,image=_image(str(executable))
    u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(base,(len(image)+4095)&~4095);u.mem_write(base,image)
    for start,size in ((0,4096),(0x10000000,0x400000),(0x20000000,0x40000),(0x30000000,4096)):u.mem_map(start,size)
    heap=0x10000000
    def integer(address):return struct.unpack('<I',u.mem_read(address,4))[0]
    def writeint(address,value):u.mem_write(address,struct.pack('<I',value&0xffffffff))
    def allocate(value):
        nonlocal heap
        encoded=value.encode('utf-16le');pointer=heap+12
        u.mem_write(heap,struct.pack('<HHII',1200,2,0xffffffff,len(encoded)//2)+encoded+b'\0\0')
        heap=(pointer+len(encoded)+7)&~3
        return pointer
    def string(pointer):
        if not pointer:return ''
        return bytes(u.mem_read(pointer,integer(pointer-4)*2)).decode('utf-16le')
    def assign(destination,value):writeint(destination,allocate(value))
    lines=document.splitlines();cursor=0
    runtimes={0x60890C,0x608914,0x60891C,0x61B6E8,0x604F78,0x604A98,0x609384,0x605788,0x6094D4,0x609114,0x60550C}
    def hook(emulator,address,size,user_data):
        nonlocal cursor
        if address not in runtimes:return
        eax=u.reg_read(UC_X86_REG_EAX);edx=u.reg_read(UC_X86_REG_EDX);ecx=u.reg_read(UC_X86_REG_ECX);esp=u.reg_read(UC_X86_REG_ESP)
        pop=0
        if address==0x61B6E8:
            destination=integer(esp+4);assign(destination,string(eax).replace('%s',string(integer(edx))));pop=4
        elif address==0x604F78:cursor=0
        elif address==0x609384:assign(edx,lines[cursor]if cursor<len(lines)else'')
        elif address==0x605788:cursor+=1
        elif address==0x6094D4:u.reg_write(UC_X86_REG_EAX,string(edx).find(string(eax))+1)
        elif address==0x609114:
            destination=integer(esp+4);assign(destination,string(eax)[max(edx-1,0):max(edx-1,0)+ecx]);pop=4
        elif address==0x60550C:u.reg_write(UC_X86_REG_EAX,int(cursor>=len(lines)))
        u.reg_write(UC_X86_REG_EIP,integer(esp));u.reg_write(UC_X86_REG_ESP,esp+4+pop)
    u.hook_add(UC_HOOK_CODE,hook)
    stack=0x20030000;output=0x20020000;parent=0x20018000
    writeint(stack,0x30000000);writeint(stack+4,parent)
    u.reg_write(UC_X86_REG_EAX,allocate(name));u.reg_write(UC_X86_REG_EDX,output);u.reg_write(UC_X86_REG_ESP,stack)
    u.emu_start(0xCC4DE8,0x30000000,timeout=3000000,count=200000)
    if u.reg_read(UC_X86_REG_EIP) != 0x30000000:
        raise RuntimeError('Original attribute reader did not return within its execution budget')
    return string(integer(output))


def native_xml_text(executable, value, *, decode=False):
    """Execute original XML encoder/decoder with isolated Delphi primitives.

    The encoder's character decisions and byte copying execute unchanged.
    The decoder's ordered replacements execute unchanged; its ReplaceString
    primitive, string allocation, assignment and cleanup are runtime fixtures.
    """
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_ESP, UC_X86_REG_EIP
    if not isinstance(value,str) or len(value)>4096:
        raise ValueError('XML text probe expects at most 4096 characters')
    base,image=_image(str(executable))
    u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(base,(len(image)+4095)&~4095);u.mem_write(base,image)
    for start,size in ((0,4096),(0x10000000,0x400000),(0x20000000,0x40000),(0x30000000,4096)):u.mem_map(start,size)
    heap=0x10000000
    def integer(address):return struct.unpack('<I',u.mem_read(address,4))[0]
    def writeint(address,number):u.mem_write(address,struct.pack('<I',number&0xffffffff))
    def memory(count):
        nonlocal heap
        pointer=heap;heap=(heap+count+3)&~3
        return pointer
    def allocate(text):
        encoded=text.encode('utf-16le');pointer=memory(len(encoded)+14)
        u.mem_write(pointer,struct.pack('<HHII',1200,2,0xffffffff,len(encoded)//2)+encoded+b'\0\0')
        return pointer+12
    def string(pointer):
        if not pointer:return ''
        return bytes(u.mem_read(pointer,integer(pointer-4)*2)).decode('utf-16le')
    def assign(destination,text):writeint(destination,allocate(text))
    runtimes={0x60890C,0x608914,0x60891C,0x608924,0x6048C0,0x6048DC,0x604B20,0x608A60,0x7FA430}
    def hook(emulator,address,size,user_data):
        if address not in runtimes:return
        eax=u.reg_read(UC_X86_REG_EAX);edx=u.reg_read(UC_X86_REG_EDX);ecx=u.reg_read(UC_X86_REG_ECX);esp=u.reg_read(UC_X86_REG_ESP)
        pop=0
        if address==0x608924:assign(eax,string(edx))
        elif address==0x6048C0:u.reg_write(UC_X86_REG_EAX,memory(eax))
        elif address==0x604B20:u.mem_write(edx,bytes(u.mem_read(eax,ecx)))
        elif address==0x608A60:assign(eax,bytes(u.mem_read(edx,ecx*2)).decode('utf-16le'))
        elif address==0x7FA430:assign(integer(esp+4),string(eax).replace(string(edx),string(ecx)));pop=4
        u.reg_write(UC_X86_REG_EIP,integer(esp));u.reg_write(UC_X86_REG_ESP,esp+4+pop)
    u.hook_add(UC_HOOK_CODE,hook)
    stack=0x20030000;output=0x20020000
    writeint(stack,0x30000000)
    u.reg_write(UC_X86_REG_EAX,allocate(value));u.reg_write(UC_X86_REG_EDX,output);u.reg_write(UC_X86_REG_ESP,stack)
    u.emu_start(0xC1B11C if decode else 0x7DF174,0x30000000,timeout=3000000,count=200000)
    if u.reg_read(UC_X86_REG_EIP) != 0x30000000:
        raise RuntimeError('Original XML text routine did not return within its execution budget')
    return string(integer(output))


if __name__=='__main__':main()
