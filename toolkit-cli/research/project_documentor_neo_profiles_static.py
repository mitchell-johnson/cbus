"""Verify every Neo report class/profile with read-only pinned EXE/MAP evidence.

No original instructions run. Public output contains source identities, spans,
hashes, field/UI literals and profile facts; proprietary code bytes stay private.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import struct
import uuid

from project_documentor_static import EXE_SHA256, MAP_SHA256, UNIT_FACTORY, _Toolkit
from project_documentor_classic_key_static import BISTABLE_GUID, _interface_ancestry
from key_preset_families import Image, agent_registrations, key_count
from cbus_toolkit.project_documentation import REGISTRATIONS
from cbus_toolkit.project_documentation_neo_profiles import NEO_CLASS_PROFILES, COUPLER_TYPES, KEYE_TYPES

COUPLER = 'CIS_TCoreBusCouplerInputUnit.TCoreBusCouplerInputUnit.'
COUPLER_KEY = 'CIS_TCoreBusCouplerInputUnit.TInputKeyCoupler.'
COUPLER_AGENT = 'CIS_TCoreBusCouplerInputCGateAgent.TCoreBusCouplerInputCGateAgent.'
EX = 'CIS_TKEYEx.TKEYEx.'
EX_AGENT = 'CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.'
CLASSIC = 'CIS_TClassicKeyInputDocumentor.TClassicKeyInputDocumentor.DocumentHTML'
METHODS = (
    'CIS_TInputKey.TInputKey.HandleMacroFunctionTemplateAfterChangeEvent',
    'CIS_TKeyMicroFunction.InitialiseKeyMicroFunctionFactory',
    CLASSIC, COUPLER + 'InternalCreate', COUPLER + 'RefreshKeyCouplerCollection',
    COUPLER + 'GetBistableSwitch', COUPLER_KEY + 'InternalCreate', COUPLER_KEY + 'GetBistableSwitch',
    COUPLER_KEY + 'SetBistableSwitch', COUPLER_AGENT + 'InternalCreate',
    COUPLER_AGENT + 'CreateBistableSwitchAttribute', COUPLER_AGENT + 'LoadBistableSwitchAttribute',
    COUPLER_AGENT + 'AfterLoadProgrammingInformation', EX + 'InfraredBankPropertyEnabled',
    EX + 'GetDefaultKeyMask', EX + 'IsKeyConnected', EX_AGENT + 'AfterLoadProgrammingInformation',
    EX_AGENT + 'SetDefaultKeysIfNeeded',
    'CIS_TCoreNeoInputCGateAgent.TCoreNeoInputCGateAgent.AfterLoadProgrammingInformation',
    'CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.AfterLoadProgrammingInformation',
    'CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.InternalCreate',
    'CIS_TCBusNeoProInputUnit.TCBusNeoProInputUnit.InternalCreate',
    'CIS_TCBusDecoratorInputUnit.TCBusDecoratorInputUnit.InternalCreate',
    'CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.InternalCreate',
    'CIS_TCoreKeyInputUnit.TCoreKeyInputUnit.InternalCreate',
    'CIS_TNeoInputDocumentor.TNeoInputDocumentor.DocumentHTML',
    'CIS_TNeoProInputDocumentor.TNeoProInputDocumentor.DocumentHTML',
)


def inspect(executable: Path, map_file: Path) -> dict:
    raw, symbols = executable.read_bytes(), map_file.read_bytes()
    sha = lambda b: hashlib.sha256(b).hexdigest()
    if (sha(raw), sha(symbols)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Pinned original Toolkit EXE/MAP hash mismatch')
    image, tables = _Toolkit(raw, symbols), Image(executable, map_file)
    agents = agent_registrations(tables)
    methods = {name: image.method(name) for name in METHODS}
    report_types = {row[0] for row in REGISTRATIONS if row[1] in {'NeoInput','NeoProInput'}}
    factory, factory_spans = image.registrations(UNIT_FACTORY)
    native_rows = [row for row in factory if row[0] in report_types]
    expected = {(row.unit_type,row.class_name,row.firmware_min,row.firmware_max) for row in NEO_CLASS_PROFILES}
    actual = {(typ,cls.split('..')[-1],lo,hi) for typ,cls,lo,hi in native_rows}
    checks = {'complete_report_types': len(report_types)==43 and report_types=={r.unit_type for r in NEO_CLASS_PROFILES},
              'complete_factory_profiles': len(native_rows)==59 and actual==expected}
    rows = []
    for typ, cls, lo, hi in native_rows:
        profile = next(r for r in NEO_CLASS_PROFILES if (r.unit_type,r.class_name,r.firmware_min,r.firmware_max)==(typ,cls.split('..')[-1],lo,hi))
        slots = {hex(off): image.slot(cls,off) for off in (0xc,0x128,0x12c,0x130,0x16c,0x190,0x194,0x1a4,0x1a8,0x1c4,0x1cc,0x234,0x268)}
        for offset, name in slots.items():
            if name == "?" and offset == "0x268" and not profile.is_pro:
                continue  # No connectivity virtual method exists on old Neo.
            methods[name] = image.method(name)
        constructor = slots['0xc']
        constructor_parent = (COUPLER+'InternalCreate' if typ in COUPLER_TYPES else
            'CIS_TCBusDecoratorInputUnit.TCBusDecoratorInputUnit.InternalCreate' if typ.startswith('KEYDV') else
            'CIS_TCBusNeoProInputUnit.TCBusNeoProInputUnit.InternalCreate' if profile.is_pro else
            'CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.InternalCreate')
        parent_calls = [op for _,mn,op in methods[constructor]['instructions'] if mn=='call' and op==hex(image.by_name[constructor_parent])]
        checks[typ+':'+lo+':constructor_parent'] = len(parent_calls)==1
        ancestor = _interface_ancestry(image,cls)
        bistable = any(BISTABLE_GUID in item['interfaces'] for item in ancestor)
        checks[typ+':'+lo+':physical_keys'] = key_count(tables,cls,0x190)[1]==profile.physical_key_count
        checks[typ+':'+lo+':eight_blocks_keys'] = key_count(tables,cls,0x16c)[1]==key_count(tables,cls,0x194)[1]==8
        checks[typ+':'+lo+':bistable_interface'] = bistable==profile.bistable
        constant = [(mn,op) for _,mn,op in methods[slots['0x1a4']]['instructions']]
        checks[typ+':'+lo+':IR_slot'] = (slots['0x1a4']==EX+'InfraredBankPropertyEnabled' if typ in KEYE_TYPES else
            ('mov','byte ptr [ebp - 5], '+str(int(profile.infrared_virtual_keys))) in constant)
        checks[typ+':'+lo+':brightness_enabled'] = ('mov','byte ptr [ebp - 5], 1') in [(mn,op) for _,mn,op in methods[slots['0x1a8']]['instructions']]
        checks[typ+':'+lo+':macro_subset'] = methods[slots['0x1c4']]['literals']==['NEOPRO' if profile.is_pro else 'NEO']
        checks[typ+':'+lo+':no_macro_override'] = slots['0x1cc']=='CIS_TCoreKeyInputUnit.TCoreKeyInputUnit.RefreshMacroFunctionOverrides'
        checks[typ+':'+lo+':usage_slots'] = slots['0x128']=='CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.DescribeInputGroupDependencyAdvanced' and slots['0x12c']=='CIS_TCommonCBus.TCBUSUnit.DescribeOutputGroupDependencyAdvanced' and slots['0x130']==('CIS_TCBusNeoProInputUnit.TCBusNeoProInputUnit.DescribeOtherGroupDependencyAdvanced' if profile.other_dependency_pro else 'CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.DescribeOtherGroupDependencyAdvanced')
        checks[typ+':'+lo+':join_slot'] = slots['0x234']==(EX+'IsJoinModeSupported' if typ in KEYE_TYPES else COUPLER+'IsJoinModeSupported' if typ in COUPLER_TYPES else 'CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.IsJoinModeSupported' if profile.is_pro else 'CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.IsJoinModeSupported')
        agent = agents[cls]
        checks[typ+':'+lo+':one_agent'] = len(agent)==1
        loader = image.slot(agent[0],0xa4)
        methods[loader] = image.method(loader)
        checks[typ+':'+lo+':loader'] = loader==(COUPLER_AGENT+'AfterLoadProgrammingInformation' if typ in COUPLER_TYPES else EX_AGENT+'AfterLoadProgrammingInformation' if typ in KEYE_TYPES else 'CIS_TCBusNeoProInputCGateAgent.TCBusNeoProInputCGateAgent.AfterLoadProgrammingInformation' if profile.is_pro else 'CIS_TCBusNeoInputCGateAgent.TCBusNeoInputCGateAgent.AfterLoadProgrammingInformation')
        rows.append({**asdict(profile),'class_symbol':cls,'agent':agent[0],'after_load':loader,'slots':slots,'constructor':constructor,'constructor_parent':constructor_parent,
                     'ancestry':[{'class':a['class'],'interfaces':a['interfaces'],'interface_table_sha256':a['interface_table_sha256']} for a in ancestor]})
    def has(name,a,mn,op): return (a,mn,op) in methods[name]['instructions']
    def call(name,a,target): return has(name,a,'call',hex(image.by_name[target]))
    def literal(name,a,text): return methods[name]['literal_at'].get(a)==text
    checks.update({
        'timer_expiry_off_key_literal':literal('CIS_TKeyMicroFunction.InitialiseKeyMicroFunctionFactory',0xc8dd33,'Off Key'),
        'decorator_constructor_calls_pro':call('CIS_TCBusDecoratorInputUnit.TCBusDecoratorInputUnit.InternalCreate',0xf9b66e,'CIS_TCBusNeoProInputUnit.TCBusNeoProInputUnit.InternalCreate'),
        'pro_constructor_calls_core':call('CIS_TCBusNeoProInputUnit.TCBusNeoProInputUnit.InternalCreate',0xca060a,'CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.InternalCreate'),
        'coupler_constructor_calls_core_and_refreshes':call(COUPLER+'InternalCreate',0xce642e,'CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.InternalCreate') and call(COUPLER+'InternalCreate',0xce6465,COUPLER+'RefreshKeyCouplerCollection'),
        'KEYEx_constructor_creates_mask':methods[EX+'InternalCreate']['literals']==['KeyMask'],
        'KEYEx_IR_is_type_length_seven':has(EX+'InfraredBankPropertyEnabled',0xea93e8,'cmp','dword ptr [ebp - 0x10], 7') and has(EX+'InfraredBankPropertyEnabled',0xea93ec,'sete','byte ptr [ebp - 5]'),
        'KEYEx_default_uses_last_type_char':has(EX+'GetDefaultKeyMask',0xea9132,'mov','ax, word ptr [eax + edx*2 - 2]') and has(EX+'GetDefaultKeyMask',0xea9137,'sub','ax, 0x31'),
        'KEYEx_default_values':all(has(EX+'GetDefaultKeyMask',a,'mov','dword ptr [ebp - 8], '+v) for a,v in ((0xea914e,'1'),(0xea9157,'3'),(0xea9160,'7'),(0xea9169,'0xf'))),
        'KEYEx_bit_zero_gate':has(EX_AGENT+'SetDefaultKeysIfNeeded',0x12d27ac,'test','al, 1') and call(EX_AGENT+'SetDefaultKeysIfNeeded',0x12d27b8,EX+'GetDefaultKeyMask'),
        'KEYEx_low_four_bits':has(EX_AGENT+'AfterLoadProgrammingInformation',0x12d2840,'and','eax, 0xf'),
        'coupler_PP_bistable_name':literal(COUPLER_AGENT+'CreateBistableSwitchAttribute',0x121ef2b,'BistableSwitchBlock'),
        'coupler_PP_bits_map_to_key_ordinal':has(COUPLER_AGENT+'LoadBistableSwitchAttribute',0x121f049,'mov','edx, dword ptr [ebp - 8]') and call(COUPLER_AGENT+'LoadBistableSwitchAttribute',0x121f04c,'CIS_Maths.IntegerBitAsBoolean') and call(COUPLER_AGENT+'LoadBistableSwitchAttribute',0x121f069,COUPLER_KEY+'SetBistableSwitch'),
        'coupler_load_after_core_pro':call(COUPLER_AGENT+'AfterLoadProgrammingInformation',0x121f476,'CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.AfterLoadProgrammingInformation') and call(COUPLER_AGENT+'AfterLoadProgrammingInformation',0x121f47e,COUPLER_AGENT+'LoadBistableSwitchAttribute'),
        'bistable_column_exact_markup':literal(CLASSIC,0xca67d9,'<th>Bistable</th>') and literal(CLASSIC,0xca6a4e,'<td>Yes</td>') and literal(CLASSIC,0xca6a5d,'<td>No</td>'),
        'bistable_only_physical_key_cell':has(CLASSIC,0xca6a37,'cmp','eax, dword ptr [ebp - 0x10]') and has(CLASSIC,0xca6a3a,'jle','0xca6a69') and has(CLASSIC,0xca6a44,'call','dword ptr [ecx + 0x10]'),
        'bistable_virtual_cell_nbsp':has(CLASSIC,0xca6a74,'mov','eax, dword ptr [0x13c26cc]') and image.resource(image.dword(0x13c26cc))=='&nbsp;',
        'core_join_firmware_1_6_count_at_most_4':methods['CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.IsJoinModeSupported']['literals']==['1.6.0'] and has('CIS_TCoreNeoProInputUnit.TCoreNeoProInputUnit.IsJoinModeSupported',0xd06817,'cmp','eax, 4'),
    })
    # Resolve the exact interface getter adjustor rather than relying only on
    # the inherited GUID. The public receipt pins this bounded thunk, not bytes.
    entry_table = image.dword(image.vmt('CIS_TCoreBusCouplerInputUnit..TCoreBusCouplerInputUnit')-0x54)
    entry_count = image.dword(entry_table)
    entries = image.pe.get_data(entry_table-image.base+4,28*entry_count)
    entry = next(entries[i*28:(i+1)*28] for i in range(entry_count)
                 if str(uuid.UUID(bytes_le=entries[i*28:i*28+16])) == BISTABLE_GUID)
    interface_vtable, adjustment = struct.unpack_from('<II',entry,16)
    getter = image.dword(interface_vtable+0x10)
    thunk_raw = image.pe.get_data(getter-image.base,10)
    thunk = [(ins.address,ins.mnemonic,ins.op_str) for ins in image.decoder.disasm(thunk_raw,getter)]
    checks.update({
        'coupler_collection_count_is_physical':has(COUPLER+'RefreshKeyCouplerCollection',0xce6533,'call','dword ptr [edx + 0x190]') and has(COUPLER+'RefreshKeyCouplerCollection',0xce6542,'call','dword ptr [edx + 0x190]'),
        'coupler_collection_same_input_key_ordinal':has(COUPLER+'RefreshKeyCouplerCollection',0xce6558,'mov','edx, dword ptr [ebp - 8]') and has(COUPLER+'RefreshKeyCouplerCollection',0xce656a,'mov','edx, dword ptr [ebp - 8]') and call(COUPLER+'RefreshKeyCouplerCollection',0xce657c,COUPLER_KEY+'SetInputKey'),
        'bistable_interface_getter_adjusts_and_forwards':thunk==[(0xce5afc,'add','eax, 0xfffffd44'),(0xce5b01,'jmp',hex(image.by_name[COUPLER+'GetBistableSwitch']))] and adjustment==0x2bc,
        'timer_afterchange_zero_primary_is_300_before_lock':call('CIS_TInputKey.TInputKey.HandleMacroFunctionTemplateAfterChangeEvent',0xd12b23,'CIS_TInputKey.TInputBlock.GetTimer') and has('CIS_TInputKey.TInputKey.HandleMacroFunctionTemplateAfterChangeEvent',0xd12b28,'test','ax, ax') and has('CIS_TInputKey.TInputKey.HandleMacroFunctionTemplateAfterChangeEvent',0xd12b2d,'mov','dx, 0x12c') and call('CIS_TInputKey.TInputKey.HandleMacroFunctionTemplateAfterChangeEvent',0xd12b34,'CIS_TInputKey.TInputBlock.SetTimer') and call('CIS_TInputKey.TInputKey.HandleMacroFunctionTemplateAfterChangeEvent',0xd12b6e,'CIS_TLock.TLock.Locked'),
    })
    failed=[n for n,v in checks.items() if not v]
    if failed: raise ValueError('Neo profile source differs: '+', '.join(failed))
    return {'format':'cbus-project-documentor-neo-profiles-static-v1','original_executed':False,
        'exe_sha256':EXE_SHA256,'map_sha256':MAP_SHA256,'types':43,'factory_partitions':59,
        'profiles':rows,'checks':checks,'factory_registration_spans':factory_spans,
        'interface_thunks':{'bistable_getter':{'start':hex(getter),'end':hex(getter+10),'sha256':sha(thunk_raw),'target':COUPLER+'GetBistableSwitch'}},
        'methods':{name:{'start':hex(m['start']),'end':hex(m['end']),'sha256':m['sha256'],'literals':m['literals']} for name,m in sorted(methods.items())},
        'limits':['Fresh complete explicit PP model only. Active joins, Scene Modify and noncanonical scene storage remain refused.',
                  'Firmware identity retains major.minor.two-digit-release grammar within each exact factory range.',
                  'No original instructions, GUI, generated-page, print, device or physical acceptance.']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--exe',type=Path,required=True);p.add_argument('--map',dest='map_file',type=Path,required=True)
    p.add_argument('--output',type=Path);p.add_argument('--check',type=Path)
    a=p.parse_args();result=inspect(a.exe,a.map_file);text=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
    if a.check and a.check.read_text()!=text:raise ValueError('Static receipt differs')
    if a.output:a.output.write_text(text)
    print(json.dumps({'checks':len(result['checks']),'methods':len(result['methods']),'types':43,'partitions':59,'original_executed':False}))

if __name__=='__main__':main()
