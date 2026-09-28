$ErrorActionPreference='Stop'
$root='C:\CBusCliOracle118-88d8'
$service=Get-Content -Raw -LiteralPath (Join-Path $root 'csv-reldn8sp-vm-service.json')|ConvertFrom-Json
$fixture=Join-Path $root 'csv-reldn8sp-synthetic.xml'
$output=Join-Path $root 'csv-reldn8sp-vm-capture-v2-raw.json'
if($service.error -or !$service.listener_ownership_verified -or
   $service.jar_sha256 -ne '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630') {
  throw 'Pinned owned C-Gate service is absent or invalid'
}
if(@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count -ne 0) {
  throw 'Guest has an IPv4 default route'
}
$java='C:\Clipsal\C-Gate3-Toolkit118\openjdk_jre_11.0.24_8_x64\bin\java.exe'
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$($service.pid)" -ErrorAction SilentlyContinue
if(!$process -or $process.ExecutablePath -ne $java) { throw 'Owned original service process changed' }
$listeners=@(Get-NetTCPConnection -State Listen -OwningProcess $service.pid -ErrorAction SilentlyContinue|
  ForEach-Object { "$($_.LocalAddress):$($_.LocalPort)" }|Sort-Object)
if(($listeners -join ',') -ne ((@($service.listeners)|Sort-Object) -join ',')) { throw 'Owned listeners changed' }
if((Get-FileHash -Algorithm SHA256 -LiteralPath $fixture).Hash.ToLowerInvariant() -ne
   '771e0a3457848c853d2245105287da84132475f8645e2cf75be6b1184c495275') {
  throw 'Synthetic fixture hash differs'
}

$client=[Net.Sockets.TcpClient]::new()
$client.ReceiveTimeout=10000;$client.SendTimeout=10000
$client.Connect('127.0.0.1',24210)
$stream=$client.GetStream()
function Read-WireLine {
  $bytes=[Collections.Generic.List[byte]]::new()
  for($i=0;$i -lt 1048576;$i++) {
    $value=$stream.ReadByte()
    if($value -lt 0) { throw 'C-Gate closed before line feed' }
    $bytes.Add([byte]$value)
    if($value -eq 10) { return [Text.Encoding]::UTF8.GetString($bytes.ToArray()) }
  }
  throw 'C-Gate response line exceeded one MiB'
}
function Exchange([string]$tag,[string]$command,[string]$document) {
  $request='['+$tag+'] '+$command+"`r`n"
  if($command.StartsWith('DBSETXML ')) { $request+=$document+"`r`nEND"+$tag+"`r`n" }
  $bytes=[Text.Encoding]::UTF8.GetBytes($request)
  $stream.Write($bytes,0,$bytes.Length)
  $lines=@()
  for($i=0;$i -lt 256;$i++) {
    $line=Read-WireLine
    $lines+=,$line
    if($line -match ('^\['+[regex]::Escape($tag)+'\] [0-9]{3} ')) {
      return [ordered]@{tag=$tag;command=$command;request=$request;response_lines=$lines}
    }
  }
  throw "C-Gate response for $tag did not terminate within 256 lines"
}
function Expect-Status($row,[string]$status) {
  if(!$row.response_lines[-1].StartsWith('['+$row.tag+'] '+$status+' ')) {
    throw "Unexpected C-Gate result for $($row.tag): $($row.response_lines[-1])"
  }
}
function Xml-FromReadback($row) {
  $prefix='['+$row.tag+'] 347-'
  $fragments=@($row.response_lines|Where-Object {$_.StartsWith($prefix)}|
    ForEach-Object {$_.Substring($prefix.Length)})
  if($fragments.Count -lt 1) { throw 'Readback omitted XML data rows' }
  return ($fragments -join '')
}

$rows=@()
$result=[ordered]@{
  format='cbus-csv-reldn8sp-original-cgate-raw-v1'
  captured_utc=(Get-Date).ToUniversalTime().ToString('o')
  fixture_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $fixture).Hash.ToLowerInvariant()
  capture_script_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $PSCommandPath).Hash.ToLowerInvariant()
  jar_sha256=$service.jar_sha256
  java_sha256=$service.java_sha256
  service_pid=$service.pid
  service_listeners=$listeners
  default_route_count=0
  complete=$false
  cases=$rows
}
try {
  $result.greeting=Read-WireLine
  $row=Exchange '100' 'PROJECT NEW XCSVSP2' $null;$rows+=,$row;Expect-Status $row '200'
  $row=Exchange '101' 'PROJECT USE XCSVSP2' $null;$rows+=,$row;Expect-Status $row '200'
  $row=Exchange '102' 'DBCREATENET 254 Local Cni 127.0.0.1:1' $null;$rows+=,$row;Expect-Status $row '301'
  $row=Exchange '103' 'DBGETXML //XCSVSP2/254' $null;$rows+=,$row;Expect-Status $row '344'
  [xml]$baseline=Xml-FromReadback $row
  $networkOid=[string]$baseline.Network.OID
  $interfaceOid=[string]$baseline.Network.Interface.OID
  if(!$networkOid -or !$interfaceOid -or [string]$baseline.Network.Address -ne '254') {
    throw 'Fresh temporary native Network identity is incomplete'
  }
  $result.network_oid=$networkOid
  $result.interface_oid=$interfaceOid
  [xml]$source=Get-Content -Raw -LiteralPath $fixture
  $application=$source.Installation.Project.Network.Application.OuterXml
  $unit=$source.Installation.Project.Network.Unit.OuterXml
  $network="<Network><OID>$networkOid</OID><TagName>Local</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><OID>$interfaceOid</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>$application$unit</Network>"
  $row=Exchange '104' 'DBSETXML //XCSVSP2/254 << END104' $network;$rows+=,$row
  $result.dbsetxml_status=($row.response_lines[-1] -replace '^\[104\] ','').Trim()
  if(!$row.response_lines[-1].StartsWith('[104] 301 ')) { throw 'Native complete Network load rejected the synthetic fixture' }
  foreach($pair in @(
      @('105','DBGETXML //XCSVSP2/254/p/9'),
      @('106','DBGETXML //XCSVSP2'),
      @('107','pp quickget //XCSVSP2/254/p/9 GroupAddress'),
      @('108','pp quickget //XCSVSP2/254/p/9 AreaGroupAddress'),
      @('109','NET LIST'),
      @('110','PROJECT SAVE XCSVSP2'),
      @('111','PROJECT CLOSE XCSVSP2'),
      @('112','PROJECT LOAD XCSVSP2'),
      @('113','PROJECT USE XCSVSP2'),
      @('114','DBGETXML //XCSVSP2/254/p/9'),
      @('115','DBGETXML //XCSVSP2'),
      @('116','pp quickget //XCSVSP2/254/p/9 GroupAddress'),
      @('117','NET LIST')
    )) {
    $row=Exchange $pair[0] $pair[1] $null;$rows+=,$row
  }
  $result.complete=$true
} catch {
  $result.error_type=$_.Exception.GetType().Name
  $result.error=$_.Exception.Message
} finally {
  $result.cases=$rows
  $result.default_route_count_after=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count
  $client.Close()
  [IO.File]::WriteAllText($output,($result|ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
}
if(!$result.complete) { exit 1 }
