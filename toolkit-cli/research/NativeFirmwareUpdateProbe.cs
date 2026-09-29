// Runs the unchanged updater's private UnzipFirmwarePackage and UpgradeFirmware
// methods with an argv-recording dfuprog stub. Unit discovery/identification in
// FirmwareUpgrader_DoWork needs WMI, so its argument assignments and required-file
// check are retyped below. No USB device, driver or physical serial port is used.
using System;
using System.ComponentModel;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using FirmwareUpdater;

class NativeFirmwareUpdateProbe {
 [DllImport("libutil.so.1")] static extern int openpty(out int master,out int slave,IntPtr name,IntPtr termios,IntPtr winsize);
 [DllImport("libc.so.6")] static extern IntPtr ttyname(int descriptor);
 [DllImport("libc.so.6")] static extern IntPtr read(int descriptor,byte[] data,UIntPtr count);
 [DllImport("libc.so.6")] static extern IntPtr write(int descriptor,byte[] data,UIntPtr count);
 [DllImport("libc.so.6")] static extern void _exit(int status);
 const BindingFlags Private=BindingFlags.NonPublic|BindingFlags.Instance;
 static readonly object Gate=new object();
 static string B(string value) {return Convert.ToBase64String(Encoding.UTF8.GetBytes(value??""));}
 static void Output(string category,string key,string value) {lock(Gate)Console.WriteLine(category+"\t"+B(key)+"\t"+B(value));}
 static string Describe(string path) {
  if(string.IsNullOrEmpty(path))return "";
  if(!File.Exists(path))return Path.GetFileName(path)+"|missing";
  using(var sha=SHA256.Create())return Path.GetFileName(path)+"|"+new FileInfo(path).Length+"|"+BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(path))).Replace("-","").ToLowerInvariant();
 }
 // Scripted unit on the PTY master: records each command and replies in order.
 static void Responder(int master,string[] replies) {
  var buffer=new byte[256];var text="";int index=0;
  while(true) {
   long count=read(master,buffer,(UIntPtr)buffer.Length).ToInt64();
   if(count<=0)return;
   text+=Encoding.ASCII.GetString(buffer,0,(int)count);
   int end;
   while((end=text.IndexOf('\r'))>=0) {
    string command=text.Substring(0,end);text=text.Substring(end+1);
    Output("serial-command",index.ToString(),command);
    if(index<replies.Length&&replies[index].Length>0) {
     byte[] data=Encoding.ASCII.GetBytes(replies[index].Replace("\\r\\n","\r\n"));
     write(master,data,(UIntPtr)data.Length);
    }
    index++;
   }
  }
 }
 static void Main(string[] args) {
  string package=args[0],hardware=args[1],stub=args[3];bool force=args[2]=="1";
  string[] replies=args.Length>4?args[4].Split('|'):null;
  Type type=typeof(FirmwareUpdater.FirmwareUpdater);
  object updater=FormatterServices.GetUninitializedObject(type);
  type.GetField("_defaultDirectory",Private).SetValue(updater,stub.EndsWith("/")?stub:stub+"/");
  // A constructed CheckBox would initialize GDI+. The original reads only
  // Checked, whose Mono implementation reflects the private check_state field.
  var box=(CheckBox)FormatterServices.GetUninitializedObject(typeof(CheckBox));
  typeof(CheckBox).GetField("check_state",Private).SetValue(box,force?CheckState.Checked:CheckState.Unchecked);
  type.GetField("ForceFontUpgradeCheckBox",Private).SetValue(updater,box);
  Output("assembly","version",type.Assembly.GetName().Version.ToString());
  Output("force","checked",box.Checked.ToString());
  var extracted=(EdltFirmwarePackage)type.GetMethod("UnzipFirmwarePackage",Private).Invoke(updater,new object[]{package});
  Output("package","version",extracted.PackageVersion);
  Output("extracted","StellarisPCI",Describe(extracted.StellarisPCIFirmwareFile));
  Output("extracted","TivaPCI",Describe(extracted.TivaPCIFirmwareFile));
  Output("extracted","TivaNCC",Describe(extracted.TivaNCCFirmwareFile));
  Output("extracted","Font",Describe(extracted.FontDataFile));
  // Retyped from FirmwareUpgrader_DoWork after its unit identification.
  var upgrade=new EdltFirmwareUpgradeArgs();
  upgrade.HardwareVersion=hardware;
  upgrade.StellarisPCIFirmwareImage=extracted.StellarisPCIFirmwareFile;
  upgrade.TivaPCIFirmwareImage=extracted.TivaPCIFirmwareFile;
  upgrade.TivaNCCFirmwareImage=extracted.TivaNCCFirmwareFile;
  upgrade.FontData=extracted.FontDataFile;
  upgrade.UpgradeFirmwareVersion=extracted.PackageVersion;
  Output("variant",hardware,upgrade.Variant.ToString());
  int master=-1,slave=-1;
  try {
   if((upgrade.Variant==EdltVariant.StellarisPCI&&string.IsNullOrWhiteSpace(upgrade.StellarisPCIFirmwareImage))||(upgrade.Variant==EdltVariant.TivaPCI&&string.IsNullOrWhiteSpace(upgrade.TivaPCIFirmwareImage))||(upgrade.Variant==EdltVariant.TivaNCC&&string.IsNullOrWhiteSpace(upgrade.TivaNCCFirmwareImage))||string.IsNullOrWhiteSpace(upgrade.FontData)) {
    Output("result","dowork","The selected firmware archive is not compatible with the connected eDLT unit.");
    return;
   }
   if(replies!=null) {
    if(openpty(out master,out slave,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero)!=0)throw new Exception("openpty failed");
    upgrade.SerialPortName=Marshal.PtrToStringAnsi(ttyname(slave));
    int owned=master;var thread=new Thread(()=>Responder(owned,replies));thread.IsBackground=true;thread.Start();
   }
   var worker=new BackgroundWorker();worker.WorkerReportsProgress=true;
   worker.ProgressChanged+=(sender,e)=>{var state=e.UserState as EdltUpgradeProgressArgs;Output("progress",e.ProgressPercentage.ToString(),state==null?"":state.Message);};
   try {
    type.GetMethod("UpgradeFirmware",Private).Invoke(updater,new object[]{worker,upgrade});
    Output("result","upgrade","returned");
   } catch(TargetInvocationException error) {
    Exception inner=error.InnerException;
    Output("result","exception",inner.GetType().Name+"|"+inner.Message+"|"+inner.Data.Contains("SuccessFlag"));
   }
  } finally {
   // RunWorkerCompleted deletes every extracted path.
   foreach(string path in new string[]{extracted.StellarisPCIFirmwareFile,extracted.TivaPCIFirmwareFile,extracted.TivaNCCFirmwareFile,extracted.FontDataFile})
    if(!string.IsNullOrEmpty(path)&&File.Exists(path))File.Delete(path);
   // The PTY pair closes with the process; closing the master here can block
   // behind the responder's read. Runtime shutdown is skipped because an
   // unrelated System.Drawing finalizer needs the global libgdiplus path.
   Console.Out.Flush();
   _exit(0);
  }
 }
}
