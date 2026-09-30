// Synthetic in-memory PP/cache only. No form, communicator, C-Gate or device.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Globalization;
using System.Reflection;
using System.Runtime.Serialization;
using System.Security.Cryptography;
using System.Text;
using System.Xml.Linq;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.CBusObjects;
class EdltTemplateModelProbe {
 static string Hash(byte[] bytes) { using(var hash=SHA256.Create())return BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant(); }
 static string Enc(string value) {return Convert.ToBase64String(Encoding.Unicode.GetBytes(value));}
 static T Bare<T>() {return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static CBusNetwork Cache() {
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();n.Languages=new BindingList<CBusLanguage>();
  n.ProjectImages=new List<KeyValuePair<string,Image>>();n.DLTP=new List<KeyValuePair<int,Image>>();n.ProjectName="OWNED";n.NetworkAddress="254";
  n.bContinue=false;CBusApplication.bAdd=false;CBusApplication.AutoAddGroupsMessageShown=true;
  foreach(int app in new[]{56,57,127,136,172,202,203,255}) {
   var a=new CBusApplication(n){AddressAsInt=app,TagName="Owned application"+app,bContinue=false};n.Applications.Add(a);
   foreach(int group in new[]{0,1,2,12,42,254})a.Groups.Add(new CBusGroup(a,"Owned group"+group,group));
   foreach(var g in a.Groups) {
    g.bContinue=false;g.TagsDLTAll=new BindingList<TagDLT>();
    foreach(var tag in g.TagsDLT){tag.TagType="TEXT";tag.TagValue="Owned "+tag.Variant;tag.LanguageID="1";g.TagsDLTAll.Add(tag);}g.PopulateDynamicAll();
    foreach(int level in new[]{0,1,2,42,254,255}) {
     var l=new CBusLevel(g,"Owned level"+level,level);foreach(var tag in l.TagsDLT){tag.TagType="TEXT";tag.TagValue="Owned level label";tag.LanguageID="1";l.TagsDLTAll.Add(tag);}l.PopulateDynamicAll();g.Levels.Add(l);
    }
   }
  }
  n.addApplicationEvent+=delegate(string a,out string output){output="";throw new Exception("UNEXPECTED ADD APPLICATION "+a);};
  n.addGroupEvent+=delegate(string a,string g,out string output){output="";throw new Exception("UNEXPECTED ADD GROUP "+a+"/"+g);};
  n.addLevelEvent+=delegate(string a,string g,string l,out string output){output="";throw new Exception("UNEXPECTED ADD LEVEL "+a+"/"+g+"/"+l);};
  return n;
 }
 static Dictionary<string,string> previous=new Dictionary<string,string>();
 static void Dump(string stage,EDLTUnit u) {
  foreach(var p in u.PPAttributes) {
   if(!previous.ContainsKey(p.Name)||previous[p.Name]!=p.Value)Console.WriteLine(stage+"\traw\t"+p.Name+"\t"+Enc(p.Value));
   previous[p.Name]=p.Value;
  }
  Console.WriteLine(stage+"\tstate\tinitialise\t"+PPAttribute.bInitialiseMode);
  Console.WriteLine(stage+"\tstate\tdirty\t"+string.Join(",",u.PPAttributes.Where(p=>p.HasBeenChanged).Select(p=>p.Name).ToArray()));
  Console.WriteLine(stage+"\tstate\tpp-count\t"+u.PPAttributes.Count);
  Console.WriteLine(stage+"\tstate\tpp-hash\t"+Hash(Encoding.UTF8.GetBytes(string.Join("\n",u.PPAttributes.Select(p=>p.Name+"\t"+p.Value).ToArray())+"\n")));
 }
 static void Model(string stage, EDLTUnit u) {
  Console.WriteLine(stage+"\tmodel\twidget-count\t"+u.Widgets.Count);
  Console.WriteLine(stage+"\tmodel\tscene-count\t"+u.Scenes.Count);
  Console.WriteLine(stage+"\tmodel\tmra\t"+u.MRAMultiplexer+","+u.MRAZone);
  Console.WriteLine(stage+"\tmodel\twidgets\t"+string.Join(",",u.Widgets.Select(w=>w.WidgetType+":"+w.WidgetData.GetType().Name).ToArray()));
  Console.WriteLine(stage+"\tmodel\tscenes\t"+string.Join(",",u.Scenes.Select(s=>s.SceneIndex+":"+s.PriSecApplication+":"+s.NameIndex+":"+s.Items.Count).ToArray()));
  Console.WriteLine(stage+"\tmodel\tlabels-count\t"+u.StaticLabels.Count);
  Console.WriteLine(stage+"\tmodel\tprimary-secondary-count\t"+u.PrimSecApplication.Count);
  Console.WriteLine(stage+"\tmodel\tprimary-secondary\t"+Enc(string.Join("|",u.PrimSecApplication.Select(a=>a.ValueAsInt+":"+a.Name).ToArray())));
  Console.WriteLine(stage+"\tmodel\tlist-events\t"+u.Widgets.RaiseListChangedEvents+","+u.Scenes.RaiseListChangedEvents+","+u.StaticLabels.RaiseListChangedEvents+","+u.PrimSecApplication.RaiseListChangedEvents);
 }
 static void Identity(string name, object first, object second) {Console.WriteLine("second\tidentity\t"+name+"\t"+Object.ReferenceEquals(first,second));}
 static void Main(string[] args) {
  CultureInfo.CurrentCulture=CultureInfo.InvariantCulture;
  foreach(var type in new[]{typeof(EDLTUnit),typeof(object),typeof(EdltTemplateModelProbe)})
   Console.Error.WriteLine("assembly\t"+type.FullName+"\t"+type.Assembly.Location+"\t"+Hash(File.ReadAllBytes(type.Assembly.Location))+"\t"+IntPtr.Size*8);
  foreach(var method in new[]{typeof(EDLTUnit).GetMethod("AfterLoadPPData"),typeof(EDLTUnit).GetMethod("LoadWidgetsFromAttributes"),typeof(CBusBaseUnit).GetMethod("AfterLoadPPData"),typeof(CBusBaseUnit).GetMethod("PopulatePrimarySecondaryApplication")})
   Console.Error.WriteLine("method\t"+method.DeclaringType.Name+"."+method.Name+"\t0x"+method.MetadataToken.ToString("x8")+"\t"+Hash(method.GetMethodBody().GetILAsByteArray()));
  string stage="setup";EDLTUnit u=null;
  try {
   PPAttribute.bInitialiseMode=true;
   u=new EDLTUnit("OWNED","254","20","owned-id",true,Cache());
   u.UnitType="KEYGL5";u.FirmwareVersion="5.5.00";u.CatalogNumber="5055EDL";
   foreach(string line in File.ReadAllLines(args[1])){int split=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});}
   string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
   Dump("initial",u);stage="first";u.AfterLoadPPData();Dump(stage,u);Model(stage,u);
   var widgets=u.Widgets.ToArray();var scenes=u.Scenes.ToArray();var labels=u.StaticLabels.ToArray();
   object widgetList=u.Widgets,sceneList=u.Scenes,labelList=u.StaticLabels,page=u.PageWidget,primary=u.PrimaryApplication,secondary=u.SecondaryApplication,proximity=u.ProximityGroup;
   stage="assign";
   int index=0;
   foreach(string line in File.ReadAllLines(args[2])) {
    int split=line.IndexOf('\t');string name=line.Substring(0,split),value=line.Substring(split+1);
    PPAttribute.bInitialiseMode=true;
    var attribute=u.GetPPAttribute(name);
    if(!attribute.Value.Equals(value)){attribute.Value=value;attribute.HasBeenChanged=true;}
    Console.WriteLine(stage+"\tassignment\t"+(index++)+"\t"+name+"\t"+Enc(u.GetPPAttribute(name).Value));
    PPAttribute.bInitialiseMode=false;
   }
   PPAttribute.bInitialiseMode=false;
   Dump("assigned",u);stage="second";u.AfterLoadPPData();Dump(stage,u);Model(stage,u);
   Identity("widget-list",widgetList,u.Widgets);Identity("scene-list",sceneList,u.Scenes);Identity("label-list",labelList,u.StaticLabels);Identity("page",page,u.PageWidget);Identity("primary",primary,u.PrimaryApplication);Identity("secondary",secondary,u.SecondaryApplication);Identity("proximity",proximity,u.ProximityGroup);
   for(int i=0;i<widgets.Length;i++)Identity("widget"+(i+1),widgets[i],u.Widgets[i]);
   for(int i=0;i<scenes.Length;i++)Identity("scene"+(i+1),scenes[i],u.Scenes[i]);
   for(int i=0;i<labels.Length;i++)Identity("label"+i,labels[i],u.StaticLabels[i]);
   stage="populated";u.PopulatePrimarySecondaryApplication();Dump(stage,u);Model(stage,u);
   Console.WriteLine("complete\ttrue");
  }catch(Exception error) {
   while(error is TargetInvocationException && error.InnerException!=null)error=error.InnerException;
   Console.WriteLine("failure\t"+stage+"\t"+error.GetType().FullName+"\t"+Enc(error.Message));
   if(u!=null){Dump("partial",u);try{Model("partial",u);}catch(Exception modelError){Console.WriteLine("partial\tmodel\tsummary-error\t"+modelError.GetType().FullName);}}
   Environment.ExitCode=1;
  }
 }
}
