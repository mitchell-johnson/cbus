// Owned, offline reflection harness for the exact SESU 3.0.7 rollout helper.
// Run only on a disposable Windows guest with no IPv4 default route. This
// program never calls the updater constructor, HTTP client, or installer.
// It redirects the original helper's public static registry field names to a
// fresh HKCU\Software\CBusCliRolloutProbe_* key and deletes that key on exit.
using System;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.Serialization;
using System.Security.Cryptography;
using Microsoft.Win32;

class NativeSesuRolloutProbe
{
    const string ExpectedAssemblySha256 =
        "21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c";
    const int HelperToken = 0x0600012C; // MultiPlatformUpdate RVA 0x5190.
    const BindingFlags StaticFields = BindingFlags.Public | BindingFlags.Static;

    static RegistryKey hive;
    static MethodInfo helper;
    static object target;
    static string ownedPath;
    static int cases;

    static string Hash(byte[] bytes)
    {
        using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
    }

    static void Require(bool condition, string reason)
    {
        if (!condition) throw new InvalidOperationException(reason);
    }

    static RegistryKey FreshKey()
    {
        hive.DeleteSubKeyTree(ownedPath, false);
        return hive.CreateSubKey(ownedPath, true);
    }

    static bool Invoke(int visibility)
    {
        try { return (bool)helper.Invoke(target, new object[] { visibility }); }
        catch (TargetInvocationException error)
        {
            throw new InvalidOperationException("Original helper threw " +
                error.InnerException.GetType().FullName, error.InnerException);
        }
    }

    static void Row(string name, int visibility, string stored, RegistryValueKind kind,
                    bool expected)
    {
        using (var key = FreshKey()) key.SetValue("Cohort", stored, kind);
        bool actual = Invoke(visibility);
        using (var key = hive.OpenSubKey(ownedPath, false))
            Require(Convert.ToString(key.GetValue("Cohort"), CultureInfo.InvariantCulture)
                == stored, "Original changed a stored cohort");
        Console.WriteLine("ROW\t{0}\t{1}\t{2}\t{3}\t{4}\t{5}", name, visibility,
            kind, stored, actual, expected);
        Require(actual == expected, name + " outcome differed");
        cases++;
    }

    static void NumericRow(string name, int visibility, int stored, bool expected)
    {
        using (var key = FreshKey()) key.SetValue("Cohort", stored, RegistryValueKind.DWord);
        bool actual = Invoke(visibility);
        using (var key = hive.OpenSubKey(ownedPath, false))
            Require((int)key.GetValue("Cohort") == stored, "Original changed a DWORD cohort");
        Console.WriteLine("ROW\t{0}\t{1}\tDWord\t{2}\t{3}\t{4}",
            name, visibility, stored, actual, expected);
        Require(actual == expected, name + " outcome differed");
        cases++;
    }

    static void MainCases()
    {
        hive.DeleteSubKeyTree(ownedPath, false);
        bool absent = Invoke(42);
        Console.WriteLine("ROW\tkey-absent\t42\tAbsent\t\t{0}\tFalse", absent);
        Require(!absent, "Absent key unexpectedly admitted");
        cases++;

        Row("equal-zero", 0, "0", RegistryValueKind.String, false);
        Row("above-zero", 1, "0", RegistryValueKind.String, true);
        Row("equal-middle", 41, "41", RegistryValueKind.String, false);
        Row("above-middle", 42, "41", RegistryValueKind.String, true);
        Row("equal-high", 99, "99", RegistryValueKind.String, false);
        Row("above-high-helper-only", 100, "99", RegistryValueKind.String, true);
        Row("hundred-stored-outside-cli", 99, "100", RegistryValueKind.String, false);
        Row("invalid-text", 42, "bad", RegistryValueKind.String, false);
        Row("integer-overflow", 42, "2147483648", RegistryValueKind.String, false);
        Row("plus-text-outside-cli", 42, "+41", RegistryValueKind.String, true);
        Row("space-text-outside-cli", 42, " 41 ", RegistryValueKind.String, true);
        NumericRow("dword-middle", 42, 41, true);

        using (var key = FreshKey()) { /* Key exists; Cohort entry is missing. */ }
        bool first = Invoke(0);
        int sampled = -1;
        using (var key = hive.OpenSubKey(ownedPath, false))
        {
            var saved = key.GetValue("Cohort");
            Require(saved is string && Int32.TryParse((string)saved, out sampled),
                "Original did not persist a decimal cohort string");
        }
        Require(sampled >= 0 && sampled <= 99 && !first,
            "Original sampled outside [0,99] or admitted visibility zero");
        Console.WriteLine("ROW\tmissing-entry-seeded\t0\tMissing\t{0}\t{1}\tFalse",
            sampled, first);
        cases++;

        bool equal = Invoke(sampled);
        bool above = Invoke(sampled + 1); // Direct helper, even if sampled=99.
        Console.WriteLine("ROW\tseed-equal\t{0}\tString\t{0}\t{1}\tFalse",
            sampled, equal);
        Console.WriteLine("ROW\tseed-above-helper-only\t{0}\tString\t{1}\t{2}\tTrue",
            sampled + 1, sampled, above);
        Require(!equal && above, "Seeded cohort comparison was not strict greater-than");
        cases += 2;

        // The literal stored sentinel is treated like a missing entry and
        // replaced with a newly sampled value; it is not a negative cohort.
        using (var key = FreshKey()) key.SetValue("Cohort", "-1", RegistryValueKind.String);
        bool sentinel = Invoke(0);
        int reseeded = -1;
        using (var key = hive.OpenSubKey(ownedPath, false))
        {
            var saved = key.GetValue("Cohort");
            Require(saved is string && Int32.TryParse((string)saved, out reseeded),
                "Original did not replace the sentinel with a decimal string");
        }
        Require(reseeded >= 0 && reseeded <= 99 && !sentinel,
            "Original failed to replace sentinel with a [0,99] cohort");
        Console.WriteLine("ROW\tstored-sentinel-reseeded\t0\tString\t-1\t{0}\t{1}\tFalse",
            reseeded, sentinel);
        cases++;
    }

    static int Main(string[] args)
    {
        if (args.Length != 1) return 2;
        string fileHash = Hash(File.ReadAllBytes(args[0]));
        Require(fileHash == ExpectedAssemblySha256, "Unexpected SESU assembly SHA-256");
        var assembly = Assembly.LoadFrom(args[0]);
        helper = (MethodInfo)assembly.ManifestModule.ResolveMethod(HelperToken);
        Require(helper.DeclaringType.FullName ==
            "SchneiderElectric.SesuBrick.DAD.MultiPlatformUpdate" &&
            helper.ReturnType == typeof(bool) &&
            helper.GetParameters().Length == 1 &&
            helper.GetParameters()[0].ParameterType == typeof(int),
            "Unexpected original rollout method identity");
        target = FormatterServices.GetUninitializedObject(helper.DeclaringType);
        ownedPath = "Software\\CBusCliRolloutProbe_" + Guid.NewGuid().ToString("N");
        var keyField = helper.DeclaringType.GetField("VisibilityRegistryKeyName", StaticFields);
        var entryField = helper.DeclaringType.GetField("VisibilityRegistryEntryName", StaticFields);
        Require(keyField != null && entryField != null, "Original registry fields missing");
        keyField.SetValue(null, ownedPath);
        entryField.SetValue(null, "Cohort");
        Require((string)keyField.GetValue(null) == ownedPath &&
            (string)entryField.GetValue(null) == "Cohort", "Registry redirection failed");
        Console.WriteLine("IDENTITY\t{0}\t0x{1:X8}\t{2}", fileHash,
            HelperToken, Hash(helper.GetMethodBody().GetILAsByteArray()));
        try
        {
            using (hive = RegistryKey.OpenBaseKey(RegistryHive.CurrentUser, RegistryView.Registry32))
                MainCases();
        }
        finally
        {
            using (var cleanup = RegistryKey.OpenBaseKey(RegistryHive.CurrentUser, RegistryView.Registry32))
            {
                cleanup.DeleteSubKeyTree(ownedPath, false);
                Require(cleanup.OpenSubKey(ownedPath, false) == null,
                    "Owned rollout registry key cleanup failed");
            }
        }
        Console.WriteLine("COMPLETE\t{0}\towned-key-absent", cases);
        return 0;
    }
}
