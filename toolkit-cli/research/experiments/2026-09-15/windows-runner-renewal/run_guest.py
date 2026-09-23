"""One explicitly released renewal stage; never rerun an admitted stage."""
from pathlib import Path
import argparse, hashlib, json, os, subprocess, sys

HERE=Path(__file__).resolve().parent
ROOT=Path('/Users/mitchell/source/cbus/toolkit-cli')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--release',required=True,help='Parent renewal release after every Windows owner confirms no pending job')
parser.add_argument('stage',choices=('compile','capture','stop','inspect','start'))
args=parser.parse_args()
if not args.release.strip():parser.error('Nonempty release identifier is required')
prep=json.loads((HERE/'preparation.json').read_text());prefix=prep['fresh_prefix']
for name,row in prep['helpers'].items():
    if hashlib.sha256((HERE/name).read_bytes()).hexdigest()!=row['draft_sha256']:
        raise RuntimeError('Prepared renewal artifact changed: '+name)
marker=HERE/(args.stage+'-host-admitted.json')
if marker.exists():raise RuntimeError('This stage may already have run; inspect preserved local/guest witnesses, never replay it')
required={'capture':'compile','stop':'capture','inspect':'stop','start':'inspect'}.get(args.stage)
if required and not (HERE/(required+'-verified.json')).is_file():
    raise RuntimeError('A separately reviewed '+required+'-verified.json witness is required before '+args.stage)
sys.path.insert(0,str(ROOT))
from research.windows_bridge import WindowsBridge, UTMCTL, VM_UUID
bridge=WindowsBridge()
uploads=[args.stage+'.cmd']
if args.stage=='compile':uploads[:0]=['NativeBridgeStop.cs','NativeBridgeRecovery.cs']
# Guard this whole stage before any guest write or exec, even if an upload fails.
with marker.open('x') as stream:
    json.dump({'stage':args.stage,'release':args.release,'uploads':uploads,'prefix':prefix,
               'meaning':'Stage admitted locally; guest execution not yet proven. Do not replay.'},stream,indent=2)
    stream.write('\n');stream.flush();os.fsync(stream.fileno())
for name in uploads:
    relative=prefix+'-'+name
    if bridge.pull(relative,missing_ok=True) is not None:raise RuntimeError('Guest artifact already exists: '+relative)
    bridge.push(relative,(HERE/name).read_bytes())
command=[UTMCTL,'exec','--debug',VM_UUID,'--cmd',r'C:\Windows\System32\cmd.exe','/d','/c',bridge.path(prefix+'-'+args.stage+'.cmd')]
result=subprocess.run(command,capture_output=True,timeout=90)
proof={'args':command,'return_code':result.returncode,'stdout':result.stdout.decode(errors='replace'),
       'stderr':result.stderr.decode(errors='replace'),'stage':args.stage,
       'acceptance_requires_guest_files':True,'guest_completion_claimed':False}
with (HERE/(args.stage+'-guest-exec.json')).open('x') as stream:json.dump(proof,stream,indent=2);stream.write('\n')
print(json.dumps(proof,indent=2))
