param([ValidateSet('prepare','cleanup')][string]$Mode='prepare')
$ErrorActionPreference='Stop'
$root='C:\CBusCliOracle118-88d8'
$result=[ordered]@{mode=$Mode;captured_utc=(Get-Date).ToUniversalTime().ToString('o');default_route_count=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count}
$listen=20023
$upstream=24210
$existing=@(Get-NetTCPConnection -State Listen -LocalPort $listen -ErrorAction SilentlyContinue)
if($Mode -eq 'prepare') {
  if($result.default_route_count -ne 0) { throw 'Guest has an IPv4 default route' }
  if($existing.Count -ne 0) { throw 'Default C-Gate command port is already occupied' }
  $native=@(Get-NetTCPConnection -State Listen -LocalAddress '127.0.0.1' -LocalPort $upstream -ErrorAction SilentlyContinue)
  if($native.Count -ne 1) { throw 'Owned original C-Gate loopback listener missing' }
  & netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=$listen connectaddress=127.0.0.1 connectport=$upstream
  if($LASTEXITCODE -ne 0) { throw 'Could not add owned loopback port relay' }
  Start-Sleep -Milliseconds 250
  $forward=@(Get-NetTCPConnection -State Listen -LocalPort $listen -ErrorAction SilentlyContinue)
  $result.loopback_only=($forward.Count -eq 1 -and $forward[0].LocalAddress -eq '127.0.0.1')
  if(!$result.loopback_only) { throw 'Default port did not bind loopback only' }
} else {
  $all=& netsh interface portproxy show v4tov4
  if(($all -join "`n") -notmatch '127\.0\.0\.1\s+20023\s+127\.0\.0\.1\s+24210') { throw 'Owned exact loopback port relay missing' }
  & netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=$listen
  if($LASTEXITCODE -ne 0) { throw 'Could not remove owned loopback port relay' }
  $result.removed=(@(Get-NetTCPConnection -State Listen -LocalPort $listen -ErrorAction SilentlyContinue).Count -eq 0)
}
[IO.File]::WriteAllText((Join-Path $root ('csv-reldn8sp-vm-gui-port-'+$Mode+'.json')),($result|ConvertTo-Json -Depth 4),[Text.UTF8Encoding]::new($false))
