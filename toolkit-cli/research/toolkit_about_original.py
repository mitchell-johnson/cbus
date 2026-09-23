"""Original About menu/resource-reader/text phases with explicit provider fixtures.

No original UI constructor, modal window, image loader, clock, file API or
C-Gate communicator executes. All other instruction addresses fail closed.
Original menu, version reader, field setters, initialization and text assembly
execute unchanged. OS/root-version-query, allocation, managed strings, integer
text conversion and control/provider methods are enumerated fixtures.
"""
from pathlib import Path
import hashlib
import json
import struct

EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'


def probe(executable):
    import pefile
    import unicorn
    from unicorn.x86_const import (UC_X86_REG_EAX as EAX, UC_X86_REG_EDX as EDX,
        UC_X86_REG_ECX as ECX, UC_X86_REG_ESP as ESP, UC_X86_REG_EIP as EIP)
    data = Path(executable).read_bytes()
    assert hashlib.sha256(data).hexdigest() == EXE_SHA256
    pe = pefile.PE(data=data); image = pe.get_memory_mapped_image(); base = pe.OPTIONAL_HEADER.ImageBase
    entry = next(kind for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries if kind.id ==16).directory.entries[0].directory.entries[0].data.struct
    blob = pe.get_data(entry.OffsetToData,entry.Size)
    fixed_offset = pe.VS_FIXEDFILEINFO[0].get_file_offset() - pe.get_offset_from_rva(entry.OffsetToData)
    assert fixed_offset ==40 and len(blob)>=fixed_offset+52
    allowed = ((0xe9f894,0xe9faa7),(0xde0eb0,0xde0f87),(0xde0fc4,0xde10fb),
        (0xde1178,0xde1245),(0xde1248,0xde14a3),(0x7b91f0,0x7b92e2),
        (0x7b641c,0x7b655d),(0x7b6570,0x7b65a7),(0x7b65a8,0x7b66fe),
        (0x6089b0,0x6089c0))
    hooks = {0x60890c,0x608914,0x60891c,0x608924,0x608978,0x608e08,0x608eec,
        0x6198ac,0x619af0,0x606200,0x604d3c,0x7b63d0,0x6048c0,0x6048dc,
        0x60e8b8,0x60e8c0,0x60e8c8,0x7ea9dc,0xf4b254,0xf4b48c,0xf4b374,
        0x71b63c,0x61dde8,0x6f61c0,0x6f62d8,0x7d6370,0x66e924,
        0x30000100,0x30000200}
    executed = {}

    def run(case):
        u=unicorn.Uc(unicorn.UC_ARCH_X86,unicorn.UC_MODE_32)
        u.mem_map(base,(len(image)+4095)&~4095);u.mem_write(base,image)
        for address,size in ((0,4096),(0x10000000,0x40000),(0x20000000,0x40000),(0x30000000,4096)):
            u.mem_map(address,size)
        heap=[0x10008000]
        def alloc(size):
            address=heap[0];heap[0]=(address+size+7)&~7;assert heap[0]<=0x10040000;return address
        def get(p):return struct.unpack('<I',u.mem_read(p,4))[0]
        def put(p,n):u.mem_write(p,struct.pack('<I',n&0xffffffff))
        def text(value):
            if not value:return 0
            raw=value.encode('utf-16le');address=alloc(len(raw)+14)
            u.mem_write(address,struct.pack('<HHII',1200,2,0xffffffff,len(raw)//2)+raw+b'\0\0');return address+12
        def read(p):
            if not p:return ''
            n=get(p-4);assert n<=4096;return bytes(u.mem_read(p,n*2)).decode('utf-16le')
        def wide(p):
            if not p:return None
            chars=bytearray()
            for i in range(4097):
                pair=bytes(u.mem_read(p+2*i,2))
                if pair==b'\0\0':return chars.decode('utf16')
                chars.extend(pair)
            raise AssertionError('unterminated pointer')
        form,about,version,workspace,cgate=0x10000000,0x10001000,0x10002000,0x10003000,0x10004000
        provider,vmt,provider_value=0x10005000,0x10005100,0x10005200
        put(get(0x13c1bc8),provider);put(provider+4,provider_value);put(provider_value,vmt);put(vmt+0x14,0x30000100)
        put(about,vmt);put(vmt+0x110,0x30000200)
        labels={offset:alloc(0x200)for offset in (0x38c,0x390,0x394,0x398,0x39c,0x3a4,0x3a8,0x3ac,0x3b0,0x388)}
        for offset,address in labels.items():put(about+offset,address)
        put(labels[0x388]+0x1b0,alloc(0x200))
        context=case.get('context')
        if context is not None:
            put(form+0x518,workspace);put(workspace+0x3c,cgate)
            put(cgate+0xac,text(context['version']));put(cgate+0xb0,text(context['build']))
        version_blob=bytearray(blob)
        major,minor,release,build=case['version']
        struct.pack_into('<II',version_blob,fixed_offset+8,(major<<16)|minor,(release<<16)|build)
        struct.pack_into('<II',version_blob,fixed_offset+24,case.get('mask',63),case['flags'])
        calls=[];captions={};visibility={};freed=[];phase_states=[]
        def fields():return {hex(offset):read(get(about+offset))for offset in range(0x3b4,0x3e4,4)}
        def hook(_u,address,size,_):
            assert address in hooks or any(a<=address<b for a,b in allowed),('unhandled original instruction',hex(address),case['id'])
            if address not in hooks:
                executed[hex(address)]=bytes(u.mem_read(address,size)).hex()
            if address in (0xe9fa0d,0xe9fa42,0xe9fa4f):phase_states.append({'next_instruction':hex(address),'fields':fields()})
            if address not in hooks:return
            a,d,c,s=(u.reg_read(r)for r in (EAX,EDX,ECX,ESP));pop=0
            if address in (0x608924,0x608978):put(a,text(read(d)))
            elif address==0x608e08:put(a,text(read(d)+read(c)))
            elif address==0x608eec:
                assert 0<d<=16;put(a,text(''.join(read(get(s+4+4*i))for i in reversed(range(d)))));pop=4*d
            elif address==0x608914:put(a,0)
            elif address==0x60891c:
                assert d<=32
                for i in range(d):put(a+4*i,0)
            elif address==0x60890c:pass
            elif address==0x6198ac:put(d,text(str(struct.unpack('<i',struct.pack('<I',a))[0])))
            elif address==0x619af0:
                value=struct.unpack('<q',u.mem_read(s+4,8))[0];put(a,text(str(value)));pop=8
            elif address==0x30000100:
                assert a==provider_value;put(d,text(case.get('product_name','C-Bus Toolkit')))
            elif address==0x7ea9dc:
                assert a==workspace;u.reg_write(EAX,workspace)
            elif address in (0xf4b254,0xf4b48c):
                assert a==cgate
                value=context['max_memory_mb' if address==0xf4b254 else 'used_memory_mb']
                u.reg_write(EAX,value&0xffffffff);u.reg_write(EDX,(value>>32)&0xffffffff)
                calls.append({'provider':hex(address),'value':value})
            elif address==0xf4b374:
                assert a==cgate;put(d,text(context['java_version']));calls.append({'provider':hex(address),'value':context['java_version']})
            elif address==0x71b63c:u.reg_write(EAX,about);calls.append({'fixture':'preallocated About form; constructor omitted'})
            elif address==0x7b63d0:u.reg_write(EAX,version);calls.append({'fixture':'preallocated zeroed version object; constructor omitted'})
            elif address==0x604d3c:
                assert a==0;put(d,text('C:\\owned\\CBusToolkit.exe'))
            elif address==0x61dde8:u.reg_write(EAX,case.get('year',2026))
            elif address==0x60e8c0:
                assert wide(get(s+4))=='C:\\owned\\CBusToolkit.exe'
                put(get(s+8),0);u.reg_write(EAX,0 if case.get('failure')=='size' else len(blob));pop=8
                calls.append({'fixture':'GetFileVersionInfoSizeW','failed':case.get('failure')=='size'})
            elif address==0x6048c0:u.reg_write(EAX,alloc(a))
            elif address==0x6048dc:pass
            elif address==0x60e8b8:
                assert wide(get(s+4))=='C:\\owned\\CBusToolkit.exe' and get(s+12)==len(blob)
                u.mem_write(get(s+16),bytes(version_blob));u.reg_write(EAX,int(case.get('failure')!='load'));pop=16
                calls.append({'fixture':'GetFileVersionInfoW','failed':case.get('failure')=='load'})
            elif address==0x60e8c8:
                assert wide(get(s+8))=='\\';put(get(s+12),get(s+4)+fixed_offset);put(get(s+16),52)
                u.reg_write(EAX,int(case.get('failure')!='query'));pop=16
                calls.append({'fixture':'VerQueryValueW root','failed':case.get('failure')=='query'})
            elif address==0x606200:assert a in (version,about);freed.append('version' if a==version else 'about')
            elif address==0x6f61c0:visibility[hex(a)]=bool(d&255)
            elif address==0x6f62d8:captions[hex(a)]=read(d)
            elif address==0x7d6370:
                calls.append({'fixture':'image lookup omitted','name':read(d),'default':read(c)});u.reg_write(EAX,0x10006000)
            elif address==0x66e924:pass
            elif address==0x30000200:calls.append({'fixture':'modal display omitted'});u.reg_write(EAX,0)
            else:raise AssertionError(hex(address))
            u.reg_write(EIP,get(s));u.reg_write(ESP,s+4+pop)
        u.hook_add(unicorn.UC_HOOK_CODE,hook)
        stack=0x2003f000;put(stack,0x30000000)
        u.reg_write(EAX,form);u.reg_write(EDX,0);u.reg_write(ESP,stack)
        u.emu_start(0xe9f894,0x30000000,timeout=3000000,count=30000)
        assert u.reg_read(EIP)==0x30000000 and freed==['version','about']
        names={0x38c:'product',0x390:'version',0x394:'copyright',0x3a4:'cgate',0x3a8:'maximum_memory',0x3ac:'used_memory',0x3b0:'java'}
        return {'input':case,'completed':True,'fields':fields(),'phase_states':phase_states,
            'window_caption':captions[hex(about)],'captions':{names[k]:captions[hex(labels[k])]for k in names},
            'visibility':{hex(k):visibility[hex(v)]for k,v in labels.items()if hex(v)in visibility},
            'calls':calls,'fixture_cleanup':freed}

    cases=[]
    for version in ((1,18,0,2754),(0,0,0,0),(65535,65535,65535,65535),(1,2,3,4)):
        for flag in (0,2,8,10,32,34,40,42):
            cases.append({'id':'version-'+'-'.join(map(str,version))+'-flags-'+str(flag),'version':version,'flags':flag})
    for flag,mask in ((0xffffffff,0),(0x1234002a,0),(0xffff0000,63),(1,63),(4,63),(16,63)):
        cases.append({'id':'mask-'+str(mask)+'-flags-'+str(flag),'version':[1,18,0,2754],'flags':flag,'mask':mask})
    for failure in ('size','load','query'):
        cases.append({'id':'failure-'+failure,'version':[1,18,0,2754],'flags':42,'failure':failure})
    for index,context in enumerate(({'version':'3.3.2','build':'2039','max_memory_mb':512,'used_memory_mb':42,'java_version':'11.0.32'},
            {'version':'','build':'','max_memory_mb':0,'used_memory_mb':0,'java_version':''},
            {'version':'\u7248\u672c','build':'build \U0001f4a1','max_memory_mb':-1,'used_memory_mb':-9223372036854775808,'java_version':'\u7248\u672c Java'},
            {'version':'3.3.2','build':'2039','max_memory_mb':9223372036854775807,'used_memory_mb':1234567890,'java_version':' openjdk '})):
        cases.append({'id':'context-'+str(index),'version':[1,18,0,2754],'flags':0,'context':context})
    for year in (1,1999,9999):cases.append({'id':'year-'+str(year),'version':[1,18,0,2754],'flags':0,'year':year})
    for index,name in enumerate(('', 'C-Bus \U0001f4a1', ' leading and trailing ')):
        cases.append({'id':'product-'+str(index),'version':[1,18,0,2754],'flags':0,'product_name':name})
    results=[]
    for case in cases:results.append(run(case))
    return {'passed':True,'format':'cbus-original-about-v1','cases':results,
        'executable_sha256':EXE_SHA256,'probe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'original_executed_instructions':executed,'version_resource_sha256':hashlib.sha256(blob).hexdigest(),
        'scope':__doc__,'os_calls':0,'ui_created':False,'network_calls':0,'registry_calls':0,'clock_read':False}


if __name__=='__main__':
    import sys
    result=probe(sys.argv[1]);Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'passed':result['passed'],'cases':len(result['cases'])}))
