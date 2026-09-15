using System;
using System.Collections.Generic;
using Mono.Cecil;
using Mono.Cecil.Cil;
class Extract {
  static void Main(string[] args) {
    using(var source=ModuleDefinition.ReadModule(args[0]))
    using(var target=ModuleDefinition.ReadModule(args[1])) {
      var original=source.GetType("eDLT.Controls.NumUpDownPercentage");
      var fixture=target.GetType("ControlFixture");
      var replacements=new Dictionary<string,string> {{"get_Value","GetValue"},{"get_Minimum","GetMinimum"},{"get_Maximum","GetMaximum"},{"set_Value","SetValue"}};
      foreach(var name in new[]{"get_PercentageValueAsByte","set_PercentageValueAsByte"}) {
        MethodDefinition src=null,dst=null;
        foreach(var m in original.Methods) if(m.Name==name)src=m;
        foreach(var m in fixture.Methods) if(m.Name==(name.StartsWith("get_")?"OriginalGet":"OriginalSet"))dst=m;
        dst.Body=new MethodBody(dst);dst.Body.InitLocals=src.Body.InitLocals;dst.Body.MaxStackSize=src.Body.MaxStackSize;
        foreach(var local in src.Body.Variables)dst.Body.Variables.Add(new VariableDefinition(target.ImportReference(local.VariableType)));
        var instructions=new Dictionary<Instruction,Instruction>();
        foreach(var old in src.Body.Instructions) {
          var item=Instruction.Create(OpCodes.Nop);item.OpCode=old.OpCode;
          instructions.Add(old,item);dst.Body.Instructions.Add(item);
        }
        foreach(var old in src.Body.Instructions) {
          object operand=old.Operand;
          var method=operand as MethodReference;
          if(method!=null) {
            if(method.DeclaringType.FullName=="System.Windows.Forms.NumericUpDown") {
              string replacement=replacements[method.Name];MethodDefinition found=null;
              foreach(var m in fixture.Methods)if(m.Name==replacement)found=m;
              operand=found;
            } else operand=target.ImportReference(method);
          } else if(operand is Instruction) operand=instructions[(Instruction)operand];
          else if(operand is VariableDefinition)operand=dst.Body.Variables[((VariableDefinition)operand).Index];
          else if(operand is ParameterDefinition)operand=dst.Parameters[((ParameterDefinition)operand).Index];
          else if(operand is TypeReference)operand=target.ImportReference((TypeReference)operand);
          instructions[old].Operand=operand;
          Console.WriteLine(name+"\t"+old+"\t"+instructions[old].OpCode+" "+operand);
        }
      }
      target.Write(args[2]);
    }
  }
}
