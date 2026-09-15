// Research-only owned original model/control probe. No production implementation.
using System;using System.IO;using System.Linq;using System.Collections.Generic;
using System.ComponentModel;using System.Drawing;using System.Reflection;
using System.Runtime.Serialization;using System.Xml.Linq;using System.Windows.Forms;
using CBusLogicModel;using CBusLogicModel.Utilities;using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;using CBusLogicModel.CBusObjects;
class NativeEdltBlankProbe {
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

 static void Dump(string stage,EDLTUnit u){Console.WriteLine("flag:"+stage+":"+PPAttribute.bInitialiseMode);foreach(var p in u.PPAttributes)Console.WriteLine("pp:"+stage+":"+p.Name+"\t"+p.Value+"\tdirty="+p.HasBeenChanged);}
 static void Require(bool b,string s){if(!b)throw new Exception(s);}
 static object Call(object o,string name,params object[] args){return o.GetType().GetMethod(name,BindingFlags.Instance|BindingFlags.NonPublic).Invoke(o,args);}
 [STAThread] static void Main(string[] args){EDLTUnit u=null;string stage="setup";
  using(var deadline=new System.Threading.Timer(delegate{Console.WriteLine("fatal:whole-probe-deadline");Console.Out.Flush();Environment.Exit(4);},null,30000,System.Threading.Timeout.Infinite))try{
   Require(args.Length==5,"SPEC VALUES OVERRIDES MODE DETAIL");PPAttribute.bInitialiseMode=true;
   u=new EDLTUnit("OWNED","254","20","owned-id",true,Cache("complete"));u.UnitType="KEYGL5";u.FirmwareVersion="5.5.00";u.CatalogNumber="5055EDL";
   foreach(string line in File.ReadAllLines(args[1])){int i=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,i),Value=line.Substring(i+1)});}
   string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
   foreach(string line in File.ReadAllLines(args[2])){int i=line.IndexOf('\t');u.GetPPAttribute(line.Substring(0,i)).Value=line.Substring(i+1);}
   foreach(var p in u.PPAttributes)p.HasBeenChanged=false;
   if(args[3]=="defaults"){
    if(args[4]=="pre-dirty"){u.GetPPAttribute("UnitAddress").HasBeenChanged=true;u.GetPPAttribute("ActivityDuration").HasBeenChanged=true;u.GetPPAttribute("StaticTextString0").HasBeenChanged=true;}
    if(args[4]=="missing-pp")u.PPAttributes.Remove(u.GetPPAttribute("ActivityDuration"));
    if(args[4]=="missing-default")u.UnitSpec.Descendants("Param").First(p=>(string)p.Element("Name")=="ActivityDuration").Element("DefaultValue").Remove();
    Dump("input",u);Console.WriteLine("db-name-before:"+Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(u.UnitName??"")));
    stage="original-reset-defaults";bool result=u.ResetToDefaults();Dump("after-defaults",u);Console.WriteLine("reset-return:"+result);
    Console.WriteLine("db-name-after:"+Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(u.UnitName??"")));
   }else if(args[3]=="blank"){
    Dump("input",u);stage="original-afterload";u.AfterLoadPPData();Dump("after-load",u);
    int index=int.Parse(args[4]);Require(index>=1&&index<=21,"widget bound");var widget=u.Widgets[index-1];var scenes=u.Scenes.ToArray();var models=u.Widgets.ToArray();var previous=widget.WidgetData;
    stage="original-bound-setup";var constants=new CommonConstants();
    using(var host=new Form())using(var combo=new ComboBox())using(var source=new BindingSource()){
     combo.DropDownStyle=ComboBoxStyle.DropDownList;combo.FormattingEnabled=true;combo.DisplayMember="FormattedDisplay";combo.ValueMember="ValueAsInt";
     combo.DataSource=index<6?(index==5?constants.WidgetTypesTimeOutNo2Slice:constants.WidgetTypesTimeOut):constants.WidgetTypesFunctionPages;
     Console.WriteLine("original-choices:"+string.Join(",",(index<6?(index==5?constants.WidgetTypesTimeOutNo2Slice:constants.WidgetTypesTimeOut):constants.WidgetTypesFunctionPages).Select(x=>x.ValueAsInt)));source.DataSource=widget;combo.DataBindings.Add(new Binding("SelectedValue",source,"WidgetType",true,DataSourceUpdateMode.OnPropertyChanged));host.Controls.Add(combo);
     host.Show();Application.DoEvents();Dump("after-bind",u);Console.WriteLine("selection-before:"+combo.SelectedValue);
     stage="original-bound-select-blank";combo.SelectedValue=0;Application.DoEvents();Dump("after-select",u);Console.WriteLine("selection-after:"+combo.SelectedValue);
     Require(widget.WidgetType==0,"bound selection did not set Blank");
     Console.WriteLine("retained-scene-identities:"+scenes.Select((s,i)=>Object.ReferenceEquals(s,u.Scenes[i])).All(b=>b));
     Console.WriteLine("retained-widget-identities:"+models.Select((s,i)=>Object.ReferenceEquals(s,u.Widgets[i])).All(b=>b));
     Console.WriteLine("selected-data-identity-retained:"+Object.ReferenceEquals(previous,widget.WidgetData));
     stage="original-before-save";Call(u,"BeforeSavePPData",true,false);Dump("before-save",u);
     stage="original-crc";typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);Dump("final",u);host.Close();
    }
   }else throw new Exception("unknown stage");
   Console.WriteLine("complete:true:physical=false:native-database=false:full-form=false");
  }catch(Exception e){Console.WriteLine("failure-stage:"+stage);Console.WriteLine("failure:"+e);if(u!=null)Dump("partial",u);Environment.ExitCode=1;}
 }
}
