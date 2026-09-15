// Owned research-only Windows job runner. No vendor implementation or network listener.
using System;
using System.IO;
using System.IO.Compression;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;

public sealed class OwnedJobQueue {
 readonly string root;
 readonly int maxAttempts;
 readonly Func<string,string,int> execute;
 readonly Dictionary<string,int> attempts = new Dictionary<string,int>();
 readonly JavaScriptSerializer json = new JavaScriptSerializer();
 public Action<string> AfterSnapshot;
 public Action<string> AfterAdmission;
 public OwnedJobQueue(string directory,Func<string,string,int> callback,int admissionLimit=120) {
  if(admissionLimit<1)throw new ArgumentOutOfRangeException("admissionLimit");
  root=directory;execute=callback;maxAttempts=admissionLimit;
 }
 public static string Hash(byte[] data) {using(var s=SHA256.Create())return BitConverter.ToString(s.ComputeHash(data)).Replace("-","").ToLowerInvariant();}
 public static void WriteNewDurable(string path,byte[] data) {
  using(var stream=new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.Read)) {stream.Write(data,0,data.Length);stream.Flush(true);}
 }
 public static void Save(string path,object value) {
  string temp=path+".tmp-"+Guid.NewGuid().ToString("N");
  WriteNewDurable(temp,Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(value)));File.Move(temp,path);
 }
 void Reject(string id,int count,string intended,string error) {
  Save(Path.Combine(root,id+".result.json"),new{complete=false,pre_execution=true,admitted=false,admission_attempts=count,intended_script_sha256=intended,error=error,utc=DateTime.UtcNow.ToString("o")});
 }
 public void Poll() {
  foreach(string request in Directory.GetFiles(root,"job-*.ready.json").OrderBy(x=>x,StringComparer.Ordinal)) {
   string name=Path.GetFileName(request);string id=name.Substring(0,name.Length-11);
   if(!Regex.IsMatch(id,@"^job-[a-z0-9-]{1,48}$"))continue;
   string result=Path.Combine(root,id+".result.json"),marker=Path.Combine(root,id+".admitted.json"),snapshot=Path.Combine(root,id+".admitted.cmd");
   // Any durable admission artifact is conservatively non-replayable, even if its
   // process never started or its final result could not be written.
   if(File.Exists(result)||File.Exists(marker)||File.Exists(snapshot))continue;
   byte[] bytes=null;string intended=null;string failure=null;
   try {
    var info=new FileInfo(request);if(info.Length>4096)throw new InvalidDataException("Ready file exceeds4096bytes");
    var spec=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(request));
    object value;if(spec==null||spec.Count!=1||!spec.TryGetValue("sha256",out value)||!(value is string))throw new InvalidDataException("Incomplete or invalid ready schema");
    intended=(string)value;if(!Regex.IsMatch(intended,@"^[a-f0-9]{64}$"))throw new InvalidDataException("Invalid intended script hash");
    string script=Path.Combine(root,id+".cmd");if(new FileInfo(script).Length>1048576)throw new InvalidDataException("Command script exceeds1MiB");
    bytes=File.ReadAllBytes(script);if(Hash(bytes)!=intended)throw new InvalidDataException("Script hash does not yet match ready hash");
   }catch(Exception e){failure=e.GetType().FullName+": "+e.Message;}
   if(failure!=null) {
    int count=attempts.ContainsKey(id)?attempts[id]+1:1;attempts[id]=count;
    if(count>=maxAttempts)Reject(id,count,intended,failure);
    continue;
   }
   // Write the EXACT bytes already read and hashed, once. Never read the mutable
   // upload path again when executing or reporting its accepted identity.
   WriteNewDurable(snapshot,bytes);
   if(AfterSnapshot!=null)AfterSnapshot(id);
   WriteNewDurable(marker,Encoding.UTF8.GetBytes(json.Serialize(new{admitted=true,script_sha256=intended,snapshot=Path.GetFileName(snapshot),utc=DateTime.UtcNow.ToString("o")})));
   if(AfterAdmission!=null)AfterAdmission(id);
   try {
    int code=execute(snapshot,id);
    Save(result,new{exit_code=code,complete=code==0,pre_execution=false,admitted=true,script_sha256=intended,utc=DateTime.UtcNow.ToString("o")});
   }catch(Exception e){Save(result,new{complete=false,pre_execution=false,admitted=true,script_sha256=intended,error=e.ToString(),utc=DateTime.UtcNow.ToString("o")});}
   return;
  }
 }
}

class NativeBridge {
 const string Root = @"C:\CBusCliOracle118-88d8";
 static JavaScriptSerializer Json = new JavaScriptSerializer();
 static string P(string name){return Path.Combine(Root,name);}
 static void Save(string name,object value){OwnedJobQueue.Save(P(name),value);}
 static int Run(string executable,string args,string directory,string basename,int timeout) {
  using(var p = new Process()) {
   p.StartInfo=new ProcessStartInfo(executable,args){WorkingDirectory=directory,UseShellExecute=false,RedirectStandardOutput=true,RedirectStandardError=true,CreateNoWindow=true};
   var output=new StringBuilder();var errors=new StringBuilder();
   p.OutputDataReceived+=(s,e)=>{if(e.Data!=null)lock(output)output.AppendLine(e.Data);};p.ErrorDataReceived+=(s,e)=>{if(e.Data!=null)lock(errors)errors.AppendLine(e.Data);};
   p.Start();p.BeginOutputReadLine();p.BeginErrorReadLine();bool done=p.WaitForExit(timeout);if(!done){p.Kill();p.WaitForExit();}else p.WaitForExit();
   File.WriteAllText(P(basename+".stdout.txt"),output.ToString());File.WriteAllText(P(basename+".stderr.txt"),errors.ToString());return done?p.ExitCode:-1000;
  }
 }
 static void Backup(string name) {if(File.Exists(P(name)))File.Move(P(name),P(name+".v1-"+DateTime.UtcNow.ToString("yyyyMMddTHHmmssfffffff")));}
 static int Main(string[] args) {try {
  if(args.Length==1&&args[0]=="--previous-identity") {
   var matches=Process.GetProcessesByName("u88").Where(p=>String.Equals(p.MainModule.FileName,@"C:\u88.exe",StringComparison.OrdinalIgnoreCase)).ToArray();
   if(matches.Length!=1)throw new Exception("Expected exactly one ownedv1runner");
   var old=matches[0];Save("bridge-v1-process.json",new{pid=old.Id,started_utc=old.StartTime.ToUniversalTime().ToString("o"),path=old.MainModule.FileName,sha256=OwnedJobQueue.Hash(File.ReadAllBytes(old.MainModule.FileName))});return 0;
  }
  if(args.Length==1&&args[0]=="--wait-previous") {
   var old=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(P("bridge-v1-process.json")));int pid=Convert.ToInt32(old["pid"]);bool alreadyExited=false;
   try {using(var process=Process.GetProcessById(pid)) {
    if(!String.Equals(process.MainModule.FileName,(string)old["path"],StringComparison.OrdinalIgnoreCase)||process.StartTime.ToUniversalTime().ToString("o")!=(string)old["started_utc"])throw new Exception("Previous PID identity changed");
    if(!process.WaitForExit(30000))throw new Exception("Ownedv1runner has not exited");
   }}catch(ArgumentException){alreadyExited=true;}
   if(!File.Exists(P("bridge-stopped.json")))throw new Exception("Ownedv1stop record missing");
   Save("bridge-v1-exit-proof.json",new{pid=pid,exit_observed=true,already_exited=alreadyExited,utc=DateTime.UtcNow.ToString("o")});return 0;
  }
  if(args.Length!=1||args[0]!="--resume")throw new Exception("v2requires explicit --resume of the ownedv1directory");
  var bootstrap=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(P("bootstrap.json")));
  if((string)bootstrap["owned_root"]!=Root||(string)bootstrap["format"]!="cbus-windows-bridge-v1")throw new Exception("Owned bootstrap identity mismatch");
  var proof=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(P("bridge-v1-exit-proof.json")));if(!(bool)proof["exit_observed"])throw new Exception("Previous process exit unverified");
  using(var exclusive=new FileStream(P("bridge-exclusive.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None)) {
   foreach(string name in new[]{"bridge-ready.json","bridge-stopped.json","stop.bridge"})Backup(name);
   var manifest=Json.Deserialize<List<Dictionary<string,object>>>(File.ReadAllText(P("guest-vendor-manifest.json")));
   if(manifest.Count!=25)throw new Exception("Unexpected original manifest count");
   foreach(var row in manifest){string f=P("vendor\\"+(string)row["name"]);if(new FileInfo(f).Length!=Convert.ToInt64(row["size"])||OwnedJobQueue.Hash(File.ReadAllBytes(f))!=(string)row["sha256"])throw new Exception("Staged original file changed: "+row["name"]);}
   DateTime expires=DateTime.UtcNow.AddHours(4);
   Save("bridge-ready.json",new{format="cbus-windows-bridge-v2",pid=Process.GetCurrentProcess().Id,expires_utc=expires.ToString("o"),job_directory=Root,network_listener=false,admission_poll_limit=120,source_protocol="hash-verified-snapshot-before-execution"});
   var queue=new OwnedJobQueue(Root,(script,id)=>Run(@"C:\Windows\System32\cmd.exe","/d /c \""+script+"\"",Root,id,300000));
   while(DateTime.UtcNow<expires&&!File.Exists(P("stop.bridge"))){queue.Poll();Thread.Sleep(500);}
   Save("bridge-stopped.json",new{format="cbus-windows-bridge-v2",pid=Process.GetCurrentProcess().Id,utc=DateTime.UtcNow.ToString("o")});
  }
  return 0;
 }catch(Exception e){Console.Error.WriteLine(e);return 1;}}
}
