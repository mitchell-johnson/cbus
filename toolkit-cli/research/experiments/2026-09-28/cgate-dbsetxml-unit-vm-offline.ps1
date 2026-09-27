$ErrorActionPreference='Stop'
$root='C:\CBusCliOracle118-88d8'
$before=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count
Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
  Remove-NetRoute -Confirm:$false
$after=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count
if($after -ne 0) { throw 'Disposable VM still has an IPv4 default route' }
$result=[ordered]@{captured_utc=(Get-Date).ToUniversalTime().ToString('o');default_routes_before=$before;default_routes_after=$after}
[IO.File]::WriteAllText((Join-Path $root 'dbsetxml-unit-vm-offline.json'),($result|ConvertTo-Json -Depth 3),[Text.UTF8Encoding]::new($false))
