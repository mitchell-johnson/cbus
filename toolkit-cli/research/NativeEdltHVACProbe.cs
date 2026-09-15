// Runtime-only: execute unchanged original HVAC model and UI availability.
using System;
using System.Linq;
using System.IO;
using System.Text;
using System.Xml.Linq;
using System.ComponentModel;
using System.Reflection;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.CBusObjects;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.EDLT.WidgetData;
using CBusLogicModel.Units.EDLT.WidgetData;
class NativeEdltHVACProbe {
 static T Bare<T>() {return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static void Attr(EDLTUnit u,string name,int value) {var a=new PPAttribute{Name=name};a.ValueAsInt=value;u.PPAttributes.Add(a);}
 static void Setup(EDLTUnit u) {
  u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();u.StaticLabels=new BindingList<DataStore>();u.StaticTextSuggest=new BindingList<DataStore>();
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();u.Network=n;
  foreach(int application in new[]{56,57,172}) {var app=new CBusApplication(n){AddressAsInt=application};n.Applications.Add(app);foreach(int group in new[]{0,42,43,254})app.Groups.Add(new CBusGroup(app,"Synthetic"+group,group));}
  for(int i=0;i<64;i++)u.StaticLabels.Add(new DataStore(u.GetPPAttribute("StaticTextString"+i).ValueAsUtf8String,i));
  var page=Bare<EDLTPageWidget>();page.Unit=u;page.Attributes=u.PPAttributes;page.WidgetNumber=0;page.WidgetData=new PageWidgetData(page,"NavWidget",u.PPAttributes);u.PageWidget=page;
  for(int i=1;i<=21;i++)u.Widgets.Add(new EDLTWidget(u,i,u.PPAttributes));
 }
 static EDLTUnit Unit(bool opaque=false,bool nativeText=false) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();
  for(int n=1;n<=21;n++) {Attr(u,"Widget"+n+"WidgetType",0);for(int b=1;b<32;b++)Attr(u,"Widget"+n+"WidgetByteValue"+b,opaque?b:0);if(n>=6)Attr(u,"Widget"+n+"RestoreLevel",100+n);}
  Attr(u,"PrimaryApplication",56);Attr(u,"SecondaryApplication",57);Attr(u,"NavWidgetType",0);Attr(u,"NavWidgetVariant",0);Attr(u,"UseBigIcon",1);
  for(int i=0;i<64;i++){var p=new PPAttribute{Name="StaticTextString"+i};p.ValueAsUtf8String=i==1?"Lamp":nativeText&&i==18?"Temperature":"";u.PPAttributes.Add(p);}
  Setup(u);return u;
 }
 static string Record(EDLTWidget w) {var data=new byte[32];data[0]=(byte)w.WidgetType;for(int i=1;i<32;i++)data[i]=(byte)w.WidgetData.WidgetByte(i).ValueAsInt;return BitConverter.ToString(data).Replace("-","");}
 static void Dump(string name,EDLTWidget w) {Console.WriteLine(name+":"+Record(w)+":"+(w._widgetNumber<6?"none":w.RestoreLevel.ToString()));}
 static void Save(EDLTUnit u) {typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.NonPublic|BindingFlags.Instance).Invoke(u,new object[]{true,false});}
 static void Fixture(string[] args,string fileLabel=null) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();
  foreach(string line in File.ReadAllLines(args[1])){int split=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});}
  Setup(u);var w=u.Widgets[int.Parse(args[2])-1];w.WidgetType=13;var d=(HVACTempDisplayData)w.WidgetData;
  d.ZoneGroup=int.Parse(args[3]);d.Zone=int.Parse(args[4]);d.Precision=int.Parse(args[5]);d.DisplayUnits=int.Parse(args[6]);
  if(args[7]!="-")d.BigIconIndex=int.Parse(args[7]);
  if(fileLabel!=null)d.LabelValueText=fileLabel;
  else if(args[8]!="-"){if(args[8].StartsWith("@"))d.FunctionStatusText=int.Parse(args[8].Substring(1));else d.LabelValueText=args[8];}
  Console.WriteLine("fixture-page-mode:"+u.MultiPage);Save(u);string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
  typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.NonPublic|BindingFlags.Instance).Invoke(u,null);
  var memory=new byte[9216];foreach(var ppa in u.PPAttributes){var param=u.UnitSpec.Descendants("Param").FirstOrDefault(x=>(string)x.Element("Name")==ppa.Name);if(param!=null)PPHelper.SetMemoryFromParamStringValue(ref memory,param,ppa.Values,ppa.Value);}
  for(int i=0;i<64;i++)Console.WriteLine("memory-static:"+i+"\t"+string.Join(" ",memory.Skip(0x1000+i*64).Take(64).Select(x=>"0x"+x.ToString("X"))));
  Dump("fixture",w);foreach(var item in u.PPAttributes)Console.WriteLine("pp:"+item.Name+"\t"+item.Value);
 }
 static void Main(string[] args) {
  PPAttribute.bInitialiseMode=true;if(args.Length==9){Fixture(args);return;}
  if(args.Length==10 && args[8]=="label-file") {
   string label;
   try {label=new UTF8Encoding(false,true).GetString(File.ReadAllBytes(args[9]));}
   catch(DecoderFallbackException){Console.Error.WriteLine("Invalid UTF-8 label file");Environment.ExitCode=2;return;}
   Fixture(args,label);return;
  }
  if(args.Length!=0)throw new ArgumentException("Expected no arguments, nine legacy arguments, or label-file plus filename");
  var c=new CommonConstants();Console.WriteLine("zones:"+string.Join("|",c.HVACZone.Select(x=>x.ValueAsInt+"="+x.Name)));Console.WriteLine("units:"+string.Join("|",c.TemperatureUnits.Select(x=>x.ValueAsInt+"="+x.Name)));
  var ui=Bare<eDLT.FrmBaseUnit>();typeof(eDLT.FrmBaseUnit).GetField("_CommonConstants",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(ui,c);
  foreach(int n in Enumerable.Range(1,21))Console.WriteLine("ui-available-"+n+":"+ui.GetAvailableWidgetTypes(new EDLTWidget{WidgetNumber=n}).Any(x=>x.ValueAsInt==13));
  foreach(bool native in new[]{false,true}){
   var u=Unit(false,native);var w=u.Widgets[5];w.WidgetType=13;var d=(HVACTempDisplayData)w.WidgetData;string prefix=native?"native-":"isolated-";
   Dump(prefix+"default",w);Console.WriteLine(prefix+"default-text:"+d.LabelValueText);Console.WriteLine(prefix+"application:"+d.ZoneGroups.First(x=>x.AddressAsInt==42).Application.AddressAsInt);
   d.ZoneGroup=42;d.Zone=4;d.Precision=2;d.DisplayUnits=1;d.BigIconIndex=38;d.LabelValueText="Room";Dump(prefix+"custom",w);d.SetForcedValues();Dump(prefix+"forced",w);
   d.LabelValueText="Temperature";Dump(prefix+"reuse",w);d.FunctionStatusText=1;Dump(prefix+"index",w);d.LabelValueText="";Dump(prefix+"empty",w);d.LabelValueText="   ";Dump(prefix+"whitespace",w);
   d.ZoneGroup=43;w.RestoreLevel=153;d.ZoneGroup=42;Dump(prefix+"group-no-restore",w);
   CBusApplication.bAdd=false;d.ZoneGroup=41;Dump(prefix+"missing-before-get",w);Console.WriteLine(prefix+"missing-group-get:"+d.ZoneGroup);Dump(prefix+"missing-after-get",w);
   d.ZoneGroup=0;Console.WriteLine(prefix+"group0-get:"+d.ZoneGroup);d.ZoneGroup=254;Console.WriteLine(prefix+"group254-get:"+d.ZoneGroup);d.ZoneGroup=255;Console.WriteLine(prefix+"unset-get:"+d.ZoneGroup);
   d.FunctionStatusText=64;Console.WriteLine(prefix+"index64-text:"+d.LabelValueText);Console.WriteLine(prefix+"index64-used:"+string.Join(",",u.GetUsedStaticText()));
  }
  foreach(int n in new[]{1,5,6,21}){var u=Unit(true);var w=u.Widgets[n-1];w.WidgetType=13;Dump("opaque-"+n,w);if(n>=6)w.RestoreLevel=155;w.WidgetType=13;Dump("same-type-"+n,w);w.WidgetData.SetToDefault();Dump("explicit-default-"+n,w);Console.WriteLine("has-restore-"+n+":"+(u.GetPPAttribute("Widget"+n+"RestoreLevel")!=null));Save(u);Dump("after-save-"+n,w);}
  var neighbor=Unit(true);neighbor.Widgets[0].WidgetType=11;Dump("double-before",neighbor.Widgets[0]);Dump("covered-before",neighbor.Widgets[1]);neighbor.Widgets[0].WidgetType=13;Dump("shrink-hvac",neighbor.Widgets[0]);Dump("covered-after-shrink",neighbor.Widgets[1]);
 }
}
