"""Original Preferences reset, CIS wrapper and recursive TRegistry deletion.

Hash-pinned x86 instructions execute unchanged. Allocation, Delphi strings,
Win32 registry calls, object release and the notice display are explicit
fixtures. This does not access a registry or emulate OS exception delivery.
"""
from pathlib import Path
import hashlib,struct
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EBX

EXE_SHA256='9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
TARGET=r'Software\Clipsal Integrated Systems\C-Bus Installation Software\3.0\DontAskAgain'
HKCU=0x80000001
RANGES=((0xddf2d4,0xddf30b),(0x8455ec,0x84567f),(0x660b54,0x660b97),
        (0x660c00,0x660ca4),(0x660938,0x6609ac),(0x6610a0,0x661229),
        (0x661250,0x6612bb),(0x661c68,0x661cfe))
HOOKS={0x660b54,0x606200,0x60890c,0x608914,0x60891c,0x608924,0x608978,0x6089b0,
       0x6091e4,0x608a60,0x608ae0,0x605544,0x60e214,0x60e22c,0x60e1fc,
       0x60e1d4,0x60e1ec,0x7d9d00}

class OriginalResetProbe:
    def __init__(self,executable):
        data=Path(executable).read_bytes()
        if hashlib.sha256(data).hexdigest()!=EXE_SHA256:raise ValueError('wrong original executable')
        pe=pefile.PE(data=data);self.base=pe.OPTIONAL_HEADER.ImageBase;self.image=pe.get_memory_mapped_image()

    def run(self,children=(),*,faults=(),far_east=False):
        """children are relative paths; fault tuples are (operation,path,index,status)."""
        assert type(far_east)is bool
        nodes={TARGET:True}
        if children is None:nodes={}
        else:
            for child in children:
                assert type(child)is str and child and not child.startswith('\\') and '\0'not in child
                parts=child.split('\\')
                for length in range(1,len(parts)+1):nodes[TARGET+'\\'+'\\'.join(parts[:length])]=True
        initial=list(nodes);handles={};counter=0x50000;trace=[];returns=[];notices=[];released=[]
        rules={(operation,path,index):status for operation,path,index,status in faults}
        u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(self.base,(len(self.image)+4095)&~4095);u.mem_write(self.base,self.image)
        for address,size in((0,4096),(0x10000000,0x200000),(0x20000000,0x40000),(0x30000000,4096)):u.mem_map(address,size)
        heap=0x10000000
        def alloc(n):
            nonlocal heap
            result=heap;heap=(heap+n+7)&~7;return result
        def get(p):return int.from_bytes(u.mem_read(p,4),'little')
        def put(p,v):u.mem_write(p,struct.pack('<I',v&0xffffffff))
        def text(s):
            if not s:return 0
            raw=s.encode('utf-16le');p=alloc(len(raw)+14)
            u.mem_write(p,struct.pack('<HHII',1200,2,0xffffffff,len(raw)//2)+raw+b'\0\0');return p+12
        def read(p):return bytes(u.mem_read(p,get(p-4)*2)).decode('utf-16le')if p else''
        def wz(p):
            parts=[]
            for i in range(4096):
                raw=bytes(u.mem_read(p+2*i,2))
                if raw==b'\0\0':return b''.join(parts).decode('utf-16le')
                parts.append(raw)
            raise AssertionError('unbounded original string')
        def resolve(parent,name):
            path=name.lstrip('\\')if parent==HKCU else handles[parent]+'\\'+name
            assert path==TARGET or path.startswith(TARGET+'\\'),path
            return path
        def immediate(path):return [node[len(path)+1:]for node in nodes if node.startswith(path+'\\')and'\\'not in node[len(path)+1:]]
        def status(operation,path,index,normal):return rules.get((operation,path,index),normal)
        empty=text('\0');form=alloc(0x600);put(get(0x13c394c),alloc(0x100))
        u.mem_write(get(0x13c41d4)+12,bytes([far_east]));put(get(0x13c4164),2)
        def hook(_u,address,size,_):
            nonlocal counter
            eax,edx,ecx,esp=(u.reg_read(r)for r in(UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_ESP))
            if address not in HOOKS:
                assert any(a<=address<b for a,b in RANGES),('unexpected original execution',hex(address))
                if address==0x845641:returns.append(bool(eax&255))
                return
            pop=4
            if address==0x660b54:
                assert edx&255
                obj=alloc(0x100);put(obj,eax);u.reg_write(UC_X86_REG_EAX,obj);u.reg_write(UC_X86_REG_EDX,edx&~255)
                return
            elif address==0x606200:released.append(eax)
            elif address==0x60890c:pass
            elif address==0x608914:put(eax,0)
            elif address==0x60891c:
                for index in range(edx):put(eax+4*index,0)
            elif address in(0x608924,0x608978):put(eax,text(read(edx)))
            elif address==0x6089b0:u.reg_write(UC_X86_REG_EAX,eax or empty)
            elif address==0x6091e4:
                old=read(get(eax));put(eax,text(old[:edx-1]+old[edx-1+ecx:]))
            elif address==0x608a60:
                assert edx==0 and ecx<=4096;put(eax,text('\0'*ecx))
            elif address==0x608ae0:put(eax,text(wz(edx)))
            elif address==0x605544:
                assert edx<=4096;u.mem_write(eax,bytes([ecx&255])*edx)
            elif address==0x60e214:
                parent,name,reserved,access,out=[get(esp+4*i)for i in range(1,6)]
                assert reserved==0 and access==0xf003f
                path=resolve(parent,wz(name));code=status('open',path,None,0 if path in nodes else 2)
                handle=0
                if not code:handle=counter;counter+=1;handles[handle]=path
                put(out,handle);trace.append({'operation':'open','path':path,'access':access,'status':code})
                u.reg_write(UC_X86_REG_EAX,code);pop+=20
            elif address==0x60e22c:
                args=[get(esp+4*i)for i in range(1,13)];path=handles[args[0]];names=immediate(path)
                code=status('query',path,None,0)
                if not code:put(args[4],len(names));put(args[5],max((len(n.encode('utf-16le'))//2 for n in names),default=0))
                trace.append({'operation':'query','path':path,'status':code,'count':len(names)if not code else None,'max_name_length':max((len(n.encode('utf-16le'))//2 for n in names),default=0)if not code else None})
                u.reg_write(UC_X86_REG_EAX,code);pop+=48
            elif address==0x60e1fc:
                handle,index,buffer,length,*unused=[get(esp+4*i)for i in range(1,9)]
                path=handles[handle];names=immediate(path);capacity=get(length)
                code=status('enumerate',path,index,0 if index<len(names)else 259);name=None
                if not code:
                    name=names[index];raw=name.encode('utf-16le')+b'\0\0';assert len(raw)//2<=capacity
                    u.mem_write(buffer,raw);put(length,len(raw)//2-1)
                trace.append({'operation':'enumerate','path':path,'index':index,'capacity':capacity,'status':code,'name':name})
                u.reg_write(UC_X86_REG_EAX,code);pop+=32
            elif address==0x60e1d4:
                handle=get(esp+4);path=handles.pop(handle);code=status('close',path,None,0)
                trace.append({'operation':'close','path':path,'status':code});u.reg_write(UC_X86_REG_EAX,code);pop+=4
            elif address==0x60e1ec:
                parent,name=get(esp+4),wz(get(esp+8));path=resolve(parent,name)
                code=status('delete',path,None,2 if path not in nodes else 5 if immediate(path)else 0)
                if not code:del nodes[path]
                trace.append({'operation':'delete','path':path,'status':code});u.reg_write(UC_X86_REG_EAX,code);pop+=8
            elif address==0x7d9d00:
                assert edx==0x2bfc;notices.append({'message_id':edx,'caption':read(get(esp+4))});pop+=4
            else:raise AssertionError(hex(address))
            u.reg_write(UC_X86_REG_EIP,get(esp));u.reg_write(UC_X86_REG_ESP,esp+pop)
        u.hook_add(UC_HOOK_CODE,hook);stack=0x20030000;put(stack,0x30000000)
        u.reg_write(UC_X86_REG_ESP,stack);u.reg_write(UC_X86_REG_EAX,form)
        u.emu_start(0xddf2d4,0x30000000,timeout=3000000,count=300000)
        assert u.reg_read(UC_X86_REG_EIP)==0x30000000 and not handles and len(released)==1
        return {'children':None if children is None else list(children),'faults':[list(row)for row in faults],'far_east_fixture':far_east,'initial_nodes':initial,'remaining_nodes':list(nodes),'trace':trace,'original_delete_return':returns,'notice_requests':notices,'registry_object_free_calls':len(released)}
