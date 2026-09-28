param([ValidateSet('prepare','cleanup')][string]$Mode='prepare')
$ErrorActionPreference='Stop'
$root='C:\CBusCliOracle118-88d8'
$work=Join-Path $root 'csv-reldn8sp-owned-20260928'
$vendor='C:\Clipsal\C-Gate3-Toolkit118'
$cgateHome='C:\ProgramData\Schneider Electric\C-Gate 3'
$cgateHomeBackup='C:\ProgramData\Schneider Electric\C-Gate 3.csv-reldn8sp-backup-20260928'
$jar=Join-Path $vendor 'cgate.jar'
$java=Join-Path $vendor 'openjdk_jre_11.0.24_8_x64\bin\java.exe'
$expectedJar='3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630'
$prepareReceipt=Join-Path $root 'csv-reldn8sp-vm-service.json'
$cleanupReceipt=Join-Path $root 'csv-reldn8sp-vm-service-cleanup.json'
$commandPort=24210
$eventPort=24211
$secureBase=24200

function Save-Json($path,$value) {
  [IO.File]::WriteAllText($path,($value|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
}
function Restore-Home {
  if(Test-Path -LiteralPath $cgateHomeBackup) {
    if(Test-Path -LiteralPath $cgateHome) {
      if(!((Get-Item -LiteralPath $cgateHome -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'C-Gate home is no longer the owned junction' }
      & cmd.exe /d /c ('rmdir "' + $cgateHome + '"')
      if($LASTEXITCODE -ne 0) { throw 'Could not remove owned C-Gate home junction' }
    }
    Move-Item -LiteralPath $cgateHomeBackup -Destination $cgateHome
  }
}

if($Mode -eq 'cleanup') {
  $result=[ordered]@{captured_utc=(Get-Date).ToUniversalTime().ToString('o');process_exit_confirmed=$false;work_removed=$false;default_route_count=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count}
  if(Test-Path -LiteralPath $prepareReceipt) {
    $prepared=Get-Content -Raw -LiteralPath $prepareReceipt|ConvertFrom-Json
    if($prepared.pid) {
      $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($prepared.pid)" -ErrorAction SilentlyContinue
      if($process) {
        if($process.ExecutablePath -ne $java) { throw 'Owned C-Gate PID points at an unexpected executable' }
        Stop-Process -Id $prepared.pid -Force
        Start-Sleep -Milliseconds 200
      }
      $result.process_exit_confirmed=($null -eq (Get-Process -Id $prepared.pid -ErrorAction SilentlyContinue))
    }
  }
  # Remove junctions as links before deleting the work tree. Never recurse
  # through a vendor directory target, even in a disposable VM.
  foreach($dir in @('lib','unitspec','help','transform','dali_catalogue')) {
    $link=Join-Path $work $dir
    if(Test-Path -LiteralPath $link) {
      & cmd.exe /d /c "rmdir $link"
      if($LASTEXITCODE -ne 0) { throw "Could not remove owned junction $dir" }
    }
  }
  Restore-Home
  if(Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
  $result.work_removed=!(Test-Path -LiteralPath $work)
  $result.original_home_restored=(Test-Path -LiteralPath $cgateHome) -and !(Test-Path -LiteralPath $cgateHomeBackup)
  Save-Json $cleanupReceipt $result
  exit 0
}

$result=[ordered]@{captured_utc=(Get-Date).ToUniversalTime().ToString('o');mode='owned-loopback-original-cgate';project_adopted=$false;physical_network_opened=$false;pid=$null;work=$work;listeners=@();error=$null}
try {
  if(@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count -ne 0) { throw 'Guest still has an IPv4 default route' }
  if((Get-FileHash -Algorithm SHA256 -LiteralPath $jar).Hash.ToLowerInvariant() -ne $expectedJar) { throw 'Original C-Gate JAR hash changed' }
  if(!(Test-Path -LiteralPath $java)) { throw 'Pinned Java 11 runtime missing' }
  if(Test-Path -LiteralPath $work) { throw 'Owned temporary directory already exists; inspect before starting again' }
  if(!(Test-Path -LiteralPath $cgateHome) -or (Test-Path -LiteralPath $cgateHomeBackup)) { throw 'Original C-Gate home is absent or a prior backup exists' }
  if(@(Get-NetTCPConnection -State Listen -LocalPort 20023 -ErrorAction SilentlyContinue).Count -ne 0) { throw 'Existing C-Gate command listener is active' }
  $ports=@($secureBase,($secureBase+1),($secureBase+2),($secureBase+3),$commandPort,$eventPort)
  if(@(Get-NetTCPConnection -State Listen -LocalPort $ports -ErrorAction SilentlyContinue).Count -ne 0) { throw 'Owned listener port is in use' }
  foreach($dir in @('config','tag','logs','key','tmp','scene','project')) { New-Item -ItemType Directory -Path (Join-Path $work $dir) -Force|Out-Null }
  foreach($dir in @('lib','unitspec','help','transform','dali_catalogue')) { New-Item -ItemType Junction -Path (Join-Path $work $dir) -Target (Join-Path $vendor $dir)|Out-Null }
  Copy-Item -LiteralPath (Join-Path $vendor 'key\cis.ks') -Destination (Join-Path $work 'key\cis.ks')
  $config=@(
    'command-local-address=127.0.0.1','command-port=24210',
    'event-mode=server','event-port=24211',
    'secure.bind-address=127.0.0.1','secure.port-base=24200',
    'accept-connections-from=127.0.0.1','console.enable-commands=no',
    'project.start=','project.default=','auto-reopen=no','network.source=db',
    'tag-autosave=no','clock.master=no','use-scenes=no',
    'use-load-change-port=no','use-config-change-port=no',
    'instance.lock-file=owned-native.lock','use-event-file=yes',
    'event-filename=logs/event.log'
  )
  [IO.File]::WriteAllText((Join-Path $work 'config\C-GateConfig.txt'),(($config -join "`r`n")+"`r`n"),[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $work 'config\access.txt'),"interface 127.0.0.1 Program`r`n",[Text.UTF8Encoding]::new($false))
  # This disposable guest's installed C-Gate reads ProgramData rather than
  # its process working directory. Redirect the entire home for this one run.
  Rename-Item -LiteralPath $cgateHome -NewName (Split-Path -Leaf $cgateHomeBackup)
  New-Item -ItemType Junction -Path $cgateHome -Target $work|Out-Null
  $arguments=@('-Djava.net.preferIPv4Stack=true',('-Djava.io.tmpdir='+ (Join-Path $work 'tmp')),'-Xms64M','-Xmx512M','-jar',$jar)
  $process=Start-Process -FilePath $java -ArgumentList $arguments -WorkingDirectory $work -RedirectStandardOutput (Join-Path $work 'logs\stdout.log') -RedirectStandardError (Join-Path $work 'logs\stderr.log') -PassThru
  $result.pid=$process.Id
  $result.jar_sha256=$expectedJar
  $result.java_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $java).Hash.ToLowerInvariant()
  $deadline=(Get-Date).AddSeconds(40)
  do {
    if($process.HasExited) { throw "Owned C-Gate exited during startup with code $($process.ExitCode)" }
    $listeners=@(Get-NetTCPConnection -State Listen -OwningProcess $process.Id -ErrorAction SilentlyContinue)
    $actual=@($listeners|ForEach-Object { "$($_.LocalAddress):$($_.LocalPort)" }|Sort-Object)
    $result.listeners=$actual
    $expected=@($ports|ForEach-Object { "127.0.0.1:$_" }|Sort-Object)
    if($actual.Count -eq 6 -and (($actual -join ',') -eq ($expected -join ','))) { break }
    if($listeners|Where-Object {$_.LocalAddress -ne '127.0.0.1'}) { throw 'Owned C-Gate opened a non-loopback listener' }
    Start-Sleep -Milliseconds 250
  } while((Get-Date) -lt $deadline)
  if($actual.Count -ne 6 -or ($actual -join ',') -ne ($expected -join ',')) { throw "Owned listener set incomplete: $($actual -join ',')" }
  $result.listeners=$actual
  $result.listener_ownership_verified=$true
  $result.java_parent_pid=(Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)").ParentProcessId
} catch {
  $result.error=$_.Exception.Message
  if($result.pid) { Stop-Process -Id $result.pid -Force -ErrorAction SilentlyContinue }
  try { Restore-Home } catch { $result.restore_error=$_.Exception.Message }
}
Save-Json $prepareReceipt $result
if($result.error) { exit 1 }
