// Owned retained-model/SceneManager research; original assemblies are unchanged.
using System;using System.IO;using System.Linq;using System.Collections.Generic;
using System.ComponentModel;using System.Drawing;using System.Reflection;
using System.Runtime.Serialization;using System.Runtime.CompilerServices;using System.Xml.Linq;
using System.Windows.Forms;using System.Net;using System.Net.Sockets;using System.Threading;
using CBusLogicModel;using CBusLogicModel.Utilities;using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;using CBusLogicModel.EDLT;using CBusLogicModel.CBusObjects;
using SharpCGateCommunicator;using eDLT.Controls.SceneManagerControls;
class NativeEdltSceneManagerValidationProbe {
 static string Stage="setup";static EDLTScene Clipboard;
 static readonly object outputLock=new object();
 static void Out(string s){lock(outputLock){Console.WriteLine(s);Console.Out.Flush();}}
 static string B64(string s){return Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(s??""));}
 static void Require(bool b,string s){if(!b)throw new Exception(s);}
 static T Bare<T>(){return (T)FormatterServices.GetUninitializedObject(typeof(T));}
 static object Field(object o,string n){var f=o.GetType().GetField(n,BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic);Require(f!=null,"missing field "+n);return f.GetValue(o);}
 static object Call(object o,string n,params object[] a){var m=o.GetType().GetMethod(n,BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic);Require(m!=null,"missing method "+n);return m.Invoke(o,a);}
 sealed class RefComparer:IEqualityComparer<object>{public new bool Equals(object a,object b){return Object.ReferenceEquals(a,b);}public int GetHashCode(object o){return RuntimeHelpers.GetHashCode(o);}}
 static readonly Dictionary<object,int> ids=new Dictionary<object,int>(new RefComparer());
 static int Id(object o){if(o==null)return 0;int id;if(!ids.TryGetValue(o,out id)){id=ids.Count+1;ids.Add(o,id);}return id;}
 static CBusNetwork Cache(){
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();n.Languages=new BindingList<CBusLanguage>();n.ProjectImages=new List<KeyValuePair<string,Image>>();n.DLTP=new List<KeyValuePair<int,Image>>();n.ProjectName="OWNED";n.NetworkAddress="254";n.bContinue=false;CBusApplication.bAdd=false;CBusApplication.AutoAddGroupsMessageShown=true;
  foreach(int app in new[]{56,57,172,202,203,255}){
   var a=new CBusApplication(n){AddressAsInt=app,TagName="Owned application "+app,bContinue=false};n.Applications.Add(a);
   foreach(int group in Enumerable.Range(0,70).Concat(new[]{254}))a.Groups.Add(new CBusGroup(a,"Owned "+app+"/"+group,group));
   foreach(var g in a.Groups){g.bContinue=false;g.TagsDLTAll=new BindingList<TagDLT>();foreach(var tag in g.TagsDLT){tag.TagType="TEXT";tag.TagValue="Owned group label "+tag.Variant;tag.LanguageID="1";g.TagsDLTAll.Add(tag);}g.PopulateDynamicAll();
    foreach(int level in new[]{0,1,2,3,4,5,6,7,42,254,255}){var l=new CBusLevel(g,"Owned level "+level,level);foreach(var tag in l.TagsDLT){tag.TagType="TEXT";tag.TagValue="Owned action "+level;tag.LanguageID="1";l.TagsDLTAll.Add(tag);}l.PopulateDynamicAll();g.Levels.Add(l);}
   }
  }
  n.addApplicationEvent+=delegate(string a,out string result){result="";throw new Exception("UNEXPECTED ADD APP "+a);};n.addGroupEvent+=delegate(string a,string g,out string result){result="";throw new Exception("UNEXPECTED ADD GROUP "+a+"/"+g);};n.addLevelEvent+=delegate(string a,string g,string l,out string result){result="";throw new Exception("UNEXPECTED ADD LEVEL "+a+"/"+g+"/"+l);};return n;
 }
 static CBusGroup Group(EDLTUnit u,int app,int group){return u.Network.Applications.Single(a=>a.AddressAsInt==app).Groups.Single(g=>g.AddressAsInt==group);}
 static void Scene(string kind,EDLTScene s){
  Out(kind+"\t"+Stage+"\t"+s.SceneIndex+"\tidentity="+Id(s)+"|variant="+Field(s,"_PriSecApplication")+"|editable="+Field(s,"_canEdit")+"|trigger="+Field(s,"_triggerGroup")+"|action="+Field(s,"_actionSelector")+"|name="+Field(s,"_nameIndex")+"|label="+Field(s,"_labelValueIndex")+"|dynamic_count="+((BindingList<DataStore>)Field(s,"_currentDynamicLabels")).Count);
  int di=0;foreach(var d in (BindingList<DataStore>)Field(s,"_currentDynamicLabels"))Out("dynamic\t"+Stage+"\t"+s.SceneIndex+"\t"+(di++)+"\t"+Id(d)+"\t"+B64(d.Name)+"\t"+B64(d.Value)+"\t"+(d.Image!=null));
  for(int i=0;i<s.Items.Count;i++){var item=s.Items[i];var g=(CBusGroup)Field(item,"_group");Out("item\t"+Stage+"\t"+s.SceneIndex+"\t"+i+"\tidentity="+Id(item)+"|group_identity="+Id(g)+"|app="+g.Application.AddressAsInt+"|group="+g.AddressAsInt+"|level="+Field(item,"_level")+"|ramp="+Field(item,"_rampRate")+"|editable="+Field(item,"_canEdit"));}
 }
 static void Dump(EDLTUnit u){Require(u.PPAttributes.Count==874,"Expected full874 fixture");Out("stage\t"+Stage);foreach(var p in u.PPAttributes)Out("pp\t"+Stage+"\t"+p.Name+"\t"+B64(p.Value)+"\t"+p.HasBeenChanged);foreach(var s in u.Scenes)Scene("scene",s);if(Clipboard!=null)Scene("clipboard",Clipboard);Out("storage\t"+Stage+"\t"+u.ScenesStorageUsedPercent);}
 static void Available(EDLTScene s){Out("available\t"+Stage+"\t"+string.Join(",",s.AvailableGroups.Select(g=>g.Application.AddressAsInt+"/"+g.AddressAsInt+"#"+Id(g))));}
 static void Step(EDLTUnit u,string name,Action action,bool expectedFull=false){Stage=name;try{action();Require(!expectedFull,"Expected capacity failure absent");}catch(SceneStorageFullException e){Require(expectedFull,"Unexpected capacity failure");Out("expected-capacity\t"+Stage+"\t"+B64(e.Message));}Dump(u);}
 static void Fixture(EDLTUnit u){
  u.GetPPAttribute("PrimaryApplication").ValueAsInt=56;u.GetPPAttribute("SecondaryApplication").ValueAsInt=57;
  int[] bucket=Enumerable.Repeat(255,232).ToArray();int[] seed={0,2,42,1,26,3,12,10,31,42,200,3,1,42,2,27,5,7,123};Array.Copy(seed,bucket,seed.Length);
  u.GetPPAttribute("SceneCount").ValueAsInt=2;for(int i=1;i<=8;i++)u.GetPPAttribute("Scene"+i+"StartAddress").ValueAsInt=i==1?0:i==2?11:255;
  u.GetPPAttribute("SceneBucket").Value=string.Join(" ",bucket.Select(n=>"0x"+n.ToString("x")));
 }
 static void ObserveValidation(EDLTUnit u){var messages=new List<string>();bool valid=u.ValidateScenes(ref messages);Out("validation\t"+Stage+"\t"+valid+"\t"+B64(string.Join("\n",messages)));}
 static bool Extra(EDLTUnit u,string name){var a=u.Scenes[0];var b=u.Scenes[1];var c=u.Scenes[2];
  if(name.StartsWith("validate-")){
   Step(u,"configured-validation",delegate{
    if(name=="validate-valid"){}
    else if(name=="validate-trigger-duplicate")b.ActionSelector=1;
    else if(name=="validate-name-duplicate")b.NameIndex=26;
    else if(name=="validate-missing-trigger")a.TriggerGroup=255;
    else if(name=="validate-missing-action")a.ActionSelector=99;
    else if(name=="validate-missing-name")a.NameIndex=255;
    else if(name=="validate-all-four"){b.ActionSelector=1;b.NameIndex=26;c.AddGroup(Group(u,56,1));}
    else if(name=="validate-shortcut-first"){a.TriggerGroup=255;a.NameIndex=255;c.TriggerGroup=42;c.ActionSelector=2;c.NameIndex=27;}
    else if(name=="validate-shortcut-second"){a.NameIndex=255;b.TriggerGroup=255;var d=u.Scenes[3];c.TriggerGroup=42;c.ActionSelector=3;c.NameIndex=28;d.TriggerGroup=42;d.ActionSelector=3;d.NameIndex=28;}
    else if(name=="validate-empty-duplicates"){a.Items.Clear();b.Items.Clear();b.ActionSelector=1;b.NameIndex=26;}
    else if(name=="validate-action255"){a.ActionSelector=255;b.ActionSelector=255;}
    else if(name=="validate-missing-action-duplicate"){a.ActionSelector=99;b.ActionSelector=99;}
    else if(name=="validate-all-empty"){foreach(var s in u.Scenes)s.CopyFrom(new EDLTScene(u,255));}
    else throw new Exception("Unknown validation case");
   });Step(u,"original-validation",delegate{ObserveValidation(u);});return true;
  }
  if(name.StartsWith("get-")){
   if(name=="get-trigger-missing-after-load")Step(u,"remove-trigger-cache",delegate{u.Network.GetApplicationByAddress(202).Groups.Remove(Group(u,202,42));});
   else if(name=="get-action-missing-after-load"||name=="get-action-zero-missing")Step(u,"remove-level-cache",delegate{var g=Group(u,202,42);g.Levels.Remove(g.Levels.Single(v=>v.AddressAsInt==1));if(name=="get-action-zero-missing")g.Levels.Remove(g.Levels.Single(v=>v.AddressAsInt==0));});
   else if(name=="get-new-missing-trigger")Step(u,"set-trigger99",delegate{a.TriggerGroup=99;});
   else if(name=="get-set-action-valid")Step(u,"set-action2",delegate{a.ActionSelector=2;});
   else if(name=="get-set-action-missing")Step(u,"set-action99",delegate{a.ActionSelector=99;});
   else if(name=="get-disabled-trigger")Step(u,"set-unused-trigger",delegate{a.TriggerGroup=255;a.ActionSelector=2;});
   else if(name=="get-output-missing-after-load")Step(u,"remove-output-cache",delegate{u.Network.GetApplicationByAddress(56).Groups.Remove(Group(u,56,12));});
   else throw new Exception("Unknown getter case");
   Step(u,"trigger-getter",delegate{Out("getter\t"+Stage+"\tTriggerGroup\t"+a.TriggerGroup);});Step(u,"action-getter",delegate{Out("getter\t"+Stage+"\tActionSelector\t"+a.ActionSelector);});Step(u,"validation-after-getters",delegate{ObserveValidation(u);});return true;
  }
  return false;
 }
 static void Model(EDLTUnit u,string name){var first=u.Scenes[0];var second=u.Scenes[1];var third=u.Scenes[2];
  if(Extra(u,name))return;
  if(name=="baseline")Step(u,"no-edit",delegate{});
  else if(name=="add-remove"){
   var original=first.Items[0];Step(u,"add-56-7",delegate{first.AddGroup(Group(u,56,7));});Step(u,"remove-original-first",delegate{Require(first.Items.Remove(original),"Original item missing");});
  }else if(name=="cross-application"){
   Available(first);Step(u,"switch-secondary",delegate{first.PriSecApplication=1;});Available(first);Step(u,"add-secondary-same-number",delegate{first.AddGroup(Group(u,57,12));});Available(first);Step(u,"switch-primary",delegate{first.PriSecApplication=0;});Available(first);
  }else if(name=="copy-paste"){
   Step(u,"copy-detached",delegate{Clipboard=new EDLTScene(u,255);Clipboard.CopyFrom(first,false);});Step(u,"change-source-after-copy",delegate{first.Items[0].Level=51;first.NameIndex=28;});Step(u,"paste-empty",delegate{Require(third.Items.Count==0,"Paste destination not empty");third.CopyFrom(Clipboard);});
  }else if(name=="clear-items")Step(u,"clear-items",delegate{first.Items.Clear();});
  else if(name=="clear-scene")Step(u,"clear-scene",delegate{var empty=new EDLTScene(u,255);first.CopyFrom(empty);});
  else if(name=="level-percent"){
   foreach(int n in new[]{-1,0,1,253,255,256}){int value=n;Step(u,"level-"+n,delegate{first.Items[0].Level=value;});Out("percent\t"+Stage+"\t"+first.Items[0].LevelAsPercent);}
   foreach(int n in new[]{-1,0,1,50,99,100,101}){int value=n;Step(u,"percent-"+n,delegate{first.Items[0].LevelAsPercent=value;});Out("percent\t"+Stage+"\t"+first.Items[0].LevelAsPercent);}
  }else if(name=="ramp")foreach(int n in new[]{0,1,15}){int value=n;Step(u,"ramp-"+n,delegate{first.Items[0].RampRate=value;});}
  else if(name=="capacity-add"){
   Step(u,"fill63",delegate{foreach(var s in u.Scenes)s.Items.Clear();for(int n=0;n<63;n++)first.AddGroup(Group(u,56,n));});Step(u,"ordered-add-until-full",delegate{foreach(int n in new[]{63,64})second.AddGroup(Group(u,57,n));},true);
  }else if(name=="capacity-paste"){
   Step(u,"fill63",delegate{foreach(var s in u.Scenes)s.Items.Clear();for(int n=0;n<4;n++)first.AddGroup(Group(u,56,n));for(int n=0;n<59;n++)second.AddGroup(Group(u,57,n));});Step(u,"copy-detached",delegate{Clipboard=new EDLTScene(u,255);Clipboard.CopyFrom(first,false);});Step(u,"partial-paste-empty",delegate{third.CopyFrom(Clipboard);},true);
  }else throw new Exception("Unknown model case");
 }
 sealed class RejectPeer:IDisposable{
  readonly TcpListener listener;readonly Thread worker;volatile bool stopping;public readonly int Port;public int Accepted,Bytes;public string Error;
  public RejectPeer(){listener=new TcpListener(IPAddress.Loopback,0);listener.Start(1);Port=((IPEndPoint)listener.LocalEndpoint).Port;worker=new Thread(Run);worker.IsBackground=true;worker.Start();Out("peer:127.0.0.1:"+Port+":reject-all=true:forwarding=false");}
  void Run(){try{while(!stopping){if(!listener.Server.Poll(100000,SelectMode.SelectRead))continue;using(var socket=listener.AcceptTcpClient()){Interlocked.Increment(ref Accepted);Require(IPAddress.IsLoopback(((IPEndPoint)socket.Client.RemoteEndPoint).Address),"non-loopback peer");socket.ReceiveTimeout=100;byte[] b=new byte[4096];try{int n=socket.GetStream().Read(b,0,b.Length);Interlocked.Add(ref Bytes,n);Out("unexpected-wire:"+BitConverter.ToString(b,0,n));}catch(IOException){}Out("unexpected-connection:true");}}}catch(Exception e){if(!stopping){Error=e.ToString();Out("peer-error:"+Error);}}}
  public void Dispose(){stopping=true;listener.Stop();Require(worker.Join(2000),"Peer thread not joined");Out("peer-cleanup:accepted="+Accepted+":bytes="+Bytes);}
 }
 static void Pin(CGateConnection c,RejectPeer p){Require(Object.ReferenceEquals(c,CGateCommunicatorFactory.GetConnection()),"Factory replaced");Require(c.IPAddrStr=="127.0.0.1"&&c.Port==p.Port&&!c.SecureSocket,"Factory endpoint changed");Require(!c.Connected&&p.Accepted==0&&p.Bytes==0&&p.Error==null,"Unexpected connection/request");Out("factory\t"+Stage+"\tretained=true|connected=false|accepted=0|bytes=0");}
 static void Stop(SceneManager m,string phase,bool dispose=false){var t=(System.Timers.Timer)Field(m,"redrawTimer");Out("timer\t"+phase+"\tenabled="+t.Enabled+"|interval="+t.Interval);Require(!t.Enabled,"Unexpected redraw timer activation");t.Stop();if(dispose)t.Dispose();}
 static void ControlStage(EDLTUnit u,SceneManager m,CGateConnection c,RejectPeer p,string stage,bool pump){Stage=stage;Require(!((CheckBox)Field(m,"cbLiveLevels")).Checked,"Live levels forbidden");Stop(m,stage);if(pump)Application.DoEvents();Stop(m,stage+"-after-pump");Dump(u);Pin(c,p);Out("control\t"+Stage+"\tcurrent="+m.scenesBindingSource.Position+"|items="+((BindingSource)Field(m,"itemsBindingSource")).Position+"|sync="+((CheckBox)Field(m,"cbSyncLevels")).Checked);}
 static void ControlCase(EDLTUnit u,SceneManager m,Form host,CGateConnection c,RejectPeer p,string name){
  host.Width=1100;host.Height=850;host.Controls.Add(m);m.Dock=DockStyle.Fill;Stop(m,"after-constructor");m.cBusEDLTUnitBindingSource.DataSource=u;ControlStage(u,m,c,p,"after-bind-before-pump",false);host.Show();ControlStage(u,m,c,p,"after-show-pump",true);
  if(name=="sync"){
   m.scenesBindingSource.Position=0;var items=(BindingSource)Field(m,"itemsBindingSource");items.Position=0;((CheckBox)Field(m,"cbSyncLevels")).Checked=true;
   var grid=(DataGridView)Field(m,"SceneItemsDataGrid");var column=grid.Columns.Cast<DataGridViewColumn>().Single(v=>v.DataPropertyName=="LevelAsPercent");grid.CurrentCell=grid.Rows[0].Cells[column.Index];Require(grid.CurrentCell.EditType==typeof(DataGridViewTextBoxEditingControl),"Unexpected percent editor");
   grid.CurrentCell.Value=50;ControlStage(u,m,c,p,"after-percent-cell-write",false);Call(m,"dataGridViewSceneItems_CellEndEdit",grid,new DataGridViewCellEventArgs(column.Index,0));ControlStage(u,m,c,p,"after-original-cell-commit",true);
  }else if(name=="copy-paste"){
   m.scenesBindingSource.Position=0;ControlStage(u,m,c,p,"copy-source-selected",true);var copy=(Button)Field(m,"btnCopy");Require(copy.Enabled,"Copy unavailable");copy.PerformClick();Clipboard=(EDLTScene)Field(m,"edltSceneCopy");Require(Clipboard!=null&&Clipboard.SceneIndex==256,"Missing detached copy");ControlStage(u,m,c,p,"after-copy",false);
   m.scenesBindingSource.Position=2;ControlStage(u,m,c,p,"empty-destination-selected",true);Require(((EDLTScene)m.scenesBindingSource.Current).Items.Count==0,"Paste modal would be required");var paste=(Button)Field(m,"btnPaste");Require(paste.Enabled,"Paste unavailable");paste.PerformClick();ControlStage(u,m,c,p,"after-paste",true);
  }else Require(name=="baseline","Unknown control case");
 }
 [STAThread]static void Main(string[] args){Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);bool complete=false;EDLTUnit u=null;SceneManager manager=null;Form host=null;RejectPeer peer=null;CGateConnection connection=null;
  using(var watchdog=new System.Threading.Timer(delegate{Out("fatal:whole-probe-deadline:45seconds");Environment.Exit(4);},null,45000,Timeout.Infinite))try{
   Require(args.Length==4,"SPEC VALUES MODEL-OR-CONTROL CASE");Require(args[2]=="model"||args[2]=="control","Unknown scope");Require(typeof(CGateCommunicatorFactory).GetField("cgateConnection",BindingFlags.Static|BindingFlags.NonPublic).GetValue(null)==null,"Preexisting factory");peer=new RejectPeer();connection=CGateCommunicatorFactory.GetConnection("127.0.0.1",peer.Port,false);Pin(connection,peer);
   PPAttribute.bInitialiseMode=true;u=new EDLTUnit("OWNED","254","20","owned-scene-id",true,Cache());u.UnitType="KEYGL5";u.FirmwareVersion="5.5.00";u.CatalogNumber="5055EDL";
   foreach(string line in File.ReadAllLines(args[1])){int i=line.IndexOf('\t');Require(i>0,"Bad PP input");u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,i),Value=line.Substring(i+1)});}string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));Fixture(u);Stage="raw-input";Dump(u);
   u.AfterLoadPPData();PPAttribute.bInitialiseMode=false;foreach(var pp in u.PPAttributes)pp.HasBeenChanged=false;var retained=u.Scenes.ToArray();Stage="after-original-load";Dump(u);Pin(connection,peer);
   if(args[2]=="model")Model(u,args[3]);else{host=new Form();manager=new SceneManager();ControlCase(u,manager,host,connection,peer,args[3]);}
   Stage="before-save";Dump(u);Pin(connection,peer);Call(u,"BeforeSavePPData",true,false);Stage="after-original-save";Dump(u);Pin(connection,peer);
   typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);Stage="after-original-crc";Dump(u);Require(retained.Select((s,i)=>Object.ReferenceEquals(s,u.Scenes[i])).All(x=>x),"Scene identity replaced");Pin(connection,peer);complete=true;
  }catch(Exception e){Out("failure-stage:"+Stage);Out("failure:"+e);if(u!=null)Dump(u);Environment.ExitCode=1;}
  finally{
   if(manager!=null)try{Stop(manager,"cleanup",true);manager.Dispose();}catch(Exception e){Out("cleanup-error:manager:"+e);complete=false;Environment.ExitCode=1;}
   if(host!=null)try{host.Close();host.Dispose();}catch(Exception e){Out("cleanup-error:host:"+e);complete=false;Environment.ExitCode=1;}
   if(connection!=null)try{connection.Disconnect();Require(Object.ReferenceEquals(connection,CGateCommunicatorFactory.GetConnection()),"Cleanup factory replaced");Require(connection.IPAddrStr=="127.0.0.1"&&connection.Port==peer.Port&&!connection.SecureSocket,"Cleanup endpoint changed");Out("factory-retained-until-process-exit:true");}catch(Exception e){Out("cleanup-error:connection:"+e);complete=false;Environment.ExitCode=1;}
   if(peer!=null)try{peer.Dispose();Require(peer.Accepted==0&&peer.Bytes==0&&peer.Error==null,"Unexpected peer activity");}catch(Exception e){Out("cleanup-error:peer:"+e);complete=false;Environment.ExitCode=1;}
   Out("complete:"+complete.ToString().ToLowerInvariant()+":physical=false:full-form=false:live=false:capture=false");
  }
 }
}
