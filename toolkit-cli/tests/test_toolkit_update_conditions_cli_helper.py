import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import toolkit_update_conditions as core, toolkit_update_conditions_cli as subject
from tests.test_toolkit_update_conditions import data, definition, facts


class ConditionHelperTests(unittest.TestCase):
    def args(self,folder,expression='false'):
        folder=Path(folder);(folder/'conditions').write_bytes(data(expression));(folder/'context').write_bytes(facts())
        return argparse.Namespace(area='update-condition-stages',file=folder/'conditions',context=folder/'context')

    def test_complete_false_survives_export_interruption_with_exact_identity(self):
        first=KeyboardInterrupt('export');second=SystemExit('second export')
        with tempfile.TemporaryDirectory() as folder:
            args=self.args(folder)
            with patch.object(core.ConditionStageReport,'as_dict',side_effect=first):
                with self.assertRaises(KeyboardInterrupt) as raised:subject.run(args)
            self.assertIs(raised.exception,first)
            with patch.object(core.ConditionStageReport,'as_dict',side_effect=second):
                value=subject.error_payload(first,args)['toolkit_update_conditions_evidence']
            self.assertIs(value['condition_result_under_supplied_context'],False);self.assertTrue(value['evidence_export_failed'])
            self.assertIn('source',value);self.assertEqual(subject.error_payload(second,args),{})
            # Even both independent export paths failing cannot replace first or lose false.
            with patch.object(core.ConditionStageReport,'as_dict',side_effect=second),patch.object(subject.json,'loads',side_effect=SystemExit('decoder')):
                value=subject.error_payload(first,args)['toolkit_update_conditions_evidence']
            self.assertTrue(value['calculation_completed_before_export_failure']);self.assertIs(value['condition_result_under_supplied_context'],False)

    def test_evaluation_interruption_partial_evidence_and_fresh_read_failure(self):
        first=KeyboardInterrupt('leaf')
        with tempfile.TemporaryDirectory() as folder:
            args=self.args(folder,'A');args.file.write_bytes(data('A',A=definition()))
            with patch.object(core,'_leaf',side_effect=first):
                with self.assertRaises(KeyboardInterrupt) as raised:subject.run(args)
            self.assertIs(raised.exception,first)
            value=subject.error_payload(first,args)['toolkit_update_conditions_evidence']
            self.assertEqual(value['events'][0]['lookup_name'],'a')
            args.file.unlink()
            with self.assertRaises(FileNotFoundError):subject.run(args)
            self.assertEqual(subject.error_payload(first,args),{})

if __name__=='__main__':unittest.main()
