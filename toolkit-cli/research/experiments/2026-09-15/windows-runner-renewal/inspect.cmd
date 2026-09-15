@echo off
cd /d C:\CBusCliOracle118-88d8
windows-generation-20260915t062650-NativeBridgeRecovery.exe --inspect >windows-generation-20260915t062650-inspect.stdout.txt 2>windows-generation-20260915t062650-inspect.stderr.txt
>windows-generation-20260915t062650-inspect.exit.txt echo %errorlevel%
