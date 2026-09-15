// Original navigation/standby model evidence and full standby PP save; no device I/O.
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
class NativeEdltStandbyProbe {
 static void NativeFixture(string[] args) {
  PPAttribute.bInitialiseMode=true;
  var unit=(EDLTUnit)FormatterServices.GetUninitializedObject(typeof(EDLTUnit));
  typeof(EDLTUnit).GetField("commonConstants",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(unit,new CommonConstants());
  unit.PPAttributes=new BindingList<PPAttribute>();unit.Widgets=new BindingList<EDLTWidget>();
  unit.Scenes=new BindingList<EDLTScene>();unit.StaticLabels=new BindingList<DataStore>();
  foreach(var line in File.ReadAllLines(args[1])) {
   var split=line.IndexOf('\t');unit.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});
  }
  for(int n=1;n<=21;n++)unit.Widgets.Add(new EDLTWidget(unit,n,unit.PPAttributes));
  unit.InitializeMRAGlobalValues();
  if(args[2]!="keep")unit.EnableStandByPage=int.Parse(args[2]);
  if(args[3]!="keep")unit.ActivityDuration=int.Parse(args[3]);
  if(args[4]!="keep")unit.TimeoutPage=int.Parse(args[4]);
  if(args[5]!="keep")unit.EnableNightlightUserKey=int.Parse(args[5]);
  if(args[6]!="keep")unit.EnableNightlightPageKey=int.Parse(args[6]);
  if(args[7]!="keep")unit.NightlightColour=int.Parse(args[7]);
  typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(unit,new object[]{true,false});
  string xml=File.ReadAllText(args[0]);unit.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
  typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(unit,null);
  foreach(var item in unit.PPAttributes)Console.WriteLine("pp:"+item.Name+"\t"+item.Value);
 }

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

 static EDLTUnit Navigation() {
  var u=Unit();foreach(var pair in new[]{new[]{"ActivityDuration","30"},new[]{"TimeoutPage","2"},new[]{"EnableNightlightUserKey","0"},new[]{"EnableNightlightPageKey","0"},new[]{"NightlightColour","1"},new[]{"QuickStatusMode","0"},new[]{"QuickStatusColour1","2"},new[]{"QuickStatusColour2","7"},new[]{"QuickStatusColour3","3"},new[]{"QuickStatusLevel1","85"},new[]{"QuickStatusLevel2","170"},new[]{"NavigationIndicatorColour","1"},new[]{"TemperatureApplication","0"},new[]{"NavDevIDZoneGroup","255"},new[]{"NavChannelZoneNumber","0"},new[]{"DynamicGroup","255"}})Attr(u,pair[0],pair[1]);
  for(int i=1;i<=4;i++)Attr(u,"PageNameIndex"+i,(40+i).ToString());return u;
 }
 static void Values(string name,EDLTUnit u) {
  var names=new[]{"ActivityDuration","TimeoutPage","EnableNightlightUserKey","EnableNightlightPageKey","NightlightColour","QuickStatusMode","QuickStatusColour1","QuickStatusColour2","QuickStatusColour3","QuickStatusLevel1","QuickStatusLevel2","NavWidgetType","NavWidgetVariant","PageNameIndex1","PageNameIndex2","PageNameIndex3","PageNameIndex4","TemperatureApplication","NavDevIDZoneGroup","NavChannelZoneNumber","DynamicGroup"};
  Console.WriteLine(name+":"+string.Join("|",names.Select(n=>n+"="+u.GetPPAttribute(n).ValueAsInt)));
 }
 static void Main(string[] args) {
  if(args.Length==8){NativeFixture(args);return;}
  PPAttribute.bInitialiseMode=true;var c=new CommonConstants();
  foreach(string p in new[]{"NavigationWidgetOptions","NavigationTempApplications","NightlightColourVariants","TimeoutPage","ActivityDuration","QuickStatus","ScreenColours","KeyColours"}) {
   var property=typeof(CommonConstants).GetProperty(p);if(property==null){Console.WriteLine("missing-list:"+p);continue;}
   var list=(System.Collections.Generic.List<DataStore>)property.GetValue(c,null);Console.WriteLine("choices-"+p+":"+string.Join("|",list.Select(d=>d.ValueAsInt+"="+d.Name)));
  }
  foreach(int initial in new[]{0,1,2,3,30,255})foreach(int value in new[]{0,1}){var u=Navigation();u.GetPPAttribute("ActivityDuration").ValueAsInt=initial;u.EnableStandByPage=value;Values("standby-"+initial+"-"+value,u);}
  foreach(int initial in new[]{0,1,2,3,255})foreach(int value in new[]{0,1}) {
   var u=Navigation();u.GetPPAttribute("TimeoutPage").ValueAsInt=initial;u.StandByNoPageChange=value;Values("stay-"+initial+"-"+value,u);
   u=Navigation();u.GetPPAttribute("TimeoutPage").ValueAsInt=initial;u.StandByPageChange=value;Values("change-"+initial+"-"+value,u);
  }
  foreach(int initial in new[]{0,1,2,3,255}){var u=Navigation();u.GetPPAttribute("NavWidgetType").ValueAsInt=initial;Console.WriteLine("page-getter-"+initial+":"+u.MultiPage+":"+u.SinglePage+":"+u.GetPPAttribute("NavWidgetType").ValueAsInt);}
  foreach(int initial in new[]{0,1,2,3})foreach(bool enabled in new[]{false,true}){var u=Navigation();u.QuickStatusMode=initial;u.QuickStatusEnabled=enabled;Values("quick-enable-"+initial+"-"+enabled,u);}
  foreach(int variant in new[]{0,1,2,3,4,5,6,7,15}) {
   var u=Navigation();u.NavWidgetVariant=variant;var d=(PageWidgetData)u.PageWidget.WidgetData;
   Values("variant-"+variant,u);Console.WriteLine("editable-"+variant+":"+d.NavTempEditable+","+d.NavLogoEditable+","+d.NavDynGroupEditable+","+d.NavDynLabelEditable+","+d.NavStaticTextEditable+","+d.NavStaticTextVisible);
   for(int i=1;i<=4;i++)u.GetPPAttribute("PageNameIndex"+i).ValueAsInt=40+i;
   u.NavWidgetVariant=variant;Values("same-variant-"+variant,u);
  }
  for(int user=0;user<2;user++)for(int page=0;page<2;page++){var u=Navigation();u.EnableNightlightUserKey=user;u.EnableNightlightPageKey=page;Console.WriteLine("nightlight-"+user+"-"+page+":"+u.EnableNightlightColour);}
 }
}
