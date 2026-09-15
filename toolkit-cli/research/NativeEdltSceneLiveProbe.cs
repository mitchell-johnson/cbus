// Owned retained-model/SceneManager research; original assemblies are unchanged.
using System;using System.IO;using System.Linq;using System.Collections.Generic;
using System.ComponentModel;using System.Drawing;using System.Reflection;
using System.Runtime.Serialization;using System.Runtime.CompilerServices;using System.Xml.Linq;
using System.Windows.Forms;using System.Net;using System.Net.Sockets;using System.Threading;
using CBusLogicModel;using CBusLogicModel.Utilities;using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;using CBusLogicModel.EDLT;using CBusLogicModel.CBusObjects;
using System.Text;using System.Text.RegularExpressions;using System.Diagnostics;using System.Security.Cryptography;
using SharpCGateCommunicator;using eDLT.Controls.SceneManagerControls;
class NativeEdltSceneLiveProbe {
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
  var n=Bare<CBusNetwork>();n.Applications=new BindingList<CBusApplication>();n.Languages=new BindingList<CBusLanguage>();n.ProjectImages=new List<KeyValuePair<string,Image>>();n.DLTP=new List<KeyValuePair<int,Image>>();n.ProjectName="OWNED";n.NetworkAddress="254";n.AddressAsInt=254;n.bContinue=false;CBusApplication.bAdd=false;CBusApplication.AutoAddGroupsMessageShown=true;
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

 static string CapturedText(string name){switch(name){case "capture-low":return "-1";case "capture-high":return "256";case "capture-overflow":return "2147483648";case "capture-signed":return " +42 ";default:return "203";}}
 static int CapturedLevel(string name){switch(name){case "capture-low":case "capture-overflow":case "capture-bad":case "capture-rejected":return 0;case "capture-high":return 255;case "capture-signed":return 42;case "capture-missing-key":return 200;default:return 203;}}
 static bool Rejected(string name){return name=="broadcast-rejected"||name=="broadcast-all-rejected";}
 static string Hex(byte[] b){return BitConverter.ToString(b).Replace("-","").ToLowerInvariant();}
 static void Wait(Func<bool> condition,string name){var start=Stopwatch.StartNew();while(!condition()){Require(start.ElapsedMilliseconds<5000,"bounded wait: "+name);Thread.Sleep(5);}}
 sealed class Peer:IDisposable{
  readonly TcpListener listener;readonly Thread worker;TcpClient socket;volatile bool stopping;
  readonly string[] commands,replies;public readonly ManualResetEvent Release=new ManualResetEvent(false),FirstRamp=new ManualResetEvent(false);
  public readonly int Port;public int Accepted,Requests,Replies;public bool Eof;public string Error;
  public Peer(string name){
   var cmd=new List<string>{"session_id tag CBusToolkit [Supplemental]"};var rsp=new List<string>{"200 OK"};
   if(name.StartsWith("capture")){
    cmd.Add("get //OWNED/254/56/12 Level");rsp.Add("300 //OWNED/254/56/12: Level=37");
    cmd.Add("get //OWNED/254/56/42 Level");rsp.Add(name=="capture-bad"?"300 //OWNED/254/56/42: Level=not-a-number":name=="capture-rejected"?"401 Owned rejection":name=="capture-missing-key"?"300 //OWNED/254/56/42: Other=80":"300 //OWNED/254/56/42: Level="+CapturedText(name));
   }else if(name!="empty"){
    cmd.Add("ramp //OWNED/254/56/12 10 0 force ");rsp.Add(Rejected(name)?"401 Owned rejection":"200 OK");
    if(name=="broadcast-all"||name=="broadcast-all-rejected"||name=="broadcast-cross"||name=="cancel-all"){cmd.Add("ramp //OWNED/254/56/42 200 0 force ");rsp.Add("200 OK");}
    if(name=="broadcast-cross"){cmd.Add("ramp //OWNED/254/57/12 0 0 force ");rsp.Add("200 OK");}
    if(name=="cancel-one"){cmd.Add("ramp //OWNED/254/56/12 10 0 force ");rsp.Add("200 OK");}
   }
   commands=cmd.ToArray();replies=rsp.ToArray();listener=new TcpListener(IPAddress.Loopback,0);listener.Start(1);Port=((IPEndPoint)listener.LocalEndpoint).Port;worker=new Thread(Run){IsBackground=true};worker.Start();Out("peer:127.0.0.1:"+Port+":forwarding=false:max-connections=1:expected="+commands.Length);
  }
  void Write(NetworkStream stream,string s){var b=Encoding.ASCII.GetBytes(s);Out("wire-rx-hex:"+Hex(b));stream.Write(b,0,b.Length);stream.Flush();Interlocked.Increment(ref Replies);}
  void Run(){try{
   Require(listener.Server.Poll(30000000,SelectMode.SelectRead),"accept deadline");socket=listener.AcceptTcpClient();Accepted++;listener.Stop();Require(IPAddress.IsLoopback(((IPEndPoint)socket.Client.RemoteEndPoint).Address),"nonloopback peer");socket.ReceiveTimeout=15000;socket.SendTimeout=5000;var stream=socket.GetStream();
   Write(stream,"201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001) #cmd-syntax=1.0\r\n");
   var line=new List<byte>();ulong prior=0;int total=0;
   while(true){int b=stream.ReadByte();if(b<0){Eof=true;Require(line.Count==0&&Requests==commands.Length,"incomplete EOF");break;}Require(++total<=8192,"wire byte bound");line.Add((byte)b);Require(line.Count<=1024,"line bound");if(b!=10)continue;
    var raw=line.ToArray();line.Clear();Out("wire-tx-hex:"+Hex(raw));Require(raw.Take(raw.Length-1).All(n=>n>=32&&n<=126),"ASCII LF framing");var match=Regex.Match(Encoding.ASCII.GetString(raw,0,raw.Length-1),@"^&4\[([1-9][0-9]*)\] (.+)$");Require(match.Success,"priority/id framing");ulong id=ulong.Parse(match.Groups[1].Value);Require(id>prior,"repeated/nonmonotonic ID");prior=id;int index=Interlocked.Increment(ref Requests)-1;Require(index<commands.Length&&match.Groups[2].Value==commands[index],"unexpected request at "+index+": "+match.Groups[2].Value);Require(index!=0||id==1,"initial session ID");
    if(index==1&&commands[index].StartsWith("ramp ")){FirstRamp.Set();Require(Release.WaitOne(10000),"withheld ACK deadline");}
    Write(stream,"["+id+"] "+replies[index]+"\r\n");
   }
  }catch(Exception e){if(!stopping){Error=e.ToString();Out("peer-error:"+Error);}}finally{if(socket!=null)socket.Close();listener.Stop();Out("peer-worker:requests="+Requests+":replies="+Replies+":eof="+Eof);}}
  public void AwaitExpected(){Wait(()=>Error!=null||(Requests==commands.Length&&Replies==commands.Length+1),"all literal replies");Require(Error==null,"peer failed");}
  public void AwaitEof(){Require(worker.Join(5000),"EOF deadline");Require(Eof&&Error==null&&Accepted==1&&Requests==commands.Length,"peer incomplete");}
  public void Dispose(){stopping=true;Release.Set();listener.Stop();if(socket!=null)socket.Close();Require(worker.Join(5000),"peer join");Release.Dispose();FirstRamp.Dispose();Out("peer-disposed:true");}
 }
 static void Pin(CGateConnection c,Peer p,bool inspectConnected=true){Require(Object.ReferenceEquals(c,CGateCommunicatorFactory.GetConnection()),"Factory replaced");Require(c.IPAddrStr=="127.0.0.1"&&c.Port==p.Port&&!c.SecureSocket,"Factory endpoint changed");Require(p.Accepted<=1&&p.Error==null,"Unexpected peer error");Out("factory\t"+Stage+"\tretained=true|connected="+(inspectConnected?c.Connected.ToString():"not-read-after-disconnect")+"|accepted="+p.Accepted+"|requests="+p.Requests);}
 static System.Timers.Timer Timer(SceneManager m){return (System.Timers.Timer)Field(m,"redrawTimer");}
 static void Stop(SceneManager m,string stage){var t=Timer(m);Out("timer\t"+stage+"\tenabled="+t.Enabled+"|interval="+t.Interval);t.Stop();}
 static void Controls(SceneManager m){Out("controls\t"+Stage+"\tcurrent="+m.scenesBindingSource.Position+"|items="+((BindingSource)Field(m,"itemsBindingSource")).Position+"|capture="+((Button)Field(m,"btnCaptureLevels")).Enabled+"|live_enabled="+((CheckBox)Field(m,"cbLiveLevels")).Enabled+"|live="+((CheckBox)Field(m,"cbLiveLevels")).Checked+"|sync_enabled="+((CheckBox)Field(m,"cbSyncLevels")).Enabled+"|sync="+((CheckBox)Field(m,"cbSyncLevels")).Checked);}
 static void RunCase(EDLTUnit u,SceneManager m,Form host,CGateConnection c,Peer p,string name){
  host.Width=1100;host.Height=850;host.Controls.Add(m);m.Dock=DockStyle.Fill;Require(!Timer(m).Enabled,"constructor timer");m.cBusEDLTUnitBindingSource.DataSource=u;host.Show();Application.DoEvents();Require(!Timer(m).Enabled,"bind timer");Require(p.Requests==0&&!c.Connected,"bind performed I/O");
  m.scenesBindingSource.Position=name=="empty"?2:0;var items=(BindingSource)Field(m,"itemsBindingSource");items.Position=0;Application.DoEvents();var live=(CheckBox)Field(m,"cbLiveLevels");var sync=(CheckBox)Field(m,"cbSyncLevels");Require(!live.Checked&&!sync.Checked&&!Timer(m).Enabled,"initial toggles/timer");
  if(name=="broadcast-cross"){u.Scenes[0].PriSecApplication=1;u.Scenes[0].AddGroup(Group(u,57,12));Application.DoEvents();}
  Require(u.Network.AddressAsInt==254&&u.Network.ProjectName=="OWNED"&&u.Scenes.SelectMany(v=>v.Items).All(i=>Object.ReferenceEquals(i.Group.Application.Network,u.Network)),"explicit cached group routing");Stage="bound-before-connect";Dump(u);Controls(m);Pin(c,p);c.Connect();Require(c.Connected,"owned connect failed");Require(p.Requests==1,"connect grammar");
  var originalItems=u.Scenes.SelectMany(s=>s.Items).ToArray();var originalGroups=originalItems.Select(i=>Field(i,"_group")).ToArray();var originalRamps=originalItems.Select(i=>i.RampRate).ToArray();
  if(name.StartsWith("capture")||name=="empty"){
   Stage="capture-handler";Exception thrown=null;try{((Button)Field(m,"btnCaptureLevels")).PerformClick();}catch(Exception e){thrown=e;Out("handler-exception:"+e);}
   Require(name=="capture-missing-key"?thrown is KeyNotFoundException:thrown==null,"capture exception shape");
   if(name!="empty"){Require(u.Scenes[0].Items[0].Level==37,"capture first");Require(u.Scenes[0].Items[1].Level==CapturedLevel(name),"capture second");Require(u.Scenes[1].Items[0].Level==123,"other scene modified");}
   Stage="after-capture-handler";Dump(u);Controls(m);
  }else{
   if(name=="broadcast-all"||name=="broadcast-all-rejected"||name=="broadcast-cross"||name=="cancel-all")sync.Checked=true;
   Stage="before-live-on";Dump(u);Controls(m);Require(p.Requests==1,"sync toggle sent request");live.Checked=true;
   Require(p.FirstRamp.WaitOne(5000),"first ramp absent");Require(p.Replies==2,"ACK was not withheld");var pending=Enumerable.Range(2,name=="broadcast-cross"?3:name=="broadcast-all"||name=="broadcast-all-rejected"||name=="cancel-all"?2:1).Select(id=>c.RspList.FindRsp((ulong)id)).ToArray();Require(pending.All(v=>v!=null),"async response record absent");var rsp=pending[0];Stage="handler-returned-before-ack";Dump(u);Controls(m);Out("async\t"+Stage+"\tcode="+rsp.Result.RspCode+"|status="+rsp.Result.Status+"|response="+B64(rsp.RspString));p.Release.Set();
   Wait(()=>rsp.Result.RspCode==(Rejected(name)?401:200),"original async result");Out("async\tafter-literal-reply\tcode="+rsp.Result.RspCode+"|status="+rsp.Result.Status+"|response="+B64(rsp.RspString));foreach(var observed in pending){Wait(()=>!c.RspList.Contains(observed.CmdID),"original async callback removed record");Out("async\tafter-original-callback\tid="+observed.CmdID+"|code="+observed.Result.RspCode+"|status="+observed.Result.Status+"|response="+B64(observed.RspString));Require(observed.Result.RspCode==(Rejected(name)&&observed.CmdID==2?401:200),"final callback code");Require(observed.Result.Status==(Rejected(name)&&observed.CmdID==2?ResultStatus.Failed:ResultStatus.Succ),"final callback result");}
   if(name=="cancel-one"||name=="cancel-all"){
    // Deliberate pending-callback simulation: no real timer scheduled during the gate.
    Timer(m).Interval=60000;Call(m,"UpdateAllLevels");Require(Timer(m).Enabled,"edit did not arm timer");live.Checked=false;Out("unchecked-pending-timer-enabled:"+Timer(m).Enabled);Require(Timer(m).Enabled,"unchecked cancelled timer");Stop(m,"owned-stop-before-deadline");Stage="unchecked-before-pending-callback";Dump(u);Controls(m);Call(m,"redrawTimer_Elapsed",null,null);Require(!Timer(m).Enabled,"callback timer retained");Out("callback-scope:manual-original-handler-after-owned-stop:not-wallclock-race");
   }
   Stage="after-broadcast";Dump(u);Controls(m);Stop(m,Stage);
  }
  p.AwaitExpected();Pin(c,p);Require(originalItems.SequenceEqual(u.Scenes.SelectMany(s=>s.Items)),"item identities replaced");for(int i=0;i<originalItems.Length;i++)Require(Object.ReferenceEquals(originalGroups[i],Field(originalItems[i],"_group"))&&originalItems[i].RampRate==originalRamps[i],"group/ramp changed");
 }
 [STAThread]static void Main(string[] args){Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);bool complete=false;EDLTUnit u=null;SceneManager manager=null;Form host=null;Peer peer=null;CGateConnection connection=null;
  using(var watchdog=new System.Threading.Timer(delegate{Out("fatal:whole-probe-deadline:60seconds");Environment.Exit(4);},null,60000,Timeout.Infinite))try{
   Require(args.Length==3,"SPEC VALUES CASE");Require(new[]{"capture-low","capture-high","capture-overflow","capture-signed","capture","capture-bad","capture-rejected","capture-missing-key","broadcast-one","broadcast-all","broadcast-all-rejected","broadcast-rejected","broadcast-cross","cancel-one","cancel-all","empty"}.Contains(args[2]),"Unknown case");
   Out("runtime:"+Environment.Version+":"+IntPtr.Size);foreach(var a in new[]{typeof(object).Assembly,typeof(Form).Assembly,typeof(Enumerable).Assembly,typeof(EDLTUnit).Assembly,typeof(SceneManager).Assembly,typeof(CGateConnection).Assembly})using(var f=File.OpenRead(a.Location))using(var hash=SHA256.Create())Out("runtime-file\t"+a.FullName+"\t"+a.Location+"\t"+Hex(hash.ComputeHash(f))+"\t"+FileVersionInfo.GetVersionInfo(a.Location).FileVersion);
   Require(typeof(CGateCommunicatorFactory).GetField("cgateConnection",BindingFlags.Static|BindingFlags.NonPublic).GetValue(null)==null,"Preexisting factory");peer=new Peer(args[2]);connection=CGateCommunicatorFactory.GetConnection("127.0.0.1",peer.Port,false);Pin(connection,peer);
   PPAttribute.bInitialiseMode=true;u=new EDLTUnit("OWNED","254","20","owned-scene-id",true,Cache());u.UnitType="KEYGL5";u.FirmwareVersion="5.5.00";u.CatalogNumber="5055EDL";
   foreach(string line in File.ReadAllLines(args[1])){int i=line.IndexOf('\t');Require(i>0,"Bad PP input");u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,i),Value=line.Substring(i+1)});}string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));Fixture(u);Stage="raw-input";Dump(u);
   u.AfterLoadPPData();PPAttribute.bInitialiseMode=false;foreach(var pp in u.PPAttributes)pp.HasBeenChanged=false;var retained=u.Scenes.ToArray();Stage="after-original-load";Dump(u);Pin(connection,peer);
   host=new Form();manager=new SceneManager();RunCase(u,manager,host,connection,peer,args[2]);
   Stage="before-save";Dump(u);Pin(connection,peer);Call(u,"BeforeSavePPData",true,false);Stage="after-original-save";Dump(u);Pin(connection,peer);typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);Stage="after-original-crc";Dump(u);Require(retained.Select((s,i)=>Object.ReferenceEquals(s,u.Scenes[i])).All(x=>x),"Scene identity replaced");Pin(connection,peer);complete=true;
  }catch(Exception e){Out("failure-stage:"+Stage);Out("failure:"+e);if(u!=null)Dump(u);Environment.ExitCode=1;}
  finally{
   if(manager!=null){try{Stop(manager,"cleanup");Timer(manager).Dispose();}catch(Exception e){Out("cleanup-error:timer:"+e);complete=false;Environment.ExitCode=1;}try{manager.Dispose();Out("manager-disposed:true");}catch(Exception e){Out("cleanup-error:manager:"+e);complete=false;Environment.ExitCode=1;}}
   if(host!=null)try{host.Close();host.Dispose();}catch(Exception e){Out("cleanup-error:host:"+e);complete=false;Environment.ExitCode=1;}
   if(connection!=null)try{connection.Disconnect();Pin(connection,peer,false);Out("factory-retained-until-process-exit:true");}catch(Exception e){Out("cleanup-error:connection:"+e);complete=false;Environment.ExitCode=1;}
   if(peer!=null){try{peer.AwaitEof();}catch(Exception e){Out("cleanup-error:peer-eof:"+e);complete=false;Environment.ExitCode=1;}try{peer.Dispose();}catch(Exception e){Out("cleanup-error:peer-dispose:"+e);complete=false;Environment.ExitCode=1;}}
   Out("complete:"+complete.ToString().ToLowerInvariant()+":physical=false:full-form=false:recording-peer=true");
  }
 }
}
