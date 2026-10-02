#!/usr/bin/env python3
"""Read-only pinned managed static-grid policy annex; no original execution."""
import argparse
import hashlib
import json
from pathlib import Path

PINS = {
 'toolkit/app/eDLT.dll': '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3',
 'toolkit/app/CBusLogicModel.dll': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823',
 'edlt-decompiled/eDLT/eDLT.Controls/StaticTextEditor.cs': 'fdd0a6be11eda9627c7cb60a12297cb0753257b497c79952f7397194bfea8f3c',
 'edlt-decompiled/eDLT/eDLT.Controls/StaticTextEditorForm.cs': 'dbeba738c5afc85c2627cef2fc41fa3a7080418dc82f6a95c62ed78c78c3df59',
 'edlt-decompiled/eDLT/eDLT/FrmBaseUnit.cs': '060323b11494c7a697656d048f97351526a143e339db767731675a87ba1b1b16',
 'edlt-decompiled/eDLT/eDLT.Controls.PPControls/ComboBoxAddEdit.cs': '77a6f18293f1213797a48193e153387b2caa30103a1061c40a3f1a82e5996027',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs': '641f5abc1c3762cd86a0c4b18bc125424a39017a3d78d6edfa4e1e2964af62b2',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTScene.cs': '91fb4aa7438f3ba911062902f022d9bbdc196bc6ce809ecf29cb2ff9bd514774',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel/PPAttribute.cs': '6c057abce7de8793501e34b326d862a9bbc2c2e32ed6c7b7ace796b0ad29e9cb',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/DataStore.cs': 'd60cd2371e221a54774e6b8c35ce631975d0c2491e6b9e053d700810831f4f2b',
}
RULES = {
 'StaticTextEditor.InitializeComponent': 'Value is read-only; Name is bound to DataStore.Name and limits editor text to64 UTF16 units; StaticLabels supplies existing row identities.',
 'StaticTextEditorForm.button1_Click': 'NotifyCurrentCellDirty(true), then Close; this is not an explicit EndEdit or CommitEdit.',
 'StaticTextEditorForm.FormClosing': 'ResetBindings(false); neither accepted-result checking nor dialog cancellation rollback.',
 'FrmBaseUnit.AddStaticText / ComboBoxAddEdit.ShowStaticTextDialog': 'Disable list events, bind the retained Unit, ShowDialog, re-enable list events, SaveStaticText, then notify StaticLabels; neither opener reconstructs names.',
 'EDLTUnit.AfterLoadPPData': 'Rebuild64 StaticLabels from PP ValueAsUtf8String, then populate suggestions and load retained scenes/widgets.',
 'EDLTUnit.SaveStaticText': 'Compare each decoded current PP string with retained Name; write only unequal strings. A dialog reopen does not decode names again.',
 'EDLTUnit.GetStaticTextIndex': 'Search retained names with ordinal equality before capacity/allocation; otherwise choose the highest unused index, change its Name, then SaveStaticText.',
 'EDLTScene.SceneName': 'The non-null name setter calls Unit.GetStaticTextIndex; SceneManager shares the same retained Name lookup before capacity/allocation.',
 'EDLTUnit.BeforeSavePPData': 'SaveStaticText(false) precedes SaveScenes and widget serialization.',
 'PPAttribute.ValueAsUtf8String': 'Canonical byte rows use Encoding.UTF8.GetString replacement fallback; setter takes at most63 encoded bytes, stops after NUL, and appends0; a UTF8 sequence can split.',
 'DataStore.Name': 'Assignment changes Name immediately and raises property notification; DataStore implements no IEditableObject row rollback.',
}


def recover(root):
    sources = []
    for name, expected in PINS.items():
        data = (root / name).read_bytes(); actual = hashlib.sha256(data).hexdigest()
        if actual != expected:raise ValueError('Pinned source mismatch: ' + name)
        sources.append({'path': name, 'sha256': actual, 'bytes': len(data)})
    return {
      'format':'cbus-edlt-static-grid-source-annex-v1',
      'original_instructions_executed':False,'original_sources':sources,
      'managed_metadata_runtime':'v4.0.30319','rules':RULES,
      'framework_reference':{
        'repository':'https://github.com/microsoft/referencesource',
        'commit':'ec9fa9ae770d522a5b5f0607898044b7478574a3',
        'path':'mscorlib/system/text/utf8encoding.cs',
        'sha256':'0302f5d59320582f5ae30d7b62ddcf3ceaad0bc31d55c1b5b7f8978a1e09c3e5',
        'invalid_prefix_grouping':'Invalid second continuation constraints consume lead+second together before U+FFFD; incomplete valid prefixes are one replacement.',
        'keyboard_policy_url':'https://learn.microsoft.com/en-us/dotnet/desktop/winforms/controls/default-keyboard-and-mouse-handling-in-the-windows-forms-datagridview-control',
        'focus_policy_url':'https://learn.microsoft.com/en-us/dotnet/desktop/winforms/controls/walkthrough-validating-data-in-the-windows-forms-datagridview-control',
        'policy_scope':'Explicit commit, Escape cell cancellation and changing-cell validation; framework-documented policy composed with pinned original DataStore binding.',
      },
      'boundaries':{
        'pending_modal_close_automatic_result':False,
        'original_host_framework_binary_verified':False,
        'noncanonical_lexical_pp_zero_tokens':False,
        'canonical_complete_64byte_pp_rows':True,
        'unpaired_surrogate_input':False,'row_insert_delete_sort_gui':False,
        'original_gui_runtime_acceptance':False,'controller_or_hardware_acceptance':False,
      },
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args(); data=recover(args.vendor_root)
    rendered=(json.dumps(data,indent=2,ensure_ascii=False)+'\n').encode()
    if args.check:
        if args.output.read_bytes()!=rendered:raise SystemExit('Static grid source annex differs')
    else:args.output.write_bytes(rendered)
    print(json.dumps({'sources':len(PINS),'rules':len(RULES),
      'original_instructions_executed':False,'sha256':hashlib.sha256(rendered).hexdigest()}))

if __name__=='__main__':main()
