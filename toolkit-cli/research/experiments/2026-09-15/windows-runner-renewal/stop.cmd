@echo off
cd /d C:\CBusCliOracle118-88d8
windows-generation-20260915t062650-NativeBridgeStop.exe --stop >windows-generation-20260915t062650-stop.stdout.txt 2>windows-generation-20260915t062650-stop.stderr.txt
>windows-generation-20260915t062650-stop.exit.txt echo %errorlevel%
