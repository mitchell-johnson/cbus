// Execute original Toolkit1.18 .NET methods against an explicit PP scaffold.
// No device I/O, assembly patching or reconstructed CRC implementation.
using System;
using System.IO;
using System.Xml.Linq;
using CBusLogicModel.Units;
using System.ComponentModel;
using System.Reflection;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units.EDLT.WidgetData;
using CBusLogicModel.Units.EDLT.WidgetData.BaseObjects;
class NativeEdltProbe {
 static void Dump(string label,LightingData data,EDLTWidget widget) {
  byte[] record=new byte[32];record[0]=2;
  for(int i=1;i<32;i++)record[i]=(byte)data.WidgetByte(i).ValueAsInt;
  Console.WriteLine(label+":"+BitConverter.ToString(record).Replace("-","")+":"+widget.RestoreLevel);
 }
 static void Main(string[] args) {
  PPAttribute.bInitialiseMode=true;
  foreach(var input in new byte[][] {new byte[0],new byte[]{0,1,2,255},System.Text.Encoding.ASCII.GetBytes("123456789")})
   Console.WriteLine("crc-vector:"+BitConverter.ToString(input).Replace("-","")+":"+Crc16Ccitt.checkCrc16(input,0,input.Length).ToString("X4"));
  if(args.Length==2) {
   var pp=new BindingList<PPAttribute>();
   foreach(var line in File.ReadAllLines(args[1])) {var split=line.IndexOf('\t');pp.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});}
   var target=(EDLTUnit)FormatterServices.GetUninitializedObject(typeof(EDLTUnit));
   target.PPAttributes=pp;
   var xml=File.ReadAllText(args[0]);target.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
   typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.NonPublic|BindingFlags.Instance).Invoke(target,null);
   foreach(var item in pp) if(item.Name.EndsWith("CRC")||item.Name=="ScenesCheckSum")Console.WriteLine("pp-crc:"+item.Name+":"+item.Value);
  }
  var attrs=new BindingList<PPAttribute>();
  for(int i=1;i<32;i++)attrs.Add(new PPAttribute{Name="Widget6WidgetByteValue"+i,Value="0"});
  attrs.Add(new PPAttribute{Name="Widget6RestoreLevel",Value="0"});
  var unit=(EDLTUnit)FormatterServices.GetUninitializedObject(typeof(EDLTUnit));
  unit.Widgets=new BindingList<EDLTWidget>();unit.PPAttributes=attrs;
  var widget=new EDLTWidget {Unit=unit,Attributes=attrs,WidgetNumber=6};
  var data=(LightingData)FormatterServices.GetUninitializedObject(typeof(LightingData));
  data.ParentWidget=widget;widget.WidgetData=data;
  typeof(WidgetBaseData).GetField("WidgetPrefix",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(data,"Widget6");
  foreach(var f in new[]{"_rampRateEditable","_targetLevel1Editable","_targetLevel2Editable","_offsetEditable"})
   typeof(AppGroupButtonFunctionsData).GetField(f,BindingFlags.NonPublic|BindingFlags.Instance).SetValue(data,true);
  data.SetToDefault();Dump("default",data,widget);
  data.GroupAddress=42;data.ApplicationVariant=1;data.DualButtonMacrofunction="10|9";data.LabelDisplayType=3;data.LabelValueIndex=1;data.StatusDisplayType=2;
  Dump("off-on-secondary-static",data,widget);
  data.DualButtonMacrofunction="15|16";data.RampRate=4;data.TargetLevel1=127;data.TargetLevel2=200;data.Offset=31;
  Dump("dimmer-secondary-static",data,widget);
 }
}
