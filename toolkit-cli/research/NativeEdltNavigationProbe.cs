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
using CBusLogicModel.CBusObjects;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units.EDLT.WidgetData;
using CBusLogicModel.EDLT.WidgetData.MRA;
using CBusLogicModel.Units.EDLT.WidgetData.BaseObjects;
class NativeEdltNavigationProbe {
 static void NativeFixture(string[] args) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();u.StaticLabels=new BindingList<DataStore>();u.StaticTextSuggest=new BindingList<DataStore>();
  typeof(EDLTUnit).GetField("commonConstants",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(u,new CommonConstants());
  foreach(var line in File.ReadAllLines(args[1])) {int split=line.IndexOf('\t');Attr(u,line.Substring(0,split),line.Substring(split+1));}
  for(int i=0;i<64;i++)u.StaticLabels.Add(new DataStore(u.GetPPAttribute("StaticTextString"+i).ValueAsUtf8String,i));
  for(int w=1;w<=21;w++)u.Widgets.Add(new EDLTWidget(u,w,u.PPAttributes));
  var page=Bare<EDLTPageWidget>();page.Unit=u;page.Attributes=u.PPAttributes;page.WidgetNumber=-1;page.WidgetData=new PageWidgetData(page,"NavWidget",u.PPAttributes);u.PageWidget=page;
  u.InitializeMRAGlobalValues();
  u.Network=Bare<CBusNetwork>();u.Network.Applications=new BindingList<CBusApplication>();u.Network.bContinue=false;CBusApplication.bAdd=false;
  var trigger=new CBusApplication(u.Network){AddressAsInt=202,TagName="Owned Trigger",bContinue=false};u.Network.Applications.Add(trigger);
  trigger.Groups[0].bContinue=false;trigger.Groups[0].Levels.Add(new CBusLevel(trigger.Groups[0],"Unused action0",0));
  u.LoadScenes();
  var options=new Dictionary<string,string>();foreach(var line in File.ReadAllLines(args[2])){int split=line.IndexOf('\t');options.Add(line.Substring(0,split),line.Substring(split+1));}
  var nav=(PageWidgetData)u.PageWidget.WidgetData;
  int initialPageMode=u.MultiPage;
  if(options.ContainsKey("page_mode"))u.MultiPage=int.Parse(options["page_mode"]);
  if(options.ContainsKey("variant"))u.NavWidgetVariant=int.Parse(options["variant"]);
  if(options.ContainsKey("temperature_source"))nav.TemperatureApplication=int.Parse(options["temperature_source"]);
  if(options.ContainsKey("device_or_group"))nav.NavDevIDZoneGroup=int.Parse(options["device_or_group"]);
  if(options.ContainsKey("channel_or_zone"))nav.NavChannelZoneNumber=int.Parse(options["channel_or_zone"]);
  if(options.ContainsKey("dynamic_group"))nav.PageDynamicGroup=int.Parse(options["dynamic_group"]);
  for(int pageNumber=1;pageNumber<=4;pageNumber++) {
   string text="text"+pageNumber,index="index"+pageNumber;
   if(options.ContainsKey(text))typeof(PageWidgetData).GetProperty("PageName"+pageNumber).SetValue(nav,System.Text.Encoding.UTF8.GetString(Convert.FromBase64String(options[text])),null);
   else if(options.ContainsKey(index))typeof(PageWidgetData).GetProperty("PageNameIndex"+pageNumber).SetValue(nav,int.Parse(options[index]),null);
  }
  typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});
  string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
  typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.NonPublic|BindingFlags.Instance).Invoke(u,null);
  var memory=new byte[9216];foreach(var ppa in u.PPAttributes){var param=u.UnitSpec.Descendants("Param").FirstOrDefault(x=>(string)x.Element("Name")==ppa.Name);if(param!=null)PPHelper.SetMemoryFromParamStringValue(ref memory,param,ppa.Values,ppa.Value);}
  for(int i=0;i<64;i++)Console.WriteLine("memory-static:"+i+"\t"+string.Join(" ",memory.Skip(0x1000+i*64).Take(64).Select(x=>"0x"+x.ToString("X"))));
  foreach(var item in u.PPAttributes)Console.WriteLine("pp:"+item.Name+"\t"+item.Value);
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
 static void Capacity() {
  PPAttribute.bInitialiseMode=true;
  foreach(int references in new[]{61,62}) {
   var u=Navigation();u.NavWidgetVariant=6;int next=0;
   for(int w=7;w<=21;w++) {
    u.GetPPAttribute("Widget"+w+"WidgetType").ValueAsInt=16;u.GetPPAttribute("Widget"+w+"WidgetByteValue1").ValueAsInt=5;
    for(int b=10;b<=13;b++)u.GetPPAttribute("Widget"+w+"WidgetByteValue"+b).ValueAsInt=next++;
    u.Widgets[w-1]=new EDLTWidget(u,w,u.PPAttributes);
   }
   u.GetPPAttribute("Widget6WidgetType").ValueAsInt=12;
   u.GetPPAttribute("Widget6WidgetByteValue10").ValueAsInt=60;
   u.GetPPAttribute("Widget6WidgetByteValue11").ValueAsInt=references-1;
   u.GetPPAttribute("Widget6WidgetByteValue13").ValueAsInt=64;
   u.Widgets[5]=new EDLTWidget(u,6,u.PPAttributes);
   try {((PageWidgetData)u.PageWidget.WidgetData).PageName1="New page";Console.WriteLine("capacity-"+references+":ok:"+u.GetPPAttribute("PageNameIndex1").ValueAsInt);}
   catch(Exception error){Console.WriteLine("capacity-"+references+":error:"+error.Message);}
  }
 }
 static void Main(string[] args) {
  if(args.Length==3){NativeFixture(args);return;}
  if(args.Length==1 && args[0]=="capacity"){Capacity();return;}
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
