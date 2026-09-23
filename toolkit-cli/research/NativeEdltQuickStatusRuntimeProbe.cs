// Read-only hashes of assemblies loaded by this owned original-controls probe.
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Diagnostics;
using System.Collections.Generic;
using System.ComponentModel;
using System.Security.Cryptography;
using System.Windows.Forms;
using CBusLogicModel.Units.EDLT;
using eDLT.Controls;
class WindowsQuickStatusRuntimeProbe {
 static void FileRow(string kind,string identity,string path) {
  string hash;using(var stream=File.OpenRead(path))using(var sha=SHA256.Create())hash=BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
  Console.WriteLine(kind+"\t"+identity+"\t"+path+"\t"+hash+"\t"+FileVersionInfo.GetVersionInfo(path).FileVersion);
 }
 [STAThread] static void Main() {
  Console.WriteLine("runtime\t"+Environment.Version+"\t"+IntPtr.Size);
  var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
  foreach(var assembly in new[]{typeof(object).Assembly,typeof(Form).Assembly,typeof(BindingSource).Assembly,typeof(PropertyDescriptor).Assembly,typeof(Enumerable).Assembly,typeof(EDLTUnit).Assembly,typeof(LevelControl).Assembly})
   if(seen.Add(assembly.Location))FileRow("assembly",assembly.FullName,assembly.Location);
  foreach(ProcessModule module in Process.GetCurrentProcess().Modules)
   if(string.Equals(module.ModuleName,"clr.dll",StringComparison.OrdinalIgnoreCase))FileRow("runtime-library",module.ModuleName,module.FileName);
 }
}
