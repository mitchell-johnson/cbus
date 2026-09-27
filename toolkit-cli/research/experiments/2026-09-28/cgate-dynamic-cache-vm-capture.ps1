$ErrorActionPreference='Stop'
try {
$root='C:\CBusCliOracle118-88d8'
$service=Get-Content -Raw -LiteralPath (Join-Path $root 'dynamic-cache-vm-service.json')|ConvertFrom-Json
if($service.error -or !$service.listener_ownership_verified -or
   $service.jar_sha256 -ne '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630') {
  throw 'Pinned owned C-Gate service receipt is absent or invalid'
}
if(@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count -gt 2) {
  throw 'Guest has more default routes than preflight permits'
}
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$($service.pid)" -ErrorAction SilentlyContinue
if(!$process -or $process.ExecutablePath -ne 'C:\Clipsal\C-Gate3-Toolkit118\openjdk_jre_11.0.24_8_x64\bin\java.exe') {
  throw 'Original owned C-Gate process changed'
}
$listeners=@(Get-NetTCPConnection -State Listen -OwningProcess $service.pid -ErrorAction SilentlyContinue|ForEach-Object { "$($_.LocalAddress):$($_.LocalPort)" }|Sort-Object)
if(($listeners -join ',') -ne ((@($service.listeners)|Sort-Object) -join ',')) { throw 'Owned listener set changed' }

$client=[Net.Sockets.TcpClient]::new()
$client.ReceiveTimeout=10000;$client.SendTimeout=10000
$client.Connect('127.0.0.1',24120)
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
function Xml-FromReadback($response) {
  $prefix='['+$response.tag+'] 347-'
  $fragments=@($response.response_lines|Where-Object {$_.StartsWith($prefix)}|ForEach-Object {$_.Substring($prefix.Length)})
  if($fragments.Count -lt 1) { throw 'Readback omitted XML data rows' }
  return ($fragments -join '')
}

$rows=@()
$greeting=Read-WireLine
$row=Exchange '900' 'HELP GET' $null;$rows+=,$row
$row=Exchange '901' 'PROJECT NEW XDLT' $null;Expect-Status $row '200';$rows+=,$row
$row=Exchange '902' 'PROJECT USE XDLT' $null;Expect-Status $row '200';$rows+=,$row
$row=Exchange '903' 'DBGETXML //XDLT' $null;Expect-Status $row '344';$rows+=,$row
[xml]$projectXml=Xml-FromReadback $row
$projectNode=$projectXml.SelectSingleNode('//Project')
if(!$projectNode) { throw 'Temporary Project missing from original XML' }
$projectOid=[string]$projectNode.SelectSingleNode('./OID').InnerText
if(!$projectOid) { throw 'Temporary Project OID missing' }
$row=Exchange '904' 'NET CREATE 254 cni 127.0.0.1:1' $null;Expect-Status $row '200';$rows+=,$row
$row=Exchange '905' ('DBADD !'+$projectOid+' Network') $null;Expect-Status $row '301';$rows+=,$row
if($row.response_lines[-1] -notmatch 'OID=([0-9a-f-]{36})') { throw 'Native DBADD Network OID missing' }
$networkOid=$Matches[1]
$interfaceOid='34343434-3434-4343-8343-343434343434'
$unitOid='54545454-5454-4545-8545-545454545454'
$network="<Network><OID>$networkOid</OID><TagName>Local</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><OID>$interfaceOid</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface><Unit><OID>$unitOid</OID><TagName>SyntheticEdlt</TagName><Address>5</Address><UnitType>KEYGL5</UnitType><UnitName>Synthetic</UnitName><FirmwareVersion>5.5.00</FirmwareVersion></Unit></Network>"
$row=Exchange '906' ('DBSETXML !'+$networkOid+' << END906') $network;Expect-Status $row '301';$rows+=,$row
$row=Exchange '907' 'DBGETXML //XDLT/254/p/5' $null;Expect-Status $row '344';$rows+=,$row
foreach($command in @(
  'GET /db//XDLT/254/p/5 ?',
  'GET /db//XDLT/254/p/5 ??',
  'GET /db//XDLT/254/p/5 *',
  'GET /db//XDLT/254/p/5 DynamicLabels',
  'GET /db//XDLT/254/p/5 LabelCache',
  'GET /db//XDLT/254/p/5 Labels',
  'GET /db//XDLT/254/p/5 WidgetGroups',
  'GET //XDLT/254/p/5 ?'
)) {
  $tag=[string](908+$rows.Count-8)
  $rows+=,(Exchange $tag $command $null)
}
$client.Close()
$result=[ordered]@{
  format='native-cgate-dynamic-cache-get-v1'
  captured_utc=(Get-Date).ToUniversalTime().ToString('o')
  guest='disposable owned UTM Windows 11 VM'
  jar_sha256=$service.jar_sha256
  java_sha256=$service.java_sha256
  service_pid=$service.pid
  service_listeners=$listeners
  default_route_count=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count
  project_oid=$projectOid
  network_oid=$networkOid
  unit_oid=$unitOid
  cni_endpoint='127.0.0.1:1'
  physical_network_opened=$false
  capture_script_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $root 'cgate-dynamic-cache-vm-capture.ps1')).Hash.ToLowerInvariant()
  greeting=$greeting
  cases=$rows
}
[IO.File]::WriteAllText((Join-Path $root 'dynamic-cache-vm-capture-raw.json'),($result|ConvertTo-Json -Depth 9),[Text.UTF8Encoding]::new($false))

} catch {
  [IO.File]::WriteAllText('C:\CBusCliOracle118-88d8\dynamic-cache-vm-capture-error.txt', $_.Exception.ToString(), [Text.UTF8Encoding]::new($false))
  throw
}
