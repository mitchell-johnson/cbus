// Preparation only. Execute only through the reviewed one-use host driver.
using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Reflection;
using System.Globalization;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Runtime.Serialization;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using Microsoft.Win32;

sealed class HarnessFailure : Exception { public HarnessFailure(string s):base(s){} }
static class NativeRegistryConditionProbe {
    const string Sentinel="23021957-xxx-yy-z-27331bfa-adf0-46be-8d44-18b1a831affe";
    const uint ReadWrite=0x2001f;
    static readonly IntPtr HKCU=new IntPtr(unchecked((int)0x80000001));
    static readonly JavaScriptSerializer Json=new JavaScriptSerializer { MaxJsonLength=262144, RecursionLimit=16 };
    static readonly BindingFlags Flags=BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Static|BindingFlags.Instance;
    static readonly List<object> Cleanup=new List<object>();
    static readonly List<object> Rows=new List<object>();
    static readonly List<string> CreatedKeys=new List<string>();
    static readonly Dictionary<string,string> WrittenValues=new Dictionary<string,string>();
    static readonly Dictionary<string,MethodInfo> Methods=new Dictionary<string,MethodInfo>();
    static readonly Dictionary<string,PropertyInfo> Properties=new Dictionary<string,PropertyInfo>();
    static readonly List<object> Failures=new List<object>();
    static Exception First;
    static IntPtr Software=IntPtr.Zero, Owned=IntPtr.Zero;
    static bool RootCreated, RootAbsent, Completed;
    static Type Condition, Checker;
    static string DirectoryRoot;
    static Timer Watchdog;
    static long OutputBytes;
    static int HandleCloseFailures;

    [DllImport("advapi32.dll",CharSet=CharSet.Unicode)] static extern int RegOpenKeyExW(IntPtr key,string sub,uint options,uint access,out IntPtr result);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode)] static extern int RegCreateKeyExW(IntPtr key,string sub,uint reserved,string cls,uint options,uint access,IntPtr security,out IntPtr result,out uint disposition);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode)] static extern int RegSetValueExW(IntPtr key,string name,uint reserved,uint type,byte[] data,uint length);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode)] static extern int RegQueryValueExW(IntPtr key,string name,IntPtr reserved,out uint type,byte[] data,ref uint length);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode)] static extern int RegDeleteValueW(IntPtr key,string name);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode)] static extern int RegDeleteKeyW(IntPtr key,string name);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode)] static extern int RegEnumKeyExW(IntPtr key,uint index,StringBuilder name,ref uint length,IntPtr reserved,IntPtr cls,IntPtr classLength,IntPtr time);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode)] static extern int RegEnumValueW(IntPtr key,uint index,StringBuilder name,ref uint length,IntPtr reserved,IntPtr type,IntPtr data,IntPtr dataLength);
    [DllImport("advapi32.dll")] static extern int RegCloseKey(IntPtr key);

    static void Guard(bool ok,string message){if(!ok)throw new HarnessFailure(message);}
    static void Status(int code,string operation){Guard(code==0,operation+" returned "+code);}
    static string Hash(byte[] bytes){using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();}
    static string SafeMessage(Exception error){try{return error.Message;}catch{return "<message unavailable>";}}
    static object Describe(Exception error){return new {type=error.GetType().FullName,message=SafeMessage(error),target=error.TargetSite==null?null:error.TargetSite.ToString()};}
    static void Remember(Exception error,string phase){if(First==null)First=error;try{Failures.Add(new {phase=phase,error=Describe(error),primary=Object.ReferenceEquals(error,First)});}catch{}}
    static void Emit(object item){string line=Json.Serialize(item);OutputBytes+=Encoding.UTF8.GetByteCount(line)+1;Guard(OutputBytes<=262144,"total output bound");Console.WriteLine(line);Console.Out.Flush();}
    static void Attempt(string phase,Action action){try{action();}catch(Exception error){Remember(error,phase);}}
    static void Close(ref IntPtr handle){if(handle==IntPtr.Zero)return;IntPtr value=handle;handle=IntPtr.Zero;int code=RegCloseKey(value);if(code!=0)HandleCloseFailures++;Status(code,"RegCloseKey");}
    static void ClosePreserving(ref IntPtr handle,Exception prior,string phase){try{Close(ref handle);}catch(Exception cleanup){if(prior==null)throw;Remember(prior,phase+"-first");Remember(cleanup,phase+"-close");}}
    static void NoLinks(string path){for(string p=Path.GetFullPath(path);!String.IsNullOrEmpty(p);p=Path.GetDirectoryName(p)){Guard((File.GetAttributes(p)&FileAttributes.ReparsePoint)==0,"reparse component: "+p);if(p==Path.GetPathRoot(p))break;}}
    static byte[] Read(string path,int limit){
        NoLinks(path);Guard((File.GetAttributes(path)&FileAttributes.Directory)==0,"regular input required");
        FileStream file=null;Exception first=null;
        try{file=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.Read);Guard(file.Length<=limit,"file bound");byte[] bytes=new byte[limit+1];int used=0;while(used<bytes.Length){int n=file.Read(bytes,used,bytes.Length-used);if(n==0)break;used+=n;}Guard(used<=limit,"file grew beyond bound");Array.Resize(ref bytes,used);return bytes;}
        catch(Exception error){first=error;throw;}
        finally{if(file!=null)try{file.Dispose();}catch(Exception cleanup){if(first==null)throw;Remember(first,"file-read");Remember(cleanup,"file-close");}}
    }
    static Dictionary<string,object> Map(object value){var map=value as Dictionary<string,object>;Guard(map!=null,"map required");return map;}
    static string Text(object value,int maximum){var s=value as string;Guard(s!=null&&s.Length<=maximum&&s.All(c=>c>0&&c<128),"bounded ASCII text required");return s;}
    static object[] ArrayValue(object value){var a=value as object[];Guard(a!=null,"array required");return a;}
    static string PathFor(string suffix){return Path.Combine(DirectoryRoot,Pins.Prefix+"-"+suffix);}
    static Assembly LoadVendor(string simple){string file;Guard(Pins.VendorFiles.TryGetValue(simple,out file),"unlisted vendor assembly: "+simple);var bytes=Read(PathFor(file),2097152);Guard(Hash(bytes)==Pins.VendorHashes[simple],"vendor identity: "+simple);var a=Assembly.LoadFrom(PathFor(file));Guard(a.GetName().Name==simple,"vendor assembly name");return a;}
    static object[] Assemblies(){var rows=new List<object>();foreach(var a in AppDomain.CurrentDomain.GetAssemblies().OrderBy(a=>a.FullName)){Guard(!a.IsDynamic&&!String.IsNullOrEmpty(a.Location),"unresolved/dynamic assembly provenance");string location=Path.GetFullPath(a.Location),hash=Hash(Read(location,33554432)),vendorFile;
        if(Pins.VendorFiles.TryGetValue(a.GetName().Name,out vendorFile))Guard(String.Equals(location,PathFor(vendorFile),StringComparison.OrdinalIgnoreCase)&&hash==Pins.VendorHashes[a.GetName().Name],"actual loaded vendor correlation");
        else Guard(String.Equals(location,PathFor("probe.exe"),StringComparison.OrdinalIgnoreCase)||location.StartsWith(@"C:\Windows\Microsoft.NET\",StringComparison.OrdinalIgnoreCase),"unlisted loaded assembly path");
        rows.Add(new {name=a.FullName,location=location,mvid=a.ManifestModule.ModuleVersionId.ToString(),sha256=hash});}return rows.ToArray();}
    static void MethodPin(MethodBase method,string key){Guard(method!=null,"method missing: "+key);Guard(method.MetadataToken==Pins.MethodTokens[key],"method token: "+key);Guard(Hash(method.GetMethodBody().GetILAsByteArray())==Pins.MethodHashes[key],"method bytes: "+key);}
    static void OriginalPins(){
        Guard(IntPtr.Size==4,"x86 process required");Guard(WindowsIdentity.GetCurrent().User.Value==Pins.Sid,"owned user SID required");
        // An unmanifested .NET Framework executable may report the compatibility
        // OS version. The separate fixed host query pins the actual Windows OS.
        Guard(Environment.OSVersion.Platform==PlatformID.Win32NT,"Windows platform required");
        Guard(Hash(Read(typeof(object).Assembly.Location,33554432))==Pins.MscorlibSha,"loaded mscorlib identity");
        AppDomain.CurrentDomain.AssemblyResolve+=(sender,args)=>{string name=new AssemblyName(args.Name).Name;if(Pins.VendorFiles.ContainsKey(name))return LoadVendor(name);throw new HarnessFailure("Unexpected unresolved assembly: "+args.Name);};
        var original=LoadVendor("SE.DAD.SESU.Common");Checker=original.GetType("SE.DAD.SESU.Common.Validation.ClientConditionChecker",true);Condition=original.GetType("SE.DAD.SESU.Common.Models.Condition",true);
        Guard(Checker.MetadataToken==Pins.CheckerToken&&Condition.MetadataToken==Pins.ConditionToken,"original type identity");
        foreach(var pair in Pins.MethodTokens){string[] key=pair.Key.Split(new[]{"::"},StringSplitOptions.None);Type type=key[0]=="Condition"?Condition:Checker;MethodBase method=key[1]==".cctor"?(MethodBase)type.TypeInitializer:type.GetMethods(Flags).Single(m=>m.Name==key[1]);MethodPin(method,pair.Key);if(type==Checker&&key[1].StartsWith("EvaluateRegistry",StringComparison.Ordinal))Methods.Add(key[1],(MethodInfo)method);}
        foreach(string name in new[]{"WhatToCheck","HowToCheck","FileOrRegistryKeyPath","RegistryEntryNameOrProductCode","ComparisonRightSideValue"})Properties.Add(name,Condition.GetProperty(name,Flags));
        Guard((string)Checker.GetField("registryEntryDefaultValue",Flags).GetValue(null)==Sentinel,"original literal sentinel");
        Emit(new {stage="original-pins",mscorlib=typeof(object).Assembly.Location,managed_os_version=Environment.OSVersion.VersionString,process_bits=IntPtr.Size*8,culture=CultureInfo.CurrentCulture.Name,input_sha256=Pins.InputSha,sid=WindowsIdentity.GetCurrent().User.Value,type_tokens=new {Checker=Checker.MetadataToken,Condition=Condition.MetadataToken},method_tokens=Pins.MethodTokens,methods=Pins.MethodHashes,assemblies=Assemblies(),public_Evaluate_called=false,provider_remapping=false});
    }
    static object Typed(object value){if(value==null)return new {kind="null",value=(object)null};Guard(value.GetType()==typeof(string)||value.GetType()==typeof(int),"unsupported returned CLR type");return new {kind=value.GetType().FullName,value=value};}
    static void Preflight(Dictionary<string,object> plan,object[] cases){
        Guard(cases.Length==12,"exact twelve cases");Guard((string)plan["root_name"]==Pins.RootName,"root identity");
        for(int n=0;n<cases.Length;n++){var row=Map(cases[n]);var fixture=Map(row["fixture"]);var condition=Map(row["condition"]);string sub=Text(fixture["subkey"],3);Guard(sub=="c"+(n+1).ToString("D2"),"case/subkey association");string name=Text(condition["name"],3);Guard(name=="R"+(n+1).ToString("D2"),"condition association");string path=Text(condition["fileOrRegistryKeyPath"],1024);Guard(path=="HKEY_CURRENT_USER\\Software\\"+Pins.RootName+"\\"+sub||path=="HKCU\\Software\\"+Pins.RootName+"\\"+sub,"owned path boundary");Guard(Text(fixture["entry"],256)==Text(condition["registryEntryNameOrProductCode"],256),"entry association");Guard((int)condition["whatToCheck"]>=3&&(int)condition["whatToCheck"]<=6,"registry-only leaf");Guard(Methods.ContainsKey(Text(row["leaf"],64)),"static leaf whitelist");}
    }
    static string[] Names(IntPtr key,bool values){var found=new List<string>();for(uint i=0;i<32;i++){uint len=256;var name=new StringBuilder(256);int status=values?RegEnumValueW(key,i,name,ref len,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero):RegEnumKeyExW(key,i,name,ref len,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero);if(status==259)return found.ToArray();Status(status,"bounded enumeration");Guard(len<=255,"name length");found.Add(name.ToString());}throw new HarnessFailure("enumeration bound");}
    static void Fixture(Dictionary<string,object> fixture){
        string sub=(string)fixture["subkey"];if(!(bool)fixture["key_exists"]){IntPtr absent;int status=RegOpenKeyExW(Owned,sub,0,0x20019,out absent);if(absent!=IntPtr.Zero)Close(ref absent);Guard(status==2,"planned absent subkey exists");return;}
        IntPtr key=IntPtr.Zero;Exception first=null;
        try{uint disposition;Status(RegCreateKeyExW(Owned,sub,0,null,0,ReadWrite,IntPtr.Zero,out key,out disposition),"create case key");Guard(disposition==1,"case key not new");CreatedKeys.Add(sub);string kind=fixture["value_kind"] as string;if(kind==null)return;
            string entry=(string)fixture["entry"];uint type;byte[] bytes;if(kind=="REG_SZ"){type=1;bytes=Encoding.Unicode.GetBytes((string)fixture["value"]+"\0");}else{Guard(kind=="REG_DWORD","fixture kind");type=4;bytes=BitConverter.GetBytes(Convert.ToUInt32(fixture["value"],CultureInfo.InvariantCulture));}
            Status(RegSetValueExW(key,entry,0,type,bytes,(uint)bytes.Length),"set owned fixture");WrittenValues.Add(sub,entry);
            uint returnedType,length=1024;byte[] returned=new byte[length];Status(RegQueryValueExW(key,entry,IntPtr.Zero,out returnedType,returned,ref length),"read owned raw fixture");Guard(returnedType==type&&length==bytes.Length&&returned.Take((int)length).SequenceEqual(bytes),"fixture exact raw readback");Emit(new {stage="fixture",subkey=sub,entry=entry,type=type,bytes_hex=BitConverter.ToString(bytes).Replace("-","")});
        }catch(Exception error){first=error;throw;}finally{ClosePreserving(ref key,first,"fixture");}
    }
    static void RunCase(Dictionary<string,object> row){
        var c=Map(row["condition"]);string name=(string)c["name"],path=(string)c["fileOrRegistryKeyPath"],entry=(string)c["registryEntryNameOrProductCode"];int what=(int)c["whatToCheck"];
        object model=FormatterServices.GetUninitializedObject(Condition);foreach(var pair in new[]{new[]{"WhatToCheck","whatToCheck"},new[]{"HowToCheck","howToCheck"},new[]{"FileOrRegistryKeyPath","fileOrRegistryKeyPath"},new[]{"RegistryEntryNameOrProductCode","registryEntryNameOrProductCode"},new[]{"ComparisonRightSideValue","comparisonRightSideValue"}}){var property=Properties[pair[0]];object value=c[pair[1]];if(property.PropertyType.IsEnum)value=Enum.ToObject(property.PropertyType,(int)value);property.SetValue(model,value,null);}
        string query=path.StartsWith("HKCU\\",StringComparison.Ordinal)?"HKEY_CURRENT_USER"+path.Substring(4):path;object defaultValue=what==3?(object)1:Sentinel;string queryEntry=what==3?"Test":entry;
        object witness=Registry.GetValue(query,queryEntry,defaultValue);var expectedWitness=Map(row["expected_provider_witness"]);string witnessKind=witness==null?"null":witness.GetType().FullName;Guard(witnessKind==(string)expectedWitness["kind"],"provider witness CLR kind");Guard(Object.Equals(witness,expectedWitness["value"]),"provider witness value");
        Emit(new {stage="provider-witness",id=row["id"],path=query,entry=queryEntry,default_value=Typed(defaultValue),result=Typed(witness),original_call_intercepted=false});
        object result=null;Exception originalError=null;
        Emit(new {stage="original-call-admitted",id=row["id"],method=row["leaf"]});
        try{result=Methods[(string)row["leaf"]].Invoke(null,new[]{(object)name,model});}
        catch(TargetInvocationException error){Guard(error.InnerException!=null,"reflection inner exception absent");originalError=error.InnerException;}
        var expected=Map(row["expected_original"]);
        bool matches=expected.ContainsKey("error_type")?(originalError!=null&&originalError.GetType().FullName==(string)expected["error_type"]&&originalError.Message==(string)expected["message"]):(originalError==null&&result is bool&&(bool)result==(bool)expected["result"]);
        if(!matches&&originalError!=null)Remember(originalError,"unexpected-original-outcome");
        var actual=new {id=row["id"],result=result,error=originalError==null?null:Describe(originalError)};Rows.Add(actual);Emit(new {stage="original-return",observation=actual});
        Guard(matches,"unexpected original result or exception");
    }
    static void CleanupRegistry(){
        if(RootCreated&&Owned!=IntPtr.Zero){
            foreach(string sub in CreatedKeys.AsEnumerable().Reverse())Attempt("cleanup-subkey-"+sub,()=>{IntPtr key=IntPtr.Zero;Exception first=null;try{Status(RegOpenKeyExW(Owned,sub,0,ReadWrite,out key),"open known owned subkey");Guard(Names(key,false).Length==0,"unexpected nested subkey; preserve it");string value;var expected=WrittenValues.TryGetValue(sub,out value)?new[]{value}:new string[0];Guard(Names(key,true).OrderBy(x=>x,StringComparer.Ordinal).SequenceEqual(expected.OrderBy(x=>x,StringComparer.Ordinal)),"unexpected value; preserve it");if(value!=null)Status(RegDeleteValueW(key,value),"delete owned value");}catch(Exception error){first=error;throw;}finally{ClosePreserving(ref key,first,"cleanup-subkey");}Status(RegDeleteKeyW(Owned,sub),"delete owned subkey");Cleanup.Add(new {subkey=sub,removed=true});});
            Attempt("cleanup-root",()=>{Guard(Names(Owned,false).Length==0&&Names(Owned,true).Length==0,"unexpected root content; preserve it");Close(ref Owned);Status(RegDeleteKeyW(Software,Pins.RootName),"delete issued root");IntPtr missing;int status=RegOpenKeyExW(Software,Pins.RootName,0,0x20019,out missing);if(missing!=IntPtr.Zero)Close(ref missing);Guard(status==2,"owned root absence not verified");RootAbsent=true;});
        }
        Attempt("close-owned-root",()=>Close(ref Owned));Attempt("close-software",()=>Close(ref Software));
    }
    static int Main(string[] args){
        try{
            Guard(args.Length==0,"no runtime-controlled paths/arguments");Console.OutputEncoding=new UTF8Encoding(false,true);CultureInfo.CurrentCulture=CultureInfo.InvariantCulture;CultureInfo.CurrentUICulture=CultureInfo.InvariantCulture;DirectoryRoot=Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory);Guard(DirectoryRoot==@"C:\CBusCliOracle118-88d8\","owned directory required");
            Watchdog=new Timer(state=>{try{Console.Error.WriteLine("Harness watchdog expired; cleanup is not established");}catch{}Environment.Exit(124);},null,30000,Timeout.Infinite);
            var bytes=Read(PathFor("input.json"),65536);Guard(Hash(bytes)==Pins.InputSha,"exact plan input hash");var text=new UTF8Encoding(false,true).GetString(bytes);var plan=Map(Json.DeserializeObject(text));var cases=ArrayValue(plan["cases"]);
            OriginalPins();Preflight(plan,cases);
            Status(RegOpenKeyExW(HKCU,"Software",0,ReadWrite,out Software),"open existing HKCU Software");uint disposition;int created=RegCreateKeyExW(Software,Pins.RootName,0,null,0,ReadWrite,IntPtr.Zero,out Owned,out disposition);if(created==0&&disposition==1)RootCreated=true;Status(created,"create scratch root");Guard(disposition==1,"scratch root already existed; will not adopt/delete");Emit(new {stage="root-created",root="HKEY_CURRENT_USER\\Software\\"+Pins.RootName,disposition=disposition,sid=WindowsIdentity.GetCurrent().User.Value});
            foreach(object item in cases)Fixture(Map(Map(item)["fixture"]));
            foreach(object item in cases)RunCase(Map(item));Completed=true;
        }catch(Exception error){Remember(error,"operation");}
        finally{
            if(Watchdog!=null)Attempt("arm-cleanup-watchdog",()=>Watchdog.Change(15000,Timeout.Infinite));
            CleanupRegistry();Attempt("final-assembly-evidence",()=>Emit(new {stage="assemblies-after",assemblies=Assemblies()}));
            Attempt("completion-evidence",()=>Emit(new {stage="complete",passed=First==null&&Completed&&RootAbsent,original_rows=Rows.Count,root_created=RootCreated,root_absence_verified=RootAbsent,handles_closed=Owned==IntPtr.Zero&&Software==IntPtr.Zero&&HandleCloseFailures==0,handle_close_failures=HandleCloseFailures,cleanup=Cleanup,failures=Failures,first_error=First==null?null:Describe(First),provider_remapping=false,network_call_sites_in_whitelisted_original_graph=0,dynamic_network_instrumentation=false}));
            if(Watchdog!=null)Attempt("dispose-watchdog",()=>Watchdog.Dispose());
        }
        return First==null&&Completed&&RootAbsent?0:1;
    }
}
