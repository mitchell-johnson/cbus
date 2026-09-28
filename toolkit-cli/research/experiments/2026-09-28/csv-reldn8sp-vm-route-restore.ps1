$ErrorActionPreference='Stop'
$root='C:\CBusCliOracle118-88d8'
$offline=Get-Content -Raw -LiteralPath (Join-Path $root 'csv-reldn8sp-vm-offline.json')|ConvertFrom-Json
$service=Get-Content -Raw -LiteralPath (Join-Path $root 'csv-reldn8sp-vm-service-cleanup.json')|ConvertFrom-Json
$port=Get-Content -Raw -LiteralPath (Join-Path $root 'csv-reldn8sp-vm-gui-port-cleanup.json')|ConvertFrom-Json
if(!$service.process_exit_confirmed -or !$service.work_removed -or !$service.original_home_restored -or !$port.removed) {
  throw 'Owned original service or loopback relay cleanup is incomplete'
}
if($offline.default_routes_before -ne 1 -or $offline.default_routes_after -ne 0 -or
   $offline.interface_index -le 0 -or !$offline.next_hop) {
  throw 'Offline route witness is incomplete'
}
$before=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue)
if($before.Count -eq 0) {
  New-NetRoute -DestinationPrefix '0.0.0.0/0' -InterfaceIndex $offline.interface_index -NextHop $offline.next_hop -RouteMetric $offline.route_metric|Out-Null
  $method='recreated'
} elseif($before.Count -eq 1 -and $before[0].InterfaceIndex -eq $offline.interface_index -and
         $before[0].NextHop -eq $offline.next_hop -and $before[0].RouteMetric -eq $offline.route_metric) {
  $method='already-restored-by-guest'
} else {
  throw 'A different default route appeared before restoration'
}
$routes=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue)
$verified=($routes.Count -eq 1 -and $routes[0].InterfaceIndex -eq $offline.interface_index -and
           $routes[0].NextHop -eq $offline.next_hop -and $routes[0].RouteMetric -eq $offline.route_metric)
$result=[ordered]@{
  captured_utc=(Get-Date).ToUniversalTime().ToString('o')
  original_default_route_count=$offline.default_routes_before
  restored_default_route_count=$routes.Count
  restore_method=$method
  original_route_recreated=$verified
  original_cgate_home_restored=$service.original_home_restored
  original_cgate_process_stopped=$service.process_exit_confirmed
  temporary_work_removed=$service.work_removed
  loopback_relay_removed=$port.removed
}
[IO.File]::WriteAllText((Join-Path $root 'csv-reldn8sp-vm-route-restore.json'),($result|ConvertTo-Json -Depth 4),[Text.UTF8Encoding]::new($false))
if(!$verified) { throw 'Default route restoration verification failed' }
