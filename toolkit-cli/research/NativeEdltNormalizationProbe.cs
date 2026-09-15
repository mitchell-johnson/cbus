// Original BeforeSavePPData normalization on explicit, nonzero PP fixtures.
using System;
using System.Linq;
using System.ComponentModel;
using System.Reflection;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
class NativeEdltNormalizationProbe {
 static void Attr(EDLTUnit u,string n,string v) {u.PPAttributes.Add(new PPAttribute{Name=n,Value=v});}
 static EDLTUnit Unit() {
  var u=(EDLTUnit)FormatterServices.GetUninitializedObject(typeof(EDLTUnit));
  u.PPAttributes=new BindingList<PPAttribute>();u.Widgets=new BindingList<EDLTWidget>();
  u.Scenes=new BindingList<EDLTScene>();u.StaticLabels=new BindingList<DataStore>();
  Attr(u,"PrimaryApplication","56");Attr(u,"SecondaryApplication","255");Attr(u,"Application","56 255");
  for(int n=1;n<=21;n++) {
   Attr(u,"Widget"+n+"WidgetType","0");
   for(int b=1;b<32;b++)Attr(u,"Widget"+n+"WidgetByteValue"+b,b.ToString());
   if(n>=6)Attr(u,"Widget"+n+"RestoreLevel",(100+n).ToString());
   u.Widgets.Add(new EDLTWidget(u,n,u.PPAttributes));
  }
  return u;
 }
 static void RawType(EDLTUnit u,int n,int kind) {u.GetPPAttribute("Widget"+n+"WidgetType").ValueAsInt=kind;u.Widgets[n-1]=new EDLTWidget(u,n,u.PPAttributes);}
 static void Dump(string phase,EDLTUnit u) {
  Console.WriteLine(phase+":"+string.Join("|",u.Widgets.Select(w=>w.WidgetNumber+"="+w.WidgetType+"/"+(w.WidgetNumber>=6?w.RestoreLevel.ToString():"none")+"/"+string.Join(",",Enumerable.Range(1,31).Select(b=>w.WidgetData.WidgetByte(b).ValueAsInt)))));
 }
 static void Save(EDLTUnit u) {typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});}
 static void Case(string name,Action<EDLTUnit> setup) {var u=Unit();setup(u);Console.WriteLine("case:"+name);Dump("before",u);Save(u);Dump("after",u);Save(u);Dump("again",u);}
 static void MRACase(string name,int selected,Action<EDLTUnit> setup,Action<EDLTUnit> edit) {
  var u=Unit();
  typeof(EDLTUnit).GetField("commonConstants",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(u,new CommonConstants());
  setup(u);u.InitializeMRAGlobalValues();Console.WriteLine("case:"+name);Console.WriteLine("selected:"+selected);Dump("source",u);
  edit(u);Dump("before",u);Save(u);Dump("after",u);Save(u);Dump("again",u);
 }
 static void MRASetup(EDLTUnit u,int first=6,int control=109) {
  RawType(u,first,7);u.GetPPAttribute("Widget"+first+"WidgetByteValue1").ValueAsInt=control;
  RawType(u,8,8);u.GetPPAttribute("Widget8WidgetByteValue1").ValueAsInt=178;
  RawType(u,10,9);u.GetPPAttribute("Widget10WidgetByteValue1").ValueAsInt=3;
 }
 static void Main(string[] args) {
  PPAttribute.bInitialiseMode=true;
  if(args.Length>0&&args[0]=="mra") {
   MRACase("unrelated",1,u=>MRASetup(u),u=>{});
   MRACase("stored-standby",1,u=>{MRASetup(u);RawType(u,1,7);u.GetPPAttribute("Widget1WidgetByteValue1").ValueAsInt=109;},u=>{});
   MRACase("stored-raw3",1,u=>MRASetup(u,6,237),u=>{});
   MRACase("replace-first",6,u=>MRASetup(u),u=>u.Widgets[5].WidgetType=10);
   MRACase("insert-earlier",6,u=>{MRASetup(u);RawType(u,6,0);u.GetPPAttribute("Widget8WidgetByteValue1").ValueAsInt=106;},u=>u.Widgets[5].WidgetType=9);
   return;
  }
  Case("no-active",u=>{});
  Case("no-active-existing-terminator",u=>RawType(u,6,255));
  Case("all-terminators",u=>{for(int n=6;n<=21;n++)RawType(u,n,255);});
  Case("standby-only",u=>u.Widgets[0].WidgetType=10);
  Case("new-trailing-terminator",u=>u.Widgets[5].WidgetType=10);
  Case("existing-trailing-terminator",u=>{u.Widgets[5].WidgetType=10;RawType(u,7,255);});
  Case("earlier-terminators",u=>{RawType(u,6,255);RawType(u,8,255);u.Widgets[8].WidgetType=10;});
  Case("last-functional-active",u=>u.Widgets[20].WidgetType=10);
 }
}
