"""Read-only Address/NetworkNumber source facts, without original execution.

This deliberately records original numeric anchor normalization alongside the
portable native adapter's exact catalogue-identity extension. No captured
original page or historical execution receipt is rebound to current source.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256


NAMES = {
    'header':'CIS_TProjectDocumentor.TProjectDocumentor.InsertHTMLNetworkNEW',
    'path':'CIS_TCommonCBus.TCBusNetwork.GetAddressAsPath',
    'string':'CIS_TCBusObject.TCGateObject.GetAddressAsString',
    'integer':'CIS_TCBusObject.TCGateObject.GetAddressAsInteger',
    'decimal':'CIS_TCBusObject.TCGateAddressAttribute.GetSimpleDecimalAddress',
    'cache':'CIS_TCBusObject.TCGateAddressAttribute.PopulateCacheValues',
    'number':'CIS_TCommonCBus.TCBusNetworkManager.NetworkByNetworkNumber',
    'constructor':'CIS_TCommonCBus.TCBusNetwork.InternalCreate',
    'bridge':'CIS_TBridgeDocumentor.TBridgeDocumentor.DocumentHTML',
    'bridge_load':'CIS_TCBusBridgeCGateAgent.TCBusBridgeCGateAgent.AfterLoadProgrammingInformation',
    'strtoint':'SysUtils.StrToInt',
    'val':'System.@ValLong',
}


def inspect(exe: Path, map_file: Path):
    raw,symbols=exe.read_bytes(),map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=EXE_SHA256 or hashlib.sha256(symbols).hexdigest()!=MAP_SHA256:
        raise ValueError('Pinned Toolkit EXE/MAP hash mismatch')
    t=_Toolkit(raw,symbols);rows={k:t.method(n) for k,n in NAMES.items()}
    def fact(k,address,mnemonic,operands):return (address,mnemonic,operands) in rows[k]['instructions']
    def call(k,address,target):
        # MAP has overloaded IntToStr symbols. Bind the exact instruction's
        # target membership, rather than whichever overload by_name retains.
        operands=next((o for a,m,o in rows[k]['instructions'] if a==address and m=='call'),None)
        return operands is not None and operands.startswith('0x') and target in t.symbols.get(int(operands,16),set())
    checks={
        'header_anchor_uses_address_string':call('header',0xf0700b,NAMES['string']),
        'header_number_label_uses_address_string':call('header',0xf07054,NAMES['string']),
        'network_path_uses_address_string':call('path',0xf2b0ea,NAMES['string']),
        'address_string_is_integer_then_decimal':call('string',0xf479ff,NAMES['integer']) and call('string',0xf47a07,'SysUtils.IntToStr'),
        'integer_uses_address_attribute_not_number':fact('integer',0xf47a1c,'mov','eax, dword ptr [eax + 0x80]') and call('integer',0xf47a22,NAMES['decimal']),
        'original_address_cache_parses_integer':call('cache',0xf47fab,'SysUtils.StrToInt'),
        'original_address_na_is_zero':fact('cache',0xf47eff,'mov','dword ptr [eax + 0x88], edx') and fact('cache',0xf47efd,'xor','edx, edx') and t.literal(0xf480c0)=='NA',
        'original_unparseable_address_cache_is255':fact('cache',0xf4803d,'mov','dword ptr [eax + 0x88], 0xff'),
        'strtoint_uses_val_long_and_checks_failure':call('strtoint',0x619b7b,'System.@ValLong') and fact('strtoint',0x619b82,'cmp','dword ptr [esp], 0'),
        'val_long_accepts_leading_ascii_spaces':fact('val',0x605955,'cmp','bx, 0x20') and fact('val',0x605959,'je','0x60594f'),
        'val_long_optional_signs':fact('val',0x60595d,'cmp','bx, 0x2d') and fact('val',0x605963,'cmp','bx, 0x2b'),
        'val_long_hex_prefixes':all(fact('val',a,'cmp',o) for a,o in [(0x605969,'bx, 0x24'),(0x60596f,'bx, 0x78'),(0x605975,'bx, 0x58'),(0x60597b,'bx, 0x30')]),
        'val_long_decimal_overflow_and_signed_terminal':fact('val',0x60594a,'mov','edi, 0xccccccc') and fact('val',0x6059a9,'cmp','eax, edi') and fact('val',0x6059c3,'test','eax, eax') and fact('val',0x6059ce,'neg','eax'),
        'val_long_hex_unsigned_accumulator_and_sign':fact('val',0x6059e3,'mov','edi, 0xfffffff') and fact('val',0x605a15,'cmp','eax, edi') and fact('val',0x605a19,'shl','eax, 4') and fact('val',0x605a2d,'neg','eax'),
        'physical_number_has_separate_attribute':fact('constructor',0xf29b5a,'mov','dword ptr [edx + 0xb8], eax') and 'NetworkNumber' in rows['constructor']['literals'],
        'physical_number_lookup_reads_separate_integer':fact('number',0xf29587,'mov','eax, dword ptr [eax + 0xb8]') and fact('number',0xf2958f,'call','dword ptr [edx + 0x94]') and fact('number',0xf29595,'cmp','eax, dword ptr [ebp - 8]'),
        'original_lookup_returns_first_manager_match':fact('number',0xf295a8,'jmp','0xf295b7'),
        'bridge_adjacent_consumes_number':call('bridge',0xd3ed0b,NAMES['number']) and call('bridge',0xd3ed3a,NAMES['number']),
        'bridge_nil_destination_has_literal_unknown_network':fact('bridge',0xd3ee2b,'test','eax, eax') and fact('bridge',0xd3ee2d,'jne','0xd3ee3e') and fact('bridge',0xd3ee2f,'mov','edx, 0xd3f0d8') and t.literal(0xd3f0d8)=='Send Messages to Remote Network: Unknown Network<br/>',
        'bridge_prefix_consumes_number':call('bridge_load',0x1256c80,NAMES['number']),
        'bridge_final_destination_consumes_number':call('bridge_load',0x1256cc0,NAMES['number']),
        'bridge_destination_defaults255_then_last_valid_prefix':[(a,o) for a,m,o in rows['bridge_load']['instructions'] if m=='mov' and o.startswith('dword ptr [ebp - 0xc],')]==[(0x1256be2,'dword ptr [ebp - 0xc], 0xff'),(0x1256c99,'dword ptr [ebp - 0xc], eax')],
    }
    if not all(checks.values()):raise ValueError('Static source check failed: '+','.join(k for k,v in checks.items() if not v))
    root=Path(__file__).resolve().parents[1]
    modules=['project_documentation.py','project_documentation_native.py','native_project_documentation.py','project_documentation_wireless.py']
    fixture=root.parent/'rust/testdata/fixtures/native_cgate_net_save_db_materialization.json'
    return {'format':'cbus-documentor-native-address-source-v1','original_executed':False,
            'original_exe_sha256':EXE_SHA256,'original_map_sha256':MAP_SHA256,'extractor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'checks':checks,'method_spans':{NAMES[k]:{'start':r['start'],'end':r['end'],'sha256':r['sha256'],'instruction_count':len(r['instructions'])} for k,r in rows.items()},
            'native_address_evidence':{'path':'rust/testdata/fixtures/native_cgate_net_save_db_materialization.json','sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'retained_execution_only':True},
            'supporting_module_sha256':{n:hashlib.sha256((root/'src/cbus_toolkit'/n).read_bytes()).hexdigest() for n in modules},
            'literal_disclosure':{'compiler_coordinate_literals_omitted':0,'original_instruction_bytes_embedded':False},
            'limits':['Exact database identities select saved native networks independently; report headings and anchors use the original signed integer address projection, including numeric aliases and name fallback255.','Distinct exact database identities can share source-projected HTML anchors; no complete original page or manager-order acceptance is claimed.','Original manager/locale ordering and duplicate-number first-match selection are not reproduced; ambiguous consumed Numbers refuse.','Bridge remote lookup consumes the last valid prefix Number, or Number255 when no prefix resolved.','No original instructions, native server, VM or hardware is executed by this extraction.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--toolkit',type=Path,required=True);p.add_argument('--map',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.write_text(json.dumps(inspect(a.toolkit,a.map),indent=2,sort_keys=True)+'\n')

if __name__=='__main__':main()
