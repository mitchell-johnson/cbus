// Calls original RCPData constructors/properties on explicit PP scaffolds.
using System;
using System.Linq;
using System.Drawing;
using System.Globalization;
using System.ComponentModel;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.CBusObjects;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units.EDLT.WidgetData;
using CBusLogicModel.EDLT.WidgetData;
class NativeEdltMeasurementProbe {
 static T Bare<T>() {return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static EDLTUnit Unit(bool opaque=false,bool zeroControl=false) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();
  for(int i=1;i<32;i++)u.PPAttributes.Add(new PPAttribute{Name="Widget6WidgetByteValue"+i,Value="0x"+(opaque?i:0).ToString("X")});
  if(opaque){u.GetPPAttribute("Widget6WidgetByteValue1").ValueAsInt=zeroControl?0:255;u.GetPPAttribute("Widget6WidgetByteValue7").ValueAsInt=23;}
  foreach(var pair in new string[][]{new[]{"Widget6RestoreLevel","153"},new[]{"PrimaryApplication","56"},new[]{"SecondaryApplication","57"},new[]{"NavWidgetVariant","0"}})u.PPAttributes.Add(new PPAttribute{Name=pair[0],Value=pair[1]});
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();u.Network=n;
  foreach(int addr in new[]{56,57,127,136,203}) {
   var app=new CBusApplication(n){AddressAsInt=addr};n.Applications.Add(app);
   foreach(int number in new[]{42,43}) {
    var g=new CBusGroup(app,"Synthetic"+number,number);app.Groups.Add(g);g.DynamicAll=new BindingList<DataStore>();
    for(int variant=0;variant<4;variant++)g.DynamicAll.Add(new DataStore("Variant"+variant,variant){Image=((variant+(number==43?1:0))%2==1)?Bare<Bitmap>():null});
   }
  }
  u.StaticLabels=new BindingList<DataStore>();u.StaticTextSuggest=new BindingList<DataStore>();
  for(int i=0;i<64;i++){var p=new PPAttribute{Name="StaticTextString"+i};p.ValueAsUtf8String=i==1?"Lamp":"";u.PPAttributes.Add(p);u.StaticLabels.Add(new DataStore(p.ValueAsUtf8String,i));}
  var page=Bare<EDLTPageWidget>();page.Unit=u;page.Attributes=u.PPAttributes;page.WidgetNumber=0;page.WidgetData=new PageWidgetData(page,"NavWidget",u.PPAttributes);u.PageWidget=page;
  return u;
 }
 static MeasurementData Measurement(EDLTUnit u) {
  var w=new EDLTWidget{Unit=u,Attributes=u.PPAttributes,WidgetNumber=6};var d=new MeasurementData(w,"Widget6",u.PPAttributes);w.WidgetData=d;u.Widgets.Add(w);return d;
 }
 static void Dump(string label,MeasurementData d) {
  var bytes=new byte[32];bytes[0]=12;for(int i=1;i<32;i++)bytes[i]=(byte)d.WidgetByte(i).ValueAsInt;
  Console.WriteLine(label+":"+BitConverter.ToString(bytes).Replace("-","")+":"+d.ParentWidget.RestoreLevel);
 }
 static void AddReferences(EDLTUnit u,int count) {
  int reference=0;
  for(int number=7;number<=21;number++) {
   for(int index=1;index<32;index++)u.PPAttributes.Add(new PPAttribute{Name="Widget"+number+"WidgetByteValue"+index,Value="0"});
   u.PPAttributes.Add(new PPAttribute{Name="Widget"+number+"RestoreLevel",Value="0"});
   u.GetPPAttribute("Widget"+number+"WidgetByteValue1").ValueAsInt=0x35;
   for(int index=9;index<=13;index++)u.GetPPAttribute("Widget"+number+"WidgetByteValue"+index).ValueAsInt=Math.Min(reference++,count-1);
   var w=new EDLTWidget{Unit=u,Attributes=u.PPAttributes,WidgetNumber=number};w.WidgetData=new MultiLevelData(w,"Widget"+number,u.PPAttributes);u.Widgets.Add(w);
  }
 }
 static void Main() {
  CultureInfo.CurrentCulture=CultureInfo.InvariantCulture;PPAttribute.bInitialiseMode=true;
  var u=Unit();var d=Measurement(u);d.SetToDefault();Dump("default",d);
  Console.WriteLine("default-text-getters:"+d.PrefixText+"|"+d.SuffixText+"|"+d.FunctionStatusText);
  Console.WriteLine("default-used:"+string.Join(",",u.GetUsedStaticText().OrderBy(x=>x)));
  d.SetForcedValues();Dump("no-forcing",d);
  d.DeviceID=254;d.Channel=254;d.Precision=5;Dump("ui-maximum",d);
  d.DeviceID=42;d.Channel=3;d.Precision=1;d.GainComposite="1.25";d.OffsetComposite="-2.5";Dump("scaled",d);
  Console.WriteLine("scaled-getters:"+d.GainComposite+":"+d.OffsetComposite);
  d.PrefixText="Temperature";Dump("prefix-allocation",d);d.SuffixText="C";Dump("suffix-allocation",d);d.FunctionStatusText="Room";Dump("label-allocation",d);
  d.PrefixText="Shared";d.SuffixText="Shared";d.FunctionStatusText="Shared";Dump("shared-text",d);
  d.PrefixText="";d.SuffixText="";d.FunctionStatusText="";Dump("empty-text",d);
  Console.WriteLine("empty-used:"+string.Join(",",u.GetUsedStaticText().OrderBy(x=>x)));
  d.FunctionStatusTextIndex=64;Console.WriteLine("sentinel64-getter:"+d.FunctionStatusText);d.PrefixText="After64";Dump("allocate-with64",d);
  d.PrefixTextIndex=50;d.SuffixTextIndex=51;d.FunctionStatusTextIndex=52;Dump("exact-indexes",d);
  foreach(string value in new[]{"0","-1","0.125","32767","-32768","32768","-32769","123456","0.00001","1000000","1.23456"}) {
   d.GainComposite=value;d.OffsetComposite=value;Dump("number-"+value,d);Console.WriteLine("number-readback:"+value+":"+d.GainComposite+":"+d.OffsetComposite);
  }
  foreach(string value in new[]{"0.29","1.15","0.07","0.58","-0.29","1.000000000000001","1e-20","1e-50","1e-51"}) {
   double number=double.Parse(value);double normal;int integer,exponent;bool exact=PPHelper.BreakNumberIntoIntegerAndExponent(number,out normal,out integer,out exponent);
   Console.WriteLine("break:"+value+":"+PPHelper.FormatDoubleWithoutE(number)+":"+exact+":"+integer+":"+exponent+":"+PPHelper.FormatDoubleWithoutE(normal));
   d.GainComposite=value;Dump("extra-number-"+value,d);Console.WriteLine("extra-readback:"+value+":"+d.GainComposite);
  }
  d.Gain=-32768;d.GainExponent=-128;d.Offset=32767;d.OffsetExponent=127;Dump("raw-signed-extremes",d);
  Console.WriteLine("raw-signed-readback:"+d.Gain+":"+d.GainExponent+":"+d.Offset+":"+d.OffsetExponent);
  d.Gain=32767;d.GainExponent=127;d.Offset=-32768;d.OffsetExponent=-128;Dump("raw-signed-opposite",d);
  Console.WriteLine("raw-signed-opposite-readback:"+d.Gain+":"+d.GainExponent+":"+d.Offset+":"+d.OffsetExponent);
  d.Gain=0;Dump("raw-zero-gain-setter",d);
  d.WidgetByte(4).ValueAsInt=0;d.WidgetByte(5).ValueAsInt=0;Dump("zero-gain-before-getter",d);Console.WriteLine("gain-readback:"+d.Gain);Dump("zero-gain-after-getter",d);
  foreach(bool zero in new[]{false,true}){var other=Measurement(Unit(true,zero));other.SetToDefault();Dump(zero?"opaque-zero":"opaque",other);}
  var nu=Unit();nu.GetPPAttribute("StaticTextString18").ValueAsUtf8String="Temperature";nu.StaticLabels[18].Name="Temperature";
  var nd=Measurement(nu);nd.SetToDefault();nd.DeviceID=42;nd.Channel=3;nd.Precision=1;nd.GainComposite="1.25";nd.OffsetComposite="-2.5";
  nd.PrefixText="Temperature";Dump("native-prefix",nd);nd.SuffixText="C";Dump("native-suffix",nd);nd.FunctionStatusText="Room";Dump("native-label",nd);
  nd.PrefixText="Shared";nd.SuffixText="Shared";nd.FunctionStatusText="Shared";Dump("native-shared",nd);
  foreach(int count in new[]{61,62}) {
   var otherUnit=Unit();var other=Measurement(otherUnit);other.SetToDefault();AddReferences(otherUnit,count);
   Console.WriteLine("capacity-before:"+count+":"+otherUnit.GetUsedStaticText().Count);
   try{other.PrefixText="NewAtCapacity";Console.WriteLine("capacity-allocation:"+count+":"+other.PrefixTextIndex);}catch(Exception e){Console.WriteLine("capacity-error:"+count+":"+e.Message);}
   other.FunctionStatusText="";Console.WriteLine("capacity-after-empty:"+count+":"+otherUnit.GetUsedStaticText().Count);
   try{other.SuffixText="AfterDetach";Console.WriteLine("capacity-detached-allocation:"+count+":"+other.SuffixTextIndex);}catch(Exception e){Console.WriteLine("capacity-detached-error:"+count+":"+e.Message);}
  }
 }
}
