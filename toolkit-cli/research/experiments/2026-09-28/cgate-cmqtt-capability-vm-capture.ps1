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
try {
  $greeting=Read-WireLine
  $request="[1] CMQTT CAPABILITIES`r`n[2] NOOP`r`n"
  $bytes=[Text.Encoding]::UTF8.GetBytes($request)
  $stream.Write($bytes,0,$bytes.Length)
  $capabilities=@(Read-Reply '1')
  $noop=@(Read-Reply '2')
  $result=[ordered]@{
    format='native-cgate-cmqtt-capability-vm-v1'
    jar_sha256=$service.jar_sha256
    greeting=$greeting
    request=$request
    capability_response_lines=$capabilities
    noop_response_lines=$noop
    default_route_count=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count
  }
  [IO.File]::WriteAllText((Join-Path $root 'cgate-cmqtt-capability-vm-capture.json'),
    ($result|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
} finally {
  $client.Close()
}
