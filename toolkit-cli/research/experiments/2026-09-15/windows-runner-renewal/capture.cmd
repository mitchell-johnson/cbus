@echo off
cd /d C:\CBusCliOracle118-88d8
windows-generation-20260915t062650-NativeBridgeStop.exe --capture >windows-generation-20260915t062650-capture.stdout.txt 2>windows-generation-20260915t062650-capture.stderr.txt
>windows-generation-20260915t062650-capture.exit.txt echo %errorlevel%
