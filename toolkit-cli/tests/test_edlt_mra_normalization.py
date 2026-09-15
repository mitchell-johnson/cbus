"""Shared save normalization matches original distributed MRA global values."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from cbus_toolkit.edlt import EdltLighting, EdltApplyError, EdltError, _field
from cbus_toolkit.edlt_mra import normalize_mra_globals
from tests.test_edlt import fixture, Session
from tests.test_edlt_normalization import values_for, record, parse_native_widgets


def mixed_values(raw3=False):
    source=values_for('no-active')
    for widget,kind,control in ((6,7,237 if raw3 else 109),(8,8,178),(10,9,3)):
        source[_field(widget)]=(kind,);source[_field(widget,1)]=(control,)
    return source


class MRANormalizationTests(unittest.TestCase):
    def test_literals_unrelated_conversion_and_optout(self):
        for raw3,second,third in ((False,106,107),(True,234,235)):
            source=mixed_values(raw3)
            result=EdltLighting._place_record(source,1,record(source))
            self.assertEqual(result[_field(8,1)],(second,));self.assertEqual(result[_field(10,1)],(third,))
            self.assertEqual(result[_field(6,1)],source[_field(6,1)])
            self.assertEqual(EdltLighting._place_record(result,1,record(result)),result)
            opted=EdltLighting._place_record(source,1,record(source),normalize_mra=False)
            self.assertEqual(opted[_field(8,1)],(178,))
            metadata=normalize_mra_globals(source,_preserve_stored_multiplexer=True).as_dict()
            self.assertEqual(metadata['multiplexer_ui_canonical'],not raw3)
        source=mixed_values();replacement=bytearray(record(source,6));replacement[0]=10;replacement[1]=2
        result=EdltLighting._place_record(source,6,replacement)
        self.assertEqual(result[_field(8,1)],(106,)) # Removed first still supplied the loaded globals.
        self.assertEqual(result[_field(10,1)],(107,))
        with self.assertRaises(EdltError):normalize_mra_globals(source,multiplexer=4,_preserve_stored_multiplexer=True)

    def test_lighting_apply_allows_canonical_sibling_changes_and_rolls_back(self):
        from dataclasses import replace
        editor=EdltLighting(fixture());session=Session(editor.spec)
        session.current.update(mixed_values())
        original=editor.snapshot(session.values())
        plan=editor.plan(original,page=1,position=2,group=42,mode='off-on')
        self.assertEqual(plan.changes[_field(8,1)],(106,))
        self.assertEqual(plan.changes[_field(10,1)],(107,))
        forged=replace(plan,changes={**plan.changes,_field(8,2):(1,)})
        with self.assertRaises(EdltError):editor.apply(session,forged)
        session.failure=_field(8,1)
        with self.assertRaises(EdltApplyError) as failure:editor.apply(session,plan)
        self.assertTrue(failure.exception.details['rollback_verified'])
        self.assertEqual(editor.snapshot(session.values()),original)
        self.assertTrue(editor.apply(session,plan)['verified'])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),'Set original Toolkit DLL fixture')
class OriginalMRANormalizationTests(unittest.TestCase):
    def test_original_save_existing_raw3_removed_first_and_inserted_earlier(self):
        root=Path(__file__).resolve().parents[1];app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend()
        if backend == 'windows':
            with OriginalModelOracle(root / 'research/NativeEdltNormalizationProbe.cs', app, backend='windows') as oracle:
                original_output = oracle.run(('mra',))
            result = subprocess.CompletedProcess([], 0, original_output, '')
        else:
            with tempfile.TemporaryDirectory() as folder:
                Path(folder,'NativeEdltNormalizationProbe.cs').write_bytes((root/'research/NativeEdltNormalizationProbe.cs').read_bytes())
                result=subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',folder+':/work','-w','/work',
                  'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',
                  'mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms -r:System.Drawing NativeEdltNormalizationProbe.cs && MONO_PATH=/input mono NativeEdltNormalizationProbe.exe mra'],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        cases={};case=None
        for line in result.stdout.splitlines():
            key,value=line.split(':',1)
            if key=='case':case=value;cases[case]={}
            else:cases[case][key]=int(value) if key=='selected' else parse_native_widgets(value)
        self.assertEqual(set(cases),{'unrelated','stored-standby','stored-raw3','replace-first','insert-earlier'})
        for name,row in cases.items():
            with self.subTest(case=name):
                source=dict(row['source']);selected=row['selected']
                if selected>=6:source[f'Widget{selected}RestoreLevel']=row['before'][f'Widget{selected}RestoreLevel']
                actual=EdltLighting._place_record(source,selected,record(row['before'],selected))
                self.assertEqual(actual,row['after']);self.assertEqual(row['again'],row['after'])
                expected=(234,235) if name=='stored-raw3' else (106,107)
                self.assertEqual((actual[_field(8,1)][0],actual[_field(10,1)][0]),expected)
        if os.environ.get('CBUS_EDLT_MRA_NORMALIZATION_REPORT'):
            import json
            Path(os.environ['CBUS_EDLT_MRA_NORMALIZATION_REPORT']).write_text(json.dumps({
                'passed': True, 'original_backend': backend, 'cases': cases,
                'original_output': result.stdout, 'physical_device_verified': False,
            }, indent=2) + '\n')


if __name__=='__main__':unittest.main()
