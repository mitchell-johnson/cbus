using System;
using System.IO;
using System.Xml.Linq;
using System.Reflection;
using System.ComponentModel;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.Units;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;

class NativeEdltGeneralProbe {
 static EDLTUnit Unit() {
  var unit=(EDLTUnit)FormatterServices.GetUninitializedObject(typeof(EDLTUnit));
  typeof(EDLTUnit).GetField("commonConstants",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(unit,new CommonConstants());
  unit.PPAttributes=new BindingList<PPAttribute>(); unit.Widgets=new BindingList<EDLTWidget>();
  unit.Scenes=new BindingList<EDLTScene>(); unit.StaticLabels=new BindingList<DataStore>();
  return unit;
 }
 static void Main(string[] args) {
  PPAttribute.bInitialiseMode=true;
  var unit=Unit();
  if(args.Length==7) {
   foreach(var line in File.ReadAllLines(args[1])) {
    var split=line.IndexOf('\t'); unit.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});
   }
   for(int n=1;n<=21;n++)unit.Widgets.Add(new EDLTWidget(unit,n,unit.PPAttributes));
   unit.InitializeMRAGlobalValues();
   if(args[2]!="keep")unit.LongPressTime=int.Parse(args[2]);
   if(args[3]!="keep")unit.DebounceTime=int.Parse(args[3]);
   if(args[4]!="keep")unit.StatusRequestInterval=int.Parse(args[4]);
   if(args[5]!="keep")unit.ToolsPageLocked=int.Parse(args[5]);
   if(args[6]!="keep")unit.EnableLevelStore=args[6]=="1";
   typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(unit,new object[]{true,false});
   string xml=File.ReadAllText(args[0]);unit.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
   typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(unit,null);
   foreach(var item in unit.PPAttributes)Console.WriteLine("pp:"+item.Name+"\t"+item.Value);
   return;
  }
  var constants=new CommonConstants();
  foreach(var value in constants.LongPress)Console.WriteLine("long-list:"+value.ValueAsInt+":"+value.FormattedDisplay);
  foreach(var value in constants.DebounceTime)Console.WriteLine("debounce-list:"+value.ValueAsInt+":"+value.FormattedDisplay);
  foreach(var name in new[]{"LongPressTime","DebounceTime","StatusRequestInterval","ToolsPageLocked","EnableLevelStore","Untouched"})
   unit.PPAttributes.Add(new PPAttribute{Name=name,Value="0"});
  unit.GetPPAttribute("Untouched").ValueAsInt=173;
  for(int n=0;n<256;n++) {
   unit.LongPressTime=n;unit.DebounceTime=n;unit.StatusRequestInterval=n;
   Console.WriteLine("scalars:"+n+":"+unit.LongPressTime+":"+unit.DebounceTime+":"+unit.StatusRequestInterval+":"+unit.GetPPAttribute("Untouched").ValueAsInt);
  }
  foreach(bool value in new[]{false,true}) {
   unit.EnableLevelStore=value;
   Console.WriteLine("enable:"+value+":"+unit.GetPPAttribute("EnableLevelStore").ValueAsInt+":"+unit.EnableLevelStore+":"+unit.DisableLevelStore);
   unit.DisableLevelStore=value;
   Console.WriteLine("disable:"+value+":"+unit.GetPPAttribute("EnableLevelStore").ValueAsInt+":"+unit.EnableLevelStore+":"+unit.DisableLevelStore);
   unit.ToolsPageLocked=value?1:0;Console.WriteLine("locked:"+value+":"+unit.ToolsPageLocked);
  }
 }
}
