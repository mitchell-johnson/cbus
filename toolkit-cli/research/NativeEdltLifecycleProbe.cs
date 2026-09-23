// Runtime-only: actual original constructor, AfterLoadPPData and BeforeSavePPData.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Reflection;
using System.Runtime.Serialization;
using System.Xml.Linq;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.CBusObjects;
class NativeEdltLifecycleProbe {
 static T Bare<T>(){return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static CBusNetwork Cache(string mode) {
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();n.Languages=new BindingList<CBusLanguage>();
  n.ProjectImages=new List<KeyValuePair<string,Image>>();n.DLTP=new List<KeyValuePair<int,Image>>();n.ProjectName="OWNED";n.NetworkAddress="254";
  if(mode=="image-present")n.ProjectImages.Add(new KeyValuePair<string,Image>("owned-image",new Bitmap(1,1)));
  n.bContinue=false;CBusApplication.bAdd=false;CBusApplication.AutoAddGroupsMessageShown=true;
  foreach(int app in new[]{56,57,127,136,172,202,203,255}) {
   if(mode=="missing-app"+app)continue;
   var a=new CBusApplication(n){AddressAsInt=app,TagName="Owned application"+app,bContinue=false};n.Applications.Add(a);
   foreach(int group in new[]{0,1,2,12,42,254})if(!(mode=="missing-group0" && app==56 && group==0))a.Groups.Add(new CBusGroup(a,"Owned group"+group,group));
   foreach(var g in a.Groups) {
    g.bContinue=false;g.TagsDLTAll=new BindingList<TagDLT>();
    foreach(var tag in g.TagsDLT){tag.TagType=(mode=="image-present" || mode=="image-absent")?"DYNAMIC":"TEXT";tag.TagValue=(mode=="image-present" || mode=="image-absent")?"owned-image":"Owned "+tag.Variant;tag.LanguageID="1";g.TagsDLTAll.Add(tag);}
    g.PopulateDynamicAll();
    if(app==56 && g.AddressAsInt==42 && mode=="dynamic-null")g.DynamicAll=null;
    if(app==56 && g.AddressAsInt==42 && mode=="dynamic-empty")g.DynamicAll.Clear();
    if(app==56 && g.AddressAsInt==42 && mode=="dynamic-short")while(g.DynamicAll.Count>1)g.DynamicAll.RemoveAt(g.DynamicAll.Count-1);
    foreach(int level in new[]{0,1,2,42,254,255})if(!((mode=="missing-level2" || mode=="missing-level0-and2") && app==202 && g.AddressAsInt==42 && (level==2 || (mode=="missing-level0-and2" && level==0)))){
     var l=new CBusLevel(g,"Owned level"+level,level);foreach(var tag in l.TagsDLT){tag.TagType="TEXT";tag.TagValue="Owned level label";tag.LanguageID="1";l.TagsDLTAll.Add(tag);}l.PopulateDynamicAll();g.Levels.Add(l);
    }
   }
  }
  n.addApplicationEvent+=delegate(string a,out string output){output="";throw new Exception("UNEXPECTED ADD APPLICATION "+a);};
  n.addGroupEvent+=delegate(string a,string g,out string output){output="";throw new Exception("UNEXPECTED ADD GROUP "+a+"/"+g);};
  n.addLevelEvent+=delegate(string a,string g,string l,out string output){output="";throw new Exception("UNEXPECTED ADD LEVEL "+a+"/"+g+"/"+l);};
  return n;
 }
 static void Dump(string stage,EDLTUnit u){foreach(var p in u.PPAttributes)Console.WriteLine(stage+":"+p.Name+"\t"+p.Value);}
 static void Main(string[] args) {
  string stage="setup";EDLTUnit u=null;
  try {
   PPAttribute.bInitialiseMode=true;
   u=new EDLTUnit("OWNED","254","20","owned-id",true,Cache(args.Length>3?args[3]:"complete"));
   u.UnitType="KEYGL5";u.FirmwareVersion="5.5.00";u.CatalogNumber="5055EDL";
   foreach(string line in File.ReadAllLines(args[1])){int split=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});}
   string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
   if(args.Length>2)foreach(string line in File.ReadAllLines(args[2])){int split=line.IndexOf('\t');u.GetPPAttribute(line.Substring(0,split)).Value=line.Substring(split+1);}
   if(args.Length>4 && args[4]=="enable-inputs") {
    u.AfterLoadPPData();u.GetPPAttribute("Widget6WidgetType").ValueAsInt=14;
    foreach(bool reverse in new[]{false,true})for(int previous=0;previous<256;previous++)foreach(int fixedValue in new[]{0,23,24,255}) {
     int left=reverse?fixedValue:previous,right=reverse?previous:fixedValue;
     u.GetPPAttribute("Widget6WidgetByteValue7").ValueAsInt=left;u.GetPPAttribute("Widget6WidgetByteValue8").ValueAsInt=right;
     u.GetPPAttribute("Widget6WidgetByteValue9").ValueAsInt=42;u.GetPPAttribute("Widget6WidgetByteValue10").ValueAsInt=43;
     var widget=new EDLTWidget(u,6,u.PPAttributes);
     Console.WriteLine("enable:"+left+":"+right+":"+u.GetPPAttribute("Widget6WidgetByteValue7").ValueAsInt+":"+u.GetPPAttribute("Widget6WidgetByteValue8").ValueAsInt+":"+u.GetPPAttribute("Widget6WidgetByteValue9").ValueAsInt+":"+u.GetPPAttribute("Widget6WidgetByteValue10").ValueAsInt);
     widget.WidgetData.Dispose();
    }
    return;
   }
   Dump("initial",u);stage="afterload";u.AfterLoadPPData();Dump(stage,u);
   stage="beforesave";typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});Dump(stage,u);
   stage="crc";typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);Dump(stage,u);
   Console.WriteLine("complete:true");
  } catch(Exception error){Console.WriteLine("failure-stage:"+stage);Console.WriteLine("failure:"+error);if(u!=null)Dump("partial",u);Environment.ExitCode=1;}
 }
}
