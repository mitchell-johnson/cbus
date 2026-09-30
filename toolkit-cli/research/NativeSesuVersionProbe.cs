// Owned reflection harness for the SESU 3.0.7 file-version comparator.
//
// Part 1 calls the unchanged private ClientConditionChecker.EvaluateFileVersion
// (SE.DAD.SESU.Common, RVA 0x26A8) for runner-built files whose version
// resource holds known text, across a right-hand version matrix and all eight
// file-version HowToCheck values. Part 2 records the same runtime's
// System.Version.TryParse/CompareTo, which that method invokes, over the full
// generated string matrix. No network, registry or machine-wide path is used.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using SE.DAD.SESU.Common.Models;

static class NativeSesuVersionProbe {
    static void Emit(object value) { Console.WriteLine(JsonConvert.SerializeObject(value)); }

    static object Parsed(string text) {
        Version value;
        bool ok=Version.TryParse(text,out value);
        return ok ? (object)new[]{value.Major,value.Minor,value.Build,value.Revision} : null;
    }

    static int Main(string[] args) {
        if(args.Length!=1) return 2;
        var plan=JObject.Parse(File.ReadAllText(args[0]));
        var strings=plan["strings"].Select(x=>(string)x).ToArray();
        foreach(var text in strings) Emit(new{stage="runtime-version-parse",text=text,parsed=Parsed(text)});
        var valid=strings.Where(s=>Parsed(s)!=null).ToArray();
        foreach(var left in valid) foreach(var right in valid)
            Emit(new{stage="runtime-version-compare",left=left,right=right,
                result=Math.Sign(Version.Parse(left).CompareTo(Version.Parse(right)))});

        var checker=typeof(Condition).Assembly.GetType("SE.DAD.SESU.Common.Validation.ClientConditionChecker",true);
        var method=checker.GetMethod("EvaluateFileVersion",BindingFlags.Static|BindingFlags.NonPublic);
        foreach(JObject file in (JArray)plan["files"]) {
            string path=(string)file["path"];
            string observed=File.Exists(path)?FileVersionInfo.GetVersionInfo(path).FileVersion:null;
            Emit(new{stage="original-file-fixture",label=(string)file["label"],exists=File.Exists(path),observed_file_version=observed});
            foreach(var right in plan["rights"].Select(x=>(string)x))
            foreach(var how in plan["hows"].Select(x=>(int)x)) {
                var condition=new Condition{WhatToCheck=(WhatToCheck)2,HowToCheck=(HowToCheck)how,
                    FileOrRegistryKeyPath=path,ComparisonRightSideValue=right};
                try {
                    var result=(bool)method.Invoke(null,new object[]{"probe",condition});
                    Emit(new{stage="original-file-version",file=(string)file["label"],right=right,how=how,result=result});
                } catch(TargetInvocationException error) {
                    Emit(new{stage="original-file-version",file=(string)file["label"],right=right,how=how,
                        error=error.InnerException.GetType().FullName,message=error.InnerException.Message});
                }
            }
        }
        Emit(new{stage="complete",runtime=Environment.Version.ToString(),original_dll_modified=false,network_calls=0,registry_operations=0});
        return 0;
    }
}
