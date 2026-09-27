# Read only the two original static field values. This does not query HKCU,
# invoke the rollout helper, construct the updater, or contact a network.
# Run in a disposable Windows guest with the pinned installed SESU DLL.
$ErrorActionPreference = 'Stop'
$dll = 'C:\Program Files (x86)\Schneider Electric\Software Update\SesuBrick.DAD.dll'
$receipt = 'C:\CBusCliOracle118-88d8\sesu-registry-identity-20260928.json'
$expected = '21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c'

function HashBytes([byte[]]$bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

if ((Get-FileHash -Algorithm SHA256 -LiteralPath $dll).Hash.ToLowerInvariant() -ne $expected) {
    throw 'Pinned SESU assembly hash mismatch'
}
Set-Location 'C:\Program Files (x86)\Schneider Electric\Software Update'
$assembly = [System.Reflection.Assembly]::LoadFrom($dll)
$module = $assembly.ManifestModule
$type = $assembly.GetType('SchneiderElectric.SesuBrick.DAD.MultiPlatformUpdate', $true)
$initializer = $type.TypeInitializer
$keyGetter = $module.ResolveMethod(0x0600009f)
$entryGetter = $module.ResolveMethod(0x060000a0)
$decoder = $module.ResolveMethod(0x0600000a)
$helper = $module.ResolveMethod(0x0600012c)

$hashes = [ordered]@{
    initializer = HashBytes($initializer.GetMethodBody().GetILAsByteArray())
    key_getter = HashBytes($keyGetter.GetMethodBody().GetILAsByteArray())
    entry_getter = HashBytes($entryGetter.GetMethodBody().GetILAsByteArray())
    decoder = HashBytes($decoder.GetMethodBody().GetILAsByteArray())
    rollout_helper = HashBytes($helper.GetMethodBody().GetILAsByteArray())
}
$expectedHashes = @{
    initializer = 'c7edbffd24f038bd24f7074857798073553319b26d14dd62a527c7503c208952'
    key_getter = '345d1ea5202becb10ab827093b111f202814a309da971345f4e5cf917e210368'
    entry_getter = '0dfe027f267b3cdcfee6dcf2cf5d2c22ab7c4fe06d7471aa339d0b21630ccbc6'
    decoder = '4016a9ea6ea9b025271ea78add159ee68cc942b7a74e2795b984140a80e0e932'
    rollout_helper = 'f6dd553c61e7af5a6d216422a6040102de46330e1bc7dad3dc7259f25bfead56'
}
foreach ($name in $expectedHashes.Keys) {
    if ($hashes[$name] -ne $expectedHashes[$name]) { throw "Original $name IL hash mismatch" }
}
$flags = [System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::Static
$keyField = $type.GetField('VisibilityRegistryKeyName', $flags)
$entryField = $type.GetField('VisibilityRegistryEntryName', $flags)
if ($null -eq $keyField -or $null -eq $entryField) { throw 'Original registry fields absent' }
$key = [string]$keyField.GetValue($null)
$entry = [string]$entryField.GetValue($null)
if ($key -cne 'Software\Schneider Electric\Software Update\Persistent' -or
    $entry -cne 'VisibilityExpectedGreaterThan') { throw 'Original registry field identity mismatch' }

$result = [ordered]@{
    format = 'cbus-native-sesu-registry-identity-v1'
    assembly_sha256 = $expected
    type = $type.FullName
    registry_hive = 'HKCU'
    registry_view = 'Registry32'
    key = $key
    entry = $entry
    method_il_sha256 = $hashes
    process_bitness = [IntPtr]::Size * 8
    user_sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    registry_read_attempted = $false
    registry_write_attempted = $false
}
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receipt -Encoding UTF8
