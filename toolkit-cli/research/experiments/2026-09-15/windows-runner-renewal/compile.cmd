@echo off
cd /d C:\CBusCliOracle118-88d8
C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe /nologo /platform:anycpu /r:System.Web.Extensions.dll /out:windows-generation-20260915t062650-NativeBridgeRecovery.exe windows-generation-20260915t062650-NativeBridgeRecovery.cs >windows-generation-20260915t062650-NativeBridgeRecovery.compile.stdout.txt 2>windows-generation-20260915t062650-NativeBridgeRecovery.compile.stderr.txt
>windows-generation-20260915t062650-NativeBridgeRecovery.compile.exit.txt echo %errorlevel%
C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe /nologo /platform:anycpu /r:System.Web.Extensions.dll /out:windows-generation-20260915t062650-NativeBridgeStop.exe windows-generation-20260915t062650-NativeBridgeStop.cs >windows-generation-20260915t062650-NativeBridgeStop.compile.stdout.txt 2>windows-generation-20260915t062650-NativeBridgeStop.compile.stderr.txt
>windows-generation-20260915t062650-NativeBridgeStop.compile.exit.txt echo %errorlevel%
