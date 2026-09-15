using System;
using System.IO;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using SE.DAD.Core.Client;
using SE.DAD.Core.Common.Models;
using SE.DAD.Core.Common.Models.SearchFilters;
using SE.DAD.Services.ClientAPI.Client;
using SE.DAD.SESU.Common;
using SE.DAD.SESU.Common.Models.SearchFilters;

sealed class ResponseFixtureHandler : HttpMessageHandler {
    public int Count;
    public string Body, Failure;
    public int Status;
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken cancellation) {
        if (++Count != 1) throw new InvalidOperationException("More than one synthetic request");
        Console.WriteLine(JsonConvert.SerializeObject(new {
            stage="captured-request",method=request.Method.Method,url=request.RequestUri.ToString(),
            body=request.Content.ReadAsStringAsync().GetAwaiter().GetResult(),network_calls=0}));
        if(Failure=="http") throw new HttpRequestException("owned synthetic HTTP failure");
        if(Failure=="cancel") throw new TaskCanceledException("owned synthetic cancellation");
        return Task.FromResult(new HttpResponseMessage((HttpStatusCode)Status) {
            Content=new StringContent(Body,Encoding.UTF8,"application/json")});
    }
}
class SesuResponseProbe {
    static int Main(string[] args) {
        if(args.Length!=1) return 2;
        var fixture=JObject.Parse(File.ReadAllText(args[0],new UTF8Encoding(false,true)));
        var handler=new ResponseFixtureHandler {Body=(string)fixture["body"],Status=(int)fixture["status"],Failure=(string)fixture["failure"]};
        using(var http=new HttpClient(handler)) {
            http.BaseAddress=new Uri("https://sw.dad.se.com/");
            var client=new ApiClient(http,null,null,null);
            client.LoadClientPlugin<ClientApiPlugin>();
            client.LoadModelPlugin<SESUModelPlugin>();
            var filters=new List<SearchFilter> {
                new NodeStateFilter((NodeState)2),
                new ProductAssignmentFilter("435e4274-3bcf-4f3e-a67a-3008278c539c",(string)fixture["version"],false)};
            try {
                var value=new CollectionApi(client).GetNodeList("PackageData",filters).GetAwaiter().GetResult();
                Console.WriteLine(JsonConvert.SerializeObject(new {
                    stage="synthetic-response",returned_null=value==null,count=value==null?(int?)null:value.Count,
                    value=value,signature_validation_executed=false,applicability_executed=false}));
            } catch(Exception error) {
                Console.WriteLine(JsonConvert.SerializeObject(new {
                    stage="synthetic-response",error=error.GetType().FullName,message=error.Message,
                    inner_error=error.InnerException==null?null:error.InnerException.GetType().FullName}));
            }
        }
        return handler.Count==1?0:2;
    }
}
