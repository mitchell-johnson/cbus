// Calls original ShutterRelayData constructors/properties on explicit PP scaffolds.
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
class NativeEdltShutterProbe {
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
 static ShutterRelayData Shutter(EDLTUnit u) {
  var w=new EDLTWidget{Unit=u,Attributes=u.PPAttributes,WidgetNumber=6};var d=new ShutterRelayData(w,"Widget6",u.PPAttributes);w.WidgetData=d;u.Widgets.Add(w);return d;
 }
 static void Dump(string label,ShutterRelayData d) {
  var bytes=new byte[32];bytes[0]=3;for(int i=1;i<32;i++)bytes[i]=(byte)d.WidgetByte(i).ValueAsInt;
  Console.WriteLine(label+":"+BitConverter.ToString(bytes).Replace("-","")+":"+d.ParentWidget.RestoreLevel);
 }
 static void Main() {
  PPAttribute.bInitialiseMode=true;
  var u=Unit();var d=Shutter(u);d.SetToDefault();Dump("default",d);
  Console.WriteLine("defaults-text:"+d.LabelValueText+":"+d.LabelValueIndex);
  d.GroupAddress=42;Dump("bound-default",d);d.ApplicationVariant=1;d.LeftButtonMacrofunction=1;d.TargetLevel1=6;d.TargetLevel2=248;
  Dump("presets-boundaries",d);
  d.TargetLevel1=0;d.TargetLevel2=255;Dump("clamped-boundaries",d);
  d.LabelValueText="Shade";d.StatusDisplayType=5;d.StatusValueText="Ready";Dump("custom-static",d);
  Console.WriteLine("static-text:"+d.LabelValueText+":"+d.LabelValueIndex+":"+d.StatusValueText+":"+d.StatusValueIndex);
  d.LeftButtonMacrofunction=0;Dump("two-key-preserves-presets",d);
  d.LabelDisplayType=10;d.LabelValueIndex=1;d.StatusDisplayType=10;d.StatusValueIndex=3;Dump("dynamic-icons",d);
  d.LabelValueIndex=2;d.StatusValueIndex=0;Dump("dynamic-text",d);
  d.SelectedGroup.DynamicAll[2].Image=Bare<Bitmap>();d.SelectedGroup.DynamicAll[0].Image=Bare<Bitmap>();
  d.LabelValueIndex=2;d.StatusValueIndex=0;Dump("same-index-refresh",d);
  for(int i=1;i<32;i++)u.PPAttributes.Add(new PPAttribute{Name="Widget7WidgetByteValue"+i,Value=i==6?"43":"0"});
  u.PPAttributes.Add(new PPAttribute{Name="Widget7RestoreLevel",Value="137"});
  var w=new EDLTWidget{Unit=u,Attributes=u.PPAttributes,WidgetNumber=7};var light=new LightingData(w,"Widget7",u.PPAttributes);w.WidgetData=light;u.Widgets.Add(w);
  d.GroupAddress=43;Dump("group-refresh",d);
  foreach(int status in new[]{1,2,3}){d.StatusDisplayType=status;Dump("status-"+status,d);}
  var existing=Unit();existing.GetPPAttribute("StaticTextString5").ValueAsUtf8String="Blind";existing.StaticLabels[5].Name="Blind";
  var reused=Shutter(existing);reused.SetToDefault();reused.GroupAddress=42;Dump("existing-blind-default",reused);
  reused.ApplicationVariant=1;reused.LeftButtonMacrofunction=1;reused.TargetLevel1=6;reused.TargetLevel2=248;Dump("existing-blind-presets",reused);
  reused.LabelValueText="Shade";reused.StatusDisplayType=5;reused.StatusValueText="Ready";Dump("existing-blind-custom",reused);
  reused.LeftButtonMacrofunction=0;Dump("existing-blind-two-key",reused);
  foreach(bool zero in new[]{false,true}){var other=Shutter(Unit(true,zero));other.SetToDefault();Dump(zero?"opaque-blank-default":"opaque-default",other);}
 }
}
