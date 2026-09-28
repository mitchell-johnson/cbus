// Launch one hash-pinned, owned CMD in the active desktop user's primary token.
// This helper is run by the disposable UTM guest agent as LocalSystem. It uses
// the already-logged-in console token; it never receives or saves a password.
using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Runtime.InteropServices;

class WindowsInteractiveOwnedProcessLauncher {
    const string Root = @"C:\CBusCliOracle118-88d8";
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct StartupInfo {
        public int cb;
        public string reserved, desktop, title;
        public uint x, y, xSize, ySize, xCount, yCount, fill, flags;
        public short show, reserved2;
        public IntPtr reservedPtr, input, output, error;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct ProcessInfo {
        public IntPtr process, thread;
        public uint pid, tid;
    }
    [DllImport("kernel32.dll")] static extern uint WTSGetActiveConsoleSessionId();
    [DllImport("wtsapi32.dll", SetLastError = true)]
    static extern bool WTSQueryUserToken(uint session, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool DuplicateTokenEx(IntPtr token, uint access, IntPtr attributes,
                                        int level, int type, out IntPtr duplicate);
    [DllImport("userenv.dll", SetLastError = true)]
    static extern bool CreateEnvironmentBlock(out IntPtr environment, IntPtr token, bool inherit);
    [DllImport("userenv.dll")] static extern bool DestroyEnvironmentBlock(IntPtr environment);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CreateProcessAsUserW(IntPtr token, string application,
        StringBuilder command, IntPtr processAttributes, IntPtr threadAttributes,
        bool inheritHandles, uint flags, IntPtr environment, string directory,
        ref StartupInfo startup, out ProcessInfo process);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr handle, uint timeout);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetExitCodeProcess(IntPtr process, out uint code);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);

    static string Hash(byte[] bytes) {
        using (SHA256 sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
    }
    static void Require(bool valid, string message) {
        if (!valid) throw new InvalidOperationException(message + "; Win32=" + Marshal.GetLastWin32Error());
    }
    static int Run(string[] args) {
        if (args.Length != 2 || !Regex.IsMatch(args[0], @"^p902i-[a-f0-9]{10}$") ||
            !Regex.IsMatch(args[1], @"^[a-f0-9]{64}$"))
            throw new ArgumentException("Expected owned run ID and lowercase SHA-256");
        string path = Path.Combine(Root, args[0] + ".cmd");
        string admission = Path.Combine(Root, args[0] + ".launch-admitted");
        string result = Path.Combine(Root, args[0] + ".launch.json");
        if (File.Exists(admission) || File.Exists(result))
            throw new InvalidOperationException("This owned launch was already attempted");
        Require(WindowsIdentity.GetCurrent().User.Value == "S-1-5-18",
                "Launcher must run under the guest agent's LocalSystem identity");
        Require(File.Exists(path) && Hash(File.ReadAllBytes(path)) == args[1],
                "Owned command differs from pinned bytes");
        uint session = WTSGetActiveConsoleSessionId();
        Require(session > 0 && session != UInt32.MaxValue, "No active interactive console");
        IntPtr original = IntPtr.Zero, token = IntPtr.Zero, environment = IntPtr.Zero;
        ProcessInfo child = new ProcessInfo();
        try {
            Require(WTSQueryUserToken(session, out original), "Active console token unavailable");
            Require(DuplicateTokenEx(original, 0xF01FF, IntPtr.Zero, 2, 1, out token),
                    "Primary token duplication failed");
            string sid;
            using (WindowsIdentity identity = new WindowsIdentity(token)) sid = identity.User.Value;
            Require(sid != "S-1-5-18", "Active console cannot be LocalSystem");
            Require(CreateEnvironmentBlock(out environment, token, false),
                    "User environment unavailable");
            using (FileStream marker = new FileStream(admission, FileMode.CreateNew,
                                                      FileAccess.Write, FileShare.Read)) {
                byte[] bytes = Encoding.UTF8.GetBytes(Hash(File.ReadAllBytes(path)));
                marker.Write(bytes, 0, bytes.Length);
                marker.Flush(true);
            }
            string systemCmd = Path.Combine(Environment.SystemDirectory, "cmd.exe");
            StartupInfo startup = new StartupInfo();
            startup.cb = Marshal.SizeOf(typeof(StartupInfo));
            startup.desktop = @"winsta0\default";
            StringBuilder command = new StringBuilder(systemCmd + " /d /c " + path);
            Require(CreateProcessAsUserW(token, systemCmd, command, IntPtr.Zero, IntPtr.Zero,
                                         false, 0x410, environment, Root, ref startup, out child),
                    "Interactive process launch failed");
            uint wait = WaitForSingleObject(child.process, 120000);
            Require(wait == 0, "Interactive process did not finish within 120 seconds");
            uint exitCode;
            Require(GetExitCodeProcess(child.process, out exitCode), "Exit code unavailable");
            Require(Hash(File.ReadAllBytes(path)) == args[1], "Owned command changed during run");
            string report = "{\"format\":\"cbus-p902-interactive-launch-v1\"," +
                            "\"active_session\":" + session + "," +
                            "\"primary_token_sid_sha256\":\"" +
                            Hash(Encoding.UTF8.GetBytes(sid)) + "\"," +
                            "\"process_id\":" + child.pid + "," +
                            "\"child_exit_code\":" + exitCode + "," +
                            "\"command_sha256\":\"" + args[1] + "\"}";
            File.WriteAllText(result, report + "\n", Encoding.UTF8);
            return exitCode == 0 ? 0 : 1;
        } finally {
            if (child.thread != IntPtr.Zero) CloseHandle(child.thread);
            if (child.process != IntPtr.Zero) CloseHandle(child.process);
            if (environment != IntPtr.Zero) DestroyEnvironmentBlock(environment);
            if (token != IntPtr.Zero) CloseHandle(token);
            if (original != IntPtr.Zero) CloseHandle(original);
        }
    }
    static int Main(string[] args) {
        try { return Run(args); }
        catch (Exception error) {
            Console.Error.WriteLine(error.GetType().Name + ": " + error.Message);
            return 1;
        }
    }
}
