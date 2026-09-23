"""Resolve exact MAP symbols before the held source-only extractor."""
from pathlib import Path
import hashlib,json,re,runpy,sys
BASE=Path(__file__).resolve().parent
MAP=Path('/Users/mitchell/source/cbus/toolkit-cli/research/vendor/toolkit/app/CBusToolkit.map')
raw=MAP.read_bytes();assert hashlib.sha256(raw).hexdigest()=='f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
lookup={}
for line in raw.decode('ascii').splitlines():
 m=re.match(r'^\s+000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*$',line)
 if m:lookup.setdefault(m[3],set()).add(int(m[2],16)+(0x601000 if m[1]=='1' else 0x1369000))
assert len(sys.argv)>2
names=sys.argv[2:];addresses=[]
for name in names:
 matches=lookup.get(name,set());assert len(matches)==1,(name,matches);addresses.append(hex(next(iter(matches))))
sys.argv=[str(BASE/'extract_static.py'),sys.argv[1],*addresses]
runpy.run_path(str(BASE/'extract_static.py'),run_name='__main__')
