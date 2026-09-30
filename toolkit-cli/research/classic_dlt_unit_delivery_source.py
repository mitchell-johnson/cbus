"""Static source receipts for the bounded classic DLT network-save planner.

This reads only the explicitly supplied, hash-pinned Toolkit EXE/MAP. It never
loads executable code, instantiates an emulator, connects to C-Gate, or reads a
project. The receipt records method hashes and checked branch locations, not a
runtime observation. Full PP serialization and unresolved model initialization
remain outside the portable planner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from project_documentor_static import _Toolkit  # noqa: E402
from topology_generator_static import EXE_SHA256, MAP_SHA256  # noqa: E402

FORMAT = 'cbus-classic-dlt-unit-delivery-source-v1'
DLT = 'CIS_TCBusDynamicLabelInputCGateAgent.TCBusDynamicLabelInputCGateAgent.'
UNIT = 'CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.'
COMMAND = 'CIS_TCGateCommand.TCGateCommand.'
METHODS = {
    'after_save': DLT + 'AfterSaveProgrammingInformation',
    'before_save': DLT + 'BeforeSaveProgrammingInformation',
    'agent_save': DLT + 'AgentSave',
    'reblock': DLT + 'SaveEnableDynamicLabelsOnly',
    'save_flavours_only': DLT + 'SaveLabelFlavoursOnly',
    'find_flavour': DLT + 'FindFlavour',
    'kfi_builder': DLT + 'SetKeyFunctionIndicators',
    'clear_builder': DLT + 'CommandClearLabel',
    'base_save': UNIT + 'SaveProgrammingInformation',
    'base_modes': UNIT + 'AgentSave',
    'inherited_after_save': 'CIS_TCGateAgent.TCGateAgent.AfterSaveProgrammingInformation',
    'scene_key': 'CIS_TInputKey.TInputKey.GetIsSceneKey',
    'scene_modify_key': 'CIS_TInputKey.TInputKey.GetIsSceneModifyKey',
    'primary_group': 'CIS_TInputKey.TInputKey.GetPrimaryDLTGroup',
    'unused_group': 'CIS_TCommonCBus.TCBusGroup.IsUnused',
    'kfi_generate': 'CIS_TcgcKFISet.TcgcKFISet.GenerateCommandText',
    'kfi_create': 'CIS_TcgcKFISet.TcgcKFISet.InternalCreate',
    'kfi_set': 'CIS_TcgcKFISet.TcgcKFISet.SetKFI',
    'kfi_results': 'CIS_TcgcKFISet.TcgcKFISet.OnProcessResults',
    'clear_generate': 'CIS_TcgcLabelClear.TcgcLabelClear.GenerateCommandText',
    'clear_results': 'CIS_TcgcLabelClear.TcgcLabelClear.OnProcessResults',
    'base_results': COMMAND + 'OnProcessResults',
    'has_response': COMMAND + 'HasResponse',
    'set_completed': COMMAND + 'SetCompleted',
    'set_exception': COMMAND + 'SetRealExceptionToRaise',
    'command_create': COMMAND + 'Create',
    'contains_all': 'CIS_Strings.StringContainsAll',
}

# Every tuple is checked against a decoded instruction at its exact VA. These
# anchors also identify the control/data flow supporting the prose below.
ANCHORS = {
    'after_save': {
        'inherited_hook': (0x121C28F, 'call', '0xcac4ec'),
        'kfi_first': (0x121C297, 'call', '0x121db88'),
        'reset_errors': (0x121C2B1, 'call', 'dword ptr [edx + 0x44]'),
        'default_present_skips_initialization': (0x121C2C8, 'jne', '0x121c30a'),
        'initialize_missing_default': (0x121C2D7, 'call', '0xf2b864'),
        'load_missing_default_graphics': (0x121C304, 'call', 'dword ptr [ebx + 0x88]'),
        'database_mode': (0x121C30D, 'cmp', 'byte ptr [eax + 0xc0], 0'),
        'database_branch': (0x121C314, 'jne', '0x121ca29'),
        'nil_unit_language_unchanged': (0x121C329, 'je', '0x121c371'),
        'update_existing_unit_language': (0x121C36B, 'mov', 'dword ptr [eax + 0x164], ebx'),
        'save_labels_gate': (0x121C379, 'cmp', 'byte ptr [eax + 0x16e], 0'),
        'save_labels_enabled': (0x121C380, 'jne', '0x121c392'),
        'transfer_gate': (0x121C385, 'cmp', 'byte ptr [eax + 0xda], 0'),
        'disabled_skips_keys': (0x121C38C, 'je', '0x121ce5f'),
        'no_keys_skips_keys': (0x121C3A8, 'jl', '0x121ce5f'),
        'modify_precedes_scene': (0x121C415, 'call', '0xd1165c'),
        'modify_missing_skips': (0x121C431, 'je', '0x121ca18'),
        'modify_unused_predicate': (0x121C444, 'call', '0xf27e14'),
        'modify_unused_skips': (0x121C44B, 'jne', '0x121ca18'),
        'modify_initialize_false': (0x121C47A, 'xor', 'edx, edx'),
        'modify_initialize': (0x121C47C, 'call', '0xf2879c'),
        'modify_bypasses_bitmap_load': (0x121C4E4, 'jmp', '0x121c7aa'),
        'scene_predicate': (0x121C4FF, 'call', '0xd115bc'),
        'scene_owner': (0x121C527, 'call', '0xc99ca4'),
        'scene_missing_skips': (0x121C52E, 'je', '0x121ca18'),
        'scene_initialize_false': (0x121C583, 'xor', 'edx, edx'),
        'scene_initialize': (0x121C585, 'call', '0xf27058'),
        'scene_bypasses_bitmap_load': (0x121C602, 'jmp', '0x121c7aa'),
        'ordinary_owner': (0x121C61D, 'call', '0xd13f54'),
        'ordinary_missing_clears': (0x121C624, 'je', '0x121c64a'),
        'ordinary_unused_predicate': (0x121C641, 'call', '0xf27e14'),
        'ordinary_used_continues': (0x121C648, 'je', '0x121c693'),
        'ordinary_unretained_clear': (0x121C688, 'call', 'dword ptr [ebx + 0x80]'),
        'ordinary_initialize_false': (0x121C6D8, 'xor', 'edx, edx'),
        'ordinary_initialize': (0x121C6DA, 'call', '0xf2879c'),
        'ordinary_find_flavour': (0x121C74A, 'call', '0x121c1dc'),
        'ordinary_bitmap_present': (0x121C767, 'jne', '0x121c7aa'),
        'ordinary_dynamic': (0x121C776, 'cmp', 'al, 2'),
        'ordinary_font': (0x121C787, 'cmp', 'al, 3'),
        'ordinary_load_bitmap': (0x121C7A5, 'call', '0xbcc474'),
        'missing_flavour_clears': (0x121C7AE, 'je', '0x121c9a2'),
        'local_handler_installed': (0x121C7D8, 'push', '0x121c8ca'),
        'reset_retained_broadcast': (0x121C7E6, 'mov', 'byte ptr [eax + 0xc4], 0'),
        'empty_value_clears': (0x121C801, 'je', '0x121c855'),
        'default_value_clears': (0x121C820, 'je', '0x121c855'),
        'dynamic_checks_bitmap': (0x121C82F, 'cmp', 'al, 2'),
        'font_checks_bitmap': (0x121C840, 'cmp', 'al, 3'),
        'bitmap_present_broadcasts': (0x121C853, 'jne', '0x121c8a5'),
        'key_index_plus_one': (0x121C863, 'inc', 'eax'),
        'retained_clear': (0x121C893, 'call', 'dword ptr [ebx + 0x80]'),
        'mark_only_after_clear_returns': (0x121C89C, 'mov', 'byte ptr [eax + 0xc4], 1'),
        'retained_broadcast': (0x121C8B7, 'call', 'dword ptr [ebx + 0x80]'),
        'local_handler': (0x121C8CA, 'jmp', '0x606a9c'),
        'caught_command_done': (0x121C99B, 'call', '0x606e8c'),
        'caught_command_continues': (0x121C9A0, 'jmp', '0x121c9f2'),
        'missing_flavour_clear': (0x121C9EC, 'call', 'dword ptr [ebx + 0x80]'),
        'collect_error': (0x121CA0B, 'call', 'dword ptr [ecx + 0x38]'),
        'next_key': (0x121CA18, 'inc', 'dword ptr [ebp - 0x20]'),
        'repeat_keys': (0x121CA1E, 'jne', '0x121c3b9'),
    },
    'before_save': {
        'database_gate': (0x121D3A3, 'cmp', 'byte ptr [eax + 0xc0], 0'),
        'network_branch': (0x121D3AA, 'je', '0x121d3df'),
        'database_inverts_block': (0x121D3BB, 'xor', 'dl, 1'),
        'network_enables': (0x121D3E5, 'mov', 'dl, 1'),
    },
    'agent_save': {
        'flavours_exclusive': (0x121D730, 'call', '0x121d9dc'),
        'flavours_skips_parent_and_reblock': (0x121D735, 'jmp', '0x121d7a4'),
        'inherited_save': (0x121D740, 'call', '0xcc9a34'),
        'database_skips_reblock': (0x121D75B, 'jne', '0x121d791'),
        'alignment_skips_reblock': (0x121D773, 'jne', '0x121d791'),
        'readdress_skips_reblock': (0x121D78B, 'jne', '0x121d791'),
        'save_reblock': (0x121D79F, 'call', '0x121d8d0'),
    },
    'reblock': {
        'block_predicate': (0x121D8E1, 'call', '0xce4ccc'),
        'unblocked_skips': (0x121D8E8, 'je', '0x121d994'),
        'initial_session_false': (0x121D8EE, 'mov', 'byte ptr [ebp - 5], 0'),
        'finally_registered': (0x121D8F5, 'push', '0x121d98d'),
        'read_session': (0x121D908, 'call', '0xf349b8'),
        'save_session': (0x121D90D, 'mov', 'byte ptr [ebp - 5], al'),
        'existing_skips_open': (0x121D914, 'jne', '0x121d93c'),
        'lock': (0x121D91B, 'call', '0xcb9884'),
        'start': (0x121D929, 'call', '0xcb9d54'),
        'load': (0x121D937, 'call', '0xcba510'),
        'set_enable_zero': (0x121D94B, 'call', '0xcbb7d0'),
        'timeout': (0x121D950, 'push', '0x7530'),
        'changes_only_true': (0x121D955, 'mov', 'cl, 1'),
        'network_save': (0x121D957, 'xor', 'edx, edx'),
        'save_for_both_sessions': (0x121D95C, 'call', '0xcbb974'),
        'existing_skips_cleanup': (0x121D972, 'jne', '0x121d98c'),
        'end': (0x121D97D, 'call', '0xcbbd24'),
        'unlock_after_end': (0x121D987, 'call', '0xcbbf04'),
        'finally': (0x121D98D, 'jmp', '0x606c24'),
        'finally_cleanup_entry': (0x121D992, 'jmp', '0x121d96e'),
    },
    'save_flavours_only': {
        'existing_skips_open': (0x121DA22, 'jne', '0x121da4a'),
        'stage_flavours': (0x121DA4D, 'call', '0x121d0b0'),
        'existing_skips_save': (0x121DAC1, 'jne', '0x121daec'),
        'owned_save_in_finally': (0x121DACF, 'call', '0xcbb974'),
        'owned_end_after_save': (0x121DADD, 'call', '0xcbbd24'),
        'owned_unlock_after_end': (0x121DAE7, 'call', '0xcbbf04'),
        'finally_entry': (0x121DAF2, 'jmp', '0x121dabd'),
    },
    'base_save': {
        'save': (0xCBDE7E, 'call', '0xcbb974'),
        'project_save': (0xCBDEEE, 'call', 'dword ptr [ebx + 0x80]'),
        'load_status': (0xCBDF12, 'call', 'dword ptr [ebx + 0x88]'),
        'after_save': (0xCBDF1D, 'call', 'dword ptr [edx + 0xa0]'),
    },
    'base_modes': {
        'to_database_changes_false': (0xCB7302, 'mov', 'byte ptr [eax + 0xd8], 0'),
        'to_database_direction': (0xCB730C, 'mov', 'byte ptr [eax + 0xd9], 1'),
        'to_database_transfer': (0xCB7316, 'mov', 'byte ptr [eax + 0xda], 1'),
        'to_network_changes_false': (0xCB733D, 'mov', 'byte ptr [eax + 0xd8], 0'),
        'to_network_direction': (0xCB7347, 'mov', 'byte ptr [eax + 0xd9], 0'),
        'to_network_transfer': (0xCB7351, 'mov', 'byte ptr [eax + 0xda], 1'),
        'database_transfer_false': (0xCB7389, 'mov', 'byte ptr [eax + 0xda], 0'),
        'ordinary_transfer_false': (0xCB73BC, 'mov', 'byte ptr [eax + 0xda], 0'),
    },
    'find_flavour': {
        'nil_language': (0x121C1F4, 'je', '0x121c25f'),
        'compare_exact': (0x121C23C, 'cmp', 'eax, dword ptr [ebp - 0xc]'),
        'return_first_match': (0x121C255, 'jmp', '0x121c25f'),
    },
    'scene_key': {'scene': (0xD115DE, 'cmp', 'al, 0x17'),
                  'scene_second': (0xD115EF, 'cmp', 'al, 0x18'),
                  'modify': (0xD11600, 'cmp', 'al, 0x19')},
    'scene_modify_key': {'modify': (0xD1167E, 'cmp', 'al, 0x19')},
    'primary_group': {
        'direct_unused': (0xD13F76, 'cmp', 'eax, 0xff'),
        'unused_falls_back': (0xD13F7B, 'je', '0xd13f8a'),
        'fallback_current_application': (0xD13F8D, 'call', '0xd11694'),
        'fallback_flag': (0xD13F94, 'mov', 'dl, 1'),
        'fallback_block': (0xD13F99, 'call', '0xd13b78'),
        'fallback_group': (0xD13FB6, 'call', '0xd0f068'),
    },
    'unused_group': {'address255': (0xF27E25, 'cmp', 'eax, 0xff')},
    'kfi_builder': {
        'gate': (0x121DB99, 'cmp', 'byte ptr [eax + 0xdd], 0'),
        'disabled_returns': (0x121DBA0, 'je', '0x121dc8e'),
        'network': (0x121DBD5, 'call', '0xf2fff8'),
        'unit_application': (0x121DBF2, 'call', 'dword ptr [edx + 0xb0]'),
        'missing_key_skips': (0x121DC37, 'jle', '0x121dc60'),
        'key_byte': (0x121DC4F, 'mov', 'cl, byte ptr [eax + 0xc0]'),
        'set_slot': (0x121DC5B, 'call', '0x121b040'),
        'eight_slots': (0x121DC63, 'cmp', 'dword ptr [ebp - 0xc], 8'),
        'execute': (0x121DC6C, 'call', '0x843860'),
    },
    'kfi_create': {'default_zero': (0x121AF90, 'mov', 'byte ptr [edx + eax + 0x9c], 0'),
                   'eight_slots': (0x121AF9B, 'cmp', 'dword ptr [ebp - 8], 8')},
    'kfi_set': {'store_byte': (0x121B058, 'mov', 'byte ptr [ecx + edx + 0x9c], al')},
    'kfi_generate': {'unsigned_byte': (0x121AE58, 'movzx', 'eax, byte ptr [ecx + eax + 0x9c]'),
                     'decimal': (0x121AE60, 'call', '0x6198ac'),
                     'eight_values': (0x121AE7D, 'cmp', 'dword ptr [ebp - 0xc], 8')},
    'kfi_results': {'prefix_mode': (0x121AFDF, 'push', '0'),
                    'has_response': (0x121AFEC, 'call', '0x843cec'),
                    'complete': (0x121AFFA, 'call', '0x843de4')},
    'clear_builder': {'zero_skips': (0x121E284, 'je', '0x121e331'),
                      'network': (0x121E2B9, 'call', '0xf2fff8'),
                      'unit_application': (0x121E2D6, 'call', 'dword ptr [edx + 0xb0]'),
                      'set_key': (0x121E306, 'mov', 'dword ptr [eax + 0x9c], edx')},
    'clear_generate': {'min_key': (0x121B156, 'cmp', 'dword ptr [eax + 0x9c], 1'),
                       'below_clears_whole_unit': (0x121B15D, 'jl', '0x121b1d1'),
                       'max_key': (0x121B162, 'cmp', 'dword ptr [eax + 0x9c], 8'),
                       'above_clears_whole_unit': (0x121B169, 'jg', '0x121b1d1')},
    'clear_results': {'syntax_tokens': (0x121B31F, 'call', '0x7b78f4'),
                      'syntax_exception': (0x121B362, 'call', '0x843e5c'),
                      'unsupported_tokens': (0x121B382, 'call', '0x7b78f4'),
                      'unsupported_exception': (0x121B3A1, 'call', '0x843e5c'),
                      'prefix_mode': (0x121B3A6, 'push', '0'),
                      'has_response': (0x121B3B3, 'call', '0x843cec'),
                      'complete_after_errors': (0x121B3C1, 'call', '0x843de4')},
    'has_response': {'case_sensitive_position': (0x843D27, 'call', '0x6094d4'),
                     'position_one': (0x843D2C, 'dec', 'eax'),
                     'prefix_equal': (0x843D2D, 'sete', 'byte ptr [ebp - 0xd]')},
    'set_completed': {'error_state': (0x843DF9, 'cmp', 'byte ptr [eax + 0x18], 1'),
                      'preserve_error': (0x843DFD, 'je', '0x843e06'),
                      'completed_state': (0x843E02, 'mov', 'byte ptr [eax + 0x18], 3')},
}

LITERALS = {
    'after_save': {'DLT_INDEX', '<Default>', 'DLTClearLabel', 'KeyNumber=', 'SaveDLTLabel'},
    'agent_save': {'ClearDLTUnitLabels', 'DLTClearLabel', 'SaveFlavours', 'Database', 'AlignUnit', 'DBReaddress'},
    'reblock': {'0', 'EnableDynamicLabels'},
    'save_flavours_only': {'LabelFlavourLSB', 'LabelFlavourMSB'},
    'base_save': {'Database', 'ProjectSave', 'LoadStatus'},
    'base_modes': {'TransferDatabaseToNetwork', 'TransferNetworkToDatabase', 'Database', 'ChangesOnly'},
    'kfi_generate': {'label kfiset %d/%d %d %s'},
    'kfi_results': {'200 OK'},
    'clear_generate': {'label clear %d/%d %d %d', 'label clear %d/%d %d'},
    'clear_results': {'400', 'Syntax Error', '402', 'Operation not supported', '200 OK'},
}


def inspect(exe_path: Path, map_path: Path) -> dict:
    exe, symbols = exe_path.read_bytes(), map_path.read_bytes()
    if hashlib.sha256(exe).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Toolkit(exe, symbols)
    methods = {key: image.method(name) for key, name in METHODS.items()}
    checks = []
    for key, anchors in ANCHORS.items():
        actual = {address: (mnemonic, operands) for address, mnemonic, operands in methods[key]['instructions']}
        for label, (address, mnemonic, operands) in anchors.items():
            if actual.get(address) != (mnemonic, operands):
                raise ValueError(f'Original static branch mismatch: {key}.{label} at {address:#x}')
            checks.append({'method': key, 'check': label, 'address': hex(address), 'verified': True})
    for key, literals in LITERALS.items():
        if not literals <= set(methods[key]['literals']):
            raise ValueError('Original literal mismatch: ' + key)
        checks.append({'method': key, 'check': 'required_literals', 'verified': True})

    expected_noop = [(0xCAC4EC, 'push', 'ebp'), (0xCAC4ED, 'mov', 'ebp, esp'),
                     (0xCAC4EF, 'push', 'ecx'), (0xCAC4F0, 'mov', 'dword ptr [ebp - 4], eax'),
                     (0xCAC4F3, 'pop', 'ecx'), (0xCAC4F4, 'pop', 'ebp'),
                     (0xCAC4F5, 'ret', ''), (0xCAC4F6, 'mov', 'eax, eax')]
    if methods['inherited_after_save']['instructions'] != expected_noop:
        raise ValueError('Original inherited AfterSave hook is no longer the pinned no-op')
    checks.append({'method': 'inherited_after_save', 'check': 'exact_noop_body', 'verified': True})
    for key, pairs in {
        'contains_all': [('call', '0x61b404'), ('mov', 'byte ptr [ebp - 0xd], 0')],
        'set_exception': [('mov', 'byte ptr [eax + 0x18], 1'), ('mov', 'dword ptr [eax + 0x40], edx')],
        'command_create': [('mov', 'dword ptr [eax + 0x38], 0x4e20')],
    }.items():
        actual = {(mnemonic, operands) for _, mnemonic, operands in methods[key]['instructions']}
        if not set(pairs) <= actual:
            raise ValueError('Original parser/constructor body mismatch: ' + key)
        checks.append({'method': key, 'check': 'required_body_operations', 'verified': True})

    # Delphi HandleOnException metadata is data, not x86 instructions. Decode it
    # explicitly: one catch class and its handler, rather than interpreting the
    # intervening bytes as code or assuming this catches arbitrary exceptions.
    catch_class = 'CIS_TCGateCommand..ECGateCommand'
    expected_table = [1, image.by_name[catch_class], 0x121C8DB]
    if [image.dword(address) for address in (0x121C8CF, 0x121C8D3, 0x121C8D7)] != expected_table:
        raise ValueError('Original retained-label exception table mismatch')
    exceptions = {name: image.ancestry(symbol) for name, symbol in {
        'ECGateCommand': catch_class,
        'ECGateSyntaxError': 'CIS_TCGateCommandExceptions..ECGateSyntaxError',
        'ECGateException': 'CIS_TCGateCommandExceptions..ECGateException',
    }.items()}
    if exceptions != {'ECGateCommand': ['ECGateCommand', 'Exception', 'TObject'],
                      'ECGateSyntaxError': ['ECGateSyntaxError', 'ECGateCommand', 'Exception', 'TObject'],
                      'ECGateException': ['ECGateException', 'ECGateCommand', 'Exception', 'TObject']}:
        raise ValueError('Original command exception inheritance mismatch')
    return {
        'format': FORMAT,
        'evidence': 'static disassembly and Delphi exception-table decoding; no original execution',
        'source_sha256': {'exe': EXE_SHA256, 'map': MAP_SHA256},
        'methods': {key: {'symbol': METHODS[key], 'start': hex(value['start']),
                          'bytes': value['end'] - value['start'], 'sha256': value['sha256']}
                    for key, value in methods.items()},
        'checks': checks,
        'exception_table': {'address': '0x121c8cf', 'catch_count': 1,
                            'catch_class': 'ECGateCommand', 'handler': '0x121c8db',
                            'ancestry': exceptions},
        'rules': {
            'lifecycle': ['network BeforeSave enables dynamic labels',
                          'inherited PP SAVE, ProjectSave and LoadStatus',
                          'AfterSave inherited no-op hook, KFI, reset label errors',
                          'initialize default language/graphics only when missing',
                          'network SaveDLTLabels OR transfer gate',
                          'ordered key dispatch',
                          'after inherited save returns, optionally reblock'],
            'mode_boundary': 'Portable planner admits ordinary network save and TransferDatabaseToNetwork only. Database, AlignUnit, DBReaddress, standalone SaveFlavours and dedicated clear verbs are excluded.',
            'keys': {
                'role_order': ['scene_modify', 'scene', 'ordinary'],
                'scene_function_types': [23, 24, 25], 'scene_modify_function_type': 25,
                'unused_group_address': 255,
                'scene_modify': 'ControlAppGroup missing or unused skips key; selected flavour uses the network default language.',
                'scene': 'Missing SceneTriggerLevel skips key; this branch has no group IsUnused test.',
                'ordinary': 'GetPrimaryDLTGroup uses a non-255 primary group, otherwise FindBlockUsedByThisKey(true, GetApplicationState) and its group; missing or unused resolved group clears key.',
                'flavour': 'FindFlavour returns the first exact selected flavour in collection order; a missing selected flavour clears key.',
                'bitmap': 'Only ordinary selected DYNAMIC/FONT with empty bitmap invokes LoadDLTBitmap before the local catch; portable inputs must already resolve this prerequisite.',
                'dispatch': 'Every retained dispatch resets broadcast=false. Empty value or exact <Default> clears before type-specific payload validation; DYNAMIC/FONT with empty bitmap also clears. A successful retained clear marks true. Repeated shared flavours reset and broadcast again.',
            },
            'failure': {
                'collected': 'Only ECGateCommand descendants raised during retained flavour reset/clear/broadcast are collected, then processing continues with the next key.',
                'fatal': ['KFI', 'default language/graphics initialization', 'owner language initialization',
                          'ordinary bitmap load', 'missing/unused primary clear', 'missing flavour clear',
                          'non-ECGateCommand exceptions inside the retained dispatch'],
                'reblock': 'Collected label errors permit reblock after inherited save returns. A propagated failure prevents that AgentSave continuation.',
            },
            'kfi': {'template': 'label kfiset {network}/{unit_application} {unit} {v1} {v2} {v3} {v4} {v5} {v6} {v7} {v8}',
                    'source_value_range': [0, 255], 'portable_value_range': [0, 15],
                    'portable_range_basis': 'deliberately narrower planner admission; not an original byte-coercion claim',
                    'missing_key_value': 0, 'slots': 8, 'timeout_ms': 20000,
                    'gate': 'unit key-function-indicator enable byte at +0xDD',
                    'result': 'Only case-sensitive 200 OK prefix completes; no explicit mapped error tokens in this derived handler.'},
            'clear': {'key_template': 'label clear {network}/{unit_application} {unit} {key}',
                      'key_range': [1, 8], 'timeout_ms': 20000, 'zero': 'agent sends no command',
                      'other_nonzero': 'generator omits key argument and therefore targets the whole unit',
                      'result': 'Case-sensitive contains-all 400/Syntax Error maps ECGateSyntaxError; 402/Operation not supported maps ECGateException; then 200 OK prefix completes unless already error. No explicit 408 or bad-object branch.'},
            'project_context': 'KFI and CLEAR use numeric relative network/application targets, with no project prefix; the intended active C-Gate project is an external prerequisite.',
            'reblock': {'gate': 'BlockDynamicUpdates=true', 'enable_dynamic_labels': 0,
                        'timeout_ms': 30000, 'database': False, 'changes_only': True,
                        'existing_session': ['SET EnableDynamicLabels=0', 'SAVE'],
                        'owned_session': ['LOCK', 'START', 'LOAD', 'SET EnableDynamicLabels=0', 'SAVE', 'END', 'UNLOCK'],
                        'cleanup': 'A finally attempts END then UNLOCK only for a session not originally open, including SAVE failure. END failure prevents UNLOCK; cleanup is not independently verified by a planner outcome.',
                        'save_flavours_contrast': 'SaveLabelFlavoursOnly stages values without SAVE when the session is already open. Its owned-session finally executes SAVE before END and UNLOCK, so SAVE failure prevents those cleanup calls.'},
        },
        'boundary': {'original_cpu_executed': False, 'native_cgate_executed': False,
                     'physical_acceptance': False, 'executor': False,
                     'caller_model_verified': False, 'whole_pp_serializer': False,
                     'excluded_prerequisites': ['project/network/unit identity resolution', 'key role and owner resolution',
                                               'network/owner language initialization', 'ordinary bitmap loading',
                                               'prepared bitmap rendering', 'C-Gate project context']},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolkit-exe', required=True, type=Path)
    parser.add_argument('--toolkit-map', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = inspect(args.toolkit_exe, args.toolkit_map or args.toolkit_exe.with_suffix('.map'))
    data = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(data)
    else:
        print(data, end='')


if __name__ == '__main__':
    main()
