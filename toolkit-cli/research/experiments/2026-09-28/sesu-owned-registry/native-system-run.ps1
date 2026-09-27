$ErrorActionPreference = 'Stop'
$root = 'C:\CBusCliOracle118-88d8'
$pythonZip = Join-Path $root 'cohort-python-3.13.14-embed-arm64.zip'
$bundleZip = Join-Path $root 'cohort-native-bundle.zip'
$pythonDir = Join-Path $root 'cohort-python-3.13.14'
$bundleDir = Join-Path $root 'cohort-native-bundle'
$result = Join-Path $root 'cohort-native-wrapper.json'
$routesBefore = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0', '::/0' -ErrorAction SilentlyContinue)
$receipt = [ordered]@{
    format = 'cbus-sesu-owned-native-wrapper-v1'
    context = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    python_version = '3.13.14'
    python_package_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $pythonZip).Hash.ToLowerInvariant()
    bundle_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $bundleZip).Hash.ToLowerInvariant()
    route_count_before = $routesBefore.Count
    process_exit_code = $null
    cleanup_confirmed = $false
}
try {
    if ((Test-Path -LiteralPath $pythonDir) -or (Test-Path -LiteralPath $bundleDir)) {
        throw 'Owned extraction path already exists'
    }
    Expand-Archive -LiteralPath $pythonZip -DestinationPath $pythonDir
    Expand-Archive -LiteralPath $bundleZip -DestinationPath $bundleDir
    $pythonExe = Join-Path $pythonDir 'python.exe'
    & $pythonExe (Join-Path $bundleDir 'accept.py') *> $null
    $receipt.process_exit_code = $LASTEXITCODE
} catch {
    $receipt.error_type = $_.Exception.GetType().Name
    $receipt.error_message = $_.Exception.Message
} finally {
    foreach ($path in @($pythonDir, $bundleDir, $pythonZip, $bundleZip)) {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    }
    $remaining = @()
    foreach ($path in @($pythonDir, $bundleDir, $pythonZip, $bundleZip)) {
        if (Test-Path -LiteralPath $path) { $remaining += $path }
    }
    $receipt.cleanup_confirmed = $remaining.Count -eq 0
    $routesAfter = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0', '::/0' -ErrorAction SilentlyContinue)
    $receipt.route_count_after = $routesAfter.Count
    $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $result -Encoding UTF8
}
