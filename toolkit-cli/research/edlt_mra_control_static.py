#!/usr/bin/env python3
"""PRIVATE draft MRA static annex. Reads bytes only; never loads/runs assemblies."""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from pathlib import Path

PINS = {'toolkit/app/eDLT.dll': '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3', 'toolkit/app/CBusLogicModel.dll': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData.MRA/MRAData.cs': 'c43924c8fd8930f9c621752a695a6a2abe8c5c489c946fbd2aee6147b07581af', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData.MRA/MRAZoneControlData.cs': '3e49d902760f3b5cac931d953d25d9f4542ecc709990f568ac2ddf5cb83bd40d', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData.MRA/MRASourceSelectData.cs': 'f278567641a91ada5937a5e437cc092799899370d66ec5d4e9b04676b3796713', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData.MRA/MRASourceControlData.cs': '1fd37289aa27cde201ed26c96bd85b93cebc250914b37808f3d6b985adc09251', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/MRAZoneWidget.cs': '07ccf1e6c77f1289f6f80a837a0dde8b623978c0d2a3af07e8baea7b03e38ea5', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/MRASourceSelectWidget.cs': '3cb2972cd878df340ffda5fb0df4f11ba4593b24610ed568df0203973185136a', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/MRASourceControlWidget.cs': '1a5cf555b16c505eb26532828a27c63d5ccf511ca1143c6fcbd85afc78d2ca52', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/CommonConstants.cs': '98e20887cf973205eaa42e621f0ee21ee5b9367aac1553f88c75b86e16d39020', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs': '641f5abc1c3762cd86a0c4b18bc125424a39017a3d78d6edfa4e1e2964af62b2', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData.BaseObjects/WidgetBaseData.cs': '9848f4b6eac5360fc9396887be2ea8aace7fa0e5fdc43cab2ece66597a086189', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.Utilities/MacroFunctionTypes.cs': '828d9b0a68076478b8514764a65b2374ee4f7cd236c088548484a2f533d176d7', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.Utilities/MicroFunctions.cs': '39f871176be4185088281e075e8801878b11aeda0891be77d0d5033da5c9681e', 'edlt-decompiled/eDLT/eDLT.WidgetPanels.baseWidgePanels/BaseWidget.cs': 'e2ecee24752731238d7901b8e2a20e7482e2e8225e76ad0afa660cc602b407d8', 'edlt-decompiled/eDLT/eDLT.Controls/ComboBoxStaticText.cs': 'e6daf32a886e18d67cb20a51d7e483b21af4e470f9f177d8877f7e34d73588c4'}
PINS['edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.Utilities/MacroFunction.cs'] = '6d4aecce2becc6f15d9111a9679d910d134773ec5b6fdf38194ead785c3ef9ae'
PARSER_PIN = "7bb4f3137bf6da42524cc512d94fe6c711f28b5a80532d018411777f9f573223"
M = "CBusLogicModel.EDLT.WidgetData.MRA."
U = "CBusLogicModel.Units.EDLT.EDLTUnit::"
W = "CBusLogicModel.Units.EDLT.WidgetData.BaseObjects.WidgetBaseData::"
C = "CBusLogicModel.Utilities.CommonConstants::"
B = "eDLT.WidgetPanels.baseWidgePanels.BaseWidget::"
S = "eDLT.Controls.ComboBoxStaticText::"
MODEL = "edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData.MRA/"
PANELS = "edlt-decompiled/eDLT/eDLT.WidgetPanels/"
COMMON = "edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/CommonConstants.cs"
UNIT = "edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs"
STATIC = "edlt-decompiled/eDLT/eDLT.Controls/ComboBoxStaticText.cs"
BASE = "edlt-decompiled/eDLT/eDLT.WidgetPanels.baseWidgePanels/BaseWidget.cs"

def sha(raw): return hashlib.sha256(raw).hexdigest()

def recover(repo, vendor):
    parser = repo / "toolkit-cli/research/edlt_scene_name_static.py"
    if sha(parser.read_bytes()) != PARSER_PIN: raise ValueError("Managed parser pin differs")
    sys.path.insert(0, str(repo / "toolkit-cli"))
    from research.edlt_scene_name_static import ManagedImage, source_span, require_order
    originals, inputs = {}, [{"logical_name":"static-managed-parser", "sha256":PARSER_PIN,
      "bytes":parser.stat().st_size,"role":"repository-static-parser"}]
    for path, expected in PINS.items():
        raw=(vendor/path).read_bytes()
        if sha(raw)!=expected: raise ValueError("Original pin differs: "+Path(path).name)
        originals[path]=raw
        inputs.append({"logical_name":Path(path).name,"sha256":expected,"bytes":len(raw),"role":"original-static-input"})
    images={n:ManagedImage(originals["toolkit/app/"+n]) for n in ("eDLT.dll","CBusLogicModel.dll")}
    if any(x.runtime!="v4.0.30319" for x in images.values()):raise ValueError("Metadata runtime differs")
    methods, decoded, declarations, checks = [], {}, [], []
    def method(symbol, assembly="CBusLogicModel.dll"):
        image=images[assembly];entries=image.methods.get(symbol,[])
        if not entries:raise ValueError("Method absent: "+symbol)
        for ordinal, entry in enumerate(entries):
            try:
                image.methods[symbol]=[entry];detail=image.instructions(symbol)
                for call in detail["calls"]:
                    token=int(call["token"],16)
                    if token>>24==43:
                        coded=image.row(43,token&0xffffff)[0]
                        call["symbol"]=image.member(((10 if coded&1 else 6)<<24)|(coded>>1))
                row=entry[1];flags=row[2]
                methods.append({**image.method(symbol),"assembly":assembly,"metadata_runtime":image.runtime,
                  "overload_ordinal":ordinal,"method_flags":f"0x{flags:04x}",
                  "method_virtual":bool(flags&0x40),"method_new_slot":bool(flags&0x100),
                  "method_final":bool(flags&0x20),**detail})
                decoded[symbol]=detail
            finally:image.methods[symbol]=entries
    # Complete class-owned bodies, not only easy setters; helpers are explicit.
    class_names=("MRAData","MRAZoneControlData","MRASourceSelectData","MRASourceControlData")
    for symbol in sorted(images["CBusLogicModel.dll"].methods):
        if any(symbol.startswith(M+n+"::") for n in class_names) or symbol.startswith(M+"MRAZoneControlData+<>c__DisplayClass1::"):
            method(symbol)
    for panel in ("MRAZoneWidget","MRASourceSelectWidget","MRASourceControlWidget"):
        for name in (".ctor","SetUpDataSource","InitializeComponent"):
            method("eDLT.WidgetPanels."+panel+"::"+name,"eDLT.dll")
    for name in (".ctor","SetUpDataSource","SetWidgetData"):method(B+name,"eDLT.dll")
    for name in (".ctor","ComboBoxStaticText_Leave","ComboImageTagDLT_PreviewKeyDown","ComboImageTagDLT_SelectedIndexChanged","DataManager_ListChanged"):
        method(S+name,"eDLT.dll")
    for name in ("WidgetByte","SetToDefault","SetForcedValues","GetUsedStaticText"):method(W+name)
    for name in ("GetStaticTextIndex","GetUsedStaticText","InitializeMRAGlobalValues","SetMRAWidgetGlobalValues","AfterLoadPPData","BeforeSavePPData"):
        method(U+name)
    for name in (".ctor","get_FunctionStatusTypesMRA","get_DualKeyMacroFunctionsMRA","get_MRAControlVariants","get_MRAMultiplexer","get_MRAZone","get_MRASourceSelectVariant","get_MRAAbsoluteSource","get_MRASourceControlVariant","get_RampRates"):
        method(C+name)
    for n in ("MacroFunctionTypes","MicroFunctions"):
        method("CBusLogicModel.Units.EDLT.Utilities."+n+"::.cctor")
    macro="CBusLogicModel.Units.EDLT.Utilities.MacroFunction"
    for symbol in sorted(images["CBusLogicModel.dll"].methods):
        if symbol.startswith(macro+"::") or symbol.startswith(macro+"+"):
            method(symbol)
    type_relationships=[]
    for name in class_names:
        image=images["CBusLogicModel.dll"];full=M+name
        index=next(i for i,n in image.types.items() if n==full)
        coded=image.row(2,index)[3];tag,base=coded&3,coded>>2
        if tag==0:base_name=image.types[base]
        elif tag==1:
            row=image.row(1,base);base_name=image.string(row[2])+"."+image.string(row[1])
        else:raise ValueError("Unexpected MRA base type encoding")
        expected="CBusLogicModel.Units.EDLT.WidgetData.BaseObjects.WidgetBaseData" if name=="MRAData" else M+"MRAData"
        if base_name!=expected:raise ValueError("MRA metadata inheritance differs")
        type_relationships.append({"type":full,"type_token":f"0x{0x02000000|index:08x}","extends_coded_index":coded,"base_type":base_name})
    def order(symbol, wanted, id_):
        require_order([r["symbol"] for r in decoded[symbol]["calls"]],wanted,id_)
        checks.append({"id":id_,"symbol":symbol,"ordered_call_suffixes":wanted,"proof_scope":"Linear IL call occurrence order, not a runtime trace. Control-flow guards require the separately pinned declaration/branches.","passed":True})
    def ints(symbol, wanted, id_):
        actual=[r["value"] for r in decoded[symbol]["integer_constants"]]
        if any(v not in actual for v in wanted):raise ValueError("Constant absent: "+id_)
        checks.append({"id":id_,"symbol":symbol,"required_integer_constants":wanted,"passed":True})
    def absent(symbol, wanted, id_):
        calls=[r["symbol"] for r in decoded[symbol]["calls"]]
        if any(any(c.endswith(v) for c in calls) for v in wanted):raise ValueError("Unexpected call: "+id_)
        checks.append({"id":id_,"symbol":symbol,"absent_call_suffixes":wanted,"passed":True})
    def decl(path, symbol, anchor, wanted=(), forbidden=()):
        span=source_span(originals[path],symbol,anchor)
        lines=originals[path].decode("utf-8-sig").splitlines(keepends=True)
        text="".join(lines[span["start_line"]-1:span["end_line"]])
        if any(v not in text for v in wanted) or any(v in text for v in forbidden):raise ValueError("Declaration mismatch: "+symbol)
        declarations.append({"logical_name":Path(path).name,**span})
        checks.append({"id":"declaration-"+symbol,"required_anchor_count":len(wanted),"absent_anchor_count":len(forbidden),"passed":True})
        return text
    # Model declarations: hash every property/method in all four classes.
    for name in class_names:
        path=MODEL+name+".cs";text=originals[path].decode("utf-8-sig");lines=text.splitlines(keepends=True)
        for i,line in enumerate(lines):
            if not re.match(r"\s*(public|protected|private)\s+",line):continue
            if " class " in line:continue
            anchor=line.strip()
            if "=>" in anchor:
                raw=line.rstrip("\r\n").encode();declarations.append({"logical_name":Path(path).name,
                  "symbol":name+"."+anchor.split("=>")[0].strip().split()[-1],"start_line":i+1,"end_line":i+1,
                  "utf8_bytes":len(raw),"sha256":sha(raw),"hash_scope":"Exact UTF8 one-line expression declaration without terminal newline/BOM; no code copied."})
            elif "(" in anchor or "{" not in anchor:decl(path,name+"."+anchor.split("(")[0].split()[-1],anchor)
    for name in class_names:
        path=MODEL+name+".cs"
        decl(path,name+"-inheritance","public "+("abstract " if name=="MRAData" else "")+"class "+name,
             ("MRAData : WidgetBaseData",) if name=="MRAData" else (name+" : MRAData",))
    for property_,offset in (("StatusDisplayType",1),("Zone",1),("Multiplexer",1),("BigIconOnIndex",2),("BigIconOffIndex",3),("FunctionVariant",6)):
        for accessor in ("get_","set_"):ints(M+"MRAData::"+accessor+property_,[offset],"base-"+accessor+property_+"-offset")
    ints(M+"MRAData::get_StatusDisplayType",[7],"mra-status-low-three-bits")
    ints(M+"MRAData::set_StatusDisplayType",[248],"mra-status-preserve-upper-five-bits")
    order(M+"MRAData::set_StatusDisplayType",["get_ValueAsInt","set_ValueAsInt","NotifyPropertyChanged"],"status-write-before-notify")
    absent(M+"MRAData::set_StatusDisplayType",["set_StatusValueIndex","set_LabelValueIndex"],"no-appgroup-index-reset")
    decl(MODEL+"MRAData.cs","status-direct-body","public int StatusDisplayType",("value + (valueAsInt & 0xF8)",'NotifyPropertyChanged("StatusDisplayValueEditable")'))
    decl(MODEL+"MRAData.cs","function-variant-same-value-guard","public int FunctionVariant",("WidgetByte(6).ValueAsInt != value",'NotifyPropertyChanged("FunctionVariant")'))
    ints(M+"MRAData::set_Zone",[3,199],"zone-preserves-status-multiplexer")
    ints(M+"MRAData::set_Multiplexer",[6,63],"multiplexer-preserves-zone-status")
    ints(M+"MRAData::get_StatusDisplayValueEditable",[5],"only-static-type5-status-text-visibility")
    for target,threshold in (("AbsoluteSource1",0),("AbsoluteSource2",1)):
        symbol=M+"MRASourceSelectData::get_"+target+"Editable"
        ints(symbol,[threshold],target+"-visibility-threshold")
        order(symbol,["get_FunctionVariant"],target+"-visibility-reads-variant")
    order(M+"MRASourceSelectData::get_AnyAbsoluteSourceEditable",["get_AbsoluteSource1Editable","get_AbsoluteSource2Editable"],"status-visibility-either-source-predicate")
    z=M+"MRAZoneControlData::"
    order(z+"get_DualButtonMacrofunction",["get_LeftButtonMacrofunction","get_RightButtonMacrofunction","Find","get_Item","get_Value","set_DualButtonMacrofunction","get_Item","get_Value"],"macro-getter-exact-find-before-repair")
    order(z+"set_DualButtonMacrofunction",["Split","TryParse","TryParse","set_LeftButtonMacrofunction","set_RightButtonMacrofunction","NotifyPropertyChanged"],"macro-setter-left-right-notify")
    ints(z+"set_DualButtonMacrofunction",[255],"macro-setter-raw-initial-sentinels-not-host-parse-proof")
    for a in ("get_","set_"):order(z+a+"LabelDisplayType",["NotImplementedException::.ctor"],"label-type-unimplemented-"+a)
    for owner,fields in (("MRAZoneControlData",(("Label",11),("Status",12))),("MRASourceSelectData",(("Label",9),("Status",10))),("MRASourceControlData",(("Label",7),))):
        for target,offset in fields:
            for accessor in ("get_","set_"):ints(M+owner+"::"+accessor+target+"ValueIndex",[offset],owner+"-"+accessor+target+"-raw-field")
            order(M+owner+"::set_"+target+"ValueText",["GetStaticTextIndex","set_"+target+"ValueIndex"],owner+"-"+target+"-allocate-with-old-reference")
            absent(M+owner+"::set_"+target+"ValueIndex",["NotifyPropertyChanged","set_StatusDisplayType","set_LabelDisplayType"],owner+"-"+target+"-no-type-notify-reset")
            ints(M+owner+"::get_"+target+"ValueText",[63],owner+"-"+target+"-text-known-index-bound")
    order(M+"MRASourceSelectData::set_BigIconOnIndex",["set_BigIconOnIndex","set_BigIconOffIndex"],"select-icon-on-then-off")
    order(M+"MRASourceControlData::set_BigIconOnIndex",["set_BigIconOffIndex","set_BigIconOnIndex"],"control-icon-off-then-on")
    order(M+"MRASourceSelectData::SetToDefault",["SetToDefault","set_FunctionVariant","set_LabelValueIndex","set_StatusValueText","set_BigIconOffIndex","set_BigIconOnIndex"],"source-select-default-intermediate-allocation")
    decl(MODEL+"MRASourceSelectData.cs","source-select-default-source-text","public override void SetToDefault()",('StatusValueText = "Source";',))
    order(z+"GetUsedStaticText",["GetUsedStaticText","get_StatusDisplayType","get_StatusValueIndex","Add","get_LabelValueIndex","Add"],"zone-status-static-only-then-label")
    ints(z+"GetUsedStaticText",[5],"zone-static-status-reference-condition")
    order(M+"MRASourceSelectData::GetUsedStaticText",["GetUsedStaticText","get_StatusValueIndex","Add","get_LabelValueIndex","Add"],"select-hidden-status-and-label-reserved")
    order(M+"MRASourceControlData::GetUsedStaticText",["GetUsedStaticText","get_LabelValueIndex","Add"],"control-label-only-reserved")
    absent(M+"MRASourceSelectData::GetUsedStaticText",["get_FunctionVariant"],"select-hidden-reference-not-variant-dependent")
    for name in class_names:
        if M+name+"::SetForcedValues" in images["CBusLogicModel.dll"].methods:raise ValueError("Unexpected MRA forced override")
    checks.append({"id":"all-three-use-inherited-empty-SetForcedValues","passed":True})
    order(U+"InitializeMRAGlobalValues",["get_Widgets","OfType","get_Current","get_Multiplexer","set_MRAMultiplexer","get_Zone","set_MRAZone","MoveNext"],"first-loaded-mra-global-capture")
    # Compiler lays out the body before MoveNext but initially branches to the guard.
    expected_branches={"InitializeMRAGlobalValues":(51,86,92,53),"SetMRAWidgetGlobalValues":(51,84,90,53)}
    for name,(jump,guard,test,body) in expected_branches.items():
        branches=decoded[U+name]["branches"]
        if {"il_offset":jump,"opcode":"0x2b","target":guard} not in branches or {"il_offset":test,"opcode":"0x2d","target":body} not in branches:raise ValueError("Enumeration guard CFG differs")
        checks.append({"id":name+"-initial-jump-to-MoveNext-then-conditional-body","initial_branch":{"offset":jump,"target":guard},"condition_branch":{"offset":test,"target":body},"passed":True})
    decl(UNIT,"initializer-first-only-source-guard","public void InitializeMRAGlobalValues()",("if (enumerator.MoveNext())","MRAData current = enumerator.Current;","return;"))
    order(U+"SetMRAWidgetGlobalValues",["get_Widgets","OfType","get_MRAZone","set_Zone","get_MRAMultiplexer","set_Multiplexer"],"save-propagates-zone-before-multiplexer")
    order(U+"BeforeSavePPData",["BeforeSavePPData","SaveStaticText","SaveScenes","SetMRAWidgetGlobalValues","SetForcedValues"],"terminal-source-shared-save-order")
    order(U+"GetStaticTextIndex",["Trim","get_Length","get_StaticLabels","get_Name","Equals","GetUsedStaticText"],"blank-then-exact-retained-name-before-capacity")
    macro_path="edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.Utilities/MacroFunction.cs"
    macros_path="edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.Utilities/MacroFunctionTypes.cs"
    micros_path="edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.Utilities/MicroFunctions.cs"
    order(macro+"::GETInputValues",["AddRange","AddRange","AddRange","AddRange"],"macro-union-four-input-lists")
    order(macro+"::HasInputvalue",["GETInputValues","Any"],"macro-input-any-over-complete-union")
    decl(macro_path,"macro-input-constructor-four-lists","public MacroFunction(",("ShortPress = shortPress;","ShortRamp = shortRamp;","LongPress = longPress;","LongRamp = longRamp;"))
    decl(macro_path,"macro-input-union-order","public List<MicroFunctions.InputValues> GETInputValues()",("AddRange(ShortPress);","AddRange(ShortRamp);","AddRange(LongPress);","AddRange(LongRamp);"))
    decl(macro_path,"macro-input-membership-predicate","public bool HasInputvalue(",("GETInputValues();","popInputValues == inputValue"))
    decl(MODEL+"MRAZoneControlData.cs","zone-two-key-eligibility-loop","public bool InputValueIsEditable(",("macroFunction.Key == LeftButtonMacrofunction","macroFunction.Key == RightButtonMacrofunction","if (flag || num >= 2)"))
    macro_table=decl(macros_path,"macro-function-table","public static List<KeyValuePair<int, MacroFunction>> MacroFunctions =")
    macro_rows={int(key):[part.strip().removeprefix("MicroFunctions.") for part in values.split(",")] for key,values in re.findall(r"new KeyValuePair<int, MacroFunction>\((\d+), new MacroFunction\(([^)]*)\)\)",macro_table)}
    expected_macros={15:["Idle","OffKey","DownKey","EndRamp"],16:["Idle","OnKey","UpKey","EndRamp"],21:["Idle","NudgeDown","Idle","Idle"],22:["Idle","NudgeUp","Idle","Idle"]}
    if any(macro_rows.get(key)!=value for key,value in expected_macros.items()):raise ValueError("MRA macro four-list roster differs")
    micro_text=originals[micros_path].decode("utf-8-sig")
    input_lists={name:re.findall(r"InputValues\.([A-Za-z0-9_]+)",body) for name,body in re.findall(r"public static List<InputValues> ([A-Za-z0-9_]+) = new List<InputValues>\s*([\s\S]*?);",micro_text)}
    enum=decl(micros_path,"micro-input-values","public enum InputValues")
    enum_names=re.findall(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*,?\s*$",enum,re.M)
    if enum_names[:2]!=["Offset","RampRate"]:raise ValueError("Macro input enum order differs")
    macro_profiles=[]
    for key,rows in expected_macros.items():
        values=[]
        for row in rows:
            if row not in input_lists:raise ValueError("Macro micro-list unavailable")
            for value in input_lists[row]:
                if value not in values:values.append(value)
        expected=["RampRate"] if key in (15,16) else ["Offset"]
        if values!=expected:raise ValueError("MRA offered macro input profile differs")
        macro_profiles.append({"macro":key,"four_input_lists":rows,"inputs":values,"source_declaration_composition_only":True})
    checks.append({"id":"offered-mra-macros-exact-RampRate-versus-Offset","profiles":macro_profiles,"passed":True})
    bindings=[]
    for panel in ("MRAZoneWidget","MRASourceSelectWidget","MRASourceControlWidget"):
        symbol="eDLT.WidgetPanels."+panel+"::"
        order(symbol+"SetUpDataSource",["SetUpDataSource","get_EDLTWidget","get_WidgetData","set_DataSource","ResetBindings"],panel+"-base-before-data-reset")
        path=PANELS+panel+".cs"
        for name,anchor in (("constructor","public "+panel+"("),("setup","public override void SetUpDataSource()"),("bindings","private void InitializeComponent()")):
            body=decl(path,panel+"-"+name,anchor)
            if name=="setup":continue
            for line in body.splitlines():
                match=re.search(r'new Binding\("([^"]*)", \(object\)([A-Za-z_0-9]+), "([^"]*)", (true|false)(?:, \(DataSourceUpdateMode\)([0-9]+))?\)',line)
                if not match:continue
                control=re.search(r'\(\(Control\)([^)]+)\)',line)
                prop,owner,target,fmt,mode=match.groups()
                bindings.append({"panel":panel,"declaration_phase":name,"control":control.group(1) if control else None,"control_property":prop,"source":owner,"source_property":target,"formatting_enabled":fmt=="true","explicit_update_mode":None if mode is None else int(mode),"update_mode_claim":"constructor default only; host schedule unassessed" if mode is None else "explicit constructor constant","line_sha256":sha(line.encode())})
    if len(bindings)!=25:raise ValueError("Exact MRA binding roster count differs: "+str(len(bindings)))
    for panel in ("MRASourceSelectWidget","MRASourceControlWidget"):
        if any(r["panel"]==panel and r["source_property"]=="StatusDisplayType" for r in bindings):raise ValueError("Invented source status picker")
    if any(r["source_property"]=="Offset" for r in bindings):raise ValueError("Unexpected bound Offset")
    checks.append({"id":"exact-25-binding-roster-no-Offset-no-source-status-picker","passed":True})
    order(B+"SetWidgetData",["set_EDLTWidget","set_EDLTWidget","SetUpDataSource"],"base-widget-clear-before-bind-and-setup")
    for name in ("ComboBoxStaticText_Leave","ComboImageTagDLT_PreviewKeyDown","ComboImageTagDLT_SelectedIndexChanged"):
        order(S+name,["WriteValue","ReadValue"],name+"-write-before-read")
    ints(S+".ctor",[64],"static-text-source-maxlength-64")
    ints(S+"ComboImageTagDLT_PreviewKeyDown",[13,37,39,38,40],"static-enter-key-and-four-arrows")
    absent(S+"DataManager_ListChanged",["WriteValue"],"eligible-static-list-refresh-no-commit")
    choices={}
    expected={"lRampRate":list(range(16)),"lFunctionStatusTypesMRA":[0,3,1,2,5],"lDualKeyMacroFunctionsMRA":["15|16","21|22"],"lMRAControlVariants":[0,1,2,3],"lMRAMultiplexer":[0,1,2],"lMRAZone":list(range(8)),"lMRASourceSelectVariant":[0,1,2],"lMRAAbsoluteSource":list(range(7)),"lMRASourceControlVariant":[0,1,2]}
    for name,wanted in expected.items():
        body=decl(COMMON,"choices-"+name,"public List<DataStore> "+name+" =")
        rows=re.findall(r'new DataStore\("([^"]*)", ("[^"]*"|[0-9]+)\)',body)
        parsed=[{"name":label,"value":json.loads(value)} for label,value in rows]
        if [r["value"] for r in parsed]!=wanted:raise ValueError("Choice order differs: "+name)
        choices[name]=parsed;checks.append({"id":"ordered-source-"+name,"values":wanted,"passed":True})
    return {"format":"cbus-private-edlt-mra-control-static-candidate-v1","candidate_only":True,"proof_interpretation":"Exact method/code spans and hashes plus ordered static call occurrences, constants and declaration predicates. Linear IL order is not a runtime trace. No event schedule, host binding parse, or original execution is inferred.",
      "original_inputs":inputs,"metadata_type_relationships":type_relationships,"macro_input_profiles":macro_profiles,"managed_method_spans":methods,"decompiled_source_symbols":declarations,"static_checks":checks,"ordered_panel_bindings":bindings,"source_choices":choices,
      "source_contract":{"inheritance":"MRAData derives WidgetBaseData, not StatusLabelTypeData/AppGroup. Its low-three-bit status setter does not reset index fields.",
       "status":"Exact byte1 setter uses value+(old&0xF8), then StatusDisplayValueEditable notification intent; offered values0/3/1/2/5 preserve upper five bits. The setter does not itself mask/clamp arbitrary caller values. FunctionVariant has unequal-byte6 guard.",
       "zone_macro_getter":"Exact list Find; absent pair writes first source pair via setter. Explicit getter effects, not automatic view evaluation.",
       "label_type":"Both Zone LabelDisplayType accessors throw NotImplementedException; no type picker is admitted.",
       "static_fields":{"zone":{"label":11,"status":12},"source-select":{"label":9,"status":10},"source-control":{"label":7}},
       "icon_order":"SourceSelect writes on then off; SourceControl off then on. Zone inherits independent on/off.",
       "defaults":"SourceSelect status Source allocation occurs before icon setters and requested edits; all original default calls/bodies remain pinned.",
       "hidden_references":"SourceSelect always reserves its status and label indices; Zone status reserved only for static type5; SourceControl reserves only label.",
       "global_order":"Initialize captures first loaded MRA globals. BeforeSave saves static/scenes, propagates Zone then Multiplexer and later calls inherited forced values.",
       "binding_mode":"25 exact panel bindings; default mode versus explicit1/2 retained separately. Declaration constants are not a host parsing/scheduling proof.",
       "static_callbacks":"Explicit Enter-key/Leave/selection callbacks WriteValue then ReadValue; eligible list refresh only ReadValue; no implicit close or schedule."},
      "unsatisfied_facts":["Actual original initialized parent/WinForms control schedule and original combined workflow.","Default binding validation/currency, implicit selection/null parse/notification refresh.","Culture/equal-name suggestion ordering; async BeginInvoke timing and modal close.","Full framework Unicode table/host TextBox behavior beyond existing named profiles.","SharpImageSelector modal/cancel scheduling and custom GDI/image rendering.","Complete model/firmware profiles, audio-control delivery, physical rendering/persistence."],
      "omissions":{"vendor_source_text_published":False,"raw_il_bytes_published":False,"original_literal_heaps_published":False,"private_coordinates_published":False},
      "limits":{"original_instructions_executed":0,"framework_instructions_executed":0,"native_service_executed":False,"physical_device_verified":False,"runtime_implementation_added":False,"current_release_acceptance":False}}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--repository-root",type=Path,required=True);p.add_argument("--vendor-root",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--check",action="store_true");o=p.parse_args()
    result=recover(o.repository_root,o.vendor_root);raw=(json.dumps(result,indent=2)+"\n").encode()
    if o.check:
        if o.output.read_bytes()!=raw:raise SystemExit("Private MRA static candidate differs")
    else:o.output.write_bytes(raw);o.output.chmod(0o600)
    print(json.dumps({"managed_spans":len(result["managed_method_spans"]),"source_spans":len(result["decompiled_source_symbols"]),"checks":len(result["static_checks"]),"panel_bindings":len(result["ordered_panel_bindings"]),"annex_sha256":sha(raw),"original_instructions_executed":0}))

if __name__=="__main__":main()
