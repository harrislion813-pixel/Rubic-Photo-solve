param(
    [ValidateSet("HtmFull", "QtmStrong")][string]$Profile,
    [string]$Python = "",
    [string]$OutputDirectory = "",
    [switch]$SkipNativeBuild,
    [switch]$SkipTableBuild,
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
if (-not $Profile) { throw "Select the release acceptance profile with -Profile HtmFull or -Profile QtmStrong." }
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $venv = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $Python = if (Test-Path -LiteralPath $venv) { $venv } else { "python" }
}
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot "dist\$Profile" }
$OutputDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

Push-Location $projectRoot
try {
    $version = (& $Python release\check_version.py).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $version) { throw "Application version check failed." }

    $htmExe = Join-Path $projectRoot "native\htm\build\cube_solver_htm.exe"
    $qtmExe = Join-Path $projectRoot "native\qtm\build\cube_solver_qtm.exe"
    if (-not (Test-Path -LiteralPath $htmExe)) {
        if ($SkipNativeBuild) { throw "HTM EXE is missing." }
        & (Join-Path $projectRoot "native\htm\build.ps1") | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "HTM native build failed." }
    }
    if ($Profile -eq "QtmStrong" -and -not (Test-Path -LiteralPath $qtmExe)) {
        if ($SkipNativeBuild) { throw "QTM EXE is missing." }
        & (Join-Path $projectRoot "native\qtm\build.ps1") -Portable | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "QTM native build failed." }
    }
    $htmAssets = @(
        "assets\htm\v1\corner_htm_v2.pdb",
        "assets\htm\v1\phase1_sym_htm_v2.pdb",
        "assets\htm\v1\tail_depth6_v4.pdb"
    )
    if (@($htmAssets | Where-Object { -not (Test-Path -LiteralPath (Join-Path $projectRoot $_)) }).Count) {
        if ($SkipTableBuild) { throw "HTM full PDB or Tail-6 is missing." }
        & (Join-Path $projectRoot "native\htm\build_tables.ps1") | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "HTM asset build failed." }
    }
    if ($Profile -eq "QtmStrong") {
        $required = @(
            "assets\qtm\v1\corner_qtm_v3.pdb",
            "assets\qtm\v1\phase1_qtm_v3.pdb",
            "assets\qtm\v1\strong_qtm_v4_nibble.pdb",
            "assets\qtm\v1\tail_qtm_depth8_v5.pdb"
        )
        if (@($required | Where-Object { -not (Test-Path -LiteralPath (Join-Path $projectRoot $_)) }).Count) {
            throw "QTM strong assets are missing. Prepare the separately verified QTM asset set before packaging."
        }
    }
    & $Python release\prepare_runtime_caches.py --profile $Profile
    if ($LASTEXITCODE -ne 0) { throw "Python fallback cache preparation failed." }
    $manifest = Join-Path $OutputDirectory "asset-manifest.json"
    & $Python release\verify_assets.py --root $projectRoot --profile $Profile --write $manifest
    if ($LASTEXITCODE -ne 0) { throw "Release asset verification failed." }
    if ($PreflightOnly) { Write-Output $manifest; return }

    & $Python -c "import PyInstaller, cv2, numpy"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller, OpenCV or NumPy is unavailable." }
    $workDirectory = Join-Path $projectRoot ".release-build\$Profile"
    $packageName = "RubicPhotoSolve"
    $pyArgs = @(
        "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", $packageName,
        "--distpath", $OutputDirectory,
        "--workpath", (Join-Path $workDirectory "work"),
        "--specpath", $workDirectory
    )
    if ($Profile -eq "HtmFull") { $pyArgs += @("--exclude-module", "cube_app.solvers.qtm") }
    $pyArgs += (Join-Path $projectRoot "windows_launcher.py")
    & $Python @pyArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $packageRoot = Join-Path $OutputDirectory $packageName
    Copy-Item -LiteralPath (Join-Path $projectRoot "web") -Destination (Join-Path $packageRoot "web") -Recurse -Force
    $selected = (Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json).files.PSObject.Properties.Name
    foreach ($relative in $selected) {
        $source = Join-Path $projectRoot $relative
        $destination = Join-Path $packageRoot $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
    Copy-Item -LiteralPath $manifest -Destination (Join-Path $packageRoot "asset-manifest.json") -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README-Windows.txt") -Destination $packageRoot -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "启动魔方求解器.cmd") -Destination $packageRoot -Force
    Set-Content -LiteralPath (Join-Path $packageRoot "VERSION.txt") -Value $version -Encoding ascii
    $archive = Join-Path $OutputDirectory "RubicPhotoSolve-$version-$Profile-windows-x64.zip"
    & $Python release\zip64_package.py $packageRoot $archive
    if ($LASTEXITCODE -ne 0) { throw "ZIP64 package failed." }
    Write-Output $archive
} finally {
    Pop-Location
}
