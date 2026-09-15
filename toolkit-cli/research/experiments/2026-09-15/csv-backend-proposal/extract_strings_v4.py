"""Static literal evidence only; no original instruction execution."""
from pathlib import Path
import json,re,hashlib,struct,pefile
BASE=Path(__file__).resolve().parent
EXE=Path('/Users/mitchell/source/cbus/toolkit-cli/research/vendor/toolkit/app/CBusToolkit.exe')
raw=EXE.read_bytes();assert hashlib.sha256(raw).hexdigest()=='9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
p=pefile.PE(data=raw,fast_load=True);rows=[];inputs={str(EXE):hashlib.sha256(raw).hexdigest()}
for directory in ('static-v1','static-v3','static-v5','static-v6','static-v8','static-v9','static-v11','static-v12'):
 for file in sorted((BASE/directory).glob('*.asm')):
  text=file.read_bytes();inputs[str(file)]=hashlib.sha256(text).hexdigest()
  for line in text.decode().splitlines():
   for m in re.finditer(r'(?<![\w])0x([0-9a-f]+)',line):
    address=int(m[1],16)
    if address<0x601000 or address>=0x600000+p.OPTIONAL_HEADER.SizeOfImage:continue
    try:
     header=p.get_data(address-0x600000-12,12)
     cp,width,refs,length=struct.unpack('<HHiI',header)
     if (cp,width,refs)==(1200,2,-1) and 0<length<=1024:
      data=p.get_data(address-0x600000,length*2);value=data.decode('utf-16le')
      row={'method_file':str(file.relative_to(BASE)),'instruction':line[:8],'pointer':hex(address),'length':length,'value':value,'header_and_bytes_sha256':hashlib.sha256(header+data).hexdigest()}
      if row not in rows:rows.append(row)
    except (ValueError,struct.error,UnicodeError,pefile.PEFormatError):pass
assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha for path,sha in inputs.items())
report={'original_execution':False,'inputs':inputs,'strings':rows,'preparation_failures':[{'output':'static-v2','reason':'Unknown exact MAP method 0xcb06bc typo rejected before output creation; corrected request omitted it'},{'output':'strings initial inline attempt','reason':'Immediate outside PE caused PEFormatError during literal scan; no output created. Current scanner explicitly checks image range and rejects non-data candidates.'}]}
with (BASE/'strings-v4.json').open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
for row in rows:print(row['instruction'],row['pointer'],repr(row['value']))
