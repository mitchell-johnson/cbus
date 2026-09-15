// Runtime-only: execute unchanged original HVAC model and UI availability.
using System;
using System.Linq;
using System.IO;
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
class NativeEdltMeasurementStandbyProbe {
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
 static void Fixture(string[] args) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();
  foreach(string line in File.ReadAllLines(args[1])){int split=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});}
  Setup(u);var w=u.Widgets[int.Parse(args[2])-1];w.WidgetType=12;var d=(MeasurementData)w.WidgetData;
  d.DeviceID=int.Parse(args[3]);d.Channel=int.Parse(args[4]);d.Precision=int.Parse(args[5]);
  d.Gain=int.Parse(args[6]);d.GainExponent=int.Parse(args[7]);d.Offset=int.Parse(args[8]);d.OffsetExponent=int.Parse(args[9]);
  if(args[10]!="-")d.PrefixText=args[10];if(args[11]!="-")d.SuffixText=args[11];
  if(args[12]!="-"){if(args[12].StartsWith("@"))d.FunctionStatusTextIndex=int.Parse(args[12].Substring(1));else d.FunctionStatusText=args[12];}
  Console.WriteLine("fixture-page-mode:"+u.MultiPage);Save(u);
  string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
  typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.NonPublic|BindingFlags.Instance).Invoke(u,null);
  var memory=new byte[9216];foreach(var ppa in u.PPAttributes){var param=u.UnitSpec.Descendants("Param").FirstOrDefault(x=>(string)x.Element("Name")==ppa.Name);if(param!=null)PPHelper.SetMemoryFromParamStringValue(ref memory,param,ppa.Values,ppa.Value);}
  for(int i=0;i<64;i++)Console.WriteLine("memory-static:"+i+"\t"+string.Join(" ",memory.Skip(0x1000+i*64).Take(64).Select(x=>"0x"+x.ToString("X"))));
  Dump("fixture",w);foreach(var item in u.PPAttributes)Console.WriteLine("pp:"+item.Name+"\t"+item.Value);
 }
 static void Main(string[] args) {
  PPAttribute.bInitialiseMode=true;if(args.Length==13){Fixture(args);return;}
  var constants=new CommonConstants();var ui=Bare<eDLT.FrmBaseUnit>();typeof(eDLT.FrmBaseUnit).GetField("_CommonConstants",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(ui,constants);
  for(int n=1;n<=5;n++) {
   Console.WriteLine("ui-available-"+n+":"+ui.GetAvailableWidgetTypes(new EDLTWidget{WidgetNumber=n}).Any(x=>x.ValueAsInt==12));
   var unit=Unit();var widget=unit.Widgets[n-1];widget.WidgetType=12;var data=(MeasurementData)widget.WidgetData;
   Dump("default-"+n,widget);Console.WriteLine("has-restore-"+n+":"+(unit.GetPPAttribute("Widget"+n+"RestoreLevel")!=null));
   data.DeviceID=42;data.Channel=3;data.Precision=1;data.Gain=125;data.GainExponent=-2;data.Offset=-25;data.OffsetExponent=-1;
   Dump("scaled-"+n,widget);Save(unit);Dump("saved-"+n,widget);
   for(int b=14;b<32;b++)widget.WidgetData.WidgetByte(b).ValueAsInt=b;
   widget.WidgetType=12;Dump("same-type-"+n,widget);
  }
 }
}
