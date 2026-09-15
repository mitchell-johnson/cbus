// Calls original TimerData constructors/properties on explicit PP scaffolds.
using System;
using System.Linq;
using System.Drawing;
using System.ComponentModel;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.CBusObjects;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units.EDLT.WidgetData;
using CBusLogicModel.EDLT.WidgetData;
class NativeEdltTimerProbe {
 static T Bare<T>() {return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static EDLTUnit Unit(bool opaque=false,bool zeroControl=false) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();
  for(int i=1;i<32;i++)u.PPAttributes.Add(new PPAttribute{Name="Widget6WidgetByteValue"+i,Value="0x"+(opaque?i:0).ToString("X")});
  if(opaque){u.GetPPAttribute("Widget6WidgetByteValue1").ValueAsInt=zeroControl?0:255;u.GetPPAttribute("Widget6WidgetByteValue7").ValueAsInt=23;}
  foreach(var pair in new string[][]{new[]{"Widget6RestoreLevel","153"},new[]{"PrimaryApplication","56"},new[]{"SecondaryApplication","57"},new[]{"NavWidgetVariant","0"}})u.PPAttributes.Add(new PPAttribute{Name=pair[0],Value=pair[1]});
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();u.Network=n;
  foreach(int addr in new[]{56,57,203}) {
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
 static TimerData Timer(EDLTUnit u) {
  var w=new EDLTWidget{Unit=u,Attributes=u.PPAttributes,WidgetNumber=6};var d=new TimerData(w,"Widget6",u.PPAttributes);w.WidgetData=d;u.Widgets.Add(w);return d;
 }
 static void Dump(string label,TimerData d) {
  var bytes=new byte[32];bytes[0]=5;for(int i=1;i<32;i++)bytes[i]=(byte)d.WidgetByte(i).ValueAsInt;
  Console.WriteLine(label+":"+BitConverter.ToString(bytes).Replace("-","")+":"+d.ParentWidget.RestoreLevel);
 }
 static void Main() {
  PPAttribute.bInitialiseMode=true;
  var u=Unit();var d=Timer(u);d.SetToDefault();Dump("default",d);
  Console.WriteLine("default-values:"+d.TimerValue+":"+d.TargetLevel+":"+d.ExpiryLevel+":"+d.RampRate+":"+d.LabelValueIndex);
  d.GroupAddress=42;Dump("bound-default",d);d.ApplicationVariant=1;
  d.TimerValue=64800;d.TargetLevel=1;d.ExpiryLevel=255;d.RampRate=0;Dump("maximum-duration",d);
  Console.WriteLine("maximum-duration-readback:"+d.TimerValue+":"+d.TargetLevel+":"+d.ExpiryLevel+":"+d.RampRate);
  d.TimerValue=0;d.TargetLevel=255;d.ExpiryLevel=0;d.RampRate=15;Dump("zero-duration",d);
  d.TargetLevel=0;d.SetForcedValues();Dump("forced-target-one",d);
  d.TargetLevel=127;d.TimerValue=300;d.ExpiryLevel=100;d.RampRate=4;
  d.LabelValueText="Timer";d.StatusDisplayType=5;d.StatusValueText="Ready";Dump("custom-static",d);
  d.LabelDisplayType=10;d.LabelValueIndex=1;d.StatusDisplayType=10;d.StatusValueIndex=3;Dump("dynamic-icons",d);
  d.LabelValueIndex=2;d.StatusValueIndex=0;Dump("dynamic-text",d);
  d.SelectedGroup.DynamicAll[2].Image=Bare<Bitmap>();d.SelectedGroup.DynamicAll[0].Image=Bare<Bitmap>();
  d.LabelValueIndex=2;d.StatusValueIndex=0;Dump("same-index-refresh",d);
  for(int i=1;i<32;i++)u.PPAttributes.Add(new PPAttribute{Name="Widget7WidgetByteValue"+i,Value=i==6?"43":"0"});
  u.PPAttributes.Add(new PPAttribute{Name="Widget7RestoreLevel",Value="137"});
  var w=new EDLTWidget{Unit=u,Attributes=u.PPAttributes,WidgetNumber=7};var light=new LightingData(w,"Widget7",u.PPAttributes);w.WidgetData=light;u.Widgets.Add(w);
  d.GroupAddress=43;Dump("group-refresh",d);
  d.LabelDisplayType=0;d.StatusDisplayType=4;Dump("timer-status-blank-label",d);
  d.StatusDisplayType=0;Dump("blank-status",d);
  var existing=Unit();existing.GetPPAttribute("StaticTextString2").ValueAsUtf8String="Fan";existing.StaticLabels[2].Name="Fan";
  var reused=Timer(existing);reused.SetToDefault();reused.GroupAddress=42;Dump("existing-fan-default",reused);
  reused.ApplicationVariant=1;reused.TimerValue=64800;reused.TargetLevel=1;reused.ExpiryLevel=255;reused.RampRate=0;Dump("existing-fan-maximum",reused);
  reused.TimerValue=0;reused.TargetLevel=255;reused.ExpiryLevel=0;reused.RampRate=15;Dump("existing-fan-zero",reused);
  reused.TargetLevel=0;reused.SetForcedValues();Dump("existing-fan-forced",reused);
  reused.ApplicationVariant=1;reused.TargetLevel=127;reused.TimerValue=300;reused.ExpiryLevel=100;reused.RampRate=4;
  reused.LabelValueText="Timer";reused.StatusDisplayType=5;reused.StatusValueText="Ready";Dump("existing-fan-custom",reused);
  foreach(bool zero in new[]{false,true}){var other=Timer(Unit(true,zero));other.SetToDefault();Dump(zero?"opaque-blank-default":"opaque-default",other);}
  var signed=Timer(Unit());signed.ExpiryLevel=-1;Console.WriteLine("unsupported-signed-expiry:"+signed.ExpiryLevel+":"+signed.WidgetByte(14).ValueAsInt+":"+signed.WidgetByte(15).ValueAsInt);
 }
}
