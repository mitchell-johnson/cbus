// Runs unchanged original model, linked LevelControl and ComboBoxAddEdit in an owned Xvfb.
using System;
using System.Linq;
using System.IO;
using System.Xml.Linq;
using CBusLogicModel.Units;
using System.Collections.Generic;
using System.ComponentModel;
using System.Reflection;
using System.Runtime.Serialization;
using System.Windows.Forms;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
using eDLT.Controls;
using eDLT.Controls.PPControls;
class NativeEdltQuickStatusProbe {
 static EDLTUnit Unit(int mode=0,int colour=8,int low=85,int high=170) {
  var u=(EDLTUnit)FormatterServices.GetUninitializedObject(typeof(EDLTUnit));u.PPAttributes=new BindingList<PPAttribute>();
  typeof(EDLTUnit).GetField("commonConstants",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(u,new CommonConstants());
  foreach(var pair in new[]{new object[]{"QuickStatusMode",mode},new object[]{"QuickStatusColour1",colour},new object[]{"QuickStatusColour2",7},new object[]{"QuickStatusColour3",3},new object[]{"QuickStatusLevel1",low},new object[]{"QuickStatusLevel2",high},new object[]{"QuickStatusGroup",255}})
   u.PPAttributes.Add(new PPAttribute{Name=(string)pair[0],Value=pair[1].ToString()});
  return u;
 }
 [STAThread] static void Main(string[] args) {
  PPAttribute.bInitialiseMode=false;
  if(args.Length==9) {
   PPAttribute.bInitialiseMode=true;
   var u=Unit();u.PPAttributes.Clear();u.Widgets=new BindingList<EDLTWidget>();u.Scenes=new BindingList<EDLTScene>();u.StaticLabels=new BindingList<DataStore>();
   foreach(var line in File.ReadAllLines(args[1])){int split=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,split),Value=line.Substring(split+1)});}
   for(int n=1;n<=21;n++)u.Widgets.Add(new EDLTWidget(u,n,u.PPAttributes));u.InitializeMRAGlobalValues();PPAttribute.bInitialiseMode=false;
   if(args[2]!="keep")u.QuickStatusMode=int.Parse(args[2]);
   // Numeric group assignment intentionally bypasses cached lookup/creation.
   if(args[3]!="keep")u.GetPPAttribute("QuickStatusGroup").ValueAsInt=int.Parse(args[3]);
   using(var f=new Form())using(var low=new LevelControl())using(var high=new LevelControl()) {
    low.MaxLevel=254;high.MinLevel=1;low.SetHigherLevelControl(high);high.SetLowerLevelControl(low);
    f.Controls.Add(low);f.Controls.Add(high);high.Top=50;
    low.DataBindings.Add(new Binding("Value",u,"QuickStatusLevel1",true));high.DataBindings.Add(new Binding("Value",u,"QuickStatusLevel2",true));
    f.Show();Application.DoEvents();
    if(args[4]!="keep")low.SetValue(int.Parse(args[4]));if(args[5]!="keep")high.SetValue(int.Parse(args[5]));Application.DoEvents();f.Close();
   }
   if(args[6]!="keep")u.QuickStatusColour1=int.Parse(args[6]);if(args[7]!="keep")u.QuickStatusColour2=int.Parse(args[7]);if(args[8]!="keep")u.QuickStatusColour3=int.Parse(args[8]);
   typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});
   string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
   typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);
   foreach(var p in u.PPAttributes)Console.WriteLine("pp:"+p.Name+"\t"+p.Value);return;
  }
  var constants=new CommonConstants();
  foreach(var name in new[]{"QuickStatus","ScreenColours","KeyColours"}) {
   var list=(List<DataStore>)typeof(CommonConstants).GetProperty(name).GetValue(constants,null);
   Console.WriteLine("choices:"+name+":"+string.Join("|",list.Select(d=>d.ValueAsInt+"="+d.Name)));
  }
  foreach(int initial in new[]{0,1,2,3,7})foreach(int target in new[]{0,1,2,3})foreach(int colour in new[]{0,3,8}) {
   var u=Unit(initial,colour);
   using(var f=new Form())using(var bs=new BindingSource())using(var colours=new BindingSource())using(var combo=new ComboBox()) {
    bs.DataSource=u;colours.DataMember="QuickStatusColours";colours.DataSource=bs;
    combo.DropDownStyle=ComboBoxStyle.DropDownList;
    combo.DataBindings.Add(new Binding("SelectedValue",bs,"QuickStatusColour1",true));
    combo.DataSource=colours;combo.DisplayMember="FormattedDisplay";combo.ValueMember="ValueAsInt";
    f.Controls.Add(combo);f.Show();Application.DoEvents();
    string before=u.QuickStatusColour1+","+combo.SelectedIndex+","+combo.SelectedValue;
    u.QuickStatusMode=target;Application.DoEvents();
    string after=u.QuickStatusColour1+","+combo.SelectedIndex+","+combo.SelectedValue;
    string validation="ok";try { f.Validate();combo.DataBindings["SelectedValue"].WriteValue(); } catch(Exception e) { validation=e.GetType().Name; } Application.DoEvents();
    Console.WriteLine("palette:"+initial+","+target+","+colour+":"+before+":"+after+":"+u.QuickStatusColour1+","+combo.SelectedIndex+","+combo.SelectedValue+":validation="+validation+":model-choices="+string.Join(",",u.QuickStatusColours.Select(d=>d.ValueAsInt))+":choices="+string.Join(",",combo.Items.Cast<DataStore>().Select(d=>d.ValueAsInt)));
    f.Close();
   }
  }
  foreach(var addresses in new[]{new int[]{42,7},new int[]{255,0,254,7},new int[0]})foreach(int initial in new[]{7,99,255}) {
   var cache=new CachedGroupFixture(addresses);var u=Unit();u.Network=cache.Network;var p=u.GetPPAttribute("QuickStatusGroup");p.ValueAsInt=initial;u.QuickStatusGroup=cache.Bind(p,-1);
   using(var f=new Form())using(var c=new ComboBoxAddEdit()) {
    c.DataBindingPropertyName="QuickStatusGroup";c.DataBindingObject=u;f.Controls.Add(c);f.Show();Application.DoEvents();
    Console.WriteLine("group:"+string.Join(",",addresses)+":"+initial+":pp="+p.ValueAsInt+":enabled="+c.Enabled+":selected="+c.comboBox.SelectedValue+":choices="+string.Join(",",c.comboBox.Items.Cast<DataStore>().Select(d=>d.ValueAsInt)));
    f.Close();
   }
  }
  foreach(var pair in new[]{new[]{85,170},new[]{0,1},new[]{254,255},new[]{85,85},new[]{0,0},new[]{255,255},new[]{170,85}})
  foreach(var requested in new[]{new[]{0,255},new[]{255,0},new[]{170,85},new[]{85,170},new[]{86,86},new[]{255,255},new[]{0,0}}) {
   var u=Unit(0,8,pair[0],pair[1]);
   using(var f=new Form())using(var low=new LevelControl())using(var high=new LevelControl()) {
    low.MaxLevel=254;high.MinLevel=1;low.SetHigherLevelControl(high);high.SetLowerLevelControl(low);
    f.Controls.Add(low);f.Controls.Add(high);high.Top=50;
    low.DataBindings.Add(new Binding("Value",u,"QuickStatusLevel1",true));high.DataBindings.Add(new Binding("Value",u,"QuickStatusLevel2",true));
    f.Show();Application.DoEvents();low.SetValue(requested[0]);high.SetValue(requested[1]);Application.DoEvents();
    Console.WriteLine("levels:"+string.Join(",",pair)+":"+string.Join(",",requested)+":"+u.QuickStatusLevel1+","+u.QuickStatusLevel2);
    f.Close();
   }
  }
  foreach(var pair in new[]{new[]{85,170},new[]{0,1},new[]{254,255},new[]{85,85},new[]{0,0},new[]{255,255},new[]{170,85}})
  foreach(int which in new[]{0,1})foreach(int requested in new[]{-1,0,1,84,85,86,169,170,171,254,255,256}) {
   using(var f=new Form())using(var low=new LevelControl())using(var high=new LevelControl()) {
    var u=Unit(0,8,pair[0],pair[1]);var events=new List<string>();
    low.MaxLevel=254;high.MinLevel=1;low.SetHigherLevelControl(high);high.SetLowerLevelControl(low);
    f.Controls.Add(low);f.Controls.Add(high);high.Top=50;low.Visible=true;high.Visible=true;
    low.DataBindings.Add(new Binding("Value",u,"QuickStatusLevel1",true));high.DataBindings.Add(new Binding("Value",u,"QuickStatusLevel2",true));
    f.Show();Application.DoEvents();
    var before=low.Value+","+high.Value+","+u.QuickStatusLevel1+","+u.QuickStatusLevel2;
    low.ValueChanged+=(o,e)=>events.Add("L"+low.Value);high.ValueChanged+=(o,e)=>events.Add("H"+high.Value);
    (which==0?low:high).SetValue(requested);Application.DoEvents();
    Console.WriteLine("single:"+pair[0]+","+pair[1]+","+which+","+requested+":"+before+":"+low.Value+","+high.Value+","+u.QuickStatusLevel1+","+u.QuickStatusLevel2+":"+string.Join("|",events));
    f.Close();
   }
  }
 }
}
