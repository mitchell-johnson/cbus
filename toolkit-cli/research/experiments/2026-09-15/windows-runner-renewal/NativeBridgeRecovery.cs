using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Diagnostics;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Security.Cryptography;
using System.Web.Script.Serialization;
class NativeBridgeRecovery {
 const string Root=@"C:\CBusCliOracle118-88d8", Prefix="windows-generation-20260915t062650-recover", ExpectedUser=@"WIN-HITK135M0TR\mitchell";
 const string RunnerHash="7d870cd1772936ca7e3de97a56cb443390da61e8484c1638629c5fb2b5ae5440";
 static readonly JavaScriptSerializer Json=new JavaScriptSerializer();
 [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct SI {public int cb;public string reserved,desktop,title;public uint x,y,xSize,ySize,xCount,yCount,fill,flags;public short show,reserved2;public IntPtr reservedPtr,input,output,error;}
 [StructLayout(LayoutKind.Sequential)] struct PI {public IntPtr process,thread;public uint pid,tid;}
 [DllImport("kernel32.dll")] static extern uint WTSGetActiveConsoleSessionId();
 [DllImport("wtsapi32.dll",SetLastError=true)] static extern bool WTSQueryUserToken(uint session,out IntPtr token);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool DuplicateTokenEx(IntPtr token,uint access,IntPtr attributes,int level,int type,out IntPtr duplicate);
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool CreateProcessAsUserW(IntPtr token,string app,StringBuilder args,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr env,string directory,ref SI startup,out PI info);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
 [DllImport("userenv.dll",SetLastError=true)] static extern bool CreateEnvironmentBlock(out IntPtr environment,IntPtr token,bool inherit);
 [DllImport("userenv.dll")] static extern bool DestroyEnvironmentBlock(IntPtr environment);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool IsProcessInJob(IntPtr process,IntPtr job,out bool value);
 [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr handle,uint timeout);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process,out uint code);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 static string P(string name){return Path.Combine(Root,name);}
 static string Hash(byte[] data){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(data)).Replace("-","").ToLowerInvariant();}
 static void Require(bool value,string message){if(!value)throw new Exception(message+"; Win32="+Marshal.GetLastWin32Error());}
 static Dictionary<string,object> Read(string path){return Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(P(path)));}
 static void Save(string suffix,object data){byte[] bytes=Encoding.UTF8.GetBytes(Json.Serialize(data));using(var file=new FileStream(P(Prefix+"-"+suffix),FileMode.CreateNew,FileAccess.Write,FileShare.Read)){file.Write(bytes,0,bytes.Length);file.Flush(true);}}
 static void Stopped(){
  Require(Process.GetProcessesByName("NativeWindowsBridgeV2").Length==0,"Existing runner found; recovery will not create another");
  var stopped=Read("bridge-stopped.json");Require((string)stopped["format"]=="cbus-windows-bridge-v2"&&Convert.ToInt32(stopped["pid"])==1964,"Unexpected stopped generation");
  var ready=Read("bridge-ready.json");Require(Convert.ToInt32(ready["pid"])==1964,"Ready changed");
  Require(Hash(File.ReadAllBytes(P("NativeWindowsBridgeV2.exe")))==RunnerHash,"Runner binary changed");
  Require(!Directory.GetFiles(Root,"job-*.ready.json").Any(f=>!File.Exists(f.Substring(0,f.Length-11)+".result.json")),"Pending job found");
  using(var file=new FileStream(P("bridge-exclusive.lock"),FileMode.Open,FileAccess.ReadWrite,FileShare.None)){}
 }
 static int Run(bool start){
  Require(WindowsIdentity.GetCurrent().User.Value=="S-1-5-18","Guest recovery must be LocalSystem");
  uint session=WTSGetActiveConsoleSessionId();Require(session==1,"Active console differs from original Console1");bool parentJob;
  Require(IsProcessInJob(Process.GetCurrentProcess().Handle,IntPtr.Zero,out parentJob)&&!parentJob,"Recovery parent is in a job");
  IntPtr original=IntPtr.Zero,token=IntPtr.Zero,environment=IntPtr.Zero;PI child=new PI();
  try {
   Require(WTSQueryUserToken(session,out original),"Console user token unavailable");Require(DuplicateTokenEx(original,0xF01FF,IntPtr.Zero,2,1,out token),"Primary token duplication failed");
   string user,sid;using(var identity=new WindowsIdentity(token)){user=identity.Name;sid=identity.User.Value;}
   string expectedSid=((SecurityIdentifier)new NTAccount(ExpectedUser).Translate(typeof(SecurityIdentifier))).Value;
   Require(String.Equals(user,ExpectedUser,StringComparison.OrdinalIgnoreCase)&&sid==expectedSid,"Console user identity differs");Stopped();
   var context=new{session=session,user=user,sid=sid,parent_in_job=parentJob,runner_sha256=RunnerHash,old_pid=1964,old_stopped=Read("bridge-stopped.json"),utc=DateTime.UtcNow.ToString("o")};
   if(!start){Save("inspect.json",context);return 0;}
   Require(File.Exists(P(Prefix+"-inspect.json")),"Fresh inspect evidence required");var inspect=Read(Prefix+"-inspect.json");Require((string)inspect["sid"]==sid&&Convert.ToUInt32(inspect["session"])==session,"Inspected context differs");
   Save("admitted.json",context); // Durable one-attempt startup marker before CreateProcessAsUser.
   Require(CreateEnvironmentBlock(out environment,token,false),"Target user environment unavailable");
   var si=new SI();si.cb=Marshal.SizeOf(typeof(SI));si.desktop=@"winsta0\default";
   Require(CreateProcessAsUserW(token,P("NativeWindowsBridgeV2.exe"),new StringBuilder("\""+P("NativeWindowsBridgeV2.exe")+"\" --resume"),IntPtr.Zero,IntPtr.Zero,false,0x608,environment,Root,ref si,out child),"User-context runner start failed");
   Save("started.json",new{pid=child.pid,session=session,sid=sid,no_inherited_handles=true,creation_flags=0x608,utc=DateTime.UtcNow.ToString("o")});
   DateTime deadline=DateTime.UtcNow.AddSeconds(30);Dictionary<string,object> ready=null;
   while(DateTime.UtcNow<deadline){uint exit;Require(GetExitCodeProcess(child.process,out exit)&&exit==259,"New runner exited during startup");
    try{var next=Read("bridge-ready.json");if(Convert.ToUInt32(next["pid"])==child.pid){ready=next;break;}}catch(IOException){}Thread.Sleep(200);
   }
   Require(ready!=null&&(string)ready["format"]=="cbus-windows-bridge-v2"&&(string)ready["job_directory"]==Root&&!(bool)ready["network_listener"],"New ready missing or differs");
   Require(DateTime.Parse((string)ready["expires_utc"]).ToUniversalTime()>DateTime.UtcNow.AddHours(4).AddMinutes(-1),"Fresh expiry too short");
   bool inJob;Require(IsProcessInJob(child.process,IntPtr.Zero,out inJob)&&!inJob,"Runner inherited a job object");
   IntPtr actual;Require(OpenProcessToken(child.process,8,out actual),"Runner token query failed");try{using(var identity=new WindowsIdentity(actual)){Require(identity.User.Value==sid,"Runner token SID differs");}}finally{CloseHandle(actual);}
   using(var process=Process.GetProcessById((int)child.pid)){Require(process.SessionId==1&&String.Equals(process.MainModule.FileName,P("NativeWindowsBridgeV2.exe"),StringComparison.OrdinalIgnoreCase),"Runner session/path differs");}
   Require(Process.GetProcessesByName("NativeWindowsBridgeV2").Length==1,"Duplicate runner found");
   Require(!File.Exists(P("bridge-stopped.json"))&&!File.Exists(P("stop.bridge")),"New runner has stop markers");
   Save("complete.json",new{complete=true,pid=child.pid,session=session,user=user,sid=sid,in_job=inJob,ready=ready,runner_sha256=RunnerHash,no_inherited_handles=true,old_exit_verified=true,utc=DateTime.UtcNow.ToString("o")});return 0;
  }finally{if(child.thread!=IntPtr.Zero)CloseHandle(child.thread);if(child.process!=IntPtr.Zero)CloseHandle(child.process);if(environment!=IntPtr.Zero)DestroyEnvironmentBlock(environment);if(token!=IntPtr.Zero)CloseHandle(token);if(original!=IntPtr.Zero)CloseHandle(original);}
 }
 static int Main(string[] args){try{Require(args.Length==1&&(args[0]=="--inspect"||args[0]=="--start"),"Explicit operation required");return Run(args[0]=="--start");}catch(Exception error){Save("failure-"+DateTime.UtcNow.ToString("HHmmssfffffff")+".json",new{error=error.ToString(),utc=DateTime.UtcNow.ToString("o")});Console.Error.WriteLine(error);return 1;}}
}
