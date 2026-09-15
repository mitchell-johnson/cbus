// Runtime-only synchronous original ResetUnit with explicit rejected PSYNC/offline status. Only session handshake succeeds. No LoadUnit, SetEDLTFrm, Save or renderer flush.
using System;using System.IO;using System.Linq;using System.Collections.Generic;
using System.ComponentModel;using System.Drawing;using System.Reflection;using System.Diagnostics;
using System.Runtime.Serialization;using System.Xml.Linq;using System.Windows.Forms;
using System.Net;using System.Net.Sockets;using System.Threading;using System.Text;
using CBusLogicModel;using CBusLogicModel.Utilities;using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;using CBusLogicModel.CBusObjects;using SharpCGateCommunicator;using eDLT;
class NativeEdltBlankPlacementProbe {
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

 static readonly object outputLock=new object();
 static void Out(string s){lock(outputLock){Console.WriteLine(s);Console.Out.Flush();}}
 static void Require(bool b,string s){if(!b)throw new Exception(s);}
 static object Field(object o,string n){var f=o.GetType().GetField(n,BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic);Require(f!=null,"missing field "+n);return f.GetValue(o);}
 static void Set(object o,string n,object v){o.GetType().GetField(n,BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic).SetValue(o,v);}
 static object Call(object o,string n,params object[] a){var method=o.GetType().GetMethod(n,BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic);Require(method!=null,"missing method "+n);return method.Invoke(o,a);}
 static void Dump(string stage,EDLTUnit u){Out("flag:"+stage+":"+PPAttribute.bInitialiseMode);foreach(var p in u.PPAttributes)Out("pp:"+stage+":"+p.Name+"\t"+p.Value+"\tdirty="+p.HasBeenChanged);}

 sealed class RejectPeer:IDisposable {
  readonly TcpListener listener;readonly Thread worker;volatile bool stopping;public readonly int Port;TcpClient active;public int Accepted,Bytes,Requests,PendingBytes;public string Error,Rejected;public bool Eof;
  public RejectPeer(){listener=new TcpListener(IPAddress.Loopback,0);listener.Start(1);Port=((IPEndPoint)listener.LocalEndpoint).Port;worker=new Thread(Run);worker.IsBackground=true;worker.Start();Out("peer:127.0.0.1:"+Port+":handshake-only=true:forwarding=false:max-connections=1");}
  void Write(NetworkStream stream,string value){byte[] bytes=Encoding.ASCII.GetBytes(value);Out("wire-reply-hex:"+BitConverter.ToString(bytes));stream.Write(bytes,0,bytes.Length);stream.Flush();}
  void Run(){try{
   while(!stopping&&!listener.Server.Poll(100000,SelectMode.SelectRead)){}
   if(stopping)return;
   using(var socket=listener.AcceptTcpClient()){active=socket;
    Interlocked.Increment(ref Accepted);listener.Stop();Require(IPAddress.IsLoopback(((IPEndPoint)socket.Client.RemoteEndPoint).Address),"peer non-loopback");socket.ReceiveTimeout=15000;socket.SendTimeout=1000;
    var stream=socket.GetStream();Write(stream,"201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001) #cmd-syntax=1.0\r\n");
    var line=new List<byte>();ulong previous=0;
    while(!stopping){int b=stream.ReadByte();if(b<0){Eof=true;Require(line.Count==0,"incomplete trailing command");break;}Interlocked.Increment(ref Bytes);Require(Bytes<=8192,"request byte bound");line.Add((byte)b);PendingBytes=line.Count;Require(line.Count<=4096,"line bound");if(b!=10)continue;
     byte[] raw=line.ToArray();line.Clear();PendingBytes=0;Interlocked.Increment(ref Requests);Out("wire-request-hex:"+BitConverter.ToString(raw));Require(Requests<=2,"unexpected extra command/retry");Require(raw.Take(raw.Length-1).All(x=>x>=32&&x<=126),"non-ASCII or CR command");
     string command=Encoding.ASCII.GetString(raw,0,raw.Length-1);var match=System.Text.RegularExpressions.Regex.Match(command,@"^&4\[([1-9][0-9]*)\] (.+)$");Require(match.Success,"tagged command grammar");ulong id=ulong.Parse(match.Groups[1].Value);Require(id>previous,"non-monotonic command id");previous=id;string payload=match.Groups[2].Value;
     if(Requests==1){Require(id==1&&payload=="session_id tag CBusToolkit [Supplemental]","exact first session handshake");Write(stream,"[1] 200 OK\r\n");}
     else{Rejected=payload;Out("rejected-next-command:"+payload);Write(stream,"["+id+"] 401 Owned probe rejects this command\r\n");Require(payload=="do 254/p/20 psync","unknown request after handshake");}
    }
   }
  }catch(Exception e){if(!stopping){Error=e.ToString();Out("peer-error:"+Error);}}}
  public void Dispose(){if(Accepted>0)worker.Join(2000);stopping=true;listener.Stop();if(active!=null)active.Close();Require(worker.Join(2000),"peer did not exit");Out("peer-cleanup:joined=true:accepted="+Accepted+":received-bytes="+Bytes+":requests="+Requests+":eof="+Eof+":pending-bytes="+PendingBytes);Require(PendingBytes==0&&(Accepted==0||Eof),"incomplete EOF capture");}
 }
 static void Pin(CGateConnection c,RejectPeer peer,string stage){Require(Object.ReferenceEquals(c,CGateCommunicatorFactory.GetConnection()),"factory instance changed");Require(c.IPAddrStr=="127.0.0.1"&&c.Port==peer.Port&&!c.SecureSocket,"factory endpoint changed");Require(peer.Accepted<=1&&peer.Requests<=2&&peer.Error==null,"unexpected peer activity");Out("pin:"+stage+":same-instance=true:connected="+c.Connected+":accepted="+peer.Accepted+":requests="+peer.Requests);}
 static string currentStage="preflight";
 static string Mark(string value){currentStage=value;Out("stage-entry:"+value);return value;}
 static int exceptions;
 static readonly HashSet<System.Timers.Timer> disposedTimers=new HashSet<System.Timers.Timer>();
 static void StopTimer(FrmBaseUnit form,string name,string phase){var timer=(System.Timers.Timer)Field(form,name);if(timer==null){Out("timer:"+phase+":"+name+":absent");return;}if(disposedTimers.Contains(timer)){Out("timer:"+phase+":"+name+":already-disposed=true");return;}Out("timer:"+phase+":"+name+":interval="+timer.Interval+":enabled-before="+timer.Enabled);timer.Stop();timer.Dispose();disposedTimers.Add(timer);Out("timer:"+phase+":"+name+":stopped-disposed=true");}
 [STAThread] static void Main(string[] args){
  Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
  AppDomain.CurrentDomain.FirstChanceException+=delegate(object sender,System.Runtime.ExceptionServices.FirstChanceExceptionEventArgs e){if(Interlocked.Increment(ref exceptions)<=40){string trace=new StackTrace(1,true).ToString();Out("first-chance:"+currentStage+":"+e.Exception.GetType().FullName+":"+(trace.Length>6000?trace.Substring(0,6000):trace));}};
  using(var watchdog=new System.Threading.Timer(delegate{Out("fatal:whole-probe-deadline:90seconds:stage="+currentStage);Environment.Exit(4);},null,90000,Timeout.Infinite)){
   EDLTUnit u=null;FrmBaseUnit form=null;RejectPeer peer=null;CGateConnection connection=null;string stage=Mark("preflight");bool complete=false;
   try{
    Require(args.Length==3,"SPEC VALUES OVERRIDES");Require(typeof(CGateCommunicatorFactory).GetField("cgateConnection",BindingFlags.Static|BindingFlags.NonPublic).GetValue(null)==null,"preexisting factory");
    peer=new RejectPeer();connection=CGateCommunicatorFactory.GetConnection("127.0.0.1",peer.Port,false);Pin(connection,peer,"before-model");
    PPAttribute.bInitialiseMode=true;var network=Cache("complete");u=new EDLTUnit("OWNED","254","20","owned-id",true,network);u.UnitType="KEYGL5";u.FirmwareVersion="5.5.00";u.CatalogNumber="5055EDL";
    foreach(string line in File.ReadAllLines(args[1])){int i=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,i),Value=line.Substring(i+1)});}
    string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
    foreach(string line in File.ReadAllLines(args[2])){int i=line.IndexOf('\t');u.GetPPAttribute(line.Substring(0,i)).Value=line.Substring(i+1);}
    Dump("input",u);stage=Mark("original-afterload");u.AfterLoadPPData();Dump("after-load",u);Pin(connection,peer,stage);
    stage=Mark("original-constructor");var elapsed=Stopwatch.StartNew();form=new FrmBaseUnit(network,"OWNED","20","owned-id",true,"Owned Reset Pilot",false,false,IntPtr.Zero);
    StopTimer(form,"_cgateTimer","immediate-after-constructor");Out("constructor-to-timer-stop-ms:"+elapsed.ElapsedMilliseconds);Require(elapsed.ElapsedMilliseconds<500,"constructor timer stop missed strict500ms pre-due bound");Pin(connection,peer,stage);
    // Replace only the constructor's empty owned model; no original LoadUnit/SetEDLTFrm is invoked.
    var empty=form._unit;form._unit=u;empty.Dispose();Out("omitted:LoadUnit,SetEDLTFrm,network-presence,firmware-query,redraw-handler,renderer-flush,form-show,save");
    stage=Mark("original-initialize-component");Call(form,"InitializeComponent");Pin(connection,peer,stage);
    stage=Mark("owned-main-binding");((BindingSource)Field(form,"bsMainConst")).DataSource=Field(form,"_CommonConstants");((BindingSource)Field(form,"bsMainUnit")).DataSource=u;((BindingSource)Field(form,"bsMainNetwork")).DataSource=network;Dump("after-main-bindings",u);Pin(connection,peer,stage);
    stage=Mark("original-populate-panels");form.Load+=delegate{Out("observed-original-control-load-returned:true");};form.PopulateWidgetPanels();Dump("after-panel-population",u);Pin(connection,peer,stage);
    Require(peer.Requests==2&&peer.Rejected=="do 254/p/20 psync","exact rejected offline status context");
    stage=Mark("original-setup-controls");Call(form,"SetUpControls",form.Controls);Call(form,"SetupForm");Dump("after-control-setup",u);Pin(connection,peer,stage);
    Require(!form.IsDisposed,"original setup disposed form");Out("owned-form:visible="+form.Visible+":handle-created="+form.IsHandleCreated+":controls="+form.Controls.Count);

    stage=Mark("original-filter-widget-placements");
    typeof(FrmBaseUnit).GetField("SuspendEvents",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(form,true);
    typeof(FrmBaseUnit).GetField("suspendCounter",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(form,1);
    var single=(RadioButton)Field(form,"rbSinglePage");
    var grid=(DataGridView)Field(form,"dataGridView1");
    var combo=(ComboBox)Field(form,"cmbWidgetType");
    // Explicit controlled row enumeration, no ShowWidget panel binding or redraw.
    for(int mode=0;mode<=1;mode++){
     single.DataBindings.Clear();single.Checked=mode==0;
     for(int page=0;page<=(mode==0?1:4);page++){
      typeof(FrmBaseUnit).GetField("_widgetPage",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(form,page);
      Call(form,"FilterWidgets");form.RedrawTimer.Stop();
      var rows=(List<EDLTWidget>)grid.DataSource;
      Out("placements:mode="+mode+":page="+page+":slots="+string.Join(",",rows.Select(w=>w._widgetNumber)));
      for(int row=0;row<rows.Count;row++){
       Call(form,"ChangeSelectedRow",row,true);form.RedrawTimer.Stop();
       Out("choice:mode="+mode+":page="+page+":slot="+rows[row]._widgetNumber+":normal="+combo.Visible+":navigation="+((ComboBox)Field(form,"cbPageType")).Visible+":values="+string.Join(",",combo.Items.Cast<object>().Select(x=>(int)x.GetType().GetProperty("ValueAsInt").GetValue(x,null))));
      }
     }
    }
    single.Checked=false;
    foreach(int leader in new[]{1,2,3,4}){
     foreach(var w in u.Widgets.Take(5))w.WidgetType=0;u.Widgets[leader-1].WidgetType=11;
     typeof(FrmBaseUnit).GetField("_widgetPage",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(form,0);
     Call(form,"FilterWidgets");form.RedrawTimer.Stop();
     Out("covered:leader="+leader+":slots="+string.Join(",",((List<EDLTWidget>)grid.DataSource).Select(w=>w._widgetNumber)));
    }
    Pin(connection,peer,stage);Out("omitted-placement-stages:row-panel-binding,renderer,ResetUnit,BeforeSave,CRC");complete=true;
   }catch(Exception e){Out("failure-stage:"+stage);Out("failure:"+e);if(u!=null)Dump("partial",u);Environment.ExitCode=1;}
   finally{
    if(form!=null){try{StopTimer(form,"_cgateTimer","cleanup");}catch(Exception e){Out("cleanup-error:cgate-timer:"+e);complete=false;Environment.ExitCode=1;}try{StopTimer(form,"RedrawTimer","cleanup");}catch(Exception e){Out("cleanup-error:redraw-timer:"+e);complete=false;Environment.ExitCode=1;}try{form.Dispose();Out("form-cleanup:disposed="+form.IsDisposed);}catch(Exception e){Out("cleanup-error:form:"+e);complete=false;Environment.ExitCode=1;}}
    // Never clear the factory while an original timer callback might still hold it.
    // Direct disconnect retains the exact owned endpoint through process exit.
    if(connection!=null)try{connection.Disconnect();Require(Object.ReferenceEquals(connection,CGateCommunicatorFactory.GetConnection()),"factory identity lost during cleanup");Require(connection.IPAddrStr=="127.0.0.1"&&connection.Port==peer.Port&&!connection.SecureSocket,"factory cleanup endpoint changed");Out("connection-cleanup:disconnected=true:factory-retained-until-process-exit=true");}catch(Exception e){Out("cleanup-error:connection:"+e);complete=false;Environment.ExitCode=1;}
    if(peer!=null){try{peer.Dispose();Require(peer.Accepted==1&&peer.Requests==2&&peer.Rejected!=null&&peer.Error==null,"peer diagnostic incomplete");}catch(Exception e){Out("cleanup-error:peer:"+e);complete=false;Environment.ExitCode=1;}}
    Out("complete:"+complete.ToString().ToLowerInvariant()+":scope=original-filter-and-choice-lists:reset=false:renderer=false:save=false:physical=false");
   }
  }
 }
}
