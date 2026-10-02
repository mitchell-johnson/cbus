"""Statically bind Bytecraft L1 logic plus unchanged body/scene consumers.

Original instructions and original generated pages are never executed here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256, UNIT_FACTORY

DOC = 'CIS_TBytecraftDimmerDocumentor.TBytecraftDimmerDocumentor.'
AGENT = 'CIS_TDIMPR12L1CGateAgent.TDIMPR12L1CGateAgent.'
UNIT = 'CIS_TDIMPR12L1.TDIMPR12L1.'
OUTPUT = 'CIS_TCBusBytecraftDimmerUnit.TBytecraftUnit.DescribeOutputGroupDependencyAdvanced'
METHODS = (DOC+'DocumentHTML', DOC+'ActionSelectorUse', DOC+'IsChannelUnused',
    AGENT+'InternalCreate', AGENT+'AfterLoadProgrammingInformation', UNIT+'Init',
    UNIT+'GetMaxLogicGroups', UNIT+'GetLogicGroups', OUTPUT,
    'CIS_TCBusBytecraftDimmerUnit.TBytecraftUnit.GetLogicGroups',
    'CIS_TCBusGOCUnit.TGOCLogicAttribute.SetUseLogic',
    'CIS_TCBusGOCUnit.TGOCLogicAttribute.SetLogicOR',
    'CIS_TCBusGOCUnit.TGOCLogicGroup.InternalCreate')


def inspect(executable:Path,mapping:Path)->dict:
    raw,symbols=executable.read_bytes(),mapping.read_bytes()
    if (hashlib.sha256(raw).hexdigest(),hashlib.sha256(symbols).hexdigest()) != (EXE_SHA256,MAP_SHA256):
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image=_Toolkit(raw,symbols)
    methods={name:image.method(name) for name in METHODS}
    def has(name,address,op,args):return (address,op,args) in methods[name]['instructions']
    def call(name,address,target):return has(name,address,'call',hex(image.by_name[target]))
    def lit(name,address,value):return methods[name]['literal_at'].get(address)==value
    rows,_=image.registrations(UNIT_FACTORY)
    profiles=[list(row) for row in rows if row[0]=='DIMPR12']
    body,load,create=DOC+'DocumentHTML',AGENT+'AfterLoadProgrammingInformation',AGENT+'InternalCreate'
    historic=json.loads((Path(__file__).parent/'fixtures/project-documentor-bytecraft-body-static.json').read_text())
    checks={
        'exact_old_and_l1_unit_factory_partitions': profiles==[['DIMPR12','CIS_TDIMPR12..TDIMPR12','0','1.9.02'],['DIMPR12','CIS_TDIMPR12L1..TDIMPR12L1','1.9.03','9']],
        'l1_derives_from_bytecraft': 'TBytecraftUnit' in image.ancestry('CIS_TDIMPR12L1..TDIMPR12L1'),
        'l1_one_logic_group':has(UNIT+'GetMaxLogicGroups',0x10148b9,'mov','dword ptr [ebp - 8], 1'),
        'l1_inherits_twelve_channels':image.slot('CIS_TDIMPR12L1..TDIMPR12L1',0x188)==image.slot('CIS_TDIMPR12..TDIMPR12',0x188),
        'l1_inherits_33_scenes':image.slot('CIS_TDIMPR12L1..TDIMPR12L1',0x190)==image.slot('CIS_TDIMPR12..TDIMPR12',0x190),
        'l1_logic_vmt_override':image.slot('CIS_TDIMPR12L1..TDIMPR12L1',0x194)==UNIT+'GetLogicGroups',
        'old_logic_null':has('CIS_TCBusBytecraftDimmerUnit.TBytecraftUnit.GetLogicGroups',0xd39a61,'xor','eax, eax'),
        'l1_init_parent_first':call(UNIT+'Init',0x101492c,'CIS_TCBusBytecraftDimmerUnit.TBytecraftUnit.Init'),
        'l1_init_channels_for_logic_attributes':has(UNIT+'Init',0x1014961,'call','dword ptr [edx + 0x188]'),
        'l1_init_add_logic_group':call(UNIT+'Init',0x1014974,'CIS_TCBusGOCUnit.TGOCLogicGroupCollection.Add'),
        'new_loader_parent_first':call(load,0x1248b02,'CIS_TDIMPR12CGateAgent.TDIMPR12CGateAgent.AfterLoadProgrammingInformation'),
        'logic_group_pp_literal_and_offset':lit(create,0x1248a27,'LogicGroupAddress') and has(create,0x1248a47,'mov','dword ptr [edx + 0x1c0], eax'),
        'logic_attribute_pp_literal_and_offset':lit(create,0x1248a4d,'LogicAttributes') and has(create,0x1248a6d,'mov','dword ptr [edx + 0x1c4], eax'),
        'use_logic_bit0_normalized':has(load,0x1248c05,'and','eax, 1') and has(load,0x1248c09,'sete','al'),
        'use_logic_setter':call(load,0x1248c31,'CIS_TCBusGOCUnit.TGOCLogicAttribute.SetUseLogic'),
        'logic_or_bit7_normalized':has(load,0x1248c64,'and','eax, 0x80') and has(load,0x1248c69,'cmp','eax, 0x80') and has(load,0x1248c6e,'sete','al'),
        'logic_or_setter':call(load,0x1248c96,'CIS_TCBusGOCUnit.TGOCLogicAttribute.SetLogicOR'),
        'body_logic_group_zero':has(body,0x1012d18,'xor','edx, edx'),
        'body_use_logic_gate':has(body,0x1012d31,'je','0x1012de3'),
        'body_logic_group_separator':lit(body,0x1012d60,', '),
        'body_logic_or_true_min_else_max':lit(body,0x1012dc2,'<td>Min</td>') and lit(body,0x1012dd4,'<td>Max</td>'),
        'output_used_if_any_attribute':has(OUTPUT,0xd3a00a,'je','0xd3a010') and has(OUTPUT,0xd3a00c,'mov','byte ptr [ebp - 0x19], 1'),
        'output_logic_labels':image.resource(image.dword(0x13c28c4))=='Logic Group' and image.resource(image.dword(0x13c2874))=='Logic Group (Unused)',
        'body_action_unused_spans_match_historical_proof':all(methods[name]['sha256']==historic['methods'][name]['sha256'] for name in (DOC+'DocumentHTML',DOC+'ActionSelectorUse',DOC+'IsChannelUnused')),
    }
    if not all(checks.values()):raise ValueError('Source checks failed: '+', '.join(k for k,v in checks.items() if not v))
    return {'format':'cbus-project-documentor-bytecraft-l1-static-v1',
        'sources':{'CBusToolkit.exe':{'sha256':EXE_SHA256,'bytes':len(raw)},'CBusToolkit.map':{'sha256':MAP_SHA256,'bytes':len(symbols)}},
        'unit_factory_profiles':profiles,'logic_group_count':1,'logic_attribute_count':12,
        'original_instructions_executed':0,'original_generated_page_comparison':'not_obtained',
        'methods':{name:{'start':hex(row['start']),'end':hex(row['end']),'sha256':row['sha256'],'literals':row['literals'],'resources':row['resources']} for name,row in methods.items()},'checks':checks}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',type=Path,required=True);parser.add_argument('--map',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.write_text(json.dumps(inspect(args.executable,args.map),indent=2,sort_keys=True)+'\n')


if __name__=='__main__':main()
