using System;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using CBusLogicModel;
class Probe {
 static string Hash(string path){using(var f=File.OpenRead(path))using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(f)).Replace("-","").ToLowerInvariant();}
 static void Main(string[] args){
  foreach(var type in new[]{typeof(Crc16Ccitt),typeof(object),typeof(Probe)})Console.Error.WriteLine(type.FullName+"\t"+type.Assembly.Location+"\t"+Hash(type.Assembly.Location)+"\t"+IntPtr.Size*8);
  using(var output=Console.OpenStandardOutput()){
   for(int value=0;value<65536;value++){
    var data=new[]{(byte)(value>>8),(byte)value};ushort crc=Crc16Ccitt.checkCrc16(data,0,2);
    output.WriteByte((byte)(crc>>8));output.WriteByte((byte)crc);
   }
   int count=0;foreach(string line in File.ReadLines(args[0])){
    if(++count>128)throw new Exception("Input bound");var data=Convert.FromBase64String(line);if(data.Length>65536)throw new Exception("Buffer bound");
    ushort crc=Crc16Ccitt.checkCrc16(data,0,data.Length);output.WriteByte((byte)(crc>>8));output.WriteByte((byte)crc);
   }
  }
 }
}
