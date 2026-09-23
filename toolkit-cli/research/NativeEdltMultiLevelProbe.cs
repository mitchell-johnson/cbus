// Calls original MultiLevelData constructors/properties on explicit PP scaffolds.
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
class NativeEdltMultiLevelProbe {
 static T Bare<T>() {return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static EDLTUnit Unit(bool opaque=false,bool zeroControl=false) {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();u.PPAttributes.Add(new PPAttribute{Name="Widget6WidgetType",Value="16"});u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();
  for(int i=1;i<32;i++)u.PPAttributes.Add(new PPAttribute{Name="Widget6WidgetByteValue"+i,Value="0x"+(opaque?i:0).ToString("X")});
  if(opaque){u.GetPPAttribute("Widget6WidgetByteValue1").ValueAsInt=zeroControl?0:255;u.GetPPAttribute("Widget6WidgetByteValue7").ValueAsInt=23;}
  foreach(var pair in new string[][]{new[]{"Widget6RestoreLevel","153"},new[]{"PrimaryApplication","56"},new[]{"SecondaryApplication","57"},new[]{"NavWidgetVariant","0"}})u.PPAttributes.Add(new PPAttribute{Name=pair[0],Value=pair[1]});
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();u.Network=n;
  foreach(int addr in new[]{48,56,57,95,96,127,136,203}) {
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
 static MultiLevelData Level(EDLTUnit u) {
  var w=new EDLTWidget{Unit=u,Attributes=u.PPAttributes,WidgetNumber=6};var d=new MultiLevelData(w,"Widget6",u.PPAttributes);w.WidgetData=d;u.Widgets.Add(w);return d;
 }
 static void Dump(string label,MultiLevelData d) {
  var bytes=new byte[32];bytes[0]=(byte)d.ParentWidget.WidgetType;for(int i=1;i<32;i++)bytes[i]=(byte)d.WidgetByte(i).ValueAsInt;
  Console.WriteLine(label+":"+BitConverter.ToString(bytes).Replace("-","")+":"+d.ParentWidget.RestoreLevel);
 }
 static void Texts(EDLTUnit u) {Console.WriteLine("texts:"+string.Join("|",u.StaticLabels.Where(x=>x.Name!="").Select(x=>x.ValueAsInt+"="+x.Name)));}
 static void Main() {
  PPAttribute.bInitialiseMode=true;
  var u=Unit();var d=Level(u);d.SetToDefault();Dump("default",d);Texts(u);
  d.GroupAddress=42;Dump("bound-default",d);d.ApplicationVariant=1;
  d.IsOneSpeed=true;Dump("one-speed",d);
  d.IsTwoSpeed=true;Dump("two-speed",d);
  d.LowMedThreshold=254;d.MedHighThreshold=254;Dump("two-boundary",d);
  d.IsThreeSpeed=true;Dump("three-speed",d);
  d.LowMedThreshold=1;d.MedHighThreshold=2;Dump("three-min",d);
  d.LowMedThreshold=253;d.MedHighThreshold=254;Dump("three-max",d);
  d.IsThreeSpeed=true;Dump("three-reset",d);
  d.LabelDisplayType=3;d.LabelValueText="Ceiling";d.StatusValueText="Stopped";d.LowStatusText="Slow";d.MedStatusText="Normal";d.HighStatusText="Fast";Dump("custom-static",d);Texts(u);
  d.LabelDisplayType=10;d.LabelValueIndex=1;Dump("dynamic-icon",d);
  d.LabelValueIndex=2;Dump("dynamic-text",d);
  d.SelectedGroup.DynamicAll[2].Image=Bare<Bitmap>();d.LabelValueIndex=2;Dump("same-index-refresh",d);
  d.StatusDisplayType=0;d.StatusValueIndex=63;d.SetForcedValues();Dump("forced-static-status",d);Console.WriteLine("off-edit-before-forcing:"+d.StatusValueIndex);
  for(int i=1;i<32;i++)u.PPAttributes.Add(new PPAttribute{Name="Widget7WidgetByteValue"+i,Value=i==6?"43":"0"});
  u.PPAttributes.Add(new PPAttribute{Name="Widget7WidgetType",Value="2"});
  u.PPAttributes.Add(new PPAttribute{Name="Widget7RestoreLevel",Value="137"});
  var w=new EDLTWidget{Unit=u,Attributes=u.PPAttributes,WidgetNumber=7};var light=new LightingData(w,"Widget7",u.PPAttributes);w.WidgetData=light;u.Widgets.Add(w);
  d.GroupAddress=43;Dump("group-refresh",d);
  var nu=Unit();
  foreach(var pair in new[]{new[]{"2","Fan"},new[]{"12","Off"},new[]{"13","Low"},new[]{"14","Medium"},new[]{"15","High"}}) {
   int i=int.Parse(pair[0]);nu.GetPPAttribute("StaticTextString"+i).ValueAsUtf8String=pair[1];nu.StaticLabels[i].Name=pair[1];
  }
  var nd=Level(nu);nd.SetToDefault();nd.GroupAddress=42;Dump("native-default",nd);Texts(nu);
  nd.ApplicationVariant=1;nd.IsOneSpeed=true;Dump("native-one",nd);
  nd.IsTwoSpeed=true;nd.LowMedThreshold=254;nd.MedHighThreshold=254;Dump("native-two",nd);
  nd.IsThreeSpeed=true;nd.LowMedThreshold=253;nd.MedHighThreshold=254;Dump("native-three",nd);
  nd.LabelDisplayType=3;nd.LabelValueText="Ceiling";nd.StatusValueText="Stopped";nd.LowStatusText="Slow";nd.MedStatusText="Normal";nd.HighStatusText="Fast";Dump("native-custom",nd);Texts(nu);
  foreach(var pair in new[]{new[]{"50","Off"},new[]{"51","Low"},new[]{"52","Medium"},new[]{"53","High"}}) {
   int i=int.Parse(pair[0]);nu.GetPPAttribute("StaticTextString"+i).ValueAsUtf8String=pair[1];nu.StaticLabels[i].Name=pair[1];
  }
  nd.StatusValueIndex=50;nd.LowStatusTextIndex=51;nd.MedStatusTextIndex=52;nd.HighStatusTextIndex=53;Dump("native-explicit-indexes",nd);
  nd.StatusValueText="Off";nd.LowStatusText="Low";nd.MedStatusText="Medium";nd.HighStatusText="High";Dump("native-first-text-match",nd);
  nd.StatusValueIndex=0;nd.LowStatusTextIndex=63;nd.MedStatusTextIndex=0;nd.HighStatusTextIndex=63;Dump("native-index-boundaries",nd);
  nd.StatusValueText="Stopped";nd.LowStatusText="Slow";nd.MedStatusText="Normal";nd.HighStatusText="Fast";
  nd.LabelDisplayType=10;nd.LabelValueIndex=2;Dump("native-dynamic-text",nd);
  nd.SelectedGroup.DynamicAll[2].Image=Bare<Bitmap>();nd.LabelValueIndex=2;Dump("native-same-index",nd);
  nd.StatusDisplayType=0;nd.SetForcedValues();Dump("native-force-static",nd);
  nd.IsOneSpeed=true;Console.WriteLine("hidden-used-static:"+string.Join(",",nd.GetUsedStaticText().OrderBy(x=>x)));
  foreach(int app in new[]{48,95,96,127,136}) {
   var au=Unit();au.GetPPAttribute("PrimaryApplication").ValueAsInt=app;
   var ad=Level(au);ad.SetToDefault();ad.GroupAddress=42;
   Dump("application-"+app,ad);Console.WriteLine("selected-app:"+app+":"+ad.GetSelectedApplication().AddressAsInt);
  }
  foreach(bool zero in new[]{false,true}){var other=Level(Unit(true,zero));other.SetToDefault();Dump(zero?"opaque-blank-default":"opaque-default",other);}
 }
}
