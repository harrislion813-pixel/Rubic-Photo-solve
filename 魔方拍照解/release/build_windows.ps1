param(
    [string]$Python = "",
    [string]$OutputDirectory = "",
    [switch]$SkipNativeBuild,
    [switch]$SkipTableBuild,
    [switch]$IncludeTailPdb,
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
$nativeCache = Join-Path $projectRoot ".cache\native"
$cornerPdb = Join-Path $nativeCache "corner_htm_v2.pdb"
$phase1Pdb = Join-Path $nativeCache "phase1_sym_htm_v2.pdb"
$tailPdb = Join-Path $nativeCache "tail_depth6_v4.pdb"
$pythonTables = Join-Path $projectRoot ".cache\solver_tables_v3.pkl"
$requiredAssets = @($nativeExe, $cornerPdb, $phase1Pdb, $pythonTables)

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

    if (-not (Test-Path -LiteralPath $nativeExe -PathType Leaf)) {
        if ($SkipNativeBuild) { throw "Native solver is missing while -SkipNativeBuild was requested." }
        Assert-FreeSpace 300MB "Native solver compilation"
        Write-Progress -Activity "Building Windows release" -Status "Compiling the C++ solver" -PercentComplete 10
        & (Join-Path $projectRoot "native\build.ps1") | Out-Host
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

    foreach ($asset in $requiredAssets) { Assert-Asset $asset }
    if ($IncludeTailPdb) { Assert-Asset $tailPdb }
    Assert-FreeSpace 1.5GB "Portable package assembly"

    if ($PreflightOnly) {
        Write-Progress -Activity "Building Windows release" -Completed
        Write-Host "Release preflight passed. Native solver and required PDBs are ready."
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
    Copy-Item -LiteralPath $cornerPdb, $phase1Pdb -Destination (Join-Path $packageRoot ".cache\native") -Force
    if ($IncludeTailPdb) {
        Copy-Item -LiteralPath $tailPdb -Destination (Join-Path $packageRoot ".cache\native\tail_depth6_v4.pdb") -Force
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README-Windows.txt") -Destination $packageRoot -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "启动魔方求解器.cmd") -Destination $packageRoot -Force
    Set-Content -LiteralPath (Join-Path $packageRoot "VERSION.txt") -Value $version -Encoding ascii

    $archive = Join-Path $OutputDirectory "$packageName-$version-windows-x64.zip"
    if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
    Write-Progress -Activity "Building Windows release" -Status "Compressing portable package" -PercentComplete 90
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $archive -CompressionLevel Optimal
    Write-Progress -Activity "Building Windows release" -Completed
    Write-Host "Windows portable package created: $archive"
} finally {
    Pop-Location
}
