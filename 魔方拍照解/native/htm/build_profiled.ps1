param(
    [string]$Compiler = "C:\msys64\ucrt64\bin\g++.exe",
    [ValidateRange(0.1, 5.0)][double]$TrainingTimeout = 5
)

$ErrorActionPreference = "Stop"

$compiler = $Compiler
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$buildDirectory = Join-Path $PSScriptRoot "build"
$trainingTarget = Join-Path $buildDirectory "cube_solver_htm_profiled.exe"
$target = Join-Path $buildDirectory "cube_solver_htm.exe"
$profileName = "pgo-$PID"
$profileDirectory = Join-Path (Join-Path $projectRoot ".cache\htm") $profileName
$cornerPdb = Join-Path $projectRoot "assets\htm\v1\corner_htm_v2.pdb"
$phase1Pdb = Join-Path $projectRoot "assets\htm\v1\phase1_sym_htm_v2.pdb"
$tailPdb = Join-Path $projectRoot "assets\htm\v1\tail_depth6_v4.pdb"
foreach ($path in @($cornerPdb, $phase1Pdb, $tailPdb)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Profile-guided build requires the native databases: $path"
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
    "src\pdb.cpp",
    "src\solver.cpp",
    "src\symmetry.cpp",
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
        -o "build\cube_solver_htm_profiled.exe"
    if ($LASTEXITCODE -ne 0) { throw "PGO instrumented build failed with exit code $LASTEXITCODE" }

    Push-Location $projectRoot
    try {
        $ErrorActionPreference = "Continue"
        try {
            $trainingPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
            if (-not (Test-Path -LiteralPath $trainingPython)) { $trainingPython = "python" }
            & $trainingPython tests\benchmark_isolation_short.py --binary $trainingTarget `
                --metric HTM --bound 16 --cases pgo16,known18 --repeats 1 --timeout $TrainingTimeout `
                --label htm-pgo-training `
                --output .cache\htm-pgo-training.json
            $trainingExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = "Stop"
        }
        if ($trainingExitCode -ne 0) { throw "PGO training solve failed with exit code $trainingExitCode" }
    } finally {
        Pop-Location
    }

    & $compiler @common "-fprofile-use=$profileDirectory" -fprofile-correction `
        "-fprofile-prefix-path=$prefix" -o "build\cube_solver_htm_profiled.exe"
    if ($LASTEXITCODE -ne 0) { throw "PGO optimized build failed with exit code $LASTEXITCODE" }
    Move-Item -LiteralPath $trainingTarget -Destination $target -Force
    [ordered]@{
        compiler = (& $compiler --version | Select-Object -First 1)
        flags = ($common -join " ") + " -fprofile-use -fprofile-correction"
        profile_guided = $true
        built_at = [DateTime]::UtcNow.ToString("o")
        binary_sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        training_cases_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot "tests\native_pgo_cases.json") -Algorithm SHA256).Hash
        training_timeout = $TrainingTimeout
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $buildDirectory "build-info.json") -Encoding utf8
} finally {
    Pop-Location
    $resolvedProfile = [System.IO.Path]::GetFullPath($profileDirectory)
    $resolvedCache = [System.IO.Path]::GetFullPath((Join-Path $projectRoot ".cache\htm"))
    if ($resolvedProfile.StartsWith($resolvedCache, [System.StringComparison]::OrdinalIgnoreCase) -and
        ([System.IO.Path]::GetFileName($resolvedProfile)).StartsWith("pgo-")) {
        Remove-Item -LiteralPath $resolvedProfile -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Output $target
