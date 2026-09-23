// Research-only: unchanged original model/control fixture; no live endpoints.
// Compile with original assemblies. Mode=controls requires an explicitly owned isolated display.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Reflection;
using System.Runtime.Serialization;
using System.Xml.Linq;
using System.Windows.Forms;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.ProgramableProperties;
using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.CBusObjects;
using eDLT.Controls;
using eDLT.Controls.PPControls;
class NativeEdltCorridorProbe {
 static string ActiveStage=null;
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
  n.addApplicationEvent+=delegate(string a,out string output){output="";Console.WriteLine("metadata-request:application:"+a);throw new Exception("UNEXPECTED ADD APPLICATION "+a);};
  n.addGroupEvent+=delegate(string a,string g,out string output){output="";Console.WriteLine("metadata-request:group:"+a+"/"+g);throw new Exception("UNEXPECTED ADD GROUP "+a+"/"+g);};
  n.addLevelEvent+=delegate(string a,string g,string l,out string output){output="";Console.WriteLine("metadata-request:level:"+a+"/"+g+"/"+l);throw new Exception("UNEXPECTED ADD LEVEL "+a+"/"+g+"/"+l);};
  return n;
 }

 static readonly string[] Roles={"Link","Office","Corridor"};
 static PPAttributeDataSourceLogic Role(EDLTUnit u,string role) {
  if(!Roles.Contains(role))throw new ArgumentException("Unknown role "+role);
  return (PPAttributeDataSourceLogic)typeof(EDLTUnit).GetProperty("CorridorLinking"+role+"Group").GetValue(u,null);
 }
 static int Raw(EDLTUnit u,string role){return u.GetPPAttribute("CorridorLinking"+role+"Group").ValueAsInt;}
 static void Dump(string stage,EDLTUnit u){foreach(var p in u.PPAttributes)Console.WriteLine(stage+":"+p.Name+"\t"+p.Value);}
 static void Lists(string stage,EDLTUnit u) {
  // No PPAttributeValue access here: listing and value lookup are separate observations.
  foreach(string role in Roles){var binding=Role(u,role);Console.WriteLine("list:"+stage+":"+role+":raw="+Raw(u,role)+":enabled="+binding.IsEnabled+":base="+binding.DataSource.ListBaseObject.Value+":choices="+string.Join(",",binding.DataSource.Select(d=>d.Value)));}
 }
 static void Observed(string stage,EDLTUnit u,Dictionary<string,ComboBoxAddEdit> controls,TimerSelector timer) {
  Lists(stage,u);
  if(controls!=null)foreach(string role in Roles) {
   var c=controls[role];Console.WriteLine("control:"+stage+":"+role+":raw="+Raw(u,role)+":enabled="+c.Enabled+":selected="+(c.comboBox.SelectedValue??"null")+":index="+c.comboBox.SelectedIndex+":choices="+string.Join(",",c.comboBox.Items.Cast<DataStore>().Select(d=>d.Value)));
  }
  Console.WriteLine("timer:"+stage+":raw="+u.GetPPAttribute("CorridorLinkingCorridorTime").ValueAsInt+":model="+u.CorridorLinkingCorridorTime+(timer==null?"":":display="+timer.TimerValue+":enabled="+timer.Enabled+":bindings="+string.Join(",",timer.DataBindings.Cast<Binding>().Select(b=>b.PropertyName+"="+b.BindingMemberInfo.BindingMember+"/"+b.DataSourceUpdateMode))));
  Dump(stage,u);
 }
 static void Validate(EDLTUnit u,IEnumerable<CBusGroup> groups,string name) {
  var captured=groups.ToList();Console.WriteLine("groups:"+name+":"+string.Join(",",captured.Select(g=>g.Application.AddressAsInt+"/"+g.AddressAsInt)));
  object[] args={captured,new List<string>()};
  var accepted=typeof(EDLTUnit).GetMethod("ValidateCorridorLinking",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,args);
  Console.WriteLine("validator:"+name+":"+accepted+":"+string.Join("|",((List<string>)args[1]).Select(v=>v.Replace("\r","\\r").Replace("\n","\\n"))));
 }
 static void RunActions(EDLTUnit u,string path,Form form,Dictionary<string,ComboBoxAddEdit> controls,TimerSelector timer) {
  int number=0;
  foreach(string line in File.ReadAllLines(path)) {
   if(line.Length==0 || line.StartsWith("#"))continue;
   string[] tokens=line.Split('\t');string command=tokens[0];string stage="action"+(++number)+"-"+command;
   ActiveStage=stage;Console.WriteLine("action:"+number+":"+line);
   if(command=="get")Console.WriteLine("getter:"+tokens[1]+":"+Role(u,tokens[1]).PPAttributeValue);
   else if(command=="set")Role(u,tokens[1]).PPAttributeValue=int.Parse(tokens[2]);
   else if(command=="primary")u.GetPPAttribute("PrimaryApplication").ValueAsInt=int.Parse(tokens[1]);
   else if(command=="timer-model")u.CorridorLinkingCorridorTime=int.Parse(tokens[1]);
   else if(command=="timer-control")timer.TimerValue=int.Parse(tokens[1]);
   else if(command=="timer-clock")timer.Value=timer.MinDate.AddSeconds(int.Parse(tokens[1]));
   else if(command=="select") {
    var c=controls[tokens[1]];int wanted=int.Parse(tokens[2]);int index=-1;
    for(int i=0;i<c.comboBox.Items.Count;i++)if(((DataStore)c.comboBox.Items[i]).ValueAsInt==wanted){index=i;break;}
    if(!c.Enabled || index<0){Console.WriteLine("selection-unavailable:"+tokens[1]+":"+wanted+":enabled="+c.Enabled);Dump(stage+"-unavailable",u);break;}
    c.comboBox.SelectedIndex=index;
    typeof(ComboBoxAddEdit).GetMethod("comboBox_SelectionChangeCommitted",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(c,new object[]{c.comboBox,EventArgs.Empty});
   }
   else if(command=="validate-controls")Console.WriteLine("validation:"+form.ValidateChildren());
   else if(command=="write-timer")timer.DataBindings["TimerValue"].WriteValue();
   else if(command=="write-group")controls[tokens[1]].comboBox.DataBindings["SelectedValue"].WriteValue();
   else if(command=="read-timer")timer.DataBindings["TimerValue"].ReadValue();
   else if(command=="enumerate")Validate(u,u.GetKeyFunctionGroups(),"widgets");
   else if(command=="supplied") {
    var groups=new List<CBusGroup>();
    foreach(string item in tokens[1].Split(','))if(item.Length!=0){var pair=item.Split('/');var app=u.Network.GetApplicationByAddress(int.Parse(pair[0]));var group=app.GetGroupByAddress(int.Parse(pair[1]));if(group==null)throw new Exception("Missing supplied owned cache group "+item);groups.Add(group);}
    Validate(u,groups,"supplied");
   }
   else if(command=="save")typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});
   else if(command=="crc")typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);
   else if(command!="observe")throw new ArgumentException("Unknown action "+command);
   Dump(stage+"-immediate",u);if(form!=null)Application.DoEvents();Dump(stage+"-pumped",u);Observed(stage,u,controls,timer);
  }
 }
 [STAThread] static void Main(string[] args) {
  // model|controls|controls-early SPEC VALUES OVERRIDES ACTIONS CACHEMODE
  if(args.Length!=6 || (args[0]!="model" && args[0]!="controls" && args[0]!="controls-early"))throw new ArgumentException("model|controls|controls-early SPEC VALUES OVERRIDES ACTIONS CACHEMODE");
  Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
  Console.WriteLine("runtime:"+Environment.Version+":"+IntPtr.Size);
  foreach(var assembly in new[]{typeof(object).Assembly,typeof(Form).Assembly,typeof(Enumerable).Assembly,typeof(EDLTUnit).Assembly,typeof(TimerSelector).Assembly}){string path=assembly.Location;using(var stream=File.OpenRead(path))using(var sha=SHA256.Create())Console.WriteLine("runtime-file\t"+assembly.FullName+"\t"+path+"\t"+BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant()+"\t"+FileVersionInfo.GetVersionInfo(path).FileVersion);}
  EDLTUnit u=null;string stage="setup";
  try {
   PPAttribute.bInitialiseMode=true;
   u=new EDLTUnit("OWNED","254","20","owned-id",true,Cache(args[5]));
   u.UnitType="KEYGL5";u.FirmwareVersion="5.5.00";u.CatalogNumber="5055EDL";
   foreach(string line in File.ReadAllLines(args[2])){int split=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});}
   string xml=File.ReadAllText(args[1]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
   foreach(string line in File.ReadAllLines(args[3])){int split=line.IndexOf('\t');u.GetPPAttribute(line.Substring(0,split)).Value=line.Substring(split+1);}
   Dump("input",u);stage="afterload";u.AfterLoadPPData();Dump(stage+"-immediate",u);stage="afterload-observation";Observed("afterload",u,null,null);
   // Original AfterLoad resets bInitialiseMode=false. Controls are loaded on that real model.
   if(args[0]=="model") {stage="model-actions";RunActions(u,args[4],null,null,null);}
   else using(var f=new Form())using(var box=new GroupBox())using(var source=new BindingSource())using(var timer=new TimerSelector()) {
    stage="controls-setup";source.DataSource=args[0]=="controls-early"?(object)u:(object)typeof(EDLTUnit);
    Console.WriteLine("binding-harness:"+args[0]);
    var controls=new Dictionary<string,ComboBoxAddEdit>();
    // Original groupBox12 collection order: Corridor, Office, Link, inert labels, Timer.
    f.Width=550;f.Height=240;box.Dock=DockStyle.Fill;f.Controls.Add(box);
    timer.CustomFormat="H:mm:ss";timer.Format=DateTimePickerFormat.Custom;
    timer.DataBindings.Add(new Binding("TimerValue",source,"CorridorLinkingCorridorTime",true));
    timer.MaxValue=64800;timer.MinValue=60;timer.ShowUpDown=true;timer.TimerValue=60;timer.Value=new DateTime(1753,1,1,0,1,0,0);
    timer.Top=110;timer.TabIndex=7;
    foreach(string role in new[]{"Corridor","Office","Link"}) {
     var control=new ComboBoxAddEdit();control.DataBindingPropertyName="CorridorLinking"+role+"Group";
     control.DataType=null;control.Top=25*(controls.Count+1);control.TabIndex=role=="Corridor"?5:role=="Office"?3:1;box.Controls.Add(control);controls.Add(role,control);
    }
    box.Controls.Add(timer);
    // Original FrmBaseUnit assigns the loaded unit before SetUpControls.
    if(args[0]=="controls")source.DataSource=u;
    Dump("timer-source-assigned",u);
    // Same recursive SetUpControls traversal ordering; no original FrmBaseUnit instantiation/I/O.
    foreach(string role in new[]{"Corridor","Office","Link"}){controls[role].DataBindingObject=u;Dump("binding-"+role,u);}
    Observed("controls-before-show",u,controls,timer);f.Show();Dump("controls-shown-immediate",u);Application.DoEvents();Observed("controls-shown",u,controls,timer);
    stage="controls-actions";RunActions(u,args[4],f,controls,timer);
    f.Close();
   }
   Console.WriteLine("complete:true");
  } catch(Exception error){Console.WriteLine("failure-stage:"+(ActiveStage??stage));Console.WriteLine("failure:"+error);if(u!=null)Dump("partial",u);Environment.ExitCode=1;}
 }
}
