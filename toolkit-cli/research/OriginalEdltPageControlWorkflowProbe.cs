// Complete original eDLT database-unit workflow through the unchanged model and C-Gate client.
// The original CBusLogicModel opens, edits, saves and reloads the unit; this host only sequences it.
using System;
using System.Collections.Generic;
using System.Reflection;
using CBusLogicModel;
using CBusLogicModel.Logic;
using CBusLogicModel.Units.EDLT;
class OriginalEdltPageControlWorkflowProbe {
 static void Dump(string stage,EDLTUnit u){foreach(var p in u.PPAttributes)Console.WriteLine(stage+"-pp:"+p.Name+"\t"+p.Value);}
 static void Assemblies(){foreach(var a in AppDomain.CurrentDomain.GetAssemblies())if(!a.IsDynamic&&a.Location!="")Console.WriteLine("assembly:"+a.GetName().Name+"\t"+a.Location);}
 static int Main(string[] args) {
  // SharpCGateCommunicator splits replies on Environment.NewLine and skips two
  // characters. Mono on macOS reports "\n"; the Windows platform value is "\r\n".
  typeof(Environment).GetField("nl",BindingFlags.NonPublic|BindingFlags.Static).SetValue(null,"\r\n");
  string stage="connect";
  try {
   if(args.Length<6||(args[5]=="edit"&&args.Length!=7)||(args[5]=="readback"&&args.Length!=6)||(args[5]!="edit"&&args[5]!="readback"))
    throw new ArgumentException("usage: port project network unit oid edit GROUP | readback");
   CBusNetworkGlobalManager.SetCGateConnection("127.0.0.1",int.Parse(args[0]),false);
   stage="network";
   var network=(CBusNetwork)CBusNetworkGlobalManager.GetNetwork(args[1],args[2],false);
   // The Toolkit host answers these metadata requests. Record them; add nothing.
   network.addApplicationEvent+=delegate(string a,out string o){o="";Console.WriteLine("host-request:add-application:"+a);};
   network.addGroupEvent+=delegate(string a,string g,out string o){o="";Console.WriteLine("host-request:add-group:"+a+"/"+g);};
   network.addLevelEvent+=delegate(string a,string g,string l,out string o){o="";Console.WriteLine("host-request:add-level:"+a+"/"+g+"/"+l);};
   foreach(var a in network.Applications)Console.WriteLine("application:"+a.AddressAsInt+":"+a.Groups.Count);
   stage="open";
   // FrmBaseUnit constructs exactly this database unit before LoadUnitThreadMain.
   var unit=new EDLTUnit(args[1],network.Address,args[3],args[4],true,network,null);
   Console.WriteLine("load-result:"+unit.LoadUnit());
   Console.WriteLine("identity:"+unit.UnitType+":"+unit.FirmwareVersion+":"+unit.CatalogNumber);
   Dump("loaded",unit);
   if(args[5]=="readback"){Console.WriteLine("page-control:"+unit.KeySetsEnableGroup.PPAttributeValue);Assemblies();Console.WriteLine("complete:true");return 0;}
   stage="edit";
   var binding=unit.KeySetsEnableGroup;
   Console.WriteLine("binding-before:"+binding.PPAttributeValue+":"+binding.DisabledValue+":"+binding.DataSource.Count);
   // The Page Control combo box writes this bound value through PPAttributeDataSourceLogic.
   binding.PPAttributeValue=int.Parse(args[6]);
   Console.WriteLine("binding-after:"+binding.PPAttributeValue+":"+unit.GetPPAttribute("KeySetsEnableGroup").Value);
   Dump("edited",unit);
   stage="save";
   // FrmBaseUnit.SaveUnit(bDatabase=true,bPhysical=false,bSaveDlt=false,bForceSave=false,global=false).
   unit.Project=network.ProjectName;unit.ShouldAlsoSaveDLt=false;
   Console.WriteLine("save-result:"+unit.SaveUnit(true,false,false,false,new List<string>()));
   foreach(var p in unit.PPAttributes)if(p.HasBeenChanged)Console.WriteLine("changed:"+p.Name);
   Dump("saved",unit);
   Assemblies();Console.WriteLine("complete:true");
   return 0;
  } catch(Exception error) {
   Console.WriteLine("failure-stage:"+stage);Console.WriteLine("failure:"+error.GetType().FullName+":"+error.Message);Assemblies();
   return 1;
  } finally {CGateCommunicatorFactory.CloseConnection();}
 }
}
