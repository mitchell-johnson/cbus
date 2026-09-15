"""HELD original-instruction cached CSV pilot; explicit providers, no native I/O.

This is not the original unit/group constructor or arbitrary database XML load.
The exact reviewed admission file is required before any emulation.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path
import re
import struct
import sys
import time

BASE = Path(__file__).resolve().parent
REPO = Path('/Users/mitchell/source/cbus/toolkit-cli')
ORIGINAL = REPO/'research/vendor/toolkit/app/CBusToolkit.exe'
MAP = ORIGINAL.with_suffix('.map')
SERIALIZER = REPO/'research/NativeToolkitDatabaseCSVProbe.py'
SERIALIZER_SHA = '4439ac0052d822fcd912c5235f748ff392871006adfca6ccdb7dc8ff4ec81e52'
EXE_SHA = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
MAP_SHA = 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
# Exact MAP starts. A separate preparation pass records bounded complete spans,
# direct call targets and instruction bytes; no vendor code executes in preparation.
EXTRA = {
 0x605938:'ValLong',0x606414:'IsClass',0x606438:'AsClass',0x6064e8:'InheritsFrom',
 0x6186e4:'UpperCase-Unicode',0x619bac:'StrToIntDef',
 0x768268:'BeginUpdate',0x768278:'BaseChanged',0x7682a4:'EndUpdate',0x7682c8:'GetUpdating',
 0x76a3cc:'ManagedChanged',0x76a444:'ResolveChange',
 0x7b6ff8:'PosChar',0x7b70b8:'StringToken',0x7b7394:'StringCompareToken',
 0x7b747c:'VersionTokenCompare',0x7b74ec:'VersionStringCompare',
 0x7dd428:'CustomReferenceGet',0x7dda60:'ReferenceAttributeGet',0x7ddbf4:'ReferenceAttributeSet',
 0x7e12e0:'CachedAttributeByName',0x7e13c4:'CachedAttributeByIndex',
 0x7e4200:'ReferenceFromObject',0x7ea9dc:'GetWorkspace',0x7eab5c:'GetSessionID',0x7ec4e8:'GetOID',
 0x7ec640:'AttributeChange',0x7ec674:'CanModifyValue',0x7eca04:'AttributeChanged',
 0x7ecd00:'AttributeInitialize',0x7ece44:'AttributeBeginUpdate',0x7ece6c:'AttributeEndUpdate',
 0x7ed3a0:'ReferenceGet',0x7ed41c:'ResolveReference',0x7ed6d4:'ReferenceSet',
 0x7ef878:'SubscribeReference',0x7ef9f4:'UnsubscribeReference',
 0x7f409c:'StorageSave',0x7f4160:'StorageLoad',
 0xc1a6e8:'FirmwareWithinLimits',0xc1a78c:'RegistrationItem',0xc1a7b0:'GetUnit',
 0xd236e0:'AreaAddressGet',0xd23704:'RelayArea',0xd23dfc:'AreaAddressSet',0xd243bc:'RelayInteraction',
 0xf288f0:'GroupAdd',0xf28b68:'GroupByAddress',0xf28d10:'GroupByAddressExclude',
 0xf2ebc0:'PrimaryApplication',0xf2ebf0:'SecondaryApplication',0xf2ffe0:'GenericInteraction',
 0xf305a8:'SetUnitType',0xf34104:'CreateFlashObject',0xf34770:'GenericArea',
 0xf47d64:'SetAddress',0x101ac50:'Relay4MaxChannels',
}
PROVIDERS = {
 0x30001100:'cached-parent',0x30001110:'cached-name-find',0x30001120:'cached-name-index',
 0x30001130:'cached-value-index',0x30001140:'cached-string-index',
 0x30001150:'variant-attribute-write',0x30001160:'group-collection-add',
 0x30001170:'storage-load',0x30001180:'storage-save',0x30001190:'workspace-name',
}
FIXTURES = {0x608cb0:'UStrSetLength',0x60bca4:'IntfClear-nil',
 0x62f294:'VariantFromInt',0x62f578:'VariantFromUStr',0x629f1c:'VariantClear',
 0x64393c:'TList-owned-Get',0x7ea6ac:'CreateInWorkspace-owned-return',
 0x7e3f90:'FlashStudio-owned-constructor-return',0x606200:'Free-owned-studio',
 0x7f07e4:'ReferenceList-owned-Add',0x7f0808:'ReferenceList-owned-Remove',
 0x7f0c50:'ReferenceList-owned-IndexOf'}


def sha(raw): return hashlib.sha256(raw).hexdigest()
def fail(condition, message):
    if not condition: raise RuntimeError(message)
def safe_error(error):
    try: message=str(error)
    except BaseException: message='<unprintable>'
    return {'type':type(error).__name__,'message':message[:2048]}
def bounded(path, limit):
    # Nonblocking descriptor admission prevents FIFO/device paths from stalling
    # before the child deadline. No-follow rejects a final symlink component.
    descriptor=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);first=None
    try:
        info=os.fstat(descriptor)
        fail(stat.S_ISREG(info.st_mode),'Regular input required: '+str(path))
        fail(info.st_size<=limit,'Input byte bound: '+str(path))
        chunks=[];size=0
        while size<=limit:
            chunk=os.read(descriptor,min(65536,limit+1-size))
            if not chunk:break
            chunks.append(chunk);size+=len(chunk)
        fail(size<=limit,'Input byte bound: '+str(path))
        return b''.join(chunks)
    except BaseException as error:first=error;raise
    finally:
        try:os.close(descriptor)
        except BaseException:
            if first is None:raise


def load_support(exe, map_raw):
    support_raw=bounded(SERIALIZER,64*1024)
    fail(sha(support_raw)==SERIALIZER_SHA,'Frozen serializer helper changed')
    spec=importlib.util.spec_from_file_location('csv_projection_serializer_fixture',SERIALIZER)
    module=importlib.util.module_from_spec(spec);exec(compile(support_raw,str(SERIALIZER),'exec'),module.__dict__)
    fail(sha(bounded(SERIALIZER,64*1024))==SERIALIZER_SHA,'Serializer changed during import')
    class FrozenOriginal:
        def read_bytes(self): return exe
    module.EXE=FrozenOriginal()
    image=module.Image()
    starts=set()
    for line in map_raw.decode('ascii').splitlines():
        match=re.match(r'^\s+0001:([0-9A-Fa-f]{8})\s+(\S+)\s*$',line)
        if match: starts.add(int(match[1],16)+0x601000)
    starts=sorted(starts)
    decoder=module.capstone.Cs(module.capstone.CS_ARCH_X86,module.capstone.CS_MODE_32)
    image.extra_calls=[];image.finally_continuations=[]
    for start,name in EXTRA.items():
        fail(start in starts,'Unknown MAP entry')
        end=next(x for x in starts if x>start)
        fail(0<end-start<=4096,'Original method span bound')
        raw=image.pe.get_data(start-image.base,end-start)
        # Deliberate static span can include trailing padding/inline literals;
        # admit only decoded addresses up to the last reachable instruction.
        pending=[start];decoded={}
        while pending:
            address=pending.pop()
            if address in decoded: continue
            fail(start<=address<end,'Original branch leaves declared method '+name+' '+hex(address)+' '+hex(end))
            instruction=next(decoder.disasm(image.pe.get_data(address-image.base,16),address,count=1),None)
            fail(instruction is not None and address+instruction.size<=end,'Bounded original instruction decode')
            fail(instruction.mnemonic not in ('int','syscall','sysenter','in','out','hlt'),'Forbidden original opcode')
            decoded[address]=instruction
            # Delphi's normal finally restores FS, pushes its continuation,
            # falls through the cleanup body and uses RET to that continuation.
            # Only this exact source instruction pattern is admitted; exception
            # dispatcher targets remain excluded.
            if instruction.mnemonic=='push' and re.fullmatch(r'0x[0-9a-f]+',instruction.op_str) and image.pe.get_data(address-image.base-3,3)==b'\x64\x89\x10':
                target=int(instruction.op_str,16)
                fail(start<=target<end,'Finally continuation outside method')
                image.finally_continuations.append({'push':hex(address),'target':hex(target),'method':name})
                pending.append(target)
            if instruction.mnemonic.startswith('ret'): continue
            if instruction.mnemonic=='jmp':
                if instruction.op_str in ('0x606c24','0x604a8c'): continue # excluded exception/invalid-cast targets
                fail(re.fullmatch(r'0x[0-9a-f]+',instruction.op_str) is not None,'Indirect jump excluded')
                pending.append(int(instruction.op_str,16));continue
            if instruction.mnemonic.startswith('j') or instruction.mnemonic.startswith('loop'):
                fail(re.fullmatch(r'0x[0-9a-f]+',instruction.op_str) is not None,'Branch address format')
                if instruction.op_str not in ('0x606c24','0x604a8c'):pending.append(int(instruction.op_str,16))
            pending.append(address+instruction.size)
            if instruction.mnemonic=='call': image.extra_calls.append({'from':hex(address),'target':instruction.op_str,'method':name})
        for address,instruction in decoded.items():
            fail(address not in image.instructions,'Overlapping original method declarations')
            image.instructions[address]=(name,instruction.bytes)
        image.spans.append({'name':name,'start':hex(start),'end_bound':hex(end),'span_sha256':sha(raw),
                            'instruction_count':len(decoded),'instructions_sha256':sha(b''.join(struct.pack('<I',a)+bytes(decoded[a].bytes) for a in sorted(decoded)))})
    fail(all(int(row['target'],16) in image.instructions for row in image.finally_continuations),'Every normal finally continuation admitted')
    fail(all(address in image.instructions for address in (0xf47dbe,0xc1a8d5,0x7ed855,0xf28cce,0x7dda85,0x7ddcb3)),'Required normal terminal instruction admission')
    return module,image


class DeclaredStop(Exception): pass


def machine_type(m):
    class CachedMachine(m.Machine):
        def __init__(self,image,case):
            super().__init__(image)
            self.case=case;self.phase='setup';self.live_studios=set();self.variants={};self.address_attributes={}
            self.ref_lists={};self.reference_attributes={};self.agents={};self.labels={};self.created=[];self.loads=[];self.saves=[]
            self.unit_obj=0;self.selected_class=None;self.return_observers={}
            self.workspace=self.object({0x20:0x30001190});self.labels[self.workspace]='owned-workspace'
            self.registration=self.object({});self.put(self.registration+0x18,self.text('RELAY4'))
            self.put(self.registration+0x1c,0x101aab4);self.put(self.registration+0x20,self.text('0'));self.put(self.registration+0x24,self.text('9'))
            self.registrations=self.object({});self.collections[self.registrations]=[self.registration]
            self.factory=self.object({0x0c:0x30001010});self.collections[self.factory]=[self.registration]
            self.put(self.factory+0x18,self.registrations);self.put(self.factory+0x20,self.workspace)
            self.factory_cell=self.alloc(4);self.put(self.factory_cell,self.factory)
            # Original indirect singleton slot receives only this owned pointer.
            # Host setup writes data, never instruction bytes; protection remains RX.
            self.u.mem_write(0x13c3eb0,struct.pack('<I',self.factory_cell))
            self.cached=self.real_object(image.word(0x7df4c0),'cached-record')
            self.cached_names=self.object({0x9c:0x30001110,0x18:0x30001120})
            self.cached_values=self.object({0x18:0x30001130,0x0c:0x30001140})
            self.put(self.cached+0x10,self.cached_names);self.put(self.cached+0x14,self.cached_values)
            parent=self.object({0x38:0x30001100});self.builder=self.object({});self.put(self.builder+4,parent)
            self.parent=parent;self.supplied_input_sha256=sha(json.dumps(case,sort_keys=True).encode())
        def real_object(self,vmt,label):
            obj=self.alloc(0x200);self.put(obj,vmt);self.labels[obj]=label
            self.put(obj+0x44,self.workspace);self.put(obj+0x4c,len(self.labels)+100)
            self.put(obj+0x58,self.attribute('OID-'+label,'oid-'+label))
            self.u.mem_write(obj+0x1c,b'\x01')
            return obj
        def attr(self,value,label):
            obj=self.attribute(value,label);self.put(self.get(obj)+0x7c,0x30001150);return obj
        def address(self,owner,value):
            obj=self.object({0x7c:0x30001150});self.put(obj+0x88,value)
            self.address_attributes[obj]=owner;self.put(owner+0x80,obj)
        def reference_attribute(self,owner,offset,target,label):
            attr=self.real_object(0x7dd8b0,'attribute-'+label)
            ref=self.object({});self.labels[ref]='reference-'+label
            self.put(ref+0x18,target);self.u.mem_write(ref+0x40,bytes([3 if target else 0]))
            if target:
                self.put(ref+0x3c,self.text('OID-'+self.labels[target]));self.put(ref+0x60,self.workspace);self.put(ref+0x64,self.get(target+0x4c))
            self.put(attr+0x78,ref);self.put(owner+offset,attr);self.reference_attributes[attr]=ref
            return attr
        def agent(self,owner,kind):
            agent=self.object({0x94:0x30001170,0x88:0x30001180})
            self.u.mem_write(agent+0x7c,b'\x01');self.put(owner+0x78,agent)
            self.agents[agent]=(owner,kind);return agent
        def group(self,address,label,created=False):
            obj=self.real_object(0xf23d2c,label);self.address(obj,address)
            tag='<Unused>' if address==255 else ('G'+str(address) if address<=8 else 'Area'+str(address))
            self.put(obj+0x9c,self.attr('' if created else tag,'tag-'+label))
            links=self.object({});items=self.object({});self.put(links+4,items);self.ref_lists[items]=[]
            self.put(obj+0x50,links);self.ref_lists[links]=self.ref_lists[items]
            self.agent(obj,'group');return obj
        def construct_unit(self,vmt):
            fail(not self.unit_obj,'Multiple unit constructors')
            obj=self.real_object(vmt,'unit');self.unit_obj=obj
            self.selected_class={0x101aab4:'TRELAY4',0xc1a320:'TCBusUnitGeneric'}[vmt]
            self.address(obj,4)
            values={'part_name':'Owned part','tag_name':'Owned unit','unit_type':self.case['type'],
                    'catalog':'OWNED','serial':'','firmware':self.case['firmware']}
            for key,offset in m.FIELDS.items():self.put(obj+offset,self.attr(values[key],key))
            app_vmt=self.image.word(0xf2338c)
            self.primary=self.real_object(app_vmt,'primary');self.secondary=self.real_object(app_vmt,'secondary')
            for app,label in [(self.primary,'Lighting'),(self.secondary,'Secondary')]:self.put(app+0x9c,self.attribute(label,'app-'+label))
            self.groups=self.object({0x58:0x30001010,0x68:0x30001160});self.labels[self.groups]='primary-groups'
            self.put(self.groups+0x30,self.primary);self.put(self.primary+0xb4,self.groups)
            by_address={a:self.group(a,'group-'+str(a)) for a in self.case['cache_addresses']}
            self.collections[self.groups]=list(by_address.values())
            self.unit_groups=self.object({0x58:0x30001010});self.collections[self.unit_groups]=[by_address[a] for a in range(1,9)]
            self.put(obj+0xd0,self.unit_groups)
            self.reference_attribute(obj,0xbc,self.primary,'primary')
            self.reference_attribute(obj,0xc0,self.secondary,'secondary')
            self.area_attribute=self.reference_attribute(obj,0x1a0,0,'area') if vmt==0x101aab4 else None
            if vmt==0x101aab4:self.put(obj+0x160,self.text(self.case['raw_area']))
            self.agent(obj,'unit')
            self.collections[self.manager].append(obj)
            self.objects[obj]={'address':4}
            return obj
        def snapshot(self):
            if not self.unit_obj:return {'unit':None,'selected_class':self.selected_class}
            obj=self.unit_obj;ref=self.reference_attributes[self.area_attribute] if self.area_attribute is not None else 0
            groups=[]
            for g in self.collections[self.groups]:
                groups.append({'object':self.labels[g],'address':self.get(self.get(g+0x80)+0x88),
                               'tag':self.attributes[self.get(g+0x9c)][0],
                               'oid':self.attributes[self.get(g+0x58)][0],
                               'reference_list':[self.labels.get(v,hex(v)) for v in self.ref_lists[self.get(g+0x50)]], 'raw_object_hex':bytes(self.u.mem_read(g,0x200)).hex()})
            return {'selected_class':self.selected_class,'unit_vmt':hex(self.get(obj)),
                    'raw_unit_hex':bytes(self.u.mem_read(obj,0x200)).hex(), 'raw_area':self.read(self.get(obj+0x160)) if ref else None,'area_target':self.labels.get(self.get(ref+0x18)) if ref else None,
                    'area_reference_state':self.u.mem_read(ref+0x40,1)[0] if ref else None,
                    'area_reference_token':self.read(self.get(ref+0x3c)) if ref else None,
                    'area_reference_workspace':self.get(ref+0x60)==self.workspace if ref else None,
                    'area_attribute_changed':self.u.mem_read(self.area_attribute+0x38,1)[0] if ref else None,
                    'area_attribute_update_count':self.get(self.area_attribute+0x10) if ref else None,
                    'raw_references':{self.labels[a]:{'attribute_hex':bytes(self.u.mem_read(a,0x200)).hex(),'reference_hex':bytes(self.u.mem_read(r,0x100)).hex()} for a,r in self.reference_attributes.items()},
                    'groups':groups,'fields':{k:self.attributes[self.get(obj+o)][0] for k,o in m.FIELDS.items()}}
        def record(self,kind,**values):
            super().record(kind,phase=getattr(self,'phase','setup'),**values)
        def return_from_provider(self,eax=None,pop=0):
            esp=self.u.reg_read(m.ESP)
            if eax is not None:self.u.reg_write(m.EAX,eax&0xffffffff)
            self.u.reg_write(m.EIP,self.get(esp));self.u.reg_write(m.ESP,esp+4+pop)
        def hook(self,u,address,size,user):
            if address not in PROVIDERS and address not in FIXTURES:
                if address in (0xd23704,0xf34770):self.record('original-area-enter',method=hex(address),state=self.snapshot())
                if address in (0xd2377e,0xf34784):self.record('original-area-return',method=hex(address),state=self.snapshot())
                if address in (0xd243bc,0xf2ffe0):self.record('original-interaction-enter',index=u.reg_read(m.EDX),method=hex(address))
                return super().hook(u,address,size,user)
            self.instructions+=1;fail(self.instructions<=1000000,'Instruction limit')
            eax,edx,ecx,esp=(u.reg_read(reg) for reg in (m.EAX,m.EDX,m.ECX,m.ESP))
            kind=PROVIDERS.get(address) or FIXTURES[address];pop=0;result=None
            if address in FIXTURES:
                # Callsite is still an exact original instruction; no imports or
                # arbitrary calls can use a provider's business meaning.
                self.rtl[kind]=self.rtl.get(kind,0)+1
            if kind=='cached-parent':
                fail(eax==self.parent,'Foreign cached parent');result=self.cached
            elif kind=='cached-name-find':
                fail(eax==self.cached_names,'Foreign cached names');name=self.read(edx)
                fail(name in ('UNITTYPE','FIRMWAREVERSION'),'Unapproved cached field')
                self.put(ecx,('FIRMWAREVERSION','UNITTYPE').index(name));result=1;self.record(kind,name=name,sorted_name_index=('FIRMWAREVERSION','UNITTYPE').index(name))
            elif kind=='cached-name-index':
                fail(eax==self.cached_names and edx in (0,1),'Foreign cached name index');result=1-edx;self.record(kind,sorted_name_index=edx,value_index=result)
            elif kind=='cached-value-index':
                fail(eax==self.cached_values and edx in (0,1),'Foreign cached value index');result=0
            elif kind=='cached-string-index':
                fail(eax==self.cached_values and edx in (0,1),'Foreign cached string index')
                value=self.case['type' if edx==0 else 'firmware'];self.put(ecx,self.text(value));self.record(kind,index=edx,value=value)
            elif kind=='UStrSetLength':
                fail(edx<=256,'String allocation bound');self.put(eax,self.text('\0'*edx))
            elif kind=='IntfClear-nil':
                fail(self.get(eax)==0,'Non-nil interface excluded');self.put(eax,0)
            elif kind=='TList-owned-Get':
                fail(eax==self.registrations and edx==0,'Foreign registration item');result=self.registration
            elif kind=='VariantFromInt':
                fail(ecx&255==252,'Variant integer fixture type');self.variants[eax]=('int',edx)
            elif kind=='VariantFromUStr':self.variants[eax]=('str',self.read(edx))
            elif kind=='VariantClear':
                fail(eax in self.variants or bytes(u.mem_read(eax,16))==bytes(16),'Unknown variant clear');self.variants.pop(eax,None)
            elif kind=='variant-attribute-write':
                fail(edx in self.variants,'Unknown variant write');typ,value=self.variants[edx]
                if eax in self.address_attributes:
                    fail(typ=='int' and value==255,'Only created255 address write admitted');self.put(eax+0x88,value)
                else:
                    fail(eax in self.attributes and typ=='str','Foreign text attribute write')
                    old,label=self.attributes[eax]
                    fail(label=='unit_type' or label.startswith('tag-created-'),'Unexpected attribute mutation')
                    self.attributes[eax]=(value,label)
                self.record(kind,attribute=hex(eax),value=value)
            elif kind=='CreateInWorkspace-owned-return':
                fail(edx&255==1 and ecx==self.workspace and self.get(esp+4)==0 and self.get(esp+8)==1,'Constructor arguments')
                caller=self.get(esp)
                if eax in (0x101aab4,0xc1a320):
                    fail(caller in (0xc1a87a,0xc1a89d),'Unit constructor caller')
                    result=self.construct_unit(eax)
                else:
                    fail(eax==0xf23d2c and caller==0xf28916 and not self.created,'Group constructor admission')
                    result=self.group(0,'created-255',created=True);self.created.append(result)
                self.record(kind,class_vmt=hex(eax),workspace='owned-workspace',dl=edx&255,stack_arguments=[0,1],caller=hex(caller),returned=self.labels[result]);pop=8
            elif kind=='group-collection-add':
                fail(eax==self.groups and edx in self.created and edx not in self.collections[eax],'Group collection add admission')
                self.collections[eax].append(edx);self.record(kind,object=self.labels[edx])
            elif kind in ('storage-load','storage-save'):
                fail(eax in self.agents,'Foreign storage agent');owner,owner_kind=self.agents[eax]
                fail(ecx in (0,1),'Storage argument count')
                args=[self.read(self.get(edx+4*i)) for i in range(ecx+1)]
                if kind=='storage-load':
                    fail(owner==self.unit_obj and owner_kind=='unit' and args==['QuickGet','Parameter=AreaGroupAddress'] and len(self.loads)<2,'StorageLoad admission')
                    index=len(self.loads);before=self.snapshot();value=self.case['quick_get'][index]
                    entry={'arguments':args,'owner':'unit','before':before,'supplied_raw_area':value,'returned':False};self.loads.append(entry)
                    self.record(kind,arguments=args,owner='unit',ordinal=index)
                    if self.case['deny']=='load':raise DeclaredStop('Explicit owned storage load denied')
                    self.put(owner+0x160,self.text(value));entry['after']=self.snapshot();entry['returned']=True
                else:
                    fail(owner in self.created and owner_kind=='group' and args==['GroupSave'] and not self.saves,'StorageSave admission')
                    self.saves.append({'arguments':args,'owner':self.labels[owner],'state':self.snapshot(),'returned':False})
                    self.record(kind,arguments=args,owner=self.labels[owner])
                    if self.case['deny']=='save':raise DeclaredStop('Explicit owned storage save denied')
                    self.saves[-1]['returned']=True
            elif kind=='FlashStudio-owned-constructor-return':
                fail(eax==self.image.word(0x7e3ce4) and edx&255==1,'Unexpected Studio constructor')
                result=self.object({});self.live_studios.add(result);self.record(kind,object=hex(result))
            elif kind=='Free-owned-studio':
                fail(eax in self.live_studios,'Unowned original free');self.live_studios.remove(eax);self.record(kind,object=hex(eax))
            elif kind=='workspace-name':
                fail(eax==self.workspace,'Foreign workspace name');self.put(edx,0);self.record(kind,value='')
            elif kind=='ReferenceList-owned-Add':
                fail(eax in self.ref_lists and edx in self.reference_attributes.values(),'Foreign reference Add')
                fail(edx not in self.ref_lists[eax],'Duplicate reference Add excluded')
                self.ref_lists[eax].append(edx);self.record(kind,reference=self.labels[edx])
            elif kind=='ReferenceList-owned-Remove':
                fail(eax in self.ref_lists and edx in self.ref_lists[eax],'Foreign reference Remove')
                self.ref_lists[eax].remove(edx);self.record(kind,reference=self.labels[edx])
            elif kind=='ReferenceList-owned-IndexOf':
                fail(eax in self.ref_lists and edx in self.reference_attributes.values(),'Foreign reference IndexOf')
                result=self.ref_lists[eax].index(edx) if edx in self.ref_lists[eax] else 0xffffffff
            else:raise RuntimeError('Unimplemented provider')
            self.return_from_provider(result,pop)
        def evidence(self):
            return {**super().evidence(),'selected_class':self.selected_class,'storage_loads':self.loads,
                    'storage_saves':self.saves,'created_groups':[self.labels[x] for x in self.created],
                    'terminal':self.snapshot(),'live_studios':len(self.live_studios)}
    return CachedMachine


def validate_cases(cases):
    fail(type(cases) is list and len(cases)==12,'Exactly twelve prepared cases')
    keys={'id','type','firmware','raw_area','quick_get','cache_addresses','columns','deny','class','expected_area',
          'expected_loads','expected_creations','expected_saves','expected_complete','expected_rows'}
    for c in cases:
        fail(type(c) is dict and set(c)==keys,'Exact case schema')
        fail(type(c['id']) is str and re.fullmatch('[a-z0-9-]{1,80}',c['id']),'Case id')
        for k in ('type','firmware','raw_area'):
            fail(type(c[k]) is str and len(c[k])<=32 and c[k].isascii() and '\0' not in c[k],'Cached string domain')
        fail(c['type'] in ('RELAY4','relay4','OWNED_UNKNOWN') and c['firmware'] in ('0','4.4','9','10','9.1'),'Finite factory input')
        fail(type(c['quick_get']) is list and len(c['quick_get'])==2 and all(type(x) is str and x in ('12','13','255','invalid') for x in c['quick_get']),'Supplied QuickGet sequence')
        fail(c['cache_addresses'] in ([1,2,3,4,5,6,7,8,12,13],[1,2,3,4,5,6,7,8,12,13,255]),'Exact ordered group cache')
        fail(all(type(x) is int for x in c['cache_addresses']),'Exact cache integer types')
        fail(c['columns'] in ('all','address') and c['deny'] in (None,'load','save'),'Finite action choices')
        fail(type(c['expected_complete']) is bool and all(type(c[k]) is int for k in ('expected_loads','expected_creations','expected_saves')),'Expected result types')
        fail(c['expected_rows'] is None or type(c['expected_rows']) is list and len(c['expected_rows'])==2 and all(type(x) is str and len(x)<=2048 for x in c['expected_rows']),'Literal expected rows')
    fail(len({c['id'] for c in cases})==12,'Distinct cases')


def finish(path,report,first):
    try:
        raw=(json.dumps(report,ensure_ascii=True,indent=2)+'\n').encode('utf-8')
        fail(len(raw)<=8*1024*1024,'Report bound')
        pending=path.with_name('report.pending.json');stream=pending.open('xb');write_error=None
        try:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        except BaseException as error:write_error=error;raise
        finally:
            try:stream.close()
            except BaseException:
                if write_error is None:raise
        os.replace(pending,path)
    except BaseException:
        if first is None:raise


def admit_output(out):
    fail(not out.exists() and not out.is_symlink() and not out.parent.is_symlink(),
         'New nonsymlink owned output required')
    parent=out.parent.resolve(strict=True)
    direct=parent==BASE
    capture=out.name=='capture' and parent.parent==BASE and (parent/'launch-owned.json').is_file() and not (parent/'launch-owned.json').is_symlink()
    prospective=out.resolve(strict=False)
    fail((direct or capture) and prospective==parent/out.name and prospective.is_relative_to(BASE),
         'New direct owned output required')


def main():
    fail(sys.version_info[:2] in ((3,10),(3,13)),'Research runtime must be Python3.10 or3.13')
    fail(len(sys.argv)==3 and sys.argv[1] in ('prepare','execute'),'Expected prepare|execute and new output')
    mode=sys.argv[1];out=Path(sys.argv[2]);admit_output(out)
    own=json.loads(bounded(BASE.parent/'ownership.json',4096));fail(own.get('task')=='/root/project_store' and own.get('owner_token')=='b0f8078731a54cc4aa069f00b043d210' and own.get('root')==str(BASE.parent),'Owned external root')
    inputs={p:bounded(p,64*1024*1024 if p in (ORIGINAL,MAP) else 1024*1024) for p in (ORIGINAL,MAP,SERIALIZER,Path(__file__),BASE/'cases.json')}
    fail(sha(inputs[ORIGINAL])==EXE_SHA and sha(inputs[MAP])==MAP_SHA and sha(inputs[SERIALIZER])==SERIALIZER_SHA,'Exact original/helper pins')
    cases=json.loads(inputs[BASE/'cases.json']);validate_cases(cases)
    if mode=='execute':
        admission=json.loads(bounded(BASE/'admission.json',4096))
        fail(admission=={'format':'csv-projection-admission-v1','probe_sha256':sha(inputs[Path(__file__)]),'cases_sha256':sha(inputs[BASE/'cases.json']), 'authorization':'root-reviewed-cached-csv-pilot12-v1'},'Explicit reviewed admission mismatch')
    admit_output(out);out.mkdir();report={'format':'cbus-original-cached-csv-pilot-v1','capture_complete':False,'original_execution':mode=='execute','inputs':{str(p):sha(v) for p,v in inputs.items()},'results':[],'scope':{'original_full_unit_constructors':False,'arbitrary_xml_projection':False,'original_storage_backend':False,'reference_event_publishers':False,'native_io':False,'supplied_cached_and_storage_primitives':True}}
    first=None
    try:
        m,image=load_support(inputs[ORIGINAL],inputs[MAP]);report['spans']=image.spans;report['direct_calls']=image.extra_calls;report['finally_continuations']=image.finally_continuations
        report['runtime']={'python':sys.version,'executable':str(Path(sys.executable).resolve()),'executable_sha256':sha(bounded(Path(sys.executable).resolve(),64*1024*1024)),
           'libraries':{str(Path(x).resolve()):sha(bounded(Path(x).resolve(),64*1024*1024)) for x in (m.capstone._cs._name,m.unicorn_core.uclib._name)},'versions':{'capstone':m.capstone.__version__,'unicorn':m.unicorn.__version__,'pefile':m.pefile.__version__}}
        fail(set(report['runtime']['libraries'].values())=={'016084c6e70d929249a2abb22f1afda95095294e6cd70f509964ffc54006bf94','7207c8e3d7a63118fb0bca73e01816797fd51b1d8a39a4cbc7abfd562ee59c85'},'Accepted emulation-library pins')
        if mode=='execute':
            launch=json.loads(bounded(out.parent/'launch-owned.json',4096))
            fail(launch=={'format':'csv-cached-owned-launch-v1','owner_token':'b0f8078731a54cc4aa069f00b043d210','probe_sha256':sha(inputs[Path(__file__)]),'cases_sha256':sha(inputs[BASE/'cases.json'])},'Owned archived launcher association')
        if mode=='prepare':report['preparation_complete']=True
        else:
            started=time.monotonic();M=machine_type(m)
            for case in cases:
                fail(time.monotonic()-started<60,'Whole emulation bound')
                machine=M(image,case);row={'id':case['id'],'case':case,'completed':False};report['results'].append(row)
                try:
                    machine.phase='factory';machine.call(0xf34104,machine.builder)
                    fail(machine.u.reg_read(m.EAX)==machine.unit_obj and machine.selected_class==case['class'],'Original factory selection mismatch')
                    row['after_factory']=machine.snapshot();machine.phase='csv'
                    try:
                        machine.call(0xf306bc,machine.manager,machine.output,0x3ffffff if case['columns']=='all' else 1)
                        row['completed']=True
                    except DeclaredStop as error:
                        row['declared_stop']=safe_error(error)
                        fail(case['deny'] is not None,'Unexpected declared stop')
                    fail(row['completed']==case['expected_complete'],'Completion expectation')
                    fail(len(machine.loads)==case['expected_loads'] and len(machine.saves)==case['expected_saves'] and len(machine.created)==case['expected_creations'],'Storage/create count expectation')
                    if row['completed']:
                        fail(machine.lines==case['expected_rows'],'Independent literal CSV mismatch')
                        target=machine.get(machine.reference_attributes[machine.area_attribute]+0x18) if machine.area_attribute is not None else 0
                        area=machine.attributes[machine.get(target+0x9c)][0] if target else '<Unused>'
                        fail(area==case['expected_area'],'Terminal Area expectation, including omitted column')
                    fail(not machine.live_studios,'Unfreed owned Studio fixture')
                    row['captured']=True
                except BaseException as error:row['error']=safe_error(error);raise
                finally:
                    pending=sys.exc_info()[1]
                    try:row.update(machine.evidence())
                    except BaseException:
                        if pending is None:raise
            report['capture_complete']=True
    except BaseException as error:first=error;report['capture_complete']=False;report['error']=safe_error(error)
    finally:
        report['after']={};report['postcheck_errors']=[]
        def postcheck(label,operation):
            nonlocal first
            try:return operation()
            except BaseException as error:
                report['postcheck_errors'].append({'check':label,**safe_error(error)})
                report['capture_complete']=False
                if first is None:first=error;report['error']=safe_error(error)
                return None
        for path,raw in inputs.items():
            value=postcheck(str(path),lambda path=path,raw=raw:sha(bounded(path,len(raw))))
            if value is not None:
                report['after'][str(path)]=value
                postcheck('source equality '+str(path),lambda value=value,raw=raw:fail(value==sha(raw),'Source changed'))
        if 'runtime' in report:
            report['runtime_after']={}
            for path,expected in report['runtime']['libraries'].items():
                value=postcheck(path,lambda path=path:sha(bounded(Path(path),64*1024*1024)))
                if value is not None:
                    report['runtime_after'][path]=value
                    postcheck('runtime equality '+path,lambda value=value,expected=expected:fail(value==expected,'Runtime changed'))
            value=postcheck('runtime executable',lambda:sha(bounded(Path(report['runtime']['executable']),64*1024*1024)))
            if value is not None:
                report['runtime_executable_after_sha256']=value
                postcheck('runtime executable equality',lambda:fail(value==report['runtime']['executable_sha256'],'Runtime executable changed'))
        else:report['runtime_postcheck_unavailable']='Runtime initialization did not complete'
        finish(out/'report.json',report,first)
    if first is not None:raise first
    print(json.dumps({'mode':mode,'preparation_complete':report.get('preparation_complete',False),'capture_complete':report['capture_complete'],'report':str(out/'report.json')}))


if __name__=='__main__':main()
