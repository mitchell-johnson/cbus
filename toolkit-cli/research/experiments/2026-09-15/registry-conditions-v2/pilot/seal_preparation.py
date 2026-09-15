"""Seal prepared local inputs only. Never submits a guest job or executes a probe."""
from pathlib import Path
import hashlib
import io
import json
import struct
import zipfile

import pefile
import run

HERE=Path(__file__).resolve().parent
ROOT=run.ROOT
sha=lambda data:hashlib.sha256(data).hexdigest()


def main():
    copied=json.loads(run.read(HERE/'source-copy-manifest.json'))
    for name,row in copied['files'].items():
        if sha(run.read(HERE/name))!=row['sha256']:raise RuntimeError('Checkpoint source changed: '+name)
    local=json.loads(run.read(HERE/'local-preparation-v2.json'))
    if (local['original_executed'] is not False or local['windows_executed'] is not False
            or local['compile_only_executable_invoked'] is not False
            or len(local['results'])!=3 or any(row['status']!='fulfilled' or row['value']['exit_code']!=0 for row in local['results'])):
        raise RuntimeError('Expected local-only compile and two guard runs')
    contract=json.loads(run.read(HERE/'contract.json'))
    paths={name:HERE/name for name in [*copied['files'],'source-copy-manifest.json','PLAN.md','seal_preparation.py','original-types.txt']}
    proposal=HERE.parent/'registry-proposal-v1'
    for name in ('PROPOSAL.md','pilot-cases.json','source-graph.json','integer-evidence.json'):
        paths['proposal/'+name]=proposal/name
    paths['original/inventory.json']=HERE.parent/'static-v1/inventory.json'
    dependency=HERE.parent/'registry-dependency-v1'
    for path in sorted(dependency.iterdir()):
        if path.is_file():paths['dependency/'+path.name]=path
    paths['dependency/historical-staged-manifest.json']=ROOT/'research/runtime/toolkit-update-check/manifest-v2.json'
    paths['prior-failure/report.json']=HERE.parent/'registry-pilot-v1/pilot-v1/report.json'
    paths['prior-failure/original.stdout']=HERE.parent/'registry-pilot-v1/pilot-v1/original.stdout'
    paths['prior-failure/analysis.json']=HERE.parent/'registry-pilot-v1/failure-analysis-v1/analysis.json'

    for row in contract['vendor'].values():paths['vendor/'+Path(row['path']).name]=Path(row['path'])
    paths['host/windows_bridge.py']=ROOT/'research/windows_bridge.py'
    paths['host/windows_provenance.py']=ROOT/'research/windows_provenance.py'
    paths['host/utmctl']=Path('/Applications/UTM.app/Contents/MacOS/utmctl')
    paths['host/interpreter-313']=ROOT/'.venv/bin/python'
    paths['host/interpreter-310']=ROOT/'research/runtime/full-wheel-environments-20260915-v6/310/bin/python'
    generation=Path(contract['provenance_root']).resolve()
    for name,relative in [('bridge-ready.json','windows-bridge/v2/bridge-ready.json'),
                          ('windows-runtime.json','edlt-lifecycle/windows-runtime.json'),
                          ('NativeWindowsBridgeV2.exe','windows-bridge/v2/NativeWindowsBridgeV2.exe')]:
        paths['provenance/'+name]=generation/relative
    paths={name:path.resolve(strict=True) for name,path in paths.items()}
    data={name:run.read(path) for name,path in paths.items()}
    required={'proposal/pilot-cases.json':contract['reviewed_plan_sha256'],
              'provenance/bridge-ready.json':contract['ready_sha256'],
              'provenance/windows-runtime.json':contract['runtime_sha256'],
              'original/inventory.json':'6b1708300f47c617e0dab410eadc6894f8373b4d3ea2ba63729e9f9de47aa7fd'}
    required.update({'vendor/'+Path(row['path']).name:row['sha256'] for row in contract['vendor'].values()})
    for name,digest in required.items():
        if sha(data[name])!=digest:raise RuntimeError('Historical or generation identity changed: '+name)
    seal={'format':'registry-pre-execution-input-seal-v1','original_executed':False,'windows_executed':False,
          'inputs':{name:{'path':str(paths[name]),'sha256':sha(value),'bytes':len(value)} for name,value in data.items()}}
    run.json_write(HERE/'source-seal.json',seal)
    data['source-seal.json']=run.read(HERE/'source-seal.json')
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as target:
        for name,value in data.items():target.writestr(name,value)
    encoded=archive.getvalue();run.write(HERE/'prepared-inputs.zip',encoded)
    with zipfile.ZipFile(io.BytesIO(run.read(HERE/'prepared-inputs.zip'))) as source:
        if {name:sha(source.read(name)) for name in source.namelist()}!={name:sha(value) for name,value in data.items()}:
            raise RuntimeError('Prepared archive readback failed')
    binary=run.read(HERE/'compile-only-v2.exe');pe=pefile.PE(data=binary)
    clr_rva=pe.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress
    flags=struct.unpack('<I',pe.get_data(clr_rva+16,4))[0]
    if pe.FILE_HEADER.Machine!=0x14c or flags&3!=3:raise RuntimeError('Local compiler output is not IL-only x86-required')
    for name,path in paths.items():
        if run.read(path)!=data[name]:raise RuntimeError('Prepared input changed while sealing')
    report={'format':'registry-pilot-preparation-state-v1','status':'prepared-awaiting-parent-admission-review',
            'original_executed':False,'windows_executed':False,'registry_accessed':False,
            'local_guard_tests_per_python':9,'local_preparation_report_sha256':sha(run.read(HERE/'local-preparation-v2.json')),
            'local_compile_only':{'sha256':sha(binary),'machine':pe.FILE_HEADER.Machine,'clr_flags':flags,'invoked':False},
            'sealed_input_count':len(paths),'archive_members':len(data),'archive_sha256':sha(encoded),
            'source_seal_sha256':sha(data['source-seal.json']),
            'plan_sha256':sha(data['PLAN.md']),'source_hashes':{name:sha(data[name]) for name in copied['files']},
            'next_action':'Parent source review; no original execution is authorized by this report.'}
    run.json_write(HERE/'STATE.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
