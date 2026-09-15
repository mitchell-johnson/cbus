// Owned original-model/control research. No FrmBaseUnit constructor, communicator or physical I/O.
using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.Serialization;
using System.Security.Cryptography;
using System.Xml.Linq;
using System.Windows.Forms;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units.EDLT.WidgetData.BaseObjects;
using CBusLogicModel.CBusObjects;
using eDLT;
using eDLT.Controls.PPControls;
using eDLT.WidgetPanels;
using eDLT.WidgetPanels.baseWidgePanels;
using eDLT.Controls.SceneManagerControls;
class NativeEdltApplicationPhasesProbe {
 static string Stage="setup",Id="";
 static T Bare<T>(){return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static string B64(string value){return Convert.ToBase64String(Encoding.UTF8.GetBytes(value??""));}
 static string Get(Dictionary<string,string> c,string key,string fallback=""){return c.ContainsKey(key)?c[key]:fallback;}
 static int Num(Dictionary<string,string> c,string key,int fallback=0){return int.Parse(Get(c,key,fallback.ToString()));}
 static bool Flag(Dictionary<string,string> c,string key){return Get(c,key)=="true";}
 static void Log(string kind,string text){Console.WriteLine(kind+"\t"+Stage+"\t"+B64(text));}
 static void Set(EDLTUnit u,string key,int value){u.GetPPAttribute(key).ValueAsInt=value;}
 static string W(int n,int b){return "Widget"+n+(b==0?"WidgetType":"WidgetByteValue"+b);}
 static CBusNetwork Cache(Dictionary<string,string> c){
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();n.Languages=new BindingList<CBusLanguage>();
  n.ProjectImages=new List<KeyValuePair<string,Image>>();n.DLTP=new List<KeyValuePair<int,Image>>();n.ProjectName="OWNED";n.NetworkAddress="254";
  n.bContinue=false;CBusApplication.bAdd=false;CBusApplication.AutoAddGroupsMessageShown=true;
  foreach(string text in Get(c,"application_order").Split(new[]{','},StringSplitOptions.RemoveEmptyEntries)){
   int address=int.Parse(text);var a=new CBusApplication(n){AddressAsInt=address,TagName="Owned app "+address,bContinue=false};n.Applications.Add(a);
   foreach(int group in new[]{0,1,2,7,12,42,254}){
    if(Flag(c,"missing_trigger_group")&&address==202&&group==42)continue;
    if(Flag(c,"missing_target_group")&&address==56&&group==7)continue;
    if(Get(c,"target_group_present")=="false"&&address==136&&group==7)continue;
    a.Groups.Add(new CBusGroup(a,"App "+address+" group "+group,group));
   }
   foreach(var g in a.Groups){
    g.bContinue=false;g.TagsDLTAll=new BindingList<TagDLT>();
    foreach(var tag in g.TagsDLT){tag.TagType="TEXT";tag.TagValue="App "+address+" group "+g.AddressAsInt+" label "+tag.Variant;tag.LanguageID="1";g.TagsDLTAll.Add(tag);}g.PopulateDynamicAll();
    foreach(int level in new[]{0,1,2,42,254,255}){
     if(Flag(c,"missing_action_level")&&address==202&&g.AddressAsInt==42&&level==2)continue;
     var l=new CBusLevel(g,"Owned level "+level,level);foreach(var tag in l.TagsDLT){tag.TagType="TEXT";tag.TagValue="Owned action "+level;tag.LanguageID="1";l.TagsDLTAll.Add(tag);}l.PopulateDynamicAll();g.Levels.Add(l);
    }
   }
  }
  n.addApplicationEvent+=delegate(string a,out string output){output="";Log("metadata-request","application "+a);throw new Exception("UNEXPECTED ADD APPLICATION "+a);};
  n.addGroupEvent+=delegate(string a,string g,out string output){output="";Log("metadata-request","group "+a+"/"+g);throw new Exception("UNEXPECTED ADD GROUP "+a+"/"+g);};
  n.addLevelEvent+=delegate(string a,string g,string l,out string output){output="";Log("metadata-request","level "+a+"/"+g+"/"+l);throw new Exception("UNEXPECTED ADD LEVEL "+a+"/"+g+"/"+l);};
  return n;
 }
 static void Dump(EDLTUnit u){
  foreach(var p in u.PPAttributes)Console.WriteLine("pp\t"+Stage+"\t"+p.Name+"\t"+B64(p.Value));
  if(u.Scenes!=null)foreach(var scene in u.Scenes){
   var flags=BindingFlags.Instance|BindingFlags.NonPublic;
   Log("scene-object",scene.SceneIndex+"|variant="+scene.PriSecApplication+"|trigger="+typeof(EDLTScene).GetField("_triggerGroup",flags).GetValue(scene)+"|action="+typeof(EDLTScene).GetField("_actionSelector",flags).GetValue(scene)+"|name="+scene.NameIndex+"|items="+string.Join(",",scene.Items.Select(i=>i.Group==null?"null":i.Group.Application.AddressAsInt+"/"+i.Group.AddressAsInt)));
  }
 }
 static void CacheDump(CBusNetwork n){
  foreach(var a in n.Applications){Log("cache-app",a.AddressAsInt+"|"+a.TagName+"|"+a.bContinue);
   foreach(var g in a.Groups)Log("cache-group",a.AddressAsInt+"|"+g.AddressAsInt+"|"+g.TagName+"|"+g.bContinue+"|levels="+string.Join(",",g.Levels.Select(l=>l.AddressAsInt))+"|labels="+string.Join(",",g.DynamicAll.Select(d=>d.Name)));
  }
 }
 static void Lists(EDLTUnit u){
  Log("list-primary",string.Join("|",u.PrimaryApplication.DataSource.Select(d=>d.ValueAsInt+"="+d.FormattedDisplay)));
  Log("list-secondary",string.Join("|",u.SecondaryApplication.DataSource.Select(d=>d.ValueAsInt+"="+d.FormattedDisplay)));
  Log("list-primsec",string.Join("|",u.PrimSecApplication.Select(d=>d.ValueAsInt+"="+d.FormattedDisplay))+";events="+u.PrimSecApplication.RaiseListChangedEvents);
 }
 static void ControlDump(Control root){
  foreach(Control child in root.Controls){var combo=child as ComboBox;if(combo!=null)Log("combo",combo.Name+"|index="+combo.SelectedIndex+"|value="+(combo.SelectedValue??"null")+"|enabled="+combo.Enabled+"|visible="+combo.Visible+"|choices="+string.Join(",",combo.Items.Cast<object>().Select(x=>x is DataStore?((DataStore)x).Value+"="+((DataStore)x).Name:x.ToString())));ControlDump(child);}
 }
 static void Overrides(EDLTUnit u,Dictionary<string,string> c){
  Set(u,"PrimaryApplication",Num(c,"primary"));Set(u,"SecondaryApplication",Num(c,"secondary"));
  if(c.ContainsKey("widget_type")){
   int n=Num(c,"widget_number",6);for(int i=6;i<n;i++)Set(u,W(i,0),0);
   Set(u,W(n,0),Num(c,"widget_type"));Set(u,W(n,1),Num(c,"widget_control",Num(c,"application_variant")<<7));Set(u,W(n,6),Num(c,"group",7));
   Set(u,W(n,7),10);Set(u,W(n,8),23);
   if(c.ContainsKey("visible_widget")){int visible=Num(c,"visible_widget");Set(u,W(visible,0),2);Set(u,W(visible,1),0);Set(u,W(visible,6),Num(c,"group",7));}
   if(c.ContainsKey("same_group_other_application_restore")){Set(u,W(7,0),2);Set(u,W(7,1),0);Set(u,W(7,6),Num(c,"group",7));Set(u,"Widget7RestoreLevel",Num(c,"same_group_other_application_restore"));}
  }
  if(c.ContainsKey("bound_global_group")){
   string name=c["bound_global_group"];if(name=="PrimaryApplicationGroups")Set(u,"DynamicGroup",Num(c,"group",7));else Set(u,name,Num(c,"group",7));
  }
  if(c.ContainsKey("proximity_mode"))Set(u,"ProximityMode",Num(c,"proximity_mode"));
  if(c.ContainsKey("scene_variant")){
   int[] b=Enumerable.Repeat(255,232).ToArray();int[] entry={3,1,42,2,26,241,12,123};Array.Copy(entry,b,8);Set(u,"SceneCount",0);Set(u,"Scene1StartAddress",0);
   if(Get(c,"scene_ui_current")=="false"){entry[0]=2;entry[3]=1;Array.Copy(entry,0,b,8,8);Set(u,"SceneCount",1);Set(u,"Scene2StartAddress",8);}
   u.GetPPAttribute("SceneBucket").Value=string.Join(" ",b.Select(v=>"0x"+v.ToString("x")));
  }
 }
 static ComboBoxAddEdit BindApp(Form host,EDLTUnit u,string field,int y){
  var control=new ComboBoxAddEdit();control.Name=field;control.comboBox.Name=field+"Combo";control.DataBindingPropertyName=field;control.DataType="Application";control.Top=y;host.Controls.Add(control);control.DataBindingObject=u;return control;
 }
 static void Dependencies(Form host,EDLTUnit u,Dictionary<string,string> c){
  if(c.ContainsKey("widget_type")){
   int n=Num(c,"visible_widget",Num(c,"widget_number",6));var widget=u.Widgets[n-1];BaseWidget panel=null;
   switch(widget.WidgetType){case 2:panel=new LightingWidget(u);break;case 3:panel=new ShutterRelayWidget(u);break;case 4:panel=new FanControlWidget(u);break;case 5:panel=new TimerWidget(u);break;case 14:panel=new EnableWidget(u);break;case 15:panel=new RCAWidget(u);break;case 16:panel=new MultiLevelWidget2(u);break;}
   if(panel!=null){panel.Top=90;host.Controls.Add(panel);panel.SetWidgetData(widget);Log("composition","Original "+panel.GetType().FullName+" for widget "+n);}else Log("composition","No dependent app/group panel for surviving type "+widget.WidgetType);
  }
  if(c.ContainsKey("scene_variant")){
   var manager=new SceneManager();manager.Top=90;host.Controls.Add(manager);manager.cBusEDLTUnitBindingSource.DataSource=u;if(Get(c,"scene_ui_current")=="false")manager.scenesBindingSource.Position=1;Log("composition","Original SceneManager with owned host; original FrmBaseUnit absent");
  }
  if(c.ContainsKey("bound_global_group")){
   string name=c["bound_global_group"];
   if(name=="PrimaryApplicationGroups"){var page=new PageWidget(u);page.Top=90;host.Controls.Add(page);page.SetWidgetData(u.PageWidget);Log("composition","Original PageWidget");}
   else{var group=new ComboBoxAddEdit();group.Name=name;group.comboBox.Name=name+"Combo";group.DataBindingPropertyName=name;group.DataType="Group";group.Top=90;host.Controls.Add(group);group.DataBindingObject=u;Log("composition","Original global ComboBoxAddEdit "+name+"; original outer radio/container bindings excluded");}
  }
 }
 static bool Action(string action,EDLTUnit u,ComboBoxAddEdit primary,ComboBoxAddEdit secondary,string mode){
  var words=action.Split(',');string kind=words[0];if(kind=="bind-only")return true;string field=words[1]=="primary"?"PrimaryApplication":"SecondaryApplication";int value=int.Parse(words[2]);
  if(kind=="ui-commit"){
   if(mode=="model"){var logic=field=="PrimaryApplication"?u.PrimaryApplication:u.SecondaryApplication;if(!logic.DataSource.Any(d=>d.ValueAsInt==value)){Log("action-unavailable",field+"="+value);return false;}Log("action-projection","Original wrapper setter counterpart of an available UI choice; no UI constructed");logic.PPAttributeValue=value;return true;}
   var c=field=="PrimaryApplication"?primary:secondary;int index=-1;for(int i=0;i<c.comboBox.Items.Count;i++)if(((DataStore)c.comboBox.Items[i]).ValueAsInt==value){index=i;break;}
   if(index<0){Log("action-unavailable",field+"="+value);return false;}
   c.comboBox.SelectedIndex=index;typeof(ComboBoxAddEdit).GetMethod("comboBox_SelectionChangeCommitted",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(c,new object[]{c.comboBox,EventArgs.Empty});
  }else if(kind=="logic-set"){(field=="PrimaryApplication"?u.PrimaryApplication:u.SecondaryApplication).PPAttributeValue=value;}
  else if(kind=="raw-set")Set(u,field,value);else throw new Exception("Unknown owned action "+kind);
  return true;
 }
 static void One(string[] args,Dictionary<string,string> c){
  EDLTUnit u=null;Form host=null;Stage="setup";Console.WriteLine("case\t"+Id+"\t"+args[3]);
  try{
   PPAttribute.bInitialiseMode=true;u=new EDLTUnit("OWNED","254","20","owned-id",true,Cache(c));u.UnitType="KEYGL5";u.FirmwareVersion="5.5.00";u.CatalogNumber="5055EDL";
   foreach(string line in File.ReadAllLines(args[1])){int i=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,i),Value=line.Substring(i+1)});}
   string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));Overrides(u,c);Stage="raw-input";Dump(u);CacheDump(u.Network);
   Stage="after-original-load";u.AfterLoadPPData();Dump(u);PPAttribute.bInitialiseMode=false;
   foreach(var p in u.PPAttributes){var observed=p;p.PropertyChanged+=(s,e)=>Log("pp-event",observed.Name+"|"+e.PropertyName);}
   u.PropertyChanged+=(s,e)=>Log("unit-event",e.PropertyName);
   u.PrimaryApplication.PropertyChanged+=(s,e)=>Log("wrapper-event","primary|"+e.PropertyName);u.SecondaryApplication.PropertyChanged+=(s,e)=>Log("wrapper-event","secondary|"+e.PropertyName);
   u.PrimaryApplication.DataSource.ListChanged+=(s,e)=>Log("list-event","primary|"+e.ListChangedType);u.SecondaryApplication.DataSource.ListChanged+=(s,e)=>Log("list-event","secondary|"+e.ListChangedType);
   Stage="populate-primsec";u.PopulatePrimarySecondaryApplication();Dump(u);Lists(u);
   ComboBoxAddEdit primary=null,secondary=null;
   if(args[3]!="model"){
    Stage="before-bind";Dump(u);host=new Form();host.Width=1000;host.Height=900;primary=BindApp(host,u,"PrimaryApplication",5);secondary=BindApp(host,u,"SecondaryApplication",40);
    if(args[3]=="dependent"){Stage="dependent-setup";Dependencies(host,u,c);}
    Stage="after-bind";host.Show();Application.DoEvents();Dump(u);Lists(u);ControlDump(host);
   }
   int step=0;foreach(string action in Get(c,"actions","bind-only").Split(';')){
    Stage="action"+(step++);bool applied=Action(action,u,primary,secondary,args[3]);Dump(u);
    Stage+="-event-pump";if(host!=null)Application.DoEvents();Dump(u);Lists(u);if(host!=null)ControlDump(host);if(!applied)break;
   }
   Stage="validation";if(host!=null){Log("validate",host.Validate().ToString());Application.DoEvents();}Dump(u);Lists(u);
   // Deliberately omit dependency getters: this is the two-application-control composition.
   Stage="original-save";typeof(EDLTUnit).GetMethod("BeforeSavePPData",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,new object[]{true,false});Dump(u);
   Stage="crc";typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);Dump(u);Console.WriteLine("complete\ttrue");
  }catch(Exception e){Log("failure",e.ToString());if(u!=null)Dump(u);Console.WriteLine("complete\tfalse");}
  finally{if(host!=null)try{host.Close();host.Dispose();}catch(Exception e){Log("cleanup-failure",e.ToString());}}
  Console.WriteLine("endcase\t"+Id);
 }
 [STAThread]static void Main(string[] args){
  Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
  Console.WriteLine("runtime\t"+Environment.Version+"\t"+IntPtr.Size);
  foreach(var assembly in new[]{typeof(object).Assembly,typeof(Form).Assembly,typeof(Enumerable).Assembly,typeof(EDLTUnit).Assembly,typeof(ComboBoxAddEdit).Assembly}){string path=assembly.Location;using(var stream=File.OpenRead(path))using(var sha=SHA256.Create())Console.WriteLine("runtime-file\t"+assembly.FullName+"\t"+path+"\t"+BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant()+"\t"+FileVersionInfo.GetVersionInfo(path).FileVersion);}
  foreach(string line in File.ReadAllLines(args[2])){var words=line.Split('\t');Id=words[0];var c=new Dictionary<string,string>();foreach(string word in words.Skip(1)){int i=word.IndexOf('=');c.Add(word.Substring(0,i),word.Substring(i+1));}One(args,c);}
 }
}
