// Metadata-only extraction. Never loads, constructs, or invokes vendor types.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Web.Script.Serialization;
using Mono.Cecil;
using Mono.Cecil.Cil;

class EdltTemplateRebindMetadata {
    static Dictionary<string, object> Row(params object[] entries) {
        var row = new Dictionary<string, object>();
        for (int i=0; i<entries.Length; i+=2) row.Add((string)entries[i], entries[i+1]);
        return row;
    }
    static int Offset(Instruction i) { return i == null ? -1 : i.Offset; }
    static string Hash(byte[] bytes) {
        using (var hash=SHA256.Create()) return BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
    }
    static byte[] RawBody(byte[] image, int rva) {
        using (var stream=new MemoryStream(image)) using(var r=new BinaryReader(stream)) {
            stream.Position=0x3c; int pe=r.ReadInt32(); stream.Position=pe+6; int sections=r.ReadUInt16();
            stream.Position=pe+20; int optional=r.ReadUInt16(); int table=pe+24+optional;
            for(int i=0;i<sections;i++) {
                stream.Position=table+i*40+8; int size=r.ReadInt32(), virtualAddress=r.ReadInt32(), rawSize=r.ReadInt32(), pointer=r.ReadInt32();
                if(rva < virtualAddress || rva >= virtualAddress+Math.Max(size,rawSize)) continue;
                int position=pointer+rva-virtualAddress; byte first=image[position]; int header, length;
                if((first&3)==2) {header=1;length=first>>2;}
                else if((first&3)==3) {header=(BitConverter.ToUInt16(image,position)>>12)*4;length=BitConverter.ToInt32(image,position+4);}
                else throw new Exception("Unsupported method header");
                return image.Skip(position+header).Take(length).ToArray();
            }
        }
        throw new Exception("RVA not mapped");
    }
    static object Operand(object value) {
        if(value==null) return null;
        var branch=value as Instruction; if(branch!=null) return Row("kind","branch","offset",branch.Offset);
        var variable=value as VariableDefinition; if(variable!=null) return Row("kind","local","index",variable.Index);
        var parameter=value as ParameterDefinition; if(parameter!=null) return Row("kind","arg","index",parameter.Index+1);
        var method=value as MethodReference;
        if(method!=null) return Row("kind","method","name",method.Name,"type",method.DeclaringType.FullName,
            "parameters",method.Parameters.Count,"instance",method.HasThis,"returns",method.ReturnType.FullName,
            "signature",method.FullName);
        var field=value as FieldReference; if(field!=null) return Row("kind","field","name",field.Name,"type",field.DeclaringType.FullName);
        var type=value as TypeReference; if(type!=null) return Row("kind","type","name",type.FullName);
        if(value is string || value is int || value is sbyte || value is byte) return value;
        return Row("kind","unsupported","type",value.GetType().FullName);
    }
    static void Main(string[] args) {
        byte[] raw=File.ReadAllBytes(args[0]);
        if(Hash(raw)!="75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3") throw new Exception("Vendor hash mismatch");
        var names=new HashSet<string>(new[]{"BeforeChangePpAttributes","AfterChangePpAttributes","PopulateWidgetPanels",
            "SetupForm","SetUpControls","ResetControlBinding","UpdateNavigationControl","ShowSelectedWidget",
            "tpKeyFunctions_SelectedIndexChanged","ClearControlsRecursively","ResumeDrawing","ShowWidget","FilterWidgets",
            "set_WidgetPage"});
        using(var module=ModuleDefinition.ReadModule(args[0])) {
            var type=module.Types.Single(t=>t.FullName=="eDLT.FrmBaseUnit"); var methods=new List<object>();
            foreach(var m in type.Methods.Where(m=>names.Contains(m.Name))) {
                var instructions=m.Body.Instructions.Select(i=>Row("offset",i.Offset,"opcode",i.OpCode.Name,"operand",Operand(i.Operand))).ToArray();
                var handlers=m.Body.ExceptionHandlers.Select(h=>Row("kind",h.HandlerType.ToString(),
                    "try_start",Offset(h.TryStart),"try_end",Offset(h.TryEnd),"handler_start",Offset(h.HandlerStart),
                    "handler_end",Offset(h.HandlerEnd),"catch_type",h.CatchType==null?null:h.CatchType.FullName)).ToArray();
                methods.Add(Row("name",m.Name,"token",m.MetadataToken.ToUInt32().ToString("x8"),"rva",m.RVA,
                    "il_sha256",Hash(RawBody(raw,m.RVA)),"il_size",m.Body.CodeSize,"locals",m.Body.Variables.Count,
                    "instructions",instructions,"handlers",handlers));
            }
            var serializer=new JavaScriptSerializer(); serializer.MaxJsonLength=4*1024*1024;
            Console.WriteLine(serializer.Serialize(Row("assembly_sha256",Hash(raw),"original_methods_executed",false,"methods",methods)));
        }
    }
}
