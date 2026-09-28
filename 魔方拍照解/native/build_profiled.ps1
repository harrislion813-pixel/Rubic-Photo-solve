param(
    [string]$Compiler = "C:\msys64\ucrt64\bin\g++.exe",
    [double]$TrainingTimeout = 30,
    [ValidateSet("HTM", "QTM")][string]$Metric = "HTM"
)

$ErrorActionPreference = "Stop"

$compiler = $Compiler
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildDirectory = Join-Path $PSScriptRoot "build"
$trainingTarget = Join-Path $buildDirectory "cube_solver_profiled.exe"
$target = Join-Path $buildDirectory "cube_solver.exe"
$profileName = "pgo-$PID"
$profileDirectory = Join-Path (Join-Path $projectRoot ".cache\native") $profileName
$profileFromProject = ".cache/native/$profileName"
$profileFromNative = "../.cache/native/$profileName"

$cornerPdb = Join-Path $projectRoot ".cache\native\corner_htm_v2.pdb"
$phase1Pdb = Join-Path $projectRoot ".cache\native\phase1_sym_htm_v2.pdb"
$tailPdb = Join-Path $projectRoot ".cache\native\tail_depth6_v4.pdb"
foreach ($path in @($cornerPdb, $phase1Pdb, $tailPdb)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Profile-guided build requires the native databases: $path"
    }
}
if ($Metric -eq "QTM") {
    foreach ($name in @("corner_qtm_v3.pdb", "phase1_qtm_v3.pdb", "strong_qtm_v3.pdb", "tail_qtm_depth8_v5.pdb")) {
        $asset = Join-Path (Join-Path $projectRoot ".cache\native") $name
        if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) {
            throw "QTM PGO training requires $asset"
        }
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
    "-march=native",
    "-mtune=native",
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
    & $compiler @common "-fprofile-generate=$profileFromProject" "-fprofile-prefix-path=$prefix" `
        -o "build\cube_solver_profiled.exe"
    if ($LASTEXITCODE -ne 0) { throw "PGO instrumented build failed with exit code $LASTEXITCODE" }

    Push-Location $projectRoot
    try {
        $ErrorActionPreference = "Continue"
        try {
            $trainingPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
            if (-not (Test-Path -LiteralPath $trainingPython)) { $trainingPython = "python" }
            if ($Metric -eq "QTM") {
                & $trainingPython tests\benchmark_native.py --binary $trainingTarget `
                    --metric QTM --profile q4-strong --pdb-manifest docs\benchmarks\qtm-q4-profile-manifest-2026-09-28.json `
                    --cases-file tests\native_qtm_pgo_cases.json --cases all --variants staged --repeats 1 `
                    --threads 8 --timeout $TrainingTimeout --startup-timeout 180 `
                    --output .cache\native-qtm-pgo-training.json
            } else {
                & $trainingPython tests\benchmark_native.py --binary $trainingTarget `
                    --cases-file tests\native_pgo_cases.json --cases all --variants staged --repeats 1 `
                    --threads ([Environment]::ProcessorCount) --timeout $TrainingTimeout `
                    --output .cache\native-pgo-training.json
            }
            $trainingExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = "Stop"
        }
        if ($trainingExitCode -ne 0) { throw "PGO training solve failed with exit code $trainingExitCode" }
    } finally {
        Pop-Location
    }

    & $compiler @common "-fprofile-use=$profileFromNative" -fprofile-correction `
        "-fprofile-prefix-path=$prefix" -o "build\cube_solver_profiled.exe"
    if ($LASTEXITCODE -ne 0) { throw "PGO optimized build failed with exit code $LASTEXITCODE" }
    Move-Item -LiteralPath $trainingTarget -Destination $target -Force
    [ordered]@{
        compiler = (& $compiler --version | Select-Object -First 1)
        flags = ($common -join " ") + " -fprofile-use -fprofile-correction"
        profile_guided = $true
        portable = $false
        metric = $Metric
        built_at = [DateTime]::UtcNow.ToString("o")
        binary_sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        training_cases_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot $(if ($Metric -eq "QTM") { "tests\native_qtm_pgo_cases.json" } else { "tests\native_pgo_cases.json" })) -Algorithm SHA256).Hash
        training_timeout = $TrainingTimeout
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $buildDirectory "build-info.json") -Encoding utf8
} finally {
    Pop-Location
    $resolvedProfile = [System.IO.Path]::GetFullPath($profileDirectory)
    $resolvedCache = [System.IO.Path]::GetFullPath((Join-Path $projectRoot ".cache\native"))
    if ($resolvedProfile.StartsWith($resolvedCache, [System.StringComparison]::OrdinalIgnoreCase) -and
        ([System.IO.Path]::GetFileName($resolvedProfile)).StartsWith("pgo-")) {
        Remove-Item -LiteralPath $resolvedProfile -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Output $target
