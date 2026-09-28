param(
    [string]$Python = "",
    [string]$OutputDirectory = "",
    [switch]$SkipNativeBuild,
    [switch]$SkipTableBuild,
    [switch]$IncludeTailPdb,
    [ValidateSet("None", "Standard", "Strong")][string]$QtmProfile = "None",
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $Python = if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $venvPython } else { "python" }
}
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $projectRoot "dist"
}

$nativeExe = Join-Path $projectRoot "native\build\cube_solver.exe"
$nativeBuildInfo = Join-Path $projectRoot "native\build\build-info.json"
$nativeCache = Join-Path $projectRoot ".cache\native"
$cornerPdb = Join-Path $nativeCache "corner_htm_v2.pdb"
$phase1Pdb = Join-Path $nativeCache "phase1_sym_htm_v2.pdb"
$tailPdb = Join-Path $nativeCache "tail_depth6_v4.pdb"
$qtmAssetNames = @()
if ($QtmProfile -ne "None") {
    $qtmAssetNames = @("corner_qtm_v3.pdb", "phase1_qtm_v3.pdb", "tail_qtm_depth7_v5.pdb")
    if ($QtmProfile -eq "Strong") {
        $qtmAssetNames += @("strong_qtm_v3.pdb", "tail_qtm_depth8_v5.pdb")
    }
}
$pythonTables = Join-Path $projectRoot ".cache\solver_tables_v3.pkl"
$pythonQtmTables = Join-Path $projectRoot ".cache\qtm_small_v1.bin"
$twoByTwoTables = @(
    (Join-Path $projectRoot ".cache\two_by_two_htm_v1.bin"),
    (Join-Path $projectRoot ".cache\two_by_two_qtm_v1.bin")
)
$requiredAssets = @($nativeExe, $cornerPdb, $phase1Pdb, $pythonTables) + $twoByTwoTables

function Assert-FreeSpace {
    param([long]$RequiredBytes, [string]$Purpose)
    $drive = (Get-Item -LiteralPath $projectRoot).PSDrive
    if ($null -ne $drive.Free -and $drive.Free -lt $RequiredBytes) {
        $requiredGiB = [Math]::Round($RequiredBytes / 1GB, 1)
        $freeGiB = [Math]::Round($drive.Free / 1GB, 1)
        throw "$Purpose requires at least $requiredGiB GiB free; drive $($drive.Name) has $freeGiB GiB."
    }
}

function Assert-Asset {
    param([string]$Path, [long]$MinimumBytes = 1MB)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required release asset is missing: $Path"
    }
    if ((Get-Item -LiteralPath $Path).Length -lt $MinimumBytes) {
        throw "Release asset is unexpectedly small and may be corrupt: $Path"
    }
}

Push-Location $projectRoot
try {
    & $Python -c "import sys; assert (3, 10) <= sys.version_info[:2] < (3, 15), sys.version; print(sys.version.split()[0])"
    if ($LASTEXITCODE -ne 0) { throw "Windows releases require Python 3.10 through 3.14." }
    $version = (& $Python release\check_version.py).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $version) { throw "Application version validation failed." }

    $nativePortable = (Test-Path -LiteralPath $nativeExe -PathType Leaf) -and
                      (Test-Path -LiteralPath $nativeBuildInfo -PathType Leaf) -and
                      ((Get-Content -LiteralPath $nativeBuildInfo -Raw | ConvertFrom-Json).portable -eq $true)
    if (-not $nativePortable) {
        if ($SkipNativeBuild) { throw "A portable native solver is required while -SkipNativeBuild was requested." }
        Assert-FreeSpace 300MB "Native solver compilation"
        Write-Progress -Activity "Building Windows release" -Status "Compiling the C++ solver" -PercentComplete 10
        & (Join-Path $projectRoot "native\build.ps1") -Portable | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Native solver compilation failed with exit code $LASTEXITCODE" }
    }

    if (-not (Test-Path -LiteralPath $cornerPdb -PathType Leaf) -or
        -not (Test-Path -LiteralPath $phase1Pdb -PathType Leaf)) {
        if ($SkipTableBuild) { throw "Required PDBs are missing while -SkipTableBuild was requested." }
        Assert-FreeSpace 1GB "PDB generation"
        Write-Progress -Activity "Building Windows release" -Status "Generating required pruning databases" -PercentComplete 25
        & (Join-Path $projectRoot "native\build_tables.ps1") -CiMinimal | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "PDB generation failed with exit code $LASTEXITCODE" }
    }

    if (-not (Test-Path -LiteralPath $pythonTables -PathType Leaf)) {
        Write-Progress -Activity "Building Windows release" -Status "Generating Python quick-solver tables" -PercentComplete 35
        & $Python -c "from cube_app.tables import load_or_build_tables; load_or_build_tables('.cache')"
        if ($LASTEXITCODE -ne 0) { throw "Python solver-table generation failed with exit code $LASTEXITCODE" }
    }

    if ($QtmProfile -ne "None") {
        & $Python -c "from cube_app.qtm_small import load_qtm_small_tables; import sys; sys.exit(0 if load_qtm_small_tables('.cache') is not None else 1)"
        if ($LASTEXITCODE -ne 0) {
            Write-Progress -Activity "Building Windows release" -Status "Generating QTM Python fallback tables" -PercentComplete 38
            & $Python -m cube_app.qtm_small
            if ($LASTEXITCODE -ne 0) { throw "QTM Python fallback tables could not be built" }
        }
        $requiredAssets += $pythonQtmTables
    }

    Write-Progress -Activity "Building Windows release" -Status "Preparing verified HTM/QTM 2x2 distance tables" -PercentComplete 40
    foreach ($metric in @("HTM", "QTM")) {
        & $Python -m cube_app.two_by_two_tables --metric $metric
        if ($LASTEXITCODE -ne 0) { throw "$metric 2x2 distance-table verification failed with exit code $LASTEXITCODE" }
    }

    & $Python -c "import json, pathlib, subprocess; p = subprocess.run([str(pathlib.Path('native/build/cube_solver.exe').resolve()), 'serve'], input='', stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', timeout=30); ready = json.loads(p.stdout.splitlines()[0]); assert p.returncode == 0 and ready.get('ok') and ready.get('type') == 'ready' and ready.get('protocol_version') == 3 and ready.get('proof_version') == 3 and {'HTM', 'QTM'}.issubset(ready.get('metrics', [])), ready; print('Native protocol 3 / proof 3: HTM, QTM verified')"
    if ($LASTEXITCODE -ne 0) { throw "Native solver lacks verified dual-metric protocol support. Rebuild with native\build.ps1." }

    foreach ($asset in $requiredAssets) { Assert-Asset $asset }
    if ($IncludeTailPdb) { Assert-Asset $tailPdb }
    $qtmVerified = $null
    if ($QtmProfile -ne "None") {
        $verificationJson = (& (Join-Path $PSScriptRoot "build_qtm_assets.ps1") -Profile $QtmProfile -PreflightOnly |
                             Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $verificationJson) { throw "QTM $QtmProfile asset preflight failed" }
        $qtmVerified = $verificationJson | ConvertFrom-Json
        if ($qtmVerified.profile -ne $QtmProfile.ToLowerInvariant() -or
            $qtmVerified.assets.Count -ne $qtmAssetNames.Count) {
            throw "QTM asset preflight returned an unexpected profile or file count"
        }
        Write-Host "QTM $QtmProfile asset preflight passed ($($qtmVerified.assets.Count) verified files)."
    }
    $assemblyBytes = if ($QtmProfile -eq "Strong") { 9GB } elseif ($QtmProfile -eq "Standard") { 3GB } else { 1.5GB }
    Assert-FreeSpace $assemblyBytes "Portable package assembly"

    if ($PreflightOnly) {
        Write-Progress -Activity "Building Windows release" -Completed
        Write-Host "Release preflight passed. Dual-metric native solver, both 2x2 tables and required PDBs are ready."
        return
    }

    & $Python -c "import PyInstaller, cv2, numpy"
    if ($LASTEXITCODE -ne 0) {
        throw "Release dependencies are missing. Run: $Python -m pip install -r requirements-release.txt"
    }

    $workDirectory = Join-Path $projectRoot ".release-build"
    $packageName = "RubicPhotoSolve"
    New-Item -ItemType Directory -Force -Path $workDirectory, $OutputDirectory | Out-Null
    Write-Progress -Activity "Building Windows release" -Status "Freezing Python and OpenCV" -PercentComplete 45
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --name $packageName `
        --distpath $OutputDirectory `
        --workpath (Join-Path $workDirectory "work") `
        --specpath $workDirectory `
        (Join-Path $projectRoot "windows_launcher.py")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    $packageRoot = Join-Path $OutputDirectory $packageName
    Write-Progress -Activity "Building Windows release" -Status "Copying web and solver assets" -PercentComplete 75
    Copy-Item -LiteralPath (Join-Path $projectRoot "web") -Destination (Join-Path $packageRoot "web") -Recurse -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "native\build") | Out-Null
    Copy-Item -LiteralPath $nativeExe -Destination (Join-Path $packageRoot "native\build\cube_solver.exe") -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot ".cache\native") | Out-Null
    Copy-Item -LiteralPath $pythonTables -Destination (Join-Path $packageRoot ".cache\solver_tables_v3.pkl") -Force
    if ($QtmProfile -ne "None") {
        Copy-Item -LiteralPath $pythonQtmTables -Destination (Join-Path $packageRoot ".cache\qtm_small_v1.bin") -Force
    }
    Copy-Item -LiteralPath $twoByTwoTables -Destination (Join-Path $packageRoot ".cache") -Force
    Copy-Item -LiteralPath $cornerPdb, $phase1Pdb -Destination (Join-Path $packageRoot ".cache\native") -Force
    if ($IncludeTailPdb) {
        Copy-Item -LiteralPath $tailPdb -Destination (Join-Path $packageRoot ".cache\native\tail_depth6_v4.pdb") -Force
    }
    if ($QtmProfile -ne "None") {
        $qtmManifest = [ordered]@{
            schema_version = 1
            profile = $QtmProfile.ToLowerInvariant()
            metric = "QTM"
            proof_version = 3
            coordinate_version = 2
            native_binary_sha256 = (Get-FileHash -LiteralPath $nativeExe -Algorithm SHA256).Hash.ToLowerInvariant()
            python_fallback_asset = [ordered]@{
                name = "qtm_small_v1.bin"
                bytes = (Get-Item -LiteralPath $pythonQtmTables).Length
                sha256 = (Get-FileHash -LiteralPath $pythonQtmTables -Algorithm SHA256).Hash.ToLowerInvariant()
            }
            assets = @()
        }
        foreach ($name in $qtmAssetNames) {
            $source = Join-Path $nativeCache $name
            $destination = Join-Path $packageRoot ".cache\native\$name"
            $verifiedRecord = @($qtmVerified.assets | Where-Object { $_.name -eq $name })
            if ($verifiedRecord.Count -ne 1) { throw "QTM verification record missing: $name" }
            Copy-Item -LiteralPath $source -Destination $destination -Force
            $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
            $copyHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
            if ($sourceHash -ne $copyHash -or $copyHash.ToLowerInvariant() -ne $verifiedRecord[0].sha256) {
                throw "Copied QTM asset hash differs: $name"
            }
            $qtmManifest.assets += [ordered]@{
                name = $name
                bytes = (Get-Item -LiteralPath $destination).Length
                sha256 = $copyHash.ToLowerInvariant()
                verification = $verifiedRecord[0].verification
            }
        }
        $qtmManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $packageRoot ".cache\native\qtm-asset-manifest.json") -Encoding utf8
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README-Windows.txt") -Destination $packageRoot -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "启动魔方求解器.cmd") -Destination $packageRoot -Force
    Set-Content -LiteralPath (Join-Path $packageRoot "VERSION.txt") -Value $version -Encoding ascii

    $archive = Join-Path $OutputDirectory "$packageName-$version-windows-x64.zip"
    if ($QtmProfile -ne "Strong" -and (Test-Path -LiteralPath $archive)) {
        Remove-Item -LiteralPath $archive -Force
    }
    Write-Progress -Activity "Building Windows release" -Status "Compressing portable package" -PercentComplete 90
    if ($QtmProfile -eq "Strong") {
        & $Python release\zip64_package.py $packageRoot $archive
        if ($LASTEXITCODE -ne 0) { throw "ZIP64 portable package assembly failed" }
    } else {
        Compress-Archive -LiteralPath $packageRoot -DestinationPath $archive -CompressionLevel Optimal
    }
    Write-Progress -Activity "Building Windows release" -Completed
    Write-Host "Windows portable package created: $archive"
} finally {
    Pop-Location
}
