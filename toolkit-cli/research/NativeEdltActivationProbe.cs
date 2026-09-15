// Runs unchanged original model methods against explicitly cached objects; no native network I/O.
using System;
using System.Linq;
using System.ComponentModel;
using System.Runtime.Serialization;
using System.Reflection;
using System.IO;
using System.Xml.Linq;
using CBusLogicModel;
using CBusLogicModel.CBusObjects;
using CBusLogicModel.ProgramableProperties;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units;
class NativeEdltActivationProbe {
 static T Bare<T>(){return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static EDLTUnit Unit(int primary=56) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();
  foreach(var pair in new[]{new[]{"PrimaryApplication",primary.ToString()},new[]{"ProximityMode","1"},new[]{"ProximityGroup","255"},new[]{"ProximityLevel","255"},new[]{"DeafultPage","1"},new[]{"IgnoreFirstKeyPress","0"},new[]{"TimeoutPage","2"},new[]{"ActivityDuration","30"}})u.PPAttributes.Add(new PPAttribute{Name=pair[0],Value=pair[1]});
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();n.bContinue=false;CBusApplication.bAdd=false;u.Network=n;
  foreach(int a in new[]{56,57,127,136,202}) {
   var app=new CBusApplication(n){AddressAsInt=a,TagName="Owned"+a,bContinue=false};n.Applications.Add(app);
   foreach(int g in a==202?new[]{7,77}:new[]{7,42}){var group=new CBusGroup(app,"Owned"+g,g);app.Groups.Add(group);}
  }
  u.ProximityGroup=new PPAttributeDataSourceLogic(n,u.GetPPAttribute("ProximityGroup"),u.GetPPAttribute("ProximityGroup"),false,-1,new BindingListCBusObject<DataStore>(n,"Applications",u.GetPPAttribute("PrimaryApplication"),u.GetPPAttribute("ProximityMode"),3,202,"Groups","<Unused>",null));
  return u;
 }
 static void Fixture(string[] args) {
  PPAttribute.bInitialiseMode=true;
  var u=Bare<EDLTUnit>();typeof(EDLTUnit).GetField("commonConstants",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(u,new CommonConstants());
  u.PPAttributes=new BindingList<PPAttribute>();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();u.StaticLabels=new BindingList<DataStore>();
  foreach(var line in File.ReadAllLines(args[1])){int split=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});}
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();n.bContinue=false;CBusApplication.bAdd=false;u.Network=n;
  foreach(int a in new[]{56,57,127,136,202}) {
   var app=new CBusApplication(n){AddressAsInt=a,bContinue=false};n.Applications.Add(app);
   for(int g=0;g<255;g++){var group=new CBusGroup(app,"Synthetic"+g,g);app.Groups.Add(group);if(a==202&&!group.Levels.Any(x=>x.AddressAsInt==77))group.Levels.Add(new CBusLevel(group,"Synthetic77",77));foreach(var v in group.Levels)v.DynamicAll=new BindingList<DataStore>();}
  }
  u.ProximityGroup=new PPAttributeDataSourceLogic(n,u.GetPPAttribute("ProximityGroup"),u.GetPPAttribute("ProximityGroup"),false,-1,new BindingListCBusObject<DataStore>(n,"Applications",u.GetPPAttribute("PrimaryApplication"),u.GetPPAttribute("ProximityMode"),3,202,"Groups","<Unused>",null));
  for(int w=1;w<=21;w++)u.Widgets.Add(new EDLTWidget(u,w,u.PPAttributes));
  u.InitializeMRAGlobalValues();u.LoadScenes();PPAttribute.bInitialiseMode=false;
  foreach(var line in File.ReadAllLines(args[2])) {
   var row=line.Split('\t');string name=row[0];int value=int.Parse(row[1]);
   if(name=="ProximityGroup")u.ProximityGroup.PPAttributeValue=value;
   else typeof(EDLTUnit).GetProperty(name).SetValue(u,value,null);
  }
  typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});
  string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
  typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);
  foreach(var item in u.PPAttributes)Console.WriteLine("pp:"+item.Name+"\t"+item.Value);
 }
 static void Main(string[] args) {
  if(args.Length==3){Fixture(args);return;}
  PPAttribute.bInitialiseMode=false;
  var c=new CommonConstants();foreach(var v in c.ProximityMode)Console.WriteLine("mode-option:"+v.ValueAsInt+":"+v.FormattedDisplay);
  foreach(var v in c.DefaultPage)Console.WriteLine("page-option:"+v.ValueAsInt+":"+v.FormattedDisplay);
  var u=Unit();
  foreach(int mode in Enumerable.Range(0,8))foreach(int timeout in Enumerable.Range(0,4))foreach(int activity in new[]{0,30}){
   u.ProximityMode=mode;u.TimeoutPage=timeout;u.ActivityDuration=activity;
   Console.WriteLine("guards:"+mode+":"+timeout+":"+activity+":"+u.EnableStandByPage+":"+u.WakeByProximityMode+":"+u.WakeOnKeyPress+":"+u.ProximityGroupEventEnabled+":"+u.ProximityModeIsGroup+":"+u.ProximityModeIsTrigger+":"+u.DefaultPageEnabled+":"+u.IgnoreFirstKeyPressAvailable);
  }
  for(int value=0;value<256;value++){u.ProximityLevel=value;Console.WriteLine("level:"+value+":"+u.ProximityLevel+":"+u.GetPPAttribute("ProximityLevel").ValueAsInt);}
  for(int value=0;value<5;value++){u.DefaultPage=value;Console.WriteLine("page:"+value+":"+u.DefaultPage+":"+u.GetPPAttribute("DeafultPage").ValueAsInt);}
  foreach(int mode in Enumerable.Range(0,8))foreach(int value in new[]{0,1}){
   u.ProximityMode=mode;u.ProximityGroup.PPAttributeValue=42;u.ProximityLevel=173;u.WakeByProximityMode=value;
   Console.WriteLine("radio-proximity:"+mode+":"+value+":"+u.ProximityMode+":"+u.GetPPAttribute("ProximityGroup").ValueAsInt+":"+u.ProximityLevel);
   u.ProximityMode=mode;u.WakeOnKeyPress=value;
   Console.WriteLine("radio-key:"+mode+":"+value+":"+u.ProximityMode+":"+u.GetPPAttribute("ProximityGroup").ValueAsInt+":"+u.ProximityLevel);
  }
  foreach(int primary in new[]{56,127,136})foreach(int mode in Enumerable.Range(0,4))foreach(int group in new[]{7,42,77,255}){
   u=Unit(primary);u.ProximityMode=mode;u.ProximityGroup.PPAttributeValue=group;int before=u.GetPPAttribute("ProximityGroup").ValueAsInt;
   int selected=u.ProximityGroup.PPAttributeValue;
   Console.WriteLine("group:"+primary+":"+mode+":"+group+":"+u.ProximityGroup.DataSource.ListBaseObject.ValueAsInt+":"+before+":"+selected+":"+u.GetPPAttribute("ProximityGroup").ValueAsInt+":"+u.ProximityGroup.IsEnabled+":"+u.EnableProximityLevel+":list="+string.Join(",",u.ProximityGroup.DataSource.Select(x=>x.ValueAsInt)));
  }
  foreach(int group in new[]{7,42,77,255}){
   u=Unit();u.ProximityMode=2;u.ProximityGroup.PPAttributeValue=group;u.ProximityLevel=173;u.ProximityMode=3;
   int before=u.GetPPAttribute("ProximityGroup").ValueAsInt;
   Console.WriteLine("switch:"+group+":"+before+":"+u.ProximityGroup.DataSource.ListBaseObject.ValueAsInt+":"+u.ProximityGroup.PPAttributeValue+":"+u.ProximityLevel);
  }
  u=Unit();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();u.PrimSecApplication=new BindingList<DataStore>();
  u.PPAttributes.Add(new PPAttribute{Name="SecondaryApplication",Value="255"});
  foreach(int a in new[]{47,48,95,96,126,128,135,137,255})u.Network.Applications.Add(new CBusApplication(u.Network){AddressAsInt=a,TagName="Owned"+a,bContinue=false});
  typeof(CBusBaseUnit).GetMethod("PopulateAllLists",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);
  foreach(int secondary in new[]{255,57,136}){
   u.SecondaryApplication.PPAttributeValue=secondary;
   Console.WriteLine("application-lists:"+secondary+":"+string.Join(",",u.PrimaryApplication.DataSource.Select(x=>x.ValueAsInt))+":"+string.Join(",",u.SecondaryApplication.DataSource.Select(x=>x.ValueAsInt)));
  }
  foreach(int primary in new[]{48,95,96,127,136}){
   u.PrimaryApplication.PPAttributeValue=primary;
   Console.WriteLine("application-set:"+primary+":"+u.PrimaryApplication.PPAttributeValue+":"+u.SecondaryApplication.PPAttributeValue+":"+string.Join(",",u.PrimSecApplication.Select(x=>x.ValueAsInt)));
  }
 }
}
