// Synthetic inputs only. Calls unchanged original PPHelper static methods;
// no model/control construction, service, project, or physical endpoint.
using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Xml;
using CBusLogicModel;

class EdltTemplateOriginalProbe {
    static string Hash(byte[] bytes) {
        using (var h = SHA256.Create())
            return BitConverter.ToString(h.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
    }
    static string Decode(string value) { return Encoding.Unicode.GetString(Convert.FromBase64String(value)); }
    static string Encode(string value) { return Convert.ToBase64String(Encoding.Unicode.GetBytes(value)); }
    static void Main(string[] args) {
        CultureInfo.CurrentCulture = CultureInfo.InvariantCulture;
        foreach (var type in new[] {typeof(PPHelper), typeof(object), typeof(EdltTemplateOriginalProbe)})
            Console.Error.WriteLine("assembly\t" + type.FullName + "\t" + type.Assembly.Location + "\t" + Hash(File.ReadAllBytes(type.Assembly.Location)) + "\t" + IntPtr.Size * 8);
        foreach (var name in new[] {"CalcTemplateCrc", "CalculateCrcForTemplate"}) {
            var method = typeof(PPHelper).GetMethod(name);
            Console.Error.WriteLine("method\t" + name + "\t0x" + method.MetadataToken.ToString("x8") + "\t" + Hash(method.GetMethodBody().GetILAsByteArray()));
        }
        int count = 0;
        foreach (string line in File.ReadLines(args[0])) {
            if (++count > 256) throw new Exception("Input bound");
            var fields = line.Split('\t');
            string id = fields[1];
            try {
                if (fields[0] == "crc") {
                    var values = fields.Skip(2).Select(Decode).ToArray();
                    if (values.Sum(s => s.Length) > 65537) throw new Exception("String bound");
                    Console.WriteLine(id + "\tok\t" + PPHelper.CalcTemplateCrc(values));
                } else if (fields[0] == "raw") {
                    var bytes = Convert.FromBase64String(fields[2]);
                    Console.WriteLine(id + "\tok\t" + PPHelper.CalculateCrcForTemplate(bytes, int.Parse(fields[3]), int.Parse(fields[4])));
                } else if (fields[0] == "xml") {
                    var document = new XmlDocument();
                    string xmlPath = Path.Combine(Path.GetDirectoryName(args[0]), "xml-input-" + id + ".xml");
                    File.WriteAllText(xmlPath, Decode(fields[2]), new UTF8Encoding(false));
                    document.Load(xmlPath);
                    var crcValues = new System.Collections.Generic.List<string>();
                    bool afterCrc = false;
                    foreach (XmlNode node in document.DocumentElement.ChildNodes) {
                        Console.WriteLine(id + "\tnode\t" + node.NodeType + "\t" + Encode(node.Name) + "\t" + Encode(node.InnerXml));
                        if (afterCrc) crcValues.Add(node.InnerXml);
                        else if (node.Name == "CRC") afterCrc = true;
                    }
                    if (afterCrc) Console.WriteLine(id + "\tchecksum\t" + PPHelper.CalcTemplateCrc(crcValues.ToArray()));
                } else if (fields[0] == "application") {
                    string value = Decode(fields[2]);
                    if (value != "") value = string.Join(" ", value.Split(' ').Select(s => string.Format("0x{0:x}", Convert.ToInt32(s, 10))).ToArray());
                    Console.WriteLine(id + "\tok\t" + Encode(value));
                } else throw new Exception("Unknown input kind");
            } catch (Exception error) {
                Console.WriteLine(id + "\terror\t" + error.GetType().FullName);
            }
        }
    }
}
