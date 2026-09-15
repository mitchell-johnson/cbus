"""Original preview, integer formatter and tag-click code; explicit string heap and label fixtures."""
from pathlib import Path
import hashlib,json,struct,sys
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_ESP,UC_X86_REG_EIP
ENTRIES={'preview':0xddf628,'tag-standard':0xddf3d4,'tag-hex':0xddf3fc,'tag-value':0xddf424}
HOOKS={0x609490:'unicode-allocation',0x608a50:'ascii-to-unicode',0x608a60:'wide-buffer-to-unicode',
 0x608924:'unicode-assignment',0x60890c:'unicode-addref',0x608914:'unicode-release',
 0x60891c:'unicode-array-release',0x6075f0:'temporary-array-release',0x6f62d8:'label-setter'}
class OriginalPreferencePreview:
 def __init__(self,executable):
  self.data=Path(executable).read_bytes()
  self.executable_sha256=hashlib.sha256(self.data).hexdigest()
  if self.executable_sha256!='9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab':
   raise ValueError('Expected the exact Toolkit1.18 executable')
  pe=pefile.PE(data=self.data);self.base=pe.OPTIONAL_HEADER.ImageBase;self.image=pe.get_memory_mapped_image()

 def run(self,operation,tag_hex,tag_override):
  if operation not in ENTRIES or type(tag_hex)is not bool or type(tag_override)is not bool:
   raise ValueError('Explicit original preview operation and boolean flags required')
  base,image=self.base,self.image
  u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(base,(len(image)+4095)&~4095);u.mem_write(base,image)
  for p,n in ((0,4096),(0x10000000,0x200000),(0x20000000,0x40000),(0x30000000,4096)):u.mem_map(p,n)
  def get(p):return struct.unpack('<I',u.mem_read(p,4))[0]
  def put(p,x):u.mem_write(p,struct.pack('<I',x&0xffffffff))
  heap=0x10010000
  def string(text):
   nonlocal heap
   raw=text.encode('utf-16-le');p=heap;heap=(heap+len(raw)+22+7)&~7
   u.mem_write(p,struct.pack('<HHII',1200,2,1,len(text))+raw+b'\0\0');return p+12
  def read(p):return bytes(u.mem_read(p,get(p-4)*2)).decode('utf-16-le') if p else ''
  form=0x10000000;label=0x10001000;put(form+0x49c,label)
  u.mem_write(0x144df1c,bytes([tag_hex]));u.mem_write(0x144df24,bytes([tag_override]))
  trace=[];executed={};label_outputs=[];number_calls=[]
  def hook(_u,address,size,_):
   assert base<=address<base+len(image),hex(address)
   executed[address]=bytes(_u.mem_read(address,size)).hex()
   eax,edx,ecx,esp=(u.reg_read(r) for r in (UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_ESP))
   if address in (0x6198ac,0x61b6e8,0x61b624):number_calls.append(hex(address))
   if address not in HOOKS:return
   row={'fixture':HOOKS[address],'address':hex(address)}
   if address==0x609490:
    assert eax<=4096;u.reg_write(UC_X86_REG_EAX,string('\0'*eax));row['length']=eax
   elif address in (0x608a50,0x608a60):
    assert ecx<=4096
    raw=bytes(u.mem_read(edx,ecx*(1 if address==0x608a50 else 2)))
    text=raw.decode('ascii' if address==0x608a50 else 'utf-16-le');put(eax,string(text));row['text']=text
   elif address==0x608924:put(eax,edx);row['text']=read(edx)
   elif address==0x6f62d8:
    assert eax==label;label_outputs.append(read(edx));row['text']=read(edx)
   trace.append(row)
   u.reg_write(UC_X86_REG_EIP,get(esp));u.reg_write(UC_X86_REG_ESP,esp+4)
  u.hook_add(UC_HOOK_CODE,hook)
  stack=0x20030000;put(stack,0x30000000)
  for reg,v in ((UC_X86_REG_EAX,form),(UC_X86_REG_EDX,0),(UC_X86_REG_ECX,0),(UC_X86_REG_ESP,stack)):u.reg_write(reg,v)
  u.emu_start(ENTRIES[operation],0x30000000,timeout=3000000,count=200000)
  assert u.reg_read(UC_X86_REG_EIP)==0x30000000 and len(label_outputs)==1
  final=[int(u.mem_read(a,1)[0]) for a in (0x144df1c,0x144df24)]
  return {'operation':operation,'initial':[tag_hex,tag_override],'final':final,'label':label_outputs[0],
   'fixtures':trace,'original_number_calls':number_calls,'executed_instructions':{hex(a):executed[a] for a in sorted(executed)}}
