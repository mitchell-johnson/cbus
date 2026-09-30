// Calls unchanged owned PPAttribute constructors/accessors. The ordered template
// loop is a source-pinned harness proxy, not the original TemplatesDialog.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using CBusLogicModel;

class EdltTemplateAssignmentProbe {
    static string Encode(string value) { return value == null ? "N" : "S" + Convert.ToBase64String(Encoding.Unicode.GetBytes(value)); }
    static string Decode(string value) { return value == "N" ? null : Encoding.Unicode.GetString(Convert.FromBase64String(value.Substring(1))); }
    static string Hash(byte[] bytes) { using (var h = SHA256.Create()) return BitConverter.ToString(h.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant(); }
    static string Tokens(PPAttribute attribute) { return attribute.Values.Count + "\t" + string.Join("\t", attribute.Values.Select(Encode).ToArray()); }
    static void State(string phase, List<PPAttribute> attributes) {
        for (int i = 0; i < attributes.Count; i++) {
            var attribute = attributes[i];
            Console.WriteLine("state\t" + phase + "\t" + PPAttribute.bInitialiseMode + "\t" + i + "\t" + Encode(attribute.Name) + "\t" + Encode(attribute.Value) + "\t" + Encode(attribute.ValueFull) + "\t" + Encode(attribute.Value1) + "\t" + attribute.HasBeenChanged + "\t" + Tokens(attribute));
        }
    }
    static void Main(string[] args) {
        CultureInfo.CurrentCulture = CultureInfo.InvariantCulture;
        foreach (var type in new[] {typeof(PPAttribute), typeof(object), typeof(EdltTemplateAssignmentProbe)})
            Console.Error.WriteLine("assembly\t" + type.FullName + "\t" + type.Assembly.Location + "\t" + Hash(File.ReadAllBytes(type.Assembly.Location)) + "\t" + IntPtr.Size * 8);
        var methods = typeof(PPAttribute).GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static)
            .Where(m => m.DeclaringType == typeof(PPAttribute)).Cast<MethodBase>()
            .Concat(typeof(PPAttribute).GetConstructors(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static));
        foreach (var method in methods.OrderBy(m => m.MetadataToken))
            Console.Error.WriteLine("method\t" + method.Name + "\t0x" + method.MetadataToken.ToString("x8") + "\t" + Hash(method.GetMethodBody().GetILAsByteArray()));
        var input = File.ReadAllLines(args[0]).Select(line => line.Split('\t')).ToArray();
        var config = input[0];
        if (config[0] != "case" || input.Length > 64) throw new Exception("Input bound");
        var attributes = new List<PPAttribute>();
        foreach (var fields in input.Where(f => f[0] == "attribute")) {
            var attribute = new PPAttribute();
            attribute.Name = Decode(fields[1]);
            attribute.HasBeenChanged = bool.Parse(fields[2]);
            foreach (var token in fields.Skip(3)) attribute.Values.Add(Decode(token));
            attributes.Add(attribute);
        }
        int listThrowIndex = int.Parse(config[3]);
        bool propertyThrow = bool.Parse(config[4]);
        int eventNumber = 0;
        for (int i = 0; i < attributes.Count; i++) {
            int attributeIndex = i;
            var attribute = attributes[i];
            attribute.Values.ListChanged += (sender, change) => {
                Console.WriteLine("event\tlist\t" + attributeIndex + "\t" + change.ListChangedType + "\t" + change.NewIndex + "\t" + change.OldIndex + "\t" + PPAttribute.bInitialiseMode + "\t" + attribute.HasBeenChanged + "\t" + Tokens(attribute));
                eventNumber++;
                if (listThrowIndex == eventNumber) throw new InvalidOperationException("synthetic list listener failure");
            };
            attribute.PropertyChanged += (sender, change) => {
                Console.WriteLine("event\tproperty\t" + attributeIndex + "\t" + Encode(change.PropertyName) + "\t" + PPAttribute.bInitialiseMode + "\t" + attribute.HasBeenChanged + "\t" + Tokens(attribute));
                if (propertyThrow) throw new InvalidOperationException("synthetic property listener failure");
            };
        }
        // Each process constructs an independent attribute graph. A case may
        // explicitly model a stale flag; no prior fixture's state is reused.
        PPAttribute.bInitialiseMode = bool.Parse(config[2]);
        State("baseline", attributes);
        string boundary = "start";
        int operation = -1;
        try {
            foreach (var fields in input.Where(f => f[0] == "operation")) {
                operation++;
                string mode = fields[1], name = Decode(fields[2]), value = Decode(fields[3]);
                int index = int.Parse(fields[4]);
                Console.WriteLine("operation\t" + operation + "\t" + mode + "\t" + Encode(name) + "\t" + Encode(value) + "\t" + index);
                boundary = "lookup";
                PPAttribute attribute;
                if (mode == "template") {
                    boundary = "application_conversion";
                    if (name == "Application" && value != "")
                        value = string.Join(" ", value.Split(' ').Select(s => string.Format("0x{0:x}", Convert.ToInt32(s, 10))).ToArray());
                    PPAttribute.bInitialiseMode = true;
                    boundary = "lookup";
                    // Source-pinned linear, case-sensitive first match; this is
                    // a lookup proxy rather than CBusBaseUnit.GetPPAttribute.
                    attribute = attributes.FirstOrDefault(a => a.Name == name);
                    if (attribute != null && !attribute.Value.Equals(value)) {
                        boundary = "Value_setter";
                        attribute.Value = value;
                        boundary = "explicit_dirty_setter";
                        attribute.HasBeenChanged = true;
                    }
                    PPAttribute.bInitialiseMode = false;
                } else {
                    attribute = attributes.First(a => a.Name == name);
                    boundary = mode;
                    if (mode == "set_value") attribute.Value = value;
                    else if (mode == "set_full") attribute.ValueFull = value;
                    else if (mode == "set_item") attribute[index] = value;
                    else if (mode == "set_int") attribute.ValueAsInt = int.Parse(value);
                    else if (mode == "set_dirty") attribute.HasBeenChanged = bool.Parse(value);
                    else if (mode == "get_int") Console.WriteLine("getter\tint\t" + attribute.ValueAsInt);
                    else if (mode == "get_bool") Console.WriteLine("getter\tbool\t" + attribute.ValueAsBool);
                    else if (mode == "get_item") Console.WriteLine("getter\tstring\t" + Encode(attribute[index]));
                    else if (mode == "get_values_int") Console.WriteLine("getter\tint\t" + attribute.ValuesAsInt);
                    else throw new Exception("Unknown mode");
                }
                boundary = "completed";
                State("after-" + operation, attributes);
            }
            Console.WriteLine("result\tok\t" + operation + "\t" + boundary + "\t" + PPAttribute.bInitialiseMode);
        } catch (Exception error) {
            Console.WriteLine("result\terror\t" + operation + "\t" + boundary + "\t" + PPAttribute.bInitialiseMode + "\t" + error.GetType().FullName);
            State("failed-" + operation, attributes);
        }
    }
}
