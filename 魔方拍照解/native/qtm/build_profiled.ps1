param(
    [string]$Compiler = "C:\msys64\ucrt64\bin\g++.exe",
    [switch]$Portable,
    [string]$OutputDirectory,
    [string]$TrainingCases,
    [ValidateRange(0.1, 5.0)][double]$TrainingTimeout = 5
)

$ErrorActionPreference = "Stop"

$compiler = $Compiler
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$buildDirectory = if ($OutputDirectory) { $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory) } else { Join-Path $PSScriptRoot "build" }
$trainingCasesPath = if ($TrainingCases) { $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($TrainingCases) } else { Join-Path $projectRoot "tests\qtm_pgo_cases.json" }
if (-not (Test-Path -LiteralPath $trainingCasesPath -PathType Leaf)) { throw "PGO training cases are missing: $trainingCasesPath" }
$trainingTarget = Join-Path $buildDirectory "cube_solver_qtm_profiled.exe"
$target = Join-Path $buildDirectory "cube_solver_qtm.exe"
$compilerTrainingOutput = [System.IO.Path]::GetRelativePath($PSScriptRoot, $trainingTarget)
$trainingReport = Join-Path $buildDirectory "pgo-training.json"
$profileName = "pgo-$PID"
$profileDirectory = Join-Path (Join-Path $projectRoot ".cache\qtm") $profileName
$cornerPdb = Join-Path $projectRoot "assets\qtm\v1\corner_htm_v2.pdb"
$phase1Pdb = Join-Path $projectRoot "assets\qtm\v1\phase1_sym_htm_v2.pdb"
$tailPdb = Join-Path $projectRoot "assets\qtm\v1\tail_depth6_v4.pdb"
foreach ($path in @($cornerPdb, $phase1Pdb, $tailPdb)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Profile-guided build requires the native databases: $path"
    }
}
foreach ($name in @("corner_qtm_v3.pdb", "phase1_qtm_v3.pdb", "strong_qtm_v4_nibble.pdb", "tail_qtm_depth8_v5.pdb")) {
    $asset = Join-Path (Join-Path $projectRoot "assets\qtm\v1") $name
    if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) {
        throw "QTM PGO training requires $asset"
    }
}
if (-not (Test-Path -LiteralPath $compiler)) {
    throw "C++ compiler not found: $compiler"
}

$env:PATH = (Split-Path -Parent $compiler) + ";" + $env:PATH
New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $profileDirectory | Out-Null

$common = @(
    "-std=c++20",
    "-O3",
    $(if ($Portable) { "-march=x86-64" } else { "-march=native" }),
    $(if ($Portable) { "-mtune=generic" } else { "-mtune=native" }),
    "-flto",
    "-fprofile-update=atomic",
    "-DNDEBUG",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-I", "include",
    "src\cube.cpp",
    "src\fast.cpp",
    "src\pdb.cpp",
    "src\solver.cpp",
    "src\symmetry.cpp",
    "src\strong_coords.cpp",
    "src\strong_pdb.cpp",
    "src\tail.cpp",
    "src\main.cpp",
    "-pthread",
    "-municode",
    "-static"
)

Push-Location $PSScriptRoot
try {
    $prefix = (Get-Location).Path
    & $compiler @common "-fprofile-generate=$profileDirectory" "-fprofile-prefix-path=$prefix" `
        -o $compilerTrainingOutput
    if ($LASTEXITCODE -ne 0) { throw "PGO instrumented build failed with exit code $LASTEXITCODE" }

    Push-Location $projectRoot
    try {
        $ErrorActionPreference = "Continue"
        try {
            $trainingPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
            if (-not (Test-Path -LiteralPath $trainingPython)) { $trainingPython = "python" }
            & $trainingPython tests\train_qtm_pgo.py --binary $trainingTarget --cases $trainingCasesPath `
                --timeout $TrainingTimeout --threads 15 --output $trainingReport
            $trainingExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = "Stop"
        }
        if ($trainingExitCode -ne 0) { throw "PGO training solve failed with exit code $trainingExitCode" }
    } finally {
        Pop-Location
    }

    $profileFiles = @(Get-ChildItem -LiteralPath $profileDirectory -Filter "*.gcda" -File -Recurse)
    if (-not $profileFiles.Count) { throw "PGO training produced no GCC profile files; refusing a nominal PGO build" }
    & $compiler @common "-fprofile-use=$profileDirectory" -fprofile-correction -Werror=missing-profile `
        "-fprofile-prefix-path=$prefix" -o $compilerTrainingOutput
    if ($LASTEXITCODE -ne 0) { throw "PGO optimized build failed with exit code $LASTEXITCODE" }
    Move-Item -LiteralPath $trainingTarget -Destination $target -Force
    $buildInfo = [ordered]@{
        compiler = (& $compiler --version | Select-Object -First 1)
        flags = ($common -join " ") + " -fprofile-use -fprofile-correction -Werror=missing-profile"
        profile_guided = $true
        portable = [bool]$Portable
        metric = "QTM"
        built_at = [DateTime]::UtcNow.ToString("o")
        binary_sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        training_cases_sha256 = (Get-FileHash -LiteralPath $trainingCasesPath -Algorithm SHA256).Hash
        training_report_sha256 = (Get-FileHash -LiteralPath $trainingReport -Algorithm SHA256).Hash
        training_cases = $trainingCasesPath
        training_timeout = $TrainingTimeout
        source_sha256 = @{}
        source_paths_sha256 = @{}
        asset_sha256 = @{}
    }
    Get-ChildItem (Join-Path $PSScriptRoot "src"), (Join-Path $PSScriptRoot "include") -File -Recurse | ForEach-Object {
        $sourceHash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        $buildInfo.source_sha256[$_.Name] = $sourceHash
        $relativeSource = [System.IO.Path]::GetRelativePath($PSScriptRoot, $_.FullName)
        $buildInfo.source_paths_sha256[$relativeSource] = $sourceHash
    }
    $trainingIdentity = Get-Content -Raw -LiteralPath $trainingReport | ConvertFrom-Json
    $buildInfo.asset_sha256 = $trainingIdentity.asset_sha256
    $buildInfo.training_flags = $trainingIdentity.flags
    $buildInfo.training_threads = $trainingIdentity.threads
    $buildInfo.training_excluded_initials = $trainingIdentity.excluded_initials
    $buildInfo | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $buildDirectory "build-info.json") -Encoding utf8
} finally {
    Pop-Location
    $resolvedProfile = [System.IO.Path]::GetFullPath($profileDirectory)
    $resolvedCache = [System.IO.Path]::GetFullPath((Join-Path $projectRoot ".cache\qtm"))
    $cachePrefix = $resolvedCache.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if ($resolvedProfile.StartsWith($cachePrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
        ([System.IO.Path]::GetFileName($resolvedProfile)).StartsWith("pgo-")) {
        Remove-Item -LiteralPath $resolvedProfile -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Output $target
