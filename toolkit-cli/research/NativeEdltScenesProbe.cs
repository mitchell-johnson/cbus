// Original Toolkit SaveScenes on explicit fixtures/input; no network calls.
using System;
using System.IO;
using System.Linq;
using System.ComponentModel;
using System.Runtime.Serialization;
using System.Security.Cryptography;
using CBusLogicModel;
using CBusLogicModel.CBusObjects;
using CBusLogicModel.EDLT;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units.EDLT.WidgetData;
class NativeEdltScenesProbe {
 static T Bare<T>() {return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static EDLTUnit Unit() {
  var u=Bare<EDLTUnit>();u.PPAttributes=new BindingList<PPAttribute>();u.Scenes=new BindingList<EDLTScene>();u.Widgets=new BindingList<EDLTWidget>();
  foreach(var name in new[]{"SceneCount","SceneBucket","NavWidgetVariant"})u.PPAttributes.Add(new PPAttribute{Name=name,Value="0x0"});
  for(int i=1;i<=8;i++)u.PPAttributes.Add(new PPAttribute{Name="Scene"+i+"StartAddress",Value="0xFF"});
  u.StaticLabels=new BindingList<DataStore>();u.StaticTextSuggest=new BindingList<DataStore>();
  for(int i=0;i<64;i++){var a=new PPAttribute{Name="StaticTextString"+i};a.ValueAsUtf8String=i==1?"Evening":"";u.PPAttributes.Add(a);u.StaticLabels.Add(new DataStore(a.ValueAsUtf8String,i));}
  var p=Bare<EDLTPageWidget>();p.Unit=u;p.Attributes=u.PPAttributes;p.WidgetNumber=0;p.WidgetData=new PageWidgetData(p,"NavWidget",u.PPAttributes);u.PageWidget=p;
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();u.Network=n;
  foreach(int addr in new[]{56,57,202}){var app=new CBusApplication(n){AddressAsInt=addr};n.Applications.Add(app);for(int g=0;g<255;g++)app.Groups.Add(new CBusGroup(app,"G"+g,g));}
  return u;
 }
 static EDLTScene Add(EDLTUnit u,int application,bool editable,int trigger,int action,int name) {
  var group=u.Network.GetApplicationByAddress(202).GetGroupByAddress(trigger);
  if(group.Levels.All(l=>l.AddressAsInt!=action))group.Levels.Add(new CBusLevel(group,"Action"+action,action));
  var s=new EDLTScene(u,application,editable,trigger,action,name,u.Scenes.Count);u.Scenes.Add(s);return s;
 }
 static void Dump(EDLTUnit u,string prefix,bool full) {
  u.SaveScenes(false);
  var tokens=u.GetPPAttribute("SceneBucket").Value.Split(new[]{' '},StringSplitOptions.RemoveEmptyEntries);
  Console.WriteLine(prefix+":length:"+tokens.Length);
  var b=tokens.Select(t=>(byte)Convert.ToInt32(t,16)).ToArray();
  Console.WriteLine(prefix+":sha256:"+BitConverter.ToString(SHA256.Create().ComputeHash(b)).Replace("-","").ToLower());
  if(full)foreach(var a in u.PPAttributes.Where(a=>a.Name.StartsWith("Scene")||a.Name.StartsWith("StaticTextString")))Console.WriteLine(prefix+":pp:"+a.Name+":"+a.Value);
 }
 static void Main(string[] args) {
  PPAttribute.bInitialiseMode=true;
  foreach(int count in new[]{63,64}) {
   var u=Unit();for(int i=0;i<8;i++)Add(u,i%2,i%2==0,42,70+i,1);
   for(int i=0;i<count;i++)u.Scenes[0].Items.Add(new EDLTSceneItem(u.Network.GetApplicationByAddress(56).GetGroupByAddress(i),i%2==0,i%16,(i*4)%256));
   Dump(u,"limit"+count,count==64);Console.WriteLine("limit"+count+":percent:"+u.ScenesStorageUsedPercent);
  }
  if(args.Length==1) {
   var u=Unit();EDLTScene selected=null;
   var names=new System.Collections.Generic.List<string>();
   foreach(var line in File.ReadAllLines(args[0])) {
    var p=line.Split('\t');if(p[0]=="scene"){selected=Add(u,int.Parse(p[1]),p[2]=="1",int.Parse(p[3]),int.Parse(p[4]),int.Parse(p[5]));names.Add(p.Length>6?p[6]:null);}
    else if(p[0]=="item")selected.Items.Add(new EDLTSceneItem(u.Network.GetApplicationByAddress(selected.PriSecApplication==0?56:57).GetGroupByAddress(int.Parse(p[1])),p[4]=="1",int.Parse(p[3]),int.Parse(p[2])));
   }
   for(int i=0;i<names.Count;i++)if(names[i]!=null)u.Scenes[i].SceneName=names[i];
   Dump(u,"input",true);
  }
 }
}
