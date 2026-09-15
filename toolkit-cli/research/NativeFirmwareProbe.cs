// Calls unchanged updater metadata and diagnostic parsers on isolated fixtures.
// No updater workflow, firmware archive extraction or physical USB access runs.
using System;
using System.Collections.Generic;
using System.IO.Ports;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using FirmwareUpdater;

class NativeFirmwareProbe {
 [DllImport("libutil.so.1")] static extern int openpty(out int master,out int slave,IntPtr name,IntPtr termios,IntPtr winsize);
 [DllImport("libc.so.6")] static extern IntPtr ttyname(int descriptor);
 [DllImport("libc.so.6")] static extern IntPtr write(int descriptor,byte[] data,UIntPtr count);
 [DllImport("libc.so.6")] static extern int close(int descriptor);
 static string B(string value) {return Convert.ToBase64String(Encoding.UTF8.GetBytes(value));}
 static void Output(string category,string key,string value) {Console.WriteLine(category+"\t"+B(key)+"\t"+B(value));}
 static object Invoke(object target,string method,params object[] args) {
  return target.GetType().GetMethod(method,BindingFlags.NonPublic|BindingFlags.Instance).Invoke(target,args);
 }
 static void Feed(EdltSerialInterface parser,SerialPort port,int master,string method,string text) {
  byte[] data=Encoding.ASCII.GetBytes(text);
  if(write(master,data,(UIntPtr)data.Length).ToInt64()!=data.Length)throw new Exception("PTY fixture short write");
  for(int i=0;i<100&&port.BytesToRead<data.Length;i++)Thread.Sleep(2);
  Invoke(parser,method,port,null);
 }
 static void Main(string[] args) {
  Output("assembly","version",typeof(EdltSerialInterface).Assembly.GetName().Version.ToString());
  foreach(string filename in args) {
   using(var archive=new ICSharpCode.SharpZipLib.Zip.ZipFile(filename)) {
    foreach(ICSharpCode.SharpZipLib.Zip.ZipEntry item in archive)
     Output("archive-entry",System.IO.Path.GetFileName(filename)+"/"+item.Name,item.Size+"|"+item.IsCrypted+"|"+item.IsFile+"|"+item.Crc.ToString("x8"));
   }
  }
  foreach(string hardware in new string[] {""," ","\u001c","\u00a0","1 (Stellaris)","1.0 (Stellaris + PCI)","1 (stellaris)","2 (Tiva)","2 (tIvA)","2.0 (Tiva + PCI)","2.0 (tiva + pci)","3.0 (Tiva + NCC)","3.0 (tiva + ncc)"," 2 (Tiva) ","other"}) {
   var value=new EdltFirmwareUpgradeArgs();value.HardwareVersion=hardware;Output("variant",hardware,value.Variant.ToString());
  }
  foreach(string filename in new string[]{"eDLTFirmware_1.7.0.zip","plain.zip","many_parts_1.2.zip","_1.0.zip","folder/eDLTFirmware_1.5.0.zip"})
   Output("package",filename,new EdltFirmwarePackage(filename).PackageVersion);
  foreach(string version in new string[]{"1.0","1.0.0","1.0.0.0","01.02","1. 2","+1.2","-0.2","\u00a01.2","1.\u20032","1.-1","1","1.2.3.4.5","2147483648.0",""}) {
   try {Output("version",version,new Version(version).CompareTo(new Version("1.0.0")).ToString());}
   catch(Exception error) {Output("version-error",version,error.GetType().Name);}
  }
  int master,slave;
  if(openpty(out master,out slave,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero)!=0)throw new Exception("openpty failed");
  try {
   string path=Marshal.PtrToStringAnsi(ttyname(slave));
   using(var port=new SerialPort(path,9600,Parity.None,8,StopBits.One)) {
    port.Handshake=Handshake.None;port.Open();
    var parser=new EdltSerialInterface();
    Feed(parser,port,master,"IdCommandDataReceived"," Manufacturer = Clipsal\r");
    Output("id-stage","fragment-count",parser.UnitValues.Count.ToString());
    Feed(parser,port,master,"IdCommandDataReceived","\nModel=eDLT\r\nSerial Number=123\r\nVersion=1.0\r\nAuthors=A\r\nCpu_Speed=80\r\nUnit Address=20\r\n");
    foreach(var pair in parser.UnitValues)Output("id",pair.Key,pair.Value);
    foreach(string method in new string[]{"HaveFullFirmware1IdResponse","HaveFullFirmware2IdResponse","HaveFullFirmware3IdResponse"})Output("complete",method,Invoke(parser,method).ToString());
    Feed(parser,port,master,"IdCommandDataReceived","Version=1.7.0\r\n Banner \r\nX=a=b\r\n");
    foreach(string key in new string[]{"Version"," Banner ","X"})Output("id-last",key,parser.UnitValues[key]);
    parser=new EdltSerialInterface();
    Feed(parser,port,master,"NvCommandDataReceived","NCC current version: 1.0.0\r");
    Feed(parser,port,master,"NvCommandDataReceived","\nNCC embedded version: 1.1.0\r\n X : a:b \r\nCOMMAND NOT VALID\r\n");
    foreach(var pair in parser.UnitValues)Output("ncc",pair.Key,pair.Value);
    foreach(var fields in new string[][] {
     new string[]{"Manufacturer","Product","Serial Number","HW Version","FW Version","Authors","Cpu_Speed","Unit Address"},
     new string[]{"Manufacturer","Product","Serial Number","HW Version","FW Version","CPU Speed","Unit Address"}}) {
     parser=new EdltSerialInterface();foreach(string name in fields)parser.UnitValues[name]="fixture";
     foreach(string method in new string[]{"HaveFullFirmware1IdResponse","HaveFullFirmware2IdResponse","HaveFullFirmware3IdResponse"})Output("schema-"+fields.Length,method,Invoke(parser,method).ToString());
    }
   }
  } finally {close(master);close(slave);}
 }
}
