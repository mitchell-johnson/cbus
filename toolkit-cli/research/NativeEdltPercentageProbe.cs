using System;
using System.Globalization;
public class ControlFixture {
  public decimal Value, Minimum=0m, Maximum=100m;
  public decimal GetValue() { return Value; }
  public decimal GetMinimum() { return Minimum; }
  public decimal GetMaximum() { return Maximum; }
  public void SetValue(decimal v) { Value=v; }
  public int OriginalGet() { throw new NotImplementedException(); }
  public void OriginalSet(int v) { throw new NotImplementedException(); }
}
class Probe {
  static string DecimalText(decimal v) {return v.ToString(CultureInfo.InvariantCulture);}
  static string SHA(string path) {
    using(var hash=System.Security.Cryptography.SHA256.Create())
    using(var file=System.IO.File.OpenRead(path))return BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
  }
  static void Main(string[] args) {
    var assembly=typeof(decimal).Assembly;
    Console.Error.WriteLine("decimal_runtime\t"+assembly.Location+"\t"+assembly.FullName+"\t"+SHA(assembly.Location)+"\tpointer_bits\t"+(IntPtr.Size*8));
    Console.Error.WriteLine("executable\t"+System.Reflection.Assembly.GetExecutingAssembly().Location+"\t"+SHA(System.Reflection.Assembly.GetExecutingAssembly().Location));
    for(int v=0;v<=255;v++) {
      var c=new ControlFixture();c.OriginalSet(v);
      Console.WriteLine("roundtrip\t"+v+"\t"+DecimalText(c.Value)+"\t"+c.OriginalGet());
    }
    foreach(var input in new[]{"0","0.1","0.3921568627450980392156862745","1","10","33.333333333333333333333333333","50","66.666666666666666666666666667","99.9","100"}) {
      var c=new ControlFixture {Value=Decimal.Parse(input,CultureInfo.InvariantCulture)};
      Console.WriteLine("get\t"+input+"\t"+c.OriginalGet());
    }
    foreach(var bounds in new[]{new[]{0m,100m},new[]{1.5m,99.5m},new[]{-10.5m,110.5m}}) {
      foreach(var value in new[]{Int32.MinValue,-1,0,1,254,255,256,Int32.MaxValue}) {
        var c=new ControlFixture {Minimum=bounds[0],Maximum=bounds[1]};c.OriginalSet(value);
        Console.WriteLine("set\t"+value+"\t"+DecimalText(c.Minimum)+"\t"+DecimalText(c.Maximum)+"\t"+DecimalText(c.Value));
      }
    }
    foreach(var line in System.IO.File.ReadAllLines(args[0])) {
      var parts=line.Split('\t');
      var c=new ControlFixture { Value=new Decimal(unchecked((int)UInt32.Parse(parts[0],CultureInfo.InvariantCulture)),unchecked((int)UInt32.Parse(parts[1],CultureInfo.InvariantCulture)),unchecked((int)UInt32.Parse(parts[2],CultureInfo.InvariantCulture)),false,Byte.Parse(parts[3],CultureInfo.InvariantCulture)) };
      Console.WriteLine("get96\t"+DecimalText(c.Value)+"\t"+c.OriginalGet()+"\t"+line);
    }
  }
}
