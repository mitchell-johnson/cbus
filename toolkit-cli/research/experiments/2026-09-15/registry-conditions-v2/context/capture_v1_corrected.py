"""One-time pre-edit v1 report capture; no original or live-provider calls."""
import hashlib
import json
from pathlib import Path
import zipfile
from cbus_toolkit import toolkit_update_conditions as subject

ROOT = Path('/Users/mitchell/source/cbus/toolkit-cli')
OUT = Path(__file__).resolve().parent
assert hashlib.sha256((ROOT/'src/cbus_toolkit/toolkit_update_conditions.py').read_bytes()).hexdigest() == 'da8ebb5837c4e87a5612b63166d4e6a7a2619ef1d9486de081677453cc1fae31'
vectors = json.loads((ROOT/'research/fixtures/toolkit-update-conditions-vectors.json').read_bytes())
encode = lambda value: json.dumps(value, separators=(',', ':')).encode()
context = encode({'format': subject.CONTEXT_FORMAT, 'culture': 'invariant-ascii', 'files': [{'path':path, **fact} for path,fact in vectors['logical_fixture_facts'].items()]})
inputs = []
for case in vectors['cases']:
    if case['kind'] in ('deserialize', 'validate'):
        raw = case['text'].encode()
    elif case['kind'] == 'file':
        raw = encode({'expression': 'A', 'conditions': {'A': {'whatToCheck':case['what'], 'howToCheck':case['how'], 'fileOrRegistryKeyPath':case['fixture'], 'comparisonRightSideValue':case['right']}}})
    elif case['kind'] == 'expression':
        raw = encode({'expression':case['expression'], 'conditions': {name:{'whatToCheck':1,'howToCheck':leaf['how'],'fileOrRegistryKeyPath':leaf['fixture']} for name,leaf in case['leaves'].items()}})
    else:
        continue
    inputs.append((case['id'], raw, context))
for number, raw in enumerate((b'bad', b'{"expression":"true","expression":"false"}', b'{"expression":"true","ignored":NaN}', b'{"expression":"true","ignored":"\\ud800"}', b'{"expression":"true","conditions":{"A":{"whatToCheck":true}}}')):
    inputs.append(('extra-typed-'+str(number), raw, context))
for number, ctx in enumerate((b'bad', b'{}', encode({'format':subject.CONTEXT_FORMAT,'culture':'current','files':[]}), encode({'format':subject.CONTEXT_FORMAT,'culture':'invariant-ascii','files':[{'path':'x','exists':None}]}))):
    inputs.append(('extra-context-'+str(number), b'{"expression":"true"}', ctx))
rows=[]
reports=[]
for name, raw, ctx in inputs:
    report=subject.ToolkitUpdateConditions().evaluate(raw,context=ctx)
    rows.append({'id':name,'conditions':raw.decode(),'context':ctx.decode(),'report_sha256':hashlib.sha256(report._document.encode()).hexdigest()})
    reports.append({'id':name,'document':report._document})
fixture={'format':'cbus-toolkit-condition-v1-report-baseline','source_sha256':'da8ebb5837c4e87a5612b63166d4e6a7a2619ef1d9486de081677453cc1fae31','note':'Complete v1 document byte hashes captured before context-v2 edits; expression cases run with the public fresh cache, not any seeded original cache.','cases':rows}
raw=encode(fixture)+b'\n'
with (OUT/'v1-report-baseline-v2.json').open('xb') as stream:stream.write(raw)
with zipfile.ZipFile(OUT/'v1-report-baseline-v2.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr('toolkit_update_conditions.py', (ROOT/'src/cbus_toolkit/toolkit_update_conditions.py').read_bytes())
    archive.writestr('baseline.json',raw)
    archive.writestr('reports.json',encode(reports))
    archive.writestr('capture_v1.py',Path(__file__).read_bytes())
print(json.dumps({'cases':len(rows),'fixture_sha256':hashlib.sha256(raw).hexdigest(),'archive_sha256':hashlib.sha256((OUT/'v1-report-baseline-v2.zip').read_bytes()).hexdigest()}))
