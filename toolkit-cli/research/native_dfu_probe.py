"""Research-only execution of original x86 eDLT LMDfu routines.

No USB library is loaded and no operating-system USB call can occur. Endpoint0,
Sleep and runtime fixtures execute in Python around the unchanged DLL code.
The transport uses scripted replies, not a DFU device model. No firmware
archive is opened; all image content is synthetic. Requires pefile/unicorn.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import struct
from pathlib import Path


class Probe:
    HANDLE = 0x20001000
    DATA = 0x20010000
    OUT = 0x20030000

    def __init__(self, dll, *, statuses=(), short=None, fail=False, attributes=4, peer=None):
        import pefile
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP
        self.registers = UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP
        pe = pefile.PE(str(dll)); data = pe.get_memory_mapped_image()
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        self.u.mem_map(pe.OPTIONAL_HEADER.ImageBase, (len(data)+4095)&~4095)
        self.u.mem_write(pe.OPTIONAL_HEADER.ImageBase, data)
        self.u.mem_map(0x20000000, 0x100000)
        self.u.mem_map(0x30000000, 0x100000)
        self.u.mem_map(0x40000000, 0x10000)
        self.u.mem_write(self.HANDLE, struct.pack('<IBBHHHHBBHHHHII',
            0x1234, 1, 0, 0x166A, 0x0501, 0x0100, 1024, attributes, 0,
            0, 256, 8, 0, 0, 0))
        self.statuses = list(statuses)
        self.short = short; self.fail = fail; self.peer = peer; self.heap = 0x20050000
        self.wire = []; self.sleeps = []; self.upload_data = b''
        self.stubs = {
            0x40000100: ('endpoint', 32), 0x40000200: ('sleep', 4),
            0x40000300: ('last_error', 0), 0x40000400: ('terminate', 4),
            0x40000500: ('post_message', 16), 0x10004181: ('free', 0), 0x100041BB: ('allocate', 0),
        }
        for source, target in ((0x10011110,0x40000100), (0x10011008,0x40000200),
                               (0x1001100C,0x40000300), (0x10011114,0x40000400),
                               (0x10011104,0x40000500)):
            self.put(source, target)
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def integer(self, address): return struct.unpack('<I', self.u.mem_read(address,4))[0]
    def put(self, address, value): self.u.mem_write(address,struct.pack('<I',value&0xffffffff))

    def hook(self, emulator, address, size, user_data):
        if address not in self.stubs: return
        eax, eip, espreg = self.registers
        esp = self.u.reg_read(espreg)
        kind, count = self.stubs[address]
        args = [self.integer(esp+4+i*4) for i in range(count//4)]
        result = 1
        if kind == 'endpoint':
            handle, bm, request, value, index, length, pointer, output = args
            if handle != 0x1234 or index != 0 or length > 1024:
                raise ValueError('Native request exceeded the isolated transport fixture')
            data = b''
            if self.peer is not None:
                outgoing = bytes(self.u.mem_read(pointer,length)) if bm == 0x21 and length else b''
                data = self.peer.control(bm,request,value,index,data=outgoing,length=length)
                if bm == 0xA1 and data: self.u.mem_write(pointer,data)
                if bm == 0x21: data = outgoing
            elif bm == 0xA1:
                if request == 3:
                    data = self.statuses.pop(0) if self.statuses else bytes.fromhex('000000000200')
                elif request == 2:
                    data = self.upload_data[:length]; self.upload_data = self.upload_data[length:]
                elif request == 0x42:
                    data = bytes.fromhex('4d4c0100')
                else: raise ValueError(f'Unscripted IN request {request}')
                if len(data) != length: raise ValueError('Scripted IN reply has the wrong length')
                if length: self.u.mem_write(pointer,data)
            elif bm == 0x21:
                if request not in (0,1,4,6): raise ValueError(f'Unscripted OUT request {request}')
                data = bytes(self.u.mem_read(pointer,length)) if length else b''
            else: raise ValueError(f'Unexpected request type {bm}')
            transferred = length if self.short is None else self.short
            self.u.mem_write(output,struct.pack('<H',transferred))
            result = 0 if self.fail else 1
            self.wire.append({'bmRequestType':bm,'bRequest':request,'wValue':value,
                              'wIndex':index,'wLength':length,'data_hex':data.hex(),
                              'fixture_transferred':transferred,'fixture_success':bool(result)})
        elif kind == 'allocate':
            size = self.integer(esp+4)
            if size > 0x40000 or self.heap+size > 0x20100000: raise ValueError('Fixture allocation exceeds budget')
            result = self.heap; self.heap += (size+15)&~15
        elif kind == 'sleep': self.sleeps.append(args[0])
        elif kind == 'last_error': result = 31
        elif kind == 'terminate': self.wire.append({'fixture_close':True})
        self.u.reg_write(eax,result)
        self.u.reg_write(eip,self.integer(esp))
        self.u.reg_write(espreg,esp+4+count)

    def call(self, address, *args):
        eax, eip, espreg = self.registers
        stack=0x30080000
        self.u.mem_write(stack,struct.pack('<'+'I'*(len(args)+1),0x40000000,*args))
        self.u.reg_write(espreg,stack)
        self.u.emu_start(address,0x40000000,timeout=3000000,count=1000000)
        if self.u.reg_read(eip) != 0x40000000: raise RuntimeError('Native execution budget exhausted')
        result=self.u.reg_read(eax)
        return result if result < 0x80000000 else result-0x100000000

    def result(self, name, result):
        return {'name':name,'native_return':result,'wire':self.wire,'sleep_ms':self.sleeps,
                'next_block':struct.unpack('<H',self.u.mem_read(self.HANDLE+0x16,2))[0]}


def run(dll):
    cases=[]
    def check(name, address, arguments, *, expected=0, **options):
        p=Probe(dll,**options)
        p.u.mem_write(p.DATA,bytes(range(256))*5)
        result=p.call(address,*arguments(p))
        if result!=expected: raise AssertionError((name,result,expected))
        cases.append(p.result(name,result)); return p
    for external in (0,1):
        tag='external' if external else 'internal'
        p=check(f'{tag}-program',0x10010050,
            lambda p:(p.HANDLE,p.DATA,1280,0x20000 if external else 0x2000,0,0,external))
        payloads=[r['data_hex'] for r in p.wire if r.get('bRequest')==1]
        expected=('0800800000050000' if external else '0100080000050000')
        assert payloads[0]==expected and [len(bytes.fromhex(v)) for v in payloads]==[8,1024,256,0]
        assert [r['wValue'] for r in p.wire if r.get('bRequest')==1]==[0,1,2,3]
        p=check(f'{tag}-erase-verified',0x1000F9C0,
            lambda p:(p.HANDLE,0x20000 if external else 0x2000,0x20000 if external else 2048,1,0,external))
        payloads=[r['data_hex'] for r in p.wire if r.get('bRequest')==1]
        assert payloads==(['0b00020002000000','0a00800000000200'] if external else
                          ['0400080002000000','0300080000080000'])
        p=check(f'{tag}-blank-check',0x1000F8C0,
            lambda p:(p.HANDLE,0x20000 if external else 0x2000,2048,external))
        assert [r['data_hex'] for r in p.wire if r.get('bRequest')==1]==[
            '0a00020000080000' if external else '0300080000080000']
    p=check('internal-erase-count-quirk',0x1000F9C0,lambda p:(p.HANDLE,0x2000,0x200000,0,0,0))
    assert [r['data_hex'] for r in p.wire if r.get('bRequest')==1]==['0400080002080000']
    for state in range(12):
        expected=-5 if state in (0,1,8) else 0
        p=check(f'idle-transition-{state}',0x1000F2B0,lambda p:(p.HANDLE,),expected=expected,
            statuses=[bytes([0,1,2,3,state,0])])
        requests=[r['bRequest'] for r in p.wire]
        assert requests==[3]+([6] if state in (3,4,5,6,7,9) else [4] if state==10 else [])
        if state in (4,6,7): assert p.sleeps==[1281]
    check('manifest-nonzero-wrong-attribute-native-success-quirk',0x1000F2B0,lambda p:(p.HANDLE,),
        statuses=[bytes.fromhex('000000000600')],attributes=1)
    p=check('manifest-without-attribute',0x1000F2B0,lambda p:(p.HANDLE,),expected=-5,
        statuses=[bytes.fromhex('000000000600')],attributes=0)
    p=check('busy-polling-24-bit-delay',0x1000ED00,lambda p:(p.HANDLE,1,p.DATA,8),
        statuses=[bytes.fromhex('000102030400'),bytes.fromhex('000000000500')])
    assert p.sleeps==[197121]
    for status in range(16):
        # Literal independent expected mapping from native status-to-error switch.
        expected=[0,-5,-5,-12,-12,-12,-12,-12,-7,-12,-4,-4,-4,-4,-4,-11][status]
        check(f'dfu-status-{status}',0x1000ED00,lambda p:(p.HANDLE,1,p.DATA,8),
            expected=expected,statuses=[bytes([status,0,0,0,5,0])])
    check('short-download',0x1000ED00,lambda p:(p.HANDLE,1,p.DATA,8),expected=-4,short=7)
    check('failed-download',0x1000ED00,lambda p:(p.HANDLE,1,p.DATA,8),expected=-4,fail=True)
    check('short-direct-status-native-success-quirk',0x1000EC00,lambda p:(p.HANDLE,p.OUT),short=5)
    check('failed-direct-status-full-length-native-success-quirk',0x1000EC00,
          lambda p:(p.HANDLE,p.OUT),short=6,fail=True)
    check('failed-direct-status-short',0x1000EC00,lambda p:(p.HANDLE,p.OUT),expected=-4,short=5,fail=True)
    check('failed-detach-native-success-quirk',0x1000E350,lambda p:(p.HANDLE,),fail=True)
    return cases


def dfuprog_download_arguments(executable, *, skip_flag=False, external=False):
    """Execute original binary-download argument forwarding, with no DLL load.

    The two option globals are set exactly as the static argument parser does.
    This does not execute the process argument parser or file-reading dispatcher.
    """
    import pefile
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP
    pe=pefile.PE(str(executable));im=pe.get_memory_mapped_image()
    u=Uc(UC_ARCH_X86,UC_MODE_32)
    u.mem_map(0x400000,(len(im)+4095)&~4095);u.mem_write(0x400000,im)
    u.mem_map(0x20000000,0x10000);u.mem_map(0x30000000,0x1000)
    u.mem_write(0x412BA8,struct.pack('<I',0x30000100))
    u.mem_write(0x412B74,struct.pack('<I',8192))
    u.mem_write(0x412B6C,bytes([int(skip_flag)]))
    u.mem_write(0x412B80,struct.pack('<I',int(external)))
    stack=0x20008000
    u.mem_write(stack,struct.pack('<4I',0x30000000,0x1234,0x20001000,1280))
    u.reg_write(UC_X86_REG_ESP,stack)
    captured=[]
    def hook(emulator,address,size,user_data):
        if address!=0x30000100:return
        esp=u.reg_read(UC_X86_REG_ESP)
        captured.append(struct.unpack('<7I',u.mem_read(esp+4,28)))
        u.reg_write(UC_X86_REG_EIP,struct.unpack('<I',u.mem_read(esp,4))[0])
        u.reg_write(UC_X86_REG_ESP,esp+32);u.reg_write(UC_X86_REG_EAX,0)
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0x402450,0x30000000,timeout=1000000,count=10000)
    if u.reg_read(UC_X86_REG_EIP)!=0x30000000 or len(captured)!=1:
        raise RuntimeError('Original wrapper did not make exactly one captured call')
    return dict(zip(('handle','buffer','length','address','verify','notification_window','external'),captured[0]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    cases=run(args.dll)
    document={'schema':1,'scope':'Unmodified x86 vendor DLL with scripted in-memory USB responses; no hardware, images or independent device model.',
        'source':{'path':str(args.dll),'sha256':hashlib.sha256(args.dll.read_bytes()).hexdigest()},
        'case_count':len(cases),'passed':True,'cases':cases}
    executable=args.dll.parents[2]/'dfuprog.exe'
    if executable.exists():
        document['dfuprog']={'sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
            'wrapper':[{ 'skip_option_global':skip,'external_option_global':ext,
                        'arguments':dfuprog_download_arguments(executable,skip_flag=skip,external=ext)}
                       for skip in (False,True) for ext in (False,True)]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(document,indent=2)+'\n')
    print(json.dumps({'passed':True,'cases':len(cases),'output':str(args.output)}))

if __name__=='__main__':main()
