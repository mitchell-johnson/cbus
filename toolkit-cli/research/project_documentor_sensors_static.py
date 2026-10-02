"""Read-only pinned source proof for multisensor and thermostat reports.

No original instructions execute. Method spans, VMT slots, loader guards and
factory registrations are read directly from the hash-pinned EXE/MAP. These
facts establish fresh snapshot projections, not original generated-page or
physical acceptance. Proprietary code and private unit catalogues stay private.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256
from csv_factory_registry_static import source_registry
from project_documentor_classic_key_macro_original import SourceMacroOracle
from key_preset_families import Image, subsets
from cbus_toolkit import project_documentation_multisensor as multi
from cbus_toolkit import project_documentation_thermostat as thermo


def inspect(exe, map_file):
    raw, symbols = exe.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=EXE_SHA256 or hashlib.sha256(symbols).hexdigest()!=MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    t=_Toolkit(raw,symbols)
    methods,checks={},{}

    def method(name):
        if name not in methods: methods[name]=t.method(name)
        return methods[name]

    def has(name,address,mnemonic,operands):
        return (address,mnemonic,operands) in method(name)['instructions']

    def call(name,address,target):
        return has(name,address,'call',hex(t.by_name[target]))

    def calls(name,target):
        return any(m=='call' and o==hex(t.by_name[target]) for _,m,o in method(name)['instructions'])

    def constant(name,value,byte=False):
        return any(m=='mov' and o==f'{"byte" if byte else "dword"} ptr [ebp - {"5" if byte else "8"}], {value}'
                   for _,m,o in method(name)['instructions'])

    rows=[row for row in source_registry(exe,map_file,())['registrations']
          if row['unit_type'] in multi.TYPES|thermo.PROFILES.keys()
          and row['class'] in set(multi.PROFILE_CLASSES)|{pair[0] for pair in thermo.PROFILES.values()}]
    actual=sorted((r['unit_type'],r['firmware_min'],r['firmware_max'],r['class'],r['agent']) for r in rows)
    expected=[('PC_TSA','0','9','TPC_TSA','TCBusProgrammableThermostatCGateAgent'),
              ('PC_TSA5','0','9','TPC_TSA5','TCBusProgrammableThermostatCGateAgent'),
              ('PC_TSB','0','9','TPC_TSB','TCBusBasicThermostatCGateAgent'),
              ('PC_TSB5','0','9','TPC_TSB5','TCBusBasicThermostatCGateAgent'),
              ('SENPILL','1.6.00','2.0.00','TSENPILL','TCBusMultisensorCGateAgent'),
              ('SENPILL','2.0.01','2.3.9','TST7SENPILL','TCBusST7MultisensorCGateAgent'),
              ('SENPILL','2.4','9','TSENPILLA','TCBusSurfaceMountMultisensorCGateAgent'),
              ('SENPILLA','0','9','TSENPILLA','TCBusSurfaceMountMultisensorCGateAgent'),
              ('SENPIRIB','2.4','9','TSENPIRIC','TCBusSurfaceMountPIRSensorCGateAgent'),
              ('SENPIRIC','0','9','TSENPIRIC','TCBusSurfaceMountPIRSensorCGateAgent'),
              ('SENLLA','0','9','TSENLLA','TCBusSurfaceMountLightLevelSensorCGateAgent')]
    checks['exact_factory_rows']=actual==sorted(expected)
    body='CIS_TMultisensorDocumentor.TMultisensorDocumentor.DocumentHTML'
    checks['multisensor_body_delegates_neo']=call(body,0xca84a4,'CIS_TNeoInputDocumentor.TNeoInputDocumentor.DocumentHTML') and method(body)['literals']==[]
    checks['multisensor_action_is_neo_not_pro']=t.slot('CIS_TMultisensorDocumentor..TMultisensorDocumentor',0x80)=='CIS_TNeoInputDocumentor.TNeoInputDocumentor.ActionSelectorUse'
    checks['thermostat_action_empty_base']=t.slot('CIS_TThermostatDocumentor..TThermostatDocumentor',0x80)=='CIS_TProjectDocumentor.TUnitTypeDocumentor.ActionSelectorUse'
    profiles=[]
    for cls in ('TSENPILL','TST7SENPILL','TSENPILLA','TSENPIRIC','TSENLLA'):
        sym=next(n for n in t.by_name if n.endswith('..'+cls))
        slots={hex(s):t.slot(sym,s) for s in (0x128,0x12c,0x130,0x16c,0x190,0x194,0x1a4,0x1a8,0x1c4,0x1cc,0x1e8,0x234,0x238,0x244,0x260)}
        profiles.append({'class':cls,'ancestry':t.ancestry(sym),'slots':slots})
        for s in (0x16c,0x190,0x194): checks[f'{cls}:eight_{s:x}']=constant(slots[hex(s)],8)
        checks[cls+':infrared']=constant(slots['0x1a4'],1,True)
        checks[cls+':no_brightness']=constant(slots['0x1a8'],0,True)
        checks[cls+':empty_output']=slots['0x12c']=='CIS_TCommonCBus.TCBUSUnit.DescribeOutputGroupDependencyAdvanced'
        checks[cls+':macro_subset']=method(slots['0x1c4'])['literals']==['SENLLA' if cls=='TSENLLA' else 'SENPILL']
        method(slots['0x128']);method(slots['0x130']);method(slots['0x1cc'])
        if cls!='TSENPILL':checks[cls+':no_key_disable']=constant(slots['0x260'],0,True)
    for cls in ('TPC_TSA','TPC_TSA5','TPC_TSB','TPC_TSB5'):
        sym='CIS_TThermostat..'+cls
        checks[cls+':thermostat_dependencies']=all('TThermostat.Describe'+k+'GroupDependencyAdvanced' in t.slot(sym,s) for k,s in [('Input',0x128),('Output',0x12c),('Other',0x130)])
        checks[cls+':relay_support']=constant(t.slot(sym,0x178),1 if cls.endswith('5') else 0,True)
    thermobody='CIS_TThermostatDocumentor.TThermostatDocumentor.DocumentHTML'
    checks['thermostat_base_first']=call(thermobody,0xfd583c,'CIS_TProjectDocumentor.TUnitTypeDocumentor.DocumentHTML')
    ordered=('Master/Slave: ','Plant Type: ','UI Displayed Temperature Zone: ','<tr><th>Plant Zone</th><td>',
             '<tr><th>Cooling Operation</th><td>','<tr><th>Heating Operation</th><td>',
             '<tr><th>Venting Operation</th><td>','<tr><th>User Controlled</th><td>',
             '<tr><th>Local Temperature Sensor</th><td>','Guard Enabled<br/>','Fan Operation Mode: ',
             '<tr><th colspan="2">Heating Fan</th></tr>','<tr><th colspan="2">Cooling Fan</th></tr>',
             '<tr><th colspan="2">Scheduling</th></tr>','<tr><th colspan="2">Internal Relays</th></tr>')
    positions=[method(thermobody)['literals'].index(text) for text in ordered]
    checks['thermostat_complete_body_order']=positions==sorted(positions)
    checks['thermostat_malformed_outer_fan_table']='<table>' in method(thermobody)['literals'] and '</tr></table>' in method(thermobody)['literals'] and '<tr>' not in method(thermobody)['literals']
    checks['thermostat_display_labels_present']=all(label.encode('utf-16le') in raw for label in (*thermo.PLANT_LABELS,*thermo.ZONE_LABELS,*thermo.FAN_LABELS))
    load='CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation'
    checks['signed_guard_threshold_fields']=has(load,0x128e7fd,'mov','eax, dword ptr [eax + 0x138]') and has(load,0x128e884,'mov','eax, dword ptr [eax + 0x144]') and all(has(load,a,'movsx','edx, al') for a in (0x128e808,0x128e88f))
    checks['guard_conversion']=all(call(load,a,'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.CGateTempToUnitTemp') for a in (0x128e80e,0x128e895))
    checks['fan_delay_division_round']=all(has(load,a,'fdiv','dword ptr [0x128f99c]') for a in (0x128ee90,0x128eec6,0x128ef9a,0x128efd0)) and struct.unpack('<f',t.pe.get_data(0x128f99c-t.base,4))[0]==6 and calls(load,'System.@ROUND')
    prefix='CIS_TThermostat.TPlantControlService.AutogeneratedPrefix'
    checks['auto_prefix_uses_zone_group']=calls(prefix,'CIS_TThermostat.TCBusParameters.GetZoneGroup') and method(prefix)['literals']==['CG','[%s%2.2d]']
    default='CIS_TThermostat.TPlantControlService.GetDefaultCoolStage1OutputGroupForPlantType'
    checks['existing_default_group_guard']=has(default,0xfe654b,'cmp','dword ptr [ebp - 8], 0xff') and call(default,0xfe6580,'CIS_TCommonCBus.TCBusGroupManager.GroupByAddress') and has(default,0xfe65c2,'call','0x6094d4') and has(default,0xfe65c8,'jne','0xfe67fe')
    primary='CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.GetApplicationObject'
    checks['primary_is_inherited_application']=has(primary,0xcb80e9,'mov','eax, dword ptr [eax + 0x88]') and has(primary,0xcb8107,'mov','eax, dword ptr [eax]') and call(primary,0xcb8120,'CIS_TCommonCBus.TCBUSApplicationManager.ApplicationByAddress')
    network='CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.GetMasterUnitNetwork'
    checks['master_network_number']=call(network,0x128fa6b,'CIS_TCommonCBus.TCBusNetworkManager.NetworkByNetworkNumber')
    programmable='CIS_TCBusThermostatCGateAgent.TCBusProgrammableThermostatCGateAgent.AfterLoadProgrammingInformation'
    checks['program_boolean_normalization']=all(has(programmable,a,m,o) for a,m,o in [(0x1299769,'dec','eax'),(0x129976a,'jle','0x1299789'),(0x129976f,'xor','edx, edx'),(0x12997cB,'dec','eax'),(0x12997d1,'mov','edx, 1')])
    checks['both_ui_allocated_loaders']=all(calls(name,'CIS_TThermostat.TUIService.GetUIAllocatedZones') for name in (programmable,'CIS_TCBusThermostatCGateAgent.TCBusBasicThermostatCGateAgent.AfterLoadProgrammingInformation'))
    surface='CIS_TCBusSurfaceMountSensorCGateAgent.TCBusSurfaceMountMultisensorCGateAgent.AfterLoadProgrammingInformation'
    checks['target_clears_margin_before_load']=has(surface,0x121781c,'mov','edx, 0xff') and has(surface,0x121782e,'mov','eax, dword ptr [eax + 0x254]') and has(surface,0x1217844,'call','dword ptr [edx + 0x94]')
    checks['bank_threshold_distinct_objects']=calls(surface,'CIS_TCBusSurfaceMountSensorUnit.TCBusSurfaceMountMultisensorUnit.SetBankSwitchLowGroup') and calls(surface,'CIS_TCBusSurfaceMountSensorUnit.TCBusSurfaceMountMultisensorUnit.SetBankSwitchHighGroup') and all(has(surface,a,'mov','edx, 0xff') for a in (0x121794c,0x12179c6))
    occupancy='CIS_TCBusMultisensorUnit.TInputKeyOccupancy.EventFlagChanged'
    checks['fresh_event_gate_no_macro_rewrite']=all(has(occupancy,a,m,o) for a,m,o in [(0xd01039,'mov','byte ptr [ebp - 0xd], 0'),(0xd01071,'cmp','word ptr [eax + 0x31a], 0'),(0xd010b9,'cmp','word ptr [eax + 0x33a], 0'),(0xd010d8,'cmp','byte ptr [ebp - 0xd], 0'),(0xd010dc,'je','0xd01129')])
    timer='CIS_TInputKey.TInputKey.HandleMacroFunctionTemplateAfterChangeEvent'
    checks['movement_timer_before_lock']=all(has(timer,a,m,o) for a,m,o in [(0xd12b05,'sub','al, 6'),(0xd12b09,'add','al, 0xe9'),(0xd12b0b,'sub','al, 7'),(0xd12b2d,'mov','dx, 0x12c')]) and call(timer,0xd12b12,'CIS_TInputKey.TInputKey.GetPrimaryBlock') and call(timer,0xd12b34,'CIS_TInputKey.TInputBlock.SetTimer')
    reconcile='CIS_TKeyMacroFunction.TKeyMacroFunction.ReconcileTemplateAndGroup'
    checks['senpill_template_overrides']=all(has(reconcile,a,'mov',o) for a,o in [(0xc979be,'dl, 0x1a'),(0xc979fa,'dl, 0x1d'),(0xc97a36,'dl, 0x1e')])
    oracle=SourceMacroOracle(exe,map_file)
    all_subsets=subsets(Image(exe,map_file))
    checks['sensor_macro_subsets']=all_subsets['SENPILL']=={'0':[16,*range(14),30,29,33,34,*range(17,25),26],'202':[16,*range(16),30,29,33,34,*range(17,25),26],'255':[16]} and all_subsets['SENLLA']=={'0':[16,*range(14),34,*range(17,25),26]}
    checks['movement_first_matches']={commands:kind for commands,kind in oracle.first_match.items() if 27<=kind<=35}=={(7,0,0,0):31,(13,7,7,0):32,(13,15,7,15):34,(13,7,0,7):33}
    # Pin consumed constructor/loader/dependency/support methods, including
    # model setter chains. Retain only span/hash receipts, never raw code.
    patterns=(r'CIS_TCBusThermostatCGateAgent\..*\.(InternalCreate|AfterLoadProgrammingInformation|GetMasterUnit|IntUnitPlantTypeToVirtualPlantType)',
              r'CIS_TCBus(Multisensor|ST7Sensor|SurfaceMountSensor)CGateAgent\..*\.(InternalCreate|AfterLoadProgrammingInformation|LoadOccupancyKeys|LoadJoinMode)',
              r'CIS_TCBus(Multisensor|ST7Sensor|SurfaceMountSensor)Unit\..*\.(DescribeInputGroupDependencyAdvanced|DescribeOtherGroupDependencyAdvanced|RefreshMacroFunctionOverrides)',
              r'CIS_TThermostat\.(TThermostat\.(Describe.*GroupDependencyAdvanced|InternalCreate)|TZoneManagerService\.(InternalCreate|HandleControlledZonesAfterChange)|TUIService\.InternalCreate)',
              r'CIS_TCoreNeoProInputCGateAgent\..*\.(AfterLoadProgrammingInformation|LoadCorridorLinkAttributes)',
              r'CIS_TDocumentorCommon\.DisplayHTMLUnit')
    for name in t.by_name:
        if '..' not in name and any(re.fullmatch(p,name) for p in patterns):method(name)
    failed=[name for name,ok in checks.items() if not ok]
    if failed:raise ValueError('Sensor source checks failed: '+', '.join(failed))
    return {'format':'cbus-project-documentor-sensors-static-v1','exe_sha256':EXE_SHA256,'map_sha256':MAP_SHA256,
            'original_executed':False,'original_generated_page_comparison':'not_obtained','factory':rows,'profiles':profiles,
            'model_sha256':{Path(m.__file__).name:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (multi,thermo)},
            'checks':checks,'methods':{name:{'start':hex(m['start']),'end':hex(m['end']),'sha256':m['sha256']} for name,m in sorted(methods.items())},
            'macro_first_match':[{'commands':list(commands),'type':kind} for commands,kind in oracle.first_match.items()],
            'macro_labels':oracle.labels,'macro_subsets':{name:all_subsets[name] for name in ('SENPILL','SENLLA')},
            'limits':['Fresh saved snapshot with complete consumed PP, not original loading or prior GUI/process state.',
                      'Active join state and noncanonical scenes remain explicit refusals.',
                      'Existing group/Level display metadata is required; no native object auto-creation.',
                      'Thermostat Input requires existing non-autogenerated output groups and observed Network context.',
                      'Foreign masters require one explicit NetworkNumber, never an Address fallback.',
                      'Explicit Celsius/Fahrenheit formatting; no original running preference observation.',
                      'No original generated-page, physical bus or hardware acceptance claimed.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--map',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=inspect(args.exe,args.map)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'checks':len(report['checks']),'methods':len(report['methods']),'profiles':len(report['factory'])}))
