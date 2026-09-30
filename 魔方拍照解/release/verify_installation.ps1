param([string]$Root = $PSScriptRoot)
$ErrorActionPreference = "Stop"
function Get-AssetHash([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
$Root = (Resolve-Path -LiteralPath $Root).Path
$manifest = Get-Content -Raw -LiteralPath (Join-Path $Root "asset-manifest.json") | ConvertFrom-Json
if ($manifest.profile -notin @("HtmFull", "QtmStrong")) { throw "Unknown installation profile." }
$expectedCount = if ($manifest.profile -eq "QtmStrong") { 19 } else { 7 }
if (@($manifest.files.PSObject.Properties).Count -ne $expectedCount) { throw "Incomplete runtime manifest." }
$version = (Get-Content -LiteralPath (Join-Path $Root "VERSION.txt") -Raw).Trim()
if ($version -ne $manifest.app_version) { throw "Version mismatch." }
foreach ($record in $manifest.files.PSObject.Properties) {
    $path = [IO.Path]::GetFullPath((Join-Path $Root $record.Name))
    if (-not $path.StartsWith($Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Invalid asset path." }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing asset: $($record.Name)" }
    if ((Get-Item -LiteralPath $path).Length -ne $record.Value.bytes -or (Get-AssetHash $path) -ne $record.Value.sha256) { throw "Asset check failed: $($record.Name)" }
}
Write-Host "verified: $version / $($manifest.profile) / $expectedCount assets"
