// Original Reset handler/component arms with separate base/audited-local wiring. No LoadUnit, SetEDLTFrm, renderer, database/network save or physical command; only exact session200 and PSYNC401.
using System;using System.IO;using System.Linq;using System.Collections.Generic;
using System.ComponentModel;using System.Drawing;using System.Reflection;using System.Diagnostics;
using System.Runtime.Serialization;using System.Runtime.CompilerServices;using System.Xml.Linq;using System.Windows.Forms;
using System.Net;using System.Net.Sockets;using System.Threading;using System.Text;
using CBusLogicModel;using CBusLogicModel.Utilities;using CBusLogicModel.Units;
using CBusLogicModel.Units.EDLT;using CBusLogicModel.CBusObjects;using SharpCGateCommunicator;using eDLT;
class NativeEdltResetEdgesProbe {
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

 sealed class IdentityComparer:IEqualityComparer<object>{public new bool Equals(object a,object b){return Object.ReferenceEquals(a,b);}public int GetHashCode(object o){return RuntimeHelpers.GetHashCode(o);}}
 static readonly Dictionary<object,int> identities=new Dictionary<object,int>(new IdentityComparer());
 static int Id(object value){if(value==null)return 0;int id;if(!identities.TryGetValue(value,out id)){id=identities.Count+1;identities[value]=id;}return id;}
 static void Dump(string stage,EDLTUnit u){
  Out("flag:"+stage+":"+PPAttribute.bInitialiseMode);foreach(var p in u.PPAttributes)Out("pp:"+stage+":"+p.Name+"\t"+p.Value+"\tdirty="+p.HasBeenChanged);
  foreach(var w in u.Widgets)Out("widget-ref:"+stage+":"+w.WidgetNumber+":"+Id(w)+":"+Id(w.WidgetData)+":"+w.WidgetData.GetType().FullName);
  foreach(var scene in u.Scenes){Out("scene-ref:"+stage+":"+scene.SceneIndex+":"+Id(scene)+":"+Field(scene,"_PriSecApplication")+":"+Field(scene,"_actionSelector"));foreach(var item in scene.Items){var g=(CBusGroup)Field(item,"_group");Out("scene-item-ref:"+stage+":"+scene.SceneIndex+":"+Id(item)+":"+Id(g)+":"+g.Application.AddressAsInt+":"+g.AddressAsInt);}}
 }

 static void Controls(FrmBaseUnit form,string phase){
  foreach(string name in new[]{"radioButton5","radioButton3","rbColourIndicatorOffFixedColour","rbColourIndicatorOnFixedColour","radioButton4","radioButton6","rbRestorePreset"}){
   var radio=(RadioButton)Field(form,name);Out("bound-control:"+phase+":"+name+":checked="+radio.Checked+":bindings="+string.Join(",",radio.DataBindings.Cast<Binding>().Select(b=>b.PropertyName+"/"+b.BindingMemberInfo.BindingMember+"/"+b.DataSourceUpdateMode)));
  }
 }
 static void NoRenderer(FrmBaseUnit form,string phase){
  var fields=typeof(System.Timers.Timer).GetFields(BindingFlags.Instance|BindingFlags.NonPublic).Where(f=>f.FieldType==typeof(System.Timers.ElapsedEventHandler)).ToArray();Require(fields.Length==1,"Cannot inspect original redraw subscription");
  var handler=(Delegate)fields[0].GetValue(form.RedrawTimer);int count=handler==null?0:handler.GetInvocationList().Length;
  Out("renderer:"+phase+":subscriptions="+count+":opening-dialog="+form.OpeningDialog);Require(count==0,"Original renderer unexpectedly subscribed");
 }
 static void LocalWiring(FrmBaseUnit form,EDLTUnit u){
  foreach(var pair in new[]{new[]{"_del","UpdateBtnApply"},new[]{"_del2","UpdateBtnOk"}}){var field=typeof(FrmBaseUnit).GetField(pair[0],BindingFlags.Instance|BindingFlags.NonPublic);var method=typeof(FrmBaseUnit).GetMethod(pair[1],BindingFlags.Instance|BindingFlags.NonPublic);field.SetValue(form,Delegate.CreateDelegate(field.FieldType,form,method));}
  var source=(BindingSource)Field(form,"bsMainUnit");
  foreach(var pair in new[]{new[]{"pnlProximityEventGroup","WakeByProximityMode"},new[]{"pnlProximityActionSelector","ProximityModeIsTrigger"},new[]{"pnlProximityLevel","ProximityModeIsGroup"},new[]{"pnlIgnoreKeyPress","IgnoreFirstKeyPressAvailable"},new[]{"pnlActivationPage","DefaultPageEnabled"}}){var c=(Control)Field(form,pair[0]);Require(c.DataBindings["Visible"]==null,"Unexpected preexisting visible binding");c.DataBindings.Add(new Binding("Visible",source,pair[1],true,DataSourceUpdateMode.Never));}
  Call(Field(form,"lcQuickStatusLevel1"),"SetHigherLevelControl",Field(form,"lcQuickStatusLevel2"));Call(Field(form,"lcQuickStatusLevel2"),"SetLowerLevelControl",Field(form,"lcQuickStatusLevel1"));
  foreach(var pair in new[]{new[]{"cbxColourIndicatorOffFixedColour","rbColourIndicatorOffFixedColour"},new[]{"cbxColourIndicatorOnFixedColour","rbColourIndicatorOnFixedColour"}}){var c=(Control)Field(form,pair[0]);Require(c.DataBindings["Visible"]==null,"Unexpected preexisting colour visible binding");c.DataBindings.Add("Visible",Field(form,pair[1]),"Checked");}
  Out("audited-local-wiring:five-unit-visible,two-colour-visible,two-linked-level-controls,two-original-button-delegates");
 }


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
    Require(args.Length==7,"SPEC VALUES OVERRIDES ARM WIRING TAB CACHE");Require(args[3]=="handler"||args[3]=="components","Invalid arm");Require(args[4]=="base"||args[4]=="audited","Invalid local wiring");Require(new[]{"tpWidgetFunctions","tpStandbyPage","tpColourOptions","tpGeneralOptions"}.Contains(args[5]),"Invalid tab");Require(args[6]=="complete"||args[6]=="missing-level2","Invalid cache");Require(typeof(CGateCommunicatorFactory).GetField("cgateConnection",BindingFlags.Static|BindingFlags.NonPublic).GetValue(null)==null,"preexisting factory");
    peer=new RejectPeer();connection=CGateCommunicatorFactory.GetConnection("127.0.0.1",peer.Port,false);Pin(connection,peer,"before-model");
    PPAttribute.bInitialiseMode=true;var network=Cache(args[6]);u=new EDLTUnit("OWNED","254","20","owned-id",true,network);u.UnitType="KEYGL5";u.FirmwareVersion="5.5.00";u.CatalogNumber="5055EDL";
    foreach(string line in File.ReadAllLines(args[1])){int i=line.IndexOf('\t');u.PPAttributes.Add(new PPAttribute{Name=line.Substring(0,i),Value=line.Substring(i+1)});}
    string xml=File.ReadAllText(args[0]);u.UnitSpec=XDocument.Parse(xml.Substring(xml.IndexOf("<?xml")));
    foreach(string line in File.ReadAllLines(args[2])){int i=line.IndexOf('\t');u.GetPPAttribute(line.Substring(0,i)).Value=line.Substring(i+1);}
    u.GetPPAttribute("EnableLevelStore").HasBeenChanged=true;u.GetPPAttribute("BacklightActiveBrightnessControlGroup").HasBeenChanged=true;u.GetPPAttribute("IndicatorOffColourControlGroup").HasBeenChanged=false;u.GetPPAttribute("UnitAddress").HasBeenChanged=true;u.GetPPAttribute("StaticTextString0").HasBeenChanged=true;Dump("input",u);stage=Mark("original-afterload");u.AfterLoadPPData();Dump("after-load",u);Pin(connection,peer,stage);
    stage=Mark("original-constructor");var elapsed=Stopwatch.StartNew();form=new FrmBaseUnit(network,"OWNED","20","owned-id",true,"Owned Reset Pilot",false,false,IntPtr.Zero);
    StopTimer(form,"_cgateTimer","immediate-after-constructor");Out("constructor-to-timer-stop-ms:"+elapsed.ElapsedMilliseconds);Require(elapsed.ElapsedMilliseconds<500,"constructor timer stop missed strict500ms pre-due bound");Pin(connection,peer,stage);
    // Replace only the constructor's empty owned model; no original LoadUnit/SetEDLTFrm is invoked.
    var empty=form._unit;form._unit=u;empty.Dispose();Out("omitted:LoadUnit,SetEDLTFrm,network-presence,firmware-query,redraw-handler,renderer-flush,form-show,save");
    stage=Mark("original-initialize-component");Call(form,"InitializeComponent");NoRenderer(form,stage);Pin(connection,peer,stage);if(args[4]=="audited"){stage=Mark("audited-local-wiring");LocalWiring(form,u);Dump(stage,u);}else Out("omitted-local-wiring:five-unit-visible,two-colour-visible,two-linked-level-controls,two-original-button-delegates");
    stage=Mark("owned-main-binding");((BindingSource)Field(form,"bsMainConst")).DataSource=Field(form,"_CommonConstants");((BindingSource)Field(form,"bsMainUnit")).DataSource=u;((BindingSource)Field(form,"bsMainNetwork")).DataSource=network;Dump("after-main-bindings",u);Pin(connection,peer,stage);
    stage=Mark("original-populate-panels");form.Load+=delegate{Out("observed-original-control-load-returned:true");};form.PopulateWidgetPanels();Dump("after-panel-population",u);Pin(connection,peer,stage);
    Require(peer.Requests==2&&peer.Rejected=="do 254/p/20 psync","exact rejected offline status context");
    stage=Mark("original-setup-controls");Call(form,"SetUpControls",form.Controls);Call(form,"SetupForm");Dump("after-control-setup",u);Pin(connection,peer,stage);
    Require(!form.IsDisposed,"original setup disposed form");Out("owned-form:visible="+form.Visible+":handle-created="+form.IsHandleCreated+":controls="+form.Controls.Count);

    var tabs=(TabControl)Field(form,"tabControl");Out("tabs:"+string.Join(",",tabs.TabPages.Cast<TabPage>().Select(t=>t.Name)));var tab=tabs.TabPages.Cast<TabPage>().Single(t=>t.Name==args[5]);tabs.SelectedTab=tab;form.RedrawTimer.Stop();Out("selected-tab:"+tabs.SelectedIndex+":"+tabs.SelectedTab.Name);Dump("before-reset",u);Controls(form,"before-reset");NoRenderer(form,"before-reset");
    if(args[3]=="handler"){
     stage=Mark("unchanged-silent-reset-handler");bool reset=form.ResetUnit(true);form.RedrawTimer.Stop();Out("original-reset-return:"+reset);Require(reset,"Original handler returned false");
    }else{
     stage=Mark("component-show-blank");form.ShowWidget(0);Dump(stage,u);
     stage=Mark("component-before-change");form.BeforeChangePpAttributes();Dump(stage,u);Controls(form,stage);
     stage=Mark("component-reset-defaults");bool reset=u.ResetToDefaults();Out("original-defaults-return:"+reset);Require(reset,"Original defaults returned false");Dump(stage,u);
     stage=Mark("component-zero-byte1");foreach(var w in u.Widgets)w.WidgetData.WidgetByte(1).ValueAsInt=0;Dump(stage,u);
     stage=Mark("component-after-change");form.AfterChangePpAttributes();Dump(stage,u);
     stage=Mark("component-widget10");var w10=u.Widgets.Single(w=>w.WidgetNumber==10);w10.WidgetType=10;w10.WidgetData.WidgetByte(1).Value="0x2";form.RedrawTimer.Stop();
    }
    Dump("after-reset",u);Controls(form,"after-reset");Pin(connection,peer,stage);NoRenderer(form,"after-reset");Require(!form.IsDisposed,"Handler disposed form");Out("final-widget10:"+u.GetPPAttribute("Widget10WidgetType").ValueAsInt+":"+u.GetPPAttribute("Widget10WidgetByteValue1").ValueAsInt);
    stage=Mark("original-before-save");Call(u,"BeforeSavePPData",true,false);form.RedrawTimer.Stop();Dump("before-save",u);Pin(connection,peer,stage);
    stage=Mark("original-crc");typeof(CBusBaseUnit).GetMethod("CalculateCRCForPPAttributes",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(u,null);form.RedrawTimer.Stop();Dump("final",u);Pin(connection,peer,stage);NoRenderer(form,"final");
    Out("scope:arm="+args[3]+":wiring="+args[4]+":tab="+args[5]+":cache="+args[6]);complete=true;
   }catch(Exception e){Out("failure-stage:"+stage);Out("failure:"+e);if(u!=null)Dump("partial",u);Environment.ExitCode=1;}
   finally{
    if(form!=null){try{StopTimer(form,"_cgateTimer","cleanup");}catch(Exception e){Out("cleanup-error:cgate-timer:"+e);complete=false;Environment.ExitCode=1;}try{StopTimer(form,"RedrawTimer","cleanup");}catch(Exception e){Out("cleanup-error:redraw-timer:"+e);complete=false;Environment.ExitCode=1;}try{form.Dispose();Out("form-cleanup:disposed="+form.IsDisposed);}catch(Exception e){Out("cleanup-error:form:"+e);complete=false;Environment.ExitCode=1;}}
    // Never clear the factory while an original timer callback might still hold it.
    // Direct disconnect retains the exact owned endpoint through process exit.
    if(connection!=null)try{connection.Disconnect();Require(Object.ReferenceEquals(connection,CGateCommunicatorFactory.GetConnection()),"factory identity lost during cleanup");Require(connection.IPAddrStr=="127.0.0.1"&&connection.Port==peer.Port&&!connection.SecureSocket,"factory cleanup endpoint changed");Out("connection-cleanup:disconnected=true:factory-retained-until-process-exit=true");}catch(Exception e){Out("cleanup-error:connection:"+e);complete=false;Environment.ExitCode=1;}
    if(peer!=null){try{peer.Dispose();Require(peer.Accepted==1&&peer.Requests==2&&peer.Rejected!=null&&peer.Error==null,"peer diagnostic incomplete");}catch(Exception e){Out("cleanup-error:peer:"+e);complete=false;Environment.ExitCode=1;}}
    Out("complete:"+complete.ToString().ToLowerInvariant()+":scope=reset-model-terminal-save-offline-status:reset=true:renderer=false:database-save=false:physical=false");
   }
  }
 }
}
