"""Issued factory input receipts; no original factory or transition is implied."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_lifecycle import EdltLifecycle
from cbus_toolkit.edlt_reset import EdltResetControls
from cbus_toolkit.edlt_global_preparation import (
    EdltGlobalPreparation,GlobalPreparationContext,_validate_factory_context,
)
from tests.test_edlt_global_preparation import fixture,vectors
from tests.test_edlt_reset import metadata


class FactoryContextTests(unittest.TestCase):
    def setUp(self):
        self.spec=fixture();self.reset=EdltResetControls(self.spec)
        self.editor=EdltGlobalPreparation(self.spec)
        self.row=vectors()['factory_project_cases'][0]
        self.raw=dict(self.row['input']);self.cache=metadata()
        self.identity=GlobalPreparationContext(self.row['source_path'],self.row['form_project'],self.row['cached_network_project'])

    def issue(self,**changes):
        args=dict(reset_editor=self.reset,context=self.identity,metadata=self.cache,dirty_parameters=['UnitAddress'])
        args.update(changes)
        return self.editor.factory_context(self.raw,**args)

    def test_receipt_retains_exact_raw_order_identity_cache_and_dirty(self):
        receipt=self.issue()
        self.assertIs(_validate_factory_context(receipt,self.reset),receipt)
        self.assertEqual(receipt.expected_raw,self.raw)
        self.assertEqual(receipt.parameter_order,tuple(self.raw))
        self.assertEqual(receipt.metadata.as_dict(),self.cache)
        self.assertEqual(receipt.context,self.identity)
        self.assertEqual(receipt.dirty_parameters,('UnitAddress',))
        self.assertEqual(receipt.specification_sha256,self.reset.specification_sha256)
        self.raw['Project']='MUTATED';self.cache['applications'][0]['name']='MUTATED'
        self.assertNotEqual(receipt.expected_raw['Project'],'MUTATED')
        self.assertNotEqual(receipt.metadata.applications[0].name,'MUTATED')
        _validate_factory_context(receipt,self.reset)
        with self.assertRaises(TypeError):receipt.expected_raw['Project']='MUTATED'

    def test_receipt_is_not_a_reset_factory_or_bridge_execution(self):
        with patch.object(self.reset.lifecycle,'load',side_effect=AssertionError('Unexpected load')),patch('socket.socket',side_effect=AssertionError('Unexpected I/O')):
            receipt=self.issue();_validate_factory_context(receipt,self.reset)
        exported=receipt.as_dict()
        self.assertEqual(exported['factory_context'],'factory-global-reset-then-remove-global-tab-v1')
        for name in ['factory_transition_executed','reset_applied','global_bridge_enabled','saved','physical_device_verified','cache_freshness_verified']:
            self.assertIs(exported[name],False)
        self.assertTrue(exported['export_is_review_only'])
        self.assertEqual(receipt.expected_raw['NavWidgetType'],'0xff')
        exported['expected_raw']['Project']='MUTATED'
        self.assertNotEqual(receipt.expected_raw['Project'],'MUTATED')

    def test_copied_replaced_exported_and_cross_editor_receipts_rejected(self):
        receipt=self.issue()
        for bad in [replace(receipt),replace(receipt,dirty_parameters=()),receipt.as_dict(),None]:
            with self.assertRaises(EdltError):_validate_factory_context(bad,self.reset)
        with self.assertRaises(EdltError):_validate_factory_context(receipt,EdltResetControls(self.spec))
        other_spec=fixture()
        with self.assertRaises(EdltError):self.issue(reset_editor=EdltResetControls(other_spec))

    def test_invalid_raw_identity_metadata_and_dirty_before_issuance(self):
        class IdentityChild(GlobalPreparationContext):pass
        for changes in [dict(context=IdentityChild(self.identity.source,self.identity.form_project,self.identity.cached_network_project)),
                        dict(metadata={}),dict(dirty_parameters=[True]),dict(dirty_parameters=['UnitAddress','UnitAddress'])]:
            with self.assertRaises(EdltError):self.issue(**changes)
        self.raw['NavWidgetType']=False
        with self.assertRaises(EdltError):self.issue()

    def test_schema_mutation_after_editor_or_context_creation_rejected(self):
        receipt=self.issue();fields=self.spec.get('Project').fields
        original=fields['Address']
        try:
            fields['Address']='0x24'
            with self.assertRaises(EdltError):_validate_factory_context(receipt,self.reset)
            with self.assertRaises(EdltError):self.issue()
        finally:fields['Address']=original
        _validate_factory_context(receipt,self.reset)

    def test_swapping_shared_lifecycle_is_rejected(self):
        receipt=self.issue();old=self.reset.lifecycle
        try:
            self.reset.lifecycle=EdltLifecycle(self.spec)
            with self.assertRaises(EdltError):_validate_factory_context(receipt,self.reset)
            with self.assertRaises(EdltError):self.issue()
        finally:self.reset.lifecycle=old
        _validate_factory_context(receipt,self.reset)

    def test_deliberate_issued_content_corruption_is_detected(self):
        for name,value in [('dirty_parameters',(True,)),('parameter_order',tuple(reversed(self.raw))),
                           ('expected_raw',{**self.raw,'Project':'CHANGED'}),('specification_sha256','changed'),
                           ('context',GlobalPreparationContext(self.identity.source,'OTHER','NetPrj'))]:
            receipt=self.issue();object.__setattr__(receipt,name,value)
            with self.subTest(name=name),self.assertRaises(EdltError):_validate_factory_context(receipt,self.reset)
        receipt=self.issue();object.__setattr__(receipt.metadata,'applications_complete',False)
        with self.assertRaises(EdltError):_validate_factory_context(receipt,self.reset)

    def test_reset_and_preparation_subclasses_are_not_canonical_issuers(self):
        class ResetChild(EdltResetControls):pass
        class PreparationChild(EdltGlobalPreparation):pass
        with self.assertRaises(EdltError):self.issue(reset_editor=ResetChild(self.spec))
        with self.assertRaises(EdltError):PreparationChild(self.spec).factory_context(self.raw,
            reset_editor=self.reset,context=self.identity,metadata=self.cache)


if __name__=='__main__':unittest.main()
