// Executes unchanged Toolkit1.18 SceneData and EDLTUnit.SaveScenes methods.
// Only explicit in-memory objects and PP attributes; no network calls.
using System;
using System.Linq;
using System.ComponentModel;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.CBusObjects;
using CBusLogicModel.EDLT;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units.EDLT.WidgetData;
class NativeEdltSceneProbe {
 static T Bare<T>() {return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static void Dump(string name, SceneData data, EDLTWidget widget) {
  byte[] bytes=new byte[32];bytes[0]=6;
  for(int i=1;i<32;i++)bytes[i]=(byte)data.WidgetByte(i).ValueAsInt;
  Console.WriteLine(name+":"+BitConverter.ToString(bytes).Replace("-","")+":"+widget.RestoreLevel);
 }
 static void Main() {
  PPAttribute.bInitialiseMode=true;
  var attrs=new BindingList<PPAttribute>();
  for(int i=1;i<32;i++)attrs.Add(new PPAttribute{Name="Widget6WidgetByteValue"+i,Value="0x0"});
  attrs.Add(new PPAttribute{Name="Widget6RestoreLevel",Value="0x99"});
  attrs.Add(new PPAttribute{Name="NavWidgetVariant",Value="0x0"});
  attrs.Add(new PPAttribute{Name="SceneCount",Value="0x0"});
  attrs.Add(new PPAttribute{Name="SceneBucket",Value="0xFF"});
  for(int i=1;i<=8;i++)attrs.Add(new PPAttribute{Name="Scene"+i+"StartAddress",Value="0xFFFF"});
  var unit=Bare<EDLTUnit>();unit.PPAttributes=attrs;unit.Widgets=new BindingList<EDLTWidget>();
  unit.StaticLabels=new BindingList<DataStore>();unit.StaticTextSuggest=new BindingList<DataStore>();
  for(int i=0;i<64;i++) {var a=new PPAttribute{Name="StaticTextString"+i};a.ValueAsUtf8String=i==1?"Evening":"";attrs.Add(a);unit.StaticLabels.Add(new DataStore(a.ValueAsUtf8String,i));}
  var widget=new EDLTWidget{Unit=unit,Attributes=attrs,WidgetNumber=6};
  var data=new SceneData(widget,"Widget6",attrs);widget.WidgetData=data;unit.Widgets.Add(widget);
  var page=Bare<EDLTPageWidget>();page.Unit=unit;page.Attributes=attrs;page.WidgetNumber=0;unit.PageWidget=page;
  page.WidgetData=new PageWidgetData(page,"NavWidget",attrs);
  unit.Scenes=new BindingList<EDLTScene>();
  data.SetToDefault();Dump("default",data,widget);
  data.SceneItem=1;data.DualButtonMacrofunction="26|27";data.LabelDisplayType=3;data.StatusDisplayType=5;data.StatusValueText="Scene ready";
  Dump("off-on-scene-label-static-status",data,widget);
  data.LabelValueIndex=3;data.StatusValueIndex=2;data.LabelDisplayType=1;data.StatusDisplayType=6;
  Dump("dynamic-index-preserved",data,widget);
  data.DualButtonMacrofunction="28|29";data.RampRate=15;Dump("ramp",data,widget);
  data.DualButtonMacrofunction="32|33";data.Offset=255;Dump("nudge",data,widget);
  data.DualButtonMacrofunction="30|31";data.SceneCycleVariant=1;
  data.Scene0=0;data.Scene1=1;data.Scene2=0;for(int i=3;i<9;i++)data.WidgetByte(13+i).ValueAsInt=255;
  Console.WriteLine("cycle-count:"+data.SceneCycle.Count);Dump("cycle-select",data,widget);
  data.SceneCycleVariant=0;for(int i=0;i<8;i++)data.WidgetByte(13+i).ValueAsInt=i%2;data.Scene8=255;
  Console.WriteLine("cycle-eight-count:"+data.SceneCycle.Count);Dump("cycle-eight",data,widget);
  for(int i=1;i<32;i++)data.WidgetByte(i).ValueAsInt=i;
  data.WidgetByte(1).ValueAsInt=0xff;data.SetToDefault();Dump("opaque-default",data,widget);
  var network=Bare<CBusNetwork>();network.Applications=new BindingList<CBusApplication>();unit.Network=network;
  var trigger=new CBusApplication(network){AddressAsInt=202};network.Applications.Add(trigger);
  var group=new CBusGroup(trigger,"Synthetic trigger",42);trigger.Groups.Add(group);
  group.Levels.Add(new CBusLevel(group,"Action77",77));group.Levels.Add(new CBusLevel(group,"Action88",88));
  var lighting=new CBusApplication(network){AddressAsInt=56};network.Applications.Add(lighting);
  var output=new CBusGroup(lighting,"Synthetic lamp",9);lighting.Groups.Add(output);
  var first=new EDLTScene(unit,0,true,42,77,1,0);first.Items.Add(new EDLTSceneItem(output,true,4,127));unit.Scenes.Add(first);
  unit.Scenes.Add(new EDLTScene(unit,0,true,42,88,1,1));
  unit.SaveScenes(false);
  foreach(var a in attrs.Where(a=>a.Name=="SceneCount"||a.Name=="SceneBucket"||a.Name.EndsWith("StartAddress")))Console.WriteLine("scene-pp:"+a.Name+":"+a.Value);
 }
}
