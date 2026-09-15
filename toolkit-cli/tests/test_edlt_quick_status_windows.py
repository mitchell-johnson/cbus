"""Independent captured original Windows controls; no Windows endpoint required."""
import hashlib
import itertools
import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt_quick_status import EdltQuickStatus, MODES, _levels
from tests.test_edlt_quick_status import fixture, Session

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'research/fixtures/edlt-quick-status-windows-acceptance.json'
VECTORS=ROOT/'research/fixtures/edlt-quick-status-windows-vectors.txt'


class WindowsQuickStatusVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=json.loads(REPORT.read_text());raw=VECTORS.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=cls.report['raw_vectors_sha256']:
            raise AssertionError('Original Windows vector file differs from pinned report')
        cls.lines=raw.decode().splitlines()

    def test_all_three_palette_properties_match_captured_original_windows_values(self):
        spec=fixture();editor=EdltQuickStatus(spec);base=editor.snapshot(Session(spec).values());seen=set()
        for line in self.lines:
            if not line.startswith('palette3:'):continue
            _,identity,before,after,validated,validation=line.split(':')
            initial,target,colour=map(int,identity.split(','));seen.add((initial,target,colour))
            current={**base,'QuickStatusMode':(initial,)}
            for index in (1,2,3):current['QuickStatusColour'+str(index)]=(colour,)
            plan=editor.plan(current,mode=MODES[target]);data=plan.as_dict()
            captured_mode,rows=validated.split(';')
            self.assertEqual(plan.values['mode'],int(captured_mode));self.assertEqual(validation,'validation=True')
            for name,row in zip(('low_colour','middle_colour','high_colour'),rows.split('|')):
                fields,choices=row.split(',choices=');value,selection_index,selection_value=fields.split(',')
                with self.subTest(identity=identity,property=name):
                    self.assertEqual(plan.values[name],int(value))
                    self.assertEqual(len(data['colour_palette']),len(choices.split(',')))
                    self.assertEqual(data['colour_ui_canonical'][name],selection_value!='null')
                    self.assertEqual(data[name] is None,int(selection_index)==-1)
            self.assertFalse(data['group_metadata_verified']);self.assertFalse(data['physical_device_verified'])
        expected=set(itertools.product(range(8),range(4),list(range(10))+[39,254,255]))
        self.assertEqual(seen,expected)
        self.assertEqual(self.report['palette_coverage']['property_transitions'],3*len(seen))

    def test_original_windows_linked_control_single_and_batch_vectors(self):
        spec=fixture();editor=EdltQuickStatus(spec);base=editor.snapshot(Session(spec).values());counts={'single':0,'levels':0}
        for line in self.lines:
            if line.startswith('single:'):
                before,unused,after,events=line[len('single:'):].split(':')
                low,high,which,request=map(int,before.split(','));captured=tuple(map(int,after.split(',')[-2:]))
                self.assertEqual(_levels(low,high,request if which==0 else None,request if which==1 else None),captured)
                counts['single']+=1
            elif line.startswith('levels:'):
                before,request,after=line[len('levels:'):].split(':');low,high=map(int,before.split(','));edit_low,edit_high=map(int,request.split(','))
                plan=editor.plan({**base,'QuickStatusLevel1':(low,),'QuickStatusLevel2':(high,)},low_threshold=edit_low,high_threshold=edit_high)
                self.assertEqual((plan.values['low_threshold'],plan.values['high_threshold']),tuple(map(int,after.split(','))))
                counts['levels']+=1
        self.assertEqual(counts,{'single':168,'levels':49})
