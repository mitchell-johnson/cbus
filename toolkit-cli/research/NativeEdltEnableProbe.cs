// Calls original EnableData constructors/properties on explicit PP scaffolds.
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
class NativeEdltEnableProbe {
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
 static EnableData Enable(EDLTUnit u) {
  var w=new EDLTWidget{Unit=u,Attributes=u.PPAttributes,WidgetNumber=6};var d=new EnableData(w,"Widget6",u.PPAttributes);w.WidgetData=d;u.Widgets.Add(w);return d;
 }
 static void Dump(string label,EnableData d) {
  var bytes=new byte[32];bytes[0]=14;for(int i=1;i<32;i++)bytes[i]=(byte)d.WidgetByte(i).ValueAsInt;
  Console.WriteLine(label+":"+BitConverter.ToString(bytes).Replace("-","")+":"+d.ParentWidget.RestoreLevel);
 }
 static void Main() {
  PPAttribute.bInitialiseMode=true;
  var u=Unit();var d=Enable(u);d.SetToDefault();Dump("default",d);
  d.GroupAddress=42;d.TargetLevel1=127;d.LabelDisplayType=3;d.LabelValueText="Enable name";d.StatusDisplayType=5;d.StatusValueText="Ready";
  Dump("preset-static",d);Console.WriteLine("static-refs:"+String.Join(",",d.GetUsedStaticText().OrderBy(x=>x)));
  d.LabelDisplayType=10;d.LabelValueIndex=1;d.StatusDisplayType=10;d.StatusValueIndex=3;Dump("dynamic-icons",d);
  d.LabelValueIndex=2;d.StatusValueIndex=0;Dump("dynamic-text",d);
  for(int i=1;i<32;i++)u.PPAttributes.Add(new PPAttribute{Name="Widget7WidgetByteValue"+i,Value=i==6?"43":"0"});
  u.PPAttributes.Add(new PPAttribute{Name="Widget7RestoreLevel",Value="137"});
  var w=new EDLTWidget{Unit=u,Attributes=u.PPAttributes,WidgetNumber=7};var light=new LightingData(w,"Widget7",u.PPAttributes);w.WidgetData=light;u.Widgets.Add(w);
  d.GroupAddress=43;Dump("group-refresh-and-cross-application-restore",d);
  d.ApplicationVariant=1;Console.WriteLine("fixed-application:"+d.SelectedApplication.AddressAsInt);Dump("retained-application-bit",d);
  d.TargetLevel1=0;d.SetForcedValues();Dump("zero-preset",d);
  d.TargetLevel1=255;Dump("maximum-preset",d);
  foreach(int status in new[]{1,2,3}){d.StatusDisplayType=status;Dump("status-"+status,d);}
  foreach(bool zero in new[]{false,true}){var other=Enable(Unit(true,zero));other.SetToDefault();Dump(zero?"opaque-blank-default":"opaque-default",other);}
 }
}
