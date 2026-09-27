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
$listeners=@(Get-NetTCPConnection -State Listen -OwningProcess $service.pid -ErrorAction SilentlyContinue|
  ForEach-Object { "$($_.LocalAddress):$($_.LocalPort)" }|Sort-Object)
if(($listeners -join ',') -ne ((@($service.listeners)|Sort-Object) -join ',')) {
  throw 'Owned listener set changed'
}

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
function Read-Reply([string]$tag) {
  $lines=@()
  for($i=0;$i -lt 128;$i++) {
    $line=Read-WireLine
    $lines+=,$line
    if($line -match ('^\['+[regex]::Escape($tag)+'\] [0-9]{3} ')) { return $lines }
  }
  throw "C-Gate response for $tag did not terminate within 128 lines"
}
function Exchange([string]$tag,[string]$command,[string]$document) {
  $request='['+$tag+'] '+$command+"`r`n"
  if($command.StartsWith('DBSETXML ')) { $request+=$document+"`r`nEND"+$tag+"`r`n" }
  $bytes=[Text.Encoding]::UTF8.GetBytes($request)
  $stream.Write($bytes,0,$bytes.Length)
  return [ordered]@{tag=$tag;command=$command;request=$request;response_lines=@(Read-Reply $tag)}
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

try {
  $greeting=Read-WireLine
  $rows=@()
  $row=Exchange '900' 'PROJECT NEW XFRAME' $null;Expect-Status $row '200';$rows+=,$row
  $row=Exchange '901' 'PROJECT USE XFRAME' $null;Expect-Status $row '200';$rows+=,$row
  # The Project readback is used only to obtain its generated OID. It contains
  # a guest hostname and timestamp, so this case is not retained in the public
  # fixture; the raw guest capture is private.
  $project=Exchange '902' 'DBGETXML //XFRAME' $null;Expect-Status $project '344'
  [xml]$projectXml=Xml-FromReadback $project
  $projectOid=[string]$projectXml.SelectSingleNode('//Project/OID').InnerText
  if(!$projectOid) { throw 'Temporary Project OID missing' }
  $row=Exchange '903' 'NET CREATE 254 cni 127.0.0.1:1' $null;Expect-Status $row '200';$rows+=,$row
  $row=Exchange '904' ('DBADD !'+$projectOid+' Network') $null;Expect-Status $row '301';$rows+=,$row
  if($row.response_lines[-1] -notmatch 'OID=([0-9a-f-]{36})') { throw 'Native Network OID missing' }
  $networkOid=$Matches[1]
  $interfaceOid='33333333-3333-4333-8333-333333333333'
  $networkStart="<Network><OID>$networkOid</OID><TagName>Local</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber><Interface><OID>$interfaceOid</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>"
  $row=Exchange '905' ('DBSETXML !'+$networkOid+' << END905') ($networkStart+'</Network>');Expect-Status $row '301';$rows+=,$row
  $row=Exchange '906' 'DBGETXML //XFRAME/254' $null;Expect-Status $row '344';$rows+=,$row
  $unit='<Unit><OID>11111111-1111-4111-8111-111111111111</OID><TagName>Bedroom</TagName><Address>20</Address><UnitType>KEYE1</UnitType><UnitName>Room</UnitName><FirmwareVersion>1.2.67</FirmwareVersion></Unit>'
  $application='<Application><OID>22222222-2222-4222-8222-222222222222</OID><TagName>Lighting</TagName><Address>56</Address></Application>'
  $row=Exchange '907' 'DBSETXML //XFRAME/254 << END907' ($networkStart+$unit+$application+'</Network>');Expect-Status $row '301';$rows+=,$row
  foreach($case in @(
      @('908','DBGETXML //XFRAME/254'),
      @('909','DBGETXML //XFRAME/254/p/20'),
      @('910','DBGETXML //XFRAME/254/56'),
      @('911','DBGETXML !11111111-1111-4111-8111-111111111111'),
      @('912','DBGETXML //XFRAME/254/p/21')
    )) {
    $row=Exchange $case[0] $case[1] $null
    $rows+=,$row
  }
  # Two commands in one TCP write verify that 344 ends the XML reply and
  # leaves the following ordinary command synchronized.
  $request="[913] DBGETXML //XFRAME/254/p/20`r`n[914] NOOP`r`n"
  $bytes=[Text.Encoding]::UTF8.GetBytes($request)
  $stream.Write($bytes,0,$bytes.Length)
  $rows+=,[ordered]@{tag='913';command='DBGETXML //XFRAME/254/p/20';request="[913] DBGETXML //XFRAME/254/p/20`r`n";response_lines=@(Read-Reply '913')}
  $rows+=,[ordered]@{tag='914';command='NOOP';request="[914] NOOP`r`n";response_lines=@(Read-Reply '914')}
  $result=[ordered]@{
    format='native-cgate-dbgetxml-framing-vm-raw-v1'
    captured_utc=(Get-Date).ToUniversalTime().ToString('o')
    jar_sha256=$service.jar_sha256
    java_sha256=$service.java_sha256
    service_pid=$service.pid
    service_listeners=$listeners
    default_route_count=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count
    project_oid=$projectOid
    network_oid=$networkOid
    interface_oid=$interfaceOid
    capture_script_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $root 'cgate-dbgetxml-framing-vm-capture.ps1')).Hash.ToLowerInvariant()
    greeting=$greeting
    private_project_readback_sha256=([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes(($project.response_lines -join ''))))).Replace('-','').ToLowerInvariant()
    cases=$rows
  }
  [IO.File]::WriteAllText((Join-Path $root 'dbgetxml-framing-vm-capture-raw.json'),
    ($result|ConvertTo-Json -Depth 9),[Text.UTF8Encoding]::new($false))
} finally {
  $client.Close()
}
