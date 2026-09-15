"""Original navigation model, cached metadata and native parameter differential."""
from dataclasses import replace
import base64
import itertools
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_navigation import EdltNavigation, NavigationMetadata, NAVIGATION_VARIANTS, PAGE_MODES, TEMPERATURE_SOURCES
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from tests.test_edlt import fixture as common_fixture, Session
from tests.test_edlt_standby import mono, ROOT
from research.original_oracle import OriginalModelOracle, selected_backend


def fixture():
    base = common_fixture(); params = dict(base.parameters)
    for name, address, bit, bits, default in (
        ('TemperatureApplication', 0x201, 7, 1, 0), ('NavDevIDZoneGroup', 0x202, 0, 8, 0),
        ('NavChannelZoneNumber', 0x203, 0, 8, 0), ('DynamicGroup', 0x204, 0, 8, 0),
        ('NavigationOpaqueBits', 0x201, 4, 3, 5)):
        params[name] = ParameterSpec(name, 'int', 'synthetic.xml', {'Name': name, 'Type': 'int', 'Address': hex(address),
            'BitAddress': str(bit), 'BitSize': str(bits), 'DefaultValue': str(default)})
    return UnitSpec(base.filename, base.metadata, base.sources, params)


def metadata(application=56, group=42, variants=(0, 1, 2, 3)):
    return {'format': 'cbus-edlt-navigation-metadata-v1', 'groups': [{'application': application, 'group': group, 'dynamic_variants': list(variants)}]}


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltNavigation(self.spec); self.session = Session(self.spec)

    def test_page_mode_getter_normalizes_and_preserves_hidden_functional_widgets(self):
        source = self.editor.snapshot(self.session.values())
        for widget in range(6, 22): source[f'Widget{widget}WidgetType'] = (2,); source[f'Widget{widget}RestoreLevel'] = (widget,)
        source['Widget21WidgetByteValue31'] = (173,)
        for raw, expected in ((0, 'single'), (1, 'multiple'), (2, 'single'), (255, 'single')):
            plan = self.editor.plan({**source, 'NavWidgetType': (raw,)})
            self.assertEqual(plan.page_mode, expected)
            for name in source:
                if name.startswith('Widget') and name != 'WidgetsCRC': self.assertNotIn(name, plan.changes)
        single = self.editor.plan(source, page_mode='single'); multiple = self.editor.plan({**source, **single.changes}, page_mode='multiple')
        self.assertEqual(multiple.changes['NavWidgetType'], (1,)); self.assertNotIn('Widget21WidgetByteValue31', multiple.changes)
        for options in ({'variant': 'time'}, {'dynamic_group': 42}, {'page_names': {1: 'Page'}}):
            with self.assertRaisesRegex(EdltError, 'multiple'): self.editor.plan(source, page_mode='single', **options)

    def test_variant_change_resets_only6and7_same_selection_preserves(self):
        source = self.editor.snapshot(self.session.values()); source['NavWidgetType'] = (1,)
        source.update({f'PageNameIndex{page}': (40+page,) for page in range(1, 5)})
        for name, code in NAVIGATION_VARIANTS.items():
            plan = self.editor.plan(source, variant=name)
            self.assertEqual(plan.page_name_indices, (255,)*4 if code == 6 else (0,)*4 if code == 7 else (41,42,43,44))
            same = self.editor.plan({**source, 'NavWidgetVariant': (code,)}, variant=name)
            self.assertEqual(same.page_name_indices, (41,42,43,44))
        source['NavWidgetVariant'] = (12,)
        plan = self.editor.plan(source, page_mode='single'); self.assertEqual(plan.variant_raw, 12)
        self.assertFalse(plan.as_dict()['variant_ui_canonical']); self.assertIsNone(plan.as_dict()['variant'])

    def test_static_names_allocate_in_page_order_share_clear_and_preserve_old_refs_until_set(self):
        plan = self.editor.plan(self.session.values(), page_mode='multiple', variant='page-names',
            page_names={'4':'Same','2':'Same','1':'First','3':'  '})
        self.assertEqual(plan.page_name_indices, (63,62,255,62))
        self.assertTrue(plan.allocations[4].reused); self.assertEqual(plan.allocations[2].index, 62)
        source = {**plan.expected, **plan.changes}
        next_plan = self.editor.plan(source, page_names={1:'Next'})
        self.assertEqual(next_plan.page_name_indices, (61,62,255,62))
        self.assertEqual(next_plan.expected['StaticTextString63'], source['StaticTextString63'])
        for key, value in source.items():
            if key.startswith('Scene') or key == 'NavigationOpaqueBits': self.assertEqual({**source, **next_plan.changes}[key], value)
        selected = self.editor.plan(source, page_name_indices={1:0, 2:255})
        self.assertEqual(selected.page_name_indices[:2], (0,255))
        for options in ({'page_names': {1:'a'},'page_name_indices': {'1':0}}, {'page_names': {True:'x'}}, {'page_names': {'01':'x'}},
                        {'page_names': {1:'x','1':'x'}}, {'page_names': {1:'\0'}}, {'page_names': {1:'é'*32}}, {'page_name_indices': {1:64}}):
            with self.subTest(options=options), self.assertRaises(EdltError): self.editor.plan(source, **options)

    def test_original_capacity_counts_measurement64_and_page255_before_allocation(self):
        for count in (61,62):
            source=self.editor.snapshot(self.session.values());source.update(NavWidgetType=(1,),NavWidgetVariant=(6,))
            for page in range(1,5):source[f'PageNameIndex{page}']=(255,)
            next_index=0
            for widget in range(7,22):
                source[f'Widget{widget}WidgetType']=(16,);source[f'Widget{widget}WidgetByteValue1']=(5,)
                for offset in range(10,14):source[f'Widget{widget}WidgetByteValue{offset}']=(next_index,);next_index+=1
            source['Widget6WidgetType']=(12,);source['Widget6WidgetByteValue10']=(60,)
            source['Widget6WidgetByteValue11']=(count-1,);source['Widget6WidgetByteValue13']=(64,)
            if count==61:
                plan=self.editor.plan(source,page_names={1:'New page'})
                self.assertEqual(plan.page_name_indices,(63,255,255,255));self.assertIn(64,plan.allocations[1].used_indices)
            else:
                with self.assertRaisesRegex(EdltError,'full'):self.editor.plan(source,page_names={1:'New page'})

    def test_dynamic_metadata_requires_correlated_group_and_available_indices(self):
        source = self.editor.snapshot(self.session.values()); source.update(NavWidgetType=(1,), NavWidgetVariant=(7,), DynamicGroup=(42,))
        plan = self.editor.plan(source, page_name_indices={1:0,2:1,3:2,4:3}, metadata=metadata())
        self.assertEqual(plan.page_name_indices, (0,1,2,3)); self.assertFalse(plan.as_dict()['physical_dynamic_labels_verified'])
        self.assertEqual(plan.as_dict()['dynamic_group_metadata']['status'], 'caller-cache-match')
        for supplied in (None, metadata(57), metadata(group=41), metadata(variants=()), metadata(variants=(0,1))):
            with self.assertRaises(EdltError): self.editor.plan(source, page_name_indices={1:3}, metadata=supplied)
        for group in (0,254,255):
            plan = self.editor.plan(source, dynamic_group=group)
            self.assertEqual(plan.dynamic_group, group)
            self.assertEqual(plan.as_dict()['dynamic_group_metadata']['status'], 'unused' if group == 255 else 'unverified')
        unused = self.editor.plan(source, dynamic_group=255, metadata=metadata(group=255, variants=()))
        with self.assertRaises(EdltError): self.editor.plan({**source, **unused.changes}, page_name_indices={1:0}, metadata=metadata(group=255, variants=()))
        source['PageNameIndex1'] = (200,)
        self.assertEqual(self.editor.plan(source, dynamic_group=255).page_name_indices[0], 200)

    def test_strict_metadata_bounds_immutability_and_duplicate_guards(self):
        for document in ({}, {**metadata(),'extra':1}, metadata(application=True), metadata(group=-1), metadata(variants=(True,)),
                         metadata(variants=(0,0)), metadata(variants=(4,)), metadata(group=255),
                         {'format':'cbus-edlt-navigation-metadata-v1','groups':metadata()['groups']*2},
                         {'format':'cbus-edlt-navigation-metadata-v1','groups':metadata()['groups']*513}):
            with self.subTest(document=document), self.assertRaises(EdltError): NavigationMetadata.from_dict(document)
        document=metadata(); plan=self.editor.plan(self.session.values(), metadata=document)
        document['groups'][0]['dynamic_variants'].clear()
        self.assertEqual(plan.options['metadata'].groups[0].dynamic_variants,(0,1,2,3))

    def test_temperature_source_bounds_hidden_values_and_explicit_metadata_scope(self):
        source=self.editor.snapshot(self.session.values()); source['NavWidgetType']=(1,)
        for device,channel in itertools.product((0,255),repeat=2):
            plan=self.editor.plan(source,variant='time-temperature',temperature_source='measurement',device_or_group=device,channel_or_zone=channel)
            self.assertEqual((plan.device_or_group,plan.channel_or_zone),(device,channel))
        plan=self.editor.plan(source,variant='date-temperature',temperature_source='hvac',device_or_group=254,channel_or_zone=4,metadata=metadata(172,254,()))
        self.assertEqual(plan.as_dict()['temperature_group_metadata']['status'],'caller-cache-match')
        for value in (5,255):
            with self.assertRaises(EdltError): self.editor.plan(source,variant='time-temperature',temperature_source='hvac',channel_or_zone=value)
        source.update(TemperatureApplication=(1,),NavChannelZoneNumber=(255,),DynamicGroup=(99,))
        plan=self.editor.plan(source,variant='blank')
        self.assertEqual((plan.channel_or_zone,plan.dynamic_group),(255,99));self.assertFalse(plan.as_dict()['temperature_channel_ui_canonical'])
        with self.assertRaises(EdltError): self.editor.plan(source,variant='blank',device_or_group=1)

    def test_invalid_options_schema_profile_forged_plan_and_stale_identity(self):
        for options in ({'page_mode':True},{'variant':'unknown'},{'temperature_source':'temperature'},{'dynamic_group':True}):
            with self.assertRaises(EdltError):self.editor.plan(self.session.values(),**options)
        with self.assertRaises(EdltError):EdltNavigation(self.spec,firmware='5.4.00')
        params=dict(self.spec.parameters);field=params['TemperatureApplication'];params[field.name]=replace(field,fields={**field.fields,'BitAddress':'6'})
        with self.assertRaises(EdltError):EdltNavigation(replace(self.spec,parameters=params))
        plan=self.editor.plan(self.session.values(),page_mode='multiple',variant='date')
        for forged in (replace(plan,variant_raw=True),replace(plan,temperature_raw=False),replace(plan,dynamic_group=False),replace(plan,changes={**plan.changes,'UnrelatedGlobal':(0,)})):
            with self.assertRaises(EdltError):self.editor.apply(self.session,forged)
        self.assertFalse(self.session.calls)
        self.session.identity['FirmwareVersion']='5.4.00'
        with self.assertRaises(EdltError):self.editor.configure(self.session,page_mode='multiple')
        self.session.identity['FirmwareVersion']='5.5.00';self.session.current['UnrelatedGlobal']=(0,)
        with self.assertRaises(EdltError):self.editor.apply(self.session,plan)
        self.assertFalse(self.session.calls)

    def test_apply_rollback_disconnect_and_same_interrupt_object(self):
        before=self.editor.snapshot(self.session.values());self.session.failure='NavWidgetVariant'
        with self.assertRaises(EdltApplyError) as caught:self.editor.configure(self.session,page_mode='multiple',variant='date')
        self.assertTrue(caught.exception.details['rollback_verified']);self.assertEqual(self.editor.snapshot(self.session.values()),before)
        for error in (KeyboardInterrupt(),SystemExit(9),ConnectionError('lost')):
            session=Session(self.spec);calls=[]
            def fail(name,value):calls.append(name);session.current[name]=value;session.connected=False;raise error
            session.set=fail
            with self.assertRaises(type(error) if not isinstance(error,Exception) else EdltApplyError) as caught:
                self.editor.configure(session,page_mode='multiple',variant='date')
            self.assertEqual(len(calls),1)
            if not isinstance(error,Exception):self.assertIs(caught.exception,error);self.assertEqual(error.edlt_navigation_evidence['attempted_parameters'],calls)
            else:self.assertFalse(caught.exception.details['rollback_verified'])
        self.assertTrue(self.editor.configure(self.session,page_mode='multiple',variant='date')['verified'])

    def test_rollback_interrupt_retains_original_failure_and_stops(self):
        interruption=SystemExit(17);calls=[]
        def fail(name,value):
            calls.append(name)
            if len(calls)==1:raise RuntimeError('original navigation failure')
            raise interruption
        self.session.set=fail
        with self.assertRaises(SystemExit) as caught:self.editor.configure(self.session,page_mode='multiple',variant='date')
        self.assertIs(caught.exception,interruption);self.assertEqual(len(calls),2)
        evidence=interruption.edlt_navigation_evidence
        self.assertEqual(evidence['original_error']['error'],'original navigation failure')
        self.assertEqual(evidence['automatic_retries'],0);self.assertTrue(evidence['pp_state_uncertain'])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),'Set original Toolkit for navigation and cached-group model acceptance')
class OriginalNavigationTests(unittest.TestCase):
    def test_original84_navigation_getters_resets_and46_cached_metadata_rows(self):
        backend = selected_backend(); app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            for name in ('NativeEdltNavigationProbe.cs','NativeEdltCachedGroupProbe.cs'):(folder/name).write_bytes((ROOT/'research'/name).read_bytes())
            if backend == 'windows':
                with OriginalModelOracle(ROOT / 'research/NativeEdltNavigationProbe.cs', app, backend='windows') as oracle:
                    output = oracle.run()
                    capacity = oracle.run(('capacity',))
            else:
                output=mono(self,folder,'mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltNavigationProbe.cs && MONO_PATH=/input mono NativeEdltNavigationProbe.exe')
                capacity=mono(self,folder,'MONO_PATH=/input mono NativeEdltNavigationProbe.exe capacity')
            self.assertEqual(capacity.splitlines(),['capacity-61:ok:63','capacity-62:error:Static Text Table is full'])
            if backend == 'windows':
                with OriginalModelOracle(ROOT / 'research/NativeEdltCachedGroupProbe.cs', app, backend='windows') as oracle:
                    groups = oracle.run()
            else:
                groups=mono(self,folder,'mcs -r:/input/CBusLogicModel.dll -r:System.Drawing NativeEdltCachedGroupProbe.cs && MONO_PATH=/input mono NativeEdltCachedGroupProbe.exe')
        rows=dict(line.split(':',1) for line in output.splitlines());self.assertEqual(len(rows),84)
        for initial,expected in ((0,0),(1,1),(2,0),(3,0),(255,0)):
            self.assertEqual(rows['page-getter-'+str(initial)],f'{expected}:{1-expected}:{expected}')
        for name,variant in NAVIGATION_VARIANTS.items():
            fields=dict(item.split('=') for item in rows['variant-'+str(variant)].split('|'))
            self.assertEqual(tuple(int(fields['PageNameIndex'+str(page)]) for page in range(1,5)),(255,)*4 if variant==6 else (0,)*4 if variant==7 else (41,42,43,44))
            same=dict(item.split('=') for item in rows['same-variant-'+str(variant)].split('|'))
            self.assertEqual(tuple(int(same['PageNameIndex'+str(page)]) for page in range(1,5)),(41,42,43,44))
        records=groups.splitlines();self.assertEqual(len(records),46)
        data=dict(line.split(':',1) for line in records[-10:])
        self.assertIn('navigation-groups:255,42',records);self.assertIn('hvac-groups:255,0,254',records)
        self.assertIn('hvac-zones:0,1,2,3,4',records)
        self.assertIn('measurement-devices:'+','.join(map(str,range(256))),records)
        self.assertIn('measurement-channels:'+','.join(map(str,range(256))),records)
        self.assertEqual(data['dynamic42'],'0=Label 0|1=Label 1|2=Label 2|3=Label 3')
        self.assertEqual((data['logo-only42'],data['dynamic255'],data['dynamic99']),('0','0:0','0:0'))
        runtime=ROOT/'research/runtime/edlt-navigation';runtime.mkdir(parents=True,exist_ok=True)
        (runtime/'navigation-original-vectors.txt').write_text(output);(runtime/'navigation-capacity-vectors.txt').write_text(capacity);(runtime/'navigation-cached-vectors.txt').write_text(groups)
        if os.environ.get('CBUS_EDLT_NAVIGATION_VECTOR_REPORT'):
            path=Path(os.environ['CBUS_EDLT_NAVIGATION_VECTOR_REPORT']);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps({'passed': True, 'original_backend': backend, 'output': output, 'capacity': capacity, 'groups': groups}, indent=2) + '\n')


@unittest.skipUnless(all(os.environ.get(name) for name in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),'Set native C-Gate, specs and original Toolkit for full navigation acceptance')
class NativeNavigationTests(unittest.TestCase):
    def test_original_full_pp_static_order_raw_boundaries_hidden_widgets_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects,NativeDatabase
        from cbus_toolkit.programming import Programmer
        specs=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve();editor=EdltNavigation(UnitSpecStore(specs).load('KEYGL5.xml'))
        project='NV'+uuid4().hex[:6].upper();network='//'+project+'/254';source='/db'+network+'/p/20';report={'passed':False,'project':project,'cases':[]}
        backend = selected_backend(); report['original_backend'] = backend
        app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);(folder/'NativeEdltNavigationProbe.cs').write_bytes((ROOT/'research/NativeEdltNavigationProbe.cs').read_bytes())
            oracle = OriginalModelOracle(ROOT / 'research/NativeEdltNavigationProbe.cs', app, backend='windows') if backend == 'windows' else None
            if oracle is not None:
                self.addCleanup(oracle.close)
            else:
                mono(self,folder,'mcs -r:/input/CBusLogicModel.dll -r:System.Xml.Linq NativeEdltNavigationProbe.cs')
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                projects,database=NativeProjects(client),NativeDatabase(client);projects.operation('new',project);projects.operation('save',project)
                try:
                    database.create_network(project,254,'Navigation_Fixture','Cni','127.0.0.1:1');database.create_unit(network,20,'eDLT','KEYGL5','5.5.00',catalog_number='5055EDL')
                    with Programmer(client).load(network,source) as session:
                        for widget in range(1,22):session.set(f'Widget{widget}WidgetType','0')
                        # Canonical original8empty scenes retain genuine255 name
                        # references during allocations and save unchanged.
                        session.set('SceneCount','8')
                        for scene in range(1,9):session.set(f'Scene{scene}StartAddress',str((scene-1)*5))
                        session.set('SceneBucket',' '.join(map(str,[2,0,255,255,255]*8+[255]*192)))
                        session.set('NavWidgetType','255')
                        def case(label,**options):
                            before=editor.snapshot(session.values());plan=editor.plan(before,**options);after={**before,**plan.changes}
                            raw_before=bytes.fromhex(session.get_raw_data(0x200,9).lines[-1].split('RawData=')[1])
                            (folder/'values.tsv').write_text(''.join(name+'\t'+(value if isinstance(value,str) else ' '.join(hex(n) for n in value))+'\n' for name,value in before.items()))
                            lines=[]
                            for name,values in (('page_mode',PAGE_MODES),('variant',NAVIGATION_VARIANTS),('temperature_source',TEMPERATURE_SOURCES)):
                                if options.get(name) is not None:lines.append(name+'\t'+str(values[options[name]]))
                            for name in ('device_or_group','channel_or_zone','dynamic_group'):
                                if options.get(name) is not None:lines.append(name+'\t'+str(options[name]))
                            for page,text in (options.get('page_names') or {}).items():lines.append('text'+str(page)+'\t'+base64.b64encode(text.encode()).decode())
                            for page,index in (options.get('page_name_indices') or {}).items():lines.append('index'+str(page)+'\t'+str(index))
                            (folder/'options.tsv').write_text('\n'.join(lines)+'\n' if lines else '')
                            if oracle is not None:
                                output = oracle.run(('KEYGL5.xml', 'values.tsv', 'options.tsv'),
                                    files={'KEYGL5.xml': (specs / 'KEYGL5.xml').read_bytes(),
                                           'values.tsv': (folder / 'values.tsv').read_bytes(), 'options.tsv': (folder / 'options.tsv').read_bytes()})
                            else:
                                output=mono(self,folder,'MONO_PATH=/input mono NativeEdltNavigationProbe.exe /spec/KEYGL5.xml values.tsv options.tsv',specs=specs)
                            observed=dict(line[3:].split('\t',1) for line in output.splitlines() if line.startswith('pp:'))
                            for line in output.splitlines():
                                if line.startswith('memory-static:'):
                                    index,value=line[14:].split('\t',1);observed['StaticTextString'+index]=value
                            parsed=editor.snapshot(observed)
                            differences={name:(parsed[name],after[name]) for name in parsed if parsed[name]!=after[name]}
                            if differences:
                                path=ROOT/'research/runtime/edlt-navigation/last-differences.json';path.parent.mkdir(parents=True,exist_ok=True)
                                path.write_text(json.dumps({'label':label,'differences':differences},indent=2))
                            self.assertEqual(differences,{},label)
                            self.assertTrue(editor.apply(session,plan)['verified'])
                            raw=bytes.fromhex(session.get_raw_data(0x200,9).lines[-1].split('RawData=')[1])
                            expected=bytes((PAGE_MODES[plan.page_mode],plan.variant_raw|before['TemperatureApplication'][0]<<7,plan.device_or_group,plan.channel_or_zone,plan.dynamic_group,*plan.page_name_indices))
                            # Source raw bits4..6 are opaque; source temperature can change explicitly.
                            self.assertEqual(raw[1]&0x70,raw_before[1]&0x70)
                            self.assertEqual(raw[0],expected[0]);self.assertEqual(raw[1]&0x8f,plan.variant_raw|plan.temperature_raw<<7)
                            self.assertEqual(raw[2:],expected[2:])
                            self.assertEqual({name:value for name,value in after.items() if name.startswith('Widget') and name not in ('WidgetsCRC',)},
                                {name:value for name,value in before.items() if name.startswith('Widget') and name not in ('WidgetsCRC',)}) if label.startswith('hidden-') else None
                            report['cases'].append({'label':label,'raw_hex':raw.hex(),'parameters_compared':len(observed),'crcs':{k:list(v) for k,v in editor.crcs(after).items()}})
                            return plan
                        case('default-page-getter')
                        for name in NAVIGATION_VARIANTS:case('variant-'+name,page_mode='multiple',variant=name)
                        case('static-text-order',variant='page-names',page_names={4:'Unique D',2:'Unique B',1:'Kitchen',3:'Unique B'})
                        case('static-same-reuse',variant='page-names',page_names={1:'Unique D',2:''})
                        case('static-explicit-index',page_name_indices={3:0,4:255})
                        case('dynamic-default-reset',variant='dynamic-labels',dynamic_group=42)
                        case('dynamic-metadata-selection',page_name_indices={1:3,2:2,3:1,4:0},metadata=metadata())
                        for group in (0,254,255):case('logo-group-'+str(group),variant='logo',dynamic_group=group)
                        for device,channel in itertools.product((0,255),repeat=2):case('measurement-endpoints',variant='time-temperature',temperature_source='measurement',device_or_group=device,channel_or_zone=channel)
                        for group,zone in itertools.product((0,254,255),(0,4)):case('hvac-endpoints',variant='date-temperature',temperature_source='hvac',device_or_group=group,channel_or_zone=zone)
                        for widget in range(6,22):session.set(f'Widget{widget}WidgetType','10');session.set(f'Widget{widget}RestoreLevel',str(widget))
                        session.set('Widget21WidgetByteValue31','173')
                        case('hidden-single',page_mode='single');case('hidden-multiple',page_mode='multiple')
                        final=editor.snapshot(session.values());session.save_to_source()
                    for action in ('save','close','load'):projects.operation(action,project)
                    with Programmer(client).load(network,source) as session:self.assertEqual(editor.snapshot(session.values()),final)
                    self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines));report.update(passed=True,saved_reloaded=True,network_state='new',physical_device_verified=False)
                finally:projects.operation('close',project);projects.operation('delete',project)
        path=Path(os.environ.get('CBUS_EDLT_NAVIGATION_REPORT',ROOT/'research/runtime/edlt-navigation/native-report.json'));path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2)+'\n')
