"""Read-only, pinned source checks for encoded KEYC/CIR key transitions.

No original CPU instructions, loader, GUI or hardware are executed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit
from project_documentor_neoclassic_static import KEY_VALUES, KEY, EXTENSION


def inspect(exe: Path, map_file: Path) -> dict:
    raw, symbols = exe.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError('Pinned original EXE/MAP hash mismatch')
    image = _Toolkit(raw, symbols)
    names = (KEY_VALUES, KEY+'RefreshMacroFunctionFromTemplate', KEY+'MacroFunctionRefresh',
             KEY+'RefreshBlocksFromTemplate', KEY+'RefreshBlocksFromTemplateScene',
             KEY+'HandleMacroFunctionTemplateAfterChangeEvent')
    methods = {n: image.method(n) for n in names}
    def has(n, a, op, args):
        return (a, op, args) in methods[n]['instructions']
    def call(n, a, target):
        return has(n, a, 'call', hex(image.by_name[target]))
    checks = {
        'selector_one_branch': has(KEY_VALUES, 0xCCA5D6, 'dec', 'eax') and has(KEY_VALUES, 0xCCA5D7, 'jne', '0xcca9c3'),
        'jp14_scene24_branch': has(KEY_VALUES, 0xCCA632, 'mov', 'dl, 0xe') and has(KEY_VALUES, 0xCCA64A, 'jne', '0xcca7b1') and has(KEY_VALUES, 0xCCA657, 'mov', 'dl, 0x18'),
        'modify25_assignment': has(KEY_VALUES, 0xCCA7B8, 'mov', 'dl, 0x19') and call(KEY_VALUES, 0xCCA7C4, KEY+'SetMacroFunctionTemplate'),
        'modify_scene_one_before_raw_stages': has(KEY_VALUES, 0xCCA7DA, 'mov', 'edx, 1') and call(KEY_VALUES, 0xCCA7DF, 'CIS_TInputKeyExtensionNeo.TNeoSceneCollection.ItemByNumber') and call(KEY_VALUES, 0xCCA7EE, EXTENSION+'SetScene'),
        'modify_pin_lock_then_unlock': call(KEY_VALUES, 0xCCA7F6, KEY+'GetMacroFunctionPin') and call(KEY_VALUES, 0xCCA7FB, 'CIS_TLock.TLock.Lock') and call(KEY_VALUES, 0xCCA94A, KEY+'GetMacroFunctionPin') and call(KEY_VALUES, 0xCCA94F, 'CIS_TLock.TLock.Unlock'),
        'modify_four_raw_stages': all(call(KEY_VALUES, a, KEY+'SetMicroFunction') for a in (0xCCA854,0xCCA89F,0xCCA8EA,0xCCA935)),
        'modify_class_subset_if_empty': has(KEY_VALUES, 0xCCA95F, 'cmp', 'dword ptr [ebp - 0x58], 0') and has(KEY_VALUES, 0xCCA975, 'call', 'dword ptr [ecx + 0x1c4]') and call(KEY_VALUES, 0xCCA981, KEY+'SetMacroFunctionSubsetName'),
        'modify_refresh_after_unlock': has(KEY_VALUES, 0xCCA986, 'xor', 'edx, edx') and call(KEY_VALUES, 0xCCA98B, KEY+'MacroFunctionRefresh'),
        'modify_final_indicator_only': has(KEY_VALUES, 0xCCA99E, 'mov', 'eax, dword ptr [eax + 0x130]') and has(KEY_VALUES, 0xCCA9AE, 'inc', 'eax') and call(KEY_VALUES, 0xCCA9B9, 'CIS_TInputKey.TInputIndicator.SetBlockNumber'),
        'refresh_reselects_template': call(KEY+'MacroFunctionRefresh',0xD11A3F,KEY+'RefreshTemplateFromMacroFunction'),
        'modify_skips_template_microfunctions': call(KEY+'RefreshMacroFunctionFromTemplate',0xD11C1E,KEY+'GetIsSceneModifyKey') and has(KEY+'RefreshMacroFunctionFromTemplate',0xD11C36,'ret',''),
        'scene_blocks_refresh_before_pin_check': call(KEY+'HandleMacroFunctionTemplateAfterChangeEvent',0xD12B60,KEY+'RefreshBlocksFromTemplate') and call(KEY+'HandleMacroFunctionTemplateAfterChangeEvent',0xD12B6E,'CIS_TLock.TLock.Locked'),
        'scene_blocks_remove_all_then_linear': call(KEY+'RefreshBlocksFromTemplateScene',0xD12794,KEY+'RemoveAllBlocks') and call(KEY+'RefreshBlocksFromTemplateScene',0xD127A1,KEY+'CalcLinearBlock'),
        'linear_block_forced_primary_unused': has(KEY+'RefreshBlocksFromTemplateScene',0xD12A10,'xor','edx, edx') and call(KEY+'RefreshBlocksFromTemplateScene',0xD12A15,'CIS_TInputKey.TInputBlock.SetSecondaryApplication') and has(KEY+'RefreshBlocksFromTemplateScene',0xD12A2A,'mov','edx, 0xff') and call(KEY+'RefreshBlocksFromTemplateScene',0xD12A2F,'CIS_TCommonCBus.TCBusGroupManager.FindGroupByAddress'),
        'linear_reference_added': call(KEY+'RefreshBlocksFromTemplateScene',0xD12A0B,KEY+'AddBlock'),
    }
    failed = [n for n,v in checks.items() if not v]
    if failed: raise ValueError('Encoded source check failed: '+', '.join(failed))
    return {'format':'cbus-project-documentor-neoclassic-scene-static-v1','exe_sha256':EXE_SHA256,'map_sha256':MAP_SHA256,'original_executed':False,'checks':checks,'methods':{n:{'start':hex(m['start']),'end':hex(m['end']),'sha256':m['sha256']} for n,m in methods.items()},'contract':{'scene24':'Reuse canonical Neo selector=1/JP14 semantics and linear unused primary unshared block guard; Classic body only.','scene_modify':'The later scene-modify receipt pins the special template25 refresh branch: key template25 remains, raw stages survive, Scene1/Instant remains, and the derived ramp template is assigned separately under its lock. Final indicator assignment does not set extension scene.','scene_modify_admission':'Canonical KEYC/CIR SceneModify is admitted by project-documentor-neoclassic-scene-modify-static.json; noncanonical/history graphs and original full-loader/page execution remain unassessed.','scene_data':'Require canonical SceneTable/SceneTablePointer when resolving extension scene or dependencies; pointer data is not needed solely to display Scene24 numeric/ramp controls.','trigger':'Native Scene24 loader binds ControlAppGroupAddress and LP/LR trigger; Classic body/action/Input consumers do not read that trigger binding. Other dependencies consume ControlAppGroupAddress independently.', 'supporting_receipt_checks':{'project-documentor-neo-static.json':['scene_collection_padded_to_eight','scene24_default_commands_are_idle','scene24_requires_jp_14','scene24_number_is_indicator_assignment_plus_one'],'project-documentor-neoclassic-static.json':['scene_commands_loaded_before_keys_even_when_disabled','classic_primary_subset_only_adds_scene_templates','secondary_macro_subset_equals_key']}},'limits':['Static source only; no original loader or generated-page acceptance.','Canonical block guard avoids native block relocation and shared-reference removal.','Inherited KEYC/CIR class/factory/subset evidence remains in the separate NeoClassic receipt.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--exe',type=Path,required=True);p.add_argument('--map',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.write_text(json.dumps(inspect(a.exe,a.map),indent=2)+'\n',encoding='utf-8')
    return 0

if __name__=='__main__':raise SystemExit(main())
