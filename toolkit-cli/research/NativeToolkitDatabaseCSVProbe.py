"""Original CSV instruction pilot with explicit cached provider/RTL fixtures.

No PE entrypoint, imports, constructors, registry, file writer or network API
executes. All guest instructions are predecoded from the pinned image ranges.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys
import time

import capstone
import pefile
import unicorn
from unicorn.unicorn_py3 import unicorn as unicorn_core
from unicorn.x86_const import (
    UC_X86_REG_EAX as EAX, UC_X86_REG_EDX as EDX,
    UC_X86_REG_ECX as ECX, UC_X86_REG_ESP as ESP,
    UC_X86_REG_EIP as EIP, UC_X86_REG_EFLAGS as FLAGS,
)

EXE = None  # Supplied explicitly by the isolated host launcher.
EXE_SHA = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
RANGES = (
    ('AsCSV', 0xf306bc, 0xf30bfd),
    ('QuoteStringForCSV', 0x7b7b84, 0x7b7c16),
    ('StringContains', 0x7b78c4, 0x7b78f4),
    ('StringReplace', 0x623ecc, 0x624081),
    ('AnsiPos', 0x623498, 0x623576),
    ('StrPos', 0x61b404, 0x61b45b),
    ('StrPosLen', 0x61b45c, 0x61b4bc),
    ('StrLComp', 0x61b2e8, 0x61b336),
    ('Pos-Unicode', 0x6094d4, 0x609520),
    ('UStrEqual-Unicode', 0x6090ac, 0x6090ed),
    ('UStrLen', 0x608ca4, 0x608cae),
    ('CvtInt', 0x619800, 0x61984c),
    ('IntToStr', 0x6198ac, 0x6198c9),
    ('GetSimpleDecimalAddress-cached', 0xf47e88, 0xf47eb8),
    ('GetFirmwareVersion', 0xf2ecac, 0xf2eccd),
    ('DisplayableSerialNumber', 0xf33c78, 0xf33cd4),
    ('GetDisplayableSerialNumber', 0x7f30a4, 0x7f30f0),
    ('FormatSerialNumber', 0x7f3140, 0x7f33a9),
)
RTL = {
    0x608924:'UStrAsg', 0x608978:'UStrLAsg', 0x608914:'UStrClr',
    0x60891c:'UStrArrayClr', 0x60890c:'UStrAddRef',
    0x608a50:'UStrFromPCharLen', 0x608aa0:'UStrFromWChar',
    0x608d48:'UStrCat', 0x608e08:'UStrCat3', 0x608eec:'UStrCatN',
    0x609114:'UStrCopy', 0x6089b0:'UStrToPWChar',
    0x60c470:'LoadResString-pinned-literal',
    0x847f7c:'Caption-pinned-literal',
    0xf2e08c:'UnitManager-owned-GetItem',
    0xf28954:'GroupManager-owned-GetItem',
}
CALLBACKS = {
    0x30001000:'attribute-text', 0x30001010:'collection-count',
    0x30001020:'output-add', 0x30001030:'unit-area',
    0x30001040:'unit-primary', 0x30001050:'unit-secondary',
    0x30001060:'unit-group-used',
}
SCALARS = ('part_name','tag_name','unit_type','catalog','serial','firmware')
FIELDS = {'part_name':0x100,'tag_name':0x9c,'unit_type':0x108,
          'catalog':0xf0,'serial':0xec,'firmware':0xc8}


def digest(data): return hashlib.sha256(data).hexdigest()
def safe_error(error):
    try: message = str(error)
    except BaseException: message = '<unprintable>'
    return {'type':type(error).__name__, 'message':message[:2048]}


class HarnessError(Exception): pass


def require(condition, message):
    if not condition: raise HarnessError(message)


class Image:
    def __init__(self):
        self.raw = EXE.read_bytes()
        require(digest(self.raw) == EXE_SHA, 'Original EXE pin mismatch')
        self.pe = pefile.PE(data=self.raw)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        require(self.pe.FILE_HEADER.Machine == 0x14c, 'Expected original x86')
        self.mapped = self.pe.get_memory_mapped_image()
        decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        self.instructions, self.spans = {}, []
        for name,start,end in RANGES:
            raw=self.pe.get_data(start-self.base,end-start)
            decoded=list(decoder.disasm(raw,start))
            require(decoded and decoded[-1].address+decoded[-1].size==end,
                    'Incomplete instruction span '+name)
            for item in decoded:
                require(item.mnemonic not in ('int','syscall','sysenter','in','out'), 'Privileged opcode')
                self.instructions[item.address]=(name,item.bytes)
            self.spans.append({'name':name,'start':hex(start),'end':hex(end),
                               'bytes':len(raw),'sha256':digest(raw)})
        self.resources={}
        for kind in self.pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if kind.id != 6: continue
            for block in kind.directory.entries:
                for language in block.directory.entries:
                    entry=language.data.struct
                    data=self.pe.get_data(entry.OffsetToData,entry.Size);pos=0
                    for index in range(16):
                        count=struct.unpack_from('<H',data,pos)[0];pos+=2
                        value=data[pos:pos+count*2].decode('utf-16le');pos+=count*2
                        self.resources.setdefault((block.id-1)*16+index,set()).add(value)
                    require(pos==len(data) or (len(data)==((pos+3)&~3) and not any(data[pos:])), 'Resource padding')
        self.captions=[]
        decoder.detail=True
        for item in decoder.disasm(self.pe.get_data(0xea8094-self.base,0xea817f-0xea8094),0xea8094):
            if item.mnemonic=='mov' and item.op_str.startswith('eax, 0x'):
                va=item.operands[1].imm
                if 0xea8180 <= va < 0xea84ec: self.captions.append(self.literal(va))
        require(len(self.captions)==26,'Caption registration count')
    def word(self, va): return struct.unpack('<I',self.pe.get_data(va-self.base,4))[0]
    def literal(self,va):
        count=self.word(va-4);require(count<=4096,'Literal size')
        return self.pe.get_data(va-self.base,count*2).decode('utf-16le')


class Machine:
    def __init__(self,image):
        self.image=image; self.u=unicorn.Uc(unicorn.UC_ARCH_X86,unicorn.UC_MODE_32)
        self.u.mem_map(image.base,(len(image.mapped)+4095)&~4095)
        self.u.mem_write(image.base,image.mapped)
        self.u.mem_protect(image.base,(len(image.mapped)+4095)&~4095,unicorn.UC_PROT_READ|unicorn.UC_PROT_EXEC)
        for address,size in ((0,4096),(0x10000000,0x400000),(0x20000000,0x40000),(0x30000000,0x2000)):
            self.u.mem_map(address,size)
        self.heap=0x10000000;self.objects={};self.collections={};self.attributes={}
        self.lines=[];self.calls=[];self.executed={};self.rtl={};self.instructions=0
        self.empty=self.text('');self.manager=self.object({0x58:0x30001010})
        self.output=self.object({0x38:0x30001020})
        self.collections[self.manager]=[]
        self.source_ranges=[]
        self.u.hook_add(unicorn.UC_HOOK_CODE,self.hook)
        self.u.hook_add(unicorn.UC_HOOK_MEM_WRITE,self.write_guard)
    def alloc(self,size):
        address=self.heap;self.heap=(self.heap+size+15)&~15
        require(self.heap<=0x10400000,'Heap limit')
        return address
    def get(self,address):return struct.unpack('<I',self.u.mem_read(address,4))[0]
    def put(self,address,value):self.u.mem_write(address,struct.pack('<I',value&0xffffffff))
    def text(self,value):
        raw=value.encode('utf-16le','surrogatepass');require(len(raw)<=32768,'Generated string limit')
        if not raw:return 0
        address=self.alloc(len(raw)+16)
        self.u.mem_write(address,struct.pack('<HHII',1200,2,0xffffffff,len(raw)//2)+raw+b'\0\0\0\0')
        return address+12
    def read(self,address):
        if not address:return ''
        count=self.get(address-4);require(count<=16384,'Read string bound')
        return bytes(self.u.mem_read(address,count*2)).decode('utf-16le','surrogatepass')
    def object(self,slots):
        vmt=self.alloc(0x200);obj=self.alloc(0x200);self.put(obj,vmt)
        for offset,callback in slots.items():self.put(vmt+offset,callback)
        return obj
    def attribute(self,value,label):
        obj=self.object({0x2c:0x30001000});self.attributes[obj]=(value,label)
        return obj
    def named(self,value,label):
        if value is None:return 0
        obj=self.object({});self.put(obj+0x9c,self.attribute(value,label));return obj
    def unit(self,data):
        obj=self.object({0xec:0x30001030,0xb0:0x30001040,0xb4:0x30001050,0x10c:0x30001060})
        address=self.object({});self.put(address+0x88,data['address'])
        self.put(obj+0x80,address)
        for field,offset in FIELDS.items():self.put(obj+offset,self.attribute(data[field],field))
        groups=self.object({0x58:0x30001010})
        self.collections[groups]=[self.named(g['tag'],'group-'+str(i+1)) for i,g in enumerate(data['groups'])]
        self.put(obj+0xd0,groups)
        self.objects[obj]={'area':self.named(data['area'],'area'),
            'primary':self.named(data['primary'],'primary'),
            'secondary':self.named(data['secondary'],'secondary'),
            'groups':[g['used'] for g in data['groups']], 'address':data['address']}
        self.collections[self.manager].append(obj)
    def write_guard(self,u,access,address,size,value,user):
        require((address==0 and size==4) or 0x10000000<=address and address+size<=0x10400000 or
                0x20000000<=address and address+size<=0x20040000, 'Guest write outside fixture memory')
    def record(self,kind,**fields):
        require(len(self.calls)<4096,'Callback transcript limit')
        self.calls.append({'kind':kind,**fields})
    def hook(self,u,address,size,user):
        self.instructions+=1;require(self.instructions<=1000000,'Instruction limit')
        eax,edx,ecx,esp=(u.reg_read(reg) for reg in (EAX,EDX,ECX,ESP))
        pop=0
        if address in CALLBACKS:
            kind=CALLBACKS[address]
            if kind=='attribute-text':
                require(eax in self.attributes,'Foreign attribute')
                value,label=self.attributes[eax];self.put(edx,self.text(value));self.record(kind,field=label,value=value)
            elif kind=='collection-count':
                require(eax in self.collections,'Foreign collection');count=len(self.collections[eax]);u.reg_write(EAX,count)
                self.record(kind,count=count)
            elif kind=='output-add':
                require(eax==self.output and len(self.lines)<8,'Foreign/bounded output')
                value=self.read(edx);require(sum(len(v) for v in self.lines)+len(value)<=32768,'Output bound')
                self.lines.append(value);u.reg_write(EAX,len(self.lines)-1);self.record(kind,value=value)
            else:
                require(eax in self.objects,'Foreign unit');obj=self.objects[eax]
                if kind=='unit-group-used':
                    require(edx<len(obj['groups']),'Foreign group index');value=obj['groups'][edx]
                    u.reg_write(EAX,int(value));self.record(kind,index=edx,value=value)
                else:
                    name=kind[5:];u.reg_write(EAX,obj[name]);self.record(kind,address=obj['address'],present=bool(obj[name]))
        elif address in RTL:
            self.rtl[RTL[address]]=self.rtl.get(RTL[address],0)+1
            if address in (0x608924,0x608978):self.put(eax,self.text(self.read(edx)))
            elif address==0x608914:self.put(eax,0)
            elif address==0x60891c:
                require(edx<=32,'Clear array bound')
                for index in range(edx):self.put(eax+4*index,0)
            elif address==0x60890c:pass
            elif address==0x608a50:
                require(ecx<=32,'Integer text bound');self.put(eax,self.text(bytes(u.mem_read(edx,ecx)).decode('ascii')))
            elif address==0x608aa0:self.put(eax,self.text(chr(edx&65535)))
            elif address==0x608d48:self.put(eax,self.text(self.read(self.get(eax))+self.read(edx)))
            elif address==0x608e08:self.put(eax,self.text(self.read(edx)+self.read(ecx)))
            elif address==0x608eec:
                require(1<=edx<=4,'Concat arity')
                value=''.join(self.read(self.get(esp+4*i)) for i in range(edx,0,-1))
                self.put(eax,self.text(value));pop=edx*4
            elif address==0x609114:
                destination=self.get(esp+4);raw=self.read(eax).encode('utf-16le','surrogatepass')
                start=max(edx,1)-1;count=min(ecx,0x7fffffff)
                self.put(destination,self.text(raw[2*start:2*(start+count)].decode('utf-16le','surrogatepass')));pop=4
            elif address==0x6089b0:
                # The RTL returns an immutable zero wide-char buffer for nil.
                u.reg_write(EAX,eax or 0x30000100)
            elif address==0x60c470:
                number=self.get(eax+4);options=self.image.resources[number]
                require(len(options)==1,'Ambiguous resource');value=next(iter(options))
                self.put(edx,self.text(value));self.record('resource',id=number,value=value)
            elif address==0x847f7c:
                require(eax==self.image.word(0x85433c) and edx<26,'Foreign caption')
                self.put(ecx,self.text(self.image.captions[edx]));self.record('caption',ordinal=edx,value=self.image.captions[edx])
            elif address in (0xf2e08c,0xf28954):
                require(eax in self.collections and edx<len(self.collections[eax]),'Foreign item')
                u.reg_write(EAX,self.collections[eax][edx]);self.record(RTL[address],index=edx)
            else:raise HarnessError('Unimplemented fixture entry')
        else:
            item=self.image.instructions.get(address)
            require(item is not None,'Unapproved original address '+hex(address))
            name,raw=item;require(bytes(u.mem_read(address,len(raw)))==raw,'Changed original instruction')
            # Do not emulate a Delphi exception or enter any original handler.
            require(not 0xf30b51<=address<0xf30bad,'Unsupported original exception phase')
            self.executed[name]=self.executed.get(name,0)+1
            return
        u.reg_write(EIP,self.get(esp));u.reg_write(ESP,esp+4+pop)
    def call(self,address,eax,edx=0,ecx=0):
        self.put(0,0);self.put(0x20030000,0x30000000)
        for reg,value in ((ESP,0x20030000),(EAX,eax),(EDX,edx),(ECX,ecx),(FLAGS,2)):
            self.u.reg_write(reg,value)
        self.u.emu_start(address,0x30000000,timeout=3000000,count=1000000)
        require(self.u.reg_read(EIP)==0x30000000,'Incomplete original return')
    def evidence(self):
        return {'rows':self.lines,'provider_calls':self.calls,'executed_original':self.executed,
                'fixture_runtime_calls':self.rtl,'instructions':self.instructions,'heap_bytes':self.heap-0x10000000}


def validate(case):
    require(type(case) is dict and type(case.get('id')) is str and len(case['id'])<=80,'Case identity')
    if case.get('kind')=='quote':
        require(set(case)=={'id','kind','text','expected'},'Quote schema')
        require(type(case['text']) is str and len(case['text'].encode('utf-16le','surrogatepass'))<=512,'Quote bound')
    else:
        require(case.get('kind')=='rows' and set(case)=={'id','kind','mask','units','expected'},'Row schema')
        require(type(case['mask']) is int and 0<=case['mask']<2**32,'Mask bound')
        require(type(case['units']) is list and len(case['units'])<=3,'Unit bound')
        for unit in case['units']:
            require(type(unit) is dict and set(unit)==set(SCALARS)|{'address','primary','secondary','area','groups'},'Unit schema')
            require(type(unit['address']) is int and 0<=unit['address']<=255,'Unit address')
            for field in SCALARS+('primary','secondary','area'):
                value=unit[field]
                require((field in ('primary','secondary','area') and value is None) or
                        type(value) is str and len(value.encode('utf-16le','surrogatepass'))<=512,'Unit string bound')
            require(type(unit['groups']) is list and len(unit['groups'])<=16,'Group bound')
            for group in unit['groups']:
                require(type(group) is dict and set(group)=={'used','tag'} and type(group['used']) is bool and
                        type(group['tag']) is str and len(group['tag'].encode('utf-16le','surrogatepass'))<=512,'Group schema')
    require(case['expected'] is None or type(case['expected']) in (str,list),'Expected literal schema')


def main():
    global EXE
    require(len(sys.argv) == 4, 'Expected cases, new output directory and exact original EXE')
    EXE = Path(sys.argv[3]).resolve(strict=True)
    input_path=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(exist_ok=False)
    raw=input_path.read_bytes();require(len(raw)<=256*1024,'Input bound')
    cases=json.loads(raw);require(type(cases) is list and 1<=len(cases)<=128,'Case count')
    for case in cases:validate(case)
    require(len({c['id'] for c in cases})==len(cases),'Duplicate case IDs')
    image=Image();started=time.monotonic()
    inputs={'probe':digest(Path(__file__).read_bytes()),'cases':digest(raw),'executable':digest(image.raw)}
    (out/'probe.py').write_bytes(Path(__file__).read_bytes());(out/'cases.json').write_bytes(raw)
    report={'format':'cbus-original-csv-instruction-pilot-v1','passed':False,'inputs':inputs,
            'python':sys.version,'pefile':pefile.__version__,'unicorn':unicorn.__version__,
            'capstone':capstone.__version__,
            'actual_libraries':{str(Path(lib).resolve()):digest(Path(lib).read_bytes()) for lib in
                                (capstone._cs._name,unicorn_core.uclib._name)},
            'original_spans':image.spans,'results':[],
            'scope':{'raw_serializer':True,'runtime_and_cached_providers_are_fixtures':True,
                     'original_constructors':False,'database_projection_verified':False,
                     'native_imports':False,'registry':False,'network':False,'file_writer':False,
                     'windows_codepage_verified':False,'original_exception_path_verified':False}}
    primary=None
    try:
        for case in cases:
            require(time.monotonic()-started<60,'Whole pilot bound')
            machine=Machine(image);row={'id':case['id'],'completed':False};report['results'].append(row)
            try:
                if case['kind']=='quote':
                    destination=machine.alloc(4)
                    machine.call(0x7b7b84,machine.text(case['text']),destination)
                    actual=machine.read(machine.get(destination));row['quoted']=actual
                else:
                    for unit in case['units']:machine.unit(unit)
                    saved_size=machine.heap-0x10000000
                    saved=bytes(machine.u.mem_read(0x10000000,saved_size))
                    machine.call(0xf306bc,machine.manager,machine.output,case['mask']);actual=machine.lines
                    require(bytes(machine.u.mem_read(0x10000000,saved_size))==saved,'Source fixture mutation')
                    row['initial_fixture_bytes_unchanged']=True
                    row['initial_fixture_bytes']=saved_size
                row['completed']=True
                if case['expected'] is not None:require(actual==case['expected'],'Independent literal mismatch '+case['id'])
            except BaseException as error:
                row['error']=safe_error(error);raise
            finally:
                pending=sys.exc_info()[1]
                try:row.update(machine.evidence())
                except BaseException:
                    if pending is None:raise
        require(digest(EXE.read_bytes())==inputs['executable'] and digest(input_path.read_bytes())==inputs['cases'] and
                digest(Path(__file__).read_bytes())==inputs['probe'],'Input changed during observation')
        report['passed']=True
    except BaseException as error:
        primary=error;report['error']=safe_error(error);raise
    finally:
        try:
            report['elapsed_seconds']=time.monotonic()-started
            data=json.dumps(report,ensure_ascii=True,indent=2)+'\n'
            stream=(out/'report.json').open('x');write_error=None
            try:stream.write(data)
            except BaseException as error:write_error=error;raise
            finally:
                try:stream.close()
                except BaseException:
                    if write_error is None:raise
        except BaseException:
            if primary is None:raise
    print(json.dumps({'passed':report['passed'],'cases':len(report['results']),'output':str(out)}))


if __name__=='__main__':main()
