// Original cached-object and binding logic; network construction/I/O is deliberately absent.
using System;
using System.Linq;
using System.ComponentModel;
using System.Collections.Generic;
using System.Drawing;
using System.Runtime.Serialization;
using CBusLogicModel;
using CBusLogicModel.CBusObjects;
using CBusLogicModel.ProgramableProperties;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units.EDLT.WidgetData;
public class CachedGroupFixture {
 public readonly CBusNetwork Network;
 public readonly CBusApplication Application;
 public readonly PPAttribute Primary;
 public CachedGroupFixture(params int[] addresses) {
  Network=(CBusNetwork)FormatterServices.GetUninitializedObject(typeof(CBusNetwork));
  Network.Applications=new BindingList<CBusApplication>();Network.bContinue=false;
  Network.ProjectImages=new List<KeyValuePair<string,Image>>();Network.DLTP=new List<KeyValuePair<int,Image>>();
  Application=new CBusApplication(Network){AddressAsInt=56,TagName="Owned lighting",bContinue=false};
  Network.Applications.Add(Application);CBusApplication.bAdd=false;
  foreach(int address in addresses) {
   var group=new CBusGroup(Application,"Owned "+address,address);group.TagsDLTAll=new BindingList<TagDLT>();
   foreach(var tag in group.TagsDLT){tag.TagType="TEXT";tag.TagValue="Label "+tag.Variant;tag.LanguageID="1";group.TagsDLTAll.Add(tag);}
   group.PopulateDynamicAll();Application.Groups.Add(group);
  }
  Primary=new PPAttribute{Name="PrimaryApplication",Value="56"};
 }
 public BindingListCBusObject<DataStore> Groups() {return new BindingListCBusObject<DataStore>(Network,"Applications",Primary,"Groups",null,null);}
 public PPAttributeDataSourceLogic Bind(PPAttribute attribute,int disabled) {return new PPAttributeDataSourceLogic(Network,attribute,attribute,true,disabled,Groups());}
}
class NativeEdltCachedGroupProbe {
 static void Main() {
  PPAttribute.bInitialiseMode=true;
  foreach(var addresses in new[]{new int[]{42,7},new int[]{7,42},new int[0]})foreach(int disabled in new[]{255,-1})foreach(int initial in new[]{7,42,99,255}) {
   var fixture=new CachedGroupFixture(addresses);var value=new PPAttribute{Name="Group",Value=initial.ToString()};var bind=fixture.Bind(value,disabled);
   var selected=bind.PPAttributeValue;
   Console.WriteLine("get:"+string.Join(",",addresses)+":"+disabled+":"+initial+":"+selected+":"+value.ValueAsInt+":"+bind.IsEnabled+":list="+string.Join(",",bind.DataSource.Select(d=>d.ValueAsInt)));
  }
  foreach(var addresses in new[]{new int[]{42,7},new int[]{7,42},new int[0]})foreach(int disabled in new[]{255,-1})foreach(bool enabled in new[]{false,true}) {
   var fixture=new CachedGroupFixture(addresses);var value=new PPAttribute{Name="Group",Value="255"};var bind=fixture.Bind(value,disabled);
   bind.IsEnabled=enabled;int before=value.ValueAsInt;bool state=bind.IsEnabled;int observed=bind.PPAttributeValue;
   Console.WriteLine("enable:"+string.Join(",",addresses)+":"+disabled+":"+enabled+":"+before+":"+state+":"+observed+":"+value.ValueAsInt+":"+bind.IsEnabled);
  }
  var f=new CachedGroupFixture(42);var u=(EDLTUnit)FormatterServices.GetUninitializedObject(typeof(EDLTUnit));
  u.Network=f.Network;u.PPAttributes=new BindingList<PPAttribute>();u.PrimaryApplication=new PPAttributeDataSourceLogic(f.Network,f.Primary,f.Primary,true,-1,new BindingListCBusObject<DataStore>(f.Network,"Applications",null,null));
  foreach(var pair in new[]{new[]{"NavWidgetVariant","7"},new[]{"DynamicGroup","42"},new[]{"TemperatureApplication","0"},new[]{"NavDevIDZoneGroup","255"},new[]{"NavChannelZoneNumber","0"}})u.PPAttributes.Add(new PPAttribute{Name=pair[0],Value=pair[1]});
  var page=(EDLTPageWidget)FormatterServices.GetUninitializedObject(typeof(EDLTPageWidget));page.Unit=u;page.Attributes=u.PPAttributes;page.WidgetNumber=-1;page.WidgetData=new PageWidgetData(page,"NavWidget",u.PPAttributes);u.PageWidget=page;
  var nav=(PageWidgetData)page.WidgetData;
  Console.WriteLine("navigation-groups:"+string.Join(",",nav.SelectedApplicationGroups.Select(g=>g.AddressAsInt)));
  Console.WriteLine("measurement-devices:"+string.Join(",",nav.DevIDZoneGroupValues.Select(g=>g.ValueAsInt)));
  Console.WriteLine("measurement-channels:"+string.Join(",",nav.ChannelZoneNumberValues.Select(g=>g.ValueAsInt)));
  var hvac=new CBusApplication(f.Network){AddressAsInt=172,TagName="Owned HVAC",bContinue=false};f.Network.Applications.Add(hvac);
  hvac.Groups.Add(new CBusGroup(hvac,"Zone 0",0));hvac.Groups.Add(new CBusGroup(hvac,"Zone 254",254));
  nav.TemperatureApplication=1;
  Console.WriteLine("hvac-groups:"+string.Join(",",nav.DevIDZoneGroupValues.Select(g=>g.ValueAsInt)));
  Console.WriteLine("hvac-zones:"+string.Join(",",nav.ChannelZoneNumberValues.Select(g=>g.ValueAsInt)));

  Console.WriteLine("dynamic42:"+string.Join("|",nav.NavDynamicLabels.Select(v=>v.ValueAsInt+"="+v.Name)));
  Console.WriteLine("logo-icons42:"+string.Join(",",nav.GetDynamicIcons().Select(t=>t.Variant)));
  u.NavWidgetVariant=5;Console.WriteLine("logo-only42:"+string.Join(",",nav.GetDynamicIcons().Select(t=>t.Variant)));
  foreach(int group in new[]{255,99}){nav.PageDynamicGroup=group;Console.WriteLine("dynamic"+group+":"+nav.NavDynamicLabels.Count+":"+nav.GetDynamicIcons().Count);}
 }
}
