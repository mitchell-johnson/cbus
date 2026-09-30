// Owned reflection harness for the unchanged SESU 3.0.7 metadata trust path.
//
// It drives the original MultiPlatformUpdate revocation traversal (RVA 0x39FC)
// and final metadata validator (RVA 0x37E0) over synthetic certificates that
// the runner generates for each run. Synthetic anchors are added only to the
// in-memory WhiteListCert maps of this process; the original DLL is unchanged.
// All certificate, subject and revocation-cache lookups are preseeded, and the
// runner executes this program under a network-denial sandbox.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Runtime.Serialization;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Threading;
using System.Threading.Tasks;
using System.IdentityModel.Tokens.Jwt;
using Microsoft.IdentityModel.Tokens;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using SE.DAD.Core.Client;
using SE.DAD.Signature.Api.Models;
using SE.DAD.Signature.Api.Payload;
using SchneiderElectric.SesuBrick.DAD;

sealed class CapturedOnlyHandler : HttpMessageHandler {
    public string Body, Path, Method;
    public int Count;
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token) {
        if(++Count!=1 || request.Method.Method!=Method || request.RequestUri.AbsolutePath!=Path)
            throw new InvalidOperationException("Unexpected synthetic request");
        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK){Content=new StringContent(Body)});
    }
}

sealed class OwnedLogSink : Serilog.Core.ILogEventSink {
    public static readonly List<object> Events=new List<object>();
    public void Emit(Serilog.Events.LogEvent e) {
        Events.Add(new{level=e.Level.ToString(),message=e.RenderMessage(),
            error=e.Exception==null?null:e.Exception.GetType().FullName,detail=e.Exception==null?null:e.Exception.Message});
    }
}

static class NativeSesuTrustPolicyProbe {
    const BindingFlags Static=BindingFlags.Static|BindingFlags.NonPublic;
    const BindingFlags Instance=BindingFlags.Instance|BindingFlags.NonPublic;
    static readonly DateTime Epoch=new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc);

    static void Emit(object value) { Console.WriteLine(JsonConvert.SerializeObject(value)); }

    static FieldInfo StaticField(Type type, Func<FieldInfo,object,bool> match, string label) {
        var found=type.GetFields(Static).Where(f=>match(f,f.GetValue(null))).ToArray();
        if(found.Length!=1) throw new InvalidOperationException("Expected one original field for "+label+", found "+found.Length);
        return found[0];
    }

    static string Base64Url(byte[] data) { return Convert.ToBase64String(data).TrimEnd('=').Replace('+','-').Replace('/','_'); }

    static string Sign(RSA key, string thumbprint, string policy, string digest, JObject lifetime) {
        // Compact RS256 JWT assembled directly; only the original validator consumes it.
        var now=DateTime.UtcNow;
        var header=new JObject{["alg"]="RS256",["kid"]=thumbprint,["typ"]="JWT",["x5t"]=thumbprint,["pol"]=policy,["crit"]=new JArray("pol")};
        long nbf=(long)(now.AddSeconds((double)lifetime["nbf"])-Epoch).TotalSeconds;
        var payload=new JObject{["nbf"]=nbf,["exp"]=(long)(now.AddSeconds((double)lifetime["exp"])-Epoch).TotalSeconds,
            ["iat"]=nbf,["payload_sha256"]=digest};
        string input=Base64Url(System.Text.Encoding.UTF8.GetBytes(header.ToString(Formatting.None)))+"."+
            Base64Url(System.Text.Encoding.UTF8.GetBytes(payload.ToString(Formatting.None)));
        byte[] signature=key.SignData(System.Text.Encoding.ASCII.GetBytes(input),HashAlgorithmName.SHA256,RSASignaturePadding.Pkcs1);
        return input+"."+Base64Url(signature);
    }

    static object ChainOutcome(X509Certificate2 leaf, IEnumerable<X509Certificate2> extra) {
        // Same policy values as the original final validator at RVA 0x37E0.
        using(var chain=new X509Chain()) {
            chain.ChainPolicy.RevocationMode=X509RevocationMode.NoCheck;
            chain.ChainPolicy.VerificationFlags=X509VerificationFlags.AllowUnknownCertificateAuthority;
            chain.ChainPolicy.ExtraStore.AddRange(extra.ToArray());
            bool built=chain.Build(leaf);
            return new{built=built,
                chain_status=chain.ChainStatus.Select(s=>s.Status.ToString()).OrderBy(s=>s).ToArray(),
                elements=chain.ChainElements.Cast<X509ChainElement>().Select(e=>new{thumbprint=e.Certificate.GetCertHashString(),
                    status=e.ChainElementStatus.Select(s=>s.Status.ToString()).OrderBy(s=>s).ToArray()}).ToArray()};
        }
    }

    static int Main(string[] args) {
        if(args.Length!=3) return 2;
        try {
            using(var socket=new System.Net.Sockets.TcpClient()) socket.Connect(IPAddress.Loopback,int.Parse(args[2]));
            throw new InvalidOperationException("Probe must run with network denied; owned loopback unexpectedly connected");
        } catch(System.Net.Sockets.SocketException error) {
            if(error.SocketErrorCode!=System.Net.Sockets.SocketError.AccessDenied) throw;
            Emit(new{stage="network-sandbox-witness",error=error.SocketErrorCode.ToString()});
        }
        Serilog.Log.Logger=new Serilog.LoggerConfiguration().WriteTo.Sink(new OwnedLogSink()).CreateLogger();
        var plan=JObject.Parse(File.ReadAllText(args[0]));

        var type=typeof(MultiPlatformUpdate);
        var byThumb=(Dictionary<string,X509Certificate2>)type.GetField("\u0005 ",Static).GetValue(null);
        var bySubject=(Dictionary<string,Tuple<X509Certificate2,DateTime>>)type.GetField("\b ",Static).GetValue(null);
        var revocations=(Dictionary<string,Tuple<RevocationList,DateTime>>)type.GetField("\u0006 ",Static).GetValue(null);
        var roots=(Dictionary<string,string>)typeof(WhiteListCert).GetField("\u0002",Static).GetValue(null);
        var signers=(Dictionary<string,string>)typeof(WhiteListCert).GetField("\b",Static).GetValue(null);
        var originalRoots=new Dictionary<string,string>(roots);
        var originalSigners=new Dictionary<string,string>(signers);
        var whitelist=typeof(WhiteListCert);
        var v1Excluded=(List<string>)StaticField(whitelist,(f,v)=>v is List<string> l && l.Count==5,"v1 exclusions").GetValue(null);
        var rv1Excluded=(List<string>)StaticField(whitelist,(f,v)=>v is List<string> l && l.Count==1,"rv1 exclusions").GetValue(null);
        var depth=(int)StaticField(whitelist,(f,v)=>v is int,"maximum depth").GetValue(null);
        var names=whitelist.GetFields(Static).Where(f=>f.FieldType==typeof(string)).Select(f=>(string)f.GetValue(null)).OrderBy(s=>s).ToArray();
        Emit(new{stage="original-policy-constants",root_pin_count=originalRoots.Count,revocation_signer_pin_count=originalSigners.Count,
            v1_excluded=v1Excluded,rv1_excluded=rv1Excluded,maximum_traversal_iterations=depth,signature_names=names});

        var handler=new CapturedOnlyHandler{Body=File.ReadAllText(args[1]),Method="POST",Path="/collections/PackageData/list"};
        List<SE.DAD.Core.Public.Models.Node> nodes;
        using(var http=new HttpClient(handler)) {
            http.BaseAddress=new Uri("https://sw.dad.se.com/");
            var api=new ApiClient(http,null,null,null);
            api.LoadClientPlugin<SE.DAD.Services.ClientAPI.Client.ClientApiPlugin>();api.LoadModelPlugin<SE.DAD.SESU.Common.SESUModelPlugin>();
            var filters=new List<SE.DAD.Core.Common.Models.SearchFilters.SearchFilter>{
                new SE.DAD.Core.Common.Models.SearchFilters.NodeStateFilter((SE.DAD.Core.Common.Models.NodeState)2),
                new SE.DAD.SESU.Common.Models.SearchFilters.ProductAssignmentFilter("435e4274-3bcf-4f3e-a67a-3008278c539c","1.18.0",false)};
            nodes=new SE.DAD.Services.ClientAPI.Client.CollectionApi(api).GetNodeList("PackageData",filters).GetAwaiter().GetResult().ToList();
        }
        var node=nodes[0];
        var traverse=type.GetMethod("\u0002",Instance,null,new[]{typeof(X509Certificate2)},null);
        var validate=type.GetMethod("\u0002",Instance,null,new[]{typeof(SE.DAD.Core.Public.Models.Node)},null);
        var generator=new PayloadGenerator();

        foreach(JObject item in (JArray)plan["cases"]) {
            string label=(string)item["label"];
            byThumb.Clear(); bySubject.Clear(); revocations.Clear(); OwnedLogSink.Events.Clear();
            roots.Clear(); foreach(var pair in originalRoots) roots.Add(pair.Key,pair.Value);
            signers.Clear(); foreach(var pair in originalSigners) signers.Add(pair.Key,pair.Value);
            var certificates=new Dictionary<string,X509Certificate2>();
            var keys=new Dictionary<string,RSA>();
            foreach(JProperty entry in ((JObject)item["certificates"]).Properties()) {
                var cert=new X509Certificate2(Convert.FromBase64String((string)entry.Value["der"]));
                certificates[entry.Name]=cert;
                if(entry.Value["key_xml"]!=null) { var rsa=RSA.Create(); rsa.FromXmlString((string)entry.Value["key_xml"]); keys[entry.Name]=rsa; }
                byThumb[cert.GetCertHashString()]=cert;
                if(entry.Name!=(string)item["leaf"]) bySubject[cert.SubjectName.Name]=Tuple.Create(cert,DateTime.UtcNow.AddMinutes(30));
            }
            foreach(var name in item["pin_roots"]) roots[certificates[(string)name].GetCertHashString()]=certificates[(string)name].GetPublicKeyString();
            foreach(var name in item["pin_signers"]) signers[certificates[(string)name].GetCertHashString()]=certificates[(string)name].GetPublicKeyString();
            var leaf=certificates[(string)item["leaf"]];
            string nodeDigest=generator.GeneratePayload(node,new SignaturePolicy{ExcludedElements=v1Excluded});
            string nodeToken=Sign(keys[(string)item["leaf"]],leaf.GetCertHashString(),"v1",nodeDigest,(JObject)item["node_lifetime"]);
            node.Signatures["v1"]=nodeToken;
            foreach(JObject list in (JArray)item["revocation_lists"]) {
                var subject=certificates[(string)list["for"]].GetCertHashString();
                var value=new RevocationList{Id=list["id"]==null?subject:(string)list["id"],Signatures=new Dictionary<string,string>(),
                    RevokedCertificates=list["revoked_certificates"].Select(x=>(string)x=="$LEAF_LOWER"?leaf.GetCertHashString().ToLowerInvariant():
                        certificates.ContainsKey((string)x)?certificates[(string)x].GetCertHashString():(string)x).ToList(),
                    RevokedSignatures=list["revoked_signatures"].Select(x=>(string)x=="$NODE_TOKEN"?nodeToken:(string)x).ToList()};
                if((bool)list["signed"]) {
                    string digest=generator.GeneratePayload(value,new SignaturePolicy{ExcludedElements=rv1Excluded});
                    var signer=certificates[(string)list["signer"]];
                    value.Signatures["rv1"]=Sign(keys[(string)list["signer"]],signer.GetCertHashString(),"rv1",digest,(JObject)list["lifetime"]);
                }
                revocations[subject]=Tuple.Create(value,DateTime.UtcNow.AddMinutes(30));
            }
            object traversal; HashSet<X509Certificate2> traversed=null;
            try {
                var result=(Tuple<HashSet<X509Certificate2>,HashSet<string>>)traverse.Invoke(FormatterServices.GetUninitializedObject(type),new object[]{leaf});
                traversed=result.Item1;
                traversal=new{accepted=true,certificates=result.Item1.Select(c=>c.GetCertHashString()).OrderBy(s=>s).ToArray(),
                    revoked_signature_count=result.Item2.Count,node_token_revoked=result.Item2.Contains(nodeToken)};
            } catch(TargetInvocationException error) {
                traversal=new{accepted=false,error=error.InnerException.GetType().FullName,message=error.InnerException.Message};
            }
            var chain=ChainOutcome(leaf,traversed??(IEnumerable<X509Certificate2>)certificates.Values);
            OwnedLogSink.Events.Clear();
            var model=(MultiPlatformUpdate)FormatterServices.GetUninitializedObject(type);
            validate.Invoke(model,new object[]{node});
            Emit(new{stage="original-trust-case",label=label,
                thumbprints=certificates.ToDictionary(p=>p.Key,p=>p.Value.GetCertHashString()),
                original_traversal=traversal,x509_chain_with_original_policy=chain,
                original_is_metadata_validated=model.IsMetadataValidated,original_log=OwnedLogSink.Events.ToArray(),
                network_calls=0,registry_operations=0});
        }
        Emit(new{stage="complete",cases=((JArray)plan["cases"]).Count,original_dll_modified=false,
            synthetic_anchors_added_in_memory_only=true,network_denied=true});
        return 0;
    }
}
