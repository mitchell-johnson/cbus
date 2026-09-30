// Branch proxy only. Cecil reads original metadata; the runtime loads this
// owned assembly with six copied methods whose model/UI dependencies are stubs.
// No original form, validators, network client, or persistence method executes.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;

public delegate void FixtureSaveRequest(bool close);
public class FixtureClosedArgs {}
public class FixtureParent {
    public void Close() { FixtureForm.Events.Add("parent-close"); }
}
public class FixtureWidget {
    public int Kind;
    public int WidgetType { get { return Kind; } }
}
public class FixtureUnit {
    public BindingList<FixtureWidget> Widgets { get {
        FixtureForm.Events.Add("widgets");
        return new BindingList<FixtureWidget>(new List<FixtureWidget> {
            new FixtureWidget { Kind=1 }, new FixtureWidget { Kind=6 },
            new FixtureWidget { Kind=3 }, new FixtureWidget { Kind=6 }});
    } }
    public bool IsValid(ref List<string> errors) {
        FixtureForm.Events.Add("unit-valid");
        FixtureForm.MaybeThrow("unit");
        if (!FixtureForm.UnitValid) errors.AddRange(new[]{"first", "second"});
        return FixtureForm.UnitValid;
    }
}
public class FixtureForm {
    public static List<string> Events = new List<string>();
    public static bool SerialValid=true, SceneValid=true, UnitValid=true;
    public static string ThrowAt="";
    public static Func<FixtureWidget,bool> CachedPredicate;
    public FixtureUnit _unit = new FixtureUnit();
    public FixtureSaveRequest saveUnitDialogRequest;
    public bool GlobalProgrammingMode;
    public FixtureParent Parent;
    public static void MaybeThrow(string stage) {
        if (ThrowAt == stage) throw new InvalidOperationException(stage);
    }
    public bool ValidateSerialNumber() {
        Events.Add("serial-valid"); MaybeThrow("serial"); return SerialValid;
    }
    public bool ValidateSceneWidgetConfig(IEnumerable<FixtureWidget> widgets) {
        Events.Add("scene-valid:" + string.Join(",", widgets.Select(w => w.Kind.ToString()).ToArray()));
        MaybeThrow("scene"); return SceneValid;
    }
    public void InvalidFormDialog(string text) {
        Events.Add("invalid-form:" + text.Replace("\r", "").Replace("\n", "|"));
    }
    public FixtureParent get_ParentForm() { Events.Add("parent"); return Parent; }
    public virtual void OnFormClosed(FixtureClosedArgs args) { Events.Add("closed:" + (args==null ? "null" : "event")); }
    // Bodies below are replaced only in a new output assembly.
    public bool Save(bool close) { throw new Exception("not replaced"); }
    public void SaveDialog(bool close) { throw new Exception("not replaced"); }
    public static bool Predicate(FixtureWidget widget) { throw new Exception("not replaced"); }
    public void btnApply_Click(object sender, EventArgs args) { throw new Exception("not replaced"); }
    public void btnOk_Click(object sender, EventArgs args) { throw new Exception("not replaced"); }
    public void btnCancel_Click(object sender, EventArgs args) { throw new Exception("not replaced"); }
}

class EdltTemplateTerminalProbe {
    static ModuleDefinition target;
    static readonly Dictionary<string,string> TypeNames = new Dictionary<string,string> {
        {"eDLT.FrmBaseUnit", "FixtureForm"},
        {"eDLT.FrmBaseUnit/SaveUnitDialogRequest", "FixtureSaveRequest"},
        {"CBusLogicModel.Units.EDLT.EDLTUnit", "FixtureUnit"},
        {"CBusLogicModel.Units.EDLT.EDLTWidget", "FixtureWidget"},
        {"System.Windows.Forms.ContainerControl", "FixtureForm"},
        {"System.Windows.Forms.Form", "FixtureParent"},
        {"System.Windows.Forms.FormClosedEventArgs", "FixtureClosedArgs"},
    };
    static TypeReference MapType(TypeReference type) {
        string mapped;
        if (TypeNames.TryGetValue(type.FullName, out mapped)) return target.GetType(mapped);
        var generic = type as GenericInstanceType;
        if (generic != null) {
            var output = new GenericInstanceType(MapType(generic.ElementType));
            foreach (var arg in generic.GenericArguments) output.GenericArguments.Add(MapType(arg));
            return output;
        }
        var byref = type as ByReferenceType;
        if (byref != null) return new ByReferenceType(MapType(byref.ElementType));
        if (type is GenericParameter) return type;
        return target.ImportReference(type);
    }
    static MethodReference MapMethod(MethodReference source) {
        string mapped;
        if (TypeNames.TryGetValue(source.DeclaringType.FullName, out mapped)) {
            string name = source.Name == "<Save>b__18" ? "Predicate" : source.Name;
            return target.GetType(mapped).Methods.Single(m => m.Name == name && m.Parameters.Count == source.Parameters.Count);
        }
        var generic = source as GenericInstanceMethod;
        if (generic != null) {
            var output = new GenericInstanceMethod(MapMethod(generic.ElementMethod));
            foreach (var arg in generic.GenericArguments) output.GenericArguments.Add(MapType(arg));
            return output;
        }
        var result = new MethodReference(source.Name, MapType(source.ReturnType), MapType(source.DeclaringType)) {
            HasThis=source.HasThis, ExplicitThis=source.ExplicitThis, CallingConvention=source.CallingConvention };
        foreach (var parameter in source.Parameters) result.Parameters.Add(new ParameterDefinition(MapType(parameter.ParameterType)));
        foreach (var parameter in source.GenericParameters) result.GenericParameters.Add(new GenericParameter(parameter.Name, result));
        return result;
    }
    static FieldReference MapField(FieldReference source) {
        if (source.DeclaringType.FullName == "eDLT.FrmBaseUnit") {
            string name = source.Name == "CS$<>9__CachedAnonymousMethodDelegate19" ? "CachedPredicate" : source.Name;
            return target.GetType("FixtureForm").Fields.Single(f => f.Name == name);
        }
        throw new Exception("Unexpected field: " + source.FullName);
    }
    static void Copy(MethodDefinition source, MethodDefinition destination) {
        destination.Body = new MethodBody(destination) {
            InitLocals=source.Body.InitLocals, MaxStackSize=source.Body.MaxStackSize };
        var body = destination.Body;
        foreach (var variable in source.Body.Variables) body.Variables.Add(new VariableDefinition(MapType(variable.VariableType)));
        var instructions = new Dictionary<Instruction,Instruction>();
        foreach (var instruction in source.Body.Instructions) {
            var copy = Instruction.Create(OpCodes.Nop);
            copy.OpCode = instruction.OpCode;
            instructions.Add(instruction, copy);
            body.Instructions.Add(copy);
        }
        foreach (var instruction in source.Body.Instructions) {
            object operand = instruction.Operand;
            if (operand is Instruction) operand = instructions[(Instruction)operand];
            else if (operand is Instruction[]) operand = ((Instruction[])operand).Select(i => instructions[i]).ToArray();
            else if (operand is MethodReference) operand = MapMethod((MethodReference)operand);
            else if (operand is FieldReference) operand = MapField((FieldReference)operand);
            else if (operand is TypeReference) operand = MapType((TypeReference)operand);
            else if (operand is VariableDefinition) operand = body.Variables[((VariableDefinition)operand).Index];
            else if (operand is ParameterDefinition) operand = destination.Parameters[((ParameterDefinition)operand).Index];
            instructions[instruction].Operand = operand;
        }
        Func<Instruction,Instruction> map = instruction => instruction==null ? null : instructions[instruction];
        foreach (var handler in source.Body.ExceptionHandlers) body.ExceptionHandlers.Add(new ExceptionHandler(handler.HandlerType) {
            TryStart=map(handler.TryStart), TryEnd=map(handler.TryEnd), HandlerStart=map(handler.HandlerStart),
            HandlerEnd=map(handler.HandlerEnd), FilterStart=map(handler.FilterStart),
            CatchType=handler.CatchType==null ? null : MapType(handler.CatchType) });
        if (!source.Body.Instructions.Select(i=>i.OpCode.Code).SequenceEqual(body.Instructions.Select(i=>i.OpCode.Code)))
            throw new Exception("Opcode changes forbidden");
        Console.WriteLine("copy\t" + source.Name + "\t" + source.MetadataToken.ToUInt32().ToString("x8") + "\t" + source.RVA.ToString("x8") + "\t" + body.Instructions.Count);
    }
    static void Build(string original, string output) {
        using (var source = ModuleDefinition.ReadModule(original))
        using (target = ModuleDefinition.ReadModule(typeof(EdltTemplateTerminalProbe).Assembly.Location)) {
            var form = source.GetType("eDLT.FrmBaseUnit");
            foreach (string name in new[]{"Save", "SaveDialog", "<Save>b__18", "btnApply_Click", "btnOk_Click", "btnCancel_Click"}) {
                var method = form.Methods.Single(m=>m.Name==name);
                var destination = target.GetType("FixtureForm").Methods.Single(m=>m.Name==(name=="<Save>b__18" ? "Predicate" : name));
                Copy(method, destination);
            }
            var allowed = new[]{"mscorlib", "System", "System.Core", "Mono.Cecil"};
            foreach (var assembly in target.AssemblyReferences)
                if (!allowed.Contains(assembly.Name)) throw new Exception("Original/nonframework runtime dependency forbidden: " + assembly.FullName);
            target.Write(output);
        }
    }
    static void Case(string id, string entry, bool subscriber=true, bool global=false, bool parent=false,
                     bool serial=true, bool scene=true, bool unit=true, string throwing="") {
        FixtureForm.Events.Clear();
        FixtureForm.CachedPredicate = null;
        FixtureForm.SerialValid=serial; FixtureForm.SceneValid=scene; FixtureForm.UnitValid=unit;
        FixtureForm.ThrowAt=throwing;
        var form = new FixtureForm { GlobalProgrammingMode=global, Parent=parent ? new FixtureParent() : null };
        if (subscriber) form.saveUnitDialogRequest = close => {
            FixtureForm.Events.Add("save-request:" + close.ToString().ToLowerInvariant());
            FixtureForm.MaybeThrow("callback");
        };
        string result="void";
        try {
            if (entry=="save") result=form.Save(false).ToString().ToLowerInvariant();
            else if (entry=="apply") form.btnApply_Click(null, EventArgs.Empty);
            else if (entry=="ok") form.btnOk_Click(null, EventArgs.Empty);
            else if (entry=="cancel") form.btnCancel_Click(null, EventArgs.Empty);
            else throw new Exception("Unknown fixture entry");
        } catch (Exception error) { result=error.GetType().FullName + ":" + error.Message; }
        Console.WriteLine("case\t" + id + "\t" + result + "\t" + string.Join(";", FixtureForm.Events.ToArray()));
    }
    static void Run() {
        Case("serial-rejected", "save", serial:false);
        Case("scene-rejected", "save", scene:false);
        Case("unit-rejected", "save", unit:false);
        Case("save-dispatched", "save");
        Case("save-no-subscriber", "save", subscriber:false);
        Case("apply-dispatched", "apply");
        Case("ok-dispatched", "ok");
        Case("ok-global-no-parent", "ok", global:true);
        Case("ok-global-parent", "ok", global:true, parent:true);
        Case("cancel", "cancel");
        foreach (var stage in new[]{"serial", "scene", "unit", "callback"}) Case(stage+"-throws", "save", throwing:stage);
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies()) {
            var name=assembly.GetName().Name;
            if (!new[]{"mscorlib", "System", "System.Core", "Mono.Cecil", "TerminalProbe"}.Contains(name))
                throw new Exception("Unexpected runtime assembly: " + name);
            Console.WriteLine("runtime\t" + name + "\t" + assembly.Location);
        }
    }
    static void Inspect(string path) {
        var wanted = new Dictionary<string,string[]> {
            {"eDLT.FrmBaseUnit", new[]{"Save", "SaveDialog", "<Save>b__18", "btnApply_Click", "btnOk_Click", "btnCancel_Click", "OnFormClosed", "ClearControlsRecursively", "Dispose", "SaveUnit", "SaveUnitThreadMain", "ResetUnit", "ValidateSerialNumber", "ValidateSceneWidgetConfig", "btnTemplates_Click"}},
            {"eDLT.Controls.TemplatesDialog", new[]{"BtnLoadClick", "Dispose", "InitializeComponent"}},
            {"CBusLogicModel.Units.CBusBaseUnit", new[]{"SaveUnit", "BeforeSavePPData", "AfterSavePPData"}},
            {"CBusLogicModel.Units.EDLT.EDLTUnit", new[]{"BeforeSavePPData", "IsValid"}},
            {"SharpContainer.SharkUnitDialogFactory", new[]{"SaveUnit", "FrmKeyUnitSaveUnitDialogRequest", "DialogFormClosed", "FireFormClosedEvent"}},
        };
        using (var module = ModuleDefinition.ReadModule(path)) {
            foreach (var type in module.Types) {
                string[] names;
                if (!wanted.TryGetValue(type.FullName, out names)) continue;
                foreach (var method in type.Methods.Where(m=>names.Contains(m.Name) && m.HasBody)) {
                    var token=method.MetadataToken.ToUInt32().ToString("x8");
                    Console.WriteLine("method\t" + type.FullName + "::" + method.Name + "\t" + token + "\t" + method.RVA.ToString("x8"));
                    foreach (var instruction in method.Body.Instructions) {
                        var callee=instruction.Operand as MethodReference;
                        if (callee!=null) Console.WriteLine("call\t" + token + "\t" + instruction.Offset.ToString("x4") + "\t" + instruction.OpCode.Name + "\t" + callee.FullName);
                    }
                    foreach (var handler in method.Body.ExceptionHandlers)
                        Console.WriteLine("handler\t" + token + "\t" + handler.HandlerType + "\t" + handler.TryStart.Offset.ToString("x4") + "\t" + handler.TryEnd.Offset.ToString("x4") + "\t" + handler.HandlerStart.Offset.ToString("x4") + "\t" + (handler.HandlerEnd==null ? "end" : handler.HandlerEnd.Offset.ToString("x4")));
                }
            }
        }
    }
    static void Main(string[] args) {
        if (args.Length==3 && args[0]=="build") Build(args[1], args[2]);
        else if (args.Length==2 && args[0]=="inspect") Inspect(args[1]);
        else if (args.Length==1 && args[0]=="run") Run();
        else throw new Exception("Expected build ORIGINAL NEW or run");
    }
}
