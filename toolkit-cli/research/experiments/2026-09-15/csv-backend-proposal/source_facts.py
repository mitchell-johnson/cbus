"""Reproducible data/VMT facts. Reads the pinned PE; never executes original code."""
from pathlib import Path
import hashlib,json,re,struct,pefile
BASE=Path(__file__).resolve().parent
ROOT=Path('/Users/mitchell/source/cbus/toolkit-cli')
EXE=ROOT/'research/vendor/toolkit/app/CBusToolkit.exe'; MAP=EXE.with_suffix('.map')
PIN={EXE:'9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab',MAP:'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'}
data={p:p.read_bytes() for p in PIN}
assert all(hashlib.sha256(data[p]).hexdigest()==v for p,v in PIN.items())
pe=pefile.PE(data=data[EXE],fast_load=True)
names={}
for line in data[MAP].decode('ascii').splitlines():
 m=re.match(r'\s+0001:([0-9A-F]{8})\s+(\S+)\s*$',line)
 if m:names.setdefault(int(m[1],16)+0x601000,set()).add(m[2])
def word(va):return struct.unpack('<I',pe.get_data(va-0x600000,4))[0]
def fact(va):return {'address':hex(va),'symbols':sorted(names.get(va,()))}
classes=[]
for prefix,slots in ((0x1249224,(0x94,0xac,0xd0,0xf4,0xf8,0xfc,0x100)),(0x1215714,(0x94,0xac,0xd0,0xf4,0xf8,0xfc,0x100)),(0x101aa5c,(0x88,0x90,0xe4,0xec,0x10c)),(0xc1a2c8,(0x88,0x90,0xe4,0xec,0x10c))):
 vmt=word(prefix);assert vmt==prefix+0x58
 classes.append({'prefix':fact(prefix),'vmt':hex(vmt),'slots':[{'offset':hex(o),'pointer':fact(word(vmt+o)),'bytes_sha256':hashlib.sha256(pe.get_data(vmt+o-0x600000,4)).hexdigest()} for o in slots]})
report={'original_execution':False,'scope':'Pinned static data/VMT fields only. Registration call order comes from separately pinned method bodies; active whole-startup registry not executed.', 'inputs':{str(p):v for p,v in PIN.items()},'classes':classes,
'quickget_exception_class_prefixes':[fact(x) for x in (0xf43d78,0x842ac8,0xf46bd4,0xf444a4)],
'preparation_failures':[{'request':'static-v2','failure':'Unknown exact method 0xcb06bc; rejected before output creation.'},{'request':'initial inline string scan','failure':'Immediate outside PE caused PEFormatError before output; versioned scanner checks PE range.'},{'request':'static-v4','failure':'Unknown exact method 0x7f3ed0; rejected before output creation.'},{'request':'static-v7','failure':'Unknown exact method 0x7e03c0; rejected before output creation.'},{'request':'static-v10','failure':'Unknown exact MAP name FlashAgent.TFlashAgentFactory.GetFlashAgent; rejected before extractor/output creation.'}]}
assert all(p.read_bytes()==raw for p,raw in data.items())
report['source_unchanged']=True
with (BASE/'source-data-v1.json').open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
print(json.dumps(report,indent=2))
