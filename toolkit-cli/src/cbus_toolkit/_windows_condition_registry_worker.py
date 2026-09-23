"""Authored Framework worker source; no proprietary assembly is embedded."""

SOURCE = r'''
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;
using Microsoft.Win32;

internal static class RegistryWorker {
  [DllImport("kernel32.dll")] static extern uint GetCurrentProcessId();
  const string Sentinel = "23021957-xxx-yy-z-27331bfa-adf0-46be-8d44-18b1a831affe";
  static string root, nonce;
  static readonly Encoding Utf8 = new UTF8Encoding(false, true);
  static string B64(string s) { return Convert.ToBase64String(Utf8.GetBytes(s)); }
  static string Text(string s) {
    byte[] b = Convert.FromBase64String(s);
    if (Convert.ToBase64String(b) != s) throw new InvalidOperationException("Noncanonical base64");
    return Utf8.GetString(b);
  }
  static string Hex(byte[] b) { return BitConverter.ToString(b).Replace("-", "").ToLowerInvariant(); }
  static string Hash(byte[] b) { using (SHA256 h = new SHA256Managed()) return Hex(h.ComputeHash(b)); }
  static string FileHash(string p) {
    using (FileStream f = new FileStream(p, FileMode.Open, FileAccess.Read, FileShare.Read))
    using (SHA256 h = new SHA256Managed()) return Hex(h.ComputeHash(f));
  }
  static void Ordinary(string value, int min, int max) {
    if (value.Length < min || value.Length > max) throw new InvalidOperationException("Text bound");
    foreach (char c in value) if (c < 32 || c >= 127) throw new InvalidOperationException("Text domain");
  }
  static void Regular(string p) {
    FileAttributes a = File.GetAttributes(p);
    if ((a & (FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0)
      throw new InvalidOperationException("Not an ordinary file");
  }
  static string Read(string name) {
    string p = Path.Combine(root, name); Regular(p);
    using (FileStream f = new FileStream(p, FileMode.Open, FileAccess.Read, FileShare.Read)) {
      if (f.Length > 16384) throw new InvalidOperationException("Input bound");
      byte[] b = new byte[16385]; int n = 0, got;
      while (n < b.Length && (got = f.Read(b, n, b.Length-n)) != 0) n += got;
      if (n > 16384) throw new InvalidOperationException("Input bound");
      foreach (byte c in b) if (c > 127) throw new InvalidOperationException("Non-ASCII transport");
      return Encoding.ASCII.GetString(b, 0, n);
    }
  }
  static void Publish(string name, string text) {
    byte[] b = Encoding.ASCII.GetBytes(text);
    if (b.Length > 16384) throw new InvalidOperationException("Output bound");
    string temp = Path.Combine(root, name + ".partial"), final = Path.Combine(root, name);
    using (FileStream f = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
      f.Write(b, 0, b.Length); f.Flush(true);
    }
    File.Move(temp, final);
  }
  static string[] Query(string wire) {
    string[] f = wire.Split('\t');
    if (f.Length != 4) throw new InvalidOperationException("Query shape");
    string p = Text(f[0]), e = Text(f[1]), d = Text(f[3]);
    Ordinary(p, 1, 1024); Ordinary(e, 1, 256);
    const string prefix = "HKEY_CURRENT_USER\\";
    if (!p.StartsWith(prefix, StringComparison.Ordinal)) throw new InvalidOperationException("Query hive");
    foreach (string component in p.Substring(prefix.Length).Split('\\'))
      if (component.Length == 0) throw new InvalidOperationException("Empty path component");
    if (!((f[2] == "I" && d == "1") || (f[2] == "S" && d == Sentinel)))
      throw new InvalidOperationException("Query default");
    return new string[] {p, e, f[2], d};
  }
  static string Limited(string s) {
    return s.Length > 512 ? s.Substring(0, 512) : s;
  }
  static void Run(string[] args) {
    if (args.Length != 2) throw new InvalidOperationException("Arguments");
    root = Path.GetFullPath(args[0]); nonce = args[1];
    if ((File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0)
      throw new InvalidOperationException("Reparse root");
    if (nonce.Length != 32) throw new InvalidOperationException("Nonce");
    foreach (char c in nonce) if (!(c >= '0' && c <= '9') && !(c >= 'a' && c <= 'f'))
      throw new InvalidOperationException("Nonce");
    Thread.CurrentThread.CurrentCulture = CultureInfo.InvariantCulture;
    Thread.CurrentThread.CurrentUICulture = CultureInfo.InvariantCulture;
    Thread watch = new Thread(delegate() { Thread.Sleep(90000); Environment.Exit(124); });
    watch.IsBackground = true; watch.Start();
    if (IntPtr.Size != 4) throw new InvalidOperationException("x86 required");
    Assembly runtime = typeof(object).Assembly;
    MethodInfo provider = typeof(Registry).GetMethod("GetValue", new Type[] {typeof(string), typeof(string), typeof(object)});
    string runtimeHash = FileHash(runtime.Location), ilHash = Hash(provider.GetMethodBody().GetILAsByteArray());
    if (runtimeHash != "93d46bdac1664dba87641925572c789d71a21bb01dc7c7e5aa99c0eca8335e5e" ||
        runtime.ManifestModule.ModuleVersionId.ToString() != "5f1a0e73-9147-408f-b533-0f636e32558c" ||
        provider.MetadataToken != 0x060000f3 || provider.DeclaringType.Assembly != runtime ||
        ilHash != "c0363d229d83fb9ca8d8c88ef77816bbd3971cec725fafb68ef96d1486024b72" ||
        provider.ReturnType != typeof(object) ||
        !String.Equals(runtime.Location, @"C:\Windows\Microsoft.NET\Framework\v4.0.30319\mscorlib.dll", StringComparison.OrdinalIgnoreCase))
      throw new InvalidOperationException("Unaccepted Framework provider");
    string[] scopeLines = Read("scope").Split('\n');
    if (scopeLines.Length < 1 || scopeLines.Length > 8) throw new InvalidOperationException("Scope count");
    List<string> scope = new List<string>();
    foreach (string line in scopeLines) { Query(line); if (scope.Contains(line)) throw new InvalidOperationException("Duplicate scope"); scope.Add(line); }
    Assembly self = Assembly.GetExecutingAssembly(); string sid;
    using (WindowsIdentity user = WindowsIdentity.GetCurrent()) sid = user.User.Value;
    Publish("ready", String.Join("\t", new string[] {"READY1", nonce, GetCurrentProcessId().ToString(CultureInfo.InvariantCulture),
      "4", B64(runtime.Location), runtimeHash, runtime.ManifestModule.ModuleVersionId.ToString(),
      "060000f3", ilHash, B64(self.Location), FileHash(self.Location), B64(sid)}));
    int index = 0;
    while (true) {
      string name = "q" + index.ToString("000", CultureInfo.InvariantCulture);
      if (File.Exists(Path.Combine(root, "finish"))) {
        if (Read("finish") != nonce + "\t" + index.ToString(CultureInfo.InvariantCulture))
          throw new InvalidOperationException("Finish correlation");
        Publish("done", "DONE1\t" + nonce + "\t" + index.ToString(CultureInfo.InvariantCulture)); return;
      }
      if (!File.Exists(Path.Combine(root, name + ".request"))) { Thread.Sleep(10); continue; }
      if (index >= 8) throw new InvalidOperationException("Query count");
      string request = Read(name + ".request"), prefix = nonce + "\t" + index.ToString(CultureInfo.InvariantCulture) + "\t";
      if (!request.StartsWith(prefix, StringComparison.Ordinal)) throw new InvalidOperationException("Request correlation");
      string wire = request.Substring(prefix.Length);
      if (!scope.Contains(wire)) throw new InvalidOperationException("Query outside scope");
      string[] q = Query(wire); string outcome;
      try {
        object value = Registry.GetValue(q[0], q[1], q[2] == "I" ? (object)1 : (object)Sentinel);
        if (value == null) outcome = "VALUE\tN\t";
        else if (value.GetType() == typeof(int)) outcome = "VALUE\tI\t" + B64(((int)value).ToString(CultureInfo.InvariantCulture));
        else if (value.GetType() == typeof(string)) {
          string text = (string)value; bool admitted = text.Length <= 256;
          foreach (char c in text) if (c == 0 || c > 127) admitted = false;
          outcome = admitted ? "VALUE\tS\t" + B64(text) : "UNSUPPORTED\t" + B64("System.String") + "\t" + B64("String outside bounded ASCII domain");
        } else outcome = "UNSUPPORTED\t" + B64(Limited(value.GetType().FullName)) + "\t" + B64("CLR result type outside profile");
      } catch (Exception e) {
        outcome = "ERROR\t" + B64(Limited(e.GetType().FullName)) + "\t" + B64(Limited(e.Message));
      }
      Publish(name + ".response", "RESPONSE1\t" + nonce + "\t" + index.ToString(CultureInfo.InvariantCulture) + "\t" +
        Hash(Encoding.ASCII.GetBytes(request)) + "\t" + outcome);
      index++;
      if (!outcome.StartsWith("VALUE\t", StringComparison.Ordinal)) return;
    }
  }
  static int Main(string[] args) {
    try { Run(args); return 0; }
    catch (Exception e) { Console.Error.WriteLine(e.GetType().FullName + ": " + e.Message); return 2; }
  }
}
'''
