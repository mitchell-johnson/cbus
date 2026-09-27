// Owned, offline reflection probe for the SESU 3.0.7 applicability method.
// Run in a disposable Windows guest with zero IPv4/IPv6 default routes. The
// method target is uninitialized; this never constructs the updater, opens
// HTTP, authenticates metadata, downloads, or installs. It directs the
// original helper's registry fields to one fresh owned HKCU Registry32 key.
using System;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.Serialization;
using System.Security.Cryptography;
using Microsoft.Win32;

class NativeSesuApplicabilityCohortProbe
{
    const string ExpectedAssemblySha256 =
        "21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c";
    const int ApplicabilityToken = 0x0600012B;
    const int RolloutToken = 0x0600012C;
    const BindingFlags Fields = BindingFlags.Instance | BindingFlags.NonPublic |
                                BindingFlags.Public;
    const BindingFlags Properties = BindingFlags.Instance | BindingFlags.NonPublic |
                                    BindingFlags.Public;

    static Module module;
    static MethodInfo applicability;
    static object target;
    static RegistryKey hive;
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

    static object EmptyInstance(Type type)
    {
        try { return Activator.CreateInstance(type, true); }
        catch (MissingMethodException) { return FormatterServices.GetUninitializedObject(type); }
    }

    static void Set(object instance, string name, object value)
    {
        Type type = instance.GetType();
        var property = type.GetProperty(name, Properties);
        object observed;
        if (property != null && property.GetSetMethod(true) != null)
        {
            property.SetValue(instance, value, null);
            observed = property.GetValue(instance, null);
        }
        else
        {
            var field = type.GetField("<" + name + ">k__BackingField", Fields) ??
                        type.GetField(name, Fields);
            Require(field != null, "Original model member missing: " + name);
            field.SetValue(instance, value);
            observed = field.GetValue(instance);
        }
        Require(Object.Equals(observed, value),
                "Original model member did not retain value: " + name);
    }

    static Type PropertyType(Type type, string name)
    {
        var property = type.GetProperty(name, Properties);
        Require(property != null, "Original model property missing: " + name);
        return property.PropertyType;
    }

    static object Package(int visibility, string variant)
    {
        Type type = module.ResolveField(0x04000030).FieldType;
        object package = EmptyInstance(type);
        DateTime now = DateTime.Now;
        DateTime start = variant == "future-start" ? now.AddDays(365) : now.AddDays(-365);
        DateTime expiry = variant == "expired" ? now.AddDays(-365) : now.AddDays(365);
        Set(package, "StartDate", start);
        Set(package, "ExpireDate", expiry);
        Set(package, "VisibilityInPercent", visibility);
        Type conditionType = PropertyType(type, "ClientConditionData");
        object condition = EmptyInstance(conditionType);
        // A nonempty expression with zero definitions is deliberately ignored
        // by this original method, as the earlier 20-case fixture observed.
        Set(condition, "Expression", "false");
        var conditionsProperty = conditionType.GetProperty("Conditions", Properties);
        Require(conditionsProperty != null, "Original Conditions property missing");
        object conditions = conditionsProperty.GetValue(condition, null);
        if (conditions == null)
        {
            Type mapType = conditionsProperty.PropertyType;
            if (mapType.IsInterface && mapType.IsGenericType)
                mapType = typeof(System.Collections.Generic.Dictionary<,>).MakeGenericType(
                    mapType.GetGenericArguments());
            conditions = EmptyInstance(mapType);
            Set(condition, "Conditions", conditions);
        }
        var count = conditions.GetType().GetProperty("Count", Properties);
        Require(count != null && (int)count.GetValue(conditions, null) == 0,
                "Original conditions are not empty");
        Set(package, "ClientConditionData", condition);
        return package;
    }

    static void Configure(int visibility, string variant)
    {
        module.ResolveField(0x04000030).SetValue(target, Package(visibility, variant));
        var uriField = module.ResolveField(0x04000033);
        uriField.SetValue(target, variant == "missing-url" ? null :
            new Uri("https://updates.example.invalid/owned.exe"));
        var mediaField = module.ResolveField(0x04000036);
        mediaField.SetValue(target, Enum.ToObject(mediaField.FieldType,
            variant == "unknown-media" ? 6 : 1));
        Require(module.ResolveField(0x04000030).GetValue(target) != null,
                "Original package field was not set");
    }

    static bool Invoke()
    {
        try { return (bool)applicability.Invoke(target, new object[0]); }
        catch (TargetInvocationException error)
        {
            throw new InvalidOperationException("Original applicability threw " +
                error.InnerException.GetType().FullName, error.InnerException);
        }
    }

    static RegistryKey FreshKey()
    {
        hive.DeleteSubKeyTree(ownedPath, false);
        return hive.CreateSubKey(ownedPath, true);
    }

    static void StoredRow(string name, int visibility, string stored,
                          string variant, bool expected)
    {
        Configure(visibility, variant);
        using (var key = FreshKey()) key.SetValue("Cohort", stored, RegistryValueKind.String);
        bool actual = Invoke();
        using (var key = hive.OpenSubKey(ownedPath, false))
            Require((string)key.GetValue("Cohort") == stored,
                "Original changed a supplied stored cohort");
        Console.WriteLine("ROW\t{0}\t{1}\t{2}\t{3}\t{4}\t{5}",
            name, variant, visibility, stored, actual, expected);
        Require(actual == expected, name + " original outcome differed");
        cases++;
    }

    static void MissingRow(string name, int visibility, string variant,
                           bool expected, bool shouldSeed)
    {
        Configure(visibility, variant);
        using (var key = FreshKey()) { /* Key exists, cohort entry is absent. */ }
        bool actual = Invoke();
        object saved;
        using (var key = hive.OpenSubKey(ownedPath, false))
            saved = key.GetValue("Cohort");
        int sampled;
        bool seeded = saved is string && Int32.TryParse((string)saved, out sampled)
            && sampled >= 0 && sampled <= 99;
        Console.WriteLine("ROW\t{0}\t{1}\t{2}\tMissing\t{3}\t{4}\t{5}",
            name, variant, visibility, actual, seeded, shouldSeed);
        Require(actual == expected && seeded == shouldSeed,
                name + " original return/rollout reach differed");
        cases++;
    }

    static void Cases()
    {
        StoredRow("pass-middle", 42, "41", "baseline", true);
        StoredRow("equal-middle", 41, "41", "baseline", false);
        StoredRow("pass-zero", 1, "0", "baseline", true);
        StoredRow("equal-zero", 0, "0", "baseline", false);
        StoredRow("pass-high", 99, "98", "baseline", true);
        StoredRow("equal-high", 99, "99", "baseline", false);
        StoredRow("date-before-start", 42, "41", "future-start", false);
        StoredRow("date-after-expiry", 42, "41", "expired", false);
        StoredRow("no-selected-uri", 42, "41", "missing-url", false);
        StoredRow("unknown-media", 42, "41", "unknown-media", false);

        MissingRow("seed-on-reached", 0, "baseline", false, true);
        MissingRow("no-seed-before-start", 42, "future-start", false, false);
        MissingRow("no-seed-after-expiry", 42, "expired", false, false);
        MissingRow("no-seed-without-uri", 42, "missing-url", false, false);
        MissingRow("no-seed-unknown-media", 42, "unknown-media", false, false);
    }

    static int Main(string[] args)
    {
        if (args.Length != 1) return 2;
        string fileHash = Hash(File.ReadAllBytes(args[0]));
        Require(fileHash == ExpectedAssemblySha256, "Unexpected SESU assembly SHA-256");
        var assembly = Assembly.LoadFrom(args[0]);
        module = assembly.ManifestModule;
        applicability = (MethodInfo)module.ResolveMethod(ApplicabilityToken);
        var helper = (MethodInfo)module.ResolveMethod(RolloutToken);
        Require(applicability.DeclaringType.FullName ==
            "SchneiderElectric.SesuBrick.DAD.MultiPlatformUpdate" &&
            applicability.ReturnType == typeof(bool) &&
            applicability.GetParameters().Length == 0 &&
            helper.DeclaringType == applicability.DeclaringType,
            "Unexpected original applicability/rollout identities");
        target = FormatterServices.GetUninitializedObject(applicability.DeclaringType);
        ownedPath = "Software\\CBusCliApplicabilityCohortProbe_" + Guid.NewGuid().ToString("N");
        var keyField = applicability.DeclaringType.GetField(
            "VisibilityRegistryKeyName", BindingFlags.Public | BindingFlags.Static);
        var entryField = applicability.DeclaringType.GetField(
            "VisibilityRegistryEntryName", BindingFlags.Public | BindingFlags.Static);
        Require(keyField != null && entryField != null, "Original registry fields missing");
        keyField.SetValue(null, ownedPath);
        entryField.SetValue(null, "Cohort");
        Require((string)keyField.GetValue(null) == ownedPath &&
            (string)entryField.GetValue(null) == "Cohort", "Registry redirect failed");
        Console.WriteLine("IDENTITY\t{0}\t0x{1:X8}\t{2}\t0x{3:X8}\t{4}",
            fileHash, ApplicabilityToken,
            Hash(applicability.GetMethodBody().GetILAsByteArray()), RolloutToken,
            Hash(helper.GetMethodBody().GetILAsByteArray()));
        try
        {
            using (hive = RegistryKey.OpenBaseKey(RegistryHive.CurrentUser, RegistryView.Registry32))
                Cases();
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
