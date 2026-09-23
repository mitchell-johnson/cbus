using System;
using System.IO;
using System.Xml.Linq;
using System.Reflection;
using CBusLogicModel.Units;
using System.ComponentModel;
using System.Linq;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;

class NativeEdltDisplayProbe {
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
  if(args[2]!="keep")unit.LargeLabeltext=args[2]=="1";unit.UseBigIcon=int.Parse(args[3]);
  unit.EnableTimeFlash=int.Parse(args[4]);unit.EnableFanControlLevelWrap=int.Parse(args[5]);
  typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(unit,new object[]{true,false});
  string xml=File.ReadAllText(args[0]);unit.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
  typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(unit,null);
  foreach(var item in unit.PPAttributes)Console.WriteLine("pp:"+item.Name+"\t"+item.Value);
 }

 static EDLTUnit Unit(int font,int big,int flash,int wrap) {
  var u=(EDLTUnit)FormatterServices.GetUninitializedObject(typeof(EDLTUnit));
  u.PPAttributes=new BindingList<PPAttribute>();
  var names=new[]{"FontStyle","UseBigIcon","EnableTimerFlash","EnableFanControlLevelWrap","Untouched"};
  var values=new[]{font,big,flash,wrap,173};
  for(int i=0;i<names.Length;i++)u.PPAttributes.Add(new PPAttribute{Name=names[i],Value=values[i].ToString()});
  return u;
 }
 static void Dump(string label,EDLTUnit u) {
  Console.WriteLine(label+":"+string.Join(",",u.PPAttributes.Select(p=>p.Name+"="+p.Value))+
     ":label="+u.LargeLabeltext+":status="+u.LargeStatusText);
 }
 static void Main(string[] args) {
  if(args.Length==6){NativeFixture(args);return;}
  PPAttribute.bInitialiseMode=true;
  for(int font=0;font<8;font++) {
   Dump("get-"+font,Unit(font,1,1,1));
   foreach(bool value in new[]{false,true}) {
    var label=Unit(font,1,1,1);label.LargeLabeltext=value;Dump("label-"+font+"-"+value,label);
    var status=Unit(font,1,1,1);status.LargeStatusText=value;Dump("status-"+font+"-"+value,status);
   }
  }
  for(int font=1;font<=2;font++)for(int big=0;big<=1;big++)for(int flash=0;flash<=1;flash++)for(int wrap=0;wrap<=1;wrap++) {
   var unit=Unit(7,0,0,0);unit.LargeLabeltext=font==1;unit.UseBigIcon=big;
   unit.EnableTimeFlash=flash;unit.EnableFanControlLevelWrap=wrap;
   Dump("combination-"+font+big+flash+wrap,unit);
  }
 }
}
