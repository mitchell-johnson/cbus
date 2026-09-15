// Unchanged original Page Control binding and full PP save/CRC code with no external I/O.
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Xml.Linq;
using System.ComponentModel;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.CBusObjects;
using CBusLogicModel.ProgramableProperties;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;
class NativeEdltPageControlProbe {
 static T Bare<T>() {return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static void Bind(EDLTUnit u) {
  u.KeySetsEnableGroup=new PPAttributeDataSourceLogic(u.Network,u.GetPPAttribute("KeySetsEnableGroup"),u.GetPPAttribute("KeySetsEnableGroup"),false,-1,new BindingListCBusObject<DataStore>(u.Network.GetApplicationByAddress(203),"Groups","<Disabled>",null));
 }
 static EDLTUnit Unit(int[] groups) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();
  foreach(var row in new[]{new[]{"KeySetsEnableGroup","255"},new[]{"PrimaryApplication","56"},new[]{"NavWidgetType","0"},new[]{"ActivityDuration","0"}})
   u.PPAttributes.Add(new PPAttribute{Name=row[0],Value=row[1]});
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();n.bContinue=false;CBusApplication.bAdd=false;u.Network=n;
  var a=new CBusApplication(n){AddressAsInt=203,TagName="OwnedEnable",bContinue=false};n.Applications.Add(a);
  foreach(int group in groups)a.Groups.Add(new CBusGroup(a,"Owned"+group,group));
  Bind(u);return u;
 }
 static void Fixture(string[] args) {
  PPAttribute.bInitialiseMode=true;
  var u=Bare<EDLTUnit>();typeof(EDLTUnit).GetField("commonConstants",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(u,new CommonConstants());
  u.PPAttributes=new BindingList<PPAttribute>();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();u.StaticLabels=new BindingList<DataStore>();
  foreach(var line in File.ReadAllLines(args[1])){int split=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});}
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();n.bContinue=false;CBusApplication.bAdd=false;u.Network=n;
  foreach(int a in new[]{56,57,127,136,202,203}) {
   var app=new CBusApplication(n){AddressAsInt=a,bContinue=false};n.Applications.Add(app);
   for(int g=0;g<255;g++){var group=new CBusGroup(app,"Synthetic"+g,g);app.Groups.Add(group);if(a==202&&!group.Levels.Any(x=>x.AddressAsInt==77))group.Levels.Add(new CBusLevel(group,"Synthetic77",77));foreach(var v in group.Levels)v.DynamicAll=new BindingList<DataStore>();}
  }
  Bind(u);for(int w=1;w<=21;w++)u.Widgets.Add(new EDLTWidget(u,w,u.PPAttributes));
  u.InitializeMRAGlobalValues();u.LoadScenes();PPAttribute.bInitialiseMode=false;
  if(args[2]!="preserve")u.KeySetsEnableGroup.PPAttributeValue=int.Parse(args[2]);
  typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});
  string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
  typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);
  foreach(var item in u.PPAttributes)Console.WriteLine("pp:"+item.Name+"\t"+item.Value);
 }
 static void Main(string[] args) {
  if(args.Length==3){Fixture(args);return;}
  PPAttribute.bInitialiseMode=false;var u=Unit(Enumerable.Range(0,255).ToArray());var b=u.KeySetsEnableGroup;
  Console.WriteLine("binding:"+b.DisabledValue+":"+b.DataSource.ListBaseObject.ValueAsInt+":"+b.DataSource.Count+":"+b.DataSource[0].ValueAsInt+":"+b.DataSource[0].FormattedDisplay);
  for(int group=0;group<256;group++) {
   b.PPAttributeValue=group;
   Console.WriteLine("set:"+group+":"+u.GetPPAttribute("KeySetsEnableGroup").ValueAsInt+":"+b.PPAttributeValue+":"+b.IsEnabled+":"+u.GetPPAttribute("PrimaryApplication").ValueAsInt+":"+u.GetPPAttribute("NavWidgetType").ValueAsInt+":"+u.GetPPAttribute("ActivityDuration").ValueAsInt);
  }
  foreach(int[] groups in new[]{new[]{42,7},new[]{7,42},new int[0]})foreach(int group in new[]{0,7,42,99,255}){
   u=Unit(groups);b=u.KeySetsEnableGroup;b.PPAttributeValue=group;int before=u.GetPPAttribute("KeySetsEnableGroup").ValueAsInt;
   Console.WriteLine("cache:"+string.Join(",",groups)+":"+group+":"+before+":"+b.PPAttributeValue+":"+u.GetPPAttribute("KeySetsEnableGroup").ValueAsInt+":"+b.IsEnabled+":list="+string.Join(",",b.DataSource.Select(x=>x.ValueAsInt)));
  }
  foreach(int primary in new[]{56,127,136})foreach(int nav in new[]{0,1})foreach(int duration in new[]{0,30}){
   u=Unit(new[]{42});u.GetPPAttribute("PrimaryApplication").ValueAsInt=primary;u.GetPPAttribute("NavWidgetType").ValueAsInt=nav;u.GetPPAttribute("ActivityDuration").ValueAsInt=duration;
   u.KeySetsEnableGroup.PPAttributeValue=42;
   Console.WriteLine("independent:"+primary+":"+nav+":"+duration+":"+u.KeySetsEnableGroup.PPAttributeValue+":"+u.KeySetsEnableGroup.DataSource.ListBaseObject.ValueAsInt);
  }
 }
}
