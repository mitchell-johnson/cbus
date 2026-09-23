using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Collections.Generic;
using System.Web.Script.Serialization;
class NativeBridgeStop {
 const string Root=@"C:\CBusCliOracle118-88d8", Prefix="windows-generation-20260915t062650-stop";
 const int ExpectedPid=1964;
 const string ExpectedUser=@"WIN-HITK135M0TR\mitchell", ExpectedSid="S-1-5-21-271988887-4100452682-1621969429-1001";
 const string RunnerHash="7d870cd1772936ca7e3de97a56cb443390da61e8484c1638629c5fb2b5ae5440";
 const string ReadyHash="8a57e6a6397e0e40d7579ab6fa50c305b0165aab54e5400627cf0f6ef5cee0f8";
 static readonly JavaScriptSerializer Json=new JavaScriptSerializer();
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process,out uint code);
 [DllImport("kernel32.dll",SetLastError=true)] static extern uint WaitForSingleObject(IntPtr handle,uint milliseconds);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 static string P(string name){return Path.Combine(Root,name);}
 static void Require(bool value,string message){if(!value)throw new Exception(message+"; Win32="+Marshal.GetLastWin32Error());}
 static string Hash(byte[] data){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(data)).Replace("-","").ToLowerInvariant();}
 static Dictionary<string,object> Read(string name){return Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(P(name)));}
 static void Save(string suffix,byte[] bytes){using(var f=new FileStream(P(Prefix+"-"+suffix),FileMode.CreateNew,FileAccess.Write,FileShare.Read)){f.Write(bytes,0,bytes.Length);f.Flush(true);}}
 static void SaveJson(string suffix,object data){Save(suffix,Encoding.UTF8.GetBytes(Json.Serialize(data)));}
 static string[] Pending(){
  var names=Directory.GetFiles(Root,"job-*.ready.json").Select(f=>f.Substring(0,f.Length-11))
   .Concat(Directory.GetFiles(Root,"job-*.admitted.json").Select(f=>f.Substring(0,f.Length-14)))
   .Distinct().Where(f=>!File.Exists(f+".result.json")).OrderBy(f=>f,StringComparer.Ordinal).ToArray();
  Require(names.Length==0,"Pending owned jobs: "+String.Join(",",names));return names;
 }
 static object Check(Process process){
  Require(process.Id==ExpectedPid&&process.SessionId==1,"Unexpected runner PID or session");
  Require(Process.GetProcessesByName("NativeWindowsBridgeV2").Length==1,"Expected exactly one runner");
  Require(String.Equals(process.MainModule.FileName,P("NativeWindowsBridgeV2.exe"),StringComparison.OrdinalIgnoreCase),"Runner path differs");
  Require(Hash(File.ReadAllBytes(process.MainModule.FileName))==RunnerHash,"Runner binary differs");
  uint exit;Require(GetExitCodeProcess(process.Handle,out exit)&&exit==259,"Runner is not active");
  IntPtr token;Require(OpenProcessToken(process.Handle,8,out token),"Cannot inspect runner token");
  string user,sid;try{using(var id=new WindowsIdentity(token)){user=id.Name;sid=id.User.Value;}}finally{CloseHandle(token);}
  Require(user==ExpectedUser&&sid==ExpectedSid,"Runner user differs");
  byte[] ready=File.ReadAllBytes(P("bridge-ready.json"));Require(Hash(ready)==ReadyHash,"Ready generation differs");
  var value=Read("bridge-ready.json");Require((string)value["format"]=="cbus-windows-bridge-v2"&&Convert.ToInt32(value["pid"])==ExpectedPid&&(string)value["job_directory"]==Root&&!(bool)value["network_listener"],"Ready identity differs");
  Require(!File.Exists(P("stop.bridge"))&&!File.Exists(P("bridge-stopped.json")),"Stop already requested");Pending();
  return new{pid=process.Id,started_utc=process.StartTime.ToUniversalTime().ToString("o"),path=process.MainModule.FileName,session=process.SessionId,user=user,sid=sid,runner_sha256=RunnerHash,ready_sha256=ReadyHash,utc=DateTime.UtcNow.ToString("o")};
 }
 static int Run(bool stop){
  Require(WindowsIdentity.GetCurrent().User.Value=="S-1-5-18","Use the owned UTM SYSTEM execution context");
  using(var process=Process.GetProcessById(ExpectedPid)){
   object identity=Check(process);
   if(!stop){SaveJson("identity.json",identity);Save("old-ready.json",File.ReadAllBytes(P("bridge-ready.json")));Save("old-runner.exe",File.ReadAllBytes(P("NativeWindowsBridgeV2.exe")));SaveJson("queue.json",new{pending=Pending(),utc=DateTime.UtcNow.ToString("o")});return 0;}
   var prior=Read(Prefix+"-identity.json");Require(Convert.ToInt32(prior["pid"])==ExpectedPid&&(string)prior["started_utc"]==process.StartTime.ToUniversalTime().ToString("o")&&(string)prior["ready_sha256"]==ReadyHash,"Captured process identity changed");
   SaveJson("admitted.json",identity);Pending();
   using(var file=new FileStream(P("stop.bridge"),FileMode.CreateNew,FileAccess.Write,FileShare.None)){byte[] bytes=Encoding.UTF8.GetBytes(Prefix);file.Write(bytes,0,bytes.Length);file.Flush(true);}
   SaveJson("requested.json",new{pid=ExpectedPid,utc=DateTime.UtcNow.ToString("o")});
   Require(WaitForSingleObject(process.Handle,60000)==0,"Graceful exit not observed; no replacement permitted");
   uint code;Require(GetExitCodeProcess(process.Handle,out code)&&code==0,"Old native process exit status is not zero");
   var stopped=Read("bridge-stopped.json");Require((string)stopped["format"]=="cbus-windows-bridge-v2"&&Convert.ToInt32(stopped["pid"])==ExpectedPid,"Stopped generation differs");
   Require(Process.GetProcessesByName("NativeWindowsBridgeV2").Length==0,"Runner still present");Pending();
   using(var file=new FileStream(P("bridge-exclusive.lock"),FileMode.Open,FileAccess.ReadWrite,FileShare.None)){}
   Save("old-stopped.json",File.ReadAllBytes(P("bridge-stopped.json")));
   SaveJson("complete.json",new{complete=true,old_pid=ExpectedPid,exit_code=code,exit_observed=true,queue_empty=true,exclusive_lock_free=true,runner_count=0,utc=DateTime.UtcNow.ToString("o")});return 0;
  }
 }
 static int Main(string[] args){try{Require(args.Length==1&&(args[0]=="--capture"||args[0]=="--stop"),"Explicit operation required");return Run(args[0]=="--stop");}catch(Exception e){SaveJson("failure-"+DateTime.UtcNow.ToString("HHmmssfffffff")+".json",new{error=e.ToString(),utc=DateTime.UtcNow.ToString("o")});Console.Error.WriteLine(e);return 1;}}
}
