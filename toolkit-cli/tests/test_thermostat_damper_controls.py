"""Independent source-literal damper callbacks and one owning settings history."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.thermostat_damper_controls import DamperControlModel, normalize_damper_operation
from cbus_toolkit.thermostat_output_groups import OutputGroupModel
from cbus_toolkit.thermostat_post_load import DAMPERS
from cbus_toolkit.thermostat_remote_references import (_GraphResolver, RemoteCreation,
    plan_remote_references, snapshot_project, validate_remote_plan, verify_project_preservation)
from cbus_toolkit.thermostat_templates import ThermostatTemplateError, NativeThermostatTemplateError
from cbus_toolkit.unitspec import UnitSpecStore
from test_thermostat_output_groups import seed, raw_values, materialize, FIELDS
from test_thermostat_remote_references import PATH
from test_thermostat_settings import _spec

FIXTURES=Path(__file__).resolve().parents[1]/'research'/'fixtures'
import os
VECTORS=json.loads((FIXTURES/'thermostat-damper-independent-literal-vectors.json').read_text())
PROVENANCE=json.loads((FIXTURES/'thermostat-damper-independent-literal-provenance.json').read_text())

def owner_for(case):
    values=dict(case['values'])
    raw={key:str(value) for key,value in values.items()}
    groups={int(key):name for key,name in case['groups'].items()}
    graph=snapshot_project(seed(case['kind'],raw,{56:groups,172:{7:'Existing zone'},203:{}}),PATH)
    owner=OutputGroupModel(values,'basic' if 'TSB' in case['kind'] else 'programmable',case['kind'],_GraphResolver(graph))
    owner.load()
    return owner

def addresses(rows):
    return [None if row is None else row['address'] for row in rows]

class DamperControlTests(unittest.TestCase):
    def test_independent_vector_provenance_and_full_values(self):
        raw=(FIXTURES/'thermostat-damper-independent-literal-vectors.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),PROVENANCE['literal_sha256'])
        self.assertEqual(len(VECTORS['cases']),PROVENANCE['cases'])
        self.assertFalse(VECTORS['producer_output_used'])
        self.assertFalse(PROVENANCE['original_instructions_executed'])
        self.assertEqual(PROVENANCE['ordered_installed_bits'],[2,4,8,16])
        self.assertEqual(PROVENANCE['cache_slots_by_zone'],['0x168','0x160','0x164','0x16c'])
        self.assertEqual(len({row['id'] for row in VECTORS['cases']}),len(VECTORS['cases']))
        for row in VECTORS['cases']:
            self.assertTrue(set(FIELDS).issubset(row['values']))
            self.assertIn('InstalledZones',row['values'])
            self.assertIn('InternalPlantZones',row['values'])

    def test_source_annex_pins_exact_branches_and_declarations(self):
        source=json.loads((FIXTURES/'thermostat-damper-controls-static.json').read_text())
        self.assertEqual(source['format'],'cbus-thermostat-damper-controls-source-v1')
        self.assertEqual(source['method_count'],92)
        self.assertEqual(source['check_count'],33)
        self.assertTrue(all(source['checks'].values()))
        self.assertEqual(source['binding_count'],5)
        self.assertEqual(source['facts']['installed_zone_field'],'InstalledZones')
        self.assertEqual(source['facts']['separate_plant_zone_field'],'InternalPlantZones')
        self.assertEqual(source['facts']['cache_offsets_by_zone'],PROVENANCE['cache_slots_by_zone'])
        self.assertEqual(source['dfm']['sha256'],'c72c47427e0081398916158ad9d5c99efac59ef4478ea520ca2b8d2d51bd2a80')
        self.assertFalse(source['original_instructions_executed'])
        self.assertFalse(source['workflow_acceptance'])

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_TOOLKIT_MAP'),
                         'Explicit original EXE/MAP required for source-data-only verification')
    def test_fresh_source_data_matches_annex(self):
        import sys
        research=Path(__file__).resolve().parents[1]/'research'
        sys.path.insert(0,str(research));self.addCleanup(lambda:sys.path.remove(str(research)))
        from thermostat_damper_controls_static import extract
        actual=extract(Path(os.environ['CBUS_TOOLKIT_EXE']).read_bytes(),Path(os.environ['CBUS_TOOLKIT_MAP']).read_bytes())
        self.assertEqual(actual,json.loads((FIXTURES/'thermostat-damper-controls-static.json').read_text()))

    def test_literal_explicit_histories(self):
        for case in VECTORS['cases']:
            with self.subTest(case=case['id']):
                owner=owner_for(case); before=dict(owner.values)
                model=DamperControlModel(owner)
                for position,event in enumerate(case['events'],1):
                    model.process(event,position)
                view=model.as_dict(); expected=case['expected']
                self.assertEqual(addresses(view['model_references']),expected['references'])
                self.assertEqual(addresses(view['caches']),expected['caches'])
                for key in ('warnings','installed_zones','checked','model_modulation','shown','after_show_installed','help_bound'):
                    self.assertEqual(view[key],expected[key],key)
                self.assertEqual([alert['code'] for alert in view['alerts']],expected['alert_codes'])
                self.assertEqual(model.expected,expected['expected'])
                self.assertEqual([{'address':row.address,'name':owner.resolver.live[row.application,row.address].name} for row in owner.resolver.operations if type(row) is RemoteCreation],expected['creations'])
                ledger=[]
                for change in owner.resolver.operations:
                    entry={'action':change.action,'address':change.address,'name':change.name}
                    if change.action == 'rename':entry['previous_name']=change.previous_name
                    ledger.append(entry)
                self.assertEqual(ledger,expected['graph_operations'])
                self.assertEqual(owner.values,before) # callbacks do not overwrite the source snapshot
                self.assertEqual(owner.values['InternalPlantZones'],before['InternalPlantZones'])
                if 'expected_boolean_writes' in case:
                    self.assertEqual(view['operations'][0]['boolean_writes'],case['expected_boolean_writes'])
                self.assertFalse(view['automatic_subscriber_dispatch_reproduced'])
                self.assertFalse(view['quick_zone_gui_reproduced'])
                self.assertFalse(view['physical_device_programmed'])

    def test_cached_live_name_and_identity_after_edit(self):
        case=VECTORS['cases'][0]; owner=owner_for(case)
        # Choose a programmable owner, regardless of vector ordering.
        self.assertEqual(owner.family,'programmable')
        model=DamperControlModel(owner)
        model.process({'op':'damper-form-show'},1)
        identity=model.cache[0].identity
        model.process({'op':'damper-installed-zones','value':0},2)
        model.process({'op':'damper-zone-update'},3)
        owner.references['DamperZone1']=owner.resolver.live[56,40]
        owner.operate([json.dumps({'op':'edit-output-group','parameter':'DamperZone1Output','outcome':'accept','name':'Renamed cached damper'})],project_tag_name='Synthetic project',validate_address=lambda *_:None)
        owner.references['DamperZone1']=owner.resolver.live[56,255]
        model.process({'op':'damper-installed-zones','value':2},5)
        model.process({'op':'damper-zone-update'},6)
        view=model.as_dict()
        self.assertEqual(view['caches'][0]['identity'],identity)
        self.assertEqual(view['caches'][0]['name'],'Renamed cached damper')
        self.assertEqual(view['model_references'][0],view['caches'][0])
        self.assertEqual([row['address'] for row in view['model_references']],[40,255,255,255])

    def test_source_callback_root_and_model_are_distinct(self):
        owner=owner_for(VECTORS['cases'][0]); model=DamperControlModel(owner)
        model.process({'op':'damper-form-show'},1)
        oldcache=model.cache[0]; oldwarning=model.warnings[0]
        for bound in (None,object()):
            with self.subTest(bound=type(bound).__name__):
                row=model._group_change(1,bound)
                self.assertEqual(row['branch'],'nil-or-non-group')
                self.assertIs(model.cache[0],oldcache)
                self.assertEqual(model.warnings[0],oldwarning)
        model._group_change(1,owner.resolver.live[56,255])
        self.assertFalse(model.warnings[0]);self.assertIs(model.cache[0],oldcache)
        owner.references['DamperZone1']=owner.resolver.live[56,41]
        row=model._group_change(1,owner.resolver.live[56,40])
        self.assertEqual(row['controller_identity'],owner.resolver.live[56,40].identity)
        self.assertEqual(model.cache[0].identity,owner.resolver.live[56,41].identity)
        self.assertTrue(model.warnings[0])
        # An object not belonging to this exact causal inventory cannot bind.
        foreign=replace(owner.resolver.live[56,40],identity='unissued-foreign-identity')
        with self.assertRaises(ThermostatTemplateError):model._group_change(1,foreign)

    def test_normalizer_refusals_and_no_detached_continuation(self):
        invalid=[{'op':'damper-installed-zones','value':v} for v in (-1,32,True,'2',None)]
        invalid += [{'op':'damper-group-change','zone':v} for v in (0,5,True,'1',None)]
        invalid += [{'op':'damper-modulation-binding','checked':v} for v in (0,1,'true',None)]
        invalid += [{'op':'damper-modulation-click','checked':True,'cache':[]}]
        for row in invalid:
            with self.subTest(row=row),self.assertRaises(ThermostatTemplateError):normalize_damper_operation(row)
        self.assertIsNone(normalize_damper_operation({'op':'ordinary-unrelated'}))
        with self.assertRaises(ThermostatTemplateError):DamperControlModel({'caches':[None]*4})
        owner=owner_for(VECTORS['cases'][0]);model=DamperControlModel(owner)
        with self.assertRaises(ThermostatTemplateError):model.process({'op':'damper-after-show'},1)
        with self.assertRaises(ThermostatTemplateError):DamperControlModel(model.as_dict())

    def test_255_only_free_is_reserved_and_refuses(self):
        case=dict(VECTORS['cases'][0]);case['kind']='PC_TSB5'
        case['groups']={str(n):'Occupied '+str(n) for n in range(255)}
        case['values']=case['values']|dict(zip(FIELDS,range(30,53)))
        owner=owner_for(case);model=DamperControlModel(owner)
        self.assertNotIn((56,255),owner.resolver.live)
        self.assertEqual([owner.references[role] for role in DAMPERS],[None]*4)
        model.process({'op':'damper-installed-zones','value':2},1)
        before=dict(owner.resolver.live)
        with self.assertRaises(ThermostatTemplateError):model.process({'op':'damper-zone-update'},2)
        self.assertEqual(owner.resolver.live,before)
        self.assertNotIn((56,255),owner.resolver.live)

    def test_all_256_group_capacity_refuses_without_changing_graph(self):
        case=dict(VECTORS['cases'][0]);case['groups']={str(n):'Existing '+str(n) for n in range(256)}
        case['values']=case['values']|{name:255 for name in FIELDS[14:18]}
        owner=owner_for(case);model=DamperControlModel(owner)
        model.process({'op':'damper-installed-zones','value':2},1)
        before=dict(owner.resolver.live)
        with self.assertRaises(ThermostatTemplateError):model.process({'op':'damper-zone-update'},2)
        self.assertEqual(owner.resolver.live,before)
        self.assertEqual(owner.resolver.operations,[])

    def test_same_zone_mask_has_no_boolean_notification_intents(self):
        owner=owner_for(VECTORS['cases'][0]);model=DamperControlModel(owner)
        row=model.process({'op':'damper-installed-zones','value':30},1)
        self.assertTrue(all(not r['changed'] and not r['notification_intent'] for r in row['boolean_writes']))
        self.assertEqual(addresses(row['after']['model_references']),[40,41,42,43])

    def test_scalar_first_callback_owned_final_form_save(self):
        from unittest.mock import Mock
        from cbus_toolkit.thermostat_settings import NativeThermostatSettings
        from test_thermostat_settings import snapshot
        raw=snapshot(InternalPlantType=6,ControlledZones=30,InstalledZones=30,InternalPlantZones=30,
            DamperModulationEnable=0)
        raw.update({name:'255' for name in FIELDS})
        raw.update(ApplicationNumber='56',ZoneGroup='7',InstallationCode='1')
        xml=seed('PC_TSA5',raw,{56:{255:'<Unused>'},172:{7:'Zone'},203:{}})
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        Path(temporary.name,'THERMOSTATA.xml').write_text(_spec('THERMOSTATA',set(raw)))
        store=UnitSpecStore(temporary.name)
        identity=dict(snapshot_project(xml,PATH).unit_identity)
        manager=NativeThermostatSettings(Mock(),store)
        manager._operation=Mock();manager._networks=Mock(return_value=('//REMOTE/11',))
        manager._read=Mock(return_value=('literal source snapshot',identity,raw))
        manager._xml=Mock(return_value=xml);manager._fresh_settings=Mock()
        with self.assertRaisesRegex(NativeThermostatTemplateError,'DamperModulationEnable=3'):
            manager.plan(PATH,{'DamperModulationEnable':1},exclusive_project=True)
        history=[{'op':'damper-form-show'},{'op':'damper-modulation-binding','checked':True},
            {'op':'damper-installed-zones','value':2}]
        plan=manager.plan(PATH,{'DamperModulationEnable':1,'InstalledZones':0},
            exclusive_project=True,output_operations=history)
        self.assertEqual(plan.settings.expected['DamperModulationEnable'],3)
        self.assertEqual(plan.settings.expected['InstalledZones'],2)
        self.assertEqual(plan.settings.expected['ControlledZones'],2)
        state=plan.as_dict()['damper_controls']
        self.assertEqual(state['operations'][0]['before']['installed_zones'],0)
        self.assertTrue(state['operations'][0]['before']['model_modulation'])
        self.assertTrue(plan.remote.as_dict()['output_projection']['loaded_master'])
        self.assertEqual(plan.settings.expected.get('InternalPlantZones',30),30)
        manager.client.command.assert_not_called()

    def test_owned_plan_full_graph_and_opaque_level_preservation(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        raw=raw_values(InstalledZones=30,DamperModulationEnable=0,ControlledZones=30,InternalPlantZones=30,
            DamperZone1Output=40,DamperZone2Output=41,DamperZone3Output=42,DamperZone4Output=43)
        for family in ('THERMOSTATA','THERMOSTATB'):
            Path(folder.name,family+'.xml').write_text(_spec(family,set(raw)))
        store=UnitSpecStore(folder.name)
        apps={56:{255:'<Unused>',40:'Zone one',41:'Zone two',42:'Zone three',43:'Zone four'},172:{7:'Zone'},203:{}}
        xml=seed('PC_TSA5',raw,apps)
        operations=[{'op':'damper-form-show'},{'op':'damper-installed-zones','value':0},{'op':'damper-zone-update'},
            {'op':'damper-installed-zones','value':30},{'op':'damper-zone-update'}]
        plan=plan_remote_references(store,'PC_TSA5',raw,{},project_xml=xml,unit_path=PATH,output_operations=operations)
        self.assertEqual([plan.output_expected[name] for name in FIELDS[14:18]],[40,41,42,43])
        view=plan.as_dict()['output_projection']['damper_controls']
        self.assertEqual(addresses(view['caches']),[40,41,42,43])
        self.assertEqual(plan.graph_operations,())
        self.assertEqual(validate_remote_plan(store,plan),plan)
        root,created=materialize(plan)
        from xml.etree import ElementTree as ET
        preservation=verify_project_preservation(xml,ET.tostring(root,encoding='unicode'),PATH,
            changed_parameters=plan.expected,created_oids=created,graph_operations=plan.graph_operations)
        self.assertTrue(preservation['preserved'])
        # Receipts are projections, not a reconstructed-plan issuer.
        with self.assertRaises(ThermostatTemplateError):validate_remote_plan(store,replace(plan,roles_json='{}'))

if __name__=='__main__':unittest.main()
