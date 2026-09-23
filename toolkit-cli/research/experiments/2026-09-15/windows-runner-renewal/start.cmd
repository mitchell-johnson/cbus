@echo off
cd /d C:\CBusCliOracle118-88d8
windows-generation-20260915t062650-NativeBridgeRecovery.exe --start >windows-generation-20260915t062650-start.stdout.txt 2>windows-generation-20260915t062650-start.stderr.txt
>windows-generation-20260915t062650-start.exit.txt echo %errorlevel%
