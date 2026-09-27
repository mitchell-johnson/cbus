$ErrorActionPreference='Stop'
$compiler='C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe'
if ((Get-FileHash $compiler -Algorithm SHA256).Hash.ToLowerInvariant() -ne '012e8cd8adff0c439a90ffd22c0e33efeb6fbc8cf660d52b4858d310649382fa') {throw 'compiler mismatch'}
& $compiler /nologo /target:exe /platform:x86 /out:C:\Windows\Temp\CbusLazyRegistryProbe.exe /r:System.Web.Extensions.dll C:\Windows\Temp\CbusLazyRegistryProbe.cs
if ($LASTEXITCODE -ne 0) {throw 'compile failed'}
$p=Start-Process C:\Windows\Temp\CbusLazyRegistryProbe.exe -PassThru
if (-not $p.WaitForExit(30000)) {Stop-Process -Id $p.Id -Force; throw 'probe deadline exceeded'}
if ($p.ExitCode -ne 0) {throw 'probe failed'}
