"""Independent static Time/Date proof and literal consumption; no vendor execution."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
RESEARCH=ROOT/'toolkit-cli/research'
ANNEX=RESEARCH/'fixtures/edlt-time-date-control-source-annex.json'
VECTORS=RESEARCH/'fixtures/edlt-time-date-control-literal-vectors.json'


def data(path):
    return json.loads(path.read_text())


def raw_record(values,widget):
    return bytes(values[f'Widget{widget}WidgetType' if i==0 else f'Widget{widget}WidgetByteValue{i}'][0] for i in range(32))


def put_record(values,widget,record):
    for i,value in enumerate(record):
        values[f'Widget{widget}WidgetType' if i==0 else f'Widget{widget}WidgetByteValue{i}']=(value,)


def source_values(case):
    values={'NavWidgetType':(0,),'UnitName':'Synthetic time/date control','Scene1StartAddress':(65535,)}
    for n in range(1,22):
        put_record(values,n,bytes(32))
        if n>=6:values[f'Widget{n}RestoreLevel']=(0,)
    values.update({n:(v,) for n,v in case['global_values'].items()})
    put_record(values,case['widget'],bytes.fromhex(case['record_hex']))
    if case['restore_level'] is not None:
        values[f"Widget{case['widget']}RestoreLevel"]=(case['restore_level'],)
    if case['adjacent_widget'] is not None:
        put_record(values,case['adjacent_widget'],bytes.fromhex(case['adjacent_record_hex']))
        if case['adjacent_restore_level'] is not None:
            values[f"Widget{case['adjacent_widget']}RestoreLevel"]=(case['adjacent_restore_level'],)
    return values


def operation(case):
    widget=case['widget']
    # Exact source slot mapping, distinct from navigation and covered-slot admission.
    page,position=(0,widget) if widget<6 else (1,widget-5) if widget<=10 else (1+(widget-6)//4,1+(widget-6)%4)
    return {'op':'time-date','page':page,'position':position,
            **({'page_mode':'multiple'} if widget>10 else {}),'time_date_controls':case['events']}


class TimeDateStaticTests(unittest.TestCase):
    def test_complete_static_spans_bindings_and_no_execution_claim(self):
        annex=data(ANNEX)
        self.assertEqual(len(annex['original_inputs']),16)
        self.assertEqual(len(annex['managed_method_spans']),71)
        self.assertEqual(len(annex['decompiled_source_symbols']),29)
        self.assertEqual(len(annex['static_checks']),41)
        self.assertEqual(len(annex['ordered_panel_bindings']),5)
        self.assertTrue(all(row['explicit_update_mode']==1 for row in annex['ordered_panel_bindings']))
        self.assertEqual({r['source_property'] for r in annex['ordered_panel_bindings']},
                         {'DisplayType','WidgetType','DateFormat','TimeFormat','TimeDateLeadingZero'})
        for key in ('original_executed','framework_executed','host_gui','service_executed','physical_verified','full_parity'):
            self.assertIs(annex['scope'][key],False)
        self.assertTrue(all('string_literals' not in r for r in annex['managed_method_spans']))
        ids={r['id'] for r in annex['static_checks']}
        self.assertTrue({'blank-default-inherited','base-default-restore-only',
            'next-widget-setter-before-selected-default','widgettype-notify-independent-of-widgetbase-suppression',
            'original-global-layout-masks-and-levelbarstyle-bit7','original-restore-only-functional-six-through21',
            'selected-index-handler-no-calls','formatted-display-default-name'}<=ids)
        for short in ('BlankData','TimeAndDateData'):
            row=next(r for r in annex['metadata_type_relationships'] if r['type'].endswith('.'+short))
            self.assertTrue(row['base_type'].endswith('.WidgetBaseData'))
        self.assertFalse(any(r['symbol'].endswith('BlankData::SetToDefault') for r in annex['managed_method_spans']))
        default=next(r for r in annex['managed_method_spans'] if r['symbol'].endswith('TimeAndDateData::SetToDefault'))
        self.assertTrue(default['method_virtual']);self.assertFalse(default['method_new_slot'])

    def test_exact_source_choices_original_layout_and_named_sibling(self):
        annex=data(ANNEX)
        choices=annex['source_choices']
        for name,values in {'l2SliceTimeDateStatus':[1,0,2],'LDateFormat':list(range(8)),
            'LTimeFormat':[3,1,0,2],'LWidgetTypesScreenSaverInt':[0,13,12,10,11],
            'LWidgetTypesScreenSaverIntNo2Slice':[0,13,12,10],
            'LWidgetTypesFunctionPages':[0,14,4,13,2,12,7,8,9,16,6,3,5,10,15]}.items():
            with self.subTest(source_list=name):self.assertEqual([r['value'] for r in choices[name]],values)
        layout=annex['unit_layout']
        self.assertEqual(layout['restore_widget_numbers'],list(range(6,22)))
        self.assertEqual(layout['sibling_field'],'LevelBarStyle');self.assertEqual(layout['sibling_mask'],128)
        self.assertEqual([(r['name'],r['address'],r['mask']) for r in layout['format_fields']],
                         [('DateFormat',281,15),('TimeDateLeadingZero',281,16),('TimeFormat',281,96),('LevelBarStyle',281,128)])

    def test_independent_vectors_cover_all_records_and_preserve_scope(self):
        vectors=data(VECTORS)
        self.assertEqual([len(vectors[k]) for k in ('property_cases','control_cases','notification_cases','offered_choice_cases','refusal_cases','parent_layout_cases','source_transition_cases')],
                         [113,150,32,24,14,5,2])
        self.assertFalse(vectors['authoring']['producer_imported']);self.assertFalse(vectors['authoring']['expected_from_producer_readback'])
        self.assertFalse(vectors['original_executed']);self.assertFalse(vectors['framework_executed'])
        for name in ('property_cases','control_cases','notification_cases','refusal_cases'):
            self.assertEqual(len({r['id'] for r in vectors[name]}),len(vectors[name]))
        for c in vectors['property_cases']+vectors['control_cases']+vectors['source_transition_cases']:
            with self.subTest(case=c['id']):
                self.assertEqual(len(bytes.fromhex(c['expected_record_hex'])),32)
                self.assertEqual(bytes.fromhex(c['record_hex'])[2:],bytes.fromhex(c['expected_record_hex'])[2:])
                if c['expected_adjacent_record_hex'] is not None:
                    self.assertEqual(len(bytes.fromhex(c['expected_adjacent_record_hex'])),32)
                    self.assertEqual(bytes.fromhex(c['adjacent_record_hex'])[1:],bytes.fromhex(c['expected_adjacent_record_hex'])[1:])
                self.assertEqual(c['global_values']['LevelBarStyle'],c['expected_global_values']['LevelBarStyle'])
        self.assertEqual(vectors['source_annex_sha256'],hashlib.sha256(ANNEX.read_bytes()).hexdigest())

    def test_independent_property_literals_consumed_by_actual_property_api(self):
        from cbus_toolkit.edlt_time_date_control_properties import (
            TimeDatePropertyState,read_time_date_property,write_time_date_property,set_time_date_default)
        for c in data(VECTORS)['property_cases']:
            with self.subTest(case=c['id']):
                g=c['global_values']
                state=TimeDatePropertyState(c['widget'],bytes.fromhex(c['record_hex']),
                    None if c['adjacent_record_hex'] is None else bytes.fromhex(c['adjacent_record_hex']),
                    c['restore_level'],c['adjacent_restore_level'],g['DateFormat'],g['TimeFormat'],g['TimeDateLeadingZero'])
                reads=[];intents=[]
                for call in c['calls']:
                    if call['kind']=='get':
                        result=read_time_date_property(state,call['property']);reads.append(result.value)
                    elif call['kind']=='set':result=write_time_date_property(state,call['property'],call['value'])
                    else:result=set_time_date_default(state)
                    intents.extend(result.notification_intents);state=result.state
                self.assertEqual(state.record.hex(),c['expected_record_hex'])
                self.assertEqual(None if state.adjacent_record is None else state.adjacent_record.hex(),c['expected_adjacent_record_hex'])
                self.assertEqual((state.restore_level,state.adjacent_restore_level),(c['expected_restore_level'],c['expected_adjacent_restore_level']))
                self.assertEqual((state.date_format,state.time_format,state.leading_zero),tuple(c['expected_global_values'][p] for p in ('DateFormat','TimeFormat','TimeDateLeadingZero')))
                self.assertEqual(reads,c.get('expected_read_values',[]))
                self.assertEqual(intents,c['expected_widget_notification_intents'])

    def test_independent_control_literals_consumed_without_expected_producer_readback(self):
        from cbus_toolkit.edlt_time_date_controls import issue_time_date_control_binding,project_time_date_controls,prepare_time_date_projection
        for c in data(VECTORS)['control_cases']:
            with self.subTest(case=c['id']):
                owner=object();values=source_values(c);op=operation(c)
                binding=issue_time_date_control_binding(owner=owner,operation=op,values=values,widget=c['widget'])
                projected=project_time_date_controls(binding,owner=owner,operation=op,values=values)
                record,changes,receipt=prepare_time_date_projection(projected,owner=owner)
                final={**values,**changes}
                self.assertEqual(record.hex(),c['expected_record_hex'])
                self.assertEqual(raw_record(final,c['widget']).hex(),c['expected_record_hex'])
                if c['adjacent_widget'] is not None:
                    self.assertEqual(raw_record(final,c['adjacent_widget']).hex(),c['expected_adjacent_record_hex'])
                if c['expected_restore_level'] is not None:
                    self.assertEqual(final[f"Widget{c['widget']}RestoreLevel"],(c['expected_restore_level'],))
                self.assertEqual({p:final[p][0] for p in c['expected_global_values']},c['expected_global_values'])
                self.assertEqual(final['UnitName'],values['UnitName']);self.assertEqual(final['Scene1StartAddress'],(65535,))
                intents=[item for row in receipt['journal'] for item in row['notification_intents']]
                self.assertEqual(intents,c['expected_widget_notification_intents'])
                self.assertTrue(all(row['pp_notification_delivery_established'] is False for row in receipt['journal']))
                self.assertFalse(receipt['implicit_framework_dispatch']);self.assertFalse(receipt['clock_set']);self.assertFalse(receipt['saved'])
                if c['expected_global_format_byte'] is not None:
                    g=c['expected_global_values'];actual=(final['DateFormat'][0]|(final['TimeDateLeadingZero'][0]<<4)|(final['TimeFormat'][0]<<5)|(final['LevelBarStyle'][0]<<7))
                    self.assertEqual(actual,c['expected_global_format_byte'])
                if c['id'].startswith('changed-type11-'):
                    self.assertEqual(projected.adjacent_widget,c['widget']+1)
                    self.assertEqual(projected.adjacent_after.hex(),c['expected_adjacent_record_hex'])
                if c['id'].startswith(('type11-to11-','type11-to10-','type10-to10-','same-functional-or-last10-')):
                    self.assertIsNone(projected.adjacent_widget)
                if c['id'].startswith('setup-widget-selection-'):
                    self.assertEqual([r['action'] for r in receipt['journal'][0]['binding_callbacks']],
                        ['DataBindings.SaveFirst','DataBindings.Clear','WidgetType.DataSource.Assign','DataBindings.AddSameBinding','Binding.ReadValue'])

    def test_source_token_notifications_remain_distinct_from_numeric_intents(self):
        # Independent raw-token/source guard interpreter; no vendor code or producer imports.
        for c in data(VECTORS)['notification_cases']:
            with self.subTest(case=c['id']):
                assigns=c['property']=='DisplayType' or c['current_numeric']!=c['requested']
                numeric=max(0,min(255,c['requested'])) if assigns else c['current_numeric']
                token=f'0x{numeric:X}' if assigns else c['current_token']
                notified=assigns and c['current_token']!=token and not c['bInitialiseMode']
                self.assertEqual((assigns,numeric,token,notified),(c['setter_assigns_attribute'],c['expected_numeric'],c['expected_token'],c['expected_Value_notification_intent']))
                self.assertEqual(notified,c['expected_HasBeenChanged'])

    def test_offered_choice_membership_is_complete_but_unrelated_target_admission_bounded(self):
        from cbus_toolkit.edlt_time_date_controls import time_date_choices
        for c in data(VECTORS)['offered_choice_cases']:
            with self.subTest(location=c['location'],choice=c['choice_index']):
                widget={'standby1..4':4,'standby5':5,'functional6..21':6}[c['location']]
                row=time_date_choices(widget)['widget-type'][c['choice_index']]
                self.assertEqual((row['identity'],row['value'],row['name'],row['formatted_display']),
                    (c['identity'],c['value'],c['name'],c['name']))
                self.assertEqual(c['time_date_adapter_target_admitted'],row['value'] in (10,11))

    def test_provenance_pins_annex_literal_and_extractor_without_self_hash_cycle(self):
        provenance=data(RESEARCH/'fixtures/edlt-time-date-control-provenance.json')
        for row in provenance['artifacts']:
            with self.subTest(path=row['path']):
                raw=(ROOT/row['path']).read_bytes()
                self.assertEqual((hashlib.sha256(raw).hexdigest(),len(raw)),(row['sha256'],row['bytes']))
        self.assertFalse(provenance['original_executed']);self.assertFalse(provenance['literal_authoring']['producer_imported'])
        self.assertNotIn('toolkit-cli/research/fixtures/edlt-time-date-control-provenance.json',[r['path'] for r in provenance['artifacts']])

    @unittest.skipUnless(os.environ.get('CBUS_TIME_DATE_STATIC_ROOT'), 'Requires explicitly configured pinned original static bytes; no instruction execution')
    def test_full_annex_regeneration_from_pinned_static_bytes(self):
        spec=importlib.util.spec_from_file_location('time_date_static',RESEARCH/'edlt_time_date_control_static.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        recovered=module.recover(ROOT,Path(os.environ['CBUS_TIME_DATE_STATIC_ROOT']))
        self.assertEqual((json.dumps(recovered,sort_keys=True,indent=2)+'\n').encode(),ANNEX.read_bytes())
