"""Independent captured original Windows74-case Corridor comparison."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from cbus_toolkit.edlt_corridor import EdltCorridor, CorridorSelectionError, CorridorConflictError
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_corridor import cache
ROOT=Path(__file__).resolve().parents[1]
VECTOR_PATH=ROOT/'research/fixtures/edlt-corridor-original-vectors.json'


def vectors():return json.loads(VECTOR_PATH.read_text())


@unittest.skipUnless(os.environ.get('CBUS_UNITSPEC_DIR'),'Set the exact vendor schema for full original Corridor vectors')
class CorridorOriginalVectorTests(unittest.TestCase):
    def test_all_original_parameters_crc_roles_and_timer_windows(self):
        document=vectors();spec_dir=Path(os.environ['CBUS_UNITSPEC_DIR']);editor=EdltCorridor(UnitSpecStore(spec_dir).load('KEYGL5.xml'))
        self.assertEqual(hashlib.sha256((spec_dir/'KEYGL5.xml').read_bytes()).hexdigest(),document['unit_spec_sha256'])
        self.assertEqual(len(document['cases']),74)
        accepted=0
        for row in document['cases']:
            with self.subTest(case=row['name']):
                source=editor.snapshot(row['input']);self.assertEqual(len(source),874)
                if row['outcome']!='accepted':
                    expected=CorridorSelectionError if row['outcome']=='selection_rejected' else CorridorConflictError
                    with self.assertRaises(expected):editor.plan(source,cache=cache(mode=row['cache_mode']),edits=row['edits'])
                    continue
                plan=editor.plan(source,cache=cache(mode=row['cache_mode']),edits=row['edits']); accepted+=1
                self.assertEqual(dict(plan.after_load),editor.snapshot(row['after_load']))
                self.assertEqual(dict(plan.after_controls),editor.snapshot(row['after_controls']))
                final={**plan.expected,**plan.changes};self.assertEqual(final,editor.snapshot(row['final']))
                self.assertEqual(len(editor.crcs(final)),5)
                controls=plan.as_dict()['controls']; last={}
                for line in row['controls']:
                    parts=line.split(':')
                    if parts[0]=='control':last[parts[2]]=dict(p.split('=',1) for p in parts[3:])
                for role,name in (('link_group','Link'),('office_group','Office'),('corridor_group','Corridor')):
                    observed=last[name];actual=controls[role]
                    self.assertEqual(actual['stored'],int(observed['raw']))
                    self.assertEqual(actual['selected'],None if observed['selected']=='null' else int(observed['selected']))
                    self.assertEqual(actual['enabled'],observed['enabled']=='True')
                    self.assertEqual([x['address'] for x in actual['choices']],[int(x) for x in observed['choices'].split(',')])
                timers=[line for line in row['controls'] if line.startswith('timer:')]
                for stage,wanted in (('controls-before-show',plan.as_dict()['control_stages'][0]['timer']),
                                    ('controls-shown',plan.as_dict()['control_stages'][1]['timer'])):
                    observed=dict(p.split('=',1) for p in next(line for line in timers if line.startswith('timer:'+stage+':')).split(':')[2:])
                    self.assertEqual(wanted['stored_seconds'],int(observed['raw']))
                    self.assertEqual(wanted['displayed_seconds'],int(observed['display']))
                last_timer=dict(p.split('=',1) for p in timers[-1].split(':')[2:])
                self.assertEqual(plan.as_dict()['timer']['stored_seconds'],int(last_timer['raw']))
                self.assertEqual(plan.as_dict()['timer']['displayed_seconds'],int(last_timer['display']))
        self.assertEqual(accepted,63)
