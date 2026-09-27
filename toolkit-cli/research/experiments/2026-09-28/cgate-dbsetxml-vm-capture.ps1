$ErrorActionPreference='Stop'
$root='C:\CBusCliOracle118-88d8'
$service=Get-Content -Raw -LiteralPath (Join-Path $root 'dbsetxml-vm-service.json')|ConvertFrom-Json
if($service.error -or !$service.listener_ownership_verified -or $service.jar_sha256 -ne '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630') {
  throw 'Pinned owned C-Gate service receipt is absent or invalid'
}
if(@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count -ne 0) {
  throw 'Guest has an IPv4 default route'
}
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$($service.pid)" -ErrorAction SilentlyContinue
if(!$process -or $process.ExecutablePath -ne 'C:\Clipsal\C-Gate3-Toolkit118\openjdk_jre_11.0.24_8_x64\bin\java.exe') {
  throw 'Original owned C-Gate process changed'
}
$listeners=@(Get-NetTCPConnection -State Listen -OwningProcess $service.pid -ErrorAction SilentlyContinue|ForEach-Object { "$($_.LocalAddress):$($_.LocalPort)" }|Sort-Object)
if(($listeners -join ',') -ne ((@($service.listeners)|Sort-Object) -join ',')) { throw 'Owned listener set changed' }

$client=[Net.Sockets.TcpClient]::new()
$client.ReceiveTimeout=10000;$client.SendTimeout=10000
$client.Connect('127.0.0.1',24110)
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
  for($i=0;$i -lt 128;$i++) {
    $line=Read-WireLine
    $lines+=,$line
    if($line -match ('^\['+[regex]::Escape($tag)+'\] [0-9]{3} ')) {
      return [ordered]@{tag=$tag;command=$command;request=$request;response_lines=$lines}
    }
  }
  throw "C-Gate response for $tag did not terminate within 128 lines"
}
function Xml-FromReadback($response) {
  $prefix='['+$response.tag+'] 347-'
  $fragments=@($response.response_lines|Where-Object {$_.StartsWith($prefix)}|ForEach-Object {$_.Substring($prefix.Length)})
  if($fragments.Count -lt 1) { throw 'Readback omitted XML data rows' }
  return ($fragments -join '')
}

$rows=@()
$greeting=Read-WireLine
$rows+=,(Exchange '900' 'PROJECT USE XVM24' $null)
$prior=Exchange '901' 'DBGETXML //XVM24/254' $null
$rows+=,$prior
[xml]$seed=Xml-FromReadback $prior
$networkOid=[string]$seed.Network.OID
$interfaceOid=[string]$seed.Network.Interface.OID
if(!$networkOid -or !$interfaceOid -or [string]$seed.Network.Address -ne '254' -or
   [string]$seed.Network.Interface.InterfaceAddress -ne '127.0.0.1:1') {
  throw 'Owned seeded network identity changed'
}
$networkStart="<Network><OID>$networkOid</OID><TagName>Local</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><OID>$interfaceOid</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>"
$rows+=,(Exchange '902' 'DBSETXML //XVM24/254 << END902' ($networkStart+'</Network>'))
$rows+=,(Exchange '903' 'DBGETXML //XVM24/254' $null)
$unit='<Unit><OID>11111111-1111-4111-8111-111111111111</OID><TagName>Bedroom</TagName><Address>20</Address><UnitType>KEYE1</UnitType><UnitName>Room</UnitName><FirmwareVersion>1.2.67</FirmwareVersion></Unit>'
$application='<Application><OID>22222222-2222-4222-8222-222222222222</OID><TagName>Lighting</TagName><Address>56</Address></Application>'
$baseDocument=$networkStart+$unit+$application+'</Network>'
$rows+=,(Exchange '904' 'DBSETXML //XVM24/254 << END904' $baseDocument)
$rows+=,(Exchange '905' 'DBGETXML //XVM24/254' $null)
$rows+=,(Exchange '906' 'DBGETXML //XVM24/254/p/20' $null)
$rows+=,(Exchange '907' 'DBGETXML //XVM24/254/56' $null)

# A namespaced unknown Unit attribute is a separate exact original mapper
# observation. The base Unit and Application remain otherwise identical.
$attributeUnit=$unit.Replace('<Unit>','<Unit ext:flag="synthetic">')
$attributeDocument=$networkStart.Replace('<Network>','<Network xmlns:ext="urn:cbus:oracle:2026">')+$attributeUnit+$application+'</Network>'
$rows+=,(Exchange '908' 'DBSETXML //XVM24/254 << END908' $attributeDocument)
$rows+=,(Exchange '909' 'DBGETXML //XVM24/254' $null)

# A namespaced unknown child tests a different mapping boundary.
$childUnit=$unit.Replace('</Unit>','<ext:Diagnostic>synthetic</ext:Diagnostic></Unit>')
$childDocument=$networkStart.Replace('<Network>','<Network xmlns:ext="urn:cbus:oracle:2026">')+$childUnit+$application+'</Network>'
$rows+=,(Exchange '910' 'DBSETXML //XVM24/254 << END910' $childDocument)
$rows+=,(Exchange '911' 'DBGETXML //XVM24/254' $null)

# Omitted Application should be tested only after the successful base graph.
$omittedDocument=$networkStart+$unit+'</Network>'
$rows+=,(Exchange '912' 'DBSETXML //XVM24/254 << END912' $omittedDocument)
$rows+=,(Exchange '913' 'DBGETXML //XVM24/254' $null)
$rows+=,(Exchange '914' 'DBGETXML //XVM24/254/56' $null)
$rows+=,(Exchange '915' 'NET LIST' $null)
$client.Close()

$result=[ordered]@{
  format='native-cgate-dbsetxml-vm-raw-v2'
  captured_utc=(Get-Date).ToUniversalTime().ToString('o')
  guest='disposable owned UTM Windows 11 VM'
  jar_sha256=$service.jar_sha256
  java_sha256=$service.java_sha256
  service_pid=$service.pid
  service_listeners=$listeners
  default_route_count=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count
  network_oid=$networkOid
  interface_oid=$interfaceOid
  capture_script_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $root 'cgate-dbsetxml-vm-capture.ps1')).Hash.ToLowerInvariant()
  greeting=$greeting
  cases=$rows
}
[IO.File]::WriteAllText((Join-Path $root 'dbsetxml-vm-capture-v2-raw.json'),($result|ConvertTo-Json -Depth 9),[Text.UTF8Encoding]::new($false))
