"""Execute exact Toolkit update-menu code with intercepted OS calls only."""
from pathlib import Path
import hashlib
import struct

EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'

def probe_update_menu(executable):
    data = Path(executable).read_bytes()
    if hashlib.sha256(data).hexdigest() != EXE_SHA256:
        raise ValueError('The exact Toolkit 1.18.0.2754 executable is required')
    import pefile
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_EAX as EAX, UC_X86_REG_EDX as EDX, UC_X86_REG_ESP as ESP, UC_X86_REG_EIP as EIP
    pe = pefile.PE(data=data)
    base = pe.OPTIONAL_HEADER.ImageBase
    image = pe.get_memory_mapped_image()
    def run(url,return_code):
        assert type(url)is str and len(url.encode('utf-16le'))<4096
        u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(base,(len(image)+4095)&~4095);u.mem_write(base,image)
        for p,n in [(0x10000000,0x10000),(0x20000000,0x10000),(0x30000000,4096)]:u.mem_map(p,n)
        def get(p):return struct.unpack('<I',u.mem_read(p,4))[0]
        def put(p,v):u.mem_write(p,struct.pack('<I',v&0xffffffff))
        def wide(p):
            if not p:return None
            out=bytearray()
            for i in range(2049):
                pair=bytes(u.mem_read(p+2*i,2))
                if pair==b'\0\0':return out.decode('utf-16le')
                out+=pair
            raise AssertionError('unterminated pointer')
        form,pref,ptr=0x10000000,0x10000100,0x1000100c
        raw=url.encode('utf-16le')
        u.mem_write(ptr-12,struct.pack('<HHII',1200,2,1,len(raw)//2)+raw+b'\0\0')
        assert get(0x13c226c)==0x144deec
        put(0x144deec,pref);put(pref+0x18,ptr if url else 0)
        initial=bytes(u.mem_read(pref,0x100));trace=[];executed={}
        def hook(_u,a,n,_):
            assert 0xe9e9f0<=a<=0xe9ea28 or 0x6089b0<=a<=0x6089ba or a in (0x6feffc,0x677a58),hex(a)
            executed[hex(a)]=bytes(u.mem_read(a,n)).hex()
            esp=u.reg_read(ESP)
            if a==0x6feffc:
                assert u.reg_read(EAX)==form;trace.append({'call':'GetHandle','fixture_handle':0x1234})
                u.reg_write(EAX,0x1234);u.reg_write(EIP,get(esp));u.reg_write(ESP,esp+4)
            elif a==0x677a58:
                args=[get(esp+4+4*i)for i in range(6)]
                trace.append({'call':'ShellExecuteW','parent':args[0],'verb':wide(args[1]),'file':wide(args[2]),
                    'parameters':wide(args[3]),'directory':wide(args[4]),'show':args[5],'fixture_result':return_code})
                u.reg_write(EAX,return_code);u.reg_write(EIP,get(esp));u.reg_write(ESP,esp+28)
        u.hook_add(UC_HOOK_CODE,hook);stack=0x2000f000;put(stack,0x30000000)
        for r,v in [(EAX,form),(EDX,0),(ESP,stack)]:u.reg_write(r,v)
        u.emu_start(0xe9e9f0,0x30000000,timeout=1000000,count=1000)
        assert u.reg_read(EIP)==0x30000000 and len(trace)==2
        assert initial==bytes(u.mem_read(pref,0x100))
        call=trace[-1]
        assert call=={'call':'ShellExecuteW','parent':0x1234,'verb':'open','file':url.split('\0')[0],
            'parameters':None,'directory':None,'show':1,'fixture_result':return_code}
        return {'preference_string':url,'fixture_shell_result':return_code,'synchronous_return':True,
            'preference_unchanged':True,'calls':trace,'original_executed_instructions':executed}

    urls = [
        'https://www.se.com/ww/en/product-range/2216-spacelogic-cbus-home-automation-system#software-and-firmware',
        '', 'https://example.invalid/check?a=1&b=2', '  https://example.invalid/  ',
        'https://example.invalid/更新', 'https://example.invalid/ok\0ignored',
    ]
    cases = [run(url, result) for url in urls for result in (0, 2, 31, 32, 33, 0xffffffff)]
    return {'format': 'cbus-original-update-menu-probe-v1', 'passed': True, 'cases': cases,
        'executable_sha256': EXE_SHA256, 'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'browser_started': False, 'native_calls': False, 'network_calls': 0, 'registry_calls': 0,
        'scope': 'Original synchronous menu handler and pointer conversion; GetHandle/ShellExecute fixtures only.'}
