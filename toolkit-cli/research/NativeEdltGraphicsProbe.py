"""Execute original graphics exports in bounded x86 emulation; no host DLL load."""
from pathlib import Path
import argparse,hashlib,json,struct
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_MEM_INVALID,UC_HOOK_CODE,UcError
from unicorn.x86_const import UC_X86_REG_EIP,UC_X86_REG_ESP,UC_X86_REG_EAX
parser=argparse.ArgumentParser();parser.add_argument('dll',type=Path);parser.add_argument('output',type=Path)
args=parser.parse_args();path=args.dll;p=pefile.PE(str(path))
if p.FILE_HEADER.Machine!=0x14c:raise ValueError('Expected original x86 PE DLL')
base=p.OPTIONAL_HEADER.ImageBase;size=p.OPTIONAL_HEADER.SizeOfImage
emu=Uc(UC_ARCH_X86,UC_MODE_32);emu.mem_map(base,size);emu.mem_write(base,p.get_memory_mapped_image())
stack=0x20000000;buf=0x21000000;stop=0x22000000
for a in (stack,buf,stop):emu.mem_map(a,0x10000)
stub=0x23000000;emu.mem_map(stub,0x10000)
imports={}
for entry in p.DIRECTORY_ENTRY_IMPORT:
 for imp in entry.imports:
  addr=stub+len(imports)*16
  imports[addr]=imp.name.decode();emu.mem_write(imp.address,struct.pack('<I',addr));emu.mem_write(addr,b'\xc3')
import_calls={}
def imported(uc,address,size,data):
 if address not in imports:return
 name=imports[address];esp=uc.reg_read(UC_X86_REG_ESP)
 a,b,c=struct.unpack('<III',bytes(uc.mem_read(esp+4,12)))
 import_calls[name]=import_calls.get(name,0)+1
 if name=='memset':uc.mem_write(a,bytes([b&255])*c);uc.reg_write(UC_X86_REG_EAX,a)
 elif name=='memcpy':uc.mem_write(a,bytes(uc.mem_read(b,c)));uc.reg_write(UC_X86_REG_EAX,a)
 else:raise RuntimeError('Unimplemented imported function '+name)
emu.hook_add(UC_HOOK_CODE,imported,begin=stub,end=stub+0xffff)
exports={s.name.decode():base+s.address for s in p.DIRECTORY_ENTRY_EXPORT.symbols if s.name}
def call(name,args=()):
 esp=stack+0xff00;emu.mem_write(esp,struct.pack('<'+'I'*(len(args)+1),stop,*args));emu.reg_write(UC_X86_REG_ESP,esp)
 emu.emu_start(exports[name],stop,count=2000000)
 if emu.reg_read(UC_X86_REG_EIP)!=stop:raise RuntimeError('Instruction limit exhausted')
 return emu.reg_read(UC_X86_REG_EAX)
call('?fninit@@YAXXZ')
rows=[]
for index in range(255):
 emu.mem_write(buf,b'\0'*2760)
 call('?fnget_icon_24bpp@@YAXPAEE@Z',(buf,index))
 data=bytes(emu.mem_read(buf,2760))
 rows.append({'index':index,'ui_visible':255 in data,'white_bytes':data.count(255),'sha256':hashlib.sha256(data).hexdigest()})
report={'dll_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'scope':'Unchanged fninit/fnget_icon_24bpp in x86 emulator, no Windows host call or physical device','import_calls':import_calls,'executed_exports':['?fninit@@YAXXZ','?fnget_icon_24bpp@@YAXPAEE@Z'],'icon_indices':[r['index'] for r in rows if r['ui_visible']],'rows':rows}
args.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))
