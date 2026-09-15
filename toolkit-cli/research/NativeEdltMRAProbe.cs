// Original MRA model/UI evidence on explicit owned fixtures; no device I/O.
using System;
using System.IO;
using System.Xml.Linq;
using System.Collections.Generic;
using CBusLogicModel.Units;
using System.Linq;
using System.ComponentModel;
using System.Reflection;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units.EDLT.WidgetData;
using CBusLogicModel.EDLT.WidgetData.MRA;
using CBusLogicModel.Units.EDLT.WidgetData.BaseObjects;
class NativeMRAProbe {
 static T Bare<T>() {return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static void Attr(EDLTUnit u,string n,string v) {u.PPAttributes.Add(new PPAttribute{Name=n,Value=v});}
 static EDLTUnit Unit(bool opaque=false) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();u.StaticLabels=new BindingList<DataStore>();u.StaticTextSuggest=new BindingList<DataStore>();
  typeof(EDLTUnit).GetField("commonConstants",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(u,new CommonConstants());
  foreach(var pair in new[]{new[]{"PrimaryApplication","56"},new[]{"SecondaryApplication","255"},new[]{"Application","56 255"},new[]{"NavWidgetType","0"},new[]{"NavWidgetVariant","0"}})Attr(u,pair[0],pair[1]);
  for(int w=1;w<=21;w++) {
   Attr(u,"Widget"+w+"WidgetType","0");
   for(int b=1;b<32;b++)Attr(u,"Widget"+w+"WidgetByteValue"+b,"0x"+(opaque?b:0).ToString("X"));
   if(w>=6)Attr(u,"Widget"+w+"RestoreLevel",(100+w).ToString());
   u.Widgets.Add(new EDLTWidget(u,w,u.PPAttributes));
  }
  for(int i=0;i<64;i++){var p=new PPAttribute{Name="StaticTextString"+i};p.ValueAsUtf8String="";u.PPAttributes.Add(p);u.StaticLabels.Add(new DataStore("",i));}
  var page=Bare<EDLTPageWidget>();page.Unit=u;page.Attributes=u.PPAttributes;page.WidgetNumber=-1;page.WidgetData=new PageWidgetData(page,"NavWidget",u.PPAttributes);u.PageWidget=page;
  u.InitializeMRAGlobalValues();return u;
 }
 static string Record(EDLTWidget w) {return BitConverter.ToString(new[]{(byte)w.WidgetType}.Concat(Enumerable.Range(1,31).Select(b=>(byte)w.WidgetData.WidgetByte(b).ValueAsInt)).ToArray()).Replace("-","");}
 static void Dump(string label,EDLTUnit u,params int[] indexes) {Console.WriteLine(label+":"+string.Join("|",indexes.Select(n=>n+"="+Record(u.Widgets[n-1])+"@"+(n<6?"none":u.Widgets[n-1].RestoreLevel.ToString())))+":global="+u.MRAMultiplexer+","+u.MRAZone);}
 static void Used(string label,MRAData data) {Console.WriteLine(label+":"+string.Join(",",data.GetUsedStaticText().OrderBy(x=>x)));}
 static void Choices(string n,System.Collections.Generic.List<DataStore> list) {Console.WriteLine(n+":"+string.Join("|",list.Select(x=>x.Value+"="+x.Name)));}
 static void NativeFixture(string[] args) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();u.StaticLabels=new BindingList<DataStore>();u.StaticTextSuggest=new BindingList<DataStore>();
  typeof(EDLTUnit).GetField("commonConstants",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(u,new CommonConstants());
  foreach(var line in File.ReadAllLines(args[1])) {int split=line.IndexOf('\t');Attr(u,line.Substring(0,split),line.Substring(split+1));}
  for(int i=0;i<64;i++)u.StaticLabels.Add(new DataStore(u.GetPPAttribute("StaticTextString"+i).ValueAsUtf8String,i));
  for(int w=1;w<=21;w++)u.Widgets.Add(new EDLTWidget(u,w,u.PPAttributes));
  var page=Bare<EDLTPageWidget>();page.Unit=u;page.Attributes=u.PPAttributes;page.WidgetNumber=-1;page.WidgetData=new PageWidgetData(page,"NavWidget",u.PPAttributes);u.PageWidget=page;
  u.InitializeMRAGlobalValues();
  var options=new Dictionary<string,string>();foreach(var line in File.ReadAllLines(args[2])){int split=line.IndexOf('\t');options.Add(line.Substring(0,split),line.Substring(split+1));}
  if(options.ContainsKey("widget")) {
   var w=u.Widgets[int.Parse(options["widget"])-1];w.WidgetType=int.Parse(options["kind"]);var d=(MRAData)w.WidgetData;
   if(options.ContainsKey("variant"))d.FunctionVariant=int.Parse(options["variant"]);
   var z=d as MRAZoneControlData;var s=d as MRASourceSelectData;var c=d as MRASourceControlData;
   if(z!=null) {
    if(options.ContainsKey("key"))z.DualButtonMacrofunction=options["key"];else{var ignored=z.DualButtonMacrofunction;}
    if(options.ContainsKey("ramp"))z.RampRate=int.Parse(options["ramp"]);
    if(options.ContainsKey("status"))z.StatusDisplayType=int.Parse(options["status"]);
    if(options.ContainsKey("label-text"))z.LabelValueText=options["label-text"];
    if(options.ContainsKey("status-text"))z.StatusValueText=options["status-text"];
    if(options.ContainsKey("on"))z.BigIconOnIndex=int.Parse(options["on"]);
    if(options.ContainsKey("off"))z.BigIconOffIndex=int.Parse(options["off"]);
   } else if(s!=null) {
    if(options.ContainsKey("source1"))s.AbsoluteSource1=int.Parse(options["source1"]);
    if(options.ContainsKey("source2"))s.AbsoluteSource2=int.Parse(options["source2"]);
    if(options.ContainsKey("label-text"))s.LabelValueText=options["label-text"];
    if(options.ContainsKey("status-text"))s.StatusValueText=options["status-text"];
    if(options.ContainsKey("on"))s.BigIconOnIndex=int.Parse(options["on"]);
   } else if(c!=null) {
    if(options.ContainsKey("label-text"))c.LabelValueText=options["label-text"];
    if(options.ContainsKey("on"))c.BigIconOnIndex=int.Parse(options["on"]);
   }
  }
  if(options.ContainsKey("multiplexer"))u.MRAMultiplexer=int.Parse(options["multiplexer"]);
  if(options.ContainsKey("zone"))u.MRAZone=int.Parse(options["zone"]);
  if(options.ContainsKey("page-mode"))u.MultiPage=int.Parse(options["page-mode"]);
  typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});
  string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
  typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.NonPublic|BindingFlags.Instance).Invoke(u,null);
  var memory=new byte[9216];foreach(var ppa in u.PPAttributes){var param=u.UnitSpec.Descendants("Param").FirstOrDefault(x=>(string)x.Element("Name")==ppa.Name);if(param!=null)PPHelper.SetMemoryFromParamStringValue(ref memory,param,ppa.Values,ppa.Value);}
  for(int i=0;i<64;i++)Console.WriteLine("memory-static:"+i+"\t"+string.Join(" ",memory.Skip(0x1000+i*64).Take(64).Select(x=>"0x"+x.ToString("X"))));
  foreach(var item in u.PPAttributes)Console.WriteLine("pp:"+item.Name+"\t"+item.Value);
 }
 static void Main(string[] args) {
  PPAttribute.bInitialiseMode=true;if(args.Length==3){NativeFixture(args);return;}var c=new CommonConstants();
  Choices("multiplexers",c.MRAMultiplexer);Choices("zones",c.MRAZone);Choices("zone-controls",c.MRAControlVariants);Choices("zone-keys",c.DualKeyMacroFunctionsMRA);Choices("zone-status",c.FunctionStatusTypesMRA);Choices("select-variants",c.MRASourceSelectVariant);Choices("sources",c.MRAAbsoluteSource);Choices("control-variants",c.MRASourceControlVariant);Choices("ramps",c.RampRates);
  var ui=Bare<eDLT.FrmBaseUnit>();typeof(eDLT.FrmBaseUnit).GetField("_CommonConstants",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(ui,c);
  foreach(int n in Enumerable.Range(1,21).Prepend(-1))Console.WriteLine("ui-types-"+n+":"+string.Join(",",ui.GetAvailableWidgetTypes(new EDLTWidget{WidgetNumber=n}).Select(x=>x.ValueAsInt)));
  foreach(int kind in new[]{7,8,9})foreach(bool opaque in new[]{false,true}) {
   var u=Unit(opaque);if(opaque)u.GetPPAttribute("Widget6WidgetByteValue1").ValueAsInt=255;
   u.Widgets[5].WidgetType=kind;Dump("default-"+kind+"-"+opaque,u,6);
   var data=(MRAData)u.Widgets[5].WidgetData;Used("default-used-"+kind+"-"+opaque,data);
   data.SetForcedValues();Dump("forced-"+kind+"-"+opaque,u,6);
   u.SetMRAWidgetGlobalValues();Dump("global-normalized-"+kind+"-"+opaque,u,6);
   u.Widgets[5].RestoreLevel=155;u.Widgets[5].WidgetType=kind;Dump("same-type-"+kind+"-"+opaque,u,6);
  }
  foreach(int references in new[]{61,62}) {
   var capacity=Unit();int index=0;
   for(int w=7;w<=21;w++){capacity.GetPPAttribute("Widget"+w+"WidgetType").ValueAsInt=16;capacity.GetPPAttribute("Widget"+w+"WidgetByteValue1").ValueAsInt=5;for(int b=10;b<=13;b++)capacity.GetPPAttribute("Widget"+w+"WidgetByteValue"+b).ValueAsInt=index++;capacity.Widgets[w-1]=new EDLTWidget(capacity,w,capacity.PPAttributes);}
   capacity.GetPPAttribute("Widget5WidgetType").ValueAsInt=12;
   foreach(int b in new[]{10,11,13})capacity.GetPPAttribute("Widget5WidgetByteValue"+b).ValueAsInt=b==11?references-1:60;
   capacity.Widgets[4]=new EDLTWidget(capacity,5,capacity.PPAttributes);
   capacity.GetPPAttribute("Widget6WidgetByteValue10").ValueAsInt=200;
   try{capacity.Widgets[5].WidgetType=8;Console.WriteLine("transient-capacity-"+references+":ok:"+Record(capacity.Widgets[5]));}
   catch(Exception e){Console.WriteLine("transient-capacity-"+references+":error:"+e.Message);}
  }
  var transient=Unit();transient.GetPPAttribute("Widget6WidgetByteValue10").ValueAsInt=200;transient.Widgets[5].WidgetType=8;Dump("select-transient-invalid-default",transient,6);
  var z=Unit();z.Widgets[5].WidgetType=7;var zd=(MRAZoneControlData)z.Widgets[5].WidgetData;
  foreach(string macro in new[]{"15|16","21|22"}){zd.DualButtonMacrofunction=macro;Console.WriteLine("editable-"+macro+":"+zd.RampRateEditable+","+zd.OffsetEditable);Dump("zone-macro-"+macro,z,6);}
  foreach(int variant in new[]{0,1,2,3}){zd.FunctionVariant=variant;Dump("zone-variant-"+variant,z,6);}
  zd.DualButtonMacrofunction="15|16";zd.RampRate=15;zd.StatusDisplayType=5;zd.LabelValueText="Kitchen";zd.StatusValueText="Audio";Dump("zone-custom",z,6);Used("zone-static-used",zd);
  zd.StatusDisplayType=0;Dump("zone-hidden-status",z,6);Used("zone-hidden-used",zd);
  zd.LeftButtonMacrofunction=254;zd.RightButtonMacrofunction=253;Console.WriteLine("invalid-macro-getter:"+zd.DualButtonMacrofunction);Dump("zone-invalid-macro-normalized",z,6);
  zd.BigIconOnIndex=0;zd.BigIconOffIndex=252;Dump("zone-icon-boundaries",z,6);
  for(int status=0;status<6;status++)if(status!=4){zd.StatusDisplayType=status;Dump("zone-status-"+status,z,6);}
  var ns=Unit();ns.GetPPAttribute("StaticTextString11").ValueAsUtf8String="Source";ns.StaticLabels[11].Name="Source";ns.Widgets[5].WidgetType=8;Dump("native-source-default-reuse",ns,6);
  var s=Unit(true);s.Widgets[5].WidgetType=8;var sd=(MRASourceSelectData)s.Widgets[5].WidgetData;
  foreach(int variant in new[]{0,1,2}){sd.FunctionVariant=variant;Dump("select-variant-"+variant,s,6);Console.WriteLine("select-editable-"+variant+":"+sd.AbsoluteSource1Editable+","+sd.AbsoluteSource2Editable+","+sd.AnyAbsoluteSourceEditable);}
  sd.AbsoluteSource1=0;sd.AbsoluteSource2=6;sd.LabelValueText="Music";sd.StatusValueText="Source";sd.BigIconOnIndex=38;Dump("select-custom",s,6);Used("select-static-used",sd);sd.FunctionVariant=0;Used("select-hidden-used",sd);Dump("select-hidden-preserved",s,6);
  for(int first=0;first<7;first++)for(int second=0;second<7;second++){sd.FunctionVariant=2;sd.AbsoluteSource1=first;sd.AbsoluteSource2=second;Dump("source-pair-"+first+"-"+second,s,6);}
  sd.LabelValueText="";sd.StatusValueText=" ";Dump("select-blank-texts",s,6);Used("select-blank-used",sd);
  var r=Unit();r.Widgets[5].WidgetType=9;var rd=(MRASourceControlData)r.Widgets[5].WidgetData;
  foreach(int variant in new[]{0,1,2}){rd.FunctionVariant=variant;Dump("control-variant-"+variant,r,6);}
  rd.LabelValueText="Playback";rd.BigIconOnIndex=254;Dump("control-custom",r,6);Used("control-used",rd);
  var shared=Unit();shared.Widgets[7].WidgetType=8;((MRAData)shared.Widgets[7].WidgetData).Multiplexer=1;((MRAData)shared.Widgets[7].WidgetData).Zone=3;
  shared.Widgets[9].WidgetType=9;((MRAData)shared.Widgets[9].WidgetData).Multiplexer=2;((MRAData)shared.Widgets[9].WidgetData).Zone=7;
  shared.InitializeMRAGlobalValues();Dump("globals-first-existing",shared,8,10);
  shared.Widgets[5].WidgetType=7;((MRAData)shared.Widgets[5].WidgetData).StatusDisplayType=5;Dump("new-earlier-before-save",shared,6,8,10);
  shared.SetMRAWidgetGlobalValues();Dump("new-earlier-global-propagation",shared,6,8,10);
  typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(shared,new object[]{true,false});Dump("before-save-global-propagation",shared,6,8,10,11);
  for(int mux=0;mux<3;mux++)for(int zone=0;zone<8;zone++){shared.MRAMultiplexer=mux;shared.MRAZone=zone;shared.SetMRAWidgetGlobalValues();Dump("global-pair-"+mux+"-"+zone,shared,6,8,10);}
 }
}
