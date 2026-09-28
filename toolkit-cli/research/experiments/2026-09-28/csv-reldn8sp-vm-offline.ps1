$ErrorActionPreference='Stop'
$root='C:\CBusCliOracle118-88d8'
$receipt=Join-Path $root 'csv-reldn8sp-vm-offline.json'
$routes=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue)
if($routes.Count -ne 1) { throw 'Expected exactly one disposable VM IPv4 default route' }
$route=$routes[0]
$record=[ordered]@{
  captured_utc=(Get-Date).ToUniversalTime().ToString('o')
  default_routes_before=$routes.Count
  interface_index=$route.InterfaceIndex
  next_hop=$route.NextHop
  route_metric=$route.RouteMetric
  policy_store=[string]$route.PolicyStore
  default_routes_after=$null
}
$route|Remove-NetRoute -Confirm:$false
$record.default_routes_after=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count
[IO.File]::WriteAllText($receipt,($record|ConvertTo-Json -Depth 4),[Text.UTF8Encoding]::new($false))
if($record.default_routes_after -ne 0) { throw 'Disposable VM still has an IPv4 default route' }
