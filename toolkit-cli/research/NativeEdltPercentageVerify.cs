using System;
using System.Collections.Generic;
using Mono.Cecil;
using Mono.Cecil.Cil;
class VerifyWritten {
  static void Main(string[] args) {
    using(var source=ModuleDefinition.ReadModule(args[0]))
    using(var target=ModuleDefinition.ReadModule(args[1])) {
      int count=0,branches=0,redirects=0;
      var original=source.GetType("eDLT.Controls.NumUpDownPercentage");
      var fixture=target.GetType("ControlFixture");
      var names=new Dictionary<string,string>{{"get_Value","GetValue"},{"get_Minimum","GetMinimum"},{"get_Maximum","GetMaximum"},{"set_Value","SetValue"}};
      foreach(var name in new[]{"get_PercentageValueAsByte","set_PercentageValueAsByte"}) {
        MethodDefinition src=null,dst=null;
        foreach(var m in original.Methods)if(m.Name==name)src=m;
        foreach(var m in fixture.Methods)if(m.Name==(name.StartsWith("get_")?"OriginalGet":"OriginalSet"))dst=m;
        if(src.Body.Instructions.Count!=dst.Body.Instructions.Count || src.Body.Variables.Count!=dst.Body.Variables.Count || src.Body.ExceptionHandlers.Count!=0 || dst.Body.ExceptionHandlers.Count!=0)throw new Exception("Body shape mismatch");
        for(int i=0;i<src.Body.Instructions.Count;i++) {
          var old=src.Body.Instructions[i];var actual=dst.Body.Instructions[i];count++;
          if(old.OpCode!=actual.OpCode)throw new Exception("Opcode changed");
          if(old.Operand is Instruction) {
            branches++;
            if(src.Body.Instructions.IndexOf((Instruction)old.Operand)!=dst.Body.Instructions.IndexOf((Instruction)actual.Operand))throw new Exception("Branch target changed");
          } else if(old.Operand is MethodReference) {
            var before=(MethodReference)old.Operand;var after=(MethodReference)actual.Operand;
            if(before.DeclaringType.FullName=="System.Windows.Forms.NumericUpDown") {
              redirects++;
              if(after.DeclaringType.FullName!="ControlFixture" || after.Name!=names[before.Name] || after.ReturnType.FullName!=before.ReturnType.FullName || after.Parameters.Count!=before.Parameters.Count)throw new Exception("Property redirect mismatch");
              for(int p=0;p<after.Parameters.Count;p++)if(after.Parameters[p].ParameterType.FullName!=before.Parameters[p].ParameterType.FullName)throw new Exception("Parameter type changed");
            } else if(before.FullName!=after.FullName)throw new Exception("Arithmetic method changed");
          } else if(Convert.ToString(old.Operand)!=Convert.ToString(actual.Operand))throw new Exception("Operand changed");
        }
      }
      Console.WriteLine("verified_instructions\t"+count+"\tbranches\t"+branches+"\tproperty_calls_redirected\t"+redirects);
    }
  }
}
