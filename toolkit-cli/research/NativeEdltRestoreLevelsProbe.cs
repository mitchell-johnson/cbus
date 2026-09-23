// Owned original-assembly research probe; no FrmBaseUnit constructor, SaveUnit or network endpoint.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Reflection;
using System.Runtime.Serialization;
using System.Xml.Linq;
using System.Windows.Forms;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.CBusObjects;
using eDLT;
using eDLT.Controls;
class NativeEdltRestoreLevelsProbe {
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
  if(mode=="duplicate-groups" || mode=="duplicate-app-groups")foreach(var a in n.Applications)foreach(var g in a.Groups)if(g.AddressAsInt!=255)g.TagName="Same group";
  if(mode=="duplicate-app-groups")foreach(var a in n.Applications)a.TagName="Same application";
  return n;
 }

 static void Dump(string stage,EDLTUnit u){foreach(var p in u.PPAttributes)Console.WriteLine(stage+":"+p.Name+"\t"+p.Value);}
 static string B64(string s){return Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(s??""));}
 static void Field(object o,string name,object value){var f=o.GetType().GetField(name,BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic);if(f==null)throw new Exception("Missing owned fixture field: "+name);f.SetValue(o,value);}
 static object Call(object o,string name,params object[] args){return o.GetType().GetMethod(name,BindingFlags.Instance|BindingFlags.NonPublic).Invoke(o,args);}
 static void Groups(string stage,EDLTUnit u){var rows=u.GetRestoreLevelGroups();Console.WriteLine(stage+":groups:"+string.Join(",",rows.Key)+":"+string.Join(",",rows.Value.Select(B64)));}
 static void Controls(string stage,EDLTUnit u,FlowLayoutPanel panel){
  for(int i=0;i<panel.Controls.Count;i++){
   var c=(PowerRestoreLevelControl)panel.Controls[i];
   Console.WriteLine(stage+":control:"+(i+6)+":"+u.Widgets[i+5].WidgetType+":"+c.Level.Value+":"+u.Widgets[i+5].RestoreLevel+":"+c.Visible+":"+B64(c.GroupName)+":"+c.Level.MinLevel+":"+c.Level.MaxLevel+":"+c.Level.DataBindings["Value"].DataSourceUpdateMode);
  }
 }
 [STAThread] static void Main(string[] args){
  EDLTUnit u=null;string stage="setup";
  try{
   PPAttribute.bInitialiseMode=true;
   u=new EDLTUnit("OWNED","254","20","owned-id",true,Cache(args[5]));
   u.UnitType="KEYGL5";u.FirmwareVersion="5.5.00";u.CatalogNumber="5055EDL";
   foreach(string line in File.ReadAllLines(args[1])){int split=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});}
   string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
   foreach(string line in File.ReadAllLines(args[2])){int split=line.IndexOf('\t');u.GetPPAttribute(line.Substring(0,split)).Value=line.Substring(split+1);}
   Dump("initial",u);stage="afterload";u.AfterLoadPPData();Dump(stage,u);PPAttribute.bInitialiseMode=false;
   // Only the two original methods under test are invoked on the uninitialized outer form.
   // All controls and widget/model objects are real original objects; the host Form is owned.
   stage="controls-setup";var outer=Bare<FrmBaseUnit>();
   using(var host=new Form())using(var box=new GroupBox())using(var panel=new FlowLayoutPanel())using(var sync=new CheckBox())using(var preset=new RadioButton())using(var previous=new RadioButton())using(var tabs=new TabControl())using(var bs=new BindingSource()){
    Field(outer,"_unit",u);Field(outer,"flpWidgetPresetLevels",panel);Field(outer,"chkPowerRestoreSynchronise",sync);Field(outer,"rbRestorePreset",preset);Field(outer,"tabControl",tabs);
    for(int i=0;i<5;i++)tabs.TabPages.Add(new TabPage("Owned"+i));tabs.SelectedIndex=4;
    bs.DataSource=typeof(EDLTUnit);
    sync.DataBindings.Add(new Binding("Visible",bs,"DisableLevelStore",true,DataSourceUpdateMode.Never));
    panel.DataBindings.Add(new Binding("Visible",bs,"DisableLevelStore",true,DataSourceUpdateMode.Never));
    previous.DataBindings.Add(new Binding("Checked",bs,"EnableLevelStore",true,DataSourceUpdateMode.OnPropertyChanged));
    preset.Checked=true;preset.DataBindings.Add(new Binding("Checked",bs,"DisableLevelStore",true,DataSourceUpdateMode.OnPropertyChanged));
    panel.AutoScroll=true;panel.Top=56;panel.Width=660;panel.Height=500;panel.FlowDirection=FlowDirection.TopDown;panel.WrapContents=false;
    sync.Left=440;previous.Left=8;preset.Left=180;
    box.Dock=DockStyle.Fill;box.Controls.Add(sync);box.Controls.Add(panel);box.Controls.Add(previous);box.Controls.Add(preset);host.Controls.Add(box);host.Width=700;host.Height=640;
    bs.DataSource=u;
    var handler=(ValueChangedEventHandler)Delegate.CreateDelegate(typeof(ValueChangedEventHandler),outer,typeof(FrmBaseUnit).GetMethod("PowerRestore_ValueChanged",BindingFlags.Instance|BindingFlags.NonPublic));
    for(int i=5;i<=20;i++){
     var c=new PowerRestoreLevelControl();c.Padding=new Padding(0);c.Margin=new Padding(0);c.Left=0;
     c.ValueChanged+=handler;
     c.Level.DataBindings.Add(new Binding("Value",u.Widgets[i],"RestoreLevel",false,DataSourceUpdateMode.OnValidation));
     c.Tag=u.Widgets[i];c.Level.Tag=u.Widgets[i];panel.Controls.Add(c);
    }
    stage="bind";host.Show();Application.DoEvents();Controls(stage,u,panel);Dump(stage,u);
    stage="refresh";Call(outer,"tpKeyFunctions_SelectedIndexChanged",null,EventArgs.Empty);Application.DoEvents();Controls(stage,u,panel);Dump(stage,u);
    int index=0;
    foreach(string line in File.ReadAllLines(args[3])){
     var words=line.Split(' ');stage="action"+(index++)+"-"+words[0];
     if(words[0]=="edit" || words[0]=="force-edit"){
      int widget=int.Parse(words[1]);sync.Checked=words[3]=="true";
      var c=(PowerRestoreLevelControl)panel.Controls[widget-6];
      Console.WriteLine(stage+":editable:"+c.Visible+":"+preset.Checked);
      if(c.Visible && preset.Checked || words[0]=="force-edit")c.Level.SetValue(int.Parse(words[2]));
      else Console.WriteLine(stage+":edit-unavailable:true");
     }else if(words[0]=="refresh")Call(outer,"tpKeyFunctions_SelectedIndexChanged",null,EventArgs.Empty);
     else if(words[0]=="groups")Groups(stage,u);
     else if(words[0]=="validate")host.Validate();
     else if(words[0]=="write")foreach(PowerRestoreLevelControl c in panel.Controls)c.Level.DataBindings["Value"].WriteValue();
     else if(words[0]=="mode"){u.MultiPage=int.Parse(words[1]);Call(outer,"tpKeyFunctions_SelectedIndexChanged",null,EventArgs.Empty);}
     else if(words[0]=="restore-mode"){if(words[1]=="preset")preset.Checked=true;else previous.Checked=true;}
     else throw new Exception("Unknown owned action");
     Application.DoEvents();Controls(stage,u,panel);Dump(stage,u);
    }
    stage="beforesave";typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});Dump(stage,u);
    stage="crc";typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);Dump(stage,u);
    host.Close();
   }
   Console.WriteLine("complete:true");
  }catch(Exception e){Console.WriteLine("failure-stage:"+stage);Console.WriteLine("failure:"+e);if(u!=null)Dump("partial",u);Environment.ExitCode=1;}
 }
}
