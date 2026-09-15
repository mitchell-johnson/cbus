"""Captured original full-PP results independently staged/persisted by C-Gate."""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.edlt import _render
from cbus_toolkit.edlt_corridor import EdltCorridor, CorridorSelectionError, CorridorConflictError, FIELDS
from cbus_toolkit.native import NativeProjects, NativeDatabase
from cbus_toolkit.programming import Programmer
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_corridor import cache
from tests.test_edlt_corridor_vectors import vectors, VECTOR_PATH
ROOT=Path(__file__).resolve().parents[1]
NAMES=('rich-no-edit','rich-group-timer','rich-sequential','rich-conflict','rich-unavailable','rich-duplicates',
       'disabled-missing-roles','missing-all-then-select','raw-zero-timer-group-edit','unchanged300',
       'disabled-secondary-scene','missing-key-group')


@unittest.skipUnless(all(os.environ.get(k) for k in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR')),
    'Select an owned native C-Gate and exact vendor schema for Corridor persistence')
class NativeCorridorTests(unittest.TestCase):
    def test_original_full_pp_crc_raw_database_save_reload_and_rejections(self):
        spec_dir=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve(); editor=EdltCorridor(UnitSpecStore(spec_dir).load('KEYGL5.xml'))
        rows={r['name']:r for r in vectors()['cases']}; project='CR'+uuid4().hex[:6].upper();network='//'+project+'/254'
        # The original owned vectors carry UnitAddress255. Keep DB/PP identity consistent.
        source='/db'+network+'/p/255'
        run=ROOT/'research/runtime/edlt-corridor'/('native-py'+str(sys.version_info.minor)+'-'+uuid4().hex[:10]);run.mkdir(parents=True)
        paths=[ROOT/'src/cbus_toolkit'/f'{name}.py' for name in ('edlt_corridor','edlt_lifecycle','edlt_application_cache','edlt','memory','unitspec','programming','native','cgate')]
        paths += [Path(__file__).resolve(),ROOT/'tests/test_edlt_corridor.py',ROOT/'tests/test_edlt_corridor_vectors.py',VECTOR_PATH,spec_dir/'KEYGL5.xml']
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        report={'passed':False,'python':sys.version,'project':project,'cases':[],'source_sha256':hashes,
                'physical_device_verified':False,'full_form_initialization_verified':False,'cleanup_errors':[]}
        def write(): (run/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        write()
        with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20033')),timeout=30) as client:
            report['native_greeting']=client.greeting
            projects,database=NativeProjects(client),NativeDatabase(client);projects.operation('new',project)
            try:
                database.create_network(project,254,'Corridor_Fixture','Cni','127.0.0.1:1')
                database.create_unit(network,255,'Corridor_Fixture','KEYGL5','5.5.00',catalog_number='5055EDL')
                projects.operation('save',project)
                for name in NAMES:
                    with Programmer(client).load(network,source) as session:
                        row=rows[name]; before=editor.snapshot(row['input']); current=editor.snapshot(session.values())
                        for key,value in before.items():
                            if current[key]!=value:session.set(key,_render(value))
                        self.assertEqual(editor.snapshot(session.values()),before)
                        entry={'name':name,'original_stdout_sha256':row['provenance']['stdout_sha256'],'outcome':row['outcome']}
                        if row['outcome']!='accepted':
                            error=CorridorSelectionError if row['outcome']=='selection_rejected' else CorridorConflictError
                            with self.assertRaises(error):editor.configure(session,cache=cache(mode=row['cache_mode']),edits=row['edits'])
                            self.assertEqual(editor.snapshot(session.values()),before)
                            entry['source_unchanged']=True;report['cases'].append(entry);write();continue
                        plan=editor.plan(before,cache=cache(mode=row['cache_mode']),edits=row['edits'])
                        expected=editor.snapshot(row['final']);self.assertEqual({**before,**plan.changes},expected)
                        self.assertTrue(editor.apply(session,plan)['verified'])
                        self.assertEqual(editor.snapshot(session.values()),expected)
                        raw=bytes.fromhex(session.get_raw_data(0x132,5).lines[-1].split('RawData=')[1])
                        seconds=expected[FIELDS['seconds']][0]
                        wanted=bytes([expected[FIELDS['link_group']][0],expected[FIELDS['office_group']][0],seconds&255,seconds>>8,expected[FIELDS['corridor_group']][0]])
                        self.assertEqual(raw,wanted)
                        for key,value in editor.crcs(expected).items():self.assertEqual(expected[key],value)
                        session.save_to_source();entry.update(parameters_compared=len(expected),crc_count=5,raw_hex=raw.hex(),saved=True)
                    for operation in ('save','close','load'):projects.operation(operation,project)
                    with Programmer(client).load(network,source) as session:
                        self.assertEqual(editor.snapshot(session.values()),expected)
                        reloaded_raw=bytes.fromhex(session.get_raw_data(0x132,5).lines[-1].split('RawData=')[1])
                        self.assertEqual(reloaded_raw,wanted)
                    entry.update(saved_closed_loaded=True,reloaded_parameters_compared=len(expected),reloaded_raw_hex=reloaded_raw.hex())
                    report['cases'].append(entry);write()
                state=client.command('GET '+network+' TargetInterfaceState').lines
                self.assertTrue(any('targetinterfacestate=closed' in line.lower() for line in state),state)
                for path in paths:self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),hashes[str(path)],str(path))
                report.update(passed=True,each_accepted_case_saved_closed_loaded=True,source_hashes_stable=True,network_state=list(state));write()
            except BaseException as error:
                report['error']={'type':type(error).__name__,'message':str(error)};write();raise
            finally:
                for operation in ('close','delete'):
                    try:projects.operation(operation,project)
                    except Exception as error:report['cleanup_errors'].append({'operation':operation,'message':str(error)})
                write()
        self.assertEqual(report['cleanup_errors'],[])
        print('Corridor native evidence: '+str(run/'report.json'))
