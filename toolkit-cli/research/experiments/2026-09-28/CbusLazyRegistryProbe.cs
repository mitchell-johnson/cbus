using System;
using System.IO;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Globalization;
using System.Threading;
using System.Security.Cryptography;
using System.Web.Script.Serialization;
using Microsoft.Win32;
using Microsoft.Win32.SafeHandles;
using System.Runtime.InteropServices;
public static class CbusLazyRegistryProbe {
 const string Base=@"C:\Program Files (x86)\Schneider Electric\Software Update";
 const string Output=@"C:\Windows\Temp\cbus-lazy-result.json";
 static readonly BindingFlags Flags=BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static;
 static Type Checker,Condition,Data,Args;
 static readonly List<object> Rows=new List<object>();
 static readonly Dictionary<string,object> Result=new Dictionary<string,object>();
 static RegistryKey Key;
 static string Root,Full;
 static string Hash(byte[] b){using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(b)).Replace("-","").ToLowerInvariant();}
 static void Guard(bool ok,string reason){if(!ok)throw new Exception(reason);}
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode)]static extern int RegCreateKeyEx(IntPtr root,string sub,uint reserved,string cls,uint options,int access,IntPtr security,out IntPtr key,out uint disposition);
 static object Make(int what,string rhs,string path=null){var c=Activator.CreateInstance(Condition);foreach(var p in new Dictionary<string,object>{{"WhatToCheck",what},{"HowToCheck",10},{"FileOrRegistryKeyPath",path??Full},{"RegistryEntryNameOrProductCode","Value"},{"ComparisonRightSideValue",rhs}}){var x=Condition.GetProperty(p.Key);x.SetValue(c,x.PropertyType.IsEnum?Enum.ToObject(x.PropertyType,p.Value):p.Value,null);}return c;}
 static object Model(string expr,params object[] pairs){var m=Activator.CreateInstance(Data);Data.GetProperty("Expression").SetValue(m,expr,null);var p=Data.GetProperty("Conditions");var d=(IDictionary)Activator.CreateInstance(p.PropertyType);for(int i=0;i<pairs.Length;i+=2)d.Add(pairs[i],pairs[i+1]);p.SetValue(m,d,null);return m;}
 static object NewChecker(object model){var c=Activator.CreateInstance(Checker);Checker.GetField("_currentClientConditionData",Flags).SetValue(c,model);return c;}
 static Dictionary<string,bool> Cache(object c){var src=(IDictionary)Checker.GetField("_currentConditionValues",Flags).GetValue(c);var d=new Dictionary<string,bool>();foreach(DictionaryEntry row in src)d.Add((string)row.Key,(bool)row.Value);return d;}
 static object Call(string id,object c,object model){var args=new object[]{model,null};object value=Checker.GetMethod("Evaluate",Flags).Invoke(c,args);Rows.Add(new {id=id,result=value,error=args[1],cache=Cache(c),culture=CultureInfo.CurrentCulture.Name});return value;}
 static object Callback(string id,object c,string name){var a=Activator.CreateInstance(Args);object value=null;string error=null;try{Checker.GetMethod("CallbackDuringEvaluation",Flags).Invoke(c,new object[]{name,a});value=Args.GetProperty("Result").GetValue(a,null);}catch(TargetInvocationException e){error=e.InnerException.GetType().FullName+": "+e.InnerException.Message;}Rows.Add(new{id=id,result=value,error=error,cache=Cache(c),culture=CultureInfo.CurrentCulture.Name});return value;}
 static void Value(object v){Key.SetValue("Value",v,v is int?RegistryValueKind.DWord:RegistryValueKind.String);}
 public static int Main(){bool owned=false;var oldCulture=Thread.CurrentThread.CurrentCulture;var oldUI=Thread.CurrentThread.CurrentUICulture;
  try{
   Guard(IntPtr.Size==4,"x86 process required");Guard(Hash(File.ReadAllBytes(typeof(object).Assembly.Location))=="93d46bdac1664dba87641925572c789d71a21bb01dc7c7e5aa99c0eca8335e5e","runtime mismatch");
   var pins=new Dictionary<string,string>{{"SE.DAD.SESU.Common","477fb88de310852611f26d1f845da23b8f0e6b602de8ab61a3eefc06339dc4ba"},{"SE.DAD.Core.Common","71e582d87734af16ba42eeb6184a329f3cacfcb86b8ad23676cdafc3aaa227f5"},{"Newtonsoft.Json","b624949df8b0e3a6153fdfb730a7c6f4990b6592ee0d922e1788433d276610f3"},{"NCalc","d6cfaeb501093d1dad90f193eacd896652509f690a591c121949b576746fbff3"},{"Antlr3.Runtime","7f1792ff5a0a5e0bd52982f9cea642240a1438909079ae0ca3695434b3b6fb69"},{"Microsoft.Win32.Registry","e9a9d281c1a708aaae366f82fd6a1742f65da2918cc4fa5eaaaada0be24277d9"}};
   var loaded=new Dictionary<string,string>();
   foreach(var p in pins){string f=Path.Combine(Base,p.Key+".dll");Guard(Hash(File.ReadAllBytes(f))==p.Value,"vendor file mismatch "+p.Key);var a=Assembly.LoadFrom(f);Guard(Hash(File.ReadAllBytes(a.Location))==p.Value,"loaded vendor mismatch "+p.Key);loaded.Add(p.Key,p.Value);}
   var common=Assembly.LoadFrom(Path.Combine(Base,"SE.DAD.SESU.Common.dll"));Checker=common.GetType("SE.DAD.SESU.Common.Validation.ClientConditionChecker",true);Condition=common.GetType("SE.DAD.SESU.Common.Models.Condition",true);Data=common.GetType("SE.DAD.SESU.Common.Models.ClientConditionData",true);Args=Assembly.LoadFrom(Path.Combine(Base,"NCalc.dll")).GetType("NCalc.ParameterArgs",true);
   var methods=new Dictionary<string,object>();foreach(string name in new[]{"Evaluate","CallbackDuringEvaluation","EvaluateRegistryEntryContent","CompareInt"}){var m=Checker.GetMethod(name,Flags);methods.Add(name,new{token=m.MetadataToken,il_sha256=Hash(m.GetMethodBody().GetILAsByteArray())});}Result["method_proof"]=methods;Result["vendor_sha256"]=loaded;Result["runtime_sha256"]=Hash(File.ReadAllBytes(typeof(object).Assembly.Location));Result["process_bits"]=32;
   Root="Software\\CBusCliLazy_"+Guid.NewGuid().ToString("N");Full="HKEY_CURRENT_USER\\"+Root;IntPtr handle;uint disposition;int status=RegCreateKeyEx(new IntPtr(unchecked((int)0x80000001)),Root,0,null,0,0xF003F,IntPtr.Zero,out handle,out disposition);Guard(status==0,"fixture create failed");Key=RegistryKey.FromHandle(new SafeRegistryHandle(handle,true));owned=disposition==1;Guard(owned,"fixture already existed");
   Thread.CurrentThread.CurrentCulture=CultureInfo.InvariantCulture;Thread.CurrentThread.CurrentUICulture=CultureInfo.InvariantCulture;
   var cond=Make(6,"0");var model=Model("A and A","A",cond);var checker=NewChecker(model);Value(0);Call("public-first-true",checker,model);Value(1);Call("public-fresh-evaluate-false",checker,model);
   model=Model("A and B","A",cond,"B",cond);checker=NewChecker(model);Value(0);Callback("callback-a-first-true",checker,"a");Value(1);Callback("callback-a-cached-true",checker,"a");Callback("callback-b-fresh-false",checker,"b");Value(0);Callback("callback-b-cached-false",checker,"b");
   var bad=Make(6,"not-an-int");model=Model("A","A",bad);checker=NewChecker(model);Callback("callback-failure-no-cache",checker,"a");Condition.GetProperty("ComparisonRightSideValue").SetValue(bad,"0",null);Callback("callback-repair-retry-true",checker,"a");
   Value(1);var invalid=Make(6,"0","");model=Model("A and B","A",cond,"B",invalid);Call("public-short-circuit-false",NewChecker(model),model);
   Value("I");model=Model("A","A",Make(5,"i"));Call("invariant-I-equals-i",NewChecker(model),model);Thread.CurrentThread.CurrentCulture=new CultureInfo("tr-TR");Thread.CurrentThread.CurrentUICulture=new CultureInfo("tr-TR");Call("turkish-I-not-equal-i",NewChecker(model),model);
   Result["completed"]=true;
  }catch(Exception e){Result["completed"]=false;Result["error"]=e.ToString();}
  finally{Thread.CurrentThread.CurrentCulture=oldCulture;Thread.CurrentThread.CurrentUICulture=oldUI;Result["rows"]=Rows;try{if(owned){Guard(Key.SubKeyCount==0,"unexpected fixture subkey");var names=Key.GetValueNames();Guard(names.Length<=1&&(names.Length==0||names[0]=="Value"),"unexpected fixture value");Key.DeleteValue("Value",false);Key.Close();Key=null;Registry.CurrentUser.DeleteSubKey(Root,false);using(var check=Registry.CurrentUser.OpenSubKey(Root)){Guard(check==null,"fixture remains");}Result["fixture_removed"]=true;}}catch(Exception e){Result["cleanup_error"]=e.Message;}if(Key!=null)Key.Close();File.WriteAllText(Output,new JavaScriptSerializer().Serialize(Result));}
  return Result.ContainsKey("completed")&&(bool)Result["completed"]?0:1;
 }
}
