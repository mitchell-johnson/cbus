// Research-only: execute unchanged original model and UI availability method.
using System;
using System.Linq;
using System.IO;
using System.Xml.Linq;
using CBusLogicModel.Units;
using System.Collections.Generic;
using System.ComponentModel;
using System.Reflection;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.EDLT.WidgetData;
using CBusLogicModel.Units.EDLT.WidgetData.BaseObjects;
class NativeTimeDateProbe {
 static T Bare<T>() { return (T)FormatterServices.GetUninitializedObject(typeof(T)); }
 static void Attr(EDLTUnit u,string name,string value) {u.PPAttributes.Add(new PPAttribute{Name=name,Value=value});}
 static EDLTUnit Unit(bool opaque=false) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();u.StaticLabels=new BindingList<DataStore>();
  foreach(var pair in new[]{new[]{"PrimaryApplication","56"},new[]{"SecondaryApplication","255"},new[]{"Application","56 255"},new[]{"DateFormat","1"},new[]{"TimeFormat","3"},new[]{"TimeDateLeadingZero","0"},new[]{"NavWidgetType","0"}}) Attr(u,pair[0],pair[1]);
  for(int w=1;w<=21;w++) {
   Attr(u,"Widget"+w+"WidgetType","0");
   for(int b=1;b<32;b++)Attr(u,"Widget"+w+"WidgetByteValue"+b,(opaque?b:0).ToString());
   if(w>=6)Attr(u,"Widget"+w+"RestoreLevel",(100+w).ToString());
   u.Widgets.Add(new EDLTWidget(u,w,u.PPAttributes));
  }
  return u;
 }
 static string Record(EDLTWidget w) { var bytes=new byte[32];bytes[0]=(byte)w.WidgetType;for(int b=1;b<32;b++)bytes[b]=(byte)w.WidgetData.WidgetByte(b).ValueAsInt;return BitConverter.ToString(bytes).Replace("-",""); }
 static void Dump(string label,EDLTUnit u,params int[] numbers) {Console.WriteLine(label+":"+string.Join("|",numbers.Select(n=>n+"="+Record(u.Widgets[n-1])+"@"+(n<6?"none":u.Widgets[n-1].RestoreLevel.ToString()))));}
 static void Save(EDLTUnit u) {typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});}
 static void NativeFixture(string[] args) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();u.StaticLabels=new BindingList<DataStore>();
  foreach(var line in File.ReadAllLines(args[1])) {int split=line.IndexOf('\t');Attr(u,line.Substring(0,split),line.Substring(split+1));}
  for(int n=1;n<=21;n++)u.Widgets.Add(new EDLTWidget(u,n,u.PPAttributes));
  var w=u.Widgets[int.Parse(args[2])-1];w.WidgetType=int.Parse(args[3]);
  ((TimeAndDateData)w.WidgetData).DisplayType=int.Parse(args[4]);
  u.DateFormat=int.Parse(args[5]);u.TimeFormat=int.Parse(args[6]);u.TimeDateLeadingZero=int.Parse(args[7]);u.MultiPage=int.Parse(args[8]);
  Save(u);
  string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
  typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.NonPublic|BindingFlags.Instance).Invoke(u,null);
  foreach(var item in u.PPAttributes)Console.WriteLine("pp:"+item.Name+"\t"+item.Value);
 }
 static void Main(string[] args) {
  PPAttribute.bInitialiseMode=true;
  if(args.Length==9){NativeFixture(args);return;}
  var c=new CommonConstants();
  Console.WriteLine("display-choices:"+string.Join("|",c.TwoSliceTimeDateStatus.Select(x=>x.ValueAsInt+"="+x.Name)));
  Console.WriteLine("date-choices:"+string.Join("|",c.DateFormat.Select(x=>x.ValueAsInt+"="+x.Name)));
  Console.WriteLine("time-choices:"+string.Join("|",c.TimeFormat.Select(x=>x.ValueAsInt+"="+x.Name)));
  Console.WriteLine("function-types:"+string.Join(",",c.WidgetTypesFunctionPages.Select(x=>x.ValueAsInt)));
  Console.WriteLine("standby-types:"+string.Join(",",c.WidgetTypesTimeOut.Select(x=>x.ValueAsInt)));
  Console.WriteLine("standby-last-types:"+string.Join(",",c.WidgetTypesTimeOutNo2Slice.Select(x=>x.ValueAsInt)));
  var ui=Bare<eDLT.FrmBaseUnit>();typeof(eDLT.FrmBaseUnit).GetField("_CommonConstants",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(ui,c);
  foreach(int n in Enumerable.Range(1,21).Prepend(-1)) Console.WriteLine("ui-types-"+n+":"+string.Join(",",ui.GetAvailableWidgetTypes(new EDLTWidget{WidgetNumber=n}).Select(x=>x.ValueAsInt)));
  foreach(int type in new[]{10,11}) {
   var u=Unit();u.Widgets[0].WidgetType=type;Dump("fresh-"+type,u,1,2);
   foreach(int display in new[]{0,1,2}) {((TimeAndDateData)u.Widgets[0].WidgetData).DisplayType=display;Dump("display-"+type+"-"+display,u,1,2);}
   var o=Unit(true);o.Widgets[5].WidgetType=type;Dump("opaque-"+type,o,6,7);
   o.Widgets[5].RestoreLevel=155;o.Widgets[5].WidgetType=type;Dump("same-type-"+type,o,6,7);
   o.Widgets[5].WidgetData.SetToDefault();Dump("explicit-default-"+type,o,6,7);
   o.Widgets[5].WidgetData.SetForcedValues();Dump("forced-"+type,o,6,7);
  }
  foreach(int neighborType in new[]{0,10,11,12,13,255}) {
   var u=Unit(true);u.GetPPAttribute("Widget2WidgetType").ValueAsInt=neighborType;
   u.Widgets[1]=new EDLTWidget(u,2,u.PPAttributes);u.Widgets[0].WidgetType=11;
   Dump("neighbor-"+neighborType,u,1,2,3);
   u.Widgets[0].WidgetType=10;Dump("shrink-after-"+neighborType,u,1,2,3);
  }
  foreach(int position in new[]{4,5,6,9,10,21}) {
   var u=Unit(true);try{u.Widgets[position-1].WidgetType=11;Dump("unrestricted-edge-"+position,u,position,Math.Min(position+1,21));}
   catch(Exception e){Console.WriteLine("edge-error-"+position+":"+e.GetType().Name+":"+Record(u.Widgets[position-1])+":notification_suppressed="+WidgetBaseData.DoNotFireNotifyPropertyChanged);WidgetBaseData.DoNotFireNotifyPropertyChanged=false;}
  }
  var same=Unit(true);same.GetPPAttribute("Widget1WidgetType").ValueAsInt=11;same.Widgets[0]=new EDLTWidget(same,1,same.PPAttributes);same.GetPPAttribute("Widget2WidgetType").ValueAsInt=10;same.Widgets[1]=new EDLTWidget(same,2,same.PPAttributes);same.Widgets[0].WidgetType=11;Dump("same-double-keeps-configured-neighbor",same,1,2);Save(same);Dump("save-keeps-existing-double-neighbor",same,1,2,6,7);
  var s=Unit(true);s.GetPPAttribute("Widget6WidgetType").ValueAsInt=255;s.Widgets[5]=new EDLTWidget(s,6,s.PPAttributes);s.Widgets[7].WidgetType=10;Dump("before-save-hole",s,6,7,8,9,10);Save(s);Dump("after-save-hole",s,6,7,8,9,10);
  var trailing=Unit(true);trailing.Widgets[0].WidgetType=11;trailing.Widgets[5].WidgetType=10;Dump("before-save-trailing",trailing,1,2,6,7,8);Save(trailing);Dump("after-save-trailing",trailing,1,2,6,7,8);
  for(int date=0;date<8;date++)for(int time=0;time<4;time++)for(int zero=0;zero<2;zero++){var u=Unit();u.DateFormat=date;u.TimeFormat=time;u.TimeDateLeadingZero=zero;Console.WriteLine("formats:"+u.DateFormat+","+u.TimeFormat+","+u.TimeDateLeadingZero);}
 }
}
