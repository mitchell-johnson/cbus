// Calls unchanged Toolkit .NET allocation and reference methods on explicit fixtures.
using System;
using System.Linq;
using System.ComponentModel;
using System.Reflection;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units.EDLT.WidgetData;
using CBusLogicModel.Units.EDLT.WidgetData.BaseObjects;
class NativeEdltStaticProbe {
 static T Bare<T>() {return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static void Main() {
  PPAttribute.bInitialiseMode=true;
  var attrs=new BindingList<PPAttribute>();
  for(int i=1;i<32;i++)attrs.Add(new PPAttribute{Name="Widget6WidgetByteValue"+i,Value="0x0"});
  attrs.Add(new PPAttribute{Name="NavWidgetVariant",Value="0x6"});
  for(int i=1;i<=4;i++)attrs.Add(new PPAttribute{Name="PageNameIndex"+i,Value="0x"+(61-i).ToString("x")});
  var unit=Bare<EDLTUnit>();unit.PPAttributes=attrs;unit.Widgets=new BindingList<EDLTWidget>();
  unit.StaticLabels=new BindingList<DataStore>();unit.StaticTextSuggest=new BindingList<DataStore>();
  for(int i=0;i<64;i++) {
   var pp=new PPAttribute{Name="StaticTextString"+i};pp.ValueAsUtf8String=i==1?"Lamp":"old"+i;
   attrs.Add(pp);unit.StaticLabels.Add(new DataStore(pp.ValueAsUtf8String,i));
  }
  unit.Scenes=new BindingList<EDLTScene>();
  unit.Scenes.Add(new EDLTScene(unit,0,true,255,0,61,0));
  var widget=new EDLTWidget{Unit=unit,Attributes=attrs,WidgetNumber=6};
  var data=Bare<LightingData>();data.ParentWidget=widget;widget.WidgetData=data;unit.Widgets.Add(widget);
  typeof(WidgetBaseData).GetField("WidgetPrefix",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(data,"Widget6");
  data.WidgetByte(1).ValueAsInt=0x35;data.WidgetByte(13).ValueAsInt=63;data.WidgetByte(14).ValueAsInt=62;
  var page=Bare<EDLTPageWidget>();page.Unit=unit;page.Attributes=attrs;page.WidgetNumber=0;var pd=Bare<PageWidgetData>();pd.ParentWidget=page;page.WidgetData=pd;unit.PageWidget=page;
  Console.WriteLine("used:"+String.Join(",",unit.GetUsedStaticText().OrderBy(x=>x)));
  Console.WriteLine("existing:"+unit.GetStaticTextIndex("Lamp"));
  Console.WriteLine("blank:"+unit.GetStaticTextIndex("   "));
  int added=unit.GetStaticTextIndex("Māori");Console.WriteLine("allocated:"+added+":"+unit.GetPPAttribute("StaticTextString"+added).Value);
  Console.WriteLine("same:"+unit.GetStaticTextIndex("Māori"));
  int replaced=unit.GetStaticTextIndex("Second");Console.WriteLine("unreferenced-slot-reused:"+replaced);
  data.WidgetByte(13).ValueAsInt=replaced;
  Console.WriteLine("next-after-binding:"+unit.GetStaticTextIndex("Third"));
  data.WidgetByte(13).ValueAsInt=63;data.WidgetByte(14).ValueAsInt=62;
  data.LabelDisplayType=3;data.LabelValueText="Pair A";
  data.StatusDisplayType=5;data.StatusValueText="Pair B";
  Console.WriteLine("pair-different:"+data.LabelValueIndex+","+data.StatusValueIndex);
  data.LabelDisplayType=3;data.LabelValueText="Shared";
  data.StatusDisplayType=5;data.StatusValueText="Shared";
  Console.WriteLine("pair-same:"+data.LabelValueIndex+","+data.StatusValueIndex);

  for(int i=1;i<32;i++)data.WidgetByte(i).ValueAsInt=i;
  data.WidgetByte(1).ValueAsInt=0x35;
  foreach(var item in new string[][] {new string[] {"0","CBusLogicModel.EDLT.WidgetData.BlankData"},new string[] {"2","CBusLogicModel.Units.EDLT.WidgetData.LightingData"},new string[] {"3","CBusLogicModel.EDLT.WidgetData.ShutterRelayData"},new string[] {"4","CBusLogicModel.EDLT.WidgetData.FanControllerData"},new string[] {"5","CBusLogicModel.Units.EDLT.WidgetData.TimerData"},new string[] {"6","CBusLogicModel.Units.EDLT.WidgetData.SceneData"},new string[] {"7","CBusLogicModel.EDLT.WidgetData.MRA.MRAZoneControlData"},new string[] {"8","CBusLogicModel.EDLT.WidgetData.MRA.MRASourceSelectData"},new string[] {"9","CBusLogicModel.EDLT.WidgetData.MRA.MRASourceControlData"},new string[] {"10","CBusLogicModel.EDLT.WidgetData.TimeAndDateData"},new string[] {"11","CBusLogicModel.EDLT.WidgetData.TimeAndDateData"},new string[] {"12","CBusLogicModel.EDLT.WidgetData.MeasurementData"},new string[] {"13","CBusLogicModel.EDLT.WidgetData.HVACTempDisplayData"},new string[] {"14","CBusLogicModel.Units.EDLT.WidgetData.EnableData"},new string[] {"15","CBusLogicModel.EDLT.WidgetData.RCPData"},new string[] {"16","CBusLogicModel.EDLT.WidgetData.MultiLevelData"}}) {
   var model=(WidgetBaseData)FormatterServices.GetUninitializedObject(typeof(EDLTUnit).Assembly.GetType(item[1]));
   model.ParentWidget=widget;
   typeof(WidgetBaseData).GetField("WidgetPrefix",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(model,"Widget6");
   Console.WriteLine("references:"+item[0]+":"+String.Join(",",model.GetUsedStaticText().OrderBy(x=>x)));
   data.WidgetByte(1).ValueAsInt=0;
   Console.WriteLine("references-blank:"+item[0]+":"+String.Join(",",model.GetUsedStaticText().OrderBy(x=>x)));
   data.WidgetByte(1).ValueAsInt=0x35;
   if(item[0]=="7") {
    data.WidgetByte(1).ValueAsInt=0x3D;
    Console.WriteLine("mra-zone-bits:"+String.Join(",",model.GetUsedStaticText().OrderBy(x=>x)));
    data.WidgetByte(1).ValueAsInt=0x35;
   }
  }
  var utf=new PPAttribute{Name="Truncation"};utf.ValueAsUtf8String=new string('A',62)+"ā";Console.WriteLine("truncated:"+utf.Value+":"+utf.ValueAsUtf8String);
  unit.Scenes.Clear();
  for(int i=0;i<63;i++)unit.Scenes.Add(new EDLTScene(unit,0,true,255,0,i,i));
  unit.Scenes.Add(new EDLTScene(unit,0,true,255,0,255,63));
  try {unit.GetStaticTextIndex("Capacity new");Console.WriteLine("capacity-unexpected-success");}
  catch(Exception error) {Console.WriteLine("capacity:"+unit.GetUsedStaticText().Count+":"+error.Message);}
  Console.WriteLine("existing-full:"+unit.GetStaticTextIndex("Lamp"));
 }
}
