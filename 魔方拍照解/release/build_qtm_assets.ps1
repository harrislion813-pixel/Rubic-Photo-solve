param(
    [ValidateSet("Standard", "Strong")][string]$Profile = "Strong",
    [string]$OutputDirectory = "",
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$solver = Join-Path $projectRoot "native\build\cube_solver.exe"
$nativeCache = Join-Path $projectRoot ".cache\native"
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $projectRoot ("dist\qtm-" + $Profile.ToLowerInvariant() + "-assets")
}
if (-not (Test-Path -LiteralPath $solver -PathType Leaf)) {
    throw "Native solver is missing. Run native\build.ps1 first."
}

$assets = @(
    @{ Name = "corner_qtm_v3.pdb"; Verify = @("verify-pdb", "--pattern", "corner", "--full") },
    @{ Name = "phase1_qtm_v3.pdb"; Verify = @("verify-pdb", "--pattern", "phase1", "--full") },
    @{ Name = "tail_qtm_depth7_v5.pdb"; Verify = @("verify-tail-pdb") }
)
if ($Profile -eq "Strong") {
    $assets += @{ Name = "strong_qtm_v4_nibble.pdb"; Verify = @("verify-strong-pdb") }
    $assets += @{ Name = "tail_qtm_depth8_v5.pdb"; Verify = @("verify-tail-pdb") }
}

$records = @()
Push-Location $projectRoot
try {
    foreach ($asset in $assets) {
        $source = Join-Path $nativeCache $asset.Name
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required $Profile asset is missing: $source. Run native\build_tables.ps1 -Metric QTM -Strong."
        }
        $arguments = @($asset.Verify[0], $source) + @($asset.Verify | Select-Object -Skip 1)
        $verificationText = (& $solver @arguments | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) { throw "Verification failed for $source" }
        $verification = $verificationText | ConvertFrom-Json
        if (-not $verification.ok -or $verification.metric -ne "QTM") {
            throw "QTM verification returned unexpected data for $source"
        }
        $item = Get-Item -LiteralPath $source
        $records += [ordered]@{
            name = $asset.Name
            bytes = $item.Length
            sha256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
            verification = $verification
        }
    }
    if ($PreflightOnly) {
        [ordered]@{
            profile = $Profile.ToLowerInvariant()
            assets = $records
        } | ConvertTo-Json -Depth 12
        return
    }
    $assetDirectory = Join-Path $OutputDirectory ".cache\native"
    New-Item -ItemType Directory -Force -Path $assetDirectory | Out-Null
    foreach ($record in $records) {
        $source = Join-Path $nativeCache $record.name
        $destination = Join-Path $assetDirectory $record.name
        Copy-Item -LiteralPath $source -Destination $destination -Force
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $record.sha256) {
            throw "Copied QTM asset hash differs from the verified source: $destination"
        }
    }
    $buildInfoPath = Join-Path $projectRoot "native\build\build-info.json"
    $manifest = [ordered]@{
        schema_version = 1
        profile = $Profile.ToLowerInvariant()
        metric = "QTM"
        proof_version = 3
        coordinate_version = 2
        native_binary_sha256 = (Get-FileHash -LiteralPath $solver -Algorithm SHA256).Hash.ToLowerInvariant()
        build_info = if (Test-Path -LiteralPath $buildInfoPath) { Get-Content -LiteralPath $buildInfoPath -Raw | ConvertFrom-Json } else { $null }
        reproduction_command = if ($Profile -eq "Strong") { "native/build_tables.ps1 -Metric QTM -Profile Strong -Resume" } else { "native/build_tables.ps1 -Metric QTM -Profile Standard" }
        assets = $records
    }
    $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $OutputDirectory "manifest.json") -Encoding utf8
    @"
QTM $Profile asset package

Copy the .cache directory into the RubicPhotoSolve portable package, preserving paths.
The native service loads the verified files on startup. The strong profile requires
several GiB of available memory and disk space. File hashes are in manifest.json.
"@ | Set-Content -LiteralPath (Join-Path $OutputDirectory "README.txt") -Encoding utf8
    Write-Output $OutputDirectory
} finally {
    Pop-Location
}
