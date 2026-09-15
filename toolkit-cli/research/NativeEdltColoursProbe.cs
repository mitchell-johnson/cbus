// Executes unchanged original setters, group bindings, save hook and CRC code.
using System;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using System.Reflection;
using System.ComponentModel;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.CBusObjects;
using CBusLogicModel.ProgramableProperties;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;
class NativeEdltColoursProbe {
 static readonly string[] Scalars={"ActiveBacklightBrightness","ActiveIndicatorBrightness","IdleBacklightBrightness","IdleIndicatorBrightness",
  "IndicatorOnColour","IndicatorOffColour","NavigationIndicatorColour","LCDForeground","LCDBackground"};
 static readonly string[] Groups={"BacklightActiveBrightnessControlGroup","BacklightIdleBrightnessControlGroup",
  "IndicatorActiveBrightnessControlGroup","IndicatorIdleBrightnessControlGroup","IndicatorOnColourControlGroup","IndicatorOffColourControlGroup"};
 static T Bare<T>(){return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static EDLTUnit Unit(){var u=Bare<EDLTUnit>();typeof(EDLTUnit).GetField("commonConstants",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(u,new CommonConstants());u.PPAttributes=new BindingList<PPAttribute>();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();u.StaticLabels=new BindingList<DataStore>();return u;}
 static void Attr(EDLTUnit u,string name,int value){u.PPAttributes.Add(new PPAttribute{Name=name,Value=value.ToString()});}
 static void Setup(EDLTUnit u) {
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();n.bContinue=false;CBusApplication.bAdd=false;u.Network=n;
  foreach(int a in new[]{56,57,202}) {
   var app=new CBusApplication(n){AddressAsInt=a,bContinue=false};n.Applications.Add(app);
   for(int g=0;g<255;g++){var group=new CBusGroup(app,"Synthetic"+g,g);app.Groups.Add(group);if(a==202&&!group.Levels.Any(x=>x.AddressAsInt==77))group.Levels.Add(new CBusLevel(group,"Synthetic77",77));foreach(var level in group.Levels)level.DynamicAll=new BindingList<DataStore>();}
  }
  foreach(var name in Groups) {
   var attribute=u.GetPPAttribute(name);
   var binding=new PPAttributeDataSourceLogic(n,attribute,attribute,true,255,new BindingListCBusObject<DataStore>(n,"Applications",u.GetPPAttribute("PrimaryApplication"),"Groups",null,null));
   typeof(EDLTUnit).GetProperty(name).SetValue(u,binding,null);
  }
 }
 static PPAttributeDataSourceLogic Binding(EDLTUnit u,string name){return (PPAttributeDataSourceLogic)typeof(EDLTUnit).GetProperty(name).GetValue(u,null);}
 static void Fixture(string[] args) {
  var u=Unit();foreach(var line in File.ReadAllLines(args[1])){int split=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});}
  Setup(u);
  for(int w=1;w<=21;w++)u.Widgets.Add(new EDLTWidget(u,w,u.PPAttributes));
  u.InitializeMRAGlobalValues();u.LoadScenes();
  foreach(var line in File.ReadAllLines(args[2])) {
   var row=line.Split('\t');string name=row[0];int value=int.Parse(row[1]);
   if(Groups.Contains(name))Binding(u,name).PPAttributeValue=value;
   else typeof(EDLTUnit).GetProperty(name).SetValue(u,value,null);
  }
  typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});
  string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
  typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);
  foreach(var item in u.PPAttributes)Console.WriteLine("pp:"+item.Name+"\t"+item.Value);
 }
 static void Main(string[] args) {
  PPAttribute.bInitialiseMode=true;if(args.Length==3){Fixture(args);return;}
  var u=Unit();foreach(string name in Scalars)Attr(u,name,0);foreach(string name in Groups)Attr(u,name,255);
  Attr(u,"PrimaryApplication",56);Attr(u,"ActivityDuration",0);Attr(u,"Untouched",173);
  var constants=new CommonConstants();
  foreach(var item in constants.KeyColours)Console.WriteLine("key:"+item.ValueAsInt+":"+item.FormattedDisplay);
  foreach(var item in constants.ScreenColours)Console.WriteLine("screen:"+item.ValueAsInt+":"+item.FormattedDisplay);
  foreach(var name in Scalars){var p=typeof(EDLTUnit).GetProperty(name);int limit=name.Contains("Brightness")?256:name.StartsWith("LCD")?8:9;
   for(int value=0;value<limit;value++){p.SetValue(u,value,null);Console.WriteLine("set:"+name+":"+value+":"+p.GetValue(u,null)+":"+u.GetPPAttribute(name).ValueAsInt+":"+u.GetPPAttribute("Untouched").ValueAsInt);}}
  Setup(u);
  foreach(var name in Groups)for(int value=0;value<256;value++) {
   var bind=Binding(u,name);bind.PPAttributeValue=value;
   Console.WriteLine("group:"+name+":"+value+":"+u.GetPPAttribute(name).ValueAsInt+":"+bind.IsEnabled+":"+bind.PPAttributeValue);
  }
  for(int value=0;value<256;value++){u.GetPPAttribute("ActivityDuration").ValueAsInt=value;Console.WriteLine("standby:"+value+":"+u.EnableStandByPage);}
  foreach(int value in new[]{0,254,255}) {
   foreach(string name in Groups)Binding(u,name).PPAttributeValue=value;
   Console.WriteLine("fixed:"+value+":"+u.EnableScreenBrightnessByFixedLevel+":"+u.IdleScreenBrightnessByFixedLevel+":"+u.EnableIndicatorBrightnessByFixedLevel+":"+u.IdleIndicatorBrightnessByFixedLevel+":"+u.EnableIndicatorOnColourByFixedColour+":"+u.EnableIndicatorOffColourByFixedColour);
  }
  foreach(string name in new[]{"IndicatorOnColour","IndicatorOffColour","NavigationIndicatorColour"})foreach(int value in new[]{9,254,255}) {
   typeof(EDLTUnit).GetProperty(name).SetValue(u,value,null);Console.WriteLine("stored:"+name+":"+value+":"+typeof(EDLTUnit).GetProperty(name).GetValue(u,null));
  }
  var primary=u.Network.Applications.Single(x=>x.AddressAsInt==56);primary.Groups.Remove(primary.Groups.Single(x=>x.AddressAsInt==99));
  foreach(string name in Groups) {
   var bind=Binding(u,name);bind.PPAttributeValue=99;
   Console.WriteLine("missing:"+name+":"+u.GetPPAttribute(name).ValueAsInt+":"+bind.IsEnabled+":"+bind.PPAttributeValue+":"+u.GetPPAttribute(name).ValueAsInt+":"+bind.IsEnabled);
  }
 }
}
