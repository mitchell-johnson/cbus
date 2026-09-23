// Independent Windows filesystem-sharing/admission tests. Owned files/processes only.
using System;
using System.IO;
using System.Diagnostics;
using System.Text;
using System.Web.Script.Serialization;
class NativeWindowsBridgeTests {
 static JavaScriptSerializer Json=new JavaScriptSerializer();
 static void Assert(bool b,string message){if(!b)throw new Exception(message);}
 static string Root;
 static string NewCase(string name){string p=Path.Combine(Root,name);Directory.CreateDirectory(p);return p;}
 static void Input(string dir,string script="echo OWNED") {File.WriteAllText(Path.Combine(dir,"job-test.cmd"),script);Ready(dir,OwnedJobQueue.Hash(File.ReadAllBytes(Path.Combine(dir,"job-test.cmd"))));}
 static void Ready(string dir,string hash){File.WriteAllText(Path.Combine(dir,"job-test.ready.json"),Json.Serialize(new{sha256=hash}));}
 static dynamic Result(string dir){return Json.Deserialize<System.Collections.Generic.Dictionary<string,object>>(File.ReadAllText(Path.Combine(dir,"job-test.result.json")));}
 static bool Exists(string dir,string suffix){return File.Exists(Path.Combine(dir,"job-test."+suffix));}
 static int Main(string[] args){try {
  if(args.Length==2&&args[0]=="crash-after-start") {
   var q=new OwnedJobQueue(args[1],(script,id)=>{
    using(var child=Process.Start(new ProcessStartInfo(@"C:\Windows\System32\cmd.exe","/d /c \""+script+"\""){UseShellExecute=false,CreateNoWindow=true})){child.WaitForExit();Assert(child.ExitCode==0,"owned script failed");}
    Environment.Exit(42);return 0;
   });q.Poll();throw new Exception("crash child did not exit");
  }
  Root=args[0];Directory.CreateDirectory(Root);
  string p=NewCase("partial-json");Input(p);string valid=File.ReadAllText(Path.Combine(p,"job-test.ready.json"));File.WriteAllText(Path.Combine(p,"job-test.ready.json"),"{");int calls=0;
  var queue=new OwnedJobQueue(p,(script,id)=>{calls++;return 0;},3);queue.Poll();Assert(calls==0&&!Exists(p,"result.json")&&!Exists(p,"admitted.json"),"partial JSON admitted");File.WriteAllText(Path.Combine(p,"job-test.ready.json"),valid);queue.Poll();Assert(calls==1&&(bool)Result(p)["complete"],"completed JSON not admitted once");queue.Poll();Assert(calls==1,"completed job replayed");Console.WriteLine("PASS partial-json-one-execution");
  foreach(string locked in new[]{"ready.json","cmd"}) {
   p=NewCase("sharing-"+locked);Input(p);calls=0;queue=new OwnedJobQueue(p,(script,id)=>{calls++;return 0;},3);
   using(var held=new FileStream(Path.Combine(p,"job-test."+locked),FileMode.Open,FileAccess.ReadWrite,FileShare.None)){queue.Poll();Assert(calls==0&&!Exists(p,"result.json")&&!Exists(p,"admitted.json"),"locked upload admitted");}
   queue.Poll();Assert(calls==1&&(bool)Result(p)["complete"],"released upload not admitted");Console.WriteLine("PASS sharing-"+locked);
  }
  p=NewCase("hash-mismatch");Input(p);string intended=new string('0',64);Ready(p,intended);calls=0;queue=new OwnedJobQueue(p,(script,id)=>{calls++;return 0;},2);queue.Poll();Assert(!Exists(p,"result.json"),"hash mismatch failed before bound");queue.Poll();var rejected=Result(p);Assert(calls==0&&!(bool)rejected["complete"]&&(bool)rejected["pre_execution"]&&!(bool)rejected["admitted"]&&(string)rejected["intended_script_sha256"]==intended,"hash rejection evidence wrong");Input(p);queue.Poll();Assert(calls==0,"rejected job later replayed");Console.WriteLine("PASS bounded-hash-rejection-intended-hash");
  p=NewCase("partial-bounded");Input(p);File.WriteAllText(Path.Combine(p,"job-test.ready.json"),"{");calls=0;queue=new OwnedJobQueue(p,(script,id)=>{calls++;return 0;},2);queue.Poll();queue.Poll();Assert(calls==0&&(bool)Result(p)["pre_execution"]&&Result(p)["intended_script_sha256"]==null,"partial bound wrong");Console.WriteLine("PASS bounded-partial-json");
  foreach(bool afterMarker in new[]{false,true}) {
   p=NewCase(afterMarker?"restart-admission":"restart-snapshot");Input(p);calls=0;queue=new OwnedJobQueue(p,(script,id)=>{calls++;return 0;});Action<string> interrupt=id=>{throw new OperationCanceledException("owned interruption");};if(afterMarker)queue.AfterAdmission=interrupt;else queue.AfterSnapshot=interrupt;
   try{queue.Poll();throw new Exception("interruption missing");}catch(OperationCanceledException){}
   Assert(calls==0&&Exists(p,"admitted.cmd")&&!Exists(p,"result.json"),"interrupted admission evidence wrong");Assert(Exists(p,"admitted.json")==afterMarker,"marker point wrong");new OwnedJobQueue(p,(script,id)=>{calls++;return 0;}).Poll();Assert(calls==0&&!Exists(p,"result.json"),"restart replayed uncertain job");Console.WriteLine("PASS "+(afterMarker?"restart-after-admission":"restart-after-snapshot"));
  }
  p=NewCase("immutable-snapshot");Input(p,"echo ORIGINAL");calls=0;queue=new OwnedJobQueue(p,(script,id)=>{calls++;Assert(File.ReadAllText(script)=="echo ORIGINAL","snapshot reread upload");Assert(Exists(p,"admitted.json"),"start preceded durable marker");return 0;});queue.AfterSnapshot=id=>File.WriteAllText(Path.Combine(p,"job-test.cmd"),"echo CHANGED");queue.Poll();Assert(calls==1&&(bool)Result(p)["complete"],"snapshot execution incomplete");Console.WriteLine("PASS exact-hashed-snapshot-and-marker-before-start");
  p=NewCase("restart-after-process");string count=Path.Combine(p,"count.txt");Input(p,"@echo off\r\necho ONCE>>"+count+"\r\n");
  using(var child=Process.Start(new ProcessStartInfo(Process.GetCurrentProcess().MainModule.FileName,"crash-after-start "+p){UseShellExecute=false,CreateNoWindow=true})){child.WaitForExit();Assert(child.ExitCode==42,"crash exit wrong");}
  Assert(Exists(p,"admitted.json")&&!Exists(p,"result.json")&&File.ReadAllLines(count).Length==1,"postprocess uncertain state wrong");calls=0;new OwnedJobQueue(p,(script,id)=>{calls++;return 0;}).Poll();Assert(calls==0&&File.ReadAllLines(count).Length==1&&!Exists(p,"result.json"),"started process replayed after restart");Console.WriteLine("PASS started-process-exit-before-result-never-replayed");
  Console.WriteLine("SUMMARY 9 PASS");return 0;
 }catch(Exception e){Console.Error.WriteLine(e);return 1;}}
}
