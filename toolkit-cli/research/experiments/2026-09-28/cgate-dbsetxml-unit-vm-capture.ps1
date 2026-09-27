$ErrorActionPreference='Stop'
$root='C:\CBusCliOracle118-88d8'
$service=Get-Content -Raw -LiteralPath (Join-Path $root 'dbsetxml-vm-service.json')|ConvertFrom-Json
if($service.error -or !$service.listener_ownership_verified -or
   $service.jar_sha256 -ne '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630') {
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
$row=Exchange '800' 'PROJECT NEW XUNIT' $null;Expect-Status $row '200';$rows+=,$row
$row=Exchange '801' 'PROJECT USE XUNIT' $null;Expect-Status $row '200';$rows+=,$row
$row=Exchange '802' 'DBGETXML //XUNIT' $null;Expect-Status $row '344';$rows+=,$row
[xml]$projectXml=Xml-FromReadback $row
$projectNode=$projectXml.SelectSingleNode('//Project')
if(!$projectNode) { throw 'Temporary Project missing from original XML' }
$projectOid=[string]$projectNode.SelectSingleNode('./OID').InnerText
if(!$projectOid) { throw 'Temporary Project OID missing' }
$row=Exchange '803' 'NET CREATE 254 cni 127.0.0.1:1' $null;Expect-Status $row '200';$rows+=,$row
$row=Exchange '804' 'NET LIST' $null;Expect-Status $row '131';$rows+=,$row
$row=Exchange '805' ('DBADD !'+$projectOid+' Network') $null;Expect-Status $row '301';$rows+=,$row
if($row.response_lines[-1] -notmatch 'OID=([0-9a-f-]{36})') { throw 'Native DBADD Network OID missing' }
$networkOid=$Matches[1]
$interfaceOid='33333333-3333-4333-8333-333333333333'
$networkStart="<Network><OID>$networkOid</OID><TagName>Local</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><OID>$interfaceOid</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>"
$unit='<Unit><OID>11111111-1111-4111-8111-111111111111</OID><TagName>Bedroom</TagName><Address>20</Address><UnitType>KEYE1</UnitType><UnitName>Room</UnitName><FirmwareVersion>1.2.67</FirmwareVersion></Unit>'
$application='<Application><OID>22222222-2222-4222-8222-222222222222</OID><TagName>Lighting</TagName><Address>56</Address></Application>'
$row=Exchange '806' ('DBSETXML !'+$networkOid+' << END806') ($networkStart+'</Network>');Expect-Status $row '301';$rows+=,$row
$row=Exchange '807' 'DBGETXML //XUNIT/254' $null;Expect-Status $row '344';$rows+=,$row
$row=Exchange '808' 'DBSETXML //XUNIT/254 << END808' ($networkStart+$unit+$application+'</Network>');Expect-Status $row '301';$rows+=,$row
$row=Exchange '809' 'DBGETXML //XUNIT/254/p/20' $null;Expect-Status $row '344';$rows+=,$row

# Compare direct Unit replacement with the previously captured combined
# Network replacement, using the same synthetic Unit and project state.
$attributeUnit=$unit.Replace('<Unit>','<Unit xmlns:ext="urn:cbus:oracle:2026" ext:flag="synthetic">')
$row=Exchange '810' 'DBSETXML //XUNIT/254/p/20 << END810' $attributeUnit;Expect-Status $row '301';$rows+=,$row
$row=Exchange '811' 'DBGETXML //XUNIT/254/p/20' $null;Expect-Status $row '344';$rows+=,$row
$row=Exchange '812' 'DBGETXML //XUNIT/254' $null;Expect-Status $row '344';$rows+=,$row
$childUnit=$unit.Replace('<Unit>','<Unit xmlns:ext="urn:cbus:oracle:2026">').Replace('</Unit>','<ext:Diagnostic>synthetic</ext:Diagnostic></Unit>')
$row=Exchange '813' 'DBSETXML //XUNIT/254/p/20 << END813' $childUnit;Expect-Status $row '301';$rows+=,$row
$row=Exchange '814' 'DBGETXML //XUNIT/254/p/20' $null;Expect-Status $row '344';$rows+=,$row
$row=Exchange '815' 'DBGETXML //XUNIT/254' $null;Expect-Status $row '344';$rows+=,$row

$combinedAttribute=$networkStart.Replace('<Network>','<Network xmlns:ext="urn:cbus:oracle:2026">')+$unit.Replace('<Unit>','<Unit ext:flag="synthetic">')+$application+'</Network>'
$row=Exchange '816' 'DBSETXML //XUNIT/254 << END816' $combinedAttribute;Expect-Status $row '301';$rows+=,$row
$row=Exchange '817' 'DBGETXML //XUNIT/254/p/20' $null;Expect-Status $row '344';$rows+=,$row
$combinedChild=$networkStart.Replace('<Network>','<Network xmlns:ext="urn:cbus:oracle:2026">')+$unit.Replace('</Unit>','<ext:Diagnostic>synthetic</ext:Diagnostic></Unit>')+$application+'</Network>'
$row=Exchange '818' 'DBSETXML //XUNIT/254 << END818' $combinedChild;Expect-Status $row '301';$rows+=,$row
$row=Exchange '819' 'DBGETXML //XUNIT/254/p/20' $null;Expect-Status $row '344';$rows+=,$row
$row=Exchange '820' 'NET LIST' $null;Expect-Status $row '131';$rows+=,$row
$client.Close()

$result=[ordered]@{
  format='native-cgate-dbsetxml-unit-vm-raw-v1'
  captured_utc=(Get-Date).ToUniversalTime().ToString('o')
  guest='disposable owned UTM Windows 11 VM'
  jar_sha256=$service.jar_sha256
  java_sha256=$service.java_sha256
  service_pid=$service.pid
  service_listeners=$listeners
  default_route_count=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count
  project_oid=$projectOid
  network_oid=$networkOid
  interface_oid=$interfaceOid
  capture_script_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $root 'cgate-dbsetxml-unit-vm-capture.ps1')).Hash.ToLowerInvariant()
  greeting=$greeting
  cases=$rows
}
[IO.File]::WriteAllText((Join-Path $root 'dbsetxml-unit-vm-capture-raw.json'),($result|ConvertTo-Json -Depth 9),[Text.UTF8Encoding]::new($false))
